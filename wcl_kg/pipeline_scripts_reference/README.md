# Windows Command Library -- Kuzu Knowledge Graph

## Build order (run once, in sequence)
1. `01_fix_source.py`         -- fixes 5 syntax/variable mismatches in the raw JSON
2. `05_widen_dictionaries.py` -- fixes tokenization bugs (IPsec, BitLocker, etc.) + widens aliases/intents via synonym clusters (vocab.py)
3. `02_export_csv.py`         -- normalizes JSON into node/rel CSV tables for Kuzu
4. `06_export_synonyms.py`    -- exports SynonymOf edges between Intent nodes
5. `03_load_kuzu.py`          -- builds ./windows_commands_db from schema.cypher + csv/

Then use it:
- `04_demo_queries.py`      -- basic intent-match / slot-fill queries
- `07_robustness_demo.py`   -- proves the widening actually works (acronym fix, synonym-only matches, fallback)
- `08_resolver.py`          -- the production-shape resolver: tiered exact -> synonym -> fuzzy -> loose-search-for-model, with a `verify_model_suggestion()` grounding check

## Files
- `windows_command_library.widened.json` -- the final, cleaned, widened source data (human-readable)
- `vocab.py` -- the 41 verb-synonym clusters + tokenization fixes (edit this to extend coverage)
- `schema.cypher` -- Kuzu graph schema
- `csv/` -- normalized node/relationship tables loaded by 03_load_kuzu.py
- `unresolved_queries.log` -- appended to by `log_unresolved()`; mine this to widen vocab.py over time

## Graph shape
Nodes: Command, Category, Module, Intent, Alias, VariableType, Example
Rels:  InCategory, RequiresModule, HasIntent, HasAlias, HasVariable, HasExample, SynonymOf

## Resolution policy (no confidence scores -- strict tiers)
1. Exact alias match (single)      -> resolved, no model
2. Exact alias match (multiple)    -> ambiguous, disambiguate (ask user / constrained model pick)
3. SynonymOf 1-hop match (single)  -> resolved, no model
4. SynonymOf 1-hop match (multiple)-> ambiguous
5. Fuzzy alias match (difflib)     -> resolved/ambiguous, still no model (typo tolerance)
6. Nothing matches                 -> UNRESOLVED: hand the model a loose-search shortlist
   (never let the model free-generate a command; always verify_model_suggestion() 
   against the graph before executing anything it proposes)

## Known limits
- Ambiguity: 175/13,546 aliases (1.3%), touching 52/1160 commands (4.5%) -- genuine
  English ambiguity (e.g. "virtual vm" -> 8 real VM cmdlets), not a bug.
  (Count last verified BETA 0.3.28 -- see tests/test_wcl_resolver.py's
  test_alias_count_matches_the_documented_figure for the running total
  and a log of what's been added directly to the live graph since the
  original pipeline build.)
- vocab.py's 41 clusters are curated, not exhaustive -- extend from unresolved_queries.log.
- Kuzu does exact string match only; typo tolerance (tier 5) is difflib in Python,
  run before hitting Kuzu with the cleaned candidate.
