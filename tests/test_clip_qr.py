"""
test_clip_qr.py -- thorough tests for clip_qr.py's three new capabilities:
SAVE_CLIPBOARD_TO_FILE, GENERATE_QR_CODE, SCAN_QR_CODE. All new this
session, so covered more heavily than a small change normally would be --
every success path, every failure path (missing package, missing
selection, sandbox rejection, write/read errors), and the QR-specific
clipboard-fallback behavior are each their own test.

Pure Python, no real PowerShell/Windows/network/qrcode/pyzbar needed --
subprocess.run, qrcode, pyzbar, and selection_context are all mocked or
monkeypatched, same posture as the rest of this suite (test_apis.py,
test_app_control.py).
"""

from unittest.mock import patch, MagicMock

import pytest

import extractor
from clip_qr import ClipboardFileAPI, QrCodeAPI, _read_clipboard_text


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    d_drive = tmp_path / "DDrive"
    desktop.mkdir()
    d_drive.mkdir()
    monkeypatch.setattr(extractor, "get_sandbox_roots",
                         lambda: [str(d_drive), str(desktop)])
    return desktop


def _clipboard_result(stdout):
    r = MagicMock()
    r.stdout = stdout
    return r


class TestReadClipboardText:
    def test_returns_stripped_text_on_success(self):
        with patch("clip_qr.subprocess.run", return_value=_clipboard_result("hello world\r\n")):
            assert _read_clipboard_text() == "hello world"

    def test_returns_empty_string_for_genuinely_empty_clipboard(self):
        with patch("clip_qr.subprocess.run", return_value=_clipboard_result("")):
            assert _read_clipboard_text() == ""

    def test_returns_none_on_subprocess_failure(self):
        with patch("clip_qr.subprocess.run", side_effect=OSError("powershell not found")):
            assert _read_clipboard_text() is None

    def test_returns_none_on_timeout(self):
        import subprocess as sp
        with patch("clip_qr.subprocess.run", side_effect=sp.TimeoutExpired(cmd="Get-Clipboard", timeout=5)):
            assert _read_clipboard_text() is None


class TestSaveClipboardToFile:
    def test_empty_clipboard_reports_nothing_to_save(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value=""):
            result = api.save_clipboard_to_file()
        assert "empty" in result.lower()
        assert not list(sandbox.iterdir())

    def test_clipboard_read_failure_is_friendly(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value=None):
            result = api.save_clipboard_to_file()
        assert "Couldn't read the clipboard" in result

    def test_default_filename_and_extension_is_timestamped_md(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="some copied text"):
            result = api.save_clipboard_to_file()
        written = list(sandbox.glob("clipboard_*.md"))
        assert len(written) == 1
        assert written[0].read_text(encoding="utf-8") == "some copied text"
        assert str(written[0]) in result or written[0].name in result

    def test_explicit_filename_is_used_verbatim(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="notes here"):
            api.save_clipboard_to_file(filename="my notes")
        assert (sandbox / "my notes.md").exists()
        assert (sandbox / "my notes.md").read_text(encoding="utf-8") == "notes here"

    def test_filename_already_having_the_right_extension_is_not_doubled(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="x"):
            api.save_clipboard_to_file(filename="notes.md")
        assert (sandbox / "notes.md").exists()
        assert not (sandbox / "notes.md.md").exists()

    def test_explicit_extension_overrides_default_md(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="plain text please"):
            api.save_clipboard_to_file(filename="notes", extension="txt")
        assert (sandbox / "notes.txt").exists()
        assert not (sandbox / "notes.md").exists()

    def test_extension_with_a_leading_dot_is_normalized(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="x"):
            api.save_clipboard_to_file(filename="notes", extension=".txt")
        assert (sandbox / "notes.txt").exists()

    def test_write_outside_sandbox_is_rejected(self, sandbox, monkeypatch):
        api = ClipboardFileAPI()
        # Simulate a traversal-style filename that would escape the
        # sandboxed Desktop -- is_within_sandbox() should catch this
        # exactly like every other filesystem-writing intent in this app.
        with patch("clip_qr._read_clipboard_text", return_value="x"):
            result = api.save_clipboard_to_file(filename="..\\..\\evil")
        assert "sandbox" in result.lower()

    def test_os_error_on_write_is_reported_cleanly(self, sandbox):
        api = ClipboardFileAPI()
        with patch("clip_qr._read_clipboard_text", return_value="x"), \
             patch("builtins.open", side_effect=OSError("disk full")):
            result = api.save_clipboard_to_file()
        assert "Couldn't write the file" in result

    def test_clipboard_with_special_shell_characters_is_written_as_plain_text(self, sandbox):
        # The whole safety point of this feature: nothing on the
        # clipboard is ever parsed as command syntax, only written as
        # literal file content.
        api = ClipboardFileAPI()
        payload = "$env:PATH; `whoami`; \"quoted\" & pipe | rm -rf /"
        with patch("clip_qr._read_clipboard_text", return_value=payload):
            api.save_clipboard_to_file(filename="danger")
        assert (sandbox / "danger.md").read_text(encoding="utf-8") == payload


