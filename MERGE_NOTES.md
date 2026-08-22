# Merge notes — BETA 0.3.53 (0.3.51-intents branch + 0.3.52-display branch)

## What was actually in the two uploaded zips

`TOKI-BETA-v0_3_51.zip` (internally versioned 0.3.50, STATUS.md header
"BETA 0.3.51") and `TOKI-BETA-v0_3_52.zip` (0.3.52) both branched from
the same 0.3.50 base but diverged into two unrelated pieces of work:

- **Intents/routing branch** (`v51`): expanded Tier A casual phrasing
  from 282 → 571 phrasings across 71 commands, fixed the `GENERATE_FILE`
  bug (it had zero phrasings in the graph so it could never be selected
  — this is why "create a function called X" fell through to Ollama),
  added a permanent self-consistency audit tool (`audit_tier_a.py`),
  startup cache priming, and an Ollama fast-fail cooldown.
- **Display/widget branch** (`v52`): DONE/INFO/ERROR display-strategy
  split (`display_strategy.py`), smooth entrance/exit animations, and
  sticky persistent UI in the floating widget.

These touched **disjoint files** apart from one place where the intents
branch added things the display branch never saw
(`app_control.py`/`orchestrator.py`/`synonyms.py` + their test files).
No line-by-line conflict resolution was needed — only a per-file choice
of which branch's version to keep:

| Kept from **intents branch** (v51) | Kept from **display branch** (v52) |
|---|---|
| `app_control.py` | `main_widget.py` |
| `orchestrator.py` | `toki_desktop_mark.py` |
| `synonyms.py` | `ui_theme.py` |
| `graph_source_data/tier_a_commands.json` | `display_strategy.py` |
| `graph_source_data/tier_a_phrasings.py` | `tests/test_display_strategy.py` |
| `audit_tier_a.py` | |
| `tests/test_graph_router.py` | |
| `tests/test_orchestrator.py` | |
| `tests/test_synonyms.py` | |
| `toki_graph_db/` (rebuilt, matches the new phrasings) | |

`vocab_staging.jsonl` (a runtime log, not source) was merged by
deduplicating on entry `id` — 675 + 619 entries → 705 unique.
`STATUS.md` was combined: both branches' full "BETA 0.3.51/0.3.52"
entries are kept in full (search for the "Merged-in:" headers), then
the shared older history continues unchanged below them.

## ⚠ The foreground_tracker fix is NOT in either zip

The chat log you pasted describes a session that root-caused the video
download / app-control focus bug to `_get_focused_window()` grabbing
whatever window has OS focus — which is always TOKI's own window right
after you type a command — and wrote `foreground_tracker.py` as a fix,
wiring it into `_get_focused_window()`'s fallback path.

**That file did not exist in either uploaded zip.** I checked directly:
no `foreground_tracker.py` anywhere, and `app_control.py`'s
`_get_focused_window()` was byte-identical between the two builds (only
difference in that whole file was v51's unrelated `prime_app_cache`
addition). Neither STATUS.md mentioned it either. My read is the zip
you downloaded was from before that code actually got written and
saved into your project folder, not after.

**Update: it's now implemented, in this same build (BETA 0.3.54, see
STATUS.md).** Written fresh from the description in your paste, since
no code from the original session was recoverable — new
`foreground_tracker.py`, wired into `app_control.py`'s
`_get_focused_window()` and started/stopped from
`orchestrator.py`'s `WindowsAIAssistant` lifecycle. 26 new tests
(`test_foreground_tracker.py` + additions to `test_app_control.py` and
`test_orchestrator.py`), full suite still green (1104 passed).
See STATUS.md's BETA 0.3.54 entry for the full writeup, and this file's
"Verified in this sandbox" section below for exactly what was and
wasn't confirmed.

## Verified in this sandbox

- `python -m pytest` (QT_QPA_PLATFORM=offscreen, no real display/Ollama
  available here): **1104 passed, 1 xpassed** (the xpass is a
  pre-existing known-gap test from the intents branch, not new; the
  count went from 1078 → 1104 with `foreground_tracker.py`'s 26 new
  tests added on top of the merge).
- `python audit_tier_a.py`: 0 self-consistency failures across all 571
  phrasings; same ~50 thin-margin (<0.05) pairs the intents branch's own
  STATUS.md entry already flagged as reviewed/acceptable.

**Not verified here (needs your real Windows/Ollama machine, same as
every prior session):** live PowerShell dispatch, live Ollama routing,
pywinauto/UI-automation paths, the widget's actual animations, and —
important for this session's new code specifically —
`foreground_tracker.py`'s real `ctypes`/`user32` calls
(`GetForegroundWindow`/`GetWindowThreadProcessId`/`IsWindow`) against
an actual desktop session. Every test for it mocks those three calls;
none of them can confirm the real Win32 behavior matches what's
assumed. Test the video downloader and an app-control click/type
command, right after switching window focus, before trusting it live.
Also worth re-running `python migrate_to_kuzu.py` yourself once, just
to confirm the checked-in `toki_graph_db/` (copied over from the
intents branch) truly matches the merged phrasings byte-for-byte rather
than only by directory size, which is all I could check here.
