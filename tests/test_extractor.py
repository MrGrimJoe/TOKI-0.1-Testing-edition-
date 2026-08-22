"""
test_extractor.py -- pins every slot-extraction case that's been manually
verified (good or bad) across this project's own STATUS.md history, plus
the 4 bugs fixed in this pass, so none of them can silently regress again
without a test failing. Pure Python, no Ollama/Windows/kuzu needed -- runs
anywhere, including CI.

Convention: each test names the STATUS.md entry (or session) it pins, so a
future failure points straight back to the context that explains why the
behavior matters.
"""

import pytest
from extractor import (
    extract_slots, resolve_missing_slot, _strip_exe_extension,
    extract_open_target_name, is_anaphoric_reference, resolve_anaphoric_target,
    canned_reply, looks_like_start_seeing, looks_like_stop_seeing,
    looks_like_start_listening, looks_like_stop_listening,
    looks_like_ambiguous_start_recording, looks_like_ambiguous_stop_recording,
    looks_like_function_creation,
)


class TestLooksLikeFunctionCreation:
    """BETA 0.3.56: "function" routes straight to GENERATE_FILE, bypassing
    Tier A's graph scoring -- but "function" can also be a real, literal
    filename ("function.py"), so this must NOT fire for a plain
    file-target request that merely happens to reference something named
    "function". See extractor.py's own docstring above
    looks_like_function_creation() for the full reasoning."""

    @pytest.mark.parametrize("text", [
        "create a function called calculator",
        "write a function that does this",
        "can you write me a function for this",
        "generate a function to sort a list",
        "make a function called add_numbers",
        "build me a function that reverses a string",
        "code up a function for this",
    ])
    def test_creation_phrasings_match(self, text):
        assert looks_like_function_creation(text) is True

    @pytest.mark.parametrize("text", [
        "open function.py",
        "delete the file called function",
        "read function.txt",
        'open "function"',
        "rename function.py to helper.py",
        "remove function.py from my desktop",
        "show me function.py",
    ])
    def test_existing_file_named_function_does_not_match(self, text):
        assert looks_like_function_creation(text) is False

    def test_creation_verb_wins_even_with_an_extension_present(self):
        # A real creation verb always overrides the existing-file signal --
        # "write a function and save it as function.py" is still
        # unambiguously a generation request.
        assert looks_like_function_creation(
            "write a function and save it as function.py"
        ) is True

    def test_no_function_word_at_all_does_not_match(self):
        assert looks_like_function_creation("open notepad") is False
        assert looks_like_function_creation("make a folder called Homework") is False


class TestLooksLikeFunctionCreationFolderFileNamedFunctionBugfix:
    """Regression test for a real live bug found while re-verifying BETA
    0.3.56, not caught by that session's own test suite: the header
    comment on _GENERATE_FUNCTION_RE claims "doesn't touch folder/file/
    script/program at all", but the code never actually enforced that --
    a creation verb (write/create/make/build/generate/code) "always wins"
    per the docstring, and "make a folder called function" ALSO contains
    a creation verb ("make"), so it was stolen into GENERATE_FILE exactly
    like the comment says can't happen. Confirmed live end-to-end via
    _process_single_request(): router.classify() was never even called,
    generate_and_save("make a folder called function") was, instead of
    MAKE_FOLDER creating a folder literally named "function". The
    pre-existing test_no_function_word_at_all_does_not_match() only
    checked "make a folder called Homework" -- which never contains the
    word "function" at all, so it could never have caught this.

    "function" as the NAME of some other explicitly-typed thing (a
    folder/file/script/program/directory) must always route normally,
    regardless of which creation verb is also present in the sentence.
    """

    @pytest.mark.parametrize("text", [
        "make a folder called function",
        "create a folder called function",
        "build a folder called function",
        "make a new folder function",
        "make a folder function",
        "add a folder named function",
        "create function folder",
        "write a script called function",
        "create a file called function",
        "make a file named function",
        "create a program called function",
        "make a directory called function",
    ])
    def test_folder_file_script_program_named_function_does_not_match(self, text):
        assert looks_like_function_creation(text) is False

    def test_live_orchestrator_routes_folder_named_function_to_make_folder_not_generate_file(self):
        """End-to-end confirmation, not just the unit-level regex check
        above: with the fix in place, "make a folder called function"
        must actually reach classify() -- graph or Ollama fallback,
        whichever resolves it -- (i.e. the looks_like_function_creation()
        pre-check in orchestrator.py must NOT short-circuit it), not get
        dispatched straight to generate_and_save().

        Historical note: when this test was first written, Tier A's
        GraphRouter (TF-IDF) missed this exact phrase, so it fell through
        to the Ollama router -- hence patching assistant.router.classify()
        and asserting it was called once. Since the component router was
        layered in front of GraphRouter (see LayeredGraphRouter in
        orchestrator.py / CHECKPOINT_MANIFEST.md), Tier A now resolves
        this phrase confidently on its own (verified directly:
        assistant.graph_router.classify("make a folder called function")
        -> {"intent": "MAKE_FOLDER"}, where plain GraphRouter alone still
        returns None) -- strictly better, since it skips the LLM round
        trip entirely. That means assistant.router.classify() (Ollama) is
        no longer necessarily on the path for this phrase, so asserting
        call count on it would be asserting an implementation detail this
        test never actually cared about. What this test has always
        actually cared about -- confirmed by its own name and docstring
        -- is the END RESULT: MAKE_FOLDER, not GENERATE_FILE. Assert that
        directly instead.
        """
        import orchestrator
        from unittest.mock import patch

        assistant = orchestrator.WindowsAIAssistant()
        try:
            with patch.object(assistant.router, "classify") as mock_classify, \
                 patch.object(assistant.generator, "generate_and_save") as mock_gen:
                mock_classify.return_value = {
                    "intent": "MAKE_FOLDER", "confidence": 0.9, "slots": {},
                }
                result = assistant._process_single_request(
                    "make a folder called function",
                    on_output=lambda l: None, on_done=lambda c: None,
                    on_thinking_token=None, on_generate_token=lambda t: None,
                    on_generate_done=lambda p, e: None,
                )
            mock_gen.assert_not_called()
            assert result.get("intent") == "MAKE_FOLDER", (
                f"expected \"make a folder called function\" to actually "
                f"dispatch as MAKE_FOLDER, got: {result}"
            )
        finally:
            assistant.shutdown()

    # Still-true positives: creation verb + "function" as the actual
    # object being created must keep working exactly as before this fix.
    @pytest.mark.parametrize("text", [
        "create a function called calculator",
        "write a function and save it as function.py",
        "make a function to sort a list",
    ])
    def test_genuine_function_creation_still_matches(self, text):
        assert looks_like_function_creation(text) is True


# ─── Bug fixes from this session ───────────────────────────────────────────

class TestExeExtensionStripping:
    """Stop-Process/Wait-Process/Get-Process -Name matches Process.ProcessName,
    which never includes the executable extension -- a process slot that
    still has .exe on it silently matches nothing. Fixed by
    _strip_exe_extension(); this pins it across all 3 affected intents."""

    @pytest.mark.parametrize("intent,slot_key,text", [
        ("KILL_PROCESS", "process", "kill notepad.exe"),
        ("WAIT_FOR_PROCESS", "process_name", "wait for chrome.exe"),
        ("FIND_PROCESS", "process_name", "find explorer.exe"),
    ])
    def test_exe_suffix_stripped(self, intent, slot_key, text):
        result = extract_slots(intent, text)
        assert result is not None
        assert not result[slot_key].lower().endswith(".exe"), (
            f"{intent} kept '.exe' in the slot -- Stop-Process/Get-Process/"
            f"Wait-Process -Name would silently match nothing"
        )

    def test_bare_process_name_unaffected(self):
        # No extension to strip -- must still work exactly as before.
        assert extract_slots("KILL_PROCESS", "kill notepad") == {"process": "notepad"}

    def test_resolve_missing_slot_also_strips_exe(self):
        # A direct follow-up answer ("notepad.exe") needs the same fix.
        assert resolve_missing_slot("KILL_PROCESS", "kill", "notepad.exe") == {"process": "notepad"}
        assert resolve_missing_slot("WAIT_FOR_PROCESS", "wait for", "winword.exe") == {"process_name": "winword"}

    def test_strip_exe_extension_helper_directly(self):
        assert _strip_exe_extension("notepad.exe") == "notepad"
        assert _strip_exe_extension("notepad") == "notepad"
        assert _strip_exe_extension("MyTool.EXE") == "MyTool"  # case-insensitive
        assert _strip_exe_extension("archive.tar.exe") == "archive.tar"  # only trailing ext
        # Never returns empty -- falls back to the original if stripping
        # would leave nothing usable.
        assert _strip_exe_extension(".exe") == ".exe"


