"""
test_chain_split_viability.py -- pins _split_chain_if_viable(), which
rejects a chain split unless EVERY resulting segment independently looks
like a real command to the graph. Fixes a real false-split bug:
"make a file called things, and stuff.txt" (one filename with a comma in
it) used to become ["make a file called things", "stuff.txt"] on the old
unconditional regex split.
"""

import pytest

kuzu = pytest.importorskip("kuzu")

from pathlib import Path

if not (Path(__file__).resolve().parent.parent / "toki_graph_db").exists():
    pytest.skip("toki_graph_db not present -- run migrate_to_kuzu.py first", allow_module_level=True)

from graph_router import GraphRouter
from orchestrator import _split_chain, _split_chain_if_viable


@pytest.fixture(scope="module")
def router():
    r = GraphRouter()
    yield r
    r.close()


class TestFalseSplitsAreRejected:
    def test_comma_and_inside_a_filename_is_not_split(self, router):
        text = "make a file called things, and stuff.txt"
        # Confirm the OLD unconditional splitter really would have split
        # this (i.e. the bug is real, not hypothetical) --
        assert len(_split_chain(text)) == 2
        # -- and the viability-checked version correctly rejects it.
        assert _split_chain_if_viable(text, router) == [text]

    def test_multi_target_rename_falls_back_to_one_segment(self, router):
        text = "rename a.txt to b.txt, and c.txt to d.txt"
        assert _split_chain_if_viable(text, router) == [text]


class TestRealChainsStillSplit:
    @pytest.mark.parametrize("text,expected_segments", [
        ("make a folder called Homework and then open it", 2),
        ("search the web for cats then open notepad", 2),
        ("empty the recycle bin; take a screenshot", 2),
        ("make a folder called Reports, and open it", 2),
    ])
    def test_genuine_chains_split_correctly(self, router, text, expected_segments):
        result = _split_chain_if_viable(text, router)
        assert len(result) == expected_segments

    def test_single_segment_message_unaffected(self, router):
        text = "what's the weather"
        assert _split_chain_if_viable(text, router) == [text]


class TestFailsOpenWithoutGraph:
    def test_no_graph_router_uses_unconditional_split(self):
        # Can't verify segment viability without a graph -- must behave
        # exactly like the old unconditional splitter rather than block
        # every chained message.
        text = "make a folder called Homework and then open it"
        assert _split_chain_if_viable(text, None) == _split_chain(text)


# ─── BETA 0.3.9: ",then" (zero space before "then") was silently
# unhandled ───────────────────────────────────────────────────────────────
#
# Found via a real live transcript, not synthetic: "Create a folder named
# \"python\" ,then rename it to java , then delete it" -- a genuine
# three-step chain -- only split into TWO segments because the regex
# required a space before "then" and only paired a bare comma with "and",
# never with "then". The first two steps (create + rename) silently
# merged into one garbled segment, which then classified as RENAME_ITEM
# alone -- the folder was never created, and PowerShell crashed trying to
# rename something that didn't exist. Fixed by making the comma before
# "then" optional with variable whitespace, the same way it already was
# for "and then".

class TestCommaBeforeThenIsHandled:
    def test_zero_space_before_then_still_splits(self, router):
        # The exact reported sentence, three genuine steps.
        text = 'Create a folder named "python" ,then rename it to java , then delete it'
        result = _split_chain_if_viable(text, router)
        assert len(result) == 3, (
            f"expected 3 segments (create, rename, delete), got "
            f"{result!r} -- the ',then' boundary (no space before "
            f"'then') must split just like ', then' or ' then' does"
        )

    @pytest.mark.parametrize("text", [
        "open notepad ,then open chrome",
        "open notepad, then open chrome",
        "open notepad then open chrome",
    ])
    def test_comma_then_spacing_variants_all_split_the_same_way(self, router, text):
        # All three spacing variants of the same boundary must behave
        # identically -- confirms the fix isn't accidentally narrow to
        # just the one reported sentence's exact spacing.
        result = _split_chain_if_viable(text, router)
        assert len(result) == 2


