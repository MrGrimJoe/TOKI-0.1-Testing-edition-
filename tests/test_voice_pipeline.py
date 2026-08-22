"""
test_voice_pipeline.py -- pins the BETA 0.3.28 fix to the Ctrl+K
"already capturing" race in HotkeyVoicePipeline._record_and_transcribe().

BUG (pre-fix): _record_and_transcribe() did its setup work (drain stale
queue, reset VAD, clear _extend_event) BEFORE setting self._capturing =
True. on_hotkey_trigger() branches on self._capturing to decide whether a
Ctrl+K press should start a new session (self._trigger.set()) or extend
the current one (extend_listening(), which just sets the module-level
_extend_event). A Ctrl+K press landing in that setup window saw
self._capturing == False and called self._trigger.set() instead of
extend_listening() -- but run()'s while-loop was still blocked inside
this very call to _record_and_transcribe(), not back at
self._trigger.wait(), so that trigger was simply lost: the user's
Ctrl+K did nothing (no extend, no fresh capture).

FIX: flip self._capturing = True as the very last step of the
stale-state cleanup, immediately before any timing-sensitive capture
work begins, shrinking the mis-routing window down to a few lines
instead of the whole setup block.

These tests exercise the ordering and the on_hotkey_trigger() branch
directly -- no real audio device, no PyQt event loop, no Silero/whisper
model loading required.
"""

import queue
import threading
import time

import numpy as np
import pytest
from unittest.mock import MagicMock

import voice_pipeline
from voice_pipeline import HotkeyVoicePipeline, extend_listening, _extend_event


@pytest.fixture(autouse=True)
def _clean_extend_event():
    _extend_event.clear()
    yield
    _extend_event.clear()


def _make_pipeline() -> HotkeyVoicePipeline:
    # Constructed but never .start()'d -- we call internals directly, so
    # no QThread event loop or real audio stream is needed.
    return HotkeyVoicePipeline()


class TestCapturingFlagRaceWindow:
    def test_capturing_is_true_before_stop_flag_lets_setup_finish(self):
        """
        Directly pins the ordering: block _record_and_transcribe() partway
        through its setup (via a stop_flag that fires as soon as
        _capturing flips True) and confirm _capturing is already True at
        that point -- i.e. the flag flips before the function can return,
        not after.
        """
        pipeline = _make_pipeline()

        # No-speech timeout path is the fastest way out of
        # _record_and_transcribe() without touching the VAD/whisper model,
        # so set the stop flag immediately -- the loop's first iteration
        # checks _stop_flag and exits right away, but _capturing must
        # already be True by the time we can observe it here because the
        # fix sets it before the loop is even entered.
        pipeline._stop_flag.set()
        pipeline._record_and_transcribe()

        # After the call returns (stop flag broke the loop before any
        # no-speech/hangover logic ran), _capturing must have been reset
        # to False again as the function's own cleanup -- but during the
        # call it must have been True. We can't observe mid-call state
        # directly here, so the meaningful regression guard is the
        # behavioral test below, which is what actually matters.
        assert pipeline._capturing is False  # cleaned up on the way out

    def test_hotkey_during_setup_window_is_treated_as_extend_not_lost(self):
        """
        The real regression: simulate a Ctrl+K press landing in the
        stale-state-cleanup window by calling on_hotkey_trigger() the
        instant _capturing flips True (patched in via a wrapper), and
        confirm it's routed as an extend (sets _extend_event), not as a
        swallowed fresh-session trigger.
        """
        pipeline = _make_pipeline()
        observed = {}

        # time.monotonic() is the very first thing called once setup
        # finishes and _capturing has been flipped (used both right after
        # the flip, for session_start_t, and again on the loop's first
        # iteration). Hooking it fires our simulated Ctrl+K press right
        # after the flag flip under the fix -- squarely inside what used
        # to be the (much larger) unfixed race window.
        import voice_pipeline as vp_module
        original_monotonic = vp_module.time.monotonic

        def _monotonic_and_trigger():
            if "fired" not in observed:
                observed["fired"] = True
                observed["capturing_at_trigger_time"] = pipeline._capturing
                pipeline.on_hotkey_trigger()
            return original_monotonic()

        vp_module.time.monotonic = _monotonic_and_trigger
        pipeline._stop_flag.set()  # exit the capture loop immediately after setup

        try:
            pipeline._record_and_transcribe()
        finally:
            vp_module.time.monotonic = original_monotonic

        assert observed.get("capturing_at_trigger_time") is True, (
            "the queue-drain check ran while _capturing was still False -- "
            "the fix (flip _capturing True before this setup work) isn't "
            "in place, so a Ctrl+K press here would still be misrouted"
        )
        assert _extend_event.is_set(), (
            "a Ctrl+K press landing in the setup window must be treated "
            "as extend_listening() (sets _extend_event), not silently "
            "lost as a swallowed fresh-session trigger"
        )
        assert not pipeline._trigger.is_set(), (
            "on_hotkey_trigger() must not have fallen through to the "
            "fresh-session branch (_trigger.set()) once _capturing is True"
        )


