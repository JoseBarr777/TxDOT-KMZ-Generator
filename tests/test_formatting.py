from txdot_overlay.export.formatting import (
    format_count,
    format_feet,
    format_miles,
    format_mph,
    format_number,
    format_traffic_count,
)


def test_format_number_trims_unnecessary_trailing_zero():
    assert format_number(4.0) == "4"
    assert format_number(55.0) == "55"


def test_format_number_preserves_valid_zero():
    assert format_number(0) == "0"
    assert format_number(0.0) == "0"


def test_format_number_preserves_meaningful_decimals():
    assert format_number(0.257) == "0.257"
    assert format_number(0.001) == "0.001"


def test_format_number_thousands_separator():
    assert format_number(12345, thousands=True) == "12,345"
    assert format_number(1500.5, thousands=True) == "1,500.5"


def test_format_number_no_thousands_separator_by_default():
    assert format_number(12345) == "12345"


def test_format_feet_unit_suffix():
    assert format_feet(20) == "20 ft"
    assert format_feet(0) == "0 ft"  # valid zero, not blank
    assert format_feet(10.5) == "10.5 ft"


def test_format_mph_unit_suffix():
    assert format_mph(45) == "45 mph"


def test_format_miles_unit_suffix():
    assert format_miles(0.257) == "0.257 mi"


def test_format_count_no_decimals_no_thousands():
    assert format_count(2) == "2"
    assert format_count(2024) == "2024"


def test_format_traffic_count_uses_thousands_separator():
    assert format_traffic_count(50) == "50"
    assert format_traffic_count(12345) == "12,345"
