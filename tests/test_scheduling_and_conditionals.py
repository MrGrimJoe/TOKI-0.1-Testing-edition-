"""
test_scheduling_and_conditionals.py -- pins the SCHEDULE_COMMAND,
CANCEL_SCHEDULED, and CONDITIONAL_COMMAND features (added to close the two
real gaps documented in STATUS.md's external-review-pass entry: no
conditional handling, no time/delay handling, both confirmed absent from
the codebase at the time).

Pure Python where possible (extractor-level detection), plus a small
number of real end-to-end tests against WindowsAIAssistant that use very
short delays (1-2 seconds) so the suite stays fast -- per the project
owner's own "don't let testing take forever" instruction. These end-to-end
tests do NOT need Ollama or Windows: the new pre-checks run BEFORE any LLM
call, and this file only asserts on the returned response dict / scheduler
state, never on actual PowerShell execution succeeding (which needs a real
Windows box this suite doesn't assume).
"""

import time
import threading

import pytest

from extractor import (
    find_time_expression, looks_conditional, looks_like_cancel_scheduled,
    extract_slots, resolve_missing_slot, format_delay,
)
from scheduler import ScheduledCommandManager, SchedulerFullError
from condition_checker import match_condition, CHECKABLE_CONDITIONS_SUMMARY
from orchestrator import WindowsAIAssistant


@pytest.fixture
def assistant():
    """BUG FOUND AND FIXED: every WindowsAIAssistant() in this file used to
    be created directly with no cleanup. On Linux (sandbox) this went
    unnoticed -- kuzu didn't enforce its file lock strictly enough to fail
    loudly. Tested for real on Windows (the project owner's own machine)
    and it broke an entirely separate, pre-existing test file
    (test_chain_split_viability.py) with 21 "Could not set lock on file"
    errors -- that file opens its own GraphRouter() on the same
    toki_graph_db, and every leaked, never-closed WindowsAIAssistant()
    instance from THIS file was still holding that same file locked when
    it ran. Fixed by routing every assistant through this fixture: yield +
    teardown guarantees .shutdown() runs even if the test body raises an
    assertion partway through, which a manual "call shutdown() at the end
    of the test" convention does not."""
    a = WindowsAIAssistant()
    yield a
    a.shutdown()


# ─── find_time_expression() ─────────────────────────────────────────────────

class TestFindTimeExpression:
    """The real bug this whole feature traces back to: graph_router.classify()
    used to silently match 'open notepad at 3pm' to plain OPEN_ITEM, dropping
    'at 3pm' entirely and firing immediately instead of scheduling or asking.
    These pin that find_time_expression() now reliably detects BOTH relative
    and absolute time expressions before classification ever runs."""

    @pytest.mark.parametrize("text,expected_remainder", [
        ("shut down in 10 minutes", "shut down"),
        ("lock my computer in 30 seconds", "lock my computer"),
        ("open notepad in 2 hours", "open notepad"),
    ])
    def test_relative_delay_detected(self, text, expected_remainder):
        result = find_time_expression(text)
        assert result is not None
        delay, _span, remainder = result
        assert delay > 0
        assert remainder == expected_remainder

    def test_absolute_time_detected(self):
        result = find_time_expression("open notepad at 3pm")
        assert result is not None
        delay, _span, remainder = result
        assert delay > 0
        assert remainder == "open notepad"

    @pytest.mark.parametrize("text", [
        "open notepad",
        "lock my computer",
        "show me disk usage",
        "empty the recycle bin",
    ])
    def test_no_false_positive_on_plain_commands(self, text):
        """A message with no genuine time expression must never be treated
        as a scheduling request -- this is the guard that keeps ordinary
        commands completely unaffected by this feature."""
        assert find_time_expression(text) is None

    def test_bare_time_expression_has_no_remainder(self):
        """'in 10 minutes' alone, with nothing to schedule, must not
        silently become a command with an empty command_text -- caller
        (extract_slots) must reject this and ask, not guess."""
        result = find_time_expression("in 10 minutes")
        assert result is not None
        _delay, _span, remainder = result
        assert remainder == ""

    def test_relative_units_seconds_minutes_hours(self):
        for unit_phrase, expected_seconds in [
            ("in 30 seconds", 30), ("in 5 minutes", 300), ("in 2 hours", 7200),
        ]:
            delay, _span, _rem = find_time_expression(f"do something {unit_phrase}")
            assert delay == expected_seconds


