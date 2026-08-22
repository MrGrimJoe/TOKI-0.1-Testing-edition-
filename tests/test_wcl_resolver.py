"""
test_wcl_resolver.py -- pins WCLResolver, a previously untested new
subsystem found already wired into the project (wcl_resolver.py's
DB_PATH points at wcl_kg/windows_commands_db) with zero test coverage
of its own. Everything here is verified against the REAL shipped
graph, not a synthetic fixture -- same "actually run it" standard as
the rest of this test suite, since a resolver that only passes against
a fake mock graph proves nothing about the real one it ships with.

wcl_kg/pipeline_scripts_reference/README.md is the authoritative
description of the resolution policy this pins:
  1. Exact alias match (single)       -> RESOLVED, no model
  2. Exact alias match (multiple)     -> AMBIGUOUS
  3. SynonymOf 1-hop match (single)   -> RESOLVED, no model
  4. SynonymOf 1-hop match (multiple) -> AMBIGUOUS
  5. Fuzzy alias match (difflib)      -> RESOLVED/AMBIGUOUS, still no model
  6. Abbreviation/full-form variant retry (BETA 0.3.29, only after 1-5
     miss): re-runs 1-5 against known short/long noun substitutions
     (e.g. "net"<->"network", "vm"<->"virtual machine")
  7. Verb...noun bracket match (BETA 0.3.30, only after 1-5 miss): head
     token + tail token bookend the value ("stop the print spooler
     service" -> "stop service" + value "print spooler")
  8. Nothing matches                  -> UNRESOLVED (loose_candidates only)
"""

import pytest

pytest.importorskip("kuzu")

from wcl_resolver import WCLResolver, normalize, DB_PATH

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="wcl_kg/windows_commands_db not present in this checkout",
)


@pytest.fixture(scope="module")
def resolver():
    r = WCLResolver()
    assert r.conn is not None, "expected the real shipped graph to load"
    yield r
    r.close()


class TestFailsOpenWithoutTheGraph:
    def test_missing_db_path_returns_unresolved_not_a_crash(self, tmp_path):
        r = WCLResolver(db_path=tmp_path / "does_not_exist")
        assert r.conn is None
        assert r.resolve("anything at all") == {
            "status": "UNRESOLVED", "tier": None, "loose_candidates": [],
        }

    def test_loose_search_on_a_closed_resolver_returns_empty_not_a_crash(self, tmp_path):
        r = WCLResolver(db_path=tmp_path / "does_not_exist")
        assert r.loose_search("anything") == []

    def test_verify_model_suggestion_on_a_closed_resolver_is_not_grounded(self, tmp_path):
        r = WCLResolver(db_path=tmp_path / "does_not_exist")
        assert r.verify_model_suggestion("Stop-Process") == {"grounded": False}


class TestNormalize:
    def test_strips_filler_prefixes(self):
        assert normalize("please stop process notepad") == "stop process notepad"
        assert normalize("how do i check ip config") == "check ip config"

    def test_strips_multiple_stacked_prefixes(self):
        # "could you please" -- two prefixes in a row must both be stripped,
        # not just the first one matched.
        assert normalize("could you please clear the screen") == "clear the screen"

    def test_lowercases_and_strips_punctuation(self):
        assert normalize("Empty the Recycle-Bin!") == "empty the recyclebin"


class TestTier1ExactAliasMatch:
    def test_known_single_alias_resolves_without_a_model(self, resolver):
        # "empty recycle bin" is a real, exact single-alias match in the
        # shipped graph -- verified live, not assumed.
        result = resolver.resolve("empty recycle bin")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 1
        assert result["command"] == "Clear-RecycleBin"
        assert "syntax" in result

    def test_resolved_result_carries_safety_metadata(self, resolver):
        # A RESOLVED result with requires_confirmation/requires_admin set
        # must actually surface them -- orchestrator.py's dispatch gating
        # depends on this being present and accurate, not just on
        # "status": "RESOLVED" alone.
        result = resolver.resolve("empty recycle bin")
        assert result["requires_admin"] is True
        assert result["requires_confirmation"] is True
        assert result["danger_level"] == "destructive"


# ─── BETA 0.3.15: Tier 2, trailing-value stripping ─────────────────────────
#
# Found live, testing the BETA 0.3.14 slot-filler feature: WCLResolver.
# resolve() required the ENTIRE query to match a known alias. The moment a
# real value got appended to a realistic phrase ("cat notes.txt", "view
# more notes.txt"), the extra word broke the match and fell straight to
# UNRESOLVED -- meaning the whole slot-filler feature, while correctly
# built and safety-gated, would almost never actually fire on a real
# sentence. This was invisible to the existing test suite because the
# integration test correctly (for testing gating logic in isolation) stubs
# the resolver to always return a fixed result, never exercising whether a
# REAL sentence with a real value actually resolves.

