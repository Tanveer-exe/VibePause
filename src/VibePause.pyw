import os, sys, re, math, time, hashlib, ctypes, threading, queue, json, winreg, urllib.request, urllib.error, tempfile, subprocess
from pathlib import Path
import tkinter as tk
import ctypes.wintypes
from tkinter import font as tkfont
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageTk, ImageFilter, ImageChops

try:
    import pystray
    TRAY_AVAILABLE = True
except Exception:
    TRAY_AVAILABLE = False

APP_NAME = "VibePause"
APP_ID = "tanveer-exe.VibePause"
APP_VERSION = "0.1.3"
UPDATE_REPO = "Tanveer-exe/VibePause"
UPDATE_ASSET = "VibePause_Setup.exe"
# Bundled resources: PyInstaller extracts/places them under sys._MEIPASS.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APPDATA = Path(os.getenv("USERPROFILE", str(Path.home()))) / "Documents" / "VibePause"
LEGACY_APPDATA = Path(os.getenv("APPDATA", str(Path.home()))) / "VibePause"
CONFIG = APPDATA / "settings.json"
LEGACY_CONFIG = LEGACY_APPDATA / "settings.json"
LOG = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs" / "ShooterGame.log"
STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME = "VibePause"
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYUP = 0x0002
user32 = ctypes.windll.user32

# Give Windows a stable AppUserModelID so the taskbar uses VibePause's
# application identity and icon instead of a generic Tk/Python icon.
if os.name == "nt":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_ID))
    except Exception:
        pass

# Update checking constants
UPDATE_CHECK_INTERVAL = 4 * 60 * 60  # 4 hours in seconds
UPDATE_CHECK_TIMEOUT = 12  # seconds for GitHub API request

# Legal acceptance constants
LEGAL_ACCEPTANCE_KEY = "legal_accepted_v" + APP_VERSION.replace(".", "_")

EVENTS = [
    ("Combat Start", "A round becomes active"),
    ("Player Eliminated", "The local player dies during a round"),
    ("Match Started", "The match becomes active"),
    ("Buy Phase Started", "The buy phase opens"),
    ("Match Ended", "The match ends"),
    ("Returned to Lobby", "You return to the main menu"),
    ("Agent Selection", "Agent selection opens"),
    ("Ultimate Used", "You are revived by an ultimate"),
]
DEFAULT_ACTIONS = {
    "Combat Start": "Pause",
    "Player Eliminated": "Play",
    "Match Started": "Play",
    "Buy Phase Started": "Play",
    "Match Ended": "Play",
    "Returned to Lobby": "Play",
    "Agent Selection": "Play",
    "Ultimate Used": "Play",
}

# These are the four apps intentionally shown in the UI.
MEDIA_APPS = ["Google Chrome", "YouTube Music", "Apple Music", "Spotify"]

CALL_APP_KEYWORDS = (
    "discord", "teams", "msteams", "lync", "zoom", "skype", "slack", "webex", "whatsapp",
    "telegram", "signal", "viber", "facetime", "gotomeeting", "bluejeans", "ringcentral",
)
VALORANT_PROCESSES = ("valorant-win64-shipping.exe", "valorant.exe")


def read_settings():
    try:
        if not CONFIG.exists():
            return {}
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except ValueError:
        try:
            CONFIG.replace(CONFIG.with_name("settings.json.bad"))
        except OSError:
            pass
        return {}
    except OSError:
        return {}
    return data if isinstance(data, dict) else {}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]


def list_processes():
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
        if snap in (None, 0, ctypes.c_void_p(-1).value):
            return None
        procs = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                procs.append((int(entry.th32ProcessID), entry.szExeFile.lower()))
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        return procs
    except Exception:
        return None


def valorant_running():
    procs = list_processes()
    if procs is None:
        return True
    return any(name in VALORANT_PROCESSES for _, name in procs)


def is_call_app(source_id):
    sid = (source_id or "").lower()
    return any(k in sid for k in CALL_APP_KEYWORDS)


def close_quietly(holder):
    for f in holder:
        try:
            f.close()
        except OSError:
            pass

# ---------------------------------------------------------------------------
# Updater logic (pure functions, no UI). Outcomes are explicit so "no update"
# is never reported as a failure.
# ---------------------------------------------------------------------------
UPDATE_API = f"https://api.github.com/repos/{UPDATE_REPO}/releases?per_page=20"

class UpdateError(Exception):
    """A real problem (network, GitHub, missing installer) with a message safe to show the user."""

def version_tuple(value):
    """'v0.1.1' -> (0, 1, 1). Ignores a leading v and any suffix such as '-alpha'."""
    m = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)", str(value or ""))
    if not m:
        return None
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:   # 0.1.0 == 0.1
        parts.pop()
    return tuple(parts)

def pick_update(releases, current_version, asset_name=UPDATE_ASSET):
    """Decide what to do from a GitHub /releases list.

    Returns ("current", latest_version_str)
         or ("update", latest_version_str, download_url, size, digest)
    Raises UpdateError if a newer release exists but has no installer.
    Pre-releases are included (the project publishes alpha releases); drafts are not.
    """
    cur = version_tuple(current_version) or (0,)
    best, best_v = None, None
    for rel in releases or []:
        if rel.get("draft"):
            continue
        v = version_tuple(rel.get("tag_name"))
        if v is None:
            continue
        if best_v is None or v > best_v:
            best, best_v = rel, v
    if best is None:
        return ("current", str(current_version))     # nothing published yet -> nothing newer
    latest = str(best.get("tag_name", "")).lstrip("vV")
    if best_v <= cur:
        return ("current", latest)
    for asset in best.get("assets", []) or []:
        if asset.get("name") == asset_name and asset.get("browser_download_url"):
            return ("update", latest, asset["browser_download_url"], int(asset.get("size") or 0), asset.get("digest") or "")
    raise UpdateError(f"VibePause {latest} was published, but its installer ({asset_name}) is missing from the release.")

