param(
    [string]$Version = "0.5.2",
    [string]$OutputDir = "",
    [string]$Compiler = ""
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $repo "dist-setup" }
if (-not $Compiler) {
    $Compiler = Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path -LiteralPath $Compiler)) { throw "Inno Setup 6 fehlt: $Compiler" }
if (-not (Test-Path -LiteralPath (Join-Path $repo "dist\NOEMA-JARVIS.exe"))) {
    throw "Zuerst scripts/build-exe.ps1 ausführen."
}
& $Compiler "/DPackageVersion=$Version" "/DPackageOutput=$OutputDir" (Join-Path $PSScriptRoot "jarvis-installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Installer-Build fehlgeschlagen ($LASTEXITCODE)." }
