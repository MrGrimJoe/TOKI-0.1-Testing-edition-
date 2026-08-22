"""
test_file_graph.py -- pins file_graph/ (BETA 0.3.44, checkpoint 4: the
graph-based file organizer).

Uses REAL temporary directories and REAL file moves (shutil.move, not a
mocked PowerShell template) for organizer.py's end-to-end tests -- same
"actually run it, don't just read the docstring" approach
tests/test_file_index.py already established for extractor.FileIndex,
and possible here specifically because this feature moves files via
plain Python stdlib, not a PowerShell subprocess. Sandbox roots are
monkeypatched to the tmp_path tree via extractor.get_sandbox_roots(),
same fixture pattern as test_file_index.py's own `sandbox` fixture.

FileGraphStore tests use a REAL Kùzu database in a tmp_path directory
(kuzu is already a hard dependency of this app, not optional here) --
no mocking of the Kùzu layer itself, only of things outside this app's
control.
"""

import os
import time

import pytest

import extractor
from file_graph.metadata import extract_metadata, tokenize_name, tokenize_text
from file_graph.scoring import (
    DEFAULT_WEIGHTS, build_folder_profile, score_candidate,
)
from file_graph.store import FileGraphStore
from file_graph.organizer import FileOrganizer, _unique_destination


# ─── metadata.py ────────────────────────────────────────────────────────

class TestTokenizeName:
    def test_splits_on_separators_and_lowercases(self):
        assert tokenize_name("Physics_Chapter_4") == frozenset({"physics", "chapter", "4"})

    def test_splits_camel_case(self):
        assert "physics" in tokenize_name("PhysicsNotes")
        assert "notes" in tokenize_name("PhysicsNotes")

    def test_drops_generic_filler_words(self):
        toks = tokenize_name("Untitled_Copy_Final")
        assert toks == frozenset()

    def test_drops_single_character_tokens(self):
        assert "a" not in tokenize_name("a_report")
        assert "report" in tokenize_name("a_report")

    def test_keeps_numbers(self):
        assert "4" in tokenize_name("Chapter_4")


class TestTokenizeText:
    def test_returns_lowercase_tokens(self):
        toks = tokenize_text("Newton's Laws of Motion describe how objects move")
        assert "newton" in toks or "newtons" in toks
        assert "laws" in toks

    def test_caps_to_limit(self):
        text = " ".join(f"word{i}" for i in range(200))
        toks = tokenize_text(text, limit=10)
        assert len(toks) <= 10


