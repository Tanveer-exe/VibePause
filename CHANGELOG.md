# Changelog

## [1.0.3] - 2026-10-17
- Same release notes as 1.0.2 (see below). Add what changed in this build if it differs.

## [1.0.2] - 2026-10-16
### Added
- Now-playing card in the main window showing the title, artist and artwork of what is playing, with Previous, Play/Pause and Next buttons that follow what the player supports. It replaces the large status circle, the waveform and the old Play/Pause buttons.
- Status pill on the card showing where you are (waiting, in the menu, in match). It turns pink with "Paused for your match" when VibePause paused your music.
- error.log now also records crashes outside the window (including background threads) and every failed update check or download, with the Windows and Python version on each entry.

### Changed
- The "Live activity" log is replaced by a "Game status" card showing only the current VALORANT state and the last three game events. Update checks, monitor errors and other system messages now stay in error.log and "Copy diagnostics".
- Clearer message, with details written to error.log, when an update download returns a web page instead of the installer or a file of the wrong size.

### Removed
- Google Drive update fallback. Updates now come from GitHub releases only.

## [1.0.1] - 2026-10-15
### Added
- Google Drive fallback for update checks, used while the GitHub repository was private. Updates were still verified with a SHA-256 checksum.

## [1.0.0] - 2026-10-13
First full release.
### Added
- Windows built-in OCR fallback for local death detection, looking for the on-screen "KILLED BY" banner during active rounds.
- Windows OCR runtime dependencies included in the packaged build.

## [0.1.4] - 2026-10-10 (pre-release)
### Added
- Volume mode: switch from Pause to Volume and each event gets a volume slider instead of Play/Pause.
- Language selection on first start, changeable in Settings (translations are machine-made, corrections welcome).
- Optional hotkey to turn VibePause on or off (off by default, can be cleared any time).
- Settings buttons: Open log folder and Copy diagnostics, to make bug reports easier.
- The update prompt now shows what's new.
- "Quit VibePause?" confirmation when closing for real (the X button with Close to Tray off, or Exit in the tray).

### Fixed
- Dying in a match is now detected, so Player Eliminated works.
- Ultimate Used no longer triggers when a teammate or enemy is revived, only when you are.
- The music no longer pauses for a moment when the buy phase opens.
- Play only resumes the music app VibePause paused, not every app that was open.
- A delayed action could fire after a newer event and flip the music the wrong way.
- If a match ended during the buy phase, the next match's first buy phase was missed.
- After a failed Play, VibePause could resume the wrong app next time.
- The Terms screen could hide behind other windows and leave the app stuck.
- Repeated errors no longer flood the log file or Live activity.

## [0.1.3] - 2026-10-05 (pre-release)
### Added
- Installer: Repair/update options and a choice of install folder during setup.
- Active toggle to pause monitoring.
- Media app selector when multiple players are detected.

### Changed
- Settings are saved to Documents\VibePause, so they're kept through updates and reinstalls.

## [0.1.2] - 2026-10-05 (pre-release)
### Fixed
- Update checker: "Check for Updates" now finds new releases, including alpha pre-releases.
- Settings panel adjusted so SAVE SETTINGS is always fully visible.

### Added
- Update download shows progress and checks the file is complete before installing.

## [0.1.1] - 2026-10-04 (pre-release)
### Changed
- Improved update checking and settings UI.
### Fixed
- Settings button layout.
- General stability improvements.

## [0.1.0] - 2026-10-04 (pre-release)
First public alpha.
- Automatic play/pause based on VALORANT events: game start, combat phase, buy phase, death, match finish, return to lobby, character select, and revive with ultimate.
- Play / Pause / None action per event, customizable event delay.
- Works with Chrome, YouTube Music, Apple Music and Spotify.
- System tray support, run on Windows startup, automatic update checking.
