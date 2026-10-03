"""Create or verify SHA-256 hashes of this spike and its architecture report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "manifest.json"
REPORT = ROOT / "docs/architecture/proposals/KNOWLEDGE_PRODUCTION_TRANSPORT_VALIDATION.md"


def expected() -> dict:
    files = [REPORT, *HERE.rglob("*")]
    entries = {}
    for path in files:
        if not path.is_file() or path == MANIFEST or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(ROOT).as_posix()
        # Hash the staged Git blob, whose bytes are what the PR will commit.
        # Windows working-tree line endings can differ from committed LF bytes.
        blob = subprocess.run(
            ["git", "show", f":{relative}"], cwd=ROOT, check=True, capture_output=True
        ).stdout
        entries[relative] = hashlib.sha256(blob).hexdigest()
    return {"algorithm": "sha256", "files": dict(sorted(entries.items()))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    actual = expected()
    if args.check:
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if recorded != actual:
            raise SystemExit("manifest mismatch")
        print(f"verified {len(actual['files'])} SHA-256 hashes")
    else:
        MANIFEST.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(actual['files'])} SHA-256 hashes")


if __name__ == "__main__":
    main()
