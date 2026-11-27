; JinFlow Windows installer.
; The application payload keeps the historical JinshujuDesktop executable name
; so 1.x update handoffs and the existing user data directory remain valid.

#ifndef AppVersion
#define AppVersion "2.0.0"
#endif
#ifndef SourceDir
#define SourceDir "."
#endif
#ifndef OutputDir
#define OutputDir "."
#endif
#ifndef OutputBaseName
#define OutputBaseName "JinFlow-Setup"
#endif

[Setup]
AppId={{A5F5F7C2-9A61-4F1F-9B9E-3E6D7F2A1C40}
AppName=JinFlow
AppVersion={#AppVersion}
AppVerName=JinFlow {#AppVersion}
AppPublisher=JinFlow contributors
AppPublisherURL=https://github.com/ghy065178-blip/JinFlow
AppSupportURL=https://github.com/ghy065178-blip/JinFlow/issues
DefaultDirName={localappdata}\Programs\JinFlow
DefaultGroupName=JinFlow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
UninstallDisplayName=JinFlow
UninstallDisplayIcon={app}\JinshujuDesktop\JinshujuDesktop.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#SourceDir}\JinshujuDesktop\*"; DestDir: "{app}\JinshujuDesktop"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\JinFlow"; Filename: "{app}\JinshujuDesktop\JinshujuDesktop.exe"; WorkingDir: "{app}\JinshujuDesktop"
Name: "{autodesktop}\JinFlow"; Filename: "{app}\JinshujuDesktop\JinshujuDesktop.exe"; WorkingDir: "{app}\JinshujuDesktop"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Run]
Filename: "{app}\JinshujuDesktop\JinshujuDesktop.exe"; Description: "启动 JinFlow"; WorkingDir: "{app}\JinshujuDesktop"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\JinshujuDesktop"
