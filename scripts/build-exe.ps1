$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "Virtuelle Umgebung fehlt. Zuerst: py -3.12 -m venv .venv"
}

& ".venv\Scripts\python.exe" -m pip install -e ".[build]"
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "NOEMA-JARVIS.spec"

Write-Host "Fertig: dist\NOEMA-JARVIS.exe"