class TestTier2TrailingValueStripping:
    def test_real_command_plus_trailing_value_resolves(self, resolver):
        # "view more notes.txt" -- "view more" is a real alias for the
        # `more` command; "notes.txt" is the user's actual value.
        result = resolver.resolve("view more notes.txt")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 2
        assert result["command"] == "more"

    def test_stripped_value_preserves_punctuation_and_case(self, resolver):
        # Regression guard for a bug caught in THIS fix's own first
        # draft: the first version built stripped_value from
        # normalize()'s already-punctuation-stripped tokens, so
        # "notes.txt" came back as "notestxt" -- a real value corruption,
        # caught by testing before it shipped. stripped_value must come
        # from the ORIGINAL text, not the normalized matching tokens.
        result = resolver.resolve("view more notes.txt")
        assert result["stripped_value"] == "notes.txt"

    def test_multiword_alias_plus_value_resolves(self, resolver):
        # "read cat notes.txt" -- "read cat" (two words) is the real
        # alias, confirming the prefix-stripping tries multi-word
        # prefixes too, not just single leading tokens.
        result = resolver.resolve("read cat notes.txt")
        assert result["status"] == "RESOLVED"
        assert result["command"] == "cat"
        assert result["stripped_value"] == "notes.txt"

    def test_full_phrase_match_is_unaffected_by_this_tier(self, resolver):
        # A query that already matches in full via tier 1 must still
        # resolve at tier 1, not get needlessly re-processed by tier 2 --
        # confirms tier 2 only fires on an actual tier-1/tier-3 MISS.
        result = resolver.resolve("empty recycle bin")
        assert result["tier"] == 1

    def test_bare_command_name_alone_is_still_unresolved(self, resolver):
        # Honest limitation, not a bug: "cat" (the bare canonical command
        # NAME) is not itself a registered Alias node in the graph --
        # only "read cat"/"view cat" are (confirmed against this
        # project's own real alias data). Tier 2 only matches against
        # Alias nodes, so "cat notes.txt" alone (no "read"/"view" prefix)
        # correctly stays UNRESOLVED. Pinned so a future change to what
        # counts as an alias is a deliberate decision, not a silent
        # side effect.
        result = resolver.resolve("cat notes.txt")
        assert result["status"] == "UNRESOLVED"

    def test_ambiguous_prefix_after_stripping_stays_ambiguous(self, resolver):
        # If the shortest successful strip still matches MULTIPLE
        # commands, this must report AMBIGUOUS, not silently pick one --
        # same "don't guess" posture as every other tier.
        result = resolver.resolve("virtual vm myvm123")
        assert result["status"] in ("AMBIGUOUS", "UNRESOLVED")
        assert result["status"] != "RESOLVED" or result.get("tier") != 2


class TestAmbiguousResolution:
    def test_documented_ambiguous_case_stays_ambiguous(self, resolver):
        # README's own worked example: "virtual vm" matches 8 real VM
        # cmdlets and is genuine English ambiguity, not a bug -- pinned
        # here so a future vocab.py change can't silently collapse this
        # into a wrong confident guess.
        result = resolver.resolve("virtual vm")
        assert result["status"] == "AMBIGUOUS"
        assert len(result["candidates"]) >= 2

    def test_ambiguous_result_never_auto_dispatches(self, resolver):
        # Structural check: AMBIGUOUS must never carry a "command"/"syntax"
        # pair the way RESOLVED does, since orchestrator.py's dispatch
        # gating only ever looks for a RESOLVED status.
        result = resolver.resolve("virtual vm")
        assert "command" not in result
        assert "syntax" not in result

    def test_ambiguous_candidates_carry_danger_level(self, resolver):
        # BETA 0.3.27 fix: candidates used to be bare (name, syntax) pairs,
        # silently dropping danger_level even though the underlying row
        # already had it -- that blinded orchestrator.py's destructive-
        # shadow guard to every AMBIGUOUS result (confirmed live: "clean
        # temp files" resolves AMBIGUOUS with a genuinely destructive
        # Clear-TempFiles candidate right there in the list, but the guard
        # only ever checked RESOLVED). Now each candidate is a 3-tuple.
        result = resolver.resolve("clean temp files")
        assert result["status"] == "AMBIGUOUS"
        assert any(len(c) == 3 for c in result["candidates"]), (
            "candidates must be (name, syntax, danger_level) 3-tuples"
        )
        names_and_levels = {c[0]: c[2] for c in result["candidates"]}
        assert names_and_levels.get("Clear-TempFiles") == "destructive"


