#!/usr/bin/env python3
"""bcu-cli — query and manage Windows uninstalls through Bulk Crap Uninstaller.

Why a wrapper at all: ``BCU-console.exe`` is powerful but awkward to drive. It
needs administrator rights for *everything*, its ``list`` is a ~58-second
full-system scan, and ``uninstall`` accepts only a generated ``.bcul`` file and
reports on stderr. This CLI turns that into:

    scan  (admin, ~60 s, once)  ->  index  ->  query (no admin, instant)
    uninstall (admin): dry-run first, apply only when explicitly confirmed

Usage:
    bcu-cli info --json
    bcu-cli scan --json                     # elevated shell, ~60s
    bcu-cli query list --top 20
    bcu-cli query show "Google Chrome" --json
    bcu-cli query orphaned
    bcu-cli uninstall "AcmeArchiver"               # DRY RUN, changes nothing
    bcu-cli uninstall "AcmeArchiver" --apply --confirm
    bcu-cli report -o apps.csv

Environment:
    BCU_CONSOLE   Path to BCU-console.exe (overrides auto-discovery)
    BCU_CLI_HOME  State directory (default ~/.bcu-cli)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Optional

import click

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cli_anything.bcu import __version__  # noqa: E402
from cli_anything.bcu.core import index as index_mod      # noqa: E402
from cli_anything.bcu.core import listfile, parse, plan    # noqa: E402
from cli_anything.bcu.core import report as report_mod     # noqa: E402
from cli_anything.bcu.core import select                   # noqa: E402
from cli_anything.bcu.utils import bcu_backend as backend  # noqa: E402

HOME_ENV = "BCU_CLI_HOME"

_state: dict[str, Any] = {
    "json": False,
    "console": None,
    "index": None,
    "repl": False,
}


# ── environment ───────────────────────────────────────────────────────

def state_home() -> str:
    """Directory holding the scan index and config."""
    return os.environ.get(HOME_ENV) or os.path.join(
        os.path.expanduser("~"), ".bcu-cli"
    )


def index_path() -> str:
    """Path of the saved scan index."""
    return os.path.join(state_home(), "index.json")


def output(data: Any, message: str = "") -> None:
    """Emit a result as JSON or human-readable text."""
    if _state["json"]:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        if message:
            click.echo(message)
        _print_human(data)


def _print_human(data: Any, indent: int = 0) -> None:
    prefix = "  " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                click.echo(f"{prefix}{key}:")
                _print_human(value, indent + 1)
            elif isinstance(value, bool):
                click.echo(f"{prefix}{key}: {'true' if value else 'false'}")
            elif isinstance(value, int):
                click.echo(f"{prefix}{key}: {value:,}")
            else:
                click.echo(f"{prefix}{key}: {value}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                click.echo(prefix + "- " + ", ".join(f"{k}={v}" for k, v in item.items()))
            else:
                click.echo(f"{prefix}- {item}")
    elif data not in (None, ""):
        click.echo(f"{prefix}{data}")


def _fail(message: str, kind: str) -> None:
    if _state["json"]:
        click.echo(json.dumps({"error": message, "type": kind}, ensure_ascii=False))
    else:
        click.echo(f"Error: {message}", err=True)
    if not _state["repl"]:
        sys.exit(1)


def handle_error(func):
    """Turn known failures into clean exit-1 errors, never a traceback."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (backend.BCUNotFound, backend.BCUExecutionError) as exc:
            _fail(str(exc), type(exc).__name__)
        except (FileNotFoundError, ValueError, KeyError, RuntimeError,
                OverflowError, AttributeError, TypeError, OSError) as exc:
            _fail(str(exc), type(exc).__name__)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _apply_globals(use_json, console, index_file):
    if use_json:
        _state["json"] = True
    if console:
        _state["console"] = console
    if index_file:
        _state["index"] = index_file


