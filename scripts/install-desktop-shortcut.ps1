param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("VM01", "WK02")]
    [string]$Role,

    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop")
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if ($Role -eq "VM01") {
    $launcherName = "start-noema-vm01.ps1"
    $shortcutName = "NOEMA 1 - LM Studio und Tunnel.lnk"
    $description = "NOEMA LM Studio und sicheren WK02-Tunnel starten"
} else {
    $launcherName = "start-noema-wk02.ps1"
    $shortcutName = "NOEMA 2 - JARVIS Dashboard.lnk"
    $description = "NOEMA J.A.R.V.I.S. starten und Dashboard öffnen"
}
$launcher = Join-Path $PSScriptRoot $launcherName

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Starter fehlt: $launcher"
}
if (-not (Test-Path -LiteralPath $DesktopPath)) {
    throw "Desktop fehlt: $DesktopPath"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $DesktopPath $shortcutName))
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = $repo
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,14"
$shortcut.Description = $description
$shortcut.Save()

Write-Host (Join-Path $DesktopPath $shortcutName)
