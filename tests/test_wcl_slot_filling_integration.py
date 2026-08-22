"""
test_wcl_slot_filling_integration.py -- proves the new single-variable WCL
slot-filler (extractor.py's _extract_wcl_slots, wired in via
orchestrator.py's registration block) actually reaches _dispatch() with the
right intent/template/slots end to end, and that the safety gate (only
danger_level == "safe" single-variable commands get this treatment; every
other shape still falls through untouched) actually holds.

Same approach as test_open_cascade_integration.py: assistant._dispatch is
mocked out (it shells to real PowerShell, Windows-only) so this test is
about the ROUTING/SLOT-FILLING decision, not real command execution --
still needs a live Windows run for that (see STATUS.md).
"""

from unittest.mock import patch

import pytest

import orchestrator


class FakeWclResolver:
    """Stands in for wcl_resolver.WCLResolver -- returns a fixed RESOLVED
    result regardless of query text, so the test controls exactly what
    orchestrator.py's registration block has to decide against."""

    def __init__(self, result):
        self._result = result

    def resolve(self, query):
        return self._result


@pytest.fixture
def assistant():
    a = orchestrator.WindowsAIAssistant()
    a.graph_router.close()
    a.graph_router = None  # force a graph miss -> straight to wcl_resolver
    real_wcl_resolver = a.wcl_resolver
    yield a
    # Some tests in this file swap a.wcl_resolver for a fake with no
    # close() -- always close the real one we created, not whatever the
    # test left behind.
    real_wcl_resolver.close()


def _run(assistant, prompt, wcl_result):
    captured = {}

    def fake_dispatch(intent, user_prompt, slots, *a, **kw):
        captured["intent"] = intent
        captured["slots"] = slots
        return {"thinking": "", "response": "ok", "kind": "command"}

    assistant._dispatch = fake_dispatch
    assistant.wcl_resolver = FakeWclResolver(wcl_result)

    with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
        assistant._process_single_request(prompt, lambda x: None, lambda x: None)
    return captured


class TestSafeSingleVariableCommandsAutoDispatch:
    def test_safe_single_variable_command_fills_and_dispatches(self, assistant):
        wcl_result = {
            "status": "RESOLVED",
            "tier": 3,
            "command": "Start-Vm",
            "syntax": "Start-VM -Name '{vm_name}'",
            "danger_level": "safe",
            "requires_admin": True,
            "requires_confirmation": False,
        }
        captured = _run(assistant, "start the vm named TestVM", wcl_result)
        assert captured["intent"] == "WCL_Start-Vm"
        assert captured["slots"] == {"vm_name": "TestVM"}

    def test_registered_template_and_slots_match_the_resolved_command(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Get-Something",
            "syntax": "Get-Something -Name '{name}'", "danger_level": "safe",
            "requires_admin": False, "requires_confirmation": False,
        }
        _run(assistant, 'get something called "widget"', wcl_result)
        meta = orchestrator.WCL_COMMANDS["WCL_Get-Something"]
        assert meta["template"] == "Get-Something -Name '{name}'"
        assert meta["slots"] == ["name"]
        assert meta["reversible"] is True


class TestPillCategorySurfacesWclTaxonomy:
    """STATUS.md's 'category taxonomy mismatch' item -- the
    windows_command_library's own 26-bucket category was stored on the
    graph but never surfaced anywhere. pill_category() is the fix: it's
    what app.py's intent pill now calls instead of a raw
    categories.INTENT_CATEGORY lookup."""

    def test_non_wcl_intent_uses_the_existing_category_map(self):
        assert orchestrator.pill_category("CHAT") == "CHAT"

    def test_intent_with_no_category_at_all_returns_empty_string(self):
        assert orchestrator.pill_category("MAKE_FOLDER") == ""

    def test_wcl_intent_surfaces_its_own_library_category(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Get-Something",
            "syntax": "Get-Something -Name '{name}'", "danger_level": "safe",
            "requires_admin": False, "requires_confirmation": False,
            "category": "disk_storage",
        }
        _run(assistant, 'get something called "widget"', wcl_result)
        assert orchestrator.pill_category("WCL_Get-Something") == "disk_storage"


