"""
Widens windows_command_library.fixed.json into
windows_command_library.widened.json by:

  1. Repairing the acronym-splitting tokenization bug (see vocab.py) in all
     existing aliases.
  2. For every alias that starts with a recognized verb/verb-phrase, adding
     one alias per synonym in that verb's cluster (bare + "the X" form).
  3. Adding every synonym in a matched cluster to the command's `intents`
     list too, so bag-of-tokens intent scoring (see 04_demo_queries.py
     query #2) also widens, independent of exact alias matches.
  4. Deduplicating and stripping any alias that collapses to empty/garbage.

This does NOT touch syntax/variables/examples -- those already passed
validation in 01_fix_source.py.
"""
import json
import re
from vocab import apply_token_fixes, find_leading_cluster

SRC = "/home/claude/kg_build/windows_command_library.fixed.json"
OUT = "/home/claude/kg_build/windows_command_library.widened.json"

data = json.load(open(SRC))

before_alias_total = sum(len(d["aliases"]) for d in data)
before_intent_total = sum(len(d["intents"]) for d in data)
commands_widened = 0

for d in data:
    # --- 1. fix tokenization artifacts on existing aliases ---
    fixed_aliases = [apply_token_fixes(a.strip().lower()) for a in d["aliases"]]

    new_aliases = set(fixed_aliases)
    new_intents = set(i.strip().lower() for i in d["intents"])

    widened_this_command = False
    for alias in fixed_aliases:
        match = find_leading_cluster(alias)
        if not match:
            continue
        _, synonyms, remainder = match
        widened_this_command = True
        for syn in synonyms:
            candidate = f"{syn} {remainder}".strip() if remainder else syn
            candidate = re.sub(r"\s+", " ", candidate)
            new_aliases.add(candidate)
            if remainder and not remainder.startswith("the "):
                new_aliases.add(re.sub(r"\s+", " ", f"{syn} the {remainder}"))
        new_intents |= synonyms

    if widened_this_command:
        commands_widened += 1

    # drop empties/dupes, keep deterministic order: originals first, then new
    ordered_aliases = list(dict.fromkeys(fixed_aliases))
    for a in sorted(new_aliases):
        if a and a not in ordered_aliases:
            ordered_aliases.append(a)

    ordered_intents = list(dict.fromkeys(i.strip().lower() for i in d["intents"]))
    for i in sorted(new_intents):
        if i and i not in ordered_intents:
            ordered_intents.append(i)

    d["aliases"] = ordered_aliases
    d["intents"] = ordered_intents

after_alias_total = sum(len(d["aliases"]) for d in data)
after_intent_total = sum(len(d["intents"]) for d in data)

json.dump(data, open(OUT, "w"), indent=2)

print(f"Wrote {OUT}")
print(f"Commands widened via synonym clusters: {commands_widened} / {len(data)}")
print(f"Aliases:  {before_alias_total} -> {after_alias_total}")
print(f"Intents:  {before_intent_total} -> {after_intent_total}")
