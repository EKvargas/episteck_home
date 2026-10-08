"""Deterministic adversarial schedules for the synthetic bounded witness."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from model import CASConflict, Denied, MAX_SUFFIX, new_system


class BoundedWitnessFailures(unittest.TestCase):
    def test_pending_publication_blocks_otherwise_permissive_authority(self) -> None:
        home, witness, publisher, reader = new_system()
        self.assertTrue(reader.authorize())
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.crash()  # The DB is still permissive; witness is already PENDING.
        self.assertTrue(home.allowed)
        self.assertEqual(witness.head.state, "PENDING")
        self.assertFalse(reader.authorize())

    def test_reader_first_linearizes_before_waiting_revocation(self) -> None:
        home, witness, publisher, reader = new_system()
        home.acquire("reader")
        try:
            self.assertTrue(reader.evaluate_locked())
            with self.assertRaisesRegex(Denied, "lock busy"):
                publisher.begin("writer-1", "revoke-1", allowed=False)
        finally:
            home.release("reader")
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        self.assertFalse(reader.authorize())
        self.assertEqual(witness.head.sequence, 1)

    def test_stale_valid_checkpoint_and_suffix_bound(self) -> None:
        home, witness, publisher, reader = new_system()
        old_signed = witness.checkpoints[0]
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        publisher.begin("writer-1", "grant-2", allowed=True)
        publisher.commit()
        self.assertTrue(reader.authorize())  # Two verified events fit the bound.
        with self.assertRaisesRegex(Denied, "checkpoint required"):
            publisher.begin("writer-1", "revoke-3", allowed=False)
        publisher.checkpoint()
        self.assertTrue(reader.authorize())
        home.acquire("reader")
        try:
            self.assertTrue(old_signed.valid())
            with self.assertRaisesRegex(Denied, "stale or invalid checkpoint"):
                reader.evaluate_locked(substituted_checkpoint=old_signed)
        finally:
            home.release("reader")
        self.assertLessEqual(witness.head.sequence - witness.head.checkpoint_sequence,
                             MAX_SUFFIX)

    def test_delayed_old_writer_cannot_publish_after_takeover(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        stale_generation, stale_head = witness.head.generation, witness.head
        publisher.begin("writer-1", "takeover-2", allowed=False)
        publisher.commit(next_epoch=True)
        self.assertEqual(witness.head.writer_identity, "writer-2")
        with self.assertRaisesRegex(Denied, "inactive writer"):
            publisher.begin("writer-1", "late-grant", allowed=True)
        with self.assertRaises(CASConflict):
            witness.cas(stale_generation, replace(stale_head, state="PENDING",
                                                  event_id="late-grant"))
        self.assertEqual((home.epoch, witness.head.epoch), (2, 2))
        self.assertFalse(reader.authorize())

    def test_restored_database_ready_cannot_revive_revoked_grant(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        self.assertFalse(reader.authorize())
        home.restore_old_allow()
        self.assertTrue(home.restored_ready)
        self.assertTrue(home.allowed)
        self.assertFalse(reader.authorize())
        self.assertEqual(witness.head.sequence, 1)

    def test_combined_home_and_valid_head_rollback_detects_retained_successor(self) -> None:
        home, witness, publisher, reader = new_system()
        old_valid_head = witness.head
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        self.assertFalse(reader.authorize())
        home.restore_old_allow()
        witness.cas(witness.head.generation, old_valid_head)
        self.assertEqual(witness.head.sequence, 0)
        self.assertTrue(old_valid_head.authority_digest == home.authority_digest)
        self.assertIn(1, witness.events)  # Retained newer revocation history.
        self.assertFalse(reader.authorize())

    def test_unknown_pending_publication_requires_fresh_readback(self) -> None:
        home, witness, publisher, reader = new_system()
        with self.assertRaises(TimeoutError):
            publisher.begin("writer-1", "unknown-1", allowed=False,
                            lose_ack=True)
        self.assertEqual((witness.fresh_head().state, witness.head.event_id),
                         ("PENDING", "unknown-1"))
        self.assertFalse(reader.authorize())
        witness.outage = True
        self.assertFalse(reader.authorize())

    def test_lost_commit_ack_allows_only_matching_fresh_commit(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        publisher.begin("writer-1", "grant-2", allowed=True)
        with self.assertRaises(TimeoutError):
            publisher.commit(lose_ack=True)
        self.assertEqual((witness.fresh_head().state, witness.head.event_id),
                         ("COMMITTED", None))
        self.assertTrue(reader.authorize())
        home.restore_old_allow()  # A mismatched local state still cannot use that COMMIT.
        self.assertFalse(reader.authorize())

    def test_missing_history_and_witness_outage_deny(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        del witness.events[1]
        self.assertFalse(reader.authorize())
        witness.outage = True
        self.assertFalse(reader.authorize())

    def test_missing_checkpoint_denies_without_full_scan_fallback(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        witness.checkpoints.pop(0)
        before = dict(witness.requests)
        self.assertFalse(reader.authorize())
        self.assertEqual(witness.requests["event_get"] - before["event_get"], 0)

    def test_bounded_request_count(self) -> None:
        home, witness, publisher, reader = new_system()
        publisher.begin("writer-1", "revoke-1", allowed=False)
        publisher.commit()
        publisher.begin("writer-1", "grant-2", allowed=True)
        publisher.commit()
        before = dict(witness.requests)
        self.assertTrue(reader.authorize())
        delta = {name: witness.requests[name] - value for name, value in before.items()}
        self.assertEqual(delta, {"head_get": 1, "checkpoint_get": 1,
                                 "event_get": MAX_SUFFIX, "successor_get": 1,
                                 "head_cas": 0})


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BoundedWitnessFailures)
    scenario_names = [test.id().split(".")[-1] for test in suite]
    result = unittest.TestResult()
    suite.run(result)
    print(json.dumps({"probe": "synthetic_bounded_witness", "tests": result.testsRun,
                      "failures": len(result.failures), "errors": len(result.errors),
                      "scenarios": scenario_names,
                      "status": "PASS" if result.wasSuccessful() else "FAIL"},
                     sort_keys=True))
    for test, traceback in result.failures + result.errors:
        print(f"{test.id()}\n{traceback}")
    raise SystemExit(0 if result.wasSuccessful() else 1)
