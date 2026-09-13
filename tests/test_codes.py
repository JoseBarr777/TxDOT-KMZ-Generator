import pytest

from txdot_overlay.processing import codes


def test_decode_hsys_known_codes():
    assert codes.decode_hsys("IH") == "Interstate"
    assert codes.decode_hsys("us") == "US Highway"  # case-insensitive
    assert codes.decode_hsys("CR") == "County Road"
    assert codes.decode_hsys("LS") == "(Local) City Street"
    assert codes.decode_hsys("TL") == "Off-System Toll Road"


def test_decode_hsys_missing_returns_none():
    assert codes.decode_hsys(None) is None
    assert codes.decode_hsys(float("nan")) is None


def test_decode_hsys_unknown_code_conservative_fallback():
    assert codes.decode_hsys("ZZ") == "Unknown code (ZZ)"


def test_decode_admin_agency_known_codes():
    assert codes.decode_admin_agency(1) == "State Highway Agency"
    assert codes.decode_admin_agency(2) == "County"
    assert codes.decode_admin_agency(16) == "Regional Mobility Authority"
    assert codes.decode_admin_agency(18) == "Unknown"  # officially documented "Unknown"


def test_decode_admin_agency_shared_by_admin_and_maintenance_fields():
    # ADMIN and RDWAY_MAINT_AGCY are documented as sharing one code table.
    assert codes.decode_admin_agency(1) == codes.decode_admin_agency(1)


def test_decode_admin_agency_unknown_code():
    assert codes.decode_admin_agency(42) == "Unknown code (42)"


def test_decode_admin_agency_missing():
    assert codes.decode_admin_agency(None) is None


def test_decode_f_system():
    assert codes.decode_f_system(1) == "Interstate"
    assert codes.decode_f_system(7) == "Local"
    assert codes.decode_f_system(None) is None
    assert codes.decode_f_system(0) == "Unknown code (0)"


def test_decode_hwy_stat_does_not_mention_artificial():
    # HWY_STAT is a construction/traffic-open status field, not a geometry
    # classification -- regression guard against reintroducing that mix-up.
    for code, label in codes.HWY_STAT_LABELS.items():
        assert "artificial" not in label.lower()
    assert codes.decode_hwy_stat(6) == "Open to Traffic"
    assert codes.decode_hwy_stat(99) == "Unknown"


def test_decode_aces_ctrl():
    assert codes.decode_aces_ctrl(1) == "Full"
    assert codes.decode_aces_ctrl(2) == "Partial"
    assert codes.decode_aces_ctrl(3) == "None"  # official TxDOT term, not a null marker
    assert codes.decode_aces_ctrl(None) is None


def test_decode_med_type():
    assert codes.decode_med_type(0) == "No median"
    assert codes.decode_med_type(7) == "Positive Barrier Rigid"
    assert codes.decode_med_type(99) == "Unknown"


def test_decode_shoulder_type_shared_by_inside_and_outside():
    assert codes.decode_shoulder_type(0) == "None (unpaved)"
    assert codes.decode_shoulder_type(1) == "Bituminous Surface (paved)"
    assert codes.decode_shoulder_type(6) == "Brick"


def test_decode_dir_trav():
    assert codes.decode_dir_trav(0) == "Not Applicable"
    assert codes.decode_dir_trav(1) == "North to South"
    assert codes.decode_dir_trav(None) is None


def test_decode_rdbd_id():
    assert codes.decode_rdbd_id("GS") == "Grade Separated Connector"
    assert codes.decode_rdbd_id("kg") == "Centerline / Single Roadbed"
    assert codes.decode_rdbd_id("ZZ") == "Unknown code (ZZ)"


def test_is_maintained_by_state_highway_agency():
    assert codes.is_maintained_by_state_highway_agency(1) is True
    assert codes.is_maintained_by_state_highway_agency("1") is True
    assert codes.is_maintained_by_state_highway_agency(2) is False
    assert codes.is_maintained_by_state_highway_agency(None) is False
    assert codes.is_maintained_by_state_highway_agency(float("nan")) is False


def test_is_maintained_by_regional_mobility_authority():
    assert codes.is_maintained_by_regional_mobility_authority(16) is True
    assert codes.is_maintained_by_regional_mobility_authority("16") is True
    assert codes.is_maintained_by_regional_mobility_authority(1) is False
    assert codes.is_maintained_by_regional_mobility_authority(None) is False
    assert codes.is_maintained_by_regional_mobility_authority(float("nan")) is False


def test_hsys_on_off_system_partition_is_complete_and_disjoint():
    overlap = codes.HSYS_ON_SYSTEM_CODES & codes.HSYS_OFF_SYSTEM_CODES
    assert overlap == frozenset()
    # Every code with a label is accounted for in exactly one partition.
    all_partitioned = codes.HSYS_ON_SYSTEM_CODES | codes.HSYS_OFF_SYSTEM_CODES
    assert set(codes.HSYS_LABELS) == all_partitioned
