"""
run_all_tests.py -- single entry point for the whole test story: the fast
pytest suite (instant, sandbox-only, no Ollama needed) AND every real
batch_test_live.py prompt file (needs a real Ollama server running), one
after another, in one command.

Every prior test-and-document pass on this project was N separate manual
commands: `pytest tests/`, then for each of 5+ prompt-generator .py files,
run it once to generate the .txt, then run batch_test_live.py on that
.txt. This script does all of that for you.

USAGE:
    python run_all_tests.py                 # everything: pytest + all live batches
    python run_all_tests.py --pytest-only    # just the fast suite, skip Ollama entirely
    python run_all_tests.py --live-only      # skip pytest, just the live batches
    python run_all_tests.py --model llama3.2 # passed through to batch_test_live.py

Each stage is run as its own subprocess (`python -m pytest ...`,
`python batch_test_live.py ...`) rather than imported and called
in-process. This is deliberate, not laziness: WindowsAIAssistant opens a
real kuzu graph-db connection that's never explicitly closed by
batch_test_live.py's own main(), and kuzu enforces a strict single-writer
file lock on real Windows (confirmed directly -- this exact lock
contention broke 21 tests when a different script left connections open
in-process; see STATUS.md's "leaked WindowsAIAssistant" entry). Running
each stage as a separate OS process guarantees its connection is released
when that process exits, regardless of what any individual script
remembers to clean up -- the safest possible boundary given a lock this
strict.

Output: pytest's own summary line, then a live progress marker for each
batch file as it starts/finishes, then a final combined summary showing
where every log file landed. Nothing here scores the batch results
correct/incorrect -- ambiguous classification calls need a human reading
the transcripts, same as every prior batch run. This script's job is
purely to stop you from typing six separate commands, not to replace
reading the logs.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

PROMPT_GENERATORS = [
    "batch_test_prompts_v2.py",
    "batch_test_prompts_v3a_chains.py",
    "batch_test_prompts_v3b_wcl_breadth.py",
    "batch_test_prompts_v3c_apps_and_edge_cases.py",
    "batch_test_prompts_v3d_filesystem_edge_cases.py",
]


def _version() -> str:
    version_file = HERE / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


def _run(cmd: list, description: str) -> int:
    """Runs a subprocess with output streamed live (not captured), so long
    Ollama-backed runs still show progress instead of going silent for
    minutes. Returns the exit code; never raises on a non-zero code --
    caller decides whether that stage's failure should stop the run."""
    print(f"\n{'=' * 70}\n{description}\n{'=' * 70}")
    result = subprocess.run(cmd, cwd=str(HERE))
    return result.returncode


def run_pytest() -> int:
    return _run([sys.executable, "-m", "pytest", "tests/", "-v"], "Running pytest suite")


def run_live_batches(model: str) -> list:
    """Generates each prompt .txt fresh (in case a generator script was
    edited since last run) then feeds it through batch_test_live.py.
    Returns a list of (name, exit_code) so the final summary can flag any
    stage that errored, without stopping earlier stages from finishing --
    a single Ollama hiccup on file 3 of 5 shouldn't hide results from
    files 1, 2, 4, 5."""
    results = []
    for generator in PROMPT_GENERATORS:
        gen_path = HERE / generator
        if not gen_path.exists():
            print(f"\n[skip] {generator} not found, skipping")
            results.append((generator, None))
            continue

        # Step 1: generate the .txt fresh from the generator script.
        gen_code = _run([sys.executable, generator], f"Generating prompts: {generator}")
        if gen_code != 0:
            print(f"[warn] {generator} exited {gen_code} -- skipping its batch run")
            results.append((generator, gen_code))
            continue

        # The generator's own __main__ block prints the .txt filename it
        # wrote (e.g. "Wrote 70 prompts to X.txt") -- rather than re-parse
        # that text, derive the same filename it uses: every generator in
        # this project names its output "<script_stem>.txt".
        txt_path = HERE / f"{gen_path.stem}.txt"
        if not txt_path.exists():
            print(f"[warn] expected {txt_path.name} after running {generator}, not found -- skipping")
            results.append((generator, -1))
            continue

        # Step 2: run the real live batch test against that prompt file.
        run_code = _run(
            [sys.executable, "batch_test_live.py", str(txt_path.name), "--model", model],
            f"Running live batch: {txt_path.name}",
        )
        results.append((generator, run_code))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pytest-only", action="store_true",
                         help="Run only the fast pytest suite, skip all Ollama-backed batches.")
    parser.add_argument("--live-only", action="store_true",
                         help="Skip pytest, run only the live Ollama-backed batches.")
    parser.add_argument("--model", default="phi4-mini",
                         help="Ollama model name, passed through to batch_test_live.py (default: phi4-mini)")
    args = parser.parse_args()

    if args.pytest_only and args.live_only:
        print("Can't pass both --pytest-only and --live-only -- pick one.")
        sys.exit(2)

    print(f"TOKI {_version()} -- full test run starting")
    overall_start = time.time()

    pytest_code = None
    live_results = []

    if not args.live_only:
        pytest_code = run_pytest()

    if not args.pytest_only:
        live_results = run_live_batches(args.model)

    total = time.time() - overall_start

    print(f"\n{'=' * 70}\nSUMMARY (TOKI {_version()})\n{'=' * 70}")
    if pytest_code is not None:
        print(f"pytest suite: {'PASSED' if pytest_code == 0 else f'FAILED (exit {pytest_code})'}")
    if live_results:
        for name, code in live_results:
            if code is None:
                status = "skipped (generator not found)"
            elif code == 0:
                status = "completed -- read the .log file for actual results"
            else:
                status = f"exited {code} -- check output above"
            print(f"  {name}: {status}")
        print("\nLive batch results are TRANSCRIPTS, not pass/fail -- read the "
              "batch_test_results_*.log files to judge classification quality "
              "yourself, same as every prior manual run.")
    print(f"\nTotal time: {total:.1f}s")

    # Exit non-zero only on the fast, deterministic pytest suite -- the
    # live batches are exploratory/transcript-based by design (see
    # batch_test_live.py's own docstring), so a "bad" classification in
    # there isn't a script error and shouldn't make this exit code look
    # like a crash.
    sys.exit(pytest_code if pytest_code else 0)


if __name__ == "__main__":
    main()