class TestLeakedTriggerWord:
    """The trigger-word alternation only ever consumed ONE matching word, so
    a phrase using two of them back to back ("find process X", "check
    service X") left the second one glued onto the captured slot value.
    Confirmed live for KILL_PROCESS/FIND_PROCESS/WAIT_FOR_PROCESS/
    FIND_SERVICE; fixed by absorbing an optional second occurrence."""

    @pytest.mark.parametrize("intent,slot_key,text,expected", [
        ("FIND_PROCESS", "process_name", "find process explorer", "explorer"),
        ("WAIT_FOR_PROCESS", "process_name", "wait for process winword", "winword"),
        ("KILL_PROCESS", "process", "stop process notepad", "notepad"),
        ("FIND_SERVICE", "service_name", "check service printer", "printer"),
    ])
    def test_leaked_trigger_word_stripped(self, intent, slot_key, text, expected):
        result = extract_slots(intent, text)
        assert result == {slot_key: expected}, (
            f"{intent} leaked a trigger word into the slot value: {result}"
        )

    def test_single_trigger_word_phrasing_still_works(self):
        # No regression: phrasing with only ONE trigger word must be
        # unaffected by the added optional group.
        assert extract_slots("FIND_PROCESS", "find explorer") == {"process_name": "explorer"}
        assert extract_slots("FIND_SERVICE", "check the printer service") == {"service_name": "printer"}
        assert extract_slots("KILL_PROCESS", "kill notepad") == {"process": "notepad"}


# ─── KILL_PROCESS / FIND_PROCESS / WAIT_FOR_PROCESS / FIND_SERVICE: general ─

class TestProcessAndServiceSlots:
    def test_kill_process_bare(self):
        assert extract_slots("KILL_PROCESS", "kill notepad") == {"process": "notepad"}

    def test_kill_process_with_the(self):
        assert extract_slots("KILL_PROCESS", "kill the notepad process") == {"process": "notepad"}

    def test_kill_process_missing_target_returns_none(self):
        # Nothing to fill a required slot with -- caller must fall back to
        # MISSING_SLOT_QUESTIONS, never guess.
        assert extract_slots("KILL_PROCESS", "kill") is None


# ─── MAKE_FOLDER / MAKE_FILE ────────────────────────────────────────────────

class TestMakeFolderAndFile:
    def test_make_folder_called(self):
        result = extract_slots("MAKE_FOLDER", "make a folder called Homework")
        assert result is not None
        assert result["path"].endswith("Homework")

    def test_make_folder_double_quoted_literal(self):
        result = extract_slots("MAKE_FOLDER", 'make a folder "Weird Name!!"')
        assert result is not None
        assert result["path"].endswith("Weird Name!!")

    def test_make_file_gets_default_txt_extension(self):
        result = extract_slots("MAKE_FILE", "make a file called notes")
        assert result is not None
        assert result["path"].endswith("notes.txt")

    def test_make_file_respects_explicit_extension(self):
        result = extract_slots("MAKE_FILE", "make a file called notes.md")
        assert result is not None
        assert result["path"].endswith("notes.md")
        assert not result["path"].endswith("notes.md.txt")

    def test_make_folder_missing_name_returns_none(self):
        assert extract_slots("MAKE_FOLDER", "make a folder") is None


class TestNameItPhrasing:
    """"name it X" -- found via live stress-testing (BETA 0.3.62): none of
    the pre-existing _NAME_TRIGGERS ("called X"/"named X"/"titled X")
    matched this everyday phrasing, so every intent using _extract_name()
    silently got no name at all for it, even though it's a completely
    unambiguous instruction. Covers the trigger itself plus a couple of
    the real intents it feeds."""

    def test_make_folder_name_it_phrasing(self):
        result = extract_slots("MAKE_FOLDER", "make a folder and name it Homework")
        assert result is not None
        assert result["path"].endswith("Homework")

    def test_make_file_name_it_phrasing(self):
        result = extract_slots("MAKE_FILE", "make a file and name it notes")
        assert result is not None
        assert result["path"].endswith("notes.txt")

    def test_name_it_does_not_intercept_named_phrasing(self):
        # "named" contains the substring "name" -- make sure the new
        # trigger doesn't accidentally fire on it and mangle the result.
        result = extract_slots("MAKE_FOLDER", "make a folder named Projects")
        assert result is not None
        assert result["path"].endswith("Projects")

    def test_name_it_quoted_literal_still_wins(self):
        result = extract_slots("MAKE_FOLDER", 'make a folder and name it "Weird One!!"')
        assert result is not None
        assert result["path"].endswith("Weird One!!")


# ─── RENAME_ITEM / MOVE_ITEM / COPY_ITEM ────────────────────────────────────

class TestRenameMoveCopy:
    def test_rename_item(self):
        result = extract_slots("RENAME_ITEM", "rename notes.txt to notes-old.txt")
        assert result is not None
        assert result["new_name"] == "notes-old.txt"
        assert result["path"].endswith("notes.txt")

    def test_move_item(self):
        result = extract_slots("MOVE_ITEM", "move notes.txt to D:\\")
        assert result is not None
        assert result["dest"].lower().rstrip("\\") == "d:"

    def test_rename_missing_to_returns_none(self):
        assert extract_slots("RENAME_ITEM", "rename notes.txt") is None


# ─── Known, still-open bugs (documented in STATUS.md) ──────────────────────
# These are xfail, not skipped: if one starts passing, that's a signal the
# underlying issue got fixed elsewhere and the marker (and this comment)
# should be removed/updated, not left stale.

class TestKnownOpenIssues:
    def test_bare_path_extraction_no_longer_swallows_the_leading_verb(self):
        # FORMERLY xfail (STATUS.md BETA 0.3.2 -> re-confirmed open through
        # BETA 0.3.3): _extract_bare_path's greedy relative-filename regex
        # ([\w .\-]+\.\w{1,5}) has nothing to anchor it to just the
        # filename slot, so "delete the file version 2.0 from my desktop"
        # (not quoted or called/named-triggered) matched "delete the file
        # version 2.0" as if that whole phrase were the filename. This
        # was actually the SAME root cause as an even simpler, previously
        # untested case: "delete notes.txt" (no filler at all) matched
        # "delete notes.txt", not "notes.txt".
        #
        # FIXED in BETA 0.3.31 by stripping a small, curated leading
        # verb+filler prefix (_BARE_PATH_LEADING_VERB_RE) before the
        # filename regex runs, plus wiring the existing
        # _looks_like_real_name() plausibility guard into extract_slots()
        # as a final safety net for whatever survives the strip but still
        # looks like a sentence fragment rather than a real name (that
        # path asks instead of guessing, rather than dispatching on a
        # bad path).
        result = extract_slots("DELETE_ITEM", "delete the file version 2.0 from my desktop")
        assert result is not None
        assert "delete the file" not in result["path"].lower()
        assert result["path"].lower().endswith("version 2.0")

    def test_trivial_verb_plus_filename_case_now_extracts_correctly(self):
        # The simpler case that exposed the same root bug: no filler at
        # all, just "<verb> <filename>". Before this fix this ALSO
        # (silently, with no test ever catching it) resolved to a
        # nonexistent ".../delete notes.txt" path.
        result = extract_slots("DELETE_ITEM", "delete notes.txt")
        assert result is not None
        assert result["path"].lower().endswith("notes.txt")
        assert "delete" not in result["path"].lower().rsplit("\\", 1)[-1]

    def test_leading_verb_strip_only_applies_at_the_very_start(self):
        # _BARE_PATH_LEADING_VERB_RE is anchored with ^ -- "can you read
        # the quarterly report.docx for me" does NOT start with a
        # recognized verb ("can" isn't one), so nothing is stripped, the
        # whole sentence gets matched as the naive candidate, and the
        # plausibility guard (containing "read", a known sentence verb)
        # correctly rejects it -- falls through to asking, rather than
        # guessing wrong. Deliberately conservative: this is a real gap
        # (only "<verb> ..." at the very start benefits from the strip),
        # not a claim that every phrasing is now handled.
        result = extract_slots("READ_FILE", "can you read the quarterly report.docx for me")
        assert result is None

    def test_safety_net_still_rejects_a_long_descriptive_phrase_even_after_stripping(self):
        # "delete the " strips, but what's left ("presentation my boss
        # sent me last week.pptx") is still clearly a description, not a
        # filename -- the word-count half of _looks_like_real_name()
        # catches this even though it contains no recognized sentence verb.
        result = extract_slots(
            "DELETE_ITEM", "delete the presentation my boss sent me last week.pptx"
        )
        assert result is None


