import sys
from pathlib import Path

import pytest

# Make the project root importable regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extractor


@pytest.fixture(autouse=True)
def _reset_file_index_between_tests():
    """extractor.file_index is a module-level singleton that scans once and
    caches forever (by design -- see its own docstring -- so production
    doesn't rescan the real disk every turn). That's a real test-isolation
    hazard: whichever test happens to trigger its first scan wins for the
    rest of the pytest process, including tests using their own
    monkeypatched sandbox roots. Confirmed directly: a real end-to-end
    pipeline test exercising resolve_open_target() against the real
    (non-Windows) environment permanently cached an empty entry list,
    silently starving test_file_index.py's sandbox-based tests of ever
    seeing their own tmp_path files if that pipeline test ran first.
    Resetting to a fresh, unscanned FileIndex before every test removes
    the ordering dependency entirely."""
    extractor.file_index = extractor.FileIndex()
    yield
    extractor.file_index = extractor.FileIndex()
