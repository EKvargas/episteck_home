from __future__ import annotations

from decimal import Decimal

import pytest

from finance_pilot.core import FinancePilot, TrustedMessage


OWNER = "PSN-OLIN-TEST"
ROSTER = {"olin": OWNER, "sister": "PSN-SISTER-TEST", "rosa": "PSN-ROSA-TEST", "maria": "PSN-MARIA-TEST", "carlos": "PSN-CARLOS-TEST"}


class IsolatedAuthorizer:
    """Test-only identities. There is no production fallback to these sessions."""

    def check_access(self, subject, domain, action, delegation=None):
        return type("Decision", (), {"allow": delegation == "olin-session" and subject == OWNER and domain == "FINANCE" and action in {"VIEW", "CREATE"}})()


def message(mid, sender, text, *, scope="private", attachment=None, evidence="message"):
    return TrustedMessage(
        channel="synthetic", message_id=mid, sender_id=ROSTER[sender],
        sender_name=sender, chat_id="family" if scope == "group" else "olin-private",
        chat_scope=scope, text=text, attachment_ref=attachment,
        attachment_sha256=f"sha-{attachment}" if attachment else None,
        evidence_kind=evidence,
    )


@pytest.fixture
def pilot(tmp_path):
    return FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)


def record(pilot, item, session="olin-session"):
    pilot.receive(item)
    return pilot.record_message(session, item.message_id)


def test_complete_exchange_partial_repayment_and_private_question(pilot):
    assert record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa.", scope="group"))["status"] == "recorded"
    assert record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1.", attachment="fund-shot"))["status"] == "recorded"
    assert record(pilot, message("del-1", "carlos", "I delivered 5000 VES to Rosa for req-1."))["status"] == "recorded"
    assert record(pilot, message("ack-1", "rosa", "I received 5000 VES for req-1."))["status"] == "recorded"
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["usd_owed"] is None
    assert record(pilot, message("debt-1", "sister", "I owe you USD 80 for req-1."))["status"] == "recorded"
    assert record(pilot, message("report-1", "sister", "I sent you USD 30 for req-1."))["status"] == "recorded"
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["outstanding_usd"] == "80"
    assert record(pilot, message("receipt-1", "olin", "Receipt USD 30 in US bank for req-1, reference US-001.", attachment="bank-shot", evidence="bank_statement"))["status"] == "recorded"
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["outstanding_usd"] == "50"
    pilot.receive(message("q-1", "olin", "How much does my sister still owe me?"))
    answer = pilot.answer_question("olin-session", "q-1")
    assert answer["outstanding_usd"] == "50"
    assert answer["reply_scope"] == "private"
    pilot.receive(message("q-group", "sister", "How much does my sister still owe me?", scope="group"))
    with pytest.raises(PermissionError):
        pilot.answer_question("olin-session", "q-group")


def test_two_requests_one_funding_and_later_agreements(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("req-2", "sister", "Please send 3000 VES to Maria."))
    record(pilot, message("fund-1", "olin", "I sent EUR 160 to Carlos for req-1 and req-2.", attachment="joint-fund"))
    for rid, ves, who in [("req-1", 5000, "rosa"), ("req-2", 3000, "maria")]:
        record(pilot, message(f"del-{rid}", "carlos", f"I delivered {ves} VES to {who.title()} for {rid}."))
        record(pilot, message(f"ack-{rid}", who, f"I received {ves} VES for {rid}."))
    state = pilot.snapshot("olin-session")
    assert state["funding"]["fund-1"]["requests"] == ["req-1", "req-2"]
    assert state["requests"]["req-1"]["status"] == "delivered_amount_unconfirmed"
    record(pilot, message("debt-1", "sister", "I owe you USD 80 for req-1."))
    record(pilot, message("debt-2", "sister", "I owe you USD 40 for req-2."))
    record(pilot, message("receipt-1", "olin", "Receipt USD 50 in US bank for req-1 and req-2, reference US-002: allocate req-1 USD 30 and req-2 USD 20.", attachment="bank-joint", evidence="bank_statement"))
    state = pilot.snapshot("olin-session")
    assert [state["requests"][rid]["outstanding_usd"] for rid in ("req-1", "req-2")] == ["50", "20"]


