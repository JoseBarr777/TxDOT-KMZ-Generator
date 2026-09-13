"""Decodes TxDOT Roadway Inventory coded-value fields into display labels.

Every table below is transcribed from "Roadway Inventory File Format -
C(enterline) -R(oadbed)" (TPP-DM-RIB, revised 2021-06-07, effective YE2020 -
current) -- the ArcGIS service itself exposes no coded-value domains for
these fields (checked via inspect-sources: every field's `domain` is null),
so the service metadata cannot serve as this project's source of truth here.
docs/FIELD_REFERENCE.md records the exact document, section, and the live
distinct values this project has actually observed for each field.

None of these tables encode maintenance, ROW, or permit meaning beyond what
TxDOT's own labels say. A decoded RDWAY_MAINT_AGCY of "State Highway Agency"
states what the source data claims about maintenance responsibility; it is
not evidence about ROW ownership or permit jurisdiction, and callers must
not treat it as such.
"""
from __future__ import annotations

from txdot_overlay.values import is_missing_value

# 1.14 HIGHWAY-SYSTEM (HSYS). "On-System" = state highway system (TxDOT
# numbered routes); "Off-System" = not part of the state highway system.
HSYS_LABELS: dict[str, str] = {
    "BF": "Business FM",
    "BI": "Business IH",
    "BS": "Business State",
    "BU": "Business US",
    "FM": "Farm to Market",
    "FS": "FM Spur",
    "IH": "Interstate",
    "PA": "Principal Arterial",
    "PR": "Park Road",
    "RE": "Rec Road",
    "RM": "Ranch to Market",
    "RP": "Rec Road Spur",
    "RR": "Ranch Road",
    "RS": "RM Spur",
    "RU": "RR Spur",
    "SA": "State Alternate",
    "SH": "State Highway",
    "SL": "State Loop",
    "SS": "State Spur",
    "UA": "US Alternate",
    "UP": "US Spur",
    "US": "US Highway",
    "CR": "County Road",
    "FD": "Federal Road",
    "LS": "(Local) City Street",
    "TL": "Off-System Toll Road",
}
HSYS_ON_SYSTEM_CODES: frozenset[str] = frozenset(
    {
        "BF", "BI", "BS", "BU", "FM", "FS", "IH", "PA", "PR", "RE", "RM",
        "RP", "RR", "RS", "RU", "SA", "SH", "SL", "SS", "UA", "UP", "US",
    }
)
HSYS_OFF_SYSTEM_CODES: frozenset[str] = frozenset({"CR", "FD", "LS", "TL"})

# 1.17 ROADBED-IDENTIFIER (RDBD_ID), Roadbed-file code set (this project's
# roadway layer is roadbed-level, confirmed live: KG appears, not CG).
RDBD_ID_LABELS: dict[str, str] = {
    "AG": "Right Frontage Road",
    "BG": "Right Supplemental Frontage Road",
    "GS": "Grade Separated Connector",
    "KG": "Centerline / Single Roadbed",
    "LG": "Left Roadbed",
    "MG": "Left Supplemental Mainlane",
    "PG": "Left Supplemental Supplemental Mainlane",
    "RG": "Right Roadbed",
    "SG": "Right Supplemental Mainlane",
    "TG": "Right Supplemental Supplemental Mainlane",
    "XG": "Left Frontage Road",
    "YG": "Left Supplemental Frontage Road",
}

# 1.28 CARDINAL-DIRECTION (DIR_TRAV).
DIR_TRAV_LABELS: dict[int, str] = {
    0: "Not Applicable",
    1: "North to South",
    2: "West to East",
    3: "South to North",
    4: "Clockwise Loop",
    5: "Counter-clockwise Loop",
}

# 3.01 ADMINISTRATIVE-SYSTEM (ADMIN) and 3.02 ROADWAY-MAINTENANCE-AGENCY
# (RDWAY_MAINT_AGCY) share this table verbatim per the spec ("Same codes as
# ADMINISTRATIVE-SYSTEM").
ADMIN_AGENCY_LABELS: dict[int, str] = {
    1: "State Highway Agency",
    2: "County",
    4: "City (Municipality)",
    5: "Private Toll",
    6: "Local Toll Authority",
    7: "Other Federal Agency (includes IBWC)",
    8: "Bureau of Indian Affairs",
    9: "Bureau of Fish and Wildlife",
    10: "U.S. Forest Service",
    11: "National Park Service",
    12: "Bureau of Reclamation",
    13: "Corp of Engineers",
    14: "Navy / Marines",
    15: "Army",
    16: "Regional Mobility Authority",
    17: "Other",
    18: "Unknown",
}
STATE_HIGHWAY_AGENCY_CODE = 1

# 3.03 FUNCTIONAL-CLASSIFICATION (F_SYSTEM).
F_SYSTEM_LABELS: dict[int, str] = {
    1: "Interstate",
    2: "Other Freeway and Expressway",
    3: "Other Principal Arterial",
    4: "Minor Arterial",
    5: "Major Collector",
    6: "Minor Collector",
    7: "Local",
}

