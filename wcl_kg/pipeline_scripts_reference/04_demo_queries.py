import kuzu

db = kuzu.Database("/home/claude/kg_build/windows_commands_db")
conn = kuzu.Connection(db)


def run(title, query, params=None):
    print(f"\n=== {title} ===")
    res = conn.execute(query, params or {})
    while res.has_next():
        print(res.get_next())


# 1. Exact alias match -> instant intent resolution (fast path)
run(
    "Exact alias match: 'kill process'",
    """
    MATCH (a:Alias {text: $phrase})<-[:HasAlias]-(c:Command)
    RETURN c.id, c.name, c.syntax
    """,
    {"phrase": "kill process"},
)

# 2. Fuzzy intent match: rank commands by overlap with a bag of intent tokens
#    parsed from free-text user input (e.g. "please terminate this process")
run(
    "Ranked intent match for tokens ['terminate','stop']",
    """
    MATCH (i:Intent)<-[:HasIntent]-(c:Command)
    WHERE i.name IN ['terminate', 'stop']
    RETURN c.name, c.category, count(i) AS score
    ORDER BY score DESC
    LIMIT 5
    """,
)

# 3. Ambiguous alias -> graph surfaces every candidate command instead of
#    silently picking one (this is the disambiguation case found in the audit)
run(
    "Ambiguous alias: 'virtual vm' maps to multiple commands",
    """
    MATCH (a:Alias {text: 'virtual vm'})<-[:HasAlias]-(c:Command)
    RETURN c.name, c.syntax
    """,
)

# 4. Slot filling: once a command is chosen, pull its ordered variable slots
#    plus the inferred value_type, so a KG-backed agent knows what to ask for
#    and how to validate the answer.
run(
    "Slot template for Show-NetIPsecRule",
    """
    MATCH (c:Command {name: 'Show-NetIPsecRule'})-[r:HasVariable]->(v:VariableType)
    RETURN r.position, v.name, v.value_type, v.description, r.example_value
    ORDER BY r.position
    """,
)

# 5. End-to-end: alias -> command -> slots, in one traversal
run(
    "End-to-end: 'display net i psec rule' -> command + slots",
    """
    MATCH (a:Alias {text: $phrase})<-[:HasAlias]-(c:Command)-[r:HasVariable]->(v:VariableType)
    RETURN c.name, c.syntax, v.name, v.value_type
    ORDER BY r.position
    """,
    {"phrase": "display net i psec rule"},
)

# 6. Category + danger filtering: "show me safe network commands"
run(
    "Safe commands in the network category (first 5)",
    """
    MATCH (c:Command)-[:InCategory]->(:Category {name: 'network'})
    WHERE c.danger_level = 'safe'
    RETURN c.name, c.description
    LIMIT 5
    """,
)
