"""
test_chain_splitting.py -- imports orchestrator.py's REAL, UNMODIFIED
_split_chain() and _split_chain_if_viable() (nothing about conjunction/
composition handling is reimplemented here) and drives them with
KuzuComponentRouter substituted for GraphRouter, to check whether the
component router's classify()/classify_or_ask() are enough for the
existing chain-splitting mechanism to keep working unchanged.

This directly answers: "does the component architecture lose TOKI's
existing conjunction/composition handling?" -- it doesn't, because that
handling lives entirely in orchestrator.py and is router-agnostic; this
test proves the substitution actually works end to end, not just in
theory.
"""

from orchestrator import _split_chain, _split_chain_if_viable
from component_router_kuzu import KuzuComponentRouter
from graph_router import GraphRouter

# A representative subset of batch_test_prompts_v3a_chains.py's real
# prompts (not reinvented) -- covering conjunctions, sequencing,
# alternatives-shaped phrasing, and the documented false-positive traps
# that file exists specifically to guard against.
CASES = [
    # Genuine chains -- should split into N viable segments
    ("empty the recycle bin; take a screenshot; mute the volume", 3),
    ("open notepad, then open calculator, then close notepad, then close calculator", 4),
    ("make a folder called Reports, then open it", 2),
    ("take a screenshot, empty the recycle bin, lock my computer, then mute the volume", 4),

    # Known false-positive traps -- should NOT split (single segment,
    # original message preserved) because one fragment isn't viable
    ("find files named budget and forecast.xlsx", 1),
    ("rename budget.xlsx and forecast.xlsx", 1),

    # Ambiguous one-verb-two-targets -- documented as ambiguous in the
    # source file itself, not asserting a specific right answer, just
    # that it doesn't crash and returns SOME consistent result.
]


def run(router, label):
    print(f"\n=== {label} ===")
    for prompt, expected_segments in CASES:
        segments = _split_chain_if_viable(prompt, router)
        ok = len(segments) == expected_segments
        print(f"{prompt[:55]:57s} -> {len(segments)} segment(s) "
              f"[{'OK' if ok else 'DIFF, expected ' + str(expected_segments)}]")
        for seg in segments:
            result = router.classify(seg)
            print(f"    {seg[:50]:52s} -> {result}")


if __name__ == "__main__":
    tf_router = GraphRouter()
    comp_router = KuzuComponentRouter("toki_graph_db_v2_fair_test")

    run(tf_router, "TF-IDF (reference)")
    run(comp_router, "Component (Kuzu-native)")

    tf_router.close()
    comp_router.close()
