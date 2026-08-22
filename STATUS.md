# TOKI — current status

## BETA 0.3.65 — Full routing-pipeline stress test (Tier A + WCL, no UI/Ollama)

User asked for maximum stress testing of the routing/dispatch layer
(everything except the PyQt6 widget and Ollama narration -- neither
available in this sandbox anyway) and specifically flagged concern that
Tier B (the broader windows_command_library) historically wasn't wired
into dispatch at all. Investigated and tested exhaustively, not sampled:

**Tier B IS wired into dispatch, and correctly gated.** This was true
before this session too (BETA 0.3.14's slot-filler + 0.3.37/0.3.38's
extension to 2-variable/any-danger-level with confirmation-first) --
the concern the user recalled (0.3.25.75's STATUS.md note: "Tier A/B
priority architecture itself deliberately not touched -- still open for
future collisions") was about a DIFFERENT, narrower gap that has since
been fixed (`_check_destructive_shadow()` / priority.md #11, present in
this checkpoint already) -- see `orchestrator.py` around
`_check_destructive_shadow`/`_dispatch_or_confirm`/`_ask_for_confirmation`.

New `stress_test_routing_pipeline.py` (kept in the tree as a repeatable
regression check): exercises the real `WindowsAIAssistant.process_request()`
pipeline end-to-end with `RunningCommand.start()` patched out (same safe
pattern as `batch_test_live.py`), no Ollama/network/Windows dependency.

- **Exhaustive sweep of every destructive-level WCL command with 0-1
  variables (120 commands)**, each dispatched via its own real alias
  (guaranteed RESOLVED, not a fuzzy guess), with Tier A's graph_router
  patched to miss so the sweep isolates the WCL_ confirmation gate
  specifically (see the test's own docstring for why -- many WCL alias
  strings collide by pure vocabulary with Tier A's own hand-built
  intents, e.g. "clean recycle bin" also matches native
  `EMPTY_RECYCLE_BIN`, which is a documented, deliberate no-confirmation
  design for Tier A's own ~74 reviewed commands, a DIFFERENT and
  separately-correct safety model from WCL's). **120/120 passed** --
  every one produced a safe halt (confirmation question), none
  auto-dispatched.
- **Exhaustive sweep of every caution-level WCL command with 0-1
  variables (94 commands), same isolation.** 93/94 passed. The one
  exception (`Stop-ScheduledTask` via alias "cancel scheduled task") is
  NOT a safety bug -- investigated fully: a pre-graph-router regex
  heuristic (`looks_like_cancel_scheduled()` in extractor.py, there for
  TOKI's own native in-app scheduled-command feature) intercepts any
  "cancel"+"scheduled task"-shaped phrase before either router ever
  runs, permanently shadowing this one WCL cmdlet for that exact
  phrasing family. Confirmed the actual runtime outcome is harmless: "Done.
  Couldn't find "task" to cancel. Currently active: none." -- a no-op
  reply, never an unconfirmed dispatch. Flagged as a real, minor
  phrasing-coverage gap (Stop-ScheduledTask becomes unreachable via that
  specific wording), not fixed this session -- fixing it means either
  narrowing the regex or adding a disambiguation step, a product
  decision better made deliberately than folded into a stress-test pass.
- Fresh (not from any training corpus) adversarial phrasings for the
  Tier-A-vs-destructive-WCL shadow-check, confirmation-then-cancel,
  confirmation-then-yes (verified `RunningCommand.start()` is actually
  reached only after an explicit "yes", via a `MagicMock` call-count
  check, not just response-text inference), 3+ variable WCL commands
  correctly never silently auto-dispatching, `tier_a_wcl_map.is_equivalent()`
  spot-checked against 3 known-should-NOT-match pairs (none false-positive),
  and a chained request ("make a folder ... and then run diskpart") still
  gating the destructive half. All passed.
- Also re-ran the pre-existing `audit_tier_a.py` self-consistency sweep
  against the full 592-phrasing Tier A corpus: 0 self-consistency
  failures (56 thin-margin pairs flagged as pre-existing, informational,
  not failures -- unchanged from before this session).

Full pytest suite re-confirmed clean after all of the above: 1299
passed, 68 skipped, 2 deselected, same 11 pre-existing sandbox-only
failures (PyQt6 dictation deps/pandoc/yt-dlp-ffmpeg, unrelated).

## BETA 0.3.64 — WCL alias fixes merged into main tree + natural-phrasing gap batch 2

Previous session's `wcl_fixes.zip` (2 real resolver bugs fixed, 25
hand-reviewed natural-phrasing aliases added) had been delivered as a
**standalone** zip, never actually merged into the project tree --
`wcl_resolver.py`, `tests/test_wcl_resolver.py`, and
`wcl_kg/windows_command_library.widened.json` + its compiled
`windows_commands_db` were still the old pre-fix versions here. Merged
all of it in this session (diffed and copied over the 3 files, kept
this tree's own `wcl_kg/add_coverage_aliases.py`/`rebuild_graph.py`/
`vocab.py`/`pipeline_scripts_reference/` unchanged since the fix didn't
touch those). Re-verified after merging, not just copied blind: full
`tests/test_wcl_resolver.py` (63 passed), the broader wcl/graph_router/
component suite (367 passed), `full_sweep.py` (13,805 aliases, 0 real
mismatches, 0 false-unresolved), and `stress_wcl.py`'s 58-query battery
(32 resolved/9 ambiguous/17 unresolved) all reproduced the prior
session's exact reported numbers on this tree.

**Batch 2 of the natural-phrasing gap** (prior session stopped at 25 of
311, flagged 286 remaining as needing the same human-reviewed treatment):
reviewed all 293 (quantify_gap.py's number shifts slightly run-to-run
depending on padding-verb edge cases; not exactly 286) remaining gap
commands by hand. Finding: ~285 of them are enterprise/datacenter-only
cmdlets -- Hyper-V VM sub-component config (SR-IOV queue pairs/VFs,
RemoteFX 3D adapters, VM Fibre Channel HBAs, replication authorization
entries), SAN "storage enclosure" hardware management (firmware,
vendor data, SAS/FC ports, LUNs, IOPS/latency telemetry), Active
Directory domain-controller DHCP/DNS-*server*-role administration, and
IPsec main/quick-mode policy rule sets. None of these have a genuine
casual phrasing a normal person running TOKI on their own PC would ever
type -- forcing one on would recreate the exact fake-alias problem this
fix effort exists to eliminate (see `wcl_kg/add_natural_phrasing_
aliases_batch2.py`'s docstring for the full reasoning). Added exactly 4
real, unambiguous, grounded aliases where a genuine gap existed: `disk
space` (Get-DiskSpaceSummary), `file sharing settings`
(Get-SmbServerConfiguration), `show dns cache`/`show my dns servers`
(Get-DnsClientCache/Get-DnsClientServerAddress -- the client-side
cmdlets, i.e. this PC's own resolver, deliberately distinct from the
DNS-*server*-role cmdlets of the same shape). Rebuilt the graph
(`wcl_kg/rebuild_graph.py`), alias count 13,805 → 13,809, updated the
pinned-constant regression-guard test with the same reasoning its own
docstring asks for. Re-validated: 63/63 resolver tests, 367 wcl/
graph_router/component tests, full_sweep.py still 0 mismatches at the
new 13,809 scale, quantify_gap.py's remaining-gap count 293 → 289.
Remaining ~289 gap commands are the enterprise-only set above --
deliberately not force-padded, open for the user's own judgment call on
whether any of TOKI's actual users would ever hit them.

Full project suite (excluding tests/test_voice_pipeline.py, which needs
PyQt6 not present in this sandbox): 1299 passed, 68 skipped, 2
deselected, 11 failed -- all 11 failures pre-existing sandbox-only gaps
unrelated to this session's changes (missing PyQt6 dictation pipeline,
pandoc, yt-dlp/ffmpeg), same class of failure flagged by prior sessions.

## BETA 0.3.63 — "run vscode" fixed; two remaining items reclassified after investigation

**Fixed, tested (1332 passed, 65 skipped, 0 failed):**

`"run vscode"`/`"run chrome"` didn't route to `LAUNCH_APP` -- neither
`ACTION_OPEN` nor `ACTION_START_PROGRAM` had a bare `"run"` alias despite
this file's own earlier notes claiming it should. Added `"run"` to
`ACTION_START_PROGRAM`'s alias list, rebuilt the graph (`migrate_to_kuzu.py`
then `python3 build_component_graph.py toki_graph_db` -- the first alone
drops the Component table, needs the second to reload it, see this same
note pattern already in this file from 0.3.42), confirmed no collision
with `"start up chrome"` or `"start a new file"` (MAKE_FILE). New test
file `tests/test_launch_app_run_alias.py`.

**One real, known side effect of this fix, pinned by its own test:**
`RUN_MACRO` has zero taxonomy coverage anywhere in this codebase (no
component map entry, no `tier_a_phrasings.py` entries) -- it wasn't
reachable via either router before this change regardless. Now
`"run my morning macro"` confidently resolves to `LAUNCH_APP` instead of
an honest miss. Not a regression to anything that worked, but flagged so
whoever gives RUN_MACRO real training data adds a forbidden-macro guard
to `LAUNCH_APP` at the same time -- see the comment on
`ACTION_START_PROGRAM` in `graph_source_data/tier_a_components.py` and
`TestRunAliasKnownRemainingGap` in the new test file.

**Investigated, NOT fixed, reclassified from "quick fix" to "needs
scoping":**

- **`"open powershell and ms word"` (single verb, and-joined list of two
  targets) turned out to be a different, bigger problem than it looked.**
  `_CHAIN_SPLIT_RE` DOES split on bare `" and "` already (no comma
  required) -- the actual reason this doesn't split into two `LAUNCH_APP`
  dispatches is that `_segment_is_viable()` correctly rejects the second
  segment ("ms word" alone, no verb) as not a real independent
  instruction, and falls back to the whole unsplit sentence. That's the
  *existing* chain-splitter working as designed (it splits sequential
  commands like `"close chrome and open notepad"`, each with its own
  verb) -- `"open X and Y"` is a single English list construction with
  one elided verb applying to both targets, which is a genuinely
  different capability (list-splitting, not chain-splitting) than what
  `_segment_is_viable`'s whitelist mechanism does today. Needs real
  design/scoping, not a one-line whitelist tweak.
- **`"clean temp files"` WCL collision** -- re-confirmed still
  reproduces (`COUNT_FILES` instead of the intended cleanup command).
  This is the same one flagged back in BETA 0.3.14 ("investigated but
  left unfixed pending live verification") -- leaving it exactly as
  deferred, same reasoning: needs live-Windows verification against the
  real WCLResolver behavior before touching it blind.
- `CONVERT_SELECTED_FILE`'s brittle literal-substring `ACTION_CONVERT`
  aliases -- still open, unchanged from 0.3.62.
- The process/file generic-noun gap (`KILL_PROCESS`/`FIND_PROCESS`/
  `READ_FILE` requiring a literal "process"/"file" word) -- still open,
  unchanged from 0.3.62, same "already tried once, caused the 'kill the
  lights' regression" reasoning.



**Fixed, tested (1326 passed, 65 skipped, 0 failed -- up from 0.3.61's
1306):**

1. **`_NAME_TRIGGERS` missing "name it X" entirely.** The pre-existing
   triggers ("called X"/"named X"/"titled X") never matched this
   everyday phrasing ("make a qr code and name it poppers", "make a
   folder and name it homework"), so `_extract_name()` silently
   returned `None` for it on every intent that uses it --
   `GENERATE_QR_CODE`'s `filename` slot, `SAVE_CLIPBOARD_TO_FILE`,
   `MAKE_FOLDER`, `MAKE_FILE`. Added a new trigger, checked it doesn't
   intercept "named X", tests added
   (`TestNameItPhrasing` in `tests/test_extractor.py`,
   `test_name_it_phrasing_extracts_filename` in
   `tests/test_extractor_clip_qr.py`).

2. **MD/DOCX->PDF conversion failed ugly with no LaTeX toolchain
   installed.** `document_backend.convert()` shells out to bare
   `pandoc ... -o out.pdf`, which needs a full LaTeX distribution (e.g.
   MiKTeX on Windows) beyond the bundled pandoc binary --
   undocumented anywhere in this repo, not covered by any existing
   test. On a machine without it, the raw multi-line LaTeX error
   ("! LaTeX Error: File `lmodern.sty' not found.") went straight
   through `apis.py`'s generic `except Exception as e: return
   f"Couldn't convert that file: {e}"` to the chat reply. Added a new
   `PdfEngineNotFoundError`, narrowly detected via a short stderr
   marker list (only checked when `target_ext == "pdf"`), now
   surfaces: "Converting to PDF needs a LaTeX toolchain installed
   alongside pandoc (e.g. MiKTeX on Windows)... Install MiKTeX from
   miktex.org, then try again." Verified against a real reproduction
   (actually removed/reinstalled the LaTeX package locally) plus 5 new
   tests in `tests/test_document_backend.py` covering the happy path,
   both known failure-message shapes, and that unrelated/non-PDF
   pandoc failures still use the old generic error unchanged.

**Confirmed working via real (unmocked) functional testing, not just
routing:** QR generate->decode round trip, clipboard->file save, image
resize/convert (6 target formats), archive compress->extract (zip/tgz/
tar.bz2), text csv/json conversions, document md->docx/html/rtf/epub/pdf
and docx->html/odt round trips, media wav->mp3/flac via ffmpeg. 23/25
conversions in a wide format-matrix sweep succeeded outright; the other
2 (json->toml, ini->toml) failed with the existing clean, documented
"install toml" / "not supported yet" messages exactly as designed --
not bugs.

**Found, confirmed real, deliberately NOT fixed this session --
architectural, needs live-Windows testing before shipping (same bar
already established in this file for confidence-threshold/routing-
priority work):**

- `KILL_PROCESS`/`FIND_PROCESS`/`READ_FILE` require a literal generic
  noun ("process"/"program"/"app"/"file") in the phrase --
  `"kill notepad"`, `"is chrome running"`, `"read notes.txt"` all miss
  entirely; `"kill the notepad process"`, `"read the file notes.txt"`
  work. Root cause: `OBJECT_PROCESS`/`OBJECT_FILE` alias lists are
  category words only, with no mechanism (unlike `LAUNCH_APP`, which
  requires no object at all) for recognizing an arbitrary app/file name
  as implying the object. Deliberately not touched: this exact idea
  (drop the object requirement) was already tried and reverted once --
  see `CONTEXT_PROCESS_DISTRESS`'s own comment in
  `graph_source_data/tier_a_components.py` ("kill the lights" false
  positive). Also found a related confidently-wrong case in the same
  family: `"is the chrome app running"` silently misroutes to
  `PROCESS_LIST` instead of `FIND_PROCESS`.
- `CONVERT_SELECTED_FILE`'s `ACTION_CONVERT` aliases are brittle
  literal multi-word substrings -- natural phrasing with words inserted
  ("turn this .md file I just selected into a pdf") misses entirely and
  falls through to TF-IDF, which also misses.
- `"run vscode"` doesn't route to `LAUNCH_APP` -- "run" isn't a
  recognized trigger despite STATUS notes claiming it should be.
- `"open powershell and ms word"` (bare "and", one "open") doesn't
  chain-split and gets dispatched as one `LAUNCH_APP` with
  `app_name: "powershell and ms word"`.
- Typo tolerance: `"hwo many aps do i have"` confidently misroutes to
  `COUNT_FOLDERS` instead of missing cleanly.
- `"clean temp files"` -- pre-existing, already-documented WCL alias
  collision, confirmed still open.



**Coverage gap, confirmed exactly as flagged:** diffed
`INTENT_COMPONENT_MAP`'s keys against the real graph's actual 74 Tier A
`Command` nodes directly (`MATCH (c:Command) WHERE c.tier = 'A' RETURN
c.name`) -- 3 real, dispatchable intents had zero taxonomy coverage:
`GENERATE_QR_CODE`, `SCAN_QR_CODE`, `SAVE_CLIPBOARD_TO_FILE` (the
checkpoint's source snapshot predates that feature). Verified this was
never a functional gap for a real user, though -- `LayeredGraphRouter`'s
whole design is "component router first, TF-IDF (`GraphRouter`) on any
miss," and the component router correctly returned `None` (never a wrong
guess) for all 3, so they were routing correctly via the fallback the
whole time. Added proper taxonomy coverage for real anyway, so Tier A
itself resolves them directly (skips the TF-IDF cosine pass entirely,
same class of win as the original 66/67 benchmark) -- new `OBJECT_QR_CODE`,
`ACTION_SCAN_OR_DECODE`, `OBJECT_MARKDOWN` components, extended
`OBJECT_CLIPBOARD` with `"copied"`/`"what i copied"` (a genuine free
improvement to `GET_CLIPBOARD`'s own real phrase `"whats copied right
now"` too, which had zero clipboard signal under this taxonomy before
this), and new `INTENT_COMPONENT_MAP` entries for all 3. `73/73`
dispatchable Tier A intents now have taxonomy coverage (was 70/73).

**A REAL confidently-wrong collision was caught while adding this, not
just a theoretical one -- this is the "what if they disagree" case:**
`ACTION_CONVERT`'s own pre-existing multi-word alias `"turn this into a"`
is a literal substring of both `"turn this into a qr code"` and `"turn
this into a markdown file"`. Before catching this,
`CONVERT_SELECTED_FILE` (required `ACTION_CONVERT` alone) won BOTH
confidently and wrongly -- worse than a miss, because
`LayeredGraphRouter` trusts the component router's first confident
answer and never cross-checks `GraphRouter`/TF-IDF once it has one (by
design -- see `LayeredGraphRouter`'s own docstring in `orchestrator.py`:
this was a deliberate choice to avoid re-litigating GraphRouter's own
tuned ask/clarifying-question logic, not an oversight -- but it does mean
the component router's own correctness matters more than it would in a
"try both, compare" design, so a confidently-wrong answer here is a real
cost, not a theoretical one). Fixed with a `forbidden` clause on
`CONVERT_SELECTED_FILE` (`OBJECT_QR_CODE`, `OBJECT_MARKDOWN`) -- checked
directly against `CONVERT_SELECTED_FILE`'s own real corpus first
(`tier_a_phrasings.py`) to confirm neither word appears in it even once,
so this can only remove a wrong answer on someone else's vocabulary,
never cost it one of its own real phrasings. `"turn this into a qr
code"` now correctly resolves to `GENERATE_QR_CODE`; `"turn this into a
markdown file"` (genuinely ambiguous with no clipboard/copied signal at
all -- could just as validly mean "convert my currently-selected file to
.md format") now correctly returns `None` and falls through to
`GraphRouter`/TF-IDF, which already gets it right via its own training
memorization. This is the intended behavior for genuine ambiguity per
this taxonomy's own established design philosophy (documented precedent:
`COPY_ITEM` vs `SET_CLIPBOARD`'s near-identical `"copy this for me"`) --
accept the miss rather than force a guess, since the fallback exists
specifically to catch this.

**A structural gotcha in `build_component_graph.py` surfaced and worked
around, not fixed at the source:** the script is purely additive -- it
checks each individual edge for existence before creating it, but has no
mechanism to REMOVE an edge that's no longer in the current Python
source after `tier_a_components.py` itself changes shape (e.g.
`SAVE_CLIPBOARD_TO_FILE`'s `required` list was restructured mid-session
from `[OBJECT_FILE, OBJECT_CLIPBOARD]` to `[OBJECT_CLIPBOARD]` alone with
`OBJECT_FILE` moved to `any_of` -- re-running the build script against
the already-modified `toki_graph_db` left the STALE old
`REQUIRES_COMPONENT: OBJECT_FILE` edge in place alongside the new
correct edges, silently making `OBJECT_FILE` required-again in the
actual graph when the Python source no longer said so). Caught this via
direct Cypher inspection
(`MATCH (c:Command {name:'SAVE_CLIPBOARD_TO_FILE'})-[:REQUIRES_COMPONENT]->(comp) RETURN comp.id`)
after a live test failed unexpectedly. Worked around this session by
rebuilding `toki_graph_db` completely fresh from the last known-clean
base copy (`TOKI-BETA-v0.3.59-execution-test-fix`'s own `toki_graph_db`,
confirmed to have zero `Component` table via a direct query before
using it) rather than patching the already-mutated one further. If
`tier_a_components.py` is ever restructured again (not just added to),
the safe move is the same: rebuild from a clean base, don't re-run
`build_component_graph.py` against a copy that already has stale
Component/edge data from an earlier shape of the same file. Fixing
`build_component_graph.py` itself to detect and clean up stale edges
(e.g. delete-then-recreate each intent's full edge set on every run,
rather than only adding missing ones) is a reasonable follow-up but
wasn't done this session -- scoped as "watch out for it," not "rebuild
the tool."

**Verified after the fresh rebuild:** all 23 new/adjusted live cases
correct (7 `GENERATE_QR_CODE`, 6 `SCAN_QR_CODE`, 7 `SAVE_CLIPBOARD_TO_FILE`
+ 1 correctly-ambiguous miss, 2 `CONVERT_SELECTED_FILE` regression-sanity
checks). Official 67-case benchmark unchanged at 66/67 (98.5%) vs TF-IDF's
64/67 -- confirms zero regression from this session's changes.
`tests/test_value_masking.py` 23/23. Full suite: **1306 passed, 0
failed** (same as v0.3.60, confirming the taxonomy/DB changes this
session didn't disturb anything already passing). Re-confirmed live
through the real `orchestrator.WindowsAIAssistant()` →
`LayeredGraphRouter` path (not just `KuzuComponentRouter` in isolation)
for a representative sample of the new/fixed phrasings.

**A separate, PRE-EXISTING gap noticed but NOT fixed this session (out
of scope of the QR/clipboard ask, flagged for awareness rather than
chased down):** while regression-testing `CONVERT_SELECTED_FILE`'s own
full real corpus directly against the live component router (not just
the phrases touched this session), 3 of its own 12 real training
phrasings don't actually resolve to `CONVERT_SELECTED_FILE` at all --
`"make this a text file"` → `MAKE_FILE`, `"make this a pdf"` → `None`,
`"i need this as a different file type"` → `FILE_TYPE_BREAKDOWN` (a
different, unrelated intent). Confirmed this predates this session's
changes entirely -- `CONVERT_SELECTED_FILE`'s `required`/`forbidden`
list was never touched in a way that could cause this (the new
`forbidden` clause only REMOVES candidacy in specific new cases, never
adds it), and `ACTION_CONVERT`'s own alias list (`"convert"`, `"change
this file to"`, `"turn this into a"`, two "turn the file I'm
selecting/selected into a" variants) genuinely never covers `"make this
a"` or the word `"pdf"` at all -- this looks like the checkpoint's own
67-case blind benchmark simply never happened to probe these 3 exact
training phrasings, so this gap was invisible to it. Given TF-IDF
handles all 3 of these correctly today (verified), `LayeredGraphRouter`'s
fallback already protects real users from this -- it's a real, disclosed
self-consistency gap in the component router's own coverage of its OWN
training corpus, not a live-user-facing bug. Worth a dedicated pass
later (likely needs `ACTION_CONVERT` to cover `"make this a"` as a
prefix alias, plus a `"pdf"` alias somewhere, plus figuring out why
`FILE_TYPE_BREAKDOWN` is winning `"file type"` over `CONVERT_SELECTED_FILE`
at all) -- not chased further this session per scope.

## BETA 0.3.60 — component router wired into the main project as Tier A's primary classifier (Tier B untouched, deferred)

**What this is:** the `toki_tier_a_component_router_checkpoint.zip` handoff
from the parallel session (component-graph-based Tier A classification,
queried via real Cypher against Component/REQUIRES_COMPONENT/
ANY_OF_COMPONENT/FORBIDS_COMPONENT nodes/edges, benchmarked at 66/67
(98.5%) vs production `GraphRouter`'s own 64/67 (95.5%) on a 67-case
blind set) is now live in `orchestrator.py`, not just a standalone
checkpoint. Tier B (`wcl_resolver.py`) was never touched, inspected, or
in scope here — left exactly as-is, per the explicit call to defer it.

**Independently re-verified the checkpoint's own claimed numbers before
touching anything**, in an isolated copy first: rebuilt a scratch
`toki_graph_db` copy with `build_component_graph.py`, re-ran
`run_comparison_v2.py` (66/67 vs 64/67, exact match),
`tests/test_value_masking.py` (23/23, exact match), `test_chain_splitting.py`
(identical behavior to TF-IDF, including the one pre-existing DIFF case
on both sides), and the full existing suite (1306 passed, 0 failed,
matching the checkpoint's own claim). Confirmed the checkpoint's own
`git diff --stat` claim too: only new files, zero existing files
modified.

**Integration: staged and fallback-guarded, exactly as
`CHECKPOINT_MANIFEST.md`'s own "what another engineer should do next"
section called for.** New `LayeredGraphRouter` class in `orchestrator.py`
tries `KuzuComponentRouter.classify()` first; on any miss, falls through
to the existing production `GraphRouter` (TF-IDF) unchanged. Implements
the identical `classify()`/`classify_or_ask()`/`close()` contract either
router alone has, so it drops in as `self.graph_router` with **zero**
changes needed at any existing call site (`_split_chain_if_viable`/
`_segment_is_viable`, both `classify()`/`classify_or_ask()` sites in
`_process_single_request`, `shutdown()`'s `close()`, the status line) —
all of them already treated `self.graph_router` as "some object with
this contract, or `None`," never `GraphRouter` specifically.
`classify_or_ask()` deliberately only layers the component router's
confident `classify()`, never its own `classify_or_ask()`/"candidate"
logic — that logic exists solely so `test_chain_splitting.py` can drive
either router interchangeably, was never tuned for real clarifying-
question UX, so every ask/candidate-whitelist behavior stays sourced
from `GraphRouter` exactly as before. Both router constructions keep the
same fail-open posture already used everywhere else in `__init__`: if
`component_router_kuzu.py` is missing, or the Component tables aren't on
a given `toki_graph_db`, or Kuzu itself fails, `component_router` just
stays `None` and `self.graph_router` behaves exactly as it always has —
this can only match or beat today's classification, never regress it.

**`toki_graph_db` (the real one shipped in this checkoint, not a
throwaway copy) now has the Component/REQUIRES_COMPONENT/
ANY_OF_COMPONENT/FORBIDS_COMPONENT tables loaded** — ran
`build_component_graph.py` directly against it. Confirmed additive-only
and idempotent before doing this (re-reads the script itself: every
`CREATE` is guarded by an existence check first) and kept a full backup
copy through the whole session as an extra safety margin. If you ever
rebuild the graph from scratch via `migrate_to_kuzu.py`, re-run
`python3 build_component_graph.py toki_graph_db` afterward to reload the
component tables — `migrate_to_kuzu.py` itself wasn't touched and
doesn't know about them.

**Verified live through the real widget-facing path, not just
`WindowsAIAssistant` in isolation** — this session specifically confirmed
the "stuff normal users see" still works, since the whole point of this
integration was to change what happens under the hood without changing
what a user experiences: booted `main_widget.py`'s real `DesktopMark`
widget under an offscreen Qt platform (PyQt6 `QApplication` starts,
widget instantiates/shows/processes events/closes cleanly — verified
directly, not assumed), loaded the real orchestrator through
`_try_load_orchestrator()`, and ran real prompts through
`_run_and_classify()` (the exact function between the widget and the
model). `"what time is it"` → `GET_TIME` with a real response; the
previously-missed `"make a dir called Games"` → `MAKE_FOLDER`, correctly
attempting the real dispatch (only actual failure was `powershell` not
existing as a binary in this Linux sandbox — expected, documented
everywhere else in this project, unrelated to this change). Confirmed
`type(assistant.graph_router).__name__ == "LayeredGraphRouter"` and
`assistant.graph_router.component_router` is a real
`KuzuComponentRouter` instance on a freshly-constructed
`WindowsAIAssistant()`, and `shutdown()` closes both layers cleanly.

**One real test fix needed, not a bug:**
`tests/test_extractor.py::TestLooksLikeFunctionCreationFolderFileNamedFunctionBugfix::test_live_orchestrator_routes_folder_named_function_to_make_folder_not_generate_file`
asserted Ollama's `router.classify()` got called exactly once, because
when this test was written, TF-IDF alone missed `"make a folder called
function"` and needed the LLM fallback to resolve it (re-verified this
session: plain `GraphRouter().classify(...)` on this phrase still
returns `None` today). With the component router layered in front,
`assistant.graph_router.classify("make a folder called function")` now
returns `{"intent": "MAKE_FOLDER"}` directly — Tier A resolves it on its
own, skipping the LLM round-trip entirely, which is strictly better but
means Ollama is no longer necessarily on this phrase's path. The test's
own name/docstring was always about the END RESULT (`MAKE_FOLDER`, never
`GENERATE_FILE`) — updated the assertion to check
`result.get("intent") == "MAKE_FOLDER"` directly instead of an
implementation detail (which classifier happened to resolve it) the test
never actually cared about. All 16 tests in that class still pass, full
existing suite still 1306 passed / 0 failed with this fix in place.

**Also repointed `tests/test_value_masking.py`'s two hardcoded DB-path
references** (`CHECKPOINT_MANIFEST.md` flagged these as a manual step
for whoever integrates this) from the throwaway `toki_graph_db_v2_fair_test`
name to the real `toki_graph_db` now that it has the Component tables
loaded permanently — re-verified 23/23 passing against the real DB, not
just the scratch copy.

**Full suite, final state this session: 1306 passed, 67 skipped
(platform/dependency-gated, correctly), 2 deselected, 1 xpassed, 0
failed.** `tests/test_desktop_mark_dragdrop.py` still segfaults under
headless Xvfb in this sandbox specifically (pre-existing, unrelated to
this session, untouched file) — excluded from this session's suite runs
for that reason; used the offscreen Qt platform (`QT_QPA_PLATFORM=offscreen`)
instead to actually exercise `DesktopMark` directly, which doesn't hit
that same limitation.

**Not done / explicitly deferred, per your own instruction:** Tier B
(`wcl_resolver.py`) — untouched, out of scope, yours for later. Also
still true from the checkpoint's own manifest and not superseded by this
session: no genuinely fresh, independently-designed blind test set has
been built yet beyond the original 67-case set this was benchmarked
against; a bigger/more adversarial pass would be the natural next
validation step whenever there's time for it.

## BETA 0.3.59 — execution test suite false failures were a test-harness bug, not a routing/execution bug (plus 4 genuinely stale tests fixed)

**What triggered this session:** a real Windows run of the new
`tests/execution/` live-dispatch suite (built last session) came back
**18 failed, 1321 passed, 18 skipped, 1 xpassed** out of 1360 collected.
The failure cluster looked alarming at a glance — every filesystem
mutation (`MAKE_FOLDER`/`MAKE_FILE`/`DELETE_ITEM`/`COPY_ITEM`/
`MOVE_ITEM`/`RENAME_ITEM`) and every filesystem/clipboard read
(`GET_CLIPBOARD`/`READ_FILE`/`COUNT_FILES`/`COUNT_FOLDERS`/`FIND_FILES`)
failing looked like the actual PowerShell execution layer behind
routing was broken or silently doing nothing.

**It wasn't.** Root cause traced to `orchestrator.py`'s `_dispatch()`
being — by design — asynchronous for `kind == "powershell"`: it starts
the real command on its own background thread
(`executor.RunningCommand`) and returns an immediate `"Done."`
placeholder synchronously; the real stdout and exit code only arrive
afterward via the `on_output`/`on_done` callbacks. This has always been
true and is exactly why `main_widget.py` already has its own
`_run_and_classify()` wrapper that waits on `on_done` and reconstructs
the real response via `display_strategy.classify_display()` before ever
showing anything to a real user — **the actual GUI path was never
affected by this.** `tests/execution/test_live_dispatch.py`'s
`real_dispatch()` helper, however, called `_dispatch()` directly and
asserted against the result immediately, both reading the stale
`"Done."` placeholder (the read-intents) and racing the background
thread's subprocess against filesystem assertions that ran before it
had actually finished (the write-intents).

**Fix, scoped entirely to the test helper, not production code:**
`real_dispatch()` now waits on a `threading.Event` set from `on_done`
and, for `kind == "powershell"` results only, rebuilds `result["response"]`
using the exact same `display_strategy.classify_display()` call
`main_widget.py` uses in production — same collected output, same
exit-code handling, same DONE/INFO/ERROR classification. Every one of
the 11 filesystem/clipboard test bodies needed zero changes; they all
route through this one helper. `_no_error()` also updated to recognize
`classify_display`'s `"Command failed (exit code ...)"` text so a
genuinely failed live command still fails the test instead of silently
passing.

**4 more failures in the same run turned out to be genuinely stale
tests, not bugs, once actually read:**
- `tests/test_app_control.py::TestLaunchAppUsesEscaping::test_plain_app_name_unaffected`
  expected the old bare `Start-Process 'chrome'` behavior — but
  `launch_app()` was updated (prior session) to prefer a real Start Menu
  match via `_find_installed_app()`, launched through
  `shell:AppsFolder\<AppID>` when one's found. On a real Windows machine
  with Chrome actually installed, that's exactly what fired, and the
  test just hadn't been updated. Fixed to explicitly pin
  `_find_installed_app` for both the no-match (old bare `Start-Process`)
  and matched (`shell:AppsFolder`) cases — the matched path previously
  had **zero** direct test coverage at all, now does.
- `tests/test_orchestrator.py::TestShutdownReleasesGraphConnections::test_shutdown_is_safe_when_graph_router_is_none`
  crashed calling `.close()` on a `graph_router` that can legitimately
  already be `None` on a real machine (fail-open KuzuDB-open-failure
  path in `__init__`) — guarded the same way production code does
  everywhere else it touches `graph_router`/`wcl_resolver`.
- `tests/test_orchestrator.py::TestStartupCachePriming::test_priming_threads_are_daemon_threads`
  hardcoded "3 priming threads" from before `foreground_tracker.start()`
  existed — `__init__` now also starts that thread (added last session
  to fix video-download/app-control focus bugs). Updated to expect 4 on
  real Windows, 3 elsewhere (`foreground_tracker.start()` is itself a
  no-op off-Windows), so the assertion stays correct in both this Linux
  sandbox and on the real machine the suite is meant for.
- `tests/test_recording_disambiguation.py::TestOrchestratorStartDisambiguation::test_answering_macro_routes_to_start_seeing`
  string-matched `"macro"`/`"pynput"`/`"recording"` in the response text,
  but the macro-recording feature's user-facing wording changed to
  `"Watching. Do whatever you want me to repeat later..."` with none of
  those substrings present anymore. Fixed to assert on the actual routed
  `intent == "START_SEEING"` instead of response text that's free to
  keep evolving independently of routing correctness.

**Environment-only failures, left alone (not code bugs):**
`TYPE_INTO_ELEMENT`/`START_LISTENING` in the same run failed because no
UI element was focused on screen during that automated test pass
("Couldn't confidently find... on screen") — a precondition of the
machine's desktop state at the time, not a routing or execution defect.

**Verified this session:** full suite re-run in this Linux sandbox
(everything `requires_windows`/`requires_app_control`/`requires_browser`
correctly auto-skips here via `tests/execution/conftest.py`'s collection
hook) — **1283 passed, 67 skipped, 2 deselected, 1 xpassed, 0 failed**,
up from 1282 passed / 1 failed before this session's fix. The one
pre-existing failure (`TestStartupCachePriming`) is now green with the
platform-aware expected-count fix. `tests/test_desktop_mark_dragdrop.py`
segfaults under headless Xvfb in this sandbox regardless of these
changes (untouched file, pre-existing sandbox/Qt limitation, not
something introduced here) — excluded from this session's run for that
reason; irrelevant to the real Windows target environment.

**Not yet re-verified against the real Windows execution_test_log.jsonl
run** — this session's fix is verified for correctness (the logic now
exactly mirrors `main_widget.py`'s already-proven production path) and
for zero regressions in this sandbox, but the actual
`pytest tests/execution/ -v` + `execution_test_log.jsonl` round-trip on
the real machine (browser with YouTube playing, `ollama serve` running)
is still the next step to fully close this out.

## BETA 0.3.58 — 10-turn rolling conversation keyword memory (the original ask that got deferred while chasing the routing/focus/naming bugs across three sessions)

**Independently verified the whole v0.3.57 build first, not just the
changelog:** rebuilt `toki_graph_db` myself, ran `audit_tier_a.py` myself
(0 self-consistency failures, matching the reported count exactly), ran
the full suite myself (**1174 passed, 1 xpassed**, matching exactly), and
directly re-ran the three originally-reported bugs end-to-end
(`"create a function called calculator"` bypasses the graph via the
dedicated pre-check and never calls `classify()`; a nameless
`"write a function that does this"` correctly asks "What should I name
it?"; `"make a folder called function"` correctly stays `MAKE_FOLDER`,
not stolen by the function pre-check). All confirmed working, not just
trusted.

### The actual ask, from the very first session, never done until now

"Keep keywords for as long as 10 turns... TOKI should be able to tell
what I was talking about [after switching topics briefly]... do it as a
FIFO -- turn 11 evicts turn 1 from the active window -- but everything
gets recorded to the log so I can fix anything broken." Got pulled into
fixing the routing/GENERATE_FILE/focus-tracking bugs across three
sessions instead and this never got built. It's the one item from the
original list that was still outstanding.

**New `conversation_memory.py`:** deliberately separate from the two
memory mechanisms that already existed --
`orchestrator.py`'s `self.history` (2-turn cap, full verbatim text, fed
straight into Ollama's chat messages -- see `_commit_history`'s own
docstring for why it stays small) and `extractor.py`'s
`resolve_anaphoric_target()` + `_last_touched` (one slot, path-only,
"delete it" resolving to whatever TOKI itself last touched). Neither
covers "discussed something several turns ago, then said something short
that doesn't carry enough information on its own." `ConversationMemory`
tracks up to 10 turns of extracted KEYWORDS (reuses
`graph_router.normalize()`/`content_words()`, not a separate tokenizer)
-- cheap to keep around, no prompt-processing cost of its own, unlike
growing `self.history` would be.

**FIFO window, exactly as specified:** a `deque(maxlen=10)` handles the
eviction automatically. Every turn — including ones already evicted from
the active window — is ALSO appended to a persistent
`conversation_memory.jsonl` log (same append-only, one-record-per-line
convention as the existing `vocab_staging.py`), so nothing is lost even
after it drops out of the active 10-turn window. Verified directly: 12
turns recorded, active window correctly holds only turns 2-11 (0 and 1
evicted), but the log has all 12, turn 0 still readable from it.

**Wired in without touching the fragile Tier A graph at all** — the one
thing this session was careful not to reopen, given this project's whole
history of TF-IDF corpus fragility (see the BETA 0.3.51/intents-branch
entries above). `WindowsAIAssistant.__init__` creates one instance;
`_commit_history()` (the single existing choke point every successful
turn already runs through) feeds it automatically, so no per-call-site
changes were needed anywhere else. The ONLY place it's actually consulted
is `OllamaRouter.classify()`'s new `extra_context` parameter, and that's
only ever populated on a TOTAL Tier A graph miss (`_process_single_request`'s
existing Ollama-fallback call site) — never touches or influences graph
scoring, WCL resolution, or anything that already worked. `extra_context`
is prepended as its own system-role message before real `history`, so
Ollama's classify sees something like "Recent conversation topics, most
recent first: sales report, delete, ..." only in exactly the situation
this was built for.

`intent` threaded through `_dispatch()`'s dozen `_commit_history()` calls
(it's already a parameter in scope there) plus the two other clear
dispatch-success call sites; every other call site (asks, errors, plain
chat replies) correctly passes no intent — `ConversationMemory`'s own
docstring notes intent is contextual metadata only, never required for
its core keyword-matching use, so this doesn't need to be perfectly
exhaustive to be useful.

**Tests:** `tests/test_conversation_memory.py` (new, 20 tests) — FIFO
eviction, turn numbers staying monotonic across evictions, persistent
log surviving eviction (including a broken log path never raising, and
the log correctly accumulating across separate instances/restarts),
keyword extraction consistency with `graph_router`, `get_recent_topic_context()`'s
most-recent-first ordering/deduplication/length cap, and
`find_turns_matching()`. `tests/test_orchestrator.py` --
`TestConversationMemoryWiring` (5 tests: instance created on init,
`_commit_history` feeds it with and without an intent, `extra_context`
passed to Ollama only on a genuine total graph miss, `extra_context` is
`None` with no recent history) and `TestOllamaRouterClassifyExtraContext`
(3 tests: prepended as a system message, real `history` untouched when
absent, correct ordering when both are present). Full suite: **1202
passed, 1 xpassed** (up from 1174, all 28 new tests green, zero
regressions). `audit_tier_a.py` re-run: still 0 self-consistency
failures — untouched, since none of this touches the graph corpus.

**Not done / deliberately deferred:** the memory is currently ONLY
consulted on a total Tier A miss. A natural follow-up (not built this
session, to keep this change bounded and fully tested rather than
sprawling) would be cross-referencing `classify_or_ask()`'s below-
threshold `unknown_words` against `find_turns_matching()` to make the
clarifying-question text itself more specific (e.g. "...still talking
about the sales report?") — the method already exists and is tested,
just not wired into that second call site yet.



**Found while independently re-verifying 0.3.56 (Claude, sandboxed), not
self-reported by that session.** 0.3.56's own header comment on
`_GENERATE_FUNCTION_RE` claims the "function" pre-check "doesn't touch
folder/file/script/program at all" and is "[d]eliberately scoped to
exactly 'function'... per the explicit ask ('function should be almost
exclusive to function creation, unless it's something very specific like
a folder')." The code never actually enforced that: `looks_like_
function_creation()`'s rule 1 ("a real creation verb... always wins")
had no exception for it. `"make a folder called function"` contains a
creation verb (`"make"`) exactly like `"create a function called
calculator"` does, so it was silently stolen into `GENERATE_FILE` too --
the precise misroute the comment says can't happen.

**Confirmed live, end-to-end, not just at the regex level:** called
`_process_single_request("make a folder called function", ...)` directly
with `router.classify` mocked. `classify()` was never invoked --
`generate_and_save("make a folder called function")` was, straight off
the pre-check in `orchestrator.py`, before the graph ever got a look.
TOKI would have tried to generate a code file rather than create a
folder named "function". Same repro pattern for `"create a file called
function"`, `"write a script called function"`, `"create a program
called function"`, `"build a folder called function"`, and a few word-
order variants (`"function folder"`, `"folder function"`) -- all
misrouted the same way.

**Why 0.3.56's own test suite didn't catch it:** its one test for this,
`test_unrelated_folder_request_is_unaffected`, used `"make a folder
called Homework"` -- which never contains the word "function" at all, so
`_GENERATE_FUNCTION_RE` never even matches and the test could not have
exercised the actual collision.

**Fix, in `extractor.py`:** a new check runs *before* the creation-verb
rule, not alongside it -- when "function" is clearly being used as the
**name** of some other explicitly-typed thing (a folder/file/script/
program/directory), that explicit type wins outright, regardless of
which creation verb is also present in the sentence. Two shapes:
`"called/named function"` (or a quoted `"function"`) anywhere alongside
one of those five type words, or `"function"` directly adjacent to one
of them in either word order (`"function folder"` / `"folder
function"`). Genuine function-creation phrasings (`"create a function
called calculator"`, `"write a function and save it as function.py"`)
are unaffected -- none of them pair "function" with a competing type
word, so the new check never fires for them.

**Tests:** `tests/test_extractor.py::
TestLooksLikeFunctionCreationFolderFileNamedFunctionBugfix` (new, 14
tests) -- 12 parametrized regex-level cases covering the folder/file/
script/program/directory + "function" collision in both word orders and
across `called`/`named`/no-linker phrasings, one live end-to-end test
through `_process_single_request()` proving `classify()` is now actually
reached and `generate_and_save()` is not, and 3 cases confirming genuine
function-creation phrasings still match exactly as 0.3.56 shipped them.
Full suite: **1174 passed, 1 xpassed** (up from 0.3.56's 1158 passed with
16 new tests, zero regressions). `audit_tier_a.py` re-run: still **0
self-consistency failures** -- unaffected, since this fix only touches
the pre-graph short-circuit, never the graph corpus itself.

**Not touched this session:** the YouTube/`media_browser.py` half of
0.3.56 (the "currently playing" / CDP-debug-browser piece) -- reviewed
directly (source read in full, existing `tests/test_media_browser.py`
and the 3 new `TestWebSearchAPI` cases re-run, all still green) and no
issue found in the same pass that surfaced the "function" bug above, but
it remains **not verified against a real Windows machine/real Chrome or
Edge install** (this sandbox has neither), same standing caveat 0.3.56
itself already flagged for that piece.

---

## BETA 0.3.56 — "function" routes straight to GENERATE_FILE (closes 0.3.55's flagged gap), YouTube search now opens through a dedicated CDP-debug-enabled browser instance for a seamless video-link grabber

Two separate pieces requested in the same chat, both picked up directly
from open items already on the record (0.3.55's own "not yet fixed" note,
and the video-download link-grabber's long-known "only works if the user
happens to already have a debug port open" limitation).

### 1. "function" bypasses Tier A's graph scoring entirely, routes straight to GENERATE_FILE

**The gap, exactly as 0.3.55 flagged it:** even with that session's ask-
on-missing-name fix in place, some GENERATE_FILE-shaped phrasings still
missed Tier A's graph classification before ever reaching the naming
logic at all -- `"create a function called calculator"` scored 0.285
against the 0.5 `CONFIDENCE_THRESHOLD`, confirmed live against the real
graph, because the query's own TF-IDF vector gets diluted by "calculator"
(or any specific name) not appearing in ANY phrasing's vocabulary. 0.3.55
named the architecturally cleaner fix directly -- strip the `"called X"`
clause before scoring -- and deliberately deferred it, since it touches
the audited `_best_command()` scoring core.

**What shipped instead, and why:** not that fix. Stripping the naming
clause before scoring is corpus-wide surgery on the same TF-IDF core this
project's entire history (see nearly every STATUS.md entry above) has
found to be fragile under exactly this kind of change -- diluting one
command's vocabulary to fix it reliably shifts scores for others
elsewhere in the corpus, confirmed painfully many times in this file
already. Given the explicit ask ("function should be almost exclusive to
function creation, unless it's something very specific like a folder"),
the safer, already-established pattern in this codebase is a dedicated
pre-check that bypasses the graph entirely for a fixed, narrow trigger --
exactly the same shape `looks_like_start_seeing()`/`looks_like_bare_timer()`
already use for "start"/"stop"/time-expression phrasings that would
otherwise distort `LAUNCH_APP`/`KILL_PROCESS` scoring.

New `extractor.looks_like_function_creation()`: matches the literal word
`"function"` anywhere in the message, nothing more. Confirmed via a full
grep of `graph_source_data/tier_a_phrasings.py` and every `intents*.py`
file that "function" appears NOWHERE else in this app's vocabulary --
there's no existing intent this could collide with. Wired into
`orchestrator.py`'s pre-check chain (same block as the start/stop
seeing/listening checks, before scheduling and before graph
classification): a match routes straight to `GENERATE_FILE` via the same
`_handle_missing_or_dispatch()` helper those checks already use.
`GENERATE_FILE` has `"slots": []` by design, so `extract_slots()` always
returns `{}` here (never triggers a generic missing-slot ask) --
`_dispatch()`'s own `extract_explicit_name()` check from 0.3.55 still
runs exactly as before on the other side of this: a bare `"write a
function that does this"` with no name still asks "what should I name
it?", it just no longer has to survive the graph's confidence threshold
to get there.

Deliberately scoped to exactly "function" -- "folder"/"file"/"script"/
"program" are untouched and keep routing exactly as they already did
(`MAKE_FOLDER`, `MAKE_FILE`, `GENERATE_FILE`'s own existing phrasings),
per the explicit instruction that something as specific as a folder
request shouldn't be swept into this.

**Follow-up, same session: "function" can be a real filename, not just
the code-generation noun.** Caught before shipping, not after: a plain
"function" match alone would have wrongly stolen `"open function.py"`,
`"delete the file called function"`, or `"rename function.py to
helper.py"` away from their real `OPEN_ITEM`/`DELETE_ITEM`/`RENAME_ITEM`
routing -- the exact same class of misrouting bug this project's entire
history keeps finding and fixing (see nearly every STATUS.md entry
above). `looks_like_function_creation()` now checks for this directly:
a real creation verb (`write`/`create`/`make`/`build`/`generate`/`code`)
anywhere in the message always wins outright; absent one, "function"
immediately followed by a file extension (`function.py`), quoted as a
literal name, or the message opening with one of the same file-management
verbs `_BARE_PATH_LEADING_VERB_RE` already recognizes for exactly this
purpose elsewhere in this file (`open`/`delete`/`read`/`rename`/...) means
this reads as an existing file being targeted, not a generation request --
falls through to normal routing instead. A creation verb still wins even
with an extension present (`"write a function and save it as
function.py"` stays GENERATE_FILE), since stating what to name the
output isn't the same thing as targeting an existing file.

**Tests:** `tests/test_orchestrator.py::TestFunctionKeywordRoutesDirectlyToGenerateFile`
(5 tests) -- calls `_process_single_request()` directly (not just
`_dispatch()`) with `router.classify` mocked to prove the pre-check fires
BEFORE graph classification is ever consulted, not just that dispatch
behaves correctly once reached: a named request dispatches straight to
`generate_and_save()` with zero `classify()` calls; a bare/unnamed
request still asks and sets `self._pending` exactly like every other
GENERATE_FILE miss; an unrelated `"make a folder called Homework"` is
completely unaffected; a real file literally named "function"
(`"open function.py"`, `"delete the file called function"`, a quoted
`'"function"'`) is never stolen into GENERATE_FILE; a creation verb
correctly wins even with a file extension present. Plus
`tests/test_extractor.py::TestLooksLikeFunctionCreation` (11 tests)
unit-testing `looks_like_function_creation()` directly against both
classes of phrasing. Full suite: **1142 passed, 1 xpassed** (up from
0.3.55's 1123 passed with 33 new tests net across this and the piece
below, zero regressions).

### 2. YouTube search now opens through a dedicated, CDP-debug-enabled browser instance -- the actual fix for "the video link grabber isn't as strong right now"

**Context on what already existed, since this was raised in chat as if it
needed building from scratch:** the pywinauto-context + browser-debug-
port hybrid described in chat is, piece for piece, what
`video_downloader/cdp_now_playing.py` already built back in BETA 0.3.44 --
`app_control.py`'s focused-window lookup for context, a local
`http://localhost:9222/json` query (not a full mitmproxy MITM) for the
exact playing URL, no TLS interception anywhere. That part didn't need
rebuilding and wasn't touched this session.

**The real gap, and what actually needed fixing:** CDP only ever answers
anything if SOME already-running Chrome/Edge process happens to have been
launched with `--remote-debugging-port` -- which almost nobody's day-to-
day browser is. In practice this meant the CDP fast path essentially
never fired, and `DOWNLOAD_PLAYING_VIDEO` fell back to the address-bar
read (right window focused at the right moment, or nothing) every single
time -- the actual "not as strong as it should be" gap.

**Fix -- new `video_downloader/media_browser.py`:** implements exactly
the first of the two options raised in chat ("launch a dedicated
automation instance... leaving your main banking/personal browser
completely untouched"), wired into the one place TOKI itself already
opens something video-shaped: `apis.py`'s `WebSearchAPI.search()` for
`site="youtube"`. `launch_media_browser()` finds a real Chrome/Edge
install (same three paths `WebSearchAPI._open_in_chrome()` already
checks, plus the two standard Edge locations), launches it against a
fresh, TOKI-owned profile directory (`%LocalAppData%\TOKI\
MediaBrowserProfile`, never the user's real profile/cookies/logins) with
`--remote-debugging-port` set and pointed at the YouTube results URL.
The next `"download this video"` (or `"download what I'm watching"`)
finds this instance's debug port already listening, and
`cdp_now_playing.py`'s existing probe -- untouched, no changes needed
there at all -- just works, with zero manual setup.

**Security posture (the second option raised in chat, "accept the port
risk bound to localhost," done as the actual implementation detail
rather than left as an alternative):** the debug flag is
`--remote-debugging-port` alone -- `--remote-debugging-address` is never
passed, so Chrome/Edge's own default (loopback-only) stands; this can't
be reached from another device on the network. `cdp_now_playing.py`'s
existing probe already only ever talks to `127.0.0.1`/`localhost` --
unchanged. Never touches, relaunches, or reconfigures the user's real
browser under any circumstance -- confirmed this is a single, additive,
opt-in-by-context change (only fires for `site="youtube"`, which nothing
else in this codebase currently sets automatically -- see BETA 0.3.44
checkpoint 2's own note on why site auto-detection from free text was
deliberately not built, still true and still not attempted here). Any
failure (no browser found, launch error) falls straight through to the
exact same plain `_open_in_chrome()` path every other search already
uses -- the search still opens either way, this only ever adds the CDP
fast path on top when it can.

**Tests:** `tests/test_media_browser.py` (new, 10 tests) -- browser-path
discovery, dedicated-profile-directory creation (confirmed distinct from
any real profile path), CDP port resolution incl. the
`TOKI_CHROME_CDP_PORT` env override and malformed-override fallback, the
launch call itself (confirmed debug port + dedicated profile in the
launched args, confirmed `--remote-debugging-address` is NEVER present),
optional-URL handling, and Popen-failure-returns-False-not-raises. 3 new
tests in `tests/test_apis.py`'s `TestWebSearchAPI` -- YouTube search
tries the dedicated instance and reports it in the response message,
falls back cleanly to the plain Chrome path when the dedicated instance
is unavailable, and confirms every OTHER site (`web`, the default) never
touches `media_browser` at all. Every test mocks `subprocess.Popen`
directly; nothing here launches a real browser or opens a real network
connection, same convention `TestWebSearchAPI`'s existing tests already
follow.

**Not done this session, flagged rather than silently left out:**
site auto-detection from free text (so `"search for lofi beats on
youtube"` would set `site="youtube"` on its own) is still the same
deliberately-deferred item BETA 0.3.44 checkpoint 2 already flagged --
unrelated to and not widened by this fix. `DOWNLOAD_PLAYING_VIDEO`
itself, `now_playing.py`'s address-bar fallback, and `cdp_now_playing.py`
are all completely unchanged -- this fix only makes sure a debug port is
actually listening when TOKI is the one that opened the video, it
doesn't touch how any of those modules use it once it is. Not verified
against a real Windows machine/real Chrome or Edge install (this sandbox
has neither) -- logically reviewed against Chrome/Edge's documented flag
behavior and this project's own established fail-soft conventions, same
standing caveat as every UI-Automation/network-dependent piece of this
project's history.

---

## BETA 0.3.55 — GENERATE_FILE now asks "what should I name it?" on a missing name instead of silently defaulting to generated_file.txt

The real, precise version of the "naming bug" the project owner kept
running into after BETA 0.3.54: `infer_filename()`'s regex extraction
was already correct (confirmed by direct testing last session), but
GENERATE_FILE was the one file-creating intent with NO
`MISSING_SLOT_QUESTIONS` entry and no ask-on-miss behavior at all --
every other one (`MAKE_FOLDER`, `MAKE_FILE`, ...) already asks "what
should I name it?" when the name is missing; GENERATE_FILE just quietly
wrote `generated_file.txt`/`.py`/etc. and moved on. That silence is
exactly what made a name that got cut off (e.g. `voice_pipeline.py`'s
1.8s `SILENCE_HANGOVER_S` ending the recording before a paused-then-
spoken "...call it calculator" ever got captured) or just never spoken
in the first place indistinguishable from a deliberate choice -- nothing
in the UI ever said the name didn't come through.

**The fix:** `generator.py`'s old `infer_filename()` split into
`extract_explicit_name()` (just the "was a name actually given" check,
returns `None` on a miss) and `infer_filename()` (unchanged output,
now built on top of the former). `orchestrator.py`'s `_dispatch()`
checks `extract_explicit_name()` before ever calling
`generator.generate_and_save()`: no name -> same `self._pending` +
`MISSING_SLOT_QUESTIONS` ask-and-pause pattern every other creation
intent already uses, new entry: *"What should I name it? (or say
'skip' and I'll pick a name)"*. `_resume_pending()` has a dedicated
GENERATE_FILE branch (it can't reuse the generic slot-resume path --
GENERATE_FILE has `"slots": []` by design, see its `INTENTS` entry's
own comment) that merges the answer into the ORIGINAL description
(`"write some code for this"` + `"calculator"` ->
`"write some code for this called calculator"`) via the same
`_strip_answer_filler()` every other resumed answer already goes
through ("call it calculator" -> "calculator"), so
`extract_explicit_name()` finds it naturally on the merged text, no
special-casing needed downstream. Explicit skip
(`GENERATE_FILE_SKIP_NAME_ANSWERS` -- "skip"/"no"/"whatever"/"you
pick"/etc.) or an empty/unusable reply both fall back to the ORIGINAL
unmerged text -- generator.py's existing generic-default naming kicks
in exactly as before, just now as an informed default instead of a
silent one, and neither case re-triggers the ask (new
`skip_generate_name_check` parameter threaded through
`_dispatch_or_confirm`/`_dispatch`, True only on this one resume path,
so there's no infinite ask loop on skip even though the unchanged text
still has no name in it).

**Tests:** `tests/test_generator.py` (new, 12 tests) for
`extract_explicit_name()`/`infer_filename()` directly, including the
"'called' with nothing after it" edge case a naive regex-group check
could get wrong. `tests/test_orchestrator.py` --
`TestGenerateFileAsksForMissingName` (new, 7 tests): no-name asks and
sets `_pending`, an explicit name dispatches immediately without
asking, resume merges a name in correctly, resume strips natural
filler ("call it X"), resume with skip/empty both fall back to the
unchanged original without re-asking. `generator.generate_and_save()`
mocked throughout -- it's a real streamed Ollama call, genuinely out of
scope for this sandbox; everything under test here is the ask/merge/
resume logic that runs strictly before that call. Full suite: **1123
passed, 1 xpassed** (same pre-existing xpass, up from 1104 with these
19 new tests).

**Separately confirmed, not yet fixed, flagged rather than silently
left out:** even with this fix, some GENERATE_FILE-shaped phrasings
still miss Tier A's graph classification entirely before ever reaching
this code -- e.g. `"create a function called calculator"` scores 0.285
against the 0.5 `CONFIDENCE_THRESHOLD` (checked directly against the
live graph), because the query's own TF-IDF vector gets diluted by
"calculator" not appearing in ANY phrasing's vocabulary -- any specific
name necessarily does this to some degree, coverage-expanding the
corpus further can't fully fix it. Falls through to `OllamaRouter`'s
own LLM-based `classify()` as designed (the safety net every graph miss
already has), not a silent failure, but that path's reliability with
phi4-mini is untested here (no live Ollama in this sandbox). The
architecturally cleaner fix would strip the `"called X"`/`"named X"`
clause (same regex `extract_explicit_name()` already uses) before
scoring, so a name never dilutes classification confidence in the
first place -- not done this session since it touches the audited
`_best_command()` scoring core directly and deserves review before
changing.

---

## BETA 0.3.54 — foreground_tracker.py: fixes _get_focused_window() (app_control.py) grabbing TOKI's own window instead of the real target, root-causing the video-download and app-control focus bugs

Written from scratch this session -- the version of this fix described
in an earlier chat's transcript was never actually saved into either
uploaded build (see the BETA 0.3.53 merge entry below and
`MERGE_NOTES.md` for the full story of how that was discovered). No
code from that earlier session was recovered or reused; this is a
fresh implementation from the bug description alone.

**The bug:** `_get_focused_window()` asks Windows for whichever window
currently has OS foreground focus. By the instant any app_control.py or
`video_downloader/now_playing.py` code actually runs, that's almost
always already TOKI's OWN window -- the user just typed or spoke a
command into it. Every video-download request ("couldn't find its
link"/"couldn't find its directory") and every click/type app-control
call was silently resolving against TOKI itself instead of the browser
or app the user actually meant, regardless of what was genuinely
focused a moment earlier when the command was issued.

**The fix:** new `foreground_tracker.py` -- a lightweight background
daemon thread, raw `ctypes`/`user32` only (no new dependency, same
"no pywin32/psutil anywhere in this project" posture `target_memory.py`
already documents), polling `GetForegroundWindow()` every 0.2s and
remembering the most recent window handle that did NOT belong to
TOKI's own process (compared by PID via `GetWindowThreadProcessId()`,
not window title/class -- TOKI owns several distinct top-level windows
over its lifetime, PID catches all of them uniformly with nothing to
keep in sync as the widget UI changes). `app_control.py`'s
`_get_focused_window()` now checks the live active window's
`process_id()` against `os.getpid()`; if it's TOKI's own, it falls back
to `foreground_tracker.get_last_foreground_window()` (which
re-validates the handle with `IsWindow()` before returning it, since
the remembered window may have since closed) instead of returning
TOKI's own window as if it were the real target. Falls back to the
live active window unchanged in every other case -- if OS focus
genuinely is on some other app, nothing about this changes. Fails open
to TOKI's own window (this function's pre-existing behavior) whenever
no usable fallback exists, rather than raising -- callers already treat
that as a clean miss.

Started as early as possible (`WindowsAIAssistant.__init__`, alongside
the existing cache-priming call) so a real window has already been
observed before the user's first command shifts focus to TOKI; stopped
in `shutdown()` alongside the scheduler/condition-poller cleanup.
Both calls wrapped in their own try/except in `orchestrator.py` in
addition to `foreground_tracker.py`'s own internal fail-soft handling
-- defense-in-depth, same posture as `_prime_caches_in_background`'s
own try/excepts: this is a best-effort UX fix and must never be able to
block `WindowsAIAssistant` from constructing or shutting down.
`video_downloader/now_playing.py` needed no changes at all -- it
already calls `app_control._get_focused_window()` directly, so it
inherits the fix automatically.

**Tests:** `tests/test_foreground_tracker.py` (new, 18 tests) --
`GetForegroundWindow()`/`GetWindowThreadProcessId()`/`IsWindow()` all
mocked (this sandbox has no real Windows environment), covering the
own-process-vs-foreign-process distinction, staleness re-validation,
thread lifecycle (idempotent start, safe double-stop), a bad poll tick
not killing the loop, and platform gating (no-op on non-Windows).
`tests/test_app_control.py` -- 5 new tests in
`TestGetFocusedWindowForegroundTrackerFallback` covering the actual
`_get_focused_window()` integration: the common case (active window
genuinely isn't TOKI's -- foreground_tracker never even consulted),
the fallback firing when it is, failing open with no tracked window
yet, failing open when the tracked handle closed in the gap, and
failing open if `process_id()` itself raises.
`tests/test_orchestrator.py` -- 3 new tests confirming `__init__`
starts the tracker, `shutdown()` stops it, and a broken `start()`
can't prevent construction. Full suite: **1104 passed, 1 xpassed**
(same pre-existing xpass as the 0.3.53 merge, no new regressions).

**NOT VERIFIED AGAINST REAL WINDOWS in this session** -- same honest
caveat as everywhere else in this project's history where the sandbox
has no live Windows/pywinauto: `GetForegroundWindow()`/
`GetWindowThreadProcessId()`/`IsWindow()` are the documented, stable
Win32 APIs for exactly this, and this is real, syntactically valid,
unit-tested code -- but nothing here confirms it behaves as expected
against an actual desktop session. Test this live (try the video
downloader and a click/type app-control command right after switching
window focus) before trusting it.

---

## BETA 0.3.53 — merge of two parallel BETA 0.3.51/0.3.52 branches: Tier A casual-phrasing expansion + GENERATE_FILE fix (routing/intents branch) combined with smooth widget animations + sticky persistent UI (display/architecture branch)

Two sessions had diverged from the same 0.3.50 base and were never
reconciled against each other -- one focused entirely on Tier A intent
coverage and the GENERATE_FILE routing bug (below, originally logged as
that session's own "BETA 0.3.51"), the other entirely on widget-level
UX/animation and the DONE/INFO/ERROR display strategy split (below,
originally logged as that session's own "BETA 0.3.51"/"BETA 0.3.52").
The two touched disjoint files with a single accidental exception
(`app_control.py`, `orchestrator.py`, `synonyms.py`, and the three test
files that pair with them, where the intents branch had also added
`prime_app_cache`/startup cache priming/Ollama fast-fail cooldown that
the display branch never saw) -- no file required a real line-by-line
reconciliation, only a decision about which branch's version of each
whole file to keep. Kept from the intents branch: `app_control.py`,
`orchestrator.py`, `synonyms.py`, `graph_source_data/tier_a_commands.json`,
`graph_source_data/tier_a_phrasings.py`, `audit_tier_a.py`,
`tests/test_graph_router.py`, `tests/test_orchestrator.py`,
`tests/test_synonyms.py`, and the rebuilt `toki_graph_db/` that matches
the expanded phrasing corpus. Kept from the display branch:
`main_widget.py`, `toki_desktop_mark.py`, `ui_theme.py`,
`display_strategy.py`, `tests/test_display_strategy.py` -- none of these
were touched by the intents branch at all, so nothing was lost by taking
them wholesale. `vocab_staging.jsonl` (a runtime log of unresolved vocab
queries, not source) was merged by deduplicating on entry `id`.

**Important honesty note not from either source session:** a separate
chat (not represented by either uploaded zip) reported writing a
`foreground_tracker.py` fix for `_get_focused_window()` grabbing TOKI's
own window instead of the last real app/browser window -- the reported
root cause of the video-download and app-control focus bugs. That file
did not exist in either uploaded build and no trace of it was in either
STATUS.md. It was NOT part of this merge -- see the BETA 0.3.54 entry
directly above for a fresh, from-scratch implementation of that fix
(written after this merge, no code recovered from the original
session).

**Not yet done by this merge, flagged here rather than silently
skipped:** the full test suite has not yet been re-run end-to-end
against the merged tree in this sandbox (no Windows/pywinauto/live
Ollama here, same limitation as every session before this one) -- run
`python run_all_tests.py --pytest-only` and `python migrate_to_kuzu.py`
yourself on the real machine before trusting this build. In particular,
`migrate_to_kuzu.py` should be re-run to confirm the checked-in
`toki_graph_db/` (copied over from the intents branch as-is) truly
matches the merged `tier_a_commands.json`/`tier_a_phrasings.py`
byte-for-byte, not just by directory size.

---

## Merged-in: intents/routing branch (originally "BETA 0.3.51")

Requested: add casual, how-people-actually-talk phrasings to every Tier A
intent (keeping a couple formal ones as a safety net), make sure nothing
breaks or overlaps, and — explicitly — don't just rely on the existing
pytest suite to prove that, because it wasn't trusted to catch everything
last time. Built `audit_tier_a.py` to satisfy that directly: a permanent
script (not a one-off check) that self-consistency-tests *every* phrasing
in the corpus against `classify()`, plus flags any command pair with a
thin (<0.05) confidence margin, so future phrasing changes get swept the
same way without hand-picking examples.

**Baseline before touching anything:** `1025 passed, 1 skipped, 2 xfailed`
— clean.

### GENERATE_FILE bug, found and fixed (not previously diagnosed)

`graph_router.py`'s own module comments had flagged, but never fixed:
GENERATE_FILE had zero Phrasing nodes in the graph, so no scoring formula
could ever select it — `"write a poem to a file"` fell through to
READ_FILE at 0.659 confidence instead. Worse: because MAKE_FILE's own
corpus contains `"make a new file called"`, any generation request that
also named its target (`"create a function called calculator"`) collided
straight into MAKE_FILE — an empty file, no generated content — which is
almost certainly the root cause of the previously-reported "function
creation fails when I give it a name" bug. Fixed by adding a real
`GENERATE_FILE` entry to `graph_source_data/tier_a_commands.json` (it had
neither a Command node nor phrasings before this) and a phrasing corpus
built around `write`/`generate`/`code`/`build` verbs — deliberately
avoiding `MAKE_FILE`/`MAKE_FOLDER`'s vocabulary so a naming clause can't
re-collide the same way. Verified directly: `"write a poem to a file"` now
returns `{"intent": "GENERATE_FILE"}`.

### The core mechanic behind almost every regression this pass hit

`graph_router.py`'s `_best_command()` uses L2-normalized cosine
similarity, not raw word-overlap counts. Two consequences that aren't
obvious until you hit them:

1. **Adding phrasings to intent X dilutes X's OWN other phrasings.**
   Every phrasing added to a command's corpus is a new document that
   command's vector gets normalized against — words that used to carry
   most of that vector's weight now carry less, even for queries that
   never changed. Concretely: `MAKE_FOLDER` had 3 original phrasings, none
   containing "named". Adding 8 casual ones (still zero rare words) was
   enough to drop `"make a folder called Homework"` — completely
   unchanged as a query — from a confident hit to a miss.
2. **A single rare/one-off word anywhere in a corpus disproportionately
   hurts that corpus's OTHER entries.** Adding `"create a folder named
   python"` to try to fix (1) actually made it worse: the rare word
   "python" grabbed a large share of MAKE_FOLDER's normalized vector,
   which starved the common words ("folder", "called", "create") that
   every OTHER MAKE_FOLDER phrasing depends on — fixed one test, broke
   three others.
3. **Adding a shared word (e.g. "files") to many DIFFERENT intents'
   corpora lowers that word's global IDF weight for everyone**, even
   intents whose own corpus never changed. `COUNT_FILES`'s unmodified
   3-phrasing corpus dropped from 0.59 to ~0.22 confidence purely because
   "files" got added to several other intents' casual phrasings
   elsewhere in this same pass.

None of this is a bug in `graph_router.py` — it's cosine similarity
working as designed — but it means "add lots of casual coverage" and
"don't move any existing score" are in real tension, not a one-time
checklist. Where they conflicted, the fix was either (a) trim the
casual additions for that specific intent back to a leaner set (done for
`MAKE_FOLDER`, `COUNT_FILES`, `VOLUME_UP`/`VOLUME_DOWN`), or (b) commit
the exact affected phrase verbatim as its own corpus entry (done for
`SEARCH_WEB`, `DISK_USAGE`, `LIST_INSTALLED_APPS`, `SET_CLIPBOARD`) — the
same house pattern already used for the "shut up" fix in BETA 0.3.27.

### LAUNCH_APP vs OPEN_ITEM, re-broken and re-fixed

The BETA-era balance between these two (see the existing comment block in
`tier_a_phrasings.py`) is exactly as fragile as documented: the first
draft of casual `OPEN_ITEM` phrasings ("pull up this file", "open this
folder for me") reintroduced the `"open steam"`/`"open vscode"` misroute
to `OPEN_ITEM`. Fixed by trimming `OPEN_ITEM`'s additions and reinforcing
`LAUNCH_APP` with app-paired phrasings (`"can u open steam for me"`) —
then had to re-trim `LAUNCH_APP` again when the reinforcement over-shot
and made `"terminate steam"` misroute to `LAUNCH_APP` instead of
`KILL_PROCESS`. Both directions verified correct now.

### MAKE_FOLDER's target name is structurally out-of-vocabulary

`'Create a folder named "python"'` (the real live-transcript sentence
`test_chain_split_viability.py` already carried from BETA 0.3.9) can't be
fixed by corpus tuning at all per the mechanic above — a folder name is
inherently unpredictable text, the same structural category as an app
name for `LAUNCH_APP` or a process name for `KILL_PROCESS`. Rather than
keep fighting the corpus, added `MAKE_FOLDER` to
`orchestrator.py`'s `_NAME_FROM_OUTSIDE_VOCAB_INTENTS` whitelist —
already an established mechanism for exactly this category — so a
below-threshold `classify_or_ask()` candidate is trusted as viable for
chain-split purposes. Confirmed this doesn't reopen the BETA 0.3.11
`"copy a.txt and b.txt to D drive"` false positive (that segment
candidates `DISK_USAGE`, not `MAKE_FOLDER`, so it's untouched).

### synonyms.py cleanup

Six `SYNONYM_MAP` entries (`trash`, `rid`, `clone`, `mention`, `storage`,
`silence`) became real, direct `TIER_A_PHRASINGS` vocabulary during this
expansion — exactly the harmless-no-op scenario the module's own
docstring anticipated. Removed the dead entries and updated
`test_synonyms.py`'s parametrized cases accordingly. One behavioral note:
`"silence the volume"` now hits `TOGGLE_MUTE` as a confident *direct* hit
instead of a below-threshold synonym-assisted candidate — a genuine
improvement, not a regression, but it meant
`test_low_confidence_synonym_hit_still_asks_not_silently_misses` needed a
different example (`"list my software"` → `LIST_INSTALLED_APPS`) to keep
exercising the below-threshold path it exists to guard.

### Final state

- 71 Tier A commands (70 original + `GENERATE_FILE`), 571 phrasings (was
  217 before this pass, deliberately majority-casual per intent with 1-2
  formal ones kept).
- `audit_tier_a.py` (new, permanent): 0 self-consistency failures across
  all 571 phrasings; 50 remaining thin-margin (<0.05) pairs, all reviewed
  — none involve an opposite-action or destructive-vs-benign flip risk
  (the ones that did — the VOLUME_UP/VOLUME_DOWN/TOGGLE_MUTE triangle —
  were tightened back to a healthy margin during this pass).
- Full suite: `1027 passed, 1 xpassed` (2 fewer skips/xfails than baseline
  — the GENERATE_FILE xfail converted to a real regression test, and one
  additional dispatchable case).
- `toki_graph_db` rebuilt via `migrate_to_kuzu.py`; ship this alongside
  the `.py`/`.json` changes — the graph is a build artifact, not
  hand-edited.

## BETA 0.3.51 continued — startup cache priming + Ollama fast-fail cooldown

Two more pieces of the same session, both following the codebase's own
established "fetch once, cache, fail soft with a retry cooldown" pattern
(`apis.py`'s `LocationCache`, `app_control.py`'s `AppController`).

### Startup cache priming

Asked for: file/folder names and installed-app names cached "just like
location is cached when the program starts." Turned out `location_cache`
itself wasn't actually eager-primed at startup either — all three
session-lifetime caches (`apis.py`'s `location_cache`, `AppController`'s
installed-app list, `extractor.py`'s `FileIndex`, which already existed
and already does exactly the sandboxed file/folder fuzzy-matching this
request wanted) were purely lazy: populated on whichever real request
happened to need one first. `apis.py`'s own `LocationAPI.get_raw_location()`
docstring even anticipated this ("for callers that need... e.g. showing a
short status on startup once the fetch completes") but nothing ever
called it early.

Fixed by adding `WindowsAIAssistant._prime_caches_in_background()`,
called at the end of `__init__`: fires all three in separate daemon
threads (parallel, not sequential — they're independent I/O waits:
network, subprocess, disk) and is fully fire-and-forget, since all three
underlying caches already fail soft and never raise. Added
`AppController.prime_app_cache()` as the public entry point for this
(previously only reachable via the private `_get_installed_apps()`).
4 new tests (`TestStartupCachePriming`) verify all three actually fire,
`__init__` doesn't block waiting on them, threads are daemons, and one
cache failing doesn't stop the others.

### Ollama fallback: fast-fail cooldown once confirmed unreachable

Requested: push the Ollama fallback as low-priority as possible. The
actual routing PRIORITY (Tier A graph → Tier B WCL → Ollama →
search-first default) was already correct and already well-documented as
deliberate (see BETA 0.3.47's note in `_process_single_request` — "Ollama
is now the RARE path"). What wasn't addressed: on a session where Ollama
genuinely isn't running (the documented common case now), every single
graph+WCL miss still attempted a brand-new connection to
`localhost:11434` and waited out that attempt before falling through —
paying that cost again and again for the rest of the session even though
the answer can't have changed. `OllamaRouter` now remembers the last
confirmed-unreachable timestamp and fast-fails `classify()`/
`stream_thinking()` with the identical `{"error": ...}` shape for
`_UNREACHABLE_RETRY_SECONDS` (30s) afterward, then retries for real —
same shape as `AppController`'s `_FAILURE_RETRY_SECONDS`. Purely a
latency change: the response `_process_single_request` sees (fall
through to search-first) is byte-identical either way. 4 new tests
(`TestOllamaFastFailWhenRecentlyUnreachable`) cover the fast-fail path,
the retry-after-cooldown path, the flag clearing on a real success, and
that a fresh router never fast-fails its first call.

---

## Merged-in: widget/display branch (originally "BETA 0.3.51" / "BETA 0.3.52")

Requested: make the widget's transition into the INFO/ERROR display card
smooth (animated, not an instant cut), keep that card on screen until the
person clicks elsewhere or presses Ctrl+K again (at which point it
collapses back into the widget smoothly but quickly), make the hover
panel stop auto-collapsing while the person is actually using it, and do
a broader pass over the widget's architecture/design for anything else
that could hurt the UX or degrade the pipeline's actual results.

### Smooth entrance/exit animations

Every frameless popup in `toki_desktop_mark.py` (`_ReplyBubble`,
`_DoneNote`, `_CommandsPanel`) used to `self.show()`/`self.hide()`
instantly -- a hard cut, no transition. New shared helpers
`_popup_fade_in(widget, target_pos)` / `_popup_fade_out(widget)` give all
three a consistent fade + short slide (170ms in, 130ms out; the DONE
note uses a slightly quicker 130ms/110ms pair since it's meant to feel
snappier). Animation objects are stored as attributes ON the widget
itself, not local variables -- confirmed directly that an early version
using local variables had PyQt garbage-collect the `QPropertyAnimation`
mid-flight (its last Python reference goes out of scope the instant the
function returns, well before a 150-200ms animation finishes), silently
cutting every animation short.

### Sticky persistent UI: click-elsewhere-or-Ctrl+K to dismiss

New `DesktopMark` state, `"engaged"`, alongside the existing `"idle"` /
`"listening"` / `"working"`: when `show_result()` receives an INFO or
ERROR strategy, the mark now stays at its expanded size/position instead
of collapsing back to the idle notch the instant the turn finishes (the
old `_bridge.done -> self.idle` connection was unconditional; it's now
routed through `_on_turn_done()`, which only calls `idle()` when the
mark isn't currently `"engaged"`). The persistent reply card and the
hover "scheduled commands" panel are both tracked as sticky
(`_sticky_reply_active` / `_sticky_panel_active`) and only come down via
`_dismiss_sticky_ui()`, triggered by:

- **A left-click anywhere** -- including outside this app's own windows
  entirely, which a plain Qt event filter has no way to see (Qt only
  gets events for its own windows). Implemented as a second lightweight
  pynput listener (`_run_mouse_listener()`, mirroring the existing
  Ctrl+K `_run_listener()` pattern exactly: background daemon thread,
  bridges via a Qt signal for cross-thread safety), checking only
  whether the click point falls inside the mark/card/panel's geometry --
  never anything about the click target itself (no window title, no
  app, no control). **Worth being upfront about the tradeoff**: this is
  a second system-wide input hook running continuously, which costs a
  small amount of background CPU and is a category of capability some
  security software watches more cautiously (global input hooks in
  general resemble what a keylogger does, even though this one only
  ever reads coordinates). Documented directly in
  `_start_global_click_listener()`'s docstring, including how to turn it
  off (don't call it from `DesktopMark.__init__`) without losing
  anything else -- Ctrl+K still dismisses either way.
- **Ctrl+K pressed again** (`_on_hotkey`): dismisses first, then
  proceeds with its normal listening-state logic -- deliberately not
  turned into a pure "close" action, since that would silently eat the
  very next Ctrl+K press someone expects to start listening with. In
  practice this reads as one fluid motion: card collapses, mark starts
  listening.
- **Clicking the mark itself** (already routes through the same
  `_on_hotkey` path via the existing single-click handling) and
  **double-clicking to open the typed-prompt box** (`_show_prompt_box`
  now dismisses sticky UI first, on the reasoning that typing a new
  command means you're done reading the old result).

### Hover panel: no longer auto-collapses on mouse-leave

Previously, `leaveEvent` started a 200ms grace timer that called
`_maybe_hide_panel()`, closing the panel (and the reply bubble, and
re-collapsing the mark) the moment the cursor left both geometries. This
was a real risk while actually using it: cancelling a scheduled item
means moving the mouse toward a small ✕ button, and a fast or imprecise
mouse path could trip that 200ms leave-timer mid-click, closing the
panel out from under the very click meant to use it. `_maybe_hide_panel`
and `_panel_hover_timer` are removed entirely; the panel is sticky once
genuinely opened (`_expand_for_hover`'s existing `HOVER_INTENT_MS` dwell
check still guards against a brush-past triggering it in the first
place) and only closes via the same `_dismiss_sticky_ui()` used by the
reply card.

### Other UX/pipeline correctness gaps found during this pass

- **PowerShell timeout was silently indistinguishable from success.**
  `_run_and_classify()`'s `done_event.wait(timeout=30)` had no way to
  tell `classify_display()` whether it actually completed or just gave
  up waiting -- a timeout left `exit_code` as `None`, which the
  `exit_code not in (None, 0)` check treated as a clean success. For a
  DONE-classified intent (e.g. `COMPRESS_SELECTED_FILE` on a large
  folder), this meant a still-running command could show a bare "Done."
  -- an outright false claim. Added a first-class `timed_out` parameter
  to `classify_display()`, checked before the exit-code branch, that
  always returns INFO with an honest "still running, taking longer than
  expected, showing what's come back so far" message regardless of the
  intent's normal DONE/INFO classification. Verified against a mock
  simulating a slow command: partial output before the timeout is shown,
  output arriving after the timeout is correctly excluded, and the
  message is never a bare "Done."
- **The "no orchestrator available" fallback predated the categorized
  display system entirely** -- still used the old `show_reply()` +
  hardcoded `QTimer.singleShot(800, mark.idle)`, disconnected from
  everything else in this file. Genuinely an error state, so it now goes
  through the same `result_ready`/`"engaged"` path as any other ERROR
  turn.

### Verification

- `tests/test_display_strategy.py`: 4 new tests for the `timed_out`
  parameter (honest partial-output message on an INFO intent, a
  DONE-classified intent that times out must NOT show "Done.", the
  empty-output timeout case, and a regression guard that
  `timed_out=False` leaves the existing non-timeout behavior unchanged)
  -- 43 total, all passing.
- Full sticky/dismiss state machine smoke-tested directly under
  `QT_QPA_PLATFORM=offscreen`: INFO result → `state="engaged"`,
  card visible → outside click → dismissed, `state="idle"`; ERROR result
  → engaged → Ctrl+K → dismissed AND transitions to `"listening"` in the
  same call, exactly as intended.
- Hover panel verified sticky: expands on hover-intent, stays visible
  through a simulated mouse-leave (the old auto-collapse trigger),
  dismissed only by an explicit outside click.
- Reply-card click semantics verified: a click landing *inside* the
  card's geometry does not dismiss it; only a click outside every sticky
  surface does.
- `_run_and_classify()`'s timeout path re-verified end-to-end against a
  mock orchestrator simulating a slow `RunningCommand`: partial output
  captured before the shortened timeout, output arriving after is
  correctly excluded, message is never "Done."
- Full suite: **`1068 passed, 1 skipped, 2 xfailed`** (zero regressions
  from the `1064`-test baseline this session started from).

## BETA 0.3.51 — DONE / INFO / ERROR display strategy: the widget now distinguishes "quick confirmation" from "content the person actually needs to read"

Requested: categorize every intent into "an action happened" (DONE) vs.
"here's information" (INFO/ERROR), and change the widget so INFO/ERROR
turns show in a persistent card ("rectangle"/"island") instead of the
old one-size-fits-all 3-second auto-fading reply bubble, while DONE stays
a quick note.

### The real gap this surfaced

Before this, every turn -- "Done.", a full directory listing, a "did you
mean X?" clarifying question, a destructive-command confirmation prompt,
an outright failure -- rendered through the exact same `_ReplyBubble`,
auto-hiding after `REPLY_SHOW_MS` (3000ms) regardless of content. Worse,
tracing `process_request()`'s actual return shape for `kind ==
"powershell"` (which covers most INFO-classified intents --
`LIST_FILES`, `DISK_USAGE`, `READ_FILE`, `PROCESS_LIST`, ...) found that
the returned `response` field is **always the literal string `"Done."`**
for every powershell dispatch, success or failure alike -- the real
stdout only exists in the `on_output` callback, streamed in
asynchronously on `executor.RunningCommand`'s own background thread,
*after* `process_request()` has already returned. `main_widget.py`
passed `on_output=lambda _line: None` -- a no-op. So before this fix, a
majority of the app's INFO-classified commands would have flashed a bare
"Done." and discarded their actual content entirely, regardless of any
display-strategy work layered on top. Fixing the display strategy
required fixing this collection gap first, not just adding a new UI
mode on top of the existing (incomplete) text pipe.

### `display_strategy.py` (new)

`DisplayStrategy` enum (`DONE` / `INFO` / `ERROR`) plus
`INTENT_DISPLAY_MAP`, a manual classification of all 81 real intents in
this codebase (`intents.py` + `intents_extended.py` +
`intents_app_control.py` + `GENERATE_FILE`, which `orchestrator.py`
registers at runtime rather than in those files -- see its own comment
above `INTENTS["GENERATE_FILE"] = {...}` -- + `PLUGIN_HELLO` from
`plugins/example_plugin`). Verified exact against the live, merged
intent set via
`tests/test_display_strategy.py::TestMapCompleteness::test_map_covers_every_real_intent_exactly`,
which diffs the map against `orchestrator.INTENT_NAMES` directly -- a
new intent added anywhere (core or plugin) without updating this map now
fails that test loudly instead of silently defaulting at runtime.

`classify_display(result, collected_output="", exit_code=None) ->
(DisplayStrategy, text)` is the actual per-turn decision function.
Combines the static intent map with `orchestrator.py`'s runtime `kind`
field, since `kind` alone can't distinguish DONE from INFO (`MAKE_FOLDER`
and `LIST_FILES` are both `kind="powershell"`) but IS needed for the
powershell-specific async-result handling above. Also treats a nonzero
exit code as `ERROR` regardless of the intent's normal classification
(a failed `DELETE_ITEM` is still an error, not a "done"), and an
`is_api_failure`-style `"Hmm, that didn't work."` prefix (the exact
string `orchestrator.py`'s own `kind == "api"` branch already produces
on failure) as `ERROR` regardless of the intent. Unmapped/unknown cases
default to `INFO` rather than `DONE` -- losing real content to an
over-eager 1.4s fade is worse than an unnecessary persistent card.

### Widget changes (`toki_desktop_mark.py`, `main_widget.py`, `ui_theme.py`)

- `ui_theme.py`: added a `"green"` accent alongside the existing
  `blue`/`orange`/`red`, for the DONE note specifically (INFO already
  owns blue, ERROR/danger already own red).
- `_ReplyBubble` (existing class) gained a persistent mode: `show_below()`
  now takes `accent=` and `persistent=` — the original call site
  (`show_reply()`, used by drag/drop file-selection feedback) is
  completely unchanged in behavior (blue, 3s auto-fade). The new
  persistent mode (blue for INFO, red for ERROR) skips the auto-hide
  timer entirely, wraps the body in a `QScrollArea` so long content (a
  real directory listing, generated file contents) scrolls internally
  instead of growing the popup off-screen, and dismisses on click
  anywhere on the card.
- New `_DoneNote` class: a small, separate, quick-fading (1.4s)
  confirmation pill, green accent, "✓ Done" (+ any detail past
  `orchestrator.py`'s own leading `"Done."` prefix, stripped so it
  doesn't read "✓ Done — Done. Scheduled..."). Deliberately its own
  class rather than a third `_ReplyBubble` mode -- DONE is meant to look
  and read differently at a glance, not just differently-colored.
- `_Bridge` gained a new signal, `result_ready = pyqtSignal(str, str)`
  (strategy, text) -- additive, the existing `reply = pyqtSignal(str)`
  and its `show_reply` connection are untouched (drag/drop still uses
  `show_reply` directly, unrelated to turn dispatch).
- `DesktopMark.show_result(strategy, text)` (new): routes to
  `_done_note` for `"done"`, `_reply_bubble` in persistent mode
  (accent per strategy) for `"info"`/`"error"`/anything unrecognized.
- `main_widget.py`: new module-level `_run_and_classify(orch, text)`
  wraps `process_request()` with real `on_output`/`on_done` collectors
  (replacing the previous no-ops), waits on a `threading.Event` (bounded
  by `_POWERSHELL_RESULT_TIMEOUT_S = 30`, only for `kind ==
  "powershell"`) for the async completion, then calls
  `classify_display()`. All three of `main_widget.py`'s dispatch call
  sites (`_dispatch_text`'s main turn path, the permission-confirm
  avatar-click path, and the dictation-stop-button path) now emit
  through `_bridge.result_ready` instead of the old bare
  `_bridge.reply.emit(response)`.

### Verification

- New `tests/test_display_strategy.py`: 39 tests -- map completeness
  against the live intent set, individually-pinned classifications for
  the most consequential intents, and `classify_display()` behavior
  across every `kind` (including the powershell async-collection paths,
  the nonzero-exit-code-is-always-error rule, the api-failure-prefix
  rule, and the unmapped-defaults-to-INFO safety net).
- `_run_and_classify()` verified end-to-end two ways: (1) against the
  real orchestrator for `"what time is it"` (api/INFO, correct output
  shown) and PowerShell-kind commands (correctly surfaced as `ERROR`
  with the real `[executor error] ...` text captured via `on_output` --
  this sandbox has no `powershell` binary, which is itself a useful
  confirmation that the exit-code/error path works, not a gap in this
  session's testing); (2) against a mock orchestrator simulating a
  real async `RunningCommand` (output arriving after
  `process_request()` already returned "Done.", `on_done` firing on a
  separate thread) for both a clean 0-exit success (`LIST_FILES` ->
  `INFO`, real collected output, not "Done.") and a nonzero-exit failure
  (`DELETE_ITEM` -> `ERROR`, real stderr captured) -- both matched
  exactly.
- Widget-level smoke test under `QT_QPA_PLATFORM=offscreen`: all three
  `DesktopMark.show_result()` paths render and dismiss correctly.
- `tests/test_desktop_mark_dragdrop.py` (pinned against `show_reply`
  directly, unrelated to this change) re-verified unaffected.
- Full suite: **`1064 passed, 1 skipped, 2 xfailed`** (39 new tests,
  zero regressions from the `1025`-test baseline this session started
  from).

---

## BETA 0.3.50 — three live misroute/gap bugs found and fixed via direct `orchestrator.py`/`graph_router.py` testing, plus a test-collection bug and a second, more severe collision the fix itself introduced (all caught before landing)

Requested: re-run the harness, then fix whatever the previous pass found,
with a hard requirement that the fixes not regress anything and that the
new tests be harder than the ones that would've caught the bug by
accident. Followed the project's own established process for phrasing
changes (see the "194-prompt corpus" section below this entry) rather
than trusting pytest alone, which is what surfaced the second bug.

**Baseline before touching anything:** `952 passed, 1 skipped, 2 xfailed`
— clean, matched the prior report exactly.

### Bug 1 — "turn the volume off" scored `VOLUME_UP` (opposite of the request, zero-slot auto-dispatch)

Same bug class as the BETA 0.3.27 "shut up" fix, different missing word.
`"off"` appeared nowhere in the Tier A phrasing corpus, so it was dropped
as out-of-vocabulary, leaving only `"turn"+"volume"` to score — which
matched `VOLUME_UP`'s own corpus more than `VOLUME_DOWN`'s.

**First attempt (later found to be wrong, see below):** added `"off"`
across four phrasings to `TOGGLE_MUTE` — `"turn the volume off"`, `"turn
off the volume"`, `"turn my volume off"`, `"volume off"`. This fixed the
reported bug and passed the full 191-prompt real-world corpus diff
(`batch_test_prompts_v2/v3a/v3b/v3c/v3d.py`, snapshotted via
`classify_or_ask()` against a pristine copy before and after) with zero
regressions.

**Second bug, found by adversarial sweeping *after* the first fix looked
clean:** systematically probed `"turn off <X>"` for unrelated features
TOKI has no intent for at all — `wifi`, `bluetooth`, `monitor`, `vpn`,
`dark mode`, `night light`, `flight mode`, `notifications`, `do not
disturb`, `airplane mode`. Every one of these **confidently
auto-dispatched to `TOGGLE_MUTE`** under the four-phrasing fix — worse
in scope than the original bug, since these are all plausible things a
real person might say.

Root cause, confirmed by directly inspecting `_build_tfidf_index()`'s
output: `"off"` has a very high IDF (it existed in only one command), and
repeating `"turn"+"off"` together across four phrasings gave those two
words enough combined term-frequency weight in `TOGGLE_MUTE`'s own
tf-idf vector that a query containing **only** `"turn"+"off"`, with
every other word completely out-of-vocabulary (e.g. `"turn off my
monitor"` — `"monitor"` matches nothing), scored **~0.535** cosine
similarity against `TOGGLE_MUTE`. That's just over `CONFIDENCE_THRESHOLD`
(0.5), so it auto-dispatched with zero required slots. `"shut"` (the
BETA 0.3.27 fix's anchor word) never had this problem because it's rare
enough that it essentially never attaches to unrelated nouns in natural
English — `"off"` is generic enough that it does, constantly.

**Fix:** narrowed to exactly three phrasings — `"turn the volume off"`,
`"turn off the volume"`, `"volume off"` (dropped the redundant `"turn my
volume off"` entry; it still generalizes correctly via cosine similarity
on the other three, verified live). This keeps `"turn"+"off"+"volume"`
together scoring confidently (all five originally-reported phrasings,
including the case/politeness/whitespace-noise variants) while
`"turn"+"off"` alone stays safely below threshold. Verified against all
14 collision probes above (all now correctly miss the graph and fall
through to ask/LLM, same as pristine baseline) plus the 191-prompt corpus
again (only 4 harmless already-"ask"-both-times candidate shifts on
genuinely nonsensical prompts like `"optimize volume"` — never an
auto-dispatch either way, before or after).

Rebuilt via `migrate_to_kuzu.py` after the final phrasing set, not the
first one. Pinned in `tests/test_graph_router.py::TestVolumeOffMeansMute`
— both the original-bug cases and, explicitly, all 14 collision probes
(`test_unrelated_turn_off_phrasings_do_not_misroute_to_mute`) so this
exact regression class can't silently return.

### Bug 2 — `SET_TIMER` (0.3.48's own fix) had phrasing gaps that reopened the exact bug it was built to close

Confirmed live, end-to-end through `orchestrator.process_request()`:

- `"set an alarm for 5 minutes"` / `"give me a reminder in 15 minutes"`
  → scheduled `command_text="set an alarm"` / `"give me a reminder"`,
  re-dispatching and silently web-searching that leftover text when the
  timer fired — the exact 0.3.48 bug, recurred.
- `"set a timer for an hour"` / `"set a 10 minute timer"` → not
  recognized as a timer **at all**, immediately web-searched the whole
  sentence, no timer ever created.

Two independent root causes in `extractor.py`:
1. `_BARE_TIMER_REMAINDER_RE` only accepted `"a"`/`"the"` (not `"an"`)
   before the trigger word, and only recognized `"set"` as a lead-in verb
   — `"an alarm"` and `"give me a reminder"` matched nothing.
2. `_RELATIVE_TIME_RE` only recognized a digit before the unit —
   word-form durations (`"an hour"`, `"a minute"`) and a duration with no
   preposition at all directly in front of the trigger word (`"a 10
   minute timer"`) never reached the scheduling pre-check.

**Fix:**
- `_RELATIVE_TIME_RE` now accepts `"a"`/`"an"` as amount-1 alongside
  digits.
- New `_BARE_DURATION_BEFORE_TIMER_RE`, anchored via lookahead on
  `timer`/`alarm`/`reminder` specifically (not a general "number + unit
  anywhere" detector — that would turn ordinary sentences like `"the
  movie is 90 minutes long"` into scheduling requests), handles the
  no-preposition case.
- `_BARE_TIMER_REMAINDER_RE` now accepts `"an"` and `"give me"` as a
  second lead-in alongside `"set"`.

Verified end-to-end via `orchestrator.py` for all four originally-broken
phrasings plus case/politeness noise, and verified real scheduled
commands (`"shut down in 10 minutes"`) and bare ambiguous time
expressions (`"in 10 minutes"` alone, no trigger word) are unaffected —
still correctly ask, don't guess. Pinned in
`tests/test_scheduling_and_conditionals.py::TestSetTimerPhrasingGaps`,
including explicit false-positive guards
(`test_no_false_positive_on_incidental_durations`,
`test_no_false_positive_on_number_unit_before_unrelated_noun`) and direct
regex unit tests for the `_BARE_TIMER_REMAINDER_RE` fix itself.

### Bug 3 (minor, safe — no misroute, just a UX gap) — dictation/macro recording didn't recognize bare imperatives

`"record what I say"` / `"record my screen"` / `"record everything I
say"` / `"start recording my clicks"` all fell through to a plain
graph/LLM miss (silent web search) instead of starting dictation/macro
capture or asking. Two root causes in `extractor.py`:

- `_START_LISTENING_RE`'s "recording + say-object" branch required **two
  separate** `"record"`-root words (one for its own opening
  `(start|begin|record)` group, a second for the literal `"record(ing)?"`
  right after) — a bare `"record what I say"` only has one, so it
  satisfied neither that branch nor the `"start|begin ... what I say"`
  branch (no start/begin present either).
- `_START_SEEING_RE` only recognized `"recording what I click"`, not
  `"recording my clicks"`, despite `"clicks"` being an unambiguous macro
  signal on its own.
- `looks_like_ambiguous_start_recording()` required a literal
  `"start"/"begin"` before `"recording"`, so a bare `"record my screen"`
  (no do/click/type/clicks/say object either) missed even the ask-once
  safety net and fell straight through to a raw miss.

**Fix:** single-occurrence `"record(ing)? ... (everything|what) I say"`
branch added to `_START_LISTENING_RE`; `"record(ing)? ... my clicks?"`
branch added to `_START_SEEING_RE`; `_AMBIGUOUS_START_RECORDING_RE`
widened to also match bare `"record"/"recording"` with no `"start"`
prefix. The widening is safe specifically because
`orchestrator.py` always checks `looks_like_start_seeing()` and
`looks_like_start_listening()` **before** consulting the ambiguous
fallback (confirmed by reading the call site directly) — so any phrasing
with a real object word is already resolved deterministically by the
time a bare `"record"` reaches the fallback.

Verified end-to-end via `orchestrator.py`. Pinned in
`tests/test_recording_disambiguation.py`, both extractor-level unit
tests and orchestrator-level end-to-end tests, including a
`test_widened_ambiguous_fallback_does_not_break_ordering_contract` check
documenting *why* the widened regex being a strict superset match is
fine (the calling order, not the regex alone, is what keeps resolved
cases from being re-asked about).

### Test-infrastructure bug found and fixed alongside the above

`tests/test_extractor.py` had **two classes both named
`TestStartListeningTrigger`** (lines 1132 and 1187 in the pre-fix file).
Python silently discards the first class definition at module-import
time when a later class reuses the same name — so pytest never collected
`test_recording_with_voice_object_matches` or
`test_bare_recording_does_not_match` from the first class at all. This
meant the `952 passed` baseline **silently excluded the actual pinning
test for the Bug 3 fix**. Confirmed directly: `pytest --collect-only -k
TestStartListeningTrigger` showed only 5 tests before the fix, 9 after.
Scanned the entire `tests/` directory (and the rest of the repo) for the
same pattern — both duplicate class names and duplicate method names
within a single class (same silent-shadowing risk) — via a small AST
script; this was the only instance anywhere. Fixed by renaming the first
class to `TestStartListeningRecordingObjectBranch`.

### Verification

- Full 191-prompt real-world corpus (`batch_test_prompts_v2.py` +
  `v3a_chains.py` + `v3b_wcl_breadth.py` + `v3c_apps_and_edge_cases.py` +
  `v3d_filesystem_edge_cases.py`) diffed via `classify_or_ask()` snapshot,
  pristine vs. fixed, per the project's own established process for
  phrasing changes — zero regressions, only 4 expected/harmless
  already-ambiguous candidate shifts.
- Broad systematic sweep after all fixes landed: `"turn on/off"` /
  `"enable"` / `"disable"` / `"switch off"` against ~40 device/feature
  nouns (wifi, bluetooth, monitor, notifications, camera, microphone,
  vpn, hotspot, printer, router, ...) — 273 probes, only 7 non-`None`
  hits (`"location"` → `GET_LOCATION`, `"battery saver"` →
  `BATTERY_STATUS`), and both confirmed **pre-existing and identical
  in the pristine baseline** — unrelated to any change this session,
  informational-read intents rather than destructive ones, left as-is
  (out of scope for this pass; flagging here rather than silently
  "fixing" something not requested).
- Full suite: **`1025 passed, 1 skipped, 2 xfailed`** (73 new tests
  across `test_graph_router.py`, `test_scheduling_and_conditionals.py`,
  `test_extractor.py`, and `test_recording_disambiguation.py`; zero
  regressions from the `952`-test baseline).
- All previously-documented collision cases (bitlocker/lock, wipe disk,
  clipboard get/set, task manager, shut-up, file-organizer/grouping
  phrasings, destructive-shadow-guard AMBIGUOUS coverage) re-verified
  live, unaffected.

## BETA 0.3.49 — docs cleanup: widget confirmed as the permanent UI, README's app.py-era history compressed

Follow-up to the same session's recording-disambiguation entry below.
The person confirmed the widget (`main_widget.py`) is the UI long-term,
not a transitional state, so the stale `app.py` references flagged
earlier were worth actually fixing rather than leaving as a banner.

- **`README.md`'s architecture table** now describes `main_widget.py` /
  `toki_desktop_mark.py` accurately (read `main_widget.py` directly to
  do this correctly rather than guessing): no chat window, a plain
  background `threading.Thread` per message rather than a QThread
  `Worker`, replies as floating text next to the mark
  (`mark.show_reply()`) rather than `ChatBubble`s. Also caught and
  documented a real behavioral gap while doing this: `GENERATE_FILE`'s
  token-streaming (`on_generate_token`/`on_generate_done`) is fully
  wired in `orchestrator.py` but **`main_widget.py` doesn't pass either
  callback**, so the live-preview-while-generating behavior the old
  `app.py` had doesn't exist in the current UI — it just shows "working"
  until the whole turn finishes. Not fixed (out of scope for a docs
  pass), but documented accurately instead of silently misdescribed.
- **README's whole "v2.6–v2.11 changes" section (~400 lines) condensed**
  into one "Earlier history" block. That versioning scheme predates
  `STATUS.md`'s `BETA 0.x` numbering and several of those entries
  described `app.py`-only UI classes (`ChatBubble`, `Worker`,
  `MainWindow`) that don't exist anywhere in this codebase anymore, not
  just renamed — kept the parts that were actually about
  `orchestrator.py`'s pipeline (still current), condensed the
  UI-specific parts into one clearly-labeled historical paragraph.
- `WIDGET_README.md` / `PROJECT_STATE_OVERVIEW.md` banners updated from
  "transitional, flag if you want this fixed" to reflect that
  widget-only is the confirmed permanent direction.

## BETA 0.3.49 — "start recording" no longer silently guesses between macro capture and dictation (chat session, tested not guessed)

The bug: `_START_SEEING_RE` (macro capture) matched bare "start
recording" unconditionally, silently claiming it every time — even when
"start recording what I say" (dictation) was meant. Two genuinely
distinct, real features (`START_SEEING`/macro click-capture,
`START_LISTENING`/voice dictation) shared one ambiguous trigger phrase
with no way to tell them apart from text alone once the object word
(click/do/type vs. say) is missing.

Tried the "score it better" approach first and confirmed — again, same
conclusion as BETA 0.3.47's `STOPWORDS` fix — that this class of problem
has a real ceiling: there's no text signal left once seeing/watching/
listening/dictating/say/do/click/type are all absent from a bare "start
recording." Fix has two parts:

1. **Where an object word IS present, route deterministically, no
   question asked.** `_START_SEEING_RE` now requires "recording" to be
   paired with "what/everything I do/click" (mirroring its own existing
   pattern); added the symmetric branch to `_START_LISTENING_RE` for
   "recording ... what/everything I say." `"start recording what I
   click"` and `"start recording what I say"` both still resolve
   instantly, unchanged in practice.
2. **Where no object word is present — the genuinely irreducible
   case — ask once instead of guessing**, via a new
   `_pending_recording_choice` state (same pattern as
   `_pending_graph_ask`/`_pending_confirmation`): "Recording clicks to
   save as a macro, or recording/dictating what you say?" A reply that
   doesn't clearly pick one is NOT guessed at — reprocessed as a fresh
   message, same fallthrough shape used everywhere else in this file for
   an unclear follow-up reply.

**"Stop recording" resolved differently, and better, than "start":** by
the time someone says "stop," something real either is or isn't actually
running, which is information text alone never has for "start." So
`orchestrator.py` checks `app_controller._active_recorder`/
`_active_dictation` directly — only asks if both happen to be active at
once (contrived but not prevented anywhere), and says "nothing's
currently recording" plainly if neither is, instead of guessing either
way.

Verified live, end-to-end, against the real orchestrator: bare "start
recording" asks; "dictation"/"macro" as the reply routes correctly;
"start recording what I say" / "what I click" both skip the question
entirely; "stop recording" resolves via real runtime state with zero
questions asked in the common (one thing running) case. 14 new tests in
`tests/test_recording_disambiguation.py`, 866 passed overall (up from
845 at 0.3.48).

**On the third "record a person" concept mentioned but deliberately
skipped this session:** reasonable to leave out for now, and not
permanently blocked either — if it's built later, giving it a required
target/name slot as part of its normal phrasing ("record John," "record
the meeting with Sarah") sidesteps the bare-ambiguity problem on its own,
the same way "recording what I say"/"what I click" already do for the
two features above. The thing to avoid is giving it a trigger word that
overlaps "recording" with nothing else distinguishing it.

## BETA 0.3.48 — routing precision + real timer/reminder support (chat session, tested not guessed)

Four separate fixes, each verified against the real graph DB / real
orchestrator, not just described.

**1. `LIST_FILES`'s phrasing corpus was too thin.** Only 3 hand-written
training phrasings, none containing "desktop," "tell," "show," or
"everything" — those scored exactly 0 against every command, so
completely normal phrasing missed the confidence threshold entirely
(`'tell me all the files on my desktop'` -> below-threshold ask, should
HIT). Widened `LIST_FILES`'s phrasings in
`graph_source_data/tier_a_phrasings.py`, rebuilt the graph. Confirmed fixed.

**2. Interrogative/discourse fillers were being scored as content words.**
`"what"`, `"does"`, `"mean"`, `"hi"`, `"going"` carry zero signal about
*which* command someone wants, but show up constantly in general
questions/greetings, and occasionally glued onto a real command's
vocabulary by pure coincidence:

    'what is the capital of mexico'      -> fake LIST_FILES candidate, 0.381
    'what does mexico and capital mean'  -> fake PATH_EXISTS candidate, 0.315
    'hi how is it going'                 -> fake COUNT_FILES candidate, 0.378

Tried a proper fix for this class of problem generally first — a real
rejection/negative class, giving the scorer actual chat/trivia phrasings
to compete against — and confirmed it *still* wasn't reliable enough on
its own; bag-of-words scoring has a real ceiling here, not a tuning
problem. What did work, cheaply: added these fillers to
`graph_router.py`'s `STOPWORDS`. Confirmed the false positives above now
come back as genuine total misses, while real commands using the exact
same words still hit correctly (`"what's the weather"` -> GET_WEATHER,
`"who am i logged in as"` -> CURRENT_USER) since those are carried by
their own domain nouns, not the interrogative. Given 0.3.46 already
routes every below-threshold miss to a silent raw-text search, this
isn't a user-facing behavior change for these cases — it's fixing
`vocab_staging.jsonl`, which was getting polluted with wrong low-confidence
guesses for text that was never command-shaped.

Known remaining edge case, not a bug: `"wow my project sucks i should
quit"` still weakly proposes `KILL_PROCESS` (0.172, well under the 0.5
dispatch floor) because `"quit"` is genuinely real `KILL_PROCESS`
vocabulary (`"force quit this program"`) — real lexical ambiguity, not
noise. Can't auto-dispatch, doesn't surface a question, falls through to
a harmless raw-text search.

**3. App-launch requests were only checked against real installed apps
*after* committing to LAUNCH_APP/OPEN_ITEM.** `app_control.py` already
had the right machinery (`app_exists()`, cached `Get-StartApps`) — it
just ran too late, so phrasings like `"pull up obs"` (no "open/launch"
trigger word, "pull up" isn't in graph vocabulary) never scored
confidently and fell straight to a web search. Fix: the graph/LLM-miss
fallback in `orchestrator.py` now runs the same `resolve_open_target()`
cascade one step earlier, before defaulting to search. Ground-truth
existence check, not another fuzzy score, so it doesn't share fix #2's
ceiling. Skipped when the explicit `""` open-target convention is used.

**4. No real timer/reminder support — confirmed missing, not just hard
to find.** Two bugs: `find_time_expression()`'s regex only matched `"in
N minutes"`, never `"for N minutes"`, so `"set a timer for 10 minutes"`
(the single most natural phrasing) matched nothing and fell straight to
a raw miss. And phrasings that DID match (`"remind me in 20 minutes"`)
got classified as `SCHEDULE_COMMAND`, storing the leftover text
(`"remind me"`) as `command_text` — which gets blindly re-run through
the full pipeline at fire time, so the timer firing meant silently
web-searching "remind me." Fixed by widening the time regex to accept
"for," and splitting out a new `SET_TIMER` intent (separate from
`SCHEDULE_COMMAND`) whose `kind: "timer"` dispatch is a plain
notification, never a re-classify-and-dispatch. Detection
(`looks_like_bare_timer()` in `extractor.py`) is a small curated
trigger-word table (timer/reminder/alarm/remind me/etc.), same "fixed
table, not a classifier" posture `synonyms.py` already uses — not an
attempt to solve fix #2's general problem. Deliberately does NOT treat a
fully bare time expression with no trigger word (`"in 10 minutes"`
alone) as a timer — genuinely ambiguous, still falls through to
`SCHEDULE_COMMAND`'s existing ask, regression-tested explicitly.

Verified live end-to-end against the real orchestrator:

    "set a timer for 2 seconds"                    -> Timer set as S1... (fires: "Timer is up!")
    "lock my computer in 3 seconds"                -> still SCHEDULE_COMMAND, unaffected
    "in 10 minutes"                                -> still asks "what should I do, and when?"
    "remind me in 2 seconds to check the oven"     -> Timer set... fires with the label, never re-dispatched

`tier_a_wcl_map.py` needed a `SET_TIMER: frozenset()` entry (no WCL
cmdlet equivalent, same as `SCHEDULE_COMMAND`) to satisfy
`test_map_covers_every_tier_a_intent`.

Not done this session: `FIND_FILES`/`OPEN_ITEM`/`READ_FILE` still have
only 3 phrasings each, same thin-corpus risk `LIST_FILES` had — left
alone since they hadn't actually been hit yet. Fix #3 is logic-verified
against the test suite but not exercised against a real `Get-StartApps`
call on an actual Windows machine (this sandbox has none). Timer
notifications go to chat history only, same visibility model
`SCHEDULE_COMMAND` already uses — no OS-level toast/tray push (there's a
`QSystemTrayIcon` in `toki_desktop_mark.py` that could carry one, but
wiring a UI-layer notification from UI-agnostic `orchestrator.py` is a
bigger, separate decision).

845 passed, 2 skipped, 2 xfailed (was 839 passed at 0.3.46) --
`test_voice_pipeline.py`/`test_video_downloader.py`/`test_app_control.py`
excluded from this session's runs, pre-existing environment gaps
(PyQt6/other native deps not present in the sandbox this session ran in),
not touched.

## BETA 0.3.46 — search-first fallback (fixes the "does mexico and capital mean search for file" bug)

**Root cause:** with Ollama mostly retired, every graph/WCL miss fell
through to `graph_router.classify_or_ask()` — a fail-open safety net
only ever meant for Ollama going down mid-session. With Ollama basically
never up, that safety net became the default handler for all normal
conversation and general-knowledge questions. `classify_or_ask()` scores
plain word-overlap against TOKI's command phrasings with no real
language understanding, so it started confidently proposing commands for
plain questions:

    'what is the capital of mexico' -> candidate LIST_FILES, 0.381
    'hi how is it going'            -> candidate COUNT_FILES, 0.378

Tried three ways to auto-separate these from real command near-misses
(confidence floor, idf weighting, coverage ratio) — none reliably works;
bogus matches score as high as genuine near-misses like "kill
notepad.exe" (0.172). Real language understanding was the actual gap,
which is why the original design leaned on Ollama for exactly this.

**Fix, in `orchestrator.py`'s `_process_single_request()`:** Ollama's
`classify()` is tried first, unconditionally, for every graph/WCL miss.
If it errors (the common case now), TOKI runs an actual web search on
the raw text via the existing SEARCH_WEB/Chrome path instead of
surfacing the graph's guess as a confusing clarifying question. A WCL
command that's genuinely resolved/ambiguous but can't be safely
auto-filled is NOT swept into search — it keeps its own "found a match,
can't fill it in yet" message. The confirmation-cancel flow ("run this?
no thanks") still cancels silently with no side effect.

**Known, disclosed trade-off:** command-shaped near-misses that used to
get a specific clarifying question ("kill notepad.exe" → "did you want
to kill process notepad?") now search the web for that text instead,
whenever Ollama is down — no way to keep the old behavior without also
keeping the false-positive bug this fixes. (Narrowed further in 0.3.47/
0.3.48 above — see those entries.)

823 passed, 2 skipped, 2 xfailed at the time.

## BETA 0.3.45 — requirements/test fixes, invisible-reply-bubble bug, shared UI theme (chat session, tested not guessed)

Two fixes found while installing checkpoint 4 fresh on a real machine:

- **`requirements.txt`** -- `winsdk>=1.0.0` was unresolvable: winsdk has
  never shipped a stable 1.0.0, only prerelease builds, and pip excludes
  prereleases from a bare `>=` range by default. Pinned to the actual
  latest prerelease, `winsdk==1.0.0b10; sys_platform == 'win32'`, so a
  clean `pip install -r requirements.txt` succeeds.
- **`macro_recorder.py`'s `MacroPlayer.play()`** -- the pywinauto
  "unavailable" branch used a live `try: import pywinauto... except
  ImportError`, which only reports unavailable if pywinauto genuinely
  isn't installed. `test_pywinauto_unavailable_reports_clearly` tried to
  simulate that by popping `pywinauto.mouse`/`pywinauto.keyboard` out of
  `sys.modules`, but on any real machine (pywinauto is a hard win32
  dependency per this same file) that pop is a no-op -- Python just
  re-imports the installed package and the "isn't available" branch
  never fires. Switched `play()` to check `app_control._PYWINAUTO_AVAILABLE`,
  the same cached-flag pattern `app_control.py` already uses for this
  exact problem, and updated the test to monkeypatch that flag instead
  of popping `sys.modules` -- matching `test_app_control.py`'s
  established, working pattern.

`test_document_backend.py::TestPandocDiscovery::test_falls_back_to_path_when_not_bundled`
also failed in the same run, but it's an environment gap, not a code bug:
it needs the `pandoc` binary on PATH, which isn't installed on the
machine that failing run happened on. Not touched this session.

**Separately, the actual root cause of "TOKI keeps asking what I mean" /
"I said yes and it did nothing":** TOKI's replies were never actually
visible. All 4 popups (`_ReplyBubble`, the scheduled-commands panel, the
dictation stop panel, the typed-prompt box in `toki_desktop_mark.py`)
put a drop-shadow on their card but gave the outer layout zero margin
for the shadow to bleed into — `adjustSize()` then sized the real window
to exactly the card, with the shadow painting outside the window's own
pixel buffer. On a `WA_TranslucentBackground` window, Windows'
`UpdateLayeredWindowIndirect` compositor rejects a dirty rect bigger
than the window's own buffer, so the popup silently never painted at
all — every reply, clarifying question, and confirmation prompt was
computed correctly and then rendered into a window Windows refused to
display. Fixed by giving all 4 popups real outer margins (20px sides/
top, 26px bottom). Also fixed 6 failing `test_macro_recorder.py` tests
(same `_PYWINAUTO_AVAILABLE` caching gap as above, different call
sites), and added `ui_theme.py` — one shared palette/font-stack/card/
button recipe replacing 4 popups' worth of drifted hand-rolled CSS
(including a `'Inter'` font reference that was never actually bundled,
silently falling back to a different-metric generic sans on every real
machine).

## BETA 0.3.44 (checkpoint 4) — graph-based file organizer + explicit file-grouping (chat session, tested not guessed)

The fourth and biggest piece of the design discussion that also produced
checkpoint 2 (search rewrite) and checkpoint 3 (dictation + OCR fallback)
-- previously left for its own session, per plan. Two related but
DELIBERATELY DIFFERENT features landed together:

**`ORGANIZE_FILES_BY_TOPIC`** -- the graph-based organizer from the
original design doc. No LLM anywhere. New `file_graph/` package:

- `file_graph/metadata.py` -- cheap per-file evidence extraction:
  filename tokenization (camelCase + separator splitting, generic-word
  filtering, numbers kept), a bounded content hash (first 8KB, not the
  whole file), and text-token extraction limited to genuinely
  plain-text formats (.txt/.md/.json/.py/etc.) -- deliberately NOT
  pandoc/PDF-parsing per file, too slow to run inline on every request.
- `file_graph/scoring.py` -- six evidence types (filename similarity,
  extension match, shared-topic-group count, recent activity,
  content-hash duplicate, extracted-text overlap) combined as a
  weighted average over only the evidence actually present (an Images
  folder isn't penalized for having no text to compare), banded exactly
  per the design doc (>90 auto / 60-90 suggest / <60 skip), with
  human-readable explanation bullets in the same shape as the doc's own
  "8 related Physics documents" example.
- `file_graph/store.py` -- a dedicated Kùzu database (`file_graph_db/`,
  fully separate from `toki_graph_db`) persisting **learned weights**
  (nudged up/down on every accepted/rejected decision) and a decision
  log -- the "learns over time" half of the design doc. See that
  module's own docstring for an honest scope note: the LIVE file/folder
  evidence graph is rebuilt fresh in plain Python on every call (cheap,
  always-correct), NOT incrementally maintained in Kùzu -- only the
  durable, learned weights are.
- `file_graph/organizer.py` -- ties it together. The single most
  important safety property is structural, not a policy comment: this
  can ONLY move a file into a folder that ALREADY exists and ALREADY
  has related content -- there is no code path anywhere that invents a
  new folder name from a guessed topic.

**`GROUP_FILES_BY_EXTENSION`** -- a deliberately DIFFERENT, simpler
feature added after the user pointed out a real gap: "put all the pdfs
and json files in a new folder named rezero" is NOT a case for the
topic organizer above -- the user already said both the filter and the
destination explicitly, so there's nothing to infer and no confidence
banding needed. New `file_grouping.py` (kept out of `file_graph/`
entirely, zero shared code, so the two features can be reasoned about
independently): lists the extensions requested, creates the named
folder if it doesn't exist (unlike the topic organizer, this DOES
create a new folder -- the user named it themselves, nothing invented),
moves every matching loose file in, never overwrites (Explorer-style
"x (1).ext" de-duplication).

Both wired the same way: `apis.py` (`FileOrganizerAPI`/`FileGroupingAPI`)
-> `orchestrator.py`'s dispatcher -> `intents.py` -> `extractor.py` slot
extraction -> `tier_a_wcl_map.py` (required guard entry, both map to
`frozenset()` since neither shells out to a cmdlet -- both move files via
plain `shutil.move()`, not PowerShell) -> `graph_source_data/`.

**A real, previously-latent bug found and fixed along the way:**
`extractor.is_within_sandbox()` normalized the PATH being checked via
`ntpath.normpath()` but never normalized the sandbox ROOT strings
themselves. Invisible in production (real `get_sandbox_roots()` always
already returns pre-normalized Windows-style strings), but silently
broke the moment a test monkeypatched `get_sandbox_roots()` to a raw
POSIX-style `tmp_path` string -- exactly the pattern
`tests/test_file_index.py`'s own `sandbox` fixture already established
for `FileIndex`. Fixed by normalizing both sides the same way (a no-op
on already-normalized production roots). Ran the full existing suite
immediately after this fix, before writing anything else, to confirm
nothing relied on the old behavior -- it didn't.

**Scoring formula bug, also found via testing, not by inspection:** the
first version of `score_candidate()` normalized confidence only over
evidence types actually present, which meant a SINGLE evidence type
firing strongly -- most commonly `recent_activity`, since any two files
touched within the same test run (or, in production, two files a user
just downloaded minutes apart) will have near-identical mtimes --
could alone reach ~100% confidence, well into the auto-organize band,
on pure coincidence. Fixed with `_SOLO_EVIDENCE_CAP`: when only one
evidence type is present, confidence is capped per-type (85% for an
exact content duplicate -- real signal even alone; 35% for
`recent_activity` alone -- closer to noise), so corroboration from a
second, independent evidence type is always required before this ever
auto-moves a file. Caught by the real end-to-end tests in
`tests/test_file_graph.py`, not written into the design up front.

**Real-world routing regressions found and fixed -- three separate
rounds, worth documenting in full given how much this cost:**

1. First pass: added ~6 training phrasings per new intent. Manual sweep
   against neighboring intents caught "organize my desktop" colliding
   verbatim with an existing `SORT_FOLDER_BY_TYPE` phrasing, and "folder
   named X" phrasings dragging `MAKE_FOLDER`'s own "make a folder named
   school" from a confident hit down to an "ask" -- same TF-IDF
   corpus-wide fragility documented in checkpoint 2's own STATUS entry.
   Fixed by trimming phrasings and swapping "named" for "called" in the
   training data (the extraction regex still recognizes "named" as real
   user input either way -- confirmed by retesting).
2. Second pass: ran the FULL pytest suite (not just a manual spot
   check) and caught a THIRD collision the manual sweep had missed --
   "clean up my desktop" (one of the organizer's own training phrasings)
   diluted the word "clean" enough that `tests/test_orchestrator.py`'s
   own shadow-guard test for "clean temp files" dropped from a confident
   `LIST_FILES` classification to missing the graph entirely. Fixed by
   removing that one phrasing.
3. Third pass, the most thorough: generated all 194 real prompts from
   this repo's own `batch_test_prompts_v2.py` /
   `batch_test_prompts_v3{a,b,c,d}_*.py` files and diffed
   `GraphRouter.classify_or_ask()`'s output against the pre-change
   baseline for every single one (via `git stash`, not guesswork). Found
   several more candidate-quality regressions the manual sweep and the
   pytest suite had both missed -- "move photo.jpg to D drive" and "move
   it to D drive" degrading from confident `MOVE_ITEM` hits to an "ask",
   and multiple unrelated prompts ("close all chrome windows", "kill all
   notepad windows", an admin-mode prompt-injection test string) having
   their suggested candidate flip to the nonsensical
   `GROUP_FILES_BY_EXTENSION` purely because a training phrasing
   happened to share the word "all". Resolved by cutting BOTH new
   intents down to exactly ONE training phrasing each, re-running the
   full 194-prompt diff after every cut, until the diff against baseline
   was empty except for one incidental IMPROVEMENT (an unrelated chained
   command, "make a folder called Reports, then open it", went from an
   "ask" to a confident hit as a side effect).

**Net result of that process:** both new intents reliably hit with full
confidence for at least one natural phrasing each; most other
reasonable phrasings for them currently land as a safe "ask" with the
CORRECT candidate suggested (never a silent misroute) rather than a
confident hit -- a deliberate, tested trade-off, not an oversight. Given
how easily a few words shifted three-round-deep regressions elsewhere in
this session, adding more training phrasings for these two intents
should always be followed by the same full-194-prompt-diff process, not
just a check that the new phrasing itself now works.

**Tests:** `tests/test_file_graph.py` (42 tests -- real tmp_path
directories, real `shutil.move()` calls, an actual Kùzu database per
test, no PowerShell mocking needed since this feature never shells out),
`tests/test_file_grouping.py` (11 tests, same real-filesystem approach),
plus new coverage in `tests/test_apis.py` (7 tests) and
`tests/test_extractor.py` (13 tests). **Full suite: 909 passed, 1
skipped, 2 xfailed** (up from checkpoint 3's 834), confirmed against the
full 194-prompt real-world corpus with zero regressions as described
above.

**Honest scope limits, not glossed over:**
- No text extraction from binary document formats (PDF/DOCX) in this
  pass -- `extracted_text_overlap` evidence only ever fires for
  already-plain-text files. Filename/extension/timestamp/hash evidence
  still work fine for PDFs/DOCX, they just don't get the extra text
  signal. A pandoc-based fast-follow is possible but wasn't worth the
  per-file subprocess cost for this checkpoint.
- No explicit-reject learning loop -- only ACCEPTED moves (auto-band, or
  suggest-band explicitly included via "organize including suggestions")
  reinforce weights. A user who sees a suggestion and simply never
  re-runs with `include_suggestions` isn't reliably distinguishable from
  "hasn't decided yet" vs. "rejects this", so negative feedback isn't
  attempted here rather than guessing at intent.
- Confidence weights (`DEFAULT_WEIGHTS`) were hand-tuned against
  synthetic test fixtures in this sandbox, not against real user file
  collections (none available here) -- reasonable starting points, not
  a claim of being optimally tuned. That's the whole point of
  `file_graph/store.py` persisting and adjusting them over time.
- Never run against a real Windows filesystem or a real user's actual
  Desktop/Downloads clutter -- verified here via synthetic tmp_path
  fixtures only.

---

## BETA 0.3.44 (checkpoint 3) — continuous dictation ("start listening") + OCR fallback before asking (chat session, tested not guessed)

Two more pieces from the same design discussion as checkpoint 2's search
rewrite. Graph-based file organization (the fourth, biggest piece from
that discussion) is explicitly NOT started here — left for a separate
chat, per plan.

**"Start listening" continuous dictation:**

New `START_LISTENING`/`STOP_LISTENING` intents. Architecturally distinct
from every other voice path in this app: `HotkeyVoicePipeline` (Ctrl+K)
captures ONE utterance and routes it through orchestrator's normal
classify/dispatch; dictation captures utterance after utterance and types
each one DIRECTLY into a target field, with zero per-utterance
orchestrator round-trip — "whatever you say immediately starts getting
typed" only works if there's no classification step in between.

- `voice_pipeline.py`: new `DictationPipeline(QThread)` — same VAD-
  segmentation shape as `HotkeyVoicePipeline._record_and_transcribe()`
  (silence hangover, hard cap, no-speech timeout), but loops forever
  until `stop()` is called instead of returning after one utterance.
  Refactored `_load_whisper` into a shared module-level
  `_load_whisper_model()` so both pipelines load the model the same way.
- `app_control.py`: `_get_focused_text_element()` — walks the focused
  window's descendants (same `win.descendants()` pattern
  `resolve_target()` already uses) for whatever currently has
  `has_keyboard_focus()`, returns it only if its control type is a real
  text-entry type. `AppController.start_dictation()`/`stop_dictation()` —
  target resolution order: explicit description →
  `resolve_target()` (same as click/type_text) → already-focused text box
  (no question asked — this IS the "screen reads as just a text editor"
  case from the design discussion) → one-time click, same
  `teach_from_next_click()`-style flow `click()` already uses on a miss.
  **Interpretation call, not verified against the original intent:** the
  design doc's "the user types control clicks the stop button" was read
  as a plain click on a dedicated stop button, not a Ctrl+modifier click
  — the button only exists while dictation is active, so nothing else on
  screen competes for an accidental plain click.
- **Real race caught and fixed while building this, not shipped as-is:**
  first draft cleared `_active_dictation` via the pipeline's own
  `dictation_stopped` signal, which only fires once the background
  QThread actually finishes closing its audio stream (up to ~0.3s later).
  A "stop listening" VOICE/TYPED command (as opposed to the widget's stop
  button) would return its own success message while `_active_dictation`
  was still momentarily non-None — `main_widget.py`'s post-turn check
  would then wrongly leave the stop panel visible. Fixed: `stop_dictation()`
  now clears `_active_dictation` synchronously, itself, the moment it's
  called, regardless of caller. Pinned with
  `test_active_session_cleared_before_the_stopped_signal_fires`.
- `intents_app_control.py` / `extractor.py` / `orchestrator.py`:
  `START_LISTENING`/`STOP_LISTENING` wired as a dedicated pre-check
  (`looks_like_start_listening`/`looks_like_stop_listening`), bypassing
  Tier A's graph entirely — same reasoning already established for
  `start_seeing`/`stop_seeing`: "start"/"stop" are common enough words
  that graph vocabulary for them would distort `LAUNCH_APP`/
  `KILL_PROCESS` scoring. `target_description` is an OPTIONAL slot
  (same precedent as `GET_WEATHER`'s `city`) — always returns a dict,
  never forces `orchestrator.py`'s missing-slot follow-up question.
- `toki_desktop_mark.py` / `main_widget.py`: new `_DictationStopPanel`
  widget (small floating panel, one "⏹ Stop" button, same frameless/
  shadow styling as the existing `_CommandsPanel`) shown for the duration
  of a session. `_Bridge` gained `dictation_active`/
  `dictation_stop_clicked` signals. `main_widget.py` checks
  `orch.app_controller._active_dictation` right after every turn's
  dispatch (no separate "session started/stopped" signal exists, and
  none was needed — dictation state only ever changes as the direct
  result of a `START_LISTENING`/`STOP_LISTENING` turn).

**OCR fallback before asking the user:**

`resolve_target()` (shared by `click()`/`type_text()`/
`start_dictation()`'s explicit-target path) now tries one more thing
after BOTH the fuzzy UIA name match AND the taught-target memory recall
have already missed, before giving up and asking the user: an OCR pass
over the focused window's screenshot, via `Windows.Media.Ocr` (the
`winsdk` package) rather than Tesseract/PaddleOCR/etc — it's a WinRT API
already built into every Windows 10/11 install, satisfying the design
discussion's "one that can run on almost any machine" with zero extra
system binary or model download. This specifically catches the case the
discussion called out by name: Chrome and Copilot both render a lot of
on-screen text into canvas/web-component surfaces with no exposed UIA
name at all, even though the text is plainly visible.

- `_ocr_lines_from_bitmap(bbox)` — the genuinely unverifiable half (real
  WinRT screenshot + `OcrEngine.recognize_async` call). Returns `[]` on
  ANY failure (package missing, no display, engine unavailable,
  recognition error) — same fail-safe contract as everywhere else in this
  file. **NOT verified against real Windows in this session** — same
  caveat as `capture_identity_at_point()`/`_get_focused_text_element()`:
  logically reviewed against winsdk's documented API surface, not run
  against a live Windows box (none available from here).
  `winsdk>=1.0.0; sys_platform == 'win32'` added to `requirements.txt`
  as an optional dependency — missing it just means this fallback
  silently doesn't fire, same clean-degrade posture as
  `websocket-client`.
- `_ocr_find_text_on_screen(target_description, window)` — the testable
  half: scores every OCR'd line against `target_description` using the
  exact same `_score()`/`_MATCH_THRESHOLD` `resolve_target()` already
  uses for UIA names, converts the winning line's bounding box to screen
  coordinates. Split from the capture half specifically so this part
  could get real test coverage (mocking `_ocr_lines_from_bitmap`, same
  approach `TestResolveTarget`'s existing tests use to mock `_Desktop`
  rather than exercising real pywinauto).
- Wired into `resolve_target()` AFTER the memory-recall check, same
  ordering reasoning that check itself already used: never changes
  behavior for anything that already worked via UIA or memory, only
  recovers a case that would otherwise be a clean miss.

**Deliberately not touched:** `start_dictation()`'s no-target branch
doesn't try OCR — there's no `target_description` to search for in that
case (it's already resolved via focused-element detection or a direct
click), so OCR has nothing to match against there. OCR only ever helps
the explicit-target path.

**Tests:** `tests/test_app_control.py` — `TestGetFocusedTextElement` (5),
`TestDictation` (11), `TestOcrFindTextOnScreen` (5),
`TestResolveTargetOcrFallback` (3). `tests/test_voice_pipeline.py` —
`TestDictationCaptureOneUtterance` (5), `TestDictationStop` (1).
`tests/test_extractor.py` — `TestStartListeningTrigger` (5),
`TestStopListeningTrigger` (3), `TestStartListeningSlots` (3),
`TestStopListeningSlots` (1). One real bug caught in my own FIRST DRAFT
of these tests, not in the shipped code: pre-loading a fake audio frame
into the queue before calling `_capture_one_utterance()` doesn't work,
because that method drains any stale queue contents as its very first
step (same pattern `_record_and_transcribe()` already uses) — fixed by
feeding frames from a background thread/timer instead, matching how audio
actually arrives in the real callback-driven capture path. Full suite:
**850 passed, 1 skipped, 2 xfailed** (was 808 at checkpoint 2's own
final count — net +42 from these three new test classes plus the OCR/
race-condition additions).

## BETA 0.3.44 (checkpoint 2) — search rewritten: no API, no scraping, builds a URL and opens Chrome (chat session, tested not guessed)

Finalized architecture decision, implemented: `WebSearchAPI` (`apis.py`)
no longer calls Wikipedia's REST API or DuckDuckGo's Instant Answer API.
The old implementation answered "what is X" from a knowledge-graph
lookup, and only for topics with a Wikipedia-style abstract — for
ordinary conversational queries it just returned nothing. New pipeline:

```
query -> build a real search-engine URL -> open it in Chrome
```

Chrome is the search capability now, not TOKI. `SEARCH_WEB`'s intent
contract in `intents.py` is unchanged (`kind: api, api: websearch,
action: search`, single `query` slot) — this is a same-signature swap
inside `apis.py`, nothing in `orchestrator.py`'s dispatch, `intents.py`,
or `extractor.py`'s slot extraction had to change, so no existing
routing/classification test was at risk.

**What's in `WebSearchAPI` now:**
- `SEARCH_URLS` — a small dict of native search-URL templates: `web`
  (Google), `youtube`, `github`, `maps`. `search(query, site="web")`
  builds `SEARCH_URLS[site].format(q=quote_plus(query))`.
- `_open_in_chrome(url)` — checks the three real Chrome install paths
  directly (`%ProgramFiles%`, `%ProgramFiles(x86)%`, `%LocalAppData%`)
  since chrome.exe is not on PATH by default, then
  `Start-Process -FilePath <chrome> -ArgumentList '<url>'`. Fails open:
  if none of those paths exist, falls back to bare `Start-Process
  '<url>'`, which opens whatever the user's actual default browser is —
  same fail-open posture as `AppController.launch_app()`.
- Same `_escape_ps_slot`-style single-quote doubling as
  `app_control.py` (own copy, since this builds its own PowerShell
  string outside the centralized `"powershell"`-kind escaping path,
  same reason `AppController.launch_app()` needed its own copy).

**Deliberately NOT done in this checkpoint:** auto-detecting `site`
(youtube/github/maps) from the query's free text. The design doc calls
for specialized searches to use their native search UIs, and
`SEARCH_URLS`/the `site` param are ready for that — but guessing
"youtube" out of arbitrary text (e.g. "search for youtube alternatives")
risks exactly the invented-structure failure mode this codebase's
regex-only slot extraction exists to avoid everywhere else. Wiring up
real per-site intents (`SEARCH_YOUTUBE` etc., extracted the same
never-guess way `extractor.py` extracts everything else) is a clean,
isolated fast-follow whenever it's wanted — `site=` param is already
there for it.

**Also not done:** a widget status indicator ("🔎 Searching `<query>`")
before Chrome opens. Checked `mark_renderer.py` first — `MoodMarkWidget`
is a mood-ring animation only, no text-overlay mechanism exists at all
yet. Bolting a one-off text label onto an animation-only widget wasn't
worth doing carelessly; this is a real (small) UI feature on its own,
not a one-line addition to this search change.

**Tests:** removed the now-dead Wikipedia-matching helpers
(`_best_matching_sentence`, `_stem`, `_question_keywords`, and their
backing regexes/stopword set) along with the code that used them — they
had no callers left. Added `TestWebSearchAPI` to `tests/test_apis.py`
(6 new tests: empty query, Google URL build, YouTube-site URL build,
unknown-site fallback to web, single-quote query doesn't break the
PowerShell command — same bug class as the "Assassin's Creed" fix in
`app_control.py` — and Popen failure returns the `"Search failed"`
prefix). Every test mocks `subprocess.Popen`; none make a real network
call or actually launch Chrome. Full suite: **808 passed, 1 skipped, 2
xfailed** (was 750 passed at last checkpoint — net +58 from other
in-flight work plus these 6).

**Remaining from the same design doc, explicitly deferred to other
sessions per MrClassic's plan** (not started, not designed further than
the chat discussion): "start listening" continuous-dictation intent,
fast on-screen OCR pre-check (`Windows.Media.Ocr`) before UI-Automation
click/type falls back to asking the user, and the graph-based file
organizer (Kuzu KG over the filesystem, confidence-banded auto-organize).

## BETA 0.3.44 — video download (yt-dlp) + media conversion_engine backend integrated, plus a CDP "actually playing" upgrade (chat session, tested not guessed)

Integrated a prepared patch set (`video_downloader/` + `conversion_engine/backends/media_backend.py`
+ supporting wiring across `apis.py`, `intents.py`, `orchestrator.py`,
`extractor.py`, `graph_source_data/`, `tier_a_wcl_map.py`) that adds two
new Tier A intents and merges cleanly against this exact checkout with
zero conflicts:

- **`DOWNLOAD_PLAYING_VIDEO`** — "download this video" / "download what
  I'm watching". Resolves its own URL at dispatch time (see below),
  never trusts anything the extractor pulled from the user's phrasing,
  since there's nothing in the phrasing that WOULD contain the URL.
- **`DOWNLOAD_VIDEO_URL`** — "download this link" / an explicit URL the
  user typed or pasted.

Both wrap **yt-dlp** (the actively-maintained fork of youtube-dl) as a
real Python library import, never a subprocess. Downloads land in a
sandboxed `Desktop/TOKI Downloads` folder by default, same sandbox
posture as every other file-producing path in this app. Audio-only
extraction and merging separately-served video+audio streams both need
the `ffmpeg` binary on PATH — checked explicitly at call time with a
named, actionable error, same convention `document_backend.py` already
uses for pandoc.

`conversion_engine` also picked up **audio/video format support**
(`media_backend.py`) in this same patch — `compress_file()` now routes
audio/video sources to it instead of falling through to the generic
zip-archive fallback, and `supported_formats()` reports the new
`audio`/`video` format lists.

### The "how do we find the URL" problem, and the trade-off worth
### flagging honestly

`DOWNLOAD_PLAYING_VIDEO` needs SOME way to know what the user means by
"this video" without them pasting a link. The patch's original approach
(`video_downloader/now_playing.py`) reads the **focused browser
window's address bar** via UI Automation — reusing `app_control.py`'s
existing focused-window lookup, walking the element tree for an
Edit/ComboBox control whose accessible name matches a curated list of
address-bar labels across Chrome/Edge/Firefox-family browsers, and
reading its value. This works, but has two known limits, both flagged
up front rather than glossed over:

1. The address-bar name list is curated, not exhaustive — a mismatch
   always means "found nothing" (safe), never "found the wrong thing",
   but it does mean some Chromium forks or future UI-string changes
   could silently miss.
2. More fundamentally: it answers "what page is focused right now", not
   "which embedded player is actually playing" — a background tab with
   a video still playing while the user's tabbed away to something else
   won't be detected at all.

**What was added this session to narrow gap #2:**
`video_downloader/cdp_now_playing.py` — a new, purely additive strategy
tried *before* the address-bar read. If the browser happens to be
running with Chrome DevTools Protocol enabled
(`--remote-debugging-port`, overridable via `TOKI_CHROME_CDP_PORT`), this
asks each open tab directly, over CDP, "do you have a `<video>` element
that's actually unpaused and has buffered playable data right now" —
the same protocol Chrome's own DevTools panel, Playwright, and
Selenium's CDP mode all use — and returns the URL of the first tab that
says yes. This is a real answer to the *actual* question ("what's
playing"), not a proxy for it.

This is deliberately kept as an **opt-in bonus path, not a replacement**:
- Most people don't run their browser with a debug port open day to
  day, so most of the time this correctly finds nothing and falls
  through to the address-bar strategy — the address-bar reader stays
  the primary real-world path.
- It never launches, relaunches, or reconfigures the user's browser —
  no injecting the debug flag, no killing the existing process. That
  would close the user's actual tabs/session, a far bigger surprise
  than "the download command didn't work this time".
- Needs the OPTIONAL `websocket-client` package (commented out in
  `requirements.txt`, same "optional, clear degrade" convention as
  `pyyaml`/`toml` above it) for the per-tab websocket RPC; the HTTP tab
  list step is stdlib-only. Missing the package just means this probe
  is silently skipped, never an error.
- Every result is checked twice: real http(s) URL AND an actually-
  playing `<video>` (`readyState > 2`, not just present-but-paused).

`now_playing.get_now_playing_url()` now tries CDP first, falls back to
the address-bar read on any miss or failure — see that module's
docstring for the exact call order. `now_playing.py`'s original UIA
logic and its existing tests are untouched; only the top-level function
changed shape, and its 3 pre-existing tests were adjusted to isolate the
address-bar strategy from the new CDP call ahead of it (rather than
depend on CDP genuinely being unreachable in whatever environment the
suite runs in).

**New tests:** `tests/test_cdp_now_playing.py` (24 tests, HTTP+websocket
both faked at the boundary, no real socket ever opened) +
`tests/test_video_downloader.py` gained 2 new cases covering the
CDP-first/address-bar-fallback interaction. Existing yt-dlp/ffmpeg-gating
tests untouched and still pass.

### Real-world intent routing — tested, one regression found and reverted

Rebuilt `toki_graph_db` from `graph_source_data/` (now includes this
patch's `DOWNLOAD_PLAYING_VIDEO`/`DOWNLOAD_VIDEO_URL` phrasings) and ran
`GraphRouter.classify_or_ask()` directly against ~20 natural real-world
phrasings for both new intents, plus a spot-check against unrelated
existing intents (`TAKE_SCREENSHOT`, `LOCK_WORKSTATION`,
`COMPRESS_SELECTED_FILE`, `LAUNCH_APP`, etc.) to confirm the new intents
don't collide with anything already shipped. Result: the shipped
phrasings correctly resolve confident, correct intents for the common
cases ("download this video", "download the video I'm watching",
"i want to download this video", "download this link") and safely fall
to a clarifying **ask** (never a wrong guess) for genuinely ambiguous
ones ("download this as an mp3", "download this url") — no misroutes
found in the shipped phrasing set.

Also **tried** adding a handful of extra phrasings (more mp3/audio-only
variants) to convert some of those "ask"s into confident hits. This
introduced a real regression, caught by re-running the same test sweep
after rebuilding the graph: "can you download this video for me" and
"i want to download this video" — both correctly `DOWNLOAD_PLAYING_VIDEO`
before — flipped to `DOWNLOAD_VIDEO_URL`. Root cause: the router's
TF-IDF scoring is corpus-wide, so adding documents to one intent shifts
the IDF weights of shared words ("download", "video") for every other
intent, not just the one being edited — a phrasing addition that looks
locally safe can silently move decision boundaries elsewhere. Reverted
those additions back to exactly the patch's original phrasing set
(confirmed via `git apply` of just that hunk, byte-identical) rather
than ship a "fix" that traded one gap for a real regression. Flagging
this here as a genuine constraint on this router design, not something
resolved this session: **any future phrasing addition to
`tier_a_phrasings.py` needs a broad before/after regression sweep, not
just a check that the new phrasing itself now works.**

**Full suite: 786 passed, 1 skipped, 2 xfailed** (up from the pre-session
750; the delta is the new video_downloader/CDP test files plus the
existing conversion_engine/apis tests the patch itself added). Two test
files were excluded from this sandbox's run for unrelated, pre-existing
reasons confirmed via a clean clone of the prior commit (not caused by
this session's changes): `tests/test_batch_test_live.py` (needs a live
Ollama instance) and `tests/test_desktop_mark_dragdrop.py` (crashes any
`QApplication` fixture in this headless Linux sandbox — no display
server, not a code bug; unaffected on the real Windows target).

**Still open / needs your machine, not glossed over:**
- `now_playing.py`'s address-bar reading and the new CDP probe are both
  UI-Automation/network-dependent — verified here at the unit level
  against stubs/fakes only, never against a real Chrome window (this
  sandbox is Linux, no display, no pywinauto).
- yt-dlp's actual network download path (`download_video()`'s
  `ydl.extract_info(..., download=True)` call) is untested against a
  real video — verified here only up to URL validation and the ffmpeg
  presence gate, both via mocks.

---

## BETA 0.3.43 — 4 real bugs from an independent review, all fixed + tested (chat session)

Another chat session reviewed the codebase fresh and flagged 4 issues not
in this file's existing tracked list. Verified each against this exact
codebase before touching anything (all 4 confirmed real, not
exaggerated), fixed all 4, and added tests that would have caught them —
none of the 4 had test coverage before, which is exactly how they shipped
unnoticed.

1. **Resize direction was silently ignored.** `extractor.py`'s
   `_extract_resize_params()` only ever extracted a magnitude from a
   percentage, never a direction — "make this image 50% bigger" and
   "shrink this by 50%" both produced `{"scale": "0.5"}` (both shrink).
   A `_SHRINK_WORDS_RE` regex existed but was never referenced anywhere —
   the enlarge-vs-shrink branch was started and never finished. Fixed:
   added `_ENLARGE_WORDS_RE`, enlarge phrasing now produces
   `1 + pct/100` (grow) instead of `pct/100` (shrink); shrink wording and
   direction-less bare percentages keep the original shrink-fraction
   behavior (matches `resize_file()`'s own no-args default). New:
   `tests/test_resize_extraction.py`, 7 tests.

2. **`text_backend.py` was silently mislabeling files it couldn't really
   convert.** json→xml and csv→yaml (any pair without a real transform)
   fell into an `else` branch that wrote the SOURCE's raw content under
   the TARGET's extension — "convert data.json to data.xml" produced a
   file named `.xml` that was actually JSON. This directly violated the
   module's own stated design ("rendered readably, not byte-copied") and
   `registry.py`'s promise that a miss is a clear "not supported yet",
   never a silent wrong conversion. Fixed: those branches now raise the
   existing `conversion_engine.registry.UnsupportedFormatError` instead
   of writing anything. Confirmed the plain-text↔plain-text pairs
   (txt/md/log/yaml/yml, none of which have real structure relative to
   each other) still correctly do a byte copy — that behavior was
   correct, only the *other* pairs' fallthrough into the same code path
   was the bug. New tests in `tests/test_conversion_engine.py`
   (`TestTextBackendUnsupportedPairs`, 4 tests).

3. **Dead `PyQt6-WebEngine` dependency.** `requirements.txt`'s comment
   for it referenced `mood_mark.py`, which no longer exists, and claimed
   `toki_desktop_mark.py` still uses `QWebEngineView`, which it hasn't
   since the 0.3.39 `mark_renderer.py` rewrite (confirmed via grep: zero
   live imports of `QWebEngineView` anywhere in the tree, only historical
   comments). Removed the dependency entirely — saves every fresh install
   from pulling in a Chromium-backed Qt module for nothing. While
   checking this, found `mark_visual.py` itself is now fully dead code
   too (nothing imports it anymore — `mark_renderer.py` transcribed its
   SVG/mood data directly instead of calling into it). Left the file in
   place and fixed its misleading docstring rather than deleting it
   unilaterally — safe to delete once you confirm you don't want it
   around for reference.

4. **Zip-slip in `archive_backend.extract()`.** `zf.extractall(dest)` had
   no member-path sanitization — a zip containing `../`-style entries
   could write files outside `dest`. Low risk for a tool acting on files
   the user themselves already selected, but a real gap if TOKI ever
   extracts anything sourced from outside the user's direct control.
   Fixed: every archive member's resolved path is now checked against
   `dest` before extraction; a member that would land outside raises
   `ValueError` and nothing is extracted. New tests in
   `tests/test_conversion_engine.py` (`TestArchiveZipSlip`, 2 tests).

All 4 fixes verified two ways: via the new unit tests, AND end-to-end
through the real user-facing `FileConvertAPI` methods in `apis.py`
(`convert_selected`/`resize_selected`/`extract_selected`) — confirmed
each now returns a clean, actionable message
("Couldn't convert that file: Can't convert json to xml...", "Couldn't
extract that file: Refusing to extract...") rather than either a
traceback or silent wrong output. No wrapper changes were needed in
`apis.py` — it already wraps every conversion_engine call in a broad
`except Exception`, so the new exceptions flow straight into the
existing error-message convention.

Full suite: **750 passed, 1 skipped, 2 xfailed** (up from 737), zero
regressions.

---

## BETA 0.3.42 — closed out all three 0.3.41 loose ends (chat session)

All three items 0.3.41 flagged as "still needed" are now actually done,
not just documented:

1. **Graph rebuild.** Turns out `wcl_kg/rebuild_graph.py` (what 0.3.41's
   own note pointed at) was the WRONG script — it rebuilds
   `windows_commands_db` (the WCL/Tier-B resolver graph), unrelated to
   Tier A phrasings. The real fix needed `migrate_to_kuzu.py`, which
   builds `toki_graph_db` from `graph_source_data/tier_a_commands.json`
   + `tier_a_phrasings.py`. Running THAT surfaced a second, real bug:
   0.3.41 added phrasings to `tier_a_phrasings.py` for the four new
   intents but never added matching entries to `tier_a_commands.json`
   (the actual source-of-truth Command-node list migrate_to_kuzu.py
   reads) — so the four new intents had zero Command nodes and zero
   presence in the tf-idf scoring index. Routing didn't just miss on
   these phrasings, it **misrouted** to unrelated existing intents
   ("convert this file" → `READ_FILE`, "zip this up" → `VOLUME_UP`,
   etc.) because their generic words (file/this) still scored against
   other commands' vectors. Added the 4 missing Command entries to
   `tier_a_commands.json` (66 Tier A commands now, was 62), rebuilt the
   graph. Verified: every seed phrasing for all 4 new intents now routes
   to the correct intent; existing nearby intents (READ_FILE,
   MAKE_FOLDER, VOLUME_UP/DOWN) still route correctly too (no
   regression). Novel/paraphrased wording not in the seed corpus
   (e.g. "convert this to a docx") safely falls to ASK, not a misroute —
   same in-sample-only caveat that already applies to every other Tier A
   intent per item 3 under "Where it still lacks" above.

2. **Drag-drop.** Wrote `tests/test_desktop_mark_dragdrop.py` —
   real `QDragEnterEvent`/`QDropEvent` objects (not mocks), fired at a
   real `DesktopMark` instance, running headless
   (`QT_QPA_PLATFORM=offscreen`). This is not a substitute for a real
   Windows/PyQt6 drag from Explorer, but it does exercise the actual
   `dragEnterEvent`/`dropEvent` methods with the same event shape Qt
   itself builds from a real OS drop, wired to the real
   `selection_context.py` singleton. 8 new tests, all passing: single-
   file accept, multi-file/non-local reject, real file → selection set +
   reply text, nonexistent path → failure reply, folder → rejected,
   multi-file drop behavior documented. Two real PyQt6 gotchas found and
   fixed in the test harness itself along the way (not TOKI bugs): (a)
   the QMimeData passed into a hand-built QDropEvent must be kept alive
   by the caller or it segfaults on `event.mimeData()` later; (b)
   `QDragEnterEvent`'s constructor wants an integer `QPoint`, but
   `QDropEvent`'s wants a `QPointF` — an actual inconsistency between the
   two PyQt6 classes.

3. **Pandoc bundling.** Resolved the open question rather than leaving
   it flagged: `document_backend.py` now checks a bundled binary
   location (`bin/pandoc/pandoc.exe` next to the app) before falling
   back to system PATH. This means whenever the installer is built out,
   bundling pandoc is just "drop the exe in `bin/pandoc/`" — zero further
   code change needed. PATH fallback keeps today's dev/test flow working
   unchanged. `tests/test_document_backend.py` (8 tests) verifies this
   against a REAL pandoc binary (available in this session's sandbox) —
   actual md→docx conversion, docx→html round trip producing real
   content, overwrite behavior, and error paths (missing pandoc, bad
   input, pdf-as-source) — not stubbed. Noted pandoc's license
   (GPL-2.0-or-later) in the module docstring since that's relevant to
   redistributing the binary, with an explicit caveat that's an
   engineering note, not legal advice.

Full suite: **737 passed, 1 skipped, 2 xfailed** (up from 715 passed at
the start of this session — +22 from the new drag-drop, document-backend,
and pre-existing test counts combined), zero regressions.

---

## BETA 0.3.41 — file-conversion engine + drag-drop selection context

**Session summary:** built the first version of the format-conversion
feature — "select a file, tell TOKI what to do with it" — as two new
pieces plus wiring through every existing layer (intents, extractor,
orchestrator dispatch, graph phrasings, the desktop overlay). Verified
with a new 23-test pytest suite (all passing) AND a full run of the
existing 714-test suite against the patched tree (715 passed, 1 skipped,
2 xfailed, zero regressions) — the one real gap the existing suite caught
(`test_map_covers_every_tier_a_intent`) was fixed properly, not skipped.
NOT yet verified: the Kuzu graph rebuild (see "still needed" below) or
anything against a real Windows machine/PyQt6 drag-drop, since this
session had neither available.

**New: `selection_context.py`.** A third, deliberately separate "what
does 'this' refer to" store alongside `target_memory.py` (UI element
clicks) and `orchestrator._last_touched` (files TOKI itself wrote) — this
one tracks the file the USER most recently pointed at from outside TOKI.
In-memory only, 10-minute TTL, single-slot (one file at a time, matching
this feature's own framing: "this file you're pointing at"). Fed by a new
`dragEnterEvent`/`dropEvent` pair on `toki_desktop_mark.py`'s
`DesktopMark` widget — drag a file onto the overlay, TOKI confirms what
got selected via `show_reply()`.

**New: `conversion_engine/` package.** Deterministic (extension,
operation) → backend routing table (`registry.py`, same "no guessing"
philosophy as `tier_a_wcl_map.py`), with four backends:
  - `image_backend.py` — Pillow: convert/resize/compress (png/jpg/webp/
    bmp/gif/tiff/ico). "Shrink this image" with no number defaults to a
    stated 50% scale. Never overwrites the original unless the caller
    explicitly says so — writes `_resized`/`_compressed` alongside it.
  - `text_backend.py` — stdlib only: json/csv/tsv/xml/txt/md/log,
    including structural round-trips (json↔csv preserves columns, not
    just a byte copy under a new extension). yaml output needs PyYAML,
    NOT currently a hard dependency — raises a specific, actionable error
    if missing rather than a bare ImportError.
  - `document_backend.py` — docx/pdf/html/rtf/odt via `pandoc` on PATH.
    Deliberately thin: no attempt to hand-roll layout-aware conversion in
    pure Python. Raises a clear "pandoc isn't installed" error if it's
    missing. Converting FROM pdf is explicitly NOT supported yet (needs a
    different tool than pandoc to reflow reliably) — raises
    `NotImplementedError` rather than producing garbled output.
  - `archive_backend.py` — stdlib `zipfile`: compress (file or whole
    folder) / extract. zip-only for now; rar/7z would need a new
    dependency, deliberately deferred.

**New intents:** `CONVERT_SELECTED_FILE`, `RESIZE_SELECTED_FILE`,
`COMPRESS_SELECTED_FILE`, `EXTRACT_SELECTED_FILE` — all `kind="api"`,
dispatched through a new `FileConvertAPI` class in `apis.py` (registered
in `orchestrator.py`'s `ToolDispatcher._apis`, same pattern as
`WeatherAPI`/`WebSearchAPI`). Every method resolves the CURRENT selection
itself at call time (not a slot passed in), so "shrink this image" always
acts on whatever's selected right now even across turns. `extractor.py`
gained format-word extraction (`_extract_target_format`, closed
vocabulary — text/json/csv/pdf/docx/png/jpg/etc, not free-text guessing),
resize-parameter extraction (explicit `WxH`, a percentage, or the stated
default), and a `MISSING_SLOT_QUESTIONS` entry so "convert this" with no
named format gets asked, not guessed.

**Added to `tier_a_wcl_map.py`:** all four new intents mapped to
`frozenset()` — same treatment as `GET_WEATHER`/`SEARCH_WEB`, since these
are `kind="api"` and never touch a PowerShell cmdlet at all.

**Phrasings added** to `graph_source_data/tier_a_phrasings.py` for
graph_router.py matching (imperative + soft-ask forms per intent, same
convention as every other Tier A command in that file).

**Still needed before this is fully live (explicitly not done this
session):**
  1. **Run `wcl_kg/rebuild_graph.py`** — the new phrasings are only in the
     seed data; the live Kuzu DB (`toki_graph_db/`) won't actually match
     them until the graph is rebuilt. Nothing routes to these four
     intents yet without that step.
  2. **Real-hardware check of the drag-drop handlers** — `setAcceptDrops`/
     `dragEnterEvent`/`dropEvent` are standard Qt and follow the same
     patterns as every other event handler already in
     `toki_desktop_mark.py`, but this session had no real Windows/PyQt6
     environment to actually drag a file onto the overlay and watch it
     work.
  3. **Installer note carried forward:** `document_backend.py` needs
     `pandoc` on PATH. Not bundled — the planned Inno Setup installer
     should either ship a portable `pandoc.exe` or prompt for it, same
     open question flagged for ffmpeg/voice-pipeline dependencies
     elsewhere in this file.
  4. Audio/video conversion (ffmpeg) was scoped out of this pass
     entirely — heaviest dependency, biggest install-size/licensing
     question, deliberately deferred rather than half-built.

---

## BETA 0.3.40 — hotkey/hover fixes, routing regression fixes, App Control test coverage, click-to-teach, "start seeing" macro recording


**Session summary:** started from a bug-hunt request (testing the Testing
Edition's Ctrl+K hotkey, the desktop-mark hover, and a handful of routing
misses), then extended into two real new features: click-to-teach (TOKI
asks the user to click a not-found target once, then remembers it) and
"start seeing" macro recording (records raw physical input by hand, replays
it later on a single made-up wake word). Every fix and every new module
below was verified against this repo's real test suite and/or a real
`GraphRouter`/`WindowsAIAssistant()` instance in this session — nothing
here is "should work," everything has either a passing test or a logged
live repro. The one thing NOT verified: any of it against a real Windows
machine/real pywinauto/real pynput, since this session had none available.
Flagged individually below wherever that matters.

---

**Bug 1 — Ctrl+K hotkey never fired, at all, on any machine.**
`toki_desktop_mark.py`'s `_run_listener()` matched on `key.char == 'k'`
while Ctrl was held. On Windows, pynput reports the *control character*
Windows itself generates for Ctrl+letter combos (Ctrl+K → `'\x0b'`, not
`'k'`) — so that comparison was false every single time, structurally, not
intermittently. This is also why mic access looked broken: the hotkey
callback that opens the mic never ran. Fixed by matching on the Windows
virtual-key code (`vk == 0x4B`) instead, which is unaffected by modifier
state.

**Bug 2 — hover felt "too quick"/twitchy.** `enterEvent` expanded the
notch instantly off a 6px-tall idle hit-region at the very top of the
screen — any incidental brush past the top edge (reaching for a browser
tab, etc.) triggered a full expand+panel with zero debounce. Added a
`HOVER_INTENT_MS = 180` dwell timer: `enterEvent` now starts a timer
instead of expanding immediately, and `leaveEvent` cancels it if the mouse
didn't linger. Existing 200ms panel-close grace timer untouched.

**Routing bugs found via a novel-phrasing test harness (`routing_test.py`,
not part of the pytest suite — ad-hoc, out-of-sample):** `"get rid of the
file called X"` misrouted to `FIND_FILES` instead of `DELETE_ITEM` (`"rid"`
wasn't in `synonyms.py`'s map at all). `"which files mention X"` misrouted
to `LIST_FILES` instead of `FIND_FILES_BY_CONTENT` (`"mention"` likewise
missing). First fix attempt for the second one mapped `"mention"` to the
generic `"find"` synonym shared across four FIND_* commands — too broad,
it just shifted the misroute to a different wrong command
(`FIND_DUPLICATE_FILES`). Fixed by mapping to `"containing"` instead,
`FIND_FILES_BY_CONTENT`'s own word, unique to it in the whole phrasing
corpus. Both fixes verified against the full 604→631-test suite, zero
regressions.

**App Control (`app_control.py`) had ZERO test coverage on its actual
click/type mechanism** — all 14 existing tests covered `LAUNCH_APP` only
(escaping, fuzzy app matching, cache handling); `resolve_target()`,
`click()`, `type_text()` had never been exercised by a single test despite
being wired end-to-end in `orchestrator.py`/`extractor.py`. Probed the real
logic against a mocked pywinauto `Desktop`/element tree — non-clickable
elements shadowing a real target by name, invisible/disabled elements,
zero-match fail-safe, a raw COM exception mid-walk, pywinauto missing
entirely, single/double/right-click dispatch, `{}/+/^/%/~/()` escaping —
everything held up exactly as documented. Added 27 new tests
(`TestResolveTarget`, `TestClickAndTypeDispatch`) pinning this logic
permanently. Still not verified against a real Windows UI Automation tree
(messier real element trees, elements that throw on property access) —
that's a real-Windows-only gap, not something closeable from this
environment.

---

### New feature: click-to-teach (`target_memory.py` + `app_control.py`)

When `resolve_target()` cleanly misses (not an error — genuinely no
confident match) on a click, TOKI now offers to learn it: asks the user to
click the target themselves once, captures whatever's actually under the
cursor via UI Automation (`capture_identity_at_point()`, using pywinauto's
`Desktop(backend="uia").from_point()`), and remembers `{name, control_type,
class_name}` against `(window title, target description)` in a flat JSON
store (`learned_targets.json`, next to the source — same "flat file, not a
database" choice as everywhere small in this app). Next miss on the same
description in the same window checks memory first — exact identity match,
never fuzzy, before falling back to the existing fail-safe "couldn't find"
path. Keyed by window TITLE, not process name (no pywin32/psutil dependency
existed in this project and adding one felt like scope creep for a feature
this small) — stated limitation: browser windows change title per tab, so
a teach on one page won't carry to a different page of the same site.

`capture_identity_at_point()` specifically is **logically reviewed, not
live-tested** — `Desktop.from_point()` is pywinauto's documented mechanism
for "what's under the cursor," but nothing in this session's environment
could run it against a real UI Automation tree. Fails safe either way (any
exception → "couldn't capture," never a fabricated identity), but this is
the one function in this whole feature that most needs a real-Windows pass
before being called genuinely done.

New tests: `tests/test_target_memory.py` (10 tests — round-trip, case/
whitespace normalization, per-window independence, corrupt-file recovery,
write-failure doesn't raise).

### New feature: "start seeing" macro recording (`macro_recorder.py`)

Records raw physical input (mouse clicks + key presses) after the user
says "start seeing" — deliberately NOT a TOKI-command replay (design
decision this session: recording actual TOKI intents instead was
considered and rejected once it became clear the actual ask was replaying
manual actions TOKI itself never decided to take, e.g. "open Steam and
Discord and start a stream by hand"). Two safety properties, both
deliberate, both settled this session:

1. **No blind coordinate replay.** Every recorded click also captures the
   UI Automation identity of whatever was under the cursor via the same
   `capture_identity_at_point()` click-to-teach uses. At replay time,
   `MacroPlayer` re-checks the element currently at that coordinate against
   the recorded identity before clicking — a mismatch **aborts the whole
   macro** and names the failing step, never clicks blind. A step recorded
   with no identity (capture failed live, e.g. click landed on empty
   desktop) degrades to coordinate-only replay — a stated, accepted gap,
   not a silent one.
2. **Trigger safety via one made-up word, exact match, hotkey-gated.** A
   macro fires only when the ENTIRE utterance is exactly its one-word name
   — enforced at the orchestrator pre-check level AND at save time
   (`AppController.stop_seeing_and_save()` rejects multi-word names
   outright, since a multi-word name could never be triggered by the
   single-bare-word check and would otherwise silently save something
   permanently untriggerable — caught live in this session before shipping
   it). Combined with the existing Ctrl+K-gated voice pipeline (no ambient
   listening path anywhere in this app), there's no path for accidental
   misfire.

**Regression found and fixed mid-session:** first attempt registered
`START_SEEING`/`STOP_SEEING` as ordinary `graph_router.py` Tier A intents
with their own phrasings. This broke `LAUNCH_APP`: `"start notepad"`
started scoring 0.631 for `START_SEEING` instead of routing to `LAUNCH_APP`
— confirmed live, not theoretical. Root cause: `"start"`/`"stop"` are
heavily load-bearing words for `LAUNCH_APP`/`KILL_PROCESS` already: adding
*any* new document containing them to the TF-IDF corpus permanently shifts
those words' IDF and dilutes `LAUNCH_APP`'s own vector share on exactly the
words a bare `"start notepad"` query has to key on. Diluting
`START_SEEING`'s own phrasing set didn't fix it — it just moved the
IDF-shift side effect elsewhere. **Reverted from the graph entirely** and
rebuilt `toki_graph_db` back to its original 62-command baseline (confirmed
byte-behavior-identical via the full 631-test pytest suite). Replaced with
a dedicated regex pre-check (`extractor.py`'s `looks_like_start_seeing()` /
`looks_like_stop_seeing()`), run in `orchestrator.py` before graph
classification — same established pattern this codebase already uses for
the scheduling/conditional pre-check, and for the identical reason
(`looks_like_cancel_scheduled()`'s own comment already documents avoiding
`"stop"`/`"close"`/`"end"` for this exact class of collision). A dedicated
regex has zero shared vocabulary with the graph, so it structurally can't
cause this bug again.

**Second bug found in the same pass:** `orchestrator.py`'s `app_control`
dispatch hardcoded `"response"` (the text actually shown on screen) to
`"Done."` regardless of what the action returned — pre-existing behavior
across every `app_control` action, not new. Harmless for actions where
"it worked or it didn't" is the whole story, but it would have silently
broken this feature's whole UX: the "click it yourself, I'll remember it"
message would never have reached the screen, leaving the user staring at
"Done." while the code blocked for up to 15s waiting for a click nobody
was told to make. Fixed to surface the real result string whenever there
is one; strictly more informative for every existing `app_control` action
too. No test in the suite asserted on the literal `"Done."` text, confirmed
before making this change.

New tests: `tests/test_macro_recorder.py` (16 tests — storage round-trip,
identity-match-clicks-normally, identity-mismatch-aborts-without-clicking,
missing-identity-degrades-to-coordinate-only, right-click, key-press
escaping, special-key mapping, pywinauto-unavailable); `tests/
test_extractor.py` additions (trigger-phrase positive/negative cases
including the two confirmed false positives, `TestStartStopSeeingNotInGraph`
pinning the graph-collision regression so it can't silently come back);
`tests/test_orchestrator.py` additions (11 tests — full dispatch wiring
through a real `WindowsAIAssistant()`, multi-word-name rejection, bare-word
trigger positive/negative, click-to-teach flow, the `"Done."` bug fix).

**Full suite: 682 passed, 1 skipped, 2 xfailed** (up from 604 at session
start). Nothing here has touched real Windows/pywinauto/pynput — that
remains the one honest gap before calling any of this genuinely done rather
than logically done.

## BETA 0.3.39 — desktop mark rendered nothing on Windows (QWebEngineView + WA_TranslucentBackground); replaced with native QPainter widget

**Bug (user-reported, reproduced on real Windows hardware, not guessed):**
after a clean venv312 install and `python main.py` running with no errors,
the desktop mark never appeared — not the idle 6px notch, not the 128px
active state after Ctrl+K, nothing, on any monitor. No exception, no
console output pointing at it.

**Root cause, confirmed by isolation test:** `toki_desktop_mark.py` embedded
a `QWebEngineView` (rendering `mark_visual.py`'s SVG/CSS/JS mark) inside a
top-level widget with `WA_TranslucentBackground` set. QWebEngineView's
Chromium compositor does not paint correctly inside a translucent Qt
window on Windows — a known Qt/Chromium limitation. Swapping the view for
a plain `QLabel` (the file's existing fallback path) made a solid shape
render immediately, confirming translucency + Chromium was the failure,
not geometry, not the hotkey, not anything else in the startup pipeline.

**Fix:** new `mark_renderer.py` — `MoodMarkWidget`, a `QPainter`-based
widget that reimplements the same design (7 ring layers, mood colour/scale/
timing configs, pulsing core) with no Chromium dependency at all, so it
composites correctly with translucency. `toki_desktop_mark.py`'s
`QWebEngineView`/`_WE`/`_MARK_HTML` branch and all 6 `self._js(...)` call
sites (`setMood`, `playStartup`) removed and replaced with direct method
calls (`self._view.set_mood(...)`, `self._view.play_startup()`).
`mark_visual.py` is now unused dead code (kept in the repo for now, not
deleted this pass — flag for a future cleanup, same as `app.py`/
`mood_mark.py` were previously).

Verified (not just "should work"): `python -m py_compile` on both changed
files; a real Qt event loop (`app.exec()`, offscreen platform) driving
`play_startup()` end-to-end and logging mood + transition state at every
850ms step boundary — sequence and timing landed exactly where the JS
version's stages (`0/220/400ms`) predict; full `DesktopMark()` construction
end-to-end confirming `self._view` is now `MoodMarkWidget`, `isVisible()`
is `True`, and `idle()`/`working()` state transitions repaint without
exception. Not yet re-verified visually on real Windows hardware post-fix —
that's the one open item before calling this closed.

**Known deliberate approximation, not a bug:** continuous ring rotation
uses constant angular velocity rather than replaying each mood's CSS
easing curve every infinite spin cycle (documented in `mark_renderer.py`'s
module docstring). Colours/geometry/mood configs/transition timings are
exact transcriptions from `mark_visual.py`, not approximated.

## BETA 0.3.38 (three-way merge) — checkpoint 3's confirmation flow adopted, an older parallel permission-gate implementation retired in its favor

Merged three independent trees that had all diverged from the same
BETA 0.3.37 base: (1) this project's own checkpoint-1+2 merge plus a
same-session plugin system and an early permission-gate feature (below),
(2) a plain re-upload of that checkpoint-1+2 merge with neither of those
two additions, (3) "checkpoint 3" — a separate session that built its own,
more thorough caution/destructive-command confirmation flow from the same
0.3.37 base. Diffed all three pairwise before touching anything, rather
than assuming any one was a strict superset.

**The real conflict:** trees (1) and (3) had EACH independently built a
gate for caution/destructive WCL commands (previously 100% unreachable),
with different designs:
- Tree (1)'s `self._pending_permission` / `confirm_pending_permission()` /
  `cancel_pending_permission()`, `"kind": "permission_gate"`, avatar-click
  wired directly to a dedicated confirm method. 3 tests.
- Tree (3)'s `self._pending_confirmation` / `_dispatch_or_confirm()` (one
  choke point covering all 4 dispatch-ready call sites, so a future call
  site can't accidentally skip the gate) / `_ask_for_confirmation()` /
  `_resume_pending_confirmation()`, `"kind": "chat"` (zero new UI
  rendering needed — it's the same path every other text response uses),
  `""` included as a valid confirm word so a bare Enter confirms. 16 tests,
  and its own STATUS.md entry documents disabling the confirmation branch
  and re-running to confirm 14 tests fail exactly as expected before
  re-enabling it.

**Kept tree (3)'s design** — single choke point, thicker test coverage,
verified by the disable-and-rerun check, explicitly requested as a
product decision in that session's chat rather than assumed. Tree (1)'s
own `orchestrator.py` permission-gate code was removed outright, not kept
alongside it — running two competing gates on the same dispatch path
would be a real correctness risk, not a redundancy.

**Not just a straight file swap, though** — tree (1) had built two things
tree (3)'s branch never had: a plugin system (`plugin_manager.py`,
`plugins/`, intents merged into `INTENTS` at import time) and real UI
wiring for the avatar-click confirm gesture (`main_widget.py`,
`toki_desktop_mark.py`). Re-spliced the plugin loading block into tree
(3)'s `orchestrator.py` (a clean, isolated addition — two small blocks,
no interaction with the confirmation logic). For the UI files: rewrote
the avatar-click handler to submit an empty string through the normal
`process_request()` path instead of calling the now-gone
`confirm_pending_permission()` directly — this works with zero other
changes because `""` is already one of tree (3)'s own `_CONFIRMATION_WORDS`,
so an avatar click and a bare Enter now go through the exact same code
path a typed confirmation would. Updated both files' `_pending_permission`
references to `_pending_confirmation` to match. `stress_test_orchestrator.py`
(a standalone dev script, not part of pytest) updated the same way —
detects a pending gate via `_pending_confirmation` instead of a
`"permission_gate"` response kind that no longer exists.

**Test files:** took tree (3)'s `tests/test_wcl_slot_filling_integration.py`
wholesale (its `TestCautionDestructiveConfirmationFlow`, 12 tests, plus 4
renamed existing tests whose old names said "blocked" when the real
behavior is now "routed to confirmation instead" — same assertions,
clearer names). Rewrote `tests/test_plugin_and_permissions.py` down to
just the plugin-loading test; its old permission-gate tests tested an API
that no longer exists and are superseded by tree (3)'s own, more thorough
coverage.

**Also kept, unaffected by any of the above** (verified byte-relevant
differences were pre-checkpoint-1/2-vs-post, not tree-3-specific, before
assuming so): checkpoint 1+2's `extractor.py`/`graph_router.py`/
`synonyms.py` work, the 230-alias WCL coverage-audit dataset and rebuilt
graph db, `README.md`'s architecture rewrite, and this session's own
prior addition, `SORT_FOLDER_BY_TYPE` (untouched by any of this — it
never touched `orchestrator.py`).

**Full suite: 624 passed** (614 prior + tree (3)'s net +13, minus 3 of
tree (1)'s now-superseded permission tests), 1 skipped, 2 xfailed. Zero
regressions — confirmed `SORT_FOLDER_BY_TYPE` and a mocked confirmation
round-trip both still resolve correctly through the merged orchestrator
before calling this done. Sandbox-only verification, same standing
limitation as always — nothing here has run against live Windows/Ollama
or a real Qt UI.

---

## BETA 0.3.38 — one new feature shipped, one tried and reverted (chat session, tested not guessed)

Picked up from a user-supplied list of ~20 non-AI automation feature ideas
(everyday productivity, power-user, team/commercial, hardware-peripheral,
file-inspection). Scoped honestly rather than attempting all of them —
most of the list either already exists in some form (the 1,160-command WCL
library already covers most "power-user"/file-inspection ideas: batch
media conversion, file signature reading, regex scanning, etc. via
WCL_-prefixed commands), needs infrastructure this project doesn't have
and a single local-machine assistant arguably shouldn't grow on its own
(LAN sharing, team template sync — multi-machine networking, no auth/trust
model, real scope creep for a sandboxed single-user tool), or needs a
live Windows/hardware environment to build against safely (hardware-
peripheral triggers, per-app audio routing — this project has never had
live Windows testing available in a chat session, per every prior
STATUS.md entry). Two were both genuinely new AND buildable/testable
Tier-A-graph-only, same shape as every existing zero/one-slot command:

- **`SORT_FOLDER_BY_TYPE` — shipped.** One-slot (`path`, reusing the
  existing `LIST_FILES`/`DELETE_ITEM` extraction branch and its bare-
  target-defaults-to-Desktop fallback, so this required zero new
  extractor.py branches). Moves top-level files only (`-File`, non-
  recursive) into `Images`/`Documents`/`Archives`/`Audio`/`Video`/`Other`
  subfolders created directly under the already-sandbox-checked `{path}`,
  skips `.lnk` shortcuts so desktop icons aren't disturbed. Every literal
  PowerShell brace in the template (hashtable literal, `Where-Object`/
  `ForEach-Object` script blocks) is doubled — this is exactly the class
  of bug BETA 0.3.37 checkpoint 1 found and fixed in 12 pre-existing
  commands, confirmed the new template `.format()`s cleanly before
  shipping it. Added to `graph_source_data/tier_a_commands.json` (61→62)
  and `tier_a_phrasings.py`, graph rebuilt via `migrate_to_kuzu.py`
  (63→62 net — see CLEAN_CLIPBOARD below), added to
  `tier_a_wcl_map.py` (`Get-ChildItem`/`Move-Item`/`New-Item` — the
  shadow-guard coverage test (`test_map_covers_every_tier_a_intent`)
  catches any Tier A intent missing from this map, which is exactly how
  this got caught before shipping). Verified live against the real
  rebuilt graph: `"sort my desktop by type"`, `"organize my desktop"`,
  `"organize my downloads folder by type"` all resolve correctly.
  6 new tests (`tests/test_extractor.py`, `tests/test_graph_router.py`).

- **`CLEAN_CLIPBOARD` — tried, then reverted.** One-shot "strip rich
  formatting from the clipboard" (`Set-Clipboard -Value (Get-Clipboard
  -Raw)`, zero slots). Built, wired, and graph-rebuilt, then two real
  problems surfaced from the existing test suite (not guessed — pytest
  caught both): (1) it collides with `GET_CLIPBOARD`/`SET_CLIPBOARD`'s
  own documented fragile shared vocabulary — `tier_a_phrasings.py`'s
  `GET_CLIPBOARD` entry already carries a BETA 0.3.27 postmortem about
  "clipboard" being the only word separating those two commands; adding
  a third clipboard command into that same narrow space is exactly the
  kind of change that history warns against. (2) Its phrasing additions
  weren't the actual cause of a separate regression that also showed up
  (`SORT_FOLDER_BY_TYPE`'s own phrasings diluted scoring enough to change
  `TestDestructiveShadowGuardCoversAmbiguous`'s `"clean temp files"` case
  — traced and fixed by rewording those phrasings, see below), but
  discovering the clipboard-collision risk while investigating was reason
  enough not to re-add it blind. Fully removed from `intents.py`,
  `tier_a_commands.json`, `tier_a_phrasings.py`, `tier_a_wcl_map.py`; a
  `TestCleanClipboardRemoved` test pins that it's gone so a future
  session doesn't reintroduce it without reading this note first.

- **Regression found and fixed along the way:** `SORT_FOLDER_BY_TYPE`'s
  first phrasing pass included `"clean up my downloads folder"` /
  `"tidy up my desktop"`, which pulled `TestDestructiveShadowGuardCoversAmbiguous::
  test_ambiguous_destructive_candidate_triggers_the_question["clean temp files"]`
  from passing to failing (`"clean temp files"` briefly stopped resolving
  to *any* Tier A intent at all). Reworded to
  `"organize my downloads folder by type"` / `"tidy my desktop by file
  type"` (dropping "clean" from this command's vocabulary entirely) —
  confirmed both the new phrasings and the pre-existing shadow-guard test
  pass together, not just individually.

Full suite: **614 passed** (was 606), 1 skipped, 2 xfailed. Sandbox-only
verification, same standing limitation as the rest of this project's
recent history — nothing here has run against live Windows/Ollama.

---

## BETA 0.3.37 — checkpoints 1 + 2 merged

Checkpoint 1 and checkpoint 2 were done in parallel off the same BETA
0.3.37 base (each closing different items from the old "known remaining
work" list), then combined in this pass:

- `extractor.py` / `tests/test_extractor.py` — took checkpoint 1's
  versions as-is (numeric-hint pair extraction, `condition` added to
  the code-like-variable blocklist). Checkpoint 2 didn't touch this file.
- `graph_router.py` / `synonyms.py` / `tests/test_synonyms.py` — took
  checkpoint 2's versions as-is (synonym expansion wired into
  `classify()`/`classify_or_ask()`). Checkpoint 1 didn't touch these.
- `wcl_kg/windows_command_library.widened.json` — merged: checkpoint 2's
  230 new coverage aliases (13,780 distinct alias texts) as the base,
  with checkpoint 1's brace-escaping fix for the 12 originally-broken
  `syntax` templates re-applied on top (checkpoint 2 branched before
  that fix existed, so its copy of the JSON still had the original,
  unescaped braces for those 12 commands — confirmed by diffing the
  `syntax` field directly before merging).
- `wcl_kg/windows_commands_db` — rebuilt from the merged JSON via
  `wcl_kg/rebuild_graph.py`, so the live db now has both the full alias
  coverage AND the escaped syntax templates at once. Verified same
  counts as checkpoint 2's rebuild (1,160 commands, 13,780 aliases).
- `tests/test_wcl_resolver.py` — checkpoint 2's version (updated alias
  count) as the base, with checkpoint 1's two extra test classes
  (`TestSyntaxVariablesFormatIntegrity`, `TestConditionVariableIsCodeLikeBlocked`)
  appended — both re-verified against the freshly-rebuilt db.
- `README.md` — checkpoint 1's rewritten version kept (checkpoint 2
  didn't touch it; still stale in checkpoint 2 alone).
- `PROJECT_STATE_OVERVIEW.md` — remaining-work list updated to reflect
  both checkpoints' items closed (see that file).

No conflicting logic changes between the two checkpoints — the
overlapping surface was purely in the WCL alias dataset, and the fix
there was additive (escaping applies to a fixed set of 12 command IDs
that don't overlap with the 230 newly-aliased ones).

---

## BETA 0.3.37 — Checkpoint 2

Picked up directly from BETA 0.3.37 below (no version bump — same
checkout, same test baseline, just further work on top of it). Closed
two of the five items PROJECT_STATE_OVERVIEW.md's old "known remaining
work" list had open (items 3 and 4), gave a deliberately-not-attempted
call on item 1 with reasoning instead of a half-built version of it, and
left items 2/5 untouched per instruction.

**Files changed this checkpoint:**
- `synonyms.py` — **new file.** Curated `SYNONYM_MAP` (12 entries) +
  `expand_synonyms()` / `is_matched_via_synonym()`.
- `graph_router.py` — wired `expand_synonyms()` into `classify()` and
  `classify_or_ask()`'s vocabulary-matching step only; the read-only-
  lookalike action-verb guard still runs on the original, un-expanded
  word set, unchanged.
- `tests/test_synonyms.py` — **new file.** 40 tests: unit tests on
  `synonyms.py` directly, data-integrity tests against the real
  `TIER_A_PHRASINGS` vocabulary, end-to-end `GraphRouter` tests for
  every synonym entry, and regression tests confirming no previously-
  fixed false positive came back.
- `wcl_kg/add_coverage_aliases.py` — **new file.** The 230-entry curated
  alias map (id -> new natural alias) plus the script that applies it
  to `windows_command_library.widened.json`.
- `wcl_kg/rebuild_graph.py` — **new file.** Rebuilds
  `wcl_kg/windows_commands_db` from the widened JSON (CSV export +
  Kuzu load + `SynonymOf` edges) using this checkout's actual paths —
  the existing `pipeline_scripts_reference/02_export_csv.py` /
  `03_load_kuzu.py` / `06_export_synonyms.py` hard-code
  `/home/claude/kg_build/...`, a build-sandbox path that was never part
  of this repo, so they can't be run here as-is.
- `wcl_kg/windows_command_library.widened.json` — data change: 230 new
  aliases added (one per never-widened command), 2 of which were
  revised mid-session after `test_wcl_coverage_audit.py` caught them
  colliding with each other (`foreach`/`%`, `r`/`ihy` — see below).
- `wcl_kg/windows_commands_db` — rebuilt from the updated widened JSON
  via `rebuild_graph.py`. This is the file `wcl_resolver.py` actually
  queries at runtime; the JSON change alone would have done nothing
  without this rebuild.
- `tests/test_wcl_coverage_audit.py` — **new file.** 23 tests: full-sweep
  assertions across all 1,160 commands (zero-alias check, every new
  alias present, no new cross-command alias collisions), plus real
  `WCLResolver.resolve()` calls against the rebuilt graph for both
  previously-`UNRESOLVED` queries and a broader correctness sample.
- `tests/test_wcl_resolver.py` — updated the pinned alias-count canary
  (`test_alias_count_matches_the_documented_figure`) from 13,546 to
  13,780, with the exact, verified (not estimated) accounting of every
  number in between written into the comment.
- `PROJECT_STATE_OVERVIEW.md` — removed the now-closed items 3 and 4
  from "What it does NOT have"; added a new "4a. Closed this session:
  items 3 and 4" section; updated the continuation prompt's test count
  (524 -> 587) and remaining-work list (item 1 now carries the
  only-3-of-181-are-`safe` reasoning for why it wasn't attempted
  generically; items 2 and 5 renumbered to 1 push/aligned as no. now
  2/3 was removed).

**What was verified, not just written:**
- Full suite: 587 passed (was 524), 1 skipped, 2 xfailed.
- Both fixes verified by deliberately reverting them and confirming
  their own tests fail (9 real `test_wcl_coverage_audit.py` failures
  against the pre-rebuild graph; 7 real `test_synonyms.py` failures
  against the pre-wiring `graph_router.py`), then restoring and
  re-confirming green.
- A real self-introduced bug caught before shipping: two of the 230 new
  WCL aliases were originally byte-identical between genuinely-near-
  synonymous PowerShell commands (`foreach`/`%`, `r`/`ihy`), which would
  have forced an avoidable `AMBIGUOUS` resolver result instead of a
  clean `RESOLVED` one. `TestCoverageFixDidNotIntroduceNewAmbiguity`
  caught it; both pairs were rewritten to distinct, still-natural
  phrasings and the graph was rebuilt again.
- One incidental correctness improvement found (not the goal, but real):
  "show battery status" resolved to the wrong command (`Get-BatteryStatus`
  instead of `Battery Status`) on the pre-fix graph; resolves correctly
  now.

**Item 1 (generic slot-filler for 3+ variable WCL commands) — explicitly
NOT attempted, by reasoned choice, not oversight:** of the 181 commands
needing 3+ variable slot-filling, only 3 are `safe` (auto-dispatch-
eligible at all) — 4 are `caution` and 174 are `destructive`, which
never auto-dispatch regardless of slot-filling capability (unrelated,
unchanged safety boundary). A generic 3+-slot parser is real new parsing
surface area in a system that dispatches live PowerShell, for a
guaranteed payoff of 3 commands. See PROJECT_STATE_OVERVIEW.md's
continuation prompt for the two honest ways to actually close this if
wanted: a narrow hand-written version for just those 3 commands, or a
dedicated full generic-parser pass treated as its own piece of work
rather than folded in here.

---

## BETA 0.3.37 checkpoint 1 — numeric-hint WCL pair extraction, README architecture rewrite, live dispatch-crash fix (12 commands), condition-variable blocklist gap closed

**Not a new version bump** — this is a checkpoint within 0.3.37, picked up
directly from `PROJECT_STATE_OVERVIEW.md`'s own "still open" list. Four
separate pieces of work, each independently verified (fix reverted,
confirmed the relevant new test(s) fail against the unfixed code, then
restored), full suite re-run after each.

**Files changed:**
- `extractor.py` — new numeric-hint pair-extraction strategy;
  `condition` added to the code-like variable blocklist
- `wcl_kg/windows_command_library.widened.json` — `syntax` field escaped
  for the 12 affected commands (source-data fix)
- `wcl_kg/windows_commands_db` — same 12 records patched directly in the
  live Kùzu DB (binary graph DB — the JSON alone is NOT what the running
  app reads; both had to be fixed for this to have any real effect)
- `tests/test_extractor.py` — 12 new tests
  (`TestWclNumericHintPairExtraction`)
- `tests/test_wcl_resolver.py` — 4 new tests
  (`TestSyntaxVariablesFormatIntegrity`,
  `TestConditionVariableIsCodeLikeBlocked`)
- `README.md` — architecture sections (top through "Extending the intent
  list") rewritten to match the current Tier A/Tier B/graph-router/WCL-
  resolver design; the old per-version changelog sections below that
  point are left as-is and explicitly labeled as historical

**1. Numeric-hint pair extraction (`PROJECT_STATE_OVERVIEW.md` #2).**
2-variable WCL commands shaped like (path, count) or (path, size) —
`Get-LargestFiles`, `Recent Files`, `Old Files`, `Large Folders`, `Find
Large Files` — had no extraction path at all for phrasing with no quotes
and no to/into/as separator ("show me the 5 largest files in
D:\Projects"). Added a third pair-extraction strategy: finds the numeral
(keyword-aware, "top N" aware, safe-fallback), converts units for sizes
(500MB -> bytes), and hands the remainder to the SAME narrowing +
plausibility + sandbox gate every other extractor here already uses —
new way to *find* the two candidate strings, not a new way to *trust*
them. Deliberately rejects a bare unitted-less size (too ambiguous) and a
number glued directly to a path segment (e.g. a folder literally named
"5"). 12 new tests; reverted and confirmed all 6 positive-case tests fail
against the unfixed code before restoring.

**2. Live dispatch-crash bug, found while auditing the WCL dataset for
something unrelated.** Checked whether every WCL command's `syntax`
template's `.format(**declared_vars)` call — the exact call
`orchestrator.py` makes at real dispatch time for any command with
declared variables — actually succeeds. 37 commands raised; of those,
only 12 actually matter live, because the other 25 have ZERO declared
variables and `orchestrator.py` already, deliberately, skips `.format()`
entirely for those (see its own comment: "Skipping .format() here matters
for windows_command_library commands whose raw PowerShell syntax contains
literal {}"). For the 12 WITH variables, `.format()` DOES run, and the
resulting exception was silently caught and reported to the user as a
plain "Done." — meaning these 12 "safe" commands never actually executed
anything, ever, including `Get-LargestFiles`/`Large Folders`/`Find Large
Files`, the exact 3 commands item #1 above just added new extraction
coverage for. Fixed by escaping every literal PowerShell brace that ISN'T
part of a real `{varname}` placeholder — verified per-command that
formatting the escaped template reproduces EXACTLY the same final
PowerShell text the original author intended, before writing anything.
**Important:** the live resolver reads from the prebuilt Kùzu DB
(`wcl_kg/windows_commands_db`), not the JSON directly — fixing only the
JSON would have changed nothing at runtime. Patched both, with a
before/after diff logged for all 12 records in the live DB. 2 new tests
run directly against the real shipped DB (same standard the rest of
`test_wcl_resolver.py` already holds itself to); reverted the DB to a
backup and confirmed both fail with the exact original `ValueError`
before restoring the fix.

**3. `condition` variable added to the code-like blocklist.** Found while
doing the audit above: `?`/`where` (both "safe") take a `condition`
variable substituted directly into a live `Where-Object { ... }`
PowerShell scriptblock — the same raw-expression-injection shape
`script_block` was already blocked for, just under a different variable
name the original blocklist didn't cover. Confirmed live before the fix:
`extract_slots("WCL_where", 'where $_.Name -eq "evil"',
wcl_variables=["condition"])` returned `{'condition': 'evil'}` — a real,
reproduced gap, not theoretical. 2 new tests; reverted and confirmed both
fail with the actual unsafe extracted value before restoring.

**4. README.md documentation pass (`PROJECT_STATE_OVERVIEW.md` #5).** The
file still described the pre-graph-router, single-tier, 60-intent v2.11
design as current. Rewrote everything from the top through "Extending the
intent list" to match the actual current pipeline (Tier A graph router +
Tier B WCL resolver, destructive-shadow guard, sandbox model, real
requirements, real test counts) — left the old per-version changelog
sections below untouched but added an explicit note marking them as
historical, since they're a real record of the project's history even
though they no longer describe current behavior.

**Full pytest suite: 540 passed, 1 skipped, 2 xfailed** (up from 0.3.37's
524 passed; +16 net new tests, zero regressions).

## BETA 0.3.37 — CRITICAL: systemic command-injection fix in WCL dispatch, found while building 0.3.36's 2-variable slot filler

**Severity: the most important fix in this project's history so far.**
Found by testing my own new feature before trusting it, not reported by
anyone -- see BETA 0.3.36 below for the feature that led here.

**Root cause, confirmed live:** `_escape_ps_slot()` (single-quote
doubling) only protects a slot value if the WCL syntax TEMPLATE ITSELF
already wraps `{var}` in matching quotes. Audited every currently-
eligible "safe" command: **297 of 298** single-variable ones have a
completely UNQUOTED placeholder (`"Get-Content -Path {path}"`,
`"subst {drive_letter} {path}"`, `"Start-Job -ScriptBlock
{script_block}"`, ...). Compounding this, `_looks_like_real_name()` (the
plausibility gate for non-path values) does ZERO character-level
filtering -- no check for `;`, backticks, `$(...)`. A value like
`"pwned.txt; Remove-Item -Recurse -Force D:\\"` passes it cleanly.
**Confirmed directly**: called the real (not mocked) `_dispatch()` with
that exact value and got back `Get-Content -Path pwned.txt; Remove-Item
-Recurse -Force D:\\` -- a genuine two-statement PowerShell command,
built and ready to run with this app's own privileges. Not theoretical.

**Fix -- `_ensure_quoted_placeholders()`:** a proper quote-STATE-tracking
scanner (not a naive regex -- see its own docstring for why a simple
adjacency check would have broken templates like `'*{query}*'`, which
have literal characters between the quote and the brace but are still
safely inside a single-quoted span). Scans a template left to right
tracking PowerShell single-quote state, wraps any `{var}` found OUTSIDE
a `'...'` region in fresh single quotes, leaves anything already safely
quoted untouched. Applied in ONE place (`_dispatch()`, before every
`powershell`-kind template fill) -- covers TOKI's own 62 hand-written
intents too (harmless no-op there; found and closed their one real gap,
`TOP_PROCESSES_BY_CPU`'s `count`, for free).

**Second, subtler gap found testing the first fix:** wrapping a
placeholder that's inside a PRE-EXISTING DOUBLE-quoted region (e.g.
`eventcreate`'s `/D "{message}"`) in NEW single quotes doesn't actually
stop injection there -- PowerShell parses the outer `"..."` for
`$(...)`/`$variable` expansion regardless of literal `'` characters
nested inside it. Confirmed against 3 real commands (`eventcreate`,
`find`, `findstr`). Fixed by extending `_escape_ps_slot()` to also
escape backtick and `$` (backtick first, so a backtick introduced for
`$` isn't double-escaped) -- inert/harmless in a single-quoted context
(which doesn't process backtick-escapes at all), and exactly the needed
protection in a double-quoted one.

**Two more gaps found in the same audit, same severity class:**
- **Path sandboxing gap**: 6 currently-shipped "safe" commands have a
  clearly path-shaped variable name that wasn't in `_WCL_PATH_VAR_NAMES`
  (so it never got routed through `resolve_path()`'s sandbox at all) --
  worst: `call {batch_file}` runs an arbitrary `.bat`/`.cmd` file, from
  ANYWHERE on disk, not just under D:\/Desktop. Full audit of all 234
  distinct WCL variable names, not just a guess at these 6; expanded the
  set to 23 names.
- **Code/scriptblock-content gap**: 15 currently-eligible "safe"
  commands take a variable representing literal CODE, not a plain value
  (`Start-Job`'s `script_block`, `Set-Alias`'s `command`, etc.). Even a
  value that's perfectly safe AS A QUOTED STRING can still end up
  EXECUTED, because PowerShell parameter binding for a
  `[scriptblock]`-typed parameter can implicitly convert a plain string
  argument into compiled, runnable code -- a risk no amount of
  string-level quoting/escaping can prevent. Fixed with a categorical
  blocklist by variable name (substring match, deliberately broad),
  checked at THREE points so it can't be bypassed by a different entry
  path: `extract_slots()`, `resolve_missing_slot()` (the follow-up-
  answer path -- without this, a value correctly blocked on the first
  message could sneak in via the answer to the resulting question), and
  `orchestrator.py`'s eligibility gate itself (so a code-like command
  never even gets a doomed missing-slot question in the first place).

**Found and fixed a real bug in my OWN new code while testing it**: the
2-variable extractor's path-shaped-variable branch was skipping the
plausibility check entirely (going straight to `resolve_path()`, which
doesn't judge whether a string LOOKS like a real name vs. a whole
garbled sentence). Repro: `"copy whatever you think is best to
backup.txt"` resolved both sides successfully, including
`"...\copy whatever you think is best"` as a real (nonsensical)
sandboxed path. Fixed by running `_looks_like_real_name()` first,
unconditionally, before the path-vs-generic split.

**Verified, not just reasoned about:** every fix above has a live
before/after test. The dispatch-level quoting fix specifically:
reverted just that one call site, confirmed the semicolon-injection test
fails and shows the exact raw exploit command, restored the fix,
confirmed it passes again.

**14 new/updated tests** across `tests/test_wcl_slot_filling_integration.py`
(`TestDispatchNeverProducesAnUnquotedInjectableCommand`, 6 tests, calling
the REAL `_dispatch()`, not a mock) and `tests/test_extractor.py`
(`TestWclCodeLikeVariableBlocklist`, 10 tests).

**Full pytest suite: 524 passed, 1 skipped, 2 xfailed.**

**Not attempted / explicitly out of scope even after this fix:**
- A full security audit of the remaining ~940 WCL commands not yet
  eligible for auto-dispatch (danger_level `"caution"`/`"destructive"`,
  or 3+ variables) -- irrelevant to injection safety right now since
  none of them can currently be auto-filled at all, but worth
  remembering if that ever changes.
- Confirming empirically against a real Windows PowerShell instance that
  `[scriptblock]`-typed parameters actually behave the way this fix
  assumes (implicit string-to-scriptblock conversion) -- reasoned from
  documented PowerShell parameter-binding behavior, not verified against
  a live instance (none available in this sandbox). The blocklist
  approach means this is a belt-and-suspenders precaution either way,
  not the only thing standing between a value and execution.

## BETA 0.3.36 — WCL phase 2: 2-variable "safe" command slot filler (61 commands)

**What this adds:** extends the existing single-variable "safe" WCL
auto-fill (BETA 0.3.15) to 2-variable "safe" commands (61 of them,
things like `Copy-Item`, `Compress-Archive`, `Join-Path`, `subst`).
Two deliberately narrow, reliable strategies in
`extractor.py::_extract_wcl_slots_pair()`:
1. Exactly two quoted substrings in the message -> assign in order
   (matches syntax order, e.g. `-Path {source} -Destination
   {destination}` lists source first).
2. No quotes (or the wrong count) -> split once on a natural
   `" to "`/`" into "`/`" as "` separator -- the same word order TOKI's
   own `RENAME_ITEM`/`MOVE_ITEM`/`COPY_ITEM` intents already use.

Explicitly NOT attempted: a numeric-hint strategy for pairs like
`(path, count)` with no quote/separator at all (e.g. "show me the 5
largest files") -- falls through to asking, same as before this session.
3+ variable commands (7 of them, all `"destructive"` anyway) remain out
of scope.

**This work is what LED TO finding the critical injection gap above** --
before extending auto-dispatch eligibility to more commands, the
existing single-variable path was checked end-to-end rather than just
building on top of it unquestioned. See BETA 0.3.37 for what that
found. The 2-variable feature itself was only actually wired into
`orchestrator.py`'s eligibility gate AFTER that fix landed -- extending
auto-dispatch surface on top of a known-vulnerable foundation would have
been the wrong order to do this in.

## BETA 0.3.35 — CRITICAL, found while scoping the 876-commands milestone: zero-variable WCL commands could bypass every safety check regardless of danger_level

**Severity: this is not a routing-correctness bug like everything else in
this session's history. This is the one that actually mattered.**

**Context:** while investigating what it would take to extend WCL
auto-dispatch to more of the ~1,200 commands (the user's "add em all"
ask, working through this session's ranked bug list), traced the
EXISTING eligibility gate in `orchestrator.py` (`if not var_names or
is_safe_single_var:`) end to end, rather than just extending it, and
found the zero-variable half of that condition (`not var_names`) had
**no `danger_level` check at all** -- unlike the single-variable half
right next to it.

**Confirmed live, concretely:** `"run diskpart"` -- `diskpart` is
`danger_level: "destructive"`, zero variables -- resolves cleanly
`RESOLVED` via `wcl_resolver.py`. Traced the full path this takes:
1. `graph_router.classify("run diskpart")` returns `None` (a genuine
   Tier A miss) -- meaning `_check_destructive_shadow()` **never runs at
   all**, since that guard is only ever invoked when Tier A ALSO
   produced a classification to compare against.
2. `wcl_resolver.resolve()` returns `RESOLVED`, `danger_level:
   "destructive"`.
3. The eligibility gate's zero-variable branch let it through with no
   danger_level check.
4. `extract_slots("WCL_diskpart", ..., wcl_variables=[])` falls through
   to `extractor.py`'s universal default (`# No slots needed for this
   intent.` -> `return {}`) -- `{}`, not `None`.
5. `slots is None` is `False`, so `process_request()` goes straight to
   `self._dispatch(...)`.
6. Grepped every use of `danger_level` in `orchestrator.py`: it is ONLY
   ever read in `_check_destructive_shadow()` (step 1, never reached
   here) and in the eligibility gate itself (step 3, the gap). Nothing
   in `_dispatch()` checks it again.

Would have silently launched `diskpart` with zero confirmation of any
kind. Also confirmed the same gap applies to the other 4 zero-variable
`"destructive"` commands and all 8 zero-variable `"caution"` commands in
the dataset -- most of those specific phrasings happen to currently
resolve `AMBIGUOUS` rather than `RESOLVED` given the CURRENT alias data
(e.g. `"restart"`/`"clean temp files"` collide with a sibling command),
which is WHY they weren't already an active exploit -- nothing was
actually preventing them; a future alias addition disambiguating any of
them (exactly the kind of change this session made repeatedly to OTHER
commands) would have silently reopened this hole for that command.

**Also found, while adding the fix's tests:** a genuine bug in the TEST
FILE itself -- `tests/test_wcl_slot_filling_integration.py` was missing
a `class` declaration before 4 existing danger-level-gate tests, leaving
them syntactically nested inside the WRONG test class
(`TestPillCategorySurfacesWclTaxonomy`). Didn't affect whether those 4
tests ran or passed, but meant nothing in this file's organization
signaled "these 4 tests are the ones guarding the safety boundary" --
and, more importantly, meant there was no natural home that made the
MISSING zero-variable case's absence obvious. Fixed by adding the
missing `class TestDangerLevelGateBlocksEverythingExceptTheNarrowSafeWindow:`
declaration and adding the 3 new zero-variable tests into it alongside
the 4 that were already there.

**Fix:** the eligibility check is now `is_safe = danger_level == "safe"`,
applied uniformly -- `eligible = (len(var_names) == 1 and is_safe) if
var_names else is_safe`. A zero-variable `"caution"`/`"destructive"` WCL
command now falls through to the LLM router like any other miss, with NO
special handling bundled into this fix (that's a separate, later
decision -- this fix only stops the silent bypass, it doesn't add a new
confirmation flow).

**3 new tests, plus fixed the pre-existing class-declaration bug
covering the other 4** (`tests/test_wcl_slot_filling_integration.py::
TestDangerLevelGateBlocksEverythingExceptTheNarrowSafeWindow`, 7 tests
total in that class now). **Confirmed by reverting the fix**: the 2 new
"must not dispatch" tests fail against the reverted code with
`'intent': 'WCL_diskpart'` actually present in the captured dispatch --
i.e. this is a real, reproduced exploit path, not a theoretical one.

**Full pytest suite: 498 passed, 1 skipped, 2 xfailed** (up from
0.3.34's 495 passed; +3 net new tests, zero regressions -- confirms
nothing in the existing suite was relying on the buggy bypass behavior).

## BETA 0.3.34 — targeted WCL alias-dataset audit (no new "sole garbage alias" cases found beyond Lock-BitLocker), FIND_FILES gets the same leading-verb-strip fix as DELETE_ITEM/READ_FILE

**Context:** the last 2 items from this session's own ranked bug list
(everything else on that list is now closed -- see BETA 0.3.31-0.3.33).

**1. WCL alias-dataset audit -- targeted, not exhaustive, scope stated
plainly.** A full natural-language-coverage audit (does every one of the
~1,200 commands have a realistic phrasing for every reasonable way a
user might ask?) was never attempted -- that's a much bigger project than
this pass. What WAS checked, directly against the live graph:
- Zero commands (destructive/caution or otherwise) have NO aliases at all.
- Only 2 destructive commands have exactly 1 alias (`reset` ->
  `"session reset"`, `erase` -> `"files erase"`) -- both legitimate
  single natural phrasings, not the garbage-duplicate-word shape.
- Specifically re-ran the exact check that caught the original
  `Lock-BitLocker` bug (a command whose ONLY alias is a literal
  duplicated single word, e.g. `"bitlocker bitlocker"`) across the
  ENTIRE dataset, not just single-alias commands this time -- found the
  duplicated-word shape appears on 12 commands total (`kill`, `restart`,
  `find`, `exit`, `compare`, `diff`, and the 6 `*-BitLocker` siblings),
  but in every one of those cases it's sitting ALONGSIDE plenty of other
  real, working aliases (e.g. `kill` also has `"stop kill"`,
  `"terminate kill"`, `"halt kill"`, etc.) -- a harmless side effect of
  the alias-generation script's synonym-templating including the
  command's own name as one of its own synonyms, not a broken command.
  Confirmed **zero** commands anywhere in the dataset have ONLY the
  garbage shape and nothing else -- the real bug shape from before is
  confirmed fixed and not recurring elsewhere.

**2. `FIND_FILES` -- given the same leading-verb-strip fix as
`DELETE_ITEM`/`READ_FILE`/`OPEN_ITEM`/`LIST_FILES` (BETA 0.3.32).**
Confirmed live: `"find files.txt"` extracted query `"find files.txt"`
instead of `"files.txt"`; `"search for report.docx"` extracted
`"search for report.docx"` instead of `"report.docx"` -- same root cause
as the DELETE_ITEM bug, just on a lower-stakes intent (a bad guess here
means a bad SEARCH, not a wrong deletion). `_BARE_PATH_LEADING_VERB_RE`
extended to also match `find`/`search`, plus an optional `"for"` filler
(`"search for X"`). **Deliberately NOT** also wired to the
`_looks_like_real_name()` plausibility guard the destructive-target
intents use -- lower stakes don't need the same "ask instead of guess"
posture, and a loose multi-word search query being sentence-shaped isn't
actually a problem the way a sentence-shaped delete target is.

**4 new tests** in `tests/test_extractor.py::TestFindFilesByNameLeadingVerbStrip`.

**Full pytest suite: 495 passed, 1 skipped, 2 xfailed** (up from 0.3.33's
491 passed; +4 new tests, zero regressions).

**This closes every item from the ranked bug list given in chat.**
Nothing left open from that list. The only remaining known items are the
two flagged as explicitly out of scope for a quick pass:
- The 876-commands generic-slot-filler milestone (see BETA 0.3.33) --
  needs its own design conversation, not attempted.
- The offline curated-synonym-table discussion for `graph_router.py` --
  raised, discussed, deliberately not implemented, no code change.
- A FULL (not targeted) natural-language-coverage audit of the WCL
  dataset -- the targeted audit above checked for the SPECIFIC failure
  shape that caused a real bug; it did not verify every command has a
  realistic phrasing for every way a user might reasonably ask.

## BETA 0.3.33 — WCL Tier 8: leading noun+verb swap retry, closes the original "bitlocker lock mount point D" repro from priority.md #11

**Context:** the user believed this (and a couple of other old
`priority.md`/early-`STATUS.md` items) had been fixed in a separate
chat. No new upload came with that message, so this session's own copy
was checked directly rather than assumed -- confirmed live that
`"bitlocker lock mount point D"` (the *exact* original test string from
`priority.md` #11, first flagged all the way back before this
conversation even started, and explicitly re-confirmed still open in
this session's own BETA 0.3.27 entry) was still `UNRESOLVED`. Also
re-checked two sibling items from that same old flagged entry --
`"wipe disk 2"` and `"disable dedup volume on E"` -- both now resolve
correctly (Tier A no longer misroutes them at all, WCL resolves them
RESOLVED+destructive+confirmation-required) as a side effect of earlier
sessions' `graph_router.py` work, not anything touched this round.

**Root cause, confirmed live:** `"lock bitlocker mount point D"`
(verb-first) already resolves cleanly via Tier 2 -- `"lock bitlocker"`
is a real 2-word alias for `Lock-BitLocker`, `"mount point D"` strips as
the trailing value. But `"bitlocker lock mount point D"` (noun BEFORE
verb) failed every one of tiers 1-7, because all of them assume the verb
leads.

**Fix -- Tier 8, leading noun+verb swap retry:** swaps ONLY `tokens[0]`
and `tokens[1]`, then re-runs the query through the EXISTING
`_resolve_normalized()` (tiers 1-5) verbatim -- no new matching logic
added, just a rewritten variant fed back through what already exists.
Same narrow-scoping posture as Tier 7 (`_bracket_resolve()`): requires
at least 3 tokens (2 to swap + a genuine remaining value), tried only
after tier 6 fails, not composed with tiers 6/7, whatever tiers 1-5
return for the swapped string (RESOLVED or AMBIGUOUS) is returned as-is
just re-tagged tier 8.

**Verified end to end, not just at the resolver:** `_check_destructive_shadow()`
now correctly produces the confirmation question for the exact original
repro string -- Tier A still guesses `LOCK_WORKSTATION` for it (unchanged,
expected), but the shadow guard catches the mismatch against `Lock-BitLocker`
correctly now that WCL actually resolves it.

**9 new tests** in `tests/test_wcl_resolver.py::TestTier8LeadingPairSwap`
/ `TestLeadingPairSwapHelperDirectly`, same style as Tier 7's own test
class. **Confirmed by disabling the tier at runtime** (not a full file
revert this time, since the change is small and additive): the target
query correctly falls back to `UNRESOLVED` with `_leading_pair_swap`
stubbed out.

**Full pytest suite: 491 passed, 1 skipped, 2 xfailed** (up from 0.3.32's
482 passed; +9 new tests, zero regressions).

**Explicitly NOT attempted this round, and flagged as too large for a
"check and resolve" pass:** the project's oldest, biggest structural gap
-- **876 of the ~1,200 WCL commands are "matchable but not runnable"**
(logged since early `STATUS.md`, restated as the explicitly agreed next
milestone, still not started as of this entry). `extract_slots()` is
hand-written per Tier A intent name (fine for TOKI's original 59 intents,
not for 876 arbitrary WCL variable names like `vm_name`/`filter`/
`setting`). This needs a real generic slot-filler keyed by variable
name/type, which is a genuine design project on its own -- not something
to bolt on inside a bug-fixing pass. If this is wanted next, it deserves
its own scoping conversation before any code gets written, given how
directly it touches what's allowed to auto-dispatch.

## BETA 0.3.32 — closes the long-standing extractor known-open issue (relative filename over-capture), plus a real trivial-case bug it was hiding

**Context:** direct continuation of BETA 0.3.31, working down the ranked
bug list from chat. `extractor.py`'s `_extract_bare_path()` relative-
filename branch had been a documented `xfail` since STATUS.md BETA 0.3.2:
no anchor on the filename slot, so a file described in a full sentence
(no quotes, no `called`/`named` trigger) swallowed the leading verb
phrase too -- e.g. `"delete the file version 2.0 from my desktop"` ->
`"delete the file version 2.0"`.

**First pass, then a real problem found in it.** The first fix wired the
existing `_looks_like_real_name()` plausibility guard (already used
elsewhere in this file for the identical shape of problem, just never
connected to THIS call site) into `DELETE_ITEM`/`READ_FILE`/`OPEN_ITEM`/
`LIST_FILES`'s bare-path fallback -- rejecting a guess containing one of
TOKI's own action verbs, falling through to "ask" instead of guessing
wrong. That closed the reported xfail correctly, but manual spot-checking
before calling it done surfaced a real usability regression the plausibility
guard alone introduced: `"delete notes.txt"` -- the single most common,
simplest possible phrasing, no filler at all -- ALSO now returned `None`
and asked, instead of just working.

Tracing that down found the guard wasn't the real problem: it was
UNMASKING a bug that predates this whole session and had no test
coverage at all -- `_extract_bare_path("delete notes.txt")` already
returned `"delete notes.txt"`, not `"notes.txt"`, silently, before any
of this session's changes. The regex's `[\w .\-]+` character class never
distinguished a leading verb from the actual filename; it was just never
caught because no earlier test exercised a plain `"<verb> <filename>"`
with no quote/trigger/filler at all.

**Real fix, two layers:**
1. `_BARE_PATH_LEADING_VERB_RE` -- a small, curated leading verb+filler
   prefix (`delete`/`remove`/`erase`/`read`/`open`/`view`/`show`/
   `display`/`list`, optionally followed by `the`/`file`/`document`/
   `folder`) is stripped from the front of the text, anchored with `^`
   so it only ever fires when the text genuinely STARTS with one of
   these words -- before the filename regex runs. Fixes the trivial case
   correctly (`"delete notes.txt"` -> `"notes.txt"`) AND, as a bonus,
   correctly resolves the ORIGINAL reported sentence too: after stripping
   `"delete the file "`, what's left of `"...version 2.0 from my
   desktop"` matches `"version 2.0"` as the filename -- which is exactly
   what the original xfail wanted, not a fallback "ask".
2. `_looks_like_real_name()`, wired into the call site as before, stays
   as a safety net for whatever survives the strip but still looks like
   a sentence fragment (either a genuine `_SENTENCE_VERBS` word still
   present, e.g. `"can you read the quarterly report.docx for me"` --
   `^` anchor means "can" blocks the strip entirely -- or just too many
   words, e.g. `"delete the presentation my boss sent me last
   week.pptx"`). Both fall through to asking correctly, verified live.

**Verified with 4 new/rewritten tests** in
`tests/test_extractor.py::TestKnownOpenIssues` (the `xfail` marker is
gone -- this is now a real, permanent pass, not a documented gap) plus 1
updated in `TestDrivePathWithSpaces` (its old assertion literally checked
for the PRE-fix broken string, since it was written to pin "this OTHER
fix didn't accidentally change this one" back when the other one was
still broken -- now updated to assert the current, correct, non-broken
value). **Confirmed by temporarily reverting `extractor.py`**: all 5
touched tests fail against the reverted code with the exact expected
before/after values, not just a vague pass/fail flip.

**Deliberately NOT touched:** `FIND_FILES`'s identical `_extract_name(text)
or _extract_bare_path(text)` pattern (line ~1047) uses the result as a
loose search query, not a destructive-dispatch target -- different risk
profile, no existing test coverage to verify against, left alone rather
than making an unverified change there too.

**Full pytest suite: 482 passed, 1 skipped, 2 xfailed** (down from
0.3.31's 478 passed, 3 xfailed -- the extractor xfail is gone for real,
not just skipped differently; net +4 tests). The 2 remaining xfails are
unrelated, pre-existing, already-documented gaps
(`test_chain_split_viability.py`'s literal-`"and"`-in-a-filename gap,
`test_graph_router.py`'s `GENERATE_FILE` zero-phrasings gap) -- confirmed
untouched by this session.

**This closes the "extractor anchor fix" item from the ranked bug list
given in chat.** Remaining from that list, unchanged:
- The WCL alias dataset audit beyond the 3 commands spot-checked so far
  (New-VM, Lock-BitLocker, Restart-NetAdapter) -- not attempted, the
  largest remaining item.
- The offline curated-synonym-table discussion for `graph_router.py` --
  raised, discussed, deliberately not implemented, no code change.
- `FIND_FILES`'s own (lower-stakes, untested) version of the same
  over-capture shape, noted above -- not attempted this round.

## BETA 0.3.31 — voice_pipeline.py Ctrl+K fix restored (an intervening edit on a different branch had reverted it), plus a dropped apis.py test re-added

**Context:** picked up an uploaded copy of the project (labeled 0.3.30)
that had real, independently-verified, good work in it
(`wcl_resolver.py`'s Tier 6/7 -- see that entry below) alongside one
genuine regression in `voice_pipeline.py`, caught by re-verifying rather
than trusting the accompanying write-up.

**`voice_pipeline.py` Ctrl+K race -- REVERTED, now RE-fixed.** The
0.3.29-era fix (`self._capturing = True` moved before the
drain/VAD-reset/`extend_event.clear()` setup block) had been moved back
to running AFTER that block in the uploaded copy -- i.e. the exact
original bug ordering -- accompanied by a comment claiming the opposite
("closes that window down to the width of these few lines"). Confirmed
live, not just by re-reading: hooked `_vad.reset()` (which runs inside
that setup block) and fired `on_hotkey_trigger()` at that point --
`self._capturing` was `False`, `extend_listening()` was NOT called, and
`self._trigger.set()` fired instead. The original bug, reproduced
exactly.

The accompanying replacement test file (`tests/test_voice_pipeline.py`,
4 tests) did not catch this: its regression test hooks `time.monotonic()`,
whose first call in `_record_and_transcribe()` happens to land AFTER
wherever `self._capturing = True` was placed, in EITHER ordering -- so it
can only ever observe `_capturing` as already `True`, regardless of
whether the fix is actually in place. Confirmed this by reverting the
fix and re-running: those 4 tests kept passing throughout, unable to
distinguish fixed from broken.

**Fix:** moved `self._capturing = True` back to the top of
`_record_and_transcribe()`, before the drain/reset block, same as
BETA 0.3.28/0.3.29. **Added back a test that actually probes the
vulnerable window** (`tests/test_voice_pipeline.py::
TestVadResetWindowIsNotVulnerable`, 2 tests) using the same
`_vad.reset()`-hooking technique used to catch the regression in the
first place -- kept the 4 existing unit-style tests too (they're not
wrong, just insufficient on their own). **Confirmed by reverting again**:
the 2 new tests fail against the reverted ordering while the 4 existing
ones keep passing regardless -- proving the gap those 4 alone had, and
that the 2 new ones close it.

**`tests/test_apis.py` -- re-added a dropped test case.** The same
uploaded copy's edit to this file (patch-target tidying, `requests.get`
-> `apis.requests.get`) also silently dropped
`test_http_error_status_also_treated_as_a_retryable_failure` (the
`raise_for_status()` / HTTP 429-style failure path, a separate code path
from a raw connection error). `apis.py` itself was untouched and this
path still worked correctly the whole time -- this was a test-coverage
regression only, not a functional one. Re-added, using the file's own
`apis.requests.get` patch convention.

**Full pytest suite: 478 passed, 1 skipped, 3 xfailed** (up from the
uploaded copy's 475; +3 net: 2 new voice_pipeline probe tests, 1
restored apis.py test). Zero regressions elsewhere -- in particular,
`wcl_resolver.py`'s Tier 6/7 work (see BETA 0.3.30 entry below) is
untouched and still fully verified.

**Not re-litigated:** everything else in the uploaded copy (Tier 6/7,
the `Restart-NetAdapter` direct alias fix, the abbreviation-pair
mechanism) was independently re-verified live in chat before this entry
and found solid -- see BETA 0.3.30 below for that work's own details.
This entry only covers what changed since then.

## BETA 0.3.30 — WCL Tier 7: verb...noun bracket resolver (open item #1, chat session, tested not guessed)

**Note before this entry:** VERSION already said 0.3.29 and
`wcl_resolver.py` already had Tier 6 (abbreviation/full-form retry) in
this checkout, but STATUS.md had no 0.3.29 entry -- a documentation gap
from that session, not something this entry retroactively fixes. Flagging
it rather than quietly filling it in with a reconstructed account.

**New: `WCLResolver._bracket_resolve()` (`wcl_resolver.py`), wired in as
Tier 7.** Handles phrasings where the verb and the object noun BOOKEND
the value -- `"stop the print spooler service"` (verb=stop, value=
"print spooler", noun=service), which none of tiers 1-6 could reach:
tier 2 only strips a TRAILING value (verb-then-value), and tier 6's
abbreviation swap doesn't relocate where the value sits.

Deliberately narrow, matching the caution this item was flagged with
(new matching logic next to a safety-relevant resolver):
- single leading token (verb) + single trailing token (noun) only, not
  multi-word head/tail combos
- `"<head> <tail>"` must be an EXACT alias-table match -- same bar as
  Tier 1, never fuzzy
- requires a genuine non-empty middle; unambiguous single command only
  (2+ real hits -> AMBIGUOUS, never a guess)
- NOT composed with Tier 6's abbreviation retry yet -- each tier is a
  real widening on its own; stacking both (abbreviation swap that only
  then becomes a bracket match) hasn't been exercised, so it's not wired
  up until it has been
- reuses the existing `stripped_value` key (same one Tier 2 already
  produces), so `orchestrator.py`/`extract_slots()` needed ZERO changes
  -- confirmed live end-to-end: `resolve("add the important job")` ->
  Tier 7 RESOLVED, Start-Job, `stripped_value="important"` ->
  `extract_slots()` -> `{"script_block": "important"}`, no new plumbing

**Verified live against the real shipped graph, not asserted:**
- `"stop the print spooler service"` -> RESOLVED tier 7, Stop-Service,
  `stripped_value="print spooler"` (article "the" correctly stripped)
- `"stop print spooler service"` (no article) -> same result, confirms
  the strip is conditional, not always chopping the first middle token
- `"backup the important vm"` -> AMBIGUOUS tier 7, `{Save-VM, Export-VM}`
  -- "backup vm" is a real 2-word alias shared by both in the live
  graph; confirms this tier never silently picks one
- `"format the usb drive"` -> **still UNRESOLVED**, confirmed live, NOT
  silently claimed fixed. Root cause checked directly: no `"format
  drive"` alias exists anywhere in the shipped data (`format`'s aliases
  are all `"<filler> format"`/`"disk format"` -- none pair it with
  `"drive"`). This is a DATA gap, not a mechanism gap -- the resolver
  tier works exactly as designed, there's just no alias for it to find.
  Feeds directly into open item #3 (dataset alias-coverage audit),
  doesn't get fixed by adding more resolver logic.
- 8 new tests in `tests/test_wcl_resolver.py` (`TestTier7BracketMatch`,
  `TestBracketResolveHelperDirectly`), all against the live graph.
  Full suite re-run: 471 passed, 1 skipped (PyQt6 not installed in this
  sandbox, unrelated), 3 xfailed (pre-existing, unrelated to this
  change), zero regressions.

**Still open, unchanged by this session:** #2 (extractor anchor
fix/relative-filename over-capture, `xfail`-marked) and #3 (full WCL
dataset alias-coverage audit, ~1,197 of ~1,200 commands never
systematically checked) -- both not started. `"format the usb drive"`
above is a concrete, freshly-confirmed data point for #3, not a new item.

## BETA 0.3.28 — concurrency + permanent-failure-caching bugs, 2 of 4 reported items fixed and verified live, 1 fixed but not yet test-covered, 1 not started (checkpoint, tested not guessed)

**Context:** a second-pass adversarial review (separate from 0.3.27's
routing/shadow-guard pass) surfaced 4 reported bugs across
`condition_checker.py`, `app_control.py`, `apis.py`, and
`voice_pipeline.py` — two concurrency races and two "a transient failure
gets cached forever" bugs. This is a mid-session CHECKPOINT, not a
finished pass: 2 of the 4 are fixed AND covered by regression tests that
were confirmed to fail against the original code and pass against the
fix; 1 is fixed but not yet test-covered; 1 (`voice_pipeline.py`) hasn't
been looked at yet. See "Still open" at the end before assuming this
session is done.

**1. `condition_checker.py` — `ConditionPoller._tick()` cancellation race
(FIXED, verified).** `_tick()` used to read `item.cancelled` and write
`item.fired`/`item._timer` with **no lock held at all**, while
`cancel()`/`shutdown()` mutate those same fields **under** `self._lock`.
`checker()` can block up to 5s (a real PowerShell subprocess) -- if the
user cancels while `_tick()` is mid-`checker()` call, the cancel stops the
CURRENT timer correctly, but `_tick()` then finishes, sees the condition
still false, and reschedules by creating a brand new timer and assigning
it to `item._timer` -- silently reviving a poller the user just told it
to stop, invisible to the `cancel()` call that already returned. A second,
narrower instance of the identical race existed at `start()`'s *initial*
timer setup (item published to `self._items` before `item._timer` was
assigned, both outside the lock) -- fixed the same way.

Fix: every read of `item.cancelled` and every write to
`item.fired`/`item._timer` now happens inside a `with self._lock:` block,
in the same critical section as the write it's guarding -- matching
`scheduler.py`'s `_run()`, which already got this right. `checker()`
ITSELF still runs with the lock released (same as `scheduler.py` never
holds its lock across `on_fire()`) -- a 5s PowerShell call must not block
`cancel()`/`shutdown()` for other items for that whole duration.

Verified with 2 new deterministic tests in
`tests/test_scheduling_and_conditionals.py::TestConditionPollerCancelRace`
that force the exact race window using `threading.Event` (not
sleep/timing, so not flaky) -- **confirmed both tests fail reliably
against the original code and pass reliably against the fix** by
temporarily reverting and re-running, not just reasoned about.

**2. `app_control.py` — `AppController._get_installed_apps()` cached a
failed call forever (FIXED, verified).** `_app_list_cache` was set to `[]`
on ANY failure (subprocess error, timeout, malformed JSON), and
`if _app_list_cache is not None: return` treated that `[]` identically to
a genuine successful (empty) result -- so a single `Get-StartApps` hiccup
(common right after boot, or PowerShell momentarily locked) permanently
degraded every app-launch/app-control action for the rest of the session.
`invalidate_app_cache()` existed but wasn't wired to anything that would
call it.

Fix: `_app_list_cache` is now only ever written on a REAL success. A
failure returns `[]` for that one call and records
`_last_fetch_failure_time`; the next call after `_FAILURE_RETRY_SECONDS`
(10s -- local subprocess, cheap enough to retry fairly often) retries for
real instead of trusting a stale cached failure. Repeated calls within
that window still return `[]` without re-paying the subprocess cost every
time. `invalidate_app_cache()` now also clears the failure timestamp.

Verified with 4 new tests in
`tests/test_app_control.py::TestAppCacheDoesNotPermanentlyCacheFailures`
-- again, **confirmed to fail against the original code and pass against
the fix** by temporarily reverting.

**3. `apis.py` — `LocationCache.get()` had the identical bug (FIXED, NOT
YET test-covered).** A transient failure against `ipinfo.io` got cached
as the all-zero/failed fallback dict forever, permanently degrading every
location-dependent feature (e.g. weather with no city given) for the rest
of the session, with no retry.

Fix: same pattern as `app_control.py` above -- `self._cached` is only
ever set on a real successful fetch; a failure returns the zero-fallback
dict for that call and records `self._last_failure_time`, with a 30s
retry backoff (longer than the app cache's 10s, since this is a real
network call, not a local subprocess -- don't hammer `ipinfo.io` during
an outage, but do recover once it's back).

**Manually verified live** (mocked `requests.get` to fail, then to
succeed after forcing the retry window open, confirmed the second call
actually retried and the result then cached correctly) -- but **no pytest
regression test has been written for this yet**. Next session should add
one mirroring `TestAppCacheDoesNotPermanentlyCacheFailures` before
considering this closed the same way #1 and #2 are.

**4. `voice_pipeline.py` — narrow race window can swallow a Ctrl+K
keypress (NOT STARTED).** Reported: between `self._trigger.clear()` and
`self._capturing = True` in `_record_and_transcribe()`,
`on_hotkey_trigger()` (called from the pynput listener thread) checks
`self._capturing`, sees `False` in that gap, and calls
`self._trigger.set()` again instead of extending the session -- but the
run-loop won't check `_trigger` again until the next session starts, so
that keypress is lost. Reported fix is one line (move
`self._capturing = True` earlier, before the queue-drain/VAD-reset).
Not yet looked at this session -- do this first next time, it's reported
as the smallest of the four.

**Full pytest suite: 442 passed, 1 skipped, 3 xfailed** (up from 0.3.27's
436 passed, 1 skipped, 3 xfailed; +6 new tests: 2 in
`test_scheduling_and_conditionals.py`, 4 in `test_app_control.py`. Zero
regressions elsewhere.)

**Still open going into the next session, in priority order:**
1. Write the `apis.py`/`LocationCache` regression test (fix is in, test
   isn't -- don't let this quietly stay untested).
2. `voice_pipeline.py` Ctrl+K race -- not started at all.
3. (Separate, unresolved discussion, not a bug fix) whether to build an
   offline curated synonym table for graph_router.py, raised and
   deliberately NOT implemented this session over safety concerns about
   a live dictionary API sitting next to the destructive-shadow guard --
   see chat notes, not reflected in any code change here.

**Not verified:** live Ollama/PowerShell round-trips on real Windows,
and the pynput-driven hotkey path in `voice_pipeline.py` (would need a
real keyboard listener thread to exercise, not attempted) -- same
sandbox-only caveat as every other change in this file.

## BETA 0.3.27 — adversarial pass on shadow guard + graph_router: 6 bugs found live, all fixed (chat session, tested not guessed)

**Context:** broad adversarial pass against the deterministic routing
layers (`graph_router.py`, `wcl_resolver.py`, `extractor.py`, 0.3.26's new
shadow guard) — natural/typo phrasing, chains, messy paths, ambiguous
input, prompt-injection-style text, WCL breadth. No Ollama in this
sandbox, so pure-LLM fallback paths (CHAT, "do that again"-style context)
weren't exercised. Everything below was reproduced live against the real
shipped code/data before being fixed, and reverified live after.

**What was already solid, reconfirmed:** the 0.3.26 shadow guard on its
original RESOLVED target cases; chain-splitting; sandbox path-escape
rejection; app-control click/type phrasing; prompt-injection-style text
falling through safely.

**1. "shut up"/"shut it up" → `VOLUME_UP` (HIGH).** The literal opposite
of what was asked, auto-dispatched with zero required slots and no
confirmation gate. Root cause: "shut" appeared nowhere in the Tier A
phrasing corpus, so `graph_router.py`'s tf-idf scoring silently dropped it
as out-of-vocabulary (contributes zero, doesn't lower the score either),
leaving only "up" to score against — which `VOLUME_UP`'s corpus matches
heavily. Fixed by adding real "shut up"/"shut it up" phrasings to
`TOGGLE_MUTE` (`graph_source_data/tier_a_phrasings.py`), giving "shut" a
real, discriminating home in the vocabulary. Rebuilt `toki_graph_db` via
`migrate_to_kuzu.py`. Verified: `shut up`/`shut it up` → `TOGGLE_MUTE`;
`turn it up`/`crank it up`/`make it louder` still → `VOLUME_UP` (no
regression on the legitimate phrasings).

**2. Absolute paths with spaces silently truncated (HIGH).**
`_extract_bare_path()`'s drive-letter regex (`extractor.py`) stopped at
the FIRST whitespace: `"read the file at D:\notes\meeting notes.txt"` →
`D:\notes\meeting` (dropped `" notes.txt"`); `"delete D:\old
files\draft v2.docx"` → `D:\old` (dropped almost everything). Quoting
worked around it, but nothing forced that, and the truncated path then
got resolved/read/deleted silently — no error surfaced, just the wrong
(nonexistent) target. Fixed with a two-pass approach: prefer a
non-greedy match up to a recognized file extension (handles internal
spaces correctly), fall back to end-of-line with trailing-filler-word
trimming ("please"/"now"/etc.) for extensionless folder paths. The
OTHER known bare-path bug (relative filenames over-capturing leading
words, `tests/test_extractor.py::TestKnownOpenIssues`, still xfail) is
the opposite failure direction and is intentionally untouched by this
fix — confirmed it still fails the same way, not regressed further.

**3. Clipboard read/write confusion (MEDIUM).** `"can u tell me whats on
my clipboard"` (a READ) routed to `SET_CLIPBOARD` (a WRITE). Root cause:
"clipboard" was the only word either command's vocabulary shared with the
query (`SET_CLIPBOARD`'s 3 phrasings all repeat "clipboard" more densely
relative to their few other words, edging out `GET_CLIPBOARD` 0.771 vs
0.670 on that single shared dimension), compounded by `"whats"` (typed
without an apostrophe) not matching the existing `"what's"` phrasing at
all — `normalize()` only replaces punctuation with a space, so `"what's"`
tokenizes as `"what"`+`"s"`, a genuinely different token from `"whats"`.
Fixed by giving `GET_CLIPBOARD` real vocabulary on `"whats"`/`"tell"`, the
words that actually carried this query. Verified fixed with zero
regression to `SET_CLIPBOARD`'s own phrasings.

**4. Action verbs on read-only lookalikes (MEDIUM).** `"stop the print
spooler service"` → `FIND_SERVICE`, `"reset network adapter"` →
`NETWORK_INFO`, `"format the usb drive"` → `LIST_USB_DEVICES` — all three
share noun vocabulary (service/network/usb) with a genuinely different
WRITE action the user asked for. `NETWORK_INFO`/`LIST_USB_DEVICES` have
zero required slots, so this silently ran the wrong (harmless-but-wrong)
read instead of asking or falling through to `wcl_resolver.py`, where the
real write command lives (`FIND_SERVICE` was already safe in practice —
blocked by a missing slot, so it asks anyway). Fixed with a new, narrowly-
scoped guard in `graph_router.py`: if one of these three specific
read-only lookalikes wins, but the query also contains a write/action verb
("stop"/"reset"/"format"/etc.) that ISN'T part of that command's own
vocabulary, treat it as a miss (fall through) instead of dispatching.
Checks against the command's OWN vocabulary (not a separate allowlist),
so a future legitimate phrasing that adds one of these verbs to that
command's corpus automatically stops tripping the guard. Verified:
`reset network adapter`/`format the usb drive` now correctly fall
through; `show my network info`/`list usb devices`/`find the print
spooler service` still dispatch normally.

**5. Shadow guard blind to AMBIGUOUS + WCL alias-coverage gap.**
`_check_destructive_shadow()` (0.3.26) only ever checked `RESOLVED` —
`"clean temp files"`/`"wipe the temp files"` resolve `AMBIGUOUS` (tier 1,
two literal alias matches) even though a genuinely destructive
`Clear-TempFiles` candidate sits right in the returned list, so the guard
never got a chance to see it. Root cause traced one layer down:
`wcl_resolver.py`'s AMBIGUOUS branches (all 4 tiers that can return it)
were discarding `danger_level` from each candidate tuple entirely — `(r[0],
r[1])` only — even though the underlying row already carried it as
`r[2]`. Fixed both: `wcl_resolver.py` now returns `(name, syntax,
danger_level)` 3-tuples for every AMBIGUOUS candidate, and
`_check_destructive_shadow()` checks AMBIGUOUS candidates the same way it
checks a RESOLVED result (still deliberately `destructive`-only, not
`caution` — same noise-avoidance rationale as 0.3.26). Verified live:
`clean temp files`/`wipe the temp files` now correctly trigger the
confirmation question; confirmed no false positives reintroduced on
`empty the recycle bin`/`copy the item`/`kill process chrome`.
Separately, confirmed `"make the vm"` (flagged) vs `"create a new vm"`
(not flagged) was a genuine WCL alias-DATA gap, not a logic bug —
`New-VM`'s alias list just didn't include that phrasing. Added
`"create a new vm"`/`"create a vm"`/`"make a new vm"`/`"make a vm"`
directly to `New-VM`'s aliases (both the `windows_command_library
.widened.json` source and the live `wcl_kg/windows_commands_db` graph, via
a direct Cypher `MERGE`/`CREATE`, since that prebuilt db — not the JSON —
is what `wcl_resolver.py` actually reads at runtime). Verified both
phrasings now trigger the guard identically. **Not attempted:** a full
sweep of the WCL dataset's ~1,200 commands for similar missing-phrasing
gaps — this closes the specific reported case, not the general problem.

**6. priority.md #14 (BitLocker) — root cause was narrower than
previously guessed, now fixed.** 0.3.26's entry guessed a systemic
one-word/two-word ("bitlocker" vs "bit locker") normalization gap across
several BitLocker cmdlets. A full scan of the dataset found this shape
(`aliases == ["X X"]`, a single duplicated-word alias) exactly ONCE:
`Lock-BitLocker` had exactly one alias in the entire dataset, and it was
the literal string `"bitlocker bitlocker"` — a duplicated single word,
not two words, and clearly an alias-generation artifact, while every
sibling BitLocker command (`Suspend-`/`Enable-`/`Disable-`/`Resume-`/
`Unlock-BitLocker`) has 6-9 real aliases. Fixed by adding real aliases
(`"lock bitlocker"`, `"lock the bitlocker"`, `"restrict bitlocker"`, etc.)
to both the source JSON and the live graph db, mirroring the sibling
commands' pattern. Verified: `"lock bitlocker"`/`"lock the bitlocker"`
now resolve tier-1 `RESOLVED` (not just fuzzy `AMBIGUOUS`) to
`Lock-BitLocker`, and correctly trigger the shadow guard against Tier A's
`LOCK_WORKSTATION`. **Not fixed:** priority.md's own original test string
`"bitlocker lock mount point D"` (verb sandwiched between "bitlocker" and
"mount point D") still resolves `UNRESOLVED` — none of `wcl_resolver.py`'s
5 tiers handle a prefix-noun + verb + trailing-value word order, only
prefix-verb + trailing-value. This is a narrower, real remaining gap
(worth a dedicated tier if this word order turns out to be common), but
the two much more natural phrasings above are now fixed.

**Data changes to the live WCL graph (`wcl_kg/windows_commands_db`),
applied directly via Cypher `MERGE`/`CREATE` rather than a full rebuild:**
10 new aliases total (6 on `Lock-BitLocker`, 4 on `New-VM`) — pinned by
`tests/test_wcl_resolver.py::TestAllAliasesCaching
::test_alias_count_matches_the_documented_figure` (13,532 → 13,542).

**Graph rebuild:** `toki_graph_db` (Tier A only) rebuilt via
`migrate_to_kuzu.py` after phrasing changes to `tier_a_phrasings.py`
(219 → 225 phrasings, 61 commands unchanged). Verified the rebuild
reproduces existing behavior byte-for-byte on every previously-passing
test before layering the new phrasings on top.

**Full pytest suite: 436 passed, 1 skipped, 3 xfailed** (was 406 passed, 3
xfailed pre-session; +30 new tests across `test_graph_router.py`,
`test_extractor.py`, `test_wcl_resolver.py`, `test_orchestrator.py`; zero
regressions elsewhere). The 1 skip is an environment guard (skips cleanly
if `graph_router`/`wcl_resolver` can't construct, same fail-open pattern
as the rest of the suite).

**Not verified:** live Ollama/PowerShell round-trips on real Windows,
and the CHAT/"do that again"-style pure-LLM fallback paths — same
sandbox-only caveat as every other change in this file.

## BETA 0.3.26 — priority.md #11 architectural fix: destructive-shadow guard (chat session, tested not guessed)

**Context:** 0.3.25.75's entry below explicitly deferred this ("the Tier
A/B priority architecture fix itself — still needed for future
collisions of this shape"). This session did it: confidence-threshold
tuning fixes specific symptom phrases one at a time (already done, see
below), but doesn't stop a *different* untuned phrase from confidently
shadowing a genuinely destructive WCL command tomorrow. This is the
structural fix, not another vocabulary patch.

**Root cause:** `orchestrator.py`'s `process_request()` calls
`GraphRouter.classify()` (Tier A) first, and only ever consults
`WCLResolver` (Tier B/WCL) on a Tier A **miss**. A confident Tier A hit
never got cross-checked against WCL at all, regardless of whether WCL's
answer for the same text was the real, destructive one.

**Fix, in two pieces:**

1. **`tier_a_wcl_map.py` (new file)** — maps each of Tier A's 59 intents
   to the WCL cmdlet name(s) that represent the *same real action*
   (e.g. `KILL_PROCESS` ↔ `Stop-Process`, `EMPTY_RECYCLE_BIN` ↔
   `Clear-RecycleBin`). This is the equivalence signal that lets the
   guard tell "Tier A is right, WCL just cross-lists the same action" apart
   from "Tier A is confidently wrong." Derived by regex over each intent's
   own `template` string, with manual correction for the two cases where
   the regex's first cmdlet match wasn't the real action (`DELETE_ITEM`'s
   template calls `Get-Item` before its real `InvokeVerb('delete')` COM
   call — not `Get-Item` itself; `TAKE_SCREENSHOT`'s first match is
   `Join-Path`, used only to build an output filename). `DELETE_ITEM` is
   deliberately treated as equivalent to `Remove-Item`/`ri`/`rm`/`del`
   even though DELETE_ITEM's own implementation is the *safer*
   Recycle-Bin version of that action — same real-world intent, safer
   method, not worth nagging on the single most common delete phrasing.
   Verified against real WCL data by `tests/test_tier_a_wcl_map.py` (76
   tests) — caught and removed 3 mapped cmdlets that don't actually exist
   in `windows_command_library.json` (`Get-FileHash`, `Select-String`,
   plus reconfirmed `Get-Printer`/`Get-WinSystemLocale`'s already-known
   absence).

2. **`WindowsAIAssistant._check_destructive_shadow()` (new method,
   `orchestrator.py`)** — called right after a Tier A graph hit, before
   it's trusted. Runs `WCLResolver.resolve()` on the same query (cheap
   local graph lookup, no LLM call, so graph-first/LLM-last latency is
   unaffected). If WCL RESOLVES to a `danger_level=="destructive"` command
   whose cmdlet ISN'T a known equivalent of Tier A's pick, that's genuine
   shadowing — instead of dispatching Tier A's answer, TOKI now asks which
   one was meant. Scoped to `destructive` only, not `caution` — `caution`-
   level overlaps (e.g. `COPY_ITEM` vs WCL's own `caution`-rated
   `Copy-Item`, which just IS the same action) are common and would only
   be nagging noise; destructive is where a wrong silent answer actually
   matters.

**Verified live against real (not synthetic) phrasings, cross-checked
against `windows_command_library.json`+`toki_graph_db`:**
- `"change the date"` → previously silently `GET_DATE`; now asks
  (real: `Set-Date`, destructive)
- `"delete the vm"` → previously silently `DELETE_ITEM`; now asks
  (real: `Remove-VM`, destructive)
- `"turn off the dedup volume"` → previously silently `VOLUME_DOWN`; now
  asks (real: `Disable-DedupVolume`, destructive — this is priority.md
  #11's own reported example)
- `"make the vm"` → previously silently `MAKE_FOLDER`; now asks (real:
  `New-VM`, destructive)
- `"delete the partition"` → previously silently `DELETE_ITEM`; now asks
  (real: `Remove-Partition`, destructive)
- **Confirmed NOT flagged (no false nagging):** `"empty the recycle bin"`
  (`EMPTY_RECYCLE_BIN`/`Clear-RecycleBin` — same action), `"copy the
  item"` (`COPY_ITEM`/`Copy-Item` — same action, also `caution` not
  `destructive` so wouldn't trigger regardless)

**Full pytest suite: 406 passed, 3 xfailed** (was 330 passed pre-session;
+76 from `test_tier_a_wcl_map.py`, zero regressions elsewhere).

**Known remaining gap, NOT fixed this session:** priority.md #11's own
`"bitlocker lock mount point D"` example still isn't caught. Traced why:
`wcl_resolver.py`'s alias data always writes "bit locker" as two words,
several BitLocker cmdlets (`Lock-`/`Suspend-`/`Enable-`/`Disable-`/
`Resume-BitLocker`) share the literal alias `"bitlocker bit locker"`, and
none of `wcl_resolver.py`'s 5 resolution tiers (exact/synonym/prefix-strip/
fuzzy) bridge "bitlocker" (one word, how people actually type it) against
"bit locker" (two words, how the data was authored) closely enough —
`resolve()` returns `UNRESOLVED` for this phrase, so my guard (which only
fires on a WCL `RESOLVED` result) never gets a chance to compare anything.
This is a `wcl_resolver.py` alias-normalization gap, separate from and
smaller than #11's routing-priority bug — worth its own pass if compound-
word aliases like this turn out to be common beyond BitLocker.

**Not verified:** live Ollama/PowerShell round-trips on real Windows —
same sandbox-only caveat as every other change in this file.

## BETA 0.3.25.75 — Tier A confidence-threshold bump + two phrasing-collision fixes + LIST_SCHEDULED_TASKS added (chat session, tested not guessed)


**Context:** live-Windows testing (BETA 0.3.25's TESTING_LOG.md) surfaced a
real safety-relevant routing gap — a query matching both a harmless Tier A
command and a correctly-flagged destructive Tier B command lets Tier A win
outright once it clears the confidence threshold, with no check for a
better Tier B candidate. The genuine architectural fix (teach
`_best_command` to defer to Tier B) is still open and deliberately NOT
attempted this session — instead, three narrower, individually-tested
fixes for the specific reported symptoms, chosen because they're safe on
a one-week ship timeline.

**1. `CONFIDENCE_THRESHOLD` 0.4 → 0.5** (`graph_router.py`). Verified via
full pytest sweep at 0.4/0.45/0.5/0.55/0.6/0.65/0.7 — 0.5 is the highest
value with zero test regressions (330 passed, 3 xfailed, unchanged);
0.55+ starts breaking real cases (`LAUNCH_APP` stops resolving "open
steam"/"open vscode", a scheduling test fails). At 0.5, "wipe disk 2"
(score 0.485) now correctly misses instead of confidently returning
`DISK_USAGE`.

**2. `VOLUME_UP`/`VOLUME_DOWN` phrasing dilution** (`graph_source_data/
tier_a_phrasings.py`). Root cause: only 3 phrasings each meant the bare
word "volume" alone was decisive enough to score 0.64 against
`VOLUME_UP` for queries with no real direction word ("volumes volume",
"optimize volume", "update the volume"). First attempt (adding MORE
phrasings containing "volume") made it worse (0.64 → 0.679) by increasing
"volume"'s term frequency further — the actual fix was adding phrasings
that reinforce direction words WITHOUT repeating "volume" ("turn it up",
"crank it up", "turn it down", "lower it"), diluting "volume"'s relative
vector weight. Bare "volume" queries now score 0.396, correctly miss;
every real volume phrase still classifies correctly (0.7-0.9 range).

**3. `OPEN_TASK_MANAGER` phrasing dilution + `LIST_SCHEDULED_TASKS` added
as a real feature, not just patched around.** Same shape as #2 — "what is
the scheduled task" shared only the word "task" with `OPEN_TASK_MANAGER`'s
3 phrasings but that was enough to score 0.584. Diluted the same way
(added "open taskmgr"/"show me task manager"/"open the process manager"
etc., none repeating "task" alone) until the collision scored 0.455
(miss). But rather than leave it a bare miss: `windows_command_library.json`
already had `Get-ScheduledTask`/`Task History` entries with this exact
alias, danger_level `safe`, no admin required — the zero-variable "list
everything" version (`Get-ScheduledTask | Get-ScheduledTaskInfo |
Select-Object TaskName, LastRunTime, LastTaskResult`) was promoted to a
first-class Tier A intent (`LIST_SCHEDULED_TASKS`, added to
`tier_a_commands.json`, `tier_a_phrasings.py`, and `intents_extended.py`'s
dispatch table) so "what is the scheduled task" now runs a real command
instead of asking or missing. 61 Tier A commands now (was 60), 66 total
intents in the LLM-fallback enum (was 65).

**Verification method:** every one of the three changes was checked with
a direct probe script against the exact reported phrases (not just
"tests pass") AND a full `pytest tests/` run after each individual change
— 330 passed, 3 xfailed, unchanged, after all three. Graph rebuilt via
`migrate_to_kuzu.py` after each `graph_source_data/` edit.

**Deliberately not touched this session:** the Tier A/B priority
architecture fix itself (still needed for future collisions of this
shape — this session's fixes are vocabulary-level, not structural), the
generic slot-filler for the remaining 817 matchable-not-runnable WCL
commands, and confidence-threshold tuning beyond the verified-safe 0.5
value.



**The instruction driving this session, verbatim in intent:** fix the
existing CHAT/GENERATE latency problem specifically, using what's already
there — no new frameworks, no new engines, canned replies only where the
answer is genuinely deterministic, and a single contained FTS experiment
against the existing TF-IDF matcher with an explicit keep-if-better/
revert-if-not instruction. Followed exactly; results below.

**Root cause traced, not re-guessed:** `keep_alive: "30m"` was already set
on both Ollama call sites (confirmed by reading orchestrator.py directly)
-- a prior session had already ruled out cold model reload as the cause,
correctly. What hadn't been measured: the actual system prompt sizes.
`_build_category_prompt()` and `_build_thinking_system_prompt()` measured
at ~500-720 tokens each, and Ollama's `/api/chat` has no cross-call
KV-cache reuse via this integration -- every single call re-evaluates
that whole prompt from scratch. On a CPU-only box (no GPU offload,
confirmed via the project owner's own `ollama ps` output showing 100%
CPU in earlier logs), 500-700 tokens of prompt_eval lines up almost
exactly with the observed 18-25 second per-call cost in every real batch
log so far -- this is prompt SIZE cost, not a reload, and not something
the old keep_alive fix could have touched.

**The actual waste, found and fixed:** every CHAT and ASK_CONTEXT turn --
including bare "hey", "hi", "thanks" -- was paying a FULL SECOND LLM call
(`_run_thinking`) just to reword a fixed instruction into one sentence,
on top of the classify() call that already ran to route it there. Live
logs confirmed this directly: 20-30+ seconds for exactly these trivial
inputs.

**Fix:** `extractor.canned_reply()` -- a deliberately narrow, hand-picked
set of PURE greeting/closing phrasings, wired into
`orchestrator._process_single_request()` as the very first check (before
even the scheduling/conditional pre-checks). Matches skip BOTH the
classify() LLM call and the thinking LLM call entirely. Deliberately NOT
a general CHAT shortcut -- test_graph_router.py's own
TestChatNeverGraphHits documents why a broad "CHAT hits skip the LLM"
behavior is unsafe (CHAT needs to stay genuinely open-ended, per the
project owner's own point that jokes/opinions/"what do you think about
X" are legitimately open-ended, not a gap to close). The match set is
narrow enough that real content alongside a greeting word never matches
-- verified directly: "hey what's the weather" and "hi can you open
notepad" both correctly fall through to the real pipeline unchanged.

**Verified end-to-end, not just at the function level:** new tests mock
BOTH `self.router.classify` and `self.router.stream_thinking` and assert
zero calls for a pure greeting -- proving the LLM is actually skipped,
not just that the returned text looks right. A second test confirms
real-content-plus-greeting-word still calls classify() once. Caught and
fixed my own wrong assumption while writing this test: first tried "hey
what's the weather" as the negative case, assuming it would reach the
LLM classify() tier -- it doesn't, because graph_router.classify() alone
already resolves it to GET_WEATHER before the LLM tier is ever reached,
which is correct EXISTING behavior, unrelated to this change. Switched to
"hey who made you" (confirmed to genuinely miss the graph) for a clean test.

**GENERATE_FILE and everything else in CHAT past pure greetings:**
untouched, per direct instruction -- GENERATE is generation by
definition, and open-ended chat (jokes, opinions) is accepted as what
CHAT is for, not treated as a gap.

**No new frameworks added:** confirmed directly -- did not add Rasa,
ChatterBot, Kùzu-Memory, or anything else. The only new code is one
small function in extractor.py plus its wiring, both fully covered by
tests (26 new: 24 unit + 2 end-to-end).

---

## FTS experiment (item #5) -- run once, contained, REVERTED

Ran exactly the scoped experiment requested: swap kuzu's native
`CREATE_FTS_INDEX`/`QUERY_FTS_INDEX` in as a drop-in comparison against
`graph_router.py`'s existing in-Python TF-IDF matcher, on the known
ambiguous/duplicate-syntax cases already flagged in TESTING_LOG.md. Never
touched the real `toki_graph_db` -- copied it to a `/tmp` scratch
location for the whole experiment, deleted afterward. `graph_router.py`
itself was never modified.

**A real mistake I caught and corrected mid-experiment:** first pass
queried FTS across the WHOLE Phrasing node table and found what looked
like a clean win on "wipe disk 2" (FTS surfaced the correct Clear-Disk
phrasing, which TF-IDF never even considers). Investigated why before
reporting it as a win, and found `toki_graph_db` still physically
contains dormant Tier B data (confirmed: `Clear-Disk`'s node has
`tier='B'`) that `GraphRouter.classify()`'s own `_is_dispatchable()`
never actually searches -- Tier B matching moved to a separate,
dedicated `wcl_resolver.py`/`wcl_kg` graph. Re-ran restricted to Tier A
only, matching what `classify()` actually searches today, and that
"win" disappeared entirely (both land on DISK_USAGE once fairly scoped).

**Results, Tier-A-only, fairly scoped:**
- 2 genuine wins: "find files named report" (FTS correctly ranks
  FIND_FILES top; TF-IDF confidently mis-fires to FIND_DUPLICATE_FILES)
  and "read report.txt" (FTS correctly ranks READ_FILE top; TF-IDF
  misses below threshold).
- 2 no-changes: "kill chrome" (both wrong/decline), "show contents of
  report.txt" (FTS ties READ_FILE/GET_CLIPBOARD exactly, still ambiguous).
- **1 real regression on a heavily-tested, currently-correct path:**
  "open notepad" -- current TF-IDF correctly resolves OPEN_ITEM; FTS's
  top-ranked answer is the WRONG LAUNCH_APP, which would break the
  existing, extensively-tested open-cascade disambiguation (see
  test_open_cascade_integration.py).

**Verdict, per the instruction given ("if yes keep it, if not revert"):
REVERTED.** A wholesale swap-in trades 2 real fixes for at least 1 real
regression on a core, well-tested path -- not a clean win. Scratch db
deleted, no project files touched. If the 2 genuine wins matter enough to
chase later, the honest next step would be using FTS as a secondary
signal only when TF-IDF's own confidence is already low, not a
replacement -- but that's new design work belonging to its own session,
not this contained experiment.

---

## BETA 0.3.24 — voice + mood-mark feature merged forward onto the 0.3.23 base

**What this was:** you uploaded a separate branch
(`TOKI_BETA_0_3_22_voice_moodmark.zip`) built on top of 0.3.22 — before
this session's own 0.3.23 narration-removal and the earlier leak fixes —
with a real voice input pipeline and the animated mood-mark icon feature
(the "abstract hypnotic mark with mood states" direction, plus a
draggable always-on-desktop overlay). Confirmed the two branches only
overlapped in one file (`app.py`) and diverged nowhere else structurally
— `orchestrator.py`'s diff between the two was entirely the 0.3.23
narration-removal changes, nothing voice-related touched it. `app.py`'s
diff was a clean superset: every line in the current 0.3.23 `app.py`
was still present verbatim in the voice branch's version, plus its
additions — so merging was a straight file-level bring-forward, not a
manual reconciliation.

**Brought forward:**
- `mood_mark.py`, `mark_visual.py` — the animated in-window icon,
  mood states tied to real app state (idle/classifying/executing/
  generating/stopped), not decorative.
- `toki_desktop_mark.py` — same mood, as a draggable always-on-top
  desktop overlay outside the app window, parked wherever last dragged,
  grows/animates while listening or working.
- `voice_pipeline.py` — wake-word (`openwakeword`) → VAD (Silero, run
  directly via onnxruntime rather than the official `silero-vad` pip
  package, which would've pulled in torch+torchaudio for no reason) →
  transcription (`faster-whisper`, CPU-only int8). Entirely local/
  offline, fails soft: no mic/deps/models just means voice doesn't run,
  typed input is unaffected either way.
- `install_autostart.py` — standalone Windows autostart registration,
  untouched from the source branch.
- `app.py` replaced wholesale with the voice branch's version (verified
  superset, see above) — wires `MoodMark`/`DesktopMark`/`VoicePipeline`
  into the existing UI, transcribed speech goes through the exact same
  `_send_text()` path as typed input.
- `requirements.txt` — appended the new dependency block
  (`PyQt6-WebEngine`, `openwakeword`, `faster-whisper`, `sounddevice`),
  same reasoning/comments as the source branch, on top of the existing
  file rather than replacing it.
- `priority.md` — a sprint-priority doc that existed on that branch but
  not on this one's lineage; brought forward, see the flag below.

**Cleanup while in there:** `toki_desktop_mark.py` had one unused import
(`QSize`) — dropped. `voice_pipeline.py`'s `sounddevice` import flagged by
pyflakes is NOT dead code — it's a deliberate availability probe with its
own `# noqa: F401` comment (checks the dependency is importable before
`_setup()` proceeds; the real usage is a separate import later in
`_audio_callback`/`run`). Left alone, same "duplication with a documented
reason" category as `normalize()`/`_escape_ps_slot()` from an earlier
session.

**Verified:** `304 passed, 3 xfailed`, unchanged — nothing in the test
suite touches `app.py`/voice/mood-mark (no PyQt6 GUI tests exist either
branch), so this confirms the merge didn't break the importable, testable
core, not that the voice/mood-mark UI itself works. That needs a real
Windows run with a mic.

**🔴 Flagging, not yet fixed — inherited from the source branch's
`priority.md`, and independently confirmed against this session's own
live batch log:** destructive Tier B commands are getting silently
shadowed by harmless Tier A commands with overlapping keywords.
Confirmed in the exact `batch_test_prompts_v2.py` transcript pasted this
session: `"wipe disk 2"` → `DISK_USAGE` (should be `Clear-Disk`, flagged
destructive), `"bitlocker lock mount point D"` → `LOCK_WORKSTATION`
(should be `Lock-BitLocker`, destructive), `"disable dedup volume on E"`
→ `VOLUME_UP` (should be `Disable-DedupVolume`, destructive). Per that
branch's `priority.md`, root cause is that Tier A and Tier B are scored
in separate pools in `graph_router.py` by design (correct — stops Tier B
noise from drowning out Tier A), but nothing stops a same-keyword Tier A
command from confidently winning even when the correct answer is Tier B.
Not a UX nicety — this is a real command dispatching as the WRONG,
differently-scoped command, and it happens to land on destructive
territory. Worth prioritizing over further feature work.

---

## BETA 0.3.23 — LLM narration removed from every command-shaped dispatch path (product decision, not a bug fix)

**Why:** real usage of this app is "get something done" or "look something
up" — not conversation. Every pure-command dispatch was paying a full
Ollama round trip (18-30s, `prompt_eval`-dominated per the live Windows
log two sessions ago) just to phrase a sentence confirming something the
graph/WCL router already matched with total confidence, deterministically,
with zero LLM involvement. That's backwards: the slowest part of the
pipeline was being spent on the part that needed the least judgment.

**What changed, in `orchestrator.py`'s `_dispatch()` and the "ask for more
detail" branches in `_process_single_request()` / `_handle_missing_or_dispatch()`:**

- `powershell` / `app_control` kinds: no more `_start_thinking()` call at
  all. Confirmation is a bare `"Done."` — literal, not templated, per
  product decision (considered a more descriptive
  `_fallback_narration()`-based sentence, went with plain `"Done."`
  instead).
- `api` kind (weather/time/search/location): the biggest actual latency
  win. `apis.py`'s own methods already return a complete, correct,
  human-readable string (e.g. `"Lahore: 22°C, wind 10 km/h"`) — the old
  code took that correct string, handed it to Ollama, and asked it to
  "narrate this in one sentence," which is asking a model to paraphrase
  an already-finished answer and occasionally get it wrong in the
  process. Now the real result is returned directly. Zero LLM calls left
  anywhere in the weather/time/search/location path.
- `schedule` / `cancel_scheduled` / `conditional` kinds: kept their real
  deterministic confirmation text (schedule ID, cancel target, watch ID —
  all facts, not filler) but dropped the LLM-generated sentence that used
  to prefix it. Also added the dispatched intent name into the
  `[Scheduled]`/`[Condition met]` history notes written when a scheduled
  item actually fires later, so history still shows what really ran
  without needing a narrated sentence to prove it (a test relied on the
  old narration incidentally leaking the intent name — fixed properly
  instead of re-adding narration to satisfy it).
- Every "ask for more detail" path (missing slot, below-threshold graph
  candidate, open-target cascade finding neither an app nor a file) now
  returns its already-existing canned/deterministic question directly,
  no LLM-generated prefix. There were three near-identical copies of the
  missing-slot version of this pattern scattered across the file — all
  three fixed the same way.

**What still uses the LLM, unchanged, on purpose:** `CHAT` kind,
`ASK_CONTEXT` kind, and `GENERATE_FILE`'s `generate` kind. These are the
only three places an LLM is actually doing something a deterministic
template can't — open-domain conversation, or writing genuinely novel
content. Per the product framing this session: if someone wants a real
conversation or wants something generated, they're probably going to
Claude for that anyway, not TOKI — TOKI's LLM should be the rare
exception, not a step in the common path.

**Verified:** `304 passed, 3 xfailed`, unchanged from every prior session's
baseline. This is a big enough change to the core dispatch loop that it's
worth a real Windows run of `run.ps1` / `batch_test_live.py` to confirm the
per-command latency actually dropped the way it should on paper — sandbox
timing doesn't reflect real Ollama call cost either way, so the *absence*
of slowness here doesn't prove anything; it's the *presence* of it on a
real box, previously measured at 18-30s per command, that this change is
meant to eliminate.

---

## BETA 0.3.22 — one command replaces the 12-command setup+test flow (`run.ps1`)

**What changed:** `run_all_tests.py` (added last session) already
collapsed pytest + all 5 live batch files into one command, but you still
had to hand-run venv creation, activation, and `pip install` yourself
first. `run.ps1` now wraps all of it: creates `.venv` if missing
(`py -3.12 -m venv .venv`), installs/verifies `requirements.txt` against
the venv's own `python.exe` directly (no `Activate.ps1` needed — the
script calls `.venv\Scripts\python.exe` explicitly), then runs
`run_all_tests.py`. Idempotent: re-running it when `.venv` already exists
skips straight to the install-verify + test steps, so it's safe as the
one command you always run, first time or the hundredth.

```
.\run.ps1                    # everything
.\run.ps1 -PytestOnly         # fast suite only, no Ollama
.\run.ps1 -LiveOnly           # live batches only, skip pytest
.\run.ps1 -Model llama3.2     # any other pulled model
```

Flags forward straight through to `run_all_tests.py`'s own
`--pytest-only` / `--live-only` / `--model`. Documented in README.md's new
"Run the tests" section, right under the existing "Run it" section.

**Verified in sandbox:** `python -m pytest tests -q` still `304 passed,
3 xfailed` after adding the script (it doesn't touch any app code, purely
additive). The venv-creation and `py -3.12` path can't be exercised here
(no Windows), same caveat as the last two sessions' Windows-only claims —
first real run on your machine is the actual test of the venv/install
steps.

---

## BETA 0.3.21 — code cleanup pass + the 21-error kuzu lock bug fully closed (Claude, sandboxed) — 304/3 stable, 5 more leak sites found and fixed beyond the one patched last session

**Context:** requested as a general "clean up and optimize" pass over the whole
codebase (`app_control.py` excluded — off-limits pending the voice rebuild).
Baseline before touching anything: `304 passed, 3 xfailed` in sandbox.

**Dead code removed (via `pyflakes`, not a guess):**
- Unused imports: `sys` (`batch_test_live.py`), `typing.Dict/List/Any`
  (`migrate_to_kuzu.py`, now dropped entirely — nothing in that file used
  them), `extractor.get_sandbox_roots` (`generator.py`), `pathlib.Path` and
  `condition_checker.CHECKABLE_CONDITIONS` (`orchestrator.py`),
  `PyQt6.QtGui.QFont` (`app.py`).
- Two unused local variables in `tests/test_scheduling_and_conditionals.py`
  (`item1`, `result` — captured return values never asserted on).
- Re-ran `pyflakes .` after: clean except `app_control.py` (skipped per
  scope), which still has one unused `typing.Any` import if that file is
  ever back in scope.

**Investigated but deliberately NOT touched — duplicate helper functions:**
`normalize()`/`content_words()` exist in both `graph_router.py` and
`migrate_to_kuzu.py`, and `_escape_ps_slot()` in both `orchestrator.py` and
`app_control.py`. All are intentional, already documented in their own
docstrings as deliberately decoupled (the migration script isn't supposed
to import runtime modules). Not a cleanup target — merging them would add
a coupling that was explicitly designed against.

**Investigated but deliberately NOT touched — data-level duplication:**
confirmed the "near-duplicate commands" issue flagged in an earlier
STATUS.md entry (Item 4, "Where it still lacks") is real: 37 groups of
entries in `graph_source_data/windows_command_library.json` share
identical `syntax` strings (e.g. 3 separate nodes all mapping to
`Clear-Host`). This is graph *data*, not code — deduping it means editing
the source JSON, re-running `migrate_to_kuzu.py`, and re-validating hit
rate against the rebuilt graph, which is a bigger and riskier decision
than a code cleanup pass. Flagged, not actioned.

**The real find — the 21 "Could not set lock on file" errors from your
last live Windows run, root-caused and fixed:** the fix documented in
this file's own scheduling-and-conditionals entry only patched ONE of six
places that create a `WindowsAIAssistant()` (each opens its own `kuzu`
connection to `toki_graph_db` in `__init__`) without ever calling
`.shutdown()`. The other five, all leaking:

- `tests/test_open_cascade_integration.py` — fixture returned the
  assistant with no teardown at all.
- `tests/test_wcl_slot_filling_integration.py` — same, in both its
  fixture and one raw in-test instantiation. Extra wrinkle here: the
  fixture nulls `graph_router` to force a wcl_resolver-only path, which
  means the *default* `assistant.shutdown()` pattern isn't enough — the
  discarded `graph_router` has to be closed explicitly before it's
  nulled, or it leaks anyway even with a teardown in place. Also had to
  guard against tests in this file swapping `wcl_resolver` for a fake
  with no `.close()` method — teardown now closes the real resolver
  object captured at fixture setup, not whatever the test body leaves
  behind.
- `tests/test_orchestrator.py` — two tests in
  `TestShutdownReleasesGraphConnections` null one resolver, then call
  `shutdown()`, which only closes the one still assigned — the nulled one
  was leaked before ever being closed. Fixed by closing it explicitly
  before nulling.
- `tests/test_batch_test_live.py` — three raw instantiations, no cleanup
  path at all. Added explicit `.shutdown()` calls at the end of each test.

Full suite re-run after all six fixes: `304 passed, 3 xfailed` — identical
to baseline, nothing else changed behaviorally. **Caveat:** this was all
verified in the Linux sandbox, where (per the original bug report) kuzu's
lock enforcement is looser than on Windows — the sandbox passing was never
proof the leaks were safe, and by the same token isn't proof this fix is
complete either. Needs a real re-run of `python -m pytest tests -v` on
your machine to confirm the 21 errors are actually gone.

**Functionality review of your real Windows `batch_test_live.py` run**
(not yet acted on, flagged for you to prioritize):
1. `thinking` calls average ~20-30s each, and it's `prompt_eval` time
   dominating (not `eval`/generation) — the prompt itself is the
   bottleneck. The "ASK, declined to guess" path still pays this full
   cost just to say no; if more of that path can be caught
   deterministically pre-LLM (the way bare-time-expression detection
   already is), those calls could be skipped entirely.
2. Chained requests re-run a full `thinking` call per segment,
   sequentially — the 3-segment chain in the live log took 71s, each
   segment paying its own ~20s `prompt_eval`. Worth checking whether
   segments that already resolved via graph_router pre-chain-split need a
   second LLM call at all.
3. Inconsistent app-name resolution: `"launch chrome"` → `OPEN_ITEM`
   cleanly, but `"open vscode"` / `"open VS Code"` → ASK, despite
   `TestLeadingInitialsAbbreviationTier` proving vscode-abbreviation
   matching works elsewhere in the codebase (`app_control`'s cascade).
   Same intent, but the fuzzy-match logic isn't reachable from every
   phrasing path that should hit it.

---

## BETA 0.3.20 — versioning made explicit (VERSION file, bumps every session going forward), plus a single combined test runner replacing 6+ manual commands

**Versioning:** added a `VERSION` file at the project root (currently
`0.3.20`) as the one place the current build number lives — no other file
had a hardcoded version string to keep in sync (checked main.py/app.py/
orchestrator.py directly, nothing there). Going forward, every session
that touches the code bumps this file and the folder name together, so
the two never drift apart. Project renamed from `TOKI_BETA_0.3.19` to
`TOKI_BETA_0.3.20` accordingly.

**Combined test runner (`run_all_tests.py`):** previously, running
everything meant 6+ separate manual commands — `pytest tests/`, then for
each of 5 prompt-generator scripts, run it once to write its `.txt`, then
run `batch_test_live.py` on that file. `run_all_tests.py` now does all of
that in one command: `python run_all_tests.py`. Flags for partial runs:
`--pytest-only` (skip Ollama entirely, just the fast suite),
`--live-only` (skip pytest), `--model` (passed through to
batch_test_live.py, same as before).

**Deliberately runs each stage as a separate subprocess, not in-process:**
this is a direct lesson from the kuzu lock-error bug found and fixed
earlier this session (leaked `WindowsAIAssistant` instances holding the
graph db open on Windows's strict single-writer lock). `batch_test_live.py`'s
own `main()` never calls `.shutdown()` either — running each prompt-file
batch as its own OS process guarantees that connection is released on
process exit regardless of what any individual script remembers to clean
up, which is a stronger guarantee than trying to close everything
correctly in-process across 6 different scripts.

**What this does NOT do:** score live batch results as pass/fail. Those
stay transcripts for a human to read, same as every prior run —
correctness on ambiguous classification calls needs a human eye, and
auto-scoring against a fixed "expected intent" list would just re-create
the same over-confident-mismatch problem found earlier in this project's
own testing methodology (see the 22-vs-7 mismatch correction from an
earlier session). This script only removes the manual-command tedium,
not the judgment step.

**Verified in sandbox:** `python run_all_tests.py --pytest-only` runs
cleanly, correct exit code, correct version string in the summary — 304
passed, 3 xfailed. The `--live-only` path's file-naming logic (each
generator's output is always `{script_stem}.txt`) verified directly
against `batch_test_prompts_v2.py`. The actual live-Ollama-backed
batches still need to be run on your machine, same as always — nothing
about needing a real Ollama server changed.

---

## Early history (BETA 0.1 – 0.3.20), condensed

Full narrative detail for this range has been condensed here — every
bug below was found, root-caused, and fixed/verified in its own
dedicated session at the time; none of it is still open. Kept as a
timeline of what shipped and why, not a live status report.

**Architecture milestones:**
- **BETA 0.2–0.3**: first fixes from actual live runs — a critical
  PowerShell command-injection bug across ~25 templates, `OPEN_ITEM`'s
  broken template, `LAUNCH_APP` losing to `OPEN_ITEM` on bare "open
  <app>" phrasing, a Wikipedia URL-encoding bug, the documented LLM
  classification fallback restored after it had silently stopped firing.
- **BETA 0.3.1–0.3.3**: history-poisoning fix (plain chat no longer
  fabricated "I did X" action claims), a visible graph-status diagnostic
  added, then the actual root cause found — the LLM was narrating fake
  completed actions because a pre-LLM gate wasn't real; fixed with an
  actual gate using live command data, not a guess.
- **BETA 0.3.4–0.3.8**: four execution-layer bugs (`.exe` suffix
  breaking `Stop-Process`/etc., a `LAUNCH_APP` injection bug reintroduced
  from BETA 0.2, trigger-word regex gaps), the app/file/ask fallback
  cascade built (`extractor.resolve_open_target`, still in use today —
  see 0.3.48's app-existence-check fix above for its most recent
  extension), chain-split viability checking added, `.exe` graph-routing
  fix, on-disk `FileIndex` added, narration/action divergence fixed at
  the root, anaphora resolution ("now open it") implemented,
  `LIST_INSTALLED_APPS` added, 28 tests restored after a prior session's
  regression, 3 test-isolation bugs fixed from a live Windows pytest run.
- **BETA 0.3.11–0.3.15**: bare "and" as a safe chain-split boundary,
  target_memory.py's click-to-teach store built independently and given
  test coverage, a real chain-split gap found and deliberately left
  unfixed pending a proper redesign (not patched over), the WCL
  slot-filler's actual blocker fixed (resolver required matching the
  WHOLE sentence, not just the alias).
- **BETA 0.3.16–0.3.20**: a kuzu lock-error bug (fixed directly by the
  project owner), `shutdown()` wired into `WindowsAIAssistant`,
  `batch_test_live.py` found to never actually test chain-splitting AND
  separately found to be silently swallowing ~2/3 of every prompt list
  as stale-question answers (`self._pending` not reset between batch
  prompts) — both root-caused and fixed, since the second bug meant
  every prior "live verification" run using that tool was measuring the
  wrong thing. Versioning made explicit (`VERSION` file, a bump every
  session from here on) and a single combined test runner
  (`run_all_tests.py`) replaced 6+ manual commands.
- **Scheduling + conditional commands implemented**: `scheduler.py` /
  `condition_checker.py` built from scratch (in-process only, does not
  survive TOKI closing — see 0.3.48's `SET_TIMER` entry above for the
  most recent addition on top of this). Conditionals honestly limited to
  what could actually be read (battery level only, at the time) rather
  than pretending to monitor things with no real check behind them.

**Recurring themes across this whole range, still true today:** every
fix was verified directly against the real pipeline (not assumed), most
sessions found and disclosed at least one thing that was NOT fixed
rather than papering over it, and "verified live on Windows/Ollama" vs.
"verified in this sandbox" was always stated explicitly — several bugs
in this history were things a live Windows run caught that sandbox
testing alone had missed.

---

## ⚠ Everything below this point predates the two-tier rebuild

The original single-tier graph build (one confidence check against Tier
A + Tier B combined, `CONFIDENCE_THRESHOLD = 0.9`) no longer exists.
`graph_router.py` has run two separate scoring passes (category, then
command, both Tier-A-only) since BETA 0.3.1, with Tier B/WCL matching in
its own separate `wcl_resolver.py`. Current threshold is `0.4` (see
`graph_router.py`, right above where it's defined, for the reasoning).

The specific historical command-count figures from this era (once
corrected to "62 Tier A intents / 259 zero-variable WCL commands / 876
commands needing variable-filling") are themselves now stale again —
actually counted this session: **80** Tier A intents across
`intents.py`/`intents_extended.py`/`intents_app_control.py` combined.
The WCL-side numbers haven't been reverified this session. Treat any
specific count in this project's older docs as "true when written," not
current fact, unless verified against the live code.

**Still genuinely true today, not just historically:**
- No generic slot-filler exists for WCL commands needing 1+ variables
  filled in — `extract_slots()` is hand-written per intent name. This
  was the explicitly agreed-on next milestone as of the pre-rebuild era
  and, as far as this session's work touched, still is.
- Live Ollama / real Windows verification remains something every
  session has to flag honestly rather than assume — this session (see
  BETA 0.3.48/0.3.49 above) ran everything it could against the real
  `orchestrator.py`/`graph_router.py` in a Linux sandbox with no Ollama
  and no PowerShell, same limitation as every session before it.

See `How to run it` below for setup; the capability/limitation lists
that used to follow it here (`Capabilities`, `Where it still lacks`)
were specific to the pre-rebuild single-tier architecture and have been
removed rather than left to misrepresent the current one — the
STATUS.md entries above (search this file for the most recent `## BETA`
headers) are the current, accurate record of what TOKI can do and
where it's still gapped.

## How to run it

Requires **Windows** (PowerShell/pywinauto-dependent) with **Ollama** installed and running.

```bash
pip install -r requirements.txt          # PyQt6, requests, kuzu (+ pywinauto/comtypes on Windows)
ollama pull phi4-mini                    # or whatever model you pass to main.py/app.py
ollama serve                             # must be running on localhost:11434
python3 main.py
```

The graph DB (`toki_graph_db/`) is already built and checked into this folder. If you ever change
`intents.py`/`intents_extended.py`/`intents_app_control.py` or drop in an updated
`windows_command_library.json`, rebuild it:

```bash
python3 migrate_to_kuzu.py
```

No graph DB present → the app still runs, just falls back to LLM-only classification for
everything (graph_router.py fails open, see its module docstring). In practice, per BETA 0.3.46
above, Ollama is now the rare path rather than the common one — see that entry for what happens
on a miss instead.
