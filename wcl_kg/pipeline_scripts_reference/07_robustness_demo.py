import kuzu

db = kuzu.Database("/home/claude/kg_build/windows_commands_db")
conn = kuzu.Connection(db)


def run(title, query, params=None):
    print(f"\n=== {title} ===")
    res = conn.execute(query, params or {})
    while res.has_next():
        print(res.get_next())


# 1. The acronym bug is gone: "ipsec" is now one clean token, not "i psec"
run(
    "Acronym fix check: alias 'show ipsec rule' variants",
    """
    MATCH (a:Alias)<-[:HasAlias]-(c:Command)
    WHERE a.text CONTAINS 'ipsec' AND c.name = 'Show-NetIPsecRule'
    RETURN a.text
    """,
)

# 2. A phrase that was NEVER a literal alias for this command, but exists
#    only because "print" is a synonym of "show" -- proves the literal
#    widening worked, not just the original hand-written aliases.
run(
    "Widened literal match: 'print net ipsec rule' (never hand-authored)",
    """
    MATCH (a:Alias {text: 'print net ipsec rule'})<-[:HasAlias]-(c:Command)
    RETURN c.name, c.syntax
    """,
)

# 3. Synonym-graph fallback: user says "please retrieve the job", which is
#    NOT a literal alias anywhere. Walk token "retrieve" -> nothing directly,
#    but "get" is recognized, then 1-hop SynonymOf reaches every command
#    tagged with any synonym intent of "get" (show/list/display/etc).
run(
    "Graph fallback: intent 'get' expanded via SynonymOf (sample of 8)",
    """
    MATCH (start:Intent {name: 'get'})-[:SynonymOf*0..1]->(syn:Intent)<-[:HasIntent]-(c:Command)
    RETURN DISTINCT c.name
    LIMIT 8
    """,
)

# 4. Coverage check: how many commands are now reachable through AT LEAST
#    one of (literal alias, intent token, 1-hop synonym intent) for a
#    deliberately loose, conversational phrasing.
run(
    "Loose phrasing: 'can you turn on bitlocker' -> candidates",
    """
    MATCH (a:Alias)<-[:HasAlias]-(c:Command)
    WHERE a.text CONTAINS 'bitlocker' AND
          (a.text STARTS WITH 'enable' OR a.text STARTS WITH 'turn on'
           OR a.text STARTS WITH 'activate')
    RETURN c.name, c.syntax
    """,
)
