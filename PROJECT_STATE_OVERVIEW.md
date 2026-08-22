# TOKI — project state overview (as of BETA 0.3.37, checkpoints 1+2 merged)

> **Stale notice:** this snapshot hasn't been refreshed since BETA
> 0.3.37 — the project is at BETA 0.3.49 now, 12 versions later
> (search-first fallback, real timer/reminder support, app-existence
> confidence checks, macro/dictation disambiguation, among others — see
> STATUS.md's most recent entries). Numbers and specifics below may not
> match the current code; treat this as historical framing of *how the
> system is structured*, not a source of current facts.
>
> Also: this file, like the old README, used to describe `app.py` as
> the UI — that's now fixed in `README.md` (widget-only, confirmed
> permanent, not transitional). If anything below still references
> `app.py`/`ChatBubble`/`MainWindow`/`Worker`, read it as describing the
> pre-widget UI, not the current one.

This is a **structured snapshot**, not a changelog — `STATUS.md` (3,500+
lines) is the chronological narrative of every session's work, in order,
with full reasoning. This document instead answers three questions
directly: what does the system actually do, what does it have vs. not
have right now, and — since a session found real safety bugs — what
changed because of that (nothing was removed; things were found broken
and fixed, and capability only ever went up).

If you're picking this project back up in a new chat, read this file
first, then jump into `STATUS.md`'s most recent entries for the full
detail on anything that matters to you.

---

## 1. What TOKI actually is, and how a message flows through it

