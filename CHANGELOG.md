# Changelog
## 1.0.0

First full release.

- Add Windows built-in OCR fallback for local death detection by looking for the on-screen “KILLED BY” banner during active rounds.
- Include Windows OCR runtime dependencies in the packaged build.

- New: Volume mode. Switch from Pause to Volume and each event gets a volume slider instead of Play/Pause
- New: 15 languages. You pick one on first start and can change it in Settings (translations are machine-made, corrections welcome)
- New: an optional hotkey to turn VibePause on or off (off by default)
- New: Open log folder and Copy diagnostics buttons in Settings
- New: the update prompt shows what's new, and VibePause asks "Quit VibePause?" before closing
- New: the installer has the same dark look as the app
- Fixed: Player Eliminated now works, and Ultimate Used only triggers when you are revived
- Fixed: several cases where the music paused or resumed at the wrong time
- Fixed: the Terms screen could hide behind other windows and leave the app stuck
- Fixed: repeated errors no longer flood the log file or Live activity
