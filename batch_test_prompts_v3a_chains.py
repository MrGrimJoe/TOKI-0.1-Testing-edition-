"""
batch_test_prompts_v3a_chains.py -- SESSION A of 4. Chain-splitting
boundary stress test.

Run with:
    python batch_test_prompts_v3a_chains.py
    python batch_test_live.py batch_test_prompts_v3a_chains.txt

WHY THIS SESSION EXISTS: BETA 0.3.19 fixed the state-leakage bug that
made ~2/3 of every past batch run untested, and BETA 0.3.18 fixed
batch_test_live.py never actually exercising chain-splitting at all.
This is the first prompt list built on top of BOTH fixes -- so results
here are the first real signal this project has ever had about how
chain-splitting behaves under live Ollama pressure across a WIDE
variety of boundary phrasings, not just the ~10 cases v2 re-verified.

Specifically targets the two open findings from BETA 0.3.18's Live
verification log:
  1. The confirmed xfail false positive ("X and Y.ext" mis-splitting) --
     more variations here to characterize how narrow/broad that gap is.
  2. The "clear the screen" segment-viability gap in 3-way semicolon
     chains -- more 3-way chains here to see if that's an isolated gap
     or a pattern with certain phrasings/verbs.
"""

PROMPTS_V3A = [
    # ── More "X and Y.ext" filename-adjacent false-positive stress
    #    (extending BETA 0.3.13's known xfail, now confirmed live) ──
    "find files named budget and forecast.xlsx",
    "open resume and cover_letter.docx",
    "delete draft and final.docx",
    "rename budget.xlsx and forecast.xlsx",  # two real filenames, ambiguous "and"
    "search for invoice and receipt.pdf",

    # ── More 3-way semicolon chains, varying which verb is last
    #    (isolate whether "clear the screen" specifically is the gap,
    #    or whether ANY WCL-only segment sinks an otherwise-viable split) ──
    "empty the recycle bin; take a screenshot; mute the volume",
    "take a screenshot; empty the recycle bin; lock my computer",
    "clear the screen; take a screenshot; empty the recycle bin",
    "mute the volume; clear the screen; take a screenshot",
    "lock my computer; empty the recycle bin; clear the screen",

    # ── Longer chains (4-5 steps), not yet tested at all ──
    "open notepad, then open calculator, then close notepad, then close calculator",
    "make a folder called A, then make a folder called B, then rename A to C, then delete B",
    "take a screenshot, empty the recycle bin, lock my computer, then mute the volume",

    # ── Mixed danger levels within one chain (safe step + destructive step) --
    #    should the destructive half still correctly refuse to auto-dispatch
    #    even when chained after a safe one? ──
    "take a screenshot and format D drive",
    "empty the recycle bin and wipe disk 2",
    "open notepad and delete notes.txt",

    # ── "and" as a genuine multi-target single action (should NOT split --
    #    same object, same verb, compound target) vs. two actions (SHOULD
    #    split) -- minimal pairs to probe where the line actually is ──
    "close chrome and steam",  # one verb, two targets -- ambiguous: one CLOSE with 2 args, or 2 closes?
    "open chrome and steam",   # same shape, OPEN_ITEM
    "kill chrome and steam",   # same shape, KILL_PROCESS

    # ── Chain connectors not yet tried: "after that", "also", "as well as" ──
    "open notepad, after that open calculator",
    "empty the recycle bin, also take a screenshot",
    "mute the volume as well as lock my computer",

    # ── Self-referential chain (second step depends on first step's result --
    #    tests whether chain-splitting interacts with anaphora resolution
    #    WITHIN a single multi-step message, not across separate turns) ──
    "make a folder called Reports, then open it",
    "rename notes.txt to notes-old.txt, then open it",
]


if __name__ == "__main__":
    with open("batch_test_prompts_v3a_chains.txt", "w", encoding="utf-8") as f:
        for p in PROMPTS_V3A:
            f.write(p + "\n")
    print(f"Wrote {len(PROMPTS_V3A)} prompts to batch_test_prompts_v3a_chains.txt")
    print("Run with: python batch_test_live.py batch_test_prompts_v3a_chains.txt")
