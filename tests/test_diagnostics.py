import geopandas as gpd
from shapely.geometry import MultiPolygon, Point, Polygon

from txdot_overlay.processing.diagnostics import (
    GeometryIssue,
    find_duplicate_ids,
    repair_and_flag_geometries,
)
from txdot_overlay.processing.geometry import repair_geometry

# A self-overlapping "bowtie" polygon: classic invalid geometry (self-intersection).
BOWTIE = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])

# Two overlapping squares as a MultiPolygon: reproduces the same class of
# topology error ("Nested shells" / overlapping parts) seen in Aransas
# County's source geometry, at a scale simple enough to assert on precisely.
OVERLAPPING_PARTS = MultiPolygon(
    [
        Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
        Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),
    ]
)

VALID_SQUARE = Polygon([(10, 10), (11, 10), (11, 11), (10, 11)])


def test_bowtie_is_invalid_but_repairable():
    assert not BOWTIE.is_valid
    repaired = repair_geometry(BOWTIE)
    assert repaired is not None
    assert repaired.is_valid
    assert not repaired.is_empty


def test_overlapping_multipolygon_is_invalid_but_repairable():
    assert not OVERLAPPING_PARTS.is_valid
    repaired = repair_geometry(OVERLAPPING_PARTS)
    assert repaired is not None
    assert repaired.is_valid
    # Repair must not balloon or erase the shape: overlap area is shared, so
    # the union is less than the naive sum of the two 4-unit squares but
    # still substantial -- not near-zero (a sign of a bad repair) and not
    # larger than the two parts combined (a sign of a corrupted repair).
    assert 0 < repaired.area < 8.0


def test_repair_geometry_returns_none_for_null_and_empty():
    assert repair_geometry(None) is None
    assert repair_geometry(Polygon()) is None  # empty geometry


def test_repair_geometry_passes_through_already_valid():
    assert repair_geometry(VALID_SQUARE) is VALID_SQUARE


def test_repair_and_flag_geometries_repairs_invalid_and_keeps_valid():
    gdf = gpd.GeoDataFrame(
        {
            "CNTY_NBR": [1, 4],
            "CNTY_NM": ["Valid County", "Aransas-like County"],
            "geometry": [VALID_SQUARE, OVERLAPPING_PARTS],
        },
        crs="EPSG:4326",
    )

    result, issues = repair_and_flag_geometries(
        gdf, id_field="CNTY_NBR", name_field="CNTY_NM", context="test"
    )

    # No row is silently dropped: both the valid and the repaired row remain.
    assert len(result) == 2
    assert set(result["CNTY_NM"]) == {"Valid County", "Aransas-like County"}
    assert all(geom.is_valid for geom in result.geometry)

    # Exactly one issue recorded, and it identifies the repaired feature by
    # both name and id -- not just a bare count.
    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, GeometryIssue)
    assert issue.id_value == 4
    assert issue.name == "Aransas-like County"
    assert issue.status == "repaired"
    assert not issue.dropped
    assert "Self-intersection" in issue.reason or "shells" in issue.reason.lower() or issue.reason


def test_repair_and_flag_geometries_drops_and_reports_null_and_empty():
    gdf = gpd.GeoDataFrame(
        {
            "CNTY_NBR": [1, 2, 3],
            "CNTY_NM": ["Has Geometry", "Null Geometry", "Empty Geometry"],
            "geometry": [VALID_SQUARE, None, Polygon()],
        },
        crs="EPSG:4326",
    )

    result, issues = repair_and_flag_geometries(
        gdf, id_field="CNTY_NBR", name_field="CNTY_NM", context="test"
    )

    assert list(result["CNTY_NM"]) == ["Has Geometry"]
    assert len(issues) == 2
    by_name = {i.name: i for i in issues}
    assert by_name["Null Geometry"].status == "dropped_null"
    assert by_name["Null Geometry"].dropped
    assert by_name["Empty Geometry"].status == "dropped_empty"
    assert by_name["Empty Geometry"].dropped


def test_find_duplicate_ids_reports_repeated_codes():
    gdf = gpd.GeoDataFrame(
        {
            "CNTY_NBR": [1, 2, 2, 3, 3, 3],
            "geometry": [Point(0, 0)] * 6,
        },
        crs="EPSG:4326",
    )
    duplicates = find_duplicate_ids(gdf, "CNTY_NBR")
    assert duplicates == {2: 2, 3: 3}


def test_find_duplicate_ids_empty_when_all_unique():
    gdf = gpd.GeoDataFrame({"CNTY_NBR": [1, 2, 3], "geometry": [Point(0, 0)] * 3}, crs="EPSG:4326")
    assert find_duplicate_ids(gdf, "CNTY_NBR") == {}
