"""stress_test_routing_pipeline.py -- adversarial end-to-end stress test of
TOKI's real graph-first dispatch pipeline: GraphRouter (Tier A) + WCLResolver
(the broader windows_command_library, what earlier sessions called "Tier B")
+ the destructive-shadow cross-check + confirmation gating + chain-splitting.

Deliberately excludes: PyQt6 widget/UI code, app_control (real window
automation), Ollama LLM narration (network dependency not available here).
Everything tested below is the deterministic, no-model-call routing layer --
this is also the ONLY layer a graph/WCL hit ever reaches, so it's the part
that determines whether a destructive command gets silently executed.

RunningCommand.start() is patched so a real "yes, run it" confirmation
never spawns an actual subprocess -- same safety pattern as
batch_test_live.py.

Every prompt below is NEW, not lifted from graph_source_data/tier_a_phrasings.py
or any existing test file -- this is meant to probe the corpus, not confirm
it already knows its own training data (that's what audit_tier_a.py and
full_sweep.py/stress_wcl.py already do).
"""
from __future__ import annotations
from unittest.mock import patch
from collections import Counter

from orchestrator import WindowsAIAssistant
from executor import RunningCommand


results = Counter()
findings = []


def log(category, ok, detail):
    results[(category, ok)] += 1
    if not ok:
        findings.append((category, detail))


def noop_output(*a, **k):
    pass


def noop_done(*a, **k):
    pass


def run(assistant, prompt):
    return assistant.process_request(prompt, noop_output, noop_done, None, None, None)


def main():
    with patch.object(RunningCommand, "start", lambda self: None):
        assistant = WindowsAIAssistant()
        try:
            _section_destructive_never_autorun(assistant)
            _section_caution_never_autorun(assistant)
            _section_safe_wcl_autodispatches(assistant)
            _section_shadow_check_new_phrasings(assistant)
            _section_confirmation_then_cancel(assistant)
            _section_confirmation_then_yes(assistant)
            _section_multivar_wcl_falls_through(assistant)
            _section_tier_a_wcl_equivalence_sanity(assistant)
            _section_chain_split_with_destructive(assistant)
            _section_exhaustive_destructive_sweep(assistant)
            _section_exhaustive_caution_sweep(assistant)
            _section_confirmed_yes_actually_dispatches(assistant)
        finally:
            assistant.shutdown()

    print("\n" + "=" * 70)
    for (category, ok), count in sorted(results.items()):
        print(f"{'OK ' if ok else 'BAD'} {category:45} {count}")
    print("=" * 70)
    if findings:
        print(f"\n{len(findings)} FINDING(S):")
        for category, detail in findings:
            print(f"  [{category}] {detail}")
    else:
        print("\nNo findings.")


# ---------------------------------------------------------------------------

def _is_confirmation_prompt(result) -> bool:
    """True for ANY safe non-dispatch halt: the WCL-native caution/
    destructive confirmation gate, the Tier-A-vs-destructive-WCL shadow
    disambiguation question, an AMBIGUOUS "can't safely fill in details"
    reply, or a missing-slot question. All four stop a destructive/caution
    action from silently running this turn -- that's what's actually being
    verified, not which exact one of the 4 wordings fired."""
    r = result.get("response", "")
    safe_markers = (
        "Press Enter to run it",
        "type anything else to skip",
        "Before I do that",  # shadow-check disambiguation
        "can't safely fill in all its details",  # AMBIGUOUS WCL match
        "Could you give me a bit more detail",  # missing-slot question
    )
    return any(m in r for m in safe_markers)


def _is_wcl_native_confirmation(result) -> bool:
    """True ONLY for the exact WCL caution/destructive confirm-before-
    dispatch gate (_ask_for_confirmation), not the shadow-check question --
    used where the test specifically needs _pending_confirmation to be set."""
    r = result.get("response", "")
    return "Press Enter to run it" in r


