# Artifact Contract

This document defines what a valid TxDOT KMZ Generator release artifact set
**is**: the artifact types, their paths and cardinalities, the `manifest.json`
schema, completeness semantics, the bulk ZIP and NetworkLink relationships,
expected delivery metadata, determinism guarantees, and how the contract is
versioned.

It does not describe how a release is built, validated, uploaded, verified or
promoted. That release process (cold source cache, validation order, release
IDs, immutable R2 prefixes, upload, verification, `current.json`, rollback) is a
separate contract that consumes this one.

The implementation is the authority; this document describes it. Paths come
from `src/txdot_overlay/export/layout.py`, the manifest from
`src/txdot_overlay/export/manifest.py`, and the release gate from
`scripts/release/gate.py`.

## Release tree

```text
manifest.json
master.kml
districts/
    <district>.kml
    <district>/
        <county>.kmz
boundaries/
    district_boundaries.kmz
    county_boundaries.kmz
    city_boundaries.kmz
    administrative_boundaries.kmz
offline/
    <district>.zip
    texas_statewide.zip
```

`<district>` and `<county>` are slugs of the TxDOT district and county names:
lowercased, each run of characters outside `a-z0-9` replaced by `_`, leading
and trailing `_` removed (`Wichita Falls` → `wichita_falls`).

An optional `txdot_overlay_single_file.kmz` may also appear at the root. It is
produced only by `build-all --single-file-kmz` and is not part of a standard
release.

All paths are relative, POSIX-separated, and never escape the release root.

## Artifact types

| `type` | Count | Path | Required | Type-specific metadata | Self-contained | Role |
|---|---|---|---|---|---|---|
| `master_kml` | 1 | `master.kml` | yes | — | no: NetworkLinks to every county KMZ | statewide entry point |
| `district_kml` | 25 | `districts/<district>.kml` | yes | `district`, `district_number` | no: district boundary + NetworkLinks to its county KMZs | per-district entry point |
| `county_kmz` | 254 | `districts/<district>/<county>.kmz` | yes | `county`, `county_fips`, `district`, `district_number` | yes | **canonical generated unit**: one county's roadways and boundaries |
| `district_boundaries_kmz` | 1 | `boundaries/district_boundaries.kmz` | yes | — | yes | district polygons only |
| `county_boundaries_kmz` | 1 | `boundaries/county_boundaries.kmz` | yes | — | yes | county polygons only |
| `city_boundaries_kmz` | 1 | `boundaries/city_boundaries.kmz` | yes | — | yes | city polygons only |
| `admin_boundaries_kmz` | 1 | `boundaries/administrative_boundaries.kmz` | yes | — | yes | combined administrative boundaries |
| `district_zip` | 25 | `offline/<district>.zip` | yes | `district`, `district_number` | yes | bulk download of one district's county KMZs + a Google Earth launcher |
| `statewide_zip` | 1 | `offline/texas_statewide.zip` | yes | — | yes | bulk download of all 254 county KMZs + a Google Earth launcher |
| `single_file_kmz` | 0–1 | `txdot_overlay_single_file.kmz` | **no** | — | yes | experimental single-document build |

A complete standard statewide release contains **310 artifact entries**
(1 + 25 + 254 + 4 + 25 + 1) plus `manifest.json`, which is not itself an
artifact entry.

## Manifest schema 2.1

`manifest.json` is a UTF-8 JSON object.

### Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string, `"MAJOR.MINOR"` | Contract version; currently `"2.1"`. |
| `generator` | string | `"txdot_overlay"`. |
| `generator_version` | string | Producer package version. Informational. |
| `generated_at` | string, `YYYY-MM-DDTHH:MM:SSZ` (UTC) | When the manifest was assembled. Not a source-data timestamp. |
| `state` | string | `"TX"`. |
| `validation` | object | The producer's completeness summary (below). |
| `artifacts` | array of objects | Every artifact that is present and valid. |
| `skipped` | array of objects | Every artifact that is missing or invalid. `[]` for a complete release. |

`validation` has exactly these fields:

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `complete`, `partial` or `failed` (see Completeness). |
| `counties_included` | int | Number of `county_kmz` entries in `artifacts`. |
| `counties_expected` | int | Counties in the source data (254). |
| `districts_included` | int | Number of `district_kml` entries in `artifacts`. |
| `districts_expected` | int | Districts in the source data (25). |
| `required_missing` | int | Required `skipped` entries whose `reason` is `"missing"`. |
| `required_invalid` | int | Required `skipped` entries with any other reason. |

### Artifact entries

Every entry in `artifacts` has:

