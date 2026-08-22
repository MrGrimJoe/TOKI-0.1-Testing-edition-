"""
test_graph_router.py -- pins graph_router.classify()'s known-good hits and
known-bad misclassifications from BETA 0.1-0.3.3's manual testing sessions.
Requires `kuzu` and the checked-in toki_graph_db/ -- skips cleanly if either
is unavailable (e.g. a dev machine without the graph built yet) rather than
failing the whole suite.
"""

import pytest

kuzu = pytest.importorskip("kuzu")

from pathlib import Path

if not (Path(__file__).resolve().parent.parent / "toki_graph_db").exists():
    pytest.skip("toki_graph_db not present -- run migrate_to_kuzu.py first", allow_module_level=True)

from graph_router import GraphRouter


@pytest.fixture(scope="module")
def router():
    r = GraphRouter()
    yield r
    r.close()


# ─── BETA 0.1: the specificity-sum scorer's false positives ────────────────
# These must all MISS (fall through to the LLM) -- a confident wrong dispatch
# here has real side effects (deleted files, killed processes, etc.), so a
# miss is always the safe failure mode, never a guess.

class TestFalsePositivesStayMisses:
    @pytest.mark.parametrize("text", [
        "clear the screen",       # was EMPTY_RECYCLE_BIN at 0.75 confidence
        "stop the music",         # was KILL_PROCESS
        "kill the lights",        # was KILL_PROCESS
        "remove this annoying popup",  # was DELETE_ITEM
        "go to the store",        # was LOCK_WORKSTATION
    ])
    def test_known_false_positive_misses(self, router, text):
        result = router.classify(text)
        assert result is None, (
            f"{text!r} dispatched to {result} -- this is a known dangerous "
            f"false positive from BETA 0.1, it must fall through to the LLM instead"
        )


# ─── BETA 0.1: the TF-IDF rework's known-good hits ─────────────────────────

class TestKnownGoodHits:
    @pytest.mark.parametrize("text,expected_intent", [
        ("make a folder called test", "MAKE_FOLDER"),
        ("what's the weather", "GET_WEATHER"),
        ("what's the forecast", "GET_FORECAST"),
        ("empty the recycle bin", "EMPTY_RECYCLE_BIN"),
        ("rename notes.txt to notes-old.txt", "RENAME_ITEM"),
    ])
    def test_known_good_hit(self, router, text, expected_intent):
        result = router.classify(text)
        assert result == {"intent": expected_intent}


# ─── BETA 0.3: LAUNCH_APP vs OPEN_ITEM on bare "open <app>" phrasing ───────

class TestLaunchAppNotOpenItem:
    @pytest.mark.parametrize("text", [
        "open chrome",
        "open discord",   # BETA 0.3: confirmed generalizes beyond the app
                            # names actually added to the phrasing data
    ])
    def test_open_app_routes_to_launch_app(self, router, text):
        result = router.classify(text)
        assert result == {"intent": "LAUNCH_APP"}, (
            f"{text!r} -> {result}; OPEN_ITEM's Start-Process template has no "
            f"way to resolve a bare app name the way LAUNCH_APP does"
        )


# ─── BETA 0.3.3: NON_GRAPH_CATEGORIES must never be returned ───────────────

class TestChatNeverGraphHits:
    @pytest.mark.parametrize("text", [
        "hey how's it going",
        "hey",
        "hi",
    ])
    def test_chat_shaped_messages_miss(self, router, text):
        result = router.classify(text)
        assert result is None, (
            f"{text!r} -> {result}; CHAT/ASK_CONTEXT must never be returned "
            f"by the graph (see NON_GRAPH_CATEGORIES) -- a graph-hit CHAT "
            f"skips the LLM call entirely and produces a templated stub reply"
        )


# ─── BETA 0.3.3: the pre-LLM gate's target case ────────────────────────────

