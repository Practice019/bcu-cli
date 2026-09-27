"""Locate and drive ``BCU-console.exe``.

Measured constraints (docs/BCU.md §1-§3) that shape this module:

* ``BCU-console.exe`` **ships inside the official release zip** — users do not
  have to build it. So discovery covers "already installed" *and* "unpacked from
  a downloaded release".
* It carries ``<requestedExecutionLevel level="requireAdministrator">``, so
  **every** invocation needs an elevated shell. This module reports that state
  and refuses with an actionable message; it never tries to elevate itself
  (silent self-elevation is how a tool ends up running with rights the caller
  did not intend).
* ``uninstall`` reports on **stderr** even when ``/F=json`` is passed, so the
  caller must read stderr as well as stdout.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from typing import Any, Iterator, Sequence

__all__ = [
    "BCUNotFound",
    "BCUExecutionError",
    "ENV_VAR",
    "RELEASE_API",
    "DEFAULT_SEARCH_PATHS",
    "JUNK_LEVELS",
    "find_console",
    "discover",
    "iter_candidates",
    "is_admin",
    "admin_requirement_message",
    "run",
    "build_list_args",
    "build_export_args",
    "build_uninstall_args",
]

#: Environment override, checked first.
ENV_VAR = "BCU_CONSOLE"

#: Where the official releases are published (used for the download hint).
RELEASE_API = "https://api.github.com/repos/BCUninstaller/Bulk-Crap-Uninstaller/releases/latest"

#: Extra locations probed after PATH. Empty by default: a machine-specific
#: literal path in the source is a bug, not a feature.
DEFAULT_SEARCH_PATHS: tuple[str, ...] = ()

#: Valid ``/J=`` levels, from BCU's own help text.
JUNK_LEVELS: tuple[str, ...] = ("VeryGood", "Good", "Questionable", "Bad", "Unknown")

#: Executable names to look for.
EXE_NAMES: tuple[str, ...] = ("BCU-console.exe", "BCU-console")

_FORMATS: tuple[str, ...] = ("json", "xml")


class BCUNotFound(RuntimeError):
    """``BCU-console.exe`` could not be located."""


class BCUExecutionError(RuntimeError):
    """BCU ran but the result was unusable."""


# ── discovery ─────────────────────────────────────────────────────────

def _path_candidates() -> list[str]:
    found: list[str] = []
    for name in EXE_NAMES:
        located = shutil.which(name)
        if located:
            found.append(located)
    return found


def _env_candidates() -> list[str]:
    """Install locations derived from the environment, never hardcoded."""
    out: list[str] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "ProgramData"):
        base = os.environ.get(variable)
        if not base:
            continue
        if len(base) == 2 and base[1] == ":":       # bare drive -> root it
            base += os.sep
        for sub in ("BCUninstaller", r"Bulk Crap Uninstaller", r"Programs\BCUninstaller"):
            out.append(os.path.join(base, sub, "BCU-console.exe"))
    return out


def _registry_candidates() -> list[str]:
    """Locations from BCU's own uninstall record, plus its App Paths entry."""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return []
    found: list[str] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            name = winreg.EnumKey(key, index)
                        except OSError:
                            continue
                        try:
                            with winreg.OpenKey(key, name) as entry:
                                try:
                                    display = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                                except OSError:
                                    continue
                                if "uninstaller" not in display.lower() and \
                                   "bcu" not in display.lower():
                                    continue
                                for value_name in ("InstallLocation", "DisplayIcon"):
                                    try:
                                        raw = str(winreg.QueryValueEx(entry, value_name)[0])
                                    except OSError:
                                        continue
                                    raw = raw.strip().strip('"')
                                    if raw.lower().endswith(".exe"):
                                        found.append(
                                            os.path.join(os.path.dirname(raw), "BCU-console.exe")
                                        )
                                    elif raw:
                                        found.append(os.path.join(raw, "BCU-console.exe"))
                        except OSError:
                            continue
            except OSError:
                continue
    return found


def iter_candidates(explicit: str | None = None) -> Iterator[tuple[str, str]]:
    """Yield ``(path, source)`` in priority order."""
    if explicit:
        yield explicit, "--console"
    from_env = os.environ.get(ENV_VAR)
    if from_env:
        yield from_env, f"${ENV_VAR}"
    for path in _path_candidates():
        yield path, "PATH"
    for path in _registry_candidates():
        yield path, "registry"
    for path in _env_candidates():
        yield path, "program-files"
    for path in DEFAULT_SEARCH_PATHS:
        yield path, "search-paths"


def discover(explicit: str | None = None) -> tuple[str, str]:
    """Return ``(path, how_it_was_found)``.

    Pure: reads the environment and the registry, writes nothing.

    Raises:
        BCUNotFound: with an actionable message.
    """
    if explicit and not os.path.exists(explicit):
        raise BCUNotFound(
            f"BCU-console.exe not found at the path given: {explicit}\n"
            "Point --console at the real file, or unset it to auto-detect."
        )
    for path, source in iter_candidates(explicit):
        if path and os.path.exists(path):
            return path, source
    raise BCUNotFound(
        "BCU-console.exe not found.\n"
        "  BCU-console ships inside the official Bulk Crap Uninstaller release:\n"
        f"    release API : {RELEASE_API}\n"
        "    1. download the ..._net8.0-windows*.zip asset and unpack it\n"
        "    2. or install BCU via winget: winget install Klocman.BulkCrapUninstaller\n"
        f"    3. or set {ENV_VAR}=<path to BCU-console.exe>, or pass --console <path>"
    )