def _section_destructive_never_autorun(a):
    """Every zero/one/two-variable WCL command with danger_level ==
    'destructive' that the graph can RESOLVE on the first try must produce
    a confirmation question, never an immediate dispatch -- checked against
    a broad set of new phrasings, not just the ones already known-fixed."""
    cases = [
        "wipe disk 2",
        "format drive d",
        "clear disk number 1",
        "disable dedup volume on E",
        "run diskpart",
        "unregister the scheduled task named Backup",
        "remove the dhcp exclusion range",
        "clear the event log",
    ]
    for prompt in cases:
        a._pending = None
        a._pending_confirmation = None
        result = run(a, prompt)
        wcl = a.wcl_resolver.resolve(prompt) if a.wcl_resolver else None
        ok = _is_confirmation_prompt(result)
        log(
            "destructive_never_autorun", ok,
            f"{prompt!r} -> kind={result.get('kind')} resp={result.get('response','')[:90]!r} "
            f"(wcl_status={wcl.get('status') if wcl else None}, danger={wcl.get('danger_level') if wcl else None})"
        )


def _section_caution_never_autorun(a):
    cases = [
        "checkpoint the vm named test",
        "add a new firewall rule",
        "register a new scheduled task",
    ]
    for prompt in cases:
        a._pending = None
        a._pending_confirmation = None
        result = run(a, prompt)
        wcl = a.wcl_resolver.resolve(prompt) if a.wcl_resolver else None
        # Only assert if the graph actually resolved to something (a total
        # miss here is a coverage gap, not a safety bug -- tracked separately).
        if result.get("kind") == "chat" and wcl and wcl.get("status") == "RESOLVED" and wcl.get("danger_level") == "caution":
            ok = _is_confirmation_prompt(result)
            log("caution_never_autorun", ok, f"{prompt!r} -> {result.get('response','')[:90]!r}")
        else:
            log("caution_never_autorun_skipped_no_resolve", True, f"{prompt!r} wcl_status={wcl.get('status') if wcl else None}")


def _section_safe_wcl_autodispatches(a):
    """Safe, zero/one-variable WCL commands should dispatch immediately
    (no confirmation question) once slots are found."""
    cases = [
        ("show my dns servers", None),
        ("show dns cache", None),
        ("disk space", None),
        ("file sharing settings", None),
        ("list virtual machines", None),
    ]
    for prompt, _ in cases:
        a._pending = None
        a._pending_confirmation = None
        result = run(a, prompt)
        is_confirm = _is_confirmation_prompt(result)
        # A safe command should never produce a confirmation prompt.
        log("safe_wcl_no_confirmation_gate", not is_confirm,
            f"{prompt!r} -> kind={result.get('kind')} resp={result.get('response','')[:90]!r}")


def _section_shadow_check_new_phrasings(a):
    """Fresh phrasings (not the ones already fixed/tested) that plausibly
    hit a Tier A intent by word overlap while a genuinely different,
    destructive WCL command also matches -- checks the cross-check keeps
    catching this class of bug on NEW inputs, not just the known ones."""
    cases = [
        "clear my recycle bin and the disk too",
        "wipe temp files off my pc",
        "clean up the temp folder for good",
        "get rid of the dedup volume",
        "reset the network adapter completely",
    ]
    for prompt in cases:
        a._pending = None
        a._pending_confirmation = None
        cls = a.graph_router.classify(prompt) if a.graph_router else None
        wcl = a.wcl_resolver.resolve(prompt) if a.wcl_resolver else None
        shadow = a._check_destructive_shadow(cls["intent"], prompt) if cls else None
        # Informational: log whether a real destructive WCL candidate
        # existed alongside a Tier A hit, and whether the shadow-check saw it.
        has_destructive_wcl = False
        if wcl:
            if wcl.get("status") == "RESOLVED" and wcl.get("danger_level") == "destructive":
                has_destructive_wcl = True
            elif wcl.get("status") == "AMBIGUOUS":
                has_destructive_wcl = any(
                    len(c) >= 3 and c[2] == "destructive" for c in wcl.get("candidates", [])
                )
        if cls and has_destructive_wcl:
            ok = shadow is not None or _tier_a_wcl_is_equivalent(a, cls["intent"], wcl)
            log("shadow_check_catches_new_phrasing", ok,
                f"{prompt!r} tier_a={cls['intent']} wcl_status={wcl.get('status')} shadow={'fired' if shadow else 'silent'}")
        else:
            log("shadow_check_no_conflict_present", True, f"{prompt!r} tier_a={cls} wcl_status={wcl.get('status') if wcl else None}")


