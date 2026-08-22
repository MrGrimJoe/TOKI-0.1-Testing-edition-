"""
test_app_control.py -- pins the LAUNCH_APP escaping fix from this session,
PLUS (this pass) the actual click/type UI-Automation mechanism -- confirmed
live this had ZERO test coverage anywhere in the suite despite being wired
end-to-end in orchestrator.py/extractor.py. Everything below TestResolveTarget
onward is new: a fake pywinauto Desktop/element tree (see FakeElem/FakeWin/
FakeDesktop) exercises resolve_target()/click()/type_text() the same way
test_app_control.py already mocks subprocess.Popen for LAUNCH_APP -- no real
Windows/pywinauto needed, but the actual scoring/dispatch code paths run for
real, not just asserted-by-inspection.

Probed by hand against this same harness before writing these as permanent
tests: resolve_target()'s clickable-type filtering, visibility/enabled
filtering, and fail-safe-on-no-match behavior all held up; click()'s
single/double/right dispatch and type_text()'s character-escaping produced
exactly the expected pywinauto calls; the "pywinauto unavailable" and "COM
exception during window walk" failure paths both surfaced correctly instead
of silently swallowing the error. Nothing found broken -- this pass is about
closing the coverage gap, not a bug fix.
"""

import os
from unittest.mock import patch, MagicMock

from app_control import AppController, _escape_ps_slot, _score_app_match, _APP_MATCH_THRESHOLD
import app_control


class TestEscapePsSlot:
    def test_doubles_single_quotes(self):
        assert _escape_ps_slot("Assassin's Creed") == "Assassin''s Creed"

    def test_no_quotes_unaffected(self):
        assert _escape_ps_slot("Chrome") == "Chrome"

    def test_injection_payload_neutralized(self):
        payload = "pwned' ; Remove-Item -Recurse -Force D:\\ ; Start-Process 'x"
        escaped = _escape_ps_slot(payload)
        # The actual PowerShell safety property: every single quote in the
        # payload must come out DOUBLED (PowerShell's own escape convention
        # for a literal ' inside '...'), so the whole thing parses as ONE
        # literal string instead of terminating early and letting the rest
        # run as a separate statement. Doubled count == 2x original count.
        assert escaped.count("'") == 2 * payload.count("'")
        # No single (unpaired) quote should exist anywhere in the escaped
        # string -- i.e. splitting on "''" should leave zero lone quotes.
        assert escaped.replace("''", "").count("'") == 0


