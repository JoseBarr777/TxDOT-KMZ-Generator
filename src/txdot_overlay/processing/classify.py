"""Classifies roadway features: physical-type taxonomy and visual/style category.

Two distinct classifications live here, deliberately kept separate:

- `classify_physical_type` answers "what kind of thing is this record" using
  only officially verified fields/values (HSYS, RDBD_ID) -- this is the
  safety-relevant taxonomy the rest of the project must not blur past.
- `classify_route_style` answers "what color/folder should this get in the
  KML" -- a presentation decision, config-driven, that happens to start from
  the same physical-type check (grade-separated connectors always get
  pulled into their own category first) but does not carry any of the
  maintenance/ROW/permit implications the physical-type taxonomy is careful
  to avoid.

Terminology note: RDBD_ID="GS" decodes officially (per the RIF spec) as
"Grade Separated Connector." That decoded label, and the empirical behavior
documented on `is_grade_separated_connector()`, are what this project can
actually stand behind. An earlier revision of this code called this category
"artificial centerline" -- that term is retired here because no current,
official TxDOT source was found asserting that every GS-coded record is
classified by TxDOT as an "Artificial Centerline." See
docs/FIELD_REFERENCE.md's "Grade-separated connectors" section for the full
history, including an older roadway-file definition that used that phrase
for a different code (HWY_STAT=2) which the live data does not support using
for this purpose.

Neither function infers maintenance responsibility, ROW ownership, or permit
jurisdiction from classification -- see processing/codes.py for the one
place that may answer a maintenance-agency question, and even that answer is
a source-data claim, not a legal determination.
"""
from __future__ import annotations

from enum import Enum

import geopandas as gpd

from txdot_overlay.config import Config
from txdot_overlay.processing.codes import (
    HSYS_OFF_SYSTEM_CODES,
    HSYS_ON_SYSTEM_CODES,
    is_maintained_by_regional_mobility_authority,
)
from txdot_overlay.values import is_missing_value

GRADE_SEPARATED_CONNECTOR_RDBD_ID = "GS"
GRADE_SEPARATED_CONNECTOR_STYLE_KEY = "grade_separated_connector"

# Sub-folder order within the "Other Public Roadways" branch (see
# kml_builder.py). Mirrors ROUTE_CATEGORY_ORDER's role for "TxDOT Roadways".
OTHER_PUBLIC_ROADWAY_CATEGORY_ORDER = [
    "county_road",
    "city_street",
    "regional_mobility_authority",
    "other_unclassified",
]


class PhysicalRoadType(str, Enum):
    STATE_HIGHWAY_SYSTEM = "state_highway_system"
    COUNTY_ROAD = "county_road"
    LOCAL_STREET = "local_street"
    OTHER_PHYSICAL_ROADWAY = "other_physical_roadway"
    GRADE_SEPARATED_CONNECTOR = "grade_separated_connector"
    UNKNOWN = "unknown"


def is_grade_separated_connector(rdbd_id) -> bool:
    """True iff RDBD_ID is the officially decoded "Grade Separated Connector" code.

    Verified via the official RIF spec (RDBD_ID=GS -> "Grade Separated
    Connector") and confirmed empirically: every GS record in Smith County
    and the Tyler District lacks physical cross-section attributes (SUR_W,
    RB_WID both null) and is a very short segment -- consistent with a
    linear-referencing continuity link through an interchange rather than
    an independently surveyed roadbed. This function name and the
    `GRADE_SEPARATED_CONNECTOR_*` constants deliberately use TxDOT's own
    decoded term rather than "artificial centerline" -- see the module
    docstring and docs/FIELD_REFERENCE.md.
    """
    if is_missing_value(rdbd_id):
        return False
    return str(rdbd_id).strip().upper() == GRADE_SEPARATED_CONNECTOR_RDBD_ID


