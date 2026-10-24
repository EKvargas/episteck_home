"""KAP-2 code on main stays disconnected until the Board ratifies it.

PR #71 merged the Knowledge PERSON candidate (``knowledge_authority`` and
``policy.typed_access``) into ``main``, so ``episteck-deploy`` ships it to the Home
bench. It is safe there only while nothing reaches it: no other Home module imports
it, ``hooks.py`` does not name it, and it exposes no whitelisted method. These tests
turn that into a check instead of a promise. Connecting it is a deliberate change
that must edit this file in the same PR.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "episteck_home"
FENCED = ("episteck_home.knowledge_authority", "episteck_home.policy.typed_access")


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path: Path, root: Path) -> set[str]:
    """Every module a file imports, with relative imports resolved."""
    module = _module_name(path, root)
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            target = ".".join(base + (node.module.split(".") if node.module else []))
            found.add(target)
            found.update(f"{target}.{alias.name}" for alias in node.names)
    return found


def _is_fenced(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FENCED)


def _inside_fence(path: Path, root: Path) -> bool:
    return _is_fenced(_module_name(path, root))


def fence_violations(root: Path) -> list[str]:
    violations = []
    for path in sorted(root.rglob("*.py")):
        if _inside_fence(path, root):
            continue
        for module in sorted(_imported_modules(path, root)):
            if _is_fenced(module):
                violations.append(f"{path.relative_to(root.parent).as_posix()} imports {module}")
    return violations


def whitelisted_in_fence(root: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        if not _inside_fence(path, root):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if "whitelist" in ast.unparse(decorator):
                        found.append(f"{path.relative_to(root.parent).as_posix()}:{node.name}")
    return found


def test_no_home_module_imports_the_kap2_candidate():
    assert fence_violations(PACKAGE_ROOT) == []


def test_hooks_do_not_name_the_kap2_candidate():
    hooks = (PACKAGE_ROOT / "hooks.py").read_text(encoding="utf-8")
    assert "knowledge_authority" not in hooks
    assert "typed_access" not in hooks


def test_kap2_candidate_exposes_no_whitelisted_method():
    assert whitelisted_in_fence(PACKAGE_ROOT) == []


def test_scanner_catches_absolute_and_relative_imports(tmp_path):
    root = tmp_path / "episteck_home"
    (root / "knowledge_authority").mkdir(parents=True)
    (root / "policy").mkdir()
    (root / "api").mkdir()
    for package in (root, root / "knowledge_authority", root / "policy", root / "api"):
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "knowledge_authority" / "lane.py").write_text(
        "import frappe\n\n@frappe.whitelist()\ndef open_lane():\n    pass\n", encoding="utf-8")
    (root / "policy" / "typed_access.py").write_text("", encoding="utf-8")
    (root / "policy" / "wrappers.py").write_text("from . import typed_access\n", encoding="utf-8")
    (root / "api" / "a.py").write_text(
        "from episteck_home.knowledge_authority.lane import open_lane\n", encoding="utf-8")
    (root / "api" / "b.py").write_text("from ..knowledge_authority import lane\n", encoding="utf-8")
    (root / "api" / "c.py").write_text("import episteck_home.policy.typed_access\n", encoding="utf-8")
    (root / "api" / "ok.py").write_text("from ..policy import wrappers\n", encoding="utf-8")

    violations = fence_violations(root)

    flagged = {v.split(" imports ")[0] for v in violations}
    assert flagged == {"episteck_home/api/a.py", "episteck_home/api/b.py",
                       "episteck_home/api/c.py", "episteck_home/policy/wrappers.py"}
    assert whitelisted_in_fence(root) == ["episteck_home/knowledge_authority/lane.py:open_lane"]
