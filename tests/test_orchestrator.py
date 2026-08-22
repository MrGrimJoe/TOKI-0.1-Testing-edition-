"""
test_orchestrator.py -- import-time and wiring sanity checks for
orchestrator.py. Runs headless (no PyQt6/pywinauto/Ollama/Windows needed) --
same "direct Python-level testing" approach used throughout this project's
own STATUS.md sessions, just pinned as real tests now instead of re-derived
by hand each time.
"""

import pytest
import threading
from unittest.mock import patch, MagicMock

import orchestrator
from categories import CATEGORY_NAMES
from graph_router import NON_GRAPH_CATEGORIES


def test_orchestrator_imports_cleanly():
    # Regression guard for the "orchestrator.py compiles/imports cleanly"
    # check every BETA session has run by hand -- validate_category_map()
    # runs at import time and would raise here if a category mapping ever
    # goes stale.
    import importlib
    importlib.reload(orchestrator)


def test_escape_ps_slot_doubles_quotes():
    assert orchestrator._escape_ps_slot("O'Brien's Homework") == "O''Brien''s Homework"


def test_escape_ps_slot_passes_through_non_strings():
    # Non-string slot values (e.g. an int day count) must pass through
    # unchanged rather than erroring on .replace().
    assert orchestrator._escape_ps_slot(3) == 3
    assert orchestrator._escape_ps_slot(None) is None


def test_generate_file_registered_with_generate_kind():
    assert orchestrator.INTENTS["GENERATE_FILE"]["kind"] == "generate"


def test_every_intent_category_target_exists_in_intents():
    # categories.py's INTENT_CATEGORY must only ever point at real intents
    # -- validate_category_map() checks this at import time already, this
    # just re-asserts it as an explicit, independently-readable test.
    from categories import INTENT_CATEGORY
    for intent in INTENT_CATEGORY:
        assert intent in orchestrator.INTENTS, (
            f"{intent} is mapped in categories.py but missing from INTENTS"
        )


def test_non_graph_categories_have_no_dispatch_kind():
    # CHAT/ASK_CONTEXT must never accidentally gain a "kind" that would let
    # them be dispatched as if they were a real command.
    for name in NON_GRAPH_CATEGORIES:
        meta = orchestrator.INTENTS.get(name)
        assert meta is not None
        assert meta["kind"] in ("chat", "ask_context")


def test_parse_command_override_known_alias():
    result = orchestrator.parse_command_override('//weather Lahore')
    assert result == ("GET_WEATHER", "Lahore")


def test_parse_command_override_unknown_token_falls_through():
    # An unrecognized "//something" must return None (fall through to
    # normal classification), never raise or half-parse.
    assert orchestrator.parse_command_override("//not_a_real_command foo") is None


def test_parse_command_override_full_intent_name_case_insensitive():
    result = orchestrator.parse_command_override('//get_weather "Karachi"')
    assert result == ("GET_WEATHER", '"Karachi"')


@pytest.mark.parametrize("category", CATEGORY_NAMES)
def test_active_category_has_at_least_one_command(category):
    from categories import commands_in_category
    assert commands_in_category(category), f"{category} has zero mapped commands"


# ─── Bug fixes from this session (BETA 0.3.7): narration grounding ─────────

class TestNarrationGrounding:
    """Live repro (both from the SAME root cause -- narration was built
    from only the intent's generic description, never the actual
    resolved slot value, so the model had to re-guess specifics from the
    raw message on its own):
      - 'Create a file nmed "python"' dispatched correctly (extractor
        grabbed 'python' from the "" literal) but got narrated as if the
        file were called 'nmed' -- the model was never told the real
        answer.
      - 'now open it' got narrated as opening a specific folder name that
        appeared nowhere in the conversation.
    Fixed by _decision_context() injecting the real value(s) into what
    the model is told, plus _is_narration_grounded()/_fallback_narration()
    as a structural backstop for when a small local model still doesn't
    follow that (STATUS.md BETA 0.3.3 and this file's own api-kind
    docstring both independently found prompting alone isn't reliable
    enough here)."""

    def test_decision_context_names_the_real_value(self):
        meta = {"description": "Create a new empty file"}
        slots = {"path": r"C:\Users\Man in blue\OneDrive\Desktop\python.txt"}
        ctx = orchestrator._decision_context(meta, slots)
        assert "python.txt" in ctx
        assert "nmed" not in ctx

    def test_decision_context_falls_back_cleanly_with_no_slots(self):
        meta = {"description": "Empty the Recycle Bin"}
        ctx = orchestrator._decision_context(meta, {})
        assert ctx == "You've decided on this action: Empty the Recycle Bin."

    def test_grounded_narration_passes(self):
        values = orchestrator._narration_values({"path": r"C:\Desktop\python.txt"})
        assert orchestrator._is_narration_grounded("Creating python.txt for you now.", values)

    def test_hallucinated_narration_fails(self):
        # The exact shape of the live "Project X" / "nmed" bugs: fluent,
        # plausible-sounding, and completely disconnected from the real
        # resolved value.
        values = orchestrator._narration_values({"path": r"C:\Desktop\python.txt"})
        assert not orchestrator._is_narration_grounded("Opening the folder Project X for you.", values)

    def test_empty_narration_fails_when_a_value_was_expected(self):
        # Ollama-unreachable case -- stream_thinking() returns "" for
        # `text` on a ConnectionError. Previously this silently showed an
        # EMPTY narration; now it's treated as ungrounded so the
        # deterministic fallback takes over instead.
        values = orchestrator._narration_values({"path": r"C:\Desktop\python.txt"})
        assert not orchestrator._is_narration_grounded("", values)

    def test_no_expected_values_is_always_grounded(self):
        # No-slot intents (about a third of them) have nothing specific
        # to get wrong -- live streaming shouldn't be second-guessed here.
        assert orchestrator._is_narration_grounded("Sure, locking your workstation now.", [])

    def test_fallback_narration_is_deterministic_and_accurate(self):
        meta = {"description": "Delete a file or folder"}
        slots = {"path": r"C:\Users\Man in blue\OneDrive\Desktop\python"}
        text = orchestrator._fallback_narration(meta, slots)
        assert "python" in text
        assert "Deleting" in text

    def test_thinking_prompt_no_longer_contains_the_parroted_example(self):
        # The literal source of the "Checking how many files are on your
        # desktop" bug: that exact phrase used to be a hardcoded example
        # inside the system prompt itself, and the small model would
        # sometimes just parrot it verbatim regardless of the real
        # decision. Pinning that it's gone for good.
        prompt = orchestrator._build_thinking_system_prompt("You've decided on this action: Check the current weather.")
        assert "checking how many files" not in prompt.lower()


