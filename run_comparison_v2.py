"""
run_comparison_v2.py -- BLIND first-pass evaluation. The taxonomy in
graph_source_data/tier_a_components.py (v2) was frozen based on reading
tier_a_phrasings.py source data alone, BEFORE this script was ever run.
Results reported here are the actual first-run output, not iterated
against afterward. See TESTING_REPORT.md for what happened next.
"""

import sys
from graph_router import GraphRouter
from component_router_kuzu import KuzuComponentRouter

# Every case below is taken directly from the real tests/test_graph_router.py
# file (not a subset -- this is the full set of parametrized cases across
# every test class in that file).

KNOWN_FALSE_POSITIVES_MUST_MISS = [
    "clear the screen", "stop the music", "kill the lights",
    "remove this annoying popup", "go to the store",
]

KNOWN_GOOD_HITS = [
    ("make a folder called test", "MAKE_FOLDER"),
    ("what's the weather", "GET_WEATHER"),
    ("what's the forecast", "GET_FORECAST"),
    ("empty the recycle bin", "EMPTY_RECYCLE_BIN"),
    ("rename notes.txt to notes-old.txt", "RENAME_ITEM"),
]

LAUNCH_APP_NOT_OPEN_ITEM = [("open chrome", "LAUNCH_APP"), ("open discord", "LAUNCH_APP")]
CHAT_MUST_MISS = ["hey how's it going", "hey", "hi"]
GENERATE_FILE = [("write a poem to a file", "GENERATE_FILE")]
LAUNCH_APP_PHRASING_POISON = [("open steam", "LAUNCH_APP")]

MAKE_FILE_NEW_PHRASING = [
    ("make a new file called test.txt", "MAKE_FILE"),
    ("make new file test.txt", "MAKE_FILE"),
    ("create a new file called test.txt", "MAKE_FILE"),
    ("make a new folder called test", "MAKE_FOLDER"),
]

SHUT_UP_MEANS_MUTE = [
    ("shut up", "TOGGLE_MUTE"), ("shut it up", "TOGGLE_MUTE"),
    ("turn it up", "VOLUME_UP"), ("turn the volume up", "VOLUME_UP"),
    ("crank it up", "VOLUME_UP"), ("make it louder", "VOLUME_UP"),
]

VOLUME_OFF_MEANS_MUTE = [
    ("turn the volume off", "TOGGLE_MUTE"), ("turn off the volume", "TOGGLE_MUTE"),
    ("turn my volume off", "TOGGLE_MUTE"), ("volume off", "TOGGLE_MUTE"),
    ("turn it up", "VOLUME_UP"), ("turn the volume down", "VOLUME_DOWN"),
    ("turn it down", "VOLUME_DOWN"),
]

TURN_OFF_UNRELATED_MUST_MISS = [
    "turn off my monitor", "turn off my screen", "turn off dark mode",
    "turn off wifi", "turn off do not disturb", "turn off bluetooth",
    "turn off notifications", "turn off airplane mode", "power off",
    "turn the computer off", "turn off my pc", "turn off flight mode",
    "turn off night light", "turn off vpn",
]

CLIPBOARD = [
    ("can u tell me whats on my clipboard", "GET_CLIPBOARD"),
    ("show what is on my clipboard", "GET_CLIPBOARD"),
    ("whats on my clipboard", "GET_CLIPBOARD"),
    ("copy this text to the clipboard", "SET_CLIPBOARD"),
    ("set my clipboard to hello", "SET_CLIPBOARD"),
    ("put this on the clipboard", "SET_CLIPBOARD"),
]

READONLY_SHADOW_MUST_MISS = [
    "stop the print spooler service", "reset network adapter", "format the usb drive",
]
READONLY_GENUINE_MUST_HIT = [
    "find the print spooler service", "show my network info", "list usb devices",
]

SORT_FOLDER = [
    ("sort my desktop by type", "SORT_FOLDER_BY_TYPE"),
    ("organize my desktop", "SORT_FOLDER_BY_TYPE"),
    ("organize my downloads folder by type", "SORT_FOLDER_BY_TYPE"),
]

