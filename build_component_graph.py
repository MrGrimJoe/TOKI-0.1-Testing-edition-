"""
build_component_graph.py -- loads graph_source_data/tier_a_components.py
into Kuzu as real Component nodes and REQUIRES_COMPONENT/ANY_OF_COMPONENT/
FORBIDS_COMPONENT edges, on a COPY of toki_graph_db (never the real one).

This is the "make the database properly" step: component_router_kuzu.py
below queries these tables directly via Cypher at match time -- the
routing decision is computed IN the graph, not by importing a Python
dict and matching in-process.
"""

import sys
from pathlib import Path

import kuzu

from graph_source_data.tier_a_components import COMPONENTS, INTENT_COMPONENT_MAP


def build(db_path: Path):
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    def table_exists(name):
        try:
            conn.execute(f"MATCH (n:{name}) RETURN count(*) LIMIT 1")
            return True
        except Exception:
            return False

    def rel_exists(name):
        try:
            conn.execute(f"MATCH ()-[r:{name}]->() RETURN count(*) LIMIT 1")
            return True
        except Exception:
            return False

    if not table_exists("Component"):
        conn.execute("""
            CREATE NODE TABLE Component(
                id STRING, canonical_name STRING, category STRING,
                aliases STRING[], description STRING, PRIMARY KEY(id)
            )
        """)
        print("[+] Created Component table")

    for rel in ("REQUIRES_COMPONENT", "ANY_OF_COMPONENT", "FORBIDS_COMPONENT"):
        if not rel_exists(rel):
            conn.execute(f"CREATE REL TABLE {rel}(FROM Command TO Component)")
            print(f"[+] Created {rel}")

    loaded = 0
    for comp_id, comp_def in COMPONENTS.items():
        exists = conn.execute("MATCH (c:Component {id: $id}) RETURN c.id", {"id": comp_id})
        if exists.has_next():
            continue
        conn.execute(
            """CREATE (c:Component {id: $id, canonical_name: $cname, category: $ccat,
                                     aliases: $aliases_val, description: $description_val})""",
            {"id": comp_id, "cname": comp_def["canonical_name"], "ccat": comp_def["category"],
             "aliases_val": comp_def["aliases"], "description_val": comp_def["description"]},
        )
        loaded += 1
    print(f"[+] Loaded {loaded} Component nodes ({len(COMPONENTS)} total defined)")

    edges = 0
    skipped = []
    for intent_name, req in INTENT_COMPONENT_MAP.items():
        cmd_result = conn.execute(
            "MATCH (c:Command {name: $name}) WHERE c.tier = 'A' RETURN c.id", {"name": intent_name}
        )
        if not cmd_result.has_next():
            skipped.append(intent_name)
            continue
        cmd_id = cmd_result.get_next()[0]

        for rel, key in (("REQUIRES_COMPONENT", "required"), ("ANY_OF_COMPONENT", "any_of"),
                          ("FORBIDS_COMPONENT", "forbidden")):
            for comp_id in req.get(key, []):
                check = conn.execute(
                    f"""MATCH (c:Command {{id: $cid}})-[:{rel}]->(comp:Component {{id: $compid}})
                        RETURN count(*) AS cnt""",
                    {"cid": cmd_id, "compid": comp_id},
                )
                if check.has_next() and check.get_next()[0] > 0:
                    continue
                conn.execute(
                    f"""MATCH (c:Command {{id: $cid}}), (comp:Component {{id: $compid}})
                        CREATE (c)-[:{rel}]->(comp)""",
                    {"cid": cmd_id, "compid": comp_id},
                )
                edges += 1

    print(f"[+] Created {edges} component-requirement edges")
    if skipped:
        print(f"[i] Skipped (no matching Command node -- expected for GENERATE_FILE, "
              f"runtime-injected by orchestrator.py): {skipped}")

    conn.close()
    db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "toki_graph_db_v2_fair_test"
    path = Path(__file__).parent / target
    if not path.exists():
        print(f"[!] {path} missing")
        sys.exit(1)
    build(path)
    print("[✓] Done")
