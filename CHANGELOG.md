# Changelog
## 0.1.4

- New: an optional hotkey to turn VibePause on or off (off by default, and you can clear it any time)
- New: Settings has Open log folder and Copy diagnostics buttons to make bug reports easier
- New: the update prompt now shows what's new
- New: Volume mode. Switch from Pause to Volume and each event gets a volume slider instead of Play/Pause
- New: You pick one on first start and can change it in Settings (translations are machine-made, corrections welcome)
- Fixed: dying in a match is now detected, so Player Eliminated works
- New: closing VibePause for real (the X button with Close to Tray off, or Exit in the tray) now asks "Quit VibePause?" first
- Fixed: Ultimate Used no longer triggers when a teammate or enemy is revived, only when you are
- Fixed: the music no longer pauses for a moment when the buy phase opens
- Fixed: Play only resumes the music app VibePause paused, not every app that was open
- Fixed: a delayed action could fire after a newer event and flip the music the wrong way
- Fixed: if a match ended during the buy phase, the next match's first buy phase was missed
- Fixed: after a failed Play, VibePause could resume the wrong app next time
- Fixed: the Terms screen could hide behind other windows and leave the app stuck
- Fixed: repeated errors no longer flood the log file or Live activity
