; Mesta PDF Pro installer (Inno Setup 6)
; Build with build_exe.bat, or:  ISCC.exe /DSrcDir=<pyinstaller dist\MestaPDFPro> installer\MestaPDFPro.iss

#define AppName "Mesta PDF Pro"
#define AppVersion "2.2.1"
#define ExeName "MestaPDFPro.exe"
#ifndef SrcDir
  #define SrcDir AddBackslash(GetEnv("TEMP")) + "psbuild\dist\MestaPDFPro"
#endif

[Setup]
AppId={{A3E2C8D1-5B7F-4E2A-9C61-0D4B8F3E7A25}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Mesta
DefaultDirName={autopf}\Mesta\PDF Pro
DefaultGroupName=Mesta
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=MestaPDFPro-Setup-{#AppVersion}
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#ExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=..\assets\wizard_large.bmp
WizardSmallImageFile=..\assets\wizard_small.bmp
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=yes
UsePreviousLanguage=no
ChangesAssociations=yes
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "arabic";  MessagesFile: "compiler:Languages\Arabic.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french";  MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
arabic.TaskAssoc=فتح ملفات PDF باستخدام Mesta PDF Pro
english.TaskAssoc=Open PDF files with Mesta PDF Pro
french.TaskAssoc=Ouvrir les fichiers PDF avec Mesta PDF Pro
arabic.TaskGroup=خيارات إضافية:
english.TaskGroup=Additional options:
french.TaskGroup=Options supplémentaires :
arabic.DocName=مستند PDF
english.DocName=PDF Document
french.DocName=Document PDF

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:TaskGroup}"
Name: "assocpdf"; Description: "{cm:TaskAssoc}"; GroupDescription: "{cm:TaskGroup}"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Mesta\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Registry]
; the app follows the Windows display language by default (changeable in Settings > Language)
; PDF association
Root: HKA; Subkey: "Software\Classes\Mesta.PDFPro.Document"; ValueType: string; ValueName: ""; ValueData: "{cm:DocName}"; Flags: uninsdeletekey; Tasks: assocpdf
Root: HKA; Subkey: "Software\Classes\Mesta.PDFPro.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#ExeName}"",0"; Tasks: assocpdf
Root: HKA; Subkey: "Software\Classes\Mesta.PDFPro.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#ExeName}"" ""%1"""; Tasks: assocpdf
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Mesta.PDFPro.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assocpdf
Root: HKA; Subkey: "Software\Classes\Applications\{#ExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: assocpdf

[Run]
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
