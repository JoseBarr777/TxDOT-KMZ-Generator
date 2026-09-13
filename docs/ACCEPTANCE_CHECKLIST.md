# Google Earth Pro Acceptance Checklist

Everything the automated test suite and `validate-output`/`audit-data` check
is XML/geometry/attribute-level: well-formed KML, coordinates in range,
folder `<visibility>` flags matching config, no silently dropped features.
**None of it proves the file actually behaves correctly inside Google Earth
Pro** -- rendering, toggle interactivity, `NetworkLink` fetch behavior, and
perceived performance can only be confirmed by opening the file in the real
application. This checklist is that manual step. As of this review, every
item below is unverified in actual Google Earth Pro and requires a human to
run it.

Build the POC before starting: `python -m txdot_overlay package-poc
--district "Tyler"`, then open `dist/poc_tyler/master.kml`.

## Checklist

1. **Default visibility of district boundaries** -- On opening master.kml,
   the "District Boundaries" folder is checked and all 25 district outlines
   (amber, thick, unfilled) are drawn immediately, with no roadway data
   loading.
2. **Default hidden state of district details** -- The "District Details"
   folder is unchecked on open; no county boundaries or roads are visible
   until the user opens it.
3. **Individual district toggles** -- Unchecking one district polygon (e.g.
   Tyler) under "District Boundaries" hides only that polygon; the other 24
   remain visible and independently toggleable.
4. **County-level toggles** -- Expanding District Details -> Tyler and
   checking "Smith" loads and displays Smith County's boundary and roads;
   unchecking it removes them without affecting other counties.
5. **Roadway-category toggles** -- Within Smith's "TxDOT Roadways" folder,
   toggling "Interstate" off hides only IH-20 segments; State Highway, US
   Highway, FM/RM, Loop/Spur/Business, and Other remain visible and
   independently toggleable.
6. **Correct HSYS styling** -- Visual colors match config: Interstate blue,
   US Highway red, State Highway gold, FM/RM green, Loop/Spur/Business
   purple, Other gray. Spot-check IH-20 (blue), a US-route, an FM road, and
   at least one "Other" (CR/TL/LS-coded) segment.
7. **Readable roadway popups** -- Clicking a road segment shows a popup
   table (not raw escaped HTML text, not a blank box) with highway
   designation, HSYS, street name, control section, lane count, speed
   limit, and lane-miles where present.
8. **Relative NetworkLink portability** -- Copy `dist/poc_tyler/` to a
   different path (a USB drive, another machine, a zipped-and-reopened
   folder) and confirm Tyler's 8 counties still load. (The automated test
   suite verifies the href strings are relative and resolve on disk; it
   cannot verify Google Earth Pro itself follows them after a real move.)
9. **Smith County boundary clipping** -- Zoom to Smith County's edge (e.g.
   the Cherokee or Rusk County line) and confirm no roadway segment
   visibly crosses into a neighboring county -- clipping should cut roads
   at the boundary, not just at whichever vertex happened to be nearest.
10. **Tyler District's eight counties** -- Confirm all eight county folders
    (Anderson, Cherokee, Gregg, Henderson, Rusk, Smith, Van Zandt, Wood)
    appear under the Tyler District folder, each independently toggleable,
    each loading its own boundary + roads.
11. **Linked-output performance** -- With only "District Boundaries" open,
    master.kml should load in well under a second with no visible lag when
    panning/zooming statewide. Opening one additional county (e.g. Smith)
    should not introduce a perceptible statewide slowdown.
12. **Single-file KMZ comparison** -- Build
    `python -m txdot_overlay build-all --district "Tyler" --single-file-kmz`
    and open `txdot_overlay_single_file.kmz` side by side with the linked
    master.kml. Confirm both render the same Tyler-area content, but note
    the single-file version's slower initial load (everything parses at
    open instead of on toggle) -- this is the tradeoff the split
    master/KMZ design exists to avoid at statewide scale.

## Additional checklist: popup/classification phase

13. **"Local, County & Other Roads" folder** -- the renamed folder (formerly
    "Other TxDOT-Maintained Road") appears under each county's TxDOT
    Roadways, styled thin muted gray, visually subordinate to the state
    highway categories above it.
14. **Grade-Separated Connectors are visually subordinate** -- when
    manually enabled (Reference Geometry > Grade-Separated Connectors is
    hidden by default), the connector segments render as a thin, muted,
    low-contrast line, never mistaken at a glance for a real drivable road.
15. **Grouped popups render cleanly** -- clicking a roadway segment shows
    section headers (Identity, Roadway Dimensions, ROW Reference,
    Operations & Traffic), only for sections with at least one populated
    field; no section renders as an empty header, and no field ever shows
    literal `nan`, `NaN`, `<NA>`, or `None` as a stand-in for a missing
    value (a decoded value that happens to legitimately be the word "None",
    e.g. Access Control, is expected and correct -- see
    `docs/FIELD_REFERENCE.md`).
16. **Friendly highway titles read naturally** -- placemark titles show
    "IH 20", "US 69", "FM 14" rather than raw `HWY` codes, while the popup's
    Identity section still shows the raw code (e.g. "Highway: IH0020")
    alongside the decoded route system.
17. **ROW_MIN disclaimer is visible whenever shown** -- any popup
    displaying "Minimum recorded ROW width" also shows the adjoining
    "Inventory reference value; not a surveyed ROW boundary." note.

## Reporting results

For each item, record: pass/fail, Google Earth Pro version, OS, and for any
failure, what was seen instead of what was expected. File-level issues
(wrong color, missing field) likely trace back to `config/config.yaml` or
`export/kml_builder.py`; interaction issues (toggle doesn't cascade, links
don't resolve) may be Google Earth Pro version-specific behavor worth
noting rather than a project bug.
