import time

from selection_context import SelectionContext, SELECTION_TTL_SECONDS


def test_set_and_get_selected(tmp_path):
    ctx = SelectionContext()
    f = tmp_path / "a.txt"
    f.write_text("hi")

    result = ctx.set_selected(str(f))
    assert result["name"] == "a.txt"
    assert result["extension"] == "txt"

    got = ctx.get_selected()
    assert got["path"] == str(f)


def test_set_selected_rejects_missing_file(tmp_path):
    ctx = SelectionContext()
    result = ctx.set_selected(str(tmp_path / "nope.txt"))
    assert result is None
    assert ctx.get_selected() is None


def test_set_selected_rejects_directory(tmp_path):
    ctx = SelectionContext()
    result = ctx.set_selected(str(tmp_path))
    assert result is None


def test_clear_removes_selection(tmp_path):
    ctx = SelectionContext()
    f = tmp_path / "a.txt"
    f.write_text("hi")
    ctx.set_selected(str(f))
    ctx.clear()
    assert ctx.get_selected() is None


def test_stale_after_file_deleted(tmp_path):
    ctx = SelectionContext()
    f = tmp_path / "a.txt"
    f.write_text("hi")
    ctx.set_selected(str(f))
    f.unlink()
    assert ctx.get_selected() is None


def test_ttl_expiry(tmp_path, monkeypatch):
    ctx = SelectionContext()
    f = tmp_path / "a.txt"
    f.write_text("hi")
    ctx.set_selected(str(f))

    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + SELECTION_TTL_SECONDS + 1)
    assert ctx.get_selected() is None


def test_new_selection_replaces_old(tmp_path):
    ctx = SelectionContext()
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("hi")
    f2.write_text("bye")

    ctx.set_selected(str(f1))
    ctx.set_selected(str(f2))
    assert ctx.get_selected()["path"] == str(f2)
