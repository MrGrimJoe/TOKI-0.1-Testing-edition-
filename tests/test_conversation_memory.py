"""
test_conversation_memory.py -- unit tests for the 10-turn rolling
keyword memory (see conversation_memory.py's module docstring for the
full design rationale: why this is separate from orchestrator.py's
self.history and _last_touched, the FIFO window, and the persistent
JSONL log that survives eviction from the active window).
"""

import json

import pytest

from conversation_memory import ConversationMemory


@pytest.fixture
def memory(tmp_path):
    """Fresh instance per test, logging to a throwaway file so tests
    never touch the real conversation_memory.jsonl or leak state into
    each other."""
    return ConversationMemory(log_path=tmp_path / "conversation_memory.jsonl")


class TestFIFOWindow:
    def test_window_starts_empty(self, memory):
        assert memory.get_window() == []
        assert memory.get_recent_topic_context() is None

    def test_ten_turns_all_stay_in_window(self, memory):
        for i in range(10):
            memory.record(f"message {i}", intent=None)
        assert len(memory.get_window()) == 10
        assert memory.get_window()[0]["user_prompt"] == "message 0"
        assert memory.get_window()[-1]["user_prompt"] == "message 9"

    def test_eleventh_turn_evicts_the_first_from_the_active_window(self, memory):
        for i in range(11):
            memory.record(f"message {i}", intent=None)
        window = memory.get_window()
        assert len(window) == 10
        # turn 0 ("message 0") must be GONE from the active window...
        prompts = [e["user_prompt"] for e in window]
        assert "message 0" not in prompts
        assert "message 1" in prompts
        assert "message 10" in prompts

    def test_turn_numbers_are_monotonic_and_never_reused(self, memory):
        for i in range(15):
            memory.record(f"message {i}", intent=None)
        window = memory.get_window()
        turn_numbers = [e["turn"] for e in window]
        # 15 turns recorded, window holds the last 10 -> turns 6..15
        assert turn_numbers == list(range(6, 16))


class TestPersistentLogSurvivesEviction:
    """The core "but everything gets recorded to the log so i can fix
    anything broken" requirement -- turns that have already fallen out
    of the active 10-turn window must still be readable from the JSONL
    log."""

    def test_every_turn_is_logged_even_after_eviction(self, memory, tmp_path):
        for i in range(15):
            memory.record(f"message {i}", intent=None)

        log_path = tmp_path / "conversation_memory.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 15

        records = [json.loads(l) for l in lines]
        prompts = [r["user_prompt"] for r in records]
        # "message 0" is long gone from the active window (see above)
        # but must still be in the log.
        assert "message 0" in prompts
        assert "message 14" in prompts

    def test_log_records_have_the_documented_shape(self, memory, tmp_path):
        memory.record("delete the sales report", intent="DELETE_ITEM")
        log_path = tmp_path / "conversation_memory.jsonl"
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["turn"] == 1
        assert "timestamp" in record
        assert record["user_prompt"] == "delete the sales report"
        assert record["intent"] == "DELETE_ITEM"
        assert isinstance(record["keywords"], list)
        assert "delete" in record["keywords"]

    def test_log_is_append_only_across_multiple_instances(self, tmp_path):
        # Simulates two separate sessions (e.g. TOKI restarted) sharing
        # the same log path -- the log itself is meant to accumulate
        # across restarts even though each ConversationMemory instance's
        # own active window and turn counter start fresh.
        log_path = tmp_path / "conversation_memory.jsonl"
        m1 = ConversationMemory(log_path=log_path)
        m1.record("first session message", intent=None)
        m2 = ConversationMemory(log_path=log_path)
        m2.record("second session message", intent=None)

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_a_broken_log_path_never_raises(self, memory, monkeypatch):
        # Logging is diagnostic, never load-bearing (same posture as
        # OllamaRouter._log_timing()) -- a write failure must not break
        # the turn it's describing.
        import conversation_memory as cm

        broken = cm.ConversationMemory(log_path="/nonexistent/deeply/nested/path.jsonl")
        broken.record("this should not raise", intent=None)  # must not raise
        assert len(broken.get_window()) == 1


