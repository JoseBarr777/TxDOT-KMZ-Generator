# Source Audit: Counties, Cities, Parcels

Live-queried 2026-09-12 while scoping the county-hierarchy/city-limits/parcel-POC
work. Companion to `docs/FIELD_REFERENCE.md` (districts/counties/roadways); this
file covers the county-boundary freshness check, the city-boundary source
comparison, and the parcel-overlay source inspection.

## 1. County-boundary source audit — decision: **KEEP**

Currently configured: `Texas_County_Boundaries_Detailed` (see `config/config.yaml`).

| Property | Value |
|---|---|
| Publisher | TxDOT Transportation Planning and Programming (TPP-GIS@txdot.gov) |
| Owner (AGOL) | `TPP_GIS`, org `KTcxiTD9dsQw4r7Z` |
| Item ID | `8b902883539a416780440ef009b3f80f` |
| Item URL | `https://www.arcgis.com/home/item.html?id=8b902883539a416780440ef009b3f80f` |
| Service URL | `https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/Texas_County_Boundaries_Detailed/FeatureServer/0` |
| Underlying source | Digitized from georeferenced USGS topographic quad maps ("Version 12" per service description) |
| Item created / modified | 2016-08-13 / 2025-01-04 |
| Item tags | Includes **"Authoritative"** (TxDOT's own designation) |
| Service-reported count | 254 (`returnCountOnly` query) |
| Downloaded count | 254 (matches; confirmed by this project's existing `test_county_completeness.py`) |
| Coordinate system | Native EPSG:3857 (Web Mercator); `f=geojson` output WGS84, as this project already assumes |
| Geometry validity | 253 valid + 1 repairable (Aransas County, "Nested shells" — already handled by `processing/diagnostics.py`, see `FIELD_REFERENCE.md`) |
| Coastline detail | High-resolution detailed coastline (that's the layer's differentiator vs. the plain "Texas County Boundaries" generalized layer on the same portal) — this project's boundary-simplification tier (`county_boundary_tolerance_degrees`) already exists specifically to make this usable at Google Earth's render scale (see README "Design notes") |
| Schema fields | 18 fields including `CNTY_NBR` (verified match to roadway `CO`), `DIST_NM`/`DIST_NBR` (district assignment without a spatial join) — both load-bearing for this project's existing attribute-join logic |

**Search for a newer official alternative**: Searched TxGIO (`geographic.texas.gov`,
`tnris.org`) directly and via web search for a distinct, more current statewide
county-boundary layer. TxGIO's own StratMap program publishes address points,
land parcels, imagery, and LiDAR as its flagship statewide layers; no separate
TxGIO-branded county-boundary polygon layer with a demonstrably newer vintage,
equal completeness (254/254), or equal detail was found. The TxDOT layer is
itself tagged "Authoritative" by its publisher and was refreshed within the
last year (2025-01-04).

**Decision**: keep `Texas_County_Boundaries_Detailed`. No other official source
was found that is demonstrably newer, more complete, and equally queryable —
per the standing instruction, that means don't switch.

## 2. City-boundary source comparison — decision: **use the TxDOT copy**

| Property | CPA/TxGIO (`Texas_City_Boundaries`) | TxDOT GRID copy (`TxDOT_City_Boundaries`) |
|---|---|---|
| Publisher | Texas Comptroller of Public Accounts, with US Census Bureau attributes added | TxDOT (same org as districts/counties/roadways: `KTcxiTD9dsQw4r7Z`) |
| Service URL | `feature.geographic.texas.gov/.../Texas_City_Boundaries/MapServer/0` | `services.arcgis.com/KTcxiTD9dsQw4r7Z/.../TxDOT_City_Boundaries/FeatureServer/0` |
| Statewide count | 1,225 | 1,227 |
| Coordinate system | Native WKID 102603/3081 (Texas Statewide Mapping System, NAD83) | Native WKID 102100 (Web Mercator) — same as this project's other TxDOT layers |
| Fields | `city_name`, `geo_id`, `geo_id_fq`, `gnis`, `cenpop2010`, `popest2020`, `last_edit` | `CITY_NM`, `TXDOT_CITY_NBR`, `CITY_FIPS`, `CNTY_SEAT_FLAG`, `POP1990`–`POP2022`, `MAP_COLOR_CD` |
| Null/invalid geometry | 0 (`Shape IS NULL` count) | 0 |
| Tyler District bbox count* | 70 | 72 |
| Cities in one source only | **Missing from CPA, present in TxDOT: `Hideaway` (Smith County) and `New London` (Rusk County)** — both confirmed real incorporated cities (Hideaway: incorporated, levies **no city sales tax**; New London: incorporated 1963, active municipal government per the Texas Municipal League directory) | — |
| TxDOT-specific identifiers needed? | — | `TXDOT_CITY_NBR` is a GRID-internal ID; not needed by this project (no GRID integration), but harmless to retain as a popup field if convenient |

\* Bounding-box query (`-95.97,31.55,-94.45,32.98`, `esriSpatialRelIntersects`)
covering the 8 Tyler District counties, not a true clip — used only for this
comparison, not for the production city-selection logic (see Section 3, which
clips/selects by actual county polygon).

**Why CPA's layer is missing these two cities — unconfirmed hypothesis, not an
established root cause**: the CPA layer's own description says it exists for
sales-tax boundary purposes ("CPA geometry is retained as the authoritative
source"). Hideaway is confirmed to levy zero city sales tax; a city with no
local sales tax would have nothing for a sales-tax-oriented boundary product
to track, which is *consistent with* its absence from CPA's layer. That is as
far as the evidence goes — this project has not confirmed CPA's actual data
pipeline, has not confirmed why New London specifically is also missing, and
has not ruled out other explanations (a data-entry gap, a stale extract,
etc.). Treat this as a plausible hypothesis worth noting, not a verified
cause. What *is* confirmed independently: both `Hideaway` and `New London`
are real incorporated cities (confirmed via web search, not via either
boundary source itself), and both are present in the TxDOT copy and absent
from the CPA copy.

**Decision**: use `TxDOT_City_Boundaries` — for this TxDOT-oriented overlay
(every other source it uses is on the same ArcGIS Online org), and because it
is confirmed more complete for the Tyler District regardless of *why* CPA's
copy is missing those two cities. Neither source is presented as a legal
annexation or permit record — see the disclaimer requirement carried into
`export/descriptions.py`.

## 4. Parcel source inspection — Smith County (research only; generation deferred)

Candidate: `stratmap_land_parcels_48_most_recent`
(`https://feature.geographic.texas.gov/arcgis/rest/services/Parcels/stratmap_land_parcels_48_most_recent/MapServer/0`).

| Property | Value |
|---|---|
| Publisher | Texas Geographic Information Office (TxGIO), housed at the Texas Water Development Board |
| AGOL item | "Land Parcels by County or State (TxGIO)", id `ac01f3669dde4e9ea67cee11f2771038`, owner `Texas Water Development Board`, modified 2024-08-15 |
| Copyright text | "TxGIO, Various Counties, Various Vendors" |
| Geometry / CRS | Polygon, native WKID 102100 (Web Mercator) |
| Record count / pagination | **Could not be determined** — see blocker below. `maxRecordCount` is 2000 per the layer metadata, but that is unverified against an actual page of results. |
| Completeness | Not assessed — only one point was checked (see below), which is not a countywide sample |

**Sample-record observation only — not verified countywide metadata.** One
`/identify` (single-point map click) request near downtown Tyler returned two
records for the same underlying property. Everything below is what those two
records happened to contain, not a confirmed property of the dataset as a
whole — a proper vintage/source/tax-year determination would require actually
paginating through Smith County's records, which the blocker below prevented:

```
PROP_ID: R049442   COUNTY: SMITH   FIPS: 48423
SOURCE: SMITH APPRAISAL DISTRICT   DATE_ACQ: 20250701   TAX_YEAR: 2025
LEGAL_DESC: CITY OF TYLER BLOCK 2 LOT 33
LAND_VALUE / IMP_VALUE / MKT_VALUE: $0 / $0 / $0   (this parcel only —
  not necessarily representative; TxGIO's value fields are typed as strings,
  not numbers, in this schema)
```

Do not treat `SOURCE = "SMITH APPRAISAL DISTRICT"`, `DATE_ACQ = 20250701`, or
`TAX_YEAR = 2025` as facts about Smith County's data as a whole — they are
this one sample's values, nothing more, until a real countywide pull confirms
(or contradicts) them.

**Duplicate PROP_ID observation**: the same `PROP_ID` came back as **two**
distinct `OBJECTID`s at that point (different `GIS_AREA`/shape each). A
future ingestion must key on **`OBJECTID`** (the layer's actual unique
identifier) and preserve both geometries as separate features — **do not**
deduplicate or dissolve records that share a `PROP_ID`; a real multi-polygon
property record and a data-quality duplicate look identical from a single
sample point, and collapsing them automatically risks silently discarding
real geometry. This mirrors the project's existing roadway duplicate-ID
diagnostics in spirit (flag and preserve, never silently merge), but for
parcels specifically, `OBJECTID` uniqueness is the correct key, not `PROP_ID`.

**Blocker: anonymous `/query` did not work on this service in this session.**
The layer metadata advertises `"capabilities": "Query,Map"`, but every
attempt to call its `/query` operation (count-only, attribute filter, any
`outFields`) returned the same ArcGIS error regardless of parameters:

```json
{"error":{"code":400,"extendedCode":-2147220222,
  "message":"Requested operation is not supported by this service.",
  "details":["The requested capability is not supported."]}}
```

The `/identify` operation (single-point map click) did work and returned the
sample above. **Why `/query` fails is not established** — this project did
not confirm whether it's a deliberate access restriction, a temporary
service issue, a misconfiguration, or something else, and does not assert a
reason. What is established is only the observed behavior: `/query` failed
consistently across every attempt this session, `/identify` succeeded once.
No sibling queryable service (e.g. a versioned `stratmap25_land_parcels_48`
alongside the `_most_recent` alias) was found publicly listed under the same
host; the `feature.tnris.org` host referenced in older documentation no
longer resolves.

**A parcel product must not be built on repeated `/identify` calls** — that
is a single-point lookup, not a bulk-query substitute, and paging a whole
county through it would be both unreliable (no geometry-complete coverage
guarantee) and a misuse of an interactive map operation. Given that
constraint, **parcel generation is deferred** — see Section 5 below.

**Smith County Appraisal District's own site** (`smithcad.org/downloads.html`)
does advertise a GIS/data-downloads section, but the page returned HTTP 403 to
an automated fetch (consistent with a click-through-disclaimer page meant for
browsers, not an API) — per instructions, it was not scraped. This project has
not confirmed whether SCAD's own download is more current than the TxGIO
sample's `DATE_ACQ`; a human should check `smithcad.org/downloads.html`
directly before relying on either source as "most current."

**Framing reminder for any future parcel product**: TxGIO's own description
of this service is a statewide 2025 compilation drawn from individual county
appraisal districts and vendors on a rolling basis — "most recent" describes
the compilation process, not a live feed. It must not be presented as
real-time or continuously current, and (per the earlier scope decision) never
as a legal record of ownership, boundary, or value.

## 5. Deferred: future import-parcels workflow

Parcel generation is **not implemented** in this pass. `config/config.yaml`
deliberately does not configure a `parcels` source, and there is no
`build-parcels` command, pipeline loader, or KML builder for parcels yet.
This section records the intended approach for whenever it is built:

- **Ingest from an official bulk download, not a live REST source.** Given
  Section 4's `/query` blocker and the explicit rule against paginating via
  repeated `/identify` calls, the future command (working name
  `import-parcels --county "Smith" --file <path>`) should read a local file —
  a shapefile or file geodatabase obtained directly from either the Smith
  County Appraisal District's own download (once confirmed available; see
  Section 4) or TxGIO's bulk StratMap distribution — rather than querying a
  live ArcGIS endpoint. This keeps the ingestion path independent of whether
  `/query` ever becomes reachable on the hosted service.
- **Key on `OBJECTID` (or the bulk file's equivalent unique feature ID), never
  `PROP_ID`.** Per Section 4's duplicate-geometry observation, every feature
  in the source file is preserved as its own placemark; nothing is
  deduplicated or dissolved by `PROP_ID` automatically.
- **Privacy-scoped popup fields carry over unchanged** from this session's
  approved scope: parcel/property ID, county, legal description, GIS/legal
  acreage, situs/site address, land-use/zoning code, source agency or vendor,
  acquisition date, and tax year. Owner/care-of names, mailing addresses, and
  all assessed/market/land/improvement value fields are excluded, regardless
  of whether the bulk source file contains them — the import step must drop
  those columns before anything reaches a popup builder, not rely on a
  downstream renderer to omit them.
- **Stays a separate product**, per the standing requirement: never merged
  into the transportation KMZ, its own command/output path.
- **Vintage/tax-year/source fields, once a real countywide file is in hand,
  should be reported per the actual imported data** — not assumed from the
  single sample record in Section 4.
