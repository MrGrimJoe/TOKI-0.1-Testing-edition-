"""
test_video_downloader.py — unit tests for video_downloader/ (BETA 0.3.43,
new). Never hits a real network or a real browser: now_playing's UI
Automation calls are exercised against stub objects shaped like
pywinauto's WindowSpecification/ElementInfo, same pattern
test_app_control.py already uses for the same underlying dependency.
"""

import pytest

from video_downloader import download_video, InvalidUrlError, FfmpegNotFoundError


class _FakeElemInfo:
    def __init__(self, name="", class_name=""):
        self.name = name
        self.class_name = class_name


class _FakeElem:
    def __init__(self, name, value):
        self.element_info = _FakeElemInfo(name=name)
        self._value = value

    def get_value(self):
        return self._value


class _FakeWin:
    def __init__(self, class_name, edits=None):
        self.element_info = _FakeElemInfo(class_name=class_name)
        self._edits = edits or []

    def descendants(self, control_type=None):
        if control_type == "Edit":
            return self._edits
        return []


class TestDownloadVideoUrlValidation:
    def test_rejects_non_url_string(self):
        with pytest.raises(InvalidUrlError):
            download_video("not a link")

    def test_rejects_non_http_scheme(self):
        with pytest.raises(InvalidUrlError):
            download_video("ftp://example.com/video.mp4")

    def test_rejects_empty_string(self):
        with pytest.raises(InvalidUrlError):
            download_video("")


class TestFfmpegGating:
    def test_missing_ffmpeg_raises_clear_error(self, monkeypatch, tmp_path):
        import video_downloader as vd
        monkeypatch.setattr(vd.shutil, "which", lambda name: None)
        with pytest.raises(FfmpegNotFoundError, match="ffmpeg"):
            download_video("https://example.com/watch?v=abc", destination=str(tmp_path))


class TestNowPlaying:
    """Exercises now_playing.py's pure element-tree-walking logic against
    stub UI Automation objects -- never a real pywinauto/Windows call."""

    def test_looks_like_browser_true_for_chrome_class(self):
        from video_downloader.now_playing import _looks_like_browser
        win = _FakeWin("Chrome_WidgetWin_1")
        assert _looks_like_browser(win) is True

    def test_looks_like_browser_true_for_firefox_class(self):
        from video_downloader.now_playing import _looks_like_browser
        win = _FakeWin("MozillaWindowClass")
        assert _looks_like_browser(win) is True

    def test_looks_like_browser_false_for_unrelated_window(self):
        from video_downloader.now_playing import _looks_like_browser
        win = _FakeWin("Notepad")
        assert _looks_like_browser(win) is False

    def test_reads_address_bar_value_with_scheme(self):
        from video_downloader.now_playing import _read_address_bar_value
        win = _FakeWin(
            "Chrome_WidgetWin_1",
            edits=[_FakeElem("Address and search bar", "https://www.youtube.com/watch?v=abc123")],
        )
        assert _read_address_bar_value(win) == "https://www.youtube.com/watch?v=abc123"

    def test_adds_scheme_when_address_bar_shows_bare_domain(self):
        from video_downloader.now_playing import _read_address_bar_value
        win = _FakeWin(
            "Chrome_WidgetWin_1",
            edits=[_FakeElem("Address and search bar", "youtube.com/watch?v=xyz")],
        )
        assert _read_address_bar_value(win) == "https://youtube.com/watch?v=xyz"

    def test_returns_none_when_no_address_bar_present(self):
        from video_downloader.now_playing import _read_address_bar_value
        win = _FakeWin("Chrome_WidgetWin_1", edits=[_FakeElem("Some other field", "irrelevant")])
        assert _read_address_bar_value(win) is None

    def test_get_now_playing_url_returns_none_if_focused_window_lookup_fails(self, monkeypatch):
        import video_downloader.now_playing as npmod
        # Isolate this test to the address-bar strategy alone -- CDP is
        # exercised in its own TestCdpNowPlaying class below.
        monkeypatch.setattr(npmod, "get_now_playing_url_via_cdp", lambda: None, raising=False)

        def _boom():
            raise RuntimeError("no display")

        monkeypatch.setattr(npmod, "_looks_like_browser", npmod._looks_like_browser)
        import app_control
        monkeypatch.setattr(app_control, "_get_focused_window", _boom, raising=False)
        assert npmod.get_now_playing_url() is None

    def test_get_now_playing_url_none_for_non_browser_focused_window(self, monkeypatch):
        import video_downloader.now_playing as npmod
        monkeypatch.setattr(npmod, "get_now_playing_url_via_cdp", lambda: None, raising=False)
        import app_control
        monkeypatch.setattr(app_control, "_get_focused_window", lambda: _FakeWin("Notepad"), raising=False)
        assert npmod.get_now_playing_url() is None

    def test_get_now_playing_url_returns_value_for_browser_with_address_bar(self, monkeypatch):
        import video_downloader.now_playing as npmod
        monkeypatch.setattr(npmod, "get_now_playing_url_via_cdp", lambda: None, raising=False)
        import app_control
        win = _FakeWin(
            "Chrome_WidgetWin_1",
            edits=[_FakeElem("Address and search bar", "https://vimeo.com/12345")],
        )
        monkeypatch.setattr(app_control, "_get_focused_window", lambda: win, raising=False)
        assert npmod.get_now_playing_url() == "https://vimeo.com/12345"

    def test_get_now_playing_url_prefers_cdp_result_over_address_bar(self, monkeypatch):
        """When CDP confidently finds a playing video, that answer wins
        even if the focused window is a browser sitting on a different
        (non-playing) page -- CDP answers the real question, the
        address bar only answers 'what's focused'."""
        import video_downloader.now_playing as npmod
        monkeypatch.setattr(
            npmod, "get_now_playing_url_via_cdp",
            lambda: "https://www.youtube.com/watch?v=cdp_hit", raising=False,
        )
        import app_control
        win = _FakeWin(
            "Chrome_WidgetWin_1",
            edits=[_FakeElem("Address and search bar", "https://example.com/unrelated-tab")],
        )
        monkeypatch.setattr(app_control, "_get_focused_window", lambda: win, raising=False)
        assert npmod.get_now_playing_url() == "https://www.youtube.com/watch?v=cdp_hit"

    def test_get_now_playing_url_falls_back_when_cdp_raises(self, monkeypatch):
        """A broken/partial CDP probe (e.g. websocket-client missing,
        malformed response) must never take down the whole lookup --
        it should fall through to the address-bar strategy exactly as
        if CDP had just returned None."""
        import video_downloader.now_playing as npmod

        def _boom():
            raise RuntimeError("websocket-client not installed")

        monkeypatch.setattr(npmod, "get_now_playing_url_via_cdp", _boom, raising=False)
        import app_control
        win = _FakeWin(
            "Chrome_WidgetWin_1",
            edits=[_FakeElem("Address and search bar", "https://vimeo.com/999")],
        )
        monkeypatch.setattr(app_control, "_get_focused_window", lambda: win, raising=False)
        assert npmod.get_now_playing_url() == "https://vimeo.com/999"
