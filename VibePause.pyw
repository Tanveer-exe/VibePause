import os, sys, re, time, ctypes, threading, queue, json, winreg, math
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

try:
    import pystray
    from PIL import Image, ImageDraw, ImageTk
    TRAY_AVAILABLE = True
except Exception:
    TRAY_AVAILABLE = False

APP_NAME = "VibePause"
APP_ID = "tanveer-exe.VibePause"
# Bundled resources: PyInstaller extracts/places them under sys._MEIPASS.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APPDATA = Path(os.getenv("APPDATA", str(Path.home()))) / "VibePause"
LEGACY_APPDATA = Path(os.getenv("APPDATA", str(Path.home()))) / "ValorantLimusicController"
CONFIG = APPDATA / "settings.json"
LEGACY_CONFIG = LEGACY_APPDATA / "settings.json"
LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs" / "ShooterGame.log"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "VibePause"
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYUP = 0x0002
user32 = ctypes.windll.user32

EVENTS = [
    ("On start combat phase", "Round becomes active"),
    ("On game start", "A game starts"),
    ("On start shopping phase", "Buy phase starts"),
    ("On game finish", "Game finishes"),
    ("On back lobby", "Return to lobby"),
    ("On character select screen", "Agent selection opens"),
    ("On revive with ULT", "Player is revived"),
]
DEFAULT_ACTIONS = {
    "On start combat phase": "Pause",
    "On game start": "Play",
    "On start shopping phase": "Play",
    "On game finish": "Play",
    "On back lobby": "Play",
    "On character select screen": "Play",
    "On revive with ULT": "Play",
}

# These are the four apps intentionally shown in the UI.
MEDIA_APPS = ["Google Chrome", "YouTube Music", "Apple Music", "Spotify"]

try:
    import asyncio
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    GSMTC_AVAILABLE = True
except Exception:
    GSMTC_AVAILABLE = False

async def _gsmtc_set(desired):
    """Ask the Windows media session for its real state, then send an explicit Play or Pause.
    Returns True/False (session now playing/paused) or None if there is no usable session."""
    mgr = await _SessionManager.request_async()
    session = mgr.get_current_session()
    if session is None:
        return None
    playing = session.get_playback_info().playback_status == _PlaybackStatus.PLAYING
    if desired and not playing:
        await session.try_play_async()
    elif not desired and playing:
        await session.try_pause_async()
    return desired

class Controller:
    def __init__(self, ui):
        self.ui = ui
        self.stop_event = threading.Event()
        self.thread = None
        self.music_playing = True
        self.current_event = "On back lobby"
        self.in_match = False
        self.lock = threading.Lock()

    def toggle_media(self):
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYUP, 0)

    def set_playing(self, desired):
        """Make the media session playing (True) or paused (False). Never blind-toggles when it can read the real state."""
        with self.lock:
            if GSMTC_AVAILABLE:
                try:
                    result = asyncio.run(_gsmtc_set(desired))
                    if result is None:
                        self.ui.event("system", "No active Windows media session")
                        return False
                    self.music_playing = desired
                    return True
                except Exception as e:
                    self.ui.event("system", f"Media session error: {e}")
            # Fallback (media session API unavailable): old toggle behaviour based on tracked state.
            if desired != self.music_playing:
                self.toggle_media()
                self.music_playing = desired
            return True

    def apply_action(self, event, actions, delay):
        action = actions.get(event, "None")
        self.current_event = event
        self.ui.event("event", (event, action))
        if action == "None":
            return
        if delay:
            time.sleep(delay / 1000)
        desired = action == "Play"
        if self.set_playing(desired):
            self.ui.event("music", "Playing" if desired else "Paused")

    def follow(self):
        while not self.stop_event.is_set():
            try:
                f = open(LOG, "r", encoding="utf-8", errors="ignore")
                f.seek(0, os.SEEK_END)
                self.ui.event("system", "Monitoring Valorant...")
                return f
            except FileNotFoundError:
                self.ui.event("system", "Waiting for Valorant...")
                time.sleep(1.5)
        return None

    def start(self, actions, delay):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, args=(actions, delay), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def run(self, actions, delay):
        f = self.follow()
        if not f:
            return
        self.apply_action("On back lobby", actions, 0)
        while not self.stop_event.is_set():
            line = f.readline()
            if not line:
                try:
                    if not LOG.exists() or LOG.stat().st_size < f.tell():
                        f.close()
                        f = self.follow()
                        if not f:
                            return
                except OSError:
                    pass
                time.sleep(.08)
                continue
            line = line.strip()
            low = line.lower()
            if "Reconcile called with the current state: MainMenu" in line:
                self.in_match = False
                self.apply_action("On back lobby", actions, delay)
                continue
            if "Reconcile called with the current state: InGame" in line:
                self.in_match = True
                self.apply_action("On game start", actions, delay)
                continue
            if self.in_match and any(x in low for x in ("pregame", "characterselection", "selectagent", "agentselect", "onagentselected", "onagentlockedin")):
                self.apply_action("On character select screen", actions, delay)
                continue
            if "Opening WBP_Screen_PreRoundShopContainer_C" in line:
                self.apply_action("On start shopping phase", actions, delay)
                continue
            if "Gameplay started at local time" in line:
                self.apply_action("On start combat phase", actions, delay)
                continue
            if self.in_match and any(x in low for x in ("revive with ult", "revived with ult", "resurrected", "resurrection")):
                self.apply_action("On revive with ULT", actions, delay)
                continue
            if any(x in line for x in ("WaitingToPostMatch", "PostMatch", "PostGame")):
                self.in_match = False
                self.apply_action("On game finish", actions, delay)
                continue