def test_ambiguous_screenshot_duplicate_and_correction_history(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    ambiguous = record(pilot, message("fund-amb", "olin", "EUR 100 sent to Carlos.", attachment="unclear"))
    assert ambiguous["status"] == "clarification_needed"
    assert "request" in ambiguous["question"].lower()
    original = message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1.", attachment="fund-shot")
    assert record(pilot, original)["status"] == "recorded"
    assert record(pilot, original)["status"] == "already_recorded"
    assert record(pilot, message("fund-copy", "olin", original.text, attachment="fund-shot"))["status"] == "duplicate_evidence"
    assert record(pilot, message("fix-1", "olin", "Correction: funding fund-1 was EUR 110, not 100."))["status"] == "recorded"
    state = pilot.snapshot("olin-session")
    assert state["funding"]["fund-1"]["eur_amount"] == "110"
    assert state["corrections"][0]["old_amount"] == "100"
    assert state["corrections"][0]["new_amount"] == "110"
    assert state["corrections"][0]["sender_id"] == OWNER
    assert state["corrections"][0]["recorded_at"]
    assert state["funding"]["fund-1"]["source_message_id"] == "fund-1"


def test_unauthorized_access_precedes_finance_reads_and_writes(pilot):
    pilot.receive(message("req-1", "sister", "Please send 5000 VES to Rosa."))
    with pytest.raises(PermissionError):
        pilot.record_message("intruder-session", "req-1")
    with pytest.raises(PermissionError):
        pilot.snapshot("intruder-session")
    assert pilot.snapshot("olin-session")["requests"] == {}


def test_restart_and_replay_do_not_repeat_effects(pilot, tmp_path):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1.", attachment="fund-shot"))
    restarted = FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)
    assert restarted.record_message("olin-session", "fund-1")["status"] == "already_recorded"
    assert restarted.snapshot("olin-session")["funding"]["fund-1"]["eur_amount"] == "100"
    assert restarted.event_count("olin-session") == 2


