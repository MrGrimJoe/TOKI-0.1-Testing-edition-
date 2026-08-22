"""
routing_test.py -- ad-hoc novel-phrasing routing test, NOT part of the
committed pytest suite. Purpose: STATUS.md itself flags that the existing
hit-rate numbers (98.8%, etc.) were measured against the graph's OWN
training aliases -- i.e. in-sample. This script instead hand-writes
phrasings a real user would plausibly type, deliberately avoiding the
exact alias strings baked into intents.py / windows_command_library, to
get an honest out-of-sample read on graph_router.py (Tier A) and
wcl_resolver.py (Tier B).

Each case is (query, expected_intent_or_None). expected=None means
"should NOT confidently dispatch" (either a genuine miss, or something
that should fall through to the LLM/ask rather than guess).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import graph_router
import wcl_resolver

# ── Tier A: novel phrasings for TOKI's own 60 hand-written intents ─────────
TIER_A_CASES = [
    # filesystem
    ("can you set up a new folder named Homework for me", "MAKE_FOLDER"),
    ("I need a blank file called notes.txt on my desktop", "MAKE_FILE"),
    ("get rid of the file called old_report.docx", "DELETE_ITEM"),
    ("change the name of budget.xlsx to budget_final.xlsx", "RENAME_ITEM"),
    ("take report.pdf and put it in the Archive folder", "MOVE_ITEM"),
    ("duplicate the resume.docx file into the Backups folder", "COPY_ITEM"),
    ("what's inside my Downloads folder", "LIST_FILES"),
    ("show me everything in D drive", "LIST_FILES"),
    ("organize my desktop by file type", "SORT_FOLDER_BY_TYPE"),
    ("locate every png on my desktop", "FIND_FILES"),
    ("open up config.json and show me what's in it", "READ_FILE"),
    ("how much space is D drive using", "DISK_USAGE"),
    ("are there any duplicate photos in my pictures folder", "FIND_DUPLICATE_FILES"),
    ("which of my files mention 'invoice'", "FIND_FILES_BY_CONTENT"),
    ("what's currently on my clipboard", "GET_CLIPBOARD"),
    ("put this text on the clipboard: hello world", "SET_CLIPBOARD"),
    ("which files in Desktop take up the most room", "LARGEST_FILES"),
    ("what did I just edit most recently on my desktop", "MOST_RECENT_FILES"),
    # process
    ("what programs are currently running", "LIST_PROCESSES"),
    ("force close spotify", "KILL_PROCESS"),
    ("which app is hogging the most CPU right now", "TOP_PROCESSES_BY_CPU"),
    ("pull up task manager", "OPEN_TASK_MANAGER"),
    # system
    ("how long has this pc been running", "SYSTEM_UPTIME"),
    ("what's this computer's name", "GET_HOSTNAME"),
    ("silence the volume", "MUTE_VOLUME"),
    ("grab a screenshot", "TAKE_SCREENSHOT"),
    ("lock my screen", "LOCK_WORKSTATION"),
    ("how much battery do I have left", "BATTERY_STATUS"),
    ("clear out the recycle bin", "EMPTY_RECYCLE_BIN"),
    # info
    ("is it going to rain today", "GET_WEATHER"),
    ("what's the forecast looking like this week", "GET_FORECAST"),
    ("what time is it right now", "GET_TIME"),
    ("what's today's date", "GET_DATE"),
    ("look up who invented the telephone", "SEARCH_WEB"),
    ("where am I right now", "GET_LOCATION"),
    # app control
    ("pull up chrome", "LAUNCH_APP"),
    ("hit the save button", "CLICK_ELEMENT"),
    # generation
    ("write me a short poem about autumn and save it", "GENERATE_FILE"),
]

# ── Tier B: novel phrasings for WCL commands (should resolve, not
#    necessarily auto-dispatch -- caution/destructive never auto-run) ──────
TIER_B_CASES = [
    "flush the dns cache on this machine",
    "show me all the network adapters",
    "what's my current ip configuration",
    "list every scheduled task set up on this computer",
    "check if the print spooler service is running",
    "show me recent entries in the system event log",
    "what version of windows am I running",
    "list every environment variable that's set",
    "restart the spooler service",
    "disable the bluetooth adapter",
]

# ── genuine misses / should NOT confidently dispatch ────────────────────────
SHOULD_MISS_CASES = [
    ("do you think I should switch careers", None),
    ("tell me a joke about programmers", None),
    ("what's the meaning of life", None),
    ("how are you feeling today", None),
    ("summarize the plot of inception", None),
]


def run_tier_a():
    gr = graph_router.GraphRouter()
    hits, misses, wrong = [], [], []
    for query, expected in TIER_A_CASES:
        result = gr.classify(query)
        got = result.get("intent") if result else None
        if got == expected:
            hits.append((query, expected))
        elif got is None:
            misses.append((query, expected, got))
        else:
            wrong.append((query, expected, got))
    return hits, misses, wrong


def run_tier_b():
    r = wcl_resolver.WCLResolver()
    resolved, unresolved = [], []
    for query in TIER_B_CASES:
        result = r.resolve(query)
        status = result.get("status")
        if status and status != "UNRESOLVED":
            resolved.append((query, status, result.get("command", result.get("name", "?"))))
        else:
            unresolved.append((query, result.get("loose_candidates", [])[:2]))
    return resolved, unresolved


def run_should_miss():
    gr = graph_router.GraphRouter()
    false_positives, correct_misses = [], []
    for query, _ in SHOULD_MISS_CASES:
        result = gr.classify(query)
        if result is not None:
            false_positives.append((query, result))
        else:
            correct_misses.append(query)
    return false_positives, correct_misses


if __name__ == "__main__":
    print("=" * 70)
    print("TIER A -- graph_router.py, novel phrasings, 38 cases")
    print("=" * 70)
    hits, misses, wrong = run_tier_a()
    for q, exp in hits:
        print(f"  HIT   {q!r} -> {exp}")
    for q, exp, got in misses:
        print(f"  MISS  {q!r} -> expected {exp}, got None (falls through to LLM)")
    for q, exp, got in wrong:
        print(f"  WRONG {q!r} -> expected {exp}, got {got}  <-- MISROUTE, real bug")
    n = len(TIER_A_CASES)
    print(f"\n  {len(hits)}/{n} correct hits, {len(misses)}/{n} misses, {len(wrong)}/{n} misroutes")

    print()
    print("=" * 70)
    print("TIER B -- wcl_resolver.py, novel phrasings, 10 cases")
    print("=" * 70)
    resolved, unresolved = run_tier_b()
    for q, status, cmd in resolved:
        print(f"  RESOLVED  {q!r} -> {cmd} ({status})")
    for q, cands in unresolved:
        cand_names = [c[0] for c in cands] if cands else []
        print(f"  UNRESOLVED  {q!r}  (loose candidates: {cand_names})")
    n = len(TIER_B_CASES)
    print(f"\n  {len(resolved)}/{n} resolved, {len(unresolved)}/{n} unresolved")

    print()
    print("=" * 70)
    print("SHOULD-MISS -- open-ended chat, must NOT graph-hit")
    print("=" * 70)
    fps, correct = run_should_miss()
    for q, res in fps:
        print(f"  FALSE POSITIVE  {q!r} -> {res}  <-- real bug, should have fallen to LLM")
    for q in correct:
        print(f"  correctly missed  {q!r}")
    n = len(SHOULD_MISS_CASES)
    print(f"\n  {len(correct)}/{n} correctly fell through, {len(fps)}/{n} false positives")
