"""Adverse schedules for publisher instances and lost DB connections."""

import json
import unittest
from dataclasses import replace

from publisher_model import Conflict, Denied, PublisherProcess, System


class PublisherFailureSchedules(unittest.TestCase):
    def test_two_instances_share_one_database_lane(self) -> None:
        system = System()
        first = PublisherProcess(system, "process-a", "publisher-1")
        second = PublisherProcess(system, "process-b", "publisher-1")
        first.begin("revoke-1", allowed=False)
        with self.assertRaisesRegex(Denied, "lock busy"):
            second.begin("competing-grant", allowed=True)
        first.commit()
        self.assertFalse(system.authorize())
        self.assertEqual(system.head.sequence, 1)
        second.begin("next-1", allowed=False)
        second.commit()
        self.assertEqual(system.head.sequence, 2)

    def test_connection_loss_fences_db_commit_and_blocks_takeover(self) -> None:
        system = System()
        first = PublisherProcess(system, "process-a", "publisher-1")
        first.begin("pending-revoke", allowed=False)
        first.disconnect()
        with self.assertRaisesRegex(Denied, "connection fence"):
            first.commit()
        self.assertEqual(system.head.state, "PENDING")
        self.assertFalse(system.authorize())
        with self.assertRaisesRegex(Denied, "pending"):
            system.takeover("publisher-2")

    def test_delayed_old_head_write_loses_after_takeover(self) -> None:
        system = System()
        old = PublisherProcess(system, "process-a", "publisher-1")
        old.begin("revoke-1", allowed=False)
        old.commit()
        snapshot = system.head
        system.takeover("publisher-2")
        with self.assertRaises(Conflict):
            system.cas(snapshot.generation, replace(snapshot, state="PENDING",
                                                     event_id="late-old-write"))
        with self.assertRaisesRegex(Denied, "inactive publisher"):
            old.begin("late-grant", allowed=True)
        self.assertEqual(system.head.publisher_epoch, 2)
        self.assertFalse(system.authorize())

    def test_restart_with_stale_pending_snapshot_denies(self) -> None:
        system = System()
        stale = system.head
        first = PublisherProcess(system, "process-a", "publisher-1")
        first.begin("pending-revoke", allowed=False)
        first.disconnect()
        restarted = PublisherProcess(system, "process-b", "publisher-1")
        with self.assertRaisesRegex(Denied, "pending"):
            restarted.begin("grant-after-restart", allowed=True)
        with self.assertRaises(Conflict):
            system.cas(stale.generation, replace(stale, state="PENDING",
                                                  event_id="stale-retry"))
        self.assertFalse(system.authorize())

    def test_delayed_valid_commit_after_lock_loss_cannot_fork(self) -> None:
        system = System()
        first = PublisherProcess(system, "process-a", "publisher-1")
        first.begin("revoke-1", allowed=False)
        delayed_commit = first.commit_db()
        first.disconnect()
        self.assertFalse(system.authorize())  # PENDING until outcome publication.
        with self.assertRaisesRegex(Denied, "pending"):
            system.takeover("publisher-2")
        system.deliver(delayed_commit)
        self.assertFalse(system.authorize())
        system.takeover("publisher-2")
        self.assertEqual(system.head.publisher_epoch, 2)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublisherFailureSchedules)
    scenario_names = [test.id().split(".")[-1] for test in suite]
    result = unittest.TestResult()
    suite.run(result)
    print(json.dumps({"probe": "synthetic_publisher_failure_schedules",
                      "tests": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "scenarios": scenario_names,
                      "status": "PASS" if result.wasSuccessful() else "FAIL"},
                     sort_keys=True))
    for test, traceback in result.failures + result.errors:
        print(f"{test.id()}\n{traceback}")
    raise SystemExit(0 if result.wasSuccessful() else 1)
