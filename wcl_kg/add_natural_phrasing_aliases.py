"""add_natural_phrasing_aliases.py -- closes a DIFFERENT, narrower gap
than add_coverage_aliases.py's own fix.

That earlier fix closed "230 commands have ZERO verb-leading aliases"
(checked via vocab.py's find_leading_cluster()). This session's full
13,780-alias self-consistency sweep of wcl_resolver.py found those 230
are fine, but a separate, larger class of commands (311 of 1,160, ~27%
-- see this session's quantify_gap.py) has aliases that DO start with a
recognized verb yet still can't be reasonably typed by a real person:
almost all of them are the mechanically-generated "<verb> me the X" /
"<verb> the me the X" template family (grammatically broken -- "list the
me the volume"), and the rest are leftover synonym-pair widening
artifacts that only work if the user ALSO types the command's own
internal short name verbatim (Get-VM's "machines vm", regedit's "editor
regedit" -- nobody says "editor regedit").

Confirmed via this session's real stress-testing (not sampled): ordinary
phrasings like "list all volumes", "list virtual machines", "open the
registry editor", "ping google.com", "what is my ip address" all failed
to resolve even though the underlying command exists and is otherwise
correctly wired, purely because no genuinely natural alias for it exists
in the graph.

Fix: same methodology as add_coverage_aliases.py -- exactly ONE
hand-reviewed, natural, grounded alias per command below, checked
against that command's real `description` field in
windows_command_library.widened.json (see this session's own
descriptions pulled and printed before writing any of these -- none are
guessed). Scoped to the specific commands confirmed broken via this
session's stress test, plus the 16 commands from quantify_gap.py's
"short, real-world object name" bucket -- a deliberately tractable,
individually-justified first batch out of the full 311, not an attempt
to mechanically process all of them at once (see this session's
conversation for why: an automated "is this alias natural" classifier
was tried and found unreliable -- it needs human review per command,
same as the original 230-command fix did).
"""

import json
from pathlib import Path

WIDENED_PATH = Path(__file__).parent / "windows_command_library.widened.json"

# id -> new natural alias to add
NEW_ALIASES = {
    "0472": "list volumes",                       # Get-Volume: "Lists volumes"
    "0622": "list virtual machines",               # Get-VM: Hyper-V VMs
    "0823": "open the registry editor",            # regedit: "Opens Registry Editor GUI"
    "0437": "show my ip address",                  # Get-NetIPAddress: "Lists IP addresses"
    "0183": "show bitlocker status",               # Get-BitLockerVolume: BitLocker status
    "0223": "show the dhcp scope",                 # Get-DhcpServerv4Scope: "Lists DHCP IPv4 scopes"
    "0818": "format the drive",                    # format: "Formats a disk for use with Windows"
    "0301": "add a dns record",                    # Add-DnsServerResourceRecord: "Adds DNS resource record"
    "0801": "ping",                                # ping: "Tests network connectivity to a host"
    "0347": "add a firewall rule",                 # New-NetFirewallRule: "Creates firewall rule"
    # quantify_gap.py's "short, real-world object name" bucket:
    "0177": "check the file signature",            # Get-AuthenticodeSignature
    "0528": "show dedup metadata",                 # Get-DedupMetadata
    "0521": "show the dedup schedule",              # Get-DedupSchedule
    "0518": "show dedup status",                   # Get-DedupStatus
    "0525": "list dedup volumes",                  # Get-DedupVolume
    "1154": "show my default browser",             # Get-DefaultBrowser
    "0220": "show dhcp server info",               # Get-DhcpServer
    "0297": "show dns server info",                # Get-DnsServer
    "0179": "show the execution policy",           # Get-ExecutionPolicy
    "1156": "show open windows",                   # Get-OpenWindows
    "0138": "show runspace debug options",         # Get-RunspaceDebug
    "0547": "list storage enclosures",             # Get-StorageEnclosure
    "0489": "list storage nodes",                  # Get-StorageNode
    "0488": "list storage subsystems",             # Get-StorageSubsystem
    "0496": "list storage tiers",                  # Get-StorageTier
}


def main():
    data = json.load(open(WIDENED_PATH))
    by_id = {d["id"]: d for d in data}

    missing = set(NEW_ALIASES) - set(by_id)
    if missing:
        raise SystemExit(f"NEW_ALIASES has ids not present in the dataset: {sorted(missing)}")

    added, skipped_dupe = 0, 0
    for cid, new_alias in NEW_ALIASES.items():
        cmd = by_id[cid]
        if new_alias in cmd["aliases"]:
            skipped_dupe += 1
            continue
        cmd["aliases"].append(new_alias)
        added += 1

    json.dump(data, open(WIDENED_PATH, "w"), indent=2)
    print(f"Added {added} new aliases ({skipped_dupe} already present, no-op). "
          f"Wrote {WIDENED_PATH}")


if __name__ == "__main__":
    main()
