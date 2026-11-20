"""Static checks on Ana's Hermes artifacts (Nutrition R1, Task 8). Nothing here touches a node."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ANA = ROOT / "deploy" / "hermes" / "home-agent-ana"
SKILL = ANA / "skills" / "olin-nutrition" / "SKILL.md"
SOUL = ANA / "SOUL.md"
CONFIG = ANA / "config-ana.yaml"
NUTRITION_SERVER = ROOT / "services" / "nutrition" / "app" / "mcp" / "server.py"
HOME_SERVER = ROOT / "services" / "home-mcp" / "home_mcp" / "server.py"

REQUIRED = [
    "mcp__home__whoami", "mcp__nutrition__search_foods", "mcp__nutrition__propose_intake",
    "mcp__nutrition__confirm_intake", "mcp__nutrition__correct_intake",
    "mcp__nutrition__void_intake", "mcp__nutrition__get_day_summary",
    "mcp__nutrition__close_day", "mcp__nutrition__set_nutrition_mode",
]


def _split() -> tuple[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return text[4:end], text[end + 5:]


def _body() -> str:
    return _split()[1]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(body: str, heading: str) -> str:
    start = body.index(heading)
    end = body.find("\n## ", start + len(heading))
    return body[start:] if end == -1 else body[start:end]


def _hermes_mcp_name(server: str, tool: str) -> str:
    clean = lambda value: re.sub(r"[^A-Za-z0-9_]", "_", value)  # noqa: E731
    return f"mcp__{clean(server)}__{clean(tool)}"


def _mcp_tools(path: Path) -> list[str]:
    return re.findall(r"@mcp\.tool(?:\([^)]*\))?\s+def (\w+)\(", path.read_text(encoding="utf-8"))


def test_frontmatter_and_required_tools_exist():
    yaml = pytest.importorskip("yaml")
    front = yaml.safe_load(_split()[0])
    assert front["name"] == "olin-nutrition"
    assert front["metadata"]["hermes"]["requires_tools"] == REQUIRED
    available = {_hermes_mcp_name("nutrition", t) for t in _mcp_tools(NUTRITION_SERVER)}
    available |= {_hermes_mcp_name("home", t) for t in _mcp_tools(HOME_SERVER)}
    assert len(_mcp_tools(NUTRITION_SERVER)) == 21
    for tool in REQUIRED:
        assert tool in available, tool


def test_no_finance_anywhere():
    for path in (SKILL, SOUL, CONFIG):
        assert "finance" not in path.read_text(encoding="utf-8").lower(), path.name


def test_fixed_spanish_replies_are_present():
    body = _flat(_body())
    for phrase in ("¿Lo guardo? (sí / corrige)", "¿Eso fue todo hoy?",
                   "Todavía no leo fotos; dime qué es.", "sin dato", "Referencia general",
                   "Eso es mejor consultarlo con tu matrona o tu médico.",
                   "Solo te ayudo con tu diario de comidas.",
                   "No tengo permiso para usar tu diario. Renuévalo en bff.home.episteck.com/runtime."):
        assert phrase in body, phrase


def test_unknown_or_empty_is_never_zero():
    section = _flat(_section(_body(), "## Numbers"))
    assert "null" in section and "`sin dato`" in section and "never 0" in section
    assert "`NO_ENTRIES`" in section and "todavía no hay registros hoy" in section
    assert "never `0 g`" in section


def test_ambiguous_yes_acts_on_the_last_question_only():
    section = _flat(_section(_body(), "## Yes and no"))
    assert "¿Lo guardo?" in section and "confirm_intake" in section
    assert "¿Eso fue todo hoy?" in section and "close_day" in section
    assert "Día cerrado." in section
    assert "¿Qué quieres que confirme?" in section
    assert "Never both" in section


def test_mode_changes_need_her_explicit_confirmation():
    section = _flat(_section(_body(), "## Mode"))
    assert "¿Confirmas que estás embarazada y que la fecha probable de parto es el <fecha>? (sí / no)" in section
    assert "set_nutrition_mode" in section and "GENERAL" in section
    assert "Never infer" in section


def test_unit_tokens_match_the_tool_guide():
    source = NUTRITION_SERVER.read_text(encoding="utf-8")
    start = source.index("_ITEM_GUIDE = ")
    guide = source[start:source.index('"""', start + 20)]
    lines = [ln.strip() for ln in guide[guide.index("unit: one of"):guide.index("stated:")].splitlines()]
    token_lines = [ln for ln in lines if ln.startswith(("g, ml", "small_glass", "tablespoon", "piece, slice"))]
    assert len(token_lines) == 4
    guide_tokens = {tok for ln in token_lines
                    for tok in re.findall(r"(?:^|,\s)([a-z_]+)(?=\s\(|[,;:]|$)", ln)}
    assert len(guide_tokens) == 14
    listed = re.search(r"^Unit tokens: (.*)$", _body(), re.M)
    assert listed, "the skill must list the unit tokens on a `Unit tokens:` line"
    assert set(re.findall(r"`([a-z_]+)`", listed.group(1))) == guide_tokens

def test_german_search_fallback_is_taught():
    body = _flat(_body())
    assert "BLS names are German" in body and "Apfelschorle" in body


def test_soul_is_spanish_and_loads_the_skill_first():
    soul = SOUL.read_text(encoding="utf-8")
    assert "olin-nutrition" in soul and "skill_view" in soul
    assert "Olin" in soul and "Ana" in soul
    assert "diario" in soul and "médic" in soul
    assert not re.search(r"\b(the|you|and)\b", soul)


def test_evening_check_in_section_exists_with_its_contract():
    section = _flat(_section(_body(), "## Evening check-in (cron)"))
    for needle in ("[SILENT]", "COMPLETE", "NO_ENTRIES", "¿Eso fue todo hoy?",
                   "No tengo permiso para usar tu diario."):
        assert needle in section, needle


def test_config_ana_pins_the_ruled_keys_and_values():
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config == {
        "model": {"default": "gpt-5.6-sol", "provider": "openai-codex"},
        "fallback_providers": [{"provider": "kimi-coding", "model": "kimi-k2.6"}],
        "stt": {"enabled": True, "language": "es", "local": {"model": "base"}},
        "timezone": "Europe/Berlin",
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "cron": {"catch_up_missed": False, "mirror_delivery": True},
        "display": {"tool_progress": "off", "interim_assistant_messages": False},
        "mcp_servers": {
            "home": {"url": "http://127.0.0.1:9937/gateway/home/", "enabled": True},
            "nutrition": {"url": "http://127.0.0.1:9937/gateway/nutrition/", "enabled": True},
        },
        "skills": {"external_dirs": "/etc/episteck/hermes-ana/skills"},
        "platforms": {"telegram": {"enabled": True}},
        "group_sessions_per_user": True,
    }
    lowered = CONFIG.read_text(encoding="utf-8").lower()
    for word in ("token", "authorization", "bearer", "secret", "api_key", "allowed"):
        assert word not in lowered, word