class ImgCheck(tk.Frame):
    """Tick box drawn from image assets (no native checkbox glyphs)."""
    def __init__(self, parent, text, variable, command, imgs, bg, fg, font):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var, self.command, self.imgs = variable, command, imgs
        self.icon = tk.Label(self, bg=bg, image=imgs[bool(variable.get())], bd=0)
        self.icon.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=bg, fg=fg, font=font, bd=0)
        self.lbl.pack(side="left", padx=(7, 0))
        for w in (self, self.icon, self.lbl):
            w.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *a: self.icon.config(image=self.imgs[bool(self.var.get())]))

    def _click(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

class App:
    # Valorant-inspired palette: deep navy, off-white, signature red, teal for "play".
    BG = "#0b121a"
    TOP = "#0f1923"
    PANEL = "#111b26"
    PANEL2 = "#182431"
    PANEL3 = "#223142"
    TEXT = "#ece8e1"
    MUTED = "#8b97a5"
    RED = "#ff4655"
    DRED = "#bd3944"
    GREEN = "#3ddbc4"
    BLUE = "#64a9ff"
    BORDER = "#243344"

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.WIN_W, self.WIN_H = 1040, 680
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{self.WIN_W}x{self.WIN_H}+{max(0,(sw-self.WIN_W)//2)}+{max(0,(sh-self.WIN_H)//2-20)}")
        self.root.resizable(False, False)
        self.root.configure(bg=self.BG, bd=0, highlightthickness=0)
        self.root.option_add("*Button.highlightThickness", 0)   # no focus outlines on flat buttons
        self.asset_dir = RESOURCE_DIR / "assets"
        self.icon_path = RESOURCE_DIR / "VibePause.ico"
        try:
            self.root.iconbitmap(default=str(self.icon_path))
        except Exception:
            pass
        fams = set(tkfont.families(self.root))
        self.fam = "Bahnschrift" if "Bahnschrift" in fams else "Segoe UI"   # DIN-style face ships with Windows 10/11
        self.assets = {}
        self.load_assets()

        self.q = queue.Queue()
        self.actions = DEFAULT_ACTIONS.copy()
        self.action_vars = {}
        self.action_button = {}
        self.action_stripe = {}
        self.delay = 0
        self.running = False
        self.startup = False
        self.close_to_tray = True
        self.settings_open = False
        self.tray_icon = None
        self.drag_x = 0
        self.drag_y = 0
        self._drag_hwnd = None
        self.load()
        self.controller = Controller(self)
        self.build()
        self.apply_windows_app_style()
        self.root.after(80, self.process)
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.create_tray()
        if "--startup" in sys.argv and TRAY_AVAILABLE:
            self.root.withdraw()   # launched by Windows at sign-in: start in the tray

    def F(self, size, bold=False):
        return (self.fam, size, "bold" if bold else "normal")

    def load(self):
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)
            source = CONFIG if CONFIG.exists() else LEGACY_CONFIG
            if source.exists():
                d = json.loads(source.read_text(encoding="utf-8"))
                for k in self.actions:
                    val = d.get("actions", {}).get(k)
                    if val in ("Play", "Pause", "None"):
                        self.actions[k] = val
                self.delay = int(d.get("delay", 0))
                self.startup = bool(d.get("startup", False))
                self.close_to_tray = bool(d.get("close_to_tray", True))
        except Exception:
            pass

    def save(self):
        APPDATA.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({
            "actions": self.actions,
            "delay": self.delay,
            "startup": self.startup,
            "close_to_tray": self.close_to_tray,
        }, indent=2), encoding="utf-8")

    def set_startup(self, enabled):
        self.startup = bool(enabled)
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE)
            if self.startup:
                if getattr(sys, "frozen", False):
                    command = f'"{sys.executable}" --startup'
                else:
                    script = str(Path(__file__).resolve())
                    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                    command = f'"{pythonw}" "{script}" --startup'
                winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            self.log_line("Startup setting error: " + str(e))
        self.save()
        self.startup_var.set(self.startup)

    def set_close_to_tray(self):
        self.close_to_tray = bool(self.close_tray_var.get())
        self.save()
        self.log_line("Close button: " + ("send to tray" if self.close_to_tray else "exit VibePause"))

    def load_assets(self):
        if not self.asset_dir.exists():
            return
        # Every UI icon is a PNG, explicitly resized. Source files are 64px and never shown at native size.
        sizes = {
            "play": 17, "pause": 17, "none": 14, "gear": 16,
            "status_play": 14, "status_pause": 14, "monitor": 16, "close": 16, "reset": 16, 
            "chrome": 20, "youtube_music": 20, "apple_music": 20, "spotify": 20,
            "vibepause_logo_16": 16, "vibepause_logo_20": 20, "vibepause_logo_24": 24, "vibepause_logo_32": 32,
            "check_on": 18, "check_off": 18,
            "ev_combat": 18, "ev_start": 18, "ev_shop": 18, "ev_finish": 18,
            "ev_lobby": 18, "ev_agent": 18, "ev_ult": 18,
        }
        for name, size in sizes.items():
            path = self.asset_dir / f"{name}.png"
            if path.exists():
                try:
                    im = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
                    self.assets[name] = ImageTk.PhotoImage(im)
                except Exception:
                    pass
        try:   # hero banner is already drawn at its exact display size
            self.assets["hero_bg"] = ImageTk.PhotoImage(Image.open(self.asset_dir / "hero_bg.png").convert("RGB"))
        except Exception:
            pass

    def img(self, name):
        return self.assets.get(name)

    def toplevel_hwnd(self):
        # Tk's winfo_id() is the inner client window. The real top-level window
        # (the one the taskbar / Alt+Tab / DWM see) is its parent.
        child = self.root.winfo_id()
        return user32.GetParent(child) or child

    def apply_windows_app_style(self):
        """Custom chrome without overrideredirect().

        The window stays a real, normal Win32 top-level window (so it keeps
        focus, a taskbar button and an Alt+Tab entry), but it has no caption,
        no sizing frame and no maximize box, so Windows draws no title bar and
        no border. Fixed size: no WS_THICKFRAME, no hit-testing, no resizing.
        """
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            hwnd = self.toplevel_hwnd()
            GWL_STYLE, GWL_EXSTYLE = -16, -20
            WS_POPUP, WS_SYSMENU, WS_MINIMIZEBOX = 0x80000000, 0x00080000, 0x00020000
            WS_CAPTION, WS_THICKFRAME, WS_MAXIMIZEBOX, WS_BORDER = 0x00C00000, 0x00040000, 0x00010000, 0x00800000
            WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = 0x00040000, 0x00000080
            style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            style |= WS_POPUP | WS_SYSMENU | WS_MINIMIZEBOX   # minimize box only so the taskbar button can minimize/restore
            style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_BORDER)
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)

            IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x0080
            self._hicon_big = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            self._hicon_small = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if self._hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, 1, self._hicon_big)
            if self._hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, 0, self._hicon_small)

            SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x2, 0x1, 0x4, 0x10, 0x20
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    # ---------- custom window ----------
    def start_drag(self, event):
        # Move the window with one cheap Win32 call per mouse event (no Tk geometry/relayout,
        # which caused the ghosting, and no native modal move loop inside a Tk callback).
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()
        self._drag_hwnd = None
        if os.name == "nt":
            try:
                self._drag_hwnd = self.toplevel_hwnd()
            except Exception:
                self._drag_hwnd = None

    def drag_window(self, event):
        x, y = event.x_root - self.drag_x, event.y_root - self.drag_y
        if self._drag_hwnd:
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
            user32.SetWindowPos(self._drag_hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        else:
            self.root.geometry(f"+{x}+{y}")

    def bind_drag(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self.start_drag)
            w.bind("<B1-Motion>", self.drag_window)

    def build(self):
        self.build_titlebar()
        self.body = tk.Frame(self.root, bg=self.BG, bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True)
        self.build_main()

    def build_titlebar(self):
        bar = tk.Frame(self.root, bg=self.TOP, height=56)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Frame(self.root, bg=self.RED, height=2).pack(fill="x")

        left = tk.Frame(bar, bg=self.TOP)
        left.pack(side="left", fill="y", padx=18)
        logo = tk.Label(left, image=self.img("vibepause_logo_32"), bg=self.TOP)
        logo.pack(side="left", padx=(0, 10))
        title = tk.Label(left, text="VIBEPAUSE", bg=self.TOP, fg=self.TEXT, font=self.F(14, True))
        title.pack(side="left")
        self.bind_drag(bar, left, logo, title)

        controls = tk.Frame(bar, bg=self.TOP)
        controls.pack(side="right", fill="y")
        self.close_tray_var = tk.BooleanVar(value=self.close_to_tray)
        self.startup_var = tk.BooleanVar(value=self.startup)
        ImgCheck(controls, "Run on Startup", self.startup_var, lambda: self.set_startup(self.startup_var.get()),
                 {True: self.img("check_on"), False: self.img("check_off")},
                 self.TOP, self.TEXT, self.F(10)).pack(side="left", padx=(0, 10), pady=16)
        self.settings_btn = tk.Button(controls, image=self.img("gear"), command=self.toggle_settings,
                                      bg=self.TOP, activebackground=self.PANEL3, relief="flat", bd=0,
                                      padx=12, pady=8, cursor="hand2")
        self.settings_btn.pack(side="left", fill="y")
        close = tk.Button(controls, image=self.img("close"), command=self.on_window_close,
                          bg=self.TOP, activebackground=self.DRED, relief="flat", bd=0,
                          padx=14, pady=8, cursor="hand2")
        close.pack(side="left", fill="y")
        close.bind("<Enter>", lambda e: close.config(bg=self.RED))
        close.bind("<Leave>", lambda e: close.config(bg=self.TOP))

    def panel(self, parent, title):
        outer = tk.Frame(parent, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        head = tk.Frame(outer, bg=self.PANEL)
        head.pack(fill="x", padx=12, pady=(10, 6))
        tk.Frame(head, bg=self.RED, width=4, height=13).pack(side="left")
        tk.Label(head, text=title, bg=self.PANEL, fg=self.TEXT, font=self.F(10, True)).pack(side="left", padx=(8, 0))
        body = tk.Frame(outer, bg=self.PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        return outer, body, head

    def build_main(self):
        for w in self.body.winfo_children():
            w.destroy()
        main = tk.Frame(self.body, bg=self.BG)
        main.pack(fill="both", expand=True, padx=24, pady=16)

        top = tk.Frame(main, bg=self.BG)
        top.pack(fill="x", pady=(0, 12))
        self.active_var = tk.BooleanVar(value=False)
        act = ImgCheck(top, "ACTIVE", self.active_var, self.toggle_active,
                       {True: self.img("check_on"), False: self.img("check_off")},
                       self.PANEL2, self.GREEN, self.F(11, True))
        act.config(padx=14, pady=7, highlightbackground=self.BORDER, highlightthickness=1)
        act.pack(side="left")
        self.monitor = tk.Label(top, image=self.img("monitor"), compound="left", text="  Ready to monitor Valorant",
                                bg=self.BG, fg=self.MUTED, font=self.F(11))
        self.monitor.pack(side="left", padx=16)
        tk.Label(top, text="GLOBAL WINDOWS MEDIA CONTROLS", bg=self.BG, fg="#5d6b7b", font=self.F(8, True)).pack(side="right")

        # Hero: banner image + live text drawn on a canvas
        hero = tk.Canvas(main, width=990, height=104, bg=self.PANEL, bd=0, highlightthickness=1,
                         highlightbackground=self.BORDER)
        hero.pack(fill="x", pady=(0, 12))
        if self.img("hero_bg"):
            hero.create_image(0, 0, image=self.img("hero_bg"), anchor="nw")
        hero.create_text(24, 14, text="CURRENT GAME STATE", fill=self.MUTED, font=self.F(9, True), anchor="nw")
        self.hero_event = hero.create_text(24, 32, text="WAITING FOR VALORANT", fill=self.TEXT, font=self.F(24, True), anchor="nw")
        self.hero_icon = hero.create_image(26, 86, image=self.img("status_play"), anchor="w")
        self.hero_music = hero.create_text(46, 86, text="Music is Playing", fill=self.GREEN, font=self.F(10, True), anchor="w")
        hero.create_text(960, 52, text="MEDIA\nCONTROL", fill="#ffffff", font=self.F(15, True), anchor="e", justify="right")
        self.hero = hero

        columns = tk.Frame(main, bg=self.BG)
        columns.pack(fill="both", expand=True)
        left_col = tk.Frame(columns, bg=self.BG)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 7))
        right_col = tk.Frame(columns, bg=self.BG, width=330)
        right_col.pack(side="right", fill="both", padx=(7, 0))
        right_col.pack_propagate(False)

        self.build_events(left_col)
        self.build_right(right_col)

        foot = tk.Frame(main, bg=self.BG)
        foot.pack(anchor="w", pady=(10, 0))
        for t in ("Made using ChatGPT by tanveer-exe",):
            tk.Label(foot, text=t, bg=self.BG, fg="#5d6b7b", font=self.F(8)).pack(side="left")
        tk.Frame(foot, bg=self.RED, width=4, height=4).pack(side="left", padx=8)
        tk.Label(foot, text="All rights reserved", bg=self.BG, fg="#5d6b7b", font=self.F(8)).pack(side="left")

    EVENT_ICON = {
        "On start combat phase": "ev_combat", "On game start": "ev_start", "On start shopping phase": "ev_shop",
        "On game finish": "ev_finish", "On back lobby": "ev_lobby", "On character select screen": "ev_agent",
        "On revive with ULT": "ev_ult",
    }

    def build_events(self, parent):
        outer, body, head = self.panel(parent, "MUSIC BEHAVIOUR")
        outer.pack(fill="both", expand=True)
        reset_btn = tk.Button(head, image=self.img("reset"), command=self.reset, bg=self.PANEL2,
                              activebackground=self.PANEL3, relief="flat", bd=0, padx=8, pady=5, cursor="hand2")
        reset_btn.pack(side="right")
        tk.Label(body, text="Click an action icon to cycle:  None  >  Play  >  Pause", bg=self.PANEL, fg=self.MUTED,
                 font=self.F(9)).pack(anchor="w", pady=(0, 8))

        for name, desc in EVENTS:
            row = tk.Frame(body, bg=self.PANEL2)
            row.pack(fill="x", pady=2)
            stripe = tk.Frame(row, bg=self.PANEL3, width=3)
            stripe.pack(side="left", fill="y")
            self.action_stripe[name] = stripe
            tk.Label(row, image=self.img(self.EVENT_ICON[name]), bg=self.PANEL2).pack(side="left", padx=(12, 8), pady=8)
            tk.Label(row, text=name, bg=self.PANEL2, fg=self.TEXT, font=self.F(10, True),
                     anchor="w").pack(side="left", padx=(0, 8))
            tk.Label(row, text=desc, bg=self.PANEL2, fg=self.MUTED, font=self.F(9),
                     anchor="w").pack(side="left", fill="x", expand=True)
            v = tk.StringVar(value=self.actions[name])
            self.action_vars[name] = v
            b = tk.Button(row, image=self.img("none"), width=28, height=24, bd=0, relief="flat",
                          command=lambda n=name, var=v: self.cycle_choice(n, var), cursor="hand2")
            b.pack(side="right", padx=9, pady=5)
            self.action_button[name] = b
            self.refresh_action(name, v)

    def refresh_action(self, event, var):
        value = var.get()
        b = self.action_button[event]
        icon_name = {"None": "none", "Play": "play", "Pause": "pause"}.get(value, "none")
        bg, stripe = {"Pause": ("#4a1d27", self.RED), "Play": ("#0f3b3a", self.GREEN)}.get(value, (self.PANEL3, self.PANEL3))
        b.config(image=self.img(icon_name), bg=bg, activebackground=bg)
        self.action_stripe[event].config(bg=stripe)

    def cycle_choice(self, event, var):
        order = ["None", "Play", "Pause"]
        value = order[(order.index(var.get()) + 1) % len(order)]
        var.set(value)
        self.actions[event] = value
        self.refresh_action(event, var)
        self.save()
        self.log_line(f"{event}: {value}")

    def build_right(self, parent):
        outer, controls, _ = self.panel(parent, "MEDIA CONTROLS")
        outer.pack(fill="x", pady=(0, 9))
        play_btn = tk.Button(controls, image=self.img("play"), text="  PLAY", compound="left", command=self.force_play,
                             bg="#0f3b3a", fg=self.GREEN, activebackground="#165252", activeforeground=self.GREEN,
                             relief="flat", bd=0, font=self.F(10, True), pady=8, cursor="hand2")
        play_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        pause_btn = tk.Button(controls, image=self.img("pause"), text="  PAUSE", compound="left", command=self.force_pause,
                              bg="#4a1d27", fg=self.RED, activebackground="#652634", activeforeground=self.RED,
                              relief="flat", bd=0, font=self.F(10, True), pady=8, cursor="hand2")
        pause_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        outer, apps, _ = self.panel(parent, "SUPPORTED MEDIA")
        outer.pack(fill="x", pady=(0, 9))
        tk.Label(apps, text="Controlled via Windows media session", bg=self.PANEL, fg=self.MUTED,
                 font=self.F(8)).pack(anchor="w", pady=(0, 8))
        grid = tk.Frame(apps, bg=self.PANEL)
        grid.pack(fill="x")
        labels = {"Google Chrome": "Chrome", "YouTube Music": "YouTube Music", "Apple Music": "Apple Music", "Spotify": "Spotify"}
        for i, name in enumerate(MEDIA_APPS):
            chip = tk.Frame(grid, bg=self.PANEL2, highlightbackground=self.BORDER, highlightthickness=1)
            chip.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            grid.columnconfigure(i % 2, weight=1)
            self.make_app_icon(chip, name).pack(side="left", padx=(8, 6), pady=6)
            tk.Label(chip, text=labels[name], bg=self.PANEL2, fg=self.TEXT, font=self.F(9, True)).pack(side="left")

        outer, body, head = self.panel(parent, "LIVE ACTIVITY")
        outer.pack(fill="both", expand=True)
        tk.Button(head, text="CLEAR", command=self.clear_log, bg=self.PANEL2, fg=self.TEXT, activebackground=self.PANEL3,
                  activeforeground=self.TEXT, relief="flat", bd=0, padx=8, pady=2, font=self.F(8, True),
                  cursor="hand2").pack(side="right")
        self.log = tk.Text(body, bg="#0b1119", fg="#b9c2d0", insertbackground="white", relief="flat", bd=0,
                           font=("Consolas", 8), wrap="word", height=4, highlightthickness=0)
        self.log.pack(fill="both", expand=True)

    def make_app_icon(self, parent, name):
        key = {"Google Chrome": "chrome", "YouTube Music": "youtube_music",
               "Apple Music": "apple_music", "Spotify": "spotify"}[name]
        return tk.Label(parent, image=self.img(key), bg=self.PANEL2)

    def toggle_settings(self):
        if self.settings_open:
            self.close_settings()
            return
        self.settings_open = True
        bg = self.TOP
        overlay = tk.Frame(self.root, bg=bg, highlightbackground=self.RED, highlightthickness=1)
        overlay.place(relx=1.0, x=-18, y=66, anchor="ne", width=330, height=262)
        self.settings_overlay = overlay
        tk.Label(overlay, text="SETTINGS", bg=bg, fg=self.TEXT, font=self.F(15, True)).pack(anchor="w", padx=18, pady=(16, 4))
        ImgCheck(overlay, "Close button sends to tray", self.close_tray_var, self.set_close_to_tray,
                 {True: self.img("check_on"), False: self.img("check_off")},
                 bg, self.TEXT, self.F(10)).pack(anchor="w", padx=18, pady=(2, 6))
        tk.Label(overlay, text="Unticked: the X button exits VibePause completely.",
                 bg=bg, fg=self.MUTED, font=self.F(9), wraplength=290, justify="left").pack(anchor="w", padx=18, pady=(0, 6))
        tk.Label(overlay, text="Event delay", bg=bg, fg=self.TEXT, font=self.F(10)).pack(anchor="w", padx=18, pady=(8, 4))
        row = tk.Frame(overlay, bg=bg)
        row.pack(fill="x", padx=18)
        self.delay_settings = tk.StringVar(value=str(self.delay))
        vcmd = (self.root.register(lambda v: v == "" or (v.isdigit() and len(v) <= 6)), "%P")
        entry = tk.Entry(row, textvariable=self.delay_settings, width=9, bg=self.PANEL2, fg=self.TEXT,
                         insertbackground="white", relief="flat", bd=0, validate="key", validatecommand=vcmd,
                         selectbackground="#2f6fd6", selectforeground="white", font=self.F(11),
                         highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.RED,
                         takefocus=True, state="normal", exportselection=False)
        entry.pack(side="left", ipady=5)
        # Tk's Entry maps Ctrl+A to "start of line" on Windows; make it Select All.
        def select_all(e):
            e.widget.select_range(0, "end"); e.widget.icursor("end"); return "break"
        entry.bind("<Control-a>", select_all)
        entry.bind("<Control-A>", select_all)
        entry.bind("<Return>", lambda e: self.save_settings_page())
        entry.bind("<Button-1>", lambda e: e.widget.focus_set())
        self.delay_entry = entry
        entry.after(50, lambda: (entry.focus_force(), entry.select_range(0, "end")))
        tk.Label(row, text="milliseconds", bg=bg, fg=self.MUTED, font=self.F(9)).pack(side="left", padx=8)
        tk.Button(overlay, text="SAVE SETTINGS", command=self.save_settings_page,
                  bg=self.RED, fg="white", activebackground="#ff6a77", activeforeground="white", relief="flat", bd=0,
                  padx=14, pady=7, font=self.F(9, True), cursor="hand2").pack(anchor="w", padx=18, pady=16)

    def close_settings(self):
        self.settings_open = False
        if hasattr(self, "settings_overlay"):
            self.settings_overlay.destroy()

    def reset(self):
        self.actions = DEFAULT_ACTIONS.copy()
        for k, v in self.action_vars.items():
            v.set(self.actions[k])
            self.refresh_action(k, v)
        self.delay = 0
        self.save()
        self.log_line("Reset to default")

    def save_settings_page(self):
        try:
            self.delay = max(0, int(self.delay_settings.get()))
        except Exception:
            self.delay = 0
        self.save()
        self.log_line("Settings saved")
        self.close_settings()

    def toggle_active(self):
        if self.active_var.get():
            self.actions = {k: v.get() for k, v in self.action_vars.items()}
            self.save()
            self.running = True
            self.controller.start(self.actions, self.delay)
            self.status_update(True)
            self.log_line("VibePause started")
        else:
            self.running = False
            self.controller.stop()
            self.status_update(False)
            self.log_line("VibePause stopped")

    def status_update(self, active):
        self.monitor.config(image=self.img("monitor"), text=("  Monitoring Valorant..." if active else "  Ready to monitor Valorant"),
                            fg=self.GREEN if active else self.MUTED)

    def set_music_status(self, playing):
        self.hero.itemconfig(self.hero_icon, image=self.img("status_play" if playing else "status_pause"))
        self.hero.itemconfig(self.hero_music, text="Music is Playing" if playing else "Music is Paused",
                             fill=self.GREEN if playing else "#ffd1d5")

    def force_play(self):
        self._manual(True)

    def force_pause(self):
        self._manual(False)

    def _manual(self, desired):
        def work():
            if self.controller.set_playing(desired):
                self.event("music", "Playing" if desired else "Paused")
                self.event("system", "Manual: " + ("Play" if desired else "Pause"))
        threading.Thread(target=work, daemon=True).start()   # keep the UI responsive

    def event(self, kind, value):
        self.q.put((kind, value))

    def process(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                now = time.strftime("%H:%M:%S")
                if kind == "cmd":
                    self.run_command(value)
                elif kind == "event":
                    event, action = value
                    self.hero.itemconfig(self.hero_event, text=event.upper())
                    self.log_line(f"{now}  {event}  [{action}]")
                elif kind == "music":
                    self.set_music_status(value == "Playing")
                    self.log_line(f"{now}  Music: {value}")
                else:
                    self.log_line(f"{now}  {value}")
        except queue.Empty:
            pass
        self.root.after(80, self.process)

    def log_line(self, text):
        if not hasattr(self, "log"):
            return
        self.log.insert("end", text + "\n")
        self.log.see("end")
        try:
            if int(self.log.index("end-1c").split(".")[0]) > 220:
                self.log.delete("1.0", "50.0")
        except Exception:
            pass

    def clear_log(self):
        if hasattr(self, "log"):
            self.log.delete("1.0", "end")

    def create_tray(self):
        if not TRAY_AVAILABLE or self.tray_icon:
            return
        try:
            img = Image.open(self.icon_path)
            img.load()
            img = img.convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (64, 64), (20, 20, 20, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Open VibePause", lambda icon, item: self.event("cmd", "open"), default=True),
            pystray.MenuItem("Start VibePause", lambda icon, item: self.event("cmd", "start")),
            pystray.MenuItem("Stop VibePause", lambda icon, item: self.event("cmd", "stop")),
            pystray.MenuItem("Exit VibePause", lambda icon, item: self.event("cmd", "exit")),
        )
        self.tray_icon = pystray.Icon("VibePause", img, APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def run_command(self, cmd):
        if cmd == "open":
            self._show()
        elif cmd == "start":
            if not self.active_var.get():
                self.active_var.set(True)
                self.toggle_active()
        elif cmd == "stop":
            if self.active_var.get():
                self.active_var.set(False)
                self.toggle_active()
        elif cmd == "exit":
            self.complete_exit()

    def hide_window(self):
        self.root.withdraw()   # removes the taskbar button and Alt+Tab entry; tray icon stays

    def _show(self):
        self.root.deiconify()
        self.apply_windows_app_style()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def on_window_close(self):
        # "Close to Tray" ticked: hide to the tray. Unticked: quit completely.
        if self.close_to_tray and TRAY_AVAILABLE:
            self.hide_window()
        else:
            self.complete_exit()

    def complete_exit(self):
        self.controller.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.save()
        try:
            self.root.destroy()
        finally:
            os._exit(0)   # make sure the process really ends

def setup_win32():
    """Declare ctypes signatures once so 64-bit handles are never truncated (a classic cause of native crashes)."""
    if os.name != "nt":
        return
    from ctypes import c_void_p, c_int, c_uint, c_size_t, c_ssize_t
    user32.GetParent.restype = c_void_p;            user32.GetParent.argtypes = [c_void_p]
    user32.GetWindowLongPtrW.restype = c_ssize_t;   user32.GetWindowLongPtrW.argtypes = [c_void_p, c_int]
    user32.SetWindowLongPtrW.restype = c_ssize_t;   user32.SetWindowLongPtrW.argtypes = [c_void_p, c_int, c_ssize_t]
    user32.SetWindowPos.restype = c_int;            user32.SetWindowPos.argtypes = [c_void_p, c_void_p, c_int, c_int, c_int, c_int, c_uint]
    user32.SendMessageW.restype = c_ssize_t;        user32.SendMessageW.argtypes = [c_void_p, c_uint, c_size_t, c_void_p]
    user32.LoadImageW.restype = c_void_p;           user32.LoadImageW.argtypes = [c_void_p, ctypes.c_wchar_p, c_uint, c_int, c_int, c_uint]

def set_windows_app_id():
    if os.name != "nt":
        return
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p("tanveer-exe.VibePause"))
    except Exception:
        pass

def already_running():
    if os.name != "nt":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        already_running.handle = kernel32.CreateMutexW(None, False, "VibePauseSingleInstanceMutex")  # kept for process lifetime
        return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False

if __name__ == "__main__":
    setup_win32()
    set_windows_app_id()
    if already_running():
        sys.exit(0)
    root = tk.Tk()
    App(root)
    root.mainloop()
