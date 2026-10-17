#define MyAppName "VibePause"
#define MyAppPublisher "tanveer-exe"
#define MyAppExeName "VibePause.exe"

[Setup]
AppId={{D5B8B6B7-7B61-4D1D-9D73-3A1B9A0D1E42}
AppName={#MyAppName}
AppVersion=0.1.3
; Keep these three in step with AppVersion. SignPath requires the product name and version to be set
; the same way in every signed file.
VersionInfoVersion=0.1.3.0
VersionInfoProductName=VibePause
VersionInfoProductVersion=0.1.3.0
VersionInfoDescription=VibePause Setup
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Tanveer-exe/VibePause
AppSupportURL=https://github.com/Tanveer-exe/VibePause/issues
AppUpdatesURL=https://github.com/Tanveer-exe/VibePause/releases
AppCopyright=Copyright (C) 2026 tanveer-exe
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
; The dark colours are painted by the [Code] section below, the same way on every Inno Setup 6.x.
; (Do not use "WizardStyle=modern dark" here: it re-colours the window itself and the rounded
; buttons then show square dark corners against a different grey.)
WizardStyle=modern
WizardImageFile=wizard_large.bmp,wizard_large_125.bmp,wizard_large_150.bmp,wizard_large_200.bmp
WizardSmallImageFile=wizard_small.bmp,wizard_small_125.bmp,wizard_small_150.bmp,wizard_small_200.bmp
DisableWelcomePage=no
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

[Messages]
WelcomeLabel1=Welcome to VibePause
WelcomeLabel2=VibePause pauses your music when a VALORANT round starts and plays it again when you die or the round ends.
FinishedHeadingLabel=VibePause is ready
FinishedLabelNoIcons=VibePause is installed.
FinishedLabel=VibePause is installed. Open it from the Start menu or tick the box below to launch it now.

[Code]
const
  ThemeBack = $1C0A0A;
  ThemePanel = $2B1414;
  ThemeField = $3D1E1E;
  ThemeText = $FFEFF1;
  ThemeMuted = $C49A9C;
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

function DwmSetWindowAttribute(hwnd: HWND; dwAttribute: Cardinal; var pvAttribute: Integer; cbAttribute: Cardinal): Integer;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall delayload';

var
  NextImg, BackImg, CancelImg, BrowseImg: TBitmapImage;

function Clamp01(V: Extended): Extended;
begin
  if V < 0 then
    Result := 0
  else if V > 1 then
    Result := 1
  else
    Result := V;
end;

function MixColor(A, B: Integer; F: Extended): Integer;
var
  R, G, Bl: Integer;
begin
  R := Round((A and $FF) * (1 - F) + (B and $FF) * F);
  G := Round(((A shr 8) and $FF) * (1 - F) + ((B shr 8) and $FF) * F);
  Bl := Round(((A shr 16) and $FF) * (1 - F) + ((B shr 16) and $FF) * F);
  Result := R or (G shl 8) or (Bl shl 16);
end;

procedure DrawPill(Bmp: TBitmap; W, H, Fill, Edge: Integer);
var
  X, Y: Integer;
  Radius, Qx, Qy, Mx, My, T, D, Outer, Inner: Extended;
  C: Integer;
begin
  Bmp.Width := W;
  Bmp.Height := H;
  Radius := H * 0.42;
  for Y := 0 to H - 1 do
    for X := 0 to W - 1 do
    begin
      Qx := Abs(X + 0.5 - W / 2) - (W / 2 - Radius);
      Qy := Abs(Y + 0.5 - H / 2) - (H / 2 - Radius);
      if Qx > 0 then Mx := Qx else Mx := 0;
      if Qy > 0 then My := Qy else My := 0;
      if Qx > Qy then T := Qx else T := Qy;
      if T > 0 then T := 0;
      D := Sqrt(Mx * Mx + My * My) + T - Radius;
      Outer := Clamp01(0.5 - D);
      Inner := Clamp01(0.5 - (D + 1.2));
      C := MixColor(ThemeBack, Edge, Outer);
      C := MixColor(C, Fill, Inner);
      Bmp.Canvas.Pixels[X, Y] := C;
    end;
end;

procedure PaintButton(Img: TBitmapImage; Cap: String; Primary, Enabled: Boolean);
var
  Fill, Edge, TextCol, TW, TH: Integer;
begin
  StringChangeEx(Cap, '&', '', True);
  if Primary then
  begin
    Fill := $381E46;
    Edge := $7150A2;
    TextCol := $8F5DFF;
  end else begin
    Fill := $28171A;
    Edge := $42322F;
    TextCol := ThemeText;
  end;
  if not Enabled then
  begin
    Fill := ThemePanel;
    Edge := $3A2A2A;
    TextCol := $7A6A6A;
  end;
  DrawPill(Img.Bitmap, Img.Parent.Width, Img.Parent.Height, Fill, Edge);
  Img.Bitmap.Canvas.Font.Assign(WizardForm.Font);
  Img.Bitmap.Canvas.Font.Style := [fsBold];
  Img.Bitmap.Canvas.Font.Color := TextCol;
  Img.Bitmap.Canvas.Brush.Style := bsClear;
  TW := Img.Bitmap.Canvas.TextWidth(Cap);
  TH := Img.Bitmap.Canvas.TextHeight(Cap);
  Img.Bitmap.Canvas.TextOut((Img.Parent.Width - TW) div 2, (Img.Parent.Height - TH) div 2, Cap);
  Img.Invalidate;
end;

function MakePill(Nat: TNewButton; Click: TNotifyEvent; Primary: Boolean): TBitmapImage;
var
  Holder: TPanel;
begin
  Holder := TPanel.Create(WizardForm);
  Holder.Parent := Nat.Parent;
  Holder.BevelOuter := bvNone;
  Holder.Color := ThemeBack;
  Holder.Caption := '';
  Holder.SetBounds(Nat.Left, Nat.Top, Nat.Width, Nat.Height);
  Holder.Anchors := Nat.Anchors;
  Holder.Cursor := crHand;
  Holder.OnClick := Click;
  Result := TBitmapImage.Create(Holder);
  Result.Parent := Holder;
  Result.Align := alClient;
  Result.Cursor := crHand;
  Result.OnClick := Click;
  PaintButton(Result, Nat.Caption, Primary, Nat.Enabled);
end;

procedure NextPillClick(Sender: TObject);
begin
  if WizardForm.NextButton.Enabled then
    WizardForm.NextButton.OnClick(WizardForm.NextButton);
end;

procedure BackPillClick(Sender: TObject);
begin
  if WizardForm.BackButton.Enabled then
    WizardForm.BackButton.OnClick(WizardForm.BackButton);
end;

procedure CancelPillClick(Sender: TObject);
begin
  if WizardForm.CancelButton.Enabled then
    WizardForm.CancelButton.OnClick(WizardForm.CancelButton);
end;

procedure BrowsePillClick(Sender: TObject);
begin
  WizardForm.DirBrowseButton.OnClick(WizardForm.DirBrowseButton);
end;

procedure SyncPill(Img: TBitmapImage; Nat: TNewButton; Primary: Boolean);
begin
  Img.Parent.Visible := Nat.Visible;
  PaintButton(Img, Nat.Caption, Primary, Nat.Enabled);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  SyncPill(NextImg, WizardForm.NextButton, True);
  SyncPill(BackImg, WizardForm.BackButton, False);
  SyncPill(CancelImg, WizardForm.CancelButton, False);
end;

procedure DarkTitleBar();
var
  One, Cap, Txt: Integer;
begin
  One := 1;
  Cap := ThemePanel;
  Txt := ThemeText;
  try
    DwmSetWindowAttribute(WizardForm.Handle, 20, One, 4);
    DwmSetWindowAttribute(WizardForm.Handle, 35, Cap, 4);
    DwmSetWindowAttribute(WizardForm.Handle, 36, Txt, 4);
  except
  end;
end;

procedure ThemeControls(Parent: TWinControl);
var
  I: Integer;
  C: TControl;
begin
  for I := 0 to Parent.ControlCount - 1 do
  begin
    C := Parent.Controls[I];
    if C is TNewStaticText then
      TNewStaticText(C).Font.Color := ThemeText
    else if C is TNewCheckBox then
      TNewCheckBox(C).Font.Color := ThemeText
    else if C is TNewRadioButton then
      TNewRadioButton(C).Font.Color := ThemeText
    else if C is TNewCheckListBox then
    begin
      TNewCheckListBox(C).Color := ThemePanel;
      TNewCheckListBox(C).Font.Color := ThemeText;
    end
    else if C is TEdit then
    begin
      TEdit(C).Color := ThemeField;
      TEdit(C).Font.Color := ThemeText;
    end
    else if C is TNewNotebookPage then
      TNewNotebookPage(C).Color := ThemeBack
    else if C is TPanel then
      TPanel(C).Color := ThemeBack;
    if C is TWinControl then
      ThemeControls(TWinControl(C));
  end;
end;

procedure InitializeWizard();
begin
  WizardForm.Color := ThemeBack;
  ThemeControls(WizardForm);
  WizardForm.MainPanel.Color := ThemePanel;
  WizardForm.PageNameLabel.Font.Color := ThemeText;
  WizardForm.PageDescriptionLabel.Font.Color := ThemeMuted;
  WizardForm.ReadyMemo.Color := ThemePanel;
  WizardForm.ReadyMemo.Font.Color := ThemeText;
  WizardForm.WelcomeLabel1.Font.Color := ThemeText;
  NextImg := MakePill(WizardForm.NextButton, @NextPillClick, True);
  BackImg := MakePill(WizardForm.BackButton, @BackPillClick, False);
  CancelImg := MakePill(WizardForm.CancelButton, @CancelPillClick, False);
  BrowseImg := MakePill(WizardForm.DirBrowseButton, @BrowsePillClick, False);
  WizardForm.Bevel.Visible := False;
  WizardForm.Bevel1.Visible := False;
  DarkTitleBar();
  WizardForm.FinishedHeadingLabel.Font.Color := ThemeText;
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
