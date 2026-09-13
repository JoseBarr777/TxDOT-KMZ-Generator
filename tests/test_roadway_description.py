import pandas as pd
import pytest

from txdot_overlay.export.descriptions import ROW_MIN_DISCLAIMER, build_roadway_description_html


@pytest.fixture
def fields(config):
    return config.sources["roadways"].fields


def _minimal_attrs(fields, **overrides):
    """All fields present-but-missing by default; override individual ones."""
    attrs = {name: None for name in fields.values()}
    for key, value in overrides.items():
        attrs[fields[key]] = value
    return attrs


# --- Conditional section rendering --------------------------------------------------


def test_section_omitted_when_no_field_has_a_value(fields):
    attrs = _minimal_attrs(fields)  # everything missing
    html = build_roadway_description_html(attrs, fields)
    assert "Identity" not in html
    assert "Roadway Dimensions" not in html
    assert "ROW Reference" not in html
    assert "Operations" not in html
    assert "No attributes." in html


def test_identity_section_renders_when_hwy_present(fields):
    attrs = _minimal_attrs(fields, highway_full="IH0020")
    html = build_roadway_description_html(attrs, fields)
    assert "<h4>Identity</h4>" in html
    assert "IH0020" in html
    assert "Roadway Dimensions" not in html


def test_only_rows_with_valid_values_render_within_a_section(fields):
    attrs = _minimal_attrs(fields, highway_full="US0271", street_name=None)
    html = build_roadway_description_html(attrs, fields)
    assert "Highway" in html
    assert "Street name" not in html


# --- Coded-value decoding embedded in popup -----------------------------------------


def test_route_system_is_decoded_not_raw_code(fields):
    attrs = _minimal_attrs(fields, highway_system="IH")
    html = build_roadway_description_html(attrs, fields)
    assert "Interstate" in html
    assert "<td>IH</td>" not in html


def test_maintenance_agency_decoded(fields):
    attrs = _minimal_attrs(fields, maintenance_agency=1)
    html = build_roadway_description_html(attrs, fields)
    assert "State Highway Agency" in html


def test_unknown_code_renders_conservatively(fields):
    attrs = _minimal_attrs(fields, highway_system="ZZ")
    html = build_roadway_description_html(attrs, fields)
    assert "Unknown code (ZZ)" in html


# --- Unit formatting -----------------------------------------------------------------


def test_dimension_fields_show_units(fields):
    attrs = _minimal_attrs(fields, lane_width=10, surface_width=20)
    html = build_roadway_description_html(attrs, fields)
    assert "10 ft" in html
    assert "20 ft" in html


def test_speed_limit_shows_mph(fields):
    attrs = _minimal_attrs(fields, speed_limit=45)
    html = build_roadway_description_html(attrs, fields)
    assert "45 mph" in html


def test_valid_zero_dimension_not_treated_as_missing(fields):
    attrs = _minimal_attrs(fields, median_width=0)
    html = build_roadway_description_html(attrs, fields)
    assert "0 ft" in html
    assert "Median width" in html


# --- ROW_MIN disclaimer --------------------------------------------------------------


def test_row_min_disclaimer_appears_when_field_displayed(fields):
    attrs = _minimal_attrs(fields, row_min=360)
    html = build_roadway_description_html(attrs, fields)
    assert "360 ft" in html
    assert ROW_MIN_DISCLAIMER in html
    assert "ROW Reference" in html


def test_row_min_disclaimer_absent_when_field_missing(fields):
    attrs = _minimal_attrs(fields)  # row_min stays None
    html = build_roadway_description_html(attrs, fields)
    assert ROW_MIN_DISCLAIMER not in html
    assert "ROW Reference" not in html


# --- Never render internal null-marker representations ------------------------------


def test_no_internal_null_markers_ever_rendered(fields):
    attrs = _minimal_attrs(
        fields,
        highway_full="US0271",
        speed_limit=float("nan"),
        num_lanes=pd.NA,
        median_width=None,
    )
    html = build_roadway_description_html(attrs, fields)
    for marker in ("nan", "NaN", "<NA>", ">None<"):
        assert marker not in html


def test_no_internal_null_markers_with_all_fields_missing(fields):
    attrs = _minimal_attrs(fields)
    html = build_roadway_description_html(attrs, fields)
    for marker in ("nan", "NaN", "<NA>", ">None<"):
        assert marker not in html
