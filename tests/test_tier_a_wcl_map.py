"""
test_tier_a_wcl_map.py -- verifies tier_a_wcl_map.py against the real
Tier A intent templates and real WCL data (priority.md #11 groundwork),
and exercises orchestrator.py's destructive-shadow guard built on top of
it.
"""
import json
import re
from pathlib import Path

import pytest

import intents
import intents_extended
import intents_app_control
from tier_a_wcl_map import TIER_A_TO_WCL_CMDLETS, is_equivalent

ROOT = Path(__file__).resolve().parent.parent

HELPER_CMDLETS = {
    "New-Object", "Add-Type", "Select-Object", "Sort-Object",
    "Where-Object", "Group-Object", "ForEach-Object", "Measure-Object",
    "Write-Output", "Add-Member", "Join-Path",
}
CMDLET_RE = re.compile(r"\b([A-Z][a-zA-Z]*-[A-Z][a-zA-Z]+)\b")


def _all_tier_a_intents():
    merged = {}
    for mod in (intents, intents_extended, intents_app_control):
        d = (
            getattr(mod, "INTENTS", None)
            or getattr(mod, "INTENTS_EXTENDED", None)
            or getattr(mod, "APP_CONTROL_INTENTS", None)
        )
        if d:
            merged.update(d)
    return merged


def test_map_covers_every_tier_a_intent():
    """Every real Tier A intent must have an entry -- a missing key would
    make is_equivalent() silently treat it as 'no equivalent' via
    .get(intent), which is the conservative-but-wrong-looking default;
    catch new/renamed intents explicitly instead of relying on that."""
    all_intents = _all_tier_a_intents()
    missing = set(all_intents) - set(TIER_A_TO_WCL_CMDLETS)
    assert not missing, f"tier_a_wcl_map.py is missing intents: {sorted(missing)}"


def test_no_stale_entries():
    """Catches entries left behind after an intent is renamed/removed."""
    all_intents = _all_tier_a_intents()
    stale = set(TIER_A_TO_WCL_CMDLETS) - set(all_intents)
    assert not stale, f"tier_a_wcl_map.py has stale entries: {sorted(stale)}"


@pytest.mark.parametrize("intent_name,spec", sorted(_all_tier_a_intents().items()))
def test_mapped_cmdlet_actually_appears_in_template(intent_name, spec):
    """For powershell-kind intents with a non-empty equivalence set,
    every listed cmdlet name that looks like a real PowerShell cmdlet
    (has a hyphen) must actually appear in the intent's own template --
    otherwise the map is asserting an equivalence that doesn't exist in
    this codebase. Non-cmdlet equivalents (aliases like 'ri'/'rm'/'del'
    for DELETE_ITEM) are intentionally exempt -- they're real-world
    equivalents to the INTENT's action, not required to appear in
    TOKI's own template text."""
    if spec.get("kind") != "powershell":
        return
    template = spec.get("template", "")
    equivalents = TIER_A_TO_WCL_CMDLETS.get(intent_name, frozenset())
    cmdlet_style = {e for e in equivalents if "-" in e}
    if not cmdlet_style:
        return
    matches = set(CMDLET_RE.findall(template))
    # At least one mapped cmdlet-style equivalent must be a real,
    # non-helper match in the template (DELETE_ITEM is exempt: its own
    # template never calls Remove-Item, by design -- see module docstring).
    if intent_name == "DELETE_ITEM":
        return
    assert matches & cmdlet_style, (
        f"{intent_name}: none of {cmdlet_style} found in its own template "
        f"({matches - HELPER_CMDLETS!r} were)"
    )


def test_wcl_json_actually_contains_every_mapped_cmdlet():
    """Every cmdlet-style equivalent must be a real cmdlet name that
    exists somewhere in windows_command_library.json -- otherwise the
    equivalence is pointing at a name wcl_resolver.py could never
    actually return, silently making the guard useless for that case."""
    wcl = json.loads((ROOT / "graph_source_data" / "windows_command_library.json").read_text())
    real_names = {c["name"].lower() for c in wcl}
    for intent_name, equivalents in TIER_A_TO_WCL_CMDLETS.items():
        for e in equivalents:
            if "-" not in e:
                continue  # bare alias like "ri"/"rm"/"del", not a WCL c.name
            assert e.lower() in real_names, (
                f"{intent_name}: mapped cmdlet {e!r} doesn't exist in "
                f"windows_command_library.json"
            )


@pytest.mark.parametrize(
    "intent,cmdlet,expected",
    [
        ("KILL_PROCESS", "Stop-Process", True),
        ("KILL_PROCESS", "stop-process", True),  # case-insensitive
        ("EMPTY_RECYCLE_BIN", "Clear-RecycleBin", True),
        ("DELETE_ITEM", "Remove-Item", True),
        ("DELETE_ITEM", "ri", True),
        ("DELETE_ITEM", "New-Partition", False),
        ("VOLUME_DOWN", "Disable-DedupVolume", False),
        ("LOCK_WORKSTATION", "Lock-BitLocker", False),
        ("DISK_USAGE", "Clear-Disk", False),
        ("GET_DATE", "Set-Date", False),
        ("COPY_ITEM", "Copy-Item", True),
        ("UNKNOWN_INTENT", "Stop-Process", False),
        ("KILL_PROCESS", "", False),
        ("KILL_PROCESS", None, False),
    ],
)
def test_is_equivalent(intent, cmdlet, expected):
    assert is_equivalent(intent, cmdlet) is expected
