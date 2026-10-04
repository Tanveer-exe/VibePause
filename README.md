# 🎵 VibePause

> **Your game. Your music. Automatically synced.**

VibePause is a lightweight Windows companion application for **VALORANT** that automatically controls your music based on what's happening in-game.

It monitors VALORANT's locally generated `ShooterGame.log`, detects important gameplay events, and performs the action you configured for that event.

**No overlays.**  
**No game injection.**  
**No memory reading.**  
**No gameplay automation.**

Just your music, automatically synced with your VALORANT session.

---

# ⚠️ Disclaimer & Responsibility

> **Please read this section before using VibePause.**

VibePause is an **independent community project**.

The developer is **not responsible for any account action, restriction, suspension, ban, compatibility issue, data loss, or other consequence resulting from the use of this software**.

Users are responsible for deciding whether they are comfortable using third-party software alongside VALORANT.

VibePause does **not** guarantee compatibility with Riot Games' systems, policies, Vanguard, or future versions of VALORANT. Riot Games may change its policies or game behavior at any time.

VibePause is:

- **Not affiliated with Riot Games**
- **Not endorsed by Riot Games**
- **Not sponsored by Riot Games**
- **Not affiliated with VALORANT**
- **Not affiliated with Overwolf**
- **Not affiliated with isMine**
- **Not affiliated with Auto Mute Music**

## About the project

This project was built from scratch through human + AI collaboration and extensive experimentation.

The code, interface, assets, icons, documentation, and development workflow were created specifically for VibePause.

This README was also written and refined with the help of ChatGPT.

> And yes, this project was absolutely vibe coded. 😭

If you have concerns regarding VibePause, its code, assets, documentation, or the project itself, please open an issue in this repository.

---

# 🎵 What is VibePause?

VibePause watches VALORANT's local `ShooterGame.log` and detects game-state events.

You decide what should happen when each event occurs.

For example:

```text
🎵 Music Playing
        ↓
🎮 VALORANT Match
        ↓
⚔️ Combat Phase
        ↓
⏸️ Music Paused
        ↓
💀 Player Dies
        ↓
🎵 Music Resumes
        ↓
🔄 Next Round
        ↓
⏸️ Music Paused
```

You don't need to Alt+Tab out of the game or manually control your music.

VibePause handles it for you.

---

# ✨ Features

## 🎮 VALORANT Event Detection

VibePause currently supports the following events:

| Event | Description |
|---|---|
| ⚔️ Start Combat Phase | Triggered when a round enters combat |
| 🎮 Game Start | Triggered when the match becomes active |
| 🛒 Start Shopping Phase | Triggered when the buy/shop phase opens |
| 🏁 Game Finish | Triggered when the match reaches its end |
| 🏠 Back to Lobby | Triggered when returning to the main menu |
| 👤 Character Select | Triggered when entering character selection |
| 💀 On Death | Triggered when the local player dies |
| ♻️ Revive with Ultimate | Triggered when the player is resurrected |

Each event can have its own action.

---

# 🎵 Music Actions

Every event can be configured independently.

The action button cycles through:

```text
None → Play → Pause → None
```

### `None`

Do nothing.

### `Play`

Start or resume your music.

### `Pause`

Pause your music.

This keeps the interface compact without filling the application with unnecessary controls.

---

# 🎧 Supported Media

VibePause uses the **Windows System Media Transport Controls / GSMTC** system to communicate with supported media sessions.

Currently supported applications include:

- 🌐 Google Chrome
- 🎵 YouTube Music
- 🍎 Apple Music
- 🟢 Spotify

VibePause does not need to directly control the websites or applications.

It communicates through Windows' media-control system instead.

---

# 💀 On Death

VibePause can detect when the **local player dies** during an active round.

This allows configurations such as:

```text
Start Combat → Pause
On Death     → Play
Next Combat  → Pause
```

Result:

```text
⚔️ Round starts
      ↓
🎵 Music pauses
      ↓
💀 You die
      ↓
🎵 Music resumes
      ↓
🔄 Next round
      ↓
🎵 Music pauses again
```

Death detection is based on information written by VALORANT into its local log.

Because VALORANT's log format can change between updates, detection behavior may change if Riot modifies its logging system.

---

# 🤖 Automatic Monitoring

VibePause automatically starts monitoring when the application launches.

```text
Launch VibePause
       ↓
Start monitoring automatically
       ↓
Wait for VALORANT
       ↓
Detect events
       ↓
Control music
```

If VALORANT is not running, VibePause simply waits for the log to become available.

---

# 🔄 Robust Event Detection

VibePause is designed to handle the fact that VALORANT does not always produce exactly the same sequence of log messages.

The event detector supports multiple known variants of game-state transitions and handles situations such as:

- Starting VALORANT while VibePause is already running
- Entering a new match without returning through the main menu
- Post-match transitions
- Character-select transitions
- Game-state transitions
- Round starts
- Round ends
- Revives
- VALORANT log rotation
- VALORANT log truncation

