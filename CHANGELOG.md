# Changelog
## 1.0.2

- Add a now-playing card to the main window. It shows the title, artist and artwork of what is playing, with previous, play/pause and next buttons that follow what the player supports. It replaces the large status circle, the waveform and the old Play/Pause buttons.
- The artwork is a slowly spinning disc. It spins only while music plays, stops while the window is hidden or minimized, and can be switched off with the new "Spinning cover" setting.
- A small status pill on the card shows where you are (waiting, in the menu, in match) and turns pink with "Paused for your match" when VibePause paused your music.
- Replace the "Live activity" log with a "Game status" card. It shows only the current VALORANT state and the last three game events. Update checks, monitor errors and other system messages no longer appear there; they stay in error.log and in "Copy diagnostics".
- Remove the "Call apps are skipped" caption from the Supported media card. Call apps are still skipped.
- Show a clearer message, and write the details to error.log, when an update download returns a web page instead of the installer or a different size than expected.
- error.log now also records crashes outside the window (including background threads) and every failed update check or download, with the Windows and Python version on each entry.
- Remove the Google Drive update fallback. Updates come from GitHub releases only.

## 1.0.1

- Add a Google Drive fallback for update checks, used while the GitHub repository is private. Updates are still verified with a SHA-256 checksum.

## 1.0.0

First full release.

- Add Windows built-in OCR fallback for local death detection by looking for the on-screen “KILLED BY” banner during active rounds.
- Include Windows OCR runtime dependencies in the packaged build.
