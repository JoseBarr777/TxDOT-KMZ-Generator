import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from txdot_overlay.processing.geometry import (
    WGS84_EPSG,
    drop_invalid_geometries,
    ensure_wgs84,
    geojson_to_geodataframe,
    simplify_geometry,
)

# Austin, TX (approx.) for round-tripping between coordinate systems.
AUSTIN_LON, AUSTIN_LAT = -97.7431, 30.2672


def test_ensure_wgs84_noop_when_already_4326():
    gdf = gpd.GeoDataFrame({"geometry": [Point(AUSTIN_LON, AUSTIN_LAT)]}, crs="EPSG:4326")
    result = ensure_wgs84(gdf)
    assert result.crs.to_epsg() == WGS84_EPSG
    assert result.geometry.iloc[0].x == pytest.approx(AUSTIN_LON)
    assert result.geometry.iloc[0].y == pytest.approx(AUSTIN_LAT)


def test_ensure_wgs84_reprojects_from_web_mercator():
    gdf = gpd.GeoDataFrame({"geometry": [Point(AUSTIN_LON, AUSTIN_LAT)]}, crs="EPSG:4326")
    web_mercator = gdf.to_crs(epsg=3857)
    assert web_mercator.crs.to_epsg() == 3857

    reprojected = ensure_wgs84(web_mercator)
    assert reprojected.crs.to_epsg() == WGS84_EPSG
    assert reprojected.geometry.iloc[0].x == pytest.approx(AUSTIN_LON, abs=1e-6)
    assert reprojected.geometry.iloc[0].y == pytest.approx(AUSTIN_LAT, abs=1e-6)


def test_ensure_wgs84_reprojects_from_nad83():
    """NAD83 (EPSG:4269), the roadway inventory's native SRS, to WGS84."""
    gdf = gpd.GeoDataFrame({"geometry": [Point(AUSTIN_LON, AUSTIN_LAT)]}, crs="EPSG:4269")
    reprojected = ensure_wgs84(gdf)
    assert reprojected.crs.to_epsg() == WGS84_EPSG
    # NAD83 -> WGS84 shift is sub-meter in Texas; coordinates barely move.
    assert reprojected.geometry.iloc[0].x == pytest.approx(AUSTIN_LON, abs=1e-5)
    assert reprojected.geometry.iloc[0].y == pytest.approx(AUSTIN_LAT, abs=1e-5)


def test_ensure_wgs84_assigns_crs_when_missing():
    gdf = gpd.GeoDataFrame({"geometry": [Point(AUSTIN_LON, AUSTIN_LAT)]})
    assert gdf.crs is None
    result = ensure_wgs84(gdf)
    assert result.crs.to_epsg() == WGS84_EPSG


def test_geojson_to_geodataframe_is_wgs84():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [AUSTIN_LON, AUSTIN_LAT]},
                "properties": {"name": "test"},
            }
        ],
    }
    gdf = geojson_to_geodataframe(geojson)
    assert gdf.crs.to_epsg() == WGS84_EPSG
    assert len(gdf) == 1


def test_drop_invalid_geometries_removes_none_and_empty():
    gdf = gpd.GeoDataFrame(
        {"geometry": [Point(0, 0), None, LineString([])]}, crs="EPSG:4326"
    )
    result = drop_invalid_geometries(gdf)
    assert len(result) == 1


def test_simplify_geometry_reduces_or_preserves_vertex_count():
    # A wiggly line that simplify() should be able to collapse.
    coords = [(0, 0), (0.0001, 0.00005), (0.0002, 0), (0.0003, 0.00005), (0.0004, 0)]
    gdf = gpd.GeoDataFrame({"geometry": [LineString(coords)]}, crs="EPSG:4326")
    simplified = simplify_geometry(gdf, tolerance_degrees=0.001)
    assert len(list(simplified.geometry.iloc[0].coords)) <= len(coords)


def test_simplify_geometry_noop_with_zero_tolerance():
    coords = [(0, 0), (1, 1)]
    gdf = gpd.GeoDataFrame({"geometry": [LineString(coords)]}, crs="EPSG:4326")
    result = simplify_geometry(gdf, tolerance_degrees=0)
    assert list(result.geometry.iloc[0].coords) == coords