# ─── BETA 0.3.27: unquoted absolute paths with spaces got truncated ───────
# _BARE_PATH_RE's drive-letter branch stopped at the FIRST whitespace, so
# any unquoted absolute path with a space anywhere silently truncated to a
# nonexistent path, e.g. "D:\notes\meeting notes.txt" -> "D:\notes\meeting"
# (dropped " notes.txt"). This is the OPPOSITE failure direction from
# TestKnownOpenIssues above (that one over-captures leftward on a
# relative filename; this one under-captured rightward on an absolute
# drive path) -- fixing one must not regress the other, hence both
# classes stay in this file side by side.

class TestDrivePathWithSpaces:
    def test_extension_terminated_path_with_internal_space(self):
        result = extract_slots("READ_FILE", r"read the file at D:\notes\meeting notes.txt")
        assert result is not None
        assert result["path"] == r"D:\notes\meeting notes.txt"

    def test_delete_path_with_internal_space_and_extension(self):
        result = extract_slots("DELETE_ITEM", r"delete D:\old files\draft v2.docx")
        assert result is not None
        assert result["path"] == r"D:\old files\draft v2.docx"

    def test_extensionless_folder_path_with_space(self):
        result = extract_slots("DELETE_ITEM", r"delete the folder D:\old files")
        assert result is not None
        assert result["path"] == r"D:\old files"

    def test_extensionless_path_trims_trailing_filler(self):
        from extractor import _extract_bare_path
        assert _extract_bare_path(r"delete D:\old files please") == r"D:\old files"

    def test_relative_filename_known_open_issue_now_fixed_not_a_regression(self):
        # TestKnownOpenIssues above covers this properly now (BETA 0.3.31)
        # -- this drive-path fix (BETA 0.3.27) only ever touched the
        # drive-letter branch; the relative-filename fix came from a
        # DIFFERENT change (leading-verb stripping), not from anything in
        # this drive-path fix. This is a "still consistent" check, not a
        # claim that this fix caused it.
        result = extract_slots("DELETE_ITEM", "delete the file version 2.0 from my desktop")
        assert result is not None
        assert "delete the file" not in result["path"].lower()


# ─── Sandbox path validation (security-relevant, always worth pinning) ─────

class TestSandboxing:
    def test_path_traversal_rejected(self):
        # "../" escaping the sandbox must resolve to None, not a path
        # outside D:\ / Desktop.
        result = extract_slots("DELETE_ITEM", 'delete "../../Windows/System32/config"')
        assert result is None or result.get("path") is None

    def test_absolute_path_outside_sandbox_rejected(self):
        result = extract_slots("DELETE_ITEM", 'delete "C:\\Windows\\System32\\notepad.exe"')
        assert result is None or result.get("path") is None


# ─── Bug fixes from this session (BETA 0.3.7) ──────────────────────────────

class TestPlausibilityGuard:
    """Live repro: "now delete the folder you just made", sent as the
    answer to "Which file or folder should I delete?", was accepted as a
    literal name -- resolve_missing_slot() only stripped a few fixed
    lead-ins ("call it X"/"name it X"/...) and trusted the rest verbatim,
    so the whole sentence became the -LiteralPath handed to PowerShell
    (repro'd exactly: Get-Item failed on '...\\Desktop\\now delete the
    folder you just made'). Fixed by _looks_like_real_name()."""

    def test_whole_sentence_answer_rejected(self):
        result = resolve_missing_slot("DELETE_ITEM", "delete it", "now delete the folder you just made")
        assert result is None

    def test_bare_pronoun_answer_rejected(self):
        result = resolve_missing_slot("DELETE_ITEM", "delete it", "it")
        assert result is None

    @pytest.mark.parametrize("answer", ["python", "Homework", "notes.txt", "my resume"])
    def test_plain_name_answer_still_accepted(self, answer):
        # No regression: a real, short bare-name answer must still work.
        result = resolve_missing_slot("DELETE_ITEM", "delete it", answer)
        assert result is not None and result["path"]

    def test_call_it_x_convention_still_works(self):
        result = resolve_missing_slot("MAKE_FOLDER", "make a folder", "call it Homework")
        assert result is not None
        assert result["path"].endswith("Homework")


class TestOpenTargetPlausibilityGuard:
    """Live repro: "now open it" -- extract_open_target_name()'s filler
    stripper doesn't recognize a leading "now" (only
    okay/ok/sure/alright + modal verbs + please + i'll/i will/...), so
    nothing gets stripped and the whole sentence got run through
    app-existence + fuzzy file-matching as if it were a real short name --
    which, against a real sandbox, could resolve to a real but completely
    unrelated file/folder instead of the thing the user actually meant.
    Fixed by the same _looks_like_real_name() guard used above."""

    def test_now_open_it_extracts_nothing(self):
        assert extract_open_target_name("now open it") is None

    def test_bare_it_extracts_nothing(self):
        assert extract_open_target_name("open it") is None

    @pytest.mark.parametrize("text,expected", [
        ("open chrome", "chrome"),
        ("please open vscode", "vscode"),
        ("can you open notepad", "notepad"),
    ])
    def test_normal_open_requests_still_work(self, text, expected):
        assert extract_open_target_name(text) == expected


class TestAnaphoraResolution:
    """"delete it" / "now open it" / "the folder you just made" have
    nothing to extract a NAME from -- they're a back-reference, not a
    name, and asking extract_slots()/resolve_missing_slot() to find one
    correctly fails (see TestPlausibilityGuard/TestOpenTargetPlausibility
    Guard above). New this session: resolve these against the
    orchestrator's _last_touched memory (whatever TOKI itself most
    recently created/renamed/moved/copied/generated) instead of either
    guessing from a fuzzy match against the whole raw sentence, or asking
    a question the user will find confusing ("didn't I just tell you?")."""

    @pytest.mark.parametrize("text", [
        "now open it", "delete it", "open that", "rename this",
        "delete the folder you just made", "open the file you created",
    ])
    def test_detects_anaphoric_phrasing(self, text):
        assert is_anaphoric_reference(text) is True

    @pytest.mark.parametrize("text", [
        "open chrome", "delete notes.txt", "make a folder called Homework",
    ])
    def test_named_targets_not_flagged_as_anaphoric(self, text):
        assert is_anaphoric_reference(text) is False

    def test_resolves_against_last_touched(self):
        last_touched = {"path": r"C:\Users\Man in blue\OneDrive\Desktop\python"}
        result = resolve_anaphoric_target("DELETE_ITEM", last_touched)
        assert result == {"path": last_touched["path"]}

    def test_returns_none_with_nothing_remembered(self):
        assert resolve_anaphoric_target("DELETE_ITEM", None) is None

    def test_ineligible_intent_returns_none(self):
        # MAKE_FOLDER needs a NEW name -- anaphora doesn't apply to naming
        # something that doesn't exist yet, so this must stay None even
        # with something remembered.
        result = resolve_anaphoric_target("MAKE_FOLDER", {"path": "C:\\Desktop\\python"})
        assert result is None