class TestUnresolvedFallsThroughSafely:
    def test_nonsense_query_is_unresolved_not_a_wrong_guess(self, resolver):
        result = resolver.resolve("supercalifragilisticexpialidocious blorp")
        assert result["status"] == "UNRESOLVED"
        assert result["tier"] is None

    def test_unresolved_still_offers_loose_candidates_for_model_grounding(self, resolver):
        # loose_search() exists specifically to give the LLM fallback path
        # real grounding material on a genuine miss -- never auto-dispatched
        # (see its own docstring), but it should still return something
        # useful when the query has real, matchable words in it.
        result = resolver.resolve("check ip config")
        assert result["status"] == "UNRESOLVED"
        assert isinstance(result["loose_candidates"], list)

    def test_loose_search_returns_nothing_for_only_short_stopword_like_tokens(self, resolver):
        # loose_search() filters to words > 2 chars before querying --
        # confirms it doesn't just return everything for a query with no
        # real matchable content.
        assert resolver.loose_search("a an it") == []


class TestVerifyModelSuggestion:
    def test_known_real_command_grounds_successfully(self, resolver):
        result = resolver.verify_model_suggestion("Clear-RecycleBin")
        assert result["grounded"] is True
        assert "syntax" in result

    def test_made_up_command_name_does_not_ground(self, resolver):
        result = resolver.verify_model_suggestion("Definitely-Not-A-Real-Cmdlet")
        assert result == {"grounded": False}