class TestGenerateQrCode:
    def test_no_content_and_empty_clipboard_asks_what_to_encode(self, sandbox):
        api = QrCodeAPI()
        with patch("clip_qr._read_clipboard_text", return_value=""):
            result = api.generate_qr_code()
        assert "what should the qr code" in result.lower()

    def test_no_content_falls_back_to_clipboard(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        fake_img = MagicMock()
        fake_qrcode.make.return_value = fake_img
        with patch("clip_qr._read_clipboard_text", return_value="https://example.com"), \
             patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            result = api.generate_qr_code()
        fake_qrcode.make.assert_called_once_with("https://example.com")
        assert "Saved a QR code" in result

    def test_explicit_content_is_preferred_over_clipboard(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        with patch("clip_qr._read_clipboard_text", return_value="should not be used"), \
             patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            api.generate_qr_code(content="use this instead")
        fake_qrcode.make.assert_called_once_with("use this instead")

    def test_missing_qrcode_package_gives_install_instructions(self, sandbox):
        api = QrCodeAPI()
        with patch.dict("sys.modules", {"qrcode": None}):
            result = api.generate_qr_code(content="hello")
        assert "pip install qrcode" in result

    def test_default_filename_is_timestamped_png(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        fake_img = MagicMock()
        fake_qrcode.make.return_value = fake_img
        with patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            api.generate_qr_code(content="hello")
        saved_path = fake_img.save.call_args[0][0]
        assert saved_path.endswith(".png")
        assert "qrcode_" in saved_path

    def test_explicit_filename_gets_png_extension_appended(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        fake_img = MagicMock()
        fake_qrcode.make.return_value = fake_img
        with patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            api.generate_qr_code(content="hello", filename="my_code")
        saved_path = fake_img.save.call_args[0][0]
        assert saved_path.endswith("my_code.png")

    def test_filename_already_having_png_is_not_doubled(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        fake_img = MagicMock()
        fake_qrcode.make.return_value = fake_img
        with patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            api.generate_qr_code(content="hello", filename="mycode.png")
        saved_path = fake_img.save.call_args[0][0]
        assert saved_path.endswith("mycode.png")
        assert not saved_path.endswith("mycode.png.png")

    def test_write_outside_sandbox_is_rejected(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        with patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            result = api.generate_qr_code(content="hello", filename="..\\..\\evil")
        assert "sandbox" in result.lower()
        fake_qrcode.make.assert_not_called()

    def test_generation_exception_is_reported_cleanly_not_a_traceback(self, sandbox):
        api = QrCodeAPI()
        fake_qrcode = MagicMock()
        fake_qrcode.make.side_effect = RuntimeError("bad data for QR encoding")
        with patch.dict("sys.modules", {"qrcode": fake_qrcode}):
            result = api.generate_qr_code(content="hello")
        assert "Couldn't generate the QR code" in result
        assert "Traceback" not in result


class TestScanQrCode:
    def test_nothing_selected_asks_to_drag_a_file(self):
        api = QrCodeAPI()
        with patch.object(api, "_current_selection_path", return_value=None):
            result = api.scan_qr_code()
        assert "drag" in result.lower()

    def test_missing_pyzbar_package_gives_install_instructions(self):
        api = QrCodeAPI()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\code.png"), \
             patch.dict("sys.modules", {"pyzbar": None, "pyzbar.pyzbar": None}):
            result = api.scan_qr_code()
        assert "pip install pyzbar" in result

    def test_image_open_failure_is_friendly(self):
        api = QrCodeAPI()
        fake_pyzbar = MagicMock()
        fake_pil_image_mod = MagicMock()
        fake_pil_image_mod.Image.open.side_effect = OSError("cannot identify image file")
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\bad.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil_image_mod, "PIL.Image": fake_pil_image_mod.Image,
             }):
            result = api.scan_qr_code()
        assert "Couldn't open that image" in result

    def test_no_qr_code_found_reports_plainly(self):
        api = QrCodeAPI()
        fake_pyzbar = MagicMock()
        fake_pyzbar.decode.return_value = []
        fake_pil = MagicMock()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\plain.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil, "PIL.Image": fake_pil.Image,
             }):
            result = api.scan_qr_code()
        assert "Didn't find a QR code" in result

    def test_single_qr_code_reports_its_value(self):
        api = QrCodeAPI()
        fake_result = MagicMock()
        fake_result.data = b"https://example.com/hello"
        fake_pyzbar = MagicMock()
        fake_pyzbar.decode.return_value = [fake_result]
        fake_pil = MagicMock()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\code.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil, "PIL.Image": fake_pil.Image,
             }):
            result = api.scan_qr_code()
        assert result == "QR code says: https://example.com/hello"

    def test_multiple_qr_codes_are_all_reported(self):
        api = QrCodeAPI()
        r1, r2 = MagicMock(), MagicMock()
        r1.data = b"first"
        r2.data = b"second"
        fake_pyzbar = MagicMock()
        fake_pyzbar.decode.return_value = [r1, r2]
        fake_pil = MagicMock()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\multi.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil, "PIL.Image": fake_pil.Image,
             }):
            result = api.scan_qr_code()
        assert "Found 2 QR codes" in result
        assert "first" in result and "second" in result

    def test_decode_exception_is_reported_cleanly_not_a_traceback(self):
        api = QrCodeAPI()
        fake_pyzbar = MagicMock()
        fake_pyzbar.decode.side_effect = RuntimeError("zbar internal error")
        fake_pil = MagicMock()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\code.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil, "PIL.Image": fake_pil.Image,
             }):
            result = api.scan_qr_code()
        assert "Couldn't scan that image" in result
        assert "Traceback" not in result

    def test_undecodable_bytes_are_replaced_not_a_crash(self):
        api = QrCodeAPI()
        fake_result = MagicMock()
        fake_result.data = b"\xff\xfe not valid utf8"
        fake_pyzbar = MagicMock()
        fake_pyzbar.decode.return_value = [fake_result]
        fake_pil = MagicMock()
        with patch.object(api, "_current_selection_path", return_value="C:\\Desktop\\code.png"), \
             patch.dict("sys.modules", {
                 "pyzbar": MagicMock(), "pyzbar.pyzbar": fake_pyzbar,
                 "PIL": fake_pil, "PIL.Image": fake_pil.Image,
             }):
            result = api.scan_qr_code()  # must not raise
        assert result.startswith("QR code says:")