class TestBelowThresholdCandidatesMissCleanly:
    def test_kill_notepad_exe_is_a_graph_miss(self, router):
        # classify() itself must miss here (None) -- classify_or_ask() is
        # the one that surfaces the below-threshold KILL_PROCESS candidate
        # for orchestrator.py's pre-LLM gate to act on.
        assert router.classify("kill notepad.exe") is None

    def test_kill_notepad_exe_has_a_real_candidate_for_the_gate(self, router):
        ask_result = router.classify_or_ask("kill notepad.exe")
        assert "intent" not in ask_result
        assert ask_result.get("candidate") == "KILL_PROCESS", (
            "orchestrator.py's pre-LLM gate depends on classify_or_ask() "
            "surfacing a real candidate here -- without it, this message "
            "would reach the LLM's free-text CHAT/GENERATE/ASK_CONTEXT "
            "judgment and risk a fabricated 'Done, I've terminated...' narration"
        )


# ─── Known, still-open bugs ─────────────────────────────────────────────────

class TestKnownOpenIssues:
    # Formerly xfail'd (STATUS.md, open since BETA 0.1): GENERATE_FILE had
    # zero Phrasing nodes in the graph checkpoint, so no scoring formula
    # could ever select it -- "write a poem to a file" fell through to
    # READ_FILE instead. Fixed by adding real phrasings for GENERATE_FILE
    # to graph_source_data/tier_a_phrasings.py (and a matching Command
    # entry in tier_a_commands.json, since it previously had neither) and
    # rebuilding the graph. This is now a real regression test, not an
    # xfail marker -- if this ever fails again, the graph wasn't rebuilt
    # after a phrasings change, or the GENERATE_FILE phrasings/vocabulary
    # got diluted by something else added later.
    def test_generate_file_is_reachable(self, router):
        result = router.classify("write a poem to a file")
        assert result == {"intent": "GENERATE_FILE"}


# ─── BETA 0.3.6: .exe (and other extension) suffixes must not break
# routing ────────────────────────────────────────────────────────────────
#
# Confirmed live (ad hoc, via route_probe.py, before this suite pinned it):
# "kill notepad.exe" / "wait for chrome.exe" / "find explorer.exe" all
# missed the graph completely (unknown_words included the process name
# itself) -- the existing .exe-strip fix in extractor.py only applies to
# SLOT extraction, which never got reached because routing failed first.
# Fixed at the source in graph_router.normalize(), which now strips a
# short fixed list of common suffixes before tokenizing.

class TestExeSuffixNormalization:
    def test_exe_suffix_produces_same_content_words_as_bare_name(self):
        from graph_router import normalize, content_words
        with_ext = content_words(normalize("kill notepad.exe"))
        without_ext = content_words(normalize("kill notepad"))
        assert with_ext == without_ext, (
            f"{with_ext} != {without_ext} -- .exe must not leave 'exe' or "
            f"a glued token behind as unmatchable vocabulary"
        )

    @pytest.mark.parametrize("text", [
        "kill notepad.exe",
        "wait for chrome.exe",
        "find explorer.exe",
    ])
    def test_exe_suffixed_query_is_not_a_blind_graph_miss(self, router, text):
        # These must not vanish into total unknown_words -- classify_or_ask()
        # should surface SOME candidate now that the suffix is stripped,
        # even if (correctly) below CONFIDENCE_THRESHOLD for a confident hit.
        result = router.classify_or_ask(text)
        assert "intent" not in result, (
            f"{text!r} confidently dispatched to {result} -- the graph "
            f"doesn't have process-name vocabulary, this should ASK, not HIT"
        )
        assert result.get("candidate") is not None, (
            f"{text!r} -> {result}; expected a real candidate now that "
            f".exe stripping lets this reach scoring at all"
        )


# ─── BETA 0.3.6: LAUNCH_APP's own seed phrasings must not poison
# unrelated commands that share an app name ────────────────────────────────
#
# Root cause found while adding the .exe fix above: "kill notepad" (no
# .exe at all) was ALSO tipping toward LAUNCH_APP over KILL_PROCESS,
# because LAUNCH_APP's phrasings literally contained "open notepad" /
# "launch notepad" -- so ANY other command mentioning "notepad" inherited
# unwanted pull toward LAUNCH_APP. Fixed by swapping "notepad" out of
# LAUNCH_APP's phrasing data for "vscode"/"steam" (those phrasings exist to
# rebalance the "open" verb's weight, not to hardcode that specific app).

