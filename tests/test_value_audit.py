import pandas as pd
import pytest

from txdot_overlay.processing.value_audit import audit_field, audit_fields


def test_audit_field_counts_each_missing_category():
    series = pd.Series([None, pd.NA, float("nan"), "", "  ", "nan", "null", "none", 5, 5])
    report = audit_field(series, field_key="test", field_name="TEST")

    assert report.total_records == 10
    assert report.none_count == 1
    assert report.pandas_na_count == 1
    assert report.nan_float_count == 1
    assert report.empty_string_count == 1
    assert report.whitespace_string_count == 1
    assert report.literal_nan_count == 1
    assert report.literal_null_count == 1
    assert report.literal_none_count == 1
    assert report.non_null_count == 2
    assert report.omitted_from_popup_count == 8


def test_audit_field_zero_count_preserves_valid_zero():
    series = pd.Series([0, 0, 1, None])
    report = audit_field(series, field_key="z", field_name="Z")
    assert report.zero_count == 2
    assert report.non_null_count == 3


def test_audit_field_sentinel_candidates_tracked_with_counts():
    series = pd.Series([99, 99, 1, 2, 999])
    report = audit_field(series, field_key="s", field_name="S")
    assert report.sentinel_candidate_values == {99: 2, 999: 1}
    # Sentinels remain counted as present/non-null -- never silently dropped.
    assert report.non_null_count == 5


def test_audit_field_distinct_values_listed_for_low_cardinality():
    series = pd.Series(["IH", "US", "IH", "SH"])
    report = audit_field(series, field_key="hsys", field_name="HSYS")
    assert report.distinct_present_value_count == 3
    assert set(report.distinct_present_values) == {"IH", "US", "SH"}


def test_audit_field_distinct_values_omitted_for_high_cardinality():
    series = pd.Series(range(1000))
    report = audit_field(series, field_key="cont", field_name="CONT")
    assert report.distinct_present_value_count == 1000
    assert report.distinct_present_values is None


def test_audit_field_never_mutates_input_series():
    series = pd.Series([None, 1, "nan"])
    original = series.copy()
    audit_field(series, field_key="f", field_name="F")
    pd.testing.assert_series_equal(series, original)


def test_audit_field_to_dict_is_json_serializable():
    import json

    series = pd.Series([1, None, "nan"])
    report = audit_field(series, field_key="f", field_name="F")
    payload = json.dumps(report.to_dict())
    assert "f" in payload


def test_audit_fields_skips_absent_columns():
    gdf = pd.DataFrame({"HSYS": ["IH", "US"]})
    fields = {"highway_system": "HSYS", "missing_key": "NOT_A_COLUMN"}
    reports = audit_fields(gdf, fields, list(fields.keys()))
    assert len(reports) == 1
    assert reports[0].field_key == "highway_system"
