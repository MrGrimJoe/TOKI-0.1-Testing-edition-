"""add_natural_phrasing_aliases_batch2.py -- second hand-reviewed batch
closing add_natural_phrasing_aliases.py's remaining 293-command gap
(quantify_gap.py, re-run against the merged tree).

Same methodology as batch 1: exactly ONE natural, grounded alias per
command below, checked against that command's real `description` field,
added only where a normal person plausibly asking TOKI (a personal
desktop assistant on their own PC/laptop) about it would actually use
that phrasing.

IMPORTANT FINDING from reviewing all 293 remaining gap commands by hand:
the overwhelming majority of them are NOT a natural-phrasing gap at
all -- they are enterprise/datacenter cmdlets that have no genuine
casual phrasing because no home-PC TOKI user would ever ask for them:

  - Hyper-V VM sub-component config: SR-IOV queue pairs/VFs/policies,
    RemoteFX 3D video adapters, VM Fibre Channel HBAs, VM replication
    authorization entries, VM key storage drives, etc. (~150 commands)
  - Storage Spaces / SAN "storage enclosure" hardware management:
    enclosure firmware, vendor data, SAS/Fibre Channel ports, LUNs,
    namespaces, IOPS/latency/bandwidth telemetry, etc. (~70 commands)
  - Active Directory Domain Controller roles: DHCP server authorization,
    IPv4/IPv6 exclusion ranges, failover replication; DNS *server* role
    (not client) zone transfers, root hints, NRPT policy (~60 commands)
  - IPsec main-mode/quick-mode policy rule sets (enterprise domain
    security policy) (~25 commands)

Forcing a fake "casual" 2-4 word alias onto e.g. Get-VMNetworkAdapter-
SriovQueuePair or Get-StorageEnclosureStorageFibreChannelPort would
recreate exactly the problem this whole fix effort was created to
avoid: padding that LOOKS clean to a classifier but that no real person
would ever type. These are left alone deliberately, not as an
oversight -- see conversation history / STATUS.md for the reasoning.

Out of all 293, only the below had a genuine, unambiguous, real-world
phrasing a normal TOKI user would use:
"""

import json
from pathlib import Path

WIDENED_PATH = Path(__file__).parent / "windows_command_library.widened.json"

# id -> new natural alias to add
NEW_ALIASES = {
    "1149": "disk space",                # Get-DiskSpaceSummary: friendly free/used disk space
    "0212": "file sharing settings",     # Get-SmbServerConfiguration: SMB = Windows file sharing
    "0337": "show dns cache",            # Get-DnsClientCache: this PC's DNS resolver cache
                                          #   (distinct from Get-DnsServerCache/0298, a DNS-Server-
                                          #   role cmdlet no home PC has installed)
    "0341": "show my dns servers",       # Get-DnsClientServerAddress: which DNS servers this PC uses
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
