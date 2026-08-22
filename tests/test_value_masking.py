"""
test_value_masking.py -- formal tests for the v2.2 fix: masking likely
slot-value regions (URLs, drive paths, quoted strings, bare filename
tokens) before component extraction, so a component alias that happens
to appear incidentally inside a slot VALUE never gets treated as
semantic routing evidence.

See component_extractor.py's mask_value_regions() docstring and
TESTING_REPORT_V2.md for the discovery (found via
test_chain_splitting.py, not the 67-case benchmark) and the general,
deterministic, intent-agnostic design.
"""

import pytest

from pathlib import Path

from component_extractor import extract_components, all_component_ids


class TestFilenameStemFalsePositives:
    """A component alias inside a filename's STEM must not fire."""

    @pytest.mark.parametrize("text,forbidden_component", [
        ("open forecast.xlsx", "OBJECT_FORECAST"),
        ("download weather.exe", "OBJECT_WEATHER"),
        ("rename battery.txt to power.txt", "OBJECT_BATTERY"),
        ("open hostname.zip", "OBJECT_HOSTNAME"),
        ("find files named forecast.xlsx and budget.docx", "OBJECT_FORECAST"),
        ("compress network.pdf", "OBJECT_NETWORK"),
        ("read disk.csv", "OBJECT_DISK"),
    ])
    def test_filename_stem_not_treated_as_component(self, text, forbidden_component):
        extracted = extract_components(text)
        assert forbidden_component not in all_component_ids(extracted), (
            f"{text!r} should not extract {forbidden_component} -- "
            f"the keyword is inside a filename, not real semantic content"
        )


class TestPathFalsePositives:
    @pytest.mark.parametrize("text,forbidden_component", [
        (r"open C:\Users\me\forecast.xlsx", "OBJECT_FORECAST"),
        (r"delete D:\reports\battery.txt", "OBJECT_BATTERY"),
    ])
    def test_windows_path_not_treated_as_component(self, text, forbidden_component):
        extracted = extract_components(text)
        assert forbidden_component not in all_component_ids(extracted)


class TestUrlFalsePositives:
    @pytest.mark.parametrize("text,forbidden_component", [
        ("open https://weather.com/forecast", "OBJECT_FORECAST"),
        ("download https://example.com/battery-report.pdf", "OBJECT_BATTERY"),
    ])
    def test_url_not_treated_as_component(self, text, forbidden_component):
        extracted = extract_components(text)
        assert forbidden_component not in all_component_ids(extracted)


class TestQuotedValueFalsePositives:
    @pytest.mark.parametrize("text,forbidden_component", [
        ('rename this to "forecast"', "OBJECT_FORECAST"),
        ('make a file called "battery"', "OBJECT_BATTERY"),
    ])
    def test_quoted_value_not_treated_as_component(self, text, forbidden_component):
        extracted = extract_components(text)
        assert forbidden_component not in all_component_ids(extracted)


class TestLegitimateSemanticUsesArePreserved:
    """The fix must not suppress a real, non-slot-value occurrence."""

    @pytest.mark.parametrize("text,required_component", [
        ("get the forecast", "OBJECT_FORECAST"),
        ("what's the weather", "OBJECT_WEATHER"),
        ("check battery status", "OBJECT_BATTERY"),
        ("show my network info", "OBJECT_NETWORK"),
        ("whats my hostname", "OBJECT_HOSTNAME"),
        ("what's the forecast for tomorrow", "OBJECT_FORECAST"),
    ])
    def test_legitimate_use_still_extracted(self, text, required_component):
        extracted = extract_components(text)
        assert required_component in all_component_ids(extracted), (
            f"{text!r} should still extract {required_component} -- "
            f"masking must not suppress genuine semantic content"
        )


class TestDecimalNumberGuard:
    """A decimal number shares the word.word shape with a filename but
    must not be masked -- the extension-must-start-with-a-letter rule
    exists specifically for this."""

    def test_decimal_number_not_masked(self):
        extracted = extract_components("resize this image to 0.5")
        assert "ACTION_RESIZE" in all_component_ids(extracted)
        assert "OBJECT_IMAGE" in all_component_ids(extracted)


class TestRouterLevelIntegration:
    """End-to-end: the fix must change the actual routing decision, not
    just the intermediate extraction."""

    def test_open_forecast_xlsx_does_not_route_to_get_forecast(self):
        from component_router_kuzu import KuzuComponentRouter
        router = KuzuComponentRouter(str(Path(__file__).resolve().parent.parent / "toki_graph_db"))
        result = router.classify("open forecast.xlsx")
        assert result != {"intent": "GET_FORECAST"}
        router.close()

    def test_get_the_forecast_still_routes_correctly(self):
        from component_router_kuzu import KuzuComponentRouter
        router = KuzuComponentRouter(str(Path(__file__).resolve().parent.parent / "toki_graph_db"))
        result = router.classify("get the forecast")
        assert result == {"intent": "GET_FORECAST"}
        router.close()

    def test_rename_two_filenames_no_longer_oversplits_in_chain(self):
        """The exact bug found via test_chain_splitting.py: masking
        "forecast.xlsx" so it no longer independently looks like a
        confident GET_FORECAST candidate, which previously caused
        orchestrator.py's real _split_chain_if_viable() to accept a
        wrong 2-way split of "rename budget.xlsx and forecast.xlsx"."""
        from orchestrator import _split_chain_if_viable
        from component_router_kuzu import KuzuComponentRouter
        router = KuzuComponentRouter(str(Path(__file__).resolve().parent.parent / "toki_graph_db"))
        segments = _split_chain_if_viable("rename budget.xlsx and forecast.xlsx", router)
        assert len(segments) == 1, f"should not split, got {segments}"
        router.close()