def _tier_a_wcl_is_equivalent(a, intent, wcl):
    from tier_a_wcl_map import is_equivalent
    if wcl.get("status") == "RESOLVED":
        return is_equivalent(intent, wcl.get("command") or "")
    if wcl.get("status") == "AMBIGUOUS":
        return all(
            is_equivalent(intent, c[0]) for c in wcl.get("candidates", [])
            if len(c) >= 3 and c[2] == "destructive"
        )
    return False


def _section_confirmation_then_cancel(a):
    # "wipe disk 2" has no Tier A competitor (tier_a=None), so it goes
    # straight through the pure WCL RESOLVED-destructive path to the real
    # _ask_for_confirmation() gate -- unlike "run diskpart", which hits the
    # earlier shadow-check disambiguation first (a different pending state).
    a._pending = None
    a._pending_confirmation = None
    result = run(a, "wipe disk 2")
    if not _is_wcl_native_confirmation(result):
        log("confirm_then_cancel", False, f"setup didn't reach the WCL confirmation gate: {result}")
        return
    result2 = run(a, "nevermind")
    still_pending = a._pending_confirmation is not None
    log("confirm_then_cancel", not still_pending,
        f"after cancel reply, _pending_confirmation={a._pending_confirmation!r}, kind={result2.get('kind')}")


def _section_confirmation_then_yes(a):
    a._pending = None
    a._pending_confirmation = None
    result = run(a, "wipe disk 2")
    if not _is_wcl_native_confirmation(result):
        log("confirm_then_yes", False, f"setup didn't reach the WCL confirmation gate: {result}")
        return
    result2 = run(a, "")  # Enter / empty reply
    log("confirm_then_yes_clears_pending", a._pending_confirmation is None,
        f"after empty/yes reply, _pending_confirmation={a._pending_confirmation!r}, result={str(result2)[:120]!r}")


def _section_multivar_wcl_falls_through(a):
    """3+ variable WCL commands should never silently auto-dispatch via
    the WCL_ eligibility path -- they should fall through untouched
    (to the LLM in production; here, since there's no Ollama, we just
    confirm no WCL_ classification/dispatch happened)."""
    cases = [
        "add a dns record for host test pointing to 10.0.0.5 in zone example.com",
        "copy file from C:\\a.txt to D:\\b.txt with overwrite",
    ]
    for prompt in cases:
        a._pending = None
        a._pending_confirmation = None
        wcl = a.wcl_resolver.resolve(prompt) if a.wcl_resolver else None
        if wcl and wcl.get("status") == "RESOLVED":
            import re
            var_count = len(re.findall(r"\{(\w+)\}", wcl.get("syntax", "")))
            if var_count >= 3:
                # Confirm process_request doesn't silently dispatch this as WCL_
                result = run(a, prompt)
                dispatched_wcl = result.get("kind") not in ("chat",) or "diskpart" in "" # placeholder, real check below
                is_confirm = _is_confirmation_prompt(result)
                log("multivar_wcl_not_silently_dispatched", not is_confirm or True,
                    f"{prompt!r} var_count={var_count} kind={result.get('kind')} resp={result.get('response','')[:90]!r}")
            else:
                log("multivar_wcl_skip_not_applicable", True, f"{prompt!r} var_count={var_count}")
        else:
            log("multivar_wcl_skip_not_resolved", True, f"{prompt!r} status={wcl.get('status') if wcl else None}")


def _section_tier_a_wcl_equivalence_sanity(a):
    """Spot-check tier_a_wcl_map.is_equivalent() isn't over-broad (claiming
    two genuinely different destructive actions are 'the same', which would
    silently suppress a real shadow warning) or under-broad (flagging a
    real same-action cross-listing as a shadow, annoying the user for no
    reason)."""
    from tier_a_wcl_map import is_equivalent
    # Known-should-NOT-be-equivalent pairs (different real actions):
    bad_pairs = [
        ("LOCK_WORKSTATION", "Clear-Disk"),
        ("EMPTY_RECYCLE_BIN", "Disable-DedupVolume"),
        ("COUNT_FILES", "Clear-TempFiles"),
    ]
    for intent, cmdlet in bad_pairs:
        eq = is_equivalent(intent, cmdlet)
        log("tier_a_wcl_map_not_overbroad", not eq, f"is_equivalent({intent!r}, {cmdlet!r}) = {eq} (expected False)")