class TestLaunchAppUsesEscaping:
    # launch_app() now tries a real Start Menu match first (via
    # _find_installed_app, covering both traditional and UWP/Store apps)
    # and only falls back to a bare `Start-Process '<name>'` when nothing
    # confidently matches -- see launch_app()'s own docstring. Both of
    # these tests therefore pin _find_installed_app explicitly rather
    # than relying on whatever's actually installed on the machine
    # running the suite: without that, "chrome" resolves differently on
    # a real Windows box (real Start Menu match -> shell:AppsFolder) than
    # it does in a bare/sandboxed CI environment (no match -> plain
    # Start-Process), which is exactly what made
    # test_plain_app_name_unaffected flaky/false-failing on a real
    # machine that actually has Chrome installed.

    def test_apostrophe_in_app_name_does_not_break_the_command(self):
        controller = AppController()
        with patch.object(AppController, "_find_installed_app", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            controller.launch_app("Assassin's Creed")

        assert mock_popen.called
        args = mock_popen.call_args[0][0]  # the argv list passed to Popen
        command_str = args[-1]  # the -Command string
        assert command_str == "Start-Process 'Assassin''s Creed'", (
            f"launch_app built an unescaped/broken command: {command_str!r}"
        )

    def test_plain_app_name_unaffected(self):
        """No confident Start Menu match -> old bare Start-Process
        behavior, unchanged."""
        controller = AppController()
        with patch.object(AppController, "_find_installed_app", return_value=None), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            controller.launch_app("chrome")

        command_str = mock_popen.call_args[0][0][-1]
        assert command_str == "Start-Process 'chrome'"

    def test_matched_installed_app_launches_via_apps_folder(self):
        """A confident Start Menu match (traditional or UWP/Store) is
        launched by AppID through shell:AppsFolder, not a bare app name
        -- this is the behavior that superseded the old always-bare
        Start-Process call, and previously had no direct test coverage
        at all."""
        controller = AppController()
        match = {"Name": "Google Chrome", "AppID": "Chrome"}
        with patch.object(AppController, "_find_installed_app", return_value=match), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            result = controller.launch_app("chrome")

        command_str = mock_popen.call_args[0][0][-1]
        assert command_str == "Start-Process 'shell:AppsFolder\\Chrome'"
        assert result == "Launching Google Chrome."


# ─── BETA 0.3.9: leading-initials-plus-trailing-words abbreviation tier ────
#
# Found live against REAL Get-StartApps output on the reporter's machine:
# "VsCode" scored only 0.38 against "Visual Studio Code", nowhere near
# _APP_MATCH_THRESHOLD (0.72) -- the whole cascade fell through to a bad
# file-path guess instead of launching the app. Root cause: "vscode" isn't
# a contiguous substring of "visualstudiocode" (tier 2's workhorse check),
# because the "vs" comes from two separate words' initials ("Visual",
# "Studio"), not a run of letters anywhere in the name itself.

class TestLeadingInitialsAbbreviationTier:
    def test_vscode_matches_visual_studio_code(self):
        assert _score_app_match("VsCode", "Visual Studio Code") >= _APP_MATCH_THRESHOLD

    def test_vs2022_matches_visual_studio_2022(self):
        assert _score_app_match("vs2022", "Visual Studio 2022") >= _APP_MATCH_THRESHOLD

    def test_does_not_reopen_the_discord_collision(self):
        # The exact regression this tier must never reintroduce: verified
        # directly that "vscode" does not also start matching "Discord"
        # now that a new scoring tier exists alongside the substring one.
        assert _score_app_match("vscode", "Discord") < _APP_MATCH_THRESHOLD

    def test_does_not_match_unrelated_short_queries(self):
        # A short query shouldn't spuriously satisfy the initials pattern
        # against an unrelated multi-word name.
        assert _score_app_match("xyz", "Visual Studio Code") < _APP_MATCH_THRESHOLD

    def test_known_gap_ms_word_style_abbreviations_not_covered(self):
        # Documented limitation, not silently claimed as fixed: this tier
        # only covers SINGLE-LETTER initials, not multi-letter prefix
        # abbreviations like "MS" for "Microsoft". Pinned so a future
        # change to this tier doesn't accidentally start relying on
        # "msword" working without deliberately extending the pattern
        # and re-testing it against collision risks first.
        assert _score_app_match("msword", "Microsoft Word") < _APP_MATCH_THRESHOLD


# ─── BETA 0.3.28: a failed Get-StartApps call must never be cached ────────
#
# _app_list_cache used to be set to [] on ANY failure (subprocess error,
# timeout, malformed JSON) and `if _app_list_cache is not None: return`
# treated that identically to a genuine successful (empty) result -- so a
# single hiccup (common right after boot, or PowerShell momentarily
# locked) permanently degraded every app-launch/app-control action for the
# rest of the session, with no TTL and no retry. Fixed: only a REAL
# success is ever written to _app_list_cache; a failure just returns []
# for that one call and is retried (for real) after
# _FAILURE_RETRY_SECONDS, not cached forever.

class TestAppCacheDoesNotPermanentlyCacheFailures:
    def setup_method(self):
        # Class-level cache is shared across ALL AppController instances
        # -- reset it before and after every test in this class so these
        # tests can't pollute each other or any other test file that
        # happens to run in the same process.
        AppController._app_list_cache = None
        AppController._last_fetch_failure_time = None

    def teardown_method(self):
        AppController._app_list_cache = None
        AppController._last_fetch_failure_time = None

    def test_failure_is_not_cached_and_next_call_retries(self):
        controller = AppController()
        with patch("subprocess.run", side_effect=OSError("powershell hiccup")):
            first = controller._get_installed_apps()
        assert first == []
        # PRE-FIX: this would still be [] because the failure got cached
        # forever, even after the underlying problem is gone. Force past
        # the retry backoff and confirm a real retry happens.
        AppController._last_fetch_failure_time = 0.0  # "long ago"
        mock_result = MagicMock()
        mock_result.stdout = '{"Name": "Notepad", "AppID": "notepad.exe"}'
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            second = controller._get_installed_apps()
        assert mock_run.called, "a fresh call after the retry window must actually retry, not stay cached"
        assert second == [{"Name": "Notepad", "AppID": "notepad.exe"}]

    def test_repeated_calls_during_failure_window_do_not_resubprocess_every_time(self):
        # Not hammering the subprocess on every single call during a
        # known-bad window is a reasonable efficiency property, not just
        # "retries forever" -- confirm the backoff actually backs off.
        controller = AppController()
        with patch("subprocess.run", side_effect=OSError("boom")) as mock_run:
            controller._get_installed_apps()
            controller._get_installed_apps()
            controller._get_installed_apps()
        assert mock_run.call_count == 1, (
            "repeated calls within the failure-retry window should not "
            "all pay the subprocess cost again"
        )

    def test_successful_result_is_still_cached_normally(self):
        # Regression guard: fixing the failure-caching bug must not
        # accidentally remove caching for the successful case, which is
        # the whole point of this cache existing.
        controller = AppController()
        mock_result = MagicMock()
        mock_result.stdout = '{"Name": "Notepad", "AppID": "notepad.exe"}'
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            controller._get_installed_apps()
            controller._get_installed_apps()
        assert mock_run.call_count == 1, "a successful result must still be cached, not re-fetched every call"

    def test_invalidate_app_cache_clears_failure_state_too(self):
        controller = AppController()
        with patch("subprocess.run", side_effect=OSError("boom")):
            controller._get_installed_apps()
        assert AppController._last_fetch_failure_time is not None
        controller.invalidate_app_cache()
        assert AppController._app_list_cache is None
        assert AppController._last_fetch_failure_time is None


# ─── new this pass: the actual click/type UI-Automation mechanism ──────────
#
# Fakes pywinauto's Desktop + element tree so resolve_target()/click()/
# type_text() run their REAL code paths (scoring, filtering, dispatch,
# escaping) against a controlled fake tree -- no real Windows/pywinauto
# install needed, but nothing here is asserted by inspection alone.

class _FakeElemInfo:
    def __init__(self, control_type, name):
        self.control_type = control_type
        self.name = name


class _FakeRect:
    def __init__(self, l, t, r, b):
        self.left, self.top, self.right, self.bottom = l, t, r, b


class _FakeElem:
    def __init__(self, control_type, name, visible=True, enabled=True, rect=(0, 0, 100, 30), focused=False):
        self.element_info = _FakeElemInfo(control_type, name)
        self._visible = visible
        self._enabled = enabled
        self._rect = _FakeRect(*rect)
        self._focused = focused

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def rectangle(self):
        return self._rect

    def has_keyboard_focus(self):
        return self._focused


class _FakeWin:
    def __init__(self, elems, pid=None, label=None):
        self._elems = elems
        self._pid = pid
        self._label = label  # test-only marker so tests can tell which fake window came back

    def wait(self, *a, **k):
        return self

    def descendants(self):
        return self._elems

    def process_id(self):
        return self._pid


def _make_fake_desktop(elems, pid=None):
    class _FakeDesktop:
        def __init__(self, backend=None):
            pass

        def window(self, active_only=True):
            return _FakeWin(elems, pid=pid)

    return _FakeDesktop


class _AppControlPywinautoFixture:
    """Shared setup/teardown: patches app_control's module-level pywinauto
    hooks so _load_pywinauto() reports available without touching the real
    package, and restores the untouched state after every test so this
    doesn't leak into other test files sharing the same process."""

    def setup_method(self):
        self._orig_available = app_control._PYWINAUTO_AVAILABLE
        self._orig_desktop = app_control._Desktop
        self._orig_comtypes = app_control._comtypes
        app_control._PYWINAUTO_AVAILABLE = True
        app_control._comtypes = MagicMock()

    def teardown_method(self):
        app_control._PYWINAUTO_AVAILABLE = self._orig_available
        app_control._Desktop = self._orig_desktop
        app_control._comtypes = self._orig_comtypes


class TestResolveTarget(_AppControlPywinautoFixture):
    def test_matches_best_clickable_element(self):
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Button", "Save"),
            _FakeElem("Button", "Cancel"),
        ])
        match, reason = app_control.resolve_target("the save button")
        assert reason is None
        assert match is not None
        x, y, name = match
        assert name == "Save"
        assert (x, y) == (50, 15)  # center of rect (0,0,100,30)

    def test_skips_non_clickable_control_types(self):
        # A Pane named "Save" should never win over a real Button also
        # named "Save" -- _CLICKABLE_TYPES exists specifically to filter
        # out generic containers that aren't real click targets.
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Pane", "Save"),
            _FakeElem("Button", "Cancel"),
        ])
        match, reason = app_control.resolve_target("the save button")
        # "Save" the Pane is filtered out entirely; nothing left clears
        # _MATCH_THRESHOLD against "Cancel" -- fail-safe, not a bad click.
        assert match is None
        assert reason is None

    def test_skips_invisible_or_disabled_elements(self):
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Button", "Save", visible=False),
            _FakeElem("Button", "Cancel", enabled=False),
        ])
        match, reason = app_control.resolve_target("the save button")
        assert match is None
        assert reason is None

    def test_no_confident_match_fails_safe_not_an_error(self):
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "OK")])
        match, reason = app_control.resolve_target("the save button")
        assert match is None
        assert reason is None  # clean miss, distinct from a real error below

    def test_real_exception_surfaces_as_a_reason_not_a_silent_none(self):
        class _BrokenDesktop:
            def __init__(self, backend=None):
                pass

            def window(self, active_only=True):
                raise OSError("COM error 0x80010106")

        app_control._Desktop = _BrokenDesktop
        match, reason = app_control.resolve_target("the save button")
        assert match is None
        assert reason is not None and "0x80010106" in reason

    def test_pywinauto_unavailable_reports_reason_not_silent_none(self):
        app_control._PYWINAUTO_AVAILABLE = False
        match, reason = app_control.resolve_target("the save button")
        assert match is None
        assert reason is not None


