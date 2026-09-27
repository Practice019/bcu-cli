"""Data model for one installed application as BCU reports it.

BCU emits 28 fields per app. This module is the only place that knows their
spellings, so a BCU upgrade that renames one is a one-file change.

Measured field availability (from a real 591-app scan, see docs/BCU.md §5):

    DisplayName            591/591 non-null
    DisplayVersion         488/591
    Publisher              552/591
    EstimatedSizeKb        591/591   (Int64)
    UninstallString        591/591
    QuietUninstallString   531/591
    QuietUninstallPossible 591/591   (bool)
    UninstallPossible      591/591   (bool)
    RegistryKeyName        345/591
    ParentKeyName            1/591   (do not depend on it)

`QuietUninstallPossible` cannot be trusted on its own: 60 apps reported the flag
as true while carrying no quiet command, and some report a command with the flag
false. Both are required for :attr:`is_quiet_capable`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: JSON keys BCU uses, mapped to our attribute names.
FIELD_MAP: dict[str, str] = {
    "DisplayName": "display_name",
    "DisplayVersion": "display_version",
    "Publisher": "publisher",
    "Comment": "comment",
    "AboutUrl": "about_url",
    "InstallLocation": "install_location",
    "InstallSource": "install_source",
    "InstallDate": "install_date",
    "EstimatedSizeKb": "estimated_size_kb",
    "UninstallString": "uninstall_string",
    "QuietUninstallString": "quiet_uninstall_string",
    "UninstallerKind": "uninstaller_kind",
    "UninstallerLocation": "uninstaller_location",
    "Is64Bit": "is_64bit",
    "IsProtected": "is_protected",
    "IsRegistered": "is_registered",
    "IsOrphaned": "is_orphaned",
    "IsUpdate": "is_update",
    "IsValid": "is_valid",
    "IsWebBrowser": "is_web_browser",
    "SystemComponent": "is_system_component",
    "RegistryKeyName": "registry_key_name",
    "RegistryPath": "registry_path",
    "ParentKeyName": "parent_key_name",
    "BundleProviderKey": "bundle_provider_key",
    "QuietUninstallPossible": "quiet_uninstall_possible",
    "UninstallPossible": "uninstall_possible",
}

_BOOL_FIELDS = (
    "is_protected", "is_registered", "is_orphaned", "is_update", "is_valid",
    "is_web_browser", "is_system_component", "quiet_uninstall_possible",
    "uninstall_possible",
)


def _text(value: Any) -> str:
    """BCU uses null in place of empty; normalise to a plain string."""
    if value is None:
        return ""
    return str(value)


def _flag(value: Any) -> bool:
    """Coerce BCU's booleans, tolerating strings and nulls."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _kbytes(value: Any) -> int:
    """EstimatedSizeKb is an Int64 in BCU's JSON but may arrive as a string."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


@dataclass
class Application:
    """One entry from ``BCU-console list /F=json``."""

    display_name: str
    display_version: str = ""
    publisher: str = ""
    comment: str = ""
    about_url: str = ""
    install_location: str = ""
    install_source: str = ""
    install_date: str = ""
    estimated_size_kb: int = 0
    uninstall_string: str = ""
    quiet_uninstall_string: str = ""
    uninstaller_kind: str = ""
    uninstaller_location: str = ""
    is_64bit: str = ""
    is_protected: bool = False
    is_registered: bool = False
    is_orphaned: bool = False
    is_update: bool = False
    is_valid: bool = False
    is_web_browser: bool = False
    is_system_component: bool = False
    registry_key_name: str = ""
    registry_path: str = ""
    parent_key_name: str = ""
    bundle_provider_key: str = ""
    quiet_uninstall_possible: bool = False
    uninstall_possible: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_bcu_json(cls, raw: dict[str, Any]) -> "Application":
        """Build from one BCU JSON object, tolerating unknown and missing keys."""
        if not isinstance(raw, dict):
            raise ValueError(f"application entry must be an object, got {type(raw).__name__}")

        # Accept both spellings: BCU's own keys (DisplayName) and our
        # attribute names (display_name), so to_dict() round-trips exactly and
        # an index written by an older version still loads.
        by_attr = {attr: key for key, attr in FIELD_MAP.items()}
        data: dict[str, Any] = {}
        for json_key, attr in FIELD_MAP.items():
            if json_key in raw:
                value = raw[json_key]
            elif attr in raw:
                value = raw[attr]
            else:
                continue
            if attr in _BOOL_FIELDS:
                data[attr] = _flag(value)
            elif attr == "estimated_size_kb":
                data[attr] = _kbytes(value)
            else:
                data[attr] = _text(value)

        known = set(FIELD_MAP) | set(FIELD_MAP.values())
        extra = {k: v for k, v in raw.items() if k not in known}

        if "display_name" not in data:
            raise ValueError("application entry has no DisplayName")
        return cls(**data, extra=extra)

    # ── derived ───────────────────────────────────────────────────────

    @property
    def is_uninstallable(self) -> bool:
        """BCU's flag *and* an actual command — either alone is a false positive."""
        return self.uninstall_possible and bool(self.uninstall_string.strip())

    @property
    def is_quiet_capable(self) -> bool:
        """Same rule as :attr:`is_uninstallable`, for the silent command."""
        return self.quiet_uninstall_possible and bool(self.quiet_uninstall_string.strip())

    @property
    def kind_normalized(self) -> str:
        """Lower-case uninstaller kind, ``"unknown"`` when BCU did not say."""
        return (self.uninstaller_kind or "unknown").strip().lower()

    @property
    def size_human(self) -> str:
        """Human size from BCU's KB estimate."""
        value = float(self.estimated_size_kb or 0)
        if value < 1024:
            return f"{int(value)} KB"
        value /= 1024
        if value < 1024:
            return f"{value:.2f} MB"
        value /= 1024
        if value < 1024:
            return f"{value:.2f} GB"
        return f"{value / 1024:.2f} TB"

    def to_dict(self) -> dict[str, Any]:
        """Round-trippable dict (``extra`` merged back under its original keys)."""
        out: dict[str, Any] = {
            attr: getattr(self, attr) for attr in FIELD_MAP.values()
        }
        out.update(self.extra)
        return out
