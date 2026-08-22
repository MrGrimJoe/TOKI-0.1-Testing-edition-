"""
test_macro_recorder.py -- storage helpers (list/load/save, all pure file
I/O, no pynput needed) plus MacroPlayer's replay safety logic: verified
directly against a mocked capture_identity_at_point, since that's the part
carrying the actual safety guarantee (never click blind on an identity
mismatch -- see macro_recorder.py's module docstring, safety property 1).

Recording itself (MacroRecorder.start_recording/stop_recording) needs a
real pynput mouse/keyboard listener and isn't covered here -- same
"logically reviewed, not live-tested" honesty note as
capture_identity_at_point() in app_control.py.
"""

from unittest.mock import patch

import macro_recorder
from macro_recorder import (
    MacroRecorder, MacroPlayer, list_macros, load_macro, _safe_macro_filename,
)


class TestMacroFilenameSafety:
    def test_lowercases_and_strips(self):
        assert _safe_macro_filename("  Zeta  ") == "zeta"

    def test_replaces_unsafe_characters(self):
        assert _safe_macro_filename("youtuber mode!!") == "youtuber_mode__"

    def test_empty_name_falls_back_to_macro(self):
        assert _safe_macro_filename("   ") == "macro"


class TestMacroStorage:
    def test_list_macros_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path / "does_not_exist")
        assert list_macros() == []

    def test_save_then_list_then_load_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 1, "y": 2, "button": "left", "identity": None, "t": 0.0}]
        r.save("zeta")
        assert list_macros() == ["zeta"]
        assert load_macro("zeta") == r._events

    def test_load_missing_macro_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        assert load_macro("nope") is None

    def test_load_corrupt_macro_file_returns_none_not_a_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
        assert load_macro("broken") is None


class TestMacroPlayerSafety:
    """The actual safety property under test: identity mismatch aborts
    immediately and does NOT fall back to a blind coordinate click."""

    def _install_fake_pywinauto(self, monkeypatch):
        import sys, types
        import app_control
        # MacroPlayer.play() gates everything on app_control._load_pywinauto(),
        # which lazily probes the REAL pywinauto package on first call and then
        # caches True/False for the rest of the process (see app_control.py's
        # _load_pywinauto() docstring). Faking sys.modules["pywinauto.mouse"]/
        # ["pywinauto.keyboard"] below is not enough on its own: if the real,
        # uncached probe hasn't already succeeded by the time these tests run
        # (e.g. because nothing earlier in the session called it, or an
        # earlier test left the cached value at False), play() bails out at
        # its "isn't available" guard before ever reaching the faked mouse/
        # keyboard modules, and every assertion below silently sees an empty
        # `calls` list. Force it the same way test_app_control.py's own
        # _AppControlPywinautoFixture does, so these tests don't depend on
        # incidental probe/ordering state elsewhere in the suite.
        monkeypatch.setattr(app_control, "_PYWINAUTO_AVAILABLE", True)
        calls = []
        fake_mouse = types.ModuleType("pywinauto.mouse")
        fake_mouse.click = lambda button="left", coords=(0, 0): calls.append(("click", button, coords))
        fake_keyboard = types.ModuleType("pywinauto.keyboard")
        fake_keyboard.send_keys = lambda s: calls.append(("send_keys", s))
        sys.modules["pywinauto.mouse"] = fake_mouse
        sys.modules["pywinauto.keyboard"] = fake_keyboard
        return calls

    def test_matching_identity_clicks_normally(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        identity = {"name": "Save", "control_type": "Button", "class_name": "X"}
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 10, "y": 20, "button": "left", "identity": identity, "t": 0.0}]
        r.save("zeta")

        with patch("app_control.capture_identity_at_point", return_value=identity):
            result = MacroPlayer().play("zeta")

        assert calls == [("click", "left", (10, 20))]
        assert "finished" in result

    def test_identity_mismatch_aborts_without_clicking(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        recorded_identity = {"name": "Save", "control_type": "Button", "class_name": "X"}
        current_identity = {"name": "Discard Changes?", "control_type": "Button", "class_name": "X"}
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 10, "y": 20, "button": "left", "identity": recorded_identity, "t": 0.0}]
        r.save("zeta")

        with patch("app_control.capture_identity_at_point", return_value=current_identity):
            result = MacroPlayer().play("zeta")

        assert calls == []  # the whole point: no blind click happened
        assert "stopped at step 1" in result
        assert "Save" in result

    def test_missing_identity_at_record_time_degrades_to_coordinate_only(self, tmp_path, monkeypatch):
        # A step recorded with identity=None (capture failed live, e.g.
        # click landed on empty desktop) still replays via coordinates --
        # documented accepted gap, not silently dropped.
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 5, "y": 5, "button": "left", "identity": None, "t": 0.0}]
        r.save("zeta")

        result = MacroPlayer().play("zeta")  # no capture_identity_at_point patch needed -- never called for this step
        assert calls == [("click", "left", (5, 5))]
        assert "finished" in result

    def test_right_click_replays_as_right_click(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 1, "y": 1, "button": "Button.right", "identity": None, "t": 0.0}]
        r.save("zeta")
        MacroPlayer().play("zeta")
        assert calls == [("click", "right", (1, 1))]

    def test_missing_macro_reports_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        result = MacroPlayer().play("does_not_exist")
        assert "No macro named" in result

    def test_empty_macro_reports_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        r = MacroRecorder()
        r._events = []
        r.save("empty")
        result = MacroPlayer().play("empty")
        assert "no recorded steps" in result

    def test_key_press_step_replays_escaped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        r = MacroRecorder()
        r._events = [{"type": "key", "key": "{", "t": 0.0}]
        r.save("zeta")
        MacroPlayer().play("zeta")
        assert calls == [("send_keys", "{{}")]

    def test_special_key_uses_sendkeys_syntax(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        calls = self._install_fake_pywinauto(monkeypatch)
        r = MacroRecorder()
        r._events = [{"type": "key", "key": "Key.enter", "t": 0.0}]
        r.save("zeta")
        MacroPlayer().play("zeta")
        assert calls == [("send_keys", "{ENTER}")]

    def test_pywinauto_unavailable_reports_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        import app_control
        monkeypatch.setattr(app_control, "_PYWINAUTO_AVAILABLE", False)
        r = MacroRecorder()
        r._events = [{"type": "click", "x": 1, "y": 1, "button": "left", "identity": None, "t": 0.0}]
        r.save("zeta")
        result = MacroPlayer().play("zeta")
        assert "isn't available" in result
