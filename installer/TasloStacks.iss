; Instalador de TasloStacks (Inno Setup 6). build.ps1 lo compila pasando /DAppVersion=x.y.z
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "TasloStacks"

[Setup]
AppId={{7D4E2C3A-5B1F-4C8E-9A2D-0A1B2C3D4E5F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=TasloStacks (software libre, MIT)
AppPublisherURL=https://github.com/taslostacks/TasloStacks
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; mismo AppId que SantiStacks (nombre hasta la 1.1.2): se instala encima, pero en la carpeta nueva
UsePreviousAppDir=no
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; la app se cierra sola antes de actualizar; que el instalador no la reabra por su cuenta (lo hace [Run])
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\TasloStacks\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; restos de SantiStacks (el nombre anterior)
Type: filesandordirs; Name: "{autopf}\SantiStacks"
Type: filesandordirs; Name: "{autoprograms}\SantiStacks"
Type: files; Name: "{autodesktop}\SantiStacks.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
; sin skipifsilent: cuando la app se actualiza sola (instalador en silencio) se vuelve a abrir al terminar
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
