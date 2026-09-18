"""Field-level data-quality auditing: null/blank/sentinel counts per field.

Strictly read-only: every function here inspects a GeoDataFrame's raw values
and reports on them. Nothing is mutated, repaired, or dropped -- that keeps
this module honest as the audit's source of truth, uncontaminated by any
decision the popup renderer (export/descriptions.py) or normalization layer
(values.py) makes about what to *show*. "The audit must inspect original
values before popup normalization" is enforced structurally: this module has
no dependency on export/descriptions.py or processing/codes.py, only on the
classification primitives in values.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from txdot_overlay.values import ValueCategory, classify_value

# Above this many distinct present values, a field is treated as continuous
# / high-cardinality and its distinct values are not enumerated in the
# report (only counted) -- this is what lets "distinct coded values where
# practical" apply automatically to small coded fields (HSYS, ADMIN, ...)
# without a hardcoded field list, while skipping traffic counts, lengths, etc.
MAX_DISTINCT_VALUES_TO_LIST = 40


@dataclass
class FieldQualityReport:
    field_key: str
    field_name: str
    total_records: int
    none_count: int = 0
    pandas_na_count: int = 0
    nan_float_count: int = 0
    empty_string_count: int = 0
    whitespace_string_count: int = 0
    literal_nan_count: int = 0
    literal_null_count: int = 0
    literal_none_count: int = 0
    zero_count: int = 0
    non_null_count: int = 0
    omitted_from_popup_count: int = 0
    sentinel_candidate_values: dict[Any, int] = field(default_factory=dict)
    distinct_present_values: list[Any] | None = None
    distinct_present_value_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_key": self.field_key,
            "field_name": self.field_name,
            "total_records": self.total_records,
            "none_count": self.none_count,
            "pandas_na_count": self.pandas_na_count,
            "nan_float_count": self.nan_float_count,
            "empty_string_count": self.empty_string_count,
            "whitespace_string_count": self.whitespace_string_count,
            "literal_nan_count": self.literal_nan_count,
            "literal_null_count": self.literal_null_count,
            "literal_none_count": self.literal_none_count,
            "zero_count": self.zero_count,
            "non_null_count": self.non_null_count,
            "omitted_from_popup_count": self.omitted_from_popup_count,
            "sentinel_candidate_values": {
                str(k): v for k, v in self.sentinel_candidate_values.items()
            },
            "distinct_present_value_count": self.distinct_present_value_count,
            "distinct_present_values": (
                [str(v) for v in self.distinct_present_values]
                if self.distinct_present_values is not None
                else None
            ),
        }


_CATEGORY_COUNTER_ATTR = {
    ValueCategory.NONE_VALUE: "none_count",
    ValueCategory.PANDAS_NA: "pandas_na_count",
    ValueCategory.NAN_FLOAT: "nan_float_count",
    ValueCategory.EMPTY_STRING: "empty_string_count",
    ValueCategory.WHITESPACE_STRING: "whitespace_string_count",
    ValueCategory.LITERAL_NAN_STRING: "literal_nan_count",
    ValueCategory.LITERAL_NULL_STRING: "literal_null_count",
    ValueCategory.LITERAL_NONE_STRING: "literal_none_count",
}


def _is_zero(value: Any) -> bool:
    try:
        return value == 0
    except Exception:  # pragma: no cover - defensive against exotic types
        return False


def audit_field(series: pd.Series, *, field_key: str, field_name: str) -> FieldQualityReport:
    """Audit one column's raw values. Never touches `series` itself."""
    report = FieldQualityReport(
        field_key=field_key, field_name=field_name, total_records=len(series)
    )
    present_values: list[Any] = []

    for value in series:
        classification = classify_value(value)
        if classification.category is ValueCategory.PRESENT:
            report.non_null_count += 1
            if _is_zero(value):
                report.zero_count += 1
            if classification.is_sentinel_candidate:
                report.sentinel_candidate_values[value] = (
                    report.sentinel_candidate_values.get(value, 0) + 1
                )
            present_values.append(value)
        else:
            counter_attr = _CATEGORY_COUNTER_ATTR[classification.category]
            setattr(report, counter_attr, getattr(report, counter_attr) + 1)
            report.omitted_from_popup_count += 1

    distinct_present = sorted(set(present_values), key=lambda v: (str(type(v)), str(v)))
    report.distinct_present_value_count = len(distinct_present)
    if len(distinct_present) <= MAX_DISTINCT_VALUES_TO_LIST:
        report.distinct_present_values = distinct_present

    return report


def audit_fields(
    gdf: pd.DataFrame, fields: dict[str, str], field_keys: list[str]
) -> list[FieldQualityReport]:
    """Audit every field in `field_keys` (project keys into `fields`) present in `gdf`."""
    reports = []
    for field_key in field_keys:
        field_name = fields.get(field_key)
        if field_name is None or field_name not in gdf.columns:
            continue
        reports.append(audit_field(gdf[field_name], field_key=field_key, field_name=field_name))
    return reports