Duplicate events are also filtered within a short window to prevent the same event from triggering multiple times.

---

# 🖥️ Windows Desktop Experience

VibePause is designed to behave like a normal Windows desktop application.

It includes:

- Custom borderless window
- Custom title bar
- Custom VibePause branding
- Fixed-size polished interface
- Windows taskbar support
- Alt+Tab support
- Custom application icon
- System tray support
- Close-to-tray option
- Start with Windows option
- Automatic monitoring
- No command prompt window required

VibePause is packaged as a standalone Windows application.

---

# 🔔 System Tray

VibePause can continue running in the Windows system tray.

Tray controls include:

- **Open VibePause**
- **Start VibePause**
- **Stop VibePause**
- **Exit VibePause**

This allows VibePause to run quietly in the background while you play.

---

# 🚀 Start with Windows

VibePause can optionally start automatically when Windows starts.

When launched through Windows startup, VibePause can start directly in the system tray while continuing to monitor VALORANT in the background.

---

# ⚙️ Settings

VibePause includes configurable settings for:

- Event actions
- Event delay
- Start with Windows
- Close to system tray
- Update checking

The application saves its settings locally so your configuration is preserved between launches.

---

# 🔄 Updates

VibePause includes an integrated **Check for Updates** system.

The intended update workflow is:

```text
Developer changes VibePause
          ↓
Commit / Push to GitHub
          ↓
GitHub Actions builds VibePause
          ↓
New release is published
          ↓
VibePause checks for updates
          ↓
New installer is downloaded
          ↓
VibePause is updated
```

The goal is to make updating VibePause as simple as possible for users.

No manually downloading GitHub Actions artifacts should be necessary for normal releases.

---

# 🎨 UI & Visual Design

VibePause was designed from the ground up with a dark, VALORANT-inspired aesthetic.

The project contains custom visual assets including:

- VibePause logo
- Application icon
- Media application icons
- Monitoring icon
- Event icons
- UI graphics
- Custom title bar
- Custom buttons
- Dark interface components
- Status indicators

The official VibePause icon uses the project's signature pause-bar design with a dark navy background and pink/cyan accents.

All VibePause-specific artwork and UI assets were created for this project.

---

# 💡 Inspiration

VibePause was inspired by **Auto Mute Music by isMine**, an Overwolf application that provides automatic music control based on events in VALORANT.

The idea of automatically controlling music around VALORANT gameplay events was an important inspiration for this project.

Huge respect to the creator of Auto Mute Music.

The original application inspired the idea behind VibePause, but VibePause has its own:

- Implementation
- Codebase
- Interface
- Architecture
- Assets
- Event detection system
- Windows media-control implementation
- Development workflow

VibePause is **not a replacement, clone, or official continuation** of Auto Mute Music.

All rights to Auto Mute Music and its original work belong to its respective creator.

If you're using Auto Mute Music, please support the original creator too. ❤️

---

# 🔒 Does VibePause Modify VALORANT?

No.

VibePause is designed as an external companion application.

It does **not**:

- ❌ Inject DLLs into VALORANT
- ❌ Read VALORANT process memory
- ❌ Modify VALORANT files
- ❌ Modify game assets
- ❌ Automate gameplay
- ❌ Control your mouse
- ❌ Control your keyboard
- ❌ Interact with Vanguard
- ❌ Modify network packets
- ❌ Provide gameplay advantages
- ❌ Use an in-game overlay
- ❌ Inject anything into the game

The intended architecture is simply:

```text
VALORANT
    │
    ▼
ShooterGame.log
    │
    ▼
VibePause
    │
    ▼
Event Detection
    │
    ▼
Configured Action
    │
    ▼
Windows Media System
    │
    ▼
Your Music
```

VibePause only needs the information written to the local VALORANT log to determine game events.

> **Important:** This does not constitute a guarantee from Riot Games that the software is permitted. Riot's policies and game behavior can change at any time.

---

# 🛡️ Privacy

VibePause is designed to operate locally.

The core application does not need:

- Your Riot account credentials
- Your VALORANT password
- Your Riot authentication token
- Your game memory
- Your gameplay input
- Your network traffic

The main game-event detection mechanism is the locally generated:

```text
ShooterGame.log
```

Update functionality may communicate with GitHub to check for and download published VibePause releases.

---

# 🧠 100% Vibe Coded

## Yes. Seriously.

VibePause was developed using **ChatGPT as an AI coding partner**.

Natural-language instructions were used throughout the development process to design, build, debug, test, improve, and refine the application.

ChatGPT was heavily involved in:

- 🧠 Application architecture
- 🐍 Python development
- 🎨 UI design
- 🖼️ Asset generation
- 🎯 VALORANT event detection
- 💀 Death detection
- 🎵 Windows media control
- 🪟 Windows desktop behavior
- 🔔 System tray functionality
- ⚙️ Settings
- 🚀 Startup functionality
- 📦 PyInstaller packaging
- 🛠️ Inno Setup installer
- ☁️ GitHub Actions
- 🔄 Update system
- 🐛 Debugging
- ✨ UI polishing
- 📖 Documentation