# ─── BETA 0.3.11: bare "and" (no comma, no "then") as a chain-split
# boundary ──────────────────────────────────────────────────────────────
#
# Confirmed live: "take a screenshot and also empty the recycle bin" never
# split at all -- the old regex only paired "and" with a leading comma
# (", and") or the word "then" ("and then"), so a plain " and " with
# neither was invisible to the splitter. Fixing this required MORE than
# just widening the regex, though: once bare "and" became a split
# boundary, the old viability check (which accepted a below-threshold
# classify_or_ask() "candidate" as good enough) let real two-slot
# commands get wrongly split -- e.g. "copy a.txt and b.txt to D drive"
# splits into "copy a.txt" (a real hit) and "b.txt to D drive" (no real
# hit, but a "candidate": DISK_USAGE, which the old code wrongly accepted
# as viable). _segment_is_viable() now requires a real classify() hit on
# every segment, not just a candidate -- verified this doesn't stop any
# of the genuine chains above from splitting (they all get real hits on
# both segments already).

class TestBareAndIsNowAChainBoundary:
    def test_confirmed_live_case_now_splits(self, router):
        # The exact case reported as missing.
        text = "take a screenshot and also empty the recycle bin"
        result = _split_chain_if_viable(text, router)
        assert result == ["take a screenshot", "also empty the recycle bin"]

    @pytest.mark.parametrize("text,expected_segments", [
        ("make a folder called Homework and open it", 2),
        ("empty the recycle bin and take a screenshot", 2),
    ])
    def test_other_bare_and_chains_split_correctly(self, router, text, expected_segments):
        result = _split_chain_if_viable(text, router)
        assert len(result) == expected_segments


class TestBareAndDoesNotBreakTwoSlotCommands:
    """The regression risk this fix had to specifically guard against:
    a single command with two arguments joined by "and" must NOT be
    chopped into two dispatches just because it contains the word "and".
    """

    @pytest.mark.parametrize("text", [
        "copy a.txt and b.txt to D drive",
        "rename a.txt to b.txt and c.txt to d.txt",
    ])
    def test_two_slot_commands_stay_one_segment(self, router, text):
        result = _split_chain_if_viable(text, router)
        assert result == [text], (
            f"a genuine two-argument single command got split into "
            f"{result!r} -- bare 'and' splitting must not fire on this"
        )

    def test_disk_usage_candidate_still_rejected_not_whitelisted(self, router):
        # BETA 0.3.14's whitelist fix (see _segment_is_viable) must not
        # widen acceptance beyond LAUNCH_APP/KILL_PROCESS/WAIT_FOR_PROCESS/
        # FIND_PROCESS/FIND_SERVICE -- this is the exact segment that
        # produces the DISK_USAGE candidate BETA 0.3.11 needed rejected.
        text = "copy a.txt and b.txt to D drive"
        assert _split_chain_if_viable(text, router) == [text]

    @pytest.mark.xfail(reason=(
        "Known gap, not fixed by BETA 0.3.11: a filename genuinely "
        "containing 'and' with no distinguishing punctuation (e.g. one "
        "meant literally as \"report and export.csv\") can still be "
        "wrongly split if BOTH halves happen to independently score a "
        "confident classify() hit on their own. No signal at the "
        "segment-viability layer distinguishes this from a real "
        "two-command chain. If this starts passing, either the graph's "
        "scoring changed or a smarter check (e.g. scoring the whole "
        "unsplit sentence as a competing candidate) was added -- either "
        "way, worth a STATUS.md note."
    ))
    def test_known_gap_ambiguous_and_inside_a_bare_filename(self, router):
        text = "find files named report and export.csv"
        assert _split_chain_if_viable(text, router) == [text]

    def test_known_gap_verb_plus_unrecognized_app_name_now_splits(self, router):
        # BETA 0.3.14: fixed via _segment_is_viable()'s whitelist of
        # intents whose target is deliberately outside graph vocabulary
        # by design (LAUNCH_APP, KILL_PROCESS, WAIT_FOR_PROCESS,
        # FIND_PROCESS, FIND_SERVICE) -- see that function's docstring.
        text = "close chrome and open notepad"
        result = _split_chain_if_viable(text, router)
        assert result == ["close chrome", "open notepad"]

    @pytest.mark.parametrize("text,expected_segments", [
        ("open chrome and close discord", ["open chrome", "close discord"]),
        ("stop chrome and start notepad", ["stop chrome", "start notepad"]),
        ("close notepad and open steam", ["close notepad", "open steam"]),
    ])
    def test_other_verb_plus_app_name_chains_now_split(self, router, text, expected_segments):
        assert _split_chain_if_viable(text, router) == expected_segments
