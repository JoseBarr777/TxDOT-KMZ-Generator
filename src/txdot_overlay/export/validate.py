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


def validate_master_kml(master_path: Path, config: Config) -> ValidationReport:
    report = ValidationReport()
    if not master_path.exists():
        report.add_error(f"Master KML not found: {master_path}")
        return report

    root = _parse_kml_bytes(master_path.read_bytes(), context=str(master_path), report=report)
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

    output_dir = master_path.parent
    missing_links = 0
    for link_el in root.iter(f"{KML_NS}href"):
        href = link_el.text
        if not href:
            continue
        target = (output_dir / href).resolve()
        if not target.exists():
            missing_links += 1
            report.add_warning(
                f"{master_path}: NetworkLink target does not exist yet: {href} "
                "(expected until its build-county/build-district run)"
            )
    if missing_links:
        logger.info("%d NetworkLink target(s) not yet built", missing_links)

    return report


def validate_county_kmz(kmz_path: Path) -> ValidationReport:
    report = ValidationReport()
    if not kmz_path.exists():
        report.add_error(f"County KMZ not found: {kmz_path}")
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
    """Validate the master KML and every county KMZ that exists on disk."""
    master_path = config.output_dir / config.master_kml_name
    report = validate_master_kml(master_path, config)

    districts_dir = config.output_dir / "districts"
    if districts_dir.exists():
        for kmz_path in sorted(districts_dir.glob("*/*.kmz")):
            sub_report = validate_county_kmz(kmz_path)
            report.errors.extend(sub_report.errors)
            report.warnings.extend(sub_report.warnings)

    return report