class TestLaunchAppPhrasingsDontPoisonOtherCommands:
    def test_kill_notepad_candidate_is_kill_process_not_launch_app(self, router):
        result = router.classify_or_ask("kill notepad")
        assert result.get("candidate") == "KILL_PROCESS", (
            f"kill notepad -> {result}; LAUNCH_APP's own seed phrasings "
            f"('open notepad', 'launch notepad') must not out-score "
            f"KILL_PROCESS just because both mention the same app name"
        )

    def test_launch_app_still_resolves_for_open_steam_and_vscode(self, router):
        # Regression guard for the phrasing swap itself: the app names
        # substituted IN (vscode/steam) must still work the way notepad
        # used to, not just "not break notepad."
        assert router.classify("open steam") == {"intent": "LAUNCH_APP"}


# ─── BETA 0.3.6: MAKE_FILE vs MAKE_FOLDER on "new" ─────────────────────────
#
# MAKE_FILE had zero phrasings containing "new", while MAKE_FOLDER had one
# ("create a new folder") -- so "make a new file called test.txt" and
# "make new file test.txt" both wrongly routed to MAKE_FOLDER.

class TestMakeFileNewPhrasing:
    @pytest.mark.parametrize("text", [
        "make a new file called test.txt",
        "make new file test.txt",
        "create a new file called test.txt",
    ])
    def test_new_file_phrasing_routes_to_make_file(self, router, text):
        result = router.classify(text)
        assert result == {"intent": "MAKE_FILE"}, (
            f"{text!r} -> {result}; 'new' must not tip this toward "
            f"MAKE_FOLDER just because MAKE_FOLDER's phrasings say "
            f"'create a new folder'"
        )

    def test_make_folder_with_new_is_unaffected(self, router):
        # Guard against overcorrecting: adding "new" to MAKE_FILE must not
        # steal MAKE_FOLDER's own legitimate "new folder" phrasing.
        result = router.classify("make a new folder called test")
        assert result == {"intent": "MAKE_FOLDER"}


# ─── BETA 0.3.6: KILL_PROCESS "close"/"terminate" synonyms ─────────────────
#
# KILL_PROCESS had no coverage for "close" or "terminate" as process-kill
# synonyms -- "close notepad" and "terminate steam" missed the graph
# entirely. These correctly ASK (not blind-HIT) since the graph doesn't
# know process names as vocabulary -- landing on the right candidate for
# the pre-LLM gate is the fix, not a confident dispatch.

class TestKillProcessSynonyms:
    @pytest.mark.parametrize("text", [
        "close notepad",
        "terminate steam",
    ])
    def test_close_and_terminate_surface_kill_process_candidate(self, router, text):
        result = router.classify_or_ask(text)
        assert "intent" not in result, (
            f"{text!r} confidently dispatched to {result} -- should ASK, "
            f"the graph has no process-name vocabulary to confirm against"
        )
        assert result.get("candidate") == "KILL_PROCESS", (
            f"{text!r} -> {result}; expected KILL_PROCESS as the "
            f"candidate now that 'close'/'terminate' phrasings exist"
        )


# ─── BETA 0.3.27: "shut up"/"shut it up" scored VOLUME_UP, the literal ────
# opposite of what was asked. Root cause: "shut" appeared nowhere in the
# Tier A phrasing corpus, so it was silently dropped as out-of-vocabulary
# by the tf-idf scorer, leaving only "up" to score against -- which
# VOLUME_UP's own corpus matches heavily. VOLUME_UP needs zero slots, so
# this auto-dispatched immediately with no confirmation gate at all. Fixed
# by giving TOGGLE_MUTE real phrasing coverage for this wording.

