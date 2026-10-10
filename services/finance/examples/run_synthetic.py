"""Run the same trusted-intake contract a future Hermes WhatsApp adapter would use.

This module contains isolated fake identities only. It never connects to Home or a chat.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finance_pilot.core import FinancePilot, TrustedMessage  # noqa: E402


OWNER = "PSN-OLIN-SYNTHETIC"
ROSTER = {
    "olin": OWNER,
    "sister": "PSN-SISTER-SYNTHETIC",
    "rosa": "PSN-ROSA-SYNTHETIC",
    "maria": "PSN-MARIA-SYNTHETIC",
    "carlos": "PSN-CARLOS-SYNTHETIC",
}


class SyntheticOnlyAuthorizer:
    def check_access(self, subject, domain, action, delegation=None):
        allowed = (
            delegation == "synthetic-olin-session" and subject == OWNER
            and domain == "FINANCE" and action in {"VIEW", "CREATE"}
        )
        return type("Decision", (), {"allow": allowed})()


def screenshot(name: str) -> tuple[str, str, str]:
    path = Path(__file__).with_name(name).resolve()
    data = path.read_bytes()
    root = ET.fromstring(data)
    # This is fixture text extraction, not OCR. A live adapter must supply OCR output.
    text = " ".join(node.text.strip() for node in root.iter() if node.tag.endswith("text") and node.text)
    return text, str(path), sha256(data).hexdigest()


def event(mid, sender, text, *, scope="private", attachment=None, evidence="message"):
    if attachment:
        text, ref, digest = screenshot(attachment)
    else:
        ref = digest = None
    return TrustedMessage(
        channel="synthetic", message_id=mid, sender_id=ROSTER[sender], sender_name=sender,
        chat_id="family" if scope == "group" else "olin-private", chat_scope=scope,
        text=text, attachment_ref=ref, attachment_sha256=digest, evidence_kind=evidence,
    )


def run_demo(db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    pilot = FinancePilot(db_path, OWNER, SyntheticOnlyAuthorizer(), ROSTER)
    items = [
        event("req-1", "sister", "Please send 5000 VES to Rosa.", scope="group"),
        event("req-2", "sister", "Please send 3000 VES to Maria.", scope="group"),
        event("fund-amb", "olin", "", attachment="ambiguous.svg"),
        event("fund-1", "olin", "", attachment="funding.svg"),
        event("fund-copy", "olin", "", attachment="funding.svg"),
        event("del-1", "carlos", "I delivered 5000 VES to Rosa."),
        event("ack-1", "rosa", "I received 5000 VES."),
        event("del-2", "carlos", "I delivered 3000 VES to Maria."),
        event("ack-2", "maria", "I received 3000 VES."),
        event("debt-1", "sister", "I owe you USD 80 for Rosa."),
        event("debt-2", "sister", "I owe you USD 40 for Maria."),
        event("report-1", "sister", "I sent you USD 50."),
        event("receipt-1", "olin", "", attachment="bank_receipt.svg", evidence="bank_statement"),
        event("fix-1", "olin", "Correction: I sent EUR 170 to Carlos, not 160."),
    ]
    conversation = []
    for item in items:
        pilot.receive(item)
        result = pilot.record_message("synthetic-olin-session", item.message_id)
        conversation.append({"sender": item.sender_name, "message": item.text, "source_message_id": item.message_id, "olin": result})
    query = event("query-1", "olin", "How much does my sister still owe me?")
    pilot.receive(query)
    answer = pilot.answer_question("synthetic-olin-session", query.message_id)
    return {"database": str(db_path.resolve()), "conversation": conversation,
            "question": query.text, "answer": answer,
            "records": pilot.snapshot("synthetic-olin-session"),
            "event_count": pilot.event_count("synthetic-olin-session")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic local Olin Finance conversation")
    parser.add_argument("--db", type=Path, required=True, help="SQLite path; rerun with the same path to test replay")
    args = parser.parse_args()
    print(json.dumps(run_demo(args.db), indent=2))


if __name__ == "__main__":
    main()
