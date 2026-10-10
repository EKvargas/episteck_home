from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_synthetic_conversation_is_runnable_and_replay_safe(tmp_path):
    script = Path(__file__).resolve().parents[1] / "examples" / "run_synthetic.py"
    db = tmp_path / "finance.sqlite"
    command = [sys.executable, str(script), "--db", str(db)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    result = json.loads(first.stdout)
    assert result["answer"]["outstanding_usd"] == "70"
    assert result["records"]["reports"]["report-1"]["status"] == "reported_unverified"
    assert result["records"]["funding"]["fund-1"]["eur_amount"] == "170"
    assert result["records"]["requests"]["req-1"]["outstanding_usd"] == "50"
    assert result["records"]["requests"]["req-2"]["outstanding_usd"] == "20"
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    replay = json.loads(second.stdout)
    assert replay["event_count"] == result["event_count"]
    assert replay["answer"] == result["answer"]