def with_globals(func):
    """Let the global flags be written after the subcommand as well."""
    func = click.option("--json", "use_json", is_flag=True, default=None,
                        help="Machine-readable JSON output.")(func)
    func = click.option("--console", "console", type=click.Path(), default=None,
                        help="Path to BCU-console.exe.")(func)
    func = click.option("--index-file", "index_file", type=click.Path(), default=None,
                        help="Scan index to read (default <home>/index.json).")(func)

    def wrapper(*args, **kwargs):
        _apply_globals(kwargs.pop("use_json", None), kwargs.pop("console", None),
                       kwargs.pop("index_file", None))
        return func(*args, **kwargs)

    wrapper.__name__ = getattr(func, "__name__", "command")
    wrapper.__doc__ = getattr(func, "__doc__", None)
    wrapper.__click_params__ = list(getattr(func, "__click_params__", []))
    return wrapper


# ── helpers ───────────────────────────────────────────────────────────

def _load_index() -> index_mod.Index:
    return index_mod.Index.load(_state["index"] or index_path())


def _require_admin(why: str) -> None:
    """BCU-console declares requireAdministrator; fail with a usable message."""
    if not backend.is_admin():
        raise backend.BCUExecutionError(
            f"{why} needs an elevated shell.\n{backend.admin_requirement_message()}"
        )


def _render(apps, message: str, fmt: str | None = None, top: int | None = None) -> None:
    if _state["json"]:
        output([a.to_dict() for a in apps])
    else:
        click.echo(message)
        click.echo(report_mod.render(apps, fmt=fmt or "table", top=top).rstrip())


# ── main group ────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--console", "console", type=click.Path(), default=None,
              help="Path to BCU-console.exe (overrides discovery).")
@click.option("--index-file", "index_file", type=click.Path(), default=None,
              help="Scan index to read.")
@click.option("--version", "show_version", is_flag=True, help="Show version and exit.")
@click.pass_context
def cli(ctx, use_json, console, index_file, show_version):
    """bcu-cli — drive Bulk Crap Uninstaller from the command line."""
    _apply_globals(use_json, console, index_file)
    ctx.ensure_object(dict)
    if show_version:
        click.echo(f"bcu-cli {__version__}")
        return
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ── info ──────────────────────────────────────────────────────────────

@cli.command("info")
@with_globals
@handle_error
def info_cmd():
    """Report where BCU-console is, its version, and whether this shell can run it."""
    payload: dict[str, Any] = {
        "cli_version": __version__,
        "is_admin": backend.is_admin(),
        "state_home": state_home(),
        "index_path": index_path(),
        "index_exists": os.path.exists(_state["index"] or index_path()),
    }
    try:
        path, source = backend.discover(_state["console"])
        payload.update({"found": True, "console": path, "source": source})
        banner = ""
        if backend.is_admin():
            try:
                result = backend.run(["help"], console=path, timeout=60)
                banner = parse.extract_version(result["stdout"] + result["stderr"])
            except backend.BCUExecutionError:
                banner = ""
        payload["bcu_version"] = banner or "unknown"
    except backend.BCUNotFound as exc:
        payload.update({"found": False, "console": None, "error": str(exc)})

    if _state["json"]:
        output(payload)
    elif payload["found"]:
        admin = "yes" if payload["is_admin"] else "NO — scans will fail"
        click.echo(f"✓ BCU-console: {payload['console']} (found via {payload['source']})")
        click.echo(f"  version    : {payload['bcu_version']}")
        click.echo(f"  elevated   : {admin}")
        click.echo(f"  index      : {payload['index_path']}"
                   f"{'' if payload['index_exists'] else '  (not scanned yet)'}")
    else:
        output(payload, "✗ BCU-console not found.")
        click.echo(payload.get("error", ""), err=True)
        sys.exit(1)


# ── scan ──────────────────────────────────────────────────────────────

@cli.command("scan")
@click.option("--timeout", type=int, default=900, show_default=True,
              help="Seconds before the scan is abandoned (a full scan is ~60s).")
@click.option("--format", "fmt", type=click.Choice(["json", "xml"]), default="json",
              show_default=True, help="Format requested from BCU-console.")
