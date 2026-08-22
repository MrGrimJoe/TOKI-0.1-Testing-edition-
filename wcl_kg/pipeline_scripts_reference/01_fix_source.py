"""
Fixes the 5 known data-quality bugs in windows_command_library.json before
normalizing it into a Kuzu graph. Writes windows_command_library.fixed.json.

Bugs fixed:
1. Four "kill process" commands (kill, Stop-Process, taskkill, spps) list
   TWO variables (process_id + process_name) but their `syntax` string only
   contains ONE placeholder. A slot-filling KG would try to fill a variable
   that has nowhere to go in the syntax. Fix: keep only the variable that
   actually appears in `syntax`.
2. mstsc /noConsentPrompt (id 0955): `syntax` references {server} AND
   {session_id}, but `variables` only declares {server}. Fix: add the missing
   session_id variable, and fill it in both worked examples (previously left
   as a literal, un-substituted "{session_id}" string).
"""
import json

SRC = "/mnt/user-data/uploads/windows_command_library.json"
OUT = "/home/claude/kg_build/windows_command_library.fixed.json"

data = json.load(open(SRC))

fixes_applied = []

for d in data:
    # --- Bug 1: process_id / process_name mismatch ---
    if d["id"] in ("0982", "0012", "0812", "0983"):
        keep = "process_id" if "{process_id}" in d["syntax"] else "process_name"
        before = [v["name"] for v in d["variables"]]
        d["variables"] = [v for v in d["variables"] if v["name"] == keep]
        fixes_applied.append(
            f"{d['id']} {d['name']}: trimmed variables {before} -> [{keep}] "
            f"to match syntax '{d['syntax']}'"
        )

    # --- Bug 2: mstsc missing session_id variable ---
    if d["id"] == "0955":
        d["variables"].append(
            {
                "name": "session_id",
                "description": "Numeric ID of the remote desktop session to shadow",
                "example": "2",
            }
        )
        for ex in d["examples"]:
            ex["resolved_command"] = ex["resolved_command"].replace(
                "{session_id}", "2"
            )
        fixes_applied.append(
            f"0955 {d['name']}: added missing session_id variable and filled "
            f"it into resolved_command examples"
        )

json.dump(data, open(OUT, "w"), indent=2)

print(f"Wrote {OUT}")
print(f"\n{len(fixes_applied)} fixes applied:")
for f in fixes_applied:
    print(" -", f)
