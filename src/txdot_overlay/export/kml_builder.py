"""Builds the master KML and per-county detail KML documents.

Structure produced (see README/docs for the full design):

    TxDOT Reference Overlay                     (Document, master.kml)
      District Boundaries                       (Folder, visible)
        <District> polygon placemark x25        (visible)
      District Details                          (Folder, hidden)
        <District> folder x25                   (hidden)
          NetworkLink -> districts/<d>/<c>.kmz   (hidden, one per county)

    <County> (Document, districts/<d>/<c>.kmz)
      County Boundary                           (Folder)
        <County> polygon placemark
      TxDOT Roadways                            (Folder)
        <Route category> folder                 (one per physical category present)
          <route> line placemark(s)
      Reference Geometry                        (Folder, hidden)
        Grade-Separated Connectors              (Folder, hidden)
          <connector> line placemark(s)          (RDBD_ID=GS, officially
                                                   decoded "Grade Separated
                                                   Connector"; excluded from
                                                   TxDOT Roadways' folders and
                                                   from physical-road counts)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import simplekml

from txdot_overlay.config import Config
from txdot_overlay.export.descriptions import build_description_html, build_roadway_description_html
from txdot_overlay.export.geometry_adapter import add_line_placemark, add_polygon_placemark
from txdot_overlay.export.titles import resolve_title
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.processing.classify import GRADE_SEPARATED_CONNECTOR_STYLE_KEY
from txdot_overlay.utils import slugify

logger = get_logger(__name__)


def _render_geometry(geometry, tolerance_degrees: float):
    """Simplify a geometry for rendering only; never mutates data used for analysis.

    Boundary polygons are only drawn as outlines here, so a coarser tolerance
    than roadway geometry is safe -- see config.yaml's simplification block.
    """
    if tolerance_degrees <= 0 or geometry is None or geometry.is_empty:
        return geometry
    return geometry.simplify(tolerance_degrees, preserve_topology=True)

# Physical-road categories only; grade_separated_connector is deliberately
# excluded -- it never appears under "TxDOT Roadways", only under
# "Reference Geometry" (see add_county_detail_content).
ROUTE_CATEGORY_ORDER = [
    "interstate",
    "us_highway",
    "state_highway",
    "fm_rm",
    "loop_spur_business",
    "county_local_other",
]


def county_kmz_relative_path(district_name: str, county_name: str) -> Path:
    """The path (relative to the output directory) a county's detail KMZ lives at."""
    return Path("districts") / slugify(district_name) / f"{slugify(county_name)}.kmz"


def build_district_boundaries_folder(
    parent: Any,
    districts: gpd.GeoDataFrame,
    config: Config,
    styles: dict[str, simplekml.Style],
) -> simplekml.Folder:
    """Add the "District Boundaries" folder as a child of `parent` (e.g. kml.document)."""
    fields = config.sources["districts"].fields
    folder = parent.newfolder(name="District Boundaries")
    folder.visibility = 1 if config.visibility_defaults["district_boundaries_folder"] else 0

    skipped = 0
    for _, row in districts.iterrows():
        name = row[fields["name"]]
        if row.geometry is None or row.geometry.is_empty:
            skipped += 1
            continue
        description = build_description_html(
            row.to_dict(), config.sources["districts"].description_fields
        )
        add_polygon_placemark(
            folder,
            name=str(name),
            geometry=_render_geometry(
                row.geometry, config.district_boundary_tolerance_degrees
            ),
            style=styles["district_boundary"],
            description=description,
            visibility=config.visibility_defaults["district_placemarks"],
        )
    if skipped:
        logger.warning("Skipped %d district(s) with missing/empty geometry", skipped)
    return folder


