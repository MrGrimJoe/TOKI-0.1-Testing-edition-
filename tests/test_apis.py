"""
test_apis.py -- pins this session's (BETA 0.3.7) fix to apis.py's failure
messages, plus the BETA 0.3.28 LocationCache failure-caching fix.
Pure Python, no network/Windows/Ollama needed.
"""

from unittest.mock import patch, MagicMock

import requests

from apis import is_api_failure, _friendly_request_error, FAILURE_PREFIXES, LocationCache, WebSearchAPI


class TestFriendlyFailureMessages:
    """Live repro: a real DNS failure surfaced as a raw exception dump --
    "Weather lookup failed: HTTPSConnectionPool(host='api.open-meteo.com',
    port=443): Max retries exceeded with url: ... NameResolutionError(...".
    That string was then handed directly to the narration model and asked
    to "narrate this in one sentence", which produced a fluent but
    completely disconnected sentence ("Checking how many files are on
    your desktop") instead of conveying the failure -- there was nothing
    in the raw exception text resembling normal narration to paraphrase.
    Fixed in two parts: apis.py now classifies the exception into a
    short, honest, non-technical reason (this file), and orchestrator.py
    skips asking the model to narrate a known failure at all (see
    test_orchestrator.py's api-kind dispatch, exercised indirectly here
    via is_api_failure())."""

    def test_connection_error_is_friendly_not_a_raw_dump(self):
        e = requests.exceptions.ConnectionError("HTTPSConnectionPool(host='api.open-meteo.com', port=443): ...")
        msg = _friendly_request_error(e, "Weather lookup", "the weather service")
        assert "NameResolutionError" not in msg
        assert "HTTPSConnectionPool" not in msg
        assert "can't reach the internet" in msg

    def test_timeout_is_friendly(self):
        msg = _friendly_request_error(requests.exceptions.Timeout(), "Forecast lookup", "the weather service")
        assert "too long" in msg

    def test_generic_exception_never_leaks_raw_repr(self):
        msg = _friendly_request_error(ValueError("some obscure internal detail"), "Weather lookup", "x")
        assert "some obscure internal detail" not in msg

    def test_failure_messages_are_detected(self):
        for prefix in FAILURE_PREFIXES:
            assert is_api_failure(f"{prefix}: something went wrong.")

    def test_real_result_is_not_a_failure(self):
        assert not is_api_failure("Lahore: 32.1\u00b0C, wind 8.4 km/h")


# ─── BETA 0.3.28: a failed ipinfo.io lookup must never be cached ──────────
#
# LocationCache used to set self._cached to the all-zero/failed fallback
# dict on ANY failure (network hiccup, DNS blip, rate limit) and
# `if self._cached is not None: return` treated that identically to a
# genuine successful fetch -- so a single transient failure permanently
# degraded every location-dependent feature (weather with no city given,
# etc.) for the rest of the session, with no TTL and no retry. Fixed the
# same way as app_control.py's AppController app cache: only a REAL
# success is ever stored in self._cached; a failure is never cached and
# just returns the zero-fallback for that one call, retrying for real
# after _FAILURE_RETRY_SECONDS.