class TestGetFocusedWindowForegroundTrackerFallback(_AppControlPywinautoFixture):
    """_get_focused_window()'s foreground_tracker fallback -- see that
    function's own docstring and foreground_tracker.py's module docstring
    for the bug this fixes (every app_control.py call resolving against
    TOKI's OWN window instead of the real target, because OS focus has
    already moved to TOKI by the time this code runs)."""

    def setup_method(self):
        super().setup_method()
        import foreground_tracker
        self._orig_get_last = foreground_tracker.get_last_foreground_window

    def teardown_method(self):
        super().teardown_method()
        import foreground_tracker
        foreground_tracker.get_last_foreground_window = self._orig_get_last

    def _make_fake_desktop_with_handle_support(self, active_pid, active_elems, handle_wins):
        """handle_wins: dict mapping hwnd -> _FakeWin, for the
        desktop.window(handle=...) call this fallback path makes."""
        class _FakeDesktop:
            def __init__(self, backend=None):
                pass

            def window(self, active_only=None, handle=None):
                if handle is not None:
                    win = handle_wins.get(handle)
                    if win is None:
                        raise OSError(f"no such window handle: {handle}")
                    return win
                return _FakeWin(active_elems, pid=active_pid)

        return _FakeDesktop

    def test_active_window_belonging_to_another_process_is_used_directly(self):
        # The common, unchanged case: OS focus genuinely is on some other
        # app (not TOKI) -- foreground_tracker must never be consulted at
        # all here, same behavior as before this fix existed.
        import foreground_tracker
        foreground_tracker.get_last_foreground_window = MagicMock(
            side_effect=AssertionError("must not be called when active window isn't TOKI's own")
        )
        app_control._Desktop = self._make_fake_desktop_with_handle_support(
            active_pid=os.getpid() + 1,  # some other process
            active_elems=[_FakeElem("Button", "Save")],
            handle_wins={},
        )
        win = app_control._get_focused_window()
        assert win.descendants()[0].element_info.name == "Save"

    def test_active_window_is_tokis_own_falls_back_to_tracked_window(self):
        import foreground_tracker
        real_win = _FakeWin([_FakeElem("Edit", "Address bar")], pid=12345, label="browser")
        foreground_tracker.get_last_foreground_window = MagicMock(return_value=999)
        app_control._Desktop = self._make_fake_desktop_with_handle_support(
            active_pid=os.getpid(),  # TOKI's own process
            active_elems=[_FakeElem("Button", "TOKI's own UI")],
            handle_wins={999: real_win},
        )
        win = app_control._get_focused_window()
        assert win is real_win
        assert win.descendants()[0].element_info.name == "Address bar"

    def test_no_tracked_fallback_available_returns_tokis_own_window(self):
        # foreground_tracker never observed anything non-TOKI yet this
        # session (e.g. very first command) -- must fail OPEN to TOKI's
        # own window rather than raising, same as this function's
        # behavior before foreground_tracker existed. Callers already
        # treat "resolved to a window with no matching element" as a
        # clean miss, not a crash.
        import foreground_tracker
        foreground_tracker.get_last_foreground_window = MagicMock(return_value=None)
        app_control._Desktop = self._make_fake_desktop_with_handle_support(
            active_pid=os.getpid(),
            active_elems=[_FakeElem("Button", "TOKI's own UI")],
            handle_wins={},
        )
        win = app_control._get_focused_window()
        assert win.descendants()[0].element_info.name == "TOKI's own UI"

    def test_tracked_handle_closed_between_tracker_check_and_use_fails_open(self):
        # foreground_tracker.get_last_foreground_window() already
        # re-validates with IsWindow() before returning a handle, but a
        # window can still close in the gap between that check and this
        # function actually resolving it -- desktop.window(handle=...)
        # raising must fail open to TOKI's own window, not propagate.
        import foreground_tracker
        foreground_tracker.get_last_foreground_window = MagicMock(return_value=999)
        app_control._Desktop = self._make_fake_desktop_with_handle_support(
            active_pid=os.getpid(),
            active_elems=[_FakeElem("Button", "TOKI's own UI")],
            handle_wins={},  # 999 not present -> window(handle=999) raises
        )
        win = app_control._get_focused_window()
        assert win.descendants()[0].element_info.name == "TOKI's own UI"

    def test_process_id_lookup_failure_fails_open_to_active_window(self):
        # If win.process_id() itself blows up (shouldn't normally, but
        # this must never be what turns a click into a crash), treat it
        # like "can't tell whose window it is" and use the live active
        # window unchanged, exactly like before this fix.
        import foreground_tracker
        foreground_tracker.get_last_foreground_window = MagicMock(
            side_effect=AssertionError("must not be called if process_id() itself failed")
        )

        class _BrokenPidWin(_FakeWin):
            def process_id(self):
                raise OSError("COM error reading process id")

        class _FakeDesktop:
            def __init__(self, backend=None):
                pass

            def window(self, active_only=None, handle=None):
                return _BrokenPidWin([_FakeElem("Button", "Whatever")])

        app_control._Desktop = _FakeDesktop
        win = app_control._get_focused_window()
        assert win.descendants()[0].element_info.name == "Whatever"


