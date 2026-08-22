"""
test_foreground_tracker.py -- unit tests for the background poller that
fixes app_control.py's _get_focused_window() grabbing TOKI's own window
instead of the real target (see foreground_tracker.py's module docstring
for the full bug writeup).

NOT VERIFIED AGAINST REAL WINDOWS -- ctypes.windll.user32 doesn't exist
on this sandbox's platform (Linux), so every test here monkeypatches
foreground_tracker._IS_WINDOWS to True and foreground_tracker._get_user32
to return a MagicMock standing in for the real user32 DLL handle. This
proves the module's OWN logic (which window counts as "ours", staleness
re-validation, thread lifecycle, fail-soft behavior) is correct against
the documented Win32 API contract; it does not and cannot prove the real
GetForegroundWindow()/GetWindowThreadProcessId()/IsWindow() calls behave
as expected on an actual desktop session. Confirm live on Windows before
trusting this for anything destructive.
"""

import os
import time

import pytest

import foreground_tracker as ft


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Every test gets _IS_WINDOWS forced True (so start()/get_last_
    foreground_window() don't just no-op on this Linux sandbox) and a
    guaranteed-clean tracker state before and after, so tests never leak
    a running thread or remembered handle into one another."""
    monkeypatch.setattr(ft, "_IS_WINDOWS", True)
    ft._reset_for_tests()
    yield
    ft._reset_for_tests()
    # _reset_for_tests() already stops the thread; also drop any cached
    # user32 binding a test installed, so the next test starts blank.
    ft._user32 = None


def _fake_user32(hwnd_pid_pairs, iswindow_result=True):
    """Builds a MagicMock standing in for ctypes.windll.user32.
    hwnd_pid_pairs: list of (hwnd, pid) the fake GetForegroundWindow()/
    GetWindowThreadProcessId() sequence should report, one pair consumed
    per call (last pair repeats once exhausted, so a poll loop that ticks
    more times than the list is long doesn't blow up)."""
    import ctypes
    user32 = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    state = {"i": 0}

    def _get_foreground_window():
        i = min(state["i"], len(hwnd_pid_pairs) - 1)
        state["i"] += 1
        return hwnd_pid_pairs[i][0]

    def _get_window_thread_process_id(hwnd, pid_ref):
        i = min(state["i"] - 1, len(hwnd_pid_pairs) - 1)
        i = max(i, 0)
        pid_ref._obj.value = hwnd_pid_pairs[i][1]

    user32.GetForegroundWindow.side_effect = _get_foreground_window
    user32.GetWindowThreadProcessId.side_effect = _get_window_thread_process_id
    user32.IsWindow.return_value = iswindow_result
    return user32


class TestGetForegroundWindowAndPid:
    def test_reads_hwnd_and_owning_pid(self):
        user32 = _fake_user32([(555, 4242)])
        hwnd, pid = ft._get_foreground_window_and_pid(user32)
        assert hwnd == 555
        assert pid == 4242

    def test_no_foreground_window_returns_none_none(self):
        user32 = _fake_user32([(0, 0)])
        hwnd, pid = ft._get_foreground_window_and_pid(user32)
        assert (hwnd, pid) == (None, None)

    def test_api_exception_fails_soft_to_none_none(self):
        from unittest.mock import MagicMock
        user32 = MagicMock()
        user32.GetForegroundWindow.side_effect = OSError("boom")
        hwnd, pid = ft._get_foreground_window_and_pid(user32)
        assert (hwnd, pid) == (None, None)


class TestPlatformGating:
    def test_start_is_a_no_op_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(ft, "_IS_WINDOWS", False)
        ft.start()
        assert ft.is_running() is False

    def test_get_last_foreground_window_returns_none_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(ft, "_IS_WINDOWS", False)
        assert ft.get_last_foreground_window() is None

    def test_get_user32_returns_none_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(ft, "_IS_WINDOWS", False)
        assert ft._get_user32() is None


class TestPollLoopRemembersLastForeignWindow:
    def _run_briefly_then_stop(self, monkeypatch, user32, ticks_to_wait=20):
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        for _ in range(ticks_to_wait):
            if ft._last_foreign_hwnd is not None:
                break
            time.sleep(0.01)
        ft.stop()

    def test_foreign_window_gets_remembered(self, monkeypatch):
        my_pid = os.getpid()
        user32 = _fake_user32([(777, my_pid + 1)])  # some other process
        self._run_briefly_then_stop(monkeypatch, user32)
        assert ft.get_last_foreground_window() == 777

    def test_own_process_window_is_never_remembered(self, monkeypatch):
        my_pid = os.getpid()
        user32 = _fake_user32([(111, my_pid)])  # TOKI's own window
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        time.sleep(0.08)  # several poll ticks
        ft.stop()
        assert ft.get_last_foreground_window() is None

    def test_switching_back_to_toki_does_not_clear_the_last_foreign_window(self, monkeypatch):
        # The whole point: once a real target window has been observed,
        # OS focus moving back to TOKI (the normal case right after the
        # user issues a command) must NOT wipe out that memory -- it's
        # exactly the moment _get_focused_window()'s fallback needs it.
        my_pid = os.getpid()
        user32 = _fake_user32([
            (777, my_pid + 1),  # browser has focus
            (111, my_pid),      # then TOKI gets focus (user hit Ctrl+K)
        ])
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        time.sleep(0.08)
        ft.stop()
        assert ft.get_last_foreground_window() == 777

    def test_a_single_bad_tick_does_not_kill_the_poll_loop(self, monkeypatch):
        from unittest.mock import MagicMock
        my_pid = os.getpid()
        user32 = MagicMock()
        calls = {"n": 0}

        def _flaky_get_foreground_window():
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient failure")
            return 888

        def _get_pid(hwnd, pid_ref):
            pid_ref._obj.value = my_pid + 1

        user32.GetForegroundWindow.side_effect = _flaky_get_foreground_window
        user32.GetWindowThreadProcessId.side_effect = _get_pid
        user32.IsWindow.return_value = True

        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        for _ in range(30):
            if ft._last_foreign_hwnd is not None:
                break
            time.sleep(0.01)
        ft.stop()
        assert ft.get_last_foreground_window() == 888


class TestGetLastForegroundWindowRevalidation:
    def test_returns_none_before_anything_observed(self, monkeypatch):
        monkeypatch.setattr(ft, "_get_user32", lambda: _fake_user32([(0, 0)]))
        assert ft.get_last_foreground_window() is None

    def test_stale_handle_that_no_longer_exists_returns_none(self, monkeypatch):
        with ft._lock:
            ft._last_foreign_hwnd = 4321
        user32 = _fake_user32([(0, 0)], iswindow_result=False)
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        assert ft.get_last_foreground_window() is None

    def test_still_valid_handle_is_returned(self, monkeypatch):
        with ft._lock:
            ft._last_foreign_hwnd = 4321
        user32 = _fake_user32([(0, 0)], iswindow_result=True)
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        assert ft.get_last_foreground_window() == 4321

    def test_iswindow_raising_fails_soft_to_none(self, monkeypatch):
        from unittest.mock import MagicMock
        with ft._lock:
            ft._last_foreign_hwnd = 4321
        user32 = MagicMock()
        user32.IsWindow.side_effect = OSError("boom")
        monkeypatch.setattr(ft, "_get_user32", lambda: user32)
        assert ft.get_last_foreground_window() is None


class TestThreadLifecycle:
    def test_start_spawns_a_daemon_thread(self, monkeypatch):
        monkeypatch.setattr(ft, "_get_user32", lambda: _fake_user32([(0, 0)]))
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        assert ft.is_running() is True
        assert ft._thread.daemon is True
        ft.stop()
        assert ft.is_running() is False

    def test_start_twice_does_not_spawn_a_second_thread(self, monkeypatch):
        monkeypatch.setattr(ft, "_get_user32", lambda: _fake_user32([(0, 0)]))
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        first_thread = ft._thread
        ft.start()
        assert ft._thread is first_thread
        ft.stop()

    def test_stop_before_start_does_not_raise(self):
        ft.stop()  # no-op, must not raise

    def test_stop_is_safe_to_call_twice(self, monkeypatch):
        monkeypatch.setattr(ft, "_get_user32", lambda: _fake_user32([(0, 0)]))
        monkeypatch.setattr(ft, "_POLL_INTERVAL_S", 0.01)
        ft.start()
        ft.stop()
        ft.stop()  # must not raise
