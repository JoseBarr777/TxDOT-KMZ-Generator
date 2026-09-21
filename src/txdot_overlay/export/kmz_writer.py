"""Writes simplekml documents to disk as .kml or .kmz, creating parent directories."""

from __future__ import annotations

import zipfile
from pathlib import Path

import simplekml

from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)

# Earliest timestamp the zip format can represent. Stamping every entry with
# it makes a KMZ's bytes depend only on its contents.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _normalize_kmz(path: Path) -> None:
    """Rewrite a KMZ so identical content always produces identical bytes.

    A zip entry records the mtime of the file it was built from, so an
    otherwise unchanged KMZ gets a fresh checksum on every build. That would
    make manifest.json's sha256 useless for the question it exists to answer
    ("did this artifact actually change since the last release?") and would
    force a publisher to re-upload all 254 county KMZs plus the boundary
    artifacts on every run. Entries are written in sorted order with a fixed
    timestamp; nothing about the KML inside is touched.
    """
    with zipfile.ZipFile(path) as source:
        entries = [
            (info, source.read(info.filename))
            for info in sorted(source.infolist(), key=lambda i: i.filename)
        ]

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            normalized = zipfile.ZipInfo(info.filename, date_time=_ZIP_EPOCH)
            normalized.compress_type = zipfile.ZIP_DEFLATED
            normalized.external_attr = info.external_attr
            target.writestr(normalized, data)


def save_kml(kml: simplekml.Kml, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kml.save(str(path))
    logger.info("Wrote %s", path)
    return path


def save_kmz(kml: simplekml.Kml, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kml.savekmz(str(path))
    _normalize_kmz(path)
    logger.info("Wrote %s", path)
    return path
