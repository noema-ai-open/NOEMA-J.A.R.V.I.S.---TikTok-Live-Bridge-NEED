@echo off
setlocal
ssh.exe -i "%USERPROFILE%\.ssh\id_wk02_noema_ed25519" -N -T ^
  -R 127.0.0.1:1234:127.0.0.1:1234 ^
  -L 127.0.0.1:8770:127.0.0.1:8770 ^
  -o BatchMode=yes ^
  -o ExitOnForwardFailure=yes ^
  -o ServerAliveInterval=15 ^
  -o ServerAliveCountMax=3 ^
  WK02
