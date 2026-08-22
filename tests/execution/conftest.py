"""
tests/execution/conftest.py -- infrastructure for the single objective:
automatically, live-execute every registered intent's real dispatch path
and log every single outcome (pass, fail, or skip -- including WHY it
was skipped) in complete detail. Nothing else.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import execution_test_log

CHECKPOINT_NAME = "execution-batch-1"


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_windows: needs a real Windows desktop")
    config.addinivalue_line("markers", "requires_browser: needs a real Chrome/Edge binary")
    config.addinivalue_line("markers", "requires_app_control: needs pywinauto + a real window")
    config.addinivalue_line("markers", "disruptive: locks the screen / empties the real Recycle Bin")


def pytest_collection_modifyitems(config, items):
    import platform
    is_windows = platform.system() == "Windows"
    for item in items:
        if not is_windows and (
            "requires_windows" in item.keywords
            or "requires_app_control" in item.keywords
            or "requires_browser" in item.keywords
        ):
            item.add_marker(pytest.mark.skip(reason="requires_windows: not running on Windows"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, "rep_" + report.when, report)


def _guess_intent_from_nodeid(nodeid: str) -> str:
    """Best-effort only, purely for log readability on a test that never
    reached its own logged() call (a setup-phase skip, before the test
    body -- and therefore this fixture -- ever runs)."""
    class_name = nodeid.split("::")[-2] if "::" in nodeid else ""
    guess = "".join(
        "_" + c if c.isupper() and i > 0 and not class_name[i - 1].isupper() else c
        for i, c in enumerate(class_name.replace("Test", "", 1))
    ).lstrip("_").upper()
    return guess or "UNKNOWN"


def pytest_runtest_logreport(report):
    """Catches tests skipped at the SETUP phase (marker-based, via
    pytest_collection_modifyitems above) -- these never enter the test
    body at all, so the `logged` fixture below (only invoked BY the test
    body) never runs and this test would otherwise be completely
    invisible in execution_test_log.jsonl. Mid-test pytest.skip() calls
    (the precondition checks inside TestVideoAndClickRequiringYouTube/
    TestGenerateFile) DO enter the body and ARE covered by `logged`
    itself instead -- see that fixture's own skip handling below; this
    hook only covers what that fixture structurally cannot.
    """
    if report.when != "setup" or not report.skipped:
        return
    if "tests/execution/" not in str(report.fspath).replace("\\", "/") and \
       "tests\\execution\\" not in str(report.fspath):
        return
    test_id = report.nodeid.split("::")[-1]
    execution_test_log.log_test_result(
        checkpoint=CHECKPOINT_NAME,
        test_id=test_id,
        intent=_guess_intent_from_nodeid(report.nodeid),
        layer="live_execution",
        passed=False,
        skipped_reason=str(report.longrepr),
    )


class _Recorder:
    def __init__(self, test_id: str, intent: str):
        self.test_id = test_id
        self.intent = intent
        self.slots = {}
        self.expected = None
        self.actual = None


@pytest.fixture
def logged(request):
    """See execution_test_log.py's docstring for the full record shape
    and why this exists (complete, per-intent, cross-session-readable
    detail -- not just a pass/fail count).

    Handles three real outcomes for a test that reaches this fixture's
    own teardown: passed, failed (with full error text), and a MID-TEST
    pytest.skip() (e.g. "no video was detected playing" -- entered the
    body, called logged(), then decided to bail with a specific reason)
    -- that last one is NOT a failure and must be logged as a skip, not
    silently counted as passed=False the way a naive report.passed check
    would.
    """
    recorders = []

    def _make(intent: str, test_id=None):
        rec = _Recorder(test_id or request.node.name, intent)
        recorders.append(rec)
        return rec

    yield _make

    call_report = getattr(request.node, "rep_call", None)
    passed = bool(call_report and call_report.passed)
    error_text = None
    skipped_reason = None
    if call_report is not None:
        if call_report.skipped:
            skipped_reason = str(call_report.longrepr)
        elif call_report.failed and call_report.longrepr is not None:
            error_text = str(call_report.longrepr)

    for rec in recorders:
        execution_test_log.log_test_result(
            checkpoint=CHECKPOINT_NAME,
            test_id=rec.test_id,
            intent=rec.intent,
            layer="live_execution",
            slots=rec.slots,
            expected=rec.expected,
            actual=rec.actual,
            passed=passed,
            error=RuntimeError(error_text) if error_text else None,
            skipped_reason=skipped_reason,
        )
