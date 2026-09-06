$ErrorActionPreference = "Stop"

$lms = Join-Path $env:USERPROFILE ".lmstudio\bin\lms.exe"
$sshKey = Join-Path $env:USERPROFILE ".ssh\id_wk02_noema_ed25519"

if (-not (Test-Path -LiteralPath $lms)) {
    throw "LM Studio CLI fehlt: $lms"
}
if (-not (Test-Path -LiteralPath $sshKey)) {
    throw "NOEMA SSH-Schlüssel fehlt."
}

$lmReady = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 1234 -State Listen `
    -ErrorAction SilentlyContinue
if (-not $lmReady) {
    Start-Process -FilePath $lms -ArgumentList @("server", "start") -WindowStyle Hidden
}

$reverseTunnel = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
    Where-Object { $_.CommandLine -like "*-R 127.0.0.1:1234:127.0.0.1:1234*" }
if (-not $reverseTunnel) {
    $arguments = @(
        "-i", $sshKey,
        "-N", "-T",
        "-R", "127.0.0.1:1234:127.0.0.1:1234",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "WK02"
    )
    Start-Process -FilePath "ssh.exe" -ArgumentList $arguments -WindowStyle Hidden
}

$dashboardTunnel = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
    Where-Object { $_.CommandLine -like "*-L 127.0.0.1:8770:127.0.0.1:8770*" }
if (-not $dashboardTunnel) {
    $arguments = @(
        "-i", $sshKey,
        "-N", "-T",
        "-L", "127.0.0.1:8770:127.0.0.1:8770",
        "-o", "BatchMode=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "WK02"
    )
    Start-Process -FilePath "ssh.exe" -ArgumentList $arguments -WindowStyle Hidden
}
