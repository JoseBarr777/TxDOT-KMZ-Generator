# txdot_overlay

Downloads, processes, styles, and exports public TxDOT ArcGIS vector data as a
Google Earth Pro overlay: TxDOT district boundaries, Texas county boundaries,
and TxDOT Roadway Inventory road vectors.

ROW determination and control-section processing are explicitly **out of
scope** for this phase.

## Why it's structured this way

Loading every TxDOT roadway in Texas (~1M+ segments) into one KML is too slow
for Google Earth. Instead:

- **`master.kml`** is small and loads instantly: 25 district boundary
  polygons plus a navigation tree of folders and `NetworkLink`s. Nothing
  roadway-related lives here.
- **Per-county KMZ files** (`data/output/districts/<district>/<county>.kmz`)
  hold one county's boundary and classified roadway geometry. Google Earth
  only downloads/parses a county's KMZ when its `NetworkLink` is switched on.
- An **optional single-file KMZ** inlines everything for a given scope (no
  `NetworkLink`s), useful for comparing against the split output or for
  environments that can't resolve relative links.

Resulting Google Earth structure:

```
TxDOT Reference Overlay
├─ District Boundaries        (visible by default)
│  └─ <25 individually toggleable district polygons>
└─ District Details           (hidden by default)
   └─ <District>              (one per district, hidden)
      └─ <County>             (NetworkLink -> county KMZ, hidden)
         ├─ Administrative Boundaries
         │  ├─ County Boundary
         │  └─ City Limits                 (hidden by default, independently
         │                                   toggleable from its parent)
         ├─ TxDOT Roadways                 (on-system roads only)
         │  ├─ Interstate / US Highway / State Highway
         │  ├─ FM / RM Road
         │  ├─ Loop / Spur / Business Route
         │  └─ Other TxDOT Roadways        (on-system safety-net; empty in
         │                                   practice today, see design notes)
         ├─ Other Public Roadways          (off-system roads, pulled out of
         │                                   TxDOT Roadways)
         │  ├─ County Roads
         │  ├─ City Streets
         │  ├─ Regional Mobility Authority Roads
         │  └─ Other / Unclassified
         └─ Roadway Network Connectors     (visible by default)
            └─ Grade-Separated Connectors  (visible by default; RDBD_ID=GS,
                                             officially decoded "Grade
                                             Separated Connector" -- excluded
                                             from physical-road counts/classification)
```

## Data sources

All four sources are public TxDOT ArcGIS Online `FeatureServer` layers,
confirmed live (see `docs/FIELD_REFERENCE.md` for the full inspection
record and exact field names used; `docs/SOURCE_AUDIT.md` for why the
TxDOT city-boundary copy was chosen over the CPA/TxGIO alternative):

| Source | Layer |
|---|---|
| TxDOT Districts | `TxDOT_Districts/FeatureServer/0` |
| Texas County Boundaries (Detailed) | `Texas_County_Boundaries_Detailed/FeatureServer/0` |
| TxDOT Roadway Inventory | `TxDOT_Roadway_Inventory/FeatureServer/0` |
| TxDOT City Boundaries | `TxDOT_City_Boundaries/FeatureServer/0` |

URLs live in [`config/config.yaml`](config/config.yaml), not hardcoded in
source, so they can be repointed (e.g. to a newer annual Roadway Inventory
publication) without a code change.

## Setup

```bash
uv sync --extra dev
```

This project targets Python 3.10+ (see `requires-python` in `pyproject.toml`);
`.python-version` pins 3.13 as the standard development version `uv` will
provision, not a minimum-supported-version requirement.

<details>
<summary>Without uv (pip)</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
</details>

Install the pre-commit hooks once per clone (runs Ruff lint/format on staged
files before each commit):

```bash
uv run pre-commit install
```

## Usage

```bash
# Confirm the live services still expose the fields/layout this project assumes
python -m txdot_overlay inspect-sources

# Build master.kml: 25 district boundaries + navigation skeleton
python -m txdot_overlay build-boundaries

# Build one district's counties (boundary + roadways KMZ per county)
python -m txdot_overlay build-district --district "Tyler"

# Build a single county's detail KMZ
python -m txdot_overlay build-county --county "Smith"

# Build master.kml + every county in a scope (repeat --district; omit for statewide)
python -m txdot_overlay build-all --district "Tyler"
python -m txdot_overlay build-all --district "Tyler" --single-file-kmz

# Sanity-check the generated output
python -m txdot_overlay validate-output

# Full data-integrity report: source/downloaded/duplicate/geometry/final counts
python -m txdot_overlay audit-data --district "Tyler"

# Assemble a portable directory (master.kml + one district's county KMZs)
python -m txdot_overlay package-poc --district "Tyler"
```

