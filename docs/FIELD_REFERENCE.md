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
- Geometry: Polygon, 254 features (one is geometrically invalid -- see README)
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
| `HWY` | String(7) | Full highway designation (e.g. "IH0020") -- primary placemark name |
| `HSYS` | String(2) | Highway system code -- drives route styling category (see below) |
| `HNUM` | String(4) | Highway number |
| `HSUF` | String(1) | Highway suffix |
| `STE_NAM` | String(50) | Street name (used as placemark name fallback) |
| `C_SEC` | String(7) | Control section (display only in this phase -- no CS *processing*) |
| `NUM_LANES` | SmallInteger | Lane count (description field) |
| `SPD_MAX` | SmallInteger | Speed limit (description field) |
| `SRF_TYPE` | SmallInteger | Surface type code (description field) |
| `LN_MILES` | Double | Lane miles (description field) |

There are ~120 additional inventory/asset fields (traffic counts, ESALs,
medians, tolling, etc.) not used in this phase -- see the live service for
the full list via `inspect-sources`.

### `HSYS` -> route styling category

Confirmed present in Smith County's data on 2026-09-12: `CR, FM, IH, LS, PR,
SH, SL, SS, TL, US`. `RM`/`BI`/`BU`/`BS`/`BF` are TxDOT-documented codes not
observed live in this sample; they're mapped defensively below and should be
re-verified with `inspect-sources`-style attribute queries if a build
surfaces an unmapped code (anything unmapped falls back to `other`, it never
errors).

| `HSYS` | Category | Color |
|---|---|---|
| `IH` | Interstate | Blue |
| `US` | US Highway | Red |
| `SH` | State Highway | Gold |
| `FM`, `RM` | FM/RM Road | Green |
| `SL`, `SS`, `BI`, `BU`, `BS`, `BF` | Loop/Spur/Business | Purple |
| `PR`, `CR`, `TL`, `LS`, anything else | Other TxDOT-maintained | Gray |

## Proof-of-concept scope

- All 25 TxDOT district boundaries
- Tyler District (`DIST_NM="Tyler"`, `DIST_NBR=10`) and its 8 counties
  (Anderson, Cherokee, Gregg, Henderson, Rusk, Smith, Van Zandt, Wood)
- Smith County (`CNTY_NBR=212`) and its 10,250 TxDOT roadway records

Verified end-to-end: `build-boundaries`, `build-county --county Smith`,
`build-district --district Tyler`, and `build-all --district Tyler
--single-file-kmz` all complete in well under a minute and pass
`validate-output` with zero errors.
