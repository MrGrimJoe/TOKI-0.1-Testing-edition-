# PRIORITY — fast path, no fluff

Rule: don't re-test what's already verified. Only chase real open gaps.
Full detail always in STATUS.md — this file is just the sprint list.

**This file was last actively maintained around BETA 0.3.26 and had
drifted badly out of date (referenced 304-passed test counts, "current"
work from 20+ versions ago) — the item list below has been re-verified
live against the current graph (BETA 0.3.49) rather than carried forward
unchecked. Anything not listed here that used to be on this list has
either shipped (see STATUS.md) or was superseded by later work.**

## 🔴 REAL BUGS, reconfirmed still open (verified live, BETA 0.3.49)

- **"find files named report" confidently mis-fires to
  `FIND_DUPLICATE_FILES`.** Reconfirmed exactly as originally reported —
  unchanged since it was first found.
- **"update the date to tomorrow" → `GET_DATE`.** Reads instead of
  recognizing a set/change request — there's still no `SET_DATE` intent
  at all. Reconfirmed unchanged.
- **"kill chrome"/"stop chrome"/"close chrome" still don't confidently
  hit `KILL_PROCESS`.** Improved since originally reported, though: they
  now correctly fall to an "ask" (a specific, low-confidence
  `LAUNCH_APP` clarifying question) instead of silently failing outright
  — not fixed, but no longer a silent wrong dispatch either.
- **`wcl_resolver.py`'s "bitlocker" (one word) vs. "bit locker" (two
  words) alias mismatch** — not reverified this session (needs the WCL
  graph specifically, not just Tier A); flagging as still-presumed-open
  rather than silently dropping it.

## ✅ CONFIRMED FIXED SINCE LAST UPDATE (verified live, BETA 0.3.49)

- **"show contents of report.txt" no longer mis-fires to
  `GET_CLIPBOARD`** — now correctly asks about `READ_FILE` instead of
  silently picking the wrong intent.
- **"what is the scheduled task" no longer conflates Task Scheduler with
  Task Manager** — now correctly resolves to `LIST_SCHEDULED_TASKS`
  (added in BETA 0.3.25.75, per STATUS.md).

## 🟡 NARROW BY DESIGN — not gaps, just stated scope (unchanged)

- Scheduling is in-process only — doesn't survive TOKI closing (still
  true as of BETA 0.3.48's `SET_TIMER` addition, which uses the same
  `scheduler.py` engine).
- Conditionals only work for what can actually be read via a real
  PowerShell check (battery level, at last count) — see
  `condition_checker.py`'s `CHECKABLE_CONDITIONS` registry for the
  current list rather than trusting a number here.

## 🟡 UNVERIFIED — needs a real Windows machine, not this sandbox

- Live web search quality (real Wikipedia/DDG calls).
- Whether `scheduler.py`/`condition_checker.py`'s poll interval and
  timeout defaults are right for real usage.
- BETA 0.3.48's app-existence-check fallback and BETA 0.3.49's macro/
  dictation runtime-state check — both logic-verified against the test
  suite, neither exercised against real `Get-StartApps`/pywinauto calls
  yet (this sandbox has none).

## NEXT

- Decide whether "find files named report" / "update the date to
  tomorrow" are worth a dedicated pass, or fine to leave for now.
- Run the still-unverified items above on a real machine when convenient
  — nothing here is urgent enough to block on.
