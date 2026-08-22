"""
test_synonyms.py -- covers synonyms.py's SYNONYM_MAP/expand_synonyms/
is_matched_via_synonym in isolation, then confirms the whole thing
actually closes real out-of-vocabulary misses end-to-end through
GraphRouter (both the confident-hit path and the below-threshold
"ask" path), and that it changes NOTHING about behavior that was
already correct before this feature existed.
"""

import pytest

from synonyms import SYNONYM_MAP, expand_synonyms, is_matched_via_synonym


# ─── Unit tests: expand_synonyms / is_matched_via_synonym ──────────────

class TestExpandSynonyms:
    def test_adds_target_for_known_synonym(self):
        assert expand_synonyms({"erase"}) == {"erase", "delete"}

    def test_never_removes_the_original_word(self):
        expanded = expand_synonyms({"erase"})
        assert "erase" in expanded

    def test_word_with_no_synonym_is_unaffected(self):
        assert expand_synonyms({"banana"}) == {"banana"}

    def test_word_that_is_already_a_vocabulary_word_is_unaffected(self):
        # "delete" has no entry in SYNONYM_MAP (it IS the target, not a
        # key) -- expanding it should add nothing.
        assert expand_synonyms({"delete"}) == {"delete"}

    def test_mixed_set_expands_only_the_synonym_words(self):
        expanded = expand_synonyms({"erase", "notes", "txt"})
        assert expanded == {"erase", "delete", "notes", "txt"}

    def test_multiple_synonyms_in_one_query(self):
        # "clone" removed from SYNONYM_MAP (BETA 0.3.51: now real
        # COPY_ITEM vocabulary directly, see synonyms.py's comment) --
        # "replicate" still isn't, so it's the live example here now.
        expanded = expand_synonyms({"replicate", "transfer"})
        assert expanded == {"replicate", "copy", "transfer", "move"}

    def test_empty_set_stays_empty(self):
        assert expand_synonyms(set()) == set()

    def test_does_not_mutate_input_set(self):
        original = {"erase"}
        expand_synonyms(original)
        assert original == {"erase"}, "expand_synonyms must return a new set, not mutate its input"


class TestIsMatchedViaSynonym:
    def test_true_when_target_is_in_matched_words(self):
        assert is_matched_via_synonym("erase", {"delete"}) is True

    def test_false_when_target_is_not_in_matched_words(self):
        assert is_matched_via_synonym("erase", {"copy"}) is False

    def test_false_for_a_word_with_no_synonym_entry(self):
        assert is_matched_via_synonym("banana", {"banana"}) is False

    def test_false_for_empty_matched_words(self):
        assert is_matched_via_synonym("erase", set()) is False


class TestSynonymMapIntegrity:
    """Guards the two hand-verification properties every entry is
    supposed to satisfy (see synonyms.py's module docstring, "how
    entries were chosen") -- catches an entry silently going stale if
    TIER_A_PHRASINGS ever changes underneath it."""

    def test_no_key_is_also_a_value(self):
        # A key mapping to another key would create a hidden chain
        # (expand_synonyms only does one hop), which is never intended.
        keys = set(SYNONYM_MAP.keys())
        values = set(SYNONYM_MAP.values())
        overlap = keys & values
        assert not overlap, f"chained/self-referential synonym entries: {overlap}"

    def test_no_key_maps_to_itself(self):
        for k, v in SYNONYM_MAP.items():
            assert k != v, f"{k!r} maps to itself"

    def test_every_target_word_is_real_tier_a_vocabulary(self):
        from graph_source_data.tier_a_phrasings import TIER_A_PHRASINGS
        from graph_router import normalize, content_words

        vocab = set()
        for phrasings in TIER_A_PHRASINGS.values():
            for p in phrasings:
                vocab |= content_words(normalize(p))

        for key, target in SYNONYM_MAP.items():
            assert target in vocab, (
                f"SYNONYM_MAP[{key!r}] = {target!r}, but {target!r} is not "
                f"actually in TIER_A_PHRASINGS's vocabulary -- this entry "
                f"would silently do nothing"
            )

    def test_every_key_is_currently_absent_from_tier_a_vocabulary(self):
        # If this ever fails, someone added the key word to a real
        # phrasing directly -- harmless (the entry becomes a no-op, see
        # the module docstring), but worth knowing about rather than
        # carrying a dead entry silently.
        from graph_source_data.tier_a_phrasings import TIER_A_PHRASINGS
        from graph_router import normalize, content_words

        vocab = set()
        for phrasings in TIER_A_PHRASINGS.values():
            for p in phrasings:
                vocab |= content_words(normalize(p))

        stale = [k for k in SYNONYM_MAP if k in vocab]
        assert not stale, (
            f"these SYNONYM_MAP keys are now real TIER_A_PHRASINGS "
            f"vocabulary words already (harmless, but the comment "
            f"explaining each entry should be revisited): {stale}"
        )


# ─── Integration tests: the actual OOV misses this closes ──────────────

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


