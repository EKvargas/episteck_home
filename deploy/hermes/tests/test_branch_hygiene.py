"""Hygiene of the files plan 2 (Episteck Home nutrition agents) adds or changes.

Nothing in them may name a local Windows user profile path: the public-identity rule forbids
pointing at the owner's machine (R21). SSH examples use `$HOME/.ssh/config` instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# The files the branch adds or changes (git diff --name-only against plan 1's merge, 53dd190).
BRANCH_FILES = (
    "deploy/hermes/home-agent-ana/SOUL.md",
    "deploy/hermes/home-agent/nutrition-diary-pointer.md",
    "deploy/hermes/home-agent/nutrition-pointer-section.md",
    "deploy/hermes/install-home-agent-ana.sh",
    "deploy/hermes/install-olin-nutrition.sh",
    "deploy/hermes/skills/olin-nutrition/SKILL.md",
    "deploy/hermes/tests/test_branch_hygiene.py",
    "deploy/hermes/tests/test_install_home_agent_ana.py",
    "deploy/hermes/tests/test_install_olin_nutrition.py",
    "deploy/hermes/tests/test_olin_nutrition_skill.py",
    "deploy/hermes/tests/test_runbook_commands.py",
    "deploy/hermes/tests/test_ultron_nutrition_notes.py",
    "deploy/hermes/ultron_nutrition_notes.py",
    "docs/runbooks/nutrition-profile-rollout.md",
    "docs/superpowers/plans/2026-11-23-nutrition-profile-p2-agents.md",
)

# A drive letter, a colon, slashes or backslashes, then the Windows profiles folder.
LOCAL_PROFILE = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]", re.I)


@pytest.mark.parametrize("rel", BRANCH_FILES)
def test_no_local_windows_user_path(rel):
    path = ROOT / rel
    assert path.is_file(), rel
    text = path.read_text(encoding="utf-8")
    found = [n for n, line in enumerate(text.splitlines(), 1) if LOCAL_PROFILE.search(line)]
    assert not found, f"{rel}: local user path on line(s) {found}"


def test_the_pattern_finds_both_spellings():
    drive = "C" + ":"
    assert LOCAL_PROFILE.search(f"ssh -F {drive}/Users/someone/.ssh/config")
    assert LOCAL_PROFILE.search(f"{drive}\\Users\\someone\\x")
    assert not LOCAL_PROFILE.search('ssh -F "$HOME/.ssh/config" episteck-node1')


@pytest.mark.parametrize("rel", [r for r in BRANCH_FILES if r.endswith(".py")])
def test_python_files_end_with_a_newline(rel):
    assert (ROOT / rel).read_bytes().endswith(b"\n"), rel
