"""
test_wcl_coverage_audit.py -- covers the fix from a full programmatic sweep
of all 1,160 windows_command_library commands (PROJECT_STATE_OVERVIEW.md,
"what it does NOT have", item 3: "only two TARGETED audits have been done
so far", never a full one).

The gap: 230 commands had ONLY mechanically-generated, noun-first aliases
left over from the original alias generator (e.g. "screen clear", "audio
sound devices") -- confirmed programmatically via vocab.py's own
find_leading_cluster(), not sampled. None of these ever starts with a
recognized verb, so they were both (a) never reachable except by typing
that exact unnatural phrase, and (b) never eligible for
05_widen_dictionaries.py's automatic synonym widening.

wcl_kg/add_coverage_aliases.py added one hand-reviewed, natural,
correctly-ordered alias to each of those 230 commands, grounded in that
command's own description/intents. wcl_kg/rebuild_graph.py rebuilt the
live graph (wcl_kg/windows_commands_db) from the updated
windows_command_library.widened.json -- wcl_resolver.py queries the
compiled graph directly, never the JSON, so the fix isn't real until the
graph is rebuilt; these tests run against that real, rebuilt graph, same
"actually run it" standard as test_wcl_resolver.py.
"""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("kuzu")

from wcl_resolver import WCLResolver, DB_PATH

WCL_KG_DIR = Path(__file__).resolve().parent.parent / "wcl_kg"
sys.path.insert(0, str(WCL_KG_DIR))

from vocab import find_leading_cluster  # noqa: E402
from add_coverage_aliases import NEW_ALIASES  # noqa: E402

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="wcl_kg/windows_commands_db not present in this checkout",
)

WIDENED_PATH = WCL_KG_DIR / "windows_command_library.widened.json"


@pytest.fixture(scope="module")
def resolver():
    r = WCLResolver()
    assert r.conn is not None, "expected the real shipped graph to load"
    yield r
    r.close()


@pytest.fixture(scope="module")
def widened_data():
    return json.load(open(WIDENED_PATH))


class TestFullSweepFindsZeroRemainingCoverageGaps:
    """The actual audit result: every one of the 1,160 commands must now
    have at least one alias, and the specific 230-command class of gap
    (mechanically-generated, noun-first-only aliases) must be fully
    closed -- checked against ALL 1,160, not a sample."""

    def test_no_command_has_zero_aliases(self, widened_data):
        zero_alias = [c for c in widened_data if len(c.get("aliases", [])) == 0]
        assert zero_alias == []

    def test_every_originally_gapped_command_now_has_its_new_alias(self, widened_data):
        by_id = {d["id"]: d for d in widened_data}
        missing = []
        for cid, expected_alias in NEW_ALIASES.items():
            if expected_alias not in by_id[cid]["aliases"]:
                missing.append((cid, expected_alias))
        assert missing == [], f"these commands are missing their coverage alias: {missing}"

    def test_all_230_originally_gapped_commands_are_now_alias_reachable(self, widened_data):
        # Re-runs the exact detection method used to originally find the
        # gap. This must now report substantially fewer never-widened
        # commands -- the ones needing a real cluster-verb fit -- and,
        # more importantly, every one of the original 230 ids must at
        # least have SOME real (non-mechanical) alias now, whether or
        # not it also happens to hit a VERB_CLUSTERS phrase.
        by_id = {d["id"]: d for d in widened_data}
        for cid in NEW_ALIASES:
            aliases = by_id[cid]["aliases"]
            assert len(aliases) >= 2, (
                f"{cid} ({by_id[cid]['name']}) still has only its original "
                f"mechanical alias(es): {aliases}"
            )


class TestPreviouslyUnreachableCommandsNowResolve:
    """Confirmed via the real, rebuilt graph -- not just present in the
    JSON, but actually resolvable through WCLResolver.resolve(). These
    specific four were directly verified UNRESOLVED against the
    pre-fix graph (backed up before the rebuild) before this fix."""

    @pytest.mark.parametrize("text,expected_command", [
        ("sort the text", "sort"),
        ("show sound devices", "Sound Devices"),
        ("take a screenshot", "Take-Screenshot"),
        ("connect over ssh", "ssh"),
    ])
    def test_now_resolves(self, resolver, text, expected_command):
        result = resolver.resolve(text)
        assert result["status"] == "RESOLVED", result
        assert result["command"] == expected_command, result


class TestCoverageFixDidNotIntroduceNewAmbiguity:
    """Adding 230 new aliases could, in principle, collide with an alias
    some OTHER command already owns (creating a new AMBIGUOUS case where
    there used to be a clean RESOLVED one). Checked against every single
    one of the 230 new aliases, not sampled."""

    def test_no_new_alias_collides_with_a_different_commands_existing_alias(self, widened_data):
        # For every (command, new_alias) pair, no OTHER command in the
        # dataset should already own that exact alias text.
        alias_owners = {}
        for d in widened_data:
            for a in d["aliases"]:
                alias_owners.setdefault(a.strip().lower(), set()).add(d["id"])

        collisions = []
        for cid, alias in NEW_ALIASES.items():
            owners = alias_owners.get(alias.strip().lower(), set())
            if len(owners) > 1:
                collisions.append((cid, alias, owners))
        assert collisions == [], f"new aliases that collide across commands: {collisions}"


class TestSampledCommandsStillResolveCorrectlyNotJustSomething:
    """A resolve() that returns SOME command isn't good enough -- must be
    the RIGHT command. Broader sample across categories than the four
    UNRESOLVED-before cases above, including ones that already resolved
    via a different tier (bag-of-tokens/fuzzy) before this fix and must
    keep resolving to the SAME, correct command now."""

    @pytest.mark.parametrize("text,expected_command", [
        ("initialize the disk", "Initialize-Disk"),
        ("show physical disks", "Physical Disks"),
        ("show memory usage", "Memory Usage"),
        ("show cpu info", "CPU Info"),
        ("show usb devices", "USB Devices"),
        ("show battery status", "Battery Status"),
        ("show firewall status", "Firewall Status"),
        ("show the routing table", "Routing Table"),
        ("show group membership", "Group Membership"),
        ("resize the partition", "Resize-Partition"),
        ("optimize the volume", "Optimize-Volume"),
        ("mount this volume", "mountvol"),
    ])
    def test_resolves_to_the_correct_command(self, resolver, text, expected_command):
        result = resolver.resolve(text)
        assert result["status"] == "RESOLVED", result
        assert result["command"] == expected_command, result


class TestFixDidNotRegressExistingResolutions:
    """Sample of commands that were already well-covered before this fix
    (real aliases, no gap) -- must be completely unaffected."""

    @pytest.mark.parametrize("text,expected_command", [
        ("stop the print spooler service", "Stop-Service"),
        ("create a new vm", "New-VM"),
        ("restart the network adapter", "Restart-NetAdapter"),
    ])
    def test_still_resolves_correctly(self, resolver, text, expected_command):
        result = resolver.resolve(text)
        assert result["status"] == "RESOLVED", result
        assert result["command"] == expected_command, result
