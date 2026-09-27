"""Render application lists as reports."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Iterable, Sequence

from .model import Application

DEFAULT_COLUMNS: tuple[str, ...] = (
    "display_name", "display_version", "size_human", "publisher", "kind_normalized",
)

_ALL_COLUMNS: tuple[str, ...] = DEFAULT_COLUMNS + (
    "install_location", "install_date", "estimated_size_kb", "is_64bit",
    "is_protected", "is_orphaned", "is_update", "is_valid",
    "quiet_uninstall_possible", "uninstall_possible",
    "registry_key_name", "uninstaller_kind",
)

_ALIGN_RIGHT = {"estimated_size_kb"}


def _cell(app: Application, column: str) -> Any:
    if column == "size_human":
        return app.size_human
    value = getattr(app, column, "")
    if isinstance(value, bool):
        return "yes" if value else "no"
    return value


def render(
    apps: Iterable[Application] | None,
    fmt: str = "table",
    columns: Sequence[str] | None = None,
    top: int | None = None,
) -> str:
    """Render *apps* in the requested format.

    Args:
        apps: Applications to render.
        fmt: ``table``, ``csv``, ``json``, ``markdown`` or ``html``.
        columns: Column subset; defaults to :data:`DEFAULT_COLUMNS`.
        top: Keep only the first *top* entries.

    Raises:
        ValueError: unknown format.
    """
    items = [a for a in (apps or []) if a is not None]
    if top is not None:
        items = items[: max(0, top)]
    cols = list(columns or DEFAULT_COLUMNS)
    known = set(_ALL_COLUMNS)
    unknown = [c for c in cols if c not in known]
    if unknown:
        raise ValueError(f"unknown column(s): {', '.join(unknown)}")
    fmt = (fmt or "table").lower()

    if fmt == "json":
        return json.dumps(
            [{c: _cell(a, c) for c in cols} for a in items],
            indent=2, ensure_ascii=False, default=str,
        )

    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(cols)
        for app in items:
            writer.writerow([_cell(app, c) for c in cols])
        return buffer.getvalue()

    if fmt == "markdown":
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join("---" for _ in cols) + " |"]
        for app in items:
            lines.append("| " + " | ".join(str(_cell(app, c)) for c in cols) + " |")
        return "\n".join(lines) + "\n"

    if fmt == "html":
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{_cell(a, c)}</td>" for c in cols) + "</tr>"
            for a in items
        )
        return f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>{body}</tbody>\n</table>\n"

    if fmt == "table":
        rows = [[str(_cell(a, c)) for c in cols] for a in items]
        widths = [
            max([len(cols[i].upper())] + [len(r[i]) for r in rows]) if rows
            else len(cols[i].upper())
            for i in range(len(cols))
        ]

        def line(cells: Sequence[str]) -> str:
            parts = []
            for i, cell in enumerate(cells):
                parts.append(cell.rjust(widths[i]) if cols[i] in _ALIGN_RIGHT
                             else cell.ljust(widths[i]))
            return "  ".join(parts).rstrip()

        out = [line([c.upper() for c in cols]), "  ".join("-" * w for w in widths)]
        out.extend(line(r) for r in rows)
        return "\n".join(out) + "\n"

    raise ValueError(
        f"unknown render format {fmt!r}; use table, csv, json, markdown or html"
    )


def write(apps: Iterable[Application] | None, path: str, fmt: str | None = None,
          columns: Sequence[str] | None = None, top: int | None = None) -> dict:
    """Render to *path*; the format defaults to the file extension."""
    resolved = (fmt or os.path.splitext(path)[1].lstrip(".") or "table").lower()
    if resolved == "md":
        resolved = "markdown"
    text = render(apps, fmt=resolved, columns=columns, top=top)
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return {"path": path, "format": resolved, "size": os.path.getsize(path)}
