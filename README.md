<p align="center">
  <img src="docs/banner.png" alt="VibePause - Your game. Your music. Automatically synced." width="100%">
</p>

<h1 align="center">VibePause</h1>

<p align="center"><b>Your game. Your music. Automatically synced.</b></p>

<p align="center">
  A lightweight Windows companion for <b>VALORANT</b> that pauses and plays your music for you,
  based on what is happening in the match.
</p>

<p align="center">
  <a href="https://github.com/Tanveer-exe/VibePause/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Tanveer-exe/VibePause?include_prereleases&label=RELEASE&labelColor=555555&color=ff4655&style=flat-square"></a>
  <a href="https://github.com/Tanveer-exe/VibePause/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/Tanveer-exe/VibePause/total?label=DOWNLOADS&labelColor=555555&color=3ddbc4&style=flat-square"></a>
  <img alt="Platform" src="https://img.shields.io/badge/PLATFORM-WINDOWS-0f1923?labelColor=555555&style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/PYTHON-3.12-3776ab?labelColor=555555&style=flat-square">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/LICENSE-MIT-0f6fff?labelColor=555555&style=flat-square"></a>
  <img alt="Made with Claude and ChatGPT" src="https://img.shields.io/badge/MADE_WITH-CLAUDE_%2B_CHATGPT-8b5cf6?labelColor=555555&style=flat-square">
</p>

<p align="center">
  <b>No overlay. No game injection. No memory reading. No gameplay automation.</b><br>
  VibePause reads one local log file and controls Windows media playback. That is all.
</p>

---

## Install