class TestLocationCacheDoesNotPermanentlyCacheFailures:
    def test_failure_is_not_cached_and_next_call_retries(self):
        cache = LocationCache()
        with patch("apis.requests.get", side_effect=OSError("network hiccup")):
            first = cache.get()
        assert first == {"city": "", "region": "", "country": "", "lat": 0.0, "lon": 0.0}
        # PRE-FIX: this would still be the zero-fallback forever, because
        # the failure itself got cached in self._cached. Force past the
        # retry backoff and confirm a real retry happens.
        cache._last_failure_time = 0.0  # "long ago"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "city": "Lahore", "region": "Punjab", "country": "PK", "loc": "31.5,74.3",
        }
        mock_resp.raise_for_status.return_value = None
        with patch("apis.requests.get", return_value=mock_resp) as mock_get:
            second = cache.get()
        assert mock_get.called, "a fresh call after the retry window must actually retry, not stay cached"
        assert second["city"] == "Lahore"

    def test_repeated_calls_during_failure_window_do_not_refetch_every_time(self):
        cache = LocationCache()
        with patch("apis.requests.get", side_effect=OSError("boom")) as mock_get:
            cache.get()
            cache.get()
            cache.get()
        assert mock_get.call_count == 1, (
            "repeated calls within the failure-retry window should not "
            "all pay the network-timeout cost again"
        )

    def test_successful_result_is_still_cached_normally(self):
        # Regression guard: fixing the failure-caching bug must not
        # accidentally remove caching for the successful case, which is
        # the whole point of this cache existing.
        cache = LocationCache()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "city": "Lahore", "region": "Punjab", "country": "PK", "loc": "31.5,74.3",
        }
        mock_resp.raise_for_status.return_value = None
        with patch("apis.requests.get", return_value=mock_resp) as mock_get:
            cache.get()
            cache.get()
        assert mock_get.call_count == 1, "a successful result must still be cached, not re-fetched every call"

    def test_http_error_status_also_treated_as_a_retryable_failure(self):
        # raise_for_status() failures (e.g. a real HTTP 500/429 from
        # ipinfo.io) are a SEPARATE code path from a raw connection error
        # -- must be caught by the same broad except Exception, not just
        # outright connection errors, and must not be cached as a success.
        cache = LocationCache()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")
        with patch("apis.requests.get", return_value=mock_resp):
            result = cache.get()
        assert result == {"city": "", "region": "", "country": "", "lat": 0.0, "lon": 0.0}
        assert cache._cached is None, "an HTTP-error response must not be cached as if it were a success"


class TestVideoDownloadAPI:
    """BETA 0.3.43, new: VideoDownloadAPI is the orchestrator-facing
    adapter over video_downloader/. Never touches the network or a real
    browser -- video_downloader.download_video and
    video_downloader.now_playing.get_now_playing_url are monkeypatched at
    their own module level, same "mock at the boundary this class
    actually calls" approach the rest of this file uses for requests.get."""

    def test_download_url_with_no_url_asks_for_one(self):
        from apis import VideoDownloadAPI
        api = VideoDownloadAPI()
        msg = api.download_url(url="")
        assert "link" in msg.lower()
        assert is_api_failure(msg)

    def test_download_url_success_reports_saved_path(self, monkeypatch):
        import video_downloader
        monkeypatch.setattr(video_downloader, "download_video", lambda url, audio_only=False: "/fake/out.mp4")
        from apis import VideoDownloadAPI
        api = VideoDownloadAPI()
        msg = api.download_url(url="https://youtu.be/abc123")
        assert msg == "Downloaded to /fake/out.mp4"
        assert not is_api_failure(msg)

    def test_download_url_failure_is_friendly_not_a_traceback(self, monkeypatch):
        import video_downloader

        def _boom(url, audio_only=False):
            raise RuntimeError("Video unavailable")

        monkeypatch.setattr(video_downloader, "download_video", _boom)
        from apis import VideoDownloadAPI
        api = VideoDownloadAPI()
        msg = api.download_url(url="https://youtu.be/gone")
        assert is_api_failure(msg)
        assert "Video unavailable" in msg

    def test_download_playing_with_nothing_detected_asks_for_a_link(self, monkeypatch):
        import video_downloader.now_playing as npmod
        monkeypatch.setattr(npmod, "get_now_playing_url", lambda: None)
        from apis import VideoDownloadAPI
        api = VideoDownloadAPI()
        msg = api.download_playing()
        assert is_api_failure(msg)
        assert "paste" in msg.lower()

    def test_download_playing_success_uses_detected_url(self, monkeypatch):
        import video_downloader.now_playing as npmod
        import video_downloader
        monkeypatch.setattr(npmod, "get_now_playing_url", lambda: "https://youtu.be/detected")
        monkeypatch.setattr(video_downloader, "download_video", lambda url, audio_only=False: "/fake/detected.mp4")
        from apis import VideoDownloadAPI
        api = VideoDownloadAPI()
        msg = api.download_playing()
        assert msg == "Downloaded to /fake/detected.mp4"


