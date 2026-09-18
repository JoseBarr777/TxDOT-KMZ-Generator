"""Strips characters that are illegal in XML 1.0 text content.

Found via a real, reproducible failure: Cameron County's STE_NAM field
contains a raw ASCII control character (code point 4, "end of
transmission") inside the text "COVEWAY <ctrl-4>R ". html.escape() (used
throughout export/descriptions.py, and by simplekml's own non-CDATA text
escaping) only escapes ampersand/angle-bracket/quote characters -- it does
not touch control characters, which are simply illegal in XML 1.0 outside
of tab, newline, and carriage return. Left in place, that one field crashed
KMZ export for the entire county (simplekml re-parses its generated XML
with xml.dom.minidom to pretty-print it, which raises an ExpatError:
"not well-formed") rather than just rendering oddly.

This is not statewide-scope creep: it is a data-safety gap in the "escape
XML and attribute values safely" requirement that happened to be found via
a county outside the Tyler POC, but the fix applies to every text value
this project writes into KML, including Tyler's -- confirmed via a live
scan that Tyler's own data has no such characters today, but nothing
guarantees that stays true for a re-published Roadway Inventory.

Character ranges are built from integer code points (via chr()) rather
than typed as literal escape sequences, so this file never embeds an
actual control byte or noncharacter in its own source text.
"""

from __future__ import annotations

import re

# XML 1.0 legal text content, per the spec's Char production, is:
#   #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]
# Everything else is illegal -- most relevantly the C0 control codes other
# than tab/LF/CR (code points 0-8, 11, 12, 14-31) and a few reserved BMP
# noncharacters. A numeric character reference to one of these code points
# (e.g. "&#x04;") is *also* illegal per the XML spec, so stripping is
# correct, not just convenient -- there is no legal way to represent them.
_ILLEGAL_RANGES = [
    (0x00, 0x08),
    (0x0B, 0x0C),
    (0x0E, 0x1F),
    (0x7F, 0x84),
    (0x86, 0x9F),
    (0xFDD0, 0xFDEF),
    (0xFFFE, 0xFFFF),
]

_ILLEGAL_XML_CHARS_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _ILLEGAL_RANGES) + "]"
)


def strip_illegal_xml_chars(text: str) -> str:
    """Remove characters that cannot legally appear in XML 1.0 text content."""
    return _ILLEGAL_XML_CHARS_RE.sub("", text)