def build_district_details_folder(
    parent: Any,
    districts: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
    config: Config,
) -> simplekml.Folder:
    """Add the "District Details" folder as a child of `parent` (e.g. kml.document)."""
    district_fields = config.sources["districts"].fields
    county_fields = config.sources["counties"].fields

    details_folder = parent.newfolder(name="District Details")
    details_folder.visibility = (
        1 if config.visibility_defaults["district_details_folder"] else 0
    )

    district_names = sorted(districts[district_fields["name"]].dropna().unique())
    for district_name in district_names:
        district_folder = details_folder.newfolder(name=str(district_name))
        district_folder.visibility = (
            1 if config.visibility_defaults["district_detail_folder"] else 0
        )

        district_counties = counties[
            counties[county_fields["district_name"]] == district_name
        ].sort_values(county_fields["name"])

        for _, county_row in district_counties.iterrows():
            county_name = county_row[county_fields["name"]]
            relative_path = county_kmz_relative_path(district_name, county_name)
            network_link = district_folder.newnetworklink(name=str(county_name))
            network_link.link.href = relative_path.as_posix()
            network_link.link.refreshmode = simplekml.RefreshMode.onchange
            network_link.visibility = 1 if config.visibility_defaults["county_folder"] else 0

    return details_folder


def build_master_kml(
    districts: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
    config: Config,
    styles: dict[str, simplekml.Style],
) -> simplekml.Kml:
    kml = simplekml.Kml()
    kml.document.name = "TxDOT Reference Overlay"

    build_district_boundaries_folder(kml.document, districts, config, styles)
    build_district_details_folder(kml.document, districts, counties, config)
    return kml


def add_county_detail_content(
    parent_folder: Any,
    *,
    county_name: str,
    county_attrs: dict[str, Any],
    county_geometry,
    roadways: gpd.GeoDataFrame,
    config: Config,
    styles: dict[str, simplekml.Style],
) -> None:
    """Add "County Boundary" + "TxDOT Roadways" folders directly under `parent_folder`.

    Shares the same folder layout as build_county_detail_kml's Document, but
    writes into an existing container instead of a new Kml() -- used by the
    single-file (inline, no NetworkLinks) export.
    """
    boundary_folder = parent_folder.newfolder(name="County Boundary")
    boundary_folder.visibility = (
        1 if config.visibility_defaults["county_boundary_folder"] else 0
    )
    add_polygon_placemark(
        boundary_folder,
        name=f"{county_name} County",
        geometry=_render_geometry(county_geometry, config.county_boundary_tolerance_degrees),
        style=styles["county_boundary"],
        description=build_description_html(
            county_attrs, config.sources["counties"].description_fields
        ),
        visibility=True,
    )

    road_fields = config.sources["roadways"].fields
    is_connector = roadways["route_category"] == GRADE_SEPARATED_CONNECTOR_STYLE_KEY
    physical_roadways = roadways[~is_connector]
    grade_separated_connectors = roadways[is_connector]

    roadways_folder = parent_folder.newfolder(name="TxDOT Roadways")
    roadways_folder.visibility = (
        1 if config.visibility_defaults["roadways_folder"] else 0
    )
    _add_route_category_folders(
        roadways_folder, physical_roadways, road_fields, config, styles
    )

    if len(grade_separated_connectors):
        reference_folder = parent_folder.newfolder(name="Reference Geometry")
        reference_folder.visibility = (
            1 if config.visibility_defaults["reference_geometry_folder"] else 0
        )
        connector_folder = reference_folder.newfolder(name="Grade-Separated Connectors")
        connector_folder.visibility = (
            1 if config.visibility_defaults["grade_separated_connectors_folder"] else 0
        )
        _add_roadway_placemarks(
            connector_folder,
            grade_separated_connectors,
            road_fields,
            styles[f"route_{GRADE_SEPARATED_CONNECTOR_STYLE_KEY}"],
        )


def _add_route_category_folders(
    roadways_folder: Any,
    physical_roadways: gpd.GeoDataFrame,
    road_fields: dict[str, str],
    config: Config,
    styles: dict[str, simplekml.Style],
) -> None:
    present_categories = set(physical_roadways.get("route_category", []))
    for category in ROUTE_CATEGORY_ORDER:
        if category not in present_categories:
            continue
        category_rows = physical_roadways[physical_roadways["route_category"] == category]
        label = config.route_styles[category].label
        category_folder = roadways_folder.newfolder(name=label)
        category_folder.visibility = (
            1 if config.visibility_defaults["route_category_folder"] else 0
        )
        _add_roadway_placemarks(
            category_folder, category_rows, road_fields, styles[f"route_{category}"]
        )


