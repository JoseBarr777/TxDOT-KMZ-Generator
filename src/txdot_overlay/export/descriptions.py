"""Builds safe, human-readable HTML descriptions (Google Earth popups) from attributes."""
from __future__ import annotations

from html import escape
from typing import Any


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def build_description_html(
    attributes: dict[str, Any],
    fields: list[str],
    field_labels: dict[str, str] | None = None,
) -> str:
    """Build a CDATA-wrapped HTML table for the given attributes.

    Only `fields` are included (never every raw attribute), so popups stay
    readable and don't leak internal-only columns. Values are HTML-escaped
    before insertion; the CDATA wrapper is what lets simplekml emit the
    markup unescaped so Google Earth renders it as HTML rather than as text.
    """
    labels = field_labels or {}
    rows = []
    for field_name in fields:
        if field_name not in attributes:
            continue
        value = attributes[field_name]
        if value in (None, ""):
            continue
        label = escape(labels.get(field_name, field_name), quote=True)
        rows.append(
            f"<tr><td><b>{label}</b></td><td>{_format_value(value)}</td></tr>"
        )
    table = "<table>" + "".join(rows) + "</table>" if rows else "<p>No attributes.</p>"
    # "]]>" cannot appear inside a CDATA section; split it defensively in case
    # any escaped field value ever produced that literal sequence.
    safe_table = table.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe_table}]]>"