| Field | Type | Meaning |
|---|---|---|
| `type` | string | One of the artifact types above. |
| `display_name` | string | Human-readable label, e.g. `"Smith County"`, `"Tyler District"`, `"Tyler District (Bulk ZIP)"`. |
| `path` | string | Location relative to the release root. |
| `size_bytes` | int | File size in bytes. |
| `sha256` | string | Lowercase hex SHA-256 of the file's bytes. For a ZIP, the hash of the ZIP file itself. |

plus, only on the types listed in the artifact table:

| Field | Type | Meaning |
|---|---|---|
| `county` | string | TxDOT county name. |
| `county_fips` | string | County FIPS code. |
| `district` | string | TxDOT district display name. |
| `district_number` | int | Stable TxDOT district number (`DIST_NBR`). Always present together with `district`; never derived from a name, slug or position. |

A field defined for a type is always present on it. There are no optional
artifact fields in 2.1.

Listed artifacts do **not** carry `required`; being listed means present and
valid. `required` appears only on `skipped` entries, which have exactly:
`type`, `path`, `reason` (`"missing"` or a validation error), and `required`
(bool).

The order of `artifacts` is deterministic but carries no meaning: master,
district KMLs, county KMZs grouped by district, district ZIPs, statewide ZIP,
the four boundary KMZs in a fixed order, then the optional single-file KMZ.
Districts and counties are alphabetical within their groups. Consumers must
not depend on the order.

## Completeness

The producer registers every required artifact and resolves `status`:

- `failed`: a required artifact is present but invalid, or `master.kml` is
  missing or invalid.
- `partial`: everything present is valid, but a required artifact is missing.
- `complete`: every required artifact is present and valid.

Only `complete` is publishable.

These counters only cover artifacts the producer registers. An artifact type
the producer stopped registering would appear in neither `artifacts` nor
`skipped`, and could not show up as missing. So the release gate independently
requires all of the following:

| Rule | Checked from |
|---|---|
| `schema_version` is a supported `"MAJOR.MINOR"` string (major `2`) | top level |
| `status == "complete"` | `validation` |
| 25/25 districts (`district_kml`) | `validation.districts_*` |
| 254/254 counties (`county_kmz`) | `validation.counties_*` |
| `required_missing == 0`, `required_invalid == 0` | `validation` |
| exactly 25 `district_zip` | counted from `artifacts` |
| exactly 1 `statewide_zip` | counted from `artifacts` |
| exactly 1 each of `master_kml`, `district_boundaries_kmz`, `county_boundaries_kmz`, `city_boundaries_kmz`, `admin_boundaries_kmz` | counted from `artifacts` |

`single_file_kmz` is optional and never required.

## Bulk ZIP contract

The **County KMZ is the canonical generated artifact.** District and Statewide
ZIPs are transport containers holding exact copies of it, plus one Google
Earth launcher KML for navigation.

| | District ZIP | Statewide ZIP |
|---|---|---|
| Path | `offline/<district>.zip` | `offline/texas_statewide.zip` |
| County members | that district's counties | all 254 counties |
| County member name | `<District> District/<County> County.kmz` | same convention, one folder per district |
| Launcher | `<District> District/Open <District> District.kml` | `Open Texas TxDOT Overlay.kml` (ZIP root) |

```text
District ZIP                           Statewide ZIP
Tyler District/                        Open Texas TxDOT Overlay.kml
    Open Tyler District.kml            Abilene District/
    Anderson County.kmz                    Borden County.kmz ...
    Smith County.kmz ...               Tyler District/
                                           Anderson County.kmz ...
```

Member names use the human-readable TxDOT names (e.g.
`Tyler District/Smith County.kmz`), not the release-path slugs. The Statewide
ZIP contains no District launchers.

Every District and Statewide ZIP:

- contains exactly the expected members (its county KMZs and its one
  launcher): none missing, none unexpected, no duplicates;
- has no explicit directory entries;
- stores every member with `ZIP_STORED` (the KMZs are already compressed);
- writes members in sorted name order, each with the fixed timestamp
  1980-01-01 00:00:00;
- contains, for every county member, bytes identical to the standalone
  `districts/<district>/<county>.kmz` in the same release.

A package is produced only when every county KMZ it needs exists.

### Package launchers

A launcher is the file a person opens in Google Earth Pro after extracting the
ZIP. It is local package navigation, not a hosted entry point: unlike
`master.kml` and `districts/<district>.kml`, its links resolve inside the
extracted package, and it needs no Internet connection.

- District launcher: a `Document` named `<District> District` holding one
  `NetworkLink` per county, named `<County> County`, in alphabetical order.
- Statewide launcher: a `Document` named `Texas TxDOT Overlay` holding one
  `Folder` per district (`<District> District`, alphabetical), each holding
  that district's county `NetworkLink`s.
- Every county `NetworkLink` has `visibility` `0` (unchecked) and a
  `Link/href` that is the county member's path relative to the launcher's own
  folder (`Smith County.kmz` in a District launcher,
  `Tyler District/Smith County.kmz` in the Statewide launcher). Each href
  resolves to a member of the same ZIP.
