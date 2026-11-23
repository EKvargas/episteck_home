"""Static checks on Ana's Hermes artifacts (Nutrition R1, Task 8). Nothing here touches a node."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ANA = ROOT / "deploy" / "hermes" / "home-agent-ana"
SKILL = ROOT / "deploy" / "hermes" / "skills" / "olin-nutrition" / "SKILL.md"
SOUL = ANA / "SOUL.md"
CONFIG = ANA / "config-ana.yaml"
NUTRITION_SERVER = ROOT / "services" / "nutrition" / "app" / "mcp" / "server.py"
HOME_SERVER = ROOT / "services" / "home-mcp" / "home_mcp" / "server.py"

REQUIRED = ["mcp__home__whoami"] + [f"mcp__nutrition__{t}" for t in (
    "search_foods", "get_food_detail", "evaluate_meal", "propose_intake", "confirm_intake",
    "correct_intake", "void_intake", "get_diary_entry", "get_day_summary", "get_period_summary",
    "close_day", "set_nutrition_mode", "get_nutrition_profile", "propose_profile",
    "confirm_profile", "search_recipes", "get_meal_plan", "plan_menu")]


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
    assert len(_mcp_tools(NUTRITION_SERVER)) == 20
    for tool in REQUIRED:
        assert tool in available, tool


def test_no_finance_anywhere():
    for path in (SKILL, SOUL, CONFIG):
        assert "finance" not in path.read_text(encoding="utf-8").lower(), path.name


def test_fixed_spanish_replies_are_present():
    body = _flat(_body())
    for phrase in (
            "¿Lo guardo? (sí / corrige)", "Guardado.", "¿Eso fue todo hoy?", "Día cerrado.",
            "¿Qué quieres que confirme?", "sin dato", "Referencia general",
            "Eso es mejor consultarlo con tu matrona o tu médico.",
            "Todavía no leo fotos; dime qué es.",
            "No tengo permiso para usar tu diario. Renuévalo en bff.home.episteck.com/runtime.",
            "¿Confirmas que estás embarazada y que la fecha probable de parto es el <fecha>? (sí / no)",
            "Para compararlo con tus objetivos necesito tu perfil. ¿Lo creamos ahora? Son unas ocho preguntas.",
            "¿Cierro el <día> de <mes>? (sí / no)",
            "Por ahora el perfil es solo para mayores de 19 años.",
            "En el embarazo no fijamos objetivos de peso ni de déficit.",
            "Todavía no registro el ejercicio; lo tendré cuando conectemos tu reloj."):
        assert phrase in body, phrase


def test_scope_line_is_not_in_the_shared_skill():
    assert "Solo te ayudo" not in _body()


def test_the_skill_lives_in_one_shared_place():
    assert not (ROOT / "deploy/hermes/home-agent-ana/skills").exists()


def test_ana_installer_reads_the_shared_skill():
    t = (ROOT / "deploy/hermes/install-home-agent-ana.sh").read_text(encoding="utf-8")
    assert "SHARED_SKILL=$SRC/skills/olin-nutrition/SKILL.md" in t and "$ANA_SRC/skills" not in t


def test_language_rule_is_explicit():
    s = _flat(_section(_body(), "## Language"))
    assert "persona" in s and "language the person writes in" in s and "verbatim" in s and "translate" in s


def test_never_sums_nutrients_itself():
    s = _flat(_section(_body(), "## Numbers"))
    for tool in ("get_day_summary", "get_period_summary", "evaluate_meal", "plan_menu"):
        assert tool in s
    assert "never add up" in s.lower()


def test_onboarding_flow():
    s = _flat(_section(_body(), "## Profile and onboarding"))
    for needle in ("propose_profile", "confirm_profile", "onboarded", "targets_after", "1.4", "1.6",
                   "1.8", "2.0", "MAINTAIN", "LOSE_FAT", "BUILD_MUSCLE", "PERFORMANCE",
                   "at most once", "UNDER_19", "NOT_ALLOWED_IN_MODE", "MEASUREMENT_TOO_OLD"):
        assert needle in s, needle


def test_reviews_use_the_period_tool_and_ask_before_closing_past_days():
    s = _flat(_section(_body(), "## Reviews and recommendations"))
    assert "get_period_summary" in s and "31" in s and "¿Cierro el" in s and "close_day" in s


def test_yes_acts_on_the_last_question_for_either_draft():
    s = _flat(_section(_body(), "## Yes and no"))
    assert "last question" in s and "confirm_intake" in s and "confirm_profile" in s and "Never both" in s


def test_pregnancy_guardrails():
    s = _flat(_section(_body(), "## Pregnancy"))
    assert s.startswith("## Pregnancy In pregnancy mode:")
    assert "No weight-loss goal, energy deficit or dieting advice" in s
    assert "En el embarazo no fijamos objetivos de peso ni de déficit." in s
    assert "Eso es mejor consultarlo con tu matrona o tu médico." in s


def test_clinical_questions_outside_pregnancy_go_to_the_doctor():
    s = _flat(_section(_body(), "## Health questions"))
    assert "Outside pregnancy mode" in s and "clinical or medical questions" in s
    assert "`Eso es mejor consultarlo con tu médico.`" in s
    assert "matrona" not in s  # the midwife line stays in pregnancy mode


def test_check_in_adds_energy_and_protein_with_a_profile():
    s = _flat(_section(_body(), "## Evening check-in (cron)"))
    assert "profile_version" in s and "energy" in s and "protein" in s and "[SILENT]" in s


def test_check_in_gives_a_nutrient_only_when_its_target_is_not_null():
    # A mode-only or MIGRATED profile version has no energy or protein targets (R15).
    s = _flat(_section(_body(), "## Evening check-in (cron)"))
    assert ("For `energy_kcal` and `protein_g` in `nutrients`, include `known` against `target` "
            "only when that nutrient's `target` is not null; leave out a nutrient whose `target` "
            "is null.") in s
    assert "A non-null `profile_version` alone is not enough" in s
    assert "A day with no targets gets the free-sugar message only." in s
    assert "When `profile_version` is not null, also include" not in s


def test_evaluate_meal_figures_need_every_food_to_report_the_nutrient():
    numbers = _flat(_section(_body(), "## Numbers"))
    assert "An `evaluate_meal` total counts only the foods that report that nutrient" in numbers
    s = _flat(_section(_body(), "## Foods, meals, recipes and menus"))
    assert "`evaluate_meal` adds up only the nutrients each food reports." in s
    assert ("Quote its figure for a nutrient only when every food in the meal lists that nutrient "
            "in `get_food_detail`'s `known_nutrients`; otherwise that nutrient reads `sin dato`.") in s
    # The field the rule relies on is the one get_food_detail returns.
    assert '"known_nutrients"' in NUTRITION_SERVER.read_text(encoding="utf-8")


def test_plan_menu_input_shape_is_the_one_the_service_reads():
    s = _flat(_section(_body(), "## Foods, meals, recipes and menus"))
    assert ("`mcp__nutrition__plan_menu` takes `subject_person_id` and `meals`, a list of meals shaped "
            '`{"label": "<name, e.g. desayuno>", "foods": [{"food_id": "<from search_foods>", '
            '"grams": <number>}]}`') in s
    assert '`mcp__nutrition__evaluate_meal` takes `foods`, a list of `{"food_id": ..., "grams": ...}`' in s
    server = NUTRITION_SERVER.read_text(encoding="utf-8")
    assert re.search(r"def plan_menu\(\s*subject_person_id: str, meals: list\[dict\]\s*\)", server)
    assert re.search(r"def evaluate_meal\(foods: list\[dict\]\)", server)
    service = (ROOT / "services" / "nutrition" / "app" / "service.py").read_text(encoding="utf-8")
    for key in ('meal["foods"]', 'meal["label"]', 'food["food_id"]', 'food["grams"]'):
        assert key in service, key


def test_confirming_names_the_entry_day_not_today():
    s = _flat(_section(_body(), "## Confirming"))
    assert "the free sugars of the entry's day from the returned `day`" in s
    assert "naming that day as day and month from its `date`" in s
    assert "today's" not in s


def test_invalid_field_reasons_cover_every_reason():
    s = _flat(_section(_body(), "## Profile and onboarding"))
    assert ("`NOT_ALLOWED_IN_MODE` in pregnancy mode only: "
            "`En el embarazo no fijamos objetivos de peso ni de déficit.`") in s
    assert "`FUTURE_DATE` on `birth_date`: ask for the birth date again." in s
    assert "`MEASUREMENT_TOO_OLD`, and `FUTURE_DATE` on `weight_measured_on`" in s
    catch_all = s[s.index("Any other reason"):]
    for reason in ("`OVER_100`", "`UNKNOWN_FIELD`", "`TOO_LONG`", "`NOT_ALLOWED_IN_MODE` outside"):
        assert reason in catch_all, reason
    assert "this field was not accepted, and ask for it again" in catch_all
    # Every reason the domain can raise is handled by name or by the catch-all.
    domain = (ROOT / "packages" / "nutrition-domain" / "src" / "nutrition_domain" / "profile.py")
    doc = re.search(r"Reasons: (.*?)\(INVALID", domain.read_text(encoding="utf-8"), re.S).group(1)
    for reason in re.findall(r"[A-Z_0-9]+", doc):
        assert f"`{reason}`" in s, reason


def test_privacy_rule():
    s = _flat(_section(_body(), "## Privacy")).lower()
    assert "memory" in s and "body data" in s

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
    assert "`date` = the day that question named (YYYY-MM-DD)" in section
    assert "never today's date by default" in section


def test_late_logging_passes_consumed_at():
    section = _flat(_section(_body(), "## Logging food"))
    assert "`consumed_at`" in section and "propose_intake" in section
    assert "local ISO date-time without offset" in section and "2026-11-20T23:30" in section


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
    assert "nutrición" in soul and "médic" in soul and "español" in soul
    assert "Solo te ayudo con tu nutrición." in soul
    assert "«Solo te ayudo con tu nutrición.»" in soul  # quoted: the exact line to send
    assert not re.search(r"\b(the|you|and)\b", soul)


def test_evening_check_in_section_exists_with_its_contract():
    section = _flat(_section(_body(), "## Evening check-in (cron)"))
    for needle in ("[SILENT]", "COMPLETE", "NO_ENTRIES", "¿Eso fue todo hoy?",
                   "No tengo permiso para usar tu diario."):
        assert needle in section, needle
    assert "an error other than an access refusal: reply exactly `[SILENT]`" in section
    assert section.index("other than an access refusal") < section.index("No tengo permiso")
    assert "names the day it is about" in section and "`date`" in section


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