class TestFormatDelay:
    def test_seconds(self):
        assert "second" in format_delay(30)

    def test_minutes(self):
        assert "minute" in format_delay(600)

    def test_hours(self):
        assert "hour" in format_delay(7200)


# ─── looks_conditional() ─────────────────────────────────────────────────────

class TestLooksConditional:
    """BUG FOUND AND FIXED during implementation: the first version required
    an explicit ',' or 'then' separator between condition and action. Tested
    directly against 'if wifi is off turn it on' (a completely natural
    phrasing with neither) and it returned False -- pinned here so that
    exact regression can never silently reappear."""

    @pytest.mark.parametrize("text", [
        "if wifi is off turn it on",           # the exact phrasing that broke the first version
        "if battery is low show battery status",
        "if battery is low, show battery status",
        "if battery is low then show battery status",
    ])
    def test_conditional_shapes_detected(self, text):
        assert looks_conditional(text) is True

    @pytest.mark.parametrize("text", [
        "open notepad",
        "find files if any exist",  # "if" not leading -- not a conditional request
        "lock my computer",
    ])
    def test_no_false_positive(self, text):
        assert looks_conditional(text) is False


# ─── looks_like_cancel_scheduled() ────────────────────────────────────────────

class TestLooksLikeCancelScheduled:
    """Deliberately narrow trigger (only 'cancel', never 'stop'/'close'/'end')
    so this can never collide with KILL_PROCESS ('stop chrome') or any other
    existing intent already using those verbs."""

    @pytest.mark.parametrize("text", [
        "cancel S1", "cancel C2", "cancel the scheduled shutdown",
        "cancel the reminder", "cancel that timer",
    ])
    def test_detected(self, text):
        assert looks_like_cancel_scheduled(text) is True

    @pytest.mark.parametrize("text", [
        "stop chrome", "close notepad", "end the process", "cancel my order",
    ])
    def test_no_collision_with_existing_intents(self, text):
        assert looks_like_cancel_scheduled(text) is False


# ─── extract_slots() / resolve_missing_slot() for the new intents ───────────

class TestScheduleCommandSlots:
    def test_extracts_command_and_delay(self):
        slots = extract_slots("SCHEDULE_COMMAND", "shut down in 10 minutes")
        assert slots == {"command_text": "shut down", "delay_seconds": "600"}

    def test_bare_time_expression_returns_none(self):
        """No command to schedule -- must ask, not dispatch an empty command."""
        assert extract_slots("SCHEDULE_COMMAND", "in 10 minutes") is None

    def test_resolve_missing_slot_accepts_restated_command(self):
        slots = resolve_missing_slot("SCHEDULE_COMMAND", "in 10 minutes", "shut down in 10 minutes")
        assert slots is not None
        assert slots["command_text"] == "shut down"


class TestCancelScheduledSlots:
    def test_extracts_ref_from_id(self):
        assert extract_slots("CANCEL_SCHEDULED", "cancel S1") == {"ref": "S1"}

    def test_extracts_ref_from_description(self):
        slots = extract_slots("CANCEL_SCHEDULED", "cancel the scheduled shutdown")
        assert slots is not None
        assert "shutdown" in slots["ref"]


class TestConditionalCommandSlots:
    def test_never_auto_resolves_from_original_text(self):
        """Per product decision: TOKI never guesses the condition/action
        split from the original message, even when it looks fully spelled
        out already -- always asks."""
        assert extract_slots("CONDITIONAL_COMMAND", "if battery is low turn on notepad") is None

    def test_resolves_from_followup_answer(self):
        slots = resolve_missing_slot("CONDITIONAL_COMMAND", "if battery is low turn on notepad",
                                      "if battery is low, launch notepad")
        assert slots == {"condition_and_action": "if battery is low, launch notepad"}