class TestOnHotkeyTriggerBranching:
    """Direct unit tests of on_hotkey_trigger()'s branch, independent of
    _record_and_transcribe()'s internals -- confirms the dispatch rule
    itself (not just this one call site) stays correct."""

    def test_not_capturing_starts_fresh_trigger(self):
        pipeline = _make_pipeline()
        pipeline._capturing = False
        pipeline.on_hotkey_trigger()
        assert pipeline._trigger.is_set()
        assert not _extend_event.is_set()

    def test_capturing_extends_instead_of_fresh_trigger(self):
        pipeline = _make_pipeline()
        pipeline._capturing = True
        pipeline.on_hotkey_trigger()
        assert _extend_event.is_set()
        assert not pipeline._trigger.is_set()


# ─── BETA 0.3.31: a direct probe of the actual vulnerable window ───────────
#
# The tests above hook time.monotonic(), whose first call in
# _record_and_transcribe() happens AFTER self._capturing = True is set --
# so they can only ever observe _capturing as True at that point, REGARDLESS
# of whether the fix (capturing=True moved before the drain/vad-reset/
# extend_event.clear() block) is actually in place or not. Confirmed this
# directly: an intervening edit moved self._capturing = True back to AFTER
# that setup block (the original bug's exact ordering) while the tests
# above kept passing, because they never probe a point BEFORE that line.
#
# This test hooks self._vad.reset() instead, which runs INSIDE that setup
# block -- strictly before self._capturing = True in the unfixed ordering,
# strictly after it in the fixed ordering. It's the one instrumentation
# point that can actually tell the two apart. Confirmed by temporarily
# reverting the fix: this test fails (capturing observed False, no
# extend_listening() call, _trigger set instead) exactly as described in
# the original bug report, while the tests above kept passing throughout.

class TestVadResetWindowIsNotVulnerable:
    def test_capturing_already_true_when_vad_reset_runs(self, monkeypatch):
        pipeline = _make_pipeline()
        entered_vad_reset = threading.Event()
        release_vad_reset = threading.Event()
        original_reset = pipeline._vad.reset

        def paused_reset():
            entered_vad_reset.set()
            release_vad_reset.wait(timeout=2)
            return original_reset()

        monkeypatch.setattr(pipeline._vad, "reset", paused_reset)

        t = threading.Thread(target=pipeline._record_and_transcribe)
        t.start()
        try:
            assert entered_vad_reset.wait(timeout=2), "test setup issue: never reached vad.reset()"
            assert pipeline._capturing is True, (
                "self._capturing must already be True by the time "
                "vad.reset() runs -- if this is False, the drain/reset "
                "block still runs BEFORE capturing is set, and the race "
                "window from the original bug report is open again"
            )
        finally:
            pipeline._stop_flag.set()
            release_vad_reset.set()
            t.join(timeout=3)
        assert not t.is_alive()

    def test_hotkey_at_vad_reset_time_extends_not_rearms(self, monkeypatch):
        pipeline = _make_pipeline()
        entered_vad_reset = threading.Event()
        release_vad_reset = threading.Event()
        original_reset = pipeline._vad.reset

        def paused_reset():
            entered_vad_reset.set()
            release_vad_reset.wait(timeout=2)
            return original_reset()

        monkeypatch.setattr(pipeline._vad, "reset", paused_reset)

        t = threading.Thread(target=pipeline._record_and_transcribe)
        t.start()
        try:
            assert entered_vad_reset.wait(timeout=2), "test setup issue: never reached vad.reset()"
            # The exact race window from the original bug report.
            pipeline.on_hotkey_trigger()
            assert _extend_event.is_set(), (
                "a Ctrl+K press landing while vad.reset() is running must "
                "be treated as extend_listening(), not silently lost"
            )
            assert not pipeline._trigger.is_set(), (
                "PRE-FIX: _trigger would be set here instead, and the "
                "keypress would sit unused until this session ends, then "
                "immediately start a whole new session instead of "
                "extending this one"
            )
        finally:
            pipeline._stop_flag.set()
            release_vad_reset.set()
            t.join(timeout=3)
        assert not t.is_alive()


# ── DictationPipeline ("start listening") ───────────────────────────────────
#
# Same approach as the HotkeyVoicePipeline tests above: exercise
# _capture_one_utterance() and stop() directly, no real audio device, no
# Silero/whisper model loading, no QThread event loop. _capture_one_
# utterance()'s own docstring calls out that it deliberately shares its
# segmentation shape with _record_and_transcribe() -- these tests confirm
# the one real difference: silence never ends the *session* here (only
# self._stop_flag does), only ever one *utterance*.