class TestAllAliasesCaching:
    def test_same_object_returned_on_repeated_calls(self, resolver):
        # Same "fetch once, reuse" pattern as LocationCache/AppController's
        # app cache elsewhere in this project -- confirms this doesn't
        # re-query the graph on every call.
        first = resolver.all_aliases()
        second = resolver.all_aliases()
        assert first is second

    def test_alias_count_matches_the_documented_figure(self, resolver):
        # Originally pinned at 13,532 (README's documented figure at the
        # time) so a future graph rebuild that silently drops data gets
        # caught here rather than discovered live. BETA 0.3.27 deliberately
        # added 10 real aliases directly to wcl_kg/windows_commands_db:
        # 6 for Lock-BitLocker (which previously had exactly ONE alias,
        # and it was the literal garbage string "bitlocker bitlocker" --
        # an alias-generation artifact, not a real phrasing) and 4 for
        # New-VM ("create a new vm" and variants, which the graph
        # previously had zero coverage for -- see priority.md #14 and the
        # "make the vm" vs "create a new vm" shadow-guard inconsistency).
        # 13532 + 10 = 13542.
        # BETA 0.3.28 added 4 more directly to the live graph for
        # Restart-NetAdapter: "restart/reboot/reset the network adapter"
        # variants alongside its existing "net adapter" aliases -- the
        # command only had "net adapter" phrasing coverage, so "restart
        # the network adapter" fell through to the Tier 2
        # read-only-lookalike guard instead of resolving (see
        # TestNetworkAdapterAliasGap below). 13542 + 4 = 13546.
        # BETA 0.3.37 (full natural-language-coverage audit, see
        # wcl_kg/add_coverage_aliases.py): a programmatic sweep of all 1,160
        # commands via vocab.py's own find_leading_cluster() found 230
        # commands whose ONLY aliases were mechanically-generated noun-first
        # phrases left over from the original alias generator (e.g. "screen
        # clear", "audio sound devices") -- never reachable by natural
        # phrasing, and never eligible for automatic synonym widening since
        # none of them starts with a recognized verb. Added one hand-
        # reviewed, natural, correctly-ordered alias to each of those 230
        # commands (grounded in that command's own description/intents).
        # Verified exactly (not estimated): windows_command_library.widened.json
        # had 13,550 distinct alias texts immediately before this change --
        # already 4 more than the 13,546 this test previously pinned, a
        # small pre-existing drift between the JSON file and the graph's
        # last build that predates this fix and isn't something this fix
        # caused or needed to resolve. Adding the 230 new aliases (2 of
        # which duplicate alias text some OTHER command already used, so
        # they don't add a new distinct Alias node) brought the file to
        # 13,778 distinct texts -- then +2 more (13,780) after a follow-up
        # correction: two of the 230 were originally byte-identical between
        # a pair of commands that are genuinely near-synonymous PowerShell
        # aliases for the same construct (foreach/%, r/ihy), caught by a
        # dedicated collision test in test_wcl_coverage_audit.py and
        # differentiated into two distinct, still-natural phrasings each so
        # they don't force an avoidable AMBIGUOUS result. Confirmed by
        # diffing the file before vs. after, and by the freshly-rebuilt
        # graph (wcl_kg/rebuild_graph.py) reporting that same 13,780 for
        # its Alias node table.
        # If this number moves again, check whether it's an intentional
        # data addition (update this comment/number) or an accidental
        # drop (investigate) before just bumping it.
        #
        # BETA 0.3.64 (this session): 13,780 -> 13,805 (+25), from
        # wcl_kg/add_natural_phrasing_aliases.py -- a full 13,780-alias
        # self-consistency sweep of wcl_resolver.py (every real alias
        # queried verbatim, checked it resolves back to its own command)
        # found 0 resolver bugs, but also surfaced a separate, larger gap
        # this test's own history didn't cover: 311 of 1,160 commands had
        # aliases that all start with a recognized verb (so they didn't
        # trip find_leading_cluster's audit above) but are still either
        # the "<verb> me the X" template family (grammatically broken --
        # "list the me the volume") or leftover synonym-pair widening
        # artifacts that only work if the user also types the command's
        # own internal short name verbatim ("editor regedit"). Confirmed
        # via real stress-testing, not sampled: ordinary phrasings like
        # "list all volumes", "open the registry editor", "ping
        # google.com" all failed to resolve even though the command
        # exists and is otherwise correctly wired. Added exactly one
        # hand-reviewed, grounded alias each to a scoped, individually-
        # justified first batch of 25 (10 confirmed-broken-by-stress-test
        # + 15 more from quantify_gap.py's short/real-world-object-name
        # bucket) -- not all 311, since an automated "is this natural"
        # classifier was tried first and found unreliable (it cleared
        # Get-Volume/Get-VM/regedit as fine when they weren't); doing the
        # rest the same properly-reviewed way is follow-up work, not done
        # in this pass. Confirmed by diffing the widened JSON before vs.
        # after, and by the freshly-rebuilt graph reporting that same
        # 13,805 for its Alias node table.
        #
        # UPDATE (batch 2, add_natural_phrasing_aliases_batch2.py):
        # reviewed all 293 remaining gap commands by hand. Found the vast
        # majority (~285) are enterprise/datacenter-only cmdlets (Hyper-V
        # VM sub-component config, SAN storage-enclosure hardware mgmt,
        # AD domain-controller DHCP/DNS-server-role, IPsec policy rule
        # sets) with no genuine casual phrasing a home-PC TOKI user would
        # ever type -- forcing one would just recreate the fake-alias
        # problem this fix exists to eliminate, so those were left alone.
        # Exactly 4 had a real, unambiguous, grounded natural phrasing:
        # disk space (Get-DiskSpaceSummary), file sharing settings
        # (Get-SmbServerConfiguration), show dns cache/show my dns
        # servers (Get-DnsClientCache/Get-DnsClientServerAddress -- the
        # client-side, i.e. this PC's own resolver cache/DNS servers, not
        # the enterprise DNS-*server*-role cmdlets of the same shape).
        # 13,805 + 4 = 13,809, confirmed via the same diff-JSON +
        # rebuilt-graph-node-count double-check as the first batch.
        assert len(resolver.all_aliases()) == 13809


# ─── BETA 0.3.28: Restart-NetAdapter "network adapter" alias gap ───────────
#
# Restart-NetAdapter's alias list only ever had "net adapter" phrasings
# ("restart net adapter", "reset net adapter", etc). A user saying the
# full word "network adapter" instead of the shortened "net adapter" had
# no exact alias to match -- and worse, "reset network adapter" is
# exactly the phrasing that graph_router.py's Tier 2 guard exists to
# steer AWAY from NETWORK_INFO and toward this resolver, so with no
# alias here to catch it, it likely fell through to UNRESOLVED entirely
# instead of finding Restart-NetAdapter. Fixed the same way as the
# New-VM alias gap above: added "network adapter" variants directly to
# the live graph (and both windows_command_library.json source files,
# for consistency on a future rebuild), alongside the existing "net
# adapter" ones.