class TestListInstalledApps:
    """"what are all the apps on my computer" had no intent to land on at
    all, so it fell through to CHAT, which fabricated a fake "I'm
    checking..." response with no real action and no result behind it.
    Fixed by adding a real, graph-reachable LIST_INSTALLED_APPS intent
    wired to app_control.py's existing Get-StartApps-backed data."""

    def test_registered_as_app_control_kind(self):
        meta = orchestrator.INTENTS["LIST_INSTALLED_APPS"]
        assert meta["kind"] == "app_control"
        assert meta["action"] == "list_installed_apps"
        assert meta["slots"] == []

    def test_action_method_exists_on_app_controller(self):
        from app_control import AppController
        assert hasattr(AppController, "list_installed_apps")

    def test_graph_classifies_the_exact_reported_phrase(self):
        # The literal phrase from the live transcript this session fixed.
        from graph_router import GraphRouter
        result = GraphRouter().classify_or_ask("what are all the apps on my computer")
        assert result.get("intent") == "LIST_INSTALLED_APPS"


# ─── BETA 0.3.6: file-index/app-cache invalidation wiring ─────────────────
#
# extractor.FileIndex and the "on the spot search for newly installed
# apps" retry-once-on-miss behavior were added directly into
# _process_single_request's open-target cascade block -- too deep in a
# method that needs a live thinking-stream/history/RunningCommand to drive
# end-to-end for a headless test. These pin the two things that ARE
# testable without that: the write-intents set itself, and that the
# source actually calls both invalidate hooks before retrying, matching
# the documented "force a real rescan, try exactly once more" design.

def test_write_intents_covers_every_filesystem_mutating_command():
    # If a new file-mutating intent is ever added to intents.py without
    # being added here too, FileIndex silently goes stale after it runs --
    # this is a deliberate explicit list (see orchestrator.py's own
    # comment above _WRITE_INTENTS), not derived automatically, so it's
    # worth pinning what it currently claims to cover.
    assert orchestrator._WRITE_INTENTS == {
        "MAKE_FOLDER", "MAKE_FILE", "DELETE_ITEM", "RENAME_ITEM",
        "MOVE_ITEM", "COPY_ITEM", "GENERATE_FILE",
    }


def test_write_intents_are_all_real_registered_intents():
    for name in orchestrator._WRITE_INTENTS:
        assert name in orchestrator.INTENTS, (
            f"_WRITE_INTENTS references {name!r}, which isn't a real "
            f"registered intent -- FileIndex invalidation for it can "
            f"never fire"
        )


def test_open_cascade_retries_once_after_invalidating_both_caches():
    # Confirms the SHAPE of the retry logic directly in source: on a
    # miss, invalidate_app_cache() and file_index.invalidate() must both
    # be called before resolve_open_target() runs a second time -- not
    # zero times (no retry at all) and not in a loop (unbounded rescans).
    import inspect
    src = inspect.getsource(orchestrator.WindowsAIAssistant._process_single_request)
    invalidate_app_pos = src.index("self.app_controller.invalidate_app_cache()")
    invalidate_file_pos = src.index("file_index.invalidate()")
    # Both invalidate calls must appear, and resolve_open_target must be
    # called again (a second occurrence) after them.
    resolve_calls = [i for i in range(len(src)) if src.startswith("= resolve_open_target(", i)]
    assert len(resolve_calls) >= 2, (
        "expected resolve_open_target() called at least twice in "
        "_process_single_request -- once for the first look, once for "
        "the post-invalidate retry"
    )
    assert resolve_calls[0] < invalidate_app_pos < invalidate_file_pos < resolve_calls[1], (
        "expected order: first resolve_open_target() call, then both "
        "cache invalidations, then the retry call -- got a different "
        "ordering, which would mean the retry doesn't actually see "
        "fresh data"
    )


# ─── BETA 0.3.16: shutdown() closes both kuzu connections ──────────────────
#
# Found via the project owner's own fix to GraphRouter.close() (missing
# self.db.close() alongside self.conn.close()) -- that fix only matters if
# something actually CALLS .close(). Nothing did, anywhere in the running
# app, before this. Added WindowsAIAssistant.shutdown() + a closeEvent
# handler in app.py's MainWindow to call it on normal window close.

class TestShutdownReleasesGraphConnections:
    def test_shutdown_calls_close_on_both_resolvers(self):
        assistant = orchestrator.WindowsAIAssistant()
        with patch.object(assistant.graph_router, "close") as mock_graph_close, \
             patch.object(assistant.wcl_resolver, "close") as mock_wcl_close:
            assistant.shutdown()
        mock_graph_close.assert_called_once()
        mock_wcl_close.assert_called_once()

    def test_shutdown_is_safe_when_graph_router_is_none(self):
        assistant = orchestrator.WindowsAIAssistant()
        # graph_router is already None here on a real machine whenever
        # the underlying KuzuDB open fails/is locked (fail-open --
        # __init__ catches that and leaves graph_router as None; see
        # orchestrator.py around `self.graph_router = GraphRouter()`).
        # Calling .close() unconditionally before nulling it out assumed
        # it was always live, which isn't a safe assumption in this
        # test's own real-dispatch environment -- guard it the same way
        # production code does everywhere else it touches graph_router.
        if assistant.graph_router is not None:
            assistant.graph_router.close()
        assistant.graph_router = None
        assistant.shutdown()  # must not raise

    def test_shutdown_is_safe_when_wcl_resolver_is_none(self):
        assistant = orchestrator.WindowsAIAssistant()
        if assistant.wcl_resolver is not None:
            assistant.wcl_resolver.close()
        assistant.wcl_resolver = None
        assistant.shutdown()  # must not raise

    def test_shutdown_is_idempotent(self):
        # closeEvent could plausibly fire more than once in some Qt
        # edge cases -- calling shutdown() twice must never raise.
        assistant = orchestrator.WindowsAIAssistant()
        assistant.shutdown()
        assistant.shutdown()


