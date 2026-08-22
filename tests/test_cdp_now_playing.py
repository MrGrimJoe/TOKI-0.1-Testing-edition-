"""
test_cdp_now_playing.py -- unit tests for video_downloader/cdp_now_playing.py
(BETA 0.3.44, new). Never opens a real socket: the HTTP discovery step
and the websocket RPC step are both faked at the boundary
(`urlopen` / `websocket.create_connection`), same "stub the external
edge, exercise the real logic" pattern tests/test_video_downloader.py
already uses for pywinauto.
"""

import json

import pytest

from video_downloader import cdp_now_playing as cdp


class _FakeHTTPResponse:
    """Minimal stand-in for what urlopen()'s context manager yields."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWebSocket:
    def __init__(self, recv_payload, raise_on_connect=None, raise_on_send=None):
        self._recv_payload = recv_payload
        self._raise_on_connect = raise_on_connect
        self._raise_on_send = raise_on_send
        self.sent = []
        self.closed = False

    def send(self, data):
        if self._raise_on_send:
            raise self._raise_on_send
        self.sent.append(data)

    def recv(self):
        return json.dumps(self._recv_payload)

    def close(self):
        self.closed = True


def _cdp_eval_result(value: bool):
    return {"id": 1, "result": {"result": {"type": "boolean", "value": value}}}


class TestConfiguredPorts:
    def test_defaults_to_9222_without_override(self, monkeypatch):
        monkeypatch.delenv("TOKI_CHROME_CDP_PORT", raising=False)
        assert cdp._configured_ports() == (9222,)

    def test_uses_env_override_when_set(self, monkeypatch):
        monkeypatch.setenv("TOKI_CHROME_CDP_PORT", "9333")
        assert cdp._configured_ports() == (9333,)

    def test_falls_back_to_default_on_malformed_override(self, monkeypatch):
        monkeypatch.setenv("TOKI_CHROME_CDP_PORT", "not-a-port")
        assert cdp._configured_ports() == (9222,)


class TestListTabs:
    def test_returns_none_when_nothing_listening(self, monkeypatch):
        def _boom(*a, **k):
            raise OSError("Connection refused")
        monkeypatch.setattr(cdp, "urlopen", _boom)
        assert cdp._list_tabs(9222) is None

    def test_returns_none_on_malformed_json(self, monkeypatch):
        class _BadResp(_FakeHTTPResponse):
            def read(self):
                return b"not json"
        monkeypatch.setattr(cdp, "urlopen", lambda *a, **k: _BadResp([]))
        assert cdp._list_tabs(9222) is None

    def test_returns_none_when_payload_is_not_a_list(self, monkeypatch):
        monkeypatch.setattr(cdp, "urlopen", lambda *a, **k: _FakeHTTPResponse({"oops": True}))
        assert cdp._list_tabs(9222) is None

    def test_returns_tab_list_on_success(self, monkeypatch):
        tabs = [{"type": "page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://x"}]
        monkeypatch.setattr(cdp, "urlopen", lambda *a, **k: _FakeHTTPResponse(tabs))
        assert cdp._list_tabs(9222) == tabs


class TestTabHasPlayingVideo:
    def test_false_when_websocket_client_not_installed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def _fake_import(name, *a, **k):
            if name == "websocket":
                raise ImportError("no module named websocket")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        assert cdp._tab_has_playing_video("ws://irrelevant") is False

    def test_false_when_connection_fails(self, monkeypatch):
        fake_ws_module = type("m", (), {})()
        def _raise_connect(*a, **k):
            raise ConnectionRefusedError()
        fake_ws_module.create_connection = _raise_connect
        monkeypatch.setitem(__import__("sys").modules, "websocket", fake_ws_module)
        assert cdp._tab_has_playing_video("ws://irrelevant") is False

    def test_true_when_evaluate_reports_playing(self, monkeypatch):
        fake_ws_module = type("m", (), {})()
        fake_conn = _FakeWebSocket(_cdp_eval_result(True))
        fake_ws_module.create_connection = lambda *a, **k: fake_conn
        monkeypatch.setitem(__import__("sys").modules, "websocket", fake_ws_module)
        assert cdp._tab_has_playing_video("ws://irrelevant") is True
        assert fake_conn.closed is True

    def test_false_when_evaluate_reports_not_playing(self, monkeypatch):
        fake_ws_module = type("m", (), {})()
        fake_conn = _FakeWebSocket(_cdp_eval_result(False))
        fake_ws_module.create_connection = lambda *a, **k: fake_conn
        monkeypatch.setitem(__import__("sys").modules, "websocket", fake_ws_module)
        assert cdp._tab_has_playing_video("ws://irrelevant") is False

    def test_false_on_malformed_response(self, monkeypatch):
        fake_ws_module = type("m", (), {})()
        fake_conn = _FakeWebSocket({"unexpected": "shape"})
        fake_ws_module.create_connection = lambda *a, **k: fake_conn
        monkeypatch.setitem(__import__("sys").modules, "websocket", fake_ws_module)
        assert cdp._tab_has_playing_video("ws://irrelevant") is False

    def test_closes_connection_even_if_send_raises(self, monkeypatch):
        fake_ws_module = type("m", (), {})()
        fake_conn = _FakeWebSocket({}, raise_on_send=RuntimeError("broken pipe"))
        fake_ws_module.create_connection = lambda *a, **k: fake_conn
        monkeypatch.setitem(__import__("sys").modules, "websocket", fake_ws_module)
        assert cdp._tab_has_playing_video("ws://irrelevant") is False
        assert fake_conn.closed is True


class TestGetNowPlayingUrlViaCdp:
    def test_none_when_no_tabs_reachable(self, monkeypatch):
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: None)
        assert cdp.get_now_playing_url_via_cdp() is None

    def test_skips_non_page_targets(self, monkeypatch):
        tabs = [{"type": "background_page", "url": "https://example.com", "webSocketDebuggerUrl": "ws://x"}]
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: True)
        assert cdp.get_now_playing_url_via_cdp() is None

    def test_skips_non_http_targets(self, monkeypatch):
        tabs = [{"type": "page", "url": "chrome://newtab", "webSocketDebuggerUrl": "ws://x"}]
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: True)
        assert cdp.get_now_playing_url_via_cdp() is None

    def test_skips_tabs_without_a_debugger_url(self, monkeypatch):
        tabs = [{"type": "page", "url": "https://example.com"}]
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: True)
        assert cdp.get_now_playing_url_via_cdp() is None

    def test_returns_url_of_first_tab_with_playing_video(self, monkeypatch):
        tabs = [
            {"type": "page", "url": "https://a.example.com", "webSocketDebuggerUrl": "ws://a"},
            {"type": "page", "url": "https://b.example.com/watch", "webSocketDebuggerUrl": "ws://b"},
        ]
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: ws == "ws://b")
        assert cdp.get_now_playing_url_via_cdp() == "https://b.example.com/watch"

    def test_none_when_tabs_exist_but_nothing_playing(self, monkeypatch):
        tabs = [{"type": "page", "url": "https://a.example.com", "webSocketDebuggerUrl": "ws://a"}]
        monkeypatch.setattr(cdp, "_list_tabs", lambda port: tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: False)
        assert cdp.get_now_playing_url_via_cdp() is None

    def test_tries_every_configured_port(self, monkeypatch):
        """A second, non-default port (e.g. TOKI_CHROME_CDP_PORT set to
        something other than 9222) must still be checked, not just the
        first one silently returning None."""
        monkeypatch.setattr(cdp, "_configured_ports", lambda: (9222, 9333))
        calls = []

        def _fake_list_tabs(port):
            calls.append(port)
            if port == 9333:
                return [{"type": "page", "url": "https://c.example.com", "webSocketDebuggerUrl": "ws://c"}]
            return None

        monkeypatch.setattr(cdp, "_list_tabs", _fake_list_tabs)
        monkeypatch.setattr(cdp, "_tab_has_playing_video", lambda ws: True)
        assert cdp.get_now_playing_url_via_cdp() == "https://c.example.com"
        assert calls == [9222, 9333]
