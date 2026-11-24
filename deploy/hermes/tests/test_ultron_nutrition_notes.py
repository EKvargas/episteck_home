"""Tests for the helper that points Ultron's own nutrition notes at the shared skill."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERMES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERMES))

import ultron_nutrition_notes as notes  # noqa: E402
from ultron_nutrition_notes import NotesChanged, main, rewrite  # noqa: E402

SAMPLE = ("# Episteck Home Agent\n\n## Tool invocation mechanics\n\n- one per tool_call\n"
          "- `mcp__nutrition__get_daily_nutrition_gap` requires `date`.\n\n## Finance workflows\n\nf\n\n"
          "## Nutrition intake capture\n\n1. old rule\n\nSee [references/nutrition-diary.md](x).\n\n"
          "## Consumer-product health claims\n\nc\n")
POINTER = (HERMES / "home-agent" / "nutrition-pointer-section.md").read_text(encoding="utf-8")


def _files(tmp_path, text=SAMPLE):
    skill = tmp_path / "SKILL.md"
    skill.write_bytes(text.encode("utf-8"))
    return skill, HERMES / "home-agent" / "nutrition-pointer-section.md"


def test_rewrite_replaces_the_section_and_drops_the_retired_tool():
    new, changes = rewrite(SAMPLE, POINTER)
    assert "old rule" not in new and POINTER.strip() in new and "get_daily_nutrition_gap" not in new
    assert "## Finance workflows" in new and "## Consumer-product health claims\n\nc\n" in new
    assert changes == ["section replaced", "retired tool line removed"]


def test_rewrite_is_idempotent():
    once, _ = rewrite(SAMPLE, POINTER)
    assert rewrite(once, POINTER) == (once, [])


def test_idempotent_when_section_is_last():
    text = "# A\n\n## Nutrition intake capture\n\nold\n"
    once, _ = rewrite(text, POINTER)
    assert once.endswith(POINTER.strip() + "\n")
    assert rewrite(once, POINTER) == (once, [])


def test_missing_heading_changes_nothing():
    with pytest.raises(NotesChanged):
        rewrite(SAMPLE.replace("## Nutrition intake capture", "## Food"), POINTER)


@pytest.mark.parametrize("other", ["## Nutrition intake capture", "## Nutrition-x", "### Nutrition"])
def test_plain_heading_is_not_prefix_matched(other):
    text = f"# A\n\n{other}\n\nbody\n\n## Next\n\nn\n"
    if other == "## Nutrition intake capture":
        new, _ = rewrite(text, POINTER)  # the first heading in order matches
        assert "body" not in new
    else:
        with pytest.raises(NotesChanged):
            rewrite(text, POINTER)


def test_nutrition_heading_used_when_first_is_absent_and_subheadings_stay_inside():
    text = "# A\n\n## Nutrition  \n\n### Sub\n\nold\n\n## Next\n\nn\n"
    new, _ = rewrite(text, POINTER)
    assert "old" not in new and "### Sub" not in new and "\n\n## Next\n\nn\n" in new


def test_main_keeps_mode_and_reports_without_content(tmp_path, capsys):
    skill, pointer = _files(tmp_path)
    os.chmod(skill, 0o640)
    mode = skill.stat().st_mode
    assert main([str(skill), str(pointer)]) == 0
    assert capsys.readouterr().out == "section replaced\nretired tool line removed\n"
    assert "old rule" not in skill.read_text(encoding="utf-8")
    assert skill.stat().st_mode == mode
    assert main([str(skill), str(pointer)]) == 0
    assert capsys.readouterr().out == "no changes\n"


def test_main_exit_3_leaves_file_untouched(tmp_path, capsys):
    skill, pointer = _files(tmp_path, SAMPLE.replace("## Nutrition intake capture", "## Food"))
    before = skill.read_bytes()
    assert main([str(skill), str(pointer)]) == 3
    assert skill.read_bytes() == before
    captured = capsys.readouterr()
    assert captured.out == "" and "by hand" in captured.err


def test_main_refuses_a_symlink(tmp_path, monkeypatch, capsys):
    skill, pointer = _files(tmp_path)
    before = skill.read_bytes()
    monkeypatch.setattr(os.path, "islink", lambda p: True)
    assert main([str(skill), str(pointer)]) == 3
    assert skill.read_bytes() == before
    assert capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["a"], ["a", "b", "c"]])
def test_main_usage(argv, capsys):
    assert main(argv) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_pointers_name_the_skill():
    for f in ("nutrition-pointer-section.md", "nutrition-diary-pointer.md"):
        t = (HERMES / "home-agent" / f).read_text(encoding="utf-8")
        assert "olin-nutrition" in t and "skill_view" in t


def test_pointer_files_shape_and_no_extra_h2():
    sec = (HERMES / "home-agent" / "nutrition-pointer-section.md").read_text(encoding="utf-8")
    diary = (HERMES / "home-agent" / "nutrition-diary-pointer.md").read_text(encoding="utf-8")
    assert sec.startswith("## Nutrition\n") and diary.startswith("# Nutrition diary workflows\n")
    for t in (sec, diary):
        assert "\r" not in t and notes.RETIRED_TOOL not in t
        assert [l for l in t.splitlines() if l.startswith("## ")] in ([], ["## Nutrition"])
