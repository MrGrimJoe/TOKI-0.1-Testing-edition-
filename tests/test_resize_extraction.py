"""
test_resize_extraction.py -- covers a real bug found via chat review:
RESIZE_SELECTED_FILE's percentage extraction ignored direction entirely,
so "make this 50% bigger" and "shrink this by 50%" both produced the
same {"scale": "0.5"} (both shrink). No test previously covered this --
that's exactly how it shipped unnoticed. Tests the real public entry
point (extract_slots), not the private helper directly.
"""
import pytest

from extractor import extract_slots


class TestResizeDirection:
    def test_shrink_by_percent(self):
        slots = extract_slots("RESIZE_SELECTED_FILE", "shrink this image by 50%")
        assert slots == {"scale": "0.5"}

    def test_enlarge_by_percent(self):
        slots = extract_slots("RESIZE_SELECTED_FILE", "make this image 50% bigger")
        assert slots == {"scale": "1.5"}

    def test_enlarge_word_variants(self):
        for phrase in [
            "enlarge this by 25%",
            "make this 25% larger",
            "grow this image 25%",
        ]:
            slots = extract_slots("RESIZE_SELECTED_FILE", phrase)
            assert slots == {"scale": "1.25"}, phrase

    def test_shrink_word_variants_still_shrink(self):
        for phrase in [
            "shrink this by 25%",
            "make this 25% smaller",
            "reduce this image by 25%",
        ]:
            slots = extract_slots("RESIZE_SELECTED_FILE", phrase)
            assert slots == {"scale": "0.25"}, phrase

    def test_bare_percent_no_direction_word_defaults_to_shrink_fraction(self):
        # No enlarge/shrink word at all -- matches resize_file()'s own
        # default semantics (its no-args default IS a shrink).
        slots = extract_slots("RESIZE_SELECTED_FILE", "resize this to 50%")
        assert slots == {"scale": "0.5"}

    def test_explicit_dimensions_unaffected_by_direction_words(self):
        slots = extract_slots("RESIZE_SELECTED_FILE", "enlarge this to 800x600")
        assert slots == {"width": "800", "height": "600"}

    def test_no_number_returns_empty_dict(self):
        # "shrink this image" alone is a complete instruction --
        # resize_file()'s own default shrink applies, no slot needed.
        slots = extract_slots("RESIZE_SELECTED_FILE", "shrink this image")
        assert slots == {}