class TestClickAndTypeDispatch(_AppControlPywinautoFixture):
    def _install_fake_pywinauto_mouse_keyboard(self):
        import sys
        import types
        calls = []
        fake_mouse = types.ModuleType("pywinauto.mouse")
        fake_mouse.click = lambda button="left", coords=(0, 0): calls.append(("click", button, coords))
        fake_keyboard = types.ModuleType("pywinauto.keyboard")
        fake_keyboard.send_keys = lambda s: calls.append(("send_keys", s))
        sys.modules["pywinauto.mouse"] = fake_mouse
        sys.modules["pywinauto.keyboard"] = fake_keyboard
        return calls

    def test_single_click_issues_exactly_one_left_click(self):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save")])
        result = AppController().click("the save button")
        assert "Save" in result
        assert calls == [("click", "left", (50, 15))]

    def test_double_click_issues_two_left_clicks(self):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save")])
        AppController().click("the save button", double=True)
        assert calls == [("click", "left", (50, 15)), ("click", "left", (50, 15))]

    def test_right_click_issues_one_right_click(self):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save")])
        AppController().click("the save button", right=True)
        assert calls == [("click", "right", (50, 15))]

    def test_click_with_no_match_does_not_touch_the_mouse(self):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "OK")])
        result = AppController().click("the save button")
        assert "Couldn't confidently find" in result
        assert calls == []  # fail-safe: no click call made at all

    def test_type_text_focuses_then_sends_escaped_keys(self):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])
        result = AppController().type_text("search box", "hello {world} & +test")
        assert "Search box" in result
        assert calls[0] == ("click", "left", (50, 15))  # focuses the field first
        assert calls[1] == ("send_keys", "hello {{}world{}} & {+}test")

    def test_type_text_special_chars_never_reach_send_keys_unescaped(self):
        # The specific injection-adjacent risk: {}/+/^/%/~/()  are all
        # pywinauto keyboard-shortcut/modifier syntax -- confirm every one
        # comes out escaped, not just the ones exercised above.
        calls = self._install_fake_pywinauto_mouse_keyboard()
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "field")])
        AppController().type_text("field", "{}+^%~()")
        sent = calls[1][1]
        assert sent == "{{}{}}{+}{^}{%}{~}{(}{)}"

    def test_pywinauto_unavailable_reports_clearly_and_does_not_crash(self):
        app_control._PYWINAUTO_AVAILABLE = False
        result = AppController().click("anything")
        assert "isn't available" in result
        result2 = AppController().type_text("anything", "hi")
        assert "isn't available" in result2


