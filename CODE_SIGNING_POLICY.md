# Code signing policy

**Status: not signed yet.** The VibePause installer is currently unsigned, so Windows SmartScreen may show
"Windows protected your PC". The steps below describe what we plan to do once code signing is approved.

## Plan

- Apply to the [SignPath Foundation](https://signpath.org/) free program for open-source projects.
- Only installers built by GitHub Actions from the tagged source in this repository will be signed.
  Nothing built on a personal computer is signed.
- Roles: the maintainer, tanveer-exe, is author, reviewer and approver.
- Once approved, this page and the README will carry the acknowledgement SignPath Foundation asks for.

## Verify a download today

Each release includes `VibePause_Setup.exe.sha256`. In PowerShell:

```powershell
Get-FileHash .\VibePause_Setup.exe -Algorithm SHA256
```

The value should match the one in that file. VibePause also checks every update it downloads
against the checksum GitHub publishes for the release file before it starts the installer.

## Privacy

VibePause only contacts GitHub, to check for and download updates. See the [Privacy Policy](src/PRIVACY_POLICY.md).