class TestShutUpMeansMute:
    @pytest.mark.parametrize("text", [
        "shut up",
        "shut it up",
    ])
    def test_shut_up_routes_to_mute_not_volume_up(self, router, text):
        result = router.classify(text)
        assert result == {"intent": "TOGGLE_MUTE"}, (
            f"{text!r} -> {result}; must never be VOLUME_UP -- that was "
            f"the literal opposite of what 'shut up' means, and it had "
            f"zero required slots so it auto-dispatched with no chance "
            f"to catch the mistake"
        )

    @pytest.mark.parametrize("text", [
        "turn it up",
        "turn the volume up",
        "crank it up",
        "make it louder",
    ])
    def test_real_volume_up_phrasings_unaffected(self, router, text):
        # Guard against overcorrecting: adding "shut up" to TOGGLE_MUTE
        # must not steal VOLUME_UP's own legitimate "up" phrasings.
        result = router.classify(text)
        assert result == {"intent": "VOLUME_UP"}, f"{text!r} -> {result}"


# ─── BETA 0.3.49: "turn the volume off" scored VOLUME_UP -- same bug ────
# class as "shut up" above, different missing word. "off" appeared
# nowhere in the Tier A phrasing corpus, so it was dropped as
# out-of-vocabulary, leaving only "turn"+"volume" to score, which matches
# VOLUME_UP's corpus ("turn the volume up") more than VOLUME_DOWN's.
# VOLUME_UP needs zero slots, so this auto-dispatched immediately with no
# confirmation gate -- the literal opposite of the request, silently
# executed. Fixed the same way: give TOGGLE_MUTE real coverage for "off".

class TestVolumeOffMeansMute:
    @pytest.mark.parametrize("text", [
        "turn the volume off",
        "turn off the volume",
        "turn my volume off",
        "volume off",
        # Case and punctuation variants -- must not depend on exact casing
        # or a bare match, since real speech-to-text output won't be clean.
        "TURN THE VOLUME OFF",
        "Turn The Volume Off",
        "turn the volume off please",
        "can you turn the volume off",
        "please turn my volume off",
        # Contraction/typo-adjacent phrasings a real user might send.
        "turn volume off",
        "turn off my volume",
    ])
    def test_volume_off_routes_to_mute_not_volume_up(self, router, text):
        result = router.classify(text)
        assert result == {"intent": "TOGGLE_MUTE"}, (
            f"{text!r} -> {result}; must never be VOLUME_UP -- that's the "
            f"literal opposite of 'off', and it had zero required slots "
            f"so it auto-dispatched with no chance to catch the mistake"
        )

    @pytest.mark.parametrize("text", [
        "turn it up",
        "turn the volume up",
        "crank it up",
        "make it louder",
        "louder please",
    ])
    def test_real_volume_up_phrasings_still_unaffected(self, router, text):
        # Guard against overcorrecting a second time: adding "off"
        # phrasings to TOGGLE_MUTE must not steal VOLUME_UP's own "up"/
        # "louder" vocabulary either.
        result = router.classify(text)
        assert result == {"intent": "VOLUME_UP"}, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text", [
        "turn the volume down",
        "turn it down",
        "quiet it down",
        "make it quieter",
    ])
    def test_real_volume_down_phrasings_unaffected(self, router, text):
        # And must not steal VOLUME_DOWN's "down"/"quiet" vocabulary --
        # "off" and "down" are semantically adjacent (both reduce volume)
        # so this is the collision most worth explicitly guarding.
        result = router.classify(text)
        assert result == {"intent": "VOLUME_DOWN"}, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text", [
        "turn off my monitor",
        "turn off my screen",
        "turn off dark mode",
        "turn off wifi",
        "turn off do not disturb",
        "turn off bluetooth",
        "turn off notifications",
        "turn off airplane mode",
        "power off",
        "turn the computer off",
        "turn off my pc",
        "turn off flight mode",
        "turn off night light",
        "turn off vpn",
    ])
    def test_unrelated_turn_off_phrasings_do_not_misroute_to_mute(self, router, text):
        """A second, more severe bug found and fixed while writing this
        fix: an earlier version of the "off" vocabulary addition (four
        near-duplicate phrasings, all repeating "turn"+"off" together --
        "turn the volume off", "turn off the volume", "turn my volume
        off", "volume off") gave "turn"+"off" enough combined term-
        frequency weight in TOGGLE_MUTE's own tf-idf vector that ANY
        query containing just "turn"+"off", with every other word
        completely out-of-vocabulary, scored ~0.535 cosine similarity
        against TOGGLE_MUTE -- clearing CONFIDENCE_THRESHOLD (0.5) on
        those two words alone and auto-dispatching to mute (zero
        required slots, no confirmation) for requests that have nothing
        to do with volume at all. Confirmed directly against every
        phrasing parametrized here under that version.

        This is the collision the "shut up" fix never had to worry
        about: "shut" is a rare word that essentially never attaches to
        unrelated nouns in natural English, but "off" is generic enough
        to appear in a huge number of legitimate, unsupported requests
        ("turn off wifi", "turn off my monitor", ...). The final fix
        (three phrasings instead of four, no duplicate "turn my volume
        off" entry) keeps the original bug fixed while keeping
        "turn"+"off" alone below threshold -- these must all still miss
        the graph and fall through to the LLM/ask path, exactly as they
        did before this fix touched anything, never a confident
        TOGGLE_MUTE dispatch.
        """
        result = router.classify(text)
        assert result is None, (
            f"{text!r} -> {result}; must miss the graph entirely (fall "
            f"through to LLM/ask), never confidently dispatch to "
            f"TOGGLE_MUTE just because it contains \"turn\"+\"off\" with "
            f"no other real signal in the query"
        )


