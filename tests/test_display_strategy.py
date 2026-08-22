"""
Tests for display_strategy.py.

TestMapCompleteness is the load-bearing one: it diffs INTENT_DISPLAY_MAP
against the live, merged intent set (orchestrator.INTENT_NAMES, which
includes intents.py + intents_extended.py + intents_app_control.py +
GENERATE_FILE + whatever plugins are installed) so a new intent added
anywhere without updating the map fails loudly here instead of silently
falling back to a guessed default at runtime.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from display_strategy import DisplayStrategy, INTENT_DISPLAY_MAP, classify_display


class TestMapCompleteness:
    def test_map_covers_every_real_intent_exactly(self):
        import orchestrator

        real_intents = set(orchestrator.INTENT_NAMES)
        mapped_intents = set(INTENT_DISPLAY_MAP.keys())

        missing = real_intents - mapped_intents
        extra = mapped_intents - real_intents

        assert not missing, (
            f"These real intents have no display-strategy classification "
            f"at all -- add them to INTENT_DISPLAY_MAP in display_strategy.py: "
            f"{sorted(missing)}"
        )
        assert not extra, (
            f"INTENT_DISPLAY_MAP has entries for intents that no longer "
            f"exist -- remove them (or check for a rename this map missed): "
            f"{sorted(extra)}"
        )

    def test_every_value_is_a_real_displaystrategy(self):
        for intent, strategy in INTENT_DISPLAY_MAP.items():
            assert isinstance(strategy, DisplayStrategy), (
                f"{intent!r} maps to {strategy!r}, not a DisplayStrategy member"
            )

    @pytest.mark.parametrize("intent", [
        # A handful of the most consequential classifications, pinned
        # individually so a future edit to the bulk map can't silently
        # flip one of these without a test noticing.
        "DELETE_ITEM", "MAKE_FOLDER", "KILL_PROCESS", "LOCK_WORKSTATION",
        "EMPTY_RECYCLE_BIN", "LAUNCH_APP", "SET_TIMER", "SCHEDULE_COMMAND",
    ])
    def test_actions_are_done(self, intent):
        assert INTENT_DISPLAY_MAP[intent] == DisplayStrategy.DONE

    @pytest.mark.parametrize("intent", [
        "LIST_FILES", "READ_FILE", "GET_WEATHER", "GET_TIME", "DISK_USAGE",
        "SEARCH_WEB", "BATTERY_STATUS", "CHAT", "ASK_CONTEXT", "GENERATE_FILE",
    ])
    def test_information_is_info(self, intent):
        assert INTENT_DISPLAY_MAP[intent] == DisplayStrategy.INFO


class TestClassifyDisplayApiKind:
    def test_successful_api_result_uses_intent_map(self):
        result = {"response": "Lahore: 32C, wind 10 km/h", "kind": "api", "intent": "GET_WEATHER"}
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.INFO
        assert text == "Lahore: 32C, wind 10 km/h"

    def test_api_failure_prefix_is_error_regardless_of_intent(self):
        # GET_WEATHER is INFO in the map, but a failed call must still be
        # ERROR, not silently shown as if it were a successful info card.
        result = {
            "response": "Hmm, that didn't work. Weather lookup failed: can't reach the internet right now.",
            "kind": "api", "intent": "GET_WEATHER",
        }
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.ERROR
        assert "didn't work" in text

    def test_api_done_intent_still_done(self):
        result = {"response": "Copied to clipboard.", "kind": "api", "intent": "SET_CLIPBOARD"}
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.DONE


class TestClassifyDisplayPowershellKind:
    def test_info_intent_uses_collected_output_not_the_done_placeholder(self):
        # This is the core bug this module exists to fix: process_request()
        # returns response="Done." synchronously for EVERY powershell-kind
        # intent, even LIST_FILES -- the real listing only exists in the
        # asynchronously-collected on_output lines.
        result = {"response": "Done.", "kind": "powershell", "intent": "LIST_FILES"}
        strategy, text = classify_display(
            result, collected_output="a.txt\nb.txt\nc.txt", exit_code=0,
        )
        assert strategy == DisplayStrategy.INFO
        assert text == "a.txt\nb.txt\nc.txt"

    def test_done_intent_ignores_collected_output(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "MAKE_FOLDER"}
        strategy, text = classify_display(
            result, collected_output="some incidental stdout noise", exit_code=0,
        )
        assert strategy == DisplayStrategy.DONE
        assert text == "Done."

    def test_nonzero_exit_code_is_error_even_for_a_done_intent(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "DELETE_ITEM"}
        strategy, text = classify_display(
            result, collected_output="Remove-Item : Access is denied", exit_code=1,
        )
        assert strategy == DisplayStrategy.ERROR
        assert "Access is denied" in text

    def test_nonzero_exit_code_with_no_output_falls_back_to_generic_message(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "KILL_PROCESS"}
        strategy, text = classify_display(result, collected_output="", exit_code=1)
        assert strategy == DisplayStrategy.ERROR
        assert "exit code 1" in text

    def test_info_intent_with_empty_output_shows_placeholder_not_blank(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "FIND_FILES"}
        strategy, text = classify_display(result, collected_output="   ", exit_code=0)
        assert strategy == DisplayStrategy.INFO
        assert text == "(no output)"

    def test_unmapped_intent_defaults_to_info_not_done(self):
        """Safety net: an intent missing from the map (shouldn't happen
        given test_map_covers_every_real_intent_exactly, but this is the
        behavior if it ever does) must default to INFO, not DONE --
        losing information is worse than an unnecessary persistent card."""
        result = {"response": "Done.", "kind": "powershell", "intent": "SOME_FUTURE_INTENT"}
        strategy, _ = classify_display(result, collected_output="real output here", exit_code=0)
        assert strategy == DisplayStrategy.INFO

    # ─── timed_out=True: the caller (main_widget.py's _run_and_classify)
    # gave up waiting for on_done within its own bound. This must NEVER
    # be treated the same as a clean 0-exit success -- an earlier version
    # of this function had no `timed_out` parameter at all, so a timeout
    # (exit_code stays None) fell through to "exit_code not in (None, 0)"
    # being False, i.e. silently treated as success, which for a
    # DONE-classified intent meant showing a bare "Done." while the
    # command might still genuinely be running.

    def test_timeout_on_info_intent_shows_partial_output_honestly(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "FIND_DUPLICATE_FILES"}
        strategy, text = classify_display(
            result, collected_output="a.txt\nb.txt", exit_code=None, timed_out=True,
        )
        assert strategy == DisplayStrategy.INFO
        assert "a.txt" in text and "b.txt" in text
        assert "still running" in text.lower() or "longer than expected" in text.lower()

    def test_timeout_on_done_intent_does_not_falsely_claim_done(self):
        """The critical case: a slow DONE-classified command (e.g.
        COMPRESS_SELECTED_FILE on a large folder) that times out must
        NOT show 'Done.' -- that would be an outright false claim that
        the operation finished when it may still be running."""
        result = {"response": "Done.", "kind": "powershell", "intent": "COMPRESS_SELECTED_FILE"}
        strategy, text = classify_display(
            result, collected_output="", exit_code=None, timed_out=True,
        )
        assert strategy != DisplayStrategy.DONE
        assert text != "Done."
        assert "still running" in text.lower() or "longer than expected" in text.lower()

    def test_timeout_with_no_output_yet_still_says_so_honestly(self):
        result = {"response": "Done.", "kind": "powershell", "intent": "MAKE_FOLDER"}
        strategy, text = classify_display(result, collected_output="", exit_code=None, timed_out=True)
        assert strategy == DisplayStrategy.INFO
        assert "nothing yet" in text.lower() or "still running" in text.lower()

    def test_timed_out_false_is_unaffected_normal_path(self):
        # Default/explicit timed_out=False must behave exactly as before
        # -- this test would have caught a regression where adding the
        # parameter accidentally changed the non-timeout code path.
        result = {"response": "Done.", "kind": "powershell", "intent": "LIST_FILES"}
        strategy, text = classify_display(
            result, collected_output="x.txt", exit_code=0, timed_out=False,
        )
        assert strategy == DisplayStrategy.INFO
        assert text == "x.txt"


class TestClassifyDisplayOtherKinds:
    def test_chat_kind_is_info_so_it_does_not_auto_vanish(self):
        # Includes clarifying questions and destructive-command
        # confirmation prompts -- these must not disappear on the old
        # 3-second auto-fade before the person reads them.
        result = {"response": "Did you mean the Downloads folder or Desktop?", "kind": "chat"}
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.INFO
        assert text == "Did you mean the Downloads folder or Desktop?"

    def test_schedule_kind_is_done(self):
        result = {
            "response": "Done. Scheduled as sch_1: \"lock the computer\" in 10 minutes.",
            "kind": "schedule", "intent": "SCHEDULE_COMMAND",
        }
        strategy, _ = classify_display(result)
        assert strategy == DisplayStrategy.DONE

    def test_timer_kind_is_done(self):
        result = {"response": "Done. Timer set as t_1, in 5 minutes.", "kind": "timer", "intent": "SET_TIMER"}
        strategy, _ = classify_display(result)
        assert strategy == DisplayStrategy.DONE

    def test_generate_kind_is_info_so_content_is_actually_shown(self):
        # Per STATUS.md's own BETA 0.3.49 entry: main_widget.py doesn't
        # wire GENERATE_FILE's live token stream, so the generated
        # content otherwise has nowhere to be seen at all except here.
        result = {"response": "def hello():\n    print('hi')", "kind": "generate", "intent": "GENERATE_FILE"}
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.INFO
        assert "def hello" in text

    def test_app_control_kind_defaults_done_when_unmapped(self):
        result = {"response": "Clicked 'Save'.", "kind": "app_control", "intent": "CLICK_ELEMENT"}
        strategy, _ = classify_display(result)
        assert strategy == DisplayStrategy.DONE

    def test_app_control_list_installed_apps_is_info(self):
        result = {
            "response": "Chrome, Notepad, Calculator, Spotify",
            "kind": "app_control", "intent": "LIST_INSTALLED_APPS",
        }
        strategy, _ = classify_display(result)
        assert strategy == DisplayStrategy.INFO


class TestClassifyDisplayEdgeCases:
    def test_none_result_is_error(self):
        strategy, text = classify_display(None)
        assert strategy == DisplayStrategy.ERROR

    def test_empty_dict_is_error(self):
        strategy, text = classify_display({})
        assert strategy == DisplayStrategy.ERROR

    def test_bare_error_key_with_no_response_is_error(self):
        result = {"error": "Can't reach Ollama — is it running on localhost:11434?"}
        strategy, text = classify_display(result)
        assert strategy == DisplayStrategy.ERROR
        assert "Ollama" in text

    def test_unknown_kind_falls_back_via_intent_map(self):
        result = {"response": "some text", "kind": "some_future_kind", "intent": "GET_TIME"}
        strategy, _ = classify_display(result)
        assert strategy == DisplayStrategy.INFO