The final project is the result of **human + AI collaboration**.

> **The code, UI, images, icons, debugging process, documentation, and development workflow were all created through extensive vibe coding with ChatGPT.**

And yes...

```text
Human: "Can you add this?"

ChatGPT: "Sure."

Human: "It broke."

ChatGPT: "I see the problem."

Human: "Now make it prettier."

ChatGPT: "Absolutely."

Human: "Can it detect death?"

ChatGPT: "Let's inspect the log."

Human: 💀
```

---

# 🧰 Tech Stack

VibePause is built using:

- **Python**
- **Tkinter**
- **Pystray**
- **Pillow**
- **Windows Runtime / GSMTC**
- **PyInstaller**
- **Inno Setup**
- **GitHub Actions**

### Development Environment

The project is primarily developed and tested on Windows.

---

# 📁 Project Structure

```text
VibePause/
│
├── VibePause.pyw
├── VibePause.spec
├── VibePause.ico
│
├── assets/
│   ├── media icons
│   ├── event icons
│   ├── UI graphics
│   └── other visual assets
│
├── installer/
│   └── VibePause.iss
│
└── .github/
    └── workflows/
        └── build.yml
```

---

# 📦 Building VibePause

The project uses:

### PyInstaller

to package the Python application into a standalone Windows application.

### Inno Setup

to create the Windows installer.

### GitHub Actions

to automate Windows builds.

The intended development workflow is:

```text
Edit source
    ↓
Commit
    ↓
Push to GitHub
    ↓
GitHub Actions
    ↓
Build EXE
    ↓
Build Installer
    ↓
Publish Release
```

---

# 🐛 Development Status

VibePause is currently an **alpha-stage project**.

It is actively being developed and improved.

Things may break.

Features may change.

VALORANT updates may change log behavior.

Windows updates may change media-control behavior.

The application is primarily being developed for:

- Experimentation
- Learning
- Personal use
- Open-source development
- Building a useful community utility

If something breaks, please open an issue and include as much information as possible.

---

# 🤝 Open Source

VibePause is intended to be a **fully open-source project**.

You are encouraged to:

- Read the source code
- Fork the repository
- Modify the application
- Experiment with the code
- Add new features
- Improve existing features
- Fix bugs
- Create your own builds
- Submit pull requests
- Create your own version of VibePause

If you want to completely change the application:

**Go for it.**

Want a different UI?

Change it.

Want new events?

Add them.

Want support for another media player?

Implement it.

Want to completely turn VibePause into something else?

Fork it and build your version.

That's the point of making the project open source.

---

# 🤝 Contributions

Contributions, suggestions, bug reports, and improvements are welcome.

If you have an idea:

1. Open an issue
2. Explain the idea
3. Discuss the implementation
4. Submit a pull request if you want to implement it

Small improvements are welcome too.

You don't need to completely rewrite the application to contribute.

---

# 🧪 Experimental Nature

VibePause is an independent project and should be treated as experimental software.

There is no guarantee that:

- Every VALORANT update will work immediately
- Every media application will behave identically
- Every log event will remain detectable
- Every Windows version will behave identically
- Future versions of VALORANT will preserve the same log format

The project will be updated as these systems change.

---

# ©️ Trademarks

VALORANT and Riot Games are trademarks of Riot Games, Inc.

Spotify, YouTube, YouTube Music, Apple Music, Google Chrome, Overwolf, Auto Mute Music, and other mentioned products are trademarks or properties of their respective owners.

VibePause does not claim ownership of third-party trademarks, names, logos, or applications.

Third-party names are used only to identify supported applications or explain project inspiration.

---

# 👨‍💻 Creator

**Made using ChatGPT by tanveer-exe**

VibePause was created through extensive human + AI collaboration.

The project was designed, developed, debugged, packaged, documented, and continuously improved with ChatGPT as an AI development partner.

---

# 📜 License

VibePause is intended to be released as open-source software.

See the repository's `LICENSE` file for the exact terms.

If you fork VibePause, you're free to take the project in your own direction according to the project's license.

---

# ❤️ Why VibePause?

Because sometimes you just want:

```text
🎵 Music ON
        ↓
🎮 Queue VALORANT
        ↓
👤 Character Select
        ↓
🛒 Buy Phase
        ↓
⚔️ Round Starts
        ↓
🎵 Music changes
        ↓
💀 You die
        ↓
🎵 Music changes
        ↓
♻️ Revive
        ↓
🎵 Music changes
        ↓
🔄 Next Round
        ↓
🏁 Match Ends
        ↓
🏠 Back to Lobby
```

No Alt+Tab.

No manually pausing Spotify.

No reaching for your music controls while playing.

No overlay.

No unnecessary complications.

Just:

```text
🎮 Your game
      +
🎵 Your music
      ↓
   VibePause
```

---

# 🎵 VibePause

### Your game. Your music. Automatically synced.

**Made with Python + ChatGPT + a lot of vibe coding. ❤️**