def fetch_releases(timeout=UPDATE_CHECK_TIMEOUT):
    """Download the release list from GitHub with friendly errors."""
    req = urllib.request.Request(UPDATE_API, headers={
        "User-Agent": f"VibePause/{APP_VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("GitHub returned 404 for the VibePause releases. The repository must be public for updates to work.")
        if e.code in (403, 429):
            raise UpdateError("GitHub is rate-limiting update checks right now. Try again in a few minutes.")
        raise UpdateError(f"GitHub returned an error (HTTP {e.code}). Try again later.")
    except urllib.error.URLError as e:
        raise UpdateError(f"Could not reach GitHub. Check your internet connection. ({e.reason})")
    except (TimeoutError, OSError) as e:
        raise UpdateError(f"Could not reach GitHub ({type(e).__name__}). Check your internet connection.")
    except ValueError:
        raise UpdateError("GitHub sent a reply VibePause could not read.")
    if not isinstance(data, list):
        raise UpdateError("Unexpected reply from GitHub.")
    return data

def verify_installer(path, digest):
    with open(path, "rb") as fh:
        if fh.read(2) != b"MZ":
            raise UpdateError("The downloaded file is not a Windows installer. Please try again.")
    if digest and digest.lower().startswith("sha256:"):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != digest.split(":", 1)[1].strip().lower():
            raise UpdateError("The downloaded installer failed its integrity check. Please try again.")

def cleanup_old_installers():
    try:
        for p in Path(tempfile.gettempdir()).glob("VibePause_Setup_*.exe"):
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


try:
    import asyncio
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _PlaybackStatus,
    )
    GSMTC_AVAILABLE = True
except Exception:
    GSMTC_AVAILABLE = False

def _session_id(session):
    try:
        return session.source_app_user_model_id
    except Exception:
        return ""

async def _gsmtc_set(desired):
    mgr = await _SessionManager.request_async()
    sessions = [s for s in mgr.get_sessions() if not is_call_app(_session_id(s))]
    if not sessions:
        return None

    for session in sessions:
        try:
            playing = session.get_playback_info().playback_status == _PlaybackStatus.PLAYING
            if desired and not playing:
                await session.try_play_async()
            elif not desired and playing:
                await session.try_pause_async()
        except Exception:
            continue

    return desired

class Controller:
    def __init__(self, ui):
        self.ui = ui
        self.stop_event = threading.Event()
        self.thread = None
        self.music_playing = True
        self.game_running = False
        self.last_process_check = 0.0
        self.in_match = False
        self.game_started = False
        self.character_select_seen = False
        self.round_active = False
        self.round_started_at = 0.0
        self.last_event = None
        self.last_event_time = 0.0
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
                    return False
            if desired != self.music_playing:
                self.toggle_media()
                self.music_playing = desired
            return True

    def apply_action(self, event, delay=None, stop_event=None):
        actions = self.ui.actions
        if delay is None:
            delay = self.ui.delay
        if not self.ui.active:
            return
        if not self.game_running:
            return

        now = time.monotonic()
        if event == self.last_event and (now - self.last_event_time) < 0.75:
            return
        self.last_event = event
        self.last_event_time = now

        action = actions.get(event, "None")
        self.ui.event("event", (event, action))
        if action == "None":
            return
        if delay:
            if stop_event is not None:
                if stop_event.wait(delay / 1000):
                    return
            else:
                time.sleep(delay / 1000)
            if not self.ui.active or not self.game_running:
                return
        if stop_event is not None and stop_event.is_set():
            return
        desired = action == "Play"
        if self.set_playing(desired):
            self.ui.event("music", "Playing" if desired else "Paused")

    def follow(self, stop_event, start_at_end):
        waited = False
        while not stop_event.is_set():
            try:
                f = open(LOG, "r", encoding="utf-8", errors="ignore")
            except FileNotFoundError:
                if not waited:
                    self.ui.event("system", "Waiting for Valorant...")
                    waited = True
                stop_event.wait(1.5)
                continue
            if start_at_end and not waited:
                f.seek(0, os.SEEK_END)
            self.ui.event("system", "Monitoring Valorant...")
            return f
        return None

    def start(self):
        if self.thread and self.thread.is_alive() and not self.stop_event.is_set():
            return
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(self.stop_event,), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def reset_match_state(self):
        self.in_match = False
        self.game_started = False
        self.character_select_seen = False
        self.round_active = False
        self.round_started_at = 0.0

    def log_replaced(self, f):
        try:
            if not LOG.exists():
                return True
            st = os.stat(LOG)
            if st.st_size < f.tell():
                return True
            cur = os.fstat(f.fileno())
            return bool(st.st_ino) and bool(cur.st_ino) and st.st_ino != cur.st_ino
        except OSError:
            return False

    def poll_game_process(self):
        now = time.monotonic()
        if now - self.last_process_check < 2.0:
            return
        self.last_process_check = now
        running = valorant_running()
        if running != self.game_running:
            self.game_running = running
            self.ui.event("valorant", running)
            if not running:
                self.reset_match_state()

    def run(self, stop_event):
        while not stop_event.is_set():
            holder = []
            try:
                self.monitor(stop_event, holder)
            except Exception as e:
                close_quietly(holder)
                self.ui.event("system", f"Monitor error, restarting: {type(e).__name__}: {e}")
                if stop_event.wait(2):
                    return
                continue
            close_quietly(holder)
            return

    def monitor(self, stop_event, holder):
        f = self.follow(stop_event, True)
        if not f:
            return
        holder[:] = [f]

        self.reset_match_state()
        self.game_running = valorant_running()
        self.last_process_check = time.monotonic()
        self.ui.event("valorant", self.game_running)
        self.apply_action("Returned to Lobby", delay=0, stop_event=stop_event)

        while not stop_event.is_set():
            self.poll_game_process()
            line = f.readline()
            if not line:
                if self.log_replaced(f):
                    f.close()
                    f = self.follow(stop_event, False)
                    if not f:
                        return
                    holder[:] = [f]
                stop_event.wait(.08)
                continue

            line = line.strip()
            low = line.lower()

            # --------------------------------------------------------------
            # High-confidence game-flow state changes from this log version.
            # --------------------------------------------------------------

            # --------------------------------------------------------------
            # Robust VALORANT game-flow detection.
            # A match can go directly from PostMatch/Pregame into another
            # match without returning to MainMenu, so reset match state from
            # both lobby AND post-match/pregame transitions.
            # --------------------------------------------------------------

            # Main menu / lobby. This is the cleanest full reset.
            if ("reconcile called with state: transitiontomainmenu and new state: mainmenu" in low
                    or "reconcile called with the current state: mainmenu" in low
                    or "broadcasting state changed to mainmenu" in low):
                was_in_match = self.in_match or self.game_started
                self.in_match = False
                self.game_started = False
                self.character_select_seen = False
                self.round_active = False
                self.round_started_at = 0.0
                if was_in_match:
                    self.apply_action("Match Ended", stop_event=stop_event)
                self.apply_action("Returned to Lobby", stop_event=stop_event)
                continue

            # Post-match is also a hard reset. This is important when the
            # player queues another match without a MainMenu transition.
            if (any(x in low for x in (
                    "waitingtopostmatch", "transitiontopostmatch", "transitioning from ingame to postmatch"))
                    or (any(x in low for x in ("postmatch", "postgame"))
                        and any(x in low for x in ("state", "transition", "broadcast")))):
                was_in_match = self.in_match or self.game_started
                self.in_match = False
                self.game_started = False
                self.character_select_seen = False
                self.round_active = False
                self.round_started_at = 0.0
                if was_in_match:
                    self.apply_action("Match Ended", stop_event=stop_event)
                continue

            # Character select / pregame starts a NEW match lifecycle. Reset
            # game_started here even if VALORANT skipped MainMenu after the
            # previous match.
            if ("characterselectpersistentlevel" in low
                    or "reconcile called with state: transitiontopregame and new state: pregame" in low
                    or "broadcasting state changed to pregame" in low):
                if not self.character_select_seen:
                    self.in_match = True
                    self.game_started = False
                    self.round_active = False
                    self.round_started_at = 0.0
                    self.character_select_seen = True
                    self.apply_action("Agent Selection", stop_event=stop_event)
                continue

            # The actual match becomes InGame after loading. Support several
            # equivalent log lines because Riot changes the surrounding text
            # between game versions.
            if ("reconcile called with state: transitiontoingame and new state: ingame" in low
                    or "transitioning from transitiontoingame to ingame" in low
                    or "broadcasting state changed to ingame" in low
                    or "reconcile called with the current state: ingame" in low):
                self.in_match = True
                if not self.game_started:
                    self.game_started = True
                    self.apply_action("Match Started", stop_event=stop_event)
                continue

            # Buy/shop phase. This can happen in later rounds too.
            if "opening wbp_screen_preroundshopcontainer_c" in low:
                self.in_match = True
                self.apply_action("Buy Phase Started", stop_event=stop_event)
                continue

            # Round/combat starts. If the game-start transition was missed,
            # recover the match state here instead of silently ignoring the
            # combat event.
            if "logshootergamestate" in low and "gameplay started at local time" in low:
                if not self.game_started:
                    self.in_match = True
                    self.game_started = True
                    self.apply_action("Match Started", stop_event=stop_event)
                self.round_active = True
                self.round_started_at = time.monotonic()
                self.apply_action("Combat Start", stop_event=stop_event)
                continue

            # Explicit round end is NOT game finish. The next round will emit
            # another Gameplay-started line.
            if any(x in low for x in (
                "ashootergamestate::onroundended",
                "logshootergamestate: onroundended",
                "onroundended"
            )):
                self.round_active = False
                continue

            # Death detection. Recent VALORANT logs can expose the local
            # player's state through `player=Me alive=0`. We only accept it
            # while a combat round is active and after a short grace period
            # following round start, because the same reconnect/spectate
            # marker can appear during initial map loading.
            if (self.in_match and self.round_active
                    and (time.monotonic() - self.round_started_at) >= 2.0
                    and "player=me alive=0" in low):
                self.round_active = False
                self.apply_action("Player Eliminated", stop_event=stop_event)
                continue

            # Revive/resurrection. Keep this deliberately narrow.
            if self.in_match and self.game_started and any(x in low for x in (
                "buff_resurrect_oneframedurationinvincible_c",
                "resurrected"
            )):
                self.apply_action("Ultimate Used", stop_event=stop_event)
                continue

def rounded_mask(size, radius, inset=0, scale=4):
    w, h = size
    m = Image.new("L", (w * scale, h * scale), 0)
    i = inset * scale
    ImageDraw.Draw(m).rounded_rectangle(
        (i, i, w * scale - 1 - i, h * scale - 1 - i), radius=max(0, radius - inset) * scale, fill=255)
    return m.resize((w, h), Image.Resampling.LANCZOS)


def glass_image(w, h, radius, fill=(255, 255, 255, 18), border=(255, 255, 255, 44), sheen=16):
    mask = rounded_mask((w, h), radius)
    inner = rounded_mask((w, h), radius, inset=1)
    body = Image.new("RGBA", (w, h), fill)
    if sheen:
        grad = Image.linear_gradient("L").resize((w, h)).point(lambda v: sheen * (255 - v) // 255)
        shine = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        shine.putalpha(grad)
        body = Image.alpha_composite(body, shine)
    body.putalpha(ImageChops.multiply(body.getchannel("A"), inner))
    ring = ImageChops.subtract(mask, inner).point(lambda v: v * border[3] // 255)
    edge = Image.new("RGBA", (w, h), border[:3] + (0,))
    edge.putalpha(ring)
    return Image.alpha_composite(body, edge)


def render_aurora(w, h):
    s = 4
    sw, sh = w // s, h // s
    base = Image.new("RGBA", (sw, sh), (9, 9, 26, 255))
    blobs = (
        (0.05, 0.00, 0.50, 0.65, (104, 66, 232, 200)),
        (0.58, -0.05, 0.30, 0.40, (214, 56, 124, 88)),
        (1.02, 1.02, 0.55, 0.65, (18, 196, 172, 175)),
        (-0.02, 1.00, 0.40, 0.42, (58, 92, 224, 85)),
    )
    for cx, cy, rx, ry, color in blobs:
        layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse(
            (int((cx - rx) * sw), int((cy - ry) * sh), int((cx + rx) * sw), int((cy + ry) * sh)), fill=color)
        base = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(sw * 0.11)))
    return base.resize((w, h), Image.Resampling.BICUBIC)


RING_STOPS = (
    (0.00, (122, 92, 255)), (0.28, (255, 78, 140)), (0.50, (196, 110, 168)),
    (0.62, (40, 214, 196)), (0.82, (60, 150, 240)), (1.00, (122, 92, 255)),
)


def ring_color(t):
    for (a, ca), (b, cb) in zip(RING_STOPS, RING_STOPS[1:]):
        if t <= b:
            f = (t - a) / (b - a)
            return tuple(int(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
    return RING_STOPS[-1][1]


def render_ring(d, thick):
    s = 3
    big = d * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    steps = 180
    for i in range(steps):
        draw.pieslice((0, 0, big - 1, big - 1), -90 + i * 360 / steps, -90 + (i + 1) * 360 / steps + 1,
                      fill=ring_color(i / steps) + (255,))
    outer = Image.new("L", (big, big), 0)
    ImageDraw.Draw(outer).ellipse((0, 0, big - 1, big - 1), fill=255)
    img.putalpha(outer)
    t = thick * s
    ImageDraw.Draw(img).ellipse((t, t, big - 1 - t, big - 1 - t), fill=(10, 10, 34, 255))
    return img.resize((d, d), Image.Resampling.LANCZOS)


def mix_color(a, b, f):
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))


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
    BG = "#0a0a1c"
    TOP = "#16162f"
    PANEL = "#14142b"
    PANEL2 = "#1e1e3d"
    PANEL3 = "#2a2a52"
    TEXT = "#f1efff"
    MUTED = "#9c9ac4"
    FAINT = "#6f6d98"
    RED = "#ff5d8f"
    DRED = "#c23d68"
    GREEN = "#2fe3c6"
    BLUE = "#7aa8ff"
    BORDER = "#33335e"

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
        self._window_icon = None
        try:
            # Keep a Tk icon reference as a fallback for the title bar/taskbar.
            icon_png = self.asset_dir / "vibepause_logo_32.png"
            if icon_png.exists() and TRAY_AVAILABLE:
                self._window_icon = ImageTk.PhotoImage(Image.open(icon_png).convert("RGBA"))
                self.root.iconphoto(True, self._window_icon)
            self.root.iconbitmap(default=str(self.icon_path))
        except Exception:
            pass
        fams = set(tkfont.families(self.root))
        self.fam = next((f for f in ("Segoe UI Variable Display", "Segoe UI", "Bahnschrift") if f in fams), "Segoe UI")
        self.assets = {}
        self.load_assets()

        self.q = queue.Queue()
        self.actions = DEFAULT_ACTIONS.copy()
        self.action_vars = {}
        self.action_button = {}
        self.action_stripe = {}
        self.cv = None
        self.imgs = []
        self.chip_imgs = {}
        self.log_lines = []
        self.log_items = []
        self.bar_items = []
        self.bars_active = True
        self._drag_ok = False
        self.delay = 0
        self.running = False
        self.startup = False
        self.close_to_tray = True
        self.settings_open = False
        self.tray_icon = None
        self.tray_popup = None
        self.tray_images = {}
        self._tray_state = None
        self.drag_x = 0
        self.drag_y = 0
        self._drag_hwnd = None
        # Auto-update / active state: must exist before build() draws the title bar
        self.auto_update_enabled = True
        self.auto_update_timer = None
        self.last_update_check = 0
        self.active = True  # VibePause is active by default
        self.legal_accepted = False
        self.valorant_running = False
        self.declined_update = None
        self.load_auto_update_settings()
        self.load()
        self.sync_startup_path()
        self.controller = Controller(self)
        self.build()
        self.apply_windows_app_style()
        self.root.after(80, self.process)
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.create_tray()
        self.start_quit_listener()
        if "--startup" in sys.argv and TRAY_AVAILABLE:
            self.root.withdraw()   # launched by Windows at sign-in: start in the tray

        self.check_legal_acceptance_on_startup()

    def F(self, size, bold=False):
        return (self.fam, size, "bold" if bold else "normal")

    def load(self):
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)

            # Migrate settings from old location to new location if needed
            if LEGACY_CONFIG.exists() and not CONFIG.exists():
                try:
                    legacy_data = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8"))
                    CONFIG.write_text(json.dumps(legacy_data, indent=2), encoding="utf-8")
                except Exception:
                    pass  # If migration fails, continue with empty settings

            # Load settings from current location
            d = read_settings()
            if d:
                for k in self.actions:
                    val = d.get("actions", {}).get(k)
                    if val in ("Play", "Pause", "None"):
                        self.actions[k] = val
                try:
                    self.delay = max(0, int(d.get("delay", 0)))
                except (TypeError, ValueError):
                    self.delay = 0
                self.startup = bool(d.get("startup", False))
                self.close_to_tray = bool(d.get("close_to_tray", True))

                # Handle legacy startup key migration
                if "legacy_startup_migrated" not in d:
                    # Try to read startup setting from registry and migrate to config
                    try:
                        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_READ)
                        value, _ = winreg.QueryValueEx(key, STARTUP_NAME)
                        winreg.CloseKey(key)
                        # If we found a startup setting, sync it with config
                        if self.startup:  # Only update if not already set from config
                            pass  # Startup setting will be handled by save() when needed
                    except FileNotFoundError:
                        pass  # No legacy startup setting
                    except Exception:
                        pass
                    # Mark that we've checked for legacy startup
                    d["legacy_startup_migrated"] = True
                    CONFIG.write_text(json.dumps(d, indent=2), encoding="utf-8")
        except Exception:
            pass

    def save(self):
        APPDATA.mkdir(parents=True, exist_ok=True)
        # Merge into the existing file instead of replacing it. Keys this method
        # does not own (legal acceptance, migration flags) must survive every
        # save, otherwise the legal popup comes back on each launch.
        data = read_settings()
        data.update({
            "actions": self.actions,
            "delay": self.delay,
            "startup": self.startup,
            "close_to_tray": self.close_to_tray,
            "auto_update_enabled": self.auto_update_enabled,
        })
        data.pop("selected_media_app", None)
        CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def check_legal_acceptance_on_startup(self):
        if self.check_legal_acceptance():
            self.begin_operation()
        else:
            self.show_legal_popup()

    def begin_operation(self):
        self.legal_accepted = True
        self.root.after(100, self.start_monitoring)
        if self.auto_update_enabled:
            self.start_auto_update_checker()
        threading.Thread(target=cleanup_old_installers, daemon=True).start()

    def sync_startup_path(self):
        if not self.startup or not getattr(sys, "frozen", False):
            return
        try:
            command = f'"{sys.executable}" --startup'
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            try:
                current, _ = winreg.QueryValueEx(key, STARTUP_NAME)
            except FileNotFoundError:
                current = None
            if current != command:
                winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, command)
            winreg.CloseKey(key)
        except Exception:
            pass

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

    def set_auto_update_enabled(self, enabled):
        """Handle auto-update enabled/disabled from settings checkbox"""
        self.auto_update_enabled = bool(enabled)
        self.save()
        if self.auto_update_enabled:
            self.start_auto_update_checker()
        else:
            self.stop_auto_update_checker()
        self.log_line(f"Automatic update checking: {'enabled' if self.auto_update_enabled else 'disabled'}")

    def set_active(self, active):
        """Handle active/inactive state from settings checkbox"""
        self.active = bool(active)
        self.save()
        if self.active:
            self.start_monitoring()
        else:
            self.stop_monitoring()
        self.log_line(f"VibePause: {'active' if self.active else 'inactive'}")

    def set_active_from_tray(self, value):
        self.active_var.set(value)
        self.set_active(value)
        self.update_tray()

    def load_auto_update_settings(self):
        """Load auto-update enabled setting from config"""
        self.auto_update_enabled = bool(read_settings().get("auto_update_enabled", True))

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
            "ev_lobby": 18, "ev_agent": 18, "ev_ult": 18, "ev_death": 18,
        }
        for name, size in sizes.items():
            path = self.asset_dir / f"{name}.png"
            if path.exists():
                try:
                    im = Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
                    self.assets[name] = ImageTk.PhotoImage(im)
                except Exception:
                    pass
        # Death icon is generated locally so no extra asset file is required.
        if "ev_death" not in self.assets:
            try:
                im = Image.new("RGBA", (18, 18), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                d.ellipse((2, 2, 16, 16), outline=(255, 70, 85, 255), width=2)
                d.line((6, 6, 12, 12), fill=(255, 70, 85, 255), width=2)
                d.line((12, 6, 6, 12), fill=(255, 70, 85, 255), width=2)
                self.assets["ev_death"] = ImageTk.PhotoImage(im)
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
            # Windows can refresh the non-client icon when the frame changes.
            if self._hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, 1, self._hicon_big)
            if self._hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, 0, self._hicon_small)
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

    LEFT_CARD = (28, 82, 328, 648)
    EVENTS_CARD = (350, 82, 1012, 456)
    MEDIA_CARD = (350, 472, 672, 648)
    ACTIVITY_CARD = (690, 472, 1012, 648)
    RING_CENTER = (178, 214)
    RING_SIZE = 190
    TILE_SIZE = (303, 68)
    CHIP_SIZE = (137, 36)
    LOG_ROWS = 5
    HEADER_H = 72

    def keep(self, photo):
        self.imgs.append(photo)
        return photo

    def photo(self, image):
        return self.keep(ImageTk.PhotoImage(image))

    def font_for(self, size, bold=False):
        return tkfont.Font(root=self.root, font=self.F(size, bold))

    def fit(self, text, width, font):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "...") > width:
            text = text[:-1]
        return text + "..."

    def tile_origin(self, i):
        return 372 + (i % 2) * 315, 130 + (i // 2) * 78

    def chip_origin(self, i):
        return 372 + (i % 2) * 147, 520 + (i // 2) * 46

    def make_clickable(self, tag, command, hover=None):
        cv = self.cv

        def enter(_e):
            cv.config(cursor="hand2")
            if hover:
                hover(True)

        def leave(_e):
            cv.config(cursor="")
            if hover:
                hover(False)

        cv.tag_bind(tag, "<Button-1>", lambda e: command())
        cv.tag_bind(tag, "<Enter>", enter)
        cv.tag_bind(tag, "<Leave>", leave)

    def canvas_press(self, event):
        self._drag_ok = event.y < self.HEADER_H and "nodrag" not in self.cv.gettags("current")
        if self._drag_ok:
            self.start_drag(event)

    def canvas_drag(self, event):
        if self._drag_ok:
            self.drag_window(event)

    def build(self):
        W, H = self.WIN_W, self.WIN_H
        self.cv = tk.Canvas(self.root, width=W, height=H, bg=self.BG, bd=0, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.hero = self.cv
        self.compose_scene(W, H)
        self.cv.create_image(0, 0, image=self.scene_photo, anchor="nw")
        self.build_chip_images()
        self.build_header()
        self.build_hero_card()
        self.build_events()
        self.build_media_card()
        self.build_activity_card()
        self.cv.create_text(W // 2, H - 17, text="Made using Claude by tanveer-exe   |   Open Source",
                            fill=self.FAINT, font=self.F(8))
        self.cv.bind("<ButtonPress-1>", self.canvas_press)
        self.cv.bind("<B1-Motion>", self.canvas_drag)
        self.animate_bars()

    def compose_scene(self, W, H):
        scene = render_aurora(W, H)

        def card(box, radius, **kw):
            x0, y0, x1, y1 = box
            scene.alpha_composite(glass_image(x1 - x0, y1 - y0, radius, **kw), (x0, y0))

        card(self.LEFT_CARD, 26, fill=(255, 255, 255, 16))
        card(self.EVENTS_CARD, 26, fill=(255, 255, 255, 16))
        card(self.MEDIA_CARD, 26, fill=(255, 255, 255, 12))
        card(self.ACTIVITY_CARD, 26, fill=(40, 210, 190, 30), border=(120, 255, 230, 52))
        tw, th = self.TILE_SIZE
        for i in range(len(EVENTS)):
            x, y = self.tile_origin(i)
            scene.alpha_composite(glass_image(tw, th, 16, fill=(255, 255, 255, 14), border=(255, 255, 255, 36)), (x, y))
        cw, ch = self.CHIP_SIZE
        for i in range(len(MEDIA_APPS)):
            x, y = self.chip_origin(i)
            scene.alpha_composite(glass_image(cw, ch, 12, fill=(255, 255, 255, 14), border=(255, 255, 255, 30)), (x, y))
        d = self.RING_SIZE
        cx, cy = self.RING_CENTER
        ring = render_ring(d, 5)
        pad = 46
        glow = Image.new("RGBA", (d + 2 * pad, d + 2 * pad), (0, 0, 0, 0))
        glow.alpha_composite(ring, (pad, pad))
        glow = glow.filter(ImageFilter.GaussianBlur(18))
        glow.putalpha(glow.getchannel("A").point(lambda v: v * 6 // 10))
        scene.alpha_composite(glow, (cx - d // 2 - pad, cy - d // 2 - pad))
        scene.alpha_composite(ring, (cx - d // 2, cy - d // 2))
        self.scene_photo = self.photo(scene.convert("RGB"))

    def build_chip_images(self):
        styles = {
            "None": ((255, 255, 255, 18), (255, 255, 255, 40), "none"),
            "Play": ((47, 227, 198, 52), (80, 240, 215, 120), "play"),
            "Pause": ((255, 93, 143, 62), (255, 125, 170, 125), "pause"),
        }
        self.chip_imgs = {}
        for state, (fill, border, icon) in styles.items():
            chip = glass_image(34, 34, 11, fill=fill, border=border, sheen=10)
            path = self.asset_dir / f"{icon}.png"
            if path.exists():
                try:
                    glyph = Image.open(path).convert("RGBA").resize((16, 16), Image.Resampling.LANCZOS)
                    chip.alpha_composite(glyph, (9, 9))
                except Exception:
                    pass
            self.chip_imgs[state] = self.photo(chip)

    def build_header(self):
        cv = self.cv
        cy = self.HEADER_H // 2
        logo = self.img("vibepause_logo_32")
        if logo:
            cv.create_image(30, cy, image=logo, anchor="w")
        cv.create_text(72, cy, text="VibePause", fill=self.TEXT, font=self.F(16, True), anchor="w")

        self.close_tray_var = tk.BooleanVar(value=self.close_to_tray)
        self.startup_var = tk.BooleanVar(value=self.startup)
        self.auto_update_var = tk.BooleanVar(value=self.auto_update_enabled)
        self.active_var = tk.BooleanVar(value=self.active)

        x = 1012
        x = self.round_button(x, cy, "close", self.img("close"), self.on_window_close, danger=True)
        x = self.round_button(x - 8, cy, "gear", self.img("gear"), self.toggle_settings)
        x = self.toggle_pill(x - 8, cy, "Auto-update", self.auto_update_var,
                             lambda: self.set_auto_update_enabled(self.auto_update_var.get()), "t_update")
        x = self.toggle_pill(x - 8, cy, "Run on startup", self.startup_var,
                             lambda: self.set_startup(self.startup_var.get()), "t_startup")
        x = self.toggle_pill(x - 8, cy, "Active", self.active_var,
                             lambda: self.set_active(self.active_var.get()), "t_active")
        self.build_status_pill(x - 8, cy)

    def round_button(self, right, cy, tag, icon, command, danger=False):
        d = 36
        x0 = right - d
        normal = self.photo(glass_image(d, d, d // 2, fill=(255, 255, 255, 18), border=(255, 255, 255, 44)))
        hot = (255, 93, 143, 90) if danger else (255, 255, 255, 40)
        hover_img = self.photo(glass_image(d, d, d // 2, fill=hot, border=(255, 255, 255, 70)))
        bg = self.cv.create_image(x0, cy, image=normal, anchor="w", tags=(tag, "nodrag"))
        if icon:
            self.cv.create_image(x0 + d // 2, cy, image=icon, tags=(tag, "nodrag"))
        self.make_clickable(tag, command, lambda on: self.cv.itemconfig(bg, image=hover_img if on else normal))
        return x0

    def toggle_pill(self, right, cy, label, var, command, tag):
        cv = self.cv
        font = self.F(10, True)
        w = self.font_for(10, True).measure(label) + 56
        h = 36
        x0 = right - w
        off = self.photo(glass_image(w, h, h // 2, fill=(255, 255, 255, 14), border=(255, 255, 255, 38)))
        on = self.photo(glass_image(w, h, h // 2, fill=(47, 227, 198, 40), border=(80, 240, 215, 125)))
        tags = (tag, "nodrag")
        bg = cv.create_image(x0, cy, image=off, anchor="w", tags=tags)
        dot = cv.create_oval(x0 + 17, cy - 5, x0 + 27, cy + 5, width=2, tags=tags)
        text = cv.create_text(x0 + 38, cy, text=label, anchor="w", font=font, tags=tags)

        def refresh(*_):
            state = bool(var.get())
            cv.itemconfig(bg, image=on if state else off)
            cv.itemconfig(dot, fill=self.GREEN if state else "", outline=self.GREEN if state else self.MUTED)
            cv.itemconfig(text, fill=self.TEXT if state else self.MUTED)

        def click():
            var.set(not var.get())
            command()

        var.trace_add("write", refresh)
        refresh()
        self.make_clickable(tag, click)
        return x0

    def build_status_pill(self, right, cy):
        cv = self.cv
        font = self.F(10, True)
        w = self.font_for(10, True).measure("VALORANT not running") + 56
        h = 36
        x0 = right - w
        bg = self.photo(glass_image(w, h, h // 2, fill=(255, 255, 255, 14), border=(255, 255, 255, 38)))
        cv.create_image(x0, cy, image=bg, anchor="w")
        self.status_dot = cv.create_oval(x0 + 17, cy - 5, x0 + 27, cy + 5, width=2, fill=self.MUTED, outline=self.MUTED)
        self.status_text = cv.create_text(x0 + 38, cy, text="Starting...", anchor="w", font=font, fill=self.MUTED)

    def build_hero_card(self):
        cv = self.cv
        cx, cy = self.RING_CENTER
        cv.create_text(cx, cy - 32, text="N O W", fill=self.GREEN, font=self.F(9, True))
        self.hero_event = cv.create_text(cx, cy + 8, text="Waiting for VALORANT", fill=self.TEXT,
                                         font=self.F(17), width=150, justify="center")
        self.bar_items = []
        base_y = 376
        for i in range(10):
            color = mix_color((47, 227, 198), (150, 96, 255), i / 9) if i < 5 else mix_color((150, 96, 255), (255, 93, 143), (i - 5) / 4)
            x = cx - 58.5 + i * 13
            self.bar_items.append(cv.create_line(x, base_y - 5, x, base_y + 5, width=6, capstyle="round", fill=color))
        self.bar_x = [cx - 58.5 + i * 13 for i in range(10)]
        self.bar_y = base_y
        self.hero_music = cv.create_text(cx, 424, text="Music is playing", fill=self.GREEN, font=self.F(10))

        for tag, label, icon, fill, border, color, x0, command in (
            ("b_play", "Play", "play", (47, 227, 198, 52), (80, 240, 215, 115), self.GREEN, 52, self.force_play),
            ("b_pause", "Pause", "pause", (255, 93, 143, 56), (255, 125, 170, 120), self.RED, 182, self.force_pause),
        ):
            w, h, y0 = 122, 48, 578
            normal = self.photo(glass_image(w, h, 18, fill=fill, border=border))
            hot = self.photo(glass_image(w, h, 18, fill=fill[:3] + (fill[3] + 36,), border=border))
            bg = cv.create_image(x0, y0, image=normal, anchor="nw", tags=(tag, "nodrag"))
            glyph = self.img(icon)
            if glyph:
                cv.create_image(x0 + 34, y0 + h // 2, image=glyph, tags=(tag, "nodrag"))
            cv.create_text(x0 + 52, y0 + h // 2, text=label, fill=color, font=self.F(11, True), anchor="w", tags=(tag, "nodrag"))
            self.make_clickable(tag, command, lambda on, b=bg, n=normal, ho=hot: cv.itemconfig(b, image=ho if on else n))

    def build_events(self):
        cv = self.cv
        cv.create_text(374, 108, text="Music behaviour", fill=self.TEXT, font=self.F(13, True), anchor="w")
        reset_icon = self.img("reset")
        d = 30
        rx = 1012 - 22 - d
        normal = self.photo(glass_image(d, d, d // 2, fill=(255, 255, 255, 18), border=(255, 255, 255, 44)))
        hot = self.photo(glass_image(d, d, d // 2, fill=(255, 255, 255, 44), border=(255, 255, 255, 70)))
        rbg = cv.create_image(rx, 108, image=normal, anchor="w", tags=("reset", "nodrag"))
        if reset_icon:
            cv.create_image(rx + d // 2, 108, image=reset_icon, tags=("reset", "nodrag"))
        self.make_clickable("reset", self.reset, lambda on: cv.itemconfig(rbg, image=hot if on else normal))

        tw, th = self.TILE_SIZE
        clear = self.photo(Image.new("RGBA", (tw, th), (0, 0, 0, 0)))
        name_font = self.font_for(11, True)
        desc_font = self.font_for(9)
        for i, (name, desc) in enumerate(EVENTS):
            x, y = self.tile_origin(i)
            tag = f"tile{i}"
            tags = (tag, "nodrag")
            cv.create_image(x, y, image=clear, anchor="nw", tags=tags)
            cv.create_text(x + 20, y + 25, text=name, fill=self.TEXT, font=name_font, anchor="w", tags=tags)
            cv.create_text(x + 20, y + 46, text=self.fit(desc, tw - 20 - 20 - 34 - 10, desc_font), fill=self.MUTED,
                           font=desc_font, anchor="w", tags=tags)
            v = tk.StringVar(value=self.actions[name])
            self.action_vars[name] = v
            self.action_button[name] = cv.create_image(x + tw - 20 - 34, y + 17, image=self.chip_imgs["None"],
                                                       anchor="nw", tags=tags)
            self.refresh_action(name, v)
            self.make_clickable(tag, lambda n=name, var=v: self.cycle_choice(n, var))

    def refresh_action(self, event, var):
        value = var.get()
        self.cv.itemconfig(self.action_button[event], image=self.chip_imgs.get(value, self.chip_imgs["None"]))

    def cycle_choice(self, event, var):
        order = ["None", "Play", "Pause"]
        value = order[(order.index(var.get()) + 1) % len(order)]
        var.set(value)
        self.actions[event] = value
        self.refresh_action(event, var)
        self.save()
        self.log_line(f"{event}: {value}")

    def build_media_card(self):
        cv = self.cv
        cv.create_text(374, 498, text="Supported media", fill=self.TEXT, font=self.F(13, True), anchor="w")
        keys = {"Google Chrome": ("chrome", "Chrome"), "YouTube Music": ("youtube_music", "YouTube Music"),
                "Apple Music": ("apple_music", "Apple Music"), "Spotify": ("spotify", "Spotify")}
        for i, name in enumerate(MEDIA_APPS):
            x, y = self.chip_origin(i)
            key, label = keys[name]
            icon = self.img(key)
            if icon:
                cv.create_image(x + 10, y + 18, image=icon, anchor="w")
            cv.create_text(x + 36, y + 18, text=label, fill=self.TEXT, font=self.F(9), anchor="w")
        cv.create_text(374, 618, text="Any Windows media app. Call apps are skipped.", fill=self.MUTED,
                       font=self.F(8), anchor="w", width=290)

    def build_activity_card(self):
        cv = self.cv
        cv.create_text(712, 498, text="Live activity", fill=self.TEXT, font=self.F(13, True), anchor="w")
        clear = cv.create_text(990, 498, text="Clear", fill=self.MUTED, font=self.F(9, True), anchor="e", tags=("clear", "nodrag"))
        self.make_clickable("clear", self.clear_log, lambda on: cv.itemconfig(clear, fill=self.TEXT if on else self.MUTED))
        self.log_font = self.font_for(9)
        self.log_items = [cv.create_text(712, 528 + i * 22, text="", anchor="w", font=self.F(9), fill=self.MUTED)
                          for i in range(self.LOG_ROWS)]

    def refresh_log(self):
        newest = self.log_lines[::-1][:self.LOG_ROWS]
        for i, item in enumerate(self.log_items):
            text = self.fit(newest[i], 282, self.log_font) if i < len(newest) else ""
            self.cv.itemconfig(item, text=text, fill=self.TEXT if i == 0 else "#b4b2d6")

    def animate_bars(self):
        try:
            if self.root.winfo_viewable():
                t = time.monotonic()
                for i, item in enumerate(self.bar_items):
                    if self.bars_active:
                        half = 5 + 22 * abs(math.sin(t * 2.3 + i * 0.9)) * (0.55 + 0.45 * abs(math.sin(t * 0.9 + i)))
                    else:
                        half = 3
                    self.cv.coords(item, self.bar_x[i], self.bar_y - half, self.bar_x[i], self.bar_y + half)
            self.root.after(90, self.animate_bars)
        except tk.TclError:
            pass

    def toggle_settings(self):
        if self.settings_open:
            self.close_settings()
            return
        self.settings_open = True
        bg = self.TOP
        overlay = tk.Frame(self.root, bg=bg, highlightbackground=self.RED, highlightthickness=1)
        overlay.place(relx=1.0, x=-28, y=70, anchor="ne", width=330, height=372)
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
        tk.Button(overlay, text="CHECK FOR UPDATES", command=self.check_for_updates,
                  bg=self.PANEL2, fg=self.TEXT, activebackground=self.PANEL3, activeforeground=self.TEXT,
                  relief="flat", bd=0, padx=14, pady=7, font=self.F(9, True), cursor="hand2").pack(anchor="w", padx=18, pady=(10, 6))
        self.update_status = tk.Label(overlay, text=f"VibePause {APP_VERSION}", bg=bg, fg=self.MUTED, font=self.F(8),
                                      wraplength=294, justify="left", anchor="nw", height=3)
        self.update_status.pack(anchor="w", fill="x", padx=18, pady=(0, 2))
        tk.Button(overlay, text="SAVE SETTINGS", command=self.save_settings_page,
                  bg=self.RED, fg="white", activebackground="#ff6a77", activeforeground="white", relief="flat", bd=0,
                  padx=14, pady=7, font=self.F(9, True), cursor="hand2", width=27, height=1).pack(anchor="w", padx=18, pady=(8, 14))

    def check_for_updates(self):
        """Settings > CHECK FOR UPDATES. Runs the network work off the UI thread."""
        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        self._set_update_status("Checking for updates...", self.BLUE)
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _set_update_status(self, text, color=None):
        if hasattr(self, "update_status"):
            try:
                self.update_status.config(text=text, fg=color or self.MUTED)
            except tk.TclError:
                pass   # settings panel was closed meanwhile

    def _check_for_updates_worker(self):
        try:
            result = pick_update(fetch_releases(), APP_VERSION)
            if result[0] == "update":
                self.event("update", ("available",) + result[1:])
            else:
                self.event("update", ("current", result[1]))
        except UpdateError as e:
            self.event("update", ("error", str(e)))
        except Exception as e:
            self.event("update", ("error", f"Update check failed ({type(e).__name__}: {e or 'no details'})."))

    def handle_update_event(self, value):
        kind = value[0]
        if kind == "current":
            self._update_busy = False
            msg = f"No update found. VibePause {APP_VERSION} is the latest version."
            self._set_update_status(msg, self.GREEN)
            self.log_line(msg)
        elif kind == "available":
            self._update_busy = False
            _, latest, url, size, digest = value
            self._set_update_status(f"Update found: VibePause {latest} is available.", self.GREEN)
            self.log_line(f"Update found: {latest} (current {APP_VERSION})")

            answer = messagebox.askyesno(
                "VibePause Update",
                f"VibePause {latest} is available.\n\n"
                f"Current version: {APP_VERSION}\n"
                f"New version: {latest}\n\n"
                "Download and install it now?",
                parent=self.root)

            if answer:
                self._update_busy = True
                self._set_update_status("Updating: downloading installer...", self.BLUE)
                threading.Thread(target=self._download_update_worker, args=(latest, url, size, digest), daemon=True).start()
            else:
                self.declined_update = latest

        elif kind == "progress":
            self._set_update_status(f"Updating: downloading installer... {value[1]}%", self.BLUE)
        elif kind == "downloaded":
            self._launch_update(value[1], value[2])
        elif kind == "error":
            self._update_busy = False
            self._set_update_status(value[1], self.RED)
            self.log_line(value[1])

    def background_update_checker(self):
        """Background thread for periodic update checks"""
        while getattr(self, '_auto_update_running', False):
            try:
                current_time = time.time()
                if current_time - self.last_update_check >= UPDATE_CHECK_INTERVAL:
                    self.last_update_check = current_time
                    update_available, version, url, size, digest = self._silent_check_for_updates()

                    if (update_available and version != self.declined_update
                            and not getattr(self, "_update_busy", False)):
                        self.root.after(0, lambda v=(version, url, size, digest): self._show_update_notification(v))

                # Wait interruptibly so shutdown wakes the checker immediately.
                if self._auto_update_stop.wait(60):
                    break
            except Exception as e:
                print(f"Background update check error: {e}")
                if self._auto_update_stop.wait(60):
                    break

    def _silent_check_for_updates(self):
        """Silently check for updates, return (update_available, version, url, size, digest)"""
        try:
            result = pick_update(fetch_releases(), APP_VERSION)
            if result[0] == "update":
                return True, result[1], result[2], result[3], result[4]
            else:
                return False, result[1], "", 0, ""
        except Exception:
            # Silently fail for background checks
            return False, "", "", 0, ""

    def _show_update_notification(self, version_info):
        """Show update notification when auto-update is enabled"""
        version, url, size, digest = version_info
        result = messagebox.askyesno(
            "Update Available",
            f"VibePause {version} is available!\n\n"
            "Would you like to download and install it now?",
            parent=self.root,
            icon='question'
        )

        if result:
            self._update_busy = True
            self._set_update_status("Updating: downloading installer...", self.BLUE)
            threading.Thread(target=self._download_update_worker, args=(version, url, size, digest), daemon=True).start()
        else:
            self.declined_update = version

    def _download_update_worker(self, latest, url, expected_size, digest=""):
        path = None
        try:
            fd, path = tempfile.mkstemp(prefix="VibePause_Setup_", suffix=".exe")
            os.close(fd)
            req = urllib.request.Request(url, headers={"User-Agent": f"VibePause/{APP_VERSION}"})
            done, last_pct = 0, -1
            with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as out:
                total = int(resp.headers.get("Content-Length") or expected_size or 0)
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = min(100, done * 100 // total)
                        if pct != last_pct and pct % 5 == 0:
                            last_pct = pct
                            self.event("update", ("progress", pct))
            if expected_size and done != expected_size:
                raise UpdateError("The downloaded installer is incomplete. Please try again.")
            verify_installer(path, digest)
            self.event("update", ("downloaded", path, latest))
        except UpdateError as e:
            self.discard_file(path)
            self.event("update", ("error", str(e)))
        except Exception as e:
            self.discard_file(path)
            self.event("update", ("error", f"Update download failed ({type(e).__name__}: {e or 'no details'})."))

    def discard_file(self, path):
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def _launch_update(self, path, latest):
        try:
            self.log_line(f"Starting the VibePause {latest} installer")
            DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP = 0x00000008, 0x00000200
            subprocess.Popen([path, "/UPDATE"], close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            self.complete_exit()   # stop monitoring, remove tray icon, quit so the installer can replace files
        except Exception as e:
            self._update_busy = False
            self._set_update_status(f"Could not start the installer: {e}", self.RED)

    def start_auto_update_checker(self):
        """Start the background update checking thread"""
        if not self.legal_accepted:
            return
        if not getattr(self, '_auto_update_running', False):
            self._auto_update_running = True
            if not hasattr(self, "_auto_update_stop"):
                self._auto_update_stop = threading.Event()
            self._auto_update_stop.clear()
            self.auto_update_thread = threading.Thread(
                target=self.background_update_checker,
                daemon=True
            )
            self.auto_update_thread.start()

    def stop_auto_update_checker(self):
        """Stop the background update checking thread"""
        self._auto_update_running = False
        # Wake the checker immediately instead of waiting for its 60-second
        # polling sleep. This keeps application shutdown from appearing frozen.
        if hasattr(self, "_auto_update_stop"):
            self._auto_update_stop.set()
        # Do not block the Tk UI waiting for a network thread. The checker is
        # daemonized and will exit on its own after the stop event is signaled.

    def check_legal_acceptance(self):
        """Check if legal documents have been accepted for current version"""
        return bool(read_settings().get(LEGAL_ACCEPTANCE_KEY, False))

    def save_legal_acceptance(self):
        """Save that legal documents have been accepted for current version"""
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)
            # Load existing settings
            d = read_settings()
            # Update legal acceptance
            d[LEGAL_ACCEPTANCE_KEY] = True
            # Save back
            CONFIG.write_text(json.dumps(d, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Failed to save legal acceptance: {e}")

    def show_legal_popup(self):
        """Show terms and conditions and privacy policy popup"""
        W, H = 640, 560
        legal_window = tk.Toplevel(self.root)
        legal_window.title("Legal Agreement")
        legal_window.configure(bg=self.BG)
        legal_window.resizable(False, False)
        legal_window.protocol("WM_DELETE_WINDOW", self.complete_exit)
        if self.root.winfo_viewable():
            legal_window.transient(self.root)

        # Center over the main window (fall back to the screen if it is hidden)
        legal_window.update_idletasks()
        if self.root.winfo_viewable():
            x = self.root.winfo_x() + (self.root.winfo_width() - W) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - H) // 2
        else:
            x = (legal_window.winfo_screenwidth() - W) // 2
            y = (legal_window.winfo_screenheight() - H) // 2
        legal_window.geometry(f"{W}x{H}+{max(0, x)}+{max(0, y)}")

        # Layout order matters with pack: the button bar is packed FIRST on the
        # bottom edge so the text area can never squeeze it out of the window.
        button_frame = tk.Frame(legal_window, bg=self.BG)
        button_frame.pack(side="bottom", fill="x", padx=20, pady=(8, 20))

        tab_frame = tk.Frame(legal_window, bg=self.BG)
        tab_frame.pack(side="top", fill="x", padx=20, pady=(20, 10))

        content_frame = tk.Frame(legal_window, bg="#0d0d24")
        content_frame.pack(side="top", fill="both", expand=True, padx=20)

        scrollbar = tk.Scrollbar(content_frame, orient="vertical", relief="flat", bd=0)
        scrollbar.pack(side="right", fill="y")

        # ONE text widget that is re-filled on every tab switch. (Destroying and
        # re-creating the container is what left the tabs blank before.)
        text_widget = tk.Text(content_frame, bg="#0d0d24", fg="#c8c6e6",
                              insertbackground="white", relief="flat", bd=0,
                              highlightthickness=0, font=self.F(10), wrap="word",
                              padx=14, pady=12, spacing1=2, spacing3=4,
                              yscrollcommand=scrollbar.set, cursor="arrow")
        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_widget.yview)

        text_widget.tag_configure("h1", font=self.F(15, True), foreground="#ece8e1",
                                  spacing1=4, spacing3=10)
        text_widget.tag_configure("h2", font=self.F(12, True), foreground="#ece8e1",
                                  spacing1=14, spacing3=4)
        text_widget.tag_configure("h3", font=self.F(10, True), foreground="#ece8e1",
                                  spacing1=10, spacing3=2)
        text_widget.tag_configure("bullet", lmargin1=14, lmargin2=28)

        def read_doc(filename, title):
            try:
                path = RESOURCE_DIR / filename
                if path.exists():
                    return path.read_text(encoding="utf-8")
                return f"# {title}\n\n{title} file not found."
            except Exception:
                return f"# {title}\n\nError loading {title.lower()}."

        def render_markdown(raw):
            for line in raw.replace("\r\n", "\n").split("\n"):
                line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
                line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
                line = line.replace("`", "")
                stripped = line.lstrip()
                if stripped.startswith("### "):
                    text_widget.insert("end", stripped[4:] + "\n", "h3")
                elif stripped.startswith("## "):
                    text_widget.insert("end", stripped[3:] + "\n", "h2")
                elif stripped.startswith("# "):
                    text_widget.insert("end", stripped[2:] + "\n", "h1")
                elif stripped.startswith(("- ", "* ")):
                    text_widget.insert("end", "•  " + stripped[2:] + "\n", "bullet")
                else:
                    text_widget.insert("end", line + "\n")

        docs = {
            "terms": ("TERMS_AND_CONDITIONS.md", "Terms and Conditions"),
            "privacy": ("PRIVACY_POLICY.md", "Privacy Policy"),
        }
        tabs = {}

        def show_doc(which):
            filename, title = docs[which]
            for key, label in tabs.items():
                active = key == which
                label.config(bg=self.PANEL2 if active else self.PANEL,
                             fg=self.TEXT if active else self.MUTED)
            text_widget.config(state="normal")
            text_widget.delete("1.0", "end")
            render_markdown(read_doc(filename, title))
            text_widget.config(state="disabled")
            text_widget.yview_moveto(0)

        for key, caption in (("terms", "Terms and Conditions"), ("privacy", "Privacy Policy")):
            label = tk.Label(tab_frame, text=caption, bg=self.PANEL, fg=self.MUTED,
                             font=self.F(10, True), padx=20, pady=10, cursor="hand2")
            label.pack(side="left", padx=(0, 8))
            label.bind("<Button-1>", lambda e, k=key: show_doc(k))
            tabs[key] = label

        show_doc("terms")

        def accept_legal():
            self.save_legal_acceptance()
            try:
                legal_window.grab_release()
            except tk.TclError:
                pass
            legal_window.destroy()
            self.begin_operation()

        accept_btn = tk.Button(button_frame, text="I Agree", command=accept_legal,
                               bg=self.RED, fg="white", activebackground="#ff6a77",
                               activeforeground="white", relief="flat", bd=0,
                               font=self.F(11, True), padx=40, pady=12, cursor="hand2")
        accept_btn.pack(side="right")

        def finish_setup():
            try:
                legal_window.lift()
                legal_window.grab_set()  # Modal behavior
                accept_btn.focus_set()
            except tk.TclError:
                pass

        legal_window.after(100, finish_setup)

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

    def start_monitoring(self):
        if not self.legal_accepted:
            return
        self.actions = {k: v.get() for k, v in self.action_vars.items()}
        self.save()
        self.running = True
        self.controller.start()
        self.status_update(True)
        self.log_line("VibePause started automatically")

    def stop_monitoring(self):
        self.running = False
        self.controller.stop()
        self.status_update(False)
        self.log_line("VibePause stopped")

    def status_update(self, active=None):
        if not self.running:
            text, color = "Stopped", self.MUTED
        elif self.valorant_running:
            text, color = "VALORANT running", self.GREEN
        else:
            text, color = "VALORANT not running", self.MUTED
        self.cv.itemconfig(self.status_text, text=text, fill=color)
        self.cv.itemconfig(self.status_dot, fill=color, outline=color)
        self.update_tray()

    def set_music_status(self, playing):
        self.bars_active = bool(playing)
        self.cv.itemconfig(self.hero_music, text="Music is playing" if playing else "Music is paused",
                           fill=self.GREEN if playing else "#ffb3c8")

    def force_play(self):
        self._manual(True)

    def force_pause(self):
        self._manual(False)

    def _manual(self, desired):
        if not self.legal_accepted:
            return
        def work():
            if self.controller.set_playing(desired):
                self.event("music", "Playing" if desired else "Paused")
                self.event("system", "Manual: " + ("Play" if desired else "Pause"))
        threading.Thread(target=work, daemon=True).start()   # keep the UI responsive

    def start_quit_listener(self):
        """Lets a newly launched copy ask this one to exit cleanly (tray icon
        removed, settings saved) instead of being force-killed."""
        if os.name != "nt":
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateEventW.restype = ctypes.c_void_p
            kernel32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
            kernel32.WaitForSingleObject.restype = ctypes.c_uint32
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            handle = kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)   # manual-reset, unsignaled
        except Exception:
            return
        if not handle:
            return

        def watch():
            while True:
                if kernel32.WaitForSingleObject(handle, 500) == 0:   # WAIT_OBJECT_0: another copy asked us to quit
                    self.event("cmd", "exit")
                    return

        threading.Thread(target=watch, daemon=True).start()

    def event(self, kind, value):
        self.q.put((kind, value))

    def handle_queue_item(self, kind, value):
        now = time.strftime("%H:%M:%S")
        if kind == "cmd":
            self.run_command(value)
        elif kind == "update":
            self.handle_update_event(value)
        elif kind == "event":
            event, action = value
            self.hero.itemconfig(self.hero_event, text=event)
            self.log_line(f"{now}  {event}  [{action}]")
        elif kind == "music":
            self.set_music_status(value == "Playing")
            self.log_line(f"{now}  Music: {value}")
        elif kind == "valorant":
            self.valorant_running = bool(value)
            self.status_update()
        else:
            self.log_line(f"{now}  {value}")

    def process(self):
        try:
            while True:
                try:
                    kind, value = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self.handle_queue_item(kind, value)
                except Exception as e:
                    try:
                        self.log_line(f"Internal error ({kind}): {type(e).__name__}: {e}")
                    except Exception:
                        pass
        finally:
            self.root.after(80, self.process)

    def log_line(self, text):
        if not self.log_items:
            return
        self.log_lines.append(text)
        del self.log_lines[:-200]
        self.refresh_log()

    def clear_log(self):
        self.log_lines.clear()
        if self.log_items:
            self.refresh_log()

    def create_tray(self):
        if not TRAY_AVAILABLE or self.tray_icon:
            return
        try:
            img = Image.open(self.icon_path)
            img.load()
            img = img.convert("RGBA")
        except Exception:
            img = Image.new("RGBA", (64, 64), (20, 20, 20, 255))
        self.tray_images = {True: img, False: img.convert("LA").convert("RGBA")}
        menu = pystray.Menu(
            pystray.MenuItem("Open VibePause", lambda icon, item: self.event("cmd", "open"), default=True),
            pystray.MenuItem("Active", lambda icon, item: self.event("cmd", "toggle_active"),
                             checked=lambda item: self.active),
            pystray.MenuItem("Exit VibePause", lambda icon, item: self.event("cmd", "exit")),
        )
        app = self

        class GlassIcon(pystray.Icon):
            def _on_notify(self, wparam, lparam):
                if lparam == 0x0205:
                    try:
                        point = ctypes.wintypes.POINT()
                        user32.GetCursorPos(ctypes.byref(point))
                        app.event("cmd", ("tray_menu", point.x, point.y))
                        return
                    except Exception:
                        pass
                super()._on_notify(wparam, lparam)

        self._tray_state = None
        self.tray_icon = GlassIcon("VibePause", self.tray_images[True], APP_NAME, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def update_tray(self):
        icon = self.tray_icon
        if not icon:
            return
        if not self.running:
            label = "Stopped"
        elif self.valorant_running:
            label = "VALORANT running"
        else:
            label = "Waiting for VALORANT"
        state = (self.running, label)
        if state == self._tray_state:
            return
        self._tray_state = state
        try:
            icon.title = f"{APP_NAME}: {label}"
            icon.icon = self.tray_images[bool(self.running)]
            icon.update_menu()
        except Exception:
            pass

    def close_tray_popup(self):
        popup = getattr(self, "tray_popup", None)
        self.tray_popup = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

    def show_tray_popup(self, px, py):
        self.close_tray_popup()
        W, H = 252, 200
        win = tk.Toplevel(self.root)
        self.tray_popup = win
        win.overrideredirect(True)
        key = "#010101"
        win.configure(bg=key)
        try:
            win.attributes("-topmost", True)
            win.attributes("-transparentcolor", key)
        except tk.TclError:
            pass
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = min(max(8, px - W // 2), sw - W - 8)
        y = py - H - 14 if py > sh // 2 else py + 14
        y = min(max(8, y), sh - H - 8)
        win.geometry(f"{W}x{H}+{x}+{y}")

        panel = render_aurora(W, H)
        panel.alpha_composite(glass_image(W, H, 20, fill=(255, 255, 255, 22), border=(255, 255, 255, 64)))
        flat = Image.new("RGB", (W, H), (1, 1, 1))
        flat.paste(panel.convert("RGB"), (0, 0), rounded_mask((W, H), 20))
        photos = [ImageTk.PhotoImage(flat)]
        cv = tk.Canvas(win, width=W, height=H, bg=key, bd=0, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=photos[0], anchor="nw")

        logo = self.img("vibepause_logo_24")
        if logo:
            cv.create_image(18, 30, image=logo, anchor="w")
        cv.create_text(50, 24, text="VibePause", fill=self.TEXT, font=self.F(12, True), anchor="w")
        if not self.running:
            label, color = "Stopped", self.MUTED
        elif self.valorant_running:
            label, color = "VALORANT running", self.GREEN
        else:
            label, color = "Waiting for VALORANT", self.MUTED
        cv.create_oval(50, 40, 58, 48, fill=color, outline=color)
        cv.create_text(65, 44, text=label, fill=color, font=self.F(9), anchor="w")
        cv.create_line(16, 62, W - 16, 62, fill="#4a4a7a")

        hover = ImageTk.PhotoImage(glass_image(W - 16, 38, 11, fill=(255, 255, 255, 34), border=(255, 255, 255, 0), sheen=0))
        switch = {}
        for state in (True, False):
            sw_img = glass_image(40, 22, 11, fill=(47, 227, 198, 90) if state else (255, 255, 255, 26),
                                 border=(80, 240, 215, 160) if state else (255, 255, 255, 60), sheen=0)
            knob = Image.new("RGBA", (40 * 4, 22 * 4), (0, 0, 0, 0))
            kx = 40 * 4 - 18 * 4 - 2 * 4 if state else 4 * 4
            ImageDraw.Draw(knob).ellipse((kx, 4 * 4 - 0, kx + 14 * 4, 4 * 4 + 14 * 4), fill=(255, 255, 255, 245) if state else (200, 198, 230, 235))
            sw_img.alpha_composite(knob.resize((40, 22), Image.Resampling.LANCZOS))
            switch[state] = ImageTk.PhotoImage(sw_img)
        photos += [hover] + list(switch.values())

        def row(i, text, command, with_switch=False):
            top = 70 + i * 42
            tag = f"row{i}"
            shade = cv.create_image(8, top, image=hover, anchor="nw", state="hidden", tags=(tag,))
            cv.create_text(24, top + 19, text=text, fill=self.TEXT, font=self.F(11), anchor="w", tags=(tag,))
            toggle = None
            if with_switch:
                toggle = cv.create_image(W - 24, top + 19, image=switch[bool(self.active)], anchor="e", tags=(tag,))
            cv.create_image(8, top, image=self.photo_clear(W - 16, 38), anchor="nw", tags=(tag,))
            cv.tag_bind(tag, "<Enter>", lambda e: (cv.itemconfig(shade, state="normal"), cv.config(cursor="hand2")))
            cv.tag_bind(tag, "<Leave>", lambda e: (cv.itemconfig(shade, state="hidden"), cv.config(cursor="")))
            cv.tag_bind(tag, "<Button-1>", lambda e: (self.close_tray_popup(), command()))
            return toggle

        row(0, "Active", lambda: self.set_active_from_tray(not self.active), with_switch=True)
        row(1, "Open VibePause", self._show)
        row(2, "Exit VibePause", self.complete_exit)
        cv.photos = photos

        state = {"entered": False, "outside": 0, "age": 0}

        def watch():
            if getattr(self, "tray_popup", None) is not win:
                return
            try:
                mx, my = win.winfo_pointerxy()
                inside = win.winfo_rootx() <= mx <= win.winfo_rootx() + W and win.winfo_rooty() <= my <= win.winfo_rooty() + H
                state["age"] += 1
                if inside:
                    state["entered"] = True
                    state["outside"] = 0
                elif state["entered"] or state["age"] > 10:
                    state["outside"] += 1
                if state["outside"] >= 3:
                    self.close_tray_popup()
                    return
                win.after(300, watch)
            except tk.TclError:
                pass

        win.bind("<Escape>", lambda e: self.close_tray_popup())
        win.bind("<FocusOut>", lambda e: self.close_tray_popup())
        win.update_idletasks()
        if os.name == "nt":
            try:
                handle = user32.GetParent(win.winfo_id()) or win.winfo_id()
                user32.SetForegroundWindow(handle)
            except Exception:
                pass
        try:
            win.focus_force()
        except tk.TclError:
            pass
        win.after(300, watch)

    def photo_clear(self, w, h):
        cache = self.__dict__.setdefault("_clear_cache", {})
        if (w, h) not in cache:
            cache[(w, h)] = self.photo(Image.new("RGBA", (w, h), (0, 0, 0, 0)))
        return cache[(w, h)]

    def run_command(self, cmd):
        if isinstance(cmd, tuple):
            if cmd[0] == "tray_menu":
                self.show_tray_popup(cmd[1], cmd[2])
            return
        if cmd == "open":
            self._show()
        elif cmd == "toggle_active":
            self.set_active_from_tray(not self.active)
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
        # Shutdown must be fast and must never wait on network I/O from the UI.
        self.controller.stop()
        self.stop_auto_update_checker()

        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

        try:
            self.save()
        except Exception:
            pass

        try:
            self.root.destroy()
        finally:
            # Background workers are daemon threads, so the process can exit
            # immediately without making the window appear frozen.
            os._exit(0)

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
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p("tanveer-exe.VibePause"))
    except Exception:
        pass

INSTANCE_MUTEX_NAME = "VibePauseSingleInstanceMutex"   # also used by the installer (AppMutex)
QUIT_EVENT_NAME = "VibePauseQuitEvent"
ERROR_ALREADY_EXISTS = 183

def already_running():
    """Try to become the single running instance.

    Returns False and keeps the mutex for the life of the process when we are
    the only copy. Returns True when another copy already owns it.
    """
    if os.name != "nt":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            # Release our handle right away. Holding it would keep the mutex
            # alive after the old copy exits, so a retry could never succeed.
            if handle:
                kernel32.CloseHandle(handle)
            return True
        already_running.handle = handle   # kept for process lifetime
        return False
    except Exception:
        return False

def find_other_instance_pids():
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return []
    exe_name = os.path.basename(sys.executable).lower()
    return [pid for pid, name in (list_processes() or []) if name == exe_name and pid != os.getpid()]

def close_tray_windows(pid):
    try:
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        found = []

        def callback(hwnd, lparam):
            owner = ctypes.c_uint32()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if "SystemTrayIcon" in buf.value:
                    found.append(hwnd)
            return 1

        user32.EnumWindows(callback_type(callback), 0)
        for hwnd in found:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
    except Exception:
        pass

def terminate_process(pid):
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)   # TERMINATE | SYNCHRONIZE
        if handle:
            kernel32.TerminateProcess(handle, 0)
            kernel32.WaitForSingleObject(handle, 3000)
            kernel32.CloseHandle(handle)
    except Exception:
        pass

def close_running_instance(timeout=6.0):
    """Close the other VibePause and take over as the single instance.

    Asks it to exit cleanly first (so it removes its tray icon and saves
    settings). If that does not work within the timeout, for example an older
    version that does not listen for the request, it is ended forcefully.
    Returns True once this process owns the instance mutex.
    """
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenEventW.restype = ctypes.c_void_p
        kernel32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.SetEvent.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        event = kernel32.OpenEventW(0x0002, False, QUIT_EVENT_NAME)   # EVENT_MODIFY_STATE
        if event:
            kernel32.SetEvent(event)
            kernel32.CloseHandle(event)
    except Exception:
        pass

    def wait_for_release(seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if not already_running():      # also acquires the mutex for us
                return True
            time.sleep(0.2)
        return False

    if wait_for_release(timeout):
        return True
    pids = find_other_instance_pids()
    for pid in pids:
        close_tray_windows(pid)
    if pids:
        time.sleep(1.0)
    for pid in pids:
        terminate_process(pid)
    return wait_for_release(4.0)

def message_box(text, flags):
    # MB_SETFOREGROUND | MB_TOPMOST so the prompt is not hidden behind other windows
    return ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags | 0x10000 | 0x40000)

def handle_existing_instance():
    """Called when another copy is running. Returns True if we should carry on starting up."""
    if "--startup" in sys.argv:
        return False   # launched by Windows at sign-in while already running: nothing to ask
    answer = message_box(
        "VibePause is already running.\n\n"
        "Click OK to close the running copy and open a new one,\n"
        "or Cancel to leave it as it is.",
        0x1 | 0x20)    # MB_OKCANCEL | MB_ICONQUESTION
    if answer != 1:    # IDOK
        return False
    if close_running_instance():
        return True
    message_box(
        "VibePause could not close the running copy.\n\n"
        "Right-click its tray icon, choose Exit VibePause, then try again.",
        0x0 | 0x30)    # MB_OK | MB_ICONWARNING
    return False

if __name__ == "__main__":
    setup_win32()
    set_windows_app_id()
    if already_running() and not handle_existing_instance():
        sys.exit(0)
    root = tk.Tk()
    if "--startup" in sys.argv and TRAY_AVAILABLE:
        root.withdraw()
    App(root)
    root.mainloop()