class TestExtractMetadata:
    def test_returns_none_for_missing_path(self, tmp_path):
        assert extract_metadata(str(tmp_path / "nope.txt")) is None

    def test_basic_fields(self, tmp_path):
        f = tmp_path / "Physics_Chapter_4.pdf"
        f.write_bytes(b"%PDF-1.4 fake pdf bytes")
        fm = extract_metadata(str(f))
        assert fm is not None
        assert fm.name == "Physics_Chapter_4.pdf"
        assert fm.ext == ".pdf"
        assert fm.stem == "Physics_Chapter_4"
        assert "physics" in fm.name_tokens
        assert "chapter" in fm.name_tokens
        assert fm.size == len(b"%PDF-1.4 fake pdf bytes")

    def test_reads_text_tokens_for_text_readable_ext(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Photosynthesis converts sunlight into chemical energy")
        fm = extract_metadata(str(f))
        assert "photosynthesis" in fm.text_tokens

    def test_no_text_tokens_for_binary_like_ext(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0fake jpeg bytes")
        fm = extract_metadata(str(f))
        assert fm.text_tokens == frozenset()

    def test_content_hash_is_stable_for_same_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical content here")
        f2.write_text("identical content here")
        fm1 = extract_metadata(str(f1))
        fm2 = extract_metadata(str(f2))
        assert fm1.content_hash == fm2.content_hash
        assert fm1.content_hash is not None

    def test_content_hash_differs_for_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("some content")
        f2.write_text("totally different content entirely")
        fm1 = extract_metadata(str(f1))
        fm2 = extract_metadata(str(f2))
        assert fm1.content_hash != fm2.content_hash


# ─── scoring.py ─────────────────────────────────────────────────────────

def _fm(name, mtime=None, text=None):
    """Builds a real FileMetadata via a throwaway tmp file -- avoids
    hand-constructing the dataclass with fields that could drift out of
    sync with extract_metadata()'s own field-population logic. Content
    defaults to something UNIQUE per filename (not a fixed placeholder)
    so unrelated test files never accidentally collide on content_hash
    -- that evidence type is intentionally powerful (see
    TestScoreCandidate::test_content_hash_duplicate_is_a_near_lock), so
    two fixture files sharing the same generic placeholder text would
    silently trigger it and contaminate unrelated tests. Pass an
    explicit `text` when a test actually wants shared/duplicate content."""
    import tempfile
    d = tempfile.mkdtemp()
    path = os.path.join(d, name)
    with open(path, "w") as f:
        f.write(text if text is not None else f"placeholder content for {name}")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return extract_metadata(path)


class TestBuildFolderProfile:
    def test_empty_files_produces_empty_profile(self):
        profile = build_folder_profile("/some/folder", [])
        assert profile.file_count == 0
        assert profile.most_recent_mtime is None

    def test_aggregates_name_tokens_across_files(self):
        files = [_fm("Physics_Chapter_1.pdf"), _fm("Physics_Chapter_2.pdf")]
        profile = build_folder_profile("/School/Physics", files)
        assert profile.name_token_counts["physics"] == 2
        assert profile.file_count == 2


class TestScoreCandidate:
    def test_no_evidence_gives_zero_confidence(self):
        # mtimes deliberately far apart (well beyond the 90-day
        # recent_activity window) so timing coincidence can't
        # contaminate this "truly nothing in common" case.
        now = time.time()
        loose = _fm("Vacation_Photo.jpg", mtime=now)
        folder = build_folder_profile("/Random", [_fm("Tax_Return_2023.pdf", mtime=now - 200 * 86400)])
        c = score_candidate(loose, folder)
        assert c.confidence == 0.0
        assert c.band == "skip"

    def test_strong_filename_and_related_group_gives_high_confidence(self):
        # Loose file's own name is a clean SUBSET of the folder's
        # existing vocabulary (no extra distinguishing token of its own,
        # e.g. no per-chapter number that couldn't already exist among
        # its siblings) -- see file_graph's own test suite
        # (test_file_graph.py's TestFileOrganizerEndToEnd) for the more
        # realistic "partial match" case and why that one correctly
        # lands in the suggest band instead.
        now = time.time()
        existing = [
            _fm(f"Physics_Chapter_{i}.pdf", mtime=now - 3600) for i in range(1, 9)
        ]
        folder = build_folder_profile("/School/Physics", existing)
        loose = _fm("Physics.pdf", mtime=now)
        c = score_candidate(loose, folder)
        assert c.confidence >= 90.0
        assert c.band == "auto"
        assert any("physics" in b.lower() for b in c.explanation)
        assert any("related" in b.lower() for b in c.explanation)

    def test_content_hash_duplicate_is_a_near_lock(self):
        existing = [_fm("Report_Draft.docx", text="the exact same content")]
        folder = build_folder_profile("/Reports", existing)
        loose = _fm("Report_Draft_Copy.docx", text="the exact same content")
        c = score_candidate(loose, folder)
        assert "content_hash_duplicate" in c.evidence
        assert any("identical" in b.lower() for b in c.explanation)

    def test_weak_single_signal_stays_below_auto_band(self):
        # Only extension_match fires (shared .pdf, nothing else in common)
        # -- mtimes deliberately far apart so recent_activity can't also
        # sneak in as a second, contaminating signal. One weak solo
        # signal alone should not reach the 90% auto band.
        now = time.time()
        existing = [_fm("Unrelated_Report.pdf", mtime=now - 200 * 86400)]
        folder = build_folder_profile("/Docs", existing)
        loose = _fm("Something_Else.pdf", mtime=now)
        c = score_candidate(loose, folder)
        assert c.band != "auto"

    def test_missing_evidence_types_are_not_penalized(self):
        # A folder with no text-readable files shouldn't be scored as if
        # extracted_text_overlap were present-and-zero.
        existing = [_fm(f"Vacation_{i}.jpg") for i in range(1, 5)]
        folder = build_folder_profile("/Photos", existing)
        loose = _fm("Vacation_5.jpg")
        c = score_candidate(loose, folder)
        assert "extracted_text_overlap" not in c.evidence

    def test_custom_weights_are_honored(self):
        existing = [_fm("Report_A.pdf")]
        folder = build_folder_profile("/Docs", existing)
        loose = _fm("Report_B.pdf")
        zeroed = {k: 0.0 for k in DEFAULT_WEIGHTS}
        c = score_candidate(loose, folder, weights=zeroed)
        assert c.confidence == 0.0


# ─── store.py ───────────────────────────────────────────────────────────

class TestFileGraphStore:
    def test_load_weights_returns_defaults_for_fresh_store(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        weights = store.load_weights()
        assert weights == DEFAULT_WEIGHTS
        store.close()

    def test_record_feedback_increases_weight_on_accept(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        before = store.load_weights()["filename_similarity"]
        store.record_feedback(["filename_similarity"], accepted=True)
        after = store.load_weights()["filename_similarity"]
        assert after > before
        store.close()

    def test_record_feedback_decreases_weight_on_reject(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        before = store.load_weights()["filename_similarity"]
        store.record_feedback(["filename_similarity"], accepted=False)
        after = store.load_weights()["filename_similarity"]
        assert after < before
        store.close()

    def test_weights_persist_across_store_instances(self, tmp_path):
        db_path = tmp_path / "fg_db"
        store1 = FileGraphStore(db_path=db_path)
        store1.record_feedback(["extension_match"], accepted=True)
        store1.close()

        store2 = FileGraphStore(db_path=db_path)
        weights = store2.load_weights()
        assert weights["extension_match"] > DEFAULT_WEIGHTS["extension_match"]
        store2.close()

    def test_weight_never_exceeds_max_after_repeated_accepts(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        for _ in range(500):
            store.record_feedback(["content_hash_duplicate"], accepted=True)
        assert store.load_weights()["content_hash_duplicate"] <= 3.0
        store.close()

    def test_weight_never_below_min_after_repeated_rejects(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        for _ in range(500):
            store.record_feedback(["recent_activity"], accepted=False)
        assert store.load_weights()["recent_activity"] >= 0.05
        store.close()

    def test_log_decision_never_raises(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        store.log_decision("/a/b.pdf", "/a/School", 94.0, "auto", accepted=True)
        store.close()

    def test_record_feedback_with_empty_list_is_a_noop(self, tmp_path):
        store = FileGraphStore(db_path=tmp_path / "fg_db")
        before = store.load_weights()
        store.record_feedback([], accepted=True)
        assert store.load_weights() == before
        store.close()

    def test_load_weights_fails_soft_if_kuzu_import_fails(self, tmp_path, monkeypatch):
        store = FileGraphStore(db_path=tmp_path / "fg_db")

        def _boom():
            raise RuntimeError("kuzu not installed")

        monkeypatch.setattr(store, "_connection", _boom)
        assert store.load_weights() == DEFAULT_WEIGHTS


# ─── organizer.py (end-to-end, real filesystem) ──────────────────────────

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Same shape as test_file_index.py's own `sandbox` fixture --
    monkeypatches get_sandbox_roots() to a real tmp_path tree so
    is_within_sandbox() (checked by organizer.py before every move)
    accepts these test paths."""
    desktop = tmp_path / "Desktop"
    d_drive = tmp_path / "DDrive"
    desktop.mkdir()
    d_drive.mkdir()
    monkeypatch.setattr(extractor, "get_sandbox_roots",
                         lambda: [str(d_drive), str(desktop)])
    return desktop


def _touch(path, content=None, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content is not None else f"placeholder content for {path.name}")
    if mtime is not None:
        os.utime(str(path), (mtime, mtime))


class TestFileOrganizerEndToEnd:
    def test_nothing_loose_reports_that_plainly(self, sandbox, tmp_path):
        (sandbox / "School" / "Physics").mkdir(parents=True)
        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize(str(sandbox))
        assert "nothing loose" in msg.lower()

    def test_no_candidate_folders_reports_that_plainly(self, sandbox, tmp_path):
        _touch(sandbox / "Physics_Chapter_4.pdf")
        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize(str(sandbox))
        assert "never invent" in msg.lower()

    def test_high_confidence_file_is_actually_moved(self, sandbox, tmp_path):
        # A loose file whose name is a clean SUBSET of what's already in
        # the candidate folder (no extra distinguishing token of its own,
        # e.g. no per-chapter number that couldn't possibly already
        # exist among its siblings) -- filename_similarity hits 1.0,
        # combined with extension_match/shared_topic_group/recent_activity
        # all firing near-perfectly, clears the 90% auto band cleanly.
        now = time.time()
        for i in range(1, 9):
            _touch(sandbox / "School" / "Physics" / f"Physics_Chapter_{i}.pdf",
                   mtime=now - 3600)
        loose = sandbox / "Physics.pdf"
        _touch(loose, mtime=now)

        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize(str(sandbox))

        dest = sandbox / "School" / "Physics" / "Physics.pdf"
        assert dest.exists()
        assert not loose.exists()
        assert "organized automatically" in msg.lower()
        assert "physics" in msg.lower()

    def test_realistic_partial_match_lands_in_suggest_band_not_auto(self, sandbox, tmp_path):
        # The more realistic case: the loose file has its OWN
        # distinguishing token (chapter 9) that couldn't already exist
        # among the 8 sibling files (1-8) -- a partial, not perfect,
        # filename match. This should be a genuine, explainable
        # suggestion, not silently auto-moved.
        now = time.time()
        for i in range(1, 9):
            _touch(sandbox / "School" / "Physics" / f"Physics_Chapter_{i}.pdf",
                   mtime=now - 3600)
        loose = sandbox / "Physics_Chapter_9.pdf"
        _touch(loose, mtime=now)

        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize(str(sandbox), include_suggestions=False)

        assert loose.exists()  # not auto-moved
        assert "not confident enough" in msg.lower()
        assert "physics" in msg.lower()

        # Re-running WITH include_suggestions=True should actually apply it.
        msg2 = org.organize(str(sandbox), include_suggestions=True)
        assert not loose.exists()
        assert (sandbox / "School" / "Physics" / "Physics_Chapter_9.pdf").exists()
        assert "organized automatically" in msg2.lower()


    def test_unrelated_file_is_left_alone(self, sandbox, tmp_path):
        _touch(sandbox / "School" / "Physics" / "Physics_Chapter_1.pdf")
        loose = sandbox / "Vacation_Selfie.jpg"
        _touch(loose)

        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize(str(sandbox))

        assert loose.exists()
        assert "left alone" in msg.lower()

    def test_outside_sandbox_path_is_refused(self, sandbox, tmp_path):
        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        msg = org.organize("/definitely/not/in/sandbox")
        assert "sandbox" in msg.lower()

    def test_never_overwrites_existing_file_at_destination(self, sandbox, tmp_path):
        now = time.time()
        for i in range(1, 9):
            _touch(sandbox / "School" / "Physics" / f"Physics_Chapter_{i}.pdf", mtime=now - 3600)
        # A file ALREADY sitting at the exact destination name.
        _touch(sandbox / "School" / "Physics" / "Physics_Chapter_9.pdf",
               content="pre-existing content")
        loose = sandbox / "Physics_Chapter_9.pdf"
        _touch(loose, content="new content", mtime=now)

        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        org.organize(str(sandbox))

        original = sandbox / "School" / "Physics" / "Physics_Chapter_9.pdf"
        deduped = sandbox / "School" / "Physics" / "Physics_Chapter_9 (1).pdf"
        assert original.read_text() == "pre-existing content"
        assert deduped.exists()
        assert deduped.read_text() == "new content"

    def test_nested_candidate_folder_is_discovered(self, sandbox, tmp_path):
        # Candidate folders can sit more than one level below the scan
        # root (the design doc's own "School/Physics/" example) -- not
        # just immediate children of the scan root.
        now = time.time()
        for i in range(1, 9):
            _touch(sandbox / "School" / "Physics" / f"Physics_Notes_{i}.pdf", mtime=now - 3600)
        loose = sandbox / "Physics_Notes.pdf"
        _touch(loose, mtime=now)

        org = FileOrganizer(store=FileGraphStore(db_path=tmp_path / "fg_db"))
        org.organize(str(sandbox))
        assert (sandbox / "School" / "Physics" / "Physics_Notes.pdf").exists()

    def test_accepted_move_reinforces_weights(self, sandbox, tmp_path):
        now = time.time()
        for i in range(1, 9):
            _touch(sandbox / "School" / "Physics" / f"Physics_Chapter_{i}.pdf", mtime=now - 3600)
        _touch(sandbox / "Physics.pdf", mtime=now)

        store = FileGraphStore(db_path=tmp_path / "fg_db")
        before = store.load_weights()["filename_similarity"]
        org = FileOrganizer(store=store)
        org.organize(str(sandbox))
        after = store.load_weights()["filename_similarity"]
        assert after > before


class TestUniqueDestination:
    def test_returns_original_when_no_conflict(self, tmp_path):
        assert _unique_destination(str(tmp_path), "a.txt") == str(tmp_path / "a.txt")

    def test_appends_counter_on_conflict(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        result = _unique_destination(str(tmp_path), "a.txt")
        assert result == str(tmp_path / "a (1).txt")

    def test_increments_past_multiple_conflicts(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "a (1).txt").write_text("x")
        result = _unique_destination(str(tmp_path), "a.txt")
        assert result == str(tmp_path / "a (2).txt")
