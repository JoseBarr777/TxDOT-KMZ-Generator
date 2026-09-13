from txdot_overlay.xml_safety import strip_illegal_xml_chars


def test_strips_control_character_reproducing_cameron_county_bug():
    """Regression test: Cameron County's STE_NAM contained a literal
    end-of-transmission control character (code point 4) that crashed KMZ
    export with an XML ExpatError (not well-formed)."""
    raw = "COVEWAY " + chr(4) + "R "
    assert strip_illegal_xml_chars(raw) == "COVEWAY R "


def test_preserves_tab_newline_carriage_return():
    text = "a\tb\nc\rd"
    assert strip_illegal_xml_chars(text) == text


def test_preserves_ordinary_text_and_punctuation():
    text = "Smith & Jones Rd, FM 14 (North)"
    assert strip_illegal_xml_chars(text) == text


def test_strips_c0_control_codes():
    for code_point in [0, 1, 7, 8, 11, 12, 14, 31]:
        text = f"before{chr(code_point)}after"
        assert strip_illegal_xml_chars(text) == "beforeafter"


def test_preserves_unicode_letters():
    text = "Café Road"  # combining accent, legal in XML
    assert strip_illegal_xml_chars(text) == text


def test_strips_unicode_noncharacters():
    assert strip_illegal_xml_chars("a￾b￿c") == "abc"


def test_empty_string_unaffected():
    assert strip_illegal_xml_chars("") == ""
