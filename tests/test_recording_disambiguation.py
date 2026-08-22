"""
test_recording_disambiguation.py -- BETA 0.3.49.

The bug: "start recording" used to unconditionally match START_SEEING
(macro capture), silently, even when the person meant dictation ("start
recording what I say"). See extractor.py's looks_like_ambiguous_start_recording()
/ looks_like_ambiguous_stop_recording() docstrings for the full root-cause
story and why a curated keyword table (not another confidence score) is
the right fix here.

Same fixture pattern as test_scheduling_and_conditionals.py's `assistant`
fixture -- see that file's own docstring for why every WindowsAIAssistant()
in a test file needs guaranteed teardown.
"""

import pytest

from extractor import (
    looks_like_start_seeing, looks_like_stop_seeing,
    looks_like_start_listening, looks_like_stop_listening,
    looks_like_ambiguous_start_recording, looks_like_ambiguous_stop_recording,
)
from orchestrator import WindowsAIAssistant


@pytest.fixture
def assistant():
    a = WindowsAIAssistant()
    yield a
    a.shutdown()


class TestExtractorLevelDisambiguation:
    """Pure-function checks -- no orchestrator needed."""

    def test_bare_recording_is_no_longer_auto_macro(self):
        assert not looks_like_start_seeing("start recording")
        assert not looks_like_start_seeing("begin recording")
        assert not looks_like_stop_seeing("stop recording")

    def test_bare_recording_is_no_longer_auto_dictation_either(self):
        # It never was -- dictation's own trigger words never included
        # "recording" before this session. Pinned so a future edit can't
        # accidentally introduce the OPPOSITE bug (a bare "record" auto-
        # claiming dictation instead).
        assert not looks_like_start_listening("start recording")

    def test_object_word_disambiguates_cleanly(self):
        assert looks_like_start_seeing("start recording what i click")
        assert looks_like_start_seeing("begin recording everything i do")
        assert looks_like_start_listening("start recording what i say")
        assert looks_like_start_listening("begin recording everything i say")

    def test_seeing_and_listening_specific_words_unaffected(self):
        # The words that were never ambiguous to begin with must keep
        # working exactly as before this session's change.
        assert looks_like_start_seeing("start seeing")
        assert looks_like_start_seeing("start watching")
        assert looks_like_start_listening("start listening")
        assert looks_like_start_listening("start dictating")

    def test_ambiguous_helpers_flag_the_bare_case_only(self):
        assert looks_like_ambiguous_start_recording("start recording")
        assert looks_like_ambiguous_stop_recording("stop recording")
        assert not looks_like_ambiguous_start_recording("start seeing")
        assert not looks_like_ambiguous_start_recording("start notepad")

    # ─── BETA 0.3.49 second pass: bare imperatives with NO "start"/     ─
    # "begin" at all. Confirmed live: "record what I say", "record my
    # screen", "record everything I say", and "start recording my
    # clicks" all missed looks_like_start_seeing/looks_like_start_
    # listening/the ambiguous-ask fallback entirely and fell through to
    # a plain graph/LLM miss (silent web search), because:
    #   - the dictation object-word branch required TWO separate
    #     "record"-root words in the sentence (one to satisfy its own
    #     opening (start|begin|record) group, a second for the literal
    #     "record(ing)?" right after) -- a bare "record what I say" only
    #     has ONE, so it satisfied neither that branch nor the
    #     "start|begin ... everything/what I say" branch (no start/
    #     begin present either).
    #   - the macro object-word branch only recognized "recording what I
    #     click", never "recording my clicks", despite "clicks" being an
    #     unambiguous macro signal on its own.
    #   - looks_like_ambiguous_start_recording() itself required a
    #     literal "start"/"begin" before "recording", so a bare "record
    #     my screen" (no object word at all, so neither of the above two
    #     functions could resolve it either) missed even the safety-net
    #     ask and fell straight through to a raw miss.

    def test_bare_imperative_with_say_object_matches_listening(self):
        """The actual reported gap: no 'start'/'begin' at all, just
        'record' + an explicit 'say' object. Must resolve directly to
        dictation, not fall through to a miss or get flagged ambiguous."""
        assert looks_like_start_listening("record what i say")
        assert looks_like_start_listening("record everything i say")
        assert not looks_like_start_seeing("record what i say")
        assert not looks_like_start_seeing("record everything i say")

    def test_my_clicks_object_matches_seeing_even_with_start_prefix(self):
        """'my clicks' (not just 'what I click') is just as unambiguous
        a macro signal and must resolve deterministically, not fall to
        the ambiguous-ask fallback for a question that has only one sane
        answer. (looks_like_ambiguous_start_recording() itself is now a
        broad superset match -- see test_widened_ambiguous_fallback_does
        _not_break_ordering_contract below for why that's fine; what
        actually matters is that the orchestrator checks
        looks_like_start_seeing() first and never reaches the ambiguous
        fallback once this returns True, which is covered end-to-end by
        TestOrchestratorStartDisambiguation.test_start_recording_my_
        clicks_resolves_without_asking.)"""
        assert looks_like_start_seeing("start recording my clicks")
        assert looks_like_start_seeing("recording my clicks")
        assert not looks_like_start_listening("start recording my clicks")

    def test_bare_record_with_no_object_still_flagged_ambiguous(self):
        """'record my screen' has no do/click/type/clicks/say object at
        all -- genuinely ambiguous (could mean macro capture or screen
        recording, TOKI has no dedicated screen-recording intent) -- and
        must still be caught by the ask-once fallback rather than falling
        through to a silent miss. This is the specific widening made to
        looks_like_ambiguous_start_recording() (dropping its previous
        hard requirement for a literal 'start'/'begin')."""
        assert looks_like_ambiguous_start_recording("record my screen")
        assert looks_like_ambiguous_start_recording("record everything")
        assert not looks_like_start_seeing("record my screen")
        assert not looks_like_start_listening("record my screen")

    def test_widened_ambiguous_fallback_does_not_break_ordering_contract(self):
        """The fallback regex is now a strict superset match (any bare
        'record'/'recording' at all, including ones with a resolvable
        object word) -- by itself it can no longer distinguish resolved
        cases from genuinely ambiguous ones. That's fine ONLY because
        orchestrator.py always checks looks_like_start_seeing() and
        looks_like_start_listening() first and only consults this
        fallback when both returned False (see orchestrator.py's
        dispatch order around looks_like_ambiguous_start_recording()).
        Pinned here as a documentation-level check: every phrasing that
        resolves deterministically above also happens to still match this
        broader regex taken in isolation, which is exactly why the
        calling order in orchestrator.py -- not this regex alone -- is
        what keeps resolved cases from being re-asked about."""
        for text in ("record what i say", "start recording my clicks"):
            assert looks_like_ambiguous_start_recording(text), (
                f"{text!r}: sanity-check that the fallback regex, taken "
                f"alone, is a superset -- if this ever stops matching, "
                f"the ordering-contract comment above needs updating too"
            )