class TestDangerLevelGateBlocksEverythingExceptTheNarrowSafeWindow:
    """Found a real, pre-existing bug in THIS file while adding the tests
    below: the 4 methods that used to follow this docstring had no class
    declaration of their own at all -- they were syntactically still
    inside TestPillCategorySurfacesWclTaxonomy above (pytest still ran
    them fine as methods of that class; it was a naming/organization bug,
    not a test-correctness one). Fixed by adding this class declaration.

    BETA 0.3.38 update: "safe" commands still dispatch immediately, but
    "caution"/"destructive" no longer fall all the way through to the
    LLM untouched -- they now route to a confirmation question instead
    (see TestCautionDestructiveConfirmationFlow below for that flow
    itself). The assertion these tests share, `_dispatch` was never
    called with this intent`, is still correct either way (falling
    through to the LLM and pausing for confirmation both mean "not
    dispatched yet") -- updated names/comments so that's not confused
    with "silently blocked", which is no longer what happens.
    """

    def test_destructive_single_variable_command_is_not_immediately_dispatched(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Remove-Something",
            "syntax": "Remove-Something -Name '{name}'", "danger_level": "destructive",
            "requires_admin": False, "requires_confirmation": True,
        }
        captured = _run(assistant, 'remove something called "widget"', wcl_result)
        assert "intent" not in captured
        assert assistant._pending_confirmation is not None

    def test_caution_single_variable_command_is_not_immediately_dispatched(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Set-Something",
            "syntax": "Set-Something -Value '{value}'", "danger_level": "caution",
            "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, 'set it to "5"', wcl_result)
        assert "intent" not in captured
        assert assistant._pending_confirmation is not None

    def test_safe_two_variable_command_now_auto_dispatches(self, assistant):
        # BETA 0.3.36/0.3.37: 2-variable "safe" commands are now
        # correctly dispatchable -- made safe to extend ONLY once
        # _ensure_quoted_placeholders() closed the injection gap in the
        # same session (see the dedicated quoting-fix test class below).
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Copy-Something",
            "syntax": "Copy-Something -Source '{source}' -Destination '{destination}'",
            "danger_level": "safe", "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, 'copy "a.txt" to "b.txt"', wcl_result)
        assert captured.get("intent") == "WCL_Copy-Something"
        assert captured["slots"]["source"].endswith("a.txt")
        assert captured["slots"]["destination"].endswith("b.txt")

    def test_safe_three_variable_command_is_still_not_auto_dispatched(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Do-ThreeThings",
            "syntax": "Do-ThreeThings -One '{one}' -Two '{two}' -Three '{three}'",
            "danger_level": "safe", "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, 'do "a" "b" "c"', wcl_result)
        assert "intent" not in captured

    def test_extraction_miss_falls_through_to_missing_slot_question_not_a_crash(self, assistant):
        # Resolved, safe, single-variable -- but the message genuinely has
        # no extractable value. Must ask, never dispatch with a garbage
        # value or raise.
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Start-Vm",
            "syntax": "Start-VM -Name '{vm_name}'", "danger_level": "safe",
            "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, "start a vm please", wcl_result)
        assert "intent" not in captured
        assert assistant._pending is not None
        assert assistant._pending["intent"] == "WCL_Start-Vm"

    # ─── BETA 0.3.35: the actual critical bug this session found ──────────
    #
    # Every test above covers the single/multi-variable cases. NONE of
    # them ever exercised a ZERO-variable command with a non-"safe"
    # danger_level -- which is exactly the gap that let this ship: the
    # zero-variable branch ("not var_names") had no danger_level check at
    # all, unlike the single-variable branch right next to it. Confirmed
    # live before the fix: "run diskpart" (destructive, zero variables)
    # resolved RESOLVED, missed Tier A entirely (so
    # _check_destructive_shadow() never even ran -- it only fires when
    # Tier A ALSO produced a classification to compare against), and
    # reached _dispatch() with literally no danger_level check anywhere
    # else in the file. Fixed by requiring danger_level == "safe" for the
    # zero-variable case too.

    def test_destructive_zero_variable_command_is_not_immediately_dispatched(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "diskpart",
            "syntax": "diskpart", "danger_level": "destructive",
            "requires_admin": True, "requires_confirmation": True,
        }
        captured = _run(assistant, "run diskpart", wcl_result)
        assert "intent" not in captured
        assert assistant._pending_confirmation is not None

    def test_caution_zero_variable_command_is_not_immediately_dispatched(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "some-caution-tool",
            "syntax": "some-caution-tool", "danger_level": "caution",
            "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, "run some caution tool", wcl_result)
        assert "intent" not in captured
        assert assistant._pending_confirmation is not None

    def test_safe_zero_variable_command_still_auto_dispatches(self, assistant):
        # Regression guard: fixing the danger_level gap above must not
        # accidentally block the legitimate, always-intended case --
        # genuinely safe, zero-variable commands (e.g. "what time is it"
        # -equivalent WCL entries) must keep working exactly as before.
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Get-Something-Safe",
            "syntax": "Get-Something-Safe", "danger_level": "safe",
            "requires_admin": False, "requires_confirmation": False,
        }
        captured = _run(assistant, "get something safe", wcl_result)
        assert captured.get("intent") == "WCL_Get-Something-Safe"
        assert captured.get("slots") == {}


# ─── BETA 0.3.15: end-to-end against the REAL resolver, not FakeWclResolver ─
#
# Every test above uses FakeWclResolver, correctly, to isolate the routing/
# gating decision from resolver behavior. But that's exactly the seam that
# let the trailing-value bug ship undetected: nothing in this file ever
# exercised whether a REAL sentence with a real value actually produces a
# RESOLVED result with a fillable slot in the first place. This class uses
# the real, live WCLResolver against the real shipped graph.

class TestRealResolverEndToEnd:
    def test_real_sentence_with_trailing_value_dispatches_correctly(self):
        # The exact bug found live: "view more notes.txt" against the
        # REAL resolver (not a fake) must produce a clean, correct
        # PowerShell command -- not garbled with the alias's own words,
        # not a total miss.
        assistant = orchestrator.WindowsAIAssistant()
        assistant.graph_router.close()
        assistant.graph_router = None  # force a graph miss -> straight to wcl_resolver

        captured = {}

        def fake_dispatch(intent, user_prompt, slots, *a, **kw):
            captured["intent"] = intent
            captured["slots"] = slots
            return {"thinking": "", "response": "ok", "kind": "command"}

        assistant._dispatch = fake_dispatch
        with patch.object(assistant.router, "classify", return_value={"error": "not used"}):
            assistant._process_single_request("view more notes.txt", lambda x: None, lambda x: None)

        assert captured.get("intent") == "WCL_more"
        assert captured["slots"]["file_path"].endswith("notes.txt")
        assert "view" not in captured["slots"]["file_path"].lower()
        assistant.shutdown()


# ─── BETA 0.3.37: CRITICAL, systemic command-injection fix ────────────────
#
# Found while scoping the 2-variable extension above: 297 of 298
# currently-eligible "safe" single-variable WCL syntax templates have a
# completely UNQUOTED {var} placeholder (e.g. "Get-Content -Path {path}",
# "Start-Job -ScriptBlock {script_block}") -- _escape_ps_slot()'s single-
# quote-doubling only protects a value if the TEMPLATE ITSELF already
# wraps the placeholder in matching quotes, which is true for TOKI's own
# 62 hand-written intents but false for nearly the entire WCL-sourced
# set. Combined with _looks_like_real_name() doing zero character-level
# filtering (no check for ';', backticks, '$(...)'), an ordinary-looking
# value could have broken out of the intended single argument and run as
# a SEPARATE PowerShell statement with this app's own privileges. These
# tests call the REAL _dispatch() (not a mock) and inspect the actual
# command string it builds -- the mocked-_dispatch tests elsewhere in
# this file never would have caught this, since they never look at what
# _dispatch() itself actually produces.

class TestDispatchNeverProducesAnUnquotedInjectableCommand:
    @pytest.fixture
    def assistant_with_test_command(self):
        a = orchestrator.WindowsAIAssistant()
        orchestrator.WCL_COMMANDS["WCL_TestInjection"] = {
            "description": "test", "kind": "powershell",
            "template": "Get-Content -Path {path}",
            "slots": ["path"], "reversible": True,
        }
        yield a
        del orchestrator.WCL_COMMANDS["WCL_TestInjection"]
        a.shutdown()

    def test_semicolon_statement_injection_is_fully_contained(self, assistant_with_test_command):
        malicious = "pwned.txt; Remove-Item -Recurse -Force D:\\"
        result = assistant_with_test_command._dispatch(
            "WCL_TestInjection", "test", {"path": malicious}, "",
            lambda x: None, lambda x: None, None, None, None,
        )
        command = result["command"]
        # The ENTIRE malicious string must be inside ONE pair of single
        # quotes -- confirmed by checking it's not possible to find an
        # unquoted ';' (i.e. the whole thing parses as one literal arg).
        assert command == "Get-Content -Path 'pwned.txt; Remove-Item -Recurse -Force D:\\'"

    def test_single_quote_breakout_is_doubled_not_left_raw(self, assistant_with_test_command):
        malicious = "a' ; Remove-Item -Recurse -Force D:\\ ; 'b"
        result = assistant_with_test_command._dispatch(
            "WCL_TestInjection", "test", {"path": malicious}, "",
            lambda x: None, lambda x: None, None, None, None,
        )
        # PowerShell's escape for an embedded ' inside '...' is '' --
        # every ' in the malicious value must have become ''.
        assert "''" in result["command"]
        assert result["command"].count("'") % 2 == 0  # always balanced

    def test_unquoted_template_gets_wrapped_by_ensure_quoted_placeholders(self):
        from orchestrator import _ensure_quoted_placeholders
        assert _ensure_quoted_placeholders("subst {drive_letter} {path}") == \
            "subst '{drive_letter}' '{path}'"

    def test_already_quoted_template_is_left_alone(self):
        from orchestrator import _ensure_quoted_placeholders
        template = "New-Item -Path '{path}' -ItemType 'Directory'"
        assert _ensure_quoted_placeholders(template) == template

    def test_partially_quoted_template_with_literal_chars_is_not_broken(self):
        # '*{query}*' -- the placeholder isn't immediately adjacent to
        # the quote characters, but IS inside the single-quoted span.
        # Must be left alone (re-wrapping would produce invalid syntax
        # like '*''{query}''*').
        from orchestrator import _ensure_quoted_placeholders
        template = "Get-ChildItem -Filter '*{query}*'"
        assert _ensure_quoted_placeholders(template) == template

    def test_double_quoted_context_gets_dollar_sign_escaped_too(self, assistant_with_test_command):
        orchestrator.WCL_COMMANDS["WCL_TestInjection2"] = {
            "description": "test", "kind": "powershell",
            "template": 'eventcreate /D "{message}"',
            "slots": ["message"], "reversible": True,
        }
        malicious = "$(Remove-Item -Recurse -Force D:\\)"
        result = assistant_with_test_command._dispatch(
            "WCL_TestInjection2", "test", {"message": malicious}, "",
            lambda x: None, lambda x: None, None, None, None,
        )
        # The dollar sign must be preceded by a backtick (PowerShell's
        # own "literal, not an expansion" escape) -- checking for a raw,
        # UN-escaped "$(" is the wrong test (the escaped form `$( still
        # contains the substring "$(" -- the backtick prefix is what
        # actually matters, not the substring's absence).
        assert "`$(Remove-Item" in result["command"]
        del orchestrator.WCL_COMMANDS["WCL_TestInjection2"]


# ─── BETA 0.3.38: caution/destructive commands get a confirmation step ────
#
# Product decision (explicit, in chat): rather than leaving
# caution/destructive WCL commands permanently unreachable (BETA 0.3.35-
# 0.3.37's posture), a resolved command with every slot filled now shows
# exactly what it would run and pauses for a plain Enter/short confirm
# word before actually dispatching. Deliberately minimal UI surface --
# "kind": "chat", same rendering path as any other text response, no new
# UI code needed.

class TestCautionDestructiveConfirmationFlow:
    def test_asks_with_the_exact_command_shown_not_a_vague_warning(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Remove-Something",
            "syntax": "Remove-Something -Name '{name}'", "danger_level": "destructive",
            "requires_admin": False, "requires_confirmation": True,
        }
        assistant.wcl_resolver = FakeWclResolver(wcl_result)
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            result = assistant._process_single_request(
                'remove something called "widget"', lambda x: None, lambda x: None,
            )
        assert result["kind"] == "chat"
        # The PREVIEW shown must be built by the exact same code that will
        # later actually run it (_build_powershell_command) -- checking
        # for the real, fully-quoted command string, not just a generic
        # "are you sure" message.
        assert "Remove-Something -Name 'widget'" in result["response"]
        assert assistant._pending_confirmation is not None
        assert assistant._pending_confirmation["intent"] == "WCL_Remove-Something"

    @pytest.mark.parametrize("reply", ["", "y", "yes", "Yes", "  ", "confirm", "ok", "run it"])
    def test_confirm_words_all_dispatch_with_the_original_slots(self, assistant, reply):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Remove-Something",
            "syntax": "Remove-Something -Name '{name}'", "danger_level": "destructive",
            "requires_admin": False, "requires_confirmation": True,
        }
        assistant.wcl_resolver = FakeWclResolver(wcl_result)
        captured = {}

        def fake_dispatch(intent, user_prompt, slots, *a, **kw):
            captured["intent"] = intent
            captured["slots"] = slots
            return {"thinking": "", "response": "ok", "kind": "command"}

        assistant._dispatch = fake_dispatch
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            assistant._process_single_request(
                'remove something called "widget"', lambda x: None, lambda x: None,
            )
        assert assistant._pending_confirmation is not None

        # The confirming turn -- process_request (not
        # _process_single_request) is where the self._pending_confirmation
        # check at the top of the turn actually lives.
        assistant.process_request(reply, lambda x: None, lambda x: None)
        assert captured.get("intent") == "WCL_Remove-Something"
        assert captured["slots"]["name"] == "widget"
        assert assistant._pending_confirmation is None

    def test_anything_else_cancels_without_dispatching_and_clears_pending_state(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Remove-Something",
            "syntax": "Remove-Something -Name '{name}'", "danger_level": "destructive",
            "requires_admin": False, "requires_confirmation": True,
        }
        assistant.wcl_resolver = FakeWclResolver(wcl_result)
        captured = {}

        def fake_dispatch(intent, user_prompt, slots, *a, **kw):
            captured["intent"] = intent
            return {"thinking": "", "response": "ok", "kind": "command"}

        assistant._dispatch = fake_dispatch
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            assistant._process_single_request(
                'remove something called "widget"', lambda x: None, lambda x: None,
            )
        assert assistant._pending_confirmation is not None

        # A genuinely different reply cancels -- swap the resolver to a
        # miss for this turn so the recursive re-processing lands on a
        # real "nothing matched" outcome, same as a real UNRESOLVED query
        # would (FakeWclResolver otherwise returns the SAME destructive
        # command regardless of what text it's given, which would make
        # this test accidentally re-trigger a second confirmation instead
        # of a genuine cancel).
        assistant.wcl_resolver = FakeWclResolver({"status": "UNRESOLVED"})
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            assistant.process_request("no thanks", lambda x: None, lambda x: None)

        assert "intent" not in captured
        assert assistant._pending_confirmation is None

    def test_slot_extraction_miss_still_asks_a_missing_slot_question_first(self, assistant):
        # A destructive command whose value genuinely can't be extracted
        # must still ask a NORMAL missing-slot question (self._pending),
        # not skip straight to a confirmation for a value that doesn't
        # exist yet, and not silently fall through to the LLM either.
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Remove-Something",
            "syntax": "Remove-Something -Name '{name}'", "danger_level": "destructive",
            "requires_admin": False, "requires_confirmation": True,
        }
        assistant.wcl_resolver = FakeWclResolver(wcl_result)
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            result = assistant._process_single_request(
                "remove something", lambda x: None, lambda x: None,
            )
        assert assistant._pending_confirmation is None
        assert assistant._pending is not None
        assert assistant._pending["intent"] == "WCL_Remove-Something"

    def test_safe_command_is_completely_unaffected_no_confirmation_step(self, assistant):
        wcl_result = {
            "status": "RESOLVED", "tier": 1, "command": "Get-Something",
            "syntax": "Get-Something -Name '{name}'", "danger_level": "safe",
            "requires_admin": False, "requires_confirmation": False,
        }
        assistant.wcl_resolver = FakeWclResolver(wcl_result)
        captured = {}

        def fake_dispatch(intent, user_prompt, slots, *a, **kw):
            captured["intent"] = intent
            return {"thinking": "", "response": "ok", "kind": "command"}

        assistant._dispatch = fake_dispatch
        with patch.object(assistant.router, "classify", return_value={"error": "not used in this test"}):
            assistant._process_single_request(
                'get something called "widget"', lambda x: None, lambda x: None,
            )
        assert captured.get("intent") == "WCL_Get-Something"
        assert assistant._pending_confirmation is None
