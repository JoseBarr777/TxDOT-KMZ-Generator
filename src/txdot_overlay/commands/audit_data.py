"""`audit-data`: full data-integrity report for districts, counties, and roadways.

Roadway auditing is scoped by --district/--county (like build-district and
build-county) rather than defaulting to the full statewide dataset: a full
audit downloads the same ~1M records a statewide build would, which this
project's proof-of-concept phase deliberately hasn't run yet. Without a
scope, only the cheap statewide record count is reported for reference.

When a roadway scope is given, this also runs the field-level data-quality
audit (processing/value_audit.py) and roadway classification tally
(processing/classify.py) across the combined scope, and writes a
machine-readable report to disk (default: dist/audits/<scope>_data_quality.json).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from txdot_overlay.acquisition.arcgis_client import ArcGISLayerClient
from txdot_overlay.config import Config
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import (
    counties_in_district,
    find_county_row,
    find_district_row,
    get_cache,
    load_and_repair,
    load_counties,
    load_districts,
)
from txdot_overlay.processing.classify import PhysicalRoadType, classify_physical_type
from txdot_overlay.processing.codes import decode_admin_agency
from txdot_overlay.processing.diagnostics import SourceAudit, build_source_audit
from txdot_overlay.processing.value_audit import audit_fields
from txdot_overlay.utils import slugify

logger = get_logger(__name__)


def _source_count(config: Config, source_key: str, where: str = "1=1") -> int | None:
    source = config.sources[source_key]
    client = ArcGISLayerClient(
        source.layer_url,
        timeout_seconds=config.network_timeout_seconds,
        max_retries=config.network_max_retries,
        retry_backoff_seconds=config.network_retry_backoff_seconds,
    )
    try:
        return client.count(where)
    except Exception as exc:  # noqa: BLE001 - audit should degrade, not crash
        logger.error("Could not query source record count for %s: %s", source.label, exc)
        return None


def audit_districts(config: Config, cache) -> SourceAudit:
    source = config.sources["districts"]
    fields = source.fields
    final_gdf, issues, raw_gdf = load_and_repair(
        source, config, cache, id_field=fields["number"], name_field=fields["name"]
    )
    source_count = _source_count(config, "districts")
    return build_source_audit(
        source_key="districts",
        label=source.label,
        id_field=fields["number"],
        source_record_count=source_count,
        raw_gdf=raw_gdf,
        final_gdf=final_gdf,
        issues=issues,
    )


def audit_counties(config: Config, cache) -> SourceAudit:
    source = config.sources["counties"]
    fields = source.fields
    final_gdf, issues, raw_gdf = load_and_repair(
        source, config, cache, id_field=fields["number"], name_field=fields["name"]
    )
    source_count = _source_count(config, "counties")
    return build_source_audit(
        source_key="counties",
        label=source.label,
        id_field=fields["number"],
        source_record_count=source_count,
        raw_gdf=raw_gdf,
        final_gdf=final_gdf,
        issues=issues,
    )


def audit_roadways_for_county(
    config: Config, cache, county_number: int, county_name: str
) -> tuple[SourceAudit, pd.DataFrame]:
    source = config.sources["roadways"]
    fields = source.fields
    where = f"{fields['county_code']} = {int(county_number)}"
    final_gdf, issues, raw_gdf = load_and_repair(
        source,
        config,
        cache,
        id_field=fields["object_id"],
        name_field=fields["highway_full"],
        where=where,
    )
    source_count = _source_count(config, "roadways", where=where)
    audit = build_source_audit(
        source_key=f"roadways:{county_name}",
        label=f"{source.label} ({county_name} County)",
        id_field=fields["object_id"],
        source_record_count=source_count,
        raw_gdf=raw_gdf,
        final_gdf=final_gdf,
        issues=issues,
    )
    return audit, raw_gdf


def _resolve_roadway_scope(config, districts_filter, counties_filter, districts_gdf, counties_gdf):
    """Return a list of county rows to audit roadways for, or [] if none requested."""
    scope = []
    if counties_filter:
        for county_name in counties_filter:
            scope.append(find_county_row(counties_gdf, config, county_name))
    if districts_filter:
        for district_name in districts_filter:
            find_district_row(districts_gdf, config, district_name)  # validates it exists
            district_counties = counties_in_district(counties_gdf, config, district_name)
            scope.extend(row for _, row in district_counties.iterrows())
    return scope


def _classification_tally(combined_roadways: pd.DataFrame, fields: dict[str, str]) -> dict[str, int]:
    hsys_col = fields["highway_system"]
    rdbd_col = fields["roadbed_id"]
    counts: dict[str, int] = {t.value: 0 for t in PhysicalRoadType}
    for hsys, rdbd_id in zip(combined_roadways[hsys_col], combined_roadways[rdbd_col]):
        counts[classify_physical_type(hsys=hsys, rdbd_id=rdbd_id).value] += 1
    return counts


def _maintenance_agency_tally(combined_roadways: pd.DataFrame, fields: dict[str, str]) -> dict[str, int]:
    agency_col = fields["maintenance_agency"]
    counts: dict[str, int] = {}
    for raw in combined_roadways[agency_col]:
        label = decode_admin_agency(raw) or "(missing)"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _scope_label(districts_filter: list[str] | None, counties_filter: list[str] | None) -> str:
    parts = [slugify(d) for d in (districts_filter or [])] + [
        slugify(c) for c in (counties_filter or [])
    ]
    return "_".join(parts) if parts else "scope"


def run(
    config: Config,
    *,
    districts_filter: list[str] | None = None,
    counties_filter: list[str] | None = None,
    audit_output_dir: Path | None = None,
) -> int:
    cache = get_cache(config)

    districts_gdf = load_districts(config, cache)
    counties_gdf = load_counties(config, cache)

    district_audit = audit_districts(config, cache)
    county_audit = audit_counties(config, cache)

    print(district_audit.format_report())
    print()
    print(county_audit.format_report())
    print()

    exit_code = 0 if district_audit.ok and county_audit.ok else 1

    scope_rows = _resolve_roadway_scope(
        config, districts_filter, counties_filter, districts_gdf, counties_gdf
    )
    county_fields = config.sources["counties"].fields
    road_fields = config.sources["roadways"].fields

    report_payload: dict[str, Any] = {
        "districts": district_audit.to_dict(),
        "counties": county_audit.to_dict(),
        "roadways_by_county": [],
        "field_quality": [],
        "physical_type_counts": {},
        "maintenance_agency_counts": {},
    }

    if not scope_rows:
        statewide_count = _source_count(config, "roadways")
        print(f"=== {config.sources['roadways'].label} (statewide) ===")
        print(f"Source record count:    {statewide_count}")
        print(
            "Downloaded count:       (skipped -- pass --district/--county to audit "
            "a scope; a full statewide download is deferred until the statewide "
            "build is approved)"
        )
        report_payload["roadways_statewide_source_record_count"] = statewide_count
    else:
        seen = set()
        raw_frames: list[pd.DataFrame] = []
        for row in scope_rows:
            county_number = row[county_fields["number"]]
            if county_number in seen:
                continue
            seen.add(county_number)
            county_name = row[county_fields["name"]]
            road_audit, raw_gdf = audit_roadways_for_county(config, cache, county_number, county_name)
            print(road_audit.format_report())
            print()
            if not road_audit.ok:
                exit_code = 1
            report_payload["roadways_by_county"].append(road_audit.to_dict())
            raw_frames.append(raw_gdf)

        combined = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame()
        if not combined.empty:
            field_reports = audit_fields(combined, road_fields, list(road_fields.keys()))
            report_payload["field_quality"] = [r.to_dict() for r in field_reports]

            physical_counts = _classification_tally(combined, road_fields)
            report_payload["physical_type_counts"] = physical_counts
            print("=== Physical-type classification (combined scope) ===")
            for category, count in physical_counts.items():
                print(f"  {category}: {count}")
            print()

            agency_counts = _maintenance_agency_tally(combined, road_fields)
            report_payload["maintenance_agency_counts"] = agency_counts
            print("=== Decoded maintenance agency (combined scope) ===")
            for label, count in agency_counts.items():
                print(f"  {label}: {count}")
            print()

    output_dir = audit_output_dir or (Path.cwd() / "dist" / "audits")
    output_dir.mkdir(parents=True, exist_ok=True)
    scope_label = _scope_label(districts_filter, counties_filter)
    output_path = output_dir / f"{scope_label}_data_quality.json"
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(report_payload, fh, indent=2, default=str)
    print(f"Machine-readable report written to {output_path}")

    return exit_code
