$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\pythonw.exe"
$executable = Join-Path $repo "dist\NOEMA-JARVIS.exe"
$dashboard = "http://127.0.0.1:8770"

try {
    $health = Invoke-RestMethod -Uri "$dashboard/health" -TimeoutSec 2
} catch {
    $health = $null
}

if ($health.status -eq "ok") {
    Start-Process $dashboard
    exit 0
}

if (-not (Test-Path -LiteralPath $executable) -and -not (Test-Path -LiteralPath $python)) {
    throw "Weder NOEMA-JARVIS.exe noch die Python-Umgebung ist vorhanden."
}

$env:NOEMA_TIKTOK_BRIDGE_URL = "http://127.0.0.1:8765"
$env:NOEMA_LLM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:NOEMA_LLM_MODEL = "qwen/qwen3.5-9b"

if (Test-Path -LiteralPath $executable) {
    Start-Process -FilePath $executable -WorkingDirectory $repo
} else {
    Start-Process -FilePath $python -ArgumentList @("-m", "app.desktop") `
        -WorkingDirectory $repo
}
