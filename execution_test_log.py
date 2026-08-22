"""
execution_test_log.py -- structured, append-only logging for the
execution-layer checkpoint test suite (tests/execution/), separate from
pytest's own pass/fail reporting.

WHY THIS EXISTS
----------------------------------------------------------------------------
Per the project owner's own multi-session strategy: routing and execution
are being tested and fixed as two separate layers now, across multiple
independent chat sessions working from a shared repo, in ~100-command
checkpoints. A later session picking up a checkpoint needs to be able to
see EXACTLY what a prior session's tests actually did and observed --
not just "47 passed, 3 skipped" -- so it can tell a real regression
apart from an environment difference (no Windows here, no Chrome there,
a different focused window) without having to re-derive that from
scratch. "Every piece of data is very important" was explicit -- this
logs the full record, not a summary.

Same append-only, one-JSON-object-per-line convention as vocab_staging.py
and conversation_memory.py -- easy to grep, easy to diff between
sessions/checkpoints, trivial to load with one json.loads() per line.

RECORD SHAPE (one per line, append-only, never rewritten or truncated)
----------------------------------------------------------------------------
    {
        "timestamp": "<ISO8601>",
        "checkpoint": "execution-batch-1",     # which checkpoint this
                                                  # test belongs to, so a
                                                  # later session can
                                                  # filter to just its
                                                  # own batch
        "test_id": "test_make_folder_command_string",
        "intent": "MAKE_FOLDER",
        "layer": "command_generation" | "live_execution",
        "slots": {"path": "C:\\Users\\test\\Desktop\\TOKI_TEST\\foo"},
        "preconditions": ["sandbox dir created", "..."],  # what setup
                                                              # this test
                                                              # needed and
                                                              # actually
                                                              # did, not
                                                              # just what
                                                              # it assumed
        "expected": "...",
        "actual": "...",
        "passed": true,
        "error": null,                          # full exception
                                                    # text/traceback if
                                                    # the test failed for
                                                    # a reason OTHER than
                                                    # a plain assertion
        "environment": {
            "platform": "Linux" | "Windows",
            "skipped_reason": null | "requires_windows: not on Windows"
        }
    }
"""

import json
import platform
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

LOG_PATH = Path(__file__).parent / "execution_test_log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_test_result(
    *,
    checkpoint: str,
    test_id: str,
    intent: str,
    layer: str,
    slots: Optional[Dict[str, Any]] = None,
    preconditions: Optional[list] = None,
    expected: Any = None,
    actual: Any = None,
    passed: bool,
    error: Optional[BaseException] = None,
    skipped_reason: Optional[str] = None,
    log_path: Path = LOG_PATH,
) -> None:
    """Called from a pytest fixture (see tests/execution/conftest.py's
    `logged_test` fixture) at the end of every execution-layer test,
    success or failure. Never raises -- exactly like every other
    diagnostic logger in this project (OllamaRouter._log_timing(),
    ConversationMemory.record()), a logging failure must never be what
    makes a test's real result unclear.
    """
    record = {
        "timestamp": _now(),
        "checkpoint": checkpoint,
        "test_id": test_id,
        "intent": intent,
        "layer": layer,
        "slots": slots or {},
        "preconditions": preconditions or [],
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "error": "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if error is not None else None,
        "environment": {
            "platform": platform.system(),
            "skipped_reason": skipped_reason,
        },
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def summarize(checkpoint: Optional[str] = None, log_path: Path = LOG_PATH) -> Dict[str, Any]:
    """Quick cross-session sanity view: how many tests ran for a given
    checkpoint, how many passed, how many were skipped for environment
    reasons (no Windows, no Chrome) vs. genuinely failed. A later
    session should run this before trusting a checkpoint is "done"."""
    if not log_path.exists():
        return {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    total = passed = failed = skipped = 0
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if checkpoint is not None and record.get("checkpoint") != checkpoint:
                continue
            total += 1
            if record["environment"].get("skipped_reason"):
                skipped += 1
            elif record["passed"]:
                passed += 1
            else:
                failed += 1
    return {"total": total, "passed": passed, "failed": failed, "skipped": skipped}
