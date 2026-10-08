"""Executable caps for one proposed regional protocol screen."""

import unittest

from request_ledger import build_ledger, benchmark_gets


class RequestLedgerTests(unittest.TestCase):
    def test_30_warm_and_30_cold_pairs_fit_with_actual_slot_outcome_reads(self) -> None:
        ledger = build_ledger(pairs_per_temperature=30)
        self.assertEqual(benchmark_gets(30), 3240)
        self.assertEqual(ledger["planned"]["get"], 4000)
        self.assertEqual(ledger["planned"]["total_objects"], 4520)
        self.assertEqual(ledger["caps"]["get"], 4200)
        self.assertLessEqual(ledger["planned"]["total_objects"], 5000)

    def test_prior_100_pair_plan_exceeds_cap(self) -> None:
        with self.assertRaisesRegex(ValueError, "GET cap"):
            build_ledger(pairs_per_temperature=100)

    def test_each_suffix_level_charges_two_objects_per_event(self) -> None:
        self.assertEqual(benchmark_gets(1), 108)
        self.assertEqual(benchmark_gets(30), 3240)


if __name__ == "__main__":
    unittest.main()
