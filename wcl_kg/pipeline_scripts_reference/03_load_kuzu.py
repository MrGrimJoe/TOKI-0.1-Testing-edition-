"""
Builds the Kuzu database from schema.cypher + the normalized CSVs.
Run once to (re)create ./windows_commands_db.
"""
import kuzu
import shutil
import os

DB_PATH = "/home/claude/kg_build/windows_commands_db"
CSV_DIR = "/home/claude/kg_build/csv"

if os.path.exists(DB_PATH):
    shutil.rmtree(DB_PATH)

db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

# --- schema ---
with open("/home/claude/kg_build/schema.cypher") as f:
    for stmt in f.read().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)

# --- node tables ---
conn.execute(f'COPY Command FROM "{CSV_DIR}/command.csv" (header=true)')
conn.execute(f'COPY Category FROM "{CSV_DIR}/category.csv" (header=true)')
conn.execute(f'COPY Module FROM "{CSV_DIR}/module.csv" (header=true)')
conn.execute(f'COPY Intent FROM "{CSV_DIR}/intent.csv" (header=true)')
conn.execute(f'COPY Alias FROM "{CSV_DIR}/alias.csv" (header=true)')
conn.execute(f'COPY VariableType FROM "{CSV_DIR}/variable_type.csv" (header=true)')
conn.execute(f'COPY Example FROM "{CSV_DIR}/example.csv" (header=true)')

# --- relationship tables ---
conn.execute(f'COPY InCategory FROM "{CSV_DIR}/command_in_category.csv" (header=true)')
conn.execute(f'COPY RequiresModule FROM "{CSV_DIR}/command_requires_module.csv" (header=true)')
conn.execute(f'COPY HasIntent FROM "{CSV_DIR}/command_has_intent.csv" (header=true)')
conn.execute(f'COPY HasAlias FROM "{CSV_DIR}/command_has_alias.csv" (header=true)')
conn.execute(f'COPY HasVariable FROM "{CSV_DIR}/command_has_variable.csv" (header=true)')
conn.execute(f'COPY HasExample FROM "{CSV_DIR}/command_has_example.csv" (header=true)')
conn.execute(f'COPY SynonymOf FROM "{CSV_DIR}/synonym_of.csv" (header=true)')

print("Database built at", DB_PATH)

# sanity counts
for tbl in ["Command", "Category", "Module", "Intent", "Alias", "VariableType", "Example"]:
    r = conn.execute(f"MATCH (n:{tbl}) RETURN count(n)")
    print(f"  {tbl}: {r.get_next()[0]}")
