"""Persistent, deliberately narrow conversational Finance pilot.

The channel adapter alone creates TrustedMessage. Model-visible tools take only an
already ingested message ID; sender, chat scope and attachments never come from them.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3


@dataclass(frozen=True)
class TrustedMessage:
    channel: str
    message_id: str
    sender_id: str
    sender_name: str
    chat_id: str
    chat_scope: str
    text: str
    attachment_ref: str | None = None
    attachment_sha256: str | None = None
    evidence_kind: str = "message"
    source_timestamp: str | None = None


def _money(raw: str) -> str:
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError("invalid amount") from error
    if not value.is_finite() or value <= 0:
        raise ValueError("amount must be positive")
    return format(value.normalize(), "f")


def _money_or_zero(value: Decimal) -> str:
    if value < 0:
        raise ValueError("allocation exceeds outstanding debt")
    return "0" if value == 0 else format(value.normalize(), "f")


def _clarify(question: str) -> dict:
    return {"status": "clarification_needed", "question": question}


class FinancePilot:
    """One owner's Finance store; a Home-compatible authorizer gates every tool call."""

    def __init__(self, db_path: str | Path, owner_person_id: str, authorizer, roster: dict[str, str]):
        self.db_path = str(db_path)
        self.owner_person_id = owner_person_id
        self.authorizer = authorizer
        self.roster = {name.lower(): person for name, person in roster.items()}
        if not self.owner_person_id or not self.roster:
            raise ValueError("owner and trusted roster are required")
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS inbox (
                    message_id TEXT PRIMARY KEY, channel TEXT NOT NULL,
                    sender_id TEXT NOT NULL, sender_name TEXT NOT NULL,
                    chat_id TEXT NOT NULL, chat_scope TEXT NOT NULL,
                    text TEXT NOT NULL, attachment_ref TEXT,
                    attachment_sha256 TEXT, evidence_kind TEXT NOT NULL,
                    source_timestamp TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_message_id TEXT NOT NULL UNIQUE REFERENCES inbox(message_id),
                    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                    attachment_sha256 TEXT UNIQUE,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _require(self, delegation: str | None, action: str) -> None:
        if not delegation:
            raise PermissionError("no authenticated human session")
        decision = self.authorizer.check_access(
            self.owner_person_id, "FINANCE", action, delegation
        )
        if decision.allow is not True:
            raise PermissionError("Finance access denied")

    def receive(self, message: TrustedMessage) -> str:
        """Trusted-adapter ingress, never exposed as a Hermes tool."""
        if (
            not message.message_id or not message.sender_id or not message.chat_id
            or message.chat_scope not in {"private", "group"}
            or self.roster.get(message.sender_name.lower()) != message.sender_id
        ):
            raise ValueError("invalid trusted message metadata")
        values = asdict(message)
        with self._db() as db:
            existing = db.execute("SELECT * FROM inbox WHERE message_id=?", (message.message_id,)).fetchone()
            if existing:
                if any(existing[key] != value for key, value in values.items()):
                    raise ValueError("message ID reused with different content")
                return message.message_id
            db.execute(
                "INSERT INTO inbox(message_id,channel,sender_id,sender_name,chat_id,chat_scope,text,attachment_ref,attachment_sha256,evidence_kind,source_timestamp) VALUES (:message_id,:channel,:sender_id,:sender_name,:chat_id,:chat_scope,:text,:attachment_ref,:attachment_sha256,:evidence_kind,:source_timestamp)",
                values,
            )
        return message.message_id

    def _state(self, db) -> dict:
        state = {"requests": {}, "funding": {}, "reports": {}, "receipts": {}, "corrections": []}
        for row in db.execute("SELECT events.source_message_id,events.kind,events.payload_json,events.recorded_at,inbox.sender_id FROM events JOIN inbox ON inbox.message_id=events.source_message_id ORDER BY events.seq"):
            source, kind, encoded, recorded_at, sender_id = row
            data = json.loads(encoded)
            if kind == "request":
                state["requests"][source] = {
                    **data, "source_message_id": source, "status": "requested",
                    "usd_owed": None, "outstanding_usd": None,
                }
            elif kind == "funding":
                state["funding"][source] = {**data, "source_message_id": source}
                for rid in data["requests"]:
                    state["requests"][rid]["funding_id"] = source
            elif kind == "delivery":
                item = state["requests"][data["request_id"]]
                item["delivery"] = {**data, "source_message_id": source}
                item["status"] = "delivery_reported"
            elif kind == "confirmation":
                item = state["requests"][data["request_id"]]
                item["recipient_confirmation"] = source
                item["status"] = "delivered_amount_unconfirmed"
            elif kind == "agreement":
                item = state["requests"][data["request_id"]]
                item["debtor_id"] = data["debtor_id"]
                item["usd_owed"] = data["usd_amount"]
                item["outstanding_usd"] = data["usd_amount"]
                item["agreement_source_message_id"] = source
                item["status"] = "debt_agreed"
            elif kind == "report":
                state["reports"][source] = {**data, "source_message_id": source, "status": "reported_unverified"}
            elif kind == "receipt":
                state["receipts"][source] = {**data, "source_message_id": source, "status": "verified"}
                for rid, amount in data["allocations"].items():
                    item = state["requests"][rid]
                    item["outstanding_usd"] = _money_or_zero(
                        Decimal(item["outstanding_usd"]) - Decimal(amount)
                    )
            elif kind == "correction":
                state["corrections"].append({**data, "source_message_id": source, "recorded_at": recorded_at, "sender_id": sender_id})
                if data["target_kind"] == "funding":
                    state["funding"][data["target_id"]]["eur_amount"] = data["new_amount"]
                elif data["target_kind"] == "agreement":
                    item = state["requests"][data["target_id"]]
                    delta = Decimal(data["new_amount"]) - Decimal(data["old_amount"])
                    item["usd_owed"] = data["new_amount"]
                    item["outstanding_usd"] = _money_or_zero(Decimal(item["outstanding_usd"]) + delta)
        return state

    def snapshot(self, delegation: str | None) -> dict:
        self._require(delegation, "VIEW")
        with self._db() as db:
            return self._state(db)

    def event_count(self, delegation: str | None) -> int:
        self._require(delegation, "VIEW")
        with self._db() as db:
            return db.execute("SELECT count(*) FROM events").fetchone()[0]

    def source(self, delegation: str | None, message_id: str) -> dict:
        self._require(delegation, "VIEW")
        with self._db() as db:
            row = db.execute("SELECT * FROM inbox WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise ValueError("unknown source message")
            return dict(row)

    def record_message(self, delegation: str | None, message_id: str) -> dict:
        self._require(delegation, "CREATE")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM inbox WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                return _clarify("I cannot find that source message. Please resend it through the trusted channel.")
            message = TrustedMessage(**{key: row[key] for key in TrustedMessage.__dataclass_fields__})
            if db.execute("SELECT 1 FROM events WHERE source_message_id=?", (message_id,)).fetchone():
                return {"status": "already_recorded", "source_message_id": message_id}
            if message.attachment_sha256 and db.execute(
                "SELECT 1 FROM events WHERE attachment_sha256=?", (message.attachment_sha256,)
            ).fetchone():
                return {"status": "duplicate_evidence", "source_message_id": message_id}
            result = self._interpret(message, self._state(db))
            if result["status"] != "recorded":
                return result
            db.execute(
                "INSERT INTO events(source_message_id,kind,payload_json,attachment_sha256) VALUES (?,?,?,?)",
                (message_id, result["kind"], json.dumps(result["data"], sort_keys=True), message.attachment_sha256),
            )
            return {"status": "recorded", "kind": result["kind"], "source_message_id": message_id}

    def answer_question(self, delegation: str | None, message_id: str) -> dict:
        self._require(delegation, "VIEW")
        with self._db() as db:
            row = db.execute("SELECT * FROM inbox WHERE message_id=?", (message_id,)).fetchone()
            if row is None:
                raise ValueError("unknown source message")
            message = TrustedMessage(**{key: row[key] for key in TrustedMessage.__dataclass_fields__})
            if message.chat_scope != "private" or message.sender_id != self.owner_person_id:
                raise PermissionError("Finance answers are private to the owner")
            match = re.fullmatch(r"How much does my (\w+) still owe me\?", message.text.strip(), re.I)
            if not match:
                return _clarify("Whose outstanding USD debt should I check?")
            debtor = self.roster.get(match[1].lower())
            if debtor is None:
                return _clarify("Which person do you mean?")
            state = self._state(db)
            total = sum(
                (Decimal(item["outstanding_usd"]) for item in state["requests"].values()
                 if item.get("debtor_id") == debtor), Decimal(0)
            )
            return {"status": "answered", "debtor_id": debtor, "outstanding_usd": _money_or_zero(total), "reply_scope": "private"}

    def _interpret(self, message: TrustedMessage, state: dict) -> dict:
        text = message.text.strip()
        sender = message.sender_id
        requests = state["requests"]

        def recorded(kind, **data):
            return {"status": "recorded", "kind": kind, "data": data}

        def resolve_targets(raw: str, eligible) -> list[str] | None:
            resolved = []
            for label in raw.split(" and "):
                if label in requests:
                    candidates = [label] if eligible(requests[label]) else []
                else:
                    person = self.roster.get(label.lower())
                    candidates = [
                        rid for rid, item in requests.items()
                        if item["beneficiary_id"] == person and eligible(item)
                    ]
                if len(candidates) != 1:
                    return None
                resolved.append(candidates[0])
            return resolved if len(set(resolved)) == len(resolved) else None

        match = re.fullmatch(r"Please send (\d+(?:\.\d+)?) VES to (\w+)\.", text, re.I)
        if match:
            beneficiary = self.roster.get(match[2].lower())
            if not beneficiary:
                return _clarify("Who is the beneficiary?")
            return recorded("request", requester_id=sender, beneficiary_id=beneficiary,
                            beneficiary_name=match[2], ves_amount=_money(match[1]))

        match = re.fullmatch(r"I sent EUR (\d+(?:\.\d+)?) to (\w+) for ([\w-]+(?: and [\w-]+)*)\.", text, re.I)
        if match:
            ids = resolve_targets(match[3], lambda item: not item.get("funding_id"))
            friend = self.roster.get(match[2].lower())
            if sender != self.owner_person_id or not friend:
                return _clarify("Who paid the friend, and who received the EUR payment?")
            if ids is None:
                return _clarify("Which unfunded request IDs does this payment cover?")
            return recorded("funding", payer_id=sender, friend_id=friend,
                            eur_amount=_money(match[1]), requests=ids)

        match = re.fullmatch(r"I delivered (\d+(?:\.\d+)?) VES to (\w+)(?: for ([\w-]+))?\.", text, re.I)
        if match:
            ids = resolve_targets(match[3] or match[2], lambda item: bool(item.get("funding_id")) and not item.get("delivery") and item["ves_amount"] == _money(match[1]))
            rid = ids[0] if ids else None
            item = requests.get(rid)
            funding = state["funding"].get(item.get("funding_id")) if item else None
            if not item or not funding or funding["friend_id"] != sender or item.get("delivery"):
                return _clarify("Which funded, undelivered request does this delivery confirm?")
            if item["beneficiary_id"] != self.roster.get(match[2].lower()) or item["ves_amount"] != _money(match[1]):
                return _clarify("The beneficiary or VES amount conflicts with the request. Which is correct?")
            return recorded("delivery", request_id=rid, ves_amount=_money(match[1]), sender_id=sender)

        match = re.fullmatch(r"I received (\d+(?:\.\d+)?) VES(?: for ([\w-]+))?\.", text, re.I)
        if match:
            if match[2]:
                ids = resolve_targets(match[2], lambda item: bool(item.get("delivery")) and not item.get("recipient_confirmation"))
            else:
                ids = [rid for rid, item in requests.items() if item["beneficiary_id"] == sender and item.get("delivery") and not item.get("recipient_confirmation") and item["delivery"]["ves_amount"] == _money(match[1])]
                if len(ids) != 1:
                    ids = None
            rid = ids[0] if ids else None
            item = requests.get(rid)
            if not item or not item.get("delivery") or item.get("recipient_confirmation"):
                return _clarify("Which reported delivery are you confirming?")
            if item["beneficiary_id"] != sender or item["delivery"]["ves_amount"] != _money(match[1]):
                return _clarify("The recipient or amount does not match the delivery. Which is correct?")
            return recorded("confirmation", request_id=rid, recipient_id=sender)

        match = re.fullmatch(r"I owe you USD (\d+(?:\.\d+)?) for ([\w-]+)\.", text, re.I)
        if match:
            ids = resolve_targets(match[2], lambda item: bool(item.get("recipient_confirmation")) and item.get("usd_owed") is None)
            rid = ids[0] if ids else None
            item = requests.get(rid)
            if not item or not item.get("recipient_confirmation") or item.get("usd_owed") is not None:
                return _clarify("Please confirm delivery first, then identify the request for this USD agreement.")
            return recorded("agreement", request_id=rid, debtor_id=sender, usd_amount=_money(match[1]))

        match = re.fullmatch(r"I sent you USD (\d+(?:\.\d+)?)(?: for ([\w-]+(?: and [\w-]+)*))?\.", text, re.I)
        if match:
            if match[2]:
                ids = resolve_targets(match[2], lambda item: item.get("debtor_id") == sender)
            else:
                ids = [rid for rid, item in requests.items() if item.get("debtor_id") == sender and Decimal(item["outstanding_usd"]) > 0]
            if not ids:
                return _clarify("Which agreed debt is this reported repayment for?")
            return recorded("report", request_ids=ids, sender_id=sender, usd_amount=_money(match[1]))

        match = re.fullmatch(
            r"Receipt USD (\d+(?:\.\d+)?) in US bank for ([\w-]+(?: and [\w-]+)*), reference ([\w-]+)(?:: allocate (.+))?\.",
            text, re.I,
        )
        if match:
            if sender != self.owner_person_id or message.evidence_kind != "bank_statement" or not message.attachment_sha256:
                return _clarify("Please provide an authorized US bank receipt before I verify repayment.")
            if any(receipt["reference"] == match[3] for receipt in state["receipts"].values()):
                return {"status": "duplicate_evidence", "source_message_id": message.message_id}
            total = Decimal(_money(match[1]))
            ids = resolve_targets(match[2], lambda item: item.get("usd_owed") is not None and Decimal(item["outstanding_usd"]) > 0)
            if not ids:
                return _clarify("Which agreed debts should this receipt settle?")
            if match[4]:
                parts = re.findall(r"([\w-]+) USD (\d+(?:\.\d+)?)", match[4], re.I)
                allocations = {}
                for label, amount in parts:
                    target = resolve_targets(label, lambda item: item.get("usd_owed") is not None and Decimal(item["outstanding_usd"]) > 0)
                    if target:
                        allocations[target[0]] = _money(amount)
                if len(parts) != len(ids) or len(allocations) != len(ids) or set(allocations) != set(ids):
                    return _clarify("How should this receipt be allocated across the debts?")
            elif len(ids) == 1:
                allocations = {ids[0]: _money(match[1])}
            else:
                return _clarify("How much of the receipt goes to each debt?")
            if sum(map(Decimal, allocations.values())) != total or any(
                Decimal(amount) > Decimal(requests[rid]["outstanding_usd"])
                for rid, amount in allocations.items()
            ):
                return _clarify("The allocations exceed the receipt or outstanding debt. What amounts are correct?")
            return recorded("receipt", account="US bank", reference=match[3],
                            usd_amount=_money(match[1]), allocations=allocations)

        match = re.fullmatch(r"Correction: funding (fund-[\w-]+) was EUR (\d+(?:\.\d+)?), not (\d+(?:\.\d+)?)\.", text, re.I)
        if match:
            target = state["funding"].get(match[1])
            if sender != self.owner_person_id or not target or target["eur_amount"] != _money(match[3]):
                return _clarify("Which funding record and prior amount should I correct?")
            return recorded("correction", target_kind="funding", target_id=match[1],
                            old_amount=_money(match[3]), new_amount=_money(match[2]), reason="explicit source correction")

        match = re.fullmatch(r"Correction: I sent EUR (\d+(?:\.\d+)?) to (\w+), not (\d+(?:\.\d+)?)\.", text, re.I)
        if match:
            friend = self.roster.get(match[2].lower())
            candidates = [fid for fid, funding in state["funding"].items()
                          if funding["payer_id"] == sender and funding["friend_id"] == friend
                          and funding["eur_amount"] == _money(match[3])]
            if sender != self.owner_person_id or len(candidates) != 1:
                return _clarify("Which EUR payment should I correct?")
            return recorded("correction", target_kind="funding", target_id=candidates[0],
                            old_amount=_money(match[3]), new_amount=_money(match[1]), reason="explicit source correction")

        match = re.fullmatch(r"Correction: debt (req-[\w-]+) was USD (\d+(?:\.\d+)?), not (\d+(?:\.\d+)?)\.", text, re.I)
        if match:
            item = requests.get(match[1])
            if not item or item.get("debtor_id") != sender or item["usd_owed"] != _money(match[3]):
                return _clarify("Which agreed debt and prior USD amount should I correct?")
            settled = Decimal(item["usd_owed"]) - Decimal(item["outstanding_usd"])
            if Decimal(_money(match[2])) < settled:
                return _clarify("The corrected debt is below verified repayments. What amount is correct?")
            return recorded("correction", target_kind="agreement", target_id=match[1],
                            old_amount=_money(match[3]), new_amount=_money(match[2]), reason="explicit debtor correction")

        return _clarify("What happened, and which request does it relate to?")
