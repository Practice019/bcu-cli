"""Parsers for what BCU-console actually emits.

Two output channels, both measured (docs/BCU.md §4 and §6):

* **stdout, UTF-8**, only with ``/F=json`` — a bare JSON array of applications.
* **stdout, UTF-16LE**, without ``/F`` — the human-readable table. The first
  bytes are literally ``42 00 43 00`` ("BC"), which is why the decoder must not
  assume UTF-8.
* **stderr**, for ``uninstall`` — ``/F=json`` has no effect there (measured:
  ``stdout=0 B stderr=799 B``), so structured results come from stderr text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .model import Application

#: "Found 591 applications."
_FOUND_RE = re.compile(r"Found\s+([\d,]+)\s+applications?", re.IGNORECASE)

#: "1 application(s) were matched by the list: Acme Archiver 4.10 (x64)"
_MATCHED_RE = re.compile(
    r"(\d+)\s+application\(s\)\s+were\s+matched\s+by\s+the\s+list\s*:\s*(.*)",
    re.IGNORECASE,
)

#: "Running: 0, Waiting: 0, Finished: 1, Failed: 0"
_COUNTS_RE = re.compile(
    r"Running:\s*(\d+),\s*Waiting:\s*(\d+),\s*Finished:\s*(\d+),\s*Failed:\s*(\d+)"
)

_DRY_RUN_RE = re.compile(r"dry\s*run", re.IGNORECASE)


def decode_console_output(raw: bytes) -> str:
    """Decode BCU console bytes, which are UTF-16LE without ``/F`` and UTF-8 with it.

    Tries, in order: UTF-8 (BOM aware), UTF-16LE, UTF-16BE, then the OEM code
    page, then latin-1 as a last resort. UTF-16 is checked *before* any
    single-byte codec, because a single-byte codec never fails and would turn a
    UTF-16 stream into silent mojibake.
    """
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")

    # Detect UTF-16 by the NUL-byte density of the first block, not by "byte 1
    # is NUL". BCU's own banner is ASCII so that shortcut works for it, but a
    # console whose first character is CJK (e.g. 闲 = 0x95F2, low byte 0xF2)
    # defeats it. ASCII in UTF-16 is ~50% NUL bigrams; UTF-8 text has none.
    sample = raw[:512]
    if len(sample) >= 4:
        pairs = len(sample) // 2
        le_zero_high = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
        be_zero_low = sum(1 for i in range(0, len(sample) - 1, 2) if sample[i] == 0)
        if pairs and le_zero_high / pairs > 0.4:
            try:
                return raw.decode("utf-16-le")
            except UnicodeDecodeError:
                pass
        if pairs and be_zero_low / pairs > 0.4:
            try:
                return raw.decode("utf-16-be")
            except UnicodeDecodeError:
                pass

    for encoding in ("utf-8", "cp936", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def parse_list_json(text: str) -> list[Application]:
    """Parse ``BCU-console list /F=json`` output.

    BCU emits a **bare array**. An object (e.g. a future ``{"Applications": []}``
    wrapper) is rejected rather than silently yielding zero apps, because a
    silent zero would look exactly like "nothing is installed".

    Raises:
        ValueError: on malformed JSON, a non-array root, or a non-object entry.
    """
    cleaned = text.lstrip("\ufeff\u200b \t\r\n")
    if not cleaned.strip():
        return []
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"BCU list output is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(
            "BCU list output must be a JSON array of applications, got "
            f"{type(data).__name__}"
        )
    out: list[Application] = []
    for index, item in enumerate(data):
        try:
            out.append(Application.from_bcu_json(item))
        except ValueError as exc:
            raise ValueError(f"entry {index}: {exc}") from exc
    return out


@dataclass
class DryRunResult:
    """What a BCU dry-run reported, reconstructed from stderr."""

    found: int | None = None
    matched_count: int = 0
    matched_names: list[str] = field(default_factory=list)
    running: int = 0
    waiting: int = 0
    finished: int = 0
    failed: int = 0
    was_dry_run: bool = False
    raw: str = ""

    @property
    def matched(self) -> bool:
        """True when the list selected at least one application."""
        return self.matched_count > 0

    @property
    def succeeded(self) -> bool:
        """Dry run that matched something and finished with no failures."""
        return self.matched and self.failed == 0

    def to_dict(self) -> dict:
        """Serializable summary."""
        return {
            "found": self.found,
            "matched_count": self.matched_count,
            "matched_names": list(self.matched_names),
            "running": self.running,
            "waiting": self.waiting,
            "finished": self.finished,
            "failed": self.failed,
            "was_dry_run": self.was_dry_run,
        }


def parse_dry_run_stderr(text: str) -> DryRunResult:
    """Parse the progress log BCU writes to **stderr** for ``uninstall``.

    ``/F=json`` is ignored on this command (measured), so this text is the only
    structured record of what a dry run selected.
    """
    result = DryRunResult(raw=text or "")
    if not text:
        return result

    found = _FOUND_RE.search(text)
    if found:
        result.found = int(found.group(1).replace(",", ""))

    matched = _MATCHED_RE.search(text)
    if matched:
        result.matched_count = int(matched.group(1))
        # BCU joins names with ", ". The count is authoritative for how many
        # matched, so a name containing a comma is kept as one entry when the
        # count says one — and split only when it agrees.
        listed = [part.strip() for part in matched.group(2).split(",") if part.strip()]
        result.matched_names = listed if len(listed) == result.matched_count else (
            [matched.group(2).strip()] if matched.group(2).strip() else []
        )

    # The last counts line is the final state.
    for counts in _COUNTS_RE.finditer(text):
        result.running = int(counts.group(1))
        result.waiting = int(counts.group(2))
        result.finished = int(counts.group(3))
        result.failed = int(counts.group(4))

    result.was_dry_run = bool(_DRY_RUN_RE.search(text))
    return result


def extract_version(console_output: str) -> str:
    """Pull the version out of BCU's banner, e.g. ``6.3.0.0``."""
    match = re.search(r"BCU-console,\s*Version=([\d.]+)", console_output or "")
    return match.group(1) if match else ""