1. Open the **[Releases page](https://github.com/Tanveer-exe/VibePause/releases)**.
2. Download **`VibePause_Setup.exe`** from the newest release.
3. Run it. It installs for your user only, so **no administrator rights are needed**.

> **Windows SmartScreen:** the installer is not code-signed, so Windows may show
> "Windows protected your PC". Click **More info**, then **Run anyway**.
> This is normal for small open-source projects. You can read the full source here and build it yourself.

After installing, VibePause starts monitoring automatically. Start a media app (Spotify, YouTube Music, Apple Music or Chrome), launch VALORANT, and play.

To update later, open **Settings** and click **Check for updates**.

---

## Disclaimer and responsibility

> **Please read this before using VibePause.**

VibePause is an **independent community project**.

The developer is **not responsible for any account action, restriction, suspension, ban, compatibility issue, data loss, or other consequence resulting from the use of this software.**

You decide whether you are comfortable running third-party software alongside VALORANT. VibePause does **not** guarantee compatibility with Riot Games' systems, policies, Vanguard, or future versions of VALORANT. Riot may change its policies or game behavior at any time.

VibePause is:

- **Not affiliated with, endorsed by, or sponsored by Riot Games or VALORANT**
- **Not affiliated with Overwolf, isMine or Auto Mute Music**

If you have concerns about the code, assets, documentation or the project itself, please open an issue.

---

## What is VibePause?

VibePause watches VALORANT's local `ShooterGame.log`, detects game-state events, and performs the action you chose for each event.

```text
Music playing
     |
Round starts  ->  music pauses
     |
You die       ->  music resumes
     |
Next round    ->  music pauses
```

No Alt+Tab. No reaching for your media keys while you play.

---

## Features

### Events

| Event | Triggered when |
|---|---|
| Start combat phase | A round becomes active |
| On death | The local player dies during a round |
| Game start | The match becomes active |
| Start shopping phase | The buy phase opens |
| Game finish | The match ends |
| Back to lobby | You return to the main menu |
| Character select | Agent selection opens |
| Revive with ULT | The player is resurrected |

Every event has its own action. Click an event's icon to cycle:

```text
None  ->  Play  ->  Pause  ->  None
```

- **None**: do nothing
- **Play**: start or resume your music
- **Pause**: pause your music

Default setup: pause when combat starts, play for everything else. You can change any of them, and **Reset** restores the defaults.

### Supported media

VibePause talks to the **Windows System Media Transport Controls (GSMTC)**, the same system your keyboard media keys and the volume flyout use. It does not control any website or app directly.

Works with:

- Google Chrome
- YouTube Music
- Apple Music
- Spotify

If more than one of these has a media session, VibePause prefers a supported music player over other sessions.

### On death

VibePause can detect when the **local player dies** during an active round, so you can resume music while you wait.

Detection reads a marker VALORANT writes into its log. A short grace period after each round starts avoids false triggers from reconnect or spectate markers that can appear while a map loads.

VALORANT's log format is not documented or guaranteed. Riot can change it in any update, and death detection (like every other event) may need adjusting afterwards.

### Automatic monitoring

VibePause starts monitoring as soon as it launches. If VALORANT is not running, it waits for the log to appear.

### Event detection details

VALORANT does not always write the same sequence of messages, so the detector accepts several known variants and also handles:

- starting VALORANT while VibePause is already running
- going into a new match without passing through the main menu
- post-match transitions
- VALORANT rotating or truncating its log file

Repeated copies of the same event within a short window are ignored so a single moment does not trigger twice. Round ends are tracked internally but do not trigger an action.

### Windows desktop experience

- Custom dark title bar and fixed-size window
- Taskbar and Alt+Tab entry with the VibePause icon
- System tray icon
- Close to tray option
- Optional start with Windows
- No console window

### System tray

VibePause can keep running quietly in the tray:

- **Open VibePause**
- **Start VibePause**
- **Stop VibePause**
- **Exit VibePause**

Whether the window's **X** button sends VibePause to the tray or exits it is a setting (**Settings > Close button sends to tray**).

### Start with Windows

Optional. When Windows starts VibePause, it opens straight into the tray and keeps monitoring in the background.

### Settings

- Event delay (milliseconds before an action runs)
- Close button sends to tray
- Check for updates
- Start with Windows (top bar)

Settings are saved locally.

### Updates

Open **Settings** and click **Check for updates**.

- If a newer release exists, VibePause says so and asks before doing anything. If you agree, it downloads the installer, closes itself, and starts the installer.
- If you are already on the latest version, it tells you: "No update found."
- If GitHub cannot be reached, or a release has no installer, it shows a specific message.

Update checks contact the public GitHub API for this repository's releases. Nothing else is sent.

---

## UI and design

VibePause has a dark, VALORANT-inspired look: deep navy, off-white and signature red, with teal for "play". Icons and graphics are image assets made for this project.

The official VibePause icon uses a pause-bar design on a dark navy background with pink and cyan accents.

---

## Does VibePause modify VALORANT?

No. VibePause is an external companion app. It does **not**:

- inject DLLs into VALORANT
- read VALORANT process memory
- modify VALORANT files or game assets
- automate gameplay or send gameplay input
- interact with Vanguard
- modify network packets
- provide gameplay advantages
- draw an in-game overlay

How it works:

```text
VALORANT -> ShooterGame.log -> VibePause -> Windows media controls -> your music
```

The only input is the local log file. The only output is a Play or Pause request to Windows media playback. If the Windows media interface is unavailable on a machine, VibePause falls back to sending the standard Windows Play/Pause media key, which is the same as pressing that key on a keyboard.

> **Important:** this is a description of what the software does. It is **not** a guarantee from Riot Games that the software is permitted. Riot's policies and game behavior can change at any time.

---

## Privacy

VibePause runs locally. It does not need or collect:

- your Riot account credentials or authentication tokens
- your game memory or gameplay input
- your network traffic

The only network access is the update check and download described above.

---

## Built with Claude and ChatGPT

VibePause was built through human and AI collaboration, using **both Claude and ChatGPT** as coding partners, guided by natural-language instructions from start to finish (a lot of "vibe coding").

They helped with:

- application architecture and the Python code
- UI design and image assets
- VALORANT event detection, including death detection
- Windows media control and system tray behavior
- settings, startup option and the update checker
- PyInstaller packaging, the Inno Setup installer and GitHub Actions
- debugging, polish and this documentation

```text
Human:  "Can you add this?"
AI:     "Sure."
Human:  "It broke."
AI:     "I see the problem."
Human:  "Now make it prettier."
AI:     "Absolutely."
Human:  "Can it detect death?"
AI:     "Let's inspect the log."
```

The project is the result of that back-and-forth, plus testing on a real Windows PC with real matches. AI-written code can contain mistakes, so please read it before trusting it, and report anything that looks wrong.

---

## Inspiration

VibePause was inspired by **Auto Mute Music by isMine**, an Overwolf app that controls music around VALORANT events. Huge respect to its creator.

VibePause has its own code, interface, event detection, assets and Windows media-control implementation. It is **not** a replacement, clone or official continuation of Auto Mute Music, and all rights to that app belong to its creator. If you use Auto Mute Music, please support the original too.

---

## Tech stack

- Python and Tkinter
- pystray and Pillow
- Windows Runtime (GSMTC) through the `winrt` packages
- PyInstaller (one-folder build)
- Inno Setup (installer)
- GitHub Actions (automatic builds and releases)

---

## Project structure

```text
VibePause/
|-- VibePause_src.zip        All application source (see below)
|-- README.md
|-- docs/                    Images used by this README
`-- .github/
    `-- workflows/
        `-- build.yml        Builds the installer and publishes releases
```

`VibePause_src.zip` contains:

```text
VibePause.pyw        Main application
VibePause.spec       PyInstaller configuration
VibePause.ico        Application icon
assets/              Media icons, event icons and UI graphics
installer/           Inno Setup script and installer images
```

## Building VibePause

Releases are built by GitHub Actions:

1. Pushing a tag such as `v0.1.3` starts the build.
2. The workflow unpacks `VibePause_src.zip` and checks that the tag, `APP_VERSION` and the installer version all match.
3. PyInstaller builds the app, Inno Setup builds `VibePause_Setup.exe`.
4. The installer is attached to the GitHub release for that tag.

To build locally on Windows: install Python 3.12, then `pip install pyinstaller pystray pillow winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections`, run `pyinstaller VibePause.spec` inside the unpacked source, then compile `installer/VibePause.iss` with Inno Setup.

---

## Development status

VibePause is **alpha software**. It is developed mostly for learning, experimentation and personal use, and shared in case it is useful to others.

Things may break. Features may change. VALORANT updates can change log behavior, and Windows updates can change media-control behavior. There is no guarantee that:

- every VALORANT update will work immediately
- every media app will behave identically
- every log event will stay detectable
- every Windows version will behave the same

If something breaks, please open an issue with as much detail as you can (what you were doing, which media app, and what VibePause showed).

---

## Open source and contributing

VibePause is an open-source project. You are welcome to read the code, fork it, change it, add events or media players, fix bugs, and send pull requests.

1. Open an issue to explain your idea or bug.
2. Discuss the approach.
3. Send a pull request if you would like to implement it.

Small improvements are welcome too.

---

## Trademarks

VALORANT and Riot Games are trademarks of Riot Games, Inc. Spotify, YouTube, YouTube Music, Apple Music, Google Chrome, Overwolf, Auto Mute Music, Claude, ChatGPT and other mentioned products are trademarks or property of their respective owners.

VibePause does not claim ownership of third-party names, logos or applications. They are used only to identify supported apps, tools and inspiration.

---

## Creator

**Made by tanveer-exe**, together with **Claude** and **ChatGPT**.

## License

VibePause is released under the **[MIT License](LICENSE)**. You can use, copy, modify and distribute it, including in your own projects, as long as you keep the copyright notice.

The names VALORANT and Riot Games, and the names and logos of the supported media apps, belong to their owners and are not covered by this license.

---

<p align="center"><b>Your game. Your music. Automatically synced.</b></p>
