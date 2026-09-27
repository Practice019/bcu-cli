"""End-to-end tests — these drive the **real** BCU-console.exe.

No graceful degradation (HARNESS.md): if BCU-console is missing these fail rather
than skip, because a wrapper whose backend cannot be tested is worth nothing.

Two things are deliberately NOT done here:

* **No real uninstall.** Removing a real application is destructive,
  environment-specific and unreproducible in CI. The safety logic is unit-tested
  and the dry-run path is exercised for real; an actual apply is a manual,
  documented step (see TEST.md §1.3).
* **No elevation from inside the test.** BCU-console declares
  requireAdministrator, so the whole suite must be started from an elevated
  shell. If it is not elevated, the tests fail with that as the reason.

Discovered console is reported at import so a failure says which binary was used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from cli_anything.bcu.core import index as index_mod     # noqa: E402
from cli_anything.bcu.core import listfile, parse, plan   # noqa: E402
from cli_anything.bcu.core import report as report_mod    # noqa: E402
from cli_anything.bcu.core import select                  # noqa: E402
from cli_anything.bcu.utils import bcu_backend as backend  # noqa: E402

STATE_ENV = "BCU_CLI_HOME"


# ── helpers ───────────────────────────────────────────────────────────

def _resolve_cli(name: str) -> list[str]:
    """Resolve the installed CLI; falls back to ``python -m`` for dev.

    Set ``CLI_ANYTHING_FORCE_INSTALLED=1`` to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = name.replace("cli-anything-", "cli_anything.") + "." + name.split("-")[-1] + "_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


@pytest.fixture(scope="module", autouse=True)
def _isolated_state_home(tmp_path_factory):
    """Keep the developer's real state directory out of the test run."""
    home = tmp_path_factory.mktemp("bcu_state")
    previous = os.environ.get(STATE_ENV)
    os.environ[STATE_ENV] = str(home)
    yield str(home)
    if previous is None:
        os.environ.pop(STATE_ENV, None)
    else:
        os.environ[STATE_ENV] = previous


@pytest.fixture(scope="module")
def console() -> str:
    """The real BCU-console.exe."""
    path, source = backend.discover()
    print(f"\n  BCU-console: {path}  (found via {source})")
    return path


@pytest.fixture(scope="module")
def elevated() -> bool:
    state = backend.is_admin()
    print(f"\n  elevated shell: {state}")
    return state


@pytest.fixture(scope="module")
def scan(console, elevated):
    """One real scan, shared across the module (it takes ~60 s)."""
    if not elevated:
        pytest.fail(
            "these E2E tests must run from an elevated shell: BCU-console declares "
            "requireAdministrator. " + backend.admin_requirement_message()
        )
    started = time.time()
    result = backend.run(backend.build_list_args(fmt="json"), console=console, timeout=900)
    elapsed = time.time() - started
    apps = parse.parse_list_json(result["stdout"])
    print(f"\n  scan: {len(apps)} apps in {elapsed:.1f}s "
          f"(exit {result['exit_code']}, {len(result['stdout']):,} chars)")
    return {"result": result, "apps": apps, "elapsed": elapsed}


# ── real backend ──────────────────────────────────────────────────────