# ─── match_condition() -- the deliberately small checkable-conditions registry ──

class TestMatchCondition:
    def test_battery_low_matches(self):
        assert match_condition("if battery is low, launch notepad") is not None

    def test_battery_full_matches(self):
        assert match_condition("battery is full") is not None

    def test_wifi_condition_not_supported(self):
        """No wifi-state check exists anywhere in this codebase (confirmed
        by grep before this feature was built) -- must return None, never
        silently pretend to monitor it."""
        assert match_condition("if wifi is off, connect to wifi") is None

    def test_summary_list_is_clean(self):
        """CHECKABLE_CONDITIONS has multiple phrasing keys per real
        condition (for substring matching) -- the user-facing summary list
        must not just dump those raw keys, or the message reads as
        redundant ('battery, battery low, battery is low, ...')."""
        assert CHECKABLE_CONDITIONS_SUMMARY == ["battery is low", "battery is full"]


# ─── scheduler.py -- ScheduledCommandManager ────────────────────────────────

class TestScheduledCommandManager:
    def test_schedule_and_it_fires(self):
        mgr = ScheduledCommandManager()
        fired = []
        mgr.schedule(0.3, "test command", lambda: fired.append(True))
        time.sleep(0.6)
        assert fired == [True]

    def test_cancel_by_id_prevents_firing(self):
        mgr = ScheduledCommandManager()
        fired = []
        item = mgr.schedule(0.3, "test command", lambda: fired.append(True))
        cancelled = mgr.cancel(item.id)
        assert cancelled is not None
        time.sleep(0.6)
        assert fired == []

    def test_cancel_by_description_substring(self):
        mgr = ScheduledCommandManager()
        item = mgr.schedule(5.0, "shut down the computer", lambda: None)
        cancelled = mgr.cancel("shutdown")
        # "shutdown" is not a literal substring of "shut down the computer"
        # (note the space) -- this pins the ACTUAL matching behavior rather
        # than assuming a looser match works.
        assert cancelled is None
        cancelled2 = mgr.cancel("shut down")
        assert cancelled2 is not None
        cancelled2_again = mgr.cancel(item.id)
        assert cancelled2_again is None  # already cancelled -- can't cancel twice

    def test_cancel_nonexistent_returns_none(self):
        mgr = ScheduledCommandManager()
        assert mgr.cancel("S999") is None

    def test_max_pending_guard(self):
        mgr = ScheduledCommandManager()
        mgr.MAX_PENDING = 2  # shrink for a fast test
        mgr.schedule(5.0, "one", lambda: None)
        mgr.schedule(5.0, "two", lambda: None)
        with pytest.raises(SchedulerFullError):
            mgr.schedule(5.0, "three", lambda: None)

    def test_list_active_excludes_cancelled_and_fired(self):
        mgr = ScheduledCommandManager()
        mgr.schedule(0.2, "will fire", lambda: None)
        item2 = mgr.schedule(5.0, "will be cancelled", lambda: None)
        mgr.cancel(item2.id)
        time.sleep(0.4)
        assert mgr.list_active() == []

    def test_shutdown_cancels_everything(self):
        mgr = ScheduledCommandManager()
        fired = []
        mgr.schedule(0.3, "a", lambda: fired.append("a"))
        mgr.schedule(0.3, "b", lambda: fired.append("b"))
        mgr.shutdown()
        time.sleep(0.6)
        assert fired == []


# ─── End-to-end through WindowsAIAssistant (no Ollama needed -- the new ────
#     pre-checks run before any LLM call is ever made) ──────────────────────