class TestSynonymClosesRealOOVMisses:
    """Each of these words is confirmed absent from TIER_A_PHRASINGS
    (see TestSynonymMapIntegrity above) -- before this feature, every
    one of these queries scored 0 confidence against every Tier A
    command (the word contributed no signal to anything). Confirms the
    fix actually lands the correct intent as a confident hit."""

    @pytest.mark.parametrize("text,expected_intent", [
        ("erase notes.txt", "DELETE_ITEM"),
        ("destroy this file", "DELETE_ITEM"),
        # "trash"/"clone"/"storage" removed from this list (BETA 0.3.51):
        # all three are now real TIER_A_PHRASINGS vocabulary directly
        # (added to DELETE_ITEM/COPY_ITEM/DISK_USAGE's own casual
        # phrasings), so "trash this folder"/"clone this folder"/"how
        # much storage is free" no longer exercise the SYNONYM_MAP path
        # this class is testing -- they're covered as direct-vocabulary
        # cases elsewhere now, and re-added here would just be testing
        # the wrong mechanism for the right answer.
        ("discard this item", "DELETE_ITEM"),
        ("replicate this file", "COPY_ITEM"),
        ("transfer this file to another location", "MOVE_ITEM"),
        ("relabel this file", "RENAME_ITEM"),
        ("locate a file called report", "FIND_FILES"),
        ("what software is installed", "LIST_INSTALLED_APPS"),
    ])
    def test_synonym_word_reaches_correct_intent(self, router, text, expected_intent):
        result = router.classify(text)
        assert result == {"intent": expected_intent}, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text,expected_intent", [
        ("trash this", "DELETE_ITEM"),
        ("clone this file", "COPY_ITEM"),
        ("hows my storage looking", "DISK_USAGE"),
    ])
    def test_now_direct_vocabulary_words_still_reach_correct_intent(self, router, text, expected_intent):
        # Companion to the SYNONYM_MAP-driven cases above: "trash",
        # "clone", and "storage" graduated from synonym-table entries to
        # real phrasing vocabulary during the BETA 0.3.51 casual-phrasing
        # expansion. This just confirms they still land correctly -- via
        # direct vocabulary now, not expand_synonyms().
        result = router.classify(text)
        assert result == {"intent": expected_intent}, f"{text!r} -> {result}"

    def test_synonym_alone_scores_zero_confidence_before_expansion(self, router):
        # Sanity check that the underlying problem is real: the RAW word
        # "erase" (not expanded) must not be in Tier A's own vocabulary,
        # i.e. it cannot appear as a scored dimension in any command's
        # tf-idf vector.
        vectors, _ = router._get_tfidf_index()
        for cmd_vec in vectors.values():
            assert "erase" not in cmd_vec

    def test_low_confidence_synonym_hit_still_asks_not_silently_misses(self, router):
        # "list my software" -> LIST_INSTALLED_APPS is the right idea but
        # stays below CONFIDENCE_THRESHOLD (LIST_INSTALLED_APPS's own
        # phrasing corpus doesn't cover this exact wording) -- this must
        # degrade to a clarifying question that correctly treats
        # "software" as understood (not "unknown"), rather than
        # auto-dispatching OR silently discarding the signal.
        #
        # BETA 0.3.51 note: this used to test "silence the volume" ->
        # TOGGLE_MUTE, but the casual-phrasing expansion that session
        # added "silence it" directly to TOGGLE_MUTE's own corpus
        # (tier_a_phrasings.py), which promoted "silence" from a
        # synonym-assisted low-confidence guess to a real, confident
        # direct hit -- a genuine improvement, not a regression, but it
        # meant "silence" stopped exercising the below-threshold path
        # this test exists to cover. "software" -> LIST_INSTALLED_APPS
        # still does.
        result = router.classify_or_ask("list my software")
        assert result.get("candidate") == "LIST_INSTALLED_APPS", result
        assert "software" not in result.get("unknown_words", []), result


class TestSynonymsDontReintroduceKnownFalsePositives:
    """Regression guard: none of the new synonym targets should make any
    of the previously-fixed false-positive cases fire again."""

    @pytest.mark.parametrize("text", [
        "clear the screen",
        "stop the music",
        "kill the lights",
        "remove this annoying popup",
        "go to the store",
    ])
    def test_known_false_positive_still_misses(self, router, text):
        result = router.classify(text)
        assert result is None, f"{text!r} -> {result}"


class TestSynonymsDontAlterActionVerbShadowGuard:
    """The read-only-lookalike action-verb guard (graph_router.py's
    _read_only_shadowed_by_action_verb) deliberately keeps using the
    ORIGINAL, un-expanded word set -- these must behave exactly as they
    did before this feature existed."""

    @pytest.mark.parametrize("text", [
        "stop the print spooler service",
        "reset network adapter",
        "format the usb drive",
    ])
    def test_write_verb_on_readonly_lookalike_still_falls_through(self, router, text):
        result = router.classify(text)
        assert result is None, f"{text!r} -> {result}"

    @pytest.mark.parametrize("text", [
        "find the print spooler service",
        "show my network info",
        "list usb devices",
    ])
    def test_genuine_readonly_phrasing_still_dispatches(self, router, text):
        result = router.classify(text)
        assert result is not None, f"{text!r} -> {result}"