def _add_roadway_placemarks(
    container: Any,
    rows: gpd.GeoDataFrame,
    road_fields: dict[str, str],
    style: simplekml.Style,
) -> None:
    for _, row in rows.iterrows():
        if row.geometry is None or row.geometry.is_empty:
            continue
        attrs = row.to_dict()
        title, _raw_identifier = resolve_title(
            hwy=attrs.get(road_fields["highway_full"]),
            ste_nam=attrs.get(road_fields["street_name"]),
            ria_rte_id=attrs.get(road_fields["route_id"]),
        )
        description = build_roadway_description_html(attrs, road_fields)
        add_line_placemark(
            container,
            name=title,
            geometry=row.geometry,
            style=style,
            description=description,
            visibility=True,
        )


def build_single_file_kml(
    districts: gpd.GeoDataFrame,
    counties: gpd.GeoDataFrame,
    county_roadways: dict[str, gpd.GeoDataFrame],
    config: Config,
    styles: dict[str, simplekml.Style],
) -> simplekml.Kml:
    """Build one self-contained KML with everything inlined (no NetworkLinks).

    Intended for small-scope comparison/testing, not the statewide dataset --
    `county_roadways` should only contain the counties actually built this run.
    """
    county_fields = config.sources["counties"].fields

    kml = simplekml.Kml()
    kml.document.name = "TxDOT Reference Overlay (Single File)"

    build_district_boundaries_folder(kml.document, districts, config, styles)

    details_folder = kml.document.newfolder(name="District Details")
    details_folder.visibility = (
        1 if config.visibility_defaults["district_details_folder"] else 0
    )

    in_scope_counties = counties[counties[county_fields["name"]].isin(county_roadways)]
    district_names = sorted(in_scope_counties[county_fields["district_name"]].dropna().unique())

    for district_name in district_names:
        district_folder = details_folder.newfolder(name=str(district_name))
        district_folder.visibility = (
            1 if config.visibility_defaults["district_detail_folder"] else 0
        )
        district_counties = in_scope_counties[
            in_scope_counties[county_fields["district_name"]] == district_name
        ].sort_values(county_fields["name"])

        for _, county_row in district_counties.iterrows():
            county_name = county_row[county_fields["name"]]
            county_folder = district_folder.newfolder(name=str(county_name))
            county_folder.visibility = 1 if config.visibility_defaults["county_folder"] else 0
            add_county_detail_content(
                county_folder,
                county_name=county_name,
                county_attrs=county_row.to_dict(),
                county_geometry=county_row.geometry,
                roadways=county_roadways[county_name],
                config=config,
                styles=styles,
            )

    return kml


def build_county_detail_kml(
    *,
    district_name: str,
    county_name: str,
    county_attrs: dict[str, Any],
    county_geometry,
    roadways: gpd.GeoDataFrame,
    config: Config,
    styles: dict[str, simplekml.Style],
) -> simplekml.Kml:
    kml = simplekml.Kml()
    kml.document.name = f"{county_name} County"

    add_county_detail_content(
        kml.document,
        county_name=county_name,
        county_attrs=county_attrs,
        county_geometry=county_geometry,
        roadways=roadways,
        config=config,
        styles=styles,
    )

    physical_count = int((roadways["route_category"] != GRADE_SEPARATED_CONNECTOR_STYLE_KEY).sum())
    connector_count = int((roadways["route_category"] == GRADE_SEPARATED_CONNECTOR_STYLE_KEY).sum())
    logger.info(
        "%s County (%s District): %d physical roadway feature(s) exported "
        "(%d grade-separated connector segment(s) excluded from that "
        "count, shown separately under Reference Geometry)",
        county_name,
        district_name,
        physical_count,
        connector_count,
    )
    return kml
