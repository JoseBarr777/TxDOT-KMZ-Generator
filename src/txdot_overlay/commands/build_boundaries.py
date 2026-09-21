"""`build-boundaries`: build master.kml with district boundaries and county navigation."""

from __future__ import annotations

from txdot_overlay.config import Config
from txdot_overlay.export.kml_builder import build_master_kml
from txdot_overlay.export.kmz_writer import save_kml
from txdot_overlay.logging_setup import get_logger
from txdot_overlay.pipeline import get_cache, load_counties, load_districts
from txdot_overlay.styling.styles import StyleResolver

logger = get_logger(__name__)


def run(config: Config, *, force_refresh: bool = False) -> int:
    cache = get_cache(config)
    districts = load_districts(config, cache, force_refresh=force_refresh)
    counties = load_counties(config, cache, force_refresh=force_refresh)

    logger.info("Loaded %d district(s), %d count(y/ies)", len(districts), len(counties))

    style_resolver = StyleResolver(config)
    kml = build_master_kml(districts, counties, config, style_resolver)

    master_path = config.output_dir / config.master_kml_name
    save_kml(kml, master_path)
    logger.info(
        "Master KML built. NetworkLinks reference per-county KMZ files under "
        "%s/districts/ -- run build-district/build-county/build-all to create them.",
        config.output_dir,
    )
    return 0
