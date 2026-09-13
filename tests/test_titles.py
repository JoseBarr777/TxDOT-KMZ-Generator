import pytest

from txdot_overlay.export.titles import (
    UNNAMED_SEGMENT_LABEL,
    format_highway_display,
    resolve_title,
)


@pytest.mark.parametrize(
    "hwy,expected",
    [
        ("US0271", "US 271"),
        ("FM0014", "FM 14"),
        ("IH0020", "IH 20"),
        ("SH0001", "SH 1"),
        ("BU0080N", "BU 80 N"),
    ],
)
def test_format_highway_display_known_shapes(hwy, expected):
    assert format_highway_display(hwy) == expected


def test_format_highway_display_falls_back_to_raw_when_unrecognized():
    assert format_highway_display("NOT-A-HWY") == "NOT-A-HWY"


# --- Title fallback order: HWY -> STE_NAM -> RIA_RTE_ID -> "Unnamed roadway segment" --


def test_title_prefers_hwy_when_present():
    title, raw = resolve_title(hwy="US0271", ste_nam="Main St", ria_rte_id="123")
    assert title == "US 271"
    assert raw == "US0271"  # preserved because formatting changed it


def test_title_falls_back_to_ste_nam_when_hwy_missing():
    title, raw = resolve_title(hwy=None, ste_nam="COUNTY ROAD 4622", ria_rte_id="123")
    assert title == "COUNTY ROAD 4622"
    assert raw is None


def test_title_falls_back_to_ste_nam_when_hwy_is_nan_float():
    title, raw = resolve_title(hwy=float("nan"), ste_nam="MAIN ST", ria_rte_id="123")
    assert title == "MAIN ST"


def test_title_falls_back_to_ria_rte_id_when_hwy_and_ste_nam_missing():
    title, raw = resolve_title(hwy=None, ste_nam=None, ria_rte_id="1599254295")
    assert title == "1599254295"
    assert raw is None


def test_title_falls_back_to_unnamed_when_everything_missing():
    title, raw = resolve_title(hwy=None, ste_nam=None, ria_rte_id=None)
    assert title == UNNAMED_SEGMENT_LABEL


def test_title_falls_back_when_all_values_are_blank_or_suspicious_strings():
    title, _ = resolve_title(hwy="", ste_nam="   ", ria_rte_id="nan")
    assert title == UNNAMED_SEGMENT_LABEL


def test_title_never_returns_missing_value_as_title():
    # A missing value must never become the popup title, in any fallback slot.
    for hwy, ste_nam, ria_rte_id in [
        (None, None, None),
        (float("nan"), float("nan"), float("nan")),
        ("", "", ""),
    ]:
        title, _ = resolve_title(hwy=hwy, ste_nam=ste_nam, ria_rte_id=ria_rte_id)
        assert title == UNNAMED_SEGMENT_LABEL
        assert title.strip() != ""
        assert "nan" not in title.lower()