class TestEndToEndScheduling:
    def test_schedule_command_dispatches_and_confirms(self, assistant):
        a = assistant
        outputs = []
        result = a.process_request(
            "show me disk usage in 2 seconds",
            on_output=outputs.append, on_done=lambda code: None,
        )
        assert result["kind"] == "schedule"
        assert "S1" in result["response"]
        assert len(a.scheduler.list_active()) == 1

    def test_schedule_then_cancel(self, assistant):
        a = assistant
        r1 = a.process_request("show me disk usage in 5 seconds",
                                on_output=lambda l: None, on_done=lambda c: None)
        assert r1["kind"] == "schedule"
        r2 = a.process_request("cancel S1",
                                on_output=lambda l: None, on_done=lambda c: None)
        assert "Cancelled" in r2["response"]
        assert a.scheduler.list_active() == []

    def test_bare_time_expression_asks_instead_of_guessing(self, assistant):
        a = assistant
        a.process_request("in 10 minutes",
                           on_output=lambda l: None, on_done=lambda c: None)
        assert a._pending is not None
        assert a._pending["intent"] == "SCHEDULE_COMMAND"

    def test_scheduled_command_actually_fires_and_redispatches(self, assistant):
        """Confirms the fired command goes through the REAL classify ->
        dispatch pipeline (shows up in history as the real dispatched
        intent), not just a raw string echo.

        BUG FOUND AND FIXED: this originally slept a single fixed 1.8s
        then asserted once. Tested for real on Windows and it failed
        (assert 2 > 2 -- history never grew) -- on real hardware, firing
        involves not just the 1s timer but a real PowerShell subprocess
        spawn via RunningCommand, which can easily take longer than a
        short fixed sleep, especially the first PowerShell call in a
        process (interpreter startup cost). Fixed by polling for up to
        10s instead of sleeping once for a fixed, possibly-too-short
        window -- this is correct on both a fast sandbox and a slower
        real machine, rather than tuned to whichever one wrote the test."""
        a = assistant
        a.process_request("show me disk usage in 1 seconds",
                           on_output=lambda l: None, on_done=lambda c: None)
        history_len_before = len(a.history)
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if len(a.history) > history_len_before:
                break
            time.sleep(0.2)
        assert len(a.history) > history_len_before, "scheduled command never fired within 10s"
        assert any("DISK_USAGE" in h.get("content", "") for h in a.history)


class TestEndToEndConditional:
    def test_conditional_asks_for_clarification_first(self, assistant):
        a = assistant
        result = a.process_request("if wifi is off turn it on",
                                    on_output=lambda l: None, on_done=lambda c: None)
        assert a._pending is not None
        assert a._pending["intent"] == "CONDITIONAL_COMMAND"
        assert "condition" in result["response"].lower()

    def test_supported_condition_starts_watching(self, assistant):
        a = assistant
        a.process_request("if battery is low turn on notepad",
                           on_output=lambda l: None, on_done=lambda c: None)
        result = a.process_request("if battery is low, launch notepad",
                                    on_output=lambda l: None, on_done=lambda c: None)
        assert result["kind"] == "conditional"
        assert len(a.condition_poller.list_active()) == 1

    def test_unsupported_condition_is_honest_not_silent(self, assistant):
        """The core honesty requirement for this feature: an unsupported
        condition (wifi -- no check exists anywhere in this codebase) must
        produce a plain statement that it can't be monitored, and must NOT
        start a background watch pretending otherwise."""
        a = assistant
        a.process_request("if wifi is off turn it on",
                           on_output=lambda l: None, on_done=lambda c: None)
        result = a.process_request("if wifi is off, connect to wifi",
                                    on_output=lambda l: None, on_done=lambda c: None)
        assert result["kind"] == "chat"
        assert "can't monitor" in result["response"].lower()
        assert a.condition_poller.list_active() == []

    def test_cancel_active_watch(self, assistant):
        a = assistant
        a.process_request("if battery is low turn on notepad",
                           on_output=lambda l: None, on_done=lambda c: None)
        a.process_request("if battery is low, launch notepad",
                           on_output=lambda l: None, on_done=lambda c: None)
        assert len(a.condition_poller.list_active()) == 1
        result = a.process_request("cancel C1",
                                    on_output=lambda l: None, on_done=lambda c: None)
        assert "watch" in result["response"].lower() or "stopped" in result["response"].lower()
        assert a.condition_poller.list_active() == []