Add `-v` for debug logging and `--force-refresh` to bypass the local cache.
Output lands under `data/output/`; open `data/output/master.kml` directly in
Google Earth Pro.

**Statewide runs**: `build-all` with no `--district` downloads and processes
all 254 counties (~1M roadway records). Validate on a small scope first (the
commands above build the Tyler/Smith proof of concept) before running it
statewide.

## Project layout

```
config/config.yaml          Source URLs, confirmed field names, styles, cache/output paths
src/txdot_overlay/
  values.py                  Missing/suspicious-value classification (shared by popups + audit)
  acquisition/               ArcGIS REST client, metadata inspection, disk cache, fetch+cache glue
  processing/
    codes.py                  Coded-value decode tables (HSYS, ADMIN, HWY_STAT, ...) + maintenance-agency checks
    classify.py                Physical-type taxonomy, on/off-system split, route styling category, and
                                 Other-Public-Roadways sub-classification (County/City/RMA/Other)
    diagnostics.py              Geometry repair-or-flag, duplicate-id checks, SourceAudit
    value_audit.py               Field-level null/suspicious-value tallies (read-only)
    geometry.py, assignment.py   CRS handling, clipping/simplification, county/district assignment
  styling/                   #RRGGBB -> KML aabbggrr color conversion, simplekml Style construction
  export/
    titles.py                  Placemark title fallback order + highway-number formatting (roadways/city limits)
    formatting.py                Clean numeric formatting (units, thousands separators)
    descriptions.py               Grouped, conditional-section popup HTML (roadways, city limits; + flat
                                    table for district/county boundaries)
    kml_builder.py, geometry_adapter.py, kmz_writer.py, validate.py
  commands/                  One module per CLI subcommand
  pipeline.py                Shared "fetch (cached) -> repaired GeoDataFrame" helpers
  cli.py                     argparse subcommand wiring
docs/FIELD_REFERENCE.md      Live-inspected fields/metadata, coded-value tables, the NaN trace
docs/SOURCE_AUDIT.md         County/city-boundary source comparison and the deferred parcel-import plan
docs/ACCEPTANCE_CHECKLIST.md Manual Google Earth Pro verification checklist
tests/                       pytest suite
data/cache/                  Cached ArcGIS responses (gitignored)
data/output/                 Generated KML/KMZ (gitignored)
dist/                        package-poc output, audit-data JSON reports (gitignored)
```

## Design notes

- **All Google Earth geometry is EPSG:4326** (WGS84 lon/lat). ArcGIS's
  `f=geojson` query output is already WGS84 per the GeoJSON spec, but
  `processing/geometry.py`'s `ensure_wgs84()` explicitly verifies/reprojects
  rather than trusting that silently -- see its docstring and
  `tests/test_geometry.py`.
- **Field names are never assumed.** `inspect-sources` queries each live
  service's `?f=json` metadata before the project's field mapping in
  `config.yaml` is treated as ground truth; it fails loudly if a configured
  field disappears from the live service.
- **County/district assignment prefers existing attributes.** The Roadway
  Inventory's `CO` code has been verified to match the county layer's
  `CNTY_NBR` (e.g. Smith County: `CNTY_NBR=212` == roadway `CO=212`), so
  assignment is an attribute join first; a spatial join against county
  polygons only runs for rows that join doesn't resolve
  (`processing/assignment.py`).
- **Two simplification tiers.** Roadway geometry uses a small tolerance
  (already short, TxDOT-segmented lines). District/county boundary polygons
  use a coarser tolerance applied only to the rendered copy -- clipping and
  spatial joins always use the unsimplified source geometry. Without this,
  `master.kml` was ~11MB (287k vertices across 25 district polygons); with
  it, ~0.8MB.
