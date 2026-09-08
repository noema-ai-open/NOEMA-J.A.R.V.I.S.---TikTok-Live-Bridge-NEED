#ifndef PackageVersion
  #define PackageVersion "0.5.7"
#endif
#ifndef PackageOutput
  #define PackageOutput "..\dist-setup"
#endif
[Setup]
AppId=NOEMA.JARVIS.Dashboard
AppName=NOEMA J.A.R.V.I.S.
AppVersion={#PackageVersion}
AppPublisher=NOEMA
AppPublisherURL=https://github.com/noema-ai-open/NOEMA-J.A.R.V.I.S.---TikTok-Live-Bridge-NEED
DefaultDirName={localappdata}\Programs\NOEMA\JARVIS
DefaultGroupName=NOEMA JARVIS
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
OutputDir={#PackageOutput}
OutputBaseFilename=NOEMA-JARVIS-Setup-{#PackageVersion}
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\dist\NOEMA-JARVIS.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Symbol NOEMA 2 - JARVIS Dashboard erstellen"; GroupDescription: "Verknuepfungen:"

[Files]
Source: "..\dist\NOEMA-JARVIS.exe"; DestDir: "{app}\dist"; Flags: ignoreversion
Source: "start-noema-wk02.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "start-noema-wk02.cmd"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\docs\INSTALLATION.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{autodesktop}\NOEMA 2 - JARVIS Dashboard"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\start-noema-wk02.ps1"""; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 14; Tasks: desktopicon
Name: "{group}\NOEMA JARVIS Dashboard"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\start-noema-wk02.ps1"""; WorkingDir: "{app}"; IconFilename: "{sys}\shell32.dll"; IconIndex: 14
Name: "{group}\Installationshinweise"; Filename: "{app}\INSTALLATION.txt"

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\start-noema-wk02.ps1"""; WorkingDir: "{app}"; Description: "JARVIS Dashboard starten"; Flags: nowait postinstall skipifsilent

; No runtime-settings.json or data/ entry: upgrades and uninstall preserve user data.