class TestWebSearchAPI:
    """
    BETA 0.3.44: search is no longer an API call -- it builds a real
    search-engine URL and hands it to Chrome. No network calls belong in
    this class's tests at all; every test here mocks subprocess.Popen and
    asserts on the URL/command that WOULD have been launched.
    """

    def test_empty_query_gives_no_query_message_without_touching_subprocess(self, monkeypatch):
        import subprocess
        called = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append((a, k)))
        api = WebSearchAPI()
        assert api.search("") == "No search query given."
        assert called == []

    def test_web_search_builds_google_url_and_launches(self, monkeypatch):
        import subprocess
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        api = WebSearchAPI()
        msg = api.search("how to install PyQt5")
        assert "Searching for 'how to install PyQt5' in Chrome." == msg
        ps_cmd = captured["args"][-1]
        assert "google.com/search?q=how+to+install+PyQt5" in ps_cmd

    def test_youtube_site_uses_youtube_native_search_url(self, monkeypatch):
        import subprocess
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        api = WebSearchAPI()
        api.search("lofi beats", site="youtube")
        ps_cmd = captured["args"][-1]
        assert "youtube.com/results?search_query=lofi+beats" in ps_cmd

    def test_youtube_uses_dedicated_media_browser_when_available(self, monkeypatch):
        # BETA 0.3.56: YouTube results try the dedicated CDP-debug-enabled
        # instance first (see video_downloader/media_browser.py) instead
        # of the plain _open_in_chrome() PowerShell path.
        from video_downloader import media_browser
        captured = {}
        monkeypatch.setattr(
            media_browser, "launch_media_browser",
            lambda url, **k: captured.setdefault("url", url) or True,
        )
        api = WebSearchAPI()
        msg = api.search("lofi beats", site="youtube")
        assert "media browser" in msg.lower()
        assert "youtube.com/results?search_query=lofi+beats" in captured["url"]

    def test_youtube_falls_back_to_plain_chrome_when_media_browser_unavailable(self, monkeypatch):
        # A failed/unavailable dedicated instance (no Chrome/Edge found,
        # etc.) must never break the search -- falls straight through to
        # the exact same plain path every other search already uses.
        import subprocess
        from video_downloader import media_browser
        monkeypatch.setattr(media_browser, "launch_media_browser", lambda url, **k: False)
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        api = WebSearchAPI()
        msg = api.search("lofi beats", site="youtube")
        assert "in Chrome." in msg
        assert "youtube.com/results?search_query=lofi+beats" in captured["args"][-1]

    def test_non_youtube_site_never_touches_media_browser(self, monkeypatch):
        from video_downloader import media_browser
        called = []
        monkeypatch.setattr(media_browser, "launch_media_browser", lambda url, **k: called.append(url) or True)
        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: MagicMock())
        api = WebSearchAPI()
        api.search("how to install PyQt5", site="web")
        assert called == []

    def test_unknown_site_falls_back_to_web(self, monkeypatch):
        import subprocess
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        api = WebSearchAPI()
        api.search("test query", site="not_a_real_site")
        ps_cmd = captured["args"][-1]
        assert "google.com/search" in ps_cmd

    def test_query_with_single_quote_does_not_break_powershell_command(self, monkeypatch):
        # Same bug class as app_control.py's "Assassin's Creed" fix --
        # confirming it separately here since this builds its own
        # PowerShell string, outside that shared escaping path.
        import subprocess
        captured = {}

        def fake_popen(args, **kwargs):
            captured["args"] = args
            return MagicMock()

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        api = WebSearchAPI()
        api.search("Assassin's Creed release date")
        ps_cmd = captured["args"][-1]
        assert "Assassin''s" not in ps_cmd  # not present in URL, but command must stay well-formed
        assert ps_cmd.count("Start-Process") >= 1

    def test_popen_failure_returns_search_failed_prefix(self, monkeypatch):
        import subprocess

        def raising_popen(*a, **k):
            raise OSError("no shell available")

        monkeypatch.setattr(subprocess, "Popen", raising_popen)
        api = WebSearchAPI()
        msg = api.search("anything")
        assert msg.startswith("Search failed")
        assert is_api_failure(msg)


