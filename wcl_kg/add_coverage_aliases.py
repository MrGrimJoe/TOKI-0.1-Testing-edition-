"""
add_coverage_aliases.py -- closes the coverage gap found by a full sweep of
all 1,160 windows_command_library commands (previous sessions only ran
"targeted" audits checking for specific known-bad shapes, per
PROJECT_STATE_OVERVIEW.md's "what it does NOT have" list, item 3).

The gap: 230 of 1,160 commands had ONLY mechanically-generated, noun-first
aliases (e.g. "screen clear", "audio sound devices") left over from the
original alias generator. None of these ever starts with a recognized verb
phrase, so 05_widen_dictionaries.py's automatic synonym-widening never fires
for them -- they're reachable ONLY by typing that exact, unnatural phrase.
Confirmed programmatically (not sampled) by running vocab.py's own
find_leading_cluster() against every command's existing aliases.

Fix: add exactly ONE hand-reviewed, natural, correctly-ordered alias to each
of these 230 commands, grounded in that command's own name/description/
intents (never invented). Where a genuinely-fitting existing VERB_CLUSTERS
verb exists (show/list/get/clear/copy/move/etc.), the new alias uses it --
that command then also gets full automatic synonym widening for free, same
as the other 930. Where no existing cluster verb is a good fit, the new
alias is still added plainly (a real, natural phrase) -- this still closes
the coverage gap for wcl_resolver's exact-match and fuzzy-match tiers even
without cluster widening, and is deliberately NOT forced into a cluster it
doesn't semantically belong to (adding new VERB_CLUSTERS entries would
change synonym behavior for the other 930 already-working commands too,
which is out of scope for this fix and not needed to close the gap).

Every entry below was reviewed against that command's real `description`
field in windows_command_library.widened.json -- none are guessed.
"""

import json
from pathlib import Path

WIDENED_PATH = Path(__file__).parent / "windows_command_library.widened.json"

