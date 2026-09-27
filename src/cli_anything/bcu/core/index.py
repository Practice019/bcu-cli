"""Local index of a BCU scan.

Why: ``BCU-console list`` is a **57.9-second full-system scan** and needs
administrator rights. Querying it per question is unusable. So the flow is

    scan  (admin, ~60 s)  ->  index file  ->  query (no admin, instant)

The index is a JSON document holding the scan result plus provenance, so a stale
index can be recognised.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .model import Application

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Index:
    """A saved BCU scan."""

    apps: list[Application] = field(default_factory=list)
    bcu_version: str = ""
    console_path: str = ""
    generated_at: str = ""
    host: str = ""

    @classmethod
    def from_apps(
        cls,
        apps: Iterable[Application],
        *,
        bcu_version: str = "",
        console_path: str = "",
        host: str = "",
    ) -> "Index":
        """Build an index from a fresh scan."""
        return cls(
            apps=list(apps),
            bcu_version=bcu_version,
            console_path=console_path,
            generated_at=_now(),
            host=host or os.environ.get("COMPUTERNAME", ""),
        )

    # ── persistence ───────────────────────────────────────────────────

    def save(self, path: str) -> str:
        """Write atomically: a half-written index must never be readable."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at or _now(),
            "bcu_version": self.bcu_version,
            "console_path": self.console_path,
            "host": self.host,
            "app_count": len(self.apps),
            "apps": [app.to_dict() for app in self.apps],
        }
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory or None, delete=False, newline="\n"
        )
        try:
            json.dump(payload, handle, indent=1, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, path)
        return path

    @classmethod
    def load(cls, path: str) -> "Index":
        """Read an index.

        Raises:
            FileNotFoundError: no index at *path*.
            ValueError: unreadable, wrong schema, or missing ``apps``.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"no scan index at {path} — run `bcu-cli scan` first"
            )
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"scan index is not readable JSON: {path} ({exc})") from exc

        if not isinstance(data, dict):
            raise ValueError(f"scan index must be a JSON object: {path}")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"scan index schema {version!r} is not supported "
                f"(expected {SCHEMA_VERSION}); re-run `bcu-cli scan`"
            )
        raw_apps = data.get("apps")
        if not isinstance(raw_apps, list):
            raise ValueError(f"scan index has no usable 'apps' array: {path}")

        apps: list[Application] = []
        for item in raw_apps:
            try:
                apps.append(Application.from_bcu_json(item))
            except ValueError:
                continue  # one bad entry must not lose the whole index
        return cls(
            apps=apps,
            bcu_version=str(data.get("bcu_version", "")),
            console_path=str(data.get("console_path", "")),
            generated_at=str(data.get("generated_at", "")),
            host=str(data.get("host", "")),
        )

    # ── summary ───────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of indexed applications."""
        return len(self.apps)

    @property
    def total_size_kb(self) -> int:
        """Sum of BCU's size estimates (KB)."""
        return sum(app.estimated_size_kb for app in self.apps)

    @property
    def quiet_capable_count(self) -> int:
        """Apps offering a usable silent uninstall command."""
        return sum(1 for app in self.apps if app.is_quiet_capable)

    @property
    def orphaned_count(self) -> int:
        """Apps whose files are gone but whose registry entry remains."""
        return sum(1 for app in self.apps if app.is_orphaned)

    @property
    def uninstallable_count(self) -> int:
        """Apps with a usable uninstall command."""
        return sum(1 for app in self.apps if app.is_uninstallable)

    def summary(self) -> dict[str, Any]:
        """Machine-readable overview."""
        return {
            "app_count": self.count,
            "uninstallable_count": self.uninstallable_count,
            "quiet_capable_count": self.quiet_capable_count,
            "orphaned_count": self.orphaned_count,
            "total_size_kb": self.total_size_kb,
            "bcu_version": self.bcu_version,
            "console_path": self.console_path,
            "generated_at": self.generated_at,
            "host": self.host,
        }
