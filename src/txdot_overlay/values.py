"""Classifies raw attribute values as present/missing/suspicious -- the single
source of truth both the popup renderer and the data-quality audit use.

Why this exists: build_county's popups were rendering literal text like
"nan" for missing roadway attributes. Traced end to end (see
docs/FIELD_REFERENCE.md "NaN trace"): ArcGIS's GeoJSON sends an explicit
JSON `null` for a missing field; after `GeoDataFrame.from_features()`,
that becomes either Python `None` (an all-null object-dtype column, e.g.
DIR_TRAV) or a bare `float('nan')` (a numeric or mixed string/null column,
e.g. SPD_MAX, HWY) -- geopandas/pandas silently pick one or the other
depending on column homogeneity, not on anything the caller controls. The
old description builder only checked `value in (None, "")`, which is False
for a NaN float (NaN != NaN), so it fell through to `str(value)` ->
literal "nan" text.

This module classifies a raw value into exactly one category, distinguishing
genuine missingness from merely *suspicious* values whose meaning is not
something this module gets to decide:

- None / pandas.NA / NumPy or Python float NaN / empty or whitespace-only
  strings are MISSING -- always omitted from popups.
- The literal source strings "nan", "null", "none" (case-insensitive) are
  flagged as suspicious -- they usually indicate upstream data was already
  stringified before reaching here, which is itself worth auditing -- but
  are still treated as missing for display, since showing a user the word
  "nan" is not meaningful, and their own text does not stand in as a
  legitimate business answer.
- Numbers matching a classic legacy sentinel shape (-1, 9, 99, 999, 9999)
  are flagged as sentinel candidates but NEVER auto-suppressed: TxDOT's own
  RIF spec documents some of these per-field (e.g. 99 = Unknown on
  HWY_STAT), and the *decoding* of "99" into an official "Unknown" label
  belongs in processing/codes.py, not here. Where no per-field decode
  exists, hiding a value just because it looks like 999 would be a guess
  this module has no authority to make, so it is left visible with the
  flag set for audit-data to surface.
- Valid zero and valid False are always PRESENT -- never treated as missing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from numbers import Number
from typing import Any

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is a hard dependency in practice
    pd = None


class ValueCategory(str, Enum):
    PRESENT = "present"
    NONE_VALUE = "none"
    PANDAS_NA = "pandas_na"
    NAN_FLOAT = "nan_float"
    EMPTY_STRING = "empty_string"
    WHITESPACE_STRING = "whitespace_string"
    LITERAL_NAN_STRING = "literal_nan_string"
    LITERAL_NULL_STRING = "literal_null_string"
    LITERAL_NONE_STRING = "literal_none_string"


MISSING_CATEGORIES = frozenset(
    {
        ValueCategory.NONE_VALUE,
        ValueCategory.PANDAS_NA,
        ValueCategory.NAN_FLOAT,
        ValueCategory.EMPTY_STRING,
        ValueCategory.WHITESPACE_STRING,
        ValueCategory.LITERAL_NAN_STRING,
        ValueCategory.LITERAL_NULL_STRING,
        ValueCategory.LITERAL_NONE_STRING,
    }
)

SUSPICIOUS_STRING_LITERALS: dict[str, ValueCategory] = {
    "nan": ValueCategory.LITERAL_NAN_STRING,
    "null": ValueCategory.LITERAL_NULL_STRING,
    "none": ValueCategory.LITERAL_NONE_STRING,
}

# Legacy-database "no data" shapes seen across transportation datasets. Not
# TxDOT-specific and not authoritative for any single field -- see the
# module docstring. Kept as a tuple (not a set of just int) so both int and
# float representations of the same magnitude are caught.
GENERIC_SENTINEL_CANDIDATES = frozenset({-1, 9, 99, 999, 9999})


@dataclass(frozen=True)
class ValueClassification:
    category: ValueCategory
    is_missing: bool
    is_suspicious_literal: bool
    is_sentinel_candidate: bool


def _is_pandas_na(value: Any) -> bool:
    if pd is None:
        return False
    try:
        return value is pd.NA
    except Exception:  # pragma: no cover - defensive
        return False


def _is_nan_float(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, float):
        return math.isnan(value)
    # numpy.float32/float64 etc. are registered as numbers.Number and behave
    # like float for isnan(), without importing numpy here directly.
    if isinstance(value, Number) and not isinstance(value, (int, complex)):
        try:
            return math.isnan(value)  # type: ignore[arg-type]
        except TypeError:  # pragma: no cover - non-float Number subtype
            return False
    return False


def classify_value(value: Any) -> ValueClassification:
    """Classify one raw attribute value. Never raises on ordinary inputs."""
    if value is None:
        return ValueClassification(ValueCategory.NONE_VALUE, True, False, False)

    if _is_pandas_na(value):
        return ValueClassification(ValueCategory.PANDAS_NA, True, False, False)

    if isinstance(value, bool):
        # Bool is an int subclass in Python; must be checked before any
        # numeric handling so a valid `False` is never treated as missing
        # or as sentinel 0/1-shaped noise.
        return ValueClassification(ValueCategory.PRESENT, False, False, False)

    if _is_nan_float(value):
        return ValueClassification(ValueCategory.NAN_FLOAT, True, False, False)

    if isinstance(value, str):
        if value == "":
            return ValueClassification(ValueCategory.EMPTY_STRING, True, False, False)
        stripped = value.strip()
        if stripped == "":
            return ValueClassification(ValueCategory.WHITESPACE_STRING, True, False, False)
        literal_category = SUSPICIOUS_STRING_LITERALS.get(stripped.lower())
        if literal_category is not None:
            return ValueClassification(literal_category, True, True, False)
        return ValueClassification(ValueCategory.PRESENT, False, False, False)

    if isinstance(value, int):
        return ValueClassification(
            ValueCategory.PRESENT, False, False, value in GENERIC_SENTINEL_CANDIDATES
        )

    if isinstance(value, Number):
        # A present, non-NaN float/numeric: sentinel-shaped only if integral.
        try:
            is_sentinel = float(value).is_integer() and int(value) in GENERIC_SENTINEL_CANDIDATES
        except (OverflowError, ValueError):  # pragma: no cover - defensive
            is_sentinel = False
        return ValueClassification(ValueCategory.PRESENT, False, False, is_sentinel)

    return ValueClassification(ValueCategory.PRESENT, False, False, False)


def is_missing_value(value: Any) -> bool:
    return classify_value(value).is_missing


def normalize_optional_value(value: Any) -> Any | None:
    """Return `value` unchanged if present, else None. Never stringifies."""
    return None if is_missing_value(value) else value
