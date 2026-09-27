"""Generate ``.bcul`` uninstall lists.

Why this module exists: ``BCU-console uninstall`` accepts **only a file**
(source: ``ProcessUninstallCommand`` requires an existing path and returns
``Invalid path or missing list file`` otherwise). It cannot uninstall by name.
So "uninstall the app called X" has to become "write a list that selects X, then
hand that file to BCU" — that translation is this module's whole job.

The format is ``XmlSerializer`` output for ``UninstallList``:

    UninstallList
      Enabled            bool
      Filters            Filter[]
        Filter
          Enabled        bool
          Exclude        bool
          Name           string
          ComparisonEntries  FilterCondition[]
            FilterCondition
              InvertResults    bool
              FilterText       string
              ComparisonMethod enum

Element order matters to ``XmlSerializer``. The shape below is not inferred: it
was validated against the real engine with a dry run, which reported
``1 application(s) were matched by the list: Acme Archiver 4.10 (x64)`` and
``Dry run finished. No changes were made.`` (docs/BCU.md §6, 坑 3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape, quoteattr

#: Comparison methods BCU's FilterCondition accepts.
COMPARISON_METHODS: tuple[str, ...] = (
    "Any", "Equals", "Contains", "StartsWith", "EndsWith", "Regex", "Wildcard",
)

_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'


@dataclass
class FilterSpec:
    """One include/exclude rule in a list."""

    pattern: str
    exclude: bool = False
    method: str = "Contains"
    name: str = "cli"

    def __post_init__(self) -> None:
        if not str(self.pattern).strip():
            raise ValueError("filter pattern cannot be empty")
        if self.method not in COMPARISON_METHODS:
            raise ValueError(
                f"unknown comparison method {self.method!r}; "
                f"valid: {', '.join(COMPARISON_METHODS)}"
            )


def _qattr(value: str) -> str:
    """Attribute-safe quoted value (use for the xmlns attributes only)."""
    return quoteattr(value)


def build_bcul(filters: Iterable[FilterSpec]) -> str:
    """Render an ``UninstallList`` XML document for *filters*.

    Every text value is escaped, so app names containing ``& < > " '`` or CJK
    characters produce a document BCU can still read.

    Raises:
        ValueError: no filters, or a blank pattern.
    """
    specs = list(filters)
    if not specs:
        raise ValueError("a .bcul list needs at least one filter")

    parts: list[str] = [
        _DECLARATION,
        '<UninstallList xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
        "  <Enabled>true</Enabled>",
        "  <Filters>",
    ]
    for spec in specs:
        if not str(spec.pattern).strip():
            raise ValueError("filter pattern cannot be empty")
        parts.extend([
            "    <Filter>",
            "      <Enabled>true</Enabled>",
            f"      <Exclude>{'true' if spec.exclude else 'false'}</Exclude>",
            f"      <Name>{escape(str(spec.name))}</Name>",
            "      <ComparisonEntries>",
            "        <FilterCondition>",
            "          <InvertResults>false</InvertResults>",
            f"          <FilterText>{escape(str(spec.pattern))}</FilterText>",
            f"          <ComparisonMethod>{spec.method}</ComparisonMethod>",
            "        </FilterCondition>",
            "      </ComparisonEntries>",
            "    </Filter>",
        ])
    parts.extend(["  </Filters>", "</UninstallList>", ""])
    return "\n".join(parts)


def write_bcul(filters: Iterable[FilterSpec], path: str) -> str:
    """Write the list to *path* as UTF-8 and return the path."""
    text = build_bcul(filters)
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path
