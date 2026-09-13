# Field Reference

Recorded from live queries against each service on 2026-09-12. Re-run
`python -m txdot_overlay inspect-sources` before relying on this if it's been
a while -- TxDOT publishes an updated Roadway Inventory annually and field
names/services can change.

## TxDOT Districts

- Service: `https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Districts/FeatureServer/0`
- Geometry: Polygon, 25 features
- Native spatial reference: EPSG:3857 (Web Mercator); `f=geojson` output is WGS84
- `maxRecordCount`: 2000; supported query formats: JSON, geoJSON, PBF

| Field | Type | Used as |
|---|---|---|
| `DIST_NM` | String(20) | District name (e.g. "Tyler") |
| `DIST_NBR` | Integer | District number (e.g. 10) |
| `DIST_ABRVN` | String(3) | District abbreviation (e.g. "TYL") |
| `TYPE` | String(10) | Rural/Urban/Metro classification |
| `TXDOT_DIST_NM` / `TXDOT_DIST_NBR` / `TXDOT_DIST_ABRVN_NM` | -- | Duplicate copies of the above; not used |
| `Label` | String(255) | Not used |

Sample (Tyler): `DIST_NM="Tyler"`, `DIST_NBR=10`, `DIST_ABRVN="TYL"`, `TYPE="Urban"`.

## Texas County Boundaries (Detailed)

- Service: `https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/Texas_County_Boundaries_Detailed/FeatureServer/0`
- Geometry: Polygon, 254 features (one -- Aransas, `CNTY_NBR=4` -- is
  source-invalid: "Nested shells". Repaired via `shapely.make_valid` before
  render-only simplification; see README and `tests/test_county_completeness.py`)
- Native spatial reference: EPSG:3857
- `maxRecordCount`: 1000; supported query formats: JSON, geoJSON, PBF

| Field | Type | Used as |
|---|---|---|
| `CNTY_NM` | String(20) | County name (e.g. "Smith") |
| `CNTY_NBR` | SmallInteger | County number -- **confirmed to equal the Roadway Inventory's `CO` code** |
| `CNTY_FIPS` | String(5) | FIPS code |
| `DIST_NM` | String(20) | This county's TxDOT district name -- existing attribute, no spatial join needed |
| `DIST_NBR` | SmallInteger | This county's TxDOT district number |
| `GID`, `CMPTRL_NBR`, `DPS_NBR`, `MSA1990/2000/2010`, `GRID_OP`, `CREATE_DT`, `CREATE_NM`, `EDIT_DT`, `EDIT_NM` | -- | Not used |

Sample (Smith): `CNTY_NM="Smith"`, `CNTY_NBR=212`, `CNTY_FIPS="48423"`, `DIST_NM="Tyler"`, `DIST_NBR=10`.

## TxDOT Roadway Inventory

- Service: `https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadway_Inventory/FeatureServer/0`
- Geometry: Polyline, ~1,027,891 features statewide (Smith County alone: 10,250)
- Native spatial reference: EPSG:4269 (NAD83); `f=geojson` output is WGS84
- `maxRecordCount`: 2000 (paginated via `resultOffset`); supported query formats: JSON, geoJSON, PBF
- 133 total fields on the live service; only the subset below is used