# id -> new natural alias to add (verb-first where a real fit exists)
NEW_ALIASES = {
    # audio_display
    "0866": "sort the text",
    "0977": "clear the screen",
    "1104": "show sound devices",
    "1155": "take a screenshot",
    # date_time
    "1075": "show the time zone",
    # disk_storage
    "0086": "format output as a custom view",
    "0087": "format output as a wide table",
    "0088": "show the file as hex",
    "0465": "initialize the disk",
    "0471": "resize the partition",
    "0474": "format the volume",
    "0476": "optimize the volume",
    "0846": "compress files on this drive",
    "0872": "map a drive letter to a path",
    "0878": "copy this floppy disk",
    "0879": "recover data from this disk",
    "0882": "label this disk",
    "0883": "show the disk volume label",
    "0920": "mount this volume",
    "1039": "check system health",
    "1048": "show the disk space report",
    "1086": "show drive space",
    "1111": "show physical disks",
    "1112": "show disk partitions",
    "1113": "show volume information",
    "1115": "show virtual disks",
    "1131": "monitor disk performance",
    "1152": "turn off the audio",
    # event_log
    "0170": "write to the event log",
    "0933": "manage event logs",
    "0934": "create a custom event log entry",
    "1044": "export event logs",
    "1073": "show a summary of recent events",
    "1126": "show recent application errors",
    "1127": "show recent system warnings",
    # filesystem
    "0062": "resolve this wildcard path",
    "0064": "split this path into its parts",
    "0848": "create a cab archive",
    "0850": "copy these files and folders",
    "0851": "robustly copy these files",
    "0853": "move these files",
    "0855": "erase these files",
    "0861": "show the directory tree",
    "0868": "show or change file attributes",
    "0873": "show file type associations",
    "0874": "show the file type command",
    "0880": "replace these files",
    "0886": "push the current directory onto the stack",
    "0887": "restore the previous directory",
    "0903": "show the environment path variable",
    "0913": "transfer files by ftp",
    "0914": "transfer files by tftp",
    "0965": "show the current directory",
    "0966": "show the current path",
    "1087": "show the file count",
    "1088": "show the folder count",
    "1089": "show file types",
    "1144": "compress these files into a zip archive",
    # hyperv_vm
    "0634": "create a snapshot of this vm",
    # misc
    "0148": "write an error to the log",
    "0149": "write a warning to the log",
    "0150": "write a verbose log message",
    "0151": "write a debug log message",
    "0152": "write an informational log message",
    "0153": "show progress status",
    "0840": "show group policy results",
    "0841": "update group policy",
    "0842": "show the resultant set of policy",
    "0843": "configure security policy",
    "0844": "show the audit policy",
    "0845": "encrypt or decrypt these files",
    "0849": "extract this cab file",
    "0852": "copy these files",
    "0871": "take ownership of these files",
    "0888": "set the command prompt style",
    "0890": "set the console color",
    "0897": "pause for a timeout",
    "0901": "set an environment variable",
    "0902": "set a permanent environment variable",
    "0906": "start a command prompt",
    "0908": "start powershell core",
    "0909": "start the windows subsystem for linux",
    "0910": "start a bash shell",
    "0919": "digitally sign this file",
    "0923": "manage the windows image",
    "0924": "install windows components",
    "0926": "manage this device",
    "0927": "manage filter drivers",
    "0932": "show a trace report",
    "0990": "select specific properties",
    "0991": "group these results",
    "0992": "measure these results",
    "1005": "query wmi objects",
    "1006": "download this web resource",
    "1022": "rerun the last command",
    "1024": "show the help documentation",
    "1032": "compute the md5 hash",
    "1033": "compute the sha1 hash",
    "1034": "compute the sha256 hash",
    "1052": "check windows update status",
    "1055": "show environment variables",
    "1056": "show running services",
    "1057": "show stopped services",
    "1058": "show installed hotfix history",
    "1064": "show group membership",
    "1072": "show windows features",
    "1077": "show the keyboard layout",
    "1078": "show installed dotnet versions",
    "1079": "show the powershell version",
    "1080": "show the powershell execution policy",
    "1081": "show loaded powershell modules",
    "1083": "show command aliases",
    "1084": "show defined variables",
    "1085": "show defined functions",
    "1090": "show recently modified files",
    "1091": "show the oldest files",
    "1092": "show the largest folders",
    "1093": "show empty folders",
    "1097": "show group policy results for this computer",
    "1098": "show windows activation status",
    "1099": "show the windows product key",
    "1110": "show logical drives",
    "1114": "show storage pools",
    "1122": "show installed windows features",
    "1123": "show installed windows store apps",
    # network
    "0028": "resolve this dns name",
    "1038": "show saved wifi passwords",
    "1041": "diagnose network problems",
    "1050": "show network adapter info",
    "1051": "show firewall status",
    "1059": "show the dns cache",
    "1060": "show the arp table",
    "1061": "show the routing table",
    "1069": "show network shares",
    "1103": "show network adapter details",
    "1116": "show active network connections",
    "1117": "show listening ports",
    "1118": "show configured dns servers",
    "1119": "show ip routes",
    "1120": "show firewall rules",
    "1132": "monitor network performance",
    # performance_monitoring
    "0928": "load performance counters",
    "0929": "unload performance counters",
    "1066": "show memory usage",
    "1067": "show cpu info",
    "1128": "show performance counters",
    "1129": "monitor cpu performance",
    "1130": "monitor memory performance",
    "1133": "show the system uptime counter",
    "1135": "show the thread count",
    # power
    "0898": "pause for a number of seconds",
    "1074": "show the active power plan",
    "1107": "show battery status",
    # process
    "0015": "diagnose this process",
    "1003": "loop over each item in the pipeline",
    "1004": "loop over each item using percent",
    "1047": "monitor running processes",
    "1125": "show scheduled task history",
    "1134": "show the process count",
    # remote_management
    "0911": "connect over ssh",
    "0912": "connect over telnet",
    "0940": "shadow a remote session",
    "0941": "connect to a remote desktop",
    "0942": "connect to a remote desktop in admin mode",
    "0943": "connect to the console session",
    "0944": "connect to a specific remote computer",
    "0945": "connect with a specific window width",
    "0946": "connect with a specific window height",
    "0947": "connect in fullscreen mode",
    "0948": "connect in public mode",
    "0949": "connect spanning multiple monitors",
    "0950": "connect using multiple monitors",
    "0951": "connect and edit the rdp file",
    "0952": "migrate old remote desktop connection files",
    "0953": "connect to shadow a remote session",
    "0954": "connect and control a remote session",
    "0955": "connect without a consent prompt",
    "0956": "connect in restricted admin mode",
    "0957": "connect using remote guard",
    "0958": "connect and prompt for credentials",
    "0959": "connect using a specific certificate",
    "0960": "connect using a remote desktop plugin",
    "0961": "connect using load balance info",
    # scheduled_task
    "1054": "show scheduled tasks",
    "1124": "show currently running tasks",
    # scripting_core
    "0081": "show a graphical command window",
    "0100": "convert this text to a secure string",
    "1025": "show help documentation",
    # security_firewall
    "0869": "show file permissions",
    "0870": "show file permissions the old way",
    "0915": "manage certificates",
    "0916": "request a certificate",
    "1053": "show bitlocker encryption status",
    "1094": "show file permissions for this item",
    "1095": "show folder permissions",
    "1121": "show windows defender status",
    # service
    "1046": "monitor windows services",
    # software_package
    "0894": "call another batch script",
    "0895": "jump to a label in the script",
    "0899": "pause the script",
    # system_info
    "0904": "show or set the system date",
    "0905": "show or set the system time",
    "0925": "manage device drivers",
    "0985": "show service status",
    "1065": "show system uptime",
    "1068": "show gpu info",
    "1071": "show installed drivers",
    "1076": "show the system locale",
    "1100": "show bios info",
    "1101": "show motherboard info",
    "1102": "show ram info",
    "1105": "show usb devices",
    "1108": "show temperature sensor readings",
    "1109": "show fan speed",
    # user_session
    "0896": "prompt for a choice",
    "0931": "manage performance logs",
    "0936": "reset this session",
    "0939": "change session settings",
    "1021": "rerun a previous command by number",
    "1049": "show user session info",
    "1063": "show local user accounts",
    "1082": "show command history",
    "1096": "show user permissions",
    # web_http
    "0030": "download this web page",
    "0031": "call this rest api",
    "1007": "download this file from the web",
    "1008": "download this url",
    "1009": "call this api endpoint",
    # window_management
    "0889": "set the console window title",
    "0893": "start this program",
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
