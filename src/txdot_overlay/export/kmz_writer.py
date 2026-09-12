"""Writes simplekml documents to disk as .kml or .kmz, creating parent directories."""
from __future__ import annotations

from pathlib import Path

import simplekml

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def save_kml(kml: simplekml.Kml, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kml.save(str(path))
    logger.info("Wrote %s", path)
    return path


def save_kmz(kml: simplekml.Kml, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kml.savekmz(str(path))
    logger.info("Wrote %s", path)
    return path