class TestRealBackend:
    """Uses the actual binary; each of these would catch a BCU upgrade."""

    def test_console_exists_and_is_named_right(self, console):
        assert os.path.exists(console)
        assert os.path.basename(console).lower() == "bcu-console.exe"

    def test_help_exits_zero(self, console, elevated):
        if not elevated:
            pytest.fail("needs an elevated shell (BCU-console requires admin)")
        result = backend.run(["help"], console=console, timeout=120)
        assert result["exit_code"] == 0
        assert "BCU-console" in result["stdout"] + result["stderr"]

    def test_version_is_parseable_from_the_banner(self, console, elevated):
        if not elevated:
            pytest.fail("needs an elevated shell")
        result = backend.run(["help"], console=console, timeout=120)
        version = parse.extract_version(result["stdout"] + result["stderr"])
        print(f"\n  BCU-console version: {version!r}")
        assert version, "could not read the version out of BCU's banner"
        assert version.split(".")[0].isdigit()

    def test_list_json_parses_and_covers_the_machine(self, scan):
        """B3: a real scan must yield a substantial, fully-mapped app set."""
        apps = scan["apps"]
        assert len(apps) > 50, f"only {len(apps)} apps found — suspicious"
        assert all(a.display_name for a in apps)
        assert sum(1 for a in apps if a.is_uninstallable) > 0

    def test_every_field_of_a_real_entry_maps(self, scan):
        """No real entry may lose its DisplayName or silently become blank."""
        losses = [a for a in scan["apps"] if not a.display_name.strip()]
        assert losses == []
        sample = scan["apps"][0]
        for attr in ("display_name", "estimated_size_kb", "is_64bit",
                     "uninstaller_kind", "is_protected"):
            assert hasattr(sample, attr)

    def test_scan_is_a_full_system_pass_not_an_empty_one(self, scan):
        assert scan["result"]["exit_code"] == 0
        assert len(scan["apps"]) > 50

    def test_plain_list_decodes_as_utf16(self, console, elevated):
        """B3: without /F the console output is UTF-16LE, not UTF-8."""
        if not elevated:
            pytest.fail("needs an elevated shell")
        result = backend.run(backend.build_list_args(), console=console, timeout=900)
        text = result["stdout"]
        assert "BCU-console" in text or "Display Name" in text
        assert "\x00" not in text, "decode left NUL bytes behind"

    def test_dry_run_matches_exactly_one_app(self, console, scan, tmp_path, elevated):
        """B4 + B6: a list selecting one app must dry-run green."""
        if not elevated:
            pytest.fail("needs an elevated shell")
        # pick a real, non-protected, uninstallable app with an ASCII name
        target = next(
            (a for a in scan["apps"]
             if a.is_uninstallable and not a.is_protected and a.display_name.isascii()),
            None,
        )
        assert target is not None, "no suitable app to test with"
        bcul = str(tmp_path / "one.bcul")
        listfile.write_bcul([listfile.FilterSpec(pattern=target.display_name)], bcul)

        result = backend.run(
            backend.build_uninstall_args(bcul, dry_run=True), console=console, timeout=900
        )
        outcome = parse.parse_dry_run_stderr(result["stderr"] or result["stdout"])
        print(f"\n  dry-run target: {target.display_name!r}")
        print(f"  matched={outcome.matched_count} finished={outcome.finished} "
              f"failed={outcome.failed} dry={outcome.was_dry_run}")

        assert outcome.matched_count >= 1, (
            f"dry run matched nothing for {target.display_name!r}; "
            f"stderr was: {result['stderr'][:300]}"
        )
        assert outcome.was_dry_run is True
        assert outcome.failed == 0
        assert "contains no" not in result["stderr"].lower()

    def test_dry_run_with_no_match_exits_one(self, console, tmp_path, elevated):
        """B6: BCU documents exit 1 when a dry run matches nothing."""
        if not elevated:
            pytest.fail("needs an elevated shell")
        bcul = str(tmp_path / "none.bcul")
        listfile.write_bcul(
            [listfile.FilterSpec(pattern="ZZZ_no_such_application_ZZZ")], bcul
        )
        result = backend.run(
            backend.build_uninstall_args(bcul, dry_run=True), console=console, timeout=900
        )
        outcome = parse.parse_dry_run_stderr(result["stderr"] or result["stdout"])
        print(f"\n  no-match dry run: exit={result['exit_code']} "
              f"matched={outcome.matched_count}")
        assert outcome.matched_count == 0
        assert result["exit_code"] == 1

    def test_dry_run_does_not_touch_the_system(self, console, scan, tmp_path, elevated):
        """The whole point of /N: prove the target's install dir is unchanged."""
        if not elevated:
            pytest.fail("needs an elevated shell")
        target = next(
            (a for a in scan["apps"]
             if a.is_uninstallable and not a.is_protected and a.install_location
             and os.path.isdir(a.install_location) and a.display_name.isascii()),
            None,
        )
        if target is None:
            pytest.skip("no app with a readable install location to compare")

        before = _tree_fingerprint(target.install_location)
        bcul = str(tmp_path / "safety.bcul")
        listfile.write_bcul([listfile.FilterSpec(pattern=target.display_name)], bcul)
        backend.run(backend.build_uninstall_args(bcul, dry_run=True),
                    console=console, timeout=900)
        after = _tree_fingerprint(target.install_location)

        print(f"\n  safety check on {target.display_name!r}: "
              f"{before['files']} files before, {after['files']} after")
        assert before == after, "the dry run modified the target's install directory"

    def test_export_produces_a_parseable_file(self, console, tmp_path, elevated):
        if not elevated:
            pytest.fail("needs an elevated shell")
        out = str(tmp_path / "export.json")
        result = backend.run(backend.build_export_args(out, fmt="json"),
                             console=console, timeout=900)
        assert result["exit_code"] == 0, result["stderr"][:400]
        assert os.path.exists(out)
        text = open(out, encoding="utf-8", errors="replace").read()
        data = json.loads(text)
        assert isinstance(data, list) and len(data) > 50


