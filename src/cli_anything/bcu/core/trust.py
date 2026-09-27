"""Warnings about the BCU fields that are easy to misread.

Measured behaviour, not theory — see ``docs/BCU-FIELDS.md`` for the evidence.
Each helper here exists because a real report was wrong at some point:

* ``EstimatedSizeKb`` is the installer's self-reported value, missing for 15% of
  entries, wrong in both directions (Edge 2.4x too large, Contoso Remote 13.9x too small)
  and counted once per registry entry, so summing it overstated disk use by 37%.
* ``IsOrphaned`` marks software found by directory scan that has no registry
  record — the opposite of "leftover registry entry". Acting on it deletes live
  directories.
* ``UninstallerLocation`` points at BCU's own helper directory for entries BCU
  removes itself; it is not the application's location.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .model import Application

#: Text shown wherever a size total is reported.
SIZE_CAVEAT = (
    "sizes are BCU's self-reported registry values, not measurements: absent for "
    "some entries, wrong in both directions, and counted once per registry entry "
    "so two entries naming one directory double count it. For disk decisions, "
    "measure the directory."
)

#: Text shown wherever orphan counts are reported.
ORPHAN_CAVEAT = (
    "'orphaned' here means software found by directory scan with no registry "
    "record (portable/unzipped installs), NOT a leftover registry entry. Their "
    "install directories are usually present and BCU removes them by deleting "
    "the directory."
)


def size_reliability(apps: Sequence[Application]) -> dict:
    """How much of this set carries a usable size, and what that implies."""
    total = len(apps)
    missing = [a for a in apps if not a.estimated_size_kb]
    return {
        "entry_count": total,
        "entries_without_size": len(missing),
        "coverage_pct": round(100 * (total - len(missing)) / total, 1) if total else 0.0,
        "caveat": SIZE_CAVEAT,
    }


def duplicate_locations(apps: Sequence[Application]) -> dict[str, list[str]]:
    """Directories claimed by more than one entry.

    Totalling sizes without this check double counts whatever is shared; one
    machine reported 88 GB for a 44 GB directory because two entries named it.
    """
    buckets: dict[str, list[str]] = {}
    for app in apps:
        key = (app.install_location or "").rstrip("\\/").lower()
        if key:
            buckets.setdefault(key, []).append(app.display_name)
    return {loc: names for loc, names in buckets.items() if len(names) > 1}


def deduplicated_total_kb(apps: Sequence[Application]) -> int:
    """Sum of sizes counting each install location once.

    Takes the largest value per directory: when several entries share a
    directory, the widest one is closest to the directory's real contents.
    """
    best: dict[str, int] = {}
    loose = 0
    for app in apps:
        key = (app.install_location or "").rstrip("\\/").lower()
        if not key:
            loose += app.estimated_size_kb
            continue
        best[key] = max(best.get(key, 0), app.estimated_size_kb)
    return sum(best.values()) + loose


def truly_dead_entries(apps: Sequence[Application]) -> list[Application]:
    """Entries that are genuinely dead registry records.

    The correct test is *not* ``IsOrphaned``: it is "there is a registry record
    **and** the install location is gone". Portable software has files but no
    registry record; dead software has a registry record but no files.
    """
    import os

    out: list[Application] = []
    for app in apps:
        has_registry = bool(app.registry_path or app.registry_key_name)
        location = (app.install_location or "").strip()
        location_gone = bool(location) and not os.path.exists(location)
        if has_registry and location_gone:
            out.append(app)
    return out


def summarize_for_report(apps: Iterable[Application]) -> dict:
    """Everything a caller should say alongside a size/health report."""
    items = list(apps)
    return {
        "entry_count": len(items),
        "size_reliability": size_reliability(items),
        "duplicate_locations": duplicate_locations(items),
        "deduplicated_total_kb": deduplicated_total_kb(items),
        "orphan_flag_count": sum(1 for a in items if a.is_orphaned),
        "orphan_caveat": ORPHAN_CAVEAT,
        "truly_dead_count": len(truly_dead_entries(items)),
    }