| Field | Type | Used as |
|---|---|---|
| `CO` | SmallInteger | County code -- joins to counties' `CNTY_NBR` |
| `DI` | SmallInteger | District code -- joins to districts' `DIST_NBR` |
| `RIA_RTE_ID` | String(10) | Unique route identifier |
| `HWY` | String(7) | Full highway designation (e.g. "IH0020") -- primary placemark title source |
| `HSYS` | String(2) | Highway system code -- decoded; drives route styling category and physical-type classification |
| `HNUM` | String(4) | Highway number (component of `HWY`; not shown separately) |
| `HSUF` | String(1) | Highway suffix (component of `HWY`; not shown separately) |
| `STE_NAM` | String(50) | Street name (title fallback when `HWY` is absent) |
| `C_SEC` | String(7) | Control section (display only in this phase -- no CS *processing*) |
| `RDBD_ID` | String(2) | Roadbed identifier -- drives grade-separated-connector detection (`GS`) |
| `DIR_TRAV` | SmallInteger | Cardinal direction of travel -- decoded |
| `HWY_STAT` | SmallInteger | Highway/traffic-open status -- decoded (see note below: NOT a geometry-type flag) |
| `RDWAY_MAINT_AGCY` | SmallInteger | Roadway maintenance agency -- decoded; the only field that may support a maintenance-responsibility statement |
| `ADMIN` | SmallInteger | Administrative system -- decoded (shares `RDWAY_MAINT_AGCY`'s code table) |
| `F_SYSTEM` | SmallInteger | Functional classification -- decoded |
| `NUM_LANES` | SmallInteger | Through-lane count |
| `LANE_WIDTH` | SmallInteger | Lane width, feet |
| `SUR_W` | SmallInteger | Surface width, feet |
| `SRF_TYPE` | SmallInteger | Surface type code (not decoded in this phase; not in the RIF spec's field list at hand) |
| `PV_RB_WID` | SmallInteger | Paved roadbed width, feet (unit inferred by naming convention -- **not found** in either official source consulted; see uncertainty note) |
| `RB_WID` | SmallInteger | Roadbed width, feet (includes shoulder + surface widths) |
| `MED_WID` | SmallInteger | Median width, feet |
| `MED_TYPE` | SmallInteger | Median type -- decoded |
| `S_WID_I` / `S_WID_O` | SmallInteger | Inside/outside shoulder width, feet |
| `S_TYPE_I` / `S_TYPE_O` | SmallInteger | Inside/outside shoulder type -- decoded (shared code table) |
| `ROW_MIN` | SmallInteger | Minimum recorded ROW width, feet -- inventory reference only, see disclaimer below |
| `SPD_MAX` | SmallInteger | Speed limit, mph |
| `ACES_CTRL` | SmallInteger | Access control -- decoded |
| `ADT_CUR` | Integer | Current AADT (annual average daily traffic) |
| `ADT_YEAR` | SmallInteger | Year the current AADT was measured |
| `LEN_SEC` | Double | Section length, miles |
| `LN_MILES` | Double | Lane miles |

There are ~100 additional inventory/asset fields (ESALs, tolling detail,
pavement history, etc.) not used in this phase -- see the live service for
the full list via `inspect-sources`.

## Coded-value field reference

Source for every table below: **"Roadway Inventory File Format -
C(enterline) -R(oadbed)"**, prepared by TPP-DM-RIB, revised 2021-06-07,
effective YE2020-current (the "RIF spec"), and the **GRID User Guide v1.5**
(November 2018), both retrieved 2026-09-12 from
`ftp.txdot.gov`/`caee.webhost.utexas.edu` mirrors of TxDOT's published
documentation. The ArcGIS service itself defines **no coded-value domains**
for any of these fields -- every one of their `domain` properties is `null`
in the live `?f=json` metadata, confirmed via `inspect-sources` -- so the
service metadata cannot be the source of truth here; only the RIF spec and
empirical live-data checks can.

Live distinct-value queries below were run against Smith County (10,250
records) and the full Tyler District (43,181 records: Anderson, Cherokee,
Gregg, Henderson, Rusk, Smith, Van Zandt, Wood) on 2026-09-12.

### `HSYS` -- Highway System (RIF 1.14)

| Raw value | Friendly label | On/Off-System | Live in Smith | Live in Tyler District |
|---|---|---|---|---|
| `IH` | Interstate | On | Yes | Yes |
| `US` | US Highway | On | Yes | Yes |
| `UA` | US Alternate | On | -- | -- |
| `SH` | State Highway | On | Yes | Yes |
| `SA` | State Alternate | On | -- | -- |
| `PA` | Principal Arterial | On | -- | -- |
| `FM` | Farm to Market | On | Yes | Yes |
| `RM` | Ranch to Market | On | -- | Yes |
| `FS` | FM Spur | On | -- | Yes |
| `RS` | RM Spur | On | -- | -- |
| `SL` | State Loop | On | Yes | Yes |
| `SS` | State Spur | On | Yes | Yes |
| `BF` | Business FM | On | -- | -- |
| `BI` | Business IH | On | -- | -- |
| `BS` | Business State | On | -- | Yes |
| `BU` | Business US | On | -- | Yes |
| `PR` | Park Road | On | Yes | Yes |
| `RE` | Rec Road | On | -- | -- |
| `RP` | Rec Road Spur | On | -- | -- |
| `RR` | Ranch Road | On | -- | -- |
| `RU` | RR Spur | On | -- | -- |
| `UP` | US Spur | On | -- | -- |
| `CR` | County Road | Off | Yes | Yes |
| `FD` | Federal Road | Off | -- | -- |
| `LS` | (Local) City Street | Off | Yes | Yes |
| `TL` | Off-System Toll Road | Off | Yes | Yes |

Nullability: not observed null in either sample. Every physical roadway
record carries an `HSYS`; a null/unrecognized value classifies as
`unknown` in `processing/classify.py`, never as a styled physical category.
No remaining uncertainty -- this table matches the RIF spec verbatim.

### `RDBD_ID` -- Roadbed Identifier (RIF 1.17, Roadbed-file code set)

This project's roadway layer is roadbed-level (confirmed: `KG` appears
live, not the Centerline-file's `CG`).

| Raw value | Friendly label | Live in Smith | Live in Tyler District |
|---|---|---|---|
| `AG` | Right Frontage Road | Yes | Yes |
| `BG` | Right Supplemental Frontage Road | -- | -- |
| `GS` | Grade Separated Connector | Yes (74) | Yes (187) |
| `KG` | Centerline / Single Roadbed | Yes | Yes |
| `LG` | Left Roadbed | Yes | Yes |
| `MG` | Left Supplemental Mainlane | -- | -- |
| `PG` | Left Supplemental Supplemental Mainlane | -- | -- |
| `RG` | Right Roadbed | Yes | Yes |
| `SG` | Right Supplemental Mainlane | -- | -- |
| `TG` | Right Supplemental Supplemental Mainlane | -- | -- |
| `XG` | Left Frontage Road | Yes | Yes |
| `YG` | Left Supplemental Frontage Road | -- | -- |

**This is the field used to detect grade-separated connectors** (see
"Grade-separated connectors" section below) -- not `HWY_STAT`. This project
uses TxDOT's own decoded label for `GS` ("Grade Separated Connector")
rather than the term "Artificial Centerline" -- see that section for why.

### `DIR_TRAV` -- Cardinal Direction of Travel (RIF 1.28)

| Code | Label |
|---|---|
| 0 | Not Applicable |
| 1 | North to South |
| 2 | West to East |
| 3 | South to North |
| 4 | Clockwise Loop |
| 5 | Counter-clockwise Loop |

**Live observation**: every single record in Smith County and the full
Tyler District has `DIR_TRAV = null` (Python `None`, object-dtype column --
the column has no non-null values at all, so pandas never upgrades it to a
float/NaN column; see the NaN trace below for why that distinction exists).
This field is fully documented but currently carries no live data in this
dataset -- the popup's "Direction of travel" row will not appear until/unless
TxDOT populates it.

### `RDWAY_MAINT_AGCY` and `ADMIN` -- share one code table (RIF 3.01/3.02)

| Code | Label | Live in Smith | Live in Tyler District |
|---|---|---|---|
| 1 | State Highway Agency | Yes | Yes |
| 2 | County | Yes | Yes |
| 4 | City (Municipality) | Yes | Yes |
| 5 | Private Toll | -- | -- |
| 6 | Local Toll Authority | -- | -- |
| 7 | Other Federal Agency (includes IBWC) | -- | -- |
| 8 | Bureau of Indian Affairs | -- | -- |
| 9 | Bureau of Fish and Wildlife | -- | -- |
| 10 | U.S. Forest Service | -- | -- |
| 11 | National Park Service | -- | -- |
| 12 | Bureau of Reclamation | -- | -- |
| 13 | Corp of Engineers | -- | -- |
| 14 | Navy / Marines | -- | -- |
| 15 | Army | -- | -- |
| 16 | Regional Mobility Authority | Yes | Yes |
| 17 | Other | -- | -- |
| 18 | Unknown | -- | -- |

**This is the only field that may support a "maintained by X" statement.**
`processing/codes.is_maintained_by_state_highway_agency()` returns true only
for code 1 -- nothing in `processing/classify.py` derives a maintenance
label from `HSYS`, `F_SYSTEM`, or physical-type alone. Even a decoded "State
Highway Agency" value is a maintenance-responsibility claim taken from the
source data, not evidence of ROW ownership or permit jurisdiction.

### `F_SYSTEM` -- Functional Classification (RIF 3.03)

| Code | Label | Live in Smith | Live in Tyler District |
|---|---|---|---|
| 1 | Interstate | Yes | Yes |
| 2 | Other Freeway and Expressway | -- | -- |
| 3 | Other Principal Arterial | Yes | Yes |
| 4 | Minor Arterial | Yes | Yes |
| 5 | Major Collector | Yes | Yes |
| 6 | Minor Collector | Yes | Yes |
| 7 | Local | Yes | Yes |

### `HWY_STAT` -- Highway Status (RIF 4.01) -- does NOT identify grade-separated connectors

Current definition (RIF spec, rev. 2021-06-07, effective YE2020-current):

| Code | Label |
|---|---|
| 0 | Proposed |
| 2 | Designated as State Highway, but not yet built |
| 3 | Under Construction |
| 4 | Open but with some construction |
| 6 | Open to Traffic |
| 7 | Temporarily Closed to Traffic |
| 99 | Unknown |

**Correction of an earlier assumption**: this project was initially asked to
use `HWY_STAT` to identify what was then called "artificial centerlines."
The current RIF spec's definition of `HWY_STAT` is exclusively about
construction/traffic-open status and never mentions centerlines, artificial
geometry, or connectors. Live data confirms this empirically: **every one
of the 43,181 records in the Tyler District -- physical roadway and
`RDBD_ID=GS` connector alike -- has `HWY_STAT = 6`** ("Open to Traffic"). A
field that is constant across 100% of records, including the very connector
segments it was meant to distinguish, cannot be the field doing that job.

**Historical note (preserved, not independently verified)**: an older
revision of the roadway-file format is reported to have defined
`HWY_STAT=2` as "Artificial Centerline for Non-Mainlane" -- a different
meaning entirely from the current spec's "Designated as State Highway, but
not yet built" for that same code. This project has not located that older
document directly, so it is recorded here as a historical note rather than
a verified fact, but it plausibly explains where an "artificial centerline"
framing for this field originated. It does not change the conclusion above:
whether under the old or current definition, `HWY_STAT` identifies nothing
in the Tyler District data this project has, because no record shows
`HWY_STAT=2` and every record (connector and physical alike) shows
`HWY_STAT=6`.

`RDBD_ID = GS`, officially decoded "Grade Separated Connector," is the
verified field used instead -- see "Grade-separated connectors" below. This
project does not use the term "artificial centerline" for that
classification: the decoded label and the empirical behavior documented
below support calling these records connector/reference geometry, but no
official *current* TxDOT source was found stating that TxDOT classifies
every `GS` record as an "Artificial Centerline." Treat that phrase, where
it still appears in this document, as historical context about where the
idea came from -- not as this project's own claim.

### `ACES_CTRL` -- Access Control (RIF 5.02)

| Code | Label |
|---|---|
| 1 | Full |
| 2 | Partial |
| 3 | None |

Note: code 3's official label is the word "None" -- meaning *no access
control exists on this roadway*, a legitimate decoded business value. This
is easy to mistake for a leaked internal null marker; it is not one. It
originates from `int` value `3` (never missing), passes through
`decode_aces_ctrl(3) == "None"`, and is exactly what TxDOT's own
documentation calls it. `tests/test_codes.py::test_decode_aces_ctrl` pins
this down explicitly so it is never "fixed" into something else by mistake.

### `MED_TYPE` -- Median Type (RIF 5.05)

| Code | Label | Live in Smith | Live in Tyler District |
|---|---|---|---|
| 0 | No median | Yes | Yes |
| 2 | Unprotected | Yes | Yes |
| 3 | Curbed | Yes | Yes |
| 4 | Positive Barrier - Unspecified | -- | -- |
| 5 | Positive Barrier Flexible | -- | -- |
| 6 | Positive Barrier Semi-Rigid | -- | Yes |
| 7 | Positive Barrier Rigid | Yes | Yes |
| 99 | Unknown | -- | -- |

### `S_TYPE_I` / `S_TYPE_O` -- Shoulder Type, Inside/Outside (RIF 5.17/5.20, shared table)

| Code | Label | Live in Smith | Live in Tyler District |
|---|---|---|---|
| 0 | None (unpaved) | Yes | Yes |
| 1 | Bituminous Surface (paved) | Yes | Yes |
| 2 | Concrete Surface (paved) | Yes | Yes |
| 3 | Stabilized-Surfaced with Flex (unpaved) | Yes | Yes |
| 4 | Combination-Surface / Stabilized (unpaved) | -- | -- |
| 5 | Earth-with or without turf (unpaved) | Yes | Yes |
| 6 | Brick | -- | -- |
| 99 | Unknown | -- | -- |

### Uncertainty remaining

- **`PV_RB_WID`** (Paved Roadbed Width): not found in either the RIF spec or
  the GRID User Guide. Its unit ("feet") is inferred only from its naming
  parallel to `RB_WID` (Roadbed Width, confirmed "feet" in the RIF spec) and
  from the ArcGIS field alias. Displayed with the same `format_feet()`
  formatter as its documented siblings, but flagged here as unverified.
- **`SRF_TYPE`** (Surface Type code): present on the live service and
  described only as "surface type code" in earlier notes; not found as a
  distinct coded-value table in the RIF spec sections reviewed (it may be
  under a different section heading not located in this pass). Not decoded
  in this phase -- shown nowhere in the current popup groups.
- **`DIR_TRAV`**: fully documented, zero live coverage (see above) -- not
  an uncertainty about meaning, but worth flagging so a future contributor
  doesn't assume the code table is unverified just because it never renders.

## Grade-separated connectors (RDBD_ID=GS)

**Terminology**: this classification is named after TxDOT's own decoded
label for the code that drives it -- `RDBD_ID = "GS"` decodes officially
(RIF spec) as **"Grade Separated Connector."** An earlier revision of this
project called this category "artificial centerline." That name is
retired: while the evidence below shows these records *behave* like
connector/reference geometry, no official *current* TxDOT source was found
stating that TxDOT classifies every `GS`-coded record as an "Artificial
Centerline." Do not treat "Grade Separated Connector" and "Artificial
Centerline" as synonymous terms unless a current official source is found
that says so explicitly. See the `HWY_STAT` historical note above for where
the "artificial centerline" phrase likely originated (a different code, in
an older, unverified document).

**Verified field: `RDBD_ID = "GS"`**, not `HWY_STAT` (see correction
above). The GRID User Guide's glossary defines the general GRID term
"Connector" as moving "traffic from the mainlane of one route to the
mainlane of another route... or off-system to on-system or vice versa" --
consistent with a linear-referencing continuity link through a
grade-separated interchange rather than an independently surveyed roadbed.

Empirical confirmation (Smith County, 74 `GS` records; Tyler District, 187):
every `GS` record has **both `SUR_W` (surface width) and `RB_WID` (roadbed
width) null**, a uniform placeholder `NUM_LANES = 1`, and very short segment
lengths (`LN_MILES` as low as 0.001) -- the signature of a
network-continuity linework segment, not a measured physical roadbed. `GS`
records were observed only on-system (`IH`, `US`, `SH`, `SL`, `BU`, `TL`),
never on `CR`/`LS`, matching the fact that grade-separated interchanges are
a state/toll-highway-system phenomenon. This is behavioral evidence for
treating `GS` records as connector/reference geometry; it is not itself an
official TxDOT statement classifying them as "Artificial Centerlines."

Counts: **Smith County: 74 grade-separated-connector segments** (of 10,250
total; 10,156 physical). **Tyler District: 187** (of 43,181 total; 42,994
physical) -- Anderson 12, Cherokee 0, Gregg 40, Henderson 45, Rusk 4, Smith
74, Van Zandt 9, Wood 3.

These are placed under `Reference Geometry > Grade-Separated Connectors`
(hidden by default, muted thin cyan `#66CCCC`, width 0.6) -- see
`export/kml_builder.py` and `tests/test_reference_geometry.py`. KML 2.2 has
no reliable dashed-line support in Google Earth Pro (no dash-pattern
property exists on `LineStyle`, and `<gx:>` extensions are not consistently
honored across versions), so `config.yaml` documents this limitation
(`styles.routes.grade_separated_connector.dashed: false`) rather than
shipping a style that silently renders solid while claiming to be dashed.

## The "nan" popup trace

Traced five representative records (a US highway, an FM road, a county
road, a local street, and a `GS` grade-separated connector) through every
stage, using Smith County's live `SPD_MAX`/`SUR_W` fields as the concrete
example (both are frequently null on county roads and connectors):

1. **Raw ArcGIS JSON** (verified via the cached response for OBJECTID
   330673, a County Road record): the property is the literal JSON token
   `null` -- e.g. `"SPD_MAX": null`, `"HWY": null`. ArcGIS does not omit the
   key or send an empty string; it sends `null` explicitly.
2. **Python value after ingestion** (`requests`' `.json()` -> standard
   `json.loads`): JSON `null` becomes Python `None`, type `NoneType`.
3. **GeoDataFrame value and dtype**: this is where the two representations
   diverge, and neither is under this project's control --
   `geopandas.GeoDataFrame.from_features()` infers a column's dtype from
   every value in it. A column with at least one real number (`SPD_MAX`:
   real values like `55.0`, `50.0` mixed with nulls) is inferred as
   `float64`, and pandas silently upgrades every `None` in it to
   `numpy.float64('nan')`. A column that is *entirely* null across every
   fetched record (`DIR_TRAV`) stays `object` dtype with plain `None`
   values -- no float coercion happens because there's no numeric value to
   force it. A string-typed column with some nulls (`HWY`, dtype shows as
   `str`) was also observed storing its missing marker as a bare Python
   `float('nan')`, not `None` or `pandas.NA` -- an artifact of this
   pandas/geopandas version's construction path from a list of dicts, not
   a deliberate choice this project made.
4. **Value passed to the (old) popup renderer**: whatever the GeoDataFrame
   stored -- `numpy.float64('nan')` for `SPD_MAX`, plain `None` for
   `DIR_TRAV`, or `float('nan')` for a missing `HWY` -- reached
   `build_description_html` via `row.to_dict()` unchanged.
5. **Final rendered KML value (the bug)**: the old description builder's
   only missing-check was `value in (None, "")`. `float('nan') in (None,
   "")` evaluates `False`, because `nan != nan` under Python/IEEE-754
   equality -- so `None`-classified fields were correctly skipped, but any
   NaN-classified field fell through to a bare `str(value)`, producing the
   literal text `"nan"` in the `<td>` cell. This reproduced consistently:
   every US highway, FM road, county road, and local street record checked
   in Smith County showed literal `"nan"` for whichever of its optional
   numeric/string fields happened to be null and NaN-typed.

**Root cause classification**: the displayed `nan` values originated as
genuine **ArcGIS/JSON `null`**, not as literal source text, not as
`pandas.NA`, and not as blank strings -- but by the time they reached the
renderer they had been silently retyped into **NumPy/Python floating-point
NaN** by pandas' own column-dtype inference, and the renderer's null check
didn't account for that representation. The fix
(`values.classify_value`/`is_missing_value`, used throughout
`export/descriptions.py`) checks for `None`, `pandas.NA`, and NaN floats
(via `math.isnan`, which works uniformly across `float`, `numpy.float32`,
and `numpy.float64`) as three named, explicit categories -- not a single
`in (None, "")` guess -- so no future dtype-inference quirk can silently
reopen this gap. See `tests/test_values.py` and
`tests/test_roadway_description.py` for the regression coverage, and the
live verification note below.

**Live verification after the fix**: a full-text scan of the rebuilt Smith
County KMZ (16MB uncompressed `doc.kml`, ~10,230 roadway placemarks) found
zero occurrences of `nan`, `NaN`, or `<NA>`. It found 2,620 occurrences of
the bare word `None` -- every single one is the "Access control" row
showing `ACES_CTRL`'s official decoded value `3 = "None"` (see above), not
a leaked internal null marker.

## XML safety: control characters in source text fields

Found while investigating unrelated build output from another concurrent
session on this project (not part of the Tyler POC): Cameron County's
`STE_NAM` field contains a raw ASCII control character (code point 4,
"end of transmission") embedded in an otherwise ordinary street name. KML
is XML, and XML 1.0 does not permit most control characters in text
content at all -- not even as an escaped entity. `html.escape()` (used
throughout `export/descriptions.py`, and by simplekml's own text escaping)
only escapes `&<>"'`; it does not strip control characters, so this one
field crashed KMZ export for the entire county (simplekml re-parses its
own generated XML with `xml.dom.minidom` to pretty-print it, which raised
`ExpatError: not well-formed`).

Fixed via `xml_safety.strip_illegal_xml_chars()`, applied to every raw
string value before it becomes placemark text (titles) or popup content
(descriptions) -- see `tests/test_xml_safety.py`. A live scan confirmed
Tyler District's own data has no such characters today, so this did not
affect the Tyler POC's correctness, but the fix applies everywhere text
reaches KML, not just where the bug was first found.

## City Limits

Source: `TxDOT_City_Boundaries` (`services.arcgis.com/KTcxiTD9dsQw4r7Z/.../TxDOT_City_Boundaries/FeatureServer/0`)
-- chosen over the Comptroller/TxGIO `Texas_City_Boundaries` layer after a
side-by-side comparison; see `docs/SOURCE_AUDIT.md` for the full
inspection, counts, and the reasoning (it's more complete for the Tyler
District, and is on the same ArcGIS Online org as every other source this
project uses).

| Field | Type | Used as |
|---|---|---|
| `OBJECTID` | OID | Feature identifier |
| `CITY_NM` | String | City name -- placemark title, popup Identity section |
| `CNTY_SEAT_FLAG` | String | Shown as-is in the popup, not decoded -- its exact encoding is not independently verified against an official spec, and this project does not guess field encodings the way it does for RIF-spec fields |
| `POP2022` / `POP2020` | Integer | Popup Population section -- POP2022 shown when present, falling back to POP2020 |
| `TXDOT_CITY_NBR` | Integer | GRID-internal city identifier -- not used by this project (no GRID integration) |
| `CITY_FIPS` | String | Not currently used |

No per-feature update-date field exists on this layer (confirmed via its
`?f=json` metadata) -- the popup's "Source" section is a fixed note citing
the service and the date of the `docs/SOURCE_AUDIT.md` comparison, not a
per-feature attribute.

Selection is spatial, not attribute-based: the statewide layer has no
county-code column, so each county's cities are selected by intersecting
its boundary polygon, then clipped to that boundary for cross-county cities
-- same raw-vs-render-simplified split as county/district boundaries (see
"Two simplification tiers" above).

**Not a legal record**: like the roadway/county sources, this layer is not
evidence of a legal annexation boundary or municipal jurisdiction beyond
what TxDOT's own source data claims.

## Proof-of-concept scope

- All 25 TxDOT district boundaries
- Tyler District (`DIST_NM="Tyler"`, `DIST_NBR=10`) and its 8 counties
  (Anderson, Cherokee, Gregg, Henderson, Rusk, Smith, Van Zandt, Wood)
- Smith County (`CNTY_NBR=212`) and its 10,250 TxDOT roadway records
  (10,156 physical + 74 grade-separated-connector segments)

Verified end-to-end: `build-boundaries`, `build-county --county Smith`,
`build-district --district Tyler`, `build-all --district Tyler
--single-file-kmz`, `audit-data --district Tyler`, and `package-poc
--district Tyler` all complete in well under a minute and pass
`validate-output` with zero errors.
