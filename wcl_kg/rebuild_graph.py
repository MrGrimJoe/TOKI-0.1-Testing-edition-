"""
rebuild_graph.py -- rebuilds wcl_kg/windows_commands_db from
windows_command_library.widened.json. Same logic as
pipeline_scripts_reference/02_export_csv.py + 03_load_kuzu.py +
06_export_synonyms.py, adapted to this repo's actual paths (the reference
scripts hard-code /home/claude/kg_build/, a build-time-only sandbox path
that isn't part of this checkout).

Run this after any edit to windows_command_library.widened.json (e.g.
add_coverage_aliases.py) to make the change take effect at runtime --
wcl_resolver.py queries the compiled Kuzu db directly, never the JSON.
"""

import csv
import json
import re
import shutil
from pathlib import Path

import kuzu

from vocab import VERB_CLUSTERS

HERE = Path(__file__).parent
SRC = HERE / "windows_command_library.widened.json"
CSV_DIR = HERE / "_build_csv"
DB_PATH = HERE / "windows_commands_db"
SCHEMA_PATH = HERE / "pipeline_scripts_reference" / "schema.cypher"

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


def norm(s: str) -> str:
    return s.strip().lower()


def export_csv(data):
    CSV_DIR.mkdir(exist_ok=True)

    categories, modules, intents, aliases = set(), set(), set(), set()
    variable_types = {}
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

    with open(CSV_DIR / "command.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "tool", "category", "description", "syntax",
                    "danger_level", "requires_admin", "requires_confirmation",
                    "platform", "availability"])
        for d in data:
            w.writerow([d["id"], d["name"], d["tool"], d["category"], d["description"],
                        d["syntax"], d["danger_level"], d["requires_admin"],
                        d["requires_confirmation"], d["platform"], d["availability"]])

    with open(CSV_DIR / "category.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["name"])
        for c in sorted(categories): w.writerow([c])

    with open(CSV_DIR / "module.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["name"])
        for m in sorted(modules): w.writerow([m])

    with open(CSV_DIR / "intent.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["name"])
        for i in sorted(intents): w.writerow([i])

    with open(CSV_DIR / "alias.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["text"])
        for a in sorted(aliases): w.writerow([a])

    with open(CSV_DIR / "variable_type.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["name", "description", "value_type"])
        for name, (desc, vtype) in sorted(variable_types.items()):
            w.writerow([name, desc, vtype])

    with open(CSV_DIR / "example.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "user_input", "resolved_command"])
        for d in data:
            for idx, ex in enumerate(d["examples"]):
                w.writerow([f"{d['id']}-{idx}", ex["user_input"], ex["resolved_command"]])

    with open(CSV_DIR / "command_in_category.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "category_name"])
        for d in data: w.writerow([d["id"], d["category"]])

    with open(CSV_DIR / "command_requires_module.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "module_name"])
        for d in data:
            if d["required_module"]: w.writerow([d["id"], d["required_module"]])

    with open(CSV_DIR / "command_has_intent.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "intent_name", "position"])
        for d in data:
            for pos, i in enumerate(d["intents"]): w.writerow([d["id"], norm(i), pos])

    with open(CSV_DIR / "command_has_alias.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "alias_text", "position"])
        for d in data:
            for pos, a in enumerate(d["aliases"]): w.writerow([d["id"], norm(a), pos])

    with open(CSV_DIR / "command_has_variable.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "variable_name", "position", "example_value"])
        for d in data:
            for pos, v in enumerate(d["variables"]):
                w.writerow([d["id"], v["name"], pos, v["example"]])

    with open(CSV_DIR / "command_has_example.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["command_id", "example_id"])
        for d in data:
            for idx, ex in enumerate(d["examples"]):
                w.writerow([d["id"], f"{d['id']}-{idx}"])

    # synonym_of.csv -- pairwise edges between Intent nodes in the same
    # VERB_CLUSTERS cluster, restricted to intents that actually exist as
    # nodes (same logic as pipeline_scripts_reference/06_export_synonyms.py)
    pairs = set()
    for cluster in VERB_CLUSTERS:
        members = sorted(p for p in cluster if p in intents)
        for a in members:
            for b in members:
                if a != b:
                    pairs.add((a, b))
    with open(CSV_DIR / "synonym_of.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["intent_a", "intent_b"])
        for a, b in sorted(pairs): w.writerow([a, b])

    return {
        "command": len(data), "category": len(categories), "module": len(modules),
        "intent": len(intents), "alias": len(aliases),
        "variable_type": len(variable_types),
        "example": sum(len(d["examples"]) for d in data),
        "synonym_of": len(pairs),
    }


def load_kuzu():
    if DB_PATH.exists():
        if DB_PATH.is_dir():
            shutil.rmtree(DB_PATH)
        else:
            DB_PATH.unlink()
    # kuzu may also leave a walog/lock sidecar next to the db file
    for sidecar in HERE.glob(str(DB_PATH.name) + ".*"):
        sidecar.unlink()

    db = kuzu.Database(str(DB_PATH))
    conn = kuzu.Connection(db)

    with open(SCHEMA_PATH) as f:
        for stmt in f.read().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)

    conn.execute(f'COPY Command FROM "{CSV_DIR}/command.csv" (header=true)')
    conn.execute(f'COPY Category FROM "{CSV_DIR}/category.csv" (header=true)')
    conn.execute(f'COPY Module FROM "{CSV_DIR}/module.csv" (header=true)')
    conn.execute(f'COPY Intent FROM "{CSV_DIR}/intent.csv" (header=true)')
    conn.execute(f'COPY Alias FROM "{CSV_DIR}/alias.csv" (header=true)')
    conn.execute(f'COPY VariableType FROM "{CSV_DIR}/variable_type.csv" (header=true)')
    conn.execute(f'COPY Example FROM "{CSV_DIR}/example.csv" (header=true)')

    conn.execute(f'COPY InCategory FROM "{CSV_DIR}/command_in_category.csv" (header=true)')
    conn.execute(f'COPY RequiresModule FROM "{CSV_DIR}/command_requires_module.csv" (header=true)')
    conn.execute(f'COPY HasIntent FROM "{CSV_DIR}/command_has_intent.csv" (header=true)')
    conn.execute(f'COPY HasAlias FROM "{CSV_DIR}/command_has_alias.csv" (header=true)')
    conn.execute(f'COPY HasVariable FROM "{CSV_DIR}/command_has_variable.csv" (header=true)')
    conn.execute(f'COPY HasExample FROM "{CSV_DIR}/command_has_example.csv" (header=true)')
    conn.execute(f'COPY SynonymOf FROM "{CSV_DIR}/synonym_of.csv" (header=true)')

    print("Database rebuilt at", DB_PATH)
    for tbl in ["Command", "Category", "Module", "Intent", "Alias", "VariableType", "Example"]:
        r = conn.execute(f"MATCH (n:{tbl}) RETURN count(n)")
        print(f"  {tbl}: {r.get_next()[0]}")
    conn.close()
    db.close()


def main():
    data = json.load(open(SRC))
    counts = export_csv(data)
    print("Exported CSVs:", counts)
    load_kuzu()
    shutil.rmtree(CSV_DIR)


if __name__ == "__main__":
    main()