# ─── BETA 0.3.27: clipboard read/write confusion ────────────────────────
# "can u tell me whats on my clipboard" (a READ request) routed to
# SET_CLIPBOARD (a WRITE). Root cause: "clipboard" was the only word
# shared with either command's vocabulary, and SET_CLIPBOARD's phrasings
# repeated it more densely relative to their few other words. Fixed by
# giving GET_CLIPBOARD real vocabulary on "whats"/"tell", the words that
# actually carried this query.

class TestClipboardReadVsWrite:
    @pytest.mark.parametrize("text", [
        "can u tell me whats on my clipboard",
        "show what is on my clipboard",
        "whats on my clipboard",
    ])
    def test_clipboard_read_phrasing_routes_to_get(self, router, text):
        result = router.classify(text)
        assert result == {"intent": "GET_CLIPBOARD"}, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text", [
        "copy this text to the clipboard",
        "set my clipboard to hello",
        "put this on the clipboard",
    ])
    def test_clipboard_write_phrasing_still_routes_to_set(self, router, text):
        # Guard against overcorrecting: GET_CLIPBOARD's new vocabulary
        # must not steal SET_CLIPBOARD's own legitimate write phrasings.
        result = router.classify(text)
        assert result == {"intent": "SET_CLIPBOARD"}, f"{text!r} -> {result}"


# ─── BETA 0.3.27: read-only lookalikes shadowing real write commands ────
# "stop the print spooler service" -> FIND_SERVICE, "reset network
# adapter" -> NETWORK_INFO, "format the usb drive" -> LIST_USB_DEVICES --
# all three are zero/low-slot READS that share their noun vocabulary
# (service/network/usb) with a genuinely different WRITE action the user
# asked for. NETWORK_INFO/LIST_USB_DEVICES have zero required slots, so
# they auto-dispatched a harmless-but-wrong read silently. Fixed with a
# guard: a read-only lookalike win is discarded (falls through) if the
# query also uses a write/action verb not in that command's own
# vocabulary.

