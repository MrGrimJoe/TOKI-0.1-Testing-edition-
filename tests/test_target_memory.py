"""
test_target_memory.py -- click-to-teach persistent store, added the same
session the feature was built. Uses a tmp_path fixture per test so nothing
here touches the real learned_targets.json next to the source.
"""

import json

from target_memory import TargetMemory


class TestTargetMemory:
    def test_miss_returns_none(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        assert mem.get("Notepad", "the save button") is None

    def test_remember_then_get_round_trips(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        identity = {"name": "Save", "control_type": "Button", "class_name": "Button"}
        mem.remember("Notepad", "the save button", identity)
        assert mem.get("Notepad", "the save button") == identity

    def test_keys_are_case_and_whitespace_insensitive(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        identity = {"name": "Save", "control_type": "Button", "class_name": "Button"}
        mem.remember("  Notepad  ", "The   Save Button", identity)
        assert mem.get("notepad", "the save button") == identity

    def test_different_windows_are_independent(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        mem.remember("Notepad", "the save button", {"name": "Save", "control_type": "Button", "class_name": "X"})
        assert mem.get("Photoshop", "the save button") is None

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "learned.json"
        identity = {"name": "Export", "control_type": "Button", "class_name": "X"}
        TargetMemory(path=path).remember("Photoshop", "the export button", identity)
        # fresh instance, same path -- must load what the first one wrote
        assert TargetMemory(path=path).get("Photoshop", "the export button") == identity

    def test_forget_removes_entry_and_reports_success(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        mem.remember("Notepad", "the save button", {"name": "Save", "control_type": "Button", "class_name": "X"})
        assert mem.forget("Notepad", "the save button") is True
        assert mem.get("Notepad", "the save button") is None

    def test_forget_on_nonexistent_entry_reports_false(self, tmp_path):
        mem = TargetMemory(path=tmp_path / "learned.json")
        assert mem.forget("Notepad", "nothing taught here") is False

    def test_corrupt_store_file_degrades_to_empty_not_a_crash(self, tmp_path):
        path = tmp_path / "learned.json"
        path.write_text("{not valid json", encoding="utf-8")
        mem = TargetMemory(path=path)
        assert mem.get("Notepad", "the save button") is None  # doesn't raise

    def test_write_failure_does_not_raise(self, tmp_path, monkeypatch):
        # Points the store at a directory that can never be a valid file
        # path (a directory, not a file) -- write must fail internally
        # without propagating, per _save()'s own "best-effort" docstring.
        bad_path = tmp_path  # a directory, not a file
        mem = TargetMemory(path=bad_path)
        mem.remember("Notepad", "the save button", {"name": "Save", "control_type": "Button", "class_name": "X"})
        # must not have raised getting here

    def test_stored_file_is_valid_json(self, tmp_path):
        path = tmp_path / "learned.json"
        mem = TargetMemory(path=path)
        mem.remember("Notepad", "the save button", {"name": "Save", "control_type": "Button", "class_name": "X"})
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and len(data) == 1
