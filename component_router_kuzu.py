"""
component_router_kuzu.py -- EXPERIMENTAL router. Same classify() contract
as graph_router.GraphRouter:
    {"intent": "MAKE_FOLDER"}   confident hit
    None                        miss

Unlike the first draft of this experiment, THIS router resolves
candidates with real Cypher queries against the Component/
REQUIRES_COMPONENT/ANY_OF_COMPONENT/FORBIDS_COMPONENT graph built by
build_component_graph.py -- INTENT_COMPONENT_MAP (the Python dict) is
used ONLY to know how many required/any_of components each intent has
(for the specificity tie-break score), not to decide whether a candidate
qualifies. Qualification itself -- "does this intent's required-component
set subset the extracted-component set, does at least one any_of member
appear, does no forbidden member appear" -- is computed by a Cypher
query, executed once per intent (INTENT_COMPONENT_MAP is only iterated to
know WHICH intents to ask the graph about).

Component extraction (text -> {"ACTION_CREATE", "OBJECT_FOLDER", ...})
happens in Python (component_extractor.py) because token matching against
alias lists is a text-processing step, not a graph query -- same division
of labor graph_router.py itself uses (normalize() in Python, phrasing
lookup in Kuzu).

No LLM anywhere. No cosine similarity, no confidence score, no threshold
constant.
"""

from typing import Dict, List, Optional, Set, Any

import kuzu

from component_extractor import extract_components, all_component_ids

NON_GRAPH_CATEGORIES = {"CHAT", "ASK_CONTEXT"}

# Same purpose as graph_router.py's own _TIE_PREFERENCE: a short, explicit
# table for candidates that tie on specificity with no principled
# component-based way to prefer one. Intentionally left EMPTY at design
# time (frozen before ever running against tests/test_graph_router.py) --
# see TESTING_REPORT.md for whether any ties actually needed one, decided
# by re-examining source phrasings after the fact, not by peeking at
# expected test answers.
_TIE_PREFERENCE: List[tuple] = []