- No absolute paths, `..`, URLs, release IDs or other remote references.
- No GIS content (placemarks, geometry, overlays) and no timestamps.

Whether a given Google Earth Pro version defers all loading of an unchecked
link until it is checked is observed behavior, not part of this contract.

## NetworkLink contract

```text
master.kml
    └── NetworkLink → districts/<district>/<county>.kmz   (every county)

districts/<district>.kml
    └── NetworkLink → <district>/<county>.kmz             (that district's counties)
```

`master.kml` and the district KMLs are **parallel entry points**. The master
links directly to county KMZs; it does **not** link to district KMLs. Every
href is relative, so a release tree keeps working when it is served from any
base URL or copied as a whole.

Breaking changes for already-published KML entry points:

- the county KMZ path pattern `districts/<district>/<county>.kmz`;
- the slug rule;
- placing `districts/<district>.kml` anywhere other than as a sibling of
  `districts/<district>/`;
- the NetworkLink relationships above.

## Delivery metadata

A release served over HTTP is expected to use these Content-Types:

| Extension | Content-Type |
|---|---|
| `.kml` | `application/vnd.google-earth.kml+xml` |
| `.kmz` | `application/vnd.google-earth.kmz` |
| `.zip` | `application/zip` |
| `.json` | `application/json` |

How they are set and checked belongs to the release process.

## Determinism

Guaranteed:

- KMZs and bulk ZIPs: sorted entries, the fixed 1980-01-01 00:00:00 entry
  timestamp, and a fixed compression method (`ZIP_DEFLATED` for KMZs,
  `ZIP_STORED` for bulk ZIPs). KMZ entries keep their original external
  attributes; every bulk ZIP member is a regular file with mode `0644`.
- Launcher KMLs are generated without simplekml, so their bytes depend only on
  the district and county names, never on process state.
- Bulk ZIPs are byte-identical for identical input county KMZs, independent of
  source row order.
- The order of `artifacts` depends only on the source reference data, not on
  filesystem enumeration or source row order.
- `size_bytes` and `sha256` describe the exact bytes in the release.

Known limitation: simplekml assigns KML element IDs from a process-global
counter. Byte-level reproducibility of KML/KMZ output therefore holds only for
the same full build run in a fresh process. The same logical county built
under a different build scope (a single-county or single-district build, or
after other documents in the same process) can have different element IDs,
and therefore a different County KMZ `sha256`, with identical content. This
contract does **not** guarantee that the same logical inputs always give the
same County KMZ hash. Within one release, every copy of a county KMZ is
byte-identical.

`generated_at` makes `manifest.json` itself differ between builds.

## Version history

| Version | Change |
|---|---|
| 2.0 | First committed manifest schema: `master_kml`, `district_kml`, `county_kmz`, the four boundary KMZ types, and the `complete`/`partial`/`failed` model. |
| 2.1 | Additive: `district_zip` and `statewide_zip` added as required types. No existing field, type or path changed. |

Within 2.1, before any 2.1 release was promoted, District and Statewide ZIPs
gained their package launcher KMLs. This added one member per ZIP and left
every county member, and the manifest schema, unchanged.

## Versioning policy

`schema_version` is a `"MAJOR.MINOR"` **string**. There is no patch level.

**MINOR** is for changes that are backward-compatible for readers:

- a new artifact type at new paths, with existing paths unchanged;
- a new top-level field, artifact metadata field or `validation` counter;
- making a new artifact type required, as long as completeness and the release
  gate are updated in the same change.

**MAJOR** is for changes a reader may need to adapt to:

- removing or renaming a field or artifact type;
- changing a field's type, units or meaning, or the meaning of `status` values;
- changing an existing artifact's path pattern or the slug rule;
- changing a NetworkLink relationship;
- changing ZIP member naming or the byte-identity rule;
- restructuring the manifest.

**No bump** for documentation-only changes, or bug fixes that restore the
documented contract.

## Consumer expectations

A consumer of this contract should:

- read only the fields it needs;
- ignore unknown fields;
- ignore unknown artifact types;
- accept any MINOR version of a MAJOR version it supports;
- reject a MAJOR version it does not support.

Consumers should not require exact equality with `"2.1"`; understanding 2.x
means accepting every 2.x. The release gate follows these rules: it accepts
any `2.x` and rejects any other major, and any value that is not a
`"MAJOR.MINOR"` string. The producer's own tests pin the exact version it
emits.

## Related boundaries

- `current.json` belongs to the release/distribution contract, not this one.
  It is the mutable pointer to the promoted release and has its own schema and
  version.
- Source provenance (source URLs, fetch times, Git SHA) is not part of 2.1. It
  could be added later as a backward-compatible MINOR extension.
