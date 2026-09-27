"""Self-review against the CLI-Anything validation checklist, adapted to this
standalone ``src/`` layout.

Run from the repository root::

    python validate_self.py

Prints PASS/FAIL per check with the evidence used. Exits non-zero if any check
fails, so it works as a gate.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
PKG = os.path.join(SRC, "cli_anything", "bcu")
CLA = os.path.join(SRC, "cli_anything")

results: list[tuple[str, bool, str]] = []


def check(section: str, name: str, ok: bool, evidence: str = "") -> None:
    results.append((f"{section}: {name}", bool(ok), evidence))


def exists(rel: str) -> str:
    return os.path.join(ROOT, rel)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ── 1. structure ──────────────────────────────────────────────────────
check("1-Structure", "src/ layout used", os.path.isdir(SRC))
check("1-Structure", "namespace sub-package exists", os.path.isdir(PKG))
check("1-Structure", "cli_anything/ has no __init__.py (PEP 420)",
      not os.path.exists(os.path.join(CLA, "__init__.py")))
check("1-Structure", "bcu/ has __init__.py", os.path.exists(os.path.join(PKG, "__init__.py")))
for sub in ("core", "utils", "tests"):
    check("1-Structure", f"{sub}/ present", os.path.isdir(os.path.join(PKG, sub)))
pyproject = read(exists("pyproject.toml"))
check("1-Structure", "pyproject declares an explicit package list",
      "packages = [" in pyproject and "cli_anything.bcu" in pyproject)

# ── 2. required files ─────────────────────────────────────────────────
required = {
    "README.md": "README.md",
    "LICENSE": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
    "pyproject.toml": "pyproject.toml",
    "docs/BCU.md (reconnaissance SOP)": "docs/BCU.md",
    "package README": "src/cli_anything/bcu/README.md",
    "bcu_cli.py": "src/cli_anything/bcu/bcu_cli.py",
    "core/model.py": "src/cli_anything/bcu/core/model.py",
    "core/parse.py": "src/cli_anything/bcu/core/parse.py",
    "core/listfile.py": "src/cli_anything/bcu/core/listfile.py",
    "core/index.py": "src/cli_anything/bcu/core/index.py",
    "core/select.py": "src/cli_anything/bcu/core/select.py",
    "core/plan.py": "src/cli_anything/bcu/core/plan.py",
    "core/report.py": "src/cli_anything/bcu/core/report.py",
    "utils/bcu_backend.py": "src/cli_anything/bcu/utils/bcu_backend.py",
    "skills/SKILL.md": "src/cli_anything/bcu/skills/SKILL.md",
    "tests/TEST.md": "src/cli_anything/bcu/tests/TEST.md",
    "tests/test_core.py": "src/cli_anything/bcu/tests/test_core.py",
    "tests/test_cli_bindings.py": "src/cli_anything/bcu/tests/test_cli_bindings.py",
    "tests/test_full_e2e.py": "src/cli_anything/bcu/tests/test_full_e2e.py",
    ".gitignore": ".gitignore",
    ".gitattributes": ".gitattributes",
}
for name, rel in required.items():
    check("2-Files", name, os.path.exists(exists(rel)), rel)

# ── 3. CLI standards ──────────────────────────────────────────────────
cli_src = read(exists("src/cli_anything/bcu/bcu_cli.py"))
check("3-CLI", "uses Click", "import click" in cli_src)
check("3-CLI", "command groups used", cli_src.count("@cli.group(") >= 1,
      f"{cli_src.count('@cli.group(')} group (query) + {cli_src.count('@cli.command(')} top-level commands")
check("3-CLI", "--json flag", '"--json"' in cli_src)
check("3-CLI", "--console override", '"--console"' in cli_src)
check("3-CLI", "handle_error decorator", "def handle_error(" in cli_src)
check("3-CLI", "REPL mode", 'def repl()' in cli_src)
check("3-CLI", "windows_expand_args disabled (app names contain spaces/wildcards)",
      "windows_expand_args=False" in cli_src)
check("3-CLI", "apply requires confirm",
      "requires --confirm" in cli_src or "confirmed" in cli_src)

# ── 4. core module standards ──────────────────────────────────────────
proj_ok = all(fn in read(exists(f"src/cli_anything/bcu/{rel}"))
              for rel, fn in (
                  ("core/model.py", "def from_bcu_json("),
                  ("core/parse.py", "def parse_list_json("),
                  ("core/listfile.py", "def build_bcul("),
                  ("core/plan.py", "def build_plan("),
                  ("core/select.py", "def select_apps("),
                  ("core/report.py", "def render("),
                  ("core/index.py", "def save("),
              ))
check("4-Core", "core modules expose their documented entry points", proj_ok)

docstring_ok, typing_ok, problems = True, True, []
for rel in ("core/model.py", "core/parse.py", "core/listfile.py", "core/index.py",
            "core/select.py", "core/plan.py", "core/report.py",
            "utils/bcu_backend.py"):
    src = read(exists(f"src/cli_anything/bcu/{rel}"))
    tree = ast.parse(src)
    if not ast.get_docstring(tree):
        docstring_ok = False
        problems.append(f"{rel}: no module docstring")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is None and not node.name.startswith("_"):
                typing_ok = False
                problems.append(f"{rel}:{node.lineno} {node.name} lacks a return annotation")
check("4-Core", "all core modules have docstrings", docstring_ok, "; ".join(problems[:3]) or "ok")
check("4-Core", "public functions are type-hinted", typing_ok, "; ".join(problems[:3]) or "ok")

# ── 5. test standards ─────────────────────────────────────────────────
test_md = read(exists("src/cli_anything/bcu/tests/TEST.md"))
check("5-Tests", "TEST.md has a plan (Part 1)", "## 1.1" in test_md)
check("5-Tests", "TEST.md has results (Part 2)", "## Part 2" in test_md
      and "_（跑完后追加）_" not in test_md)
e2e = read(exists("src/cli_anything/bcu/tests/test_full_e2e.py"))
check("5-Tests", "TestCLISubprocess present", "class TestCLISubprocess" in e2e)
check("5-Tests", "_resolve_cli used", '_resolve_cli("cli-anything-bcu")' in e2e)
check("5-Tests", "_resolve_cli supports FORCE_INSTALLED",
      "CLI_ANYTHING_FORCE_INSTALLED" in e2e)
check("5-Tests", "E2E states it never performs a real uninstall",
      "No real uninstall" in e2e or "no real uninstall" in e2e.lower())
check("5-Tests", "E2E proves a dry run changes nothing",
      "does_not_touch_the_system" in e2e)
check("5-Tests", "real fixtures are present",
      os.path.getsize(exists("src/cli_anything/bcu/tests/fixtures/list_591_apps.json")) > 100_000)
bindings = read(exists("src/cli_anything/bcu/tests/test_cli_bindings.py"))
check("5-Tests", "CLI binding regression suite exists", "CliRunner" in bindings)

# ── 6. documentation ──────────────────────────────────────────────────
readme = read(exists("README.md"))
check("6-Docs", "README installation", "## Install" in readme)
check("6-Docs", "README usage", "## Usage" in readme)
check("6-Docs", "README command reference", "## Command reference" in readme)
check("6-Docs", "README safety model", "## Safety model" in readme)
check("6-Docs", "README examples", readme.count("```bash") >= 4,
      f"{readme.count('```bash')} bash blocks")
sop = read(exists("docs/BCU.md"))
check("6-Docs", "SOP records measured facts", "实测" in sop or "measured" in sop.lower())
check("6-Docs", "SOP lists the three traps", sop.count("坑") >= 3,
      f"{sop.count('坑')} trap sections")
check("6-Docs", "third-party attribution present", os.path.exists(exists("THIRD_PARTY_NOTICES.md")))

# ── 7. packaging ──────────────────────────────────────────────────────
check("7-Packaging", "package name convention", 'name = "cli-anything-bcu"' in pyproject)
check("7-Packaging", "entry point declared",
      'cli-anything-bcu = "cli_anything.bcu.bcu_cli:main"' in pyproject)
check("7-Packaging", "dependencies declared", "dependencies = [" in pyproject)
check("7-Packaging", "requires-python >= 3.10", 'requires-python = ">=3.10"' in pyproject)
check("7-Packaging", "package-data covers docs and fixtures",
      '"tests/TEST.md"' in pyproject and '"tests/fixtures/*"' in pyproject)
check("7-Packaging", "no cli_anything/__init__.py",
      not os.path.exists(os.path.join(CLA, "__init__.py")))

# ── 8. code quality ───────────────────────────────────────────────────
syntax_ok, syntax_evidence = True, []
for dirpath, _dirs, files in os.walk(PKG):
    for name in files:
        if name.endswith(".py"):
            path = os.path.join(dirpath, name)
            try:
                ast.parse(read(path))
            except SyntaxError as exc:
                syntax_ok = False
                syntax_evidence.append(f"{name}: {exc}")
check("8-Quality", "no syntax errors", syntax_ok, "; ".join(syntax_evidence) or "all parse")

DRIVE_LITERAL = re.compile(r"^[A-Za-z]:\\")
bare_except, hardcoded, long_lines = [], [], []
for dirpath, _dirs, files in os.walk(PKG):
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(dirpath, name)
        rel = os.path.relpath(path, ROOT)
        src = read(path)
        is_test = os.sep + "tests" + os.sep in path
        for i, line in enumerate(src.splitlines(), 1):
            if re.match(r"except\s*:", line.strip()):
                bare_except.append(f"{rel}:{i}")
            if len(line) > 120:
                long_lines.append(f"{rel}:{i}({len(line)})")
        if is_test:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    body[0].value.value = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and DRIVE_LITERAL.match(node.value):
                hardcoded.append(f"{rel}:{node.lineno} {node.value!r}")
check("8-Quality", "no bare except", not bare_except, "; ".join(bare_except) or "none")
check("8-Quality", "no hardcoded paths in executable code", not hardcoded,
      "; ".join(hardcoded) or "no drive-letter literals outside docstrings/tests")
check("8-Quality", "no lines over 120 chars", not long_lines,
      "; ".join(long_lines[:5]) or "none")

# ── report ────────────────────────────────────────────────────────────
passed = sum(1 for _n, ok, _e in results if ok)
print("CLI Harness Validation Report")
print("Software: bcu (Bulk Crap Uninstaller)")
print(f"Path: {PKG}\n")
for name, ok, evidence in results:
    if not ok:
        print(f"  [FAIL] {name}  -- {evidence}")
if passed == len(results):
    print("  (all checks passed)")
print(f"\nOverall: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)} checks)")
sys.exit(0 if passed == len(results) else 1)