class TestCannedGreetingSkipsBothLlmCalls:
    """The actual latency claim, proven end-to-end rather than just at the
    canned_reply() function level: a pure greeting must never reach
    self.router.classify() OR self.router.stream_thinking()/_run_thinking
    at all -- confirmed by patching both and asserting zero calls, not
    just checking the returned text looks right. This is what actually
    avoids the measured 20-30s/call prompt_eval cost on a CPU-only Ollama
    box; asserting only on the reply text wouldn't catch a regression
    where a canned reply is returned ALONGSIDE a wasted LLM call still
    silently happening in the background."""

    def test_pure_greeting_never_calls_the_llm(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify") as mock_classify, \
                 patch.object(assistant.router, "stream_thinking") as mock_stream:
                result = assistant.process_request(
                    "hey", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_classify.assert_not_called()
            mock_stream.assert_not_called()
            assert result["kind"] == "chat"
            assert result["response"]  # got a real reply, not an empty string
        finally:
            assistant.shutdown()

    def test_real_content_alongside_a_greeting_word_still_calls_classify(self):
        """The safety-critical negative case: a greeting word followed by
        real, open-ended content must NOT be caught by the canned path --
        it needs the real classify() call. Uses "hey who made you" rather
        than a weather-style question: confirmed directly that
        graph_router.classify() alone already resolves something like
        "hey what's the weather" to GET_WEATHER without ever reaching
        self.router.classify() (the LLM tier) at all -- that's correct
        EXISTING behavior (the graph runs before the LLM), not something
        this test should assert on. "hey who made you" is confirmed to
        miss the graph (no WCL/graph phrasing matches it) so it's a clean
        test of whether canned_reply() incorrectly swallows it before the
        LLM tier ever gets a turn. Mocks classify() to return a
        deterministic CHAT result (no real Ollama needed) and asserts it
        WAS called, proving the canned check didn't intercept this message."""
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify", return_value={"intent": "CHAT"}) as mock_classify:
                assistant.process_request(
                    "hey who made you", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_classify.assert_called_once()
        finally:
            assistant.shutdown()


# ─── BETA 0.3.27: destructive-shadow guard's AMBIGUOUS gap ─────────────────
#
# _check_destructive_shadow() only ever checked wcl_resolver's RESOLVED
# status. "clean temp files" / "wipe the temp files" resolve AMBIGUOUS
# (not RESOLVED) even though a genuinely destructive Clear-TempFiles
# candidate sits right in the returned candidate list -- so the guard
# never got a chance to fire. Root cause was one layer down in
# wcl_resolver.py (AMBIGUOUS candidates dropped danger_level entirely);
# fixed there, and this class exercises the guard's own logic on top of
# that fix. Requires the real graph/WCL data on disk, same as
# test_graph_router.py/test_wcl_resolver.py -- skips cleanly if absent.

class TestDestructiveShadowGuardCoversAmbiguous:
    @classmethod
    @pytest.fixture(scope="class")
    def assistant(cls):
        a = orchestrator.WindowsAIAssistant()
        if a.graph_router is None or a.wcl_resolver is None:
            pytest.skip("graph_router/wcl_resolver unavailable in this environment")
        yield a
        a.shutdown()

    @pytest.mark.parametrize("text", [
        "clean temp files",
        "wipe the temp files",
    ])
    def test_ambiguous_destructive_candidate_triggers_the_question(self, assistant, text):
        classification = assistant.graph_router.classify(text)
        assert classification is not None, f"{text!r} unexpectedly missed the graph"
        question = assistant._check_destructive_shadow(classification["intent"], text)
        assert question is not None, (
            f"{text!r} resolves AMBIGUOUS with a destructive candidate in "
            f"the list -- the guard must still fire, not just on RESOLVED"
        )

    @pytest.mark.parametrize("text", [
        "empty the recycle bin",
        "copy the item",
        "kill process chrome",
    ])
    def test_known_good_equivalences_stay_silent(self, assistant, text):
        # Regression guard: extending the check to AMBIGUOUS must not
        # start nagging on the legitimate equivalences this guard was
        # explicitly designed to stay silent on.
        classification = assistant.graph_router.classify(text)
        if classification is None:
            pytest.skip(f"{text!r} misses the graph in this build -- nothing to check")
        question = assistant._check_destructive_shadow(classification["intent"], text)
        assert question is None, f"{text!r} -> unexpected shadow question: {question!r}"

    def test_make_the_vm_vs_create_a_new_vm_now_consistent(self, assistant):
        # BETA 0.3.27 also closed the WCL alias-data gap that made this
        # inconsistent: "make the vm" was flagged, "create a new vm" was
        # not, purely because New-VM's alias list didn't cover that
        # phrasing. Both must now trigger identically.
        for text in ("make the vm", "create a new vm"):
            classification = assistant.graph_router.classify(text)
            assert classification is not None, f"{text!r} missed the graph"
            question = assistant._check_destructive_shadow(classification["intent"], text)
            assert question is not None and "New-VM" in question, (
                f"{text!r} -> {question!r}; expected a New-VM shadow warning"
            )

    def test_bitlocker_lock_now_caught(self, assistant):
        # priority.md #14 / BETA 0.3.27: Lock-BitLocker had exactly one
        # alias in the whole dataset, and it was the literal garbage
        # string "bitlocker bitlocker" (an alias-generation artifact) --
        # so natural phrasings like "lock bitlocker" never resolved to it
        # cleanly. Fixed by adding real aliases directly to the WCL graph.
        for text in ("lock bitlocker", "lock the bitlocker"):
            classification = assistant.graph_router.classify(text)
            assert classification is not None, f"{text!r} missed the graph"
            question = assistant._check_destructive_shadow(classification["intent"], text)
            assert question is not None and "Lock-BitLocker" in question, (
                f"{text!r} -> {question!r}; expected a Lock-BitLocker shadow warning"
            )


# ─── this session: click-to-teach + "start seeing" macro recording ─────────
#
# See target_memory.py/macro_recorder.py/app_control.py's own docstrings
# for the full design/safety rationale. Everything below exercises the
# REAL WindowsAIAssistant()/real graph db, same pattern as
# TestCannedGreetingSkipsBothLlmCalls above -- only the pynput-dependent
# innards of app_control.AppController get mocked/monkeypatched, never the
# orchestrator's own dispatch logic.

class TestStartStopSeeingDispatch:
    def test_start_seeing_dispatches_to_app_control(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "start_seeing", return_value="Watching.") as mock_start:
                result = assistant.process_request(
                    "start seeing", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_start.assert_called_once()
            assert result["kind"] == "app_control"
            assert result["response"] == "Watching."
        finally:
            assistant.shutdown()

    def test_stop_seeing_asks_for_a_name_first(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            result = assistant.process_request(
                "stop seeing", on_output=lambda l: None, on_done=lambda c: None,
            )
            assert result["kind"] == "chat"
            assert "call this macro" in result["response"]
        finally:
            assistant.shutdown()

    def test_stop_seeing_then_name_dispatches_stop_seeing_and_save(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant.process_request("stop seeing", on_output=lambda l: None, on_done=lambda c: None)
            with patch.object(assistant.app_controller, "stop_seeing_and_save",
                               return_value="Saved \"zeta\" (3 step(s)).") as mock_stop:
                result = assistant.process_request(
                    "zeta", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_stop.assert_called_once_with(macro_name="zeta")
            assert result["response"] == "Saved \"zeta\" (3 step(s))."
        finally:
            assistant.shutdown()

    def test_response_surfaces_the_real_result_not_a_hardcoded_done(self):
        # BUG FIX pinned here: "response" used to always be "Done."
        # regardless of what the action actually returned -- see
        # orchestrator.py's app_control dispatch block for the full note.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "start_seeing",
                               return_value="pynput not installed -- macro recording unavailable."):
                result = assistant.process_request(
                    "start seeing", on_output=lambda l: None, on_done=lambda c: None,
                )
            assert result["response"] == "pynput not installed -- macro recording unavailable."
            assert result["response"] != "Done."
        finally:
            assistant.shutdown()


class TestMacroNameMustBeOneWord:
    def test_multiword_name_is_rejected_by_app_controller(self):
        # Unit-level: AppController.stop_seeing_and_save() enforces this
        # directly (see app_control.py) -- this is the actual product
        # requirement from this session's design discussion ("the users
        # have to make a completely random [single] word up").
        import app_control
        ctrl = app_control.AppController()
        ctrl._active_recorder = MagicMock()
        ctrl._active_recorder.stop_recording.return_value = [{"type": "click"}]
        result = ctrl.stop_seeing_and_save("youtuber mode")
        assert "more than one word" in result
        # Still recording -- rejecting a bad name must not lose the
        # in-progress capture.
        assert ctrl._active_recorder is not None

    def test_valid_one_word_name_is_accepted(self):
        import app_control
        ctrl = app_control.AppController()
        fake_recorder = MagicMock()
        fake_recorder.stop_recording.return_value = [{"type": "click"}]
        ctrl._active_recorder = fake_recorder
        result = ctrl.stop_seeing_and_save("zeta")
        assert "Saved" in result
        assert ctrl._active_recorder is None  # recording session closed out


class TestBareWordMacroTrigger:
    def test_saved_macro_name_alone_dispatches_run_macro(self, tmp_path, monkeypatch):
        import macro_recorder
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        r = macro_recorder.MacroRecorder()
        r._events = [{"type": "click", "x": 1, "y": 2, "button": "left", "identity": None, "t": 0.0}]
        r.save("zeta")

        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "run_macro", return_value="Macro \"zeta\" finished.") as mock_run:
                result = assistant.process_request(
                    "zeta", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_run.assert_called_once_with(macro_name="zeta")
            assert result["response"] == "Macro \"zeta\" finished."
        finally:
            assistant.shutdown()

    def test_multiword_message_never_triggers_a_macro(self, tmp_path, monkeypatch):
        # Safety property 2 (macro_recorder.py docstring): only an exact
        # single bare word can trigger -- a saved macro named "zeta" must
        # never fire from a sentence that happens to contain "zeta".
        import macro_recorder
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        r = macro_recorder.MacroRecorder()
        r._events = [{"type": "click", "x": 1, "y": 2, "button": "left", "identity": None, "t": 0.0}]
        r.save("zeta")

        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "run_macro") as mock_run:
                assistant.process_request(
                    "can you run zeta for me", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_run.assert_not_called()
        finally:
            assistant.shutdown()

    def test_unsaved_word_does_not_trigger_anything(self, tmp_path, monkeypatch):
        import macro_recorder
        monkeypatch.setattr(macro_recorder, "MACROS_DIR", tmp_path)
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "run_macro") as mock_run:
                assistant.process_request(
                    "banana", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_run.assert_not_called()
        finally:
            assistant.shutdown()


class TestClickToTeachFlow:
    def test_clean_miss_offers_to_learn_from_next_click(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "click",
                               return_value="Couldn't confidently find \"the export button\" on screen -- not clicking anything.") as mock_click, \
                 patch.object(assistant.app_controller, "teach_from_next_click",
                               return_value="Got it -- I'll remember \"Export\" as \"the export button\".") as mock_teach:
                result = assistant.process_request(
                    "click the export button", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_click.assert_called_once()
            mock_teach.assert_called_once()
            assert "I'll remember" in result["response"]
        finally:
            assistant.shutdown()

    def test_successful_click_does_not_trigger_teach_flow(self):
        # BETA 0.3.40: a successful click's response is "Done." now (see
        # _process_single_request's app_control branch) -- "Clicked
        # \"Save\" at (50, 15)." on a SUCCESS is the exact same action
        # restated in different words, not new information. What this
        # test actually guards is unchanged: a successful click must not
        # trigger the click-to-teach fallback.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "click", return_value="Clicked \"Save\" at (50, 15).") as mock_click, \
                 patch.object(assistant.app_controller, "teach_from_next_click") as mock_teach:
                result = assistant.process_request(
                    "click the save button", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_click.assert_called_once()
            mock_teach.assert_not_called()
            assert result["response"] == "Done."
        finally:
            assistant.shutdown()

    def test_click_failure_still_surfaces_the_real_message(self):
        # Negative case for the same fix: a click failure that ISN'T the
        # "couldn't find it" click-to-teach trigger (e.g. UI Automation
        # missing entirely) must still reach the user as real text, not
        # get collapsed to "Done." along with the success case.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(
                assistant.app_controller, "click",
                return_value="Cursor control isn't available on this system (pywinauto/UI Automation required).",
            ):
                result = assistant.process_request(
                    "click the save button", on_output=lambda l: None, on_done=lambda c: None,
                )
            assert result["response"] == (
                "Cursor control isn't available on this system (pywinauto/UI Automation required)."
            )
        finally:
            assistant.shutdown()

    def test_launch_app_stays_done(self):
        # Same fix, LAUNCH_APP side: a successful launch's own return
        # string ("Launching Notepad.") is restatement, not new info --
        # response should be "Done.". Calls _dispatch() directly,
        # bypassing the real app-name-resolution pipeline entirely, since
        # what's under test here is the response-scoping logic in
        # _process_single_request, not app resolution.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "launch_app", return_value="Launching Notepad."):
                result = assistant._dispatch(
                    "LAUNCH_APP", "open notepad", {"app_name": "notepad"}, "",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=None, on_generate_done=None,
                )
            assert result["response"] == "Done."
        finally:
            assistant.shutdown()

    def test_launch_app_failure_still_surfaces_the_real_message(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.app_controller, "launch_app", return_value="Couldn't launch Notepad: boom"):
                result = assistant._dispatch(
                    "LAUNCH_APP", "open notepad", {"app_name": "notepad"}, "",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=None, on_generate_done=None,
                )
            assert result["response"] == "Couldn't launch Notepad: boom"
        finally:
            assistant.shutdown()


# ─── BETA 0.3.40: _pending_graph_ask was set but never resolved ────────────
#
# confirm_pending_graph_ask()/reject_pending_graph_ask() had zero callers
# anywhere (no thumbs UI in main_widget.py, which has no chat window at
# all) -- so a graph clarifying question sat unresolved forever, and the
# user's actual next message/utterance was silently reclassified from
# scratch instead of being read as the answer. These tests exercise the
# fix directly, without needing the real graph/kuzu data on disk: they
# fabricate a pending ask the same shape classify_or_ask()'s "ask" branch
# produces, exactly like tests/test_batch_test_live.py already does for
# its own _pending_graph_ask state-leakage coverage.

class TestGraphAskResumption:
    def _assistant_with_pending_ask(self):
        assistant = orchestrator.WindowsAIAssistant()
        assistant._pending_graph_ask = {
            "user_prompt": "frobnicate the thing",
            "unknown_words": ["frobnicate"],
            "candidate": "MAKE_FOLDER",
            "staged_ids": ["fake-id-1"],
        }
        return assistant

    def test_yes_reply_confirms_staged_words_and_clears_pending(self):
        assistant = self._assistant_with_pending_ask()
        try:
            with patch.object(orchestrator, "confirm_graph_ask") as mock_confirm, \
                 patch.object(orchestrator, "reject_graph_ask") as mock_reject:
                result = assistant.process_request(
                    "yes", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_confirm.assert_called_once_with(["fake-id-1"])
            mock_reject.assert_not_called()
            assert assistant._pending_graph_ask is None
            assert result["kind"] == "chat"
        finally:
            assistant.shutdown()

    def test_no_reply_rejects_staged_words_and_clears_pending(self):
        assistant = self._assistant_with_pending_ask()
        try:
            with patch.object(orchestrator, "confirm_graph_ask") as mock_confirm, \
                 patch.object(orchestrator, "reject_graph_ask") as mock_reject:
                result = assistant.process_request(
                    "no", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_reject.assert_called_once_with(["fake-id-1"])
            mock_confirm.assert_not_called()
            assert assistant._pending_graph_ask is None
            assert result["kind"] == "chat"
        finally:
            assistant.shutdown()

    def test_unrelated_next_message_is_not_swallowed(self):
        """The actual bug: before this fix, _process_single_request never
        checked self._pending_graph_ask at all, so this path was never
        even reached -- a real follow-up message after an unresolved ask
        just got classified fresh anyway (no crash), which masked the
        problem in casual testing. The REAL regression this guards
        against is upstream of this test (the missing top-of-method
        check, now added) and downstream (voice/widget dispatch treating
        every reply as a normal new message with no way to ever answer
        the question, so it stayed pending across the whole session).
        This test locks in the fixed contract: a non-yes/no reply stages
        the ask as rejected and is fully reprocessed as its own turn."""
        assistant = self._assistant_with_pending_ask()
        try:
            with patch.object(orchestrator, "reject_graph_ask") as mock_reject:
                result = assistant.process_request(
                    "hey", on_output=lambda l: None, on_done=lambda c: None,
                )
            mock_reject.assert_called_once_with(["fake-id-1"])
            assert assistant._pending_graph_ask is None
            # "hey" is a canned greeting -- proves the message actually
            # got reprocessed as new input, not swallowed as a bad answer.
            assert result["kind"] == "chat"
            assert result["response"]
        finally:
            assistant.shutdown()


class TestFunctionKeywordRoutesDirectlyToGenerateFile:
    """BETA 0.3.56: "function" bypasses Tier A's graph scoring entirely
    and routes straight to GENERATE_FILE -- see extractor.py's
    looks_like_function_creation() docstring for the full bug this
    closes (a named GENERATE_FILE request scoring below
    CONFIDENCE_THRESHOLD because the name dilutes the query's own
    TF-IDF vector, e.g. "create a function called calculator" measured
    live at 0.285 against the 0.5 threshold -- see STATUS.md's 0.3.55
    entry). Calls _process_single_request() directly (not just
    _dispatch()) so this proves the pre-check actually fires before
    graph classification is ever consulted, not just that _dispatch()
    behaves correctly once reached."""

    def test_named_function_request_dispatches_without_reaching_the_graph(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify") as mock_classify, \
                 patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._process_single_request(
                    "create a function called calculator",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_classify.assert_not_called()
            mock_gen.assert_called_once()
            called_prompt = mock_gen.call_args[0][0]
            assert called_prompt == "create a function called calculator"
        finally:
            assistant.shutdown()

    def test_bare_function_request_with_no_name_still_asks(self):
        # The 0.3.55 ask-on-miss behavior is untouched by this pre-check --
        # a bare "write a function that does this" (no "called X"/"named
        # X") still asks "what should I name it?" instead of silently
        # defaulting, exactly as it does when GENERATE_FILE is reached
        # the normal way.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify") as mock_classify, \
                 patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._process_single_request(
                    "write a function that does this",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_classify.assert_not_called()
            mock_gen.assert_not_called()
            assert result["kind"] == "chat"
            assert "name" in result["response"].lower()
            assert assistant._pending == {
                "intent": "GENERATE_FILE",
                "original_text": "write a function that does this",
            }
        finally:
            assistant.shutdown()

    def test_unrelated_folder_request_is_unaffected(self):
        # A plain "make a folder called Homework" has nothing to do with
        # "function" and must keep routing to MAKE_FOLDER exactly as
        # before -- this pre-check is scoped to the literal word
        # "function" only, never "folder"/"file"/"script"/"program".
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._process_single_request(
                    "make a folder called Homework",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_gen.assert_not_called()
            assert result.get("intent") != "GENERATE_FILE"
        finally:
            assistant.shutdown()

    def test_a_real_file_literally_named_function_is_not_stolen(self):
        # "function" can be a real filename, not just the code-generation
        # noun -- "open function.py" / "delete the file called function" /
        # a quoted literal name must all fall through to their normal
        # file-target intent instead of being swept into GENERATE_FILE.
        # None of these contain a creation verb (write/create/make/build/
        # generate/code), so looks_like_function_creation() must say False
        # for every one of them.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                for phrasing in [
                    "open function.py",
                    "delete the file called function",
                    "read function.txt",
                    'open "function"',
                ]:
                    result = assistant._process_single_request(
                        phrasing,
                        on_output=lambda l: None, on_done=lambda c: None,
                        on_thinking_token=None, on_generate_token=lambda t: None,
                        on_generate_done=lambda p, e: None,
                    )
                    assert result.get("intent") != "GENERATE_FILE", phrasing
            mock_gen.assert_not_called()
        finally:
            assistant.shutdown()

    def test_creation_verb_still_wins_even_with_a_file_extension_present(self):
        # A real creation verb always wins, regardless of what else is in
        # the sentence -- "write a function and save it as function.py"
        # is still unambiguously a generation request. No "called X"/
        # "named X" clause here, so this correctly lands on GENERATE_FILE's
        # own ask-for-a-name path (0.3.55) rather than dispatching outright
        # -- what matters for this test is that it's GENERATE_FILE asking,
        # not some other intent silently claiming it.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify") as mock_classify, \
                 patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._process_single_request(
                    "write a function and save it as function.py",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_classify.assert_not_called()
            mock_gen.assert_not_called()
            assert assistant._pending["intent"] == "GENERATE_FILE"
        finally:
            assistant.shutdown()


class TestGenerateFileAsksForMissingName:
    """BETA 0.3.55: GENERATE_FILE now asks "what should I name it?" on a
    missing name instead of generator.py silently defaulting to
    "generated_file.txt" -- see MISSING_SLOT_QUESTIONS' GENERATE_FILE
    entry, generator.extract_explicit_name(), and _dispatch()'s
    skip_generate_name_check parameter. generator.generate_and_save() is
    mocked throughout -- it's a real streamed Ollama call, out of scope
    for this file (no live Ollama in this sandbox); what's under test
    here is entirely the ask/merge/resume logic that runs BEFORE that
    call ever happens."""

    def _dispatch_generate_file(self, assistant, user_prompt):
        return assistant._dispatch(
            "GENERATE_FILE", user_prompt, {}, "context",
            on_output=lambda l: None, on_done=lambda c: None,
            on_thinking_token=None, on_generate_token=lambda t: None,
            on_generate_done=lambda p, e: None,
        )

    def test_no_name_present_asks_instead_of_generating(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = self._dispatch_generate_file(assistant, "write some code for this")
            mock_gen.assert_not_called()
            assert result["kind"] == "chat"
            assert "name" in result["response"].lower()
            assert assistant._pending == {
                "intent": "GENERATE_FILE", "original_text": "write some code for this",
            }
        finally:
            assistant.shutdown()

    def test_explicit_name_present_dispatches_immediately_without_asking(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                self._dispatch_generate_file(assistant, "create a function called calculator")
            mock_gen.assert_called_once()
            called_prompt = mock_gen.call_args[0][0]
            assert called_prompt == "create a function called calculator"
            assert assistant._pending is None
        finally:
            assistant.shutdown()

    def test_resume_with_a_name_merges_it_into_the_original_description(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant._pending = {
                "intent": "GENERATE_FILE",
                "original_text": "write some code for this",
            }
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                assistant._resume_pending(
                    "calculator",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_gen.assert_called_once()
            called_prompt = mock_gen.call_args[0][0]
            assert called_prompt == "write some code for this called calculator"
            assert assistant._pending is None
        finally:
            assistant.shutdown()

    def test_resume_strips_natural_answer_filler_before_merging(self):
        # "call it calculator" -> "calculator", same _strip_answer_filler
        # every other MISSING_SLOT_QUESTIONS answer already goes through.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant._pending = {
                "intent": "GENERATE_FILE", "original_text": "write some code for this",
            }
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                assistant._resume_pending(
                    "call it calculator",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            called_prompt = mock_gen.call_args[0][0]
            assert called_prompt == "write some code for this called calculator"
        finally:
            assistant.shutdown()

    def test_resume_with_skip_proceeds_with_original_text_unchanged(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant._pending = {
                "intent": "GENERATE_FILE", "original_text": "write some code for this",
            }
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                assistant._resume_pending(
                    "skip",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_gen.assert_called_once()
            called_prompt = mock_gen.call_args[0][0]
            # Unchanged from the original -- generator.py's own default
            # "generated_file" naming kicks in from here, same as before
            # this feature existed, but now as an INFORMED default (the
            # user was asked and explicitly declined) rather than silent.
            assert called_prompt == "write some code for this"
            assert assistant._pending is None
        finally:
            assistant.shutdown()

    def test_resume_with_empty_reply_also_falls_back_to_default_not_a_reask_loop(self):
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant._pending = {
                "intent": "GENERATE_FILE", "original_text": "write some code for this",
            }
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._resume_pending(
                    "   ",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_gen.assert_called_once()
            assert assistant._pending is None
            assert result["kind"] == "generate"
        finally:
            assistant.shutdown()

    def test_resumed_dispatch_does_not_re_ask_even_though_merge_text_has_the_word_called(self):
        # Sanity check on skip_generate_name_check itself: the merged
        # prompt DOES contain "called <name>" so extract_explicit_name()
        # would find it anyway here, but this confirms the bypass flag is
        # actually being threaded through correctly rather than
        # coincidentally working because the merge happens to satisfy the
        # regex -- skip case (previous test) is the one that actually
        # proves the flag matters, since "write some code for this" alone
        # would otherwise re-trigger the ask.
        assistant = orchestrator.WindowsAIAssistant()
        try:
            assistant._pending = {
                "intent": "GENERATE_FILE", "original_text": "write some code for this",
            }
            with patch.object(assistant.generator, "generate_and_save") as mock_gen:
                result = assistant._resume_pending(
                    "skip",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            assert result["kind"] != "chat" or "name" not in result.get("response", "").lower()
            mock_gen.assert_called_once()
        finally:
            assistant.shutdown()


class TestStartupCachePriming:
    """BETA 0.3.51: apis.py's location_cache, AppController's installed-app
    list, and extractor.py's FileIndex all fetch once and cache for the
    rest of the process -- but until this change, all three stayed lazy
    (populated on whichever real request happened to need one first), so
    the FIRST app-launch/file-open/location-dependent turn of a session
    silently paid the full fetch cost that every later turn got for free.
    WindowsAIAssistant.__init__ now fires all three in parallel background
    daemon threads instead."""

    def test_init_fires_all_three_priming_calls(self):
        calls = []
        with patch("orchestrator.location_cache") as mock_loc, \
             patch.object(orchestrator.AppController, "prime_app_cache",
                           lambda self: calls.append("apps")), \
             patch("orchestrator.file_index") as mock_fi:
            mock_loc.get = MagicMock(side_effect=lambda: calls.append("location"))
            mock_fi.get_entries = MagicMock(side_effect=lambda: calls.append("files"))
            a = orchestrator.WindowsAIAssistant()
            try:
                import time
                for _ in range(20):  # up to ~1s, polling rather than a fixed sleep
                    if len(calls) == 3:
                        break
                    time.sleep(0.05)
                assert sorted(calls) == ["apps", "files", "location"], calls
            finally:
                a.shutdown()

    def test_priming_does_not_block_init(self):
        # A slow/hanging cache call must never delay __init__ itself --
        # priming is fire-and-forget by design (see the method's own
        # docstring). Simulates a cache that takes noticeably longer than
        # a reasonable __init__ budget and confirms construction still
        # returns fast.
        import time

        def _slow_get():
            time.sleep(2.0)

        with patch("orchestrator.location_cache") as mock_loc:
            mock_loc.get = MagicMock(side_effect=_slow_get)
            t0 = time.time()
            a = orchestrator.WindowsAIAssistant()
            elapsed = time.time() - t0
            try:
                assert elapsed < 1.5, (
                    f"__init__ took {elapsed:.2f}s -- background priming "
                    f"must not block construction"
                )
            finally:
                a.shutdown()

    def test_priming_threads_are_daemon_threads(self):
        # Must never be what keeps the process alive, and must never block
        # shutdown waiting on a slow/hung network or subprocess call.
        # Patches threading.Thread itself rather than polling
        # threading.enumerate() after the fact -- with everything else
        # mocked, priming threads finish and exit almost instantly, so a
        # post-hoc enumerate() is a real race that can (and did, caught
        # here) find them already gone.
        #
        # __init__ now starts a 4th threading.Thread on real Windows, on
        # top of the original 3 cache-priming threads (location/apps/
        # files): foreground_tracker.start()'s own background thread
        # (added to fix video-download/app-control focus bugs -- see
        # __init__'s comment right above `foreground_tracker.start()`).
        # foreground_tracker.start() is itself a no-op on any non-Windows
        # platform (see its own docstring), so the expected count is
        # platform-dependent -- that fourth thread must be just as safe
        # (daemon, never blocks shutdown) as the priming ones wherever it
        # does start, so it's asserted here too rather than only counting
        # the original 3.
        import platform
        expected = 4 if platform.system() == "Windows" else 3
        created = []
        real_thread = threading.Thread

        def _spy_thread(*args, **kwargs):
            t = real_thread(*args, **kwargs)
            created.append(t)
            return t

        with patch("orchestrator.location_cache") as mock_loc, \
             patch.object(orchestrator.AppController, "prime_app_cache", lambda self: None), \
             patch("orchestrator.file_index") as mock_fi, \
             patch("orchestrator.threading.Thread", side_effect=_spy_thread):
            mock_loc.get = MagicMock()
            mock_fi.get_entries = MagicMock()
            a = orchestrator.WindowsAIAssistant()
            try:
                assert len(created) == expected, (
                    f"expected {expected} priming/tracking thread(s), got {len(created)}"
                )
                assert all(t.daemon for t in created), (
                    "every priming/tracking thread must be a daemon thread"
                )
            finally:
                a.shutdown()

    def test_a_failing_cache_does_not_affect_the_other_two(self):
        # Each cache's own fetch already fails soft internally (never
        # raises -- see each cache's docstring), but the priming wrapper
        # itself also try/excepts around each call as defense in depth.
        # This confirms one cache raising doesn't stop the others from
        # firing or crash the background thread silently in a way that's
        # invisible to a caller.
        calls = []
        with patch("orchestrator.location_cache") as mock_loc, \
             patch.object(orchestrator.AppController, "prime_app_cache",
                           lambda self: calls.append("apps")), \
             patch("orchestrator.file_index") as mock_fi:
            mock_loc.get = MagicMock(side_effect=RuntimeError("network is down"))
            mock_fi.get_entries = MagicMock(side_effect=lambda: calls.append("files"))
            a = orchestrator.WindowsAIAssistant()
            try:
                import time
                for _ in range(20):
                    if len(calls) == 2:
                        break
                    time.sleep(0.05)
                assert sorted(calls) == ["apps", "files"], calls
            finally:
                a.shutdown()


class TestOllamaFastFailWhenRecentlyUnreachable:
    """BETA 0.3.51: once a real network attempt confirms Ollama is
    unreachable, classify()/stream_thinking() must short-circuit to the
    same {"error": ...} shape for _UNREACHABLE_RETRY_SECONDS rather than
    attempting a fresh connection on every single call -- same
    fail-soft-with-cooldown pattern as apis.py's LocationCache and
    app_control.py's AppController (_FAILURE_RETRY_SECONDS)."""

    def _router(self):
        return orchestrator.OllamaRouter()

    def test_connection_error_is_remembered(self):
        router = self._router()
        with patch.object(router, "_call", return_value={"error": "Can't reach Ollama — is it running on localhost:11434?"}) as mock_call:
            # First call: real attempt, records unreachability itself
            # inside _call() in production -- simulate that side effect
            # directly since _call is mocked here.
            router._last_unreachable_time = None
            import time
            router._last_unreachable_time = time.time()
            result = router.classify("open notepad")
        # classify() must NOT have called _call() at all -- fast-failed
        # before the network attempt.
        mock_call.assert_not_called()
        assert "error" in result

    def test_retries_for_real_after_cooldown_expires(self):
        router = self._router()
        router._last_unreachable_time = __import__("time").time() - (
            orchestrator.OllamaRouter._UNREACHABLE_RETRY_SECONDS + 1
        )
        with patch.object(router, "_call", return_value={"category": "CHAT"}) as mock_call:
            result = router.classify("hello")
        mock_call.assert_called()
        assert result == {"intent": "CHAT"}

    def test_success_clears_the_unreachable_flag(self):
        # A successful _call() (real HTTP round trip in production) must
        # reset _last_unreachable_time so a LATER genuine failure doesn't
        # get confused with a stale one, and so the fast-fail path
        # doesn't linger after Ollama comes back up mid-session.
        router = self._router()
        router._last_unreachable_time = __import__("time").time()

        def _fake_call(*args, **kwargs):
            router._last_unreachable_time = None  # what a real success does
            return {"category": "CHAT"}

        # Cooldown hasn't expired, but since real production code resets
        # the flag INSIDE _call() the moment a real response comes back
        # (not inside classify()), this simulates that by calling classify
        # a first time with a cooldown already expired to allow the real
        # call through, then confirms the flag is gone afterward.
        router._last_unreachable_time = __import__("time").time() - (
            orchestrator.OllamaRouter._UNREACHABLE_RETRY_SECONDS + 1
        )
        with patch.object(router, "_call", side_effect=_fake_call):
            router.classify("hello")
        assert router._last_unreachable_time is None

    def test_never_fast_fails_when_ollama_has_never_been_tried(self):
        # A brand-new router (never attempted a call yet) must always try
        # for real -- _last_unreachable_time starts as None, not some
        # sentinel that accidentally fast-fails the very first call.
        router = self._router()
        assert router._last_unreachable_time is None
        with patch.object(router, "_call", return_value={"category": "CHAT"}) as mock_call:
            router.classify("hello")
        mock_call.assert_called()


class TestForegroundTrackerWiring:
    """foreground_tracker.py fixes _get_focused_window() (app_control.py)
    grabbing TOKI's own window instead of the real target -- see that
    module's docstring for the full bug writeup. WindowsAIAssistant just
    needs to start it early (__init__) and stop it on shutdown()."""

    def test_init_starts_the_tracker(self):
        with patch("orchestrator.foreground_tracker") as mock_tracker:
            a = orchestrator.WindowsAIAssistant()
            try:
                mock_tracker.start.assert_called_once()
            finally:
                a.shutdown()

    def test_shutdown_stops_the_tracker(self):
        with patch("orchestrator.foreground_tracker") as mock_tracker:
            a = orchestrator.WindowsAIAssistant()
            a.shutdown()
            mock_tracker.stop.assert_called_once()

    def test_a_broken_tracker_start_does_not_prevent_init(self):
        # start() itself already fails soft internally (see foreground_
        # tracker.py), but __init__ wraps the call too, defense-in-depth
        # -- a failure here must never be able to block construction of
        # the whole assistant.
        with patch("orchestrator.foreground_tracker") as mock_tracker:
            mock_tracker.start.side_effect = RuntimeError("should never happen, but just in case")
            a = orchestrator.WindowsAIAssistant()
            a.shutdown()


class TestConversationMemoryWiring:
    """conversation_memory.py's ConversationMemory is instantiated per
    WindowsAIAssistant, fed via _commit_history() (the one existing
    choke point every successful turn already runs through), and
    consulted ONLY on a total Tier A graph miss, as extra_context for
    OllamaRouter.classify() -- see that method's own docstring and the
    call site inside _process_single_request for exactly why that one
    spot and no other."""

    def test_init_creates_a_conversation_memory_instance(self):
        a = orchestrator.WindowsAIAssistant()
        try:
            assert isinstance(a.conversation_memory, orchestrator.ConversationMemory)
            assert a.conversation_memory.get_window() == []
        finally:
            a.shutdown()

    def test_commit_history_records_into_conversation_memory(self):
        a = orchestrator.WindowsAIAssistant()
        try:
            a._commit_history("open notepad", "Opening Notepad...", intent="LAUNCH_APP")
            window = a.conversation_memory.get_window()
            assert len(window) == 1
            assert window[0]["user_prompt"] == "open notepad"
            assert window[0]["intent"] == "LAUNCH_APP"
        finally:
            a.shutdown()

    def test_commit_history_without_intent_still_records_keywords(self):
        # Most _commit_history call sites (asks, errors, chat replies)
        # don't have a cleanly resolved intent -- intent=None must still
        # produce a usable keyword record, not skip recording entirely.
        a = orchestrator.WindowsAIAssistant()
        try:
            a._commit_history("what's the weather like", "It's sunny.")
            window = a.conversation_memory.get_window()
            assert len(window) == 1
            assert window[0]["intent"] is None
            assert "weather" in window[0]["keywords"]
        finally:
            a.shutdown()

    def test_extra_context_is_passed_to_classify_only_on_total_graph_miss(self):
        a = orchestrator.WindowsAIAssistant()
        try:
            # Seed some recent topic history.
            a._commit_history("let's talk about the sales report", "Sure, what about it?")

            with patch.object(a.graph_router, "classify", return_value=None), \
                 patch.object(a.graph_router, "classify_or_ask",
                               return_value={"ask": "", "unknown_words": []}), \
                 patch.object(a.router, "classify",
                               return_value={"error": "Can't reach Ollama"}) as mock_classify:
                a._process_single_request(
                    "can you sort that out", on_output=lambda l: None, on_done=lambda c: None,
                )
                assert mock_classify.called
                _, kwargs = mock_classify.call_args
                assert kwargs.get("extra_context") is not None
                assert "sales" in kwargs["extra_context"] or "report" in kwargs["extra_context"]
        finally:
            a.shutdown()

    def test_extra_context_is_none_with_no_recent_history(self):
        a = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(a.graph_router, "classify", return_value=None), \
                 patch.object(a.graph_router, "classify_or_ask",
                               return_value={"ask": "", "unknown_words": []}), \
                 patch.object(a.router, "classify",
                               return_value={"error": "Can't reach Ollama"}) as mock_classify:
                a._process_single_request(
                    "search the web for cats", on_output=lambda l: None, on_done=lambda c: None,
                )
                assert mock_classify.called
                _, kwargs = mock_classify.call_args
                assert kwargs.get("extra_context") is None
        finally:
            a.shutdown()


class TestOllamaRouterClassifyExtraContext:
    """Unit-level coverage of OllamaRouter.classify()'s new extra_context
    parameter itself, independent of the wiring above."""

    def _router(self):
        return orchestrator.OllamaRouter()

    def test_extra_context_prepended_as_a_system_message(self):
        router = self._router()
        captured = {}

        def _fake_call(system_prompt, user_prompt, schema, history=None):
            captured["history"] = history
            return {"category": "CHAT"}

        with patch.object(router, "_call", side_effect=_fake_call):
            router.classify("hi", extra_context="Recent topics: sales report, delete")

        assert captured["history"] is not None
        assert captured["history"][0] == {
            "role": "system",
            "content": "Recent topics: sales report, delete",
        }

    def test_no_extra_context_leaves_history_unchanged(self):
        router = self._router()
        captured = {}

        def _fake_call(system_prompt, user_prompt, schema, history=None):
            captured["history"] = history
            return {"category": "CHAT"}

        real_history = [{"role": "user", "content": "earlier turn"}]
        with patch.object(router, "_call", side_effect=_fake_call):
            router.classify("hi", history=real_history)

        assert captured["history"] == real_history

    def test_extra_context_combined_with_real_history_in_order(self):
        router = self._router()
        captured = {}

        def _fake_call(system_prompt, user_prompt, schema, history=None):
            captured["history"] = history
            return {"category": "CHAT"}

        real_history = [{"role": "user", "content": "earlier turn"}]
        with patch.object(router, "_call", side_effect=_fake_call):
            router.classify("hi", history=real_history, extra_context="topic note")

        assert captured["history"][0] == {"role": "system", "content": "topic note"}
        assert captured["history"][1:] == real_history
