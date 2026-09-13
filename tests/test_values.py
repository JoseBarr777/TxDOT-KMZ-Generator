import math

import numpy as np
import pandas as pd
import pytest

from txdot_overlay.values import (
    ValueCategory,
    classify_value,
    is_missing_value,
    normalize_optional_value,
)

# --- Missing-like representations -------------------------------------------------


@pytest.mark.parametrize(
    "value,expected_category",
    [
        (None, ValueCategory.NONE_VALUE),
        (pd.NA, ValueCategory.PANDAS_NA),
        (float("nan"), ValueCategory.NAN_FLOAT),
        (math.nan, ValueCategory.NAN_FLOAT),
        (np.nan, ValueCategory.NAN_FLOAT),
        (np.float64("nan"), ValueCategory.NAN_FLOAT),
        (np.float32("nan"), ValueCategory.NAN_FLOAT),
        ("", ValueCategory.EMPTY_STRING),
        ("   ", ValueCategory.WHITESPACE_STRING),
        ("\t\n", ValueCategory.WHITESPACE_STRING),
    ],
)
def test_null_like_representations_are_missing(value, expected_category):
    result = classify_value(value)
    assert result.category == expected_category
    assert result.is_missing is True
    assert is_missing_value(value) is True
    assert normalize_optional_value(value) is None


# --- Literal suspicious strings ----------------------------------------------------


@pytest.mark.parametrize(
    "value,expected_category",
    [
        ("nan", ValueCategory.LITERAL_NAN_STRING),
        ("NaN", ValueCategory.LITERAL_NAN_STRING),
        ("NAN", ValueCategory.LITERAL_NAN_STRING),
        ("null", ValueCategory.LITERAL_NULL_STRING),
        ("NULL", ValueCategory.LITERAL_NULL_STRING),
        ("none", ValueCategory.LITERAL_NONE_STRING),
        ("None", ValueCategory.LITERAL_NONE_STRING),
    ],
)
def test_literal_suspicious_strings_are_flagged_and_missing(value, expected_category):
    result = classify_value(value)
    assert result.category == expected_category
    assert result.is_missing is True
    assert result.is_suspicious_literal is True
    # Suspicious literals are still omitted from popups...
    assert normalize_optional_value(value) is None


def test_suspicious_literal_with_surrounding_whitespace_still_detected():
    result = classify_value("  nan  ")
    assert result.category == ValueCategory.LITERAL_NAN_STRING
    assert result.is_suspicious_literal is True


def test_ordinary_string_is_not_suspicious():
    result = classify_value("COUNTY ROAD 4622")
    assert result.category == ValueCategory.PRESENT
    assert result.is_suspicious_literal is False
    assert result.is_missing is False


# --- Valid zero and valid False must be preserved -----------------------------------


@pytest.mark.parametrize("value", [0, 0.0, np.int64(0), np.float64(0.0)])
def test_valid_zero_is_present_not_missing(value):
    result = classify_value(value)
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False
    assert normalize_optional_value(value) == 0


@pytest.mark.parametrize("value", [False, np.bool_(False)])
def test_valid_false_is_present_not_missing(value):
    result = classify_value(value)
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False
    assert result.is_sentinel_candidate is False
    assert normalize_optional_value(value) == value


def test_valid_true_is_present():
    result = classify_value(True)
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False


# --- Sentinel candidates: flagged, never auto-suppressed ----------------------------


@pytest.mark.parametrize("value", [-1, 9, 99, 999, 9999])
def test_sentinel_shaped_numbers_are_flagged_but_kept_present(value):
    result = classify_value(value)
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False  # never auto-suppressed
    assert result.is_sentinel_candidate is True
    assert normalize_optional_value(value) == value  # visible until decoded


def test_sentinel_shaped_float_also_flagged():
    result = classify_value(999.0)
    assert result.is_sentinel_candidate is True
    assert result.is_missing is False


@pytest.mark.parametrize("value", [1, 2, 55, 100, -2, 0])
def test_non_sentinel_numbers_are_not_flagged(value):
    result = classify_value(value)
    assert result.is_sentinel_candidate is False


# --- NumPy scalar types and ordinary Python values ----------------------------------


def test_numpy_integer_present_and_not_missing():
    result = classify_value(np.int64(55))
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False


def test_numpy_float_present_value():
    result = classify_value(np.float64(55.5))
    assert result.category == ValueCategory.PRESENT
    assert result.is_missing is False


def test_ordinary_int_and_float_present():
    assert classify_value(42).category == ValueCategory.PRESENT
    assert classify_value(3.14).category == ValueCategory.PRESENT


# --- Internal representations must never leak through normalize_optional_value ------


@pytest.mark.parametrize("value", [None, pd.NA, float("nan"), np.nan, "", "   "])
def test_normalize_optional_value_never_returns_internal_null_markers(value):
    result = normalize_optional_value(value)
    assert result is None
    # Defensive: whatever comes back must never stringify to a null marker.
    assert str(result) != "nan"
    assert str(result) != "NaN"
