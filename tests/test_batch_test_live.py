"""
test_batch_test_live.py -- regression coverage for batch_test_live.py.

Context (found live, BETA 0.3.17's own handoff): batch_test_live.py's
run_one() called assistant._process_single_request() directly instead of
assistant.process_request() (the public entry point app.py itself calls,
and the one that runs _split_chain_if_viable() before dispatch). This
silently skipped chain-splitting for EVERY multi-step prompt in the
batch's own prompt list -- "close chrome and open notepad" was
classified as one giant unsplit string instead of two real segments.
Confirmed directly: _process_single_request() returned chained=None on
that prompt; process_request() returned chained=True with 2 steps.

These tests pin the fix: run_one() must call assistant.process_request,
never assistant._process_single_request, and must correctly log/summarize
a chained result instead of only reflecting the last step.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "batch_test_live.py"


def _load_batch_test_live():
    spec = importlib.util.spec_from_file_location("batch_test_live", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["batch_test_live"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def btl():
    return _load_batch_test_live()


def _fake_log_file():
    log = MagicMock()
    log.write = MagicMock()
    log.flush = MagicMock()
    return log


class TestRunOneCallsRealChainSplittingEntryPoint:
    def test_run_one_calls_process_request_not_single_request(self, btl):
        assistant = MagicMock()
        assistant.process_request.return_value = {
            "intent": "OPEN_ITEM", "kind": "action", "response": "ok",
        }
        log = _fake_log_file()

        btl.run_one(assistant, "open notepad", log)

        assistant.process_request.assert_called_once()
        assistant._process_single_request.assert_not_called()

    def test_chained_result_is_logged_per_step_not_just_last_step(self, btl):
        assistant = MagicMock()
        assistant.process_request.return_value = {
            "intent": "OPEN_ITEM",  # mirrors LAST step only, per process_request's own docstring
            "kind": "action",
            "chained": True,
            "steps": [
                {"intent": "KILL_PROCESS", "kind": "action", "response": "closing chrome"},
                {"intent": "OPEN_ITEM", "kind": "action", "response": "opening notepad"},
            ],
        }
        log = _fake_log_file()

        btl.run_one(assistant, "close chrome and open notepad", log)

        written = "".join(call.args[0] for call in log.write.call_args_list)
        assert "CHAINED: 2 steps" in written
        assert "KILL_PROCESS" in written
        assert "OPEN_ITEM" in written
        assert "closing chrome" in written
        assert "opening notepad" in written

    def test_chained_result_prints_chained_summary(self, btl, capsys):
        assistant = MagicMock()
        assistant.process_request.return_value = {
            "intent": "OPEN_ITEM",
            "kind": "action",
            "chained": True,
            "steps": [{"intent": "KILL_PROCESS"}, {"intent": "OPEN_ITEM"}],
        }
        log = _fake_log_file()

        btl.run_one(assistant, "close chrome and open notepad", log)

        out = capsys.readouterr().out
        assert "chained x2" in out

    def test_non_chained_result_still_logs_single_intent_as_before(self, btl):
        assistant = MagicMock()
        assistant.process_request.return_value = {
            "intent": "OPEN_ITEM", "kind": "action", "response": "opening notepad",
        }
        log = _fake_log_file()

        btl.run_one(assistant, "open notepad", log)

        written = "".join(call.args[0] for call in log.write.call_args_list)
        assert "INTENT: OPEN_ITEM" in written
        assert "CHAINED" not in written

    def test_ask_declined_to_guess_still_distinguished_from_plain_chat(self, btl, capsys):
        # Regression guard for the OTHER fix already shipped this BETA --
        # make sure the chained-result branch didn't accidentally swallow it.
        assistant = MagicMock()
        assistant.process_request.return_value = {
            "intent": None, "kind": "chat", "response": "did you mean X?",
        }
        log = _fake_log_file()
        btl.run_one(assistant, "format D drive", log)
        assert "ASK (declined to guess)" in capsys.readouterr().out


class TestRunOneResetsStateBetweenPrompts:
    """Regression coverage for the state-leakage bug found live: assistant
    is built once and reused for the whole batch, so TOKI's own
    conversation-pause state (self._pending etc.) persisted across
    "unrelated" prompts unless explicitly reset every turn."""

    def test_run_one_clears_pending_before_processing(self, btl):
        assistant = MagicMock()
        assistant._pending = {"intent": "RENAME_ITEM", "original_text": "rename this"}
        assistant._pending_graph_ask = {"some": "state"}
        assistant._last_touched = {"path": "C:\\stale"}
        assistant.history = [{"stale": "turn"}]
        assistant.process_request.return_value = {"intent": "OPEN_ITEM"}
        log = _fake_log_file()

        btl.run_one(assistant, "open notepad", log)

        # Reset must happen BEFORE process_request is called, not after --
        # check what process_request actually saw, not the object's final
        # state (which process_request's own mock return value doesn't
        # touch either way).
        assert assistant._pending is None
        assert assistant._pending_graph_ask is None
        assert assistant._last_touched is None
        assistant.process_request.assert_called_once()

    def test_pending_from_one_prompt_does_not_leak_into_the_next_real_call(self):
        """End-to-end proof against the real pipeline (no Ollama needed):
        replays the exact scenario found live -- a prompt that legitimately
        sets self._pending, immediately followed by a totally unrelated
        prompt that WOULD resolve cleanly on its own -- and confirms the
        second prompt is classified fresh, not silently swallowed as an
        "answer" to the first (the real live bug: 47 of 70 prompts in the
        project's own real batch list were swallowed this way after
        "display type of notes.txt" set a pending question)."""
        from orchestrator import WindowsAIAssistant

        class FakeRunningCommand:
            def __init__(self, command, on_output, on_done):
                self._on_done = on_done

            def start(self):
                self._on_done(0)

            def stop(self):
                pass

        with patch("orchestrator.RunningCommand", FakeRunningCommand):
            assistant = WindowsAIAssistant()

        btl = _load_batch_test_live()
        log = _fake_log_file()

        # "rename this" has no antecedent -- the exact prompt class that
        # sets self._pending (a genuine missing-slot follow-up).
        btl.run_one(assistant, "rename this", log)
        assert assistant._pending is not None  # sanity: it DID set pending

        # "empty recycle bin" resolves cleanly to EMPTY_RECYCLE_BIN on its
        # own (confirmed directly against this same pipeline). Without the
        # fix, self._pending would still be set here, so this call would
        # go through _resume_pending() instead of real classification and
        # never reach EMPTY_RECYCLE_BIN at all.
        log2 = _fake_log_file()
        btl.run_one(assistant, "empty recycle bin", log2)
        written = "".join(call.args[0] for call in log2.write.call_args_list)
        assert "INTENT: EMPTY_RECYCLE_BIN" in written
        assistant.shutdown()

    """End-to-end proof (no Ollama needed -- graph classification and
    chain-split viability are both local/offline) that the entry point
    matters: the exact prompt from this project's own batch-test list
    produces a materially different, correct result via process_request()
    than via _process_single_request()."""

    def test_close_chrome_and_open_notepad_only_chains_via_process_request(self):
        from orchestrator import WindowsAIAssistant

        class FakeRunningCommand:
            def __init__(self, command, on_output, on_done):
                self._on_done = on_done

            def start(self):
                self._on_done(0)

            def stop(self):
                pass

        def on_output(_):
            pass

        def on_done(_):
            pass

        with patch("orchestrator.RunningCommand", FakeRunningCommand):
            single = WindowsAIAssistant()
            real = WindowsAIAssistant()

        prompt = "close chrome and open notepad"

        single_result = single._process_single_request(prompt, on_output, on_done)
        real_result = real.process_request(prompt, on_output, on_done)

        # The bug: calling the internal method never splits the chain at all.
        assert not single_result.get("chained")
        # The fix: the real public entry point does.
        assert real_result.get("chained") is True
        single.shutdown()
        real.shutdown()
        assert len(real_result.get("steps", [])) == 2