@with_globals
@handle_error
def scan_cmd(timeout, fmt):
    """Run a full BCU scan and save the local index (needs an elevated shell)."""
    _require_admin("scanning")
    started = time.time()

    args = backend.build_list_args(fmt=fmt)
    result = backend.run(args, console=_state["console"], timeout=timeout)

    # Measure this rather than assume it: `list` is a full-system scan.
    elapsed_ms = result["elapsed_ms"]

    apps = parse.parse_list_json(result["stdout"])
    if not apps:
        raise backend.BCUExecutionError(
            "BCU returned no applications.\n"
            f"  exit code : {result['exit_code']}\n"
            f"  stdout    : {len(result['stdout']):,} chars\n"
            f"  stderr    : {result['stderr'][:400] or '(empty)'}"
        )

    resolved = result["argv"][0]
    idx = index_mod.Index.from_apps(
        apps,
        bcu_version=parse.extract_version(result["stdout"] + result["stderr"]),
        console_path=resolved,
    )
    path = idx.save(_state["index"] or index_path())

    payload = {**idx.summary(), "index_path": path, "elapsed_ms": elapsed_ms,
               "total_ms": int((time.time() - started) * 1000)}
    output(payload,
           f"✓ Indexed {idx.count:,} applications in {elapsed_ms / 1000:.1f}s\n"
           f"  index : {path}\n"
           f"  quiet-capable: {idx.quiet_capable_count:,} | "
           f"orphaned: {idx.orphaned_count:,}")


# ── query ─────────────────────────────────────────────────────────────

@cli.group()
def query():
    """Ask questions of the saved scan (no admin, no re-scan)."""


@query.command("summary")
@with_globals
@handle_error
def query_summary():
    """Overview of the saved scan, including what the numbers can and cannot mean.

    The trust block is not decoration: BCU's size field is a self-reported
    registry value (see docs/BCU-FIELDS.md §9), and its orphan flag means
    "no registry record", not "leftover entry". Reporting either without the
    caveat is how a wrong answer gets delivered.
    """
    from cli_anything.bcu.core import trust

    idx = _load_index()
    payload = {**idx.summary(), "trust": trust.summarize_for_report(idx.apps)}
    if _state["json"]:
        output(payload)
        return
    click.echo(f"{idx.count:,} applications indexed")
    click.echo(f"  uninstallable : {idx.uninstallable_count:,}")
    click.echo(f"  silent-capable: {idx.quiet_capable_count:,}")
    click.echo(f"  BCU size sum  : {idx.total_size_kb / 1024 / 1024:.1f} GB  "
               f"(self-reported, NOT measured)")
    t = payload["trust"]
    click.echo(f"  size coverage : {t['size_reliability']['coverage_pct']}% of entries "
               f"({t['size_reliability']['entries_without_size']} have no value)")
    if t["duplicate_locations"]:
        click.echo(f"  ⚠ {len(t['duplicate_locations'])} directories are claimed by "
                   f"more than one entry — totalling double counts them")
    click.echo(f"  deduplicated  : {t['deduplicated_total_kb'] / 1024 / 1024:.1f} GB "
               f"(still self-reported)")
    click.echo(f"  orphan flag   : {t['orphan_flag_count']} "
               f"— means 'no registry record', not 'leftover entry'")
    click.echo(f"  truly dead    : {t['truly_dead_count']} "
               f"(has a registry record BUT the files are gone)")


@query.command("list")
@click.option("--top", "-n", type=int, default=None, help="Show only the first N.")
@click.option("--sort", "sort_by", type=click.Choice(["size", "name"]), default="size",
              show_default=True)
@click.option("--orphaned", is_flag=True, help="Only entries whose files are gone.")
@click.option("--quiet-capable", is_flag=True, help="Only entries with a silent uninstaller.")
@click.option("--format", "fmt", type=click.Choice(["table", "csv", "json", "markdown"]),
              default=None)
@with_globals
@handle_error
def query_list(top, sort_by, orphaned, quiet_capable, fmt):
    """List indexed applications."""
    apps = _load_index().apps
    if orphaned:
        apps = [a for a in apps if a.is_orphaned]
    if quiet_capable:
        apps = [a for a in apps if a.is_quiet_capable]
    if sort_by == "size":
        apps = sorted(apps, key=lambda a: -a.estimated_size_kb)
    else:
        apps = sorted(apps, key=lambda a: a.display_name.lower())

    if _state["json"]:
        output([a.to_dict() for a in (apps[:top] if top else apps)])
    else:
        click.echo(report_mod.render(apps, fmt=fmt or "table", top=top).rstrip())