# ─── Generic WCL (windows_command_library) single-variable slot filler ────
#
# Pins the Phase 1 slot-filler added to unlock single-variable,
# danger_level=="safe" WCL commands -- see extractor.py's
# _extract_wcl_slots() docstring for the scope decision (single-var only,
# 2+ variable commands explicitly out of scope here).

class TestWclGenericSlotFiller:
    def test_quoted_value_used_verbatim_for_unknown_variable_name(self):
        # "server" isn't a name TOKI has any special-case logic for --
        # this must still work via the same quote-first convention every
        # other slot in this file honors.
        result = extract_slots("WCL_Get-Something", 'check the server "PROD-DB01"', wcl_variables=["server"])
        assert result == {"server": "PROD-DB01"}

    def test_named_trigger_works_for_unknown_variable_name(self):
        result = extract_slots("WCL_Start-Vm", "start the vm named TestVM", wcl_variables=["vm_name"])
        assert result == {"vm_name": "TestVM"}

    def test_path_variable_routes_through_sandboxed_resolve_path(self):
        result = extract_slots("WCL_Get-Content", 'read the file "notes.txt"', wcl_variables=["file_path"])
        assert result is not None
        assert result["file_path"].endswith("notes.txt")

    def test_path_variable_outside_sandbox_is_rejected_not_guessed(self):
        result = extract_slots(
            "WCL_Get-Content", 'read the file "C:\\Windows\\System32\\config"',
            wcl_variables=["file_path"],
        )
        assert result is None

    def test_whole_sentence_answer_rejected_not_treated_as_a_value(self):
        # Same _looks_like_real_name plausibility guard every other
        # identifier-ish slot already gets -- a leftover instruction/
        # sentence must never become a literal PowerShell argument.
        result = extract_slots(
            "WCL_Do-Something", "please just go ahead and do the thing for me",
            wcl_variables=["name"],
        )
        assert result is None

    def test_no_wcl_variables_falls_through_to_no_slots_needed(self):
        # A zero-variable WCL command (the pre-existing path) still passes
        # wcl_variables=None/[] and must behave exactly as before: no
        # slots required, empty dict back.
        assert extract_slots("WCL_Clear-Host", "clear the screen", wcl_variables=None) == {}

    def test_two_variable_command_now_extracts_via_quotes(self):
        # BETA 0.3.36/0.3.37: 2-variable "safe" WCL commands (61 of them,
        # e.g. Copy-Item, Move-Item, Join-Path, Rename-Item -- see
        # TestWclTwoVariableSlotFiller below) -- made safe to build only
        # once orchestrator.py's _ensure_quoted_placeholders() closed the
        # underlying command-injection gap in the SAME session (see
        # STATUS.md BETA 0.3.37). This is no longer "out of scope".
        import extractor
        desktop = extractor._resolve_real_desktop_path()
        result = extract_slots(
            "WCL_Copy-Item", 'copy "a.txt" to "b.txt"',
            wcl_variables=["source", "destination"],
        )
        assert result == {
            "source": f"{desktop}\\a.txt",
            "destination": f"{desktop}\\b.txt",
        }

    def test_three_plus_variable_command_is_still_out_of_scope_returns_none(self):
        # 3+ variable commands remain the explicitly separate, not-yet-
        # built phase -- must never guess an order/split here. (All 7 of
        # them are "destructive" anyway, so orchestrator.py's danger_level
        # gate would block them regardless -- this test is about
        # extract_slots() itself never guessing, independent of that.)
        result = extract_slots(
            "WCL_Some-ThreeVarCmd", 'do "a" "b" "c"',
            wcl_variables=["one", "two", "three"],
        )
        assert result is None

    def test_resolve_missing_slot_fills_wcl_follow_up_answer(self):
        result = resolve_missing_slot(
            "WCL_Start-Vm", "start a vm", "TestVM", wcl_variables=["vm_name"],
        )
        assert result == {"vm_name": "TestVM"}

    def test_resolve_missing_slot_rejects_implausible_wcl_answer(self):
        result = resolve_missing_slot(
            "WCL_Start-Vm", "start a vm", "I don't know, whatever one you think is right",
            wcl_variables=["vm_name"],
        )
        assert result is None


# ─── BETA 0.3.15: wcl_stripped_value threading ─────────────────────────────
#
# wcl_resolver.py's new Tier 2 (trailing-value stripping) already isolates
# the exact value when it strips a trailing alias match off the raw query.
# Found live: without threading that value through, extract_slots() was
# re-deriving a value from the FULL raw sentence via generic pattern
# matching, which has no way to know the command's own alias words ("view
# more", "display type of", ...) aren't part of the value -- it swallowed
# the whole sentence, producing a garbled path instead of just the real
# filename.

class TestWclTwoVariableSlotFiller:
    """BETA 0.3.36/0.3.37: 2-variable "safe" WCL commands (61 of them).
    Made safe to build only once orchestrator.py's
    _ensure_quoted_placeholders() closed the underlying command-
    injection gap (see STATUS.md BETA 0.3.37) -- these tests exercise
    the extraction logic; the injection-safety fix itself is tested
    separately in test_orchestrator.py / test_wcl_slot_filling_integration.py.
    """

    def test_two_quotes_assigned_in_order(self):
        import extractor
        desktop = extractor._resolve_real_desktop_path()
        result = extract_slots(
            "WCL_Copy-Item", 'copy "a.txt" to "b.txt"',
            wcl_variables=["source", "destination"],
        )
        assert result == {
            "source": f"{desktop}\\a.txt",
            "destination": f"{desktop}\\b.txt",
        }

    def test_to_separator_without_quotes(self):
        result = extract_slots(
            "WCL_Join-Path", "join path D:\\projects to notes.txt",
            wcl_variables=["path", "child_path"],
        )
        assert result is not None
        assert "projects" in result["path"]
        assert result["child_path"].endswith("notes.txt")

    def test_into_separator_without_quotes(self):
        # "source"/"destination" are in the expanded _WCL_PATH_VAR_NAMES
        # (BETA 0.3.37) -- correctly routed through resolve_path()'s
        # sandbox, so the result is a full sandboxed path, not the bare
        # filename verbatim.
        result = extract_slots(
            "WCL_Compress-Archive", 'compress "report.docx" into "archive.zip"',
            wcl_variables=["source", "destination"],
        )
        assert result is not None
        assert result["source"].endswith("report.docx")
        assert result["destination"].endswith("archive.zip")

    def test_exactly_two_quotes_required_not_one_or_three(self):
        # Only one quoted value present -- must not guess which variable
        # it belongs to.
        result = extract_slots(
            "WCL_Copy-Item", 'copy "a.txt" somewhere',
            wcl_variables=["source", "destination"],
        )
        assert result is None

    def test_no_quotes_and_no_separator_returns_none(self):
        result = extract_slots(
            "WCL_Get-ChildItem", "get child items in D:\\projects",
            wcl_variables=["path", "filter"],
        )
        assert result is None

    def test_one_side_implausible_rejects_the_whole_pair(self):
        # Even with the right separator, a sentence-shaped side must
        # still be rejected via the same _looks_like_real_name guard --
        # never dispatch with one good value and one garbled one.
        result = extract_slots(
            "WCL_Copy-Item", "copy whatever you think is best to backup.txt",
            wcl_variables=["source", "destination"],
        )
        assert result is None

    def test_path_shaped_variable_names_route_through_sandbox_even_in_pairs(self):
        result = extract_slots(
            "WCL_Copy-Item", 'copy "C:\\Windows\\System32\\config" to "safe.txt"',
            wcl_variables=["source", "destination"],
        )
        # "source" isn't literally named "path", but IS in the expanded
        # _WCL_PATH_VAR_NAMES set (BETA 0.3.37) -- must be sandboxed and
        # reject an out-of-bounds path, not accept it verbatim.
        assert result is None

    def test_three_variable_commands_never_reach_the_pair_extractor(self):
        result = extract_slots(
            "WCL_Something", 'do "a" "b" "c"',
            wcl_variables=["one", "two", "three"],
        )
        assert result is None


