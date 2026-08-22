"""
route_probe.py -- ad hoc driver for GraphRouter.classify_or_ask(),
no LLM, no PowerShell, no pywinauto. Pure graph routing test.

Not part of the test suite -- this is exploratory, for eyeballing what
kuzu actually does with a wide spread of phrasings, grouped by what
the handoff doc flagged as highest-risk.
"""
from graph_router import GraphRouter

r = GraphRouter()


def run(label, phrases):
    print(f"\n=== {label} ===")
    for p in phrases:
        result = r.classify_or_ask(p)
        if "intent" in result:
            print(f"  HIT   {p!r:55} -> {result['intent']}")
        else:
            uw = result.get("unknown_words", [])
            print(f"  ASK   {p!r:55} -> unknown_words={uw}")


# 1. Open-target cascade phrasings (feature under test, unverifiable on
# real Windows here, but the ROUTING into OPEN_ITEM/LAUNCH_APP is fully
# testable without Windows).
run("open-target cascade: short/abbreviated app names", [
    "open steam",
    "open obs",
    "open code",
    "open discord",
    "open chrome",
    "open word",
])

run("open-target cascade: explicit quoting bypass", [
    "open 'MyWeirdApp'",
    'open "Some Custom Tool"',
])

run("open-target cascade: vague/ambiguous", [
    "open the thing",
    "open",
])

# 2. This session's bug fixes
run("kill/wait/find with .exe suffix", [
    "kill notepad.exe",
    "wait for chrome.exe",
    "find explorer.exe",
])

run("apostrophes in names", [
    "open O'Brien's Notes",
])

run("process/service word-gluing", [
    "find process explorer",
    "check service printer",
])

# 3. Chain-split viability
run("chain splitting", [
    "make a folder called Homework and then open it",
    "make a file called things, and stuff.txt",
])

# 4. Broad regression -- file ops
run("file ops", [
    "make a new file called test.txt",
    "delete report.docx",
    "rename notes.txt to notes-old.txt",
    "move photo.jpg to the desktop",
    "copy budget.xlsx to D drive",
    "make a folder called Projects",
    "delete the Projects folder",
])

# 5. Broad regression -- system/process
run("system & process commands", [
    "empty the recycle bin",
    "take a screenshot",
    "lock workstation",
    "lock my pc",
])

# 6. Multi-step chain unrelated to open
run("unrelated multi-step chain", [
    "take a screenshot then empty the recycle bin",
])

# 7. Plain chat -- must NEVER graph-hit
run("plain chat (must ASK / fall through, never hit)", [
    "hey how's it going",
    "hey",
    "hi",
    "thanks!",
    "lol nice",
    "what's up",
])

# 8. Below-threshold command-shaped candidate
run("below-threshold command-shaped (should miss cleanly)", [
    "kill the lights",
])

# 9. Known open bugs -- confirm still failing the SAME documented way
run("known open bug: GENERATE_FILE (should still misroute, not crash)", [
    "write a poem to a file",
    "generate a file with a haiku in it",
])

run("known open bug: greedy bare-path regex (xfail'd, routing only)", [
    "delete the file version 2.0 from my desktop",
])

# 10. Extra adversarial spread -- not in the handoff doc, but cheap to
# check while we're here: near-miss phrasings, typos, and category
# boundary cases between similarly-worded FILESYSTEM vs PROCESS vs
# APP_CONTROL commands.
run("extra: near-miss / typo tolerance", [
    "opne chrome",
    "delet file.txt",
    "cna you open steam",
]) 

run("extra: category boundary cases (kill/close/end process wording)", [
    "close notepad",
    "end task chrome.exe",
    "terminate steam",
    "stop the process explorer",
])

run("extra: app control vs launch app phrasing", [
    "click the save button",
    "type hello world into notepad",
    "click on OK",
])

run("extra: info/generate category", [
    "what's the weather today",
    "what's the weather like in Lahore",
    "search for python tutorials",
    "write a poem to a file",
])
