"""Full self-consistency sweep: every real alias in the graph, queried
verbatim, should resolve RESOLVED back to its OWN command (tier 1, exact
match) -- or, if that literal alias text is genuinely shared by 2+
different commands, AMBIGUOUS listing all of them. Anything else is a
real bug: either the resolver failing on data that should trivially hit
tier 1, or a genuine alias-text collision worth knowing about.
"""
from wcl_resolver import WCLResolver
from collections import defaultdict
import time

r = WCLResolver()
rows = r._all_alias_rows()
print(f"Total (alias, command) rows: {len(rows)}")

# Group by alias text first to find true collisions up front (cheap, no DB calls)
by_alias = defaultdict(set)
for alias_text, name, *_ in rows:
    by_alias[alias_text].add(name)

collisions = {a: cmds for a, cmds in by_alias.items() if len(cmds) > 1}
print(f"Distinct alias texts: {len(by_alias)}")
print(f"Alias texts shared by 2+ DIFFERENT commands (true collisions): {len(collisions)}")

# Now the real sweep: for every DISTINCT alias text, call resolve() and check
t0 = time.time()
mismatches = []      # alias resolves, but to the WRONG command (real bug)
false_unresolved = []  # alias fails to resolve at all (real bug)
n = 0
for alias_text, expected_cmds in by_alias.items():
    n += 1
    res = r.resolve(alias_text)
    if res["status"] == "RESOLVED":
        if res["command"] not in expected_cmds:
            mismatches.append((alias_text, expected_cmds, res["command"], res["tier"]))
    elif res["status"] == "AMBIGUOUS":
        got = {c[0] for c in res["candidates"]}
        if not got.issuperset(expected_cmds) and len(expected_cmds) == 1:
            # single true owner, but resolver produced ambiguity with OTHER commands not in the raw collision set
            if got != expected_cmds:
                mismatches.append((alias_text, expected_cmds, got, res["tier"]))
    else:
        false_unresolved.append((alias_text, expected_cmds))

elapsed = time.time() - t0
print(f"\nSwept {n} distinct alias texts in {elapsed:.1f}s")
print(f"Real mismatches (resolved to WRONG command(s)): {len(mismatches)}")
print(f"Real false-UNRESOLVED (alias exists but resolve() misses it): {len(false_unresolved)}")

print("\n--- sample mismatches (up to 15) ---")
for m in mismatches[:15]:
    print(m)

print("\n--- sample false-unresolved (up to 15) ---")
for f in false_unresolved[:15]:
    print(f)
