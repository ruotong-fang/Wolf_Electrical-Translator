#define MyAppName "Wolf Electrical Translator"
#define MyAppVersion "0.2.1"
#define MyAppPublisher "Wolf Electrical Translator"
#define MyAppExeName "EETranslator.exe"

[Setup]
AppId={{7E7FCE1E-3F35-49B9-B1EC-26F52DD0B38A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Wolf Electrical Translator
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=Wolf-Electrical-Translator-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=LICENSE

[Files]
Source: "dist\EETranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\电气工程翻译器"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动电气工程翻译器"; Flags: nowait postinstall skipifsilent
