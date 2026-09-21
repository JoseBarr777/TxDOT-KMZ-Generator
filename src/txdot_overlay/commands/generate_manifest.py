"""`generate-manifest`: write manifest.json describing every valid, currently-built
KML/KMZ artifact in the output directory.

Independent of `build-all` and `validate-output` -- run it any time after a
build to (re)generate manifest.json from whatever is on disk. See
export/manifest.py's module docstring for why it validates artifacts itself
instead of requiring `validate-output` to have been run first.
"""

from __future__ import annotations

import json

from txdot_overlay.config import Config
from txdot_overlay.export.manifest import build_manifest
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import get_cache, load_counties, load_districts

logger = get_logger(__name__)

MANIFEST_FILENAME = "manifest.json"


def run(config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    manifest = build_manifest(config, districts, counties)
    payload = manifest.to_dict()

    output_path = config.output_dir / MANIFEST_FILENAME
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")

    validation = payload["validation"]
    print(f"Release status:      {validation['status']}")
    print(f"Artifacts included:  {len(manifest.artifacts)}")
    print(
        f"  districts:         {validation['districts_included']}"
        f"/{validation['districts_expected']}"
    )
    print(
        f"  counties:          {validation['counties_included']}/{validation['counties_expected']}"
    )
    print(
        f"Required missing:    {validation['required_missing']}  "
        f"(invalid: {validation['required_invalid']})"
    )
    for skipped in manifest.skipped:
        marker = "REQUIRED" if skipped.required else "optional"
        print(f"  SKIPPED [{marker}] {skipped.path}: {skipped.reason}")
    print(f"Manifest written to {output_path}")

    return 0 if manifest.complete else 1