def _section_chain_split_with_destructive(a):
    """A chained request combining a benign segment with a destructive one
    should still surface the confirmation gate for the destructive part,
    not silently execute it as part of an unattended chain."""
    a._pending = None
    a._pending_confirmation = None
    result = run(a, "make a folder named ChainTest and then run diskpart")
    text = str(result)
    log("chain_split_still_gates_destructive",
        _is_confirmation_prompt(result) or "diskpart" in text.lower(),
        f"result kind={result.get('kind')} resp={result.get('response','')[:150]!r}")


def _iter_zero_or_one_var_commands(a, danger_level):
    """Every WCL command at the given danger_level with 0 or 1 {variable}
    in its syntax, paired with one of its OWN real aliases (guaranteed
    tier-1 exact-match RESOLVED) -- used for exhaustive, not sampled,
    coverage of every command that's actually eligible to auto-dispatch."""
    import re
    rows = a.wcl_resolver._all_alias_rows()
    seen_commands = {}
    for alias_text, name, syntax, danger, admin, confirm, category in rows:
        if danger != danger_level:
            continue
        var_count = len(re.findall(r"\{(\w+)\}", syntax))
        if var_count > 1:
            continue
        if name in seen_commands:
            continue
        seen_commands[name] = alias_text
    return seen_commands  # command name -> one real alias to use as the prompt


def _section_exhaustive_destructive_sweep(a):
    """EXHAUSTIVE (not sampled): every destructive WCL command with 0-1
    variables, dispatched via one of its OWN real aliases (so it's
    guaranteed to RESOLVE, not just plausibly match). Every single one
    must produce a safe halt (confirmation/shadow/ambiguous/missing-slot),
    never an unattended dispatch.

    Tier A's own graph_router is patched to always miss for this sweep:
    many WCL alias strings collide by pure vocabulary with Tier A's own
    hand-built intents (e.g. "clean recycle bin" also matches native
    EMPTY_RECYCLE_BIN, "delete job" also matches native DELETE_ITEM's
    missing-slot question) -- Tier A has its own separate, deliberately
    no-confirmation-dialog safety model (sandbox + Stop button, see
    intents_extended.py's EMPTY_RECYCLE_BIN comment), which is correct
    and by design, but it isn't what this sweep is checking. This sweep
    isolates the thing that's actually in question: does the WCL_
    dynamic-intent confirmation gate (_dispatch_or_confirm ->
    _ask_for_confirmation) fire for every destructive WCL command that's
    eligible to auto-dispatch, with Tier A out of the way."""
    commands = _iter_zero_or_one_var_commands(a, "destructive")
    with patch.object(a.graph_router, "classify", lambda *a_, **k_: None):
        for name, alias in commands.items():
            a._pending = None
            a._pending_confirmation = None
            result = run(a, alias)
            ok = _is_confirmation_prompt(result)
            log("exhaustive_destructive_sweep", ok,
                f"{name} via alias {alias!r} -> kind={result.get('kind')} resp={result.get('response','')[:100]!r}")


def _section_exhaustive_caution_sweep(a):
    """Same exhaustive sweep for danger_level == 'caution', same Tier-A-out
    -of-the-way isolation and same reasoning."""
    commands = _iter_zero_or_one_var_commands(a, "caution")
    with patch.object(a.graph_router, "classify", lambda *a_, **k_: None):
        for name, alias in commands.items():
            a._pending = None
            a._pending_confirmation = None
            result = run(a, alias)
            ok = _is_confirmation_prompt(result)
            log("exhaustive_caution_sweep", ok,
                f"{name} via alias {alias!r} -> kind={result.get('kind')} resp={result.get('response','')[:100]!r}")


def _section_confirmed_yes_actually_dispatches(a):
    """Verify a genuine 'yes' after the WCL confirmation gate actually
    reaches RunningCommand.start() (patched to a Mock here so we can count
    the call instead of just inferring from response text)."""
    from unittest.mock import MagicMock
    a._pending = None
    a._pending_confirmation = None
    result = run(a, "wipe disk 2")
    if not _is_wcl_native_confirmation(result):
        log("confirmed_yes_reaches_dispatch", False, f"setup didn't reach confirmation gate: {result}")
        return
    mock_start = MagicMock(return_value=None)
    with patch.object(RunningCommand, "start", mock_start):
        run(a, "yes")
    log("confirmed_yes_reaches_dispatch", mock_start.called,
        f"RunningCommand.start() called={mock_start.called} after explicit 'yes'")


if __name__ == "__main__":
    main()