class TestKeywordExtraction:
    def test_uses_the_same_content_words_as_graph_router(self, memory):
        # Consistency with the rest of the app's vocabulary handling --
        # this deliberately reuses graph_router.normalize/content_words
        # rather than its own tokenizer. normalize() strips punctuation
        # (including the ".xlsx" extension's dot), same as it does for
        # every real Tier A query -- "sales_report.xlsx" becomes
        # "sales_report" here for exactly that reason, not a bug in this
        # module.
        memory.record("please delete the sales_report.xlsx file", intent="DELETE_ITEM")
        keywords = memory.get_window()[0]["keywords"]
        assert "delete" in keywords
        assert "sales_report" in keywords
        # stopwords ("please", "the") must not appear
        assert "please" not in keywords
        assert "the" not in keywords

    def test_pure_filler_produces_empty_keywords_without_raising(self, memory):
        memory.record("thanks", intent=None)
        # "thanks" isn't a stopword but also isn't nonsense -- either way
        # this must not raise, and the record must still exist.
        assert len(memory.get_window()) == 1


class TestGetRecentTopicContext:
    def test_none_when_nothing_recorded(self, memory):
        assert memory.get_recent_topic_context() is None

    def test_none_when_all_recent_turns_have_no_keywords(self, memory, monkeypatch):
        import conversation_memory as cm
        monkeypatch.setattr(cm, "content_words", lambda *_: set())
        memory.record("uh", intent=None)
        memory.record("um", intent=None)
        assert memory.get_recent_topic_context() is None

    def test_contains_keywords_from_recent_turns(self, memory):
        memory.record("let's talk about the sales report", intent=None)
        memory.record("delete it", intent="DELETE_ITEM")
        context = memory.get_recent_topic_context()
        assert context is not None
        assert "sales" in context or "report" in context
        assert "delete" in context

    def test_most_recent_keywords_come_first(self, memory):
        memory.record("alpha topic", intent=None)
        memory.record("beta topic", intent=None)
        context = memory.get_recent_topic_context()
        # "beta" (most recent) should appear before "alpha" in the string
        assert context.index("beta") < context.index("alpha")

    def test_duplicate_keywords_across_turns_appear_once(self, memory):
        memory.record("delete the report", intent=None)
        memory.record("delete the other report", intent=None)
        context = memory.get_recent_topic_context()
        # "delete" and "report" each only counted once despite appearing
        # in both turns
        assert context.count("delete") == 1
        assert context.count("report") == 1

    def test_capped_length_even_with_many_dense_turns(self, memory):
        for i in range(10):
            memory.record(f"unique_word_{i} another_unique_{i}", intent=None)
        context = memory.get_recent_topic_context()
        # 10 turns * 2 unique keywords each = 20 raw candidates, under the
        # 25-word cap, so nothing should be silently dropped here --
        # this just confirms the cap doesn't fire prematurely.
        assert context.count("unique_word") == 10


class TestFindTurnsMatching:
    def test_finds_turns_sharing_a_keyword(self, memory):
        memory.record("discussing the sales report", intent=None)
        memory.record("what's the weather", intent=None)
        matches = memory.find_turns_matching({"sales"})
        assert len(matches) == 1
        assert matches[0]["user_prompt"] == "discussing the sales report"

    def test_most_recent_match_first(self, memory):
        memory.record("report number one", intent=None)
        memory.record("report number two", intent=None)
        matches = memory.find_turns_matching({"report"})
        assert len(matches) == 2
        assert matches[0]["user_prompt"] == "report number two"

    def test_empty_words_returns_nothing(self, memory):
        memory.record("anything", intent=None)
        assert memory.find_turns_matching(set()) == []

    def test_no_match_returns_empty_list(self, memory):
        memory.record("talking about cats", intent=None)
        assert memory.find_turns_matching({"dogs"}) == []
