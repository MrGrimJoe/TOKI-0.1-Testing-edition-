<#
run.ps1 -- the 12-manual-commands problem, collapsed into one.

Used to be: create the venv, activate it, install requirements, THEN
separately run pytest, THEN separately run each of 5 batch-prompt
generators, THEN separately run batch_test_live.py against each .txt it
produced. This script does all of it, in order, idempotently -- safe to
re-run any time (skips venv creation / reinstall if already done).

USAGE (from the project root, in a normal PowerShell window -- you do NOT
need to activate the venv yourself first, this script does it for you):

    .\run.ps1                    # everything: setup + pytest + all live batches
    .\run.ps1 -PytestOnly         # setup + fast suite only, skip Ollama entirely
    .\run.ps1 -LiveOnly           # setup + live batches only, skip pytest
    .\run.ps1 -Model llama3.2     # passed through to run_all_tests.py / batch_test_live.py

If you've never run this before, first run may take a few minutes (venv
creation + downloading PyQt6/kuzu/etc.). Every run after that is fast to
get INTO the tests -- setup is skipped once .venv already has everything
requirements.txt asks for.
#>

param(
    [switch]$PytestOnly,
    [switch]$LiveOnly,
    [string]$Model = "phi4-mini"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# ── Step 1: venv (create only if missing) ────────────────────────────────
$venvPython = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "== No .venv found -- creating one (py -3.12) ==" -ForegroundColor Cyan
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "venv creation failed -- is Python 3.12 installed and on PATH as 'py -3.12'?" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "== .venv already exists, skipping creation ==" -ForegroundColor DarkGray
}

# ── Step 2: install requirements ──────────────────────────────────────────
# Not skipped even on a pre-existing venv -- pip install is a fast no-op
# when everything's already satisfied, and this guarantees a venv from an
# older session (missing a package requirements.txt later grew, e.g. the
# pywinauto addition) gets caught up automatically instead of failing
# later with a confusing ImportError.
Write-Host "== Installing/verifying requirements.txt ==" -ForegroundColor Cyan
& $venvPython -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed -- see output above." -ForegroundColor Red
    exit 1
}

# ── Step 3: run the tests (this venv's python, no Activate.ps1 needed) ───
$testArgs = @()
if ($PytestOnly) { $testArgs += "--pytest-only" }
if ($LiveOnly)   { $testArgs += "--live-only" }
$testArgs += "--model"
$testArgs += $Model

Write-Host "== Running tests ==" -ForegroundColor Cyan
& $venvPython run_all_tests.py @testArgs
exit $LASTEXITCODE
