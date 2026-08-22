"""
Deterministic resolution policy for the command KG. No confidence scores --
just a strict tier order. The model is only ever consulted for status
UNRESOLVED or AMBIGUOUS-with-no-tiebreak. Everything else is decided by the
graph alone.
"""
import kuzu
import re
import difflib

db = kuzu.Database("/home/claude/kg_build/windows_commands_db")
conn = kuzu.Connection(db)

# Cache every alias once so fuzzy matching doesn't hit the DB per-candidate.
_ALL_ALIASES = None


def all_aliases():
    global _ALL_ALIASES
    if _ALL_ALIASES is None:
        res = conn.execute("MATCH (a:Alias) RETURN a.text")
        _ALL_ALIASES = []
        while res.has_next():
            _ALL_ALIASES.append(res.get_next()[0])
    return _ALL_ALIASES


FILLER_PREFIXES = [
    "please ", "could you ", "can you ", "would you ", "i want to ",
    "i need to ", "how do i ", "how do you ", "how to ",
]


def normalize(q: str) -> str:
    q = q.lower().strip()
    q = re.sub(r"[^\w\s]", "", q)   # strip punctuation
    q = re.sub(r"\s+", " ", q)
    changed = True
    while changed:
        changed = False
        for prefix in FILLER_PREFIXES:
            if q.startswith(prefix):
                q = q[len(prefix):]
                changed = True
    return q.strip()


def resolve(query: str):
    q = normalize(query)

    # Tier 1: exact literal alias match
    res = conn.execute(
        "MATCH (a:Alias {text: $q})<-[:HasAlias]-(c:Command) RETURN c.name, c.syntax",
        {"q": q},
    )
    candidates = [(r[0], r[1]) for r in res.get_all() if True] if False else []
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    if len(rows) == 1:
        return {"status": "RESOLVED", "tier": 1, "command": rows[0][0], "syntax": rows[0][1]}
    if len(rows) > 1:
        return {"status": "AMBIGUOUS", "tier": 1, "candidates": rows}

    # Tier 3: SynonymOf 1-hop from any recognized leading token (try the
    # 2-word verb phrase first, e.g. "turn on", then fall back to 1 word)
    tokens = q.split()
    leading_candidates = []
    if len(tokens) >= 2:
        leading_candidates.append(" ".join(tokens[:2]))
    if tokens:
        leading_candidates.append(tokens[0])
    for phrase in leading_candidates:
        res = conn.execute(
            """
            MATCH (start:Intent {name: $phrase})-[:SynonymOf*0..1]->(syn:Intent)
                  <-[:HasIntent]-(c:Command)-[:HasAlias]->(a:Alias)
            WHERE a.text CONTAINS $rest
            RETURN DISTINCT c.name, c.syntax
            """,
            {"phrase": phrase, "rest": q.replace(phrase, "").strip() or q},
        )
        rows = []
        while res.has_next():
            rows.append(res.get_next())
        if len(rows) == 1:
            return {"status": "RESOLVED", "tier": 3, "command": rows[0][0], "syntax": rows[0][1]}
        if len(rows) > 1:
            return {"status": "AMBIGUOUS", "tier": 3, "candidates": rows}

    # Tier 4: fuzzy near-miss against real alias text -- catches typos/odd
    # phrasing that isn't an exact match anywhere but is clearly "close to"
    # something real. Still zero model calls; difflib is just string math.
    close = difflib.get_close_matches(q, all_aliases(), n=3, cutoff=0.82)
    if close:
        rows = []
        for alias_text in close:
            res = conn.execute(
                "MATCH (a:Alias {text: $t})<-[:HasAlias]-(c:Command) RETURN c.name, c.syntax",
                {"t": alias_text},
            )
            while res.has_next():
                rows.append(res.get_next())
        distinct = list({(r[0], r[1]) for r in rows})
        if len(distinct) == 1:
            return {"status": "RESOLVED", "tier": 4, "command": distinct[0][0],
                     "syntax": distinct[0][1], "matched_alias": close[0]}
        if len(distinct) > 1:
            return {"status": "AMBIGUOUS", "tier": 4, "candidates": distinct}

    return {"status": "UNRESOLVED", "tier": None, "loose_candidates": loose_search(q)}


def loose_search(q: str, limit: int = 8):
    """
    Last resort before the model: no exact/synonym match exists, so widen
    to substring search across description/category/name. This is NOT
    returned as a resolved answer -- it's grounding material handed to the
    model so it picks from real commands instead of generating one from
    scratch. Keep this list, even if imperfect, in front of the model.
    """
    words = [w for w in q.split() if len(w) > 2]
    if not words:
        return []
    res = conn.execute(
        """
        MATCH (c:Command)
        WHERE ANY(w IN $words WHERE c.description CONTAINS w OR c.category CONTAINS w OR c.name CONTAINS w)
        RETURN c.name, c.description, c.syntax
        LIMIT $limit
        """,
        {"words": words, "limit": limit},
    )
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    return rows


def log_unresolved(query: str, path="/home/claude/kg_build/unresolved_queries.log"):
    """Append genuinely-unresolved queries so vocab.py can be widened later."""
    with open(path, "a") as f:
        f.write(query.strip() + "\n")


def verify_model_suggestion(command_name: str):
    """
    Call this on whatever command name the model proposes for an UNRESOLVED
    query, BEFORE trusting or executing it. A model suggestion is only as
    safe as the metadata we can attach to it -- if it doesn't correspond to
    a real node, it carries none of the danger_level/requires_admin/
    requires_confirmation vetting every graph-resolved command has.
    """
    res = conn.execute(
        """
        MATCH (c:Command {name: $name})
        RETURN c.syntax, c.danger_level, c.requires_admin, c.requires_confirmation
        """,
        {"name": command_name},
    )
    if res.has_next():
        syntax, danger, admin, confirm = res.get_next()
        return {
            "grounded": True,
            "syntax": syntax,
            "danger_level": danger,
            "requires_admin": admin,
            "requires_confirmation": confirm,
        }
    return {"grounded": False}


TEST_QUERIES = [
    "show ipsec rule",                     # tier 1, exact literal
    "print net ipsec rule",                # tier 1, only exists via widening
    "please turn on bitlocker",            # punctuation/filler word stripped
    "kill process",                        # tier 1
    "kil the procces",                     # typo -> tier 4 fuzzy, still no model
    "virtual vm",                          # deliberately ambiguous (8 VM cmds)
    "reticulate the splines",              # genuinely nothing -- must escalate
]

for q in TEST_QUERIES:
    result = resolve(q)
    print(f"{q!r:35} -> {result}")

print("\n--- Grounding a model suggestion for the truly unresolved query ---")
# Pretend the model, given "reticulate the splines" had no real command in
# mind and (correctly) said it doesn't know -- vs. a case where it guesses
# a plausible-sounding but WRONG cmdlet name.
for guess in ["Get-Process", "Reticulate-Splines"]:
    print(f"model guessed {guess!r:25} -> {verify_model_suggestion(guess)}")
