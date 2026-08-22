"""
tests/test_media_browser.py -- BETA 0.3.56.

video_downloader/media_browser.py launches a real OS process on success;
every test here mocks subprocess.Popen (never actually launches a
browser) and os.path.exists/environ (never depends on this sandbox
actually having Chrome/Edge installed at a Windows path, since it
doesn't -- this is a Linux sandbox).
"""

import os
from unittest.mock import MagicMock

import pytest

from video_downloader import media_browser


class TestFindBrowserExe:
    def test_returns_none_when_nothing_exists(self, monkeypatch):
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        assert media_browser._find_browser_exe() is None

    def test_returns_first_existing_candidate(self, monkeypatch):
        # Simulate only the LocalAppData Chrome path existing.
        def fake_exists(path):
            return "LocalAppData" in path or "Local" in path

        monkeypatch.setattr(os.path, "exists", fake_exists)
        result = media_browser._find_browser_exe()
        assert result is not None
        assert result.endswith("chrome.exe") or result.endswith("msedge.exe")


class TestDedicatedProfileDir:
    def test_creates_a_toki_owned_directory_distinct_from_default_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LocalAppData", str(tmp_path))
        profile_dir = media_browser._dedicated_profile_dir()
        assert profile_dir == os.path.join(str(tmp_path), "TOKI", "MediaBrowserProfile")
        assert os.path.isdir(profile_dir)

    def test_idempotent_on_repeat_calls(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LocalAppData", str(tmp_path))
        first = media_browser._dedicated_profile_dir()
        second = media_browser._dedicated_profile_dir()
        assert first == second


class TestCdpPort:
    def test_defaults_to_9222(self, monkeypatch):
        monkeypatch.delenv("TOKI_CHROME_CDP_PORT", raising=False)
        assert media_browser._cdp_port() == 9222

    def test_honors_env_override(self, monkeypatch):
        monkeypatch.setenv("TOKI_CHROME_CDP_PORT", "9333")
        assert media_browser._cdp_port() == 9333

    def test_ignores_malformed_override(self, monkeypatch):
        monkeypatch.setenv("TOKI_CHROME_CDP_PORT", "not-a-number")
        assert media_browser._cdp_port() == 9222


class TestLaunchMediaBrowser:
    def test_returns_false_when_no_browser_found(self, monkeypatch):
        monkeypatch.setattr(media_browser, "_find_browser_exe", lambda: None)
        assert media_browser.launch_media_browser("https://youtube.com") is False

    def test_launches_with_debug_port_and_dedicated_profile_never_the_real_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr(media_browser, "_find_browser_exe", lambda: r"C:\fake\chrome.exe")
        monkeypatch.setattr(media_browser, "_dedicated_profile_dir", lambda: str(tmp_path / "MediaBrowserProfile"))
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(media_browser.subprocess, "Popen", fake_popen)
        ok = media_browser.launch_media_browser("https://youtube.com/results?search_query=x", port=9222)
        assert ok is True
        args = captured["args"]
        assert any(a.startswith("--remote-debugging-port=9222") for a in args)
        assert any("MediaBrowserProfile" in a for a in args)
        # Never the address flag that would expose this off localhost.
        assert not any("remote-debugging-address" in a for a in args)
        assert args[-1] == "https://youtube.com/results?search_query=x"

    def test_url_is_optional(self, monkeypatch, tmp_path):
        monkeypatch.setattr(media_browser, "_find_browser_exe", lambda: r"C:\fake\chrome.exe")
        monkeypatch.setattr(media_browser, "_dedicated_profile_dir", lambda: str(tmp_path))
        captured = {}
        monkeypatch.setattr(
            media_browser.subprocess, "Popen",
            lambda args, **k: captured.setdefault("args", args) or MagicMock(),
        )
        ok = media_browser.launch_media_browser()
        assert ok is True
        assert not captured["args"][-1].startswith("http")

    def test_popen_failure_returns_false_not_raises(self, monkeypatch):
        monkeypatch.setattr(media_browser, "_find_browser_exe", lambda: r"C:\fake\chrome.exe")
        monkeypatch.setattr(media_browser, "_dedicated_profile_dir", lambda: "/tmp/whatever")

        def raising_popen(*a, **k):
            raise OSError("boom")

        monkeypatch.setattr(media_browser.subprocess, "Popen", raising_popen)
        assert media_browser.launch_media_browser("https://x.com") is False
