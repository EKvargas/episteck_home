"""Count every planned object request in one synthetic regional experiment."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal


SUFFIXES = (0, 1, 8)
CAPS = {"get": 4200, "create": 160, "head_cas": 160,
        "list": 200, "total_objects": 5000, "kms_sign_per_key": 160}


def benchmark_gets(pairs_per_temperature: int) -> int:
    """Warm and cold pair; each read GETs head, checkpoint, two/event, successor."""
    if pairs_per_temperature < 1:
        raise ValueError("at least one pair per temperature is required")
    return sum(2 * pairs_per_temperature * 2 * (3 + 2 * suffix)
               for suffix in SUFFIXES)


def build_ledger(*, pairs_per_temperature: int = 30) -> dict:
    benchmark_rows = [
        {"case": f"warm+cold_{suffix}_suffix", "method": "GET",
         "count": 2 * pairs_per_temperature * 2 * (3 + 2 * suffix),
         "per_authorization": {"head": 1, "checkpoint": 1,
                               "slot_and_outcome": 2 * suffix, "successor": 1}}
        for suffix in SUFFIXES
    ]
    rows = benchmark_rows + [
        {"case": "64_mutations_head_successor_readback", "method": "GET", "count": 64 * 3},
        {"case": "8_checkpoint_publications", "method": "GET", "count": 8 * 2},
        {"case": "genesis_and_identity_preflight", "method": "GET", "count": 18},
        {"case": "adversarial_schedules", "method": "GET", "count": 160},
        {"case": "two_full_recovery_audits_128_events_8_checkpoints_head", "method": "GET",
         "count": 2 * (64 * 2 + 8 + 1)},
        {"case": "GET_retry_reserve", "method": "GET", "count": 100},
        {"case": "64_slots_64_outcomes_8_checkpoints_genesis", "method": "CREATE",
         "count": 64 * 2 + 8 + 1},
        {"case": "adversarial_immutable_creates", "method": "CREATE", "count": 8},
        {"case": "CREATE_retry_reserve", "method": "CREATE", "count": 15},
        {"case": "64_prepare_64_commit_8_checkpoint_1_genesis", "method": "HEAD_CAS",
         "count": 64 * 2 + 8 + 1},
        {"case": "adversarial_head_cas", "method": "HEAD_CAS", "count": 12},
        {"case": "HEAD_CAS_retry_reserve", "method": "HEAD_CAS", "count": 11},
        {"case": "two_audits_20_pages_each", "method": "LIST", "count": 40},
        {"case": "adversarial_list", "method": "LIST", "count": 60},
        {"case": "LIST_retry_reserve", "method": "LIST", "count": 100},
    ]
    planned = {
        "get": sum(row["count"] for row in rows if row["method"] == "GET"),
        "create": sum(row["count"] for row in rows if row["method"] == "CREATE"),
        "head_cas": sum(row["count"] for row in rows if row["method"] == "HEAD_CAS"),
        "list": sum(row["count"] for row in rows if row["method"] == "LIST"),
    }
    planned["total_objects"] = sum(planned.values())
    for category, cap in CAPS.items():
        if category == "kms_sign_per_key":
            continue
        if planned[category] > cap:
            raise ValueError(f"{category.upper()} cap exceeded: {planned[category]} > {cap}")

    # Official regional Standard flat-namespace rates; estimates exclude storage,
    # egress, IAM/API overhead, taxes and currency conversion.
    class_a = Decimal(planned["create"] + planned["head_cas"] + planned["list"])
    class_b = Decimal(planned["get"])
    kms_sign = {"old_epoch": 140, "new_epoch": 140, "checkpoint": 16}
    if max(kms_sign.values()) > CAPS["kms_sign_per_key"]:
        raise ValueError("KMS sign cap exceeded")
    object_cost = class_a * Decimal("0.005") / 1000 + class_b * Decimal("0.0004") / 1000
    kms_version_cost = 3 * 24 * Decimal("0.000082192")
    kms_operation_cost = sum(kms_sign.values()) * Decimal("0.03") / 10000
    return {
        "probe": "one_region_bounded_witness_request_ledger",
        "pairs_per_temperature_per_suffix": pairs_per_temperature,
        "temperatures": ["warm", "cold"], "suffixes": list(SUFFIXES),
        "cold_definition": "new HTTP client/pool and TCP/TLS connection before each pair; RT1 and RT2 within the pair may reuse it; no local evidence cache",
        "rows": rows, "planned": planned, "caps": CAPS,
        "kms_sign_attempts": kms_sign,
        "cost_usd_core_one_day": {
            "object_requests": str(object_cost),
            "three_active_software_versions": str(kms_version_cost),
            "sign_attempts": str(kms_operation_cost),
            "planned_total": str(object_cost + kms_version_cost + kms_operation_cost),
            "conservative_all_5000_objects_class_a_plus_480_signs_and_keys": str(
                5000 * Decimal("0.005") / 1000 + kms_version_cost
                + 480 * Decimal("0.03") / 10000
            ),
        },
        "sample_limit": "30 values per warm/cold suffix group; p95 is near the second largest and p99 near the maximum, so this only screens candidates; KAP-10 needs a separately approved larger end-to-end run",
        "source_urls": ["https://cloud.google.com/storage/pricing",
                        "https://cloud.google.com/kms/pricing"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs-per-temperature", type=int, default=30)
    arguments = parser.parse_args()
    print(json.dumps(build_ledger(pairs_per_temperature=arguments.pairs_per_temperature),
                     sort_keys=True))