class TestWclNumericHintPairExtraction:
    """BETA 0.3.38: the numeric-hint strategy for (path/name, count) and
    (path/name, size) 2-variable WCL pairs -- PROJECT_STATE_OVERVIEW.md's
    #2 remaining-work item ("show me the 5 largest files" has no quote
    and no to/into/as separator, so strategies 1/2 both miss it). Exercises
    the real shape of the 5 currently-eligible WCL commands that need
    this (Get-LargestFiles, Recent Files, Old Files, Large Folders --
    (path, count); Find Large Files -- (path, size_bytes)).
    """

    def test_count_next_to_largest_keyword(self):
        result = extract_slots(
            "WCL_Get-LargestFiles", "show me the 5 largest files in D:\\Projects",
            wcl_variables=["path", "count"],
        )
        assert result == {"count": "5", "path": "D:\\Projects"}

    def test_top_n_phrasing(self):
        result = extract_slots(
            "WCL_Recent-Files", "top 10 files in D:\\Projects",
            wcl_variables=["path", "count"],
        )
        assert result == {"count": "10", "path": "D:\\Projects"}

    def test_bare_fallback_number_still_works_with_no_keyword_nearby(self):
        result = extract_slots(
            "WCL_Old-Files", "grab 4 from D:\\Archive",
            wcl_variables=["path", "count"],
        )
        assert result == {"count": "4", "path": "D:\\Archive"}

    def test_no_number_at_all_returns_none(self):
        # No numeral anywhere -- must fall through to the missing-slot
        # question exactly like before this strategy existed, never
        # invent a count.
        result = extract_slots(
            "WCL_Get-LargestFiles", "show me the largest files in D:\\Projects",
            wcl_variables=["path", "count"],
        )
        assert result is None

    def test_number_glued_to_path_is_not_mistaken_for_the_count(self):
        # "5" here is part of the path itself (a folder literally named
        # "5"), not a count the user supplied -- the standalone-int
        # fallback must not strip it out of the path and misfile it as
        # `count`. Falls through to asking rather than guessing wrong.
        result = extract_slots(
            "WCL_Recent-Files", "recent files in D:\\5",
            wcl_variables=["path", "count"],
        )
        assert result is None

    def test_size_with_explicit_unit_converts_to_bytes(self):
        result = extract_slots(
            "WCL_Find-Large-Files", "find large files over 500MB in D:\\Projects",
            wcl_variables=["path", "size_bytes"],
        )
        assert result == {"size_bytes": str(500 * 1024 * 1024), "path": "D:\\Projects"}

    def test_size_with_spelled_out_unit(self):
        result = extract_slots(
            "WCL_Find-Large-Files", "find large files over 2 gigabytes in D:\\Projects",
            wcl_variables=["path", "size_bytes"],
        )
        assert result == {"size_bytes": str(2 * 1024 ** 3), "path": "D:\\Projects"}

    def test_size_without_a_unit_is_rejected_not_guessed_as_bytes(self):
        # "size_bytes" without an explicit unit is deliberately NOT
        # accepted -- too ambiguous whether a bare "500" means bytes,
        # or something else entirely (a count, a percentage...).
        result = extract_slots(
            "WCL_Find-Large-Files", "find large files over 500 in D:\\Projects",
            wcl_variables=["path", "size_bytes"],
        )
        assert result is None

    def test_generic_non_path_variable_paired_with_count_still_works(self):
        # Confirms the strategy maps by variable NAME, not fixed
        # position, and reuses the same quote-aware _extract_name() path
        # for the non-numeric side when it isn't path-shaped.
        result = extract_slots(
            "WCL_Something", 'show 5 items for "TestVM"',
            wcl_variables=["vm_name", "count"],
        )
        assert result == {"count": "5", "vm_name": "TestVM"}

    def test_two_variable_names_with_neither_numeric_shaped_still_returns_none(self):
        # Regression guard: a pair with no "count"/"size" in either
        # variable name (e.g. Get-ChildItem's path/filter) must not be
        # affected by this strategy at all.
        result = extract_slots(
            "WCL_Get-ChildItem", "get child items in D:\\projects",
            wcl_variables=["path", "filter"],
        )
        assert result is None

    def test_exactly_two_quotes_present_but_unresolved_does_not_fall_back_to_numeric_guessing(self):
        # Same "don't guess differently once an explicit signal was
        # given" rule strategy 1 already enforces for itself -- a message
        # with exactly two quotes that fails to resolve must not then be
        # rescued by the numeric-hint strategy guessing something else.
        result = extract_slots(
            "WCL_Get-LargestFiles", 'show me "5" "whatever you think is best to use here"',
            wcl_variables=["count", "path"],
        )
        assert result is None

    def test_code_like_variable_name_still_blocks_before_numeric_strategy_runs(self):
        # The BETA 0.3.37 code-like blocklist is checked before ANY pair
        # strategy (see _extract_wcl_slots()) -- confirms this new
        # strategy didn't accidentally bypass that earlier gate.
        result = extract_slots(
            "WCL_Set-PSBreakpoint", "set breakpoint on script.ps1 at line 5",
            wcl_variables=["script", "line"],
        )
        assert result is None


class TestWclCodeLikeVariableBlocklist:
    """BETA 0.3.37: CRITICAL fix, found while scoping the 2-variable
    extension. 15 currently-eligible "safe" commands have a variable
    representing literal CODE/COMMAND content (Start-Job's
    `script_block`, Set-Alias's `command`, etc.) -- even a value that's
    perfectly safe as a quoted STRING LITERAL can still end up EXECUTED
    if PowerShell implicitly converts it to a [scriptblock] at parameter-
    binding time, a risk no amount of quoting/escaping the string itself
    can prevent. Categorical blocklist by variable name, checked before
    anything else, at every entry point (extract_slots(),
    resolve_missing_slot(), AND orchestrator.py's eligibility gate
    itself -- see test_wcl_slot_filling_integration.py for that layer).
    """

    @pytest.mark.parametrize("var_name", [
        "script_block", "script", "command", "function", "arguments", "params",
        "command_name",  # deliberately broad substring match -- see module comment
    ])
    def test_single_variable_code_like_name_never_extracts(self, var_name):
        result = extract_slots(
            "WCL_Start-Job", 'run "Get-Process" as a job',
            wcl_variables=[var_name],
        )
        assert result is None

    def test_two_variable_command_blocked_if_either_side_is_code_like(self):
        result = extract_slots(
            "WCL_Set-Alias", 'set alias "ll" to "Get-ChildItem"',
            wcl_variables=["alias_name", "command"],
        )
        assert result is None

    def test_resolve_missing_slot_also_blocks_code_like_follow_up_answers(self):
        # Without this, a value extract_slots() correctly refused on the
        # FIRST message could still sneak in via the ANSWER to the
        # resulting missing-slot question -- a separate entry point into
        # the exact same risk.
        result = resolve_missing_slot(
            "WCL_Start-Job", "start a job", "Get-Process | Stop-Process",
            wcl_variables=["script_block"],
        )
        assert result is None

    def test_non_code_like_names_are_unaffected(self):
        # Regression guard: the blocklist must not accidentally catch
        # ordinary variable names that just happen to share a letter or
        # two -- only real substring matches from the fixed list.
        result = extract_slots("WCL_Start-Vm", "start the vm named TestVM", wcl_variables=["vm_name"])
        assert result == {"vm_name": "TestVM"}


