"""
test_open_cascade_integration.py -- proves the reported bug ("asked it to
open apps last time it tried to open folder") is fixed end to end, by
running it through WindowsAIAssistant._process_single_request() itself
with graph classification forced to reproduce the exact old misfire
(OPEN_ITEM instead of LAUNCH_APP) and app existence mocked -- confirms the
cascade OVERRIDES a wrong classification rather than just working in
isolation.

_dispatch() itself is mocked out (it shells to real PowerShell/pywinauto,
Windows-only) -- this test is about the ROUTING decision, not actual
command execution, which still needs a live Windows run (see the PR
notes/README).
"""

from unittest.mock import patch

import pytest

import orchestrator


@pytest.fixture
def assistant():
    a = orchestrator.WindowsAIAssistant()
    yield a
    a.shutdown()


def _run(assistant, prompt, app_exists, classified_intent):
    """Runs one message through the real pipeline with _dispatch mocked
    out (captures what it WOULD have dispatched) and graph classification
    forced to a specific (possibly wrong) guess, reproducing exactly what
    the old single one-shot classifier used to hand off.

    BETA 0.3.7 fix: also mocks assistant.router.classify() (the real
    Ollama HTTP call) unconditionally now. It used to only be mocked via
    the graph_router-is-None branch, which meant on any machine where
    self.graph_router IS constructed (the normal case) but classify()
    naturally falls through to the LLM fallback for some other reason,
    a REAL network call to localhost:11434 could fire. On a machine
    without Ollama running this accidentally still passed (the request
    just failed and fell through to the documented fail-open graph
    fallback) -- but a live Windows run with Ollama actually running
    caught the real model answering unpredictably (once with
    GENERATE_FILE for an explicit "open 'SomeApp'" case that should
    never have reached the LLM path's classify() at all). Mocking this
    directly makes the test deterministic regardless of what's running
    on the machine executing it."""
    captured = {}

    def fake_dispatch(intent, user_prompt, slots, *a, **kw):
        captured["intent"] = intent
        captured["slots"] = slots
        return {"thinking": "", "response": "ok", "kind": "command"}

    assistant._dispatch = fake_dispatch

    patches = [
        patch.object(assistant.app_controller, "app_exists", side_effect=app_exists),
        patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}),
    ]
    if assistant.graph_router is not None:
        patches.append(patch.object(assistant.graph_router, "classify", return_value={"intent": classified_intent}))
    else:
        patches.append(patch.object(assistant, "_run_thinking", return_value=""))

    with patches[0], patches[1], patches[2]:
        result = assistant._process_single_request(prompt, lambda x: None, lambda x: None)
    return captured, result


class TestReportedBugIsFixed:
    def test_open_app_misclassified_as_open_item_gets_corrected(self, assistant):
        # Reproduces the EXACT bug: graph says OPEN_ITEM, but "steam" is a
        # real installed app. Old behavior: dispatched OPEN_ITEM, asked
        # "which file or folder?" New behavior: cascade overrides to
        # LAUNCH_APP because the app actually exists.
        captured, result = _run(
            assistant, "open steam",
            app_exists=lambda n: n == "steam",
            classified_intent="OPEN_ITEM",
        )
        assert captured.get("intent") == "LAUNCH_APP"
        assert captured.get("slots", {}).get("app_name") == "steam"

    def test_open_file_misclassified_as_launch_app_gets_corrected(self, assistant):
        # The reverse misfire: graph guesses LAUNCH_APP for something
        # that's actually a real file, no matching app exists.
        with patch("extractor.os.path.exists", return_value=True):
            captured, result = _run(
                assistant, "open my resume",
                app_exists=lambda n: False,
                classified_intent="LAUNCH_APP",
            )
        assert captured.get("intent") == "OPEN_ITEM"
        assert "path" in captured.get("slots", {})

    def test_neither_exists_asks_instead_of_dispatching_the_wrong_guess(self, assistant):
        with patch("extractor.os.path.exists", return_value=False), \
             patch.object(assistant, "_run_thinking", return_value="Hmm, I can't find that."):
            captured, result = _run(
                assistant, "open totally_made_up_thing_xyz",
                app_exists=lambda n: False,
                classified_intent="OPEN_ITEM",
            )
        # Never reached _dispatch at all -- asked instead.
        assert captured == {}
        assert result["kind"] == "chat"

    def test_explicit_app_quote_bypasses_cascade_and_dispatches_launch_app(self, assistant):
        # The '' convention is an explicit user override -- must reach
        # _dispatch as LAUNCH_APP even if app_exists_fn would say no
        # (matches resolve_open_target's own unit tests; this just proves
        # the orchestrator wiring respects it too).
        captured, result = _run(
            assistant, "open 'SomeApp'",
            app_exists=lambda n: False,
            classified_intent="LAUNCH_APP",
        )
        assert captured.get("intent") == "LAUNCH_APP"
        assert captured.get("slots", {}).get("app_name") == "SomeApp"