class TestGetFocusedTextElement(_AppControlPywinautoFixture):
    """
    _get_focused_text_element() -- the "does the screen already read as
    just a text editor" check start_dictation() uses to decide whether to
    ask where to type. Same fake Desktop/window harness as
    TestResolveTarget above; has_keyboard_focus() is the one new fake
    method this needed (see _FakeElem's focused= param).
    """

    def test_returns_center_and_name_of_the_focused_edit_control(self):
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Button", "Save"),
            _FakeElem("Edit", "Search box", focused=True, rect=(0, 0, 200, 40)),
        ])
        result = app_control._get_focused_text_element()
        assert result == (100, 20, "Search box")

    def test_returns_none_when_focused_element_is_not_a_text_control(self):
        # Something IS focused, it's just not a place text can go --
        # start_dictation() must ask here, not guess.
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Button", "Save", focused=True),
        ])
        assert app_control._get_focused_text_element() is None

    def test_returns_none_when_nothing_has_focus(self):
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Button", "Save"),
            _FakeElem("Edit", "Search box"),
        ])
        assert app_control._get_focused_text_element() is None

    def test_returns_none_when_pywinauto_unavailable(self):
        app_control._PYWINAUTO_AVAILABLE = False
        assert app_control._get_focused_text_element() is None

    def test_returns_none_on_com_exception_not_a_crash(self):
        class _BrokenDesktop:
            def __init__(self, backend=None):
                pass

            def window(self, active_only=True):
                raise OSError("COM error 0x80010106")

        app_control._Desktop = _BrokenDesktop
        assert app_control._get_focused_text_element() is None