# ─── BETA 0.3.28: ConditionPoller cancel-vs-reschedule race ────────────────
#
# _tick() used to read/write item.cancelled/item.fired/item._timer with NO
# lock held, while cancel()/shutdown() mutate those same fields UNDER
# self._lock. checker() can block for up to 5s (a real PowerShell
# subprocess) -- if cancel() runs while _tick() is mid-checker() call, the
# cancel takes effect against the CURRENT timer, but _tick() then finishes,
# sees the condition still false, and reschedules by creating a NEW timer,
# silently reviving a poller the user just cancelled. Reproduced here
# deterministically with threading.Event (not sleep/timing), matching the
# actual described race exactly.

class TestConditionPollerCancelRace:
    def test_cancel_during_slow_checker_call_does_not_revive(self):
        from condition_checker import ConditionPoller

        poller = ConditionPoller()
        checker_entered = threading.Event()
        release_checker = threading.Event()
        fired = threading.Event()

        def slow_checker():
            checker_entered.set()
            release_checker.wait(timeout=5)
            return False  # condition still false when checker() returns

        item = poller.start(
            checker=slow_checker,
            description="test slow condition",
            on_true=lambda: fired.set(),
            on_error=lambda e: None,
            on_timeout=lambda: None,
        )

        # Force the first tick to run NOW instead of waiting
        # POLL_INTERVAL_SECONDS (5s): cancel the real timer (so it never
        # fires on its own mid-test) and invoke the tick function it was
        # holding directly, on a background thread -- exactly what the
        # real Timer thread would have done.
        with poller._lock:
            tick_fn = item._timer.function
            item._timer.cancel()
        tick_thread = threading.Thread(target=tick_fn)
        tick_thread.start()

        assert checker_entered.wait(timeout=2), "checker() was never entered"

        # Cancel while checker() is still blocked -- the exact race window
        # described in the bug report.
        cancelled = poller.cancel(item.id)
        assert cancelled is not None
        assert item.cancelled is True

        # Let checker() finish and return False. PRE-FIX: _tick() would
        # silently create+start a brand new timer right here, reviving a
        # poller that was just told to stop.
        release_checker.set()
        tick_thread.join(timeout=2)

        with poller._lock:
            assert item._timer is None or not item._timer.is_alive(), (
                "cancelled condition was silently revived by a new timer "
                "after cancel() raced with a slow checker() call"
            )
        assert not fired.is_set()
        assert poller.list_active() == []

    def test_cancel_after_checker_returns_true_but_before_fired_flag(self):
        """A softer variant of the same race: cancel() lands in the tiny
        window after checker() returns True but before _tick() has
        committed item.fired -- must not call on_true() for an already-
        cancelled item."""
        from condition_checker import ConditionPoller

        poller = ConditionPoller()
        checker_returned = threading.Event()
        release_after_check = threading.Event()
        fired = threading.Event()

        def checker():
            result = True
            checker_returned.set()
            release_after_check.wait(timeout=5)
            return result

        # Can't easily pause INSIDE _tick() between checker() returning and
        # the lock being acquired without patching, so instead we assert
        # the actually-shipped behavior directly: cancelling before
        # checker() returns must mean on_true() is never called once it
        # does return True.
        item = poller.start(
            checker=checker,
            description="test true-but-cancelled",
            on_true=lambda: fired.set(),
            on_error=lambda e: None,
            on_timeout=lambda: None,
        )
        with poller._lock:
            tick_fn = item._timer.function
            item._timer.cancel()
        tick_thread = threading.Thread(target=tick_fn)
        tick_thread.start()

        assert checker_returned.wait(timeout=2)
        poller.cancel(item.id)
        release_after_check.set()
        tick_thread.join(timeout=2)

        assert not fired.is_set(), (
            "on_true() fired for an item that was cancelled before the "
            "result was committed"
        )