class TestFileOrganizerAPI:
    """BETA 0.3.44, checkpoint 4: FileOrganizerAPI is the orchestrator-
    facing adapter over file_graph/. The underlying FileOrganizer is
    monkeypatched at the instance level here (same "mock at the boundary
    this class actually calls" convention as TestVideoDownloadAPI above)
    -- file_graph/'s own real-filesystem end-to-end behavior is covered
    separately in tests/test_file_graph.py."""

    def test_organize_with_no_path_asks_for_one(self):
        from apis import FileOrganizerAPI
        api = FileOrganizerAPI()
        msg = api.organize(path="")
        assert "folder" in msg.lower()
        assert is_api_failure(msg)

    def test_organize_success_passes_through_the_summary(self, monkeypatch):
        from apis import FileOrganizerAPI
        api = FileOrganizerAPI()
        monkeypatch.setattr(api._organizer, "organize",
                             lambda path, include_suggestions=False: "Organized automatically:\n  a.pdf -> School")
        msg = api.organize(path="/Desktop")
        assert "Organized automatically" in msg
        assert not is_api_failure(msg)

    def test_organize_coerces_include_suggestions_string_to_bool(self, monkeypatch):
        from apis import FileOrganizerAPI
        api = FileOrganizerAPI()
        captured = {}

        def fake_organize(path, include_suggestions=False):
            captured["include_suggestions"] = include_suggestions
            return "done"

        monkeypatch.setattr(api._organizer, "organize", fake_organize)
        api.organize(path="/Desktop", include_suggestions="true")
        assert captured["include_suggestions"] is True

        api.organize(path="/Desktop", include_suggestions="")
        assert captured["include_suggestions"] is False

    def test_organize_failure_is_friendly_not_a_traceback(self, monkeypatch):
        from apis import FileOrganizerAPI
        api = FileOrganizerAPI()

        def _boom(path, include_suggestions=False):
            raise RuntimeError("disk full")

        monkeypatch.setattr(api._organizer, "organize", _boom)
        msg = api.organize(path="/Desktop")
        assert is_api_failure(msg)
        assert "disk full" in msg


class TestFileGroupingAPI:
    """BETA 0.3.44, checkpoint 4: FileGroupingAPI is the orchestrator-
    facing adapter over file_grouping.py's fully-explicit
    GROUP_FILES_BY_EXTENSION action. See TestFileOrganizerAPI's own
    docstring just above for the same mocking convention; real-filesystem
    behavior is covered separately in tests/test_file_grouping.py."""

    def test_group_with_missing_slots_asks_for_them(self):
        from apis import FileGroupingAPI
        api = FileGroupingAPI()
        assert is_api_failure(api.group(path="", extensions=".pdf", dest_name="rezero"))
        assert is_api_failure(api.group(path="/Desktop", extensions="", dest_name="rezero"))
        assert is_api_failure(api.group(path="/Desktop", extensions=".pdf", dest_name=""))

    def test_group_splits_comma_joined_extensions(self, monkeypatch):
        from apis import FileGroupingAPI
        api = FileGroupingAPI()
        captured = {}

        def fake_group(path, extensions, dest_name):
            captured["extensions"] = extensions
            return "Moved 2 file(s)"

        monkeypatch.setattr(api, "_group", fake_group)
        api.group(path="/Desktop", extensions=".pdf,.json", dest_name="rezero")
        assert captured["extensions"] == [".pdf", ".json"]

    def test_group_failure_is_friendly_not_a_traceback(self, monkeypatch):
        from apis import FileGroupingAPI
        api = FileGroupingAPI()

        def _boom(path, extensions, dest_name):
            raise RuntimeError("permission denied")

        monkeypatch.setattr(api, "_group", _boom)
        msg = api.group(path="/Desktop", extensions=".pdf", dest_name="rezero")
        assert is_api_failure(msg)
        assert "permission denied" in msg
