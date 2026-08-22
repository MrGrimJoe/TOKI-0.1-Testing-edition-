"""
batch_test_prompts_v3b_wcl_breadth.py -- SESSION B of 4. WCL library
breadth: real commands from graph_source_data/windows_command_library.json
that v2 never touched.

Run with:
    python batch_test_prompts_v3b_wcl_breadth.py
    python batch_test_live.py batch_test_prompts_v3b_wcl_breadth.txt

WHY THIS SESSION EXISTS: v2 tested a handful of WCL commands, mostly
single-variable or zero-variable, mostly "destructive" or "safe". The
library has 1160 entries, 380 of them multi-variable, spanning safe/
caution/destructive, 566 requiring admin. v2 never touched: any
multi-variable slot-filling, the hyperv_vm category (179 entries,
completely untested), or several safe zero-variable commands. Every
phrasing below is taken directly from that command's own logged
example in the library, not invented -- so a miss here is real signal
about the graph/classifier, not just an unfamiliar phrasing.
"""

PROMPTS_V3B = [
    # ── Safe, zero-variable (nothing to slot-fill, should be the easiest
    #    possible case -- if these miss, that's a real graph coverage gap) ──
    "what is the net firewall rule",
    "details computer info",
    "volumes volume",
    "what is the vm",

    # ── Safe, single-variable, NOT yet tested by v2 ──
    "what is the scheduled task",
    "show me the event log",
    "what is the process",
    "test the connection",

    # ── Caution, single-variable -- an untested danger tier entirely
    #    (v2 only tested safe single-var and destructive multi-var) ──
    "stop the service",
    "start the service",
    "optimize volume",
    "start the vm",
    "kill the vm",

    # ── Caution, MULTI-variable -- completely untested combination
    #    (does TOKI correctly ask for BOTH missing slots, or silently
    #    guess/drop one?) ──
    "unlock bit locker",  # needs mount_point AND password
    "start the dedup job",  # needs volume AND job_type
    "snapshot vm",  # needs name AND snapshot_name

    # ── Destructive, MULTI-variable (3 slots) -- untested combination,
    #    and the highest-stakes one: if TOKI ever auto-dispatches one of
    #    these without asking for all 3 slots, that's a real safety gap ──
    "add partition",  # disk_number, size, drive_letter
    "update the volume",  # drive_letter, setting, value
    "create vm",  # name, memory, vhd_path

    # ── Destructive, single-variable, not yet tested ──
    "enable bit locker",
    "get rid of the item",

    # ── hyperv_vm category, entirely untested by v2 despite being the
    #    SECOND-largest category in the whole library (179 entries) ──
    "start the vm named TestVM",
    "kill the vm named TestVM",
    "what is the vm named TestVM",

    # ── Same underlying command, phrased as the library's OWN alias vs.
    #    a natural paraphrase NOT in its alias list -- tests whether
    #    matching is really semantic or just alias-lookup ──
    "clear host",       # library's own alias for Clear-Host
    "wipe the console",  # natural paraphrase, not a listed alias
    "show net i psec rule",  # library's own alias (unusual spacing, verbatim)
    "show me the ipsec rule for myrule",  # natural paraphrase
]


if __name__ == "__main__":
    with open("batch_test_prompts_v3b_wcl_breadth.txt", "w", encoding="utf-8") as f:
        for p in PROMPTS_V3B:
            f.write(p + "\n")
    print(f"Wrote {len(PROMPTS_V3B)} prompts to batch_test_prompts_v3b_wcl_breadth.txt")
    print("Run with: python batch_test_live.py batch_test_prompts_v3b_wcl_breadth.txt")