def test_report_is_not_receipt_and_agreement_requires_confirmed_delivery(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    assert record(pilot, message("debt-early", "sister", "I owe you USD 80 for req-1."))["status"] == "clarification_needed"
    assert record(pilot, message("report-early", "sister", "I sent you USD 30 for req-1."))["status"] == "clarification_needed"
    assert pilot.event_count("olin-session") == 1


def test_different_debtor_and_requester_and_duplicate_receipt_reference(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1."))
    record(pilot, message("del-1", "carlos", "I delivered 5000 VES to Rosa for req-1."))
    record(pilot, message("ack-1", "rosa", "I received 5000 VES for req-1."))
    record(pilot, message("debt-1", "maria", "I owe you USD 80 for req-1."))
    record(pilot, message("receipt-1", "olin", "Receipt USD 30 in US bank for req-1, reference US-001.", attachment="bank-1", evidence="bank_statement"))
    repeated = record(pilot, message("receipt-2", "olin", "Receipt USD 30 in US bank for req-1, reference US-001.", attachment="bank-2", evidence="bank_statement"))
    assert repeated["status"] == "duplicate_evidence"
    state = pilot.snapshot("olin-session")
    assert state["requests"]["req-1"]["requester_id"] == ROSTER["sister"]
    assert state["requests"]["req-1"]["debtor_id"] == ROSTER["maria"]
    assert state["funding"]["fund-1"]["payer_id"] == OWNER
    assert state["requests"]["req-1"]["outstanding_usd"] == "50"


def test_debt_correction_preserves_history_and_recalculates_outstanding(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1."))
    record(pilot, message("del-1", "carlos", "I delivered 5000 VES to Rosa for req-1."))
    record(pilot, message("ack-1", "rosa", "I received 5000 VES for req-1."))
    record(pilot, message("debt-1", "sister", "I owe you USD 80 for req-1."))
    record(pilot, message("receipt-1", "olin", "Receipt USD 30 in US bank for req-1, reference US-001.", attachment="bank-1", evidence="bank_statement"))
    assert record(pilot, message("fix-debt", "sister", "Correction: debt req-1 was USD 90, not 80."))["status"] == "recorded"
    state = pilot.snapshot("olin-session")
    assert state["requests"]["req-1"]["outstanding_usd"] == "60"
    assert state["corrections"][-1]["old_amount"] == "80"
    assert state["corrections"][-1]["new_amount"] == "90"
    assert state["requests"]["req-1"]["agreement_source_message_id"] == "debt-1"


def test_planned_action_is_not_recorded_and_sender_metadata_is_checked(pilot):
    planned = record(pilot, message("plan-1", "sister", "I will send you USD 30 for req-1."))
    assert planned["status"] == "clarification_needed"
    assert pilot.event_count("olin-session") == 0
    forged = message("forged", "sister", "Please send 5000 VES to Rosa.")
    from dataclasses import replace
    with pytest.raises(ValueError, match="metadata"):
        pilot.receive(replace(forged, sender_id=OWNER))


def test_source_and_correction_keep_sender_attachment_and_times(pilot):
    from dataclasses import replace
    source = replace(
        message("req-1", "sister", "Please send 5000 VES to Rosa.", attachment="request-shot"),
        source_timestamp="2099-01-02T03:04:05Z",
    )
    record(pilot, source)
    saved = pilot.source("olin-session", "req-1")
    assert saved["sender_id"] == ROSTER["sister"]
    assert saved["attachment_ref"] == "request-shot"
    assert saved["source_timestamp"] == "2099-01-02T03:04:05Z"
    assert saved["received_at"]
    with pytest.raises(PermissionError):
        pilot.source("intruder-session", "req-1")


def test_second_delivery_message_cannot_repeat_financial_effect(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for req-1."))
    record(pilot, message("del-1", "carlos", "I delivered 5000 VES to Rosa for req-1."))
    repeated = record(pilot, message("del-2", "carlos", "I delivered 5000 VES to Rosa for req-1."))
    assert repeated["status"] == "clarification_needed"
    assert pilot.event_count("olin-session") == 3


def test_natural_beneficiary_references_without_request_ids(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("req-2", "sister", "Please send 3000 VES to Maria."))
    assert record(pilot, message("fund-1", "olin", "I sent EUR 160 to Carlos for Rosa and Maria."))["status"] == "recorded"
    assert record(pilot, message("del-1", "carlos", "I delivered 5000 VES to Rosa."))["status"] == "recorded"
    assert record(pilot, message("ack-1", "rosa", "I received 5000 VES."))["status"] == "recorded"
    assert record(pilot, message("debt-1", "sister", "I owe you USD 80 for Rosa."))["status"] == "recorded"
    assert record(pilot, message("report-1", "sister", "I sent you USD 30."))["status"] == "recorded"
    assert record(pilot, message("receipt-1", "olin", "Receipt USD 30 in US bank for Rosa, reference US-001.", attachment="bank-1", evidence="bank_statement"))["status"] == "recorded"
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["outstanding_usd"] == "50"


def test_same_beneficiary_in_two_open_requests_requires_clarification(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("req-2", "sister", "Please send 5000 VES to Rosa."))
    result = record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for Rosa."))
    assert result["status"] == "clarification_needed"
    assert pilot.event_count("olin-session") == 2


def test_natural_funding_correction_resolves_unique_prior_payment(pilot):
    record(pilot, message("req-1", "sister", "Please send 5000 VES to Rosa."))
    record(pilot, message("fund-1", "olin", "I sent EUR 100 to Carlos for Rosa."))
    result = record(pilot, message("fix-1", "olin", "Correction: I sent EUR 110 to Carlos, not 100."))
    assert result["status"] == "recorded"
    assert pilot.snapshot("olin-session")["funding"]["fund-1"]["eur_amount"] == "110"