class TestNetworkAdapterAliasGap:
    @pytest.mark.parametrize("query", [
        "restart the network adapter",
        "reboot the network adapter",
        "reset network adapter",
        "restart network adapter",
    ])
    def test_network_adapter_phrasing_resolves(self, resolver, query):
        result = resolver.resolve(query)
        assert result["status"] == "RESOLVED", (
            f"{query!r} should resolve now that 'network adapter' aliases "
            f"exist alongside the original 'net adapter' ones -- got {result}"
        )
        assert result["command"] == "Restart-NetAdapter"

    def test_original_net_adapter_phrasing_still_resolves(self, resolver):
        # Regression guard: adding the new "network adapter" aliases must
        # not disturb the existing "net adapter" coverage.
        result = resolver.resolve("restart net adapter")
        assert result["status"] == "RESOLVED"
        assert result["command"] == "Restart-NetAdapter"


# ─── BETA 0.3.29: Tier 6, abbreviation/full-form variant retry ─────────────
#
# The Restart-NetAdapter gap above was one command with one missing
# phrasing -- but "short form vs. full form of the same noun" is a
# SHAPE of gap, not a one-off, and a full dataset-wide alias audit is a
# much bigger, still-open project (see priority.md). This tier closes
# the common cases of that shape generically: for known short/long noun
# pairs (net/network, vm/virtual machine, config/configuration, etc --
# see ABBREVIATION_PAIRS), a query using either form gets a substituted
# variant tried, but ONLY after tiers 1-5 have already failed on the
# query exactly as typed, and the substituted variant is run back
# through those same tiers rather than matched directly -- so this
# never loosens what any existing tier considers a match, it only
# supplies wording gaps tiers 1-5 would otherwise dead-end on.

class TestAbbreviationVariantRetry:
    def test_long_form_resolves_via_short_form_alias(self, resolver):
        # "virtual machine" has zero alias coverage in the live graph;
        # "vm" is the form actually used. Confirms the substitution
        # reaches an alias tiers 1-5 already knew about.
        result = resolver.resolve("restart virtual machine")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 6
        assert result["command"] == "Restart-VM"

    def test_does_not_fire_when_tiers_1_to_5_already_resolve(self, resolver):
        # A query that resolves normally must report its REAL tier, not
        # get relabeled as tier 6 just because it happens to contain a
        # word from ABBREVIATION_PAIRS.
        result = resolver.resolve("restart net adapter")
        assert result["status"] == "RESOLVED"
        assert result["tier"] != 6

    def test_short_form_alone_without_a_gap_is_unaffected(self, resolver):
        # "vm" itself (no verb) shouldn't suddenly start resolving to
        # something via variant expansion if it wouldn't otherwise --
        # confirms tier 6 doesn't broaden matching, only fills gaps.
        result = resolver.resolve("xyzzy not a real command at all")
        assert result["status"] == "UNRESOLVED"

    def test_unrelated_word_containing_short_form_is_not_mangled(self, resolver):
        # "net" must only substitute on a whole-word boundary -- must
        # never match inside "internet" and corrupt the query into
        # nonsense (e.g. turning "internet" into "innetworkt").
        from wcl_resolver import _abbreviation_variants, normalize
        variants = _abbreviation_variants(normalize("check internet connection"))
        for v in variants:
            assert "internet" in v

    def test_variant_result_still_carries_full_safety_metadata(self, resolver):
        # A tier-6 RESOLVED result must carry the same danger_level/
        # requires_admin/requires_confirmation/category fields as any
        # other tier -- the destructive-shadow guard and orchestrator.py
        # depend on these being present regardless of which tier
        # produced the match.
        result = resolver.resolve("restart virtual machine")
        assert result["status"] == "RESOLVED"
        for key in ("danger_level", "requires_admin", "requires_confirmation", "category"):
            assert key in result, f"tier-6 result missing {key!r}"

    def test_combined_with_tier_2_trailing_value_still_resolves(self, resolver):
        # A query needing BOTH the abbreviation substitution AND Tier 2's
        # trailing-value stripping (e.g. "restart virtual machine
        # web-server-01") must still resolve and still carry a
        # stripped_value -- known, documented limitation: because the
        # substituted variant has no corresponding "real" original text,
        # the returned stripped_value loses original punctuation/casing
        # here (falls back to the normalized token, same defensive
        # fallback Tier 2 already has for a token-count mismatch) --
        # this pins that known behavior rather than leaving it
        # undocumented, not claiming it's ideal.
        result = resolver.resolve("restart virtual machine web-server-01")
        assert result["status"] == "RESOLVED"
        assert result["command"] == "Restart-VM"
        assert "stripped_value" in result

    def test_ambiguous_variant_result_never_auto_dispatches(self, resolver):
        # Whatever tier 6 turns up, an AMBIGUOUS result must stay
        # AMBIGUOUS -- same fail-safe contract as every other tier.
        result = resolver.resolve("change the vm auth configuration setting")
        assert result["status"] in ("AMBIGUOUS", "RESOLVED", "UNRESOLVED")
        if result["status"] == "AMBIGUOUS":
            assert "command" not in result