def _tree_fingerprint(path: str) -> dict:
    """(name, size) pairs under *path* — cheap, and enough to see deletion."""
    entries = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            full = os.path.join(root, name)
            try:
                entries.append((os.path.relpath(full, path), os.path.getsize(full)))
            except OSError:
                entries.append((os.path.relpath(full, path), -1))
    entries.sort()
    return {"files": len(entries), "digest": hash(tuple(entries))}


# ── index workflow ────────────────────────────────────────────────────

class TestIndexWorkflow:

    def test_scan_save_reload_matches(self, scan, tmp_path):
        idx = index_mod.Index.from_apps(
            scan["apps"], bcu_version="6.3.0.0", console_path="x")
        path = str(tmp_path / "idx.json")
        idx.save(path)
        again = index_mod.Index.load(path)
        assert again.count == idx.count
        assert again.apps[0].display_name == idx.apps[0].display_name

    def test_query_does_not_invoke_bcu(self, scan, tmp_path):
        """The index exists precisely so queries are fast and unprivileged."""
        idx = index_mod.Index.from_apps(scan["apps"], bcu_version="6.3.0.0",
                                        console_path="x")
        path = str(tmp_path / "idx.json")
        idx.save(path)

        started = time.time()
        reloaded = index_mod.Index.load(path)
        selection = select.select_apps(reloaded.apps, reloaded.apps[0].display_name)
        report_mod.render(selection.matched, fmt="table")
        elapsed = time.time() - started
        print(f"\n  index query took {elapsed * 1000:.0f} ms")
        assert len(selection.matched) >= 1
        assert elapsed < 5, "a query should not take anywhere near a scan's duration"

    def test_report_round_trips_from_the_real_index(self, scan, tmp_path):
        path = str(tmp_path / "apps.csv")
        result = report_mod.write(scan["apps"], path, fmt="csv", top=10)
        assert result["size"] > 0
        lines = open(path, encoding="utf-8").read().strip().splitlines()
        assert len(lines) == 11  # header + 10


# ── CLI as a subprocess ───────────────────────────────────────────────

