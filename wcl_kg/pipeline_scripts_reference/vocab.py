"""
Domain vocabulary used to widen the command library's matching surface:

1. TOKEN_FIXES -- repairs a tokenization bug in the *original* alias
   generator. It split PascalCase purely on capital-letter boundaries, which
   works for "NetFirewallRule" -> "net firewall rule" but breaks acronyms
   that are followed by lowercase letters, e.g. "NetIPsecRule" ->
   "net i psec rule" (should be "net ipsec rule"), and "NetAdapterVPort" ->
   "net adapter v port" (should be "net adapter vport").

2. VERB_CLUSTERS -- groups of phrases a real user might say for the same
   underlying action (loosely based on PowerShell's own "approved verb"
   synonym guidance, e.g. Get~List~Show~Display~View, New~Create~Add~Make,
   Remove~Delete~Erase, Stop~Kill~Terminate~End, etc.), extended with plain-
   English phrasing people actually type ("turn on", "get rid of").

This is a curated, best-effort dictionary, not an exhaustive NLP model --
it's meant to be edited/extended over time as real user queries reveal
phrasings it misses.
"""
import re

TOKEN_FIXES = [
    (re.compile(r"\bi psec\b"), "ipsec"),
    (re.compile(r"\bv port\b"), "vport"),
    (re.compile(r"\bbit locker\b"), "bitlocker"),
    (re.compile(r"\bapp locker\b"), "applocker"),
    (re.compile(r"\bpower shell\b"), "powershell"),
]


def apply_token_fixes(text: str) -> str:
    for pattern, repl in TOKEN_FIXES:
        text = pattern.sub(repl, text)
    return text


VERB_CLUSTERS = [
    {"show", "display", "view", "list", "get", "print", "output", "read"},
    {"set", "configure", "update", "change", "modify", "adjust"},
    {"create", "new", "make", "add", "generate", "build"},
    {"remove", "delete", "erase", "uninstall", "get rid of", "discard"},
    {"clear", "clean", "wipe", "purge", "flush"},
    {"enable", "turn on", "activate", "switch on"},
    {"disable", "turn off", "deactivate", "switch off"},
    {"start", "launch", "run", "begin", "fire up"},
    {"stop", "kill", "terminate", "end", "halt", "cancel"},
    {"restart", "reboot", "recycle", "reset"},
    {"resume", "continue", "unpause"},
    {"suspend", "pause", "hold", "freeze"},
    {"export", "save", "extract", "dump", "backup", "back up"},
    {"import", "load", "restore", "bring in"},
    {"copy", "duplicate", "clone", "replicate"},
    {"rename", "change the name of"},
    {"test", "check", "verify", "diagnose", "validate"},
    {"connect", "join", "link", "attach"},
    {"disconnect", "detach", "unlink", "disjoin"},
    {"lock", "restrict"},
    {"unlock", "unrestrict", "free", "release"},
    {"mount", "attach"},
    {"dismount", "unmount", "eject"},
    {"repair", "fix"},
    {"grant", "allow", "permit", "give"},
    {"revoke", "deny", "block", "take away"},
    {"register", "enroll"},
    {"unregister", "unenroll"},
    {"install", "set up"},
    {"search", "find", "locate", "look for"},
    {"send", "transmit", "push", "dispatch"},
    {"receive", "pull"},
    {"sync", "synchronize"},
    {"convert", "transform", "change into"},
    {"move", "transfer", "relocate"},
    {"monitor", "watch", "observe", "track"},
    {"schedule", "plan"},
    {"rename", "name"},
    {"open", "launch"},
    {"close", "shut", "exit"},
    {"invoke", "call", "execute", "run"},
    {"compare", "diff"},
    {"measure", "calculate"},
]

# phrase -> cluster index, longest phrases first so "turn on" matches before "on"
_PHRASE_TO_CLUSTER = {}
for idx, cluster in enumerate(VERB_CLUSTERS):
    for phrase in cluster:
        _PHRASE_TO_CLUSTER.setdefault(phrase, set()).add(idx)

ALL_PHRASES_BY_LENGTH = sorted(
    _PHRASE_TO_CLUSTER.keys(), key=lambda p: -len(p.split())
)


def find_leading_cluster(alias: str):
    """
    If `alias` starts with a known verb/verb-phrase, return
    (matched_phrase, set_of_all_synonym_phrases, remainder_text).
    Longest phrase match wins ("turn on" beats "on").
    """
    for phrase in ALL_PHRASES_BY_LENGTH:
        if alias == phrase or alias.startswith(phrase + " "):
            remainder = alias[len(phrase):].strip()
            synonyms = set()
            for cidx in _PHRASE_TO_CLUSTER[phrase]:
                synonyms |= VERB_CLUSTERS[cidx]
            return phrase, synonyms, remainder
    return None
