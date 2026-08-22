"""
batch_test_live.py -- run a list of prompts through TOKI's REAL, LIVE
pipeline (real graph routing, real Ollama narration, real slot
extraction) with ZERO real PowerShell execution, and log every result
to a file -- so you can start it, walk away, and read a full transcript
when you get back, instead of typing one message at a time and waiting.

WHY THIS IS SAFE TO RUN UNATTENDED:
_process_single_request() genuinely dispatches real PowerShell commands
at the very end of a turn (RunningCommand -> subprocess.Popen). This
script patches RunningCommand itself so .start() never spawns a real
process -- it just pretends the command finished instantly. Everything
BEFORE that point (graph classification, Ollama narration, slot
extraction, chain-splitting) runs completely for real, against your
real local model. Only the actual "run this on my machine" step is
faked. This means: no files get created/deleted/renamed, no real apps
get launched, nothing on your disk changes -- but you get real,
honest answers to "did it pick the right command" and "did the
narration match what was actually decided," which is the part that
needed a real conversation to test in the first place.

WHAT THIS DOES NOT REPLACE:
- Real live-Windows testing where commands actually run (this is
  deliberately the opposite of that -- for prompt/routing/narration
  correctness, not execution correctness).
- pytest tests/ -- that's instant, sandbox-only, no Ollama needed, and
  should still be your first check on any new package.

USAGE:
    python batch_test_live.py                  # runs the built-in prompt list
    python batch_test_live.py my_prompts.txt    # one prompt per line, your own file
    python batch_test_live.py --model llama3.2  # if you're not on phi4-mini

Requires Ollama actually running (`ollama serve`) with the model pulled,
same as running TOKI normally. Takes roughly (number of prompts) x
(your model's real per-turn time) to finish -- that's still real model
time, just unattended instead of you sitting there for each one.

Output: batch_test_results_<timestamp>.log in the current directory,
plus a live progress line printed to the terminal as each prompt
finishes, so you can glance at it without waiting for the whole run.
"""
import time
import argparse
from datetime import datetime
from unittest.mock import patch

from orchestrator import WindowsAIAssistant


# A real spread, covering categories that have actually caused problems
# in this project's history: plain chat (must never dispatch), the
# chain-splitting boundary types (,then / bare and / semicolon), known
# tricky app names, ambiguous phrasing, and a few flat-out nonsense
# inputs that should cleanly miss rather than confidently guess wrong.
DEFAULT_PROMPTS = [
    # Plain chat -- must stay conversational, never fire a command
    "hey how's it going",
    "tell me a joke",
    "what do you think about pineapple on pizza",

    # Known-good, single-step commands
    "take a screenshot",
    "what's the weather today",
    "clear the screen",

    # Chain-splitting: the exact boundary types this project has fixed bugs in
    "make a folder called TestFolder, then rename it to TestFolder2, then delete it",
    "take a screenshot and also empty the recycle bin",
    "open notepad; open calculator",

    # App-name matching: the exact kind of query that broke before
    "open vscode",
    "open VS Code",
    "launch chrome",

    # Ambiguous / should ask, not guess
    "open the thing",
    "delete it",
    "kill the lights",

    # Nonsense -- must miss cleanly, not crash, not fabricate an action
    "asdkfjhaslkdjfh",
    "how many licks does it take to get to the center of a tootsie pop",
]


def build_fake_running_command():
    """Returns a drop-in replacement for executor.RunningCommand whose
    .start() never touches subprocess -- it just calls on_done(0)
    (pretend success) on the same thread, synchronously, so the rest
    of the pipeline (history commit, narration join) proceeds exactly
    like a real successful run, without ever running anything."""
    class FakeRunningCommand:
        def __init__(self, command, on_output, on_done):
            self.command = command
            self._on_done = on_done

        def start(self):
            # Real RunningCommand streams output async on a thread and
            # calls on_done(returncode) when the process exits. Faking
            # a clean, instant success (0) is enough for the pipeline's
            # own bookkeeping (history, _remember_touched) to proceed
            # normally -- this script cares about what TOKI DECIDED to
            # run, not about a fake execution result.
            self._on_done(0)

        def stop(self):
            pass

    return FakeRunningCommand


class RealExecutionAttempted(RuntimeError):
    """Raised if anything ever actually tries to spawn a real process
    during a batch run -- see the tripwire in main() below."""


def _tripwire_popen(*args, **kwargs):
    raise RealExecutionAttempted(
        f"subprocess.Popen was called for real during a batch test run "
        f"-- this must NEVER happen; args={args!r} kwargs={kwargs!r}"
    )