@query.command("show")
@click.argument("pattern")
@click.option("--json-detail", is_flag=True, help="Dump every known field.")
@with_globals
@handle_error
def query_show(pattern, json_detail):
    """Show one application in detail (fuzzy match)."""
    selection = select.select_apps(_load_index().apps, pattern)
    if not selection.matched:
        raise ValueError(selection.reason or f"no match for {pattern!r}")
    if selection.ambiguous:
        names = "\n  ".join(selection.names[:25])
        raise ValueError(
            f"{len(selection.matched)} applications match {pattern!r}; be more specific:\n"
            f"  {names}"
        )
    app = selection.matched[0]
    if _state["json"] or json_detail:
        output(app.to_dict())
        return
    click.echo(f"{app.display_name}")
    for label, value in (
        ("version", app.display_version),
        ("publisher", app.publisher),
        ("size", app.size_human),
        ("installed", app.install_date),
        ("location", app.install_location),
        ("uninstaller kind", app.uninstaller_kind),
        ("64-bit", app.is_64bit),
        ("can be uninstalled", app.is_uninstallable),
        ("can be uninstalled silently", app.is_quiet_capable),
        ("orphaned", app.is_orphaned),
        ("protected", app.is_protected),
        ("registry key", app.registry_key_name),
        ("uninstall command", app.uninstall_string),
        ("quiet command", app.quiet_uninstall_string),
    ):
        if value not in ("", None):
            click.echo(f"  {label:<30} {value}")


@query.command("orphaned")
@with_globals
@handle_error
def query_orphaned():
    """Entries whose files are gone but whose registry record remains."""
    apps = [a for a in _load_index().apps if a.is_orphaned]
    _render(apps, f"{len(apps)} orphaned entr{'y' if len(apps) == 1 else 'ies'}")


@query.command("dead")
@with_globals
@handle_error
def query_dead():
    """Genuinely dead entries: a registry record exists but the files are gone.

    This is the correct definition, and it is NOT BCU's `IsOrphaned` flag.
    `IsOrphaned` marks portable software found by directory scan — those have
    files and no registry record, the exact opposite. Removing them frees
    nothing and would delete live directories.
    """
    from cli_anything.bcu.core import trust

    items = trust.truly_dead_entries(_load_index().apps)
    _render(items, f"{len(items)} dead entr{'y' if len(items) == 1 else 'ies'} "
                   f"(registry record present, files gone)")


@query.command("duplicates")
@with_globals
@handle_error
def query_duplicates():
    """Directories claimed by more than one registry entry.

    Totalling sizes without this double counts whatever is shared; one machine
    reported 88 GB for a 44 GB directory because two entries named it.
    """
    from cli_anything.bcu.core import trust

    idx = _load_index()
    dupes = trust.duplicate_locations(idx.apps)
    payload = {
        "count": len(dupes),
        "directories": {loc: names for loc, names in dupes.items()},
        "note": "each shared directory is counted once per entry when summing sizes",
    }
    if _state["json"]:
        output(payload)
        return
    click.echo(f"{len(dupes)} directories claimed by multiple entries")
    for loc, names in list(dupes.items())[:25]:
        click.echo(f"  {loc}")
        for n in names:
            click.echo(f"      {n}")

@query.command("top")
@click.option("--count", "-n", type=int, default=20, show_default=True)
@with_globals
@handle_error
def query_top(count):
    """Largest indexed applications."""
    apps = select.top_by_size(_load_index().apps, limit=count)
    _render(apps, f"Top {len(apps)} by estimated size")


# ── uninstall ─────────────────────────────────────────────────────────

@cli.command("uninstall")
@click.argument("pattern")
# `apply` is a Python builtin, so the parameter is named apply_ — it must be
# named explicitly here or Click passes `apply=` and binding fails at runtime.
@click.option("--apply", "apply_", is_flag=True,
              help="Actually uninstall. Without this it is a DRY RUN.")
