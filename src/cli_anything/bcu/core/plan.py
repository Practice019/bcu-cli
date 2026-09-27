"""Build the uninstall command, safely.

BCU's own help says it plainly:

    /U  - Unattended mode (do not ask user for confirmation).
          WARNING: ONLY USE AFTER THOROUGH TESTING. ... THERE ARE NO WARRANTIES

So this module enforces a two-phase protocol and never lets ``/U`` be implied:

    dry-run (default)  ->  human/agent reads what would happen  ->  apply

Refusals are explicit and carry a reason, rather than silently downgrading to a
dry run or silently proceeding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from . import listfile
from .listfile import FilterSpec
from .model import Application
from .select import Selection

#: Junk-cleanup levels BCU accepts. Below VeryGood the vendor warns heavily.
JUNK_LEVELS: tuple[str, ...] = ("VeryGood", "Good", "Questionable", "Bad", "Unknown")

MODE_DRY_RUN = "dry-run"
MODE_APPLY = "apply"


@dataclass
class Plan:
    """A ready-to-run (or refused) uninstall task."""

    mode: str
    selection: Selection
    bcul_text: str = ""
    argv: list[str] = field(default_factory=list)
    refused: bool = False
    reason: str = ""
    quiet_capable: list[str] = field(default_factory=list)
    not_quiet_capable: list[str] = field(default_factory=list)

    @property
    def will_run(self) -> bool:
        """True when this plan is safe to execute."""
        return not self.refused and bool(self.argv)

    @property
    def destructive(self) -> bool:
        """True when executing this plan changes the system."""
        return self.mode == MODE_APPLY and self.will_run

    def to_dict(self) -> dict:
        """Serializable summary — what an agent should show before applying."""
        return {
            "mode": self.mode,
            "destructive": self.destructive,
            "refused": self.refused,
            "reason": self.reason,
            "targets": self.selection.names,
            "target_count": len(self.selection.matched),
            "quiet_capable": self.quiet_capable,
            "not_quiet_capable": self.not_quiet_capable,
            "argv": self.argv,
        }


def _refuse(selection: Selection, mode: str, reason: str) -> Plan:
    return Plan(mode=mode, selection=selection, refused=True, reason=reason)


def build_plan(
    selection: Selection,
    *,
    mode: str | None = None,
    quiet: bool = False,
    unattended: bool = False,
    confirmed: bool = False,
    junk_level: str | None = None,
    bcul_path: str = "uninstall.bcul",
) -> Plan:
    """Assemble the BCU command for *selection*.

    Args:
        selection: Result of :func:`cli_anything.bcu.core.select.select_apps`.
        mode: ``"dry-run"`` (default) or ``"apply"``.
        quiet: Pass ``/Q`` so BCU prefers silent uninstallers.
        unattended: Pass ``/U``. Requires ``confirmed``.
        confirmed: Caller has explicitly accepted an irreversible run.
        junk_level: One of :data:`JUNK_LEVELS`; omit to skip junk cleanup.
        bcul_path: Where the generated list will be written.

    Raises:
        ValueError: unknown mode, or an invalid junk level.
    """
    resolved_mode = mode or MODE_DRY_RUN
    if resolved_mode not in (MODE_DRY_RUN, MODE_APPLY):
        raise ValueError(f"mode must be {MODE_DRY_RUN!r} or {MODE_APPLY!r}, got {mode!r}")
    if junk_level is not None and junk_level not in JUNK_LEVELS:
        raise ValueError(
            f"unknown junk level {junk_level!r}; valid: {', '.join(JUNK_LEVELS)}"
        )

    # ── refuse before building anything ───────────────────────────────
    if not selection.matched:
        return _refuse(selection, resolved_mode,
                       selection.reason or "nothing selected, nothing to do")
    if selection.ambiguous:
        return _refuse(selection, resolved_mode,
                       selection.reason or "selection is ambiguous; refusing to guess")
    if any(app.is_protected for app in selection.matched):
        names = ", ".join(app.display_name for app in selection.matched if app.is_protected)
        return _refuse(selection, resolved_mode,
                       f"refusing to uninstall protected system component(s): {names}")
    if unattended and resolved_mode == MODE_APPLY and not confirmed:
        return _refuse(
            selection, resolved_mode,
            "unattended (/U) uninstall is irreversible and requires --confirm; "
            "run without --unattended first to preview",
        )

    targets = [app for app in selection.matched if app.is_uninstallable]

    # ── build ─────────────────────────────────────────────────────────
    specs: Sequence[FilterSpec] = [
        FilterSpec(pattern=app.display_name, name=app.display_name[:60] or "cli")
        for app in targets
    ]
    if not specs:
        return _refuse(
            selection, resolved_mode,
            "no selected application reports a usable uninstall command",
        )

    bcul_text = listfile.build_bcul(specs)
    argv: list[str] = ["uninstall", bcul_path]
    if resolved_mode == MODE_DRY_RUN:
        argv.append("/N")
    if quiet:
        argv.append("/Q")
    if unattended and resolved_mode == MODE_APPLY:
        argv.append("/U")
    if junk_level:
        argv.append(f"/J={junk_level}")

    plan = Plan(mode=resolved_mode, selection=selection, bcul_text=bcul_text, argv=argv)
    plan.quiet_capable = [a.display_name for a in targets if a.is_quiet_capable]
    plan.not_quiet_capable = [a.display_name for a in targets if not a.is_quiet_capable]
    return plan
