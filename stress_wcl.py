from wcl_resolver import WCLResolver
import json

r = WCLResolver()

# Broad natural-language battery covering many command families, mixing:
# - exact/near-exact phrasing that SHOULD resolve
# - realistic casual phrasing a user would actually type
# - deliberately ambiguous phrasing
# - garbage/out-of-vocabulary phrasing that SHOULD miss (UNRESOLVED)
queries = [
    # file/folder ops
    "make a new folder called test",
    "delete this file",
    "copy file to backup",
    "read the contents of readme.txt",
    "list files in this directory",
    "find large files",
    "compress this folder",
    "extract the zip",
    # process/service
    "kill notepad",
    "close chrome",
    "list running processes",
    "stop the print spooler service",
    "start the dns service",
    "restart the service",
    # disk/storage
    "wipe disk 2",
    "format the usb drive",
    "get disk space",
    "show me the disk usage",
    "list all volumes",
    "check disk for errors",
    "shrink partition",
    # network
    "what is my ip address",
    "show open ports",
    "ping google.com",
    "flush dns cache",
    "list network adapters",
    "disable the wifi adapter",
    "show firewall rules",
    "add a firewall rule for port 8080",
    # bitlocker / security
    "bitlocker lock mount point D",
    "encrypt drive c with bitlocker",
    "show bitlocker status",
    "take ownership of this file",
    # scheduled tasks / registry
    "list scheduled tasks",
    "create a scheduled task",
    "open the registry editor",
    # vm / hyperv
    "list virtual machines",
    "start vm named test",
    "create a checkpoint of the vm",
    "get vm memory usage",
    # dedup / storage pools
    "disable dedup volume on E",
    "enable deduplication on drive e",
    "get storage pool status",
    # dns/dhcp
    "get dns server cache",
    "add a dns record",
    "authorize the dhcp server",
    "get dhcp scope",
    # powershell/console
    "clear the screen",
    "show command history",
    "list powershell modules",
    # event log
    "clear the event log",
    "show recent errors in event log",
    # casual / ambiguous / should miss
    "hey how's it going",
    "what's the weather",
    "turn off my monitor",
    "shut up",
    "go to the store",
    "stop the music",
]

results = []
for q in queries:
    res = r.resolve(q)
    results.append((q, res.get("status"), res.get("tier"), res.get("command") if res.get("status")=="RESOLVED" else res.get("candidates") or res.get("loose_candidates")))

resolved = sum(1 for _,s,_,_ in results if s == "RESOLVED")
ambiguous = sum(1 for _,s,_,_ in results if s == "AMBIGUOUS")
unresolved = sum(1 for _,s,_,_ in results if s == "UNRESOLVED")

print(f"Total: {len(results)}  RESOLVED: {resolved}  AMBIGUOUS: {ambiguous}  UNRESOLVED: {unresolved}\n")
for q, status, tier, extra in results:
    print(f"[{status:10}] tier={str(tier):4} | {q!r:50} -> {extra}")
