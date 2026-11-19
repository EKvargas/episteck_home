"""Static checks on the Hermes home-agent artifacts for Olin Finance (B9, I2). Nothing here
touches a node.

Run from the repo root:
    uv run --no-project --python 3.13 --with pytest --with pyyaml python -m pytest deploy/hermes/tests -q
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HERMES = ROOT / "deploy" / "hermes"
SKILL = HERMES / "home-agent" / "skills" / "olin-finance" / "SKILL.md"
MCP_SNIPPET = HERMES / "home-agent" / "config-finance.yaml"
INSTALL = HERMES / "install-olin-finance.sh"
SCANNER = HERMES / "memory_hygiene.py"
RUNBOOK = ROOT / "docs" / "runbooks" / "finance-i1-nuremberg-bringup.md"
RUNBOOK_I2 = ROOT / "docs" / "runbooks" / "finance-i2-exchanges.md"
FINANCE = ROOT / "services" / "finance" / "app"
MCP_SERVER = FINANCE / "mcp" / "server.py"
RECEIVABLES_TOOLS = FINANCE / "mcp" / "receivables_tools.py"
GATEWAY_CONF = ROOT / "deploy" / "gateway" / "nginx-mcp-gateway.conf"

SKILLS_ROOT = "/etc/episteck/hermes/skills"
MCP_URL = "http://127.0.0.1:9934/gateway/finance/"
# The skill is hidden from the index unless every one of these is connected (spec §8.3).
REQUIRED_TOOLS = ("finance_overview", "finance_receivables", "finance_record_exchange",
                  "finance_record_receipt", "finance_resolve_pending", "finance_pending")
MONEY = re.compile(r"(?:[€$£]\s?\d|\d[\d.,]*\s?(?:€|EUR|USD|VES)\b)")


def _yaml():
    return pytest.importorskip("yaml")


def _split() -> tuple[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return text[4:end], text[end + 5:]


def _body() -> str:
    return _split()[1]


def _frontmatter_and_body() -> tuple[dict, str]:
    front, body = _split()
    return _yaml().safe_load(front), body


def _hermes_mcp_name(server: str, tool: str) -> str:
    """Hermes 0.21.2 tools/mcp_tool_schema.mcp_prefixed_tool_name."""
    clean = lambda value: re.sub(r"[^A-Za-z0-9_]", "_", value)  # noqa: E731
    return f"mcp__{clean(server)}__{clean(tool)}"


def _mcp_tools(path: Path) -> list[str]:
    return re.findall(r"@mcp\.tool\s+def (\w+)\(", path.read_text(encoding="utf-8"))


def _receivables_source() -> str:
    files = sorted((FINANCE / "receivables").glob("*.py")) + [RECEIVABLES_TOOLS]
    return "".join(path.read_text(encoding="utf-8") for path in files)


def _flat(text: str) -> str:
    """Prose may wrap anywhere: compare phrases with whitespace collapsed."""
    return " ".join(text.split())


def _section(body: str, heading: str) -> str:
    start = body.index(heading)
    end = body.find("\n## ", start + len(heading))
    return body[start:] if end == -1 else body[start:end]


# --- the skill -----------------------------------------------------------------------------

def test_skill_frontmatter_names_the_skill():
    front, _ = _frontmatter_and_body()
    assert front["name"] == "olin-finance"
    # Hermes's skill index truncates past 60 characters, losing the routing signal.
    assert 20 <= len(front["description"]) <= 60
    assert front["license"]
    _, body = _frontmatter_and_body()
    assert body.index("## When to Use") < body.index("## The one source of figures")
    hermes = front["metadata"]["hermes"]
    assert hermes["requires_tools"] == [_hermes_mcp_name("finance", t) for t in REQUIRED_TOOLS]


def test_requires_tools_lists_the_overview_receivables_and_answer_tools():
    # Parsed without yaml so it runs with the plain pytest command too.
    front, _ = _split()
    listed = re.search(r"^\s*requires_tools: \[(.*)\]\s*$", front, re.M)
    assert listed, "requires_tools must be a one-line flow list"
    names = [name.strip() for name in listed.group(1).split(",")]
    assert names == [_hermes_mcp_name("finance", t) for t in REQUIRED_TOOLS]


def test_the_required_tools_exist_in_the_finance_mcp_server():
    server = MCP_SERVER.read_text(encoding="utf-8")
    assert re.search(r"@mcp\.tool\s+def finance_overview\(valuation_currency", server)
    tools = _mcp_tools(MCP_SERVER) + _mcp_tools(RECEIVABLES_TOOLS)
    assert set(REQUIRED_TOOLS) <= set(tools)
    body = _body()
    for tool in tools:  # a new Finance tool must be taught to the skill before it ships
        assert _hermes_mcp_name("finance", tool) in body, tool


def test_skill_covers_every_refusal_code_the_mcp_server_returns():
    # The refusal table lives with the receivables tools since I2; server.py imports it.
    source = MCP_SERVER.read_text(encoding="utf-8") + RECEIVABLES_TOOLS.read_text(encoding="utf-8")
    codes = re.findall(r'\(\w+, "([a-z_]+)"\)', source)
    assert len(codes) >= 5
    body = _body()
    for code in codes:
        assert f"`{code}`" in body, code


def test_skill_covers_every_receivables_tool_and_error_code():
    tools = _mcp_tools(RECEIVABLES_TOOLS)
    assert len(tools) == 14
    body = _body()
    for tool in tools:
        assert _hermes_mcp_name("finance", tool) in body, tool
    source = _receivables_source()
    codes = ("validation_error", "clarification_needed", "possible_duplicate",
             "idempotency_conflict", "already_linked", "unknown_choice", "unknown_pending",
             "already_resolved", "internal_error", "options_changed", "changed", "stale",
             "not_resolved", "unknown_movement")
    statuses = ("confirmation_required", "needs_amount", "needs_counterparty",
                "needs_correction", "asked_again", "already_settled", "dismissed",
                "not_recorded", "cancelled", "linked", "not_exchange", "needs_exchange",
                "not_yet", "recorded", "confirmed", "snoozed", "reversed")
    for value in codes + statuses:
        assert f'"{value}"' in source, f"{value} is not something Finance returns"
        assert f"`{value}`" in body, value


def test_skill_covers_every_pending_kind_option_and_notice():
    model = (FINANCE / "receivables" / "model.py").read_text(encoding="utf-8")
    kinds = re.findall(r'"([A-Z_]+)"',
                       re.search(r"class PendingKind\(str, Enum\):(.*?)\n\n", model, re.S).group(1))
    assert len(kinds) == 6
    source = _receivables_source()
    notices = set(re.findall(r'notice\(conn, ws, f"([a-z_]+):', source))
    notices |= set(re.findall(r'_BOOKED_CHANGED = "([a-z_]+)"', source))
    assert notices == {"funding_closed", "rate_outlier", "receipt_applied",
                       "small_difference_closed", "booked_amount_changed", "fund_low"}
    options = ("ALL", "ADD_TO", "REGISTER", "NOT_EXCHANGE", "NOT_YET", "OTHER", "LATER")
    body = _body()
    for value in kinds + sorted(notices):
        assert f"`{value}`" in body, value
    for value in options:
        assert f'"{value}' in source, value
        assert f"`{value}" in body, value


def test_every_receivables_field_the_skill_relies_on_exists_in_finance():
    source = _receivables_source()
    fields = ("owed_to_you", "held_for_others", "owed_to_partner", "to_fix", "subtotals",
              "held_cash", "where", "opening", "since", "out_since", "in_since", "account",
              "lines", "outstanding", "exchange_ref", "entry_ref", "delivered_on", "items",
              "code", "options", "choice", "label", "requires_answer", "details", "suggested",
              "notice", "echo", "high_value", "duplicate_of", "eur_pending", "expected",
              "candidates", "field", "detail", "question", "resolution", "balance_after",
              "credit", "direction", "rate", "reference_rate", "funding_ref", "receipt_ref",
              "exchange_refs", "booking_date", "sender", "held", "alert", "new_funding_ref",
              "eur_before", "eur_after", "amount_before", "amount_after", "new_receipt_ref",
              "rules_revoked", "undo_ref", "shown", "created_at")
    body = _body()
    for field in fields:
        assert f'"{field}"' in source, f"{field} is not a receivables result field"
        assert f"`{field}`" in body, f"the skill does not explain {field}"
    assert "eur_per_usd" in source and "`eur_per_usd`" in body


def test_skill_forbids_confirming_without_the_owner_tap():
    lowered = _flat(_body()).lower()
    for phrase in ("writes nothing until the owner says yes",
                   "[sí] [corregir] [cancelar]",
                   "[es otro] [es el mismo]",
                   "only with the owner's own answer",
                   "never send `yes` on the owner's behalf",
                   "a yes given before the echo is not a yes to it",
                   "buttons carry `choice`, never `n`"):
        assert phrase in lowered, phrase
    # for_delivery marks items as sent: it belongs to the scheduled job only.
    outside = _flat(_body().replace(_section(_body(), "## Scheduled delivery"), "")).lower()
    assert "for_delivery=true" not in outside.replace("never set `for_delivery=true`", "")


def test_skill_states_the_cron_contract():
    section = _flat(_section(_body(), "## Scheduled delivery"))
    for needle in ("06:35", "18:35", "UTC", "`mcp__finance__finance_pending`",
                   "`for_delivery=true`", "exactly `[SILENT]`", "one message",
                   "pendiente de tu confirmación", "P<n> sí"):
        assert needle in section, needle


def test_skill_covers_every_account_status_and_liquidity():
    overview = (FINANCE / "overview.py").read_text(encoding="utf-8")
    statuses = set(re.findall(r'"(FRESH|STALE|REAUTH_DUE|REAUTH_REQUIRED|NO_DATA)"', overview))
    assert statuses == {"FRESH", "STALE", "REAUTH_DUE", "REAUTH_REQUIRED", "NO_DATA"}
    domain = (FINANCE / "domain.py").read_text(encoding="utf-8")
    liquidity = re.search(r"class Liquidity\(str, Enum\):(.*?)\n\n", domain, re.S).group(1)
    body = _body()
    for value in statuses | set(re.findall(r'"([A-Z]+)"', liquidity)) | {"SIMPLEFIN", "ENABLE_BANKING"}:
        assert f"`{value}`" in body, value


def test_every_result_field_the_skill_relies_on_exists_in_finance():
    source = "".join((FINANCE / name).read_text(encoding="utf-8")
                     for name in ("overview.py", "service.py"))
    fields = ("as_of", "accounts", "subtotals", "valuation", "hidden_accounts", "institution",
              "currency", "liquidity", "amount", "source", "status", "stale", "includes_stale",
              "rate_date", "stale_rates", "unvalued", "basis")
    body = _body()
    for field in fields:
        assert f'"{field}"' in source, f"{field} is not a Finance result field"
        assert f"`{field}`" in body, f"the skill does not explain {field}"


def test_skill_states_the_non_negotiable_rules():
    lowered = _flat(_body()).lower()
    for phrase in ("this same turn", "never save", "spanish", "no actor", "valuation_currency",
                   "mcp__home__check_access", "never sum", "private chat",
                   # I2 (spec §8.3): amounts, VES, bank payments, "where is my money"
                   "plain decimal", "never convert ves", "bank sync", "de los cuales",
                   "names of family members with amounts"):
        assert phrase in lowered, phrase


def test_skill_contains_no_example_figures_the_model_could_repeat():
    body = _body()
    assert not MONEY.search(body), MONEY.search(body)
    assert not re.search(r"\b[A-Z]{2}\d{2}\s?\d{4}", body)  # no IBAN-shaped examples
    # Normalisation is taught with digit placeholders, never with a real-looking amount.
    assert not re.search(r"\d[.,]\d{3}[.,]\d{2}", body)


# --- the MCP entry -------------------------------------------------------------------------

def test_mcp_snippet_points_hermes_at_the_gateway_finance_route_only():
    config = _yaml().safe_load(MCP_SNIPPET.read_text(encoding="utf-8"))
    assert config["mcp_servers"] == {"finance": {"url": MCP_URL, "enabled": True}}
    assert config["skills"] == {"external_dirs": SKILLS_ROOT}
    gateway = GATEWAY_CONF.read_text(encoding="utf-8")
    assert "listen 127.0.0.1:9934;" in gateway
    assert "location /gateway/finance/ {" in gateway


def test_mcp_snippet_carries_no_credentials():
    text = MCP_SNIPPET.read_text(encoding="utf-8").lower()
    for word in ("header", "token", "authorization", "bearer", "secret", "api_key", "delegation:"):
        assert word not in text, word


# --- the install script ----------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_install_script_is_syntactically_valid():
    result = subprocess.run(["bash", "-n", INSTALL.relative_to(ROOT).as_posix()], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_install_script_has_every_step_and_matches_the_snippet():
    text = INSTALL.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    for step in ("preflight", "install", "cron", "verify", "memory-scan", "rollback-cron",
                 "rollback"):
        assert re.search(rf"^\s*{step}\)", text, re.M), step
    assert f'MCP_URL={MCP_URL}' in text
    assert f'SKILLS_ROOT={SKILLS_ROOT}' in text
    assert 'config set mcp_servers.finance.url "$MCP_URL"' in text
    assert 'config set skills.external_dirs "$SKILLS_ROOT"' in text


def _case(text: str, step: str) -> str:
    start = re.search(rf"^  {re.escape(step)}\)", text, re.M).start()
    return text[start:text.index(";;", start)]


def test_install_script_has_cron_step_with_rollback():
    text = INSTALL.read_text(encoding="utf-8")
    assert "CRON_NAME=olin-finance-pending" in text
    assert "CRON_SCHEDULE='35 6,18 * * *'" in text  # spec F9: 06:35 and 18:35 UTC
    cron = _case(text, "cron")
    # Idempotent: a job of that name is removed first, so a re-run never adds a second one.
    assert cron.count("cron create") == 1
    assert cron.index("cron_remove") < cron.index("cron create")
    for part in ('--name "$CRON_NAME"', "--deliver telegram", "--skill olin-finance",
                 '"$CRON_SCHEDULE" "$CRON_PROMPT"'):
        assert part in cron, part
    assert '[ -f "$SKILL_DIR/SKILL.md" ]' in cron  # the job loads the installed skill
    assert 'cron remove "$CRON_NAME"' in text  # by name, inside cron_remove
    assert "cron_remove" in _case(text, "rollback-cron")
    assert "cron_remove" in _case(text, "rollback")  # a full rollback leaves no orphan job
    # verify lists the job through cron_show, which prints `hermes cron list` lines for it
    assert "cron_show" in _case(text, "verify")
    start = text.index("cron_show() {")
    assert "cron list" in text[start:text.index("\n}\n", start)]


def test_cron_prompt_delivers_once_and_stays_silent_when_empty():
    text = INSTALL.read_text(encoding="utf-8")
    prompt = _flat(re.search(r"^CRON_PROMPT='([^']*)'$", text, re.M | re.S).group(1))
    for needle in ("mcp__finance__finance_pending", "for_delivery=true", "exactly once",
                   "[SILENT]", "pendiente de tu confirmación", "Spanish", "Call no other tool"):
        assert needle in prompt, needle
    # The job list is searched for the job name: the prompt must not contain it.
    assert "olin-finance-pending" not in prompt
    assert not MONEY.search(prompt)


def test_install_backs_up_the_config_before_changing_it_and_rollback_restores_it():
    text = INSTALL.read_text(encoding="utf-8")
    install = text[text.index("  install)"):text.index("  verify)")]
    assert install.index('cp -p "$CONFIG"') < install.index("config set")
    rollback = text[text.index("  rollback)"):]
    assert 'cp -p "$bk/config.yaml" "$CONFIG"' in rollback
    # The skill is root-owned and read-only to home-agent: the agent cannot rewrite its rules.
    assert "install -m 644 -o root -g root" in install


def test_install_script_never_prints_secrets_or_memory_contents():
    text = INSTALL.read_text(encoding="utf-8")
    assert not re.search(r"\b(cat|less|head|tail|grep)\b[^\n]*(\.env|auth\.json|memories)", text)
    assert "| sh" not in text and "| bash" not in text
    assert "rm -rf" not in text
    assert "diff " not in text  # a config diff could print values; the key diff prints paths


# --- the memory hygiene scanner --------------------------------------------------------------

def _scanner():
    spec = importlib.util.spec_from_file_location("memory_hygiene", SCANNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scanner_counts_amounts_ibans_and_account_numbers(tmp_path):
    (tmp_path / "MEMORY.md").write_text(
        "Prefers USD first.\nBalance was 1.234,56 € and $1,200 and 300 USD and Bs 45\n",
        encoding="utf-8")
    (tmp_path / "USER.md").write_text("IBAN DE89 3704 0044 0532 0130 00, card 4111111111111111\n",
                                      encoding="utf-8")
    (tmp_path / "clean.md").write_text("Likes short answers in Spanish.\n", encoding="utf-8")
    results = _scanner().scan(tmp_path)
    assert results["MEMORY.md"]["amount"] == 4
    assert results["USER.md"]["iban"] == 1
    assert results["USER.md"]["long_number"] >= 1
    assert sum(results["clean.md"].values()) == 0


def test_scanner_prints_counts_only_and_exits_1_on_findings(tmp_path, capsys):
    (tmp_path / "MEMORY.md").write_text("Saldo: 987,65 EUR, IBAN DE89 3704 0044 0532 0130 00\n",
                                        encoding="utf-8")
    assert _scanner().main(["memory_hygiene.py", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "987" not in out and "DE89" not in out and "3704" not in out
    assert "MEMORY.md" in out and "findings=" in out


def test_scanner_exits_0_when_clean_and_2_on_bad_usage(tmp_path):
    (tmp_path / "MEMORY.md").write_text("Prefiere respuestas cortas.\n", encoding="utf-8")
    scanner = _scanner()
    assert scanner.main(["memory_hygiene.py", str(tmp_path)]) == 0
    assert scanner.main(["memory_hygiene.py"]) == 2
    assert scanner.main(["memory_hygiene.py", str(tmp_path / "missing")]) == 2


# --- the runbook ---------------------------------------------------------------------------

def test_runbook_has_the_skill_step_with_backup_rollback_and_memory_check():
    text = RUNBOOK.read_text(encoding="utf-8")
    section = text[text.index("## 11. Olin Finance skill"):text.index("## Purge")]
    assert "install-olin-finance.sh" in section
    for step in ("preflight", "install", "verify", "memory-scan", "rollback"):
        assert f"HSTEP {step}" in section, step
    assert "**Rollback:**" in section and "**Verify" in section


def test_i2_runbook_covers_upgrade_skill_cron_accounts_rules_and_rollback():
    text = RUNBOOK_I2.read_text(encoding="utf-8")
    for needle in ('STEP build "$SHA"', 'STEP install "$SHA"', "finance-sync.timer",
                   "HSTEP install", "HSTEP cron", "HSTEP verify", "HSTEP rollback-cron",
                   "watch-account", "own-iban", "FINANCE_DESCRIPTION_RULES=on", "VACUUM",
                   "matcher failed", 'STEP install "$PREV_SHA"', "**Verify", "**Rollback:**",
                   "OWN TERMINAL"):
        assert needle in text, needle
    # own-iban reads the IBAN with getpass only on a TTY; without one the terminal echoes it.
    commands = [line for line in text.splitlines() if "app.admin own-iban" in line]
    assert commands, "own-iban command missing"
    block = text[text.rindex("ssh -t", 0, text.index("app.admin own-iban")):
                 text.index("app.admin own-iban")]
    assert "podman run --rm -it" in block
    assert "finance-i2-exchanges.md" in RUNBOOK.read_text(encoding="utf-8")


# --- fix round 1 (R55): the skill's money gaps ---------------------------------------------

def _row(body: str, key: str) -> str:
    """The markdown table row whose first cell is `key`."""
    return next(line for line in body.splitlines() if line.startswith(f"| `{key}`"))


def test_skill_answers_an_open_echo_before_proposing_again():
    lowered = _flat(_body()).lower()
    # A CONFIRM stays open (and the cron re-sends it): a later "sí" would record the old figure.
    assert ("when the owner changes or drops an open echo, first answer its code with "
            "`correct` (or `cancel`), then propose again") in lowered
    assert "send the choice their words mean: `yes`, `correct` or `cancel`" in lowered
    # possible_duplicate after "yes": re-proposing would return the same open code.
    assert "cancel this code, then propose again" in lowered
    cron = _flat(_section(_body(), "## Scheduled delivery")).lower()
    assert "`created_at`" in cron


def test_skill_asks_how_a_person_paid_and_never_records_a_bank_payment():
    body = _body()
    lowered = _flat(body).lower()
    assert "¿en efectivo, en especie o por el banco?" in lowered
    assert "never record a bank payment, not even as `cash` when the owner asks" in lowered
    assert "propose `mcp__finance__finance_reverse` of its `r<n>`" in lowered
    validation = _row(body, "validation_error").lower()
    assert "never suggest recording it another way" in validation
    assert "efectivo" not in validation


def test_skill_teaches_the_opening_sign_per_counterparty_kind():
    # The convention lives in Finance: a person's amount is signed, a fund's is what you hold.
    proposals = (FINANCE / "receivables" / "proposals.py").read_text(encoding="utf-8")
    corrections = (FINANCE / "receivables" / "corrections.py").read_text(encoding="utf-8")
    assert 'shown = "held" if cp.kind is CounterpartyKind.FUND else "amount"' in proposals
    assert "PERSON: signed as given (positive: they owe you" in corrections
    assert "FUND: what you hold, stored negative" in corrections
    section = _flat(_section(_body(), "## Exchanges: what to pass")).lower()
    for phrase in ("a person: positive = te debe, negative = a su favor",
                   "a fund: the amount you hold for it, positive",
                   "a minus sign only for a person's credit"):
        assert phrase in section, phrase
    confirmations = _flat(_section(_body(), "## Confirmations")).lower()
    for phrase in ('"te debe <amount>', '"a su favor <amount', '"guardas <held>'):
        assert phrase in confirmations, phrase


def test_cron_keeps_finance_option_numbers_and_duplicates_take_words():
    cron = _flat(_section(_body(), "## Scheduled delivery")).lower()
    assert "every option with its `n` exactly as returned" in cron
    assert "never renumber, reorder or drop one" in cron
    assert "«p<n> es otro» o «p<n> es el mismo»" in cron
    prompt = _flat(re.search(r"^CRON_PROMPT='([^']*)'$", INSTALL.read_text(encoding="utf-8"),
                             re.M | re.S).group(1)).lower()
    for phrase in ("its number n exactly as returned", "never renumber, reorder or drop",
                   "p<n> es otro", "created_at"):
        assert phrase in prompt, phrase


def test_skill_covers_reverse_forms_held_cash_and_partner_shape():
    body = _body()
    lowered = _flat(body).lower()
    assert "`rule:<name>`" in body and "`mcp__finance__finance_explain`" in body
    assert "`undo_ref` from `ignored`" in lowered
    assert "undo its `f<n>` first" in _row(body, "already_linked").lower()
    assert "`owed_to_partner` is an object" in lowered
    assert "`opening`" in _row(body, "receipt_applied")
    assert "`shown`" in _flat(_section(body, "## Exchanges: which tool"))
    screenshot = _flat(_section(body, "## Exchanges: what to pass")).lower()
    assert "`delivered_on`" in screenshot and "the format rules above still apply" in screenshot
    assert '"cambio c<n> del <fecha>"' in _flat(_row(body, "LINK_FUNDING")).lower()


# --- fix round 1: the install script ------------------------------------------------------

def test_cron_step_refuses_a_skill_that_is_not_this_commits():
    cron = _case(INSTALL.read_text(encoding="utf-8"), "cron")
    assert "need_src" in cron
    assert 'cmp -s "$SRC/home-agent/skills/olin-finance/SKILL.md" "$SKILL_DIR/SKILL.md"' in cron
    assert "'^## Scheduled delivery'" in cron


def test_cron_step_shows_the_id_line_and_warns_before_a_rerun():
    text = INSTALL.read_text(encoding="utf-8")
    start = text.index("cron_show() {")
    show = text[start:text.index("\n}\n", start)]
    assert re.search(r'grep -F -B \d -A \d "\$CRON_NAME"', show)
    cron = _case(text, "cron")
    assert 'created="$(as_agent "$HERMES" cron create' in cron
    assert "a job may exist: remove it by id before re-running" in cron


def test_cron_step_checks_the_hermes_timezone_setting():
    text = INSTALL.read_text(encoding="utf-8")
    assert 'c.get("timezone")' in text  # the one config value printed besides the finance keys
    assert "hermes_tz" in _case(text, "preflight")
    cron = _case(text, "cron")
    assert "hermes_tz" in cron and "UTC" in cron


def test_memory_scan_counts_cron_output_files_and_verify_counts_tools():
    text = INSTALL.read_text(encoding="utf-8")
    scan = _case(text, "memory-scan")
    assert "$HHOME/cron/output" in scan and "wc -l" in scan
    assert not re.search(r"\b(cat|less|head|tail)\b[^\n]*cron/output", text)  # counts only
    verify = _case(text, "verify")
    assert "tail -n 20" not in verify
    assert "(expect 15)" in verify


# --- fix round 1: the I2 runbook -----------------------------------------------------------

def test_i2_runbook_first_load_follows_f8_and_watches_accounts_last():
    text = RUNBOOK_I2.read_text(encoding="utf-8")
    first_load = _section(text, "## 7. First load (F8) and go-live")
    order = ("finance_setup_counterparty", "finance_record_opening", "screenshot",
             "PREVIOUS_UNPAID", "watch-account <account-id> on")
    positions = [first_load.index(step) for step in order]
    assert positions == sorted(positions), "F8 order: counterparties, openings, exchange, IBAN, watch"
    # No account is watched before the first load.
    assert text.index("watch-account <account-id> on") > text.index("## 7. First load (F8)")
    flat = _flat(first_load).lower()
    for phrase in ("right after a sync", "as the bank showed them at the last sync",
                   "before the next sync", "never asked about", "no es de intercambios",
                   "undo_ref"):
        assert phrase in flat, phrase


def test_i2_runbook_has_a_read_only_schema_check_before_and_after_the_restart():
    text = RUNBOOK_I2.read_text(encoding="utf-8")
    for needle in ("mode=ro", "PRAGMA integrity_check", "start_rowid", "matcher_cursor"):
        assert needle in text, needle
    # The checked tables are exactly the ones the I2 schema creates.
    schema = (FINANCE / "store" / "receivables_schema.py").read_text(encoding="utf-8")
    created = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\(", schema)
    listed = re.findall(r'"(\w+)"', re.search(r"^I2 = \((.*?)\)$", text, re.M | re.S).group(1))
    assert sorted(listed) == sorted(created) and len(created) == 22
    step4 = _section(text, "## 4.")
    assert step4.index("SCHEMA_CHECK") < step4.index('STEP install "$SHA"') \
        < step4.rindex("SCHEMA_CHECK")


def test_i2_runbook_rolls_back_everything_once_the_skill_is_installed():
    text = RUNBOOK_I2.read_text(encoding="utf-8")
    step4 = _flat(_section(text, "## 4."))
    assert "Rollback (everything)" in step4 and "Hermes first" in step4
    assert "requires_tools" in step4
    rollback = _flat(_section(text, "## Rollback (everything)"))
    assert "printed by" in rollback and "HSTEP rollback" in rollback


def test_i2_runbook_has_the_pre_deploy_s1_and_go_live_checklist():
    section = _flat(_section(RUNBOOK_I2.read_text(encoding="utf-8"),
                             "## Pre-deploy S1 and go-live checklist"))
    for needle in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "/gateway/finance/",
                   "/var/lib/episteck-mcp-gateway/access.log", "session_invalid", "cron/output",
                   "[SILENT]", "private chat", "--skill", "hermes cron remove"):
        assert needle in section, needle