class KuzuComponentRouter:
    def __init__(self, db_path: str):
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        self._load_intent_component_counts()

    def _load_intent_component_counts(self):
        """One-time load of each intent's required/any_of SIZE (for the
        specificity score) straight from the graph itself -- not from
        the Python INTENT_COMPONENT_MAP dict -- so the tie-break is also
        graph-derived, not dict-derived."""
        self._required_count: Dict[str, int] = {}
        self._any_of_ids: Dict[str, Set[str]] = {}

        result = self.conn.execute("""
            MATCH (c:Command)-[:REQUIRES_COMPONENT]->(comp:Component)
            WHERE c.tier = 'A'
            RETURN c.name, count(comp) AS n
        """)
        while result.has_next():
            name, n = result.get_next()
            self._required_count[name] = n

        result = self.conn.execute("""
            MATCH (c:Command)-[:ANY_OF_COMPONENT]->(comp:Component)
            WHERE c.tier = 'A'
            RETURN c.name, comp.id
        """)
        while result.has_next():
            name, comp_id = result.get_next()
            self._any_of_ids.setdefault(name, set()).add(comp_id)

    def classify(self, user_prompt: str) -> Optional[Dict[str, str]]:
        extracted = extract_components(user_prompt)
        have = all_component_ids(extracted)
        if not have:
            return None

        candidates = self._query_candidates(have)
        if not candidates:
            return None
        if len(candidates) == 1:
            intent = candidates[0]
            return None if intent in NON_GRAPH_CATEGORIES else {"intent": intent}

        best = self._resolve_tie(candidates, have)
        if best is None:
            return None
        return None if best in NON_GRAPH_CATEGORIES else {"intent": best}

    def _query_candidates(self, have: Set[str]) -> List[str]:
        """A real Cypher query against the Component graph: for every
        Tier A command, MATCH and collect() its REQUIRES_COMPONENT /
        ANY_OF_COMPONENT / FORBIDS_COMPONENT target ids. The final
        subset/intersection check against `have` is done in Python
        because Kuzu 0.11.3 has a confirmed, reproducible aggregation
        bug: combining two aggregate functions in the same WITH clause
        where one is a parameterized `count(CASE WHEN x.prop IN $param
        THEN 1 END)` silently returns 0 regardless of actual matches
        (verified directly against this database: `req.id IN $have`
        evaluates correctly alone, but count()-wrapping it alongside
        another aggregate over the same pattern does not) -- collect()
        alone doesn't trigger it. This is a Kuzu-version workaround, not
        a design choice: the graph traversal (which components does
        each command require/accept/forbid) still happens entirely in
        Kuzu; only the final boolean subset test happens in Python.
        """
        result = self.conn.execute("""
            MATCH (c:Command) WHERE c.tier = 'A'
            OPTIONAL MATCH (c)-[:REQUIRES_COMPONENT]->(req:Component)
            WITH c, collect(req.id) AS required_ids
            OPTIONAL MATCH (c)-[:ANY_OF_COMPONENT]->(anyof:Component)
            WITH c, required_ids, collect(anyof.id) AS any_of_ids
            OPTIONAL MATCH (c)-[:FORBIDS_COMPONENT]->(forb:Component)
            WITH c, required_ids, any_of_ids, collect(forb.id) AS forbidden_ids
            RETURN c.name, required_ids, any_of_ids, forbidden_ids
        """)
        candidates = []
        while result.has_next():
            name, required_ids, any_of_ids, forbidden_ids = result.get_next()
            required_ids = [x for x in (required_ids or []) if x is not None]
            any_of_ids = [x for x in (any_of_ids or []) if x is not None]
            forbidden_ids = [x for x in (forbidden_ids or []) if x is not None]

            if not required_ids and not any_of_ids:
                continue
            if not set(required_ids).issubset(have):
                continue
            if any_of_ids and not (set(any_of_ids) & have):
                continue
            if set(forbidden_ids) & have:
                continue
            candidates.append(name)
        return candidates

    def _resolve_tie(self, candidates: List[str], have: Set[str]) -> Optional[str]:
        def specificity(intent: str) -> int:
            req = self._required_count.get(intent, 0)
            any_of_matched = len(self._any_of_ids.get(intent, set()) & have)
            return req + any_of_matched

        scored = {c: specificity(c) for c in candidates}
        top = max(scored.values())
        tied = [c for c, s in scored.items() if s == top]
        if len(tied) == 1:
            return tied[0]

        tied_set = set(tied)
        for preferred, other in _TIE_PREFERENCE:
            if {preferred, other} <= tied_set:
                return preferred
        return None  # genuinely ambiguous -- reject, don't guess

    def classify_or_ask(self, user_prompt: str) -> Dict[str, Any]:
        """Mirrors GraphRouter.classify_or_ask()'s three-shape contract
        so orchestrator.py's real, UNMODIFIED _segment_is_viable() /
        _split_chain_if_viable() can drive either router interchangeably
        -- see tests/test_chain_splitting.py, which imports those two
        functions directly from orchestrator.py (never reimplemented)
        and calls them with a KuzuComponentRouter instance in place of
        GraphRouter.

        classify() confident hit -> identical {"intent": X} shape.
        Otherwise, "candidate" is the single Tier A intent with the most
        REQUIRES_COMPONENT members satisfied (even a partial match, e.g.
        ACTION alone) -- the component-model analogue of TF-IDF's "some
        vocabulary overlap, but not enough to auto-dispatch" case. This
        exists ONLY so orchestrator.py's existing
        _NAME_FROM_OUTSIDE_VOCAB_INTENTS whitelist logic has something to
        check .get("candidate") against; it doesn't add any new
        confidence semantics of its own.
        """
        confident = self.classify(user_prompt)
        if confident is not None:
            return confident

        extracted = extract_components(user_prompt)
        have = all_component_ids(extracted)
        if not have:
            return {"ask": "I didn't catch that -- can you rephrase?", "unknown_words": []}

        result = self.conn.execute("""
            MATCH (c:Command) WHERE c.tier = 'A'
            OPTIONAL MATCH (c)-[:REQUIRES_COMPONENT]->(req:Component)
            RETURN c.name, collect(req.id)
        """)
        best_name, best_score = None, 0
        while result.has_next():
            name, required_ids = result.get_next()
            required_ids = [x for x in (required_ids or []) if x is not None]
            if not required_ids:
                continue
            score = len(set(required_ids) & have)
            if score > best_score:
                best_name, best_score = name, score

        return {"ask": "I'm not fully sure what you mean.", "unknown_words": [], "candidate": best_name}

    def close(self):
        self.conn.close()
        self.db.close()
