; StockKeep Windows installer (Inno Setup 6).
;
; Build with:  powershell -ExecutionPolicy Bypass -File .\build-setup.ps1
; The resulting setup is written to dist\StockKeepSetup-<version>.exe.
;
; The app is portable: its database, reports, backups, logs, exports and
; config live beside StockKeep.exe.  The installer deliberately installs only
; the executable, so uninstalling never removes business data.  The default
; folder is %USERPROFILE%\StockKeep because that is already the project's
; portable data folder; the user may choose another writable folder.

#define AppName "StockKeep"
#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#define AppExe "StockKeep.exe"

[Setup]
AppId={{15CDFFF6-92AD-4EAB-9126-22D331E3B80D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=StockKeep
DefaultDirName={%USERPROFILE}\StockKeep
DefaultGroupName=StockKeep
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=StockKeepSetup-{#AppVersion}
SetupIconFile=..\assets\stockkeep.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=1.2.0.0
VersionInfoCompany=StockKeep
VersionInfoDescription=StockKeep inventory management setup
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; No data folders are listed here on purpose: database, reports, backups,
; logs, config and exports must survive an uninstall.