# New (not used to design the taxonomy): held-out paraphrases invented
# independently, never checked against tier_a_phrasings.py during design.
NEVER_SEEN_PARAPHRASES = [
    ("make a dir called Games", "MAKE_FOLDER"),
    ("create a dir", "MAKE_FOLDER"),
    ("erase this dir", "DELETE_ITEM"),
    ("build a new folder", "MAKE_FOLDER"),
]


def run_case(tf_router, comp_router, cases, mode):
    rows = []
    for case in cases:
        text, expected = case if mode == "hit" else (case, None)
        tf_result = tf_router.classify(text)
        comp_result = comp_router.classify(text)
        tf_ok = (tf_result == {"intent": expected}) if mode == "hit" else (tf_result is None)
        comp_ok = (comp_result == {"intent": expected}) if mode == "hit" else (comp_result is None)
        rows.append((text, expected, tf_result, tf_ok, comp_result, comp_ok))
    return rows


def main():
    tf_router = GraphRouter()
    comp_router = KuzuComponentRouter("toki_graph_db")

    suites = [
        ("KnownFalsePositivesMustMiss", run_case(tf_router, comp_router, KNOWN_FALSE_POSITIVES_MUST_MISS, "miss")),
        ("KnownGoodHits", run_case(tf_router, comp_router, KNOWN_GOOD_HITS, "hit")),
        ("LaunchAppNotOpenItem", run_case(tf_router, comp_router, LAUNCH_APP_NOT_OPEN_ITEM, "hit")),
        ("ChatMustMiss", run_case(tf_router, comp_router, CHAT_MUST_MISS, "miss")),
        ("GenerateFile", run_case(tf_router, comp_router, GENERATE_FILE, "hit")),
        ("LaunchAppPhrasingPoison", run_case(tf_router, comp_router, LAUNCH_APP_PHRASING_POISON, "hit")),
        ("MakeFileNewPhrasing", run_case(tf_router, comp_router, MAKE_FILE_NEW_PHRASING, "hit")),
        ("ShutUpMeansMute", run_case(tf_router, comp_router, SHUT_UP_MEANS_MUTE, "hit")),
        ("VolumeOffMeansMute", run_case(tf_router, comp_router, VOLUME_OFF_MEANS_MUTE, "hit")),
        ("TurnOffUnrelatedMustMiss", run_case(tf_router, comp_router, TURN_OFF_UNRELATED_MUST_MISS, "miss")),
        ("Clipboard", run_case(tf_router, comp_router, CLIPBOARD, "hit")),
        ("ReadonlyShadowMustMiss", run_case(tf_router, comp_router, READONLY_SHADOW_MUST_MISS, "miss")),
        ("SortFolder", run_case(tf_router, comp_router, SORT_FOLDER, "hit")),
        ("NeverSeenParaphrases (NEW, held-out)", run_case(tf_router, comp_router, NEVER_SEEN_PARAPHRASES, "hit")),
    ]

    ro_rows = []
    for text in READONLY_GENUINE_MUST_HIT:
        tf_result = tf_router.classify(text)
        comp_result = comp_router.classify(text)
        ro_rows.append((text, "(any)", tf_result, tf_result is not None, comp_result, comp_result is not None))
    suites.append(("ReadonlyGenuineMustHit", ro_rows))

    total_tf = total_comp = total = 0
    print(f"{'CASE':58s} {'EXPECTED':16s} {'TF-IDF':20s} {'COMPONENT (Kuzu)':20s}")
    print("=" * 130)
    for label, rows in suites:
        print(f"\n--- {label} ---")
        for text, expected, tf_result, tf_ok, comp_result, comp_ok in rows:
            total += 1
            total_tf += tf_ok
            total_comp += comp_ok
            tf_mark = "OK" if tf_ok else "FAIL"
            comp_mark = "OK" if comp_ok else "FAIL"
            print(f"{text[:56]:58s} {str(expected):16s} "
                  f"{str(tf_result):14s}[{tf_mark:4s}] {str(comp_result):14s}[{comp_mark:4s}]")

    print("\n" + "=" * 130)
    print(f"TOTAL CASES: {total}")
    print(f"TF-IDF (current, production):     {total_tf}/{total}  ({100*total_tf/total:.1f}%)")
    print(f"Component (Kuzu-native, v2, blind): {total_comp}/{total}  ({100*total_comp/total:.1f}%)")

    tf_router.close()
    comp_router.close()


if __name__ == "__main__":
    main()
