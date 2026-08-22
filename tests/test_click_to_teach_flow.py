"""
test_click_to_teach_flow.py -- exercises the FULL click-to-teach round trip:
teach() actually writing a real identity, AND a LATER resolve_target() call
actually finding it.

Confirmed gap before this file: target_memory.py's storage layer had
thorough tests (tests/test_target_memory.py), and orchestrator.py's own
routing to teach_from_next_click() on a click miss had tests (see
TestClickToTeachFlow in tests/test_orchestrator.py) -- but those
orchestrator tests mock teach_from_next_click() itself out entirely, so
nothing anywhere actually proved that teaching a target and then asking
TOKI to click it AGAIN produces a successful click. AppController.teach()/
teach_from_next_click() themselves, and resolve_target()'s memory-recall
branch (_try_resolve_from_memory), had zero direct coverage. This file
closes that gap: the round trip (miss -> teach -> resolve again -> hit)
is exercised end-to-end against a fake pywinauto tree, same "logically
reviewed, not live-tested" caveat as the rest of this suite until it's
run on a real Windows machine.

Uses its own small fakes rather than importing test_app_control.py's --
deliberately self-contained so this file doesn't depend on another test
module's internal helpers surviving unchanged.
"""

from unittest.mock import MagicMock

import app_control
from app_control import AppController, resolve_target
from target_memory import TargetMemory


class _FakeElemInfo:
    def __init__(self, control_type, name):
        self.control_type = control_type
        self.name = name


class _FakeRect:
    def __init__(self, l, t, r, b):
        self.left, self.top, self.right, self.bottom = l, t, r, b


class _FakeElem:
    def __init__(self, control_type, name, visible=True, enabled=True, rect=(0, 0, 100, 30)):
        self.element_info = _FakeElemInfo(control_type, name)
        self._visible = visible
        self._enabled = enabled
        self._rect = _FakeRect(*rect)

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def rectangle(self):
        return self._rect


class _FakeWin:
    def __init__(self, elems, title="TestApp"):
        self._elems = elems
        self._title = title

    def wait(self, *a, **k):
        return self

    def descendants(self):
        return self._elems

    def window_text(self):
        return self._title


class _FakePointHit:
    """What _Desktop(backend='uia').from_point(x, y) returns -- has
    name/control_type/class_name attributes, same shape capture_identity_
    at_point() reads via getattr()."""
    def __init__(self, name, control_type="Custom", class_name="X"):
        self.name = name
        self.control_type = control_type
        self.class_name = class_name


def _make_fake_desktop(win, point_hit=None):
    """point_hit: what from_point() should return for teach()'s capture
    step. win: what window(active_only=True) should return for both the
    fuzzy pass and _get_focused_window_title()."""
    class _FakeDesktop:
        def __init__(self, backend=None):
            pass

        def window(self, active_only=True):
            return win

        def from_point(self, x, y):
            return point_hit

    return _FakeDesktop


class _TeachFixture:
    """Same pattern as test_app_control.py's _AppControlPywinautoFixture,
    self-contained here. Also swaps in a fresh, tmp_path-backed
    TargetMemory as the module-level singleton so tests never touch the
    real learned_targets.json and never leak state between tests."""

    def setup_method(self, method=None):
        self._orig_available = app_control._PYWINAUTO_AVAILABLE
        self._orig_desktop = app_control._Desktop
        self._orig_comtypes = app_control._comtypes
        self._orig_target_memory = app_control._target_memory
        app_control._PYWINAUTO_AVAILABLE = True
        app_control._comtypes = MagicMock()

    def teardown_method(self, method=None):
        app_control._PYWINAUTO_AVAILABLE = self._orig_available
        app_control._Desktop = self._orig_desktop
        app_control._comtypes = self._orig_comtypes
        app_control._target_memory = self._orig_target_memory

    def _use_fresh_memory(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        app_control._target_memory = mem
        return mem


class TestTeach(_TeachFixture):
    def test_pywinauto_unavailable_returns_clear_message(self):
        app_control._PYWINAUTO_AVAILABLE = False
        ctrl = AppController()
        result = ctrl.teach("the export button", 10, 20)
        assert "Cursor control isn't available" in result

    def test_capture_returning_none_does_not_teach_anything(self, tmp_path):
        self._use_fresh_memory(tmp_path)
        app_control._Desktop = _make_fake_desktop(_FakeWin([]), point_hit=None)
        ctrl = AppController()
        result = ctrl.teach("the export button", 10, 20)
        assert "Couldn't identify" in result
        assert app_control._target_memory.get("TestApp", "the export button") is None

    def test_capture_with_no_name_does_not_teach_anything(self, tmp_path):
        self._use_fresh_memory(tmp_path)
        app_control._Desktop = _make_fake_desktop(_FakeWin([]), point_hit=_FakePointHit(name=""))
        ctrl = AppController()
        result = ctrl.teach("the export button", 10, 20)
        assert "Couldn't identify" in result

    def test_missing_window_title_does_not_teach_anything(self, tmp_path, monkeypatch):
        self._use_fresh_memory(tmp_path)
        app_control._Desktop = _make_fake_desktop(_FakeWin([]), point_hit=_FakePointHit(name="Export"))
        monkeypatch.setattr(app_control, "_get_focused_window_title", lambda: None)
        ctrl = AppController()
        result = ctrl.teach("the export button", 10, 20)
        assert "Couldn't tell which window" in result

    def test_successful_teach_writes_the_real_identity(self, tmp_path):
        mem = self._use_fresh_memory(tmp_path)
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([], title="Photoshop"),
            point_hit=_FakePointHit(name="Export", control_type="Button", class_name="Btn"),
        )
        ctrl = AppController()
        result = ctrl.teach("the export button", 40, 60)
        assert "Export" in result
        assert "the export button" in result
        assert "Photoshop" in result
        stored = mem.get("Photoshop", "the export button")
        assert stored == {"name": "Export", "control_type": "Button", "class_name": "Btn"}


