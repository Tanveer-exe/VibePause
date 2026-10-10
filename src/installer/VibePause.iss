#define MyAppName "VibePause"
#define MyAppPublisher "tanveer-exe"
#define MyAppExeName "VibePause.exe"

[Setup]
AppId={{D5B8B6B7-7B61-4D1D-9D73-3A1B9A0D1E42}
AppName={#MyAppName}
AppVersion=0.1.4
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\VibePause
DefaultGroupName=VibePause
DisableProgramGroupPage=yes
; "auto": the folder page is skipped when VibePause is already installed, so an
; update always goes into the existing folder instead of creating a second copy.
; To pick a new folder the user chooses "No" below, which removes the old copy first.
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\installer_output
OutputBaseFilename=VibePause_Setup
Compression=lzma2
SolidCompression=yes
; Inno Setup 6.6+ can draw the whole wizard in dark mode, matching the app. Older compilers
; fall back to the normal (light) modern style, so the build never breaks.
#if Ver >= 0x06060000
WizardStyle=modern dark
#else
WizardStyle=modern
#endif
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
; Same deep navy as the app background (Inno colours are BGR: #0a0a1c)
WizardImageBackColor=$1c0a0a
WizardSmallImageBackColor=$1c0a0a
SetupIconFile=..\VibePause.ico
UninstallDisplayIcon={app}\VibePause.ico
UninstallDisplayName=VibePause
ArchitecturesInstallIn64BitMode=x64compatible
AppMutex=VibePauseSingleInstanceMutex
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{D5B8B6B7-7B61-4D1D-9D73-3A1B9A0D1E42}_is1';

function GetUninstallValue(const ValueName: String; var Value: String): Boolean;
begin
  Result := RegQueryStringValue(HKCU, UninstallKey, ValueName, Value) or
            RegQueryStringValue(HKLM, UninstallKey, ValueName, Value);
end;

procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM VibePause.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function UninstallOldVersion(): Boolean;
var
  UninstallString: String;
  UninstallExe: String;
  OldDir: String;
  ResultCode: Integer;
begin
  Result := False;
  CloseRunningApp();

  if GetUninstallValue('UninstallString', UninstallString) then
  begin
    UninstallExe := RemoveQuotes(UninstallString);
    OldDir := ExtractFileDir(UninstallExe);
    Result := Exec(UninstallExe, '/VERYSILENT /NORESTART _?=' + OldDir, '', SW_HIDE,
                   ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    if Result then
    begin
      DeleteFile(UninstallExe);
      DeleteFile(ChangeFileExt(UninstallExe, '.dat'));
      RemoveDir(OldDir);
    end;
  end;

  if not Result then
    MsgBox('The existing VibePause installation could not be removed.' + #13#10 +
           'Uninstall it from Windows Settings > Apps, then run this installer again.',
           mbError, MB_OK);
end;

function HasSwitch(const Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function InitializeSetup(): Boolean;
var
  OldVersion: String;
  OldPath: String;
  Answer: Integer;
begin
  Result := True;

  // Is VibePause already installed?
  if (not HasSwitch('/UPDATE')) and GetUninstallValue('UninstallString', OldVersion) then
  begin
    if not GetUninstallValue('DisplayVersion', OldVersion) then
      OldVersion := '';
    if not GetUninstallValue('Inno Setup: App Path', OldPath) then
      OldPath := '(unknown location)';

    Answer := MsgBox('VibePause ' + OldVersion + ' is already installed at:' + #13#10 +
                     OldPath + #13#10 + #13#10 +
                     'What would you like to do?' + #13#10 + #13#10 +
                     'Yes: Update to version {#SetupSetting("AppVersion")} in that same folder' + #13#10 +
                     'No: Remove the existing installation first, then install (lets you pick a new folder)' + #13#10 +
                     'Cancel: Exit setup',
                     mbConfirmation, MB_YESNOCANCEL);

    case Answer of
      IDYES:
        Result := True;
      IDNO:
        Result := UninstallOldVersion();
    else
      Result := False;
    end;
  end;
end;

[Files]
Source: "..\dist\VibePause\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\VibePause.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\TERMS_AND_CONDITIONS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY_POLICY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\VibePause"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\VibePause.ico"; AppUserModelID: "tanveer-exe.VibePause"
Name: "{autodesktop}\VibePause"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\VibePause.ico"; Tasks: desktopicon; AppUserModelID: "tanveer-exe.VibePause"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Registry]
; Remove the Run-on-Startup entry when VibePause is uninstalled.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "VibePause"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch VibePause"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Preserve the user's config in Documents\VibePause
; Only remove the old AppData location if it exists (for cleanup)
Type: filesandordirs; Name: "{localappdata}\VibePause"
