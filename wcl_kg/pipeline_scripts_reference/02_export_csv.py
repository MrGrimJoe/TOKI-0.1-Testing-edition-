"""
Normalizes windows_command_library.fixed.json into node/relationship CSV
tables ready for Kuzu COPY FROM.

Why normalize at all?
Kuzu is a *structured* property graph: every node/rel table has a fixed,
typed schema. The source JSON nests variable-length lists (intents, aliases,
variables, examples) as arrays-of-objects inside each command record. Kuzu
has no native "array of struct" column type you can traverse, filter, or
join on -- so those nested arrays must become their own node tables
connected by relationships. That's what makes intent matching and slot
filling "effortless" for a KG: instead of parsing JSON blobs at query time,
the graph engine just walks edges.

Output tables (all under ./csv/):
  Node tables:
    command.csv        one row per command
    category.csv        26 distinct categories
    module.csv           distinct required_module values
    intent.csv            distinct intent tokens
    alias.csv              distinct alias phrases (normalized, lowercase)
    variable_type.csv    distinct variable *names* (deduped across commands),
                          each tagged with an inferred value_type used for
                          slot-filling validation (e.g. "path", "ip_address")
    example.csv           one row per worked example

  Relationship tables (Command -> X), each carries a `position` (0-indexed,
  preserves original order -- e.g. position 0 alias/intent is the primary one):
    command_in_category.csv
    command_requires_module.csv
    command_has_intent.csv
    command_has_alias.csv
    command_has_variable.csv   (+ example_value property, for slot defaults)
    command_has_example.csv
"""
import json
import csv
import re
import os

SRC = "/home/claude/kg_build/windows_command_library.widened.json"
OUTDIR = "/home/claude/kg_build/csv"
os.makedirs(OUTDIR, exist_ok=True)

data = json.load(open(SRC))


def norm(s: str) -> str:
    return s.strip().lower()


# ---------------------------------------------------------------------------
# value_type inference for VariableType nodes -- used so a slot-filling KG
# knows what shape of value to expect/validate for a given variable name,
# without re-deriving it from the free-text `description` at query time.
# ---------------------------------------------------------------------------
TYPE_RULES = [
    (r"ip_address|ip$", "ip_address"),
    (r"mac_address", "mac_address"),
    (r"^uri$|url", "uri"),
    (r"port$", "port"),
    (r"(^|_)(id|_id)$|session_id|job_id|client_id|acl_id|mapping_id", "identifier"),
    (r"path", "path"),
    (r"enabled$|^is_|_flag$", "boolean"),
    (r"count$|number$|_range$|size$", "integer"),
    (r"date|time", "datetime"),
    (r"server|host|computer_name", "hostname"),
    (r"name$", "name"),
]


def infer_value_type(varname: str) -> str:
    for pattern, vtype in TYPE_RULES:
        if re.search(pattern, varname):
            return vtype
    return "generic"


# ---------------------------------------------------------------------------
# Collect distinct dimension values
# ---------------------------------------------------------------------------
categories, modules, intents, aliases = set(), set(), set(), set()
variable_types = {}  # name -> (description, value_type)  first description wins

for d in data:
    categories.add(d["category"])
    if d["required_module"]:
        modules.add(d["required_module"])
    for i in d["intents"]:
        intents.add(norm(i))
    for a in d["aliases"]:
        aliases.add(norm(a))
    for v in d["variables"]:
        if v["name"] not in variable_types:
            variable_types[v["name"]] = (v["description"], infer_value_type(v["name"]))

# ---------------------------------------------------------------------------
# Write node tables
# ---------------------------------------------------------------------------
with open(f"{OUTDIR}/command.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(
        [
            "id", "name", "tool", "category", "description", "syntax",
            "danger_level", "requires_admin", "requires_confirmation",
            "platform", "availability",
        ]
    )
    for d in data:
        w.writerow(
            [
                d["id"], d["name"], d["tool"], d["category"], d["description"],
                d["syntax"], d["danger_level"], d["requires_admin"],
                d["requires_confirmation"], d["platform"], d["availability"],
            ]
        )

with open(f"{OUTDIR}/category.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name"])
    for c in sorted(categories):
        w.writerow([c])

with open(f"{OUTDIR}/module.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name"])
    for m in sorted(modules):
        w.writerow([m])

with open(f"{OUTDIR}/intent.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name"])
    for i in sorted(intents):
        w.writerow([i])

with open(f"{OUTDIR}/alias.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["text"])
    for a in sorted(aliases):
        w.writerow([a])

with open(f"{OUTDIR}/variable_type.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["name", "description", "value_type"])
    for name, (desc, vtype) in sorted(variable_types.items()):
        w.writerow([name, desc, vtype])

with open(f"{OUTDIR}/example.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "user_input", "resolved_command"])
    for d in data:
        for idx, ex in enumerate(d["examples"]):
            w.writerow([f"{d['id']}-{idx}", ex["user_input"], ex["resolved_command"]])

# ---------------------------------------------------------------------------
# Write relationship tables
# ---------------------------------------------------------------------------
with open(f"{OUTDIR}/command_in_category.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "category_name"])
    for d in data:
        w.writerow([d["id"], d["category"]])

with open(f"{OUTDIR}/command_requires_module.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "module_name"])
    for d in data:
        if d["required_module"]:
            w.writerow([d["id"], d["required_module"]])

with open(f"{OUTDIR}/command_has_intent.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "intent_name", "position"])
    for d in data:
        for pos, i in enumerate(d["intents"]):
            w.writerow([d["id"], norm(i), pos])

with open(f"{OUTDIR}/command_has_alias.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "alias_text", "position"])
    for d in data:
        for pos, a in enumerate(d["aliases"]):
            w.writerow([d["id"], norm(a), pos])

with open(f"{OUTDIR}/command_has_variable.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "variable_name", "position", "example_value"])
    for d in data:
        for pos, v in enumerate(d["variables"]):
            w.writerow([d["id"], v["name"], pos, v["example"]])

with open(f"{OUTDIR}/command_has_example.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["command_id", "example_id"])
    for d in data:
        for idx, ex in enumerate(d["examples"]):
            w.writerow([d["id"], f"{d['id']}-{idx}"])

print("Node counts:")
print("  command       ", len(data))
print("  category      ", len(categories))
print("  module        ", len(modules))
print("  intent        ", len(intents))
print("  alias         ", len(aliases))
print("  variable_type ", len(variable_types))
print("  example       ", sum(len(d["examples"]) for d in data))
