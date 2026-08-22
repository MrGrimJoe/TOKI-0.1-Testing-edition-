# TOKI BETA 0.3.49

Created by **MrMIB**.

A Windows desktop assistant that executes instantly for anything
confidently safe, and — as of BETA 0.3.38 — asks a plain-text, one-line
question before running anything caution/destructive-rated, rather than
either a modal dialog or staying fully unreachable. The safety controls
are the sandbox (`D:\` and Desktop only), a conservative "don't auto-run
it if it isn't confidently safe" dispatch gate, that one narrow
confirmation step, and the always-visible Stop button.

> **Note on this file's age:** everything below `## v2.11 changes` is a
> changelog from an earlier phase of the project (the original Ollama-
> classification-only design, before the graph router/WCL resolver existed)
> and is kept only as historical context — it does **not** describe the app
> as it works today. `STATUS.md` is the actual up-to-date, chronological
> changelog (3,500+ lines); `PROJECT_STATE_OVERVIEW.md` is a shorter
> structured snapshot of current state. Everything from here down to that
> divider has been rewritten to match the code as of BETA 0.3.37.

## Status at a glance

**What it works on:** Windows only (PowerShell execution + pywinauto/UI
Automation for app control — both Windows-specific). Python 3.11+. A local
Ollama instance running a small model (phi4-mini recommended) as the
fallback for anything the router doesn't confidently resolve — most
requests never reach it at all (see "Flow" below). No cloud LLM calls and no
API keys anywhere — the only network calls this app makes are to Ollama
(localhost) and two keyless public APIs (Open-Meteo for weather/forecast,
ipinfo.io for one-time location caching). Web search is not an API call at
all as of BETA 0.3.44 — it builds a real search-engine URL and opens it in
Chrome; see "Web search" under Architecture below.

**Architecture, top to bottom:**
```
main.py            entry point — dependency check, then launches
                   main_widget.py
main_widget.py     the entire UI: no chat window, no text field. Just
                   DesktopMark (a small animated mark, top-centre) plus
                   the voice pipeline. Ctrl+K talks to it; double-click
                   the mark to type instead. One shared dispatch path
                   (`_dispatch_text`) handles both, on a plain background
                   `threading.Thread` per message (not a QThread) so Qt
                   stays responsive. Replies show as floating text next
                   to the mark (`mark.show_reply()`, fades after ~3s) —
                   see WIDGET_README.md for the mood/animation states.
toki_desktop_mark.py   `DesktopMark` itself, plus the 4 popup panels:
                   scheduled-commands panel, dictation stop panel, the
                   reply bubble, the typed-prompt box (all share one
                   palette/font/card recipe via `ui_theme.py`)
orchestrator.py    the brain (WindowsAIAssistant + OllamaRouter) —
                   process_request() runs the full pipeline below, in order
graph_router.py    Tier A — TOKI's own 80 hand-written intents, matched via
                   TF-IDF cosine similarity against a prebuilt Kùzu graph
                   database (toki_graph_db/); fast, deterministic, offline
wcl_resolver.py    Tier B — only consulted when Tier A misses; matches
                   against the 1,160-command Windows Command Library
                   (wcl_kg/windows_commands_db) through an ordered cascade
                   of increasingly-loose matching tiers
categories.py      7 Tier A categories, and the map from every Tier A
                   intent to its category
intents*.py        the closed Tier A vocabulary (80 intents across 3 files)
                   — each intent's description, execution "kind",
                   template/API binding, and required slot names
extractor.py       turns raw user text into slot VALUES via regex only, for
                   BOTH Tier A intents and eligible WCL commands — plus
                   sandbox path resolution and the fixed missing-slot
                   questions; never guesses when a value isn't confidently
                   present
scheduler.py       "in 10 minutes"-style scheduled requests — parsed ahead
                   of the main classification pipeline, handed to a
                   background timer. Backs two distinct intents:
                   SCHEDULE_COMMAND (a real command to run later, e.g.
                   "shut down in 10 minutes") and SET_TIMER (a bare
                   timer/reminder with nothing to run, e.g. "set a timer
                   for 10 minutes" / "remind me in 20 minutes to check the
                   oven") — kept separate as of BETA 0.3.48 because a bare
                   timer has no command to hand to the pipeline at fire
                   time; see STATUS.md's 0.3.48 entry for the bug this
                   split fixes.
condition_checker.py   "when the CPU drops below X"-style conditional
                   requests — a background poller, concurrency-safe against
                   cancellation races
executor.py        runs PowerShell as a real killable subprocess
app_control.py     UI Automation (pywinauto) — resolves "the Save button"
                   to real on-screen coordinates via fuzzy matching, never
                   the model; failure and success are cached separately so
                   a transient hiccup doesn't permanently degrade a feature.
                   Falls back to OCR (Windows.Media.Ocr) before asking the
                   user when UIA finds no accessible name close enough —
                   catches on-screen text with no exposed name at all
                   (Chrome/Copilot canvas & web-component surfaces)
apis.py            weather/search/time/location — the non-PowerShell
                   tools, with the same failure/success caching split.
                   Search builds a real search-engine URL and opens it in
                   Chrome — not an API call, no scraping
generator.py       GENERATE_FILE — the one place real free-text generation
                   happens, isolated from the command pipeline, written via
                   plain file I/O, never through a shell
voice_pipeline.py  Ctrl+K hotkey-triggered voice input — openWakeWord
                   (wake word), Silero VAD via ONNX (torch-free), and
                   faster-whisper (tiny.en, int8, CPU) for transcription.
                   Also: DictationPipeline for "start listening" —
                   continuous capture that types every utterance directly
                   into a target field until stopped, no per-utterance
                   round-trip through the classifier
```

**What works (wired end-to-end, per the current code):**
- **Tier A**: 80 hand-written intents across 7 categories (file
  operations, process control, system info, app launching/control via real
  UI Automation coordinates, one file-generation intent, one chat intent),
  matched via a Kùzu graph database, fully offline
- **Tier B**: 630 of the Windows Command Library's 1,160 commands are
  auto-dispatchable today — every `danger_level == "safe"` command at 0/1/2
  variable counts (see `PROJECT_STATE_OVERVIEW.md` §2 for the exact
  breakdown by danger level and variable count). `caution`/`destructive`
  commands never auto-dispatch, at any variable count, by deliberate design
- The destructive-shadow guard (`orchestrator.py::_check_destructive_shadow`)
  — if Tier A matches something, this independently checks whether WCL also
  has a genuinely destructive command for the same phrase, and asks a
  clarifying question instead of silently trusting Tier A's guess
- Regex-only slot extraction (single-variable AND 2-variable WCL commands,
  plus a numeric-hint strategy for path+count/size pairs like "show me the
  5 largest files") with a fixed follow-up question whenever a required
  slot can't be confidently pulled from the message — never invented
- Sandbox enforcement to `D:\` and the real Desktop (resolved via Windows'
  own known-folder API, not assumed from `%USERPROFILE%`)
- Command-injection protection on every PowerShell template substitution —
  `_ensure_quoted_placeholders()` + `_escape_ps_slot()` guarantee a value
  lands inside a fully-literal, properly-escaped string regardless of how
  the source template itself was written
- A categorical blocklist for variables representing literal code/
  scriptblock content, and a path-variable allowlist routing 23 distinct
  variable names through the sandboxed `resolve_path()` rather than
  trusting them as free text
- PowerShell execution with live streaming output and a Stop button that
  kills the whole process tree
- Weather/forecast (Open-Meteo), web search (builds a real search-engine
  URL, opens it in Chrome — no search API, no scraping), time/date, cached
  location
- File generation: streamed model content written straight to a sandboxed
  file via plain Python I/O, never through a command string
- App control: launch apps, click/double-click/right-click/type into
  whatever's focused, via fuzzy-matched real UI Automation coordinates —
  falls back to OCR (Windows.Media.Ocr) before giving up, then fails safe
  (no click) if nothing matches confidently either way
- Continuous dictation ("start listening"): types everything said directly
  into a target field until stopped (widget stop button, or "stop
  listening") — resolves the target from what's already focused, a named
  description, or a one-time click, never a guess
- Macro capture ("start seeing"): records real clicks/keypresses to replay
  later under a name you give it (`macro_recorder.py`). A bare "start
  recording" (no object word) is genuinely ambiguous between this and
  dictation above — as of BETA 0.3.49, TOKI asks once rather than
  guessing; "start recording what I click" / "what I say" both still
  resolve instantly with no question. See STATUS.md's 0.3.49 entry.
- Command chaining ("make a folder and then open it")
- Scheduled ("in 10 minutes") and conditional ("when the CPU drops below X")
  requests, handled by a separate pre-check before the main pipeline
- Ctrl+K voice input, fully offline (wake word + VAD + transcription)
- `//command` direct override and `""`/`''` literal-value quoting, both of
  which skip classification/heuristic guessing entirely when used
- Live streaming narration for the LLM-fallback path
- Creator identity (MrMIB) known to the model

**What's still under dev / known gaps** (see `PROJECT_STATE_OVERVIEW.md` §3
for the full, current list — this is a summary):
- No generic slot-filler for 3+ variable WCL commands (181 of them)
- No auto-dispatch for `caution`/`destructive` WCL commands at any
  variable count — deliberate, not a gap
- No auto-dispatch for `caution`/`destructive` WCL commands without
  confirmation — as of BETA 0.3.38 these pause and show the exact
  command via a plain-text question (a bare Enter or an avatar click
  both confirm) instead of being 100% unreachable; still no MODAL dialog
  anywhere, and 3+ variable commands remain entirely out of scope either
  way
- No full natural-language-coverage audit of the 1,160-command WCL alias
  dataset — only targeted audits so far
- No live Ollama or live Windows testing anywhere in this project's recent
  history — everything is verified via direct unit/integration testing of
  the Python logic
- Windows-only — no macOS/Linux support, since PowerShell and pywinauto's
  UI Automation backend are both Windows-specific

**Capabilities, in plain terms — what you can actually ask it:**
- *Files/folders* (sandboxed to `D:\`/Desktop): create, delete, rename,
  move, copy, list, find, read, open; disk usage; path existence/
  properties/resolve/split; count files/folders; file-type breakdown; find
  duplicates; find files by content; clipboard get/set; export a folder
  listing to CSV; largest/most-recent/oldest files, largest folders (with
  an optional count, e.g. "show me the 5 largest files"); find files over
  a given size ("find large files over 500MB")
- *Processes*: list, find, wait for, kill by name; top CPU consumers; open
  Task Manager
- *System*: uptime, hostname, locale, printers, USB devices, temperature
  sensors, services, mute/volume, screenshot, lock the workstation, battery
  status, empty the Recycle Bin, network info, current user, basic system
  info; plus 1,160 real Windows commands via Tier B, for anything Tier A's
  own 80 intents don't cover
- *Info lookups*: current weather/forecast (by city or your cached
  location), time, date, your location, web search
- *App control*: launch any app by name; click/double-click/right-click/
  type into whatever's currently focused on screen
- *File generation*: ask for a script/document/etc. and get real generated
  content written to a sandboxed file
- *Scheduling*: "shut down in 10 minutes" (a real command, later) / "set a
  timer for 10 minutes" or "remind me in 20 minutes to check the oven" (a
  bare timer/reminder, nothing to run — just a notification when it's up,
  as of BETA 0.3.48) / "when the CPU usage drops below 20%, tell me"
- *Chaining*: multi-step single messages ("make a folder called Homework
  and then open it")
- *Voice*: press Ctrl+K and speak, fully offline
- *Chat*: anything else, conversational, via the local Ollama fallback

## How a message actually flows through the app

```
your message
   -> canned replies (a handful of greetings/thanks) get an instant, fixed
      response with zero model calls                                        [orchestrator.py]
   -> scheduling / conditional pre-check ("in 10 minutes" / "when X drops
      below Y") gets parsed and handed to a background timer/poller,
      separate from everything below                                        [scheduler.py, condition_checker.py]
   -> Tier A: the graph router tries TOKI's own 80 intents against a
      prebuilt Kùzu graph via TF-IDF cosine similarity                       [graph_router.py]
   -> Tier B: only if Tier A missed, the WCL resolver tries the
      1,160-command Windows library through its ordered matching cascade    [wcl_resolver.py]
   -> the destructive-shadow guard: if Tier A DID match something, this
      independently asks WCL "is there also a genuinely destructive
      command for this same phrase?" and asks the user instead of
      silently trusting Tier A's guess if so                                [orchestrator.py]
   -> the WCL eligibility gate: a RESOLVED WCL command only becomes
      directly runnable if danger_level == "safe", at every variable count  [orchestrator.py]
   -> slot extraction: regex-only, for both Tier A intents and eligible
      WCL commands — asks a fixed follow-up question if a required value
      can't be confidently pulled from the message, never guesses          [extractor.py]
   -> anything that falls through all of the above (a genuine miss, or an
      ineligible/ambiguous/dangerous WCL match) goes to Ollama for
      open-ended handling                                                    [orchestrator.py::OllamaRouter]
   -> dispatch: runs the PowerShell command as a real, killable subprocess,
      or calls the relevant tool (weather/search/location, UI Automation,
      file generation)                                                       [orchestrator.py::_dispatch, executor.py]
```

A message can also contain more than one request, split on literal
conjunctions the user actually typed ("and then", "then", ";", ", and").
Each resulting piece runs through the exact same pipeline above, in order,
capped at 4 segments — this is deliberately **not** a general planner:
there's no model call deciding how to break up the request, and no
inferred steps beyond what's literally separated in the user's own text.

## Safety model

TOKI has **no MODAL permission dialogs**. Safety comes from four things
working together, not from a dialog box on every action:

- **Not auto-running things that aren't confidently safe** — Tier A intents
  are a hand-vetted closed set; Tier B (WCL) only auto-dispatches commands
  whose `danger_level` is `"safe"`, at every variable count including zero.
  `caution`/`destructive` commands (0/1/2 variables) now pause for a plain-
  text confirmation instead (BETA 0.3.38, see below) — never straight to
  execution without it, and 3+ variable commands remain unreachable either
  way.
- **A narrow, single-choke-point confirmation step for the one case above**
  — `orchestrator.py`'s `_dispatch_or_confirm()` is the one place every
  dispatch-ready call site routes through, so it can't be accidentally
  bypassed at a new call site. Shows the EXACT command that would run
  (built by the same code path the real dispatch uses, so the preview can
  never drift from reality), renders through `"kind": "chat"` — the same
  plain-text path as any other response, no modal, no new UI needed. A
  bare Enter, a short word ("y"/"yes"/"ok"/"confirm"/"run it"), or an
  avatar click all confirm; anything else cancels silently and that
  message is processed as an ordinary new turn.
- **A sandboxed filesystem boundary** — every resolved path is checked
  against `D:\` and `%USERPROFILE%\Desktop` only (`extractor.get_sandbox_roots`
  / `is_within_sandbox`). Anything outside — System32, Program Files, `..`
  traversal — is rejected before it ever reaches PowerShell. A curated
  allowlist of 23 WCL variable names is routed through this same sandbox
  rather than trusted as free text (e.g. `call {batch_file}` can't be
  pointed at an arbitrary script anywhere on disk).
- **An always-visible Stop button** — not just while busy. Calls
  `WindowsAIAssistant.stop()`, which cancels the in-flight Ollama request
  and/or kills the running PowerShell process tree (`taskkill /F /T`) so a
  bad call can be killed the instant it looks wrong.

On top of those three, a few more specific mechanisms close narrower gaps
found by testing (see `PROJECT_STATE_OVERVIEW.md` §4 for the full history
of what was found broken and fixed):

- Every PowerShell template substitution goes through a quote-state-
  tracking scanner (`_ensure_quoted_placeholders()`) plus backtick/`$`
  escaping (`_escape_ps_slot()`) — closes a confirmed-live command-
  injection path that existed in 297 of 298 single-variable "safe" WCL
  commands before it was fixed.
- A categorical blocklist (by variable name substring) for WCL variables
  representing literal code/scriptblock content — quoting alone doesn't
  protect against PowerShell implicitly compiling a string into an
  executable scriptblock for certain parameter types.
- The destructive-shadow guard described above.
- **Delete** goes through the Shell COM `InvokeVerb('delete')`, i.e. the
  Recycle Bin, not a permanent delete.
- **Chaining has a hard cap** (`_MAX_CHAIN_SEGMENTS = 4`) and stops
  immediately if any segment needs clarification, rather than guessing at
  later steps out of order.

## Requirements

- Windows (PowerShell execution + UI Automation are Windows-only)
- Python 3.11+
- [Kùzu](https://kuzudb.com/) (`kuzu>=0.11.0`) — the embedded graph database
  behind Tier A's router and Tier B's WCL matching. Not optional: this is
  how the majority of requests get handled before any LLM call happens.
- [Ollama](https://ollama.com/), with a small model pulled — **Phi-4-mini**
  is the recommended default for a 7GB VRAM budget, used only as the
  fallback path for requests neither Tier A nor Tier B resolves:
  ```
  ollama pull phi4-mini
  ```
- `pywinauto` + `comtypes` (Windows-only) for `app_control.py`'s real
  on-screen coordinate resolution.
- `openwakeword` + `faster-whisper` + `sounddevice` for the optional Ctrl+K
  voice pipeline (wake word, offline transcription, mic capture) — TOKI
  runs fine without these installed, just without voice input.
- `PyQt6-WebEngine`, optional — only needed to see the animated header icon
  and desktop overlay actually animate; both fail soft to a static
  placeholder without it.
- `yt-dlp` for `DOWNLOAD_PLAYING_VIDEO`/`DOWNLOAD_VIDEO_URL` (BETA
  0.3.44), plus the `ffmpeg` binary on PATH (not pip-installable) for
  audio-only extraction or merging separately-served video+audio
  streams. `websocket-client`, optional — only needed for the CDP
  "which tab is actually playing a video" probe in
  `video_downloader/cdp_now_playing.py`; without it, video-download
  falls straight through to the focused-browser-address-bar fallback.

See `requirements.txt` for exact version pins and per-package rationale.

## Run it

```
pip install -r requirements.txt
python main.py
```

## Run the tests

```
pytest tests/ -q
```

Currently: 536 passed, 1 skipped (environment-dependent), 2 xfailed (both
pre-existing, unrelated, documented gaps) — see `PROJECT_STATE_OVERVIEW.md`
for what those xfails are. This is the fast, fully-offline, deterministic
suite (no live Ollama, no live Windows needed) that covers the router, the
WCL resolver, the extractor, the safety guards, and the orchestrator's
dispatch logic directly.

`run.ps1` / `run_all_tests.py` also exist for driving live-Ollama batch
tests (`batch_test_*.py`) on top of the pytest suite — see those scripts'
own `--help` / comment headers for current flags, since their scope is
separate from (and slower than) the pytest suite above.

## APIs used

- **Weather**: [Open-Meteo](https://open-meteo.com/) — free, no key required.
- **Search**: not an API. As of BETA 0.3.44, `WebSearchAPI` builds a real
  search-engine URL (Google by default; native YouTube/GitHub/Maps search
  URLs available via a `site=` param, not yet auto-detected from free
  text — see `STATUS.md`) and opens it in Chrome. No search API, no HTML
  scraping, no knowledge-graph lookup standing in for a real search.
- **Time/date**: pure Python (`datetime.now()`), zero network calls.
- **Location**: IP-based geolocation via ipinfo.io, fetched once at
  startup (off the UI thread) and cached for the session.
- **OCR**: `Windows.Media.Ocr` via the `winsdk` package — a WinRT API
  already built into Windows 10/11, no separate engine or model download.
  Optional fallback for `click()`/`type_text()` when UI Automation finds
  no accessible name close enough; not verified against real Windows yet
  (see `STATUS.md`).

## File generation

`GENERATE_FILE` is fully wired end to end in `orchestrator.py`:
`generator.py` streams generated content token-by-token via
`on_generate_token`, then calls `on_generate_done(path, error)` once the
file is saved. **The current widget UI doesn't consume that streaming,
though** — `main_widget.py`'s `_dispatch_text` calls `process_request()`
without passing `on_generate_token`/`on_generate_done` at all (they
default to `None`), so there's no live preview today; the mark just
shows "working" until the whole turn finishes, then `show_reply()` shows
the final result. The streaming plumbing is real and there for a future
UI that wants it (or a `main_widget.py` change to wire it up) — it's
just unused right now. Writes are plain Python file I/O — never through
PowerShell — and still land inside the same `D:\`/Desktop sandbox as
everything else.

## Video download (BETA 0.3.44)

`DOWNLOAD_PLAYING_VIDEO` ("download this video") and `DOWNLOAD_VIDEO_URL`
("download this link") wrap `yt-dlp`, saving into a sandboxed
`Desktop/TOKI Downloads` folder. `DOWNLOAD_PLAYING_VIDEO` resolves its
own URL at dispatch time via `video_downloader/now_playing.py`, in two
steps:

1. **CDP probe** (`video_downloader/cdp_now_playing.py`, needs the
   optional `websocket-client` package and a browser already running
   with `--remote-debugging-port` open) — asks each open tab directly
   whether it has an actually-playing `<video>` element, independent of
   window focus.
2. **Address-bar fallback** (the original approach, always available) —
   reads the focused browser window's address bar via UI Automation.
   Honest limits, not glossed over: the address-bar label list is
   curated (Chrome/Edge/Firefox-family only), and absent step 1 there's
   no reliable, extension-free way to know *which tab's video* is
   playing versus just which page is focused.

See `STATUS.md`'s BETA 0.3.44 entry for the full integration writeup,
including a phrasing-regression that was found and reverted during
testing (a cautionary note about `graph_source_data/tier_a_phrasings.py`
edits' corpus-wide side effects).

## File organization (BETA 0.3.44, checkpoint 4)

Two DIFFERENT intents, easy to conflate from casual phrasing but handled
oppositely:

- **`ORGANIZE_FILES_BY_TOPIC`** ("organize my files by topic") — the
  graph-based organizer. No LLM. Scores every loose file against
  existing subfolders using six evidence types (filename similarity,
  extension match, related-file count, recent activity, content-hash
  duplicate, extracted-text overlap — see `file_graph/scoring.py`),
  bands the result (>90% auto-moves it, 60–90% surfaces as an
  explained suggestion, <60% leaves it alone), and can only ever move a
  file into a folder that **already exists and already has related
  content** — it never invents a new folder from a guessed topic.
  Learned per-evidence-type weights persist in their own Kùzu database
  (`file_graph_db/`) and nudge up on every accepted move.
- **`GROUP_FILES_BY_EXTENSION`** ("put the pdfs and json files in a new
  folder named rezero") — the opposite posture: a fully explicit
  instruction with no scoring at all. Creates the named destination
  folder if it doesn't exist (the user named it, nothing invented) and
  moves every matching file in immediately.

Both move files via plain `shutil.move()`, never a PowerShell template —
see `STATUS.md`'s checkpoint-4 entry for the full design writeup, a real
bug fix that came out of testing this (`extractor.is_within_sandbox()`
wasn't normalizing sandbox root strings), and three separate rounds of
real-world routing regressions found and fixed via a 194-prompt
before/after diff against this repo's own `batch_test_prompts_*.py`
files.

## Command chaining

A message can contain more than one request, split on literal conjunctions
the user actually typed — "and then", "then", ";", ", and". Each resulting
piece runs through the exact same single-request pipeline as any other
message, in order, capped at 4 segments, and each shows its own result in
the chat. This is deliberately **not** a general planner: there's no model
call deciding how to break up the request, and no inferred steps beyond
what's literally separated in the user's own text — same "never let the
model invent structure" rule that governs slot extraction everywhere else
in this app. See `orchestrator.py`'s `_split_chain()` docstring for the
full reasoning, including why a bare "and" without "then" or a comma
deliberately does *not* split (so a folder literally named "Homework and
Projects" doesn't get chopped in half).

## Extending the intent list

**Tier A (a new hand-written intent):** add a new entry to
`INTENTS_EXTENDED` (or a new file, following the same shape) with a
description + PowerShell template + slots, register it in `categories.py`'s
`INTENT_CATEGORY` map (required — `orchestrator.py` asserts every intent
has a category at import time), and add a matching branch in
`extract_slots()` in `extractor.py` if it needs non-trivial variable
extraction. Then re-run the graph-database build step so the new intent's
phrasing corpus is actually indexed (see `migrate_to_kuzu.py`).

**Tier B (unlocking more of the existing WCL dataset):** the 1,160 commands
already exist in `wcl_kg/windows_command_library.widened.json` — most of
the extension surface here isn't adding new commands, it's extending
`extractor.py`'s generic WCL slot-filler to cover more variable-count/shape
combinations (see `_extract_wcl_slots()` / `_extract_wcl_slots_pair()` /
`_extract_wcl_numeric_pair()`), or deciding whether/how `caution`/
`destructive` commands should ever become dispatchable (currently: never,
by design).

If a template has zero slots but still contains literal PowerShell braces
(`if (...) { ... }`), escape them as `{{ }}` — every template goes through
Python's `.format(**slots)`, so an unescaped brace will raise at dispatch
time even with an empty slots dict.

## Earlier history (v2.6 – v2.11), condensed

This project used "v2.x" versioning before switching to the `BETA 0.x`
scheme `STATUS.md` uses today — these entries predate that switch and
describe the **old `app.py` chat-window UI**, which no longer exists
(the project is widget-only now — `main_widget.py` — and is staying
that way; see the note at the top of this file). Condensed here rather
than kept in full, both because the versioning scheme changed and
because several of these entries describe UI classes (`ChatBubble`,
`MainWindow`, `Worker`) that were later deleted outright, not just
renamed — keeping them in full would describe code that doesn't exist
anywhere in this repository anymore.

**Fixes that were about the classification/dispatch pipeline (still
relevant — this logic lives in `orchestrator.py`, used by the current
widget UI too, not just the old chat window):**
- The fabricated-narration bug (LLM narrating actions it never actually
  took) was fixed structurally in `orchestrator.py`'s `_dispatch()`, not
  by prompt-tuning — later superseded by BETA 0.3.23's complete removal
  of LLM narration from command-dispatch paths (see `STATUS.md`).
- Classification prompts fixed to actually use conversation history
  (previously ignored it entirely on both the tier-1 classify call and
  CHAT-kind narration).
- Chaining added (`_split_chain()` in `orchestrator.py`, wrapping
  `_process_single_request()` to run multiple split segments in
  sequence) — this is the same chaining mechanism still in use today.
- File generation (`GENERATE_FILE`) enabled and wired end-to-end.
- Web search fixed (Wikipedia search+summary replacing a
  DuckDuckGo-only implementation) and query-extraction filler-word
  stripping fixed to match `LAUNCH_APP`'s approach.
- `""`/`''` explicit-literal quoting convention and `//command` direct
  override both added — both still current, see the extractor/WCL
  sections above.
- A real Windows startup bug fixed (`pywinauto`'s `CoInitializeEx` at
  import time colliding with Qt's own `OleInitialize()` if pywinauto
  was imported before `QApplication()` existed) — `_load_pywinauto()`'s
  lazy-import pattern in `app_control.py` is the fix, and it's still
  the current mechanism (see `_PYWINAUTO_AVAILABLE`'s tri-state design).

**Fixes that were specifically about `app.py`'s chat UI (no longer
applicable — kept only as a record that these were real, fixed bugs at
the time, not to describe anything current):** the "two replies" bug
(collapsible thinking widget removed, narration streamed into one
answer label), `ChatBubble.add_step_block()` rendering multi-step
chains, a busy-indicator animation, bubble alignment/styling, an
"intent pill" showing the two-tier classification decision. All of this
UI was later replaced wholesale by the widget (mark + floating reply
text, no chat window at all — see `main_widget.py`/`WIDGET_README.md`),
which solves the same "show the user what's happening" problem
differently rather than carrying any of this forward.

