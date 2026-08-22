"""
test_file_index.py -- pins extractor.FileIndex, added in BETA 0.3.6 to
close a real gap in resolve_open_target(): step 2 of that cascade only
ever checked ONE resolved path for existence, with no fuzzy matching
against what's actually on disk (unlike step 1's app check, which already
fuzzy-matches via app_control._score_app_match).

Uses a REAL temporary directory tree monkeypatched in as the sandbox
roots -- same "actually run it, don't just read the docstring" approach
used to verify this class live before it had permanent tests. This is
pure os/ntpath code, so it runs identically on Linux (this test suite) or
Windows (where the app actually ships).
"""

import ntpath
import os

import pytest

import extractor
from extractor import FileIndex, resolve_open_target


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A real directory tree: tmp_path/Desktop/{resume.docx, notes.txt,
    Homework/essay.txt}. Monkeypatches get_sandbox_roots() to return
    [d_drive, desktop] -- the same two-element shape the real function
    returns (D:\\ at index 0, Desktop at index 1, see
    extractor.get_sandbox_roots()) -- so _default_root_for()'s roots[1]
    indexing behaves exactly like production instead of needing a
    special-cased single-root shape."""
    desktop = tmp_path / "Desktop"
    d_drive = tmp_path / "DDrive"
    (desktop / "Homework").mkdir(parents=True)
    (desktop / "resume.docx").write_text("")
    (desktop / "notes.txt").write_text("")
    (desktop / "Homework" / "essay.txt").write_text("")
    d_drive.mkdir()

    monkeypatch.setattr(extractor, "get_sandbox_roots",
                         lambda: [str(d_drive), str(desktop)])
    return desktop


class TestFileIndexScanning:
    def test_indexes_files_and_folders_under_the_sandbox(self, sandbox):
        idx = FileIndex()
        names = {e["name"] for e in idx.get_entries()}
        assert names == {"Homework", "resume.docx", "notes.txt", "essay.txt"}

    def test_marks_directories_correctly(self, sandbox):
        idx = FileIndex()
        entries = {e["name"]: e["is_dir"] for e in idx.get_entries()}
        assert entries["Homework"] is True
        assert entries["resume.docx"] is False

    def test_entries_cached_across_calls(self, sandbox):
        # Same "fetch once, reuse" contract as LocationCache/
        # _get_installed_apps -- a second get_entries() call must not
        # rescan (verified indirectly: adding a file after the first
        # call must NOT appear until invalidate() is called).
        idx = FileIndex()
        first = idx.get_entries()
        (sandbox / "late_arrival.txt").write_text("")
        second = idx.get_entries()
        assert first is second
        assert "late_arrival.txt" not in {e["name"] for e in second}

    def test_scan_failure_fails_soft_to_empty_list(self, monkeypatch):
        # A missing/unreadable root must return [], not raise -- same
        # "no apps found" and "couldn't check" collapse as
        # AppController._get_installed_apps().
        monkeypatch.setattr(extractor, "get_sandbox_roots",
                             lambda: ["/definitely/does/not/exist/anywhere"])
        idx = FileIndex()
        assert idx.get_entries() == []


class TestFileIndexMatching:
    def test_exact_match_finds_the_real_entry(self, sandbox):
        idx = FileIndex()
        match = idx.find_best_match("resume.docx")
        assert match is not None
        assert match["name"] == "resume.docx"

    def test_folder_name_matches_too(self, sandbox):
        idx = FileIndex()
        match = idx.find_best_match("homework")  # case-insensitive
        assert match is not None
        assert match["name"] == "Homework"

    def test_unrelated_query_matches_nothing(self, sandbox):
        idx = FileIndex()
        assert idx.find_best_match("xyz123nonexistent") is None

    def test_no_indexed_entries_fails_open_to_no_match(self, monkeypatch):
        monkeypatch.setattr(extractor, "get_sandbox_roots", lambda: [])
        idx = FileIndex()
        assert idx.find_best_match("anything") is None

    def test_low_confidence_typo_correctly_does_not_match(self, sandbox):
        # Honest limitation, not a bug: "resme" scores 0.47 against
        # "resume.docx" under _score_app_match's precision-first design
        # (see app_control.py's own docstring on why it's substring-first,
        # not plain fuzzy ratio) -- below the 0.72 _APP_MATCH_THRESHOLD.
        # Pinning this so a future threshold change is a deliberate
        # decision, not a silent side effect.
        idx = FileIndex()
        assert idx.find_best_match("resme") is None


# ─── BETA 0.3.10: a short query must not steamroll a short, generic
# real file/folder name ────────────────────────────────────────────────────
#
# Found live, reasoning through a real bug report: FileIndex reuses
# app_control._score_app_match, which (correctly, for app matching) scores
# short abbreviation-style queries generously. But on the FILE path, that
# means "vscode" scores 0.917 against a real folder literally named
# "Code" -- HIGHER than legitimate app matches like "chrome" vs "Google
# Chrome" (0.875) -- because a short, generic single-word file/folder
# name carries far less disambiguating signal than a full app display
# name does. This only matters when the app check fails first (apps are
# checked before files in resolve_open_target), but that's exactly what
# happened in an earlier live bug report where an app abbreviation query
# legitimately missed the (then-unfixed) app matcher and fell through to
# the file cascade.

class TestFileIndexRejectsShortGenericNameCollisions:
    def test_short_query_does_not_match_a_shorter_generic_folder(self, sandbox):
        (sandbox / "Code").mkdir()
        idx = FileIndex()
        idx.invalidate()
        assert idx.find_best_match("vscode") is None, (
            "a folder literally named 'Code' must not win against the "
            "query 'vscode' just because 'code' is a substring of it -- "
            "the matched name is SHORTER than the query, which is "
            "exactly backwards for a real abbreviation"
        )

    def test_exact_match_with_extension_still_works(self, sandbox):
        # Regression guard for a bug caught in THIS fix's own first
        # draft: comparing the extension-stripped match against the RAW
        # query (11 chars, "resume.docx") instead of the extension-
        # stripped query (6 chars, "resume") wrongly rejected this exact
        # match. Both sides must be compared on the same basis.
        idx = FileIndex()
        match = idx.find_best_match("resume.docx")
        assert match is not None
        assert match["name"] == "resume.docx"

    def test_query_without_extension_still_finds_the_real_file(self, sandbox):
        idx = FileIndex()
        match = idx.find_best_match("resume")
        assert match is not None
        assert match["name"] == "resume.docx"

    def test_legitimate_longer_match_is_unaffected(self, sandbox):
        # A real, longer folder name should still be found by a shorter
        # query, same as before this fix -- only the SHORTER-than-query
        # case is newly rejected.
        idx = FileIndex()
        match = idx.find_best_match("homework")
        assert match is not None
        assert match["name"] == "Homework"


class TestFileIndexInvalidation:
    def test_invalidate_forces_a_rescan_that_sees_new_files(self, sandbox):
        idx = FileIndex()
        idx.get_entries()  # populate cache
        (sandbox / "newfile.txt").write_text("")
        idx.invalidate()
        names = {e["name"] for e in idx.get_entries()}
        assert "newfile.txt" in names

    def test_invalidate_forces_a_rescan_that_drops_deleted_files(self, sandbox):
        idx = FileIndex()
        idx.get_entries()
        os.remove(str(sandbox / "notes.txt"))
        idx.invalidate()
        names = {e["name"] for e in idx.get_entries()}
        assert "notes.txt" not in names


# ─── Wiring into resolve_open_target's fuzzy fallback ──────────────────────

class TestFileIndexWiredIntoOpenCascade:
    def test_exact_path_check_still_wins_without_needing_the_index(self, sandbox):
        # Step 2 (plain os.path.exists) should resolve this before the
        # fuzzy fallback is ever consulted -- confirmed by NOT relying on
        # FileIndex being populated correctly to pass this case.
        result = resolve_open_target("open resume.docx", app_exists_fn=lambda n: False)
        assert result is not None
        assert result["intent"] == "OPEN_ITEM"
        assert ntpath.basename(result["path"]).lower() == "resume.docx"

    def test_fuzzy_fallback_finds_a_real_file_the_exact_check_misses(self, sandbox):
        # extractor.file_index is a module-level singleton -- reset it so
        # this test's sandbox fixture is what actually gets scanned,
        # not whatever an earlier test happened to cache.
        extractor.file_index.invalidate()
        result = resolve_open_target("open Homework", app_exists_fn=lambda n: False)
        assert result is not None
        assert result["intent"] == "OPEN_ITEM"
        assert ntpath.basename(result["path"]) == "Homework"
        extractor.file_index.invalidate()