class TestDictation(_AppControlPywinautoFixture):
    """
    start_dictation()/stop_dictation() -- target resolution + the actual
    DictationPipeline lifecycle. voice_pipeline.DictationPipeline itself
    is replaced with a fake (no real QThread/sounddevice/whisper spun up
    in tests) so these tests are about app_control.py's own dispatch
    logic, not voice_pipeline.py's capture loop (that's exercised
    separately in test_voice_pipeline.py).
    """

    def _install_fake_pywinauto_mouse_keyboard(self):
        import sys
        import types
        calls = []
        fake_mouse = types.ModuleType("pywinauto.mouse")
        fake_mouse.click = lambda button="left", coords=(0, 0): calls.append(("click", button, coords))
        fake_keyboard = types.ModuleType("pywinauto.keyboard")
        fake_keyboard.send_keys = lambda s: calls.append(("send_keys", s))
        sys.modules["pywinauto.mouse"] = fake_mouse
        sys.modules["pywinauto.keyboard"] = fake_keyboard
        return calls

    def _install_fake_dictation_pipeline(self, monkeypatch):
        import voice_pipeline

        class _FakePipeline:
            instances = []

            def __init__(self):
                self.started = False
                self.utterance_handler = None
                self.stopped_handler = None
                _FakePipeline.instances.append(self)

            class _Signal:
                def __init__(self, owner, attr):
                    self._owner, self._attr = owner, attr

                def connect(self, fn):
                    setattr(self._owner, self._attr, fn)

            @property
            def utterance_transcribed(self):
                return self._Signal(self, "utterance_handler")

            @property
            def unavailable(self):
                return self._Signal(self, "_unused_unavailable_handler")

            @property
            def dictation_stopped(self):
                return self._Signal(self, "stopped_handler")

            def start(self):
                self.started = True

            def stop(self):
                if self.stopped_handler:
                    self.stopped_handler()

        monkeypatch.setattr(voice_pipeline, "DictationPipeline", _FakePipeline)
        return _FakePipeline

    def test_start_with_explicit_target_resolves_focuses_and_starts_pipeline(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])

        ctrl = AppController()
        result = ctrl.start_dictation("search box")

        assert "Search box" in result
        assert calls == [("click", "left", (50, 15))]
        assert len(fake_cls.instances) == 1
        assert fake_cls.instances[0].started is True
        assert ctrl._active_dictation is fake_cls.instances[0]

    def test_start_with_no_target_uses_already_focused_text_box_without_asking(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([
            _FakeElem("Edit", "Notes", focused=True, rect=(0, 0, 200, 40)),
        ])

        ctrl = AppController()
        result = ctrl.start_dictation("")

        assert "Notes" in result
        assert calls == [("click", "left", (100, 20))]
        assert fake_cls.instances[0].started is True

    def test_start_with_no_target_and_no_focused_text_box_falls_back_to_click(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save", focused=True)])
        monkeypatch.setattr(app_control, "wait_for_single_click", lambda timeout: (30, 40))
        monkeypatch.setattr(app_control, "capture_identity_at_point", lambda x, y: {"name": "Comment box"})

        ctrl = AppController()
        result = ctrl.start_dictation("")

        assert "Comment box" in result
        assert calls == [("click", "left", (30, 40))]
        assert fake_cls.instances[0].started is True

    def test_start_gives_up_cleanly_if_no_click_seen_in_time(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save", focused=True)])
        monkeypatch.setattr(app_control, "wait_for_single_click", lambda timeout: None)

        ctrl = AppController()
        result = ctrl.start_dictation("")

        assert "Didn't see a click" in result
        assert calls == []
        assert fake_cls.instances == []
        assert ctrl._active_dictation is None

    def test_start_with_unresolvable_explicit_target_does_not_start_a_pipeline(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "OK")])

        ctrl = AppController()
        result = ctrl.start_dictation("the search box")

        assert "Couldn't confidently find" in result
        assert calls == []
        assert fake_cls.instances == []

    def test_utterance_gets_typed_via_send_keys_with_trailing_space(self, monkeypatch):
        calls = self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])

        ctrl = AppController()
        ctrl.start_dictation("search box")
        pipeline = fake_cls.instances[0]
        pipeline.utterance_handler("hello world")

        assert calls[-1] == ("send_keys", "hello world ")

    def test_second_start_while_already_listening_is_refused(self, monkeypatch):
        self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])

        ctrl = AppController()
        ctrl.start_dictation("search box")
        result = ctrl.start_dictation("search box")

        assert "Already listening" in result
        assert len(fake_cls.instances) == 1  # second call never created another pipeline

    def test_stop_with_no_active_session_says_so(self):
        ctrl = AppController()
        ctrl._active_dictation = None
        assert "Nothing's being dictated" in ctrl.stop_dictation()

    def test_stop_calls_pipeline_stop_and_clears_active_session(self, monkeypatch):
        self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])

        ctrl = AppController()
        ctrl.start_dictation("search box")
        result = ctrl.stop_dictation()

        assert "Stopped listening" in result
        assert ctrl._active_dictation is None  # cleared synchronously by stop_dictation() itself

    def test_active_session_cleared_before_the_stopped_signal_fires(self, monkeypatch):
        # Pins the actual race this was written to avoid: main_widget.py
        # checks _active_dictation right after stop_dictation() returns to
        # decide whether to hide the dictation panel -- that check must
        # never see a stale non-None value while waiting on the pipeline's
        # own (slower, async) dictation_stopped signal.
        self._install_fake_pywinauto_mouse_keyboard()
        fake_cls = self._install_fake_dictation_pipeline(monkeypatch)
        app_control._Desktop = _make_fake_desktop([_FakeElem("Edit", "Search box")])

        ctrl = AppController()
        ctrl.start_dictation("search box")
        pipeline = fake_cls.instances[0]
        pipeline.stopped_handler = None  # simulate the signal never firing (yet)

        ctrl.stop_dictation()
        assert ctrl._active_dictation is None  # already cleared, independent of the signal

    def test_pywinauto_unavailable_reports_clearly(self):
        app_control._PYWINAUTO_AVAILABLE = False
        result = AppController().start_dictation("")
        assert "isn't available" in result


