"""Point Ultron's own nutrition notes at the shared `olin-nutrition` skill.

Usage (stdlib only):
    python3 -I ultron_nutrition_notes.py <skill.md> <pointer-section.md>

Replaces the nutrition section of the agent's standing skill with the pointer section and removes
every line naming the retired tool. Prints one change per line (or `no changes`); never file content.
Exit 0 = rewritten or already current, 2 = usage, 3 = stop: the file was left untouched.
"""
from __future__ import annotations

import os
import sys

NUTRITION_HEADINGS = ("## Nutrition intake capture", "## Nutrition")
RETIRED_TOOL = "get_daily_nutrition_gap"


class NotesChanged(Exception):
    """The notes no longer have the expected shape; a person must look."""


def rewrite(text: str, pointer_section: str) -> tuple[str, list[str]]:
    lines = text.split("\n")
    start = next((i for h in NUTRITION_HEADINGS for i, ln in enumerate(lines) if ln.rstrip() == h), None)
    if start is None:
        raise NotesChanged("nutrition heading not found")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    new_lines = lines[:start] + pointer_section.strip("\n").split("\n") + [""] + lines[end:]
    changes: list[str] = []
    if new_lines != lines:
        changes.append("section replaced")
    kept = [ln for ln in new_lines if RETIRED_TOOL not in ln]
    if len(kept) != len(new_lines):
        changes.append("retired tool line removed")
    return ("\n".join(kept), changes) if changes else (text, [])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ultron_nutrition_notes.py <skill.md> <pointer-section.md>", file=sys.stderr)
        return 2
    skill, pointer = argv
    if os.path.islink(skill):
        print(f"refusing: {skill} is a symlink; leaving everything untouched", file=sys.stderr)
        return 3
    with open(pointer, encoding="utf-8", newline="") as f:
        pointer_text = f.read()
    with open(skill, encoding="utf-8", newline="") as f:
        text = f.read()
    try:
        new, changes = rewrite(text, pointer_text)
    except NotesChanged as exc:
        print(f"{exc}: look at the nutrition section of {skill} by hand; nothing was changed",
              file=sys.stderr)
        return 3
    if changes:
        with open(skill, "w", encoding="utf-8", newline="") as f:  # same inode: owner and mode stay
            f.write(new)
    print("\n".join(changes) if changes else "no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))