- **Known upstream data issue, repaired not dropped**: Aransas County's
  polygon fails a geometry-validity check ("Nested shells" -- overlapping
  parts, likely from the source's detailed-coastline digitizing). An earlier
  version of this project silently dropped it, undercounting 254 counties as
  253. `processing/diagnostics.py` now repairs it via `shapely.make_valid`
  (0.06% area change, identical bounding box) and logs the repair; a feature
  is only ever dropped -- loudly, by name and id -- if it's null, empty, or
  genuinely unrepairable. See `docs/FIELD_REFERENCE.md` and
  `tests/test_county_completeness.py`.
- **`audit-data`** reports source/downloaded/duplicate/geometry/final counts
  per source (districts and counties always; roadways when scoped with
  `--district`/`--county`, since a full statewide roadway audit downloads
  the same ~1M records a statewide build would).
- **`package-poc`** copies master.kml + one district's county KMZs into a
  clean directory and re-validates the *copy* (not the original output) to
  confirm the relative NetworkLinks still resolve after the whole folder is
  moved -- see `docs/ACCEPTANCE_CHECKLIST.md` for the manual Google Earth
  Pro verification this can't automate.
- **Missing values are never stringified before classification.** A shared
  `values.classify_value()` distinguishes `None`/`pandas.NA`/NaN
  floats/blank strings (always missing) from literal source strings like
  `"nan"` (suspicious, reported by `audit-data`, still hidden from popups)
  from legacy-sentinel-shaped numbers like `99`/`999` (flagged, never
  auto-suppressed -- only a documented per-field code table, in
  `processing/codes.py`, may translate one). This exists because an earlier
  version's popups displayed literal `"nan"` text; see
  `docs/FIELD_REFERENCE.md`'s "nan" trace for the full root-cause writeup.
- **Coded fields are decoded from TxDOT's own published spec, never
  guessed from field names.** `processing/codes.py` transcribes "Roadway
  Inventory File Format" (TPP-DM-RIB, rev. 2021-06-07) and the GRID User
  Guide verbatim; an unrecognized code renders as `"Unknown code (N)"`
  rather than silently guessing or dropping the row.
- **Grade-separated connectors (`RDBD_ID=GS`, officially decoded "Grade
  Separated Connector") are never shown as ordinary roads.** They're
  retained (never dropped), excluded from physical-road counts and
  classification, and placed under a visible-by-default `Roadway Network
  Connectors > Grade-Separated Connectors` folder in a muted style. The
  field originally assumed to identify these (`HWY_STAT`) turned out not
  to -- see `docs/FIELD_REFERENCE.md`. This category was previously named
  "artificial centerline"; that name is retired because no official
  current TxDOT source was found asserting that every `GS` record is
  classified by TxDOT as an "Artificial Centerline" -- see
  `processing/classify.py`'s module docstring.
- **On-system and off-system roadways get separate top-level folders.**
  `TxDOT Roadways` now holds only records whose HSYS code is part of the
  state highway system (`processing/classify.py`'s `PhysicalRoadType.
  STATE_HIGHWAY_SYSTEM`); everything off-system (County Road, (Local) City
  Street, and the small Federal-Road/Off-System-Toll-Road remainder) is
  pulled out into a sibling `Other Public Roadways` folder, further split
  into County Roads / City Streets / Regional Mobility Authority Roads /
  Other-Unclassified. The RMA split uses the same verified `RDWAY_MAINT_AGCY`
  field this project already uses for maintenance-agency questions (code 16)
  -- it never overrides the on/off-system split itself, which comes from
  HSYS alone.
- **City Limits is a new, independently toggleable layer**, sourced from
  TxDOT's own `TxDOT_City_Boundaries` layer rather than the Comptroller/TxGIO
  copy -- see `docs/SOURCE_AUDIT.md` for the side-by-side comparison and why
  the TxDOT copy was chosen. It lives under a new `Administrative Boundaries`
  folder alongside `County Boundary`, hidden by default.

**Safety note**: this overlay is an informational screening/reference tool.
`HSYS`, `RDWAY_MAINT_AGCY`, `ROW_MIN`, inclusion in the Roadway Inventory,
grade-separated-connector geometry, and proximity to a centerline are none
of them evidence that a TxDOT permit is or is not required, nor proof of
ROW ownership or maintenance jurisdiction beyond what TxDOT's own source data
claims. Nothing in this project performs or implies a legal ROW
determination.

## License

This project's code is licensed under the [MIT License](LICENSE). The
underlying GIS data (TxDOT districts/roadways/city boundaries, Texas county
boundaries) comes from public TxDOT ArcGIS Online services -- see
`docs/SOURCE_AUDIT.md` for source details; that data's own usage terms are
separate from this repository's code license.