class TestWclStrippedValueThreading:
    def test_stripped_value_used_verbatim_for_path_variable(self):
        # Without wcl_stripped_value, this would fall through to generic
        # extraction on the full sentence and swallow "view more" as part
        # of the path -- confirmed live before this fix existed.
        result = extract_slots(
            "WCL_more", "view more notes.txt",
            wcl_variables=["file_path"], wcl_stripped_value="notes.txt",
        )
        assert result is not None
        assert result["file_path"].endswith("notes.txt")
        assert "view" not in result["file_path"].lower()
        assert "more" not in ntpath_basename_lower(result["file_path"])

    def test_stripped_value_used_verbatim_for_non_path_variable(self):
        result = extract_slots(
            "WCL_Start-Vm", "launch vm named TestVM",
            wcl_variables=["vm_name"], wcl_stripped_value="TestVM",
        )
        assert result == {"vm_name": "TestVM"}

    def test_implausible_stripped_value_still_rejected(self):
        # The plausibility guard must still apply even when the value
        # came from the resolver's own stripping, not just generic
        # extraction -- a stripped leftover that's itself not name-shaped
        # (e.g. just "of", a stray filler word) must not become a literal
        # value.
        result = extract_slots(
            "WCL_Do-Something", "please display type of the thing",
            wcl_variables=["name"], wcl_stripped_value="of the thing please just do it",
        )
        assert result is None

    def test_no_stripped_value_falls_back_to_generic_extraction_unchanged(self):
        # None (tier 1/3/5 matches, which never needed to strip anything)
        # must behave EXACTLY like before this fix -- confirms the fallback
        # path is untouched, not just that the new path works.
        result = extract_slots(
            "WCL_Get-Something", 'check the server "PROD-DB01"',
            wcl_variables=["server"], wcl_stripped_value=None,
        )
        assert result == {"server": "PROD-DB01"}


class TestCityExtractionCaseInsensitive:
    """BUG FOUND AND FIXED: _CITY_RE originally required the city name to
    start with a capital letter ([A-Z]...). Tested directly against
    "whats the weather in lahore" -- an entirely ordinary, lowercase way to
    type a chat message -- and it silently returned None, so GET_WEATHER
    fell back to "couldn't determine your location" even though the user
    explicitly named a city. Never caught before: the only prior tests
    (test_orchestrator.py) always used properly-capitalized city names
    ("Lahore", "Karachi"). Fixed to match case-insensitively, plus strip
    trailing filler words ("please", "right now", etc.) that a
    capital-letter-free match would otherwise swallow along with the city."""

    @pytest.mark.parametrize("text,expected_city", [
        ("whats the weather in lahore", "lahore"),
        ("weather in tokyo", "tokyo"),
        ("is it raining in london", "london"),
        ("weather in lahore please", "lahore"),
        ("what is the weather in san francisco right now", "san francisco"),
        ("weather in Lahore today", "Lahore"),  # capitalized still works
        ("weather in New York", "New York"),    # multi-word capitalized still works
    ])
    def test_lowercase_and_capitalized_cities_both_extracted(self, text, expected_city):
        result = extract_slots("GET_WEATHER", text)
        assert result == {"city": expected_city}


class TestFindFilesByContentPhrasing:
    """BUG FOUND AND FIXED: the original trigger only matched 3 exact
    phrases ("containing X" / "with the text X" / "for the text X").
    Tested directly against realistic phrasings -- "search inside files in
    downloads for TODO", "search for TODO in my files", "find files that
    contain TODO", "search files for the word urgent" -- and 4 of 6 real
    cases returned None. Fixed with a broader trigger plus post-processing
    to strip leading "the word/text/phrase" filler and trailing "in my
    files"/"in downloads" location filler that a broader trigger would
    otherwise swallow into the pattern."""

    @pytest.mark.parametrize("text,expected_pattern", [
        ("find files containing ERROR", "ERROR"),
        ("search for TODO in my files", "TODO"),
        ("find files with the text password", "password"),
        ("search files for the word urgent", "urgent"),
        ("find files that contain TODO", "TODO"),
        ("search inside files for TODO", "TODO"),
        ("search inside files in downloads for TODO", "TODO"),
        ("search for the word urgent in documents", "urgent"),
    ])
    def test_realistic_phrasings_extract_correct_pattern(self, text, expected_pattern):
        result = extract_slots("FIND_FILES_BY_CONTENT", text)
        assert result is not None
        assert result["pattern"] == expected_pattern

    @pytest.mark.parametrize("text", ["find files", "search for"])
    def test_bare_trigger_with_no_pattern_returns_none(self, text):
        """A trigger phrase with nothing after it must not silently
        extract garbage as the search pattern."""
        assert extract_slots("FIND_FILES_BY_CONTENT", text) is None


class TestFindFilesByNameLeadingVerbStrip:
    """BETA 0.3.33: FIND_FILES (search by NAME, not by content -- a
    different intent from FIND_FILES_BY_CONTENT above) shared the exact
    same over-capture bug as DELETE_ITEM/READ_FILE/etc: "find files.txt"
    extracted query "find files.txt" instead of "files.txt", "search for
    report.docx" extracted "search for report.docx" instead of
    "report.docx". Fixed by extending the same _BARE_PATH_LEADING_VERB_RE
    used for DELETE_ITEM/READ_FILE to also cover find/search (with "for"
    as an optional filler too). Lower stakes than the destructive-target
    intents (a bad guess here is a bad SEARCH, not a wrong deletion), so
    deliberately NOT also wired to the _looks_like_real_name() safety net
    -- just the strip.
    """

    @pytest.mark.parametrize("text,expected_query", [
        ("find files.txt", "files.txt"),
        ("search for report.docx", "report.docx"),
        ("find the report.docx", "report.docx"),
    ])
    def test_leading_verb_no_longer_swallowed_into_the_query(self, text, expected_query):
        result = extract_slots("FIND_FILES", text)
        assert result is not None
        assert result["query"] == expected_query

    def test_free_text_query_with_no_extension_still_returns_none(self):
        # No dot+extension anywhere means _BARE_FILENAME_RE never matches
        # at all -- unchanged, pre-existing behavior, not something this
        # fix touches either way.
        assert extract_slots("FIND_FILES", "find files about my budget") is None


class TestCannedReply:
    """Latency fix, not a new feature: measured directly that EVERY CHAT/
    ASK_CONTEXT turn was paying a full second LLM call (~500-700 token
    system prompt, fully re-evaluated, no cross-call KV-cache reuse via
    Ollama's /api/chat) just to reword a fixed instruction into one
    sentence -- confirmed costing 20-30+ seconds on a CPU-only box for
    inputs as simple as "hey" or "thanks". Deliberately narrow: only pure
    greetings/closings match, never real content alongside one, since a
    broad "CHAT skips the LLM" behavior is unsafe (see
    test_graph_router.py's TestChatNeverGraphHits for why CHAT itself
    must stay genuinely open-ended)."""

    @pytest.mark.parametrize("text", [
        "hey", "hi", "hello", "yo",
        "hey how's it going", "hi how are you",
        "thanks", "thank you", "thx", "ok", "okay", "got it",
        "thanks, that's all for now", "bye", "goodbye",
    ])
    def test_pure_greetings_and_closings_get_a_canned_reply(self, text):
        assert canned_reply(text) is not None

    @pytest.mark.parametrize("text", [
        "hey what's the weather",
        "hi can you open notepad",
        "thanks for opening notepad, now close it",
        "who made you",
        "tell me a joke",
        "what do you think about pineapple on pizza",
        "",
        "   ",
    ])
    def test_real_content_never_matches_even_with_a_greeting_word(self, text):
        """The core safety requirement: anything with real content --
        even alongside a greeting word -- must fall through to the real
        pipeline, never get intercepted by a canned stub."""
        assert canned_reply(text) is None

    def test_reply_is_deterministic_not_random(self):
        """Same input must always produce the same reply -- a stable pick
        keyed on the text itself, not random.choice, so repeated test/CI
        runs are reproducible."""
        assert canned_reply("hey") == canned_reply("hey")
        assert canned_reply("thanks") == canned_reply("thanks")


