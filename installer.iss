; Inno Setup script for AFV Tracker
; Build with build_release.ps1 (which passes /DAppVersion=x.y.z), or directly:
;   ISCC.exe installer.iss /DAppVersion=1.0.0
;
; Installs per-user (no admin prompt) into %LocalAppData%\Programs\AFV Tracker,
; the same pattern Stratos and most Electron apps use.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName "AFV Tracker"
#define Publisher "Africana Virtual Airways"
#define ExeName "AFV Tracker.exe"

[Setup]
AppId={{7A3B9C64-52E1-4F8D-9B2A-AFV0TRACKER1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL=https://africanava.ddns.net
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=AFV-Tracker-Setup-{#AppVersion}
SetupIconFile=client\assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
OutputDir=dist\installer

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\AFV Tracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
