"""
batch_test_prompts_v3d_filesystem_edge_cases.py -- SESSION D of 4.
Filesystem/process op edge cases: special characters, spacing, unicode,
long names, near-duplicates -- the kind of real-world messiness v2's
clean "notes.txt"/"report.docx" examples never touch.

Run with:
    python batch_test_prompts_v3d_filesystem_edge_cases.py
    python batch_test_live.py batch_test_prompts_v3d_filesystem_edge_cases.txt
"""

PROMPTS_V3D = [
    # ── Filenames with spaces (regex slot extraction has to find the
    #    RIGHT boundary, not just split on the first space) ──
    "make a folder called My Project Files",
    "rename my resume.docx to final resume v2.docx",
    "delete the file named quarterly report draft.docx",
    "open my cover letter.docx",

    # ── Filenames with punctuation/special characters PowerShell would
    #    need to handle carefully (quotes, ampersands, parens, brackets) ──
    "make a folder called Q1 & Q2 Results",
    "open the file called notes (copy).txt",
    "rename [draft].txt to [final].txt",
    "delete report's_backup.txt",

    # ── Deeply nested / explicit paths, not just bare filenames ──
    "open D:\\Projects\\2026\\Q1\\summary.docx",
    "delete the file at D:\\Temp\\old\\notes.txt",
    "make a folder called Archive inside D:\\Backups",

    # ── Same base name, different extensions in one sentence (should
    #    extract the RIGHT one, or ask, never guess wrong) ──
    "open budget.xlsx not budget.csv",
    "delete report.docx but keep report.pdf",

    # ── Very long filenames ──
    "rename notes.txt to " + ("very-" * 20) + "long-filename.txt",
    "make a folder called " + ("Sub" * 15) + "Folder",

    # ── Numbers-only / minimal names ──
    "make a folder called 2026",
    "open 1.txt",
    "rename 001.docx to 002.docx",

    # ── Unicode filenames (accents, non-Latin scripts, emoji) ──
    "open café-menu.docx",
    "make a folder called Résumés",
    "delete 报告.txt",
    "rename notes.txt to 📁notes.txt",

    # ── Near-duplicate process/app names (should disambiguate or ask,
    #    never kill the wrong one) ──
    "kill chrome.exe",
    "kill google chrome",
    "terminate the chrome process",
    "close all chrome windows",

    # ── Multiple similar processes running (ambiguity within ONE
    #    process-management command, not a chain) ──
    "kill all notepad windows",
    "close every instance of chrome",

    # ── File ops where source and destination could be confused ──
    "copy notes.txt from D drive to desktop",
    "move the file from Downloads to Desktop called setup.exe",

    # ── Relative/vague location references ──
    "make a folder called Test on my desktop",
    "open the resume in my downloads folder",
    "delete everything in the Temp folder",  # should ask, not bulk-delete
]


if __name__ == "__main__":
    with open("batch_test_prompts_v3d_filesystem_edge_cases.txt", "w", encoding="utf-8") as f:
        for p in PROMPTS_V3D:
            f.write(p + "\n")
    print(f"Wrote {len(PROMPTS_V3D)} prompts to batch_test_prompts_v3d_filesystem_edge_cases.txt")
    print("Run with: python batch_test_live.py batch_test_prompts_v3d_filesystem_edge_cases.txt")
