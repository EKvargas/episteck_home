"""Static checks on the Hermes home-agent artifacts for Olin Finance (B9). Nothing here
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
FINANCE = ROOT / "services" / "finance" / "app"
GATEWAY_CONF = ROOT / "deploy" / "gateway" / "nginx-mcp-gateway.conf"

SKILLS_ROOT = "/etc/episteck/hermes/skills"
MCP_URL = "http://127.0.0.1:9934/gateway/finance/"


def _yaml():
    return pytest.importorskip("yaml")


def _frontmatter_and_body() -> tuple[dict, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return _yaml().safe_load(text[4:end]), text[end + 5:]


def _hermes_mcp_name(server: str, tool: str) -> str:
    """Hermes 0.21.2 tools/mcp_tool_schema.mcp_prefixed_tool_name."""
    clean = lambda value: re.sub(r"[^A-Za-z0-9_]", "_", value)  # noqa: E731
    return f"mcp__{clean(server)}__{clean(tool)}"


# --- the skill -----------------------------------------------------------------------------

def test_skill_frontmatter_names_the_skill_and_requires_the_finance_tool():
    front, _ = _frontmatter_and_body()
    assert front["name"] == "olin-finance"
    # Hermes's skill index truncates past 60 characters, losing the routing signal.
    assert 20 <= len(front["description"]) <= 60
    assert front["license"]
    _, body = _frontmatter_and_body()
    assert body.index("## When to Use") < body.index("## The one source of figures")
    hermes = front["metadata"]["hermes"]
    # Hidden from the skill index whenever the Finance MCP server is not connected.
    assert hermes["requires_tools"] == [_hermes_mcp_name("finance", "finance_overview")]


def test_the_required_tool_exists_in_the_finance_mcp_server():
    server = (FINANCE / "mcp" / "server.py").read_text(encoding="utf-8")
    assert re.search(r"@mcp\.tool\s+def finance_overview\(valuation_currency", server)
    tools = re.findall(r"@mcp\.tool\s+def (\w+)\(", server)
    _, body = _frontmatter_and_body()
    for tool in tools:  # a new Finance tool must be taught to the skill before it ships
        assert _hermes_mcp_name("finance", tool) in body, tool


def test_skill_covers_every_refusal_code_the_mcp_server_returns():
    server = (FINANCE / "mcp" / "server.py").read_text(encoding="utf-8")
    codes = re.findall(r'\(\w+, "([a-z_]+)"\)', server)
    assert len(codes) >= 5
    _, body = _frontmatter_and_body()
    for code in codes:
        assert f"`{code}`" in body, code


def test_skill_covers_every_account_status_and_liquidity():
    overview = (FINANCE / "overview.py").read_text(encoding="utf-8")
    statuses = set(re.findall(r'"(FRESH|STALE|REAUTH_DUE|REAUTH_REQUIRED|NO_DATA)"', overview))
    assert statuses == {"FRESH", "STALE", "REAUTH_DUE", "REAUTH_REQUIRED", "NO_DATA"}
    domain = (FINANCE / "domain.py").read_text(encoding="utf-8")
    liquidity = re.search(r"class Liquidity\(str, Enum\):(.*?)\n\n", domain, re.S).group(1)
    _, body = _frontmatter_and_body()
    for value in statuses | set(re.findall(r'"([A-Z]+)"', liquidity)) | {"SIMPLEFIN", "ENABLE_BANKING"}:
        assert f"`{value}`" in body, value


def test_every_result_field_the_skill_relies_on_exists_in_finance():
    source = "".join((FINANCE / name).read_text(encoding="utf-8")
                     for name in ("overview.py", "service.py"))
    fields = ("as_of", "accounts", "subtotals", "valuation", "hidden_accounts", "institution",
              "currency", "liquidity", "amount", "source", "status", "stale", "includes_stale",
              "rate_date", "stale_rates", "unvalued", "basis")
    _, body = _frontmatter_and_body()
    for field in fields:
        assert f'"{field}"' in source, f"{field} is not a Finance result field"
        assert f"`{field}`" in body, f"the skill does not explain {field}"


def test_skill_states_the_non_negotiable_rules():
    _, body = _frontmatter_and_body()
    lowered = body.lower()
    for phrase in ("this same turn", "never save", "spanish", "no actor", "valuation_currency",
                   "mcp__home__check_access", "never sum", "private chat"):
        assert phrase in lowered, phrase


def test_skill_contains_no_example_figures_the_model_could_repeat():
    _, body = _frontmatter_and_body()
    money = re.compile(r"(?:[€$£]\s?\d|\d[\d.,]*\s?(?:€|EUR|USD|VES)\b)")
    assert not money.search(body), money.search(body)
    assert not re.search(r"\b[A-Z]{2}\d{2}\s?\d{4}", body)  # no IBAN-shaped examples


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
    for step in ("preflight", "install", "verify", "memory-scan", "rollback"):
        assert re.search(rf"^\s*{step}\)", text, re.M), step
    assert f'MCP_URL={MCP_URL}' in text
    assert f'SKILLS_ROOT={SKILLS_ROOT}' in text
    assert 'config set mcp_servers.finance.url "$MCP_URL"' in text
    assert 'config set skills.external_dirs "$SKILLS_ROOT"' in text


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