def ntpath_basename_lower(path):
    import ntpath
    return ntpath.basename(path).lower()


# ─── New feature: SORT_FOLDER_BY_TYPE / CLEAN_CLIPBOARD ────────────────────
# Everyday-productivity intents added on top of the existing generic
# path-extraction branch (DELETE_ITEM/READ_FILE/OPEN_ITEM/LIST_FILES) --
# these pin that the new intents got wired into that branch correctly and
# that CLEAN_CLIPBOARD (zero slots) hits the function's default "no slots
# needed" fallback rather than accidentally matching an unrelated branch.

class TestSortFolderByType:
    def test_explicit_folder_name_resolves_a_path(self):
        result = extract_slots("SORT_FOLDER_BY_TYPE", "sort my downloads folder by type")
        assert result is not None
        assert "path" in result
        assert result["path"]

    def test_bare_desktop_mention_falls_back_to_default_root(self):
        """Mirrors LIST_FILES's own bare-target fallback -- 'sort my desktop
        by type' names no specific subfolder, so extraction should resolve
        the default root itself rather than returning None."""
        result = extract_slots("SORT_FOLDER_BY_TYPE", "sort my desktop by type")
        assert result is not None
        assert result["path"]

    def test_organize_this_folder_phrasing(self):
        result = extract_slots("SORT_FOLDER_BY_TYPE", "organize this folder by file type")
        assert result is not None
        assert result["path"]


# ─── New feature: ORGANIZE_FILES_BY_TOPIC / GROUP_FILES_BY_EXTENSION ───────
# BETA 0.3.44, checkpoint 4. See extractor.py's own comment block right
# above these two branches for why they have OPPOSITE extraction
# postures despite superficially similar phrasing.

class TestOrganizeFilesByTopic:
    def test_always_resolves_never_returns_none(self):
        # No required slot here -- path always has a default, so this
        # must never fall through to "ask the user" the way a genuinely
        # missing required slot would.
        result = extract_slots("ORGANIZE_FILES_BY_TOPIC", "organize my files")
        assert result is not None
        assert result["path"]

    def test_bare_mention_falls_back_to_default_root(self):
        result = extract_slots("ORGANIZE_FILES_BY_TOPIC", "organize this")
        assert result is not None
        assert result["path"]
        assert result["include_suggestions"] == ""

    def test_explicit_folder_name_resolves_a_path(self):
        result = extract_slots("ORGANIZE_FILES_BY_TOPIC", "organize my downloads folder")
        assert result is not None
        assert result["path"]

    def test_include_suggestions_flag_detected(self):
        result = extract_slots(
            "ORGANIZE_FILES_BY_TOPIC", "organize my desktop including suggestions",
        )
        assert result["include_suggestions"] == "true"

    def test_include_suggestions_flag_absent_by_default(self):
        result = extract_slots("ORGANIZE_FILES_BY_TOPIC", "organize my desktop")
        assert result["include_suggestions"] == ""

    def test_be_more_aggressive_phrasing_also_sets_the_flag(self):
        result = extract_slots("ORGANIZE_FILES_BY_TOPIC", "organize my desktop, be more aggressive")
        assert result["include_suggestions"] == "true"


class TestGroupFilesByExtension:
    def test_explicit_types_and_folder_name(self):
        result = extract_slots(
            "GROUP_FILES_BY_EXTENSION",
            "put all the pdfs and json files here in a new folder named rezero",
        )
        assert result is not None
        assert ".pdf" in result["extensions"]
        assert ".json" in result["extensions"]
        assert result["dest_name"] == "rezero"
        assert result["path"]

    def test_called_variant_also_recognized(self):
        result = extract_slots(
            "GROUP_FILES_BY_EXTENSION", "move all pdf files into a folder called archive",
        )
        assert result is not None
        assert result["dest_name"] == "archive"
        assert ".pdf" in result["extensions"]

    def test_missing_dest_name_returns_none(self):
        # Fully explicit intent -- a miss on either required slot must
        # be an extraction MISS (ask), never a guessed folder name.
        result = extract_slots("GROUP_FILES_BY_EXTENSION", "put all the pdfs somewhere")
        assert result is None

    def test_missing_extensions_returns_none(self):
        result = extract_slots("GROUP_FILES_BY_EXTENSION", "put my stuff in a folder named rezero")
        assert result is None

    def test_image_word_maps_to_real_extensions(self):
        result = extract_slots(
            "GROUP_FILES_BY_EXTENSION", "group the images into a folder called photos",
        )
        assert result is not None
        assert ".jpg" in result["extensions"]

    def test_generic_word_files_fallback(self):
        result = extract_slots(
            "GROUP_FILES_BY_EXTENSION", "put the csv files in a folder called data",
        )
        assert result is not None
        assert ".csv" in result["extensions"]

    def test_generic_fallback_excludes_stopwords(self):
        # "all the files" should never be misread as an extension "the".
        result = extract_slots(
            "GROUP_FILES_BY_EXTENSION", "put all the files in a folder called stuff",
        )
        assert result is None


class TestCleanClipboardRemoved:
    """CLEAN_CLIPBOARD was tried and reverted in this session: it collides
    with GET_CLIPBOARD/SET_CLIPBOARD's already-documented fragile shared
    vocabulary (see tier_a_phrasings.py's GET_CLIPBOARD comment on the
    BETA 0.3.27 clipboard-routing bug) and diluted scoring enough to break
    an existing destructive-shadow-guard test ('clean temp files'). Not
    re-added -- flagging so a future session doesn't reintroduce it blind.
    """
    def test_intent_does_not_exist(self):
        from intents import INTENTS
        assert "CLEAN_CLIPBOARD" not in INTENTS


class TestStartStopSeeingNotInGraph:
    """START_SEEING/STOP_SEEING (macro recording) were ALSO tried as
    graph_router.py Tier A intents in this same session and reverted for
    the same class of reason as CLEAN_CLIPBOARD above: "start"/"stop" are
    load-bearing words for LAUNCH_APP/KILL_PROCESS, and even a small,
    carefully-diluted phrasing set measurably shifted those words' TF-IDF
    weight enough to misroute "start notepad" away from LAUNCH_APP
    (confirmed live: scored 0.631 for START_SEEING, should have gone to
    LAUNCH_APP). Handled instead as a dedicated regex pre-check
    (looks_like_start_seeing/looks_like_stop_seeing below), which has no
    shared vocabulary with the graph and can't cause this class of
    collision. Not re-added to the graph -- flagging so a future session
    doesn't reintroduce it blind, same purpose as the CLEAN_CLIPBOARD note
    above."""
    def test_not_registered_as_graph_intents(self):
        import json
        data = json.loads(open("graph_source_data/tier_a_commands.json").read())
        names = {c["name"] for c in data}
        assert "START_SEEING" not in names
        assert "STOP_SEEING" not in names

    def test_start_notepad_still_routes_to_launch_app(self):
        # The actual regression this session found and fixed -- pinned
        # here so it can't silently come back if someone adds these (or
        # anything else "start"/"stop"-keyed) to the graph again later.
        import graph_router
        gr = graph_router.GraphRouter()
        result = gr.classify("start notepad")
        assert result is None or result["intent"] != "START_SEEING"

    def test_stop_the_music_still_correctly_misses(self):
        import graph_router
        gr = graph_router.GraphRouter()
        assert gr.classify("stop the music") is None