TOKI is a Windows desktop assistant (PyQt6 app) that takes a typed or
spoken message and either runs a real PowerShell command, calls a small
set of local tools (weather, search, app control, file generation), or
falls back to a local LLM (Ollama) for open-ended chat. It deliberately
has **no permission dialogs** — the design philosophy (`README.md`,
`orchestrator.py`'s own module docstring) is that safety comes from
**not auto-running things that aren't confidently safe**, a sandboxed
filesystem boundary (`D:\` and the real Desktop only), and an
always-visible Stop button — not from asking "are you sure? y/n" on
every action.

**The pipeline, in the order a message actually travels through it**
(`orchestrator.py::process_request`):

1. **Canned replies** — a handful of greetings/thanks get an instant,
   fixed response with zero model calls (latency optimization).
2. **Scheduling / conditional pre-check** (`scheduler.py`,
   `condition_checker.py`) — "in 10 minutes" / "when the CPU drops below
   X" style requests get parsed and handed to a background
   timer/poller, separate from the main classification pipeline.
3. **Tier A: the graph router** (`graph_router.py`) — a small, curated
   set of **65 hand-written intents** (file/process/system/info/app-
   control/generate/chat), each with its own natural-language phrasing
   corpus, matched via TF-IDF cosine similarity against a prebuilt Kùzu
   graph database (`toki_graph_db/`). Fast, deterministic, fully
   offline. A confidence threshold and several purpose-built guards (see
   §3) decide whether a match is trusted or treated as a miss.
4. **Tier B: the WCL resolver** (`wcl_resolver.py`) — only consulted
   when Tier A misses. Matches against **1,160 real Windows
   command-library entries** (`wcl_kg/windows_commands_db`) through an
   ordered cascade of increasingly-loose tiers (exact alias match,
   trailing-value stripping, abbreviation retry, verb-noun bracket
   matching, leading-word-order swap, fuzzy fallback) — see §2 for the
   full list. Returns `RESOLVED`, `AMBIGUOUS`, or `UNRESOLVED`, always
   with `danger_level` attached.
5. **The destructive-shadow guard** (`orchestrator.py::
   _check_destructive_shadow`) — if Tier A DID produce a match, this
   independently asks WCL "is there also a genuinely destructive command
   for this same phrase?" and, if so, asks the user a clarifying
   question instead of silently trusting Tier A's guess. This is the
   single most safety-critical piece of logic in the app.
6. **WCL auto-dispatch eligibility gate** — a RESOLVED WCL command only
   becomes directly runnable if `danger_level == "safe"` (regardless of
   variable count) — see §2 for exactly what's eligible today.
7. **Slot extraction** (`extractor.py`) — regex-only, no LLM involved,
   for both Tier A intents and eligible WCL commands. If a required
   value can't be confidently pulled from the message, the system
   **asks a fixed follow-up question** rather than guessing.
8. **LLM fallback** (`OllamaRouter` in `orchestrator.py`) — anything
   that falls through all of the above (a genuine miss, or an
   ineligible/ambiguous/dangerous WCL match) goes to a local Ollama
   model for open-ended handling.
9. **Dispatch** (`orchestrator.py::_dispatch` → `executor.py`) — actually
   runs the PowerShell command (as a real, killable subprocess) or calls
   the relevant tool (`apis.py` for weather/search/location,
   `app_control.py` for UI Automation, `generator.py` for file writes).

---

## 2. What it HAS — concretely, right now

**Tier A (TOKI's own 65 intents):** file operations, process control,
system info, app launching/control (via real UI Automation coordinates,
never guessed), one file-generation intent, one chat intent. Fully
covered by hand-written phrasing corpora and dedicated extraction logic
per intent.

**Tier B (WCL — the 1,160-command Windows library), auto-dispatchable
subset, exactly as of this session:**
| danger_level | 0 vars | 1 var | 2 vars | 3+ vars | **auto-dispatchable now** |
|---|---|---|---|---|---|
| safe | 271 | 298 | 61 | 3 | **630** (0/1/2-var only) |
| caution | 8 | 86 | 45 | 4 | 0 (deliberately — see §4) |
| destructive | 5 | 115 | 90 | 174 | 0 (deliberately — see §4) |

Everything in that 630 goes through the SAME extraction and dispatch
path as Tier A intents — same sandboxing, same missing-slot-question
fallback, same injection protections (see §3).

**WCL resolution tiers (in `wcl_resolver.py`, tried in this order):**
1. Exact alias match
2. Trailing-value stripping (`"stop the print spooler"` → alias `stop`
   + value `the print spooler`)
3. (ambiguous variant of tier 1)
4. Fuzzy/loose fallback (returns candidates, never auto-dispatches)
5. (ambiguous variant of tier 2-ish matching)
6. Abbreviation retry (curated fixed pairs — net/network, vm/virtual
   machine, etc. — **not** a live thesaurus API, a deliberate safety
   choice)
7. Verb...noun bracket match (`"stop the print spooler service"` — verb
   and object noun bookend the value)
8. Leading noun+verb swap retry (`"bitlocker lock mount point D"` — same
   idea as tier 2, just tried again with the first two words swapped)

**Safety mechanisms currently in place:**
- The destructive-shadow guard (§1, step 5)
- The `danger_level == "safe"` eligibility gate, applied uniformly
  regardless of variable count (this session's fix — it did NOT used to
  check this for zero-variable commands, see §4)
- `_ensure_quoted_placeholders()` + extended `_escape_ps_slot()` — every
  value substituted into every PowerShell template is now guaranteed to
  land inside a fully-literal, properly-escaped string, regardless of
  whether the source template itself was written with quotes (this
  session's fix, see §4)
- A categorical blocklist for variable names representing literal
  code/scriptblock content, checked at 3 separate entry points so it
  can't be bypassed via the follow-up-question path (this session's
  fix, see §4)
- A path-variable allowlist (`_WCL_PATH_VAR_NAMES`) routing 23 distinct
  variable names through `resolve_path()`'s `D:\`/Desktop sandbox,
  rather than trusting them as free text (this session expanded this
  from 6 to 23 names, see §4)
- `_looks_like_real_name()` — a plausibility gate (length, word count,
  no bare pronoun, no whole-word match against TOKI's own action-verb
  vocabulary) applied to every non-path auto-filled value
- A read-only-lookalike guard in `graph_router.py` — a write verb
  ("stop"/"reset"/"format") paired with a read-only intent's own noun
  vocabulary is treated as a miss, not a false match
- Real concurrency safety in `condition_checker.py` (a poller can't be
  silently revived by a race between cancellation and a slow check)
- Failure-vs-success caching correctly separated in `app_control.py`
  and `apis.py` (a transient PowerShell/network hiccup no longer
  permanently degrades a feature for the rest of the session)

**Test suite: 603 passed, 1 skipped (environment-dependent), 2 xfailed
(both pre-existing, unrelated, documented gaps).**

---

## 3. What it does NOT have

- **No generic slot-filler for 3+ variable WCL commands** (181 of
  them — 4 caution, 174 destructive, 3 safe). Would need real
  multi-slot parsing (ordering, boundaries between 3+ values in one
  sentence) — not attempted.
- **No auto-dispatch path for `caution`/`destructive` WCL commands
  without confirmation** — BETA 0.3.38 (checkpoint 3, merged this
  session) changed this: 0/1/2-variable caution/destructive commands now
  pause and show the exact command via a plain-text confirmation
  question (`orchestrator.py`'s `_dispatch_or_confirm()`/
  `_ask_for_confirmation()`) instead of being 100% unreachable. Still
  true, unchanged: 3+ variable commands (181 of them, any danger level)
  remain entirely out of scope — no extraction logic exists for that
  shape.
- **No MODAL confirmation dialogs anywhere** — still a stated design
  choice (`README.md`). The one confirmation flow that does exist (above)
  deliberately renders through `"kind": "chat"`, the same plain-text path
  every other response uses, and a bare Enter or an avatar click both
  count as confirming — not a dialog that has to be dismissed.
- **`FIND_FILES`'s search-by-content sibling intents** haven't been
  re-examined this session.
- **No live Ollama or live Windows testing anywhere in this project's
  recent history** — everything is verified via direct unit/integration
  testing of the Python logic. This is a real, standing limitation, not
  specific to this session.

---

## 3a. Merged this session: two independently-built permission-gate designs, checkpoint 3's kept

Two sessions had each built a confirmation flow for caution/destructive
WCL commands from the same 0.3.37 base, independently, with genuinely
different designs (`_pending_permission`/`confirm_pending_permission()`/
`"kind": "permission_gate"` vs. checkpoint 3's `_pending_confirmation`/
`_dispatch_or_confirm()`/`"kind": "chat"`). Kept checkpoint 3's — single
choke point across every dispatch call site, 16 tests vs. 3, and a
documented disable-and-rerun verification in its own STATUS.md entry.
The other implementation's `orchestrator.py` code was removed outright
(not layered alongside it — two competing gates on the same dispatch
path is a correctness risk, not redundancy). Its two real, unique
contributions — a plugin system and avatar-click UI wiring for the
gate — were preserved by re-splicing the plugin-loading block into
checkpoint 3's `orchestrator.py` and rewriting the avatar-click handler
to submit `""` (already a valid confirm word in checkpoint 3's design)
through the normal `process_request()` path instead of calling a now-
removed method directly. Full detail in `STATUS.md`'s BETA 0.3.38
(three-way merge) entry.

---

## 4a. Closed this session: items 3 and 4 from the old remaining-work list

- **Offline curated synonym table for `graph_router.py`'s Tier A
  out-of-vocabulary-word problem** (was "raised, not decided, no code
  either way" — now built): `synonyms.py`, a small (12-entry) curated
  `SYNONYM_MAP` wired into `classify()`/`classify_or_ask()`'s
  vocabulary-matching step only — the read-only-lookalike action-verb
  guard still runs on the user's literal words, untouched. Confirmed a
  real, complete miss beforehand (e.g. "erase notes.txt" scored 0.0
  confidence against every Tier A command, since "erase" appeared
  nowhere in `TIER_A_PHRASINGS`). `tests/test_synonyms.py` (40 tests) —
  verified by temporarily reverting the `graph_router.py` wiring and
  confirming the tests fail before restoring it.
- **Full natural-language-coverage audit of the WCL alias dataset**
  (was "only two TARGETED audits ... neither verifies every one of
  1,160 commands" — now a real full sweep, not a sample): programmatic
  sweep via `vocab.py`'s own `find_leading_cluster()` against all 1,160
  commands found 230 whose ONLY aliases were mechanically-generated,
  noun-first leftovers from the original alias generator (e.g. "screen
  clear", "audio sound devices") — unreachable by natural phrasing and
  ineligible for automatic synonym widening. `wcl_kg/add_coverage_aliases.py`
  added one hand-reviewed, natural, correctly-ordered alias to each of
  the 230, grounded in that command's own description/intents.
  `wcl_kg/rebuild_graph.py` (new — the existing pipeline scripts under
  `pipeline_scripts_reference/` hard-code a build-sandbox path that
  isn't part of this checkout) rebuilt the live graph from the updated
  data. `tests/test_wcl_coverage_audit.py` (23 tests) caught a real
  self-introduced bug before it shipped (two pairs of the new aliases
  were byte-identical between genuinely-near-synonymous PowerShell
  commands — `foreach`/`%`, `r`/`ihy` — which would have forced an
  avoidable AMBIGUOUS result; differentiated and re-verified). Verified
  against the real, rebuilt graph (not a mock), including confirming
  specific previously-`UNRESOLVED` queries now resolve, one previously
  wrong-command mismatch (`Battery Status` vs `Get-BatteryStatus`) now
  resolves correctly, and a sample of pre-existing resolutions are
  unaffected. Test suite: 587 passed (was 564), 1 skipped, 2 xfailed.

---

## 4b. Closed via checkpoint 1 (done in parallel, merged in afterward)

Checkpoint 1 branched off the same BETA 0.3.37 base as checkpoint 2,
independently, and closed the two other old remaining-work items plus
two bugs found along the way:

- **Numeric-hint extraction strategy for 2-variable WCL commands**
  pairing a path/name with a count/size (e.g. "show me the 5 largest
  files" — no quote, no to/into/as separator, so the two existing
  strategies both missed it). Covers the 5 currently-eligible `safe`
  commands with this shape. `tests/test_extractor.py` — 12 new tests.
- **Documentation pass on `README.md`** — was describing a `v2.11`,
  60-intent version of the app with no mention of `graph_router.py`,
  `wcl_resolver.py`, `condition_checker.py`, `voice_pipeline.py`, or
  `scheduler.py`. Rewritten to match the current architecture; the old
  changelog content is kept below an explicit divider as history only.
- **Live-dispatch-crash fix (12 commands)** — found while building the
  numeric-hint strategy, not on the original list: 12 `safe` WCL
  commands with declared variables had literal, unescaped PowerShell
  braces (`Where-Object`/`ForEach-Object` scriptblocks, `@{...}`
  calculated properties) sitting next to their real `{varname}`
  placeholders in the shipped `wcl_kg/windows_commands_db` — every
  dispatch attempt silently failed `.format()` and reported a fake
  "Done." without running anything. Fixed by escaping every literal
  brace that isn't a declared placeholder. `tests/test_wcl_resolver.py`'s
  `TestSyntaxVariablesFormatIntegrity` pins this against the real
  shipped db.
- **`condition`-variable code-injection gap** — the `?`/`where` WCL
  commands' `condition` variable (substituted directly into a live
  `Where-Object { ... }` scriptblock) wasn't covered by `extractor.py`'s
  code-like-variable blocklist, the same raw-expression-injection shape
  `script_block` was already blocked for. Added. Pinned by
  `TestConditionVariableIsCodeLikeBlocked`.

## 4c. This pass: merging checkpoints 1 and 2 together

Checkpoints 1 and 2 were independent, parallel sessions off the same
base, so they had to be combined by hand rather than just picked:

- `extractor.py` + `tests/test_extractor.py`: checkpoint 1's versions
  used as-is (checkpoint 2 never touched this file).
- `graph_router.py` + `synonyms.py` + `tests/test_synonyms.py`:
  checkpoint 2's versions used as-is (checkpoint 1 never touched these).
- `wcl_kg/windows_command_library.widened.json`: the one real merge
  conflict. Checkpoint 2 branched *before* checkpoint 1's brace-escaping
  fix existed, so its copy of the JSON still had the original, broken
  `syntax` templates for those 12 command IDs underneath its own 230 new
  aliases. Took checkpoint 2's JSON (full alias coverage) and
  re-applied checkpoint 1's escaped `syntax` strings for exactly those
  12 IDs on top — confirmed via direct field diff, not a guess.
- `wcl_kg/windows_commands_db`: rebuilt from the merged JSON via
  checkpoint 2's `wcl_kg/rebuild_graph.py` — 1,160 commands, 13,780
  aliases, same counts checkpoint 2 reported, now with the escaping fix
  included too.
- `tests/test_wcl_resolver.py`: checkpoint 2's version (updated 13,780
  alias-count assertion) as the base, with checkpoint 1's two extra test
  classes appended on top and re-verified against the rebuilt db.
- `README.md`: checkpoint 1's rewrite kept (checkpoint 2 never touched
  it).

Full suite after the merge: **603 passed, 1 skipped, 2 xfailed** —
587 (checkpoint 2's count) + 16 new tests carried over from checkpoint 1
(12 numeric-hint extraction tests, 2 syntax-integrity tests, 2
condition-blocklist tests). No test needed changes beyond the alias-count
assertion checkpoint 2 already had.

---

## 4. What was found BROKEN and FIXED this session

**Nothing described below was ever a working feature that got removed.**
Every item here is a bug that existed in the code before this session
touched it (some for a long time, some introduced earlier in this same
multi-session conversation), found by testing rather than assumed safe,
and closed. Net effect on capability: strictly positive (2-variable WCL
commands are now supported, which they weren't before) and net effect on
safety: strictly positive (every gap below is closed, none reopened).

- **Zero-variable WCL commands could bypass every safety check
  regardless of `danger_level`.** `"run diskpart"` (destructive, zero
  variables) would have silently launched `diskpart` — Tier A misses it
  entirely (so the shadow guard never runs), and nothing else checked
  `danger_level` for the zero-variable case. Fixed: the eligibility gate
  now requires `danger_level == "safe"` uniformly, at every variable
  count.
- **Command injection via unquoted PowerShell templates** — the single
  most serious finding. 297 of 298 currently-eligible "safe"
  single-variable WCL commands had a completely unquoted `{var}` in
  their syntax template, and the plausibility check gating non-path
  values does no character-level filtering at all. Confirmed live that
  an ordinary-looking value could break out of its intended argument and
  run as a separate PowerShell statement. Fixed with a proper quote-
  state-tracking scanner applied universally at dispatch time, plus
  backtick/`$` escaping for the (rarer, but real) double-quoted-context
  variant of the same problem.
- **Two narrower instances of the same underlying "don't trust the WCL
  data blindly" lesson**: 6 commands with unsandboxed path-shaped
  variables (worst: `call {batch_file}`, an arbitrary batch file with no
  path restriction at all), and 15 commands whose variable represents
  literal code content, which quoting alone can't fully protect against
  (PowerShell can implicitly compile a string into a scriptblock for
  certain parameter types). Both fixed with dedicated, tested guards.
- **A real bug in this session's own new code**, caught by its own test
  suite before shipping: the 2-variable extractor's path-shaped-value
  branch skipped the plausibility check entirely, so a whole garbled
  sentence could resolve to a "valid" (if nonsensical) sandboxed path.
  Fixed before merging.
- **A Ctrl+K hotkey race in `voice_pipeline.py`** that had been fixed in
  an earlier session, then reverted by an intervening edit (with a
  comment claiming the opposite of what the code actually did) — caught
  by re-verifying live rather than trusting the accompanying notes, and
  restored, with a test that actually probes the vulnerable window this
  time (the previous replacement tests couldn't distinguish fixed from
  broken).
- **Several routing-correctness bugs** (not safety-critical, but real):
  "shut up" being parsed as a volume-UP command, absolute paths with
  spaces getting truncated, clipboard read/write intent confusion,
  write-verbs silently matching read-only lookalikes, a missing WCL
  alias for BitLocker/New-VM/NetAdapter, an extractor bug that swallowed
  leading verbs into a filename even in the simplest possible case
  (`"delete notes.txt"` → wrongly extracted `"delete notes.txt"` as the
  filename). All fixed and tested — see `STATUS.md`'s earlier entries
  (BETA 0.3.27 through 0.3.34) for full detail on each.
- **Two concurrency bugs and two permanent-failure-caching bugs**
  (`condition_checker.py`, `app_control.py`, `apis.py`) — a cancelled
  background poller could be silently revived by a race condition, and a
  single transient PowerShell/network hiccup used to permanently
  degrade a feature for the rest of the session with no retry. Both
  fixed with real concurrency tests and TTL/retry logic respectively.

---

## 5. Continuation prompt — for a fresh chat picking this up

If you're starting a new conversation to continue this work, paste
something like this:

> I'm continuing work on TOKI, a Windows desktop assistant (PyQt6 +
> Ollama + PowerShell). Read `PROJECT_STATE_OVERVIEW.md` first for the
> current state, then `STATUS.md`'s most recent entries for full detail.
> The test suite currently passes 603/603 (plus 1 environment-dependent
> skip, 2 pre-existing unrelated xfails) — run `pytest tests/ -q` from
> the project root to confirm before making any changes, and again
> after, the same way every fix in `STATUS.md` was verified (a fix isn't
> "done" until there's a test that fails against the old code and passes
> against the new one — several sessions' worth of fixes were verified
> exactly that way, including by temporarily reverting a fix to confirm
> its own test actually catches the regression).
>
> Please pick up from here: [PASTE YOUR NEXT GOAL].
>
> Known remaining work:
> 1. Generic slot-filler for 3+ variable WCL commands (181 commands,
>    genuinely hard — real multi-value parsing, not just quotes/separators).
>    NOTE: of these 181, only 3 are `safe` (auto-dispatch-eligible at
>    all) — 4 are `caution` and 174 are `destructive`, which never
>    auto-dispatch regardless of slot-filling capability (see the
>    unchanged safety boundary below). Building general 3+-slot parsing
>    machinery mainly to benefit 3 commands is a lot of new parsing
>    surface area (real bug risk) for a small guaranteed payoff — worth
>    re-scoping ("just handle those 3 commands specifically" instead of
>    "build a generic 3+ slot parser") rather than attempting generically.
>    This is the only item left on the old remaining-work list — the
>    numeric-hint extraction, documentation pass, synonym table, and
>    full alias-coverage audit items are all closed now (checkpoints 1
>    and 2, merged).
>
> Safety ground rules that shouldn't change without an explicit,
> deliberate decision: no `caution`/`destructive` WCL command auto-
> dispatches at any variable count; every PowerShell template
> substitution goes through `_ensure_quoted_placeholders()` +
> `_escape_ps_slot()`; no interactive confirmation-dialog mechanism
> exists or should be assumed to exist — safety is "don't auto-run it",
> not "ask permission first".