class TestGenerateThenScanRealRoundTrip:
    """No mocking of qrcode/pyzbar/PIL here at all -- generate_qr_code()
    writes a REAL PNG via the real qrcode package, and scan_qr_code()
    decodes that REAL file via the real pyzbar+PIL stack, through
    selection_context exactly as a genuine drag-drop would set it up.
    This is the strongest test in this file: it can't pass on a stubbed
    contract that happens to match what the mocks above assume -- if
    either real library's actual behavior differs from what the mocked
    tests assume, this is the one that would catch it.
    Skips itself gracefully if qrcode/pyzbar aren't installed in
    whatever environment runs this suite, same as any other optional-
    dependency test elsewhere in this project."""

    def teardown_method(self, method=None):
        # selection_context is a module-level singleton (same pattern as
        # target_memory.py's) -- clear it so a selection set here never
        # leaks into another test file sharing the same pytest process.
        from selection_context import get_selection_context
        get_selection_context().clear()

    def test_content_generated_is_exactly_what_gets_scanned_back(self, sandbox):
        pytest.importorskip("qrcode")
        pytest.importorskip("pyzbar")
        gen_api = QrCodeAPI()
        payload = "https://example.com/real-round-trip?x=1&y=2"
        result = gen_api.generate_qr_code(content=payload, filename="roundtrip")
        assert "Saved a QR code" in result
        png_path = sandbox / "roundtrip.png"
        assert png_path.exists()

        from selection_context import get_selection_context
        get_selection_context().set_selected(str(png_path))
        scan_api = QrCodeAPI()
        scan_result = scan_api.scan_qr_code()
        assert scan_result == f"QR code says: {payload}"

    def test_clipboard_fallback_content_survives_the_real_round_trip(self, sandbox):
        pytest.importorskip("qrcode")
        pytest.importorskip("pyzbar")
        gen_api = QrCodeAPI()
        with patch("clip_qr._read_clipboard_text", return_value="copied-from-clipboard-content"):
            result = gen_api.generate_qr_code(filename="clip_roundtrip")
        assert "Saved a QR code" in result
        png_path = sandbox / "clip_roundtrip.png"

        from selection_context import get_selection_context
        get_selection_context().set_selected(str(png_path))
        scan_api = QrCodeAPI()
        scan_result = scan_api.scan_qr_code()
        assert scan_result == "QR code says: copied-from-clipboard-content"
