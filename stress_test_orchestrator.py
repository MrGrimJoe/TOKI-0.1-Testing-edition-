"""
stress_test_orchestrator.py — Live End-to-End Stress Test Script for TOKI

Executes ~100 diverse command prompts covering:
1. Core Hand-written Intents (Filesystem, Process, System, Info, App Control)
2. Plugin System Intents (Loaded from example_plugin)
3. Dangerous Command Permission Gate (Caution & Destructive commands hold & confirm)
4. WCL Resolved 0, 1, and 2-variable commands
5. Anaphora & Multi-segment Chained Commands
6. Canned replies & Fallback handling

Generates a detailed execution log report at stress_test_report.log.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Insert local repository path
HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))

from orchestrator import WindowsAIAssistant, WCL_COMMANDS
from plugin_manager import plugin_manager

REPORT_PATH = HERE / "stress_test_report.log"

TEST_PROMPTS = [
    # ── 1. Plugin Intents
    "hello from plugin",
    "plugin say hello",
    "say hi from the plugin",
    
    # ── 2. Dangerous Commands (Permission Gate Triggering)
    "clean temp files",
    "run diskpart",
    "restart system",
    "regedit",
    "clear event log",

    # ── 3. Basic Hand-written & System Intents
    "what is my hostname",
    "who is current user",
    "check system uptime",
    "get battery status",
    "take screenshot",
    "toggle mute",
    "get time",
    "get date",
    "get location",
    "search web for python 3.12 documentation",
    "get weather for New York",

    # ── 4. Filesystem & Navigation
    "make a folder named StressTestFolder",
    "make a file named test1.txt",
    "copy test1.txt to test2.txt",
    "rename test2.txt to test3.txt",
    "delete file test3.txt",
    "delete folder StressTestFolder",

    # ── 5. Process & App Control
    "list running processes",
    "open task manager",
    "find process python",
    "launch notepad",
    "kill process notepad",

    # ── 6. Chained Commands
    "make a folder named ChainDir and then make a file named ChainDir\\file.txt",
    "delete file ChainDir\\file.txt and then delete folder ChainDir",

    # ── 7. Direct Command Overrides (// prefix)
    "//hostname",
    "//user",
    "//uptime",
    "//battery",
    "//weather New York",

    # ── 8. WCL 0-Var, 1-Var, 2-Var Safe Commands
    "clear DNS cache",
    "get IP configuration",
    "list network adapters",
    "show routing table",
    "get active TCP connections",
    "show system environment variables",
    "get Windows version",
    "check disk space",
    "list installed printers",
    "get system driver info",

    # ── 9. Additional Multi-variation Prompts to reach ~100 tests
]

# Expand variations to create a 100-command stress test battery
EXTENDED_PROMPTS = list(TEST_PROMPTS)
variations = [
    "what's my hostname",
    "who am I logged in as",
    "how long has the computer been on",
    "show battery status",
    "snap screen",
    "mute audio",
    "what time is it",
    "what date is today",
    "where am I",
    "search web for rust language",
    "weather in Tokyo",
    "make folder DemoFolder1",
    "make folder DemoFolder2",
    "make file fileA.txt",
    "make file fileB.txt",
    "copy fileA.txt to fileC.txt",
    "rename fileC.txt to fileD.txt",
    "delete file fileD.txt",
    "delete file fileA.txt",
    "delete file fileB.txt",
    "delete folder DemoFolder1",
    "delete folder DemoFolder2",
    "list processes",
    "show task manager",
    "find process cmd",
    "launch cmd",
    "kill process cmd",
    "make folder TestBox and then make file TestBox\\note.txt",
    "delete file TestBox\\note.txt and then delete folder TestBox",
    "//time",
    "//date",
    "//location",
    "//screenshot",
    "flush dns",
    "show ipconfig",
    "list network interfaces",
    "print environment variables",
    "get os version",
    "get disk space",
    "hello",
    "thanks",
    "thank you",
    "hi",
    "hey",
]

# Add WCL 0-var prompts from WCL database to round up to 100+
for i in range(100 - len(EXTENDED_PROMPTS)):
    if i < len(variations):
        EXTENDED_PROMPTS.append(variations[i])
    else:
        EXTENDED_PROMPTS.append(f"what time is it {i}")


def run_stress_test():
    print("=" * 70)
    print(f"STARTING TOKI 100-COMMAND STRESS TEST BATTERY")
    print(f"Total Test Prompts: {len(EXTENDED_PROMPTS)}")
    print("=" * 70)

    assistant = WindowsAIAssistant()

    passed_count = 0
    gate_count = 0
    fail_count = 0
    log_lines = []

    start_time = time.time()

    for idx, prompt in enumerate(EXTENDED_PROMPTS, 1):
        test_start = time.time()
        print(f"[{idx:03d}/{len(EXTENDED_PROMPTS)}] Testing: '{prompt}' ... ", end="", flush=True)

        try:
            # Execute request synchronously through process_request
            res = assistant.process_request(
                prompt,
                on_output=lambda line: None,
                on_done=lambda code: None,
            )

            duration = (time.time() - test_start) * 1000
            kind = res.get("kind", "unknown")
            response = res.get("response", "") or res.get("thinking", "")

            # BETA 0.3.38: caution/destructive commands no longer use a
            # distinct "permission_gate" kind -- they ask through the same
            # "chat" kind everything else uses (see orchestrator.py's
            # _ask_for_confirmation()), detected here via the pending state
            # itself instead of a response kind.
            if getattr(assistant, "_pending_confirmation", None) is not None:
                gate_count += 1
                danger_level = assistant._pending_confirmation.get("context", "caution")
                status_str = f"GATE ({danger_level})"
                # Verify confirmation flow works -- empty string is one of
                # orchestrator.py's own _CONFIRMATION_WORDS, same as a bare
                # Enter in the real UI.
                confirm_res = assistant.process_request(
                    "", on_output=lambda line: None, on_done=lambda code: None,
                )
                confirm_kind = confirm_res.get("kind", "done")
                log_entry = (
                    f"[{idx:03d}] PROMPT: '{prompt}' -> {status_str} "
                    f"[{duration:.1f}ms] | CONFIRMED: {confirm_kind}"
                )
            else:
                passed_count += 1
                status_str = f"OK ({kind})"
                log_entry = (
                    f"[{idx:03d}] PROMPT: '{prompt}' -> {status_str} "
                    f"[{duration:.1f}ms] | RESP: {response[:60]}..."
                )

            print(status_str)
            log_lines.append(log_entry)

        except Exception as exc:
            fail_count += 1
            duration = (time.time() - test_start) * 1000
            print(f"FAIL ({exc})")
            log_lines.append(f"[{idx:03d}] PROMPT: '{prompt}' -> FAIL: {exc}")

    total_duration = time.time() - start_time

    summary = [
        "",
        "=" * 70,
        "STRESS TEST SUMMARY REPORT",
        f"Total Executed:   {len(EXTENDED_PROMPTS)}",
        f"Normal Dispatches: {passed_count}",
        f"Permission Gates:  {gate_count}",
        f"Failures:          {fail_count}",
        f"Total Time:        {total_duration:.2f} seconds",
        f"Average Latency:   {(total_duration / len(EXTENDED_PROMPTS)) * 1000:.1f} ms / command",
        "=" * 70,
    ]

    report_content = "\n".join(log_lines + summary)
    REPORT_PATH.write_text(report_content, encoding="utf-8")

    print("\n".join(summary))
    print(f"\nDetailed log written to: {REPORT_PATH}")

    return fail_count == 0


if __name__ == "__main__":
    success = run_stress_test()
    sys.exit(0 if success else 1)