class TestTeachFromNextClick(_TeachFixture):
    def test_pywinauto_unavailable_returns_clear_message(self):
        app_control._PYWINAUTO_AVAILABLE = False
        ctrl = AppController()
        result = ctrl.teach_from_next_click("the export button")
        assert "Cursor control isn't available" in result

    def test_click_timeout_does_not_teach_anything(self, tmp_path, monkeypatch):
        self._use_fresh_memory(tmp_path)
        monkeypatch.setattr(app_control, "wait_for_single_click", lambda timeout: None)
        ctrl = AppController()
        result = ctrl.teach_from_next_click("the export button", timeout_seconds=5.0)
        assert "Didn't see a click" in result
        assert app_control._target_memory.get("TestApp", "the export button") is None

    def test_click_captured_delegates_to_teach_at_that_point(self, tmp_path, monkeypatch):
        mem = self._use_fresh_memory(tmp_path)
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([], title="Photoshop"),
            point_hit=_FakePointHit(name="Export", control_type="Button", class_name="Btn"),
        )
        monkeypatch.setattr(app_control, "wait_for_single_click", lambda timeout: (40, 60))
        ctrl = AppController()
        result = ctrl.teach_from_next_click("the export button")
        assert "Export" in result
        assert mem.get("Photoshop", "the export button") is not None


class TestResolveTargetMemoryRoundTrip(_TeachFixture):
    """The actual thing a user cares about: does teaching a target once
    make the NEXT click succeed? Uses a taught name ("IconGlyph9F") that
    deliberately shares no words with its description ("the funky little
    icon in the corner") -- confirmed below threshold via _score() before
    writing these -- so the ordinary fuzzy pass genuinely can't succeed on
    its own; the only way resolve_target() can return a match is via
    memory recall. (An earlier draft of this file used "Export" / "the
    export button", which _score()'s substring-match boost clears on its
    own regardless of memory -- caught by test_a_real_fuzzy_match_wins_
    without_ever_consulting_memory below actually needing that boost, so
    it was silently not testing what it claimed to. Worth keeping in mind
    if these tests are extended later: a taught pair that ALSO fuzzy-
    matches proves nothing about the memory path specifically.)"""

    _DESC = "the funky little icon in the corner"
    _NAME = "IconGlyph9F"
    _IDENTITY = {"name": _NAME, "control_type": "Button", "class_name": "Btn"}

    def test_taught_target_is_found_on_a_later_resolve(self, tmp_path):
        mem = self._use_fresh_memory(tmp_path)
        mem.remember("Photoshop", self._DESC, self._IDENTITY)

        # A fresh candidate list -- as if the app was re-scanned this
        # turn -- containing an element matching the TAUGHT identity.
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([_FakeElem("Button", self._NAME, rect=(10, 10, 90, 40))], title="Photoshop")
        )
        match, reason = resolve_target(self._DESC)
        assert reason is None
        assert match is not None
        x, y, name = match
        assert name == self._NAME
        assert (x, y) == (50, 25)  # center of the taught element's CURRENT rect

    def test_taught_in_a_different_window_does_not_leak_across(self, tmp_path):
        mem = self._use_fresh_memory(tmp_path)
        mem.remember("Photoshop", self._DESC, self._IDENTITY)

        # Same description, same identity present, but the CURRENTLY
        # focused window has a different title -- must not resolve via a
        # different app's taught mapping.
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([_FakeElem("Button", self._NAME, rect=(10, 10, 90, 40))], title="GIMP")
        )
        match, reason = resolve_target(self._DESC)
        assert match is None
        assert reason is None  # clean miss, not an error

    def test_taught_element_no_longer_present_still_misses_cleanly(self, tmp_path):
        # UI changed since teaching -- the taught identity simply isn't in
        # the current tree. Must NOT fall back to fuzzy-guessing the stale
        # name; a clean miss is the correct, safe outcome.
        mem = self._use_fresh_memory(tmp_path)
        mem.remember("Photoshop", self._DESC, self._IDENTITY)
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([_FakeElem("Button", "SomethingElse", rect=(10, 10, 90, 40))], title="Photoshop")
        )
        match, reason = resolve_target(self._DESC)
        assert match is None
        assert reason is None

    def test_invisible_taught_element_still_misses_cleanly(self, tmp_path):
        mem = self._use_fresh_memory(tmp_path)
        mem.remember("Photoshop", self._DESC, self._IDENTITY)
        app_control._Desktop = _make_fake_desktop(
            _FakeWin([_FakeElem("Button", self._NAME, visible=False, rect=(10, 10, 90, 40))], title="Photoshop")
        )
        match, reason = resolve_target(self._DESC)
        assert match is None
        assert reason is None

    def test_a_real_fuzzy_match_wins_without_ever_consulting_memory(self, tmp_path, monkeypatch):
        # If the ordinary fuzzy pass already succeeds (a real, literally-
        # named "Export" button against "the export button"), memory
        # should never even be consulted -- confirmed here by making a
        # memory lookup raise, which would fail this test if it were ever
        # called.
        self._use_fresh_memory(tmp_path)

        def _boom(*a, **k):
            raise AssertionError("memory should not be consulted on a real fuzzy hit")
        monkeypatch.setattr(app_control, "_try_resolve_from_memory", _boom)

        app_control._Desktop = _make_fake_desktop(
            _FakeWin([_FakeElem("Button", "Export", rect=(10, 10, 90, 40))], title="Photoshop")
        )
        match, reason = resolve_target("the export button")
        assert reason is None
        assert match is not None
        assert match[2] == "Export"