def run_one(assistant, prompt, log_file):
    # CRITICAL: reset TOKI's own per-conversation state before every single
    # prompt. assistant is built ONCE and reused for the whole batch (real
    # Ollama connections/graph DBs are expensive to reopen per-prompt), but
    # that means self._pending/_pending_graph_ask/_last_touched/history all
    # persist across "unrelated" prompts in the list unless explicitly
    # cleared here.
    #
    # Found live, root-caused, not guessed: replaying the project's own
    # real 70-prompt list against the real pipeline showed
    # "display type of notes.txt" set self._pending (a genuine missing-slot
    # follow-up, the documented TYPE_INTO_ELEMENT/WCL `type` collision from
    # BETA 0.3.15) -- and every SINGLE ONE of the 47 remaining prompts in
    # that list was then silently swallowed by _resume_pending() as an
    # attempted ANSWER to that one stale question, never actually
    # classified at all. This matches, exactly, the long run of "[ 0.0s]"
    # entries at the tail of every real batch log this project has ever
    # produced (_resume_pending() skips graph classification and Ollama
    # entirely, so it returns near-instantly) -- roughly two-thirds of
    # every 70-prompt run, silently untested, since before this tool even
    # had the chain-splitting bug fixed.
    #
    # This reset intentionally makes every prompt fully independent (no
    # anaphora/history carryover) -- consistent with this file's OWN
    # existing DEFAULT_PROMPTS comment ("anaphora... included so their
    # MISSING/degraded behavior with NO prior context is also visible"),
    # i.e. testing degraded behavior WITHOUT context was always the
    # intent, this just makes it actually true instead of accidentally
    # true only for whichever prompt happens to follow a real question.
    assistant._pending = None
    assistant._pending_graph_ask = None
    assistant._last_touched = None
    assistant.history = []

    outputs = []
    thinking_tokens = []

    def on_output(text):
        outputs.append(text)

    def on_done(returncode):
        pass

    def on_thinking_token(token):
        thinking_tokens.append(token)

    start = time.time()
    try:
        # NOTE: must be process_request(), the public entry point app.py
        # itself calls -- it's the one that runs _split_chain_if_viable()
        # before dispatch. _process_single_request() is the INTERNAL
        # single-segment method; calling it directly (as this script did
        # before) silently skips chain-splitting entirely, so every
        # multi-step prompt in this batch's own prompt list got classified
        # as one giant unsplit segment instead of the real per-segment
        # behavior the app actually exhibits. Confirmed directly: on
        # "close chrome and open notepad", _process_single_request()
        # returns chained=None (one failed whole-string classification),
        # while process_request() returns chained=True with 2 real steps.
        result = assistant.process_request(
            prompt, on_output, on_done, on_thinking_token,
        )
        elapsed = time.time() - start
        error = None
    except Exception as e:
        elapsed = time.time() - start
        result = None
        error = repr(e)

    entry_lines = [
        f"PROMPT: {prompt}",
        f"TIME: {elapsed:.1f}s",
    ]
    if error:
        entry_lines.append(f"ERROR (pipeline raised): {error}")
    elif result.get("chained"):
        # Top-level intent/kind/narration on a chained result only mirror
        # the LAST step (see process_request()'s own docstring) -- write
        # every step separately here or the transcript silently hides all
        # but the final segment's decision, which defeats the point of
        # deliberately including chain-split prompts in this batch.
        steps = result.get("steps", [])
        entry_lines.append(f"CHAINED: {len(steps)} steps")
        for i, step in enumerate(steps, 1):
            entry_lines.append(f"  STEP {i} INTENT: {step.get('intent', '(none / chat)')}")
            entry_lines.append(f"  STEP {i} KIND: {step.get('kind', '?')}")
            step_narration = step.get("thinking") or step.get("response") or "(empty)"
            entry_lines.append(f"  STEP {i} NARRATION: {step_narration}")
            if step.get("command"):
                entry_lines.append(f"  STEP {i} WOULD-HAVE-RUN (not executed): {step['command']}")
    else:
        entry_lines.append(f"INTENT: {result.get('intent', '(none / chat)')}")
        entry_lines.append(f"KIND: {result.get('kind', '?')}")
        narration = result.get("thinking") or result.get("response") or "(empty)"
        entry_lines.append(f"NARRATION: {narration}")
        if result.get("command"):
            entry_lines.append(f"WOULD-HAVE-RUN (not executed): {result['command']}")
    entry = "\n".join(entry_lines) + "\n" + ("-" * 70) + "\n"

    log_file.write(entry + "\n")
    log_file.flush()
    if error:
        summary = "ERROR"
    elif result.get("chained"):
        summary = f"chained x{len(result.get('steps', []))}"
    elif result.get("intent"):
        summary = result["intent"]
    elif result.get("response"):
        # A real response with NO intent means TOKI correctly declined to
        # guess (e.g. a risky/ambiguous command) rather than genuine small
        # talk -- these used to both print as bare "chat", making it
        # impossible to tell "asked a clarifying question" apart from
        # "just chatted" at a glance. Distinguishing this is exactly the
        # point of testing destructive/ambiguous commands in this batch.
        summary = "ASK (declined to guess)"
    else:
        summary = "chat"
    print(f"  [{elapsed:5.1f}s] {prompt!r:60.60} -> {summary}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt_file", nargs="?", default=None,
                         help="Optional file, one prompt per line. Defaults to the built-in list.")
    parser.add_argument("--model", default="phi4-mini",
                         help="Ollama model name (default: phi4-mini, same as TOKI's default)")
    args = parser.parse_args()

    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompts = [line.strip() for line in f if line.strip()]
    else:
        prompts = DEFAULT_PROMPTS

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"batch_test_results_{timestamp}.log"

    print(f"Running {len(prompts)} prompts against a REAL Ollama instance "
          f"(model: {args.model}).")
    print("PowerShell dispatch is faked -- nothing will actually run on "
          "your machine.")
    print(f"Logging to {log_path}\n")

    FakeRunningCommand = build_fake_running_command()
    with patch("orchestrator.RunningCommand", FakeRunningCommand), \
         patch("subprocess.Popen", side_effect=_tripwire_popen):
        assistant = WindowsAIAssistant(model_name=args.model)
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(f"TOKI batch test run -- {timestamp}\n")
            log_file.write(f"Model: {args.model}\n")
            log_file.write(f"{len(prompts)} prompts, PowerShell dispatch faked (nothing executed)\n")
            log_file.write("=" * 70 + "\n\n")

            overall_start = time.time()
            for prompt in prompts:
                run_one(assistant, prompt, log_file)
            total = time.time() - overall_start

            summary = f"\nDone. {len(prompts)} prompts in {total:.1f}s total.\n"
            log_file.write(summary)
            print(summary)

    print(f"Full transcript: {log_path}")


if __name__ == "__main__":
    main()
