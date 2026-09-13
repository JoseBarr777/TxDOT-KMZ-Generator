from txdot_overlay.export.descriptions import build_description_html


def test_escapes_html_special_characters_in_values():
    html = build_description_html(
        {"STE_NAM": "Smith & Jones <Rd>"}, fields=["STE_NAM"]
    )
    assert "&amp;" in html
    assert "&lt;Rd&gt;" in html
    assert "<Rd>" not in html


def test_wraps_output_in_cdata():
    html = build_description_html({"NAME": "value"}, fields=["NAME"])
    assert html.startswith("<![CDATA[")
    assert html.endswith("]]>")


def test_only_includes_requested_fields():
    html = build_description_html(
        {"PUBLIC": "shown", "INTERNAL_ONLY": "hidden"}, fields=["PUBLIC"]
    )
    assert "shown" in html
    assert "hidden" not in html


def test_skips_none_and_empty_values():
    html = build_description_html({"A": None, "B": ""}, fields=["A", "B"])
    assert "No attributes." in html


def test_skips_nan_float_values_regression():
    """Regression test for the original bug: a NaN float must not render as "nan"."""
    html = build_description_html({"SPD_MAX": float("nan")}, fields=["SPD_MAX"])
    assert "nan" not in html.lower()
    assert "No attributes." in html


def test_skips_pandas_na_values():
    import pandas as pd

    html = build_description_html({"FIELD": pd.NA}, fields=["FIELD"])
    assert "<NA>" not in html
    assert "No attributes." in html


def test_uses_field_labels_when_provided():
    html = build_description_html(
        {"HSYS": "IH"}, fields=["HSYS"], field_labels={"HSYS": "Highway System"}
    )
    assert "Highway System" in html
    assert "IH" in html