class TestOcrFindTextOnScreen:
    """
    _ocr_find_text_on_screen() -- the testable half (scoring + coordinate
    math). _ocr_lines_from_bitmap() itself (the real WinRT capture/
    recognize call) is mocked out entirely here, same reasoning as
    resolve_target()'s own tests mocking _Desktop rather than exercising
    real pywinauto -- see that function's docstring for why it can't be
    verified against real Windows from this sandbox.
    """

    class _FakeWindowForRect:
        def __init__(self, rect):
            self._rect = _FakeRect(*rect)

        def rectangle(self):
            return self._rect

    def test_picks_the_best_scoring_line_and_offsets_to_screen_coords(self, monkeypatch):
        monkeypatch.setattr(
            app_control, "_ocr_lines_from_bitmap",
            lambda bbox: [("Cancel", (0, 0, 60, 20)), ("Save changes", (0, 30, 100, 50))],
        )
        win = self._FakeWindowForRect((500, 300, 900, 700))  # screen offset (500, 300)
        result = app_control._ocr_find_text_on_screen("save changes", win)
        assert result is not None
        x, y, text = result
        assert text == "Save changes"
        assert (x, y) == (500 + 50, 300 + 40)  # bitmap-local center + window offset

    def test_no_line_clears_match_threshold_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            app_control, "_ocr_lines_from_bitmap",
            lambda bbox: [("Unrelated text", (0, 0, 60, 20))],
        )
        win = self._FakeWindowForRect((0, 0, 100, 100))
        assert app_control._ocr_find_text_on_screen("save changes", win) is None

    def test_empty_ocr_result_returns_none(self, monkeypatch):
        monkeypatch.setattr(app_control, "_ocr_lines_from_bitmap", lambda bbox: [])
        win = self._FakeWindowForRect((0, 0, 100, 100))
        assert app_control._ocr_find_text_on_screen("anything", win) is None

    def test_window_rectangle_failure_returns_none_not_a_crash(self):
        class _BrokenWindow:
            def rectangle(self):
                raise OSError("no rect")

        assert app_control._ocr_find_text_on_screen("anything", _BrokenWindow()) is None

    def test_winsdk_unavailable_gives_empty_lines_not_an_exception(self):
        # _load_winsdk_ocr() returning None (winsdk not installed) is the
        # expected, common case on any machine without it -- confirms the
        # real (unmocked) _ocr_lines_from_bitmap degrades cleanly.
        assert app_control._ocr_lines_from_bitmap((0, 0, 10, 10)) == []


