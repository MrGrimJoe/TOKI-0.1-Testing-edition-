"""
test_extractor_clip_qr.py -- slot extraction tests for the 3 new intents
added this session: SAVE_CLIPBOARD_TO_FILE, GENERATE_QR_CODE, SCAN_QR_CODE.
New feature, so covered as thoroughly as extract_slots()'s existing
intents (see test_extractor.py's own convention note) -- every phrasing
variant, every "nothing extracted, defaults apply at dispatch time"
case, and the deliberate difference in contract between these three
(none of them ever return None the way e.g. GROUP_FILES_BY_EXTENSION
does on a missing required slot -- see each class's own docstring for
why).
"""

from extractor import extract_slots


class TestSaveClipboardToFileSlots:
    """No slot is ever required here -- "save the clipboard" alone is a
    complete instruction (defaults: timestamped filename, .md extension,
    both applied inside ClipboardFileAPI itself, not here). So this
    intent's extract_slots() call NEVER returns None -- unlike e.g.
    GROUP_FILES_BY_EXTENSION's required dest_name/extensions."""

    def test_bare_request_returns_empty_slots_not_none(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "save the clipboard")
        assert result == {"filename": "", "extension": ""}

    def test_into_a_dot_md_file_phrasing_extracts_md(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "turn this into a .md file")
        assert result is not None
        assert result["extension"] == "md"

    def test_into_a_md_file_no_dot_phrasing_extracts_md(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "turn this into a md file")
        assert result is not None
        assert result["extension"] == "md"

    def test_as_markdown_phrasing_extracts_md(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "save what i copied as markdown")
        assert result is not None
        assert result["extension"] == "md"

    def test_as_a_text_file_phrasing_extracts_txt(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "save my clipboard as a text file")
        assert result is not None
        assert result["extension"] == "txt"

    def test_named_clause_extracts_filename(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "save the clipboard as a file called project notes")
        assert result is not None
        assert result["filename"] == "project notes"

    def test_no_extension_mentioned_leaves_it_empty_for_the_api_default(self):
        result = extract_slots("SAVE_CLIPBOARD_TO_FILE", "put the clipboard into a file")
        assert result is not None
        assert result["extension"] == ""


class TestGenerateQrCodeSlots:
    """Also never returns None -- "turn this into a QR code" with zero
    extractable content is a COMPLETE instruction whose content comes
    from the clipboard at dispatch time (QrCodeAPI.generate_qr_code's own
    fallback), not something extract_slots() should ever block on."""

    def test_bare_turn_this_into_a_qr_code_extracts_nothing_by_design(self):
        # "this" is anaphoric and not resolved here -- the empty content
        # slot is exactly what tells QrCodeAPI to fall back to the
        # clipboard, which is the whole point of this phrasing.
        result = extract_slots("GENERATE_QR_CODE", "turn this into a qr code")
        assert result == {"content": "", "filename": ""}

    def test_url_in_the_text_is_extracted_as_content(self):
        result = extract_slots("GENERATE_QR_CODE", "make a qr code for https://example.com/page")
        assert result is not None
        assert result["content"] == "https://example.com/page"

    def test_quoted_text_is_extracted_as_content(self):
        result = extract_slots("GENERATE_QR_CODE", 'make a qr code that says "call me back"')
        assert result is not None
        assert result["content"] == "call me back"

    def test_url_is_preferred_when_both_a_url_and_quotes_are_present(self):
        # _extract_url is tried first in extractor.py's implementation --
        # pin that ordering explicitly so a future edit can't silently
        # flip which one wins.
        result = extract_slots(
            "GENERATE_QR_CODE",
            'make a qr code for https://example.com saying "ignored text"',
        )
        assert result is not None
        assert result["content"] == "https://example.com"

    def test_named_clause_extracts_filename(self):
        result = extract_slots("GENERATE_QR_CODE", 'make a qr code for "hello" called wifi_code')
        assert result is not None
        assert result["filename"] == "wifi_code"

    def test_plain_sentence_with_no_url_or_quotes_extracts_no_content(self):
        result = extract_slots("GENERATE_QR_CODE", "generate a qr code")
        assert result is not None
        assert result["content"] == ""

    def test_name_it_phrasing_extracts_filename(self):
        # Found via live stress-testing (BETA 0.3.62): the exact real
        # phrasing "make a qr code of the text i just copied and name it
        # poppers" previously returned filename="" -- "name it X" wasn't
        # covered by _NAME_TRIGGERS at all (only "called X"/"named X").
        result = extract_slots(
            "GENERATE_QR_CODE",
            "make a qr code of the text i just copied and name it poppers",
        )
        assert result is not None
        assert result["filename"] == "poppers"


class TestScanQrCodeSlots:
    """No slots at all -- always acts on selection_context's current
    selection (same pattern as EXTRACT_SELECTED_FILE)."""

    def test_returns_empty_dict_not_none(self):
        result = extract_slots("SCAN_QR_CODE", "scan this qr code")
        assert result == {}

    def test_every_phrasing_variant_also_returns_empty_dict(self):
        for text in ["read this qr code", "whats in this qr code", "decode this qr code"]:
            assert extract_slots("SCAN_QR_CODE", text) == {}
