"""Google Earth launcher KMLs for the District/Statewide offline packages.

A launcher is the one obvious file a person opens after extracting a bulk
ZIP. It holds no GIS content -- only a named hierarchy of KML NetworkLinks,
each pointing at one packaged county KMZ by a relative archive path, all
starting unchecked (`visibility` 0). The county KMZs stay the canonical,
byte-identical artifacts; the launcher is navigation layered over them, and
nothing it references lives outside the extracted package (no hosted URLs,
no release IDs, no R2).

This is deliberately separate from the hosted `master.kml`/district KML
builders in `kml_builder.py`: those link relative to the hosted release
tree, which does not exist inside an extracted package. It is also built
with `xml.etree` rather than simplekml: launchers need no element IDs, and
simplekml's process-global ID counter would make launcher bytes depend on
what else the process built.

Output is deterministic: fixed element order, caller-supplied
(alphabetical) ordering, no timestamps or environment-specific content.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from txdot_overlay.export.layout import (
    STATEWIDE_LAUNCHER_ARCHIVE_PATH,
    STATEWIDE_PACKAGE_NAME,
    district_launcher_archive_path,
    offline_county_archive_path,
)

KML_NAMESPACE = "http://www.opengis.net/kml/2.2"

_DESCRIPTION = (
    "Check a county to load it in Google Earth. Every county file is included in this "
    "package; no Internet connection is needed."
)


def launcher_href(launcher: PurePosixPath, member: PurePosixPath) -> str:
    """`member`'s path relative to the directory `launcher` sits in."""
    return member.relative_to(launcher.parent).as_posix()


def _document(name: str) -> tuple[ET.Element, ET.Element]:
    kml = ET.Element("kml", xmlns=KML_NAMESPACE)
    document = ET.SubElement(kml, "Document")
    ET.SubElement(document, "name").text = name
    ET.SubElement(document, "open").text = "1"
    ET.SubElement(document, "description").text = _DESCRIPTION
    return kml, document


def _county_link(parent: ET.Element, county_name: str, href: str) -> None:
    link = ET.SubElement(parent, "NetworkLink")
    ET.SubElement(link, "name").text = f"{county_name} County"
    # Unchecked: Google Earth fetches a NetworkLink's target when it is
    # made visible, so a county is meant to load only once someone checks it.
    ET.SubElement(link, "visibility").text = "0"
    ET.SubElement(link, "open").text = "0"
    target = ET.SubElement(link, "Link")
    ET.SubElement(target, "href").text = href
    ET.SubElement(target, "refreshMode").text = "onChange"


def _serialize(kml: ET.Element) -> bytes:
    ET.indent(kml, space="  ")
    return ET.tostring(kml, encoding="utf-8", xml_declaration=True) + b"\n"


def build_district_launcher(district_name: str, county_names: list[str]) -> bytes:
    """Launcher for one District ZIP: a flat list of that district's counties."""
    launcher = district_launcher_archive_path(district_name)
    kml, document = _document(f"{district_name} District")
    for county_name in county_names:
        member = offline_county_archive_path(district_name, county_name)
        _county_link(document, county_name, launcher_href(launcher, member))
    return _serialize(kml)


def build_statewide_launcher(districts: list[tuple[str, list[str]]]) -> bytes:
    """Launcher for the Statewide ZIP: one folder per district, each holding
    that district's counties. Takes (district_name, county_names) pairs in the
    order they should appear.
    """
    launcher = STATEWIDE_LAUNCHER_ARCHIVE_PATH
    kml, document = _document(STATEWIDE_PACKAGE_NAME)
    for district_name, county_names in districts:
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = f"{district_name} District"
        ET.SubElement(folder, "visibility").text = "0"
        ET.SubElement(folder, "open").text = "0"
        for county_name in county_names:
            member = offline_county_archive_path(district_name, county_name)
            _county_link(folder, county_name, launcher_href(launcher, member))
    return _serialize(kml)
