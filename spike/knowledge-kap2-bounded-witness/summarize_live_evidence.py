"""Validate and summarize sanitized per-step disposable probe evidence."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).with_name("evidence") / "2026-10-09"
files = ("preflight.jsonl", "smoke.jsonl", "events.jsonl", "fault-reads.jsonl",
         "stale-cas.jsonl")
summary: dict = {"files": {}, "object_attempts_total": 0}
for filename in files:
    path = ROOT / filename
    lines = path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    attempts = Counter(event["category"] for event in events
                       if event.get("type") == "attempt_reserved")
    responses = Counter(f"{event['category']}:{event.get('status', event.get('transport_error'))}"
                        for event in events if event.get("type") == "request")
    finals = [event["result"] for event in events if event.get("type") == "final"]
    if not finals:
        raise ValueError(f"missing final evidence in {filename}")
    object_attempts = sum(attempts.get(category, 0) for category in
                          ("get", "create", "head_cas", "list", "other_object"))
    # The main process resumed from the first attempt's counters. The earlier
    # preflight/smoke attempts started fresh and have separate final rows.
    final_count = finals[-1]["counts"]
    for category, count in attempts.items():
        if category == "kms_sign":
            continue
        expected = final_count[category] if filename == "events.jsonl" else sum(
            item["counts"][category] for item in finals)
        if expected != count:
            raise ValueError(f"counter mismatch {filename}: {category}")
    if final_count["get"] > 4200 or final_count["create"] > 160 or \
       final_count["head_cas"] > 160 or final_count["list"] > 200:
        raise ValueError(f"category cap exceeded in {filename}")
    summary["files"][filename] = {
        "lines": len(lines), "object_attempts": object_attempts,
        "attempts": dict(attempts), "responses": dict(responses),
        "final_statuses": [item["status"] for item in finals],
    }
    summary["object_attempts_total"] += object_attempts

main = [json.loads(line)["result"] for line in (ROOT / "events.jsonl").read_text(
    encoding="utf-8").splitlines() if json.loads(line).get("type") == "final"][-1]
summary["main_final"] = main
if summary["object_attempts_total"] > 5000:
    raise ValueError("all-client hard object-request cutoff exceeded")
if main["status"] != "PASS_WITH_OPEN_PROOFS":
    raise ValueError("main probe did not reach expected final result")
(ROOT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8", newline="\n")
print(json.dumps({"status": "PASS", "object_attempts_total":
                  summary["object_attempts_total"],
                  "main_counts": main["counts"],
                  "main_status": main["status"]}, sort_keys=True))
