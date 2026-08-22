"""
test_file_grouping.py -- pins file_grouping.py's GROUP_FILES_BY_EXTENSION
(BETA 0.3.44, checkpoint 4's second half): "put all the pdfs and json
files in a new folder named rezero".

Real tmp_path directories and real shutil.move, same approach as
test_file_graph.py -- see that file's own docstring, and
test_file_index.py's `sandbox` fixture, for why this is possible (no
PowerShell subprocess in the loop) and how the sandbox-root monkeypatch
pattern works.
"""

import extractor
import pytest

from file_grouping import group_files_by_extension, _unique_destination


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    desktop = tmp_path / "Desktop"
    d_drive = tmp_path / "DDrive"
    desktop.mkdir()
    d_drive.mkdir()
    monkeypatch.setattr(extractor, "get_sandbox_roots",
                         lambda: [str(d_drive), str(desktop)])
    return desktop


class TestGroupFilesByExtension:
    def test_moves_matching_files_into_new_folder(self, sandbox):
        (sandbox / "a.pdf").write_text("x")
        (sandbox / "b.json").write_text("x")
        (sandbox / "c.txt").write_text("x")  # should NOT be moved

        msg = group_files_by_extension(str(sandbox), [".pdf", ".json"], "rezero")

        dest = sandbox / "rezero"
        assert (dest / "a.pdf").exists()
        assert (dest / "b.json").exists()
        assert not (sandbox / "a.pdf").exists()
        assert (sandbox / "c.txt").exists()  # left in place
        assert "2" in msg
        assert "rezero" in msg

    def test_creates_folder_if_it_does_not_exist(self, sandbox):
        (sandbox / "a.pdf").write_text("x")
        assert not (sandbox / "brandnew").exists()
        group_files_by_extension(str(sandbox), [".pdf"], "brandnew")
        assert (sandbox / "brandnew").is_dir()
        assert (sandbox / "brandnew" / "a.pdf").exists()

    def test_uses_existing_folder_if_it_already_exists(self, sandbox):
        (sandbox / "archive").mkdir()
        (sandbox / "archive" / "already_here.pdf").write_text("x")
        (sandbox / "new.pdf").write_text("x")
        group_files_by_extension(str(sandbox), [".pdf"], "archive")
        assert (sandbox / "archive" / "already_here.pdf").exists()
        assert (sandbox / "archive" / "new.pdf").exists()

    def test_no_matching_files_reports_that_plainly(self, sandbox):
        (sandbox / "a.txt").write_text("x")
        msg = group_files_by_extension(str(sandbox), [".pdf"], "rezero")
        assert "no" in msg.lower()
        assert not (sandbox / "rezero").exists()

    def test_only_moves_loose_files_not_files_in_subfolders(self, sandbox):
        (sandbox / "Sub").mkdir()
        (sandbox / "Sub" / "nested.pdf").write_text("x")
        (sandbox / "loose.pdf").write_text("x")
        group_files_by_extension(str(sandbox), [".pdf"], "rezero")
        assert (sandbox / "Sub" / "nested.pdf").exists()
        assert (sandbox / "rezero" / "loose.pdf").exists()

    def test_deduplicates_on_name_collision(self, sandbox):
        (sandbox / "rezero").mkdir()
        (sandbox / "rezero" / "a.pdf").write_text("pre-existing")
        (sandbox / "a.pdf").write_text("new one")
        group_files_by_extension(str(sandbox), [".pdf"], "rezero")
        assert (sandbox / "rezero" / "a.pdf").read_text() == "pre-existing"
        assert (sandbox / "rezero" / "a (1).pdf").read_text() == "new one"

    def test_outside_sandbox_source_is_refused(self):
        msg = group_files_by_extension("/definitely/not/sandboxed", [".pdf"], "rezero")
        assert "sandbox" in msg.lower()

    def test_missing_source_folder_reports_that_plainly(self, sandbox):
        msg = group_files_by_extension(str(sandbox / "NoSuchFolder"), [".pdf"], "rezero")
        assert "couldn't find" in msg.lower()

    def test_extension_matching_is_case_insensitive(self, sandbox):
        (sandbox / "A.PDF").write_text("x")
        group_files_by_extension(str(sandbox), [".pdf"], "rezero")
        assert (sandbox / "rezero" / "A.PDF").exists()


class TestUniqueDestination:
    def test_no_conflict_returns_plain_path(self, tmp_path):
        assert _unique_destination(str(tmp_path), "a.pdf") == str(tmp_path / "a.pdf")

    def test_conflict_appends_counter(self, tmp_path):
        (tmp_path / "a.pdf").write_text("x")
        assert _unique_destination(str(tmp_path), "a.pdf") == str(tmp_path / "a (1).pdf")
