"""P10: restored old payload, newer suppression state (H7 / B4 C1's T1/T2/T4 case).

Models the restore-freshness invariant: a restored payload must not become usable unless
the suppression/control state used for reconciliation is PROVABLY at least as current as
the restored payload. Unknown freshness fails closed -- no restored Knowledge is
retrievable when currency cannot be proven, full stop, not "retrievable with a caveat."
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RestoreEvent:
    payload_version_id: str
    payload_captured_at: int  # when the backup snapshot was taken
    control_state_known_current_as_of: int | None  # None = freshness UNPROVABLE


def restored_content_retrievable(event: RestoreEvent) -> bool:
    """The restore-freshness gate (H7). Fails closed on unprovable currency."""
    if event.control_state_known_current_as_of is None:
        return False  # UNPROVABLE -> fail closed, no exception, no partial allowance
    return event.control_state_known_current_as_of >= event.payload_captured_at


def test_p10_restored_payload_with_unprovable_freshness_denies():
    """Currency unprovable -> X not retrievable. Explicit abstention, not an exception,
    not a partial success."""
    event = RestoreEvent(
        payload_version_id="X", payload_captured_at=2_000_000_000, control_state_known_current_as_of=None,
    )
    assert restored_content_retrievable(event) is False


def test_p10_restored_payload_with_stale_control_state_denies():
    """Control state known current as of a point BEFORE the payload was captured (T1 <
    T2 in B4 C1's language) -- currency is provably insufficient, must deny."""
    event = RestoreEvent(
        payload_version_id="X", payload_captured_at=2_000_000_000,
        control_state_known_current_as_of=1_999_000_000,  # older than the payload
    )
    assert restored_content_retrievable(event) is False


def test_p10_restored_payload_with_provably_current_control_state_allows():
    """Control group: control state known current AT OR AFTER the payload capture time --
    freshness is provable, restore is retrievable. Confirms the gate isn't always-false."""
    event = RestoreEvent(
        payload_version_id="X", payload_captured_at=2_000_000_000,
        control_state_known_current_as_of=2_000_000_500,  # newer than the payload
    )
    assert restored_content_retrievable(event) is True