@click.option("--confirm", is_flag=True,
              help="Acknowledge that --apply is irreversible.")
@click.option("--unattended", is_flag=True,
              help="Pass /U to BCU (no prompts). Requires --apply --confirm.")
@click.option("--quiet", is_flag=True, help="Pass /Q: prefer silent uninstallers.")
@click.option("--junk", "junk_level", type=click.Choice(backend.JUNK_LEVELS),
              default=None, help="Also clean leftovers at this confidence level.")
@click.option("--first", "first_only", is_flag=True,
              help="If several match, take the first instead of refusing.")
@click.option("--bcul", "bcul_path", type=click.Path(), default=None,
              help="Where to write the generated .bcul list.")
@click.option("--timeout", type=int, default=900, show_default=True)
@with_globals
@handle_error
def uninstall_cmd(pattern, apply_, confirm, unattended, quiet, junk_level,
                  first_only, bcul_path, timeout):
    """Uninstall an application by name. DRY RUN unless --apply --confirm."""
    _require_admin("uninstalling")
    idx = _load_index()
    selection = select.select_apps(idx.apps, pattern, first_only=first_only)

    target = bcul_path or os.path.join(state_home(), "uninstall.bcul")
    mode = plan.MODE_APPLY if apply_ else plan.MODE_DRY_RUN
    built = plan.build_plan(
        selection, mode=mode, quiet=quiet, unattended=unattended,
        confirmed=confirm, junk_level=junk_level, bcul_path=target,
    )

    if built.refused:
        raise ValueError(built.reason)

    listfile.write_bcul(
        [listfile.FilterSpec(pattern=app.display_name) for app in selection.matched],
        target,
    )

    result = backend.run(
        backend.build_uninstall_args(
            target, dry_run=(mode == plan.MODE_DRY_RUN), quiet=quiet,
            unattended=(unattended and mode == plan.MODE_APPLY),
            junk_level=junk_level,
        ),
        console=_state["console"], timeout=timeout,
    )
    # /F=json is ignored on `uninstall`, so the report is on stderr.
    outcome = parse.parse_dry_run_stderr(result["stderr"] or result["stdout"])
    payload = {
        **built.to_dict(),
        "bcul_path": target,
        "exit_code": result["exit_code"],
        "elapsed_ms": result["elapsed_ms"],
        "bcu": outcome.to_dict(),
    }

    if result["exit_code"] not in (0, 1):
        raise backend.BCUExecutionError(
            f"BCU-console exited {result['exit_code']}\n{result['stderr'][:800]}"
        )
    if not outcome.matched and mode == plan.MODE_DRY_RUN:
        raise backend.BCUExecutionError(
            f"the dry run matched nothing (BCU exit {result['exit_code']}).\n"
            f"  pattern : {pattern!r}\n"
            f"  list    : {target}\n"
            f"  stderr  : {result['stderr'][:400]}"
        )

    if _state["json"]:
        output(payload)
    else:
        verb = "Uninstalled" if mode == plan.MODE_APPLY else "WOULD uninstall (dry run)"
        click.echo(f"{verb}: {', '.join(built.selection.names)}")
        click.echo(f"  matched      : {outcome.matched_count}")
        click.echo(f"  silent-able  : "
                   f"{', '.join(built.quiet_capable) or '(none — will show prompts)'}")
        click.echo(f"  list file    : {target}")
        if mode == plan.MODE_DRY_RUN:
            click.echo("  nothing was changed; re-run with --apply --confirm to proceed")


# ── report / export ───────────────────────────────────────────────────

@cli.command("report")
@click.option("--output", "-o", "destination", type=click.Path(), required=True)
@click.option("--format", "fmt",
              type=click.Choice(["table", "csv", "json", "markdown", "html"]), default=None)
@click.option("--top", "-n", type=int, default=None)
@with_globals
@handle_error
def report_cmd(destination, fmt, top):
    """Write the indexed applications to a file."""
    apps = sorted(_load_index().apps, key=lambda a: -a.estimated_size_kb)
    result = report_mod.write(apps, destination, fmt=fmt, top=top)
    output(result, f"✓ {result['size']:,} bytes → {result['path']}")