# 4.01 HIGHWAY-STATUS (HWY_STAT), current definition (RIF spec, rev.
# 2021-06-07, effective YE2020-current): construction/traffic-open status.
#
# Historical note: an older revision of the roadway-file format is reported
# to have described HWY_STAT=2 as "Artificial Centerline for Non-Mainlane" --
# a different meaning from the current spec's "Designated as State Highway,
# but not yet built" for that same code. This project has not located that
# older definition directly and does not treat it as verified, but preserves
# the note because it plausibly explains where an "artificial centerline"
# framing for this field could have come from. It does not change this
# project's conclusion: live Tyler District data never shows HWY_STAT=2 at
# all (every record, connector and physical roadway alike, is HWY_STAT=6),
# so HWY_STAT -- under either the old or current definition -- identifies
# nothing in the data this project actually has. The grade-separated
# connector classification uses RDBD_ID=GS instead; see
# processing/classify.py and docs/FIELD_REFERENCE.md.
HWY_STAT_LABELS: dict[int, str] = {
    0: "Proposed",
    2: "Designated as State Highway, but not yet built",
    3: "Under Construction",
    4: "Open but with some construction",
    6: "Open to Traffic",
    7: "Temporarily Closed to Traffic",
    99: "Unknown",
}

# 5.02 ACCESS-CONTROL (ACES_CTRL).
ACES_CTRL_LABELS: dict[int, str] = {1: "Full", 2: "Partial", 3: "None"}

# 5.05 MEDIAN-TYPE (MED_TYPE).
MED_TYPE_LABELS: dict[int, str] = {
    0: "No median",
    2: "Unprotected",
    3: "Curbed",
    4: "Positive Barrier - Unspecified",
    5: "Positive Barrier Flexible",
    6: "Positive Barrier Semi-Rigid",
    7: "Positive Barrier Rigid",
    99: "Unknown",
}

# 5.17 / 5.20 SHOULDER-TYPE-INSIDE / -OUTSIDE (S_TYPE_I / S_TYPE_O) share
# one table per the spec ("S_TYPE_O: See Shoulder-Type-Inside").
SHOULDER_TYPE_LABELS: dict[int, str] = {
    0: "None (unpaved)",
    1: "Bituminous Surface (paved)",
    2: "Concrete Surface (paved)",
    3: "Stabilized-Surfaced with Flex (unpaved)",
    4: "Combination-Surface / Stabilized (unpaved)",
    5: "Earth-with or without turf (unpaved)",
    6: "Brick",
    99: "Unknown",
}


def _decode_int(value, table: dict[int, str]) -> str | None:
    if is_missing_value(value):
        return None
    try:
        code = int(value)
    except (TypeError, ValueError):
        return f"Unknown code ({value})"
    label = table.get(code)
    return label if label is not None else f"Unknown code ({code})"


def _decode_str(value, table: dict[str, str]) -> str | None:
    if is_missing_value(value):
        return None
    code = str(value).strip().upper()
    label = table.get(code)
    return label if label is not None else f"Unknown code ({code})"


def decode_hsys(value) -> str | None:
    return _decode_str(value, HSYS_LABELS)


def decode_rdbd_id(value) -> str | None:
    return _decode_str(value, RDBD_ID_LABELS)


def decode_dir_trav(value) -> str | None:
    return _decode_int(value, DIR_TRAV_LABELS)


def decode_admin_agency(value) -> str | None:
    """Decodes both ADMIN and RDWAY_MAINT_AGCY -- verified to share one table."""
    return _decode_int(value, ADMIN_AGENCY_LABELS)


def decode_f_system(value) -> str | None:
    return _decode_int(value, F_SYSTEM_LABELS)


def decode_hwy_stat(value) -> str | None:
    return _decode_int(value, HWY_STAT_LABELS)


def decode_aces_ctrl(value) -> str | None:
    return _decode_int(value, ACES_CTRL_LABELS)


def decode_med_type(value) -> str | None:
    return _decode_int(value, MED_TYPE_LABELS)


def decode_shoulder_type(value) -> str | None:
    return _decode_int(value, SHOULDER_TYPE_LABELS)


def is_maintained_by_state_highway_agency(rdway_maint_agcy) -> bool:
    """True only when RDWAY_MAINT_AGCY is present and decodes to code 1.

    This is the one place that may answer "is this agency code the state
    highway agency" -- callers must not derive a "TxDOT-maintained" label
    from HSYS, F_SYSTEM, or any other field, and even this answer is a
    maintenance-responsibility claim from the source data, not evidence of
    ROW ownership or permit jurisdiction.
    """
    if is_missing_value(rdway_maint_agcy):
        return False
    try:
        return int(rdway_maint_agcy) == STATE_HIGHWAY_AGENCY_CODE
    except (TypeError, ValueError):
        return False


REGIONAL_MOBILITY_AUTHORITY_CODE = 16


def is_maintained_by_regional_mobility_authority(rdway_maint_agcy) -> bool:
    """True only when RDWAY_MAINT_AGCY is present and decodes to code 16.

    Used only to sub-classify off-system roadways (see
    processing/classify.py's classify_other_public_roadway_category) into a
    "Regional Mobility Authority Roads" bucket -- like
    is_maintained_by_state_highway_agency, this is a maintenance-
    responsibility claim from the source data, never a physical-
    classification signal on its own.
    """
    if is_missing_value(rdway_maint_agcy):
        return False
    try:
        return int(rdway_maint_agcy) == REGIONAL_MOBILITY_AUTHORITY_CODE
    except (TypeError, ValueError):
        return False
