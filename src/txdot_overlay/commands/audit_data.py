"""`audit-data`: full data-integrity report for districts, counties, and roadways.

Roadway auditing is scoped by --district/--county (like build-district and
build-county) rather than defaulting to the full statewide dataset: a full
audit downloads the same ~1M records a statewide build would, which this
project's proof-of-concept phase deliberately hasn't run yet. Without a
scope, only the cheap statewide record count is reported for reference.
"""
from __future__ import annotations

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
from txdot_overlay.processing.diagnostics import SourceAudit, build_source_audit

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


def audit_roadways_for_county(config: Config, cache, county_number: int, county_name: str) -> SourceAudit:
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
    return build_source_audit(
        source_key=f"roadways:{county_name}",
        label=f"{source.label} ({county_name} County)",
        id_field=fields["object_id"],
        source_record_count=source_count,
        raw_gdf=raw_gdf,
        final_gdf=final_gdf,
        issues=issues,
    )


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


def run(
    config: Config,
    *,
    districts_filter: list[str] | None = None,
    counties_filter: list[str] | None = None,
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

    if not scope_rows:
        statewide_count = _source_count(config, "roadways")
        print(f"=== {config.sources['roadways'].label} (statewide) ===")
        print(f"Source record count:    {statewide_count}")
        print(
            "Downloaded count:       (skipped -- pass --district/--county to audit "
            "a scope; a full statewide download is deferred until the statewide "
            "build is approved)"
        )
        return exit_code

    seen = set()
    for row in scope_rows:
        county_number = row[county_fields["number"]]
        if county_number in seen:
            continue
        seen.add(county_number)
        county_name = row[county_fields["name"]]
        road_audit = audit_roadways_for_county(config, cache, county_number, county_name)
        print(road_audit.format_report())
        print()
        if not road_audit.ok:
            exit_code = 1

    return exit_code
