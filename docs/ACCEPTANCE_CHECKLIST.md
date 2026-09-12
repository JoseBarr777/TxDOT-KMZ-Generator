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

## Reporting results

For each item, record: pass/fail, Google Earth Pro version, OS, and for any
failure, what was seen instead of what was expected. File-level issues
(wrong color, missing field) likely trace back to `config/config.yaml` or
`export/kml_builder.py`; interaction issues (toggle doesn't cascade, links
don't resolve) may be Google Earth Pro version-specific behavor worth
noting rather than a project bug.
