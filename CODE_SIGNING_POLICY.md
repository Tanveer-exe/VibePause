# Code signing policy

**Status: planned.** VibePause is a new project that is building a track record (users, releases and
history). It plans to apply for free code signing from the [SignPath Foundation](https://signpath.org/) once
that is in place. Until then, the installer is **not signed**, so Windows SmartScreen may show
"Windows protected your PC".

If the application is approved, releases will be signed and this page will carry the line
"Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org)".

## Installing while it is unsigned

1. Run `VibePause_Setup.exe`. If your browser says the file isn't commonly downloaded, open the download's menu,
   choose **Keep**, then **Keep anyway**.
2. If Windows shows **Windows protected your PC**, click **More info**.
3. Click **Run anyway**.

Only do this for an installer you downloaded from this repository's Releases page or the
[official website](https://tanveer-exe.github.io/VibePause/). You can compare its checksum first (see below).

## What will be signed

- Only the installer and program files built by GitHub Actions from the tagged source in this repository.
  Nothing built on a personal computer is signed.
- Every release needs a manual approval before it is signed.

## Team roles

- Committers and reviewers: [tanveer-exe](https://github.com/Tanveer-exe)
- Approvers: [tanveer-exe](https://github.com/Tanveer-exe)

## Privacy policy

Read the full [Privacy Policy](src/PRIVACY_POLICY.md). In short, VibePause collects no personal data. It only
contacts GitHub, to check for and download updates, and you can turn the automatic check off in Settings.

## Verify a download today

Each release includes `VibePause_Setup.exe.sha256`. In PowerShell:

```powershell
Get-FileHash .\VibePause_Setup.exe -Algorithm SHA256
```

The value should match the one in that file. VibePause also checks every update it downloads against the
checksum GitHub publishes for the release file before it starts the installer.