class TestTier7BracketMatch:
    """Verb...noun bracket match -- "stop the print spooler service" and
    similar phrasings where the value sits BETWEEN the verb and the
    object noun, not before/after both. All against the real shipped
    graph, same standard as every other class in this file.
    """

    def test_verb_noun_bracket_resolves_with_middle_as_value(self, resolver):
        # "stop service" is a real, exact two-word alias for Stop-Service
        # in the shipped graph -- confirmed live, not assumed. The middle
        # ("the print spooler") is the value tiers 1-6 have no way to
        # isolate, since neither is bookended like this.
        result = resolver.resolve("stop the print spooler service")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 7
        assert result["command"] == "Stop-Service"
        assert result["stripped_value"] == "print spooler"

    def test_without_leading_article_still_resolves(self, resolver):
        # Same bracket, no "the" this time -- confirms the article strip
        # is conditional (only fires when actually present), not always
        # chopping the first middle token regardless.
        result = resolver.resolve("stop print spooler service")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 7
        assert result["stripped_value"] == "print spooler"

    def test_ambiguous_bracket_never_auto_picks_one_command(self, resolver):
        # "backup vm" is a real two-word alias shared by BOTH Save-VM and
        # Export-VM in the shipped graph -- confirmed live. A bracket
        # match landing on a genuinely ambiguous alias must report
        # AMBIGUOUS, not silently prefer one.
        result = resolver.resolve("backup the important vm")
        assert result["status"] == "AMBIGUOUS"
        assert result["tier"] == 7
        names = {c[0] for c in result["candidates"]}
        assert names == {"Save-VM", "Export-VM"}

    def test_does_not_fire_when_an_earlier_tier_already_resolves(self, resolver):
        # "stop the service" (no bracketed value at all) is already a
        # tier 1 exact match -- must report its real tier, not get
        # relabeled as 7 just because it also happens to fit the
        # head+tail shape.
        result = resolver.resolve("stop the service")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 1

    def test_short_queries_never_reach_the_bracket_tier(self, resolver):
        # Fewer than 3 tokens means there's no room for a real middle
        # value -- must fall through to genuine UNRESOLVED, not error.
        result = resolver.resolve("xyzzy blorp")
        assert result["status"] == "UNRESOLVED"

    def test_unrelated_head_and_tail_fails_safe_to_unresolved(self, resolver):
        # A verb and noun that don't correspond to any real alias
        # together must fail open to UNRESOLVED (with grounding
        # candidates for the model), never a wrong guess -- same
        # fail-safe posture as every other tier here.
        result = resolver.resolve("wobble the nonexistent gizmo widget")
        assert result["status"] == "UNRESOLVED"

    def test_bracket_result_carries_full_safety_metadata(self, resolver):
        # Same contract as tier 6: a tier-7 RESOLVED result must carry
        # danger_level/requires_admin/requires_confirmation/category --
        # orchestrator.py's destructive-shadow guard and auto-dispatch
        # eligibility both depend on these being present regardless of
        # which tier produced the match.
        result = resolver.resolve("stop the print spooler service")
        assert result["status"] == "RESOLVED"
        for key in ("danger_level", "requires_admin", "requires_confirmation", "category"):
            assert key in result, f"tier-7 result missing {key!r}"