class TestResolveTargetOcrFallback(_AppControlPywinautoFixture):
    """
    resolve_target()'s new OCR fallback -- checked only after BOTH the
    fuzzy UIA pass and the memory-recall pass have already missed, and
    must never fire (or change the result) when either of those already
    succeeded.
    """

    def test_ocr_recovers_a_clean_uia_miss(self, monkeypatch):
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "OK")])
        monkeypatch.setattr(app_control, "_ocr_find_text_on_screen", lambda desc, win: (77, 88, "Save changes"))
        match, reason = app_control.resolve_target("save changes")
        assert reason is None
        assert match == (77, 88, "Save changes")

    def test_ocr_also_missing_still_fails_safe(self, monkeypatch):
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "OK")])
        monkeypatch.setattr(app_control, "_ocr_find_text_on_screen", lambda desc, win: None)
        match, reason = app_control.resolve_target("save changes")
        assert match is None
        assert reason is None

    def test_ocr_never_consulted_when_uia_already_matched(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            app_control, "_ocr_find_text_on_screen",
            lambda desc, win: calls.append(1) or (0, 0, "should not be used"),
        )
        app_control._Desktop = _make_fake_desktop([_FakeElem("Button", "Save")])
        match, reason = app_control.resolve_target("the save button")
        assert match is not None
        assert match[2] == "Save"  # real UIA match won, not the OCR fake
        assert calls == []  # OCR never even called
