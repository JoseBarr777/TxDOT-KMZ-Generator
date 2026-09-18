"""Builds safe, human-readable HTML descriptions (Google Earth popups).

Two builders live here:

- `build_description_html` -- a flat labeled table, used for district/county
  boundary popups where the field set is small and uncategorized.
- `build_roadway_description_html` -- grouped sections (Identity, Roadway
  Dimensions, ROW Reference, Operations & Traffic) for roadway placemarks,
  per the popup redesign: a section renders only if at least one of its
  rows has a present value, and a row renders only if its own value is
  present. Coded fields are decoded via processing/codes.py; the popup
  never falls back to raw ADMIN/HSYS/etc. codes for these fields.

Both builders check missingness with values.is_missing_value BEFORE any
string conversion happens (see values.py's module docstring for why this
matters -- a naive `str(value)` on a NaN float renders the literal text
"nan"). Values are HTML-escaped and the whole result is CDATA-wrapped so
simplekml emits the markup unescaped for Google Earth to render as HTML.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any

from txdot_overlay.export.formatting import (
    format_count,
    format_feet,
    format_miles,
    format_mph,
    format_number,
    format_traffic_count,
)
from txdot_overlay.processing.codes import (
    decode_aces_ctrl,
    decode_admin_agency,
    decode_dir_trav,
    decode_f_system,
    decode_hsys,
    decode_hwy_stat,
    decode_med_type,
    decode_shoulder_type,
)
from txdot_overlay.values import is_missing_value
from txdot_overlay.xml_safety import strip_illegal_xml_chars

ROW_MIN_DISCLAIMER = "Inventory reference value; not a surveyed ROW boundary."


def _wrap_cdata(inner_html: str) -> str:
    # "]]>" cannot appear inside a CDATA section; split it defensively in
    # case any escaped field value ever produced that literal sequence.
    safe = inner_html.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def _format_value(value: Any) -> str:
    # Strip illegal XML control characters BEFORE escaping -- html.escape()
    # only handles &<>"', not control bytes, and a source field containing
    # one (observed live: Cameron County's STE_NAM) crashes KMZ export
    # entirely rather than just rendering oddly. See xml_safety.py.
    return escape(strip_illegal_xml_chars(str(value)), quote=True)


def build_description_html(
    attributes: dict[str, Any],
    fields: list[str],
    field_labels: dict[str, str] | None = None,
) -> str:
    """Build a CDATA-wrapped flat HTML table for the given attributes.

    Only `fields` are included; a field is skipped when its value is
    missing per values.is_missing_value (never a bare `value in (None, "")`
    check, which lets NaN floats slip through as literal "nan" text).
    """
    labels = field_labels or {}
    rows = []
    for field_name in fields:
        if field_name not in attributes:
            continue
        value = attributes[field_name]
        if is_missing_value(value):
            continue
        label = escape(labels.get(field_name, field_name), quote=True)
        rows.append(f"<tr><td><b>{label}</b></td><td>{_format_value(value)}</td></tr>")
    table = "<table>" + "".join(rows) + "</table>" if rows else "<p>No attributes.</p>"
    return _wrap_cdata(table)


@dataclass
class PopupRow:
    label: str
    value: str


@dataclass
class PopupSection:
    title: str
    rows: list[PopupRow]


def _row(label: str, raw_value: Any, render: Callable[[Any], Any] = str) -> PopupRow | None:
    """Build one row, or None if `raw_value` is missing or renders to nothing.

    `render` receives the RAW value -- decoders (processing/codes.py) and
    formatters (export/formatting.py) both expect a present value, which is
    guaranteed here since missingness is checked before render() is called.
    """
    if is_missing_value(raw_value):
        return None
    rendered = render(raw_value)
    if rendered is None:
        return None
    text = strip_illegal_xml_chars(str(rendered)).strip()
    if not text:
        return None
    return PopupRow(label, text)


def _section(title: str, rows: list[PopupRow | None]) -> PopupSection | None:
    present = [r for r in rows if r is not None]
    return PopupSection(title, present) if present else None


def _build_identity_section(attrs: dict[str, Any], fields: dict[str, str]) -> PopupSection | None:
    rows = [
        _row("Highway", attrs.get(fields["highway_full"])),
        _row("Route system", attrs.get(fields["highway_system"]), decode_hsys),
        _row("Street name", attrs.get(fields["street_name"])),
        _row("Route ID", attrs.get(fields["route_id"])),
        _row("Control section", attrs.get(fields["control_section"])),
        _row("Roadbed ID", attrs.get(fields["roadbed_id"])),
        _row("Direction of travel", attrs.get(fields["direction_of_travel"]), decode_dir_trav),
        _row("Highway status", attrs.get(fields["highway_status"]), decode_hwy_stat),
        _row("Maintenance agency", attrs.get(fields["maintenance_agency"]), decode_admin_agency),
        _row(
            "Administrative classification", attrs.get(fields["admin_system"]), decode_admin_agency
        ),
        _row("Functional system", attrs.get(fields["functional_system"]), decode_f_system),
    ]
    return _section("Identity", rows)


def _build_dimensions_section(attrs: dict[str, Any], fields: dict[str, str]) -> PopupSection | None:
    rows = [
        _row("Number of lanes", attrs.get(fields["num_lanes"]), format_count),
        _row("Lane width", attrs.get(fields["lane_width"]), format_feet),
        _row("Surface width", attrs.get(fields["surface_width"]), format_feet),
        _row("Paved roadbed width", attrs.get(fields["paved_roadbed_width"]), format_feet),
        _row("Roadbed width", attrs.get(fields["roadbed_width"]), format_feet),
        _row("Median width", attrs.get(fields["median_width"]), format_feet),
        _row("Median type", attrs.get(fields["median_type"]), decode_med_type),
        _row("Inside shoulder width", attrs.get(fields["inside_shoulder_width"]), format_feet),
        _row(
            "Inside shoulder type", attrs.get(fields["inside_shoulder_type"]), decode_shoulder_type
        ),
        _row("Outside shoulder width", attrs.get(fields["outside_shoulder_width"]), format_feet),
        _row(
            "Outside shoulder type",
            attrs.get(fields["outside_shoulder_type"]),
            decode_shoulder_type,
        ),
    ]
    return _section("Roadway Dimensions", rows)


def _build_row_reference_section(
    attrs: dict[str, Any], fields: dict[str, str]
) -> PopupSection | None:
    """ROW_MIN only, always paired with the inventory-reference disclaimer.

    Do not use ROW_MIN to generate a ROW polygon or assume the centerline is
    centered within the recorded width -- it is exactly what its name says,
    a minimum recorded width from the inventory, not a surveyed boundary.
    """
    row = _row("Minimum recorded ROW width", attrs.get(fields["row_min"]), format_feet)
    if row is None:
        return None
    return PopupSection("ROW Reference", [row, PopupRow("Note", ROW_MIN_DISCLAIMER)])


def _build_operations_section(attrs: dict[str, Any], fields: dict[str, str]) -> PopupSection | None:
    rows = [
        _row("Speed limit", attrs.get(fields["speed_limit"]), format_mph),
        _row("Access control", attrs.get(fields["access_control"]), decode_aces_ctrl),
        _row("Current AADT", attrs.get(fields["adt_current"]), format_traffic_count),
        _row("AADT year", attrs.get(fields["adt_year"]), format_count),
        _row("Section length", attrs.get(fields["section_length"]), format_miles),
        _row("Lane miles", attrs.get(fields["lane_miles"]), format_number),
    ]
    return _section("Operations & Traffic", rows)


def _render_sections_html(sections: list[PopupSection]) -> str:
    if not sections:
        return _wrap_cdata("<p>No attributes.</p>")

    parts: list[str] = []
    for section in sections:
        parts.append(f"<h4>{escape(section.title, quote=True)}</h4><table>")
        for row in section.rows:
            parts.append(
                f"<tr><td><b>{escape(row.label, quote=True)}</b></td>"
                f"<td>{escape(row.value, quote=True)}</td></tr>"
            )
        parts.append("</table>")
    return _wrap_cdata("".join(parts))


def build_roadway_description_html(attrs: dict[str, Any], fields: dict[str, str]) -> str:
    """Build the grouped-section popup for one roadway placemark.

    `attrs` is the record's raw attribute dict (e.g. from a GeoDataFrame
    row.to_dict()); `fields` is config.sources["roadways"].fields, mapping
    this project's field keys to the live service's column names.
    """
    sections = [
        s
        for s in (
            _build_identity_section(attrs, fields),
            _build_dimensions_section(attrs, fields),
            _build_row_reference_section(attrs, fields),
            _build_operations_section(attrs, fields),
        )
        if s is not None
    ]
    return _render_sections_html(sections)


CITY_LIMITS_SOURCE_NOTE = (
    "TxDOT City Boundaries (GRID), reviewed 2026-09-12 -- see docs/SOURCE_AUDIT.md "
    "for the source comparison. This layer's ArcGIS service exposes no "
    "per-feature update-date attribute."
)


def _build_city_identity_section(
    attrs: dict[str, Any], fields: dict[str, str]
) -> PopupSection | None:
    rows = [
        _row("City name", attrs.get(fields["name"])),
        # Raw value shown as-is (not decoded into Yes/No) -- unlike the RIF-
        # spec coded fields in processing/codes.py, this flag's exact
        # encoding has not been independently verified against an official
        # spec, and this project does not guess field encodings.
        _row("County seat flag", attrs.get(fields["county_seat_flag"])),
    ]
    return _section("Identity", rows)


def _build_city_population_section(
    attrs: dict[str, Any], fields: dict[str, str]
) -> PopupSection | None:
    row = _row("Population (2022)", attrs.get(fields["population_2022"]), format_count)
    if row is None:
        row = _row("Population (2020)", attrs.get(fields["population_2020"]), format_count)
    return _section("Population", [row]) if row is not None else None


def build_city_limits_description_html(attrs: dict[str, Any], fields: dict[str, str]) -> str:
    """Build the grouped-section popup for one city-limits placemark.

    `fields` is config.sources["city_limits"].fields. The "Source" section
    is a fixed note, not a per-feature field -- this layer's ArcGIS service
    has no per-feature update-date attribute (confirmed during the
    docs/SOURCE_AUDIT.md source audit), so a per-row date is never fabricated.
    """
    sections = [
        s
        for s in (
            _build_city_identity_section(attrs, fields),
            _build_city_population_section(attrs, fields),
        )
        if s is not None
    ]
    sections.append(PopupSection("Source", [PopupRow("Note", CITY_LIMITS_SOURCE_NOTE)]))
    return _render_sections_html(sections)
