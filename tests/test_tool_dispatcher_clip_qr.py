"""
test_tool_dispatcher_clip_qr.py -- confirms orchestrator.py's ToolDispatcher
actually routes the 3 new intents to the right method on the right object,
and that INTENTS itself has each one wired with a matching kind/api/action
triple. clip_qr.py's classes are already unit-tested directly in
test_clip_qr.py -- this file is specifically about the WIRING between
orchestrator.INTENTS / ToolDispatcher._apis and those classes, which is
its own failure mode (e.g. a typo'd api key, or an intent whose "action"
string doesn't match any real method) that per-class unit tests can't
catch on their own.
"""

from unittest.mock import patch

import orchestrator
from orchestrator import ToolDispatcher, INTENTS
from clip_qr import ClipboardFileAPI, QrCodeAPI


class TestIntentsAreWiredCorrectly:
    def test_save_clipboard_to_file_intent_shape(self):
        meta = INTENTS["SAVE_CLIPBOARD_TO_FILE"]
        assert meta["kind"] == "api"
        assert meta["api"] == "clipboardfile"
        assert meta["action"] == "save_clipboard_to_file"
        assert hasattr(ClipboardFileAPI, meta["action"])

    def test_generate_qr_code_intent_shape(self):
        meta = INTENTS["GENERATE_QR_CODE"]
        assert meta["kind"] == "api"
        assert meta["api"] == "qrcode"
        assert meta["action"] == "generate_qr_code"
        assert hasattr(QrCodeAPI, meta["action"])

    def test_scan_qr_code_intent_shape(self):
        meta = INTENTS["SCAN_QR_CODE"]
        assert meta["kind"] == "api"
        assert meta["api"] == "qrcode"
        assert meta["action"] == "scan_qr_code"
        assert hasattr(QrCodeAPI, meta["action"])


class TestToolDispatcherRouting:
    def test_clipboardfile_is_registered_under_the_expected_key(self):
        d = ToolDispatcher()
        assert "clipboardfile" in d._apis
        assert isinstance(d._apis["clipboardfile"], ClipboardFileAPI)

    def test_qrcode_is_registered_under_the_expected_key(self):
        d = ToolDispatcher()
        assert "qrcode" in d._apis
        assert isinstance(d._apis["qrcode"], QrCodeAPI)

    def test_call_dispatches_save_clipboard_to_file_with_its_slots(self):
        d = ToolDispatcher()
        with patch.object(d.clipboardfile, "save_clipboard_to_file", return_value="Saved.") as m:
            result = d.call(
                {"api": "clipboardfile", "action": "save_clipboard_to_file"},
                {"filename": "notes", "extension": "md"},
            )
        m.assert_called_once_with(filename="notes", extension="md")
        assert result == "Saved."

    def test_call_dispatches_generate_qr_code_with_its_slots(self):
        d = ToolDispatcher()
        with patch.object(d.qrcode, "generate_qr_code", return_value="Saved a QR code.") as m:
            result = d.call(
                {"api": "qrcode", "action": "generate_qr_code"},
                {"content": "https://example.com", "filename": ""},
            )
        m.assert_called_once_with(content="https://example.com", filename="")
        assert result == "Saved a QR code."

    def test_call_dispatches_scan_qr_code_with_no_slots(self):
        d = ToolDispatcher()
        with patch.object(d.qrcode, "scan_qr_code", return_value="QR code says: hi") as m:
            result = d.call({"api": "qrcode", "action": "scan_qr_code"}, {})
        m.assert_called_once_with()
        assert result == "QR code says: hi"

    def test_extra_unrecognized_slot_is_filtered_not_a_typeerror(self):
        # Mirrors ToolDispatcher.call()'s own TypeError-filter fallback
        # (used elsewhere for e.g. an empty optional city slot) -- confirms
        # it also covers these 3 new methods if extract_slots() ever hands
        # over a stray key none of them accept.
        d = ToolDispatcher()
        result = d.call(
            {"api": "qrcode", "action": "generate_qr_code"},
            {"content": "hello", "filename": "x", "unexpected_extra_key": "ignored"},
        )
        # Real call (not mocked) -- generate_qr_code handles a missing
        # qrcode package gracefully rather than raising, so this proves
        # the filtered call actually went through with the accepted
        # subset of kwargs instead of raising TypeError.
        assert "unexpected_extra_key" not in result

    def test_unknown_api_key_reports_plainly_not_a_crash(self):
        d = ToolDispatcher()
        result = d.call({"api": "not_a_real_api", "action": "whatever"}, {})
        assert "Unknown API action" in result

    def test_unknown_action_on_a_real_api_reports_plainly_not_a_crash(self):
        d = ToolDispatcher()
        result = d.call({"api": "qrcode", "action": "not_a_real_method"}, {})
        assert "Unknown API action" in result