class TestReadOnlyLookalikesDontShadowWriteVerbs:
    @pytest.mark.parametrize("text", [
        "stop the print spooler service",
        "reset network adapter",
        "format the usb drive",
    ])
    def test_write_verb_on_readonly_lookalike_falls_through(self, router, text):
        result = router.classify(text)
        assert result is None, (
            f"{text!r} -> {result}; a write verb paired with a read-only "
            f"lookalike's noun must fall through (to WCL/LLM), not "
            f"silently dispatch the wrong read"
        )

    @pytest.mark.parametrize("text", [
        "find the print spooler service",
        "show my network info",
        "list usb devices",
    ])
    def test_genuine_readonly_phrasing_still_dispatches(self, router, text):
        # Guard against overcorrecting: legitimate read-only phrasing for
        # these same three commands must still work.
        result = router.classify(text)
        assert result is not None, f"{text!r} -> {result}; expected a hit"


# ─── New feature: SORT_FOLDER_BY_TYPE / CLEAN_CLIPBOARD ────────────────────
# Pins that the two new everyday-productivity Tier A intents added to
# tier_a_commands.json / tier_a_phrasings.py actually resolve through the
# real, rebuilt graph -- not just that the Python dict lookups work.

class TestSortFolderByTypeAndCleanClipboardHits:
    @pytest.mark.parametrize("text,expected_intent", [
        ("sort my desktop by type", "SORT_FOLDER_BY_TYPE"),
        ("organize my desktop", "SORT_FOLDER_BY_TYPE"),
        ("organize my downloads folder by type", "SORT_FOLDER_BY_TYPE"),
    ])
    def test_known_good_hit(self, router, text, expected_intent):
        result = router.classify(text)
        assert result == {"intent": expected_intent}, f"{text!r} -> {result}"


# ─── New feature: SAVE_CLIPBOARD_TO_FILE / GENERATE_QR_CODE / SCAN_QR_CODE ──
# Same pattern as the class above: pins that the 3 new intents added this
# session (graph_source_data/tier_a_commands.json + tier_a_phrasings.py)
# actually resolve through the real, rebuilt graph -- not just that
# extract_slots()/ToolDispatcher's own Python-level tests pass. Manually
# spot-checked against this exact rebuilt toki_graph_db before writing
# these as permanent tests (see this session's own notes).

class TestClipboardFileAndQrCodeHits:
    @pytest.mark.parametrize("text,expected_intent", [
        ("turn this into a markdown file", "SAVE_CLIPBOARD_TO_FILE"),
        ("save what i copied as a md file", "SAVE_CLIPBOARD_TO_FILE"),
        ("save my clipboard as a text file", "SAVE_CLIPBOARD_TO_FILE"),
        ("put the clipboard into a file", "SAVE_CLIPBOARD_TO_FILE"),
        ("make a qr code for this", "GENERATE_QR_CODE"),
        ("generate a qr code", "GENERATE_QR_CODE"),
        ("turn this into a qr code", "GENERATE_QR_CODE"),
        ("qr code this", "GENERATE_QR_CODE"),
        ("scan this qr code", "SCAN_QR_CODE"),
        ("read this qr code", "SCAN_QR_CODE"),
        ("whats in this qr code", "SCAN_QR_CODE"),
        ("decode this qr code", "SCAN_QR_CODE"),
    ])
    def test_known_good_hit(self, router, text, expected_intent):
        result = router.classify(text)
        assert result == {"intent": expected_intent}, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text", [
        "scan this document",       # a real, different, older intent word
                                     # ("scan") must not get pulled toward
                                     # SCAN_QR_CODE just because "scan" is
                                     # in its vocabulary now
        "make a copy of this file",  # generic "copy"/"make" should not
                                      # drift toward the new clipboard/QR
                                      # vocabulary
    ])
    def test_lookalikes_do_not_get_pulled_toward_the_new_intents(self, router, text):
        result = router.classify(text)
        assert result not in (
            {"intent": "SAVE_CLIPBOARD_TO_FILE"},
            {"intent": "GENERATE_QR_CODE"},
            {"intent": "SCAN_QR_CODE"},
        ), f"{text!r} -> {result}; a lookalike phrase was pulled into a new intent"
