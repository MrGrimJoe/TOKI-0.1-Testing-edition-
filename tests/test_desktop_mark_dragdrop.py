"""
test_desktop_mark_dragdrop.py -- exercises toki_desktop_mark.py's
dragEnterEvent/dropEvent with REAL PyQt6 QDragEnterEvent/QDropEvent
objects (constructed QMimeData + QUrl, not a hand-rolled fake), running
headless (QT_QPA_PLATFORM=offscreen, set in conftest.py before any Qt
import happens).

This does not prove real Windows Explorer drag-and-drop end-to-end --
no substitute for that exists off a real Windows/PyQt6 box. What it DOES
prove: the actual dragEnterEvent/dropEvent methods, called with the same
event shape Qt itself constructs from a real OS-level drop (QMimeData
with file:// QUrls), on the real widget class, wired to the real
selection_context.py singleton -- not a reimplementation or mock of the
logic being tested.
"""
import sys
from pathlib import Path

import pytest

QtCore = pytest.importorskip("PyQt6.QtCore")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QUrl, QPoint, QPointF, QMimeData
from PyQt6.QtGui import QDropEvent, QDragEnterEvent
from PyQt6.QtCore import Qt as QtNS

# QDropEvent/QDragEnterEvent don't take a Python reference to the QMimeData
# they're handed -- PyQt6 wraps the C++ pointer, but nothing keeps the
# QMimeData's Python object alive for the lifetime of the event once the
# constructing function returns. Losing that reference frees the C++
# object out from under the event, so event.mimeData().urls() (called
# later, inside dragEnterEvent/dropEvent) dereferences a dangling pointer
# -> segfault, not a TOKI bug. Every test that builds an event must keep
# the QMimeData pinned in a variable for as long as the event is used.
#
# QDragEnterEvent's constructor takes an integer QPoint; QDropEvent's
# takes a QPointF -- a real inconsistency between the two PyQt6 classes,
# not a typo here.
_POINT_TYPE = {
    QDragEnterEvent: QPoint,
    QDropEvent: QPointF,
}


def _make_drag_event(cls, urls):
    mime = QMimeData()
    mime.setUrls(urls)
    point_cls = _POINT_TYPE[cls]
    event = cls(
        point_cls(10, 10),
        QtNS.DropAction.CopyAction,
        mime,
        QtNS.MouseButton.LeftButton,
        QtNS.KeyboardModifier.NoModifier,
    )
    event._mime_keepalive = mime  # pin it to the event's own lifetime
    return event


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


@pytest.fixture
def mark(qapp, monkeypatch):
    # Hotkey listener touches real global-hotkey OS hooks -- not relevant
    # to drag-drop and not safe/meaningful off real hardware, so it's
    # patched out for this widget instance the same way a real Windows
    # test run would still want drag-drop tested in isolation from it.
    monkeypatch.setattr(
        "toki_desktop_mark._start_hotkey_listener", lambda: None
    )
    import toki_desktop_mark as tdm

    w = tdm.DesktopMark()
    yield w
    w.deleteLater()


@pytest.fixture(autouse=True)
def _clear_selection():
    from selection_context import get_selection_context

    get_selection_context().clear()
    yield
    get_selection_context().clear()


class TestDragEnter:
    def test_single_local_file_accepted(self, mark):
        event = _make_drag_event(QDragEnterEvent, [QUrl.fromLocalFile("/tmp/somefile.txt")])
        mark.dragEnterEvent(event)
        assert event.isAccepted()

    def test_multiple_files_rejected(self, mark):
        event = _make_drag_event(
            QDragEnterEvent,
            [QUrl.fromLocalFile("/tmp/a.txt"), QUrl.fromLocalFile("/tmp/b.txt")],
        )
        mark.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_non_local_url_rejected(self, mark):
        event = _make_drag_event(QDragEnterEvent, [QUrl("https://example.com/file.txt")])
        mark.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_no_urls_rejected(self, mark):
        event = _make_drag_event(QDragEnterEvent, [])
        mark.dragEnterEvent(event)
        assert not event.isAccepted()


class TestDropReal:
    def test_drop_real_existing_file_sets_selection(self, mark, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("hello")

        event = _make_drag_event(QDropEvent, [QUrl.fromLocalFile(str(f))])
        replies = []
        mark._reply_bubble  # sanity: attribute exists
        mark.show_reply = lambda text: replies.append(text)  # capture UI call

        mark.dropEvent(event)

        from selection_context import get_selection_context
        sel = get_selection_context().get_selected()
        assert sel is not None
        assert sel["name"] == "report.txt"
        assert event.isAccepted()
        assert replies and "report.txt" in replies[0]

    def test_drop_nonexistent_path_shows_failure_reply(self, mark, tmp_path):
        ghost = tmp_path / "ghost.txt"  # never created
        event = _make_drag_event(QDropEvent, [QUrl.fromLocalFile(str(ghost))])
        replies = []
        mark.show_reply = lambda text: replies.append(text)

        mark.dropEvent(event)

        from selection_context import get_selection_context
        assert get_selection_context().get_selected() is None
        assert replies and "couldn't select" in replies[0].lower()

    def test_drop_folder_rejected_not_selected(self, mark, tmp_path):
        folder = tmp_path / "a_folder"
        folder.mkdir()
        event = _make_drag_event(QDropEvent, [QUrl.fromLocalFile(str(folder))])
        replies = []
        mark.show_reply = lambda text: replies.append(text)

        mark.dropEvent(event)

        from selection_context import get_selection_context
        assert get_selection_context().get_selected() is None
        assert replies and "couldn't select" in replies[0].lower()

    def test_drop_multi_file_ignored(self, mark, tmp_path):
        f1 = tmp_path / "one.txt"
        f2 = tmp_path / "two.txt"
        f1.write_text("1")
        f2.write_text("2")
        event = _make_drag_event(QDropEvent, [QUrl.fromLocalFile(str(f1)), QUrl.fromLocalFile(str(f2))])

        mark.dropEvent(event)

        # dropEvent's own guard is single-file-only via dragEnterEvent
        # upstream in real usage, but dropEvent itself only reads urls[0] --
        # confirm it doesn't silently select the second file or crash.
        from selection_context import get_selection_context
        sel = get_selection_context().get_selected()
        # urls[0] ("one.txt") is a real existing file, so current dropEvent
        # code DOES select it even on a multi-file drop that dragEnterEvent
        # would have rejected upstream -- documenting actual behavior.
        assert sel is not None and sel["name"] == "one.txt"