class TestStartSeeingTrigger:
    def test_bare_phrase_matches(self):
        assert looks_like_start_seeing("start seeing")

    def test_natural_variants_match(self):
        assert looks_like_start_seeing("can you start watching what i do")
        assert looks_like_start_seeing("watch everything i click")

    def test_start_app_does_not_match(self):
        assert not looks_like_start_seeing("start notepad")
        assert not looks_like_start_seeing("start spotify")
        assert not looks_like_start_seeing("start this program")

    def test_launch_does_not_match(self):
        assert not looks_like_start_seeing("launch chrome")

    def test_bare_recording_no_longer_auto_matches(self):
        """BETA 0.3.49: this used to be the actual bug -- 'begin recording'
        matched here unconditionally, silently claiming macro capture even
        when someone meant dictation ('begin recording what I say'). Bare
        'recording' with no object word is now genuinely ambiguous, not a
        macro match -- see TestAmbiguousRecordingTrigger below."""
        assert not looks_like_start_seeing("begin recording")
        assert not looks_like_start_seeing("start recording")

    def test_recording_with_macro_object_still_matches(self):
        assert looks_like_start_seeing("start recording what i click")
        assert looks_like_start_seeing("begin recording everything i do")


class TestStopSeeingTrigger:
    def test_bare_phrase_matches(self):
        assert looks_like_stop_seeing("stop seeing")

    def test_natural_variants_match(self):
        assert looks_like_stop_seeing("stop watching")
        assert looks_like_stop_seeing("that's it, save this")
        assert looks_like_stop_seeing("save that as a macro")

    def test_stop_process_does_not_match(self):
        # The actual false positive this session found and fixed --
        # pinned so it can't silently regress.
        assert not looks_like_stop_seeing("stop chrome")
        assert not looks_like_stop_seeing("stop the music")
        assert not looks_like_stop_seeing("stop this program")

    def test_bare_recording_no_longer_auto_matches(self):
        """BETA 0.3.49: same bug/fix as TestStartSeeingTrigger above, stop
        side -- 'stop recording' bare no longer assumes macro. The
        orchestrator resolves this via runtime state instead (is a macro
        recorder active? is dictation?), not via this text-only check."""
        assert not looks_like_stop_seeing("stop recording")


class TestStartListeningRecordingObjectBranch:
    """BETA 0.3.49: distinct from TestStartListeningTrigger below (which
    predates this fix) -- these pin the specific 'recording + say-object'
    branch added to fix the bare 'record what I say' / 'record everything
    I say' miss (see extractor.py's _START_LISTENING_RE comment). Named
    differently from the other class in this file on purpose: it used to
    share the exact name TestStartListeningTrigger, which meant Python
    silently discarded this entire class at import time (the later
    same-named class definition overwrites the earlier one in the module
    namespace) and pytest never collected these tests at all -- including
    test_recording_with_voice_object_matches, the actual regression pin
    for this fix. Confirmed directly: collect-only against the old name
    showed only 5 tests, not the 9 defined across both bodies.
    """

    def test_recording_with_voice_object_matches(self):
        """BETA 0.3.49: the symmetric counterpart to macro's 'recording
        what I do/click' branch -- 'recording' + an explicit 'say' object
        is now an unambiguous dictation trigger too."""
        assert looks_like_start_listening("start recording what i say")
        assert looks_like_start_listening("begin recording everything i say")
        # Bare imperative, no start/begin at all -- the actual reported
        # gap ("record what I say" / "record everything I say" matched
        # nothing before this fix).
        assert looks_like_start_listening("record what i say")
        assert looks_like_start_listening("record everything i say")

    def test_begin_dictation_variant_matches(self):
        assert looks_like_start_listening("begin dictation")

    def test_bare_recording_does_not_match(self):
        assert not looks_like_start_listening("start recording")
        assert not looks_like_start_listening("begin recording")

    def test_start_app_does_not_match(self):
        assert not looks_like_start_listening("start notepad")


class TestAmbiguousRecordingTrigger:
    """BETA 0.3.49: the genuinely irreducible leftover case -- bare 'start/
    stop recording' with no companion word telling us which of the two
    real features (macro capture vs. voice dictation) it means. See
    looks_like_ambiguous_start_recording()/looks_like_ambiguous_stop_recording()
    docstrings for why this asks instead of guessing, and
    orchestrator.py's use of these for how "stop" actually gets resolved
    via runtime state instead, most of the time."""

    def test_bare_start_recording_is_ambiguous(self):
        assert looks_like_ambiguous_start_recording("start recording")
        assert looks_like_ambiguous_start_recording("begin recording")

    def test_disambiguated_start_recording_is_not_flagged_ambiguous(self):
        # These already matched a real intent above -- the orchestrator
        # only checks the ambiguous case AFTER both of those return
        # False, so double-matching here wouldn't actually cause a bug,
        # but pinning it documents the intended non-overlap.
        assert looks_like_start_seeing("start seeing")
        assert looks_like_start_listening("start listening")

    def test_bare_stop_recording_is_ambiguous(self):
        assert looks_like_ambiguous_stop_recording("stop recording")

    def test_unrelated_stop_does_not_match(self):
        assert not looks_like_ambiguous_stop_recording("stop chrome")
        assert not looks_like_ambiguous_start_recording("start notepad")


class TestStartSeeingSlots:
    def test_needs_no_slots(self):
        result = extract_slots("START_SEEING", "start seeing")
        assert result == {}


class TestStartListeningTrigger:
    def test_bare_phrase_matches(self):
        assert looks_like_start_listening("start listening")

    def test_natural_variants_match(self):
        assert looks_like_start_listening("begin dictating")
        assert looks_like_start_listening("start dictation")
        assert looks_like_start_listening("can you start listening please")

    def test_start_app_does_not_match(self):
        # Same false-positive risk _START_SEEING_RE guards against --
        # "start" alone must never trigger this.
        assert not looks_like_start_listening("start notepad")
        assert not looks_like_start_listening("start spotify")
        assert not looks_like_start_listening("start this program")

    def test_launch_does_not_match(self):
        assert not looks_like_start_listening("launch chrome")

    def test_listen_to_music_does_not_match(self):
        # "listen" alone (no start/begin) must never trigger this --
        # "play some music so I can listen" is not a dictation request.
        assert not looks_like_start_listening("play some music so i can listen")


class TestStopListeningTrigger:
    def test_bare_phrase_matches(self):
        assert looks_like_stop_listening("stop listening")

    def test_natural_variants_match(self):
        assert looks_like_stop_listening("stop dictating")
        assert looks_like_stop_listening("please stop the dictation")

    def test_stop_process_does_not_match(self):
        # Same false-positive class the STOP_SEEING fix pinned above.
        assert not looks_like_stop_listening("stop chrome")
        assert not looks_like_stop_listening("stop the music")
        assert not looks_like_stop_listening("stop this program")


class TestStartListeningSlots:
    def test_no_target_named_gives_empty_string_not_none(self):
        # OPTIONAL slot -- must always return a dict, never None, or
        # orchestrator.py's MISSING_SLOT_QUESTIONS path would force a
        # follow-up question that start_dictation() never needs.
        result = extract_slots("START_LISTENING", "start listening")
        assert result == {"target_description": ""}

    def test_named_target_is_extracted(self):
        result = extract_slots("START_LISTENING", "start listening into the search box")
        assert result == {"target_description": "search box"}

    def test_named_target_variant_phrasing(self):
        result = extract_slots("START_LISTENING", "start dictating in notepad")
        assert result == {"target_description": "notepad"}


class TestStopListeningSlots:
    def test_needs_no_slots(self):
        result = extract_slots("STOP_LISTENING", "stop listening")
        assert result == {}


class TestStopSeeingSlots:
    def test_always_asks_never_guesses_from_trigger_text(self):
        # Same pattern as CONDITIONAL_COMMAND -- nothing in "stop seeing"
        # itself could plausibly BE the macro name.
        assert extract_slots("STOP_SEEING", "stop seeing") is None

    def test_resolve_missing_slot_takes_the_answer_verbatim(self):
        from extractor import resolve_missing_slot
        result = resolve_missing_slot("STOP_SEEING", "stop seeing", "zeta")
        assert result == {"macro_name": "zeta"}

    def test_resolve_missing_slot_empty_answer_returns_none(self):
        from extractor import resolve_missing_slot
        result = resolve_missing_slot("STOP_SEEING", "stop seeing", "   ")
        assert result is None