def classify_physical_type(*, hsys, rdbd_id) -> PhysicalRoadType:
    """Classify one record's physical nature from verified fields only."""
    if is_grade_separated_connector(rdbd_id):
        return PhysicalRoadType.GRADE_SEPARATED_CONNECTOR

    if is_missing_value(hsys):
        return PhysicalRoadType.UNKNOWN

    code = str(hsys).strip().upper()
    if code in HSYS_ON_SYSTEM_CODES:
        return PhysicalRoadType.STATE_HIGHWAY_SYSTEM
    if code == "CR":
        return PhysicalRoadType.COUNTY_ROAD
    if code == "LS":
        return PhysicalRoadType.LOCAL_STREET
    if code in HSYS_OFF_SYSTEM_CODES:  # FD, TL (CR/LS already handled above)
        return PhysicalRoadType.OTHER_PHYSICAL_ROADWAY
    return PhysicalRoadType.UNKNOWN


def classify_route_style(*, hsys, rdbd_id, config: Config) -> str:
    """Return the config-driven styling/folder category for one record.

    Grade-separated connectors always resolve to
    `grade_separated_connector`, regardless of HSYS, so they never inherit a
    physical road's color or folder. Everything else defers to config.yaml's
    route_classification (HSYS -> category) map -- see config.route_category().
    """
    if is_grade_separated_connector(rdbd_id):
        return GRADE_SEPARATED_CONNECTOR_STYLE_KEY
    return config.route_category(hsys)


def classify_other_public_roadway_category(*, physical_type: str, rdway_maint_agcy) -> str | None:
    """Return the "Other Public Roadways" sub-folder for one off-system record.

    Returns None for on-system (`state_highway_system`) and grade-separated-
    connector rows -- those never appear under "Other Public Roadways" at
    all, see kml_builder.py. RDWAY_MAINT_AGCY is consulted only here, and
    only to split the small `other_physical_roadway`/`unknown` remainder
    (FD/TL codes, or a missing/unrecognized HSYS) into a Regional-Mobility-
    Authority-maintained bucket versus everything else -- it never overrides
    the on-system/off-system split itself, which comes from HSYS via
    classify_physical_type(). County Road (CR) and (Local) City Street (LS)
    are placed by HSYS alone, matching their RIF-spec meaning directly.
    """
    if physical_type == PhysicalRoadType.COUNTY_ROAD.value:
        return "county_road"
    if physical_type == PhysicalRoadType.LOCAL_STREET.value:
        return "city_street"
    if physical_type in (
        PhysicalRoadType.OTHER_PHYSICAL_ROADWAY.value,
        PhysicalRoadType.UNKNOWN.value,
    ):
        if is_maintained_by_regional_mobility_authority(rdway_maint_agcy):
            return "regional_mobility_authority"
        return "other_unclassified"
    return None


def classify_routes(roadways: gpd.GeoDataFrame, config: Config) -> gpd.GeoDataFrame:
    """Add `physical_type`, `route_category`, and `other_public_roadway_category` columns."""
    fields = config.sources["roadways"].fields
    hsys_field = fields["highway_system"]
    rdbd_field = fields["roadbed_id"]
    maint_agcy_field = fields["maintenance_agency"]

    result = roadways.copy()
    result["physical_type"] = [
        classify_physical_type(hsys=hsys, rdbd_id=rdbd_id).value
        for hsys, rdbd_id in zip(result[hsys_field], result[rdbd_field])
    ]
    result["route_category"] = [
        classify_route_style(hsys=hsys, rdbd_id=rdbd_id, config=config)
        for hsys, rdbd_id in zip(result[hsys_field], result[rdbd_field])
    ]
    result["other_public_roadway_category"] = [
        classify_other_public_roadway_category(
            physical_type=physical_type, rdway_maint_agcy=rdway_maint_agcy
        )
        for physical_type, rdway_maint_agcy in zip(
            result["physical_type"], result[maint_agcy_field]
        )
    ]
    return result
