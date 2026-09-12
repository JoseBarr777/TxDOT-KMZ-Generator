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
         ├─ County Boundary
         └─ TxDOT Roadways
            ├─ Interstate / US Highway / State Highway
            ├─ FM / RM Road
            ├─ Loop / Spur / Business Route
            └─ Other TxDOT-Maintained Road
```

## Data sources

All three sources are public TxDOT ArcGIS Online `FeatureServer` layers,
confirmed live (see `docs/FIELD_REFERENCE.md` for the full inspection
record and exact field names used):

| Source | Layer |
|---|---|
| TxDOT Districts | `TxDOT_Districts/FeatureServer/0` |
| Texas County Boundaries (Detailed) | `Texas_County_Boundaries_Detailed/FeatureServer/0` |
| TxDOT Roadway Inventory | `TxDOT_Roadway_Inventory/FeatureServer/0` |

URLs live in [`config/config.yaml`](config/config.yaml), not hardcoded in
source, so they can be repointed (e.g. to a newer annual Roadway Inventory
publication) without a code change.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
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
  acquisition/               ArcGIS REST client, metadata inspection, disk cache, fetch+cache glue
  processing/                CRS handling, clipping/simplification, county/district assignment, route classification
  styling/                   #RRGGBB -> KML aabbggrr color conversion, simplekml Style construction
  export/                    KML/KMZ folder building, HTML descriptions, KMZ writing, output validation
  commands/                  One module per CLI subcommand
  pipeline.py                Shared "fetch (cached) -> clean GeoDataFrame" helpers
  cli.py                     argparse subcommand wiring
docs/FIELD_REFERENCE.md      Live-inspected fields/metadata this project relies on
tests/                       pytest suite (colors, CRS conversion, field inspection, folder visibility)
data/cache/                  Cached ArcGIS responses (gitignored)
data/output/                 Generated KML/KMZ (gitignored)
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
- **Known upstream data issue**: Aransas County's polygon fails a
  geometry-validity check (self-intersecting, likely from the source's
  detailed-coastline digitizing) and is skipped with a logged warning rather
  than crashing the build.
