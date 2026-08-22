"""
audit_tier_a.py -- systematic sweep over the ENTIRE Tier A phrasing corpus,
not just the pre-existing pytest regression cases.

Two checks:

1. SELF-CONSISTENCY: every phrasing string that's actually committed to
   graph_source_data/tier_a_phrasings.py must classify() back to its own
   intent. If it doesn't, either the corpus is internally contradictory
   (two intents both claim near-identical wording) or CONFIDENCE_THRESHOLD
   dilution has pushed it below the cutoff -- either way, it's a phrasing
   that's in the data but not actually reachable, which is worse than not
   having it at all (false confidence in coverage).

2. MARGIN CHECK: for every phrasing that DOES self-classify correctly,
   how close is the #2 intent behind it? A thin margin (<0.05) flags a
   command pair that's one future phrasing addition away from flipping --
   worth knowing about even if nothing is broken today.

Run after every migrate_to_kuzu.py rebuild.
"""
import sys
from graph_router import GraphRouter, normalize, content_words, expand_synonyms, NON_GRAPH_CATEGORIES
from graph_source_data.tier_a_phrasings import TIER_A_PHRASINGS

router = GraphRouter()


def top2(query: str):
    norm = normalize(query)
    words = content_words(norm)
    if not words:
        return None, 0.0, None, 0.0
    mw = expand_synonyms(words)
    matches = router._fetch_dispatchable_matches(mw)
    if not matches:
        return None, 0.0, None, 0.0
    vectors, idf = router._get_tfidf_index()
    import math
    qvec = {}
    for w in mw:
        qvec[w] = qvec.get(w, 0.0) + idf.get(w, 0.0)
    qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
    scores = {}
    candidate_cmds = {c for c, _ in matches}
    for cmd in candidate_cmds:
        cvec = vectors.get(cmd, {})
        dot = sum(qvec.get(w, 0.0) * cvec.get(w, 0.0) for w in qvec)
        cnorm = math.sqrt(sum(v * v for v in cvec.values())) or 1.0
        scores[cmd] = dot / (qnorm * cnorm)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    first = ranked[0] if len(ranked) > 0 else (None, 0.0)
    second = ranked[1] if len(ranked) > 1 else (None, 0.0)
    return first[0], first[1], second[0], second[1]


failures = []
thin_margins = []
total = 0

for intent, phrasings in TIER_A_PHRASINGS.items():
    for p in phrasings:
        total += 1
        result = router.classify(p)
        got = result["intent"] if result else None
        if intent in NON_GRAPH_CATEGORIES:
            # CHAT/ASK_CONTEXT are deliberately filtered out of classify()
            # by design (NON_GRAPH_CATEGORIES, BETA 0.3.3) -- they exist
            # in the graph for TF-IDF grounding but should never win a
            # direct dispatch. A None here is correct; the real thing to
            # check is that nothing ELSE (a genuine Tier A command) is
            # accidentally winning instead.
            top, score, second, score2 = top2(p)
            if top not in (None, "CHAT") and score >= 0.5:
                failures.append((intent, p, top, top, score))
            continue
        if got != intent:
            top, score, second, score2 = top2(p)
            failures.append((intent, p, got, top, score))
        else:
            top, score, second, score2 = top2(p)
            margin = score - score2
            if margin < 0.05:
                thin_margins.append((intent, p, second, score, score2, margin))

print(f"Checked {total} phrasings across {len(TIER_A_PHRASINGS)} intents.\n")

print(f"=== SELF-CONSISTENCY FAILURES: {len(failures)} ===")
for intent, phrase, got, top_scored, score in failures:
    print(f"  [{intent}] {phrase!r}")
    print(f"      -> classify() returned: {got!r} (raw top score: {top_scored} @ {score:.3f})")

print()
print(f"=== THIN MARGINS (<0.05 between #1 and #2): {len(thin_margins)} ===")
for intent, phrase, second, s1, s2, margin in sorted(thin_margins, key=lambda x: x[-1]):
    print(f"  [{intent}] {phrase!r} beats [{second}] by only {margin:.3f} ({s1:.3f} vs {s2:.3f})")

sys.exit(1 if failures else 0)
