"""Turn a user-supplied pattern into the set of applications to act on.

The dangerous failure mode for an uninstaller is selecting the *wrong* set, so
selection is explicit about ambiguity and refuses rather than guessing:

* exact match first (case-insensitive),
* otherwise substring/glob, and multiple hits are reported as ``ambiguous``,
* protected system components are excluded unless asked for,
* an app that BCU says cannot be uninstalled is reported, not silently skipped.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .model import Application

#: Fields a pattern may be matched against.
SEARCH_FIELDS: tuple[str, ...] = ("display_name", "registry_key", "any")


@dataclass
class Selection:
    """The outcome of matching a pattern against a scan."""

    pattern: str
    matched: list[Application] = field(default_factory=list)
    ambiguous: bool = False
    reason: str = ""
    excluded_protected: list[Application] = field(default_factory=list)
    not_uninstallable: list[Application] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when exactly the intended set was identified."""
        return bool(self.matched) and not self.ambiguous

    @property
    def names(self) -> list[str]:
        """Display names of the selection."""
        return [app.display_name for app in self.matched]

    def to_dict(self) -> dict:
        """Serializable summary."""
        return {
            "pattern": self.pattern,
            "matched": [app.display_name for app in self.matched],
            "matched_count": len(self.matched),
            "ambiguous": self.ambiguous,
            "reason": self.reason,
            "excluded_protected": [app.display_name for app in self.excluded_protected],
            "not_uninstallable": [app.display_name for app in self.not_uninstallable],
        }


def _key(app: Application, by: str) -> str:
    if by == "registry_key":
        return app.registry_key_name.lower()
    return app.display_name.lower()


def select_apps(
    apps: Iterable[Application],
    pattern: str,
    *,
    exact: bool = True,
    glob: bool = False,
    by: str = "display_name",
    include_protected: bool = False,
    first_only: bool = False,
) -> Selection:
    """Match *pattern* against *apps*.

    Args:
        apps: The indexed applications.
        pattern: What to look for.
        exact: Prefer an exact (case-insensitive) match; falls back to substring.
        glob: Treat *pattern* as a shell glob instead of a substring.
        by: ``display_name``, ``registry_key`` or ``any``.
        include_protected: Allow protected system components through.
        first_only: Keep only the first match (for scripts that accept ambiguity).

    Raises:
        ValueError: blank pattern, or an unknown *by*.
    """
    if not str(pattern).strip():
        raise ValueError("search pattern cannot be empty")
    if by not in SEARCH_FIELDS:
        raise ValueError(f"unknown search field {by!r}; valid: {', '.join(SEARCH_FIELDS)}")
    if by == "any":
        raise ValueError("'any' is for documentation; pick display_name or registry_key")

    pool = list(apps)
    needle = pattern.strip().lower()

    def matches(app: Application) -> bool:
        if glob:
            return fnmatch.fnmatch(app.display_name.lower(), needle) or \
                   fnmatch.fnmatch(app.registry_key_name.lower(), needle)
        return needle in _key(app, by)

    found = [app for app in pool if matches(app)]

    if exact and not glob:
        exact_hits = [app for app in found if _key(app, by) == needle]
        if exact_hits:
            found = exact_hits

    result = Selection(pattern=pattern)

    if not include_protected:
        protected = [app for app in found if app.is_protected]
        if protected:
            result.excluded_protected = protected
            found = [app for app in found if not app.is_protected]

    if not found:
        result.reason = (
            f"no installed application matches {pattern!r}"
            if not result.excluded_protected
            else f"{pattern!r} only matches protected system components"
        )
        return result

    if len(found) > 1 and first_only:
        found = found[:1]
        result.reason = "multiple matches; kept the first"

    result.matched = found
    result.ambiguous = len(found) > 1
    result.not_uninstallable = [app for app in found if not app.is_uninstallable]
    if result.ambiguous and not result.reason:
        result.reason = (
            f"{len(found)} applications match {pattern!r}; narrow it down "
            "or pass --first to take the first"
        )
    return result


def top_by_size(apps: Sequence[Application], limit: int = 20) -> list[Application]:
    """Largest indexed applications first (BCU's KB estimate)."""
    ordered = sorted(apps, key=lambda app: -app.estimated_size_kb)
    return ordered[: max(0, limit)]
