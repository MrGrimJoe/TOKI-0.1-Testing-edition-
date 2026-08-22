# tests/

A real regression suite, replacing the "re-derive test cases by re-reading
STATUS.md prose each session" workflow this project was running on before.

Everything here is pure Python -- no Ollama, no Windows, no PowerShell
needed. `test_graph_router.py` needs `kuzu` + the checked-in `toki_graph_db/`
and skips cleanly if either is missing.

## Run it

```bash
pip install pytest
python3 -m pytest tests/ -v
```

As of this session: **82 passed, 2 xfailed** (the xfails are documented,
still-open bugs -- see below, not something to "fix" by deleting the test).

## What's covered

- `test_extractor.py` -- every slot-extraction case (good and bad) that's
  been manually verified across BETA 0.1-0.3.3, plus BETA 0.3.4's 4
  fixes: `.exe` suffix stripping on process-name slots, leaked
  trigger-word bug (KILL_PROCESS/FIND_PROCESS/WAIT_FOR_PROCESS/
  FIND_SERVICE), sandbox path validation.
- `test_graph_router.py` -- classification hits/misses: BETA 0.1's known
  dangerous false positives (`"clear the screen"` -> EMPTY_RECYCLE_BIN,
  etc.), known-good hits, BETA 0.3's LAUNCH_APP-vs-OPEN_ITEM fix, BETA
  0.3.3's NON_GRAPH_CATEGORIES enforcement and the pre-LLM gate.
- `test_app_control.py` -- the LAUNCH_APP PowerShell-escaping fix from
  BETA 0.3.4 (mocks `subprocess.Popen`, checks the exact command string).
- `test_orchestrator.py` -- import-time wiring sanity (category map
  validity, override parsing, the shared `_escape_ps_slot()` helper).
- `test_open_target_cascade.py` -- BETA 0.3.5's app/file/ask cascade
  decision logic (`extractor.resolve_open_target`), plus the
  `_score_app_match()` app-matching safety fix (a real collision:
  `"vscode"` used to fuzzy-match `"Discord"` under plain
  `difflib.ratio()` -- see STATUS.md for the numbers).
- `test_open_cascade_integration.py` -- proves the actual reported bug
  ("asked it to open apps, it tried to open a folder") is fixed
  end-to-end through `WindowsAIAssistant._process_single_request()`
  itself, not just in isolated unit tests.
- `test_chain_split_viability.py` -- BETA 0.3.5's
  `_split_chain_if_viable()`, which rejects a chain split unless every
  resulting segment independently looks like a real command.

## Known, still-open bugs (marked `xfail(strict=True)`, not skipped)

These represent real, currently-open bugs from STATUS.md that nobody's
fixed yet. They're written as tests that assert the CORRECT behavior (so
they currently fail, hence `xfail`), not the buggy behavior -- so the
moment someone fixes the underlying issue, the test starts passing,
`strict=True` turns that into a hard failure ("hey, this xfail marker is
stale, remove it"), and CI tells you to update this file. That's the
point: a fix and its test going green happen in the same commit instead of
the marker silently rotting.

1. `test_extractor.py::TestKnownOpenIssues` -- `_extract_bare_path`'s
   greedy regex swallows leading words when a file is described in a full
   sentence instead of being quoted/`called`-triggered.
2. `test_graph_router.py::TestKnownOpenIssues` -- `GENERATE_FILE` has zero
   Phrasing nodes in the graph, so it can never be matched (needs a
   `migrate_to_kuzu.py`/`graph_source_data` fix, not a `graph_router.py` one).

## Adding a new test when you find (or fix) a bug

Same pattern every time: name the test after the exact input that broke,
assert what the CORRECT output should be, and put a one-line comment
pointing back to how it was found (a live run, a specific message, etc.) --
same spirit as this project's own STATUS.md entries, just executable
instead of prose. If you're documenting a bug you haven't fixed yet, mark
it `@pytest.mark.xfail(reason="...", strict=True)` so it doesn't block the
suite but still tracks the gap.