@cli.command("export")
@click.option("--output", "-o", "destination", type=click.Path(), required=True)
@click.option("--format", "fmt", type=click.Choice(["json", "xml"]), default="json")
@click.option("--timeout", type=int, default=900, show_default=True)
@with_globals
@handle_error
def export_cmd(destination, fmt, timeout):
    """Use BCU's own export (needs an elevated shell)."""
    _require_admin("exporting")
    args = backend.build_export_args(destination, fmt=fmt)
    result = backend.run(args, console=_state["console"], timeout=timeout)
    if result["exit_code"] != 0 or not os.path.exists(destination):
        raise backend.BCUExecutionError(
            f"export failed (exit {result['exit_code']}):\n{result['stderr'][:600]}"
        )
    output({"path": destination, "size": os.path.getsize(destination),
            "format": fmt, "elapsed_ms": result["elapsed_ms"]},
           f"✓ {os.path.getsize(destination):,} bytes → {destination}")


@cli.command("list-file")
@click.argument("pattern", nargs=-1, required=True)
@click.option("--output", "-o", "destination", type=click.Path(), required=True)
@click.option("--exclude", is_flag=True, help="Make it an exclude list instead.")
@with_globals
@handle_error
def list_file_cmd(pattern, destination, exclude):
    """Generate a .bcul uninstall list without running anything."""
    specs = [listfile.FilterSpec(pattern=p, exclude=exclude) for p in pattern]
    listfile.write_bcul(specs, destination)
    text = open(destination, encoding="utf-8").read()
    output({"path": destination, "filters": len(specs), "size": len(text),
            "preview": text},
           f"✓ {len(specs)} filter(s) → {destination}")


# ── REPL ──────────────────────────────────────────────────────────────

@cli.command("repl", hidden=True)
def repl():
    """Interactive REPL."""
    _state["repl"] = True
    from cli_anything.bcu.utils.repl_skin import ReplSkin

    skin = ReplSkin("bcu", version=__version__)
    skin.print_banner()
    commands = {
        "info": "Locate BCU-console, show version and elevation state",
        "scan": "Full scan → index (elevated shell, ~60s)",
        "query summary": "Overview of the saved scan",
        "query list -n 20": "List indexed applications",
        'query show "<name>"': "Detail for one application",
        "query orphaned": "Registry entries whose files are gone",
        "query top -n 20": "Largest applications",
        'uninstall "<name>"': "DRY RUN: show what would be uninstalled",
        'uninstall "<name>" --apply --confirm': "Actually uninstall (irreversible)",
        "report -o apps.csv": "Write a report",
        "export -o apps.json": "Use BCU's own export (elevated)",
        "list-file <name> -o x.bcul": "Generate a .bcul list only",
        "help": "Show this help",
        "quit / exit": "Leave the REPL",
    }
    try:
        prompt_session = skin.create_prompt_session()
    except Exception:
        prompt_session = None

    while True:
        try:
            line = skin.get_input(prompt_session, project_name="bcu")
        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break
        if not line:
            continue
        stripped = line.strip()
        if stripped in ("quit", "exit", "q"):
            skin.print_goodbye()
            break
        if stripped == "help":
            skin.help(commands)
            continue
        try:
            cli.main(stripped.split(), standalone_mode=False)
        except SystemExit:
            pass
        except click.ClickException as exc:
            skin.error(exc.format_message())
        except Exception as exc:  # keep the REPL alive
            skin.error(f"{type(exc).__name__}: {exc}")


def main() -> None:
    """Console-script entry point.

    ``windows_expand_args=False`` matters here: application names contain
    spaces and wildcards, and Click would otherwise glob them against the
    working directory before the command ever sees them.
    """
    try:
        cli.main(windows_expand_args=False, standalone_mode=False)
    except click.exceptions.Abort:
        click.echo("Aborted.", err=True)
        sys.exit(1)
    except click.ClickException as exc:
        wants_json = _state["json"] or "--json" in sys.argv[1:]
        if wants_json:
            click.echo(json.dumps(
                {"error": exc.format_message(), "type": type(exc).__name__},
                ensure_ascii=False))
        else:
            exc.show()
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
