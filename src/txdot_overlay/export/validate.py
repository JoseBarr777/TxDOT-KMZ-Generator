"""Sanity-checks generated KML/KMZ output: well-formedness, links, coordinates, visibility."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from txdot_overlay.config import Config
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)

KML_NS = "{http://www.opengis.net/kml/2.2}"

# Generous Texas bounding box (lon/lat, WGS84) used only as a sanity check.
TEXAS_BOUNDS = {"min_lon": -106.7, "max_lon": -93.3, "min_lat": 25.7, "max_lat": 36.6}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        logger.error(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)


def _parse_kml_bytes(data: bytes, *, context: str, report: ValidationReport) -> ET.Element | None:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        report.add_error(f"{context}: not well-formed XML: {exc}")
        return None


def _check_coordinates_text(coord_text: str, *, context: str, report: ValidationReport) -> None:
    for tuple_str in coord_text.split():
        parts = tuple_str.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            report.add_error(f"{context}: non-numeric coordinate {tuple_str!r}")
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            report.add_error(f"{context}: coordinate out of range: {lon}, {lat}")
        elif not (
            TEXAS_BOUNDS["min_lon"] <= lon <= TEXAS_BOUNDS["max_lon"]
            and TEXAS_BOUNDS["min_lat"] <= lat <= TEXAS_BOUNDS["max_lat"]
        ):
            report.add_warning(f"{context}: coordinate outside expected Texas bounds: {lon}, {lat}")


def _validate_kml_element(root: ET.Element, *, context: str, report: ValidationReport) -> None:
    for coords_el in root.iter(f"{KML_NS}coordinates"):
        if coords_el.text:
            _check_coordinates_text(coords_el.text, context=context, report=report)


def _check_folder_visibility(
    root: ET.Element,
    folder_name: str,
    expected_visible: bool,
    *,
    context: str,
    report: ValidationReport,
) -> None:
    for folder in root.iter(f"{KML_NS}Folder"):
        name_el = folder.find(f"{KML_NS}name")
        if name_el is None or name_el.text != folder_name:
            continue
        vis_el = folder.find(f"{KML_NS}visibility")
        actual_visible = vis_el is None or vis_el.text != "0"
        if actual_visible != expected_visible:
            report.add_error(
                f"{context}: folder {folder_name!r} visibility is "
                f"{actual_visible} but expected {expected_visible}"
            )
        return
    report.add_warning(f"{context}: folder {folder_name!r} not found")


def _load_kml_root(path: Path, report: ValidationReport) -> ET.Element | None:
    if not path.exists():
        report.add_error(f"KML not found: {path}")
        return None
    return _parse_kml_bytes(path.read_bytes(), context=str(path), report=report)


def _check_network_link_targets(root: ET.Element, kml_path: Path, report: ValidationReport) -> None:
    """Resolve every NetworkLink href relative to the document's own directory.

    Unbuilt targets are warnings, not errors: master.kml and each district
    KML legitimately reference counties that a scoped build hasn't produced
    yet. Whether that shortfall blocks a release is the manifest's call
    (see export/manifest.py's completeness model), not this check's.
    """
    base_dir = kml_path.parent
    missing_links = 0
    for link_el in root.iter(f"{KML_NS}href"):
        href = link_el.text
        if not href:
            continue
        target = (base_dir / href).resolve()
        if not target.exists():
            missing_links += 1
            report.add_warning(
                f"{kml_path}: NetworkLink target does not exist yet: {href} "
                "(expected until its build-county/build-district run)"
            )
    if missing_links:
        logger.info("%s: %d NetworkLink target(s) not yet built", kml_path, missing_links)


def validate_kml_document(kml_path: Path) -> ValidationReport:
    """Generic .kml checks: present, well-formed, sane coordinates, links resolve.

    Used for any plain-KML artifact with no document-specific structure to
    assert -- currently the per-district NetworkLink KMLs. master.kml has
    its own validator below that adds the folder checks it guarantees.
    """
    report = ValidationReport()
    root = _load_kml_root(kml_path, report)
    if root is None:
        return report
    _validate_kml_element(root, context=str(kml_path), report=report)
    _check_network_link_targets(root, kml_path, report)
    return report


def validate_master_kml(master_path: Path, config: Config) -> ValidationReport:
    report = ValidationReport()
    root = _load_kml_root(master_path, report)
    if root is None:
        return report

    _validate_kml_element(root, context=str(master_path), report=report)
    _check_folder_visibility(
        root,
        "District Boundaries",
        config.visibility_defaults["district_boundaries_folder"],
        context=str(master_path),
        report=report,
    )
    _check_folder_visibility(
        root,
        "District Details",
        config.visibility_defaults["district_details_folder"],
        context=str(master_path),
        report=report,
    )
    _check_network_link_targets(root, master_path, report)
    return report


def validate_kmz(kmz_path: Path) -> ValidationReport:
    """Generic .kmz checks: valid zip, contains KML, well-formed, sane coordinates.

    Applies to every KMZ this project ships -- county detail KMZs, the
    administrative-boundary collections, and the optional single-file
    build -- none of which need structure assertions beyond being a
    readable, well-formed archive.
    """
    report = ValidationReport()
    if not kmz_path.exists():
        report.add_error(f"KMZ not found: {kmz_path}")
        return report

    try:
        with zipfile.ZipFile(kmz_path) as zf:
            kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                report.add_error(f"{kmz_path}: no .kml file inside KMZ archive")
                return report
            data = zf.read(kml_names[0])
    except zipfile.BadZipFile as exc:
        report.add_error(f"{kmz_path}: not a valid KMZ/zip archive: {exc}")
        return report

    root = _parse_kml_bytes(data, context=str(kmz_path), report=report)
    if root is not None:
        _validate_kml_element(root, context=str(kmz_path), report=report)
    return report


def validate_output(config: Config) -> ValidationReport:
    """Validate every KML/KMZ artifact that currently exists on disk.

    Covers master.kml, the per-district NetworkLink KMLs, every county
    detail KMZ, and the administrative-boundary artifacts. Paths are sorted
    so the report reads the same way on every run.
    """
    master_path = config.output_dir / config.master_kml_name
    report = validate_master_kml(master_path, config)

    def merge(sub_report: ValidationReport) -> None:
        report.errors.extend(sub_report.errors)
        report.warnings.extend(sub_report.warnings)

    districts_dir = config.output_dir / "districts"
    if districts_dir.exists():
        for kml_path in sorted(districts_dir.glob("*.kml")):
            merge(validate_kml_document(kml_path))
        for kmz_path in sorted(districts_dir.glob("*/*.kmz")):
            merge(validate_kmz(kmz_path))

    boundaries_dir = config.output_dir / "boundaries"
    if boundaries_dir.exists():
        for kmz_path in sorted(boundaries_dir.glob("*.kmz")):
            merge(validate_kmz(kmz_path))

    return report
