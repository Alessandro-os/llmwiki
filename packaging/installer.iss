; Installer di LLMWiki (Inno Setup 6). Lo compila packaging\build.ps1 se trova ISCC.exe:
;   winget install JRSoftware.InnoSetup
; Si installa per il solo utente, senza diritti di amministratore. La disinstallazione toglie
; il programma e lascia intatti documenti, spazi e decision model.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8B6B0C3E-4E53-4E6B-9C55-6E1E3A2F7A41}
AppName=LLMWiki
AppVersion={#AppVersion}
AppVerName=LLMWiki {#AppVersion}
AppPublisher=LLMWiki
DefaultDirName={localappdata}\Programs\LLMWiki
DefaultGroupName=LLMWiki
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=LLMWiki-{#AppVersion}-setup
SetupIconFile=llmwiki.ico
UninstallDisplayIcon={app}\LLMWiki.exe
UninstallDisplayName=LLMWiki
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un'icona sul desktop"; GroupDescription: "Icone:"
Name: "autostart"; Description: "Avvia LLMWiki all'accensione del computer (resta nell'area di notifica)"; GroupDescription: "Avvio:"; Flags: unchecked

[Files]
Source: "..\dist\LLMWiki\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\LLMWiki"; Filename: "{app}\LLMWiki.exe"
Name: "{group}\Leggimi"; Filename: "{app}\LEGGIMI.txt"
Name: "{userdesktop}\LLMWiki"; Filename: "{app}\LLMWiki.exe"; Tasks: desktopicon
Name: "{userstartup}\LLMWiki"; Filename: "{app}\LLMWiki.exe"; Parameters: "--no-window"; Tasks: autostart

[Run]
Filename: "{app}\LLMWiki.exe"; Description: "Avvia LLMWiki"; Flags: nowait postinstall skipifsilent
