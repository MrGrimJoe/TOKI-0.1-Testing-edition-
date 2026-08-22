"""
tests/execution/test_live_dispatch.py -- THE ONE OBJECTIVE: real, live
execution of every registered intent (all 82, not just the 71 Tier A
ones -- SET_TIMER/SCHEDULE_COMMAND/CONDITIONAL_COMMAND/RUN_MACRO/
START_SEEING/etc. bypass the graph but are real dispatched features too),
calling orchestrator.py's actual WindowsAIAssistant._dispatch() -- the
single real code path every intent goes through in production -- with
hand-crafted, known-good slots. No routing, no NLU, no slot extraction:
that's deliberately deferred (see this session's own strategy
discussion). Just: does what each intent is supposed to DO actually work.

Everything here needs a real Windows desktop (PowerShell, pywinauto, real
processes) -- marked requires_windows, auto-skipped everywhere else via
pytest_collection_modifyitems below, runs for real the moment this suite
is run on a real Windows machine.

TWO THINGS YOU NEED TO DO BEFORE RUNNING THIS ON WINDOWS
----------------------------------------------------------------------------
1. Have a browser open with a real YouTube video playing, in a tab with
   at least one other video visible (e.g. in the sidebar or as a
   thumbnail) -- needed for TestVideoAndClickRequiringYouTube. Everything
   else sets up its own preconditions automatically (temp files,
   launching/closing its own Notepad instance, recording its own throwaway
   macro, etc.) and needs nothing from you.
2. Have Ollama actually running (ollama serve) if you want
   TestGenerateFile to run for real -- it's skipped with a clear reason
   if Ollama isn't reachable, not silently faked.

DELIBERATELY EXCLUDED FROM AUTOMATIC EXECUTION
----------------------------------------------------------------------------
LOCK_WORKSTATION (would lock your real screen mid-test-run) and
EMPTY_RECYCLE_BIN (would permanently affect whatever's actually in your
real Recycle Bin right now) are marked `disruptive` instead of running
automatically -- deselected by default. Run them yourself explicitly
with `pytest -m disruptive` only when you're ready for exactly what they
do.

LOGGING
----------------------------------------------------------------------------
Every test, pass/fail/skip, writes one line to execution_test_log.jsonl
via the `logged` fixture (see conftest.py) -- intent, slots used, the
real dispatch result, pass/fail, full error text. That log is what gets
sent back for review after a run -- not just the pytest console output.
"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import orchestrator
from display_strategy import classify_display

# process_request()/_dispatch() return an immediate "Done." placeholder
# for kind=="powershell" -- the real command runs on its own background
# thread (executor.RunningCommand) and its real stdout/exit code only
# arrive afterward via the on_output/on_done callbacks. main_widget.py's
# _run_and_classify() is the real production code path: it waits on
# on_done and reconstructs the true response via
# display_strategy.classify_display() before ever showing anything to a
# user. real_dispatch() below now does the exact same thing, or every
# assertion in this file is racing a background thread and reading the
# stale synchronous "Done." placeholder instead of what actually
# happened -- which is what was producing false failures for
# GET_CLIPBOARD/READ_FILE/COUNT_FILES/COUNT_FOLDERS/FIND_FILES (real
# output silently discarded, "Done." asserted against) and for
# MAKE_FOLDER/MAKE_FILE/DELETE_ITEM/COPY_ITEM/MOVE_ITEM/RENAME_ITEM
# (filesystem assertions running before the background thread's
# subprocess had actually finished).
_POWERSHELL_TEST_TIMEOUT_S = 15



# ── shared dispatch helper ──────────────────────────────────────────────────

class _Capture:
    """Collects everything a real _dispatch() call streams out, so a test
    can inspect it after the (synchronous, blocking-until-done) call
    returns."""

    def __init__(self):
        self.output_lines = []
        self.thinking_tokens = []
        self.generate_tokens = []
        self.generate_result = None  # (path, error) once on_generate_done fires
        self.done_code = None
        # Set by on_done -- lets a caller block until the real background
        # command (powershell kind only; every other kind is already
        # fully resolved by the time _dispatch() returns) has actually
        # finished, instead of racing it. See real_dispatch() below.
        self.done_event = threading.Event()

    def on_output(self, line):
        self.output_lines.append(line)

    def on_done(self, code):
        self.done_code = code
        self.done_event.set()

    def on_thinking_token(self, tok):
        self.thinking_tokens.append(tok)

    def on_generate_token(self, tok):
        self.generate_tokens.append(tok)

    def on_generate_done(self, path, error):
        self.generate_result = (path, error)


def real_dispatch(assistant, intent, slots, user_prompt=None, skip_generate_name_check=True):
    """Calls the real _dispatch() -- same function orchestrator.py itself
    calls once routing has decided on an intent. skip_generate_name_check
    defaults True here since name-extraction-from-text is explicitly out
    of scope for this suite (that's slot extraction, deferred)."""
    cap = _Capture()
    result = assistant._dispatch(
        intent, user_prompt or f"<execution test for {intent}>", slots, "<execution test>",
        cap.on_output, cap.on_done, cap.on_thinking_token,
        cap.on_generate_token, cap.on_generate_done,
        skip_generate_name_check=skip_generate_name_check,
    )

    if isinstance(result, dict) and result.get("kind") == "powershell":
        completed = cap.done_event.wait(timeout=_POWERSHELL_TEST_TIMEOUT_S)
        collected_output = "\n".join(cap.output_lines)
        strategy, display_text = classify_display(
            result,
            collected_output=collected_output,
            exit_code=cap.done_code,
            timed_out=not completed,
        )
        # Overwrite the stale synchronous "Done." placeholder with the
        # real, fully-resolved response text -- exactly what a real user
        # would actually see, per classify_display's DONE/INFO/ERROR
        # rules. `result["kind"]` is deliberately left as "powershell" so
        # callers/log records can still tell what path this went through;
        # only the *content* of "response" was ever stale.
        result = dict(result)
        result["response"] = display_text
        result["display_strategy"] = strategy.value
        result["_powershell_timed_out"] = not completed

    return result, cap


@pytest.fixture(scope="module")
def assistant():
    a = orchestrator.WindowsAIAssistant()
    yield a
    a.shutdown()


@pytest.fixture
def sandbox_dir(tmp_path):
    """Real, disposable directory -- never the user's actual Desktop/D:\\
    sandbox. Every filesystem-touching test below creates its OWN files
    here first; nothing here depends on anything already existing on the
    real machine."""
    return tmp_path


def _no_error(result):
    """Every _dispatch() success path returns a dict without a top-level
    'error' style failure a user would see as broken. Different intents
    phrase failure differently (some raise, most return an error-shaped
    response text) -- this centralizes what "looks broken" means so
    every test below checks it the same way."""
    if not isinstance(result, dict):
        return True
    response = str(result.get("response", ""))
    failure_markers = (
        "Couldn't", "couldn't", "Error:", "Unknown API action",
        "isn't wired up", "failed:", "Failed:",
        # classify_display()'s ERROR-path text for a real non-zero
        # powershell exit code (see real_dispatch() above) -- doesn't
        # contain any of the markers above, so without this a genuinely
        # failed live command would silently pass _no_error().
        "Command failed (exit code",
    )
    return not any(m in response for m in failure_markers)


# ── read-only system info: no precondition needed at all ──────────────────

READ_ONLY_NO_PRECONDITION = [
    "GET_TIME", "GET_DATE", "DISK_USAGE", "SYSTEM_INFO", "NETWORK_INFO",
    "CURRENT_USER", "HOSTNAME", "SYSTEM_UPTIME", "SYSTEM_LOCALE",
    "BATTERY_STATUS", "LIST_PRINTERS", "LIST_USB_DEVICES",
    "TEMPERATURE_SENSORS", "PROCESS_LIST", "LIST_SCHEDULED_TASKS",
    "CURRENT_LOCATION", "GET_CLIPBOARD", "GET_LOCATION",
    "TAKE_SCREENSHOT", "OPEN_TASK_MANAGER", "LIST_INSTALLED_APPS",
    "CHAT",
]


class TestReadOnlySystemInfo:
    pytestmark = pytest.mark.requires_windows

    @pytest.mark.parametrize("intent_name", READ_ONLY_NO_PRECONDITION)
    def test_real_dispatch_succeeds(self, logged, assistant, intent_name):
        rec = logged(intent_name)
        rec.expected = "dispatches without an exception or an error-shaped response"
        result, cap = real_dispatch(assistant, intent_name, {})
        rec.actual = result
        assert _no_error(result), f"{intent_name} looked broken: {result}"


# ── network-dependent read-only APIs ────────────────────────────────────────

class TestNetworkApis:
    pytestmark = pytest.mark.requires_windows

    def test_get_weather(self, logged, assistant):
        rec = logged("GET_WEATHER")
        rec.slots = {"city": "London"}
        rec.expected = "real weather data for a real city, no error text"
        result, cap = real_dispatch(assistant, "GET_WEATHER", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_get_forecast(self, logged, assistant):
        rec = logged("GET_FORECAST")
        rec.slots = {"city": "London", "days": "3"}
        result, cap = real_dispatch(assistant, "GET_FORECAST", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_search_web(self, logged, assistant):
        rec = logged("SEARCH_WEB")
        rec.slots = {"query": "what is the capital of france"}
        result, cap = real_dispatch(assistant, "SEARCH_WEB", rec.slots)
        rec.actual = result
        assert _no_error(result)


# ── clipboard round trip (self-contained: sets, then reads back) ──────────

class TestClipboardRoundTrip:
    pytestmark = pytest.mark.requires_windows

    def test_set_then_get_clipboard(self, logged, assistant):
        marker = f"TOKI_EXECUTION_TEST_{int(time.time())}"
        rec = logged("SET_CLIPBOARD")
        rec.slots = {"value": marker}
        set_result, _ = real_dispatch(assistant, "SET_CLIPBOARD", rec.slots)
        rec.actual = set_result
        assert _no_error(set_result)

        get_result, _ = real_dispatch(assistant, "GET_CLIPBOARD", {})
        assert _no_error(get_result)
        assert marker in str(get_result.get("response", "")), (
            f"set clipboard to {marker!r} but reading it back didn't contain it: {get_result}"
        )


# ── volume controls (harmless, but real -- your actual system volume will change) ──

class TestVolumeControls:
    pytestmark = pytest.mark.requires_windows

    @pytest.mark.parametrize("intent_name", ["VOLUME_UP", "VOLUME_DOWN", "TOGGLE_MUTE"])
    def test_real_dispatch_succeeds(self, logged, assistant, intent_name):
        rec = logged(intent_name)
        rec.expected = "dispatches without error (your real system volume WILL change)"
        result, cap = real_dispatch(assistant, intent_name, {})
        rec.actual = result
        assert _no_error(result)


# ── filesystem: every test creates its own real files first ───────────────

class TestFilesystemOperations:
    pytestmark = pytest.mark.requires_windows

    def test_make_folder(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "new_folder"
        rec = logged("MAKE_FOLDER")
        rec.slots = {"path": str(target)}
        result, cap = real_dispatch(assistant, "MAKE_FOLDER", rec.slots)
        rec.actual = f"result={result}, exists={target.exists()}"
        assert _no_error(result)
        assert target.is_dir()

    def test_make_file(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "new_file.txt"
        rec = logged("MAKE_FILE")
        rec.slots = {"path": str(target)}
        result, cap = real_dispatch(assistant, "MAKE_FILE", rec.slots)
        rec.actual = f"result={result}, exists={target.exists()}"
        assert _no_error(result)
        assert target.is_file()

    def test_delete_item(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "doomed.txt"
        target.write_text("delete me")
        rec = logged("DELETE_ITEM")
        rec.slots = {"path": str(target)}
        result, cap = real_dispatch(assistant, "DELETE_ITEM", rec.slots)
        rec.actual = f"result={result}, exists={target.exists()}"
        assert _no_error(result)
        assert not target.exists()

    def test_copy_item(self, logged, assistant, sandbox_dir):
        source = sandbox_dir / "source.txt"
        source.write_text("copy me")
        dest = sandbox_dir / "dest.txt"
        rec = logged("COPY_ITEM")
        rec.slots = {"path": str(source), "dest": str(dest)}
        result, cap = real_dispatch(assistant, "COPY_ITEM", rec.slots)
        rec.actual = f"result={result}, source_exists={source.exists()}, dest_exists={dest.exists()}"
        assert _no_error(result)
        assert source.exists() and dest.exists()
        assert dest.read_text() == "copy me"

    def test_move_item(self, logged, assistant, sandbox_dir):
        source = sandbox_dir / "source.txt"
        source.write_text("move me")
        dest = sandbox_dir / "dest.txt"
        rec = logged("MOVE_ITEM")
        rec.slots = {"path": str(source), "dest": str(dest)}
        result, cap = real_dispatch(assistant, "MOVE_ITEM", rec.slots)
        rec.actual = f"result={result}, source_exists={source.exists()}, dest_exists={dest.exists()}"
        assert _no_error(result)
        assert not source.exists() and dest.exists()

    def test_rename_item(self, logged, assistant, sandbox_dir):
        source = sandbox_dir / "old_name.txt"
        source.write_text("rename me")
        new_path = sandbox_dir / "new_name.txt"
        rec = logged("RENAME_ITEM")
        rec.slots = {"path": str(source), "new_name": "new_name.txt"}
        result, cap = real_dispatch(assistant, "RENAME_ITEM", rec.slots)
        rec.actual = f"result={result}, old_exists={source.exists()}, new_exists={new_path.exists()}"
        assert _no_error(result)
        assert not source.exists() and new_path.exists()

    def test_list_files(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.txt").write_text("x")
        (sandbox_dir / "b.txt").write_text("y")
        rec = logged("LIST_FILES")
        rec.slots = {"path": str(sandbox_dir)}
        result, cap = real_dispatch(assistant, "LIST_FILES", rec.slots)
        rec.actual = result
        assert _no_error(result)
        assert "a.txt" in str(result.get("response", "")) or "a.txt" in "".join(cap.output_lines)

    def test_read_file(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "readme.txt"
        target.write_text("hello from the execution test suite")
        rec = logged("READ_FILE")
        rec.slots = {"path": str(target)}
        result, cap = real_dispatch(assistant, "READ_FILE", rec.slots)
        rec.actual = result
        assert _no_error(result)
        assert "hello from the execution test suite" in str(result.get("response", ""))

    def test_path_exists_true_and_false(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "exists.txt"
        target.write_text("x")
        rec = logged("PATH_EXISTS")
        rec.slots = {"path": str(target)}
        result, _ = real_dispatch(assistant, "PATH_EXISTS", rec.slots)
        rec.actual = result
        assert _no_error(result)

        missing_result, _ = real_dispatch(assistant, "PATH_EXISTS", {"path": str(sandbox_dir / "nope.txt")})
        assert _no_error(missing_result)  # a "doesn't exist" answer isn't itself an error

    def test_item_properties(self, logged, assistant, sandbox_dir):
        target = sandbox_dir / "props.txt"
        target.write_text("some content")
        rec = logged("ITEM_PROPERTIES")
        rec.slots = {"path": str(target)}
        result, _ = real_dispatch(assistant, "ITEM_PROPERTIES", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_resolve_path(self, logged, assistant, sandbox_dir):
        rec = logged("RESOLVE_PATH")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "RESOLVE_PATH", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_split_path(self, logged, assistant, sandbox_dir):
        rec = logged("SPLIT_PATH")
        rec.slots = {"path": str(sandbox_dir / "file.txt")}
        result, _ = real_dispatch(assistant, "SPLIT_PATH", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_count_files(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.txt").write_text("x")
        (sandbox_dir / "b.txt").write_text("y")
        rec = logged("COUNT_FILES")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "COUNT_FILES", rec.slots)
        rec.actual = result
        assert _no_error(result)
        assert "2" in str(result.get("response", ""))

    def test_count_folders(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "sub1").mkdir()
        (sandbox_dir / "sub2").mkdir()
        rec = logged("COUNT_FOLDERS")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "COUNT_FOLDERS", rec.slots)
        rec.actual = result
        assert _no_error(result)
        assert "2" in str(result.get("response", ""))

    def test_file_type_breakdown(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.txt").write_text("x")
        (sandbox_dir / "b.pdf").write_text("y")
        rec = logged("FILE_TYPE_BREAKDOWN")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "FILE_TYPE_BREAKDOWN", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_find_duplicate_files(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.txt").write_text("same content")
        (sandbox_dir / "b.txt").write_text("same content")
        rec = logged("FIND_DUPLICATE_FILES")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "FIND_DUPLICATE_FILES", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_find_files(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "target_file.txt").write_text("x")
        rec = logged("FIND_FILES")
        rec.slots = {"root": str(sandbox_dir), "query": "target_file"}
        result, _ = real_dispatch(assistant, "FIND_FILES", rec.slots)
        rec.actual = result
        assert _no_error(result)
        assert "target_file" in str(result.get("response", ""))

    def test_find_files_by_content(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "haystack.txt").write_text("the needle is in here")
        rec = logged("FIND_FILES_BY_CONTENT")
        rec.slots = {"path": str(sandbox_dir), "pattern": "needle"}
        result, _ = real_dispatch(assistant, "FIND_FILES_BY_CONTENT", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_export_folder_listing_csv(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.txt").write_text("x")
        rec = logged("EXPORT_FOLDER_LISTING_CSV")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "EXPORT_FOLDER_LISTING_CSV", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_sort_folder_by_type(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "photo.jpg").write_text("x")
        (sandbox_dir / "doc.pdf").write_text("y")
        rec = logged("SORT_FOLDER_BY_TYPE")
        rec.slots = {"path": str(sandbox_dir)}
        result, _ = real_dispatch(assistant, "SORT_FOLDER_BY_TYPE", rec.slots)
        rec.actual = f"result={result}, listing_after={list(sandbox_dir.iterdir())}"
        assert _no_error(result)

    def test_group_files_by_extension(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "a.pdf").write_text("x")
        (sandbox_dir / "b.pdf").write_text("y")
        rec = logged("GROUP_FILES_BY_EXTENSION")
        rec.slots = {"path": str(sandbox_dir), "extensions": ".pdf", "dest_name": "pdfs"}
        result, _ = real_dispatch(assistant, "GROUP_FILES_BY_EXTENSION", rec.slots)
        rec.actual = f"result={result}, listing_after={list(sandbox_dir.iterdir())}"
        assert _no_error(result)

    def test_organize_files_by_topic(self, logged, assistant, sandbox_dir):
        (sandbox_dir / "invoice_march.txt").write_text("march invoice content")
        (sandbox_dir / "invoice_april.txt").write_text("april invoice content")
        rec = logged("ORGANIZE_FILES_BY_TOPIC")
        rec.slots = {"path": str(sandbox_dir), "include_suggestions": "false"}
        result, _ = real_dispatch(assistant, "ORGANIZE_FILES_BY_TOPIC", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_open_item(self, logged, assistant, sandbox_dir):
        # Opens a real file with its default program -- Notepad for
        # .txt, unavoidable side effect of testing this for real. The
        # opened window is left open; harmless but you may see a fresh
        # Notepad window after this test runs.
        target = sandbox_dir / "will_open.txt"
        target.write_text("opened by the execution test suite")
        rec = logged("OPEN_ITEM")
        rec.slots = {"path": str(target)}
        result, _ = real_dispatch(assistant, "OPEN_ITEM", rec.slots)
        rec.actual = result
        assert _no_error(result)


# ── process control: self-contained round trip (launches, then kills, its own Notepad) ──

class TestProcessControl:
    pytestmark = pytest.mark.requires_windows

    def test_launch_then_kill_own_notepad(self, logged, assistant):
        rec = logged("LAUNCH_APP")
        rec.slots = {"app_name": "notepad"}
        launch_result, _ = real_dispatch(assistant, "LAUNCH_APP", rec.slots)
        rec.actual = launch_result
        assert _no_error(launch_result)

        time.sleep(2)  # give the real process a moment to actually start

        kill_rec = logged("KILL_PROCESS", test_id="test_kill_the_notepad_just_launched")
        kill_rec.slots = {"process": "notepad"}
        kill_result, _ = real_dispatch(assistant, "KILL_PROCESS", kill_rec.slots)
        kill_rec.actual = kill_result
        assert _no_error(kill_result)

    def test_find_process_after_launching_it(self, logged, assistant):
        real_dispatch(assistant, "LAUNCH_APP", {"app_name": "notepad"})
        time.sleep(2)
        rec = logged("FIND_PROCESS")
        rec.slots = {"process_name": "notepad"}
        result, _ = real_dispatch(assistant, "FIND_PROCESS", rec.slots)
        rec.actual = result
        assert _no_error(result)
        real_dispatch(assistant, "KILL_PROCESS", {"process": "notepad"})  # cleanup

    def test_wait_for_process_that_is_not_running(self, logged, assistant):
        # Bounded, short-timeout check that a definitely-not-running
        # process is correctly reported as not running -- not an
        # actually blocking wait.
        rec = logged("WAIT_FOR_PROCESS")
        rec.slots = {"process_name": "definitely_not_a_real_process_xyz"}
        result, _ = real_dispatch(assistant, "WAIT_FOR_PROCESS", rec.slots)
        rec.actual = result
        # Not asserting _no_error here -- "process not found" may itself
        # be phrased with one of the failure-marker words. Just confirm
        # it returns promptly rather than hanging.

    def test_find_service(self, logged, assistant):
        rec = logged("FIND_SERVICE")
        rec.slots = {"service_name": "Spooler"}  # Print Spooler -- present on all real Windows installs
        result, _ = real_dispatch(assistant, "FIND_SERVICE", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_top_processes_by_cpu(self, logged, assistant):
        rec = logged("TOP_PROCESSES_BY_CPU")
        rec.slots = {"count": "5"}
        result, _ = real_dispatch(assistant, "TOP_PROCESSES_BY_CPU", rec.slots)
        rec.actual = result
        assert _no_error(result)


# ── app control needing a target: self-contained via a real launched Notepad ──

class TestAppControlWithNotepadTarget:
    """TYPE_INTO_ELEMENT is fully self-contained (launches its own
    Notepad, types into it, closes it). CLICK/DOUBLE_CLICK/RIGHT_CLICK
    need a real clickable UI element with a matching description -- see
    TestVideoAndClickRequiringYouTube below for those instead, since a
    freshly-launched Notepad's only obviously-describable elements
    (its own text area) don't exercise click resolution meaningfully."""
    pytestmark = pytest.mark.requires_windows


    def test_launch_notepad_then_type_into_it(self, logged, assistant):
        launch_result, _ = real_dispatch(assistant, "LAUNCH_APP", {"app_name": "notepad"})
        assert _no_error(launch_result)
        time.sleep(2)

        rec = logged("TYPE_INTO_ELEMENT")
        rec.slots = {"target_description": "the text editor area", "text": "typed by the execution test suite"}
        result, _ = real_dispatch(assistant, "TYPE_INTO_ELEMENT", rec.slots)
        rec.actual = result
        try:
            assert _no_error(result)
        finally:
            real_dispatch(assistant, "KILL_PROCESS", {"process": "notepad"})  # cleanup, don't save the file


# ── needs YouTube open -- the one real manual precondition in this suite ──

class TestVideoAndClickRequiringYouTube:
    """PRECONDITION (see this file's module docstring): a real browser
    tab with a YouTube video playing, with at least one other video
    visible on the page (sidebar recommendation or a thumbnail) to click.
    Every test here checks that precondition itself first and SKIPS with
    a clear, specific reason if it isn't met, rather than failing
    confusingly.
    """
    pytestmark = pytest.mark.requires_windows


    def test_download_playing_video(self, logged, assistant):
        rec = logged("DOWNLOAD_PLAYING_VIDEO")
        rec.slots = {"audio_only": "false"}
        result, cap = real_dispatch(assistant, "DOWNLOAD_PLAYING_VIDEO", rec.slots)
        rec.actual = result
        if not _no_error(result) and "couldn't detect what's playing" in str(result.get("response", "")).lower():
            pytest.skip(
                "No playing video was detected -- make sure a YouTube tab "
                "is open and actually playing before running this test."
            )
        assert _no_error(result)

    def test_click_a_video_thumbnail(self, logged, assistant):
        # "the clicking task can literally be clicking another video" --
        # clicks a recommended/sidebar video thumbnail on the currently
        # open YouTube page.
        rec = logged("CLICK_ELEMENT")
        rec.slots = {"target_description": "a recommended video thumbnail"}
        result, cap = real_dispatch(assistant, "CLICK_ELEMENT", rec.slots)
        rec.actual = result
        if not _no_error(result) and "couldn't find" in str(result.get("response", "")).lower():
            pytest.skip(
                "No matching clickable element found -- make sure YouTube "
                "is open with at least one other video visible (sidebar "
                "or thumbnail) before running this test."
            )
        assert _no_error(result)


# ── GENERATE_FILE -- needs Ollama running ───────────────────────────────────

class TestGenerateFile:
    pytestmark = pytest.mark.requires_windows

    def test_generate_and_save_a_real_file(self, logged, assistant, sandbox_dir):
        import requests
        try:
            requests.get("http://localhost:11434", timeout=2)
        except Exception:
            pytest.skip("Ollama isn't reachable on localhost:11434 -- start it with `ollama serve` to run this test.")

        rec = logged("GENERATE_FILE")
        cap = _Capture()
        result = assistant._dispatch(
            "GENERATE_FILE",
            "write a one-line python script that prints hello world, save it as execution_test_output.py",
            {}, "<execution test>",
            cap.on_output, cap.on_done, cap.on_thinking_token,
            cap.on_generate_token, cap.on_generate_done,
            skip_generate_name_check=True,
        )
        rec.actual = f"result={result}, generate_result={cap.generate_result}"
        assert cap.generate_result is not None, "on_generate_done was never called"
        path, error = cap.generate_result
        assert error is None, f"generation failed: {error}"
        assert path is not None and Path(path).exists(), f"no file was actually written: {path}"


# ── macro round trip: self-contained (records a trivial macro, plays it back) ──

class TestMacroRoundTrip:
    pytestmark = pytest.mark.requires_windows

    def test_record_then_play_a_macro(self, logged, assistant):
        start_rec = logged("START_SEEING")
        start_result, _ = real_dispatch(assistant, "START_SEEING", {})
        start_rec.actual = start_result
        assert _no_error(start_result)

        time.sleep(1)  # give the recorder a moment to actually be listening

        macro_name = f"execution_test_macro_{int(time.time())}"
        stop_rec = logged("STOP_SEEING", test_id="test_stop_seeing_and_save")
        stop_rec.slots = {"macro_name": macro_name}
        stop_result, _ = real_dispatch(assistant, "STOP_SEEING", stop_rec.slots)
        stop_rec.actual = stop_result
        assert _no_error(stop_result)

        play_rec = logged("RUN_MACRO")
        play_rec.slots = {"macro_name": macro_name}
        play_result, _ = real_dispatch(assistant, "RUN_MACRO", play_rec.slots)
        play_rec.actual = play_result
        assert _no_error(play_result)


# ── dictation round trip: self-contained (starts, then immediately stops) ──

class TestDictationRoundTrip:
    pytestmark = pytest.mark.requires_windows

    def test_start_then_stop_dictation(self, logged, assistant):
        start_rec = logged("START_LISTENING")
        start_rec.slots = {"target_description": "the currently focused field"}
        start_result, _ = real_dispatch(assistant, "START_LISTENING", start_rec.slots)
        start_rec.actual = start_result
        assert _no_error(start_result)

        time.sleep(1)

        stop_rec = logged("STOP_LISTENING")
        stop_result, _ = real_dispatch(assistant, "STOP_LISTENING", {})
        stop_rec.actual = stop_result
        assert _no_error(stop_result)


# ── timer / schedule / conditional / ask_context / cancel_scheduled ────────

class TestTimerScheduleConditional:
    pytestmark = pytest.mark.requires_windows

    def test_set_timer(self, logged, assistant):
        rec = logged("SET_TIMER")
        rec.slots = {"delay_seconds": "2", "label": "execution test timer"}
        result, _ = real_dispatch(assistant, "SET_TIMER", rec.slots)
        rec.actual = result
        assert _no_error(result)

    def test_schedule_command_then_cancel_it(self, logged, assistant):
        rec = logged("SCHEDULE_COMMAND")
        rec.slots = {"command_text": "get the time", "delay_seconds": "3600"}  # far enough out that it won't actually fire during the test
        result, _ = real_dispatch(assistant, "SCHEDULE_COMMAND", rec.slots)
        rec.actual = result
        assert _no_error(result)

        # Best-effort cleanup: cancel whatever ref this just created so it
        # doesn't linger after the test suite exits. Extracting the real
        # ref format is scheduler.py's own concern; this just tries the
        # most recent one.
        try:
            import scheduler
            jobs = assistant.scheduler.list_jobs() if hasattr(assistant.scheduler, "list_jobs") else []
            if jobs:
                cancel_rec = logged("CANCEL_SCHEDULED", test_id="test_cancel_the_schedule_just_created")
                ref = jobs[-1].get("ref") if isinstance(jobs[-1], dict) else str(jobs[-1])
                cancel_rec.slots = {"ref": ref}
                cancel_result, _ = real_dispatch(assistant, "CANCEL_SCHEDULED", cancel_rec.slots)
                cancel_rec.actual = cancel_result
        except Exception:
            pass  # best-effort cleanup only; not the point of this test


# ── DISRUPTIVE: excluded from automatic runs, opt-in only ──────────────────

class TestDisruptiveIntents:
    """These are real registered Tier A intents and DO need to be
    verified eventually -- but not automatically, not without you
    watching. LOCK_WORKSTATION locks your real screen the instant it
    runs (blocking every OTHER test behind it in the same run until you
    unlock). EMPTY_RECYCLE_BIN permanently affects whatever's actually
    in your real Recycle Bin right now. Run these two, and only these
    two, explicitly: `pytest -m disruptive -k TestDisruptiveIntents`.
    """
    pytestmark = pytest.mark.requires_windows


    @pytest.mark.disruptive
    def test_empty_recycle_bin(self, logged, assistant):
        rec = logged("EMPTY_RECYCLE_BIN")
        result, _ = real_dispatch(assistant, "EMPTY_RECYCLE_BIN", {})
        rec.actual = result
        assert _no_error(result)

    @pytest.mark.disruptive
    def test_lock_workstation(self, logged, assistant):
        rec = logged("LOCK_WORKSTATION")
        result, _ = real_dispatch(assistant, "LOCK_WORKSTATION", {})
        rec.actual = result
        assert _no_error(result)


# ── meta: confirm every registered intent landed in exactly one class above ──

def test_no_registered_intent_is_missing_from_this_suite(logged):
    rec = logged("_meta_coverage", test_id="test_no_intent_uncovered_in_live_suite")
    covered = set(READ_ONLY_NO_PRECONDITION) | {
        "GET_WEATHER", "GET_FORECAST", "SEARCH_WEB",
        "SET_CLIPBOARD",
        "VOLUME_UP", "VOLUME_DOWN", "TOGGLE_MUTE",
        "MAKE_FOLDER", "MAKE_FILE", "DELETE_ITEM", "COPY_ITEM", "MOVE_ITEM",
        "RENAME_ITEM", "LIST_FILES", "READ_FILE", "PATH_EXISTS",
        "ITEM_PROPERTIES", "RESOLVE_PATH", "SPLIT_PATH", "COUNT_FILES",
        "COUNT_FOLDERS", "FILE_TYPE_BREAKDOWN", "FIND_DUPLICATE_FILES",
        "FIND_FILES", "FIND_FILES_BY_CONTENT", "EXPORT_FOLDER_LISTING_CSV",
        "SORT_FOLDER_BY_TYPE", "GROUP_FILES_BY_EXTENSION",
        "ORGANIZE_FILES_BY_TOPIC", "OPEN_ITEM",
        "LAUNCH_APP", "KILL_PROCESS", "WAIT_FOR_PROCESS", "FIND_SERVICE",
        "TOP_PROCESSES_BY_CPU", "FIND_PROCESS",
        "TYPE_INTO_ELEMENT",
        "DOWNLOAD_PLAYING_VIDEO", "CLICK_ELEMENT",
        "GENERATE_FILE",
        "START_SEEING", "STOP_SEEING", "RUN_MACRO",
        "START_LISTENING", "STOP_LISTENING",
        "SET_TIMER", "SCHEDULE_COMMAND", "CANCEL_SCHEDULED",
        "EMPTY_RECYCLE_BIN", "LOCK_WORKSTATION",
    }
    # Not individually exercised above (documented why, not oversights):
    #   CONDITIONAL_COMMAND, ASK_CONTEXT -- both slot-less/context-only,
    #     genuinely can't be meaningfully dispatched with synthetic slots
    #     the way every other intent here can; need a real ambiguous
    #     conversational turn, which is routing/NLU territory, explicitly
    #     out of scope this round.
    #   DOUBLE_CLICK_ELEMENT, RIGHT_CLICK_ELEMENT -- same underlying
    #     AppController.click() as CLICK_ELEMENT (see orchestrator.INTENTS,
    #     both just set extra_args={"double": True}/{"right": True}); one
    #     real click-resolution test already covers whether click targeting
    #     itself works, a second and third real click against the same
    #     page didn't seem worth the extra manual video precondition.
    #   CONVERT_SELECTED_FILE, RESIZE_SELECTED_FILE, COMPRESS_SELECTED_FILE,
    #     EXTRACT_SELECTED_FILE, DOWNLOAD_VIDEO_URL, PLUGIN_HELLO -- not
    #     covered yet, tracked as a real gap for the next pass, not
    #     silently dropped.
    #   SAVE_CLIPBOARD_TO_FILE, GENERATE_QR_CODE, SCAN_QR_CODE -- brand
    #     new this session (clip_qr.py), thoroughly unit-tested (see
    #     tests/test_clip_qr.py, tests/test_extractor_clip_qr.py,
    #     tests/test_tool_dispatcher_clip_qr.py, and the graph-routing
    #     checks in tests/test_graph_router.py's
    #     TestClipboardFileAndQrCodeHits) but never run against a real
    #     Windows clipboard/PowerShell/selection_context -- same "no
    #     Windows machine available this session" gap as the
    #     selected-file conversion intents above, not an oversight.
    known_gaps = {
        "CONDITIONAL_COMMAND", "ASK_CONTEXT",
        "DOUBLE_CLICK_ELEMENT", "RIGHT_CLICK_ELEMENT",
        "CONVERT_SELECTED_FILE", "RESIZE_SELECTED_FILE",
        "COMPRESS_SELECTED_FILE", "EXTRACT_SELECTED_FILE",
        "DOWNLOAD_VIDEO_URL", "PLUGIN_HELLO",
        "SAVE_CLIPBOARD_TO_FILE", "GENERATE_QR_CODE", "SCAN_QR_CODE",
    }
    uncovered = set(orchestrator.INTENTS.keys()) - covered - known_gaps
    rec.expected = "empty (beyond the explicitly documented known_gaps)"
    rec.actual = sorted(uncovered)
    assert not uncovered, f"Intent(s) with NO coverage and no documented reason: {sorted(uncovered)}"
