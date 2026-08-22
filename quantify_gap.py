"""Quantify the natural-phrasing coverage gap: for every command, is
there at least one alias that (a) isn't just template padding-verb noise
("get me the X" / "list the me the X" etc.) and (b) is short enough
(<=3 real content words after stripping stopwords/padding) to plausibly
be something a real person would actually type, rather than a bloated
enclosure-style multi-word technical phrase.

This is DIFFERENT from the project's existing find_leading_cluster audit
(which only checks "starts with a recognized verb" -- Get-Volume passes
that fine, its aliases DO start with recognized verbs, they're just all
padding).
"""
from collections import defaultdict
from wcl_resolver import WCLResolver, normalize, _content_words, ALIAS_PADDING_VERBS, STOPWORDS

r = WCLResolver()
rows = r._all_alias_rows()

by_command = defaultdict(list)
for alias_text, name, syntax, danger, admin, confirm, category in rows:
    by_command[name].append(alias_text)

TEMPLATE_MARKERS = (" me the ", " the me the ")

def is_clean(alias_text: str) -> bool:
    if any(m in f" {alias_text} " for m in TEMPLATE_MARKERS):
        return False
    words = _content_words(alias_text.split())
    real = [w for w in words if w not in ALIAS_PADDING_VERBS]
    # must have at least 1 real distinguishing word, and the WHOLE alias
    # (not just real words) must be short enough to be plausible --
    # <=4 tokens total, matching how short real commands get typed
    return len(real) >= 1 and len(alias_text.split()) <= 4

gap_commands = []
for name, aliases in by_command.items():
    if not any(is_clean(a) for a in aliases):
        gap_commands.append((name, len(aliases), aliases[:3]))

print(f"Total commands with at least one alias: {len(by_command)}")
print(f"Commands where EVERY alias is template-padded/awkward (no clean short alias): {len(gap_commands)}")
print(f"That's {100*len(gap_commands)/len(by_command):.1f}% of all commands with aliases")
print()
print("--- sample (first 30) ---")
for name, n_aliases, sample in sorted(gap_commands)[:30]:
    print(f"{name:35} ({n_aliases} aliases) e.g. {sample}")