def find_console(explicit: str | None = None) -> str:
    """Path to ``BCU-console.exe`` (see :func:`discover`)."""
    return discover(explicit)[0]


# ── elevation ─────────────────────────────────────────────────────────

def is_admin() -> bool:
    """True when this process can run BCU-console at all."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # pragma: no cover - platform dependent
        return False


def admin_requirement_message() -> str:
    """Why an elevated shell is needed and what to do about it."""
    return (
        "BCU-console.exe declares requireAdministrator, so it cannot be launched "
        "from this shell (the OS refuses with 'requested operation requires "
        "elevation').\n"
        "Run this command from an elevated terminal, or elevate a dedicated "
        "PowerShell and point it at the same arguments. The wrapper will not "
        "elevate itself silently."
    )


# ── argument builders (pure) ──────────────────────────────────────────

def _flag(name: str, value: str = "") -> str:
    return f"/{name}{value}"


def build_list_args(*, fmt: str | None = None, quiet: bool = False,
                    unattended: bool = False, verbose: bool = False) -> list[str]:
    """argv for ``list``.

    Raises:
        ValueError: *fmt* is neither ``None``, ``json`` nor ``xml``.
    """
    if fmt is not None and fmt not in _FORMATS:
        raise ValueError(f"format must be one of {', '.join(_FORMATS)}; got {fmt!r}")
    args = ["list"]
    if quiet:
        args.append(_flag("Q"))
    if unattended:
        args.append(_flag("U"))
    if verbose:
        args.append(_flag("V"))
    if fmt is not None:
        args.append(_flag("F", f"={fmt}"))
    return args


def build_export_args(path: str, *, fmt: str | None = None, quiet: bool = False,
                      unattended: bool = False, verbose: bool = False) -> list[str]:
    """argv for ``export``."""
    if fmt is not None and fmt not in _FORMATS:
        raise ValueError(f"format must be one of {', '.join(_FORMATS)}; got {fmt!r}")
    if not str(path).strip():
        raise ValueError("export needs a destination filename")
    args = ["export", path]
    if quiet:
        args.append(_flag("Q"))
    if unattended:
        args.append(_flag("U"))
    if verbose:
        args.append(_flag("V"))
    if fmt is not None:
        args.append(_flag("F", f"={fmt}"))
    return args


def build_uninstall_args(
    bcul_path: str,
    *,
    dry_run: bool = True,
    quiet: bool = False,
    unattended: bool = False,
    verbose: bool = False,
    junk_level: str | None = None,
) -> list[str]:
    """argv for ``uninstall``.

    ``dry_run`` defaults to **True**: the only safe default for an irreversible
    operation.

    Raises:
        ValueError: bad junk level, or a blank path.
    """
    if not str(bcul_path).strip():
        raise ValueError("uninstall needs a .bcul path")
    if junk_level is not None and junk_level not in JUNK_LEVELS:
        raise ValueError(
            f"unknown junk level {junk_level!r}; valid: {', '.join(JUNK_LEVELS)}"
        )
    args = ["uninstall", bcul_path]
    if dry_run:
        args.append(_flag("N"))
    if quiet:
        args.append(_flag("Q"))
    if unattended:
        args.append(_flag("U"))
    if verbose:
        args.append(_flag("V"))
    if junk_level:
        args.append(_flag("J", f"={junk_level}"))
    return args


# ── execution ─────────────────────────────────────────────────────────

def run(
    argv: Sequence[str],
    *,
    console: str | None = None,
    timeout: int = 900,
    require_admin: bool = True,
    check_admin: bool = True,
) -> dict[str, Any]:
    """Run BCU-console and return both output streams decoded.

    Args:
        argv: Arguments *after* the executable (see the builders).
        console: Explicit path; discovered when omitted.
        timeout: Seconds before the run is abandoned.
        require_admin: If True, refuse when not elevated.
        check_admin: Allow tests to bypass the elevation check.

    Returns:
        ``{"success", "exit_code", "stdout", "stderr", "elapsed_ms", "argv"}``.
        Both streams are returned because ``uninstall`` reports on stderr.

    Raises:
        BCUNotFound: the executable is missing.
        BCUExecutionError: not elevated, or the process could not start/timed out.
    """
    resolved = find_console(console)
    if require_admin and check_admin and not is_admin():
        raise BCUExecutionError(admin_requirement_message())

    import time
    started = time.time()
    try:
        completed = subprocess.run(
            [resolved, *argv],
            capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BCUExecutionError(
            f"BCU-console timed out after {timeout}s running: {' '.join(argv)}\n"
            "`list` is a full-system scan and can take ~60s; a dry run ~30s. "
            "Raise --timeout if this machine is slower."
        ) from exc
    except OSError as exc:
        raise BCUExecutionError(f"could not launch BCU-console: {exc}") from exc
    elapsed_ms = int((time.time() - started) * 1000)

    from ..core.parse import decode_console_output
    return {
        "success": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": decode_console_output(completed.stdout),
        "stderr": decode_console_output(completed.stderr),
        "elapsed_ms": elapsed_ms,
        "argv": [resolved, *argv],
    }