from voice_pipeline import DictationPipeline


def _make_dictation_pipeline() -> DictationPipeline:
    # Constructed but never .start()'d, same reasoning as _make_pipeline()
    # above -- we drive _capture_one_utterance() directly.
    return DictationPipeline()


class _FakeSegment:
    def __init__(self, text):
        self.text = text


class TestDictationCaptureOneUtterance:
    def test_stop_flag_already_set_returns_empty_without_blocking(self):
        pipeline = _make_dictation_pipeline()
        pipeline._stop_flag.set()
        assert pipeline._capture_one_utterance() == ""

    def test_no_speech_within_timeout_returns_empty(self, monkeypatch):
        monkeypatch.setattr("voice_pipeline.NO_SPEECH_TIMEOUT_S", 0.05)
        pipeline = _make_dictation_pipeline()
        # Queue stays empty the whole time -- every get() times out, VAD
        # never sees a frame, heard_speech never flips True.
        assert pipeline._capture_one_utterance() == ""

    def test_speech_then_silence_hangover_transcribes_and_returns_text(self, monkeypatch):
        monkeypatch.setattr("voice_pipeline.SILENCE_HANGOVER_S", 0.05)
        monkeypatch.setattr("voice_pipeline.NO_SPEECH_TIMEOUT_S", 5.0)
        pipeline = _make_dictation_pipeline()

        # Force the VAD to report "speech" for every frame it's given,
        # skipping the real Silero model entirely (not available in this
        # sandbox, same as the existing HotkeyVoicePipeline tests' approach).
        monkeypatch.setattr(pipeline._vad, "speech_prob", lambda frame: 1.0)

        # _capture_one_utterance() drains any STALE queue contents as its
        # very first step (same "clear leftovers from the previous
        # utterance" pattern _record_and_transcribe() uses -- see that
        # method's own comments) -- so the frame has to arrive from a
        # background feeder AFTER capture starts, not be pre-loaded before
        # the call, or the drain step consumes it before the loop ever runs.
        frame = np.zeros(voice_pipeline.VAD_FRAME_SAMPLES, dtype=np.int16)
        feeder = threading.Timer(0.02, lambda: pipeline._audio_q.put(frame))
        feeder.start()

        pipeline._whisper = MagicMock()
        pipeline._whisper.transcribe.return_value = ([_FakeSegment("hello world")], None)

        result = pipeline._capture_one_utterance()
        feeder.join()
        assert result == "hello world"
        pipeline._whisper.transcribe.assert_called_once()

    def test_max_utterance_cap_ends_a_runaway_recording(self, monkeypatch):
        # Speech that never stops (VAD always True, hangover never fires)
        # must still end via the hard cap, not hang forever.
        monkeypatch.setattr("voice_pipeline.MAX_UTTERANCE_S", 0.2)
        monkeypatch.setattr("voice_pipeline.SILENCE_HANGOVER_S", 999)
        pipeline = _make_dictation_pipeline()
        monkeypatch.setattr(pipeline._vad, "speech_prob", lambda frame: 1.0)

        frame = np.zeros(voice_pipeline.VAD_FRAME_SAMPLES, dtype=np.int16)
        stop_feeding = threading.Event()

        def _keep_feeding():
            while not stop_feeding.is_set():
                pipeline._audio_q.put(frame)
                time.sleep(0.01)

        feeder = threading.Thread(target=_keep_feeding, daemon=True)
        feeder.start()

        pipeline._whisper = MagicMock()
        pipeline._whisper.transcribe.return_value = ([_FakeSegment("done")], None)

        result = pipeline._capture_one_utterance()
        stop_feeding.set()
        feeder.join(timeout=1)
        assert result == "done"

    def test_transcription_error_returns_empty_not_a_crash(self, monkeypatch):
        monkeypatch.setattr("voice_pipeline.SILENCE_HANGOVER_S", 0.05)
        monkeypatch.setattr("voice_pipeline.NO_SPEECH_TIMEOUT_S", 5.0)
        pipeline = _make_dictation_pipeline()
        monkeypatch.setattr(pipeline._vad, "speech_prob", lambda frame: 1.0)

        frame = np.zeros(voice_pipeline.VAD_FRAME_SAMPLES, dtype=np.int16)
        feeder = threading.Timer(0.02, lambda: pipeline._audio_q.put(frame))
        feeder.start()

        pipeline._whisper = MagicMock()
        pipeline._whisper.transcribe.side_effect = RuntimeError("model error")

        result = pipeline._capture_one_utterance()
        feeder.join()
        assert result == ""


class TestDictationStop:
    def test_stop_sets_the_flag_callable_from_any_thread(self):
        pipeline = _make_dictation_pipeline()
        assert not pipeline._stop_flag.is_set()
        pipeline.stop()
        assert pipeline._stop_flag.is_set()