class TestCLISubprocess:
    """Drive the CLI the way a user or agent would — installed, from any cwd."""

    CLI_BASE = _resolve_cli("cli-anything-bcu")

    @pytest.fixture(scope="class")
    def env(self, tmp_path_factory):
        home = tmp_path_factory.mktemp("bcu_cli_home")
        merged = os.environ.copy()
        merged[STATE_ENV] = str(home)
        merged["PYTHONIOENCODING"] = "utf-8"
        return merged

    def _run(self, args, env, check=True):
        # No cwd on purpose: the installed command must work from anywhere.
        return subprocess.run(
            self.CLI_BASE + args, capture_output=True, text=True,
            encoding="utf-8", env=env, check=check,
        )

    def test_help_lists_the_command_groups(self, env):
        result = self._run(["--help"], env)
        assert result.returncode == 0
        for group in ("scan", "query", "uninstall", "report", "info"):
            assert group in result.stdout, group

    def test_version(self, env):
        result = self._run(["--version"], env)
        assert result.returncode == 0
        assert "bcu-cli" in result.stdout

    def test_info_reports_discovery_and_elevation(self, env):
        result = self._run(["--json", "info"], env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "found" in payload
        assert "is_admin" in payload
        assert "index_path" in payload

    def test_global_flag_after_subcommand(self, env):
        """Regression class: `info --json` must mean the same as `--json info`."""
        before = self._run(["--json", "info"], env)
        after = self._run(["info", "--json"], env)
        assert before.returncode == 0 and after.returncode == 0
        assert json.loads(before.stdout)["found"] == json.loads(after.stdout)["found"]

    def test_query_without_index_fails_with_a_useful_message(self, env):
        result = self._run(["--json", "query", "summary"], env, check=False)
        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert "scan" in payload["error"].lower()

    def test_list_file_generates_bcul_without_running_anything(self, env, tmp_path):
        out = str(tmp_path / "made.bcul")
        result = self._run(["--json", "list-file", "Google Chrome", "-o", out], env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["filters"] == 1
        text = open(out, encoding="utf-8").read()
        assert "<UninstallList" in text and "Google Chrome" in text

    def test_uninstall_without_index_fails_cleanly(self, env):
        result = self._run(["--json", "uninstall", "Anything"], env, check=False)
        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["type"] in ("FileNotFoundError", "BCUExecutionError")

    def test_apply_without_confirm_is_refused_and_runs_nothing(self, env, tmp_path, scan):
        """The safety contract, asserted strictly.

        History: this test originally accepted "any non-zero exit". That was too
        weak, and it hid a real defect -- `--apply` without `--confirm` actually
        executed an uninstall (BCU failed with exit 13 and nothing was removed,
        but the intent was wrong). The assertions below are deliberately harsh:

          * the wrapper must REFUSE before invoking BCU at all,
          * the error must say so,
          * --apply --confirm must get past the refusal (proving the gate is a
            gate, not a wall).
        """
        idx = index_mod.Index.from_apps(scan["apps"], bcu_version="6.3.0.0",
                                       console_path="x")
        idx.save(os.path.join(env[STATE_ENV], "index.json"))
        target = next(a for a in scan["apps"]
                      if a.is_uninstallable and a.display_name.isascii())

        result = self._run(
            ["--json", "uninstall", target.display_name, "--apply"], env, check=False
        )
        assert result.returncode != 0, (
            "`--apply` without `--confirm` must not succeed"
        )
        payload = json.loads(result.stdout)
        message = payload.get("error", "").lower()
        assert "confirm" in message, (
            f"the refusal must mention --confirm, got: {payload!r}"
        )
        # A refusal must mean BCU never ran: an argv list is only populated once
        # the plan is accepted.
        assert not payload.get("argv"), (
            f"BCU must not have been invoked for a refused plan: {payload!r}"
        )

    def test_apply_with_confirm_passes_the_gate(self, env, tmp_path, scan):
        """Positive control: the safety gate must not be a wall.

        This still does not uninstall anything -- it points BCU at a list whose
        target is chosen and then immediately dry-run, so what is asserted is
        that the refusal in the previous test is specifically about --confirm.
        """
        idx = index_mod.Index.from_apps(scan["apps"], bcu_version="6.3.0.0",
                                       console_path="x")
        idx.save(os.path.join(env[STATE_ENV], "index.json"))
        # an app BCU reports as NOT uninstallable: the planner refuses for a
        # different, checkable reason, without ever offering to remove anything
        not_removable = next((a for a in scan["apps"] if not a.is_uninstallable), None)
        if not_removable is None:
            pytest.skip("every app on this machine reports a usable uninstaller")
        result = self._run(
            ["--json", "uninstall", not_removable.display_name, "--apply", "--confirm"],
            env, check=False,
        )
        payload = json.loads(result.stdout)
        assert result.returncode != 0
        assert "no selected application reports a usable uninstall command" in \
            payload.get("error", ""), payload
