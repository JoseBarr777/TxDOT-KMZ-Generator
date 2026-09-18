"""Popup/placemark title selection: fallback order plus best-effort highway formatting.

A missing value must never become a title -- `resolve_title` only ever
returns a present, non-blank string, falling all the way through to a fixed
"Unnamed roadway segment" label rather than letting an empty title slip
through silently.
"""

from __future__ import annotations

import re

from txdot_overlay.values import is_missing_value
from txdot_overlay.xml_safety import strip_illegal_xml_chars

UNNAMED_SEGMENT_LABEL = "Unnamed roadway segment"
UNNAMED_CITY_LABEL = "Unnamed city"

# HWY = Highway-System (2 letters) + Highway-Number (up to 4 digits,
# zero-padded) + optional Highway-Suffix (1 letter), per the RIF spec's
# SIGNED-HIGHWAY definition. Formatting is best-effort: any HWY value that
# doesn't cleanly match this shape is shown exactly as stored rather than
# guessed at.
_HWY_PATTERN = re.compile(r"^([A-Z]{2})0*(\d{1,4})([A-Z]?)$")


def format_highway_display(hwy: str) -> str:
    """Best-effort "IH0020" -> "IH 20", "US0271" -> "US 271". Falls back to the raw value."""
    match = _HWY_PATTERN.match(hwy.strip().upper())
    if not match:
        return hwy
    system, number, suffix = match.groups()
    formatted = f"{system} {number}"
    if suffix:
        formatted += f" {suffix}"
    return formatted


def resolve_title(*, hwy, ste_nam, ria_rte_id) -> tuple[str, str | None]:
    """Return (display_title, raw_identifier_if_different_from_title).

    Fallback order: HWY -> STE_NAM -> RIA_RTE_ID -> "Unnamed roadway segment".
    The raw identifier is returned alongside the title only when formatting
    changed it (e.g. "IH0020" -> "IH 20"), so callers can show both without
    duplicating an unformatted field verbatim.
    """
    if not is_missing_value(hwy):
        raw = strip_illegal_xml_chars(str(hwy)).strip()
        display = format_highway_display(raw)
        return display, (raw if display != raw else None)

    if not is_missing_value(ste_nam):
        raw = strip_illegal_xml_chars(str(ste_nam)).strip()
        if raw:
            return raw, None

    if not is_missing_value(ria_rte_id):
        raw = strip_illegal_xml_chars(str(ria_rte_id)).strip()
        if raw:
            return raw, None

    return UNNAMED_SEGMENT_LABEL, None


def resolve_city_limits_title(*, city_name) -> tuple[str, str | None]:
    """Return (display_title, raw_identifier_if_different) for a city-limits placemark.

    Same missing-value/XML-safety handling as resolve_title, just a single
    fallback field (city name) since city limits carry no highway-style
    identifier hierarchy.
    """
    if not is_missing_value(city_name):
        raw = strip_illegal_xml_chars(str(city_name)).strip()
        if raw:
            return raw, None

    return UNNAMED_CITY_LABEL, None