class TestOrchestratorStartDisambiguation:
    def test_bare_start_recording_asks_instead_of_guessing(self, assistant):
        r = assistant.process_request(
            "start recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "chat"
        assert assistant._pending_recording_choice is not None
        assert assistant._pending_recording_choice["mode"] == "start"

    def test_answering_macro_routes_to_start_seeing(self, assistant):
        assistant.process_request(
            "start recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        r = assistant.process_request(
            "macro", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        # Whether it actually starts depends on pynput being installed
        # (it isn't in this sandbox) -- what matters here is it picked
        # the RIGHT intent, not that the underlying capture succeeded.
        # The macro-recording feature's user-facing name/wording changed
        # to "seeing" (app_control.py's start_seeing() now replies
        # "Watching. Do whatever you want me to repeat later..." with no
        # literal "macro"/"recording"/"pynput" substring at all) -- assert
        # on the actual routed intent instead of matching brittle response
        # text that's free to keep evolving independently of routing
        # correctness.
        assert r.get("intent") == "START_SEEING", (
            f"expected \"macro\" to route to START_SEEING, got: {r}"
        )

    def test_answering_voice_routes_to_start_listening(self, assistant):
        assistant.process_request(
            "start recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        r = assistant.process_request(
            "dictation", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r.get("intent") == "START_LISTENING"

    def test_unclear_answer_is_not_guessed_reprocessed_as_new_message(self, assistant):
        assistant.process_request(
            "start recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        # "banana" matches neither the macro nor voice keyword set -- must
        # NOT silently pick one. Reprocessed as a fresh message instead
        # (same fallthrough shape as _resume_pending_graph_ask()).
        r = assistant.process_request(
            "banana", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") not in ("START_SEEING", "START_LISTENING")

    def test_disambiguated_phrasing_never_asks(self, assistant):
        r = assistant.process_request(
            "start recording what i say", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") == "START_LISTENING"

    def test_bare_record_what_i_say_resolves_without_start_prefix(self, assistant):
        """BETA 0.3.49 second-pass fix: no 'start'/'begin' at all -- must
        resolve straight to dictation, not ask, and not fall through to
        a plain miss (silent web search of the whole sentence)."""
        r = assistant.process_request(
            "record what i say", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") == "START_LISTENING"

    def test_bare_record_everything_i_say_resolves_without_start_prefix(self, assistant):
        r = assistant.process_request(
            "record everything i say", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") == "START_LISTENING"

    def test_start_recording_my_clicks_resolves_without_asking(self, assistant):
        """BETA 0.3.49 second-pass fix: 'my clicks' is just as
        unambiguous as 'what I click' -- must resolve directly to macro
        capture, not ask a question with only one sane answer."""
        r = assistant.process_request(
            "start recording my clicks", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") == "START_SEEING"

    def test_bare_record_my_screen_asks_instead_of_silently_missing(self, assistant):
        """BETA 0.3.49 second-pass fix: no object word at all ('screen'
        isn't do/click/type/clicks/say) -- genuinely ambiguous, and must
        now reach the ask-once fallback (same shape as bare 'start
        recording') instead of falling straight through to a raw graph/
        LLM miss with no timer/recording ever started."""
        r = assistant.process_request(
            "record my screen", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "chat"
        assert assistant._pending_recording_choice is not None
        assert assistant._pending_recording_choice["mode"] == "start"


class _FakeDictationPipeline:
    """Minimal stand-in for voice_pipeline.DictationPipeline -- just
    enough surface (a no-op .stop()) for stop_dictation() to run past the
    "is something active" check without needing a real audio pipeline in
    this sandbox."""
    def stop(self):
        pass


class TestOrchestratorStopDisambiguation:
    def test_stop_recording_with_nothing_active_says_so(self, assistant):
        r = assistant.process_request(
            "stop recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert "nothing" in r["response"].lower()

    def test_stop_recording_resolves_via_runtime_state_macro_only(self, assistant):
        assistant.app_controller._active_recorder = object()
        r = assistant.process_request(
            "stop recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        # Routed to STOP_SEEING without asking -- confirmed via its own
        # missing-slot ask firing (macro name), not a fresh miss/search.
        assert "macro" in r["response"].lower()

    def test_stop_recording_resolves_via_runtime_state_dictation_only(self, assistant):
        assistant.app_controller._active_dictation = _FakeDictationPipeline()
        r = assistant.process_request(
            "stop recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert assistant._pending_recording_choice is None
        assert r.get("intent") == "STOP_LISTENING"

    def test_stop_recording_with_both_active_asks(self, assistant):
        assistant.app_controller._active_recorder = object()
        assistant.app_controller._active_dictation = _FakeDictationPipeline()
        r = assistant.process_request(
            "stop recording", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r["kind"] == "chat"
        assert assistant._pending_recording_choice is not None
        assert assistant._pending_recording_choice["mode"] == "stop"

        r2 = assistant.process_request(
            "the dictation one", on_output=lambda l: None, on_done=lambda c: None,
        )
        assert r2.get("intent") == "STOP_LISTENING"
