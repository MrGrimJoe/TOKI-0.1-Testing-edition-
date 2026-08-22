"""
Emits synonym_of.csv: pairwise edges between every Intent node that belongs
to the same verb cluster (e.g. show<->display<->view<->list<->get<->...).

This encodes synonymy IN the graph itself, as a second, independent path
to robustness alongside the literal widened aliases: even if a user's exact
phrase was never generated as a literal alias, a 1-hop SynonymOf traversal
from whichever intent token *was* recognized still reaches every command
tagged with any synonym of it.
"""
import csv
from vocab import VERB_CLUSTERS

OUT = "/home/claude/kg_build/csv/synonym_of.csv"

# Only connect intents that actually exist as Intent nodes (i.e. some command
# really uses that token) -- a cluster phrase that no command ever adopted
# isn't a graph node, so skip it rather than fail the COPY.
existing_intents = set()
with open("/home/claude/kg_build/csv/intent.csv") as f:
    next(f)  # header
    for line in f:
        existing_intents.add(line.strip())

pairs = set()
for cluster in VERB_CLUSTERS:
    members = sorted(p for p in cluster if p in existing_intents)
    for a in members:
        for b in members:
            if a != b:
                pairs.add((a, b))

with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["intent_a", "intent_b"])
    for a, b in sorted(pairs):
        w.writerow([a, b])

print(f"Wrote {len(pairs)} SynonymOf edges -> {OUT}")