class TestTier8LeadingPairSwap:
    """Leading noun+verb swap retry (BETA 0.3.33) -- catches a noun-before-
    verb phrasing ("bitlocker lock mount point D") by re-running the
    EXISTING verb-first tiers against the swapped-prefix variant. All
    against the real shipped graph, same standard as every other class
    in this file.
    """

    def test_noun_first_phrasing_resolves_via_swap(self, resolver):
        # The exact original repro (priority.md's own test string) --
        # "lock bitlocker" is a real two-word alias for Lock-BitLocker
        # (confirmed live, added in an earlier session), but nothing in
        # tiers 1-7 tries the NOUN-first order until this tier does.
        result = resolver.resolve("bitlocker lock mount point D")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 8
        assert result["command"] == "Lock-BitLocker"
        assert "mount point d" in result["stripped_value"].lower()

    def test_verb_first_order_unaffected_still_resolves_at_its_own_tier(self, resolver):
        # Regression guard: adding the swap retry must not change which
        # tier a query that ALREADY resolves verb-first reports.
        result = resolver.resolve("lock bitlocker mount point D")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 2
        assert result["command"] == "Lock-BitLocker"

    def test_does_not_fire_when_an_earlier_tier_already_resolves(self, resolver):
        result = resolver.resolve("stop the service")
        assert result["status"] == "RESOLVED"
        assert result["tier"] == 1

    def test_short_queries_never_reach_this_tier(self, resolver):
        # Fewer than 3 tokens means there's no room for a swap PLUS a
        # real remaining value -- must fall through to UNRESOLVED.
        result = resolver.resolve("xyzzy blorp")
        assert result["status"] == "UNRESOLVED"

    def test_unrelated_swap_fails_safe_to_unresolved(self, resolver):
        # Swapping two unrelated words must not coincidentally produce a
        # real alias match -- fails open to UNRESOLVED like every other
        # tier here, never a wrong guess.
        result = resolver.resolve("gizmo wobble the nonexistent widget")
        assert result["status"] == "UNRESOLVED"

    def test_swap_result_carries_full_safety_metadata(self, resolver):
        # Same contract as tiers 6/7: orchestrator.py's destructive-shadow
        # guard and auto-dispatch eligibility both depend on these being
        # present regardless of which tier produced the match.
        result = resolver.resolve("bitlocker lock mount point D")
        assert result["status"] == "RESOLVED"
        for key in ("danger_level", "requires_admin", "requires_confirmation", "category"):
            assert key in result, f"tier-8 result missing {key!r}"
        assert result["danger_level"] == "destructive"


class TestLeadingPairSwapHelperDirectly:
    def test_swaps_only_the_first_two_tokens(self):
        from wcl_resolver import _leading_pair_swap
        assert _leading_pair_swap("bitlocker lock mount point d") == "lock bitlocker mount point d"

    def test_returns_none_below_three_tokens(self):
        from wcl_resolver import _leading_pair_swap
        assert _leading_pair_swap("a b") is None
        assert _leading_pair_swap("a") is None
        assert _leading_pair_swap("") is None

    def test_does_not_touch_tokens_beyond_the_first_two(self):
        from wcl_resolver import _leading_pair_swap
        assert _leading_pair_swap("a b c d e") == "b a c d e"


class TestBracketResolveHelperDirectly:
    """Direct unit tests of _bracket_resolve(), independent of full
    resolve() tier ordering, to pin the narrow contract on its own."""

    def test_returns_none_below_three_tokens(self, resolver):
        # Fewer than 3 tokens leaves no room for a real head+middle+tail
        # split -- must refuse rather than guess at a degenerate bracket.
        assert resolver._bracket_resolve("stop it", ["stop", "it"], "stop it") is None

    def test_returns_none_on_a_real_three_token_miss(self, resolver):
        # "wobble ... widget" isn't a real alias combo -- must fail open
        # (None) rather than raise or fabricate a result.
        tokens = ["wobble", "the", "widget"]
        assert resolver._bracket_resolve("wobble the widget", tokens, "wobble the widget") is None


class TestAbbreviationVariantsHelper:
    """Direct unit tests of _abbreviation_variants(), independent of the
    live graph -- confirms the substitution logic itself stays correct
    even if the underlying alias data changes."""

    def test_short_to_long_substitution(self):
        from wcl_resolver import _abbreviation_variants
        variants = _abbreviation_variants("reset net adapter")
        assert "reset network adapter" in variants

    def test_long_to_short_substitution(self):
        from wcl_resolver import _abbreviation_variants
        variants = _abbreviation_variants("restart virtual machine")
        assert "restart vm" in variants

    def test_no_pair_present_returns_empty(self):
        from wcl_resolver import _abbreviation_variants
        assert _abbreviation_variants("open notepad please") == []

    def test_whole_word_boundary_not_substring(self):
        from wcl_resolver import _abbreviation_variants
        # "net" must not match inside "internet"
        variants = _abbreviation_variants("check internet connection")
        for v in variants:
            assert "innetworkt" not in v
            assert "internet" in v

    def test_original_query_never_returned_as_its_own_variant(self):
        from wcl_resolver import _abbreviation_variants
        q = "reset net adapter"
        assert q not in _abbreviation_variants(q)


