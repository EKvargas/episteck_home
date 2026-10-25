"""Count amount-like, IBAN-like and account-number-like strings in Hermes memory files.

The Olin Finance skill forbids storing figures in Hermes memory (proposal §8.4); this is the
periodic check. It prints file names and COUNTS only, never the matched text. A string can
count in more than one category (an IBAN also contains a long number).

    python3 -I memory_hygiene.py /home/home-agent/.hermes/memories

Exit 0 when nothing is found, 1 when something is, 2 on a usage error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_CURRENCY = r"(?:€|\$|£|\b(?:EUR|USD|VES|Bs\.?|euros?|d[oó]lares|bol[ií]vares)\b)"
PATTERNS = {
    "amount": re.compile(rf"{_CURRENCY}\s?-?\d[\d.,]*|\d[\d.,]*\s?{_CURRENCY}", re.IGNORECASE),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"),
    "long_number": re.compile(r"(?<![\d.,])\d{8,}(?![\d.,])"),
}


def scan(root: Path) -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        name = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            results[name] = {"unreadable": 1}
            continue
        results[name] = {kind: len(rx.findall(text)) for kind, rx in PATTERNS.items()}
    return results


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: memory_hygiene.py <memories-dir>", file=sys.stderr)
        return 2
    root = Path(argv[1]).expanduser()
    if not root.is_dir():
        print("not a directory", file=sys.stderr)
        return 2
    results = scan(root)
    findings = 0
    for name, counts in results.items():
        print(f"{name}: " + " ".join(f"{kind}={n}" for kind, n in counts.items()))
        findings += sum(counts.values())
    print(f"files={len(results)} findings={findings}")
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