# ─── SET_TIMER (BETA 0.3.48) ─────────────────────────────────────────────
# The bug this closes: a bare "set a timer for 10 minutes" / "remind me in
# 20 minutes" has no real command to run. Before this intent existed,
# SCHEDULE_COMMAND claimed these too and stored the leftover text ("set a
# timer for", "remind me") as command_text -- which got blindly re-run
# through the full pipeline at fire time and silently web-searched that
# exact phrase. See extractor.py's looks_like_bare_timer() docstring.
class TestSetTimer:
    def test_for_phrasing_now_matches(self):
        """'for N minutes' used to match nothing at all in
        find_time_expression -- only 'in N minutes' did -- so this exact
        phrasing (arguably the most natural way to ask for a timer) fell
        all the way through to a raw graph/LLM miss."""
        from extractor import find_time_expression
        result = find_time_expression("set a timer for 10 minutes")
        assert result is not None
        delay, _span, _remainder = result
        assert delay == 600

    def test_bare_timer_request_dispatches_as_timer_not_schedule(self, assistant):
        r = assistant.process_request(
            "set a timer for 2 seconds",
            on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "timer"
        assert assistant._pending is None

    def test_reminder_with_label_keeps_label_for_notification_only(self, assistant):
        r = assistant.process_request(
            "remind me in 2 seconds to check the oven",
            on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "timer"
        assert "check the oven" in r["response"]
        time.sleep(2.5)
        # The label must show up only as notification text, never get
        # re-run through process_request as if it were a command -- this
        # asserts the actual mechanism, not just the immediate response.
        assert any("check the oven" in h.get("content", "") for h in assistant.history[-3:])

    def test_real_scheduled_command_is_unaffected(self, assistant):
        """A message WITH a real command attached must still go through
        SCHEDULE_COMMAND, not get diverted here -- looks_like_bare_timer()
        must return None for these."""
        r = assistant.process_request(
            "lock my computer in 3 seconds",
            on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "schedule"

    def test_ambiguous_bare_time_expression_still_asks(self, assistant):
        """Regression guard: a bare time expression with NO timer/reminder
        trigger word at all ('in 10 minutes' alone) is genuinely
        ambiguous -- could be a truncated real command just as easily as
        a timer -- and must still fall through to SCHEDULE_COMMAND's
        existing 'what should I do, and when?' ask, not silently guess
        either way."""
        assistant.process_request(
            "in 10 minutes", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending is not None
        assert assistant._pending["intent"] == "SCHEDULE_COMMAND"


# ─── BETA 0.3.49: SET_TIMER phrasing gaps reopened the exact bug it was ──
# built to close. Two independent root causes in extractor.py:
#   1. _BARE_TIMER_REMAINDER_RE only accepted "a"/"the" (not "an") before
#      the trigger word, and only recognized "set" as a lead-in verb --
#      "an alarm" and "give me a reminder" both missed the trigger-word
#      check entirely and fell through to raw SCHEDULE_COMMAND, which
#      re-runs the leftover text ("set an alarm", "give me a reminder")
#      verbatim through the pipeline at fire time and silently
#      web-searches it -- the exact 0.3.48 bug, recurred via a different
#      gap.
#   2. find_time_expression()/_RELATIVE_TIME_RE only recognized a digit
#      before the unit -- word-form durations ("an hour", "a minute")
#      and a duration with no preposition at all directly in front of
#      the trigger word ("a 10 minute timer") never matched, so these
#      cases didn't even reach the scheduling pre-check -- straight to a
#      plain miss, no timer ever created.
class TestSetTimerPhrasingGaps:
    @pytest.mark.parametrize("text,expected_seconds", [
        ("set an alarm for 5 minutes", 300),
        ("give me a reminder in 15 minutes", 900),
        ("set a timer for an hour", 3600),
        ("set a timer for a minute", 60),
        ("set a 10 minute timer", 600),
        ("set a 2 hour timer", 7200),
        ("give me an alarm in 5 minutes", 300),
        # Case/politeness/whitespace noise shouldn't matter.
        ("SET AN ALARM FOR 5 MINUTES", 300),
        ("please set an alarm for 5 minutes", 300),
        ("can you give me a reminder in 15 minutes", 900),
    ])
    def test_previously_missed_phrasings_now_extract_a_timer(
        self, assistant, text, expected_seconds
    ):
        r = assistant.process_request(
            text, on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "timer", (
            f"{text!r} -> {r}; must be dispatched as a bare timer, not "
            f"fall through to SCHEDULE_COMMAND (which would silently "
            f"re-run the leftover text as a command at fire time) or a "
            f"raw graph/LLM miss (which would web-search the sentence "
            f"and never create a timer at all)"
        )
        assert assistant._pending is None

    def test_word_form_duration_computes_correct_delay(self):
        from extractor import find_time_expression
        for text, expected_seconds in [
            ("set a timer for an hour", 3600),
            ("remind me in a minute", 60),
            ("wake me up in a second", 1),
        ]:
            result = find_time_expression(text)
            assert result is not None, f"{text!r} matched nothing"
            delay, _span, _remainder = result
            assert delay == expected_seconds, f"{text!r} -> {delay}"

    def test_bare_duration_before_timer_noun_computes_correct_delay(self):
        from extractor import find_time_expression
        for text, expected_seconds in [
            ("set a 10 minute timer", 600),
            ("set a 90 second timer", 90),
            ("set a 2 hour alarm", 7200),
        ]:
            result = find_time_expression(text)
            assert result is not None, f"{text!r} matched nothing"
            delay, _span, _remainder = result
            assert delay == expected_seconds, f"{text!r} -> {delay}"

    @pytest.mark.parametrize("text", [
        "lock my computer in an hour",
        "shut down for a minute",  # nonsensical duration for shut down,
        # but must still be treated as a real (non-timer) scheduled
        # command, not silently dropped or misparsed -- word-form
        # duration support must not be timer-noun-specific in a way that
        # breaks SCHEDULE_COMMAND's own remainder extraction.
    ])
    def test_word_form_duration_still_works_for_real_scheduled_commands(
        self, assistant, text
    ):
        r = assistant.process_request(
            text, on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "schedule", f"{text!r} -> {r}"

    @pytest.mark.parametrize("text", [
        "the movie is 90 minutes long",
        "it took a minute to load",
        "wait a minute, that's not right",
        "a 10 minute walk sounds nice",
    ])
    def test_no_false_positive_on_incidental_durations(self, text):
        """Guard against overcorrecting: widening the amount pattern to
        accept 'a'/'an' and adding the no-preposition bare-duration path
        must NOT turn ordinary sentences that merely mention a duration
        into scheduling requests. The no-preposition path only fires
        when the duration sits directly before timer/alarm/reminder --
        these sentences have no such word nearby, and none contain an
        in/for preposition either, so they must still fall through
        find_time_expression() as None."""
        from extractor import find_time_expression
        assert find_time_expression(text) is None, (
            f"{text!r} incorrectly matched a time expression"
        )

    def test_no_false_positive_on_number_unit_before_unrelated_noun(self):
        """'a 10 minute meeting' is a duration attached to something that
        is NOT a timer/alarm/reminder -- the no-preposition bare-duration
        regex is anchored on the specific trigger nouns via lookahead and
        must not fire here."""
        from extractor import find_time_expression
        assert find_time_expression("schedule a 10 minute meeting") is None

    @pytest.mark.parametrize("text", [
        "an alarm",
        "a reminder",
        "the timer",
        "give me a reminder",
        "set an alarm",
    ])
    def test_bare_timer_remainder_recognizes_an_and_give_me(self, text):
        """Direct unit coverage of the regex fix itself: 'an' alongside
        'a'/'the', and 'give me' alongside 'set', as accepted lead-ins
        with nothing else actionable in the remainder."""
        from extractor import _BARE_TIMER_REMAINDER_RE
        assert _BARE_TIMER_REMAINDER_RE.match(text), f"{text!r} should match"

    @pytest.mark.parametrize("text", [
        "give me the report",
        "give me a reminder to call mom",  # has a real label -- must be
        # handled by the "remind me to X" label branch, not swallowed as
        # a bare (label-less) timer remainder.
        "set an alarm clock company",
    ])
    def test_bare_timer_remainder_does_not_overmatch(self, text):
        from extractor import _BARE_TIMER_REMAINDER_RE
        assert not _BARE_TIMER_REMAINDER_RE.match(text), f"{text!r} should NOT match"
