"""Per-feature geometry auditing: repair what's safely repairable, and never
drop a feature without recording who it was, what was wrong, and why it's gone.

This exists because build-boundaries silently dropped Aransas County (a
geometrically invalid but otherwise legitimate record) via a blanket
drop_invalid_geometries() call, and undercounted 254 Texas counties as 253
with no trace of which one or why. Every non-"ok" row now produces a
GeometryIssue that survives into logs and the audit-data report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
from shapely.validation import explain_validity

from txdot_overlay.logging_setup import get_logger
from txdot_overlay.processing.geometry import repair_geometry

logger = get_logger(__name__)

DROPPED_STATUSES = {"dropped_null", "dropped_empty", "dropped_invalid"}


@dataclass
class GeometryIssue:
    id_value: Any
    name: Any
    status: str  # "repaired" | "dropped_null" | "dropped_empty" | "dropped_invalid"
    reason: str

    @property
    def dropped(self) -> bool:
        return self.status in DROPPED_STATUSES


def repair_and_flag_geometries(
    gdf: gpd.GeoDataFrame, *, id_field: str, name_field: str, context: str = ""
) -> tuple[gpd.GeoDataFrame, list[GeometryIssue]]:
    """Classify every row's geometry, repairing invalid-but-fixable ones.

    Returns (gdf_with_repairs_applied_and_unfixable_rows_removed, issues).
    `issues` contains one entry per row that was NOT plain "ok" -- repaired
    rows are included (they're notable) alongside dropped ones, so nothing
    that deviates from a clean valid geometry disappears without a record.
    """
    if gdf.empty:
        return gdf, []

    issues: list[GeometryIssue] = []
    final_geoms: list[Any] = []
    keep_mask: list[bool] = []

    for geom, id_value, name in zip(gdf.geometry, gdf[id_field], gdf[name_field]):
        if geom is None:
            issues.append(GeometryIssue(id_value, name, "dropped_null", "geometry is null"))
            keep_mask.append(False)
            final_geoms.append(None)
            logger.error("%s: dropping %s (id=%s): geometry is null", context, name, id_value)
            continue

        if geom.is_empty:
            issues.append(GeometryIssue(id_value, name, "dropped_empty", "geometry is empty"))
            keep_mask.append(False)
            final_geoms.append(None)
            logger.error("%s: dropping %s (id=%s): geometry is empty", context, name, id_value)
            continue

        if not geom.is_valid:
            reason = explain_validity(geom)
            repaired = repair_geometry(geom)
            if repaired is not None:
                issues.append(GeometryIssue(id_value, name, "repaired", reason))
                keep_mask.append(True)
                final_geoms.append(repaired)
                logger.warning(
                    "%s: repaired invalid geometry for %s (id=%s): %s",
                    context,
                    name,
                    id_value,
                    reason,
                )
            else:
                issues.append(GeometryIssue(id_value, name, "dropped_invalid", reason))
                keep_mask.append(False)
                final_geoms.append(None)
                logger.error(
                    "%s: dropping unrepairable geometry for %s (id=%s): %s",
                    context,
                    name,
                    id_value,
                    reason,
                )
            continue

        keep_mask.append(True)
        final_geoms.append(geom)

    result = gdf.copy()
    result["geometry"] = gpd.GeoSeries(final_geoms, index=gdf.index, crs=gdf.crs)
    result = result[keep_mask]
    return result, issues


def find_duplicate_ids(gdf: gpd.GeoDataFrame, id_field: str) -> dict[Any, int]:
    """Return {id_value: count} for every id that appears more than once."""
    if gdf.empty:
        return {}
    counts = gdf[id_field].value_counts()
    return {k: int(v) for k, v in counts[counts > 1].items()}


@dataclass
class SourceAudit:
    """Full data-integrity picture for one source (or one scoped slice of one)."""

    source_key: str
    label: str
    source_record_count: int | None  # None if not queried (e.g. skipped statewide)
    downloaded_record_count: int
    unique_id_count: int
    duplicate_ids: dict[Any, int]
    null_geometry_count: int
    empty_geometry_count: int
    invalid_geometry_count: int  # includes both repaired and unrepaired
    repaired_geometry_count: int
    dropped_count: int
    final_exported_count: int
    dropped_details: list[GeometryIssue]

    @property
    def ok(self) -> bool:
        return not self.duplicate_ids and not self.dropped_details

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "label": self.label,
            "source_record_count": self.source_record_count,
            "downloaded_record_count": self.downloaded_record_count,
            "unique_id_count": self.unique_id_count,
            "duplicate_ids": {str(k): v for k, v in self.duplicate_ids.items()},
            "null_geometry_count": self.null_geometry_count,
            "empty_geometry_count": self.empty_geometry_count,
            "invalid_geometry_count": self.invalid_geometry_count,
            "repaired_geometry_count": self.repaired_geometry_count,
            "dropped_count": self.dropped_count,
            "final_exported_count": self.final_exported_count,
            "dropped_details": [
                {
                    "id_value": str(i.id_value),
                    "name": str(i.name),
                    "status": i.status,
                    "reason": i.reason,
                }
                for i in self.dropped_details
            ],
        }

    def format_report(self) -> str:
        lines = [f"=== {self.label} ({self.source_key}) ==="]
        if self.source_record_count is not None:
            lines.append(f"Source record count:    {self.source_record_count}")
            if self.source_record_count != self.downloaded_record_count:
                lines.append(
                    f"  WARNING: downloaded count ({self.downloaded_record_count}) "
                    f"!= source count ({self.source_record_count})"
                )
        else:
            lines.append("Source record count:    (not queried)")
        lines.append(f"Downloaded count:       {self.downloaded_record_count}")
        lines.append(f"Unique IDs:             {self.unique_id_count}")
        lines.append(f"Duplicate IDs:          {len(self.duplicate_ids)}")
        for id_value, count in self.duplicate_ids.items():
            lines.append(f"  DUPLICATE id={id_value} appears {count} times")
        lines.append(f"Null geometries:        {self.null_geometry_count}")
        lines.append(f"Empty geometries:       {self.empty_geometry_count}")
        lines.append(f"Invalid geometries:     {self.invalid_geometry_count}")
        lines.append(f"Repaired geometries:    {self.repaired_geometry_count}")
        lines.append(f"Dropped (unrepairable): {self.dropped_count}")
        for issue in self.dropped_details:
            lines.append(
                f"  DROPPED {issue.name!r} (id={issue.id_value}): {issue.status}: {issue.reason}"
            )
        lines.append(f"Final exported count:   {self.final_exported_count}")
        return "\n".join(lines)


def build_source_audit(
    *,
    source_key: str,
    label: str,
    id_field: str,
    source_record_count: int | None,
    raw_gdf: gpd.GeoDataFrame,
    final_gdf: gpd.GeoDataFrame,
    issues: list[GeometryIssue],
) -> SourceAudit:
    """Assemble a SourceAudit from what load_and_repair already computed."""
    duplicate_ids = find_duplicate_ids(raw_gdf, id_field)
    null_count = sum(1 for i in issues if i.status == "dropped_null")
    empty_count = sum(1 for i in issues if i.status == "dropped_empty")
    repaired_count = sum(1 for i in issues if i.status == "repaired")
    dropped_invalid_count = sum(1 for i in issues if i.status == "dropped_invalid")
    dropped_details = [i for i in issues if i.dropped]

    return SourceAudit(
        source_key=source_key,
        label=label,
        source_record_count=source_record_count,
        downloaded_record_count=len(raw_gdf),
        unique_id_count=int(raw_gdf[id_field].nunique()) if not raw_gdf.empty else 0,
        duplicate_ids=duplicate_ids,
        null_geometry_count=null_count,
        empty_geometry_count=empty_count,
        invalid_geometry_count=repaired_count + dropped_invalid_count,
        repaired_geometry_count=repaired_count,
        dropped_count=len(dropped_details),
        final_exported_count=len(final_gdf),
        dropped_details=dropped_details,
    )