class TestSyntaxVariablesFormatIntegrity:
    """BETA 0.3.37 checkpoint 1: every WCL command that declares
    variables must have its `syntax` template actually SUCCEED when run
    through `.format(**dummy_slots)` -- because that's exactly what
    orchestrator.py's dispatch path does for real, for any WCL command
    with a non-empty `variables` list (see the "if meta.get('slots'):"
    branch in orchestrator.py's powershell dispatch).

    Before this checkpoint, 12 "safe" commands with declared variables
    had literal, unescaped PowerShell braces (Where-Object/ForEach-Object
    scriptblocks, `@{...}` calculated properties) sitting alongside their
    real `{varname}` placeholders in the SAME live wcl_kg/windows_commands_db
    the resolver actually ships with -- meaning every dispatch attempt at
    those commands silently failed with a caught KeyError/ValueError and
    reported a fake "Done." without ever running anything. Fixed by
    escaping every literal brace that ISN'T part of a declared
    `{varname}` placeholder, verified to reproduce the exact same final
    PowerShell text the original template intended.

    This test pins the fix against the REAL shipped database (same
    "actually run it" standard as the rest of this file), not a
    synthetic fixture, and would fail immediately if that escaping regressed
    -- e.g. if the dataset is regenerated from source without carrying
    the fix forward.
    """

    def test_every_command_with_variables_formats_cleanly_in_the_live_db(self):
        import kuzu

        db = kuzu.Database(str(DB_PATH), read_only=True)
        conn = kuzu.Connection(db)
        res = conn.execute("MATCH (c:Command) RETURN c.id, c.name, c.syntax")
        rows = []
        while res.has_next():
            rows.append(res.get_next())
        conn.close()

        variables_by_id = _load_variables_by_command_id()

        failures = []
        checked_with_vars = 0
        for cid, name, syntax in rows:
            declared = variables_by_id.get(cid, [])
            if not declared:
                continue
            checked_with_vars += 1
            dummy = {v: "X" for v in declared}
            try:
                syntax.format(**dummy)
            except Exception as e:
                failures.append((cid, name, str(e)))

        assert checked_with_vars >= 12, (
            "expected at least the 12 known variable-having commands to "
            "be present in the live DB -- got fewer, something else changed"
        )
        assert failures == [], (
            f"{len(failures)} WCL command(s) with declared variables would "
            f"crash orchestrator.py's real dispatch .format() call: {failures}"
        )

    def test_the_12_originally_broken_commands_are_specifically_fixed(self):
        import kuzu

        originally_broken_ids = {
            "1153", "1159", "1036", "1042", "0988", "0989",
            "1092", "1093", "1043", "1003", "1004", "1045",
        }
        variables_by_id = _load_variables_by_command_id()

        db = kuzu.Database(str(DB_PATH), read_only=True)
        conn = kuzu.Connection(db)
        for cid in originally_broken_ids:
            res = conn.execute("MATCH (c:Command {id: $id}) RETURN c.name, c.syntax", {"id": cid})
            row = res.get_next()
            assert row is not None, f"command id {cid} missing from live DB entirely"
            name, syntax = row[0], row[1]
            declared = variables_by_id.get(cid, [])
            dummy = {v: "X" for v in declared}
            try:
                syntax.format(**dummy)
            except Exception as e:
                pytest.fail(f"{cid} ({name}) still crashes .format(): {e}")
        conn.close()


def _load_variables_by_command_id():
    import json
    json_path = DB_PATH.parent / "windows_command_library.widened.json"
    data = json.loads(json_path.read_text())
    return {d["id"]: [v["name"] for v in d.get("variables", [])] for d in data}


class TestConditionVariableIsCodeLikeBlocked:
    """BETA 0.3.37 checkpoint 1: `condition` (used by the "safe" `?`/
    `where` WCL commands, substituted directly into a live
    `Where-Object { ... }` PowerShell scriptblock) was NOT covered by
    extractor.py's code-like variable blocklist before this checkpoint --
    the exact same raw-expression-injection shape `script_block` is
    already blocked for, just missed under a different variable name.
    """

    def test_condition_is_code_like(self):
        from extractor import _is_wcl_code_like_var
        assert _is_wcl_code_like_var("condition") is True

    def test_where_command_variable_never_auto_extracted(self):
        from extractor import extract_slots
        # Whatever a user says here, a `condition` variable must never
        # resolve to a real value -- same "ask instead of guess" posture
        # as script_block, since this is live PowerShell scriptblock
        # content with no safe way to validate it's not malicious.
        result = extract_slots(
            "WCL_where", 'where $_.Name -eq "evil"',
            wcl_variables=["condition"],
        )
        assert result is None
