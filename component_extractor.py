"""
component_extractor.py -- deterministically pulls semantic components
out of normalized user text, using the alias table in
graph_source_data/tier_a_components.py.

Reuses graph_router.normalize()/content_words() rather than
re-implementing normalization, so this experiment compares routing
STRATEGIES on identical input handling, not also different ".exe"
stripping or stopword rules.

v2.1: also reuses synonyms.expand_synonyms() -- graph_router.py's own
real, shipped curated-synonym-table mechanism (see synonyms.py's module
docstring) -- rather than inventing a parallel synonym list here. This
is a genuine "migrate the general mechanism, not the phrases" case:
synonyms.py's SYNONYM_MAP already has "erase"->"delete" etc; expanding
component extraction's word set through the SAME function
graph_router.py itself calls means any future addition to that shared
table benefits both routers identically, with zero duplication.

Pure Python, no Kuzu access -- fully unit-testable without a database.
This module's matching MECHANICS (multi-word-first scanning, a word
mapping to multiple components) were not changed between the v1 and v2
taxonomy passes; only graph_source_data/tier_a_components.py's data
changed.
"""

from typing import Dict, List, Set

from graph_router import normalize, content_words
from synonyms import expand_synonyms, is_matched_via_synonym
from graph_source_data.tier_a_components import COMPONENTS

# v2.2: reuse extractor.py's own, already-tested, general slot-value
# patterns to MASK likely value regions (URLs, drive paths, quoted
# strings) out of the text before any component/vocabulary matching
# happens -- see mask_value_regions() below for why this exists and
# TESTING_REPORT_V2.md's "lexical false positive" section for the
# concrete bug (a bare keyword incidentally inside a filename, e.g.
# "forecast.xlsx", was confidently triggering GET_FORECAST) that made
# this necessary. Imported directly rather than duplicated, so any
# future improvement to extractor.py's own URL/path/quote handling
# automatically carries over here with zero drift.
from extractor import _URL_IN_TEXT_RE, _BARE_DRIVE_PATH_WITH_EXT_RE, _QUOTED_RE

import re

# The one genuinely NEW pattern here (not lifted from extractor.py):
# extractor.py's own _BARE_FILENAME_RE (r"[\w .\-]+\.\w{1,5}") is
# DELIBERATELY greedy -- it's used downstream, for a KNOWN intent, to
# capture a whole space-containing filename as a single path value
# ("my final report.docx"). That greediness is wrong for THIS use case
# (masking): applied to a full sentence with no anchor, it would eat
# back across legitimate instruction words too. This pattern instead
# matches a single WORD-shaped token immediately followed by a
# dot-extension, with no spaces inside the match at all --
# "forecast.xlsx", "chrome.exe", "report.docx", "readme.md" -- while
# leaving surrounding sentence words completely alone. Extension is
# required to START with a letter (not a digit) specifically so this
# doesn't also swallow decimal numbers like "0.5" or "11.2", which share
# the same word.word shape but carry no filename semantics at all.
_BARE_FILENAME_TOKEN_RE = re.compile(r"\b[\w\-]+\.[A-Za-z][A-Za-z0-9]{0,4}\b")


def mask_value_regions(text: str) -> str:
    """Replaces URL / drive-path / quoted-string / bare-filename-token
    spans with a single neutral space, so a component alias that happens
    to appear INSIDE a slot value (a filename, a path, a quoted name, a
    pasted link) never gets counted as semantic evidence for routing.

    This runs on the RAW (pre-normalize()) text specifically because
    URLs and drive paths contain characters (":", "/", "\\") that
    normalize()'s own punctuation-stripping would otherwise scramble
    before this function ever got a chance to recognize the shape.

    General, deterministic, and intent-agnostic by construction: it has
    no knowledge of "forecast" or any other specific word, so it can't
    be a benchmark-specific patch -- it fires identically whether the
    incidental keyword is "forecast", "weather", "battery", "hostname",
    or anything else that happens to double as a component alias and a
    filename stem.

    KNOWN, disclosed trade-off (see TESTING_REPORT_V2.md): a domain-like
    token such as "google.com" also matches the bare-filename-token
    pattern and gets masked whole, which means a query like "search
    google.com for weather" loses "google" as OBJECT_WEB evidence too --
    accepted as a rare, narrow cost of a single general rule over a
    special-cased one.
    """
    text = _URL_IN_TEXT_RE.sub(" ", text)
    text = _BARE_DRIVE_PATH_WITH_EXT_RE.sub(" ", text)
    text = _QUOTED_RE.sub(" ", text)
    text = _BARE_FILENAME_TOKEN_RE.sub(" ", text)
    return text

_MULTI_WORD_ALIASES: List[tuple] = []
_SINGLE_WORD_ALIASES: Dict[str, List[str]] = {}

for _comp_id, _def in COMPONENTS.items():
    for _alias in _def["aliases"]:
        if " " in _alias:
            _MULTI_WORD_ALIASES.append((_alias, _comp_id))
        else:
            _SINGLE_WORD_ALIASES.setdefault(_alias, []).append(_comp_id)

# Longest phrase first so e.g. "turn the volume off" is consumed whole
# before a shorter alias could partially match inside it.
_MULTI_WORD_ALIASES.sort(key=lambda pair: -len(pair[0]))


def extract_components(text: str) -> Dict[str, List[str]]:
    """Returns e.g. {"ACTION": ["ACTION_CREATE"], "OBJECT": ["OBJECT_FOLDER"]}.
    Category keys with no matches are omitted. Always includes
    "unmatched_words" for debugging.
    """
    norm = normalize(mask_value_regions(text))
    if not norm:
        return {"unmatched_words": []}

    remaining = f" {norm} "
    found_ids: Set[str] = set()

    for alias, comp_id in _MULTI_WORD_ALIASES:
        needle = f" {alias} "
        if needle in remaining:
            found_ids.add(comp_id)
            remaining = remaining.replace(needle, " ")

    words = content_words(remaining)
    # Same usage contract as graph_router.py's own synonym-expansion
    # calls (see synonyms.py's docstring): expand_synonyms() feeds ONLY
    # the vocabulary-lookup word set below, never the original `words`
    # used for unmatched-word reporting, so this can't silently change
    # what counts as a "real" word for any other purpose.
    match_words = expand_synonyms(words)
    alias_matched_words: Set[str] = set()
    for w in match_words:
        comp_ids = _SINGLE_WORD_ALIASES.get(w)
        if comp_ids:
            found_ids.update(comp_ids)
            alias_matched_words.add(w)

    matched_words: Set[str] = {
        w for w in words
        if w in alias_matched_words or is_matched_via_synonym(w, alias_matched_words)
    }

    unmatched = sorted(words - matched_words)

    result: Dict[str, List[str]] = {}
    for comp_id in found_ids:
        category = COMPONENTS[comp_id]["category"]
        result.setdefault(category, []).append(comp_id)
    for v in result.values():
        v.sort()

    result["unmatched_words"] = unmatched
    return result


def all_component_ids(extracted: Dict[str, List[str]]) -> Set[str]:
    ids: Set[str] = set()
    for key, vals in extracted.items():
        if key == "unmatched_words":
            continue
        ids.update(vals)
    return ids
