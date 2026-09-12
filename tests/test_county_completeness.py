"""Regression test for the "253 vs 254 counties" acceptance bug.

build-boundaries once silently dropped Aransas County via a blanket
drop_invalid_geometries() call (invalid "Nested shells" topology). The fix
(processing/diagnostics.repair_and_flag_geometries) repairs it instead. This
test hits the real TxDOT service -- deliberately, since the bug was in how
real source data was handled, not something a synthetic fixture would catch
-- and is designed to fail loudly with the *reason* rather than pass
silently on a regression, per the "no silent discard" requirement.
"""
from __future__ import annotations

import geopandas as gpd
import pytest
import requests

from txdot_overlay.pipeline import get_cache, load_and_repair
from txdot_overlay.processing.diagnostics import find_duplicate_ids

EXPECTED_COUNTY_COUNT = 254


def test_all_254_texas_counties_are_processed(config):
    """Either all 254 counties survive (repaired if necessary), or the
    shortfall is explicitly named -- never a silent undercount.
    """
    cache = get_cache(config)
    source = config.sources["counties"]
    fields = source.fields

    try:
        final_gdf, issues, raw_gdf = load_and_repair(
            source,
            config,
            cache,
            id_field=fields["number"],
            name_field=fields["name"],
        )
    except requests.RequestException as exc:
        pytest.skip(f"Network unavailable, cannot verify against live service: {exc}")

    downloaded_count = len(raw_gdf)
    final_count = len(final_gdf)
    unique_ids = final_gdf[fields["number"]].nunique()
    duplicates = find_duplicate_ids(raw_gdf, fields["number"])
    unrepaired_drops = [i for i in issues if i.dropped]

    diagnostic = (
        f"downloaded={downloaded_count}, final={final_count}, "
        f"unique_ids={unique_ids}, duplicate_ids={duplicates}, "
        f"unrepaired_drops={[(i.name, i.id_value, i.status, i.reason) for i in unrepaired_drops]}"
    )

    assert downloaded_count == EXPECTED_COUNTY_COUNT, (
        f"Source record count changed from the expected {EXPECTED_COUNTY_COUNT}. {diagnostic}"
    )
    assert not duplicates, f"Duplicate county codes found in source data. {diagnostic}"
    assert not unrepaired_drops, (
        f"{len(unrepaired_drops)} count(y/ies) could not be repaired and were "
        f"excluded from output -- this is a real source-data omission, not a "
        f"test bug. {diagnostic}"
    )
    assert final_count == EXPECTED_COUNTY_COUNT, f"Unexpected final count. {diagnostic}"
    assert unique_ids == EXPECTED_COUNTY_COUNT, f"Unexpected unique id count. {diagnostic}"
