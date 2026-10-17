import os, sys, re, math, time, hashlib, ctypes, threading, queue, json, winreg, urllib.request, urllib.error, tempfile, subprocess, platform, stat
from pathlib import Path
import tkinter as tk
import ctypes.wintypes
from tkinter import font as tkfont
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageTk, ImageFilter, ImageChops, ImageGrab
from io import BytesIO

try:
    import pystray
    TRAY_AVAILABLE = True
except Exception:
    TRAY_AVAILABLE = False

APP_NAME = "VibePause"
APP_ID = "tanveer-exe.VibePause"
APP_VERSION = "1.0.2"
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
UPDATE_RETRY_DELAY = 5 * 60  # seconds before retrying a failed background check
UPDATE_CHECK_TIMEOUT = 12  # seconds for GitHub API request

# Legal acceptance constants
LEGAL_DOCS = ("TERMS_AND_CONDITIONS.md", "PRIVACY_POLICY.md")
LEGAL_ACCEPTANCE_KEY = "legal_accepted_hash"


def legal_fingerprint():
    """Short hash of the bundled Terms and Privacy Policy text.

    Acceptance is stored as this hash, so editing either document automatically asks users to
    accept again, with no version number to remember to raise. Line endings and surrounding
    whitespace are normalised so Git/Windows newline differences never trigger a prompt."""
    h = hashlib.sha256()
    for name in LEGAL_DOCS:
        try:
            text = (RESOURCE_DIR / name).read_text(encoding="utf-8-sig")
        except OSError:
            text = ""
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        h.update(name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    return h.hexdigest()[:16]

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

# ---------------------------------------------------------------------------
# Game status. One state value (App.game_state) drives both the status pill on the music card and
# the Game status card, so they can never disagree. Every state below comes from something the
# Controller really detects: the VALORANT process, or one of the EVENTS above.
# key -> (sentence on the Game status card, short text on the music card's pill)
# ---------------------------------------------------------------------------
GAME_STATES = {
    "waiting": ("Waiting for VALORANT", "Waiting for VALORANT"),
    "off": ("VibePause is off", "VibePause is off"),
    "open": ("VALORANT is open", "VALORANT is open"),
    "menu": ("In the menu", "In the menu"),
    "agent_select": ("Agent select", "In match"),
    "match_started": ("Match started", "In match"),
    "buy": ("Buy phase", "In match"),
    "round": ("Round started", "In match"),
    "dead": ("You died", "In match"),
    "revived": ("You were revived", "In match"),
    "match_ended": ("Match ended", "Match ended"),
}
EVENT_STATES = {
    "Agent Selection": "agent_select", "Match Started": "match_started", "Buy Phase Started": "buy",
    "Combat Start": "round", "Player Eliminated": "dead", "Ultimate Used": "revived",
    "Match Ended": "match_ended", "Returned to Lobby": "menu",
}
GAME_HISTORY_TEXT = {"open": "VALORANT opened", "waiting": "VALORANT closed"}   # process start / exit

# ---------------------------------------------------------------------------
# Volume mode and translations
# ---------------------------------------------------------------------------
MODE_PAUSE, MODE_VOLUME = "pause", "volume"
# Volume mode mirrors the pause-mode defaults: quiet while a round is live, full volume otherwise.
DEFAULT_VOLUMES = {name: (20 if DEFAULT_ACTIONS[name] == "Pause" else 100) for name, _ in EVENTS}


def clean_volume(value, default):
    """0-100, or None meaning 'leave the volume alone for this event'."""
    if value is None:
        return None
    if isinstance(value, bool):
        return default
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


# (code, name shown in the language menu). Each non-English language is a plain JSON file in
# the "lang" folder; any text missing from a file simply stays in English.
LANGUAGES = (
    ("en", "English"), ("es", "Español"), ("pt-BR", "Português (Brasil)"), ("fr", "Français"),
    ("de", "Deutsch"), ("it", "Italiano"), ("pl", "Polski"), ("tr", "Türkçe"), ("ru", "Русский"),
    ("ja", "日本語"), ("ko", "한국어"), ("zh-CN", "简体中文"), ("zh-TW", "繁體中文"),
    ("id", "Bahasa Indonesia"), ("vi", "Tiếng Việt"),
)
LANG_CODES = {code for code, _ in LANGUAGES}
_translations = {}


def set_language(code):
    global _translations
    _translations = {}
    if code and code != "en" and code in LANG_CODES:
        try:
            data = json.loads((RESOURCE_DIR / "lang" / f"{code}.json").read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                _translations = {str(k): v for k, v in data.items() if isinstance(v, str) and v}
        except (OSError, ValueError):
            _translations = {}


def tr(text):
    """Translate a UI string into the chosen language (English text is the lookup key)."""
    return _translations.get(text, text)


# These are the four apps intentionally shown in the UI.
MEDIA_APPS = ["Google Chrome", "YouTube Music", "Apple Music", "Spotify"]

CALL_APP_KEYWORDS = (
    "discord", "teams", "msteams", "lync", "zoom", "skype", "slack", "webex", "whatsapp",
    "telegram", "signal", "viber", "facetime", "gotomeeting", "bluejeans", "ringcentral",
)
VALORANT_PROCESSES = ("valorant-win64-shipping.exe", "valorant.exe")


def open_log(path):
    if os.name != "nt":
        return open(path, "r", encoding="utf-8", errors="ignore")
    import msvcrt
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        error = ctypes.get_last_error()
        if error in (2, 3):
            raise FileNotFoundError(str(path))
        raise OSError(error, "Could not open the VALORANT log", str(path))
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY), "r", encoding="utf-8", errors="ignore")


def _parse_settings_bytes(raw):
    """Decode and parse settings leniently. Returns a dict, or None if it is truly unreadable.
    Tolerates a UTF-8 BOM, UTF-16 / ANSI files written by other tools, NUL padding, and
    stray text after the JSON object."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "cp1252")
    for enc in encodings:
        try:
            text = raw.decode(enc).replace("\x00", "").strip()
        except UnicodeDecodeError:
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            continue
        return data if isinstance(data, dict) else None
    return None


def read_settings():
    try:
        if not CONFIG.exists():
            return {}
        raw = CONFIG.read_bytes()
    except OSError:
        return {}
    data = _parse_settings_bytes(raw)
    if data is not None:
        return data
    if not raw.strip():
        return {}
    # Genuinely unreadable. Keep a copy for recovery without overwriting an earlier backup, and
    # record why, so settings never vanish silently.
    try:
        bad = CONFIG.with_name("settings.json.bad")
        if bad.exists():
            bad = CONFIG.with_name(f"settings.json.{time.strftime('%Y%m%d-%H%M%S')}.bad")
        CONFIG.replace(bad)
        write_error_log(f"settings.json could not be read and was moved to {bad.name} "
                        f"({len(raw)} bytes, starts with {raw[:12]!r}). Defaults were loaded.")
    except OSError:
        pass
    return {}


MAX_DELAY_MS = 99999


def clean_delay(value):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(MAX_DELAY_MS, number))


def clean_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    return default


def set_settings_writable(writable):
    try:
        if CONFIG.exists():
            os.chmod(CONFIG, stat.S_IREAD | stat.S_IWRITE if writable else stat.S_IREAD)
    except OSError:
        pass


def write_settings(data):
    tmp = CONFIG.with_name("settings.json.tmp")
    set_settings_writable(True)
    try:
        APPDATA.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    finally:
        set_settings_writable(False)


ERROR_LOG_COOLDOWN = 6 * 60 * 60  # an identical error is written at most once per 6 hours
_error_log_seen = {}              # error text -> [time last written, repeats suppressed since]
_error_log_lock = threading.Lock()


def write_error_log(text, cooldown=ERROR_LOG_COOLDOWN):
    """Append to error.log. Identical errors inside the cooldown window are suppressed so a
    persistent failure (e.g. a 404 on the update check) cannot spam the file.
    Returns True if the entry was written, False if it was suppressed as a repeat."""
    now = time.time()
    note = ""
    with _error_log_lock:
        entry = _error_log_seen.get(text)
        if entry and now - entry[0] < cooldown:
            entry[1] += 1
            return False
        if entry and entry[1]:
            note = f"(the same error occurred {entry[1]} more time(s) since the last entry)\n"
        if len(_error_log_seen) > 200:
            _error_log_seen.clear()
        _error_log_seen[text] = [now, 0]
    try:
        APPDATA.mkdir(parents=True, exist_ok=True)
        path = APPDATA / "error.log"
        if path.exists() and path.stat().st_size > 200000:
            path.replace(APPDATA / "error.old.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {APP_VERSION}\n{note}{text}\n\n")
    except OSError:
        pass
    return True


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
        return None
    return any(name in VALORANT_PROCESSES for _, name in procs)


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_uint32)]


MONITOR_DEFAULTTONEAREST = 2


def valorant_monitor_rect():
    """The Windows monitor VALORANT's window is currently on, as a (left, top, right, bottom)
    tuple in virtual-screen coordinates (can include negative values for a monitor to the
    left of or above the primary one). None if it can't be determined (VALORANT not running,
    its window not found, or any Win32 call fails), so callers can fall back to the primary
    monitor instead of silently screenshotting the wrong one on a multi-monitor setup."""
    if os.name != "nt":
        return None
    try:
        procs = list_processes()
        if not procs:
            return None
        valorant_pids = {pid for pid, name in procs if name in VALORANT_PROCESSES}
        if not valorant_pids:
            return None

        HWND, LPARAM, BOOL, DWORD = ctypes.wintypes.HWND, ctypes.wintypes.LPARAM, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD
        WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HWND, LPARAM)
        user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
        user32.EnumWindows.restype = BOOL
        user32.IsWindowVisible.argtypes = [HWND]
        user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
        user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(_RECT)]
        user32.MonitorFromRect.argtypes = [ctypes.POINTER(_RECT), ctypes.c_uint32]
        user32.MonitorFromRect.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]

        best = []   # [(area, _RECT)], largest matching top-level window wins
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in valorant_pids:
                return True
            rect = _RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w <= 0 or h <= 0:
                return True
            if not best or w * h > best[0][0]:
                best[:] = [(w * h, rect)]
            return True

        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        if not best:
            return None

        hmon = user32.MonitorFromRect(ctypes.byref(best[0][1]), MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        m = info.rcMonitor
        return (m.left, m.top, m.right, m.bottom)
    except Exception:
        return None


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

NOTES_LIMIT = 900   # characters of release notes shown in the update prompt

def clean_release_notes(body, limit=NOTES_LIMIT):
    """Turn a GitHub release body (Markdown) into short plain text for a message box."""
    lines = []
    for raw in str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)           # [text](url) -> text
        line = re.sub(r"\s+by @\S+ in https?://\S+", "", line)           # auto-generated credit suffix
        line = re.sub(r"\*\*|__|`", "", line).strip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        if re.match(r"^(full changelog\b|https?://)", line, re.I):
            continue
        if re.match(r"^[-*+]\s+", line):
            line = "\u2022 " + re.sub(r"^[-*+]\s+", "", line)
        if line or (lines and lines[-1]):
            lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0].rstrip() + "\n\u2026 (more on the GitHub release page)"
    return text

def collect_notes(releases, cur_tuple, limit=NOTES_LIMIT):
    """Notes for every published release newer than the installed one (newest first, max 3)."""
    newer = []
    for rel in releases or []:
        v = version_tuple(rel.get("tag_name"))
        if rel.get("draft") or v is None or v <= cur_tuple:
            continue
        newer.append((v, rel))
    newer.sort(key=lambda item: item[0], reverse=True)
    parts = []
    for _, rel in newer[:3]:
        body = clean_release_notes(rel.get("body"), limit)
        if body:
            name = str(rel.get("tag_name", "")).lstrip("vV")
            parts.append(body if len(newer) == 1 else f"{name}:\n{body}")
    text = "\n\n".join(parts)
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0].rstrip() + "\n\u2026 (more on the GitHub release page)"
    return text

def pick_update(releases, current_version, asset_name=UPDATE_ASSET):
    """Decide what to do from a GitHub /releases list.

    Returns ("current", latest_version_str)
         or ("update", latest_version_str, download_url, size, digest, release_notes)
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
            return ("update", latest, asset["browser_download_url"], int(asset.get("size") or 0),
                    asset.get("digest") or "", collect_notes(releases, cur))
    raise UpdateError(f"VibePause {latest} was published, but its installer ({asset_name}) is missing from the release.")

def fetch_releases(timeout=UPDATE_CHECK_TIMEOUT):
    """Download the release list from GitHub with friendly errors."""
    req = urllib.request.Request(UPDATE_API, headers={
        "User-Agent": f"VibePause/{APP_VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        write_error_log(f"Update check: HTTP {e.code}")
        raise UpdateError("Can't check for updates right now. Try again later.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        write_error_log(f"Update check: {type(e).__name__}: {e}")
        raise UpdateError("Can't check for updates. Check your internet connection.")
    except ValueError:
        raise UpdateError("Can't check for updates right now. Try again later.")
    if not isinstance(data, list):
        raise UpdateError("Can't check for updates right now. Try again later.")
    return data

def check_for_update(current_version):
    """Checks GitHub releases for a newer version."""
    return pick_update(fetch_releases(), current_version)

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

# Optional Windows built-in OCR. The OCR language pack for English must be installed.
# Imports are lazy so the app can still start if OCR components are unavailable.
try:
    from winrt.windows.media.ocr import OcrEngine as _OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder as _BitmapDecoder
    from winrt.windows.storage.streams import InMemoryRandomAccessStream as _InMemoryRandomAccessStream
    from winrt.windows.storage.streams import DataWriter as _DataWriter
    WINDOWS_OCR_AVAILABLE = True
except Exception:
    WINDOWS_OCR_AVAILABLE = False

# Album art for the now-playing card. Separate from the OCR import so either can be missing.
try:
    from winrt.windows.storage.streams import DataReader as _DataReader
    THUMBNAIL_AVAILABLE = True
except Exception:
    THUMBNAIL_AVAILABLE = False

def _session_id(session):
    try:
        return session.source_app_user_model_id
    except Exception:
        return ""

_manager_cache = None

async def _get_manager():
    global _manager_cache
    if _manager_cache is None:
        _manager_cache = await _SessionManager.request_async()
    return _manager_cache

_paused_ids = set()

async def _gsmtc_set(desired):
    mgr = await _get_manager()
    sessions = [s for s in mgr.get_sessions() if not is_call_app(_session_id(s))]
    if not sessions:
        return None

    targets = sessions
    if desired:
        targets = [s for s in sessions if _session_id(s) in _paused_ids]
        if not targets:
            try:
                current = mgr.get_current_session()
            except Exception:
                current = None
            targets = [current] if current is not None and not is_call_app(_session_id(current)) else sessions

    async def one(session):
        sid = _session_id(session)
        try:
            playing = session.get_playback_info().playback_status == _PlaybackStatus.PLAYING
            if desired:
                if playing:
                    _paused_ids.discard(sid)
                    return None
                ok = bool(await session.try_play_async())
                if ok:
                    _paused_ids.discard(sid)
                return ok
            if not playing:
                return None
            ok = bool(await session.try_pause_async())
            if ok:
                _paused_ids.add(sid)
            return ok
        except Exception:
            return False

    results = await asyncio.gather(*(one(s) for s in targets))
    attempted = [r for r in results if r is not None]
    if attempted and not any(attempted):
        return "failed"
    return desired


class MediaLoop:
    def __init__(self):
        self.loop = None
        self.guard = threading.Lock()

    def start(self):
        with self.guard:
            if self.loop is not None:
                return
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, daemon=True).start()
            self.loop = loop

    def run(self, coro, timeout=8):
        global _manager_cache
        self.start()
        try:
            return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)
        except Exception:
            _manager_cache = None
            raise


MEDIA = MediaLoop()

# ---------------------------------------------------------------------------
# Now playing: title, artist, artwork and transport controls of the active media session.
# Everything below runs on the media loop thread (or the watcher thread that calls it); the UI only
# ever receives plain data through App.event(). Call apps are skipped by is_call_app(), exactly as
# for auto-pause, so the card never shows or controls them.
# ---------------------------------------------------------------------------
NP_POLL = 2.5                   # seconds between polls; media events wake the watcher sooner
NP_WAKE = threading.Event()     # set by media events (any thread) and by the UI after a button press
_np_subs = {}                   # session id -> (session, [(remove_function, token), ...])
_np_mgr = None
_np_resub = [False]


def _np_wake(*_):
    NP_WAKE.set()


def _np_sessions_changed(*_):
    _np_resub[0] = True
    NP_WAKE.set()


def _np_unsubscribe_all():
    for _session, tokens in list(_np_subs.values()):
        for remove, token in tokens:
            try:
                remove(token)
            except Exception:
                pass
    _np_subs.clear()


def _np_subscribe(mgr, sessions):
    """Wake the watcher when a session's track or playback state changes. Polling stays on as a
    fallback, so a missed event only delays the card by a couple of seconds."""
    global _np_mgr
    if _np_mgr is not mgr:
        _np_subs.clear()            # tokens of a previous manager are dead
        try:
            mgr.add_sessions_changed(_np_sessions_changed)
            mgr.add_current_session_changed(_np_wake)
        except Exception as e:
            write_error_log(f"Now playing: manager events unavailable: {type(e).__name__}: {e}")
        _np_mgr = mgr
    if _np_resub[0]:
        _np_resub[0] = False
        _np_unsubscribe_all()
    live = set()
    for session in sessions:
        sid = _session_id(session)
        live.add(sid)
        if sid in _np_subs:
            continue
        tokens = []
        for name in ("media_properties_changed", "playback_info_changed"):
            try:
                tokens.append((getattr(session, "remove_" + name), getattr(session, "add_" + name)(_np_wake)))
            except Exception as e:
                write_error_log(f"Now playing: could not subscribe to {name}: {type(e).__name__}: {e}")
        _np_subs[sid] = (session, tokens)
    for sid in [k for k in _np_subs if k not in live]:
        for remove, token in _np_subs.pop(sid)[1]:
            try:
                remove(token)
            except Exception:
                pass


def _np_pick(mgr):
    """The session the card shows and controls: a playing one, else the system's current one."""
    sessions = [s for s in mgr.get_sessions() if not is_call_app(_session_id(s))]
    if not sessions:
        return None, sessions
    for session in sessions:
        try:
            if session.get_playback_info().playback_status == _PlaybackStatus.PLAYING:
                return session, sessions
        except Exception:
            pass
    try:
        current = mgr.get_current_session()
    except Exception:
        current = None
    if current is not None and not is_call_app(_session_id(current)):
        return current, sessions
    return sessions[0], sessions


async def _np_read_thumbnail(props):
    ref = props.thumbnail
    if ref is None:
        return None
    stream = await ref.open_read_async()
    try:
        size = int(stream.size)
        if size <= 0 or size > 8 * 1024 * 1024:
            return None
        reader = _DataReader(stream)
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        return Image.open(BytesIO(bytes(buf))).convert("RGBA")
    finally:
        try:
            stream.close()
        except Exception:
            pass


async def _np_snapshot(want_thumb):
    """Plain-data picture of what is playing. want_thumb(key) says whether to (re)read the artwork."""
    mgr = await _get_manager()
    session, sessions = _np_pick(mgr)
    _np_subscribe(mgr, sessions)
    if session is None:
        return {"status": "none"}
    info = session.get_playback_info()
    status = info.playback_status
    status = "playing" if status == _PlaybackStatus.PLAYING else "paused" if status == _PlaybackStatus.PAUSED else "stopped"
    can_prev = can_toggle = can_next = False
    try:
        c = info.controls
        can_prev, can_next = bool(c.is_previous_enabled), bool(c.is_next_enabled)
        can_toggle = bool(c.is_play_pause_toggle_enabled or c.is_play_enabled or c.is_pause_enabled)
    except Exception as e:
        write_error_log(f"Now playing: controls unavailable: {type(e).__name__}: {e}")
    title = artist = album = ""
    props = None
    try:
        props = await session.try_get_media_properties_async()
        title = (props.title or "").strip()
        artist = (props.artist or props.album_artist or "").strip()
        album = (props.album_title or "").strip()
    except Exception as e:
        write_error_log(f"Now playing: media properties unavailable: {type(e).__name__}: {e}")
    key = "\x1f".join((_session_id(session), title, artist, album))
    snap = {"status": status, "key": key, "title": title, "artist": artist,
            "can_prev": can_prev, "can_toggle": can_toggle, "can_next": can_next}
    if props is not None and THUMBNAIL_AVAILABLE and want_thumb(key):
        snap["thumb_tried"] = True
        try:
            snap["thumb"] = await _np_read_thumbnail(props)
        except Exception as e:
            write_error_log(f"Now playing: artwork unavailable: {type(e).__name__}: {e}")
    return snap


async def _np_control(action):
    mgr = await _get_manager()
    session, _sessions = _np_pick(mgr)
    if session is None:
        return None
    call = {"prev": session.try_skip_previous_async, "toggle": session.try_toggle_play_pause_async,
            "next": session.try_skip_next_async}[action]
    return bool(await call())


def np_control(action):
    """Blocking. Runs the command on the media loop thread, so call it from a worker thread only."""
    return MEDIA.run(_np_control(action))

# ---------------------------------------------------------------------------
# Per-app volume (volume mode). Uses the same per-app volume Windows shows in its volume mixer.
# All Core Audio calls run on one dedicated thread so COM is initialised exactly once.
# ---------------------------------------------------------------------------
try:
    import importlib.util
    AUDIO_AVAILABLE = os.name == "nt" and importlib.util.find_spec("pycaw") is not None
except Exception:
    AUDIO_AVAILABLE = False

AUDIO_SKIP_PROCESSES = VALORANT_PROCESSES + ("vibepause.exe",)
AUDIO_SKIP_PREFIXES = ("riot", "valorant", "vanguard", "vgc")
_volume_baseline = {}   # process id -> the app's volume before VibePause first changed it


def audio_skip(name):
    """Never touch the game itself, Riot/Vanguard, voice chat or call apps, or VibePause."""
    n = (name or "").lower()
    return (not n or n in AUDIO_SKIP_PROCESSES or n.startswith(AUDIO_SKIP_PREFIXES)
            or any(k in n for k in CALL_APP_KEYWORDS))


def _audio_sessions():
    from pycaw.pycaw import AudioUtilities
    names = {pid: str(name).lower() for pid, name in (list_processes() or [])}
    for session in AudioUtilities.GetAllSessions():
        pid = session.ProcessId
        if pid and not audio_skip(names.get(pid, "")):
            yield pid, session.SimpleAudioVolume


def set_app_volume(level):
    """Set the volume (0.0-1.0) of every music/media app. Returns how many apps were changed."""
    changed = 0
    for pid, volume in _audio_sessions():
        if pid not in _volume_baseline:
            _volume_baseline[pid] = volume.GetMasterVolume()
        volume.SetMasterVolume(level, None)
        changed += 1
    return changed


def restore_app_volume():
    """Put back the volume each app had before VibePause changed it."""
    for pid, volume in _audio_sessions():
        if pid in _volume_baseline:
            volume.SetMasterVolume(_volume_baseline[pid], None)
    _volume_baseline.clear()


class AudioWorker:
    def __init__(self):
        self.q = queue.Queue()
        self.thread = None
        self.guard = threading.Lock()

    def _start(self):
        with self.guard:
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def _run(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        while True:
            fn, args, box, done = self.q.get()
            try:
                box["result"] = fn(*args)
            except Exception as e:
                box["error"] = e
            finally:
                done.set()

    def call(self, fn, *args, timeout=8):
        self._start()
        box, done = {}, threading.Event()
        self.q.put((fn, args, box, done))
        if not done.wait(timeout):
            raise TimeoutError("the audio request timed out")
        if "error" in box:
            raise box["error"]
        return box.get("result")


AUDIO = AudioWorker()

class Controller:
    def __init__(self, ui):
        self.ui = ui
        self.stop_event = threading.Event()
        self.thread = None
        self.ocr_thread = None
        self.ocr_stop_event = None
        self.music_playing = True
        self.game_running = False
        self.last_process_check = 0.0
        self.in_match = False
        self.game_started = False
        self.character_select_seen = False
        self.round_active = False
        self.round_started_at = 0.0
        self.player_dead = False
        self.buy_announced = False
        self.last_event = None
        self.last_event_time = 0.0
        self.paused_by_us = False
        self.resume_pos = None
        self.action_generation = 0
        self.volume_changed = False
        self.lock = threading.Lock()

    def toggle_media(self):
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYUP, 0)

    def set_playing(self, desired):
        """Make the media session playing (True) or paused (False). Never blind-toggles when it can read the real state."""
        with self.lock:
            if GSMTC_AVAILABLE:
                try:
                    result = MEDIA.run(_gsmtc_set(desired))
                    if result is None:
                        self.ui.event("system", "No active Windows media session")
                        return False
                    if result == "failed":
                        self.ui.event("system", "The media app did not respond")
                        return False
                    self.music_playing = desired
                    if desired:
                        self.paused_by_us = False
                    return True
                except Exception as e:
                    self.ui.event("system", f"Media session error: {e}")
                    return False
            if desired != self.music_playing:
                self.toggle_media()
                self.music_playing = desired
            return True

    def set_volume(self, level):
        """Volume mode: set the volume of the media apps to level (0-100)."""
        with self.lock:
            try:
                changed = AUDIO.call(set_app_volume, level / 100.0)
            except Exception as e:
                self.ui.event("system", f"Volume error: {type(e).__name__}: {e}")
                return False
            self.volume_changed = self.volume_changed or bool(changed)
            if not changed:
                self.ui.event("system", "No audio apps to change the volume of")
                return False
            return True

    def restore_volume(self):
        if not self.volume_changed:
            return
        try:
            AUDIO.call(restore_app_volume)
        except Exception as e:
            self.ui.event("system", f"Volume error: {type(e).__name__}: {e}")
        self.volume_changed = False

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

        if self.ui.mode == MODE_VOLUME:
            level = self.ui.volumes.get(event)
            self.ui.event("event", (event, "None" if level is None else f"{level}%"))
            if level is None:
                return
            desired = ("volume", level)
        else:
            action = actions.get(event, "None")
            self.ui.event("event", (event, action))
            if action == "None":
                return
            desired = action == "Play"
        self.action_generation += 1
        generation = self.action_generation
        if delay:
            threading.Thread(target=self.apply_later, args=(desired, delay, stop_event, generation), daemon=True).start()
            return
        self.commit_action(desired, stop_event)

    def apply_later(self, desired, delay, stop_event, generation):
        if stop_event is not None:
            if stop_event.wait(delay / 1000):
                return
        else:
            time.sleep(delay / 1000)
        if generation != self.action_generation:
            return
        if not self.ui.active or not self.game_running:
            return
        self.commit_action(desired, stop_event)

    def commit_action(self, desired, stop_event):
        if stop_event is not None and stop_event.is_set():
            return
        if isinstance(desired, tuple):               # volume mode: ("volume", level)
            if self.set_volume(desired[1]):
                self.ui.event("volume", desired[1])
            return
        if self.set_playing(desired):
            self.paused_by_us = not desired
            self.ui.event("music", "Playing" if desired else "Paused")

    def follow(self, stop_event, start_at_end):
        waited = False
        while not stop_event.is_set():
            try:
                f = open_log(LOG)
            except OSError:
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

    def release(self):
        """Undo whatever VibePause did: restore app volumes and resume music it paused."""
        self.restore_volume()
        if self.paused_by_us:
            return self.set_playing(True)
        return False

    def reset_match_state(self):
        self.in_match = False
        self.game_started = False
        self.character_select_seen = False
        self.round_active = False
        self.round_started_at = 0.0
        self.player_dead = False
        self.buy_announced = False
        self.last_event = None

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
        if running is None:
            return
        if running != self.game_running:
            self.game_running = running
            self.ui.event("valorant", running)
            if not running:
                self.reset_match_state()
                self.restore_volume()
                if self.paused_by_us and self.ui.active and self.set_playing(True):
                    self.ui.event("music", "Playing")

    def run(self, stop_event):
        resume = False
        failures = 0
        while not stop_event.is_set():
            holder = []
            started = time.monotonic()
            try:
                self.monitor(stop_event, holder, resume)
            except Exception as e:
                resume = True
                close_quietly(holder)
                # A run that stayed healthy for a while resets the backoff; a crash loop does not.
                failures = 1 if time.monotonic() - started > 60 else failures + 1
                msg = f"Monitor error, restarting: {type(e).__name__}: {e}"
                self.ui.event("system", msg)      # Live activity throttles repeats of this
                write_error_log(msg)              # error.log dedupes repeats
                if stop_event.wait(min(60, 2 * 2 ** min(failures - 1, 5))):
                    return
                continue
            close_quietly(holder)
            return

    async def _ocr_recognize(self, engine, screenshot_bytes):
        stream = _InMemoryRandomAccessStream()
        writer = _DataWriter(stream)
        writer.write_bytes(screenshot_bytes)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await _BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        return " ".join(line.text for line in result.lines)

    async def _ocr_death_loop_async(self, stop_event):
        engine = _OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            self.ui.event("system", "Windows OCR unavailable: install the English OCR language pack in Windows Settings.")
            return
        self.ui.event("system", "Windows OCR death detection enabled (looking for KILLED BY).")
        error_reported = False
        while not stop_event.is_set():
            try:
                # OCR only during an active combat round; this avoids scanning the desktop
                # during the lobby and limits CPU use. Crop to the right-hand HUD column,
                # then encode as BMP for Windows.Media.Ocr.
                if (self.game_running and self.in_match and self.round_active
                        and not self.player_dead
                        and (time.monotonic() - self.round_started_at) >= 2.0):
                    # Grab the monitor VALORANT is actually on, not just the primary one,
                    # so detection still works when the game runs on a secondary display.
                    # Falls back to the primary monitor if that can't be determined.
                    monitor_rect = valorant_monitor_rect()
                    if monitor_rect:
                        shot = ImageGrab.grab(bbox=monitor_rect, all_screens=True)
                    else:
                        shot = ImageGrab.grab()
                    w, h = shot.size
                    # On death, VALORANT's "KILLED BY" panel appears in the right-hand HUD
                    # column, directly below the kill feed - NOT centered on screen. Its exact
                    # vertical offset moves with how many kill-feed rows happen to be showing
                    # at that moment (confirmed from real screenshots), so this crops a tall,
                    # generous right-hand column instead of a narrow band at a fixed height.
                    # The kill feed above it reads "PlayerName [weapon icon] PlayerName" with
                    # no "KILLED"/"BY" text (confirmed), and Combat Report below it says things
                    # like "154 KILLED" or "40 KILLED YOU", never "KILLED" immediately followed
                    # by "BY" - so including both in the crop carries no false-positive risk.
                    shot = shot.crop((int(w * 0.70), int(h * 0.08), w, int(h * 0.65)))
                    # This column is a modest fraction of the screen, so its text can still be
                    # small in absolute pixels even at high resolutions. Upscale toward a
                    # comfortable floor for Windows OCR; the region is small enough that a
                    # larger scale factor here is still cheap.
                    cw, ch = shot.size
                    if cw and cw < 1400:
                        scale = min(5.0, 1400 / cw)
                        shot = shot.resize((round(cw * scale), round(ch * scale)), Image.Resampling.LANCZOS)
                    out = BytesIO()
                    shot.save(out, format="BMP")
                    text = await self._ocr_recognize(engine, out.getvalue())
                    upper_text = text.upper()
                    # Windows OCR may put a space/punctuation between words, or merge them into
                    # one token with no space. Support both representations, but require "KILLED"
                    # and "BY" to be whole words/tokens: matching a bare substring of the whole
                    # screen's text (e.g. "...SKILLED BY nature...") would false-positive.
                    tokens = re.findall(r"[A-Z0-9]+", upper_text)
                    has_death_banner = (
                        "KILLEDBY" in tokens
                        or any(
                            tokens[i] == "KILLED" and tokens[i + 1] == "BY"
                            for i in range(len(tokens) - 1)
                        )
                    )
                    if has_death_banner and self.round_active and not self.player_dead:
                        self.player_dead = True
                        self.round_active = False
                        self.ui.event("system", "Death banner detected by Windows OCR.")
                        self.apply_action("Player Eliminated", stop_event=stop_event)
                    error_reported = False
                await asyncio.sleep(0.65)
            except Exception as e:
                if not error_reported:
                    self.ui.event("system", f"Windows OCR error: {type(e).__name__}: {e}")
                    write_error_log(f"Windows OCR error: {type(e).__name__}: {e}")
                    error_reported = True
                await asyncio.sleep(1.5)

    def _start_ocr_death_monitor(self, stop_event):
        if not WINDOWS_OCR_AVAILABLE:
            self.ui.event("system", "Windows OCR unavailable in this build; install the updated VibePause build with OCR support.")
            return
        # A thread tied to an older stop_event may still be alive (its loop only checks the
        # event once per sleep cycle), but it is already on its way out and will never serve
        # this stop_event. Only an OCR thread for THIS stop_event counts as already running.
        if (self.ocr_thread is not None and self.ocr_thread.is_alive()
                and self.ocr_stop_event is stop_event):
            return
        def run_ocr():
            try:
                asyncio.run(self._ocr_death_loop_async(stop_event))
            except Exception as e:
                msg = f"Windows OCR monitor stopped: {type(e).__name__}: {e}"
                self.ui.event("system", msg)
                write_error_log(msg)
        self.ocr_stop_event = stop_event
        self.ocr_thread = threading.Thread(target=run_ocr, name="VibePause-OCR", daemon=True)
        self.ocr_thread.start()

    def monitor(self, stop_event, holder, resume=False):
        self._start_ocr_death_monitor(stop_event)
        f = self.follow(stop_event, not resume)
        if not f:
            return
        holder[:] = [f]

        if resume and self.resume_pos is not None:
            try:
                if os.fstat(f.fileno()).st_size >= self.resume_pos:
                    f.seek(self.resume_pos)
            except OSError:
                pass
        else:
            self.reset_match_state()
        self.game_running = bool(valorant_running())
        self.last_process_check = time.monotonic()
        self.ui.event("valorant", self.game_running)

        partial = ""
        while not stop_event.is_set():
            self.poll_game_process()
            chunk = f.readline()
            if not chunk:
                if self.log_replaced(f):
                    f.close()
                    partial = ""
                    self.resume_pos = None
                    self.reset_match_state()
                    f = self.follow(stop_event, False)
                    if not f:
                        return
                    holder[:] = [f]
                stop_event.wait(.08)
                continue

            self.resume_pos = f.tell()
            partial += chunk
            if not partial.endswith("\n") and len(partial) < 65536:
                continue
            line, partial = partial.strip(), ""
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
                self.player_dead = False
                self.buy_announced = False
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
                self.player_dead = False
                self.buy_announced = False
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
                    self.player_dead = False
                    self.buy_announced = False
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
                if not self.buy_announced:
                    self.buy_announced = True
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
                match = re.search(r"gameplay started at local time ([0-9.]+)", low)
                local_time = float(match.group(1)) if match else 30.0
                self.player_dead = False
                if local_time < 15.0:
                    self.round_active = False
                    if not self.buy_announced:
                        self.buy_announced = True
                        self.apply_action("Buy Phase Started", stop_event=stop_event)
                    continue
                self.buy_announced = False
                self.round_active = True
                self.round_started_at = time.monotonic()
                self.apply_action("Combat Start", stop_event=stop_event)
                continue

            # Explicit round end is NOT game finish. The next round will emit
            # another Gameplay-started line.
            if any(x in low for x in (
                "ashootergamestate::onroundended",
                "logshootergamestate: onroundended"
            )):
                self.round_active = False
                self.player_dead = False
                self.buy_announced = False
                continue

            # The local player's pawn changes when they die: the game switches them to an
            # "<Agent>_PostDeath_PC_C" pawn, and back to the normal pawn on a revive or the
            # next round. Only the local player controller logs this.
            if "clientrestart_implementation" in low and "acknowledgepawn(" in low:
                ack = re.search(r"acknowledgepawn\('([^']*)'", low)
                prev = re.search(r"prevpawn\('([^']*)'", low)
                ack_dead = bool(ack and "_postdeath_" in ack.group(1))
                prev_dead = bool(prev and "_postdeath_" in prev.group(1))
                if ack_dead and not self.player_dead:
                    self.player_dead = True
                    self.round_active = False
                    self.apply_action("Player Eliminated", stop_event=stop_event)
                elif prev_dead and not ack_dead and self.player_dead:
                    self.player_dead = False
                    self.round_active = True
                    self.apply_action("Ultimate Used", stop_event=stop_event)
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
                self.player_dead = True      # lets the local-pawn revive check above recognise YOUR revive
                self.apply_action("Player Eliminated", stop_event=stop_event)
                continue

            # Note: there is deliberately no generic "resurrect" text match here any more. Those log
            # lines are written for every player on the map, so a teammate or enemy being revived
            # triggered "Ultimate Used". Only the local player's own pawn change (above) counts.

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


def _render_aurora(w, h):
    s = 4
    sw, sh = w // s, h // s
    base = Image.new("RGBA", (sw, sh), (9, 9, 26, 255))
    blobs = (
        (0.05, 0.00, 0.50, 0.65, (104, 66, 232, 200)),
        (0.58, -0.05, 0.30, 0.40, (214, 56, 124, 88)),
        (1.02, 1.05, 0.42, 0.45, (24, 160, 150, 90)),
        (-0.02, 1.00, 0.40, 0.42, (58, 92, 224, 85)),
    )
    for cx, cy, rx, ry, color in blobs:
        layer = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse(
            (int((cx - rx) * sw), int((cy - ry) * sh), int((cx + rx) * sw), int((cy + ry) * sh)), fill=color)
        base = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(sw * 0.11)))
    return base.resize((w, h), Image.Resampling.BICUBIC)


_AURORA_CACHE = {}


def render_aurora(w, h):
    """Same blurred background every popup uses, cached by size since the blur is the
    expensive part. Callers get their own copy back, since several of them composite
    more layers onto the result in place."""
    cached = _AURORA_CACHE.get((w, h))
    if cached is None:
        cached = _render_aurora(w, h)
        _AURORA_CACHE[(w, h)] = cached
    return cached.copy()


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


# ---------------------------------------------------------------------------
# Now-playing cover: a spinning disc. The cover is rotated ONCE per track into DISC_FRAMES frames
# (never per tick); the animation only swaps which frame the canvas shows. Only the square cover
# is rotated; the circular mask and the vinyl overlay are the same at every angle, so they are
# applied/drawn without rotating (no fringe at the edge, and the overlay is one static image).
# ---------------------------------------------------------------------------
DISC_STEP = 4                   # degrees between pre-rendered frames
DISC_FRAMES = 360 // DISC_STEP  # 90
SPIN_PERIOD = 8.0               # seconds per revolution


def disc_mask(d, scale=4):
    big = d * scale
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).ellipse((0, 0, big - 1, big - 1), fill=255)
    return m.resize((d, d), Image.Resampling.LANCZOS)


def square_cover(img, d):
    """Centre-crop any artwork to a square and size it d x d (opaque RGB)."""
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((d, d), Image.Resampling.LANCZOS)


COVER_SS = 2    # cover is rotated at 2x and scaled down, so spinning frames stay as sharp as the still one


def cover_frames_source(img, d):
    """Square cover at COVER_SS * d, sharpened a little when the artwork had to be enlarged."""
    sq = square_cover(img, d * COVER_SS)
    if min(img.size) < d * COVER_SS:
        sq = sq.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    return sq


def placeholder_cover(d):
    """Artwork stand-in: a muted conic gradient in the ring colours, so the spin is visible."""
    big = max(d, 64)
    img = Image.new("RGB", (big, big), (24, 24, 52))
    draw = ImageDraw.Draw(img)
    steps = 72
    for i in range(steps):
        r, g, b = ring_color(i / steps)
        col = (int(24 + (r - 24) * 0.55), int(24 + (g - 24) * 0.55), int(52 + (b - 52) * 0.55))
        draw.pieslice((-big // 4, -big // 4, big + big // 4, big + big // 4),
                      -90 + i * 360 / steps, -90 + (i + 1) * 360 / steps + 1, fill=col)
    return img.resize((d, d), Image.Resampling.LANCZOS)


def disc_frame(sq, mask, angle):
    """One frame: the square cover turned clockwise by angle, cut to a circle.
    sq may be larger than mask (supersampled); it is scaled down after rotating."""
    frame = sq if angle % 360 == 0 else sq.rotate(-angle, resample=Image.Resampling.BICUBIC)
    if frame.size != mask.size:
        frame = frame.resize(mask.size, Image.Resampling.LANCZOS)
    frame = frame.convert("RGBA")
    frame.putalpha(mask)
    return frame


def disc_overlay(d):
    """Static vinyl look drawn over the cover: faint grooves, a rim and a small centre hole."""
    s = 4
    big = d * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c = big / 2
    for n, frac in enumerate((0.95, 0.88, 0.81, 0.74, 0.67, 0.60, 0.53, 0.46, 0.39, 0.32)):
        r = c * frac
        color = (0, 0, 0, 52) if n % 2 == 0 else (255, 255, 255, 14)
        draw.ellipse((c - r, c - r, c + r, c + r), outline=color, width=s)
    r = c - 1
    draw.ellipse((c - r, c - r, c + r, c + r), outline=(255, 255, 255, 46), width=s)
    r = c * 0.115                               # soft shadow around the hole
    draw.ellipse((c - r, c - r, c + r, c + r), fill=(0, 0, 0, 80))
    r = c * 0.075                               # the hole itself matches the ring's dark inside
    draw.ellipse((c - r, c - r, c + r, c + r), fill=(10, 10, 34, 255), outline=(255, 255, 255, 70), width=s)
    return img.resize((d, d), Image.Resampling.LANCZOS)


def control_button_image(kind, d, state):
    """Round transport button. kind: prev / play / pause / next. state: normal / hot / dim."""
    s = 4
    big = d * s
    if kind in ("play", "pause"):
        grad = Image.linear_gradient("L").resize((big, big)).rotate(45, resample=Image.Resampling.BICUBIC)
        base = Image.composite(Image.new("RGB", (big, big), (90, 140, 255)),
                               Image.new("RGB", (big, big), (47, 227, 198)), grad).convert("RGBA")
        if state == "hot":
            base = Image.blend(base, Image.new("RGBA", (big, big), (255, 255, 255, 255)), 0.16)
        edge = Image.new("L", (big, big), 0)
        ImageDraw.Draw(edge).ellipse((0, 0, big - 1, big - 1), fill=255 if state != "dim" else 70)
        base.putalpha(edge)
        glyph_color = (12, 12, 36, 255 if state != "dim" else 150)
    else:
        a, b = ((255, 255, 255, 44), (255, 255, 255, 70)) if state == "hot" else ((255, 255, 255, 18), (255, 255, 255, 44))
        base = glass_image(big, big, big // 2, fill=a, border=b, sheen=0)
        glyph_color = (241, 239, 255, 255 if state != "dim" else 90)
        if state == "dim":
            base.putalpha(base.getchannel("A").point(lambda v: v * 6 // 10))
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    cx = cy = big / 2
    h = big * (0.17 if kind in ("play", "pause") else 0.14)
    if kind == "play":
        g.polygon([(cx - 0.7 * h, cy - h), (cx - 0.7 * h, cy + h), (cx + 1.0 * h, cy)], fill=glyph_color)
    elif kind == "pause":
        for x0, x1 in ((-0.8, -0.2), (0.2, 0.8)):
            g.rounded_rectangle((cx + x0 * h, cy - h, cx + x1 * h, cy + h), radius=0.12 * h, fill=glyph_color)
    elif kind == "prev":
        g.rounded_rectangle((cx - h, cy - h, cx - 0.6 * h, cy + h), radius=0.08 * h, fill=glyph_color)
        g.polygon([(cx + h, cy - h), (cx + h, cy + h), (cx - 0.5 * h, cy)], fill=glyph_color)
    else:
        g.rounded_rectangle((cx + 0.6 * h, cy - h, cx + h, cy + h), radius=0.08 * h, fill=glyph_color)
        g.polygon([(cx - h, cy - h), (cx - h, cy + h), (cx + 0.5 * h, cy)], fill=glyph_color)
    base.alpha_composite(layer)
    return base.resize((d, d), Image.Resampling.LANCZOS)


class ScaledCanvas(tk.Canvas):
    def __init__(self, master, scale, **kw):
        super().__init__(master, **kw)
        self.k = scale

    def _p(self, values):
        return [round(v * self.k) for v in values]

    def _o(self, kw):
        for key in ("width", "height"):
            if isinstance(kw.get(key), (int, float)):
                kw[key] = max(1, round(kw[key] * self.k))
        return kw

    def create_image(self, x, y, **kw):
        return super().create_image(*self._p((x, y)), **kw)

    def create_text(self, x, y, **kw):
        return super().create_text(*self._p((x, y)), **self._o(kw))

    def create_line(self, *c, **kw):
        return super().create_line(*[round(v * self.k) for v in c], **self._o(kw))

    def create_oval(self, *c, **kw):
        return super().create_oval(*[round(v * self.k) for v in c], **self._o(kw))

    def create_window(self, x, y, **kw):
        return super().create_window(*self._p((x, y)), **self._o(kw))

    def coords(self, item, *c):
        if c:
            return super().coords(item, *[round(v * self.k) for v in c])
        return super().coords(item)


def round_window(hwnd, width, height, radius):
    if os.name != "nt":
        return
    try:
        if sys.getwindowsversion().build >= 22000:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(ctypes.c_int(2)), 4)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 34, ctypes.byref(ctypes.c_uint(0xFFFFFFFE)), 4)
            return
        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2)
        user32.SetWindowRgn(ctypes.c_void_p(hwnd), ctypes.c_void_p(region), True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Optional global hotkey (turns VibePause on/off). Off by default.
# ---------------------------------------------------------------------------
HOTKEY_MODS = (("Ctrl", 0x2), ("Alt", 0x1), ("Shift", 0x4))          # RegisterHotKey MOD_* flags
HOTKEY_NAMED_KEYS = {"Space": 0x20, "Insert": 0x2D, "Delete": 0x2E, "Home": 0x24, "End": 0x23,
                     "PageUp": 0x21, "PageDown": 0x22, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28}
TK_KEY_NAMES = {"space": "Space", "Insert": "Insert", "Delete": "Delete", "Home": "Home", "End": "End",
                "Prior": "PageUp", "Next": "PageDown", "Left": "Left", "Up": "Up", "Right": "Right", "Down": "Down"}
TK_SHIFT_DIGITS = {"exclam": "1", "at": "2", "numbersign": "3", "dollar": "4", "percent": "5",
                   "asciicircum": "6", "ampersand": "7", "asterisk": "8", "parenleft": "9", "parenright": "0"}
TK_MODIFIER_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Caps_Lock",
                       "Num_Lock", "Win_L", "Win_R", "Super_L", "Super_R", "Meta_L", "Meta_R", "ISO_Level3_Shift"}


def hotkey_vk(name):
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    m = re.fullmatch(r"F(\d{1,2})", name)
    if m and 1 <= int(m.group(1)) <= 24:
        return 0x70 + int(m.group(1)) - 1
    return HOTKEY_NAMED_KEYS.get(name)


def parse_hotkey(spec):
    """'Ctrl+Alt+P' -> (modifier flags, virtual key). None if empty or invalid.
    At least one modifier is required so a plain key can never be taken over system-wide."""
    parts = [p.strip() for p in str(spec or "").split("+") if p.strip()]
    if len(parts) < 2:
        return None
    flags = dict(HOTKEY_MODS)
    mods = 0
    for part in parts[:-1]:
        if part not in flags:
            return None
        mods |= flags[part]
    vk = hotkey_vk(parts[-1])
    return (mods, vk) if vk else None


def hotkey_from_event(state, keysym):
    """Tk key event -> (spec, problem). Exactly one of the two is None."""
    if len(keysym) == 1 and keysym.isascii() and keysym.isalnum():
        key = keysym.upper()
    elif keysym in TK_KEY_NAMES:
        key = TK_KEY_NAMES[keysym]
    elif keysym in TK_SHIFT_DIGITS and state & 0x1:
        key = TK_SHIFT_DIGITS[keysym]
    elif re.fullmatch(r"F\d{1,2}", keysym) and hotkey_vk(keysym):
        key = keysym
    else:
        return None, "That key can't be used. Try a letter, number, F-key or arrow key."
    mods = [name for name, bit in (("Ctrl", 0x4), ("Alt", 0x20000), ("Shift", 0x1)) if state & bit]
    if not mods:
        return None, "Also hold Ctrl, Alt or Shift, so normal typing isn't affected."
    return "+".join(mods + [key]), None


class HotkeyListener:
    """System-wide hotkey. RegisterHotKey has to run on the thread that pumps messages,
    so every registration gets its own small thread."""
    WM_HOTKEY, WM_QUIT, MOD_NOREPEAT = 0x0312, 0x0012, 0x4000

    def __init__(self, callback):
        self.callback = callback
        self.spec = ""
        self._thread = None
        self._tid = 0

    def start(self, spec):
        """Register spec ('' = no hotkey). False if invalid or already used by another program."""
        self.stop()
        if not spec:
            return True
        parsed = parse_hotkey(spec)
        if not parsed or os.name != "nt":
            return False
        mods, vk = parsed
        ready, state = threading.Event(), {}

        def run():
            msg = ctypes.wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)    # make sure this thread has a message queue
            state["tid"] = ctypes.windll.kernel32.GetCurrentThreadId()
            state["ok"] = bool(user32.RegisterHotKey(None, 1, mods | self.MOD_NOREPEAT, vk))
            ready.set()
            if not state["ok"]:
                return
            if state.get("abandon"):
                user32.UnregisterHotKey(None, 1)
                return
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == self.WM_HOTKEY:
                        try:
                            self.callback()
                        except Exception:
                            pass
            finally:
                user32.UnregisterHotKey(None, 1)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        if not ready.wait(2.0):
            state["abandon"] = True
            return False
        if not state.get("ok"):
            return False
        self._thread, self._tid, self.spec = thread, state["tid"], spec
        return True

    def stop(self):
        thread, tid = self._thread, self._tid
        self._thread, self._tid, self.spec = None, 0, ""
        if thread and thread.is_alive() and tid:
            try:
                user32.PostThreadMessageW(tid, self.WM_QUIT, 0, 0)
            except Exception:
                pass
            thread.join(1.0)


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
        self.WIN_W, self.WIN_H = 1040, 648
        self.S = self.compute_scale()
        try:
            self.root.tk.call("tk", "scaling", self.S * 96 / 72)
        except tk.TclError:
            pass
        pw, ph = self.sx(self.WIN_W), self.sx(self.WIN_H)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{pw}x{ph}+{max(0,(sw-pw)//2)}+{max(0,min((sh-ph)//2-20,sh-ph-48))}")
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
        self.fam = next((f for f in ("Segoe UI Variable Display", "Segoe UI", "Bahnschrift") if f in fams),
                        tkfont.nametofont("TkDefaultFont").actual("family"))
        self.assets = {}
        self.load_assets()

        self.q = queue.Queue()
        self.actions = DEFAULT_ACTIONS.copy()
        self.action_vars = {}
        self.action_button = {}
        self.cv = None
        self.imgs = []
        self.chip_imgs = {}
        self.log_lines = []            # everything, for Copy diagnostics; the window shows only game events
        self.bars_active = False
        self._drag_ok = False
        self.delay = 0
        self.running = False
        self.startup = False
        self.close_to_tray = True
        self.hotkey = ""   # global on/off hotkey; empty = none (default)
        self.hotkeys = HotkeyListener(lambda: self.event("cmd", "toggle_active"))
        self.mode = MODE_PAUSE                      # "pause" (play/pause) or "volume" (per-event volume)
        self.volumes = DEFAULT_VOLUMES.copy()       # event -> 0-100, or None = leave unchanged
        self.language = "en"
        self.language_chosen = False                # becomes True once the person has picked a language
        self.vol_widgets = {}
        self.spin_cover = True                      # "Spinning cover" setting
        # Game status (see GAME_STATES): one state for the music card's pill and the Game status card.
        self.game_state = "waiting"
        self.game_action = None                     # action applied by the last game event, for the sentence
        self.game_events = []                       # (time, state key, action), newest last
        self._valorant_seen = None
        self._paused_by_app = False                 # VibePause paused the music for the match
        self._paused_at = 0.0
        self._game_tick_running = False
        # Now playing card
        self.np_key = None
        self.np_title_text = ""
        self.np_artist_text = ""
        self.np_status = "none"                     # playing / paused / stopped / none / unavailable
        self.np_caps = (False, False, False)        # previous, play/pause, next supported by the player
        self.np_btn = {}
        self.np_busy = False
        self.np_flash_until = 0.0
        self.pill_items = {}
        self.pill_bars = []
        self._np_photos = {}
        self._eq_flat = False
        self._np_thumb = None                       # artwork of the current track (PIL), kept to re-render
        self._cover_gen = 0                         # bumped on every track change; stale work checks it
        self._cover_job = None
        self._disc_pending = []                     # rendered frames waiting to become PhotoImages
        self._disc_tk = []                          # per-track PhotoImage frames (freed on track change)
        self._disc_static = None
        self._disc_ready = False
        self._disc_angle = 0.0
        self._disc_idx = 0
        self._disc_last_t = None
        self._disc_d = 0
        self.disc_item = None
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
        self.last_update_check = 0
        self.active = True  # VibePause is active by default
        self.legal_accepted = False
        self.valorant_running = False
        self.declined_update = None
        # Lazily-set state, initialised here so it never needs a getattr(self, ..., default) guard.
        self._bars_running = False
        self._status_limit = None
        self._media_watch_started = False
        self._update_busy = False
        self._update_failures = 0
        self._pending_update = None
        self._auto_update_running = False
        self._last_log_key = None
        self._last_log_count = 1
        self._legal_win = None
        self._quit_win = None
        self.tray_thread = None
        self.load_auto_update_settings()
        self.load()
        self.sync_startup_path()
        self.controller = Controller(self)
        self.build()
        self.apply_windows_app_style()
        self.root.after(80, self.process)
        self.root.after(700, self.warm_settings)
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.root.report_callback_exception = self.report_error
        self.create_tray()
        self.start_quit_listener()
        if "--startup" in sys.argv and TRAY_AVAILABLE:
            self.root.withdraw()   # launched by Windows at sign-in: start in the tray

        self.check_legal_acceptance_on_startup()

    def report_error(self, exc, val, tb):
        import traceback
        if not write_error_log("".join(traceback.format_exception(exc, val, tb))):
            return  # same error already reported recently
        try:
            self.log_line("Something went wrong. Details are in error.log")
        except Exception:
            pass

    def F(self, size, bold=False):
        return (self.fam, size, "bold" if bold else "normal")

    def load(self):
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)

            # Migrate settings from old location to new location if needed
            if LEGACY_CONFIG.exists() and not CONFIG.exists():
                try:
                    legacy_data = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8"))
                    write_settings(legacy_data)
                except Exception:
                    pass  # If migration fails, continue with empty settings

            # Load settings from current location
            d = read_settings()
            if d:
                saved_actions = d.get("actions")
                if not isinstance(saved_actions, dict):
                    saved_actions = {}
                for k in self.actions:
                    val = saved_actions.get(k)
                    if val in ("Play", "Pause", "None"):
                        self.actions[k] = val
                self.delay = clean_delay(d.get("delay", 0))
                self.active = clean_bool(d.get("active"), True)
                self.startup = clean_bool(d.get("startup"), False)
                self.close_to_tray = clean_bool(d.get("close_to_tray"), True)
                self.spin_cover = clean_bool(d.get("spin_cover"), True)
                saved_hotkey = d.get("hotkey", "")
                self.hotkey = saved_hotkey if parse_hotkey(saved_hotkey) else ""
                lang = d.get("language")
                self.language = lang if lang in LANG_CODES else "en"
                self.language_chosen = clean_bool(d.get("language_chosen"), False)
                set_language(self.language)
                mode = d.get("mode")
                self.mode = mode if mode in (MODE_PAUSE, MODE_VOLUME) else MODE_PAUSE
                saved_volumes = d.get("volumes")
                if isinstance(saved_volumes, dict):
                    for k in self.volumes:
                        if k in saved_volumes:
                            self.volumes[k] = clean_volume(saved_volumes[k], self.volumes[k])
        except Exception:
            pass

    def save(self):
        # Merge into the existing file instead of replacing it. Keys this method
        # does not own (legal acceptance, migration flags) must survive every
        # save, otherwise the legal popup comes back on each launch.
        data = read_settings()
        data.update({
            "actions": self.actions,
            "delay": self.delay,
            "active": self.active,
            "startup": self.startup,
            "close_to_tray": self.close_to_tray,
            "spin_cover": self.spin_cover,
            "auto_update_enabled": self.auto_update_enabled,
            "hotkey": self.hotkey,
            "language": self.language,
            "language_chosen": self.language_chosen,
            "mode": self.mode,
            "volumes": self.volumes,
        })
        data.pop("selected_media_app", None)
        if not write_settings(data):
            self.log_line("Could not save settings")

    def check_legal_acceptance_on_startup(self):
        if not self.language_chosen:
            # First start: pick a language before the Terms, so they are read in a familiar language.
            self.show_language_popup(self.check_legal_acceptance_on_startup)
            return
        if self.check_legal_acceptance():
            self.begin_operation()
        else:
            self.show_legal_popup()

    def begin_operation(self):
        self.legal_accepted = True
        if self.hotkey and not self.hotkeys.start(self.hotkey):
            self.log_line(f"Hotkey {self.hotkey} is used by another program, so it is off")
        self.start_media_watch()
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
        self.auto_update_enabled = clean_bool(read_settings().get("auto_update_enabled"), True)

    def load_assets(self):
        if not self.asset_dir.exists():
            return
        # Every UI icon is a PNG, explicitly resized. Source files are 64px and never shown at native size.
        sizes = {
            "play": 17, "pause": 17, "none": 14, "gear": 16, "close": 16, "reset": 16,
            "chrome": 20, "youtube_music": 20, "apple_music": 20, "spotify": 20,
            "vibepause_logo_24": 24, "vibepause_logo_32": 32,
        }
        for name, size in sizes.items():
            path = self.asset_dir / f"{name}.png"
            if path.exists():
                try:
                    px = self.sx(size)
                    im = Image.open(path).convert("RGBA").resize((px, px), Image.Resampling.LANCZOS)
                    self.assets[name] = ImageTk.PhotoImage(im)
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

            SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x2, 0x4, 0x10, 0x20
            # Tk sized the window while it still had a title bar and borders. With the frame
            # stripped that outer size is now all client area, which showed up as an empty strip
            # along the bottom and right. Resize to exactly the content size.
            pw, ph = self.sx(self.WIN_W), self.sx(self.WIN_H)
            user32.SetWindowPos(hwnd, None, 0, 0, pw, ph, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            round_window(hwnd, pw, ph, self.sx(12))
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

    LEFT_CARD = (28, 82, 328, 616)
    EVENTS_CARD = (350, 82, 1012, 432)
    MEDIA_CARD = (350, 448, 672, 616)
    ACTIVITY_CARD = (690, 448, 1012, 616)
    RING_CENTER = (178, 270)
    RING_SIZE = 232
    DISC_SIZE = 216
    TILE_SIZE = (303, 68)
    CHIP_SIZE = (137, 36)
    GAME_ROWS = 3
    HEADER_H = 72

    def sx(self, value):
        return int(round(value * self.S))

    def compute_scale(self):
        try:
            dpi = float(self.root.winfo_fpixels("1i"))
        except tk.TclError:
            dpi = 96.0
        scale = min(3.0, max(1.0, dpi / 96.0))
        scale = min(scale, self.root.winfo_screenheight() / (self.WIN_H + 56))
        return round(max(0.75, scale), 2)

    def keep(self, photo):
        self.imgs.append(photo)
        return photo

    def photo(self, image):
        return self.keep(ImageTk.PhotoImage(image))

    def gi(self, w, h, radius, **kw):
        return glass_image(self.sx(w), self.sx(h), self.sx(radius), **kw)

    def font_for(self, size, bold=False):
        return tkfont.Font(root=self.root, font=self.F(size, bold))

    def fit(self, text, width, font):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "...") > width:
            text = text[:-1]
        return text + "..."

    def fit_size(self, text, width, size, bold=False, smallest=7):
        """Largest font size (down to smallest) at which text is at most width logical pixels wide."""
        while size > smallest and self.font_for(size, bold).measure(text) > width * self.S:
            size -= 1
        return size

    def tile_origin(self, i):
        return 372 + (i % 2) * 315, 130 + (i // 2) * 74

    def chip_origin(self, i):
        return 372 + (i % 2) * 147, 496 + (i // 2) * 46

    def make_clickable(self, tag, command, hover=None, cv=None):
        cv = cv or self.cv

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
        self._drag_ok = event.y < self.sx(self.HEADER_H) and "nodrag" not in self.cv.gettags("current")
        if self._drag_ok:
            self.start_drag(event)

    def canvas_drag(self, event):
        if self._drag_ok:
            self.drag_window(event)

    def build(self):
        W, H = self.WIN_W, self.WIN_H
        self.cv = ScaledCanvas(self.root, self.S, width=self.sx(W), height=self.sx(H), bg=self.BG, bd=0, highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.compose_scene(W, H)
        self.cv.create_image(0, 0, image=self.scene_photo, anchor="nw")
        self.build_chip_images()
        self.build_header()
        self.build_now_playing_card()
        self.build_events()
        self.build_media_card()
        self.build_activity_card()
        self.refresh_game_ui()
        self.cv.create_text(W // 2, H - 17, text="Made using Claude by tanveer-exe   |   Open Source",
                            fill=self.FAINT, font=self.F(8))
        self.cv.bind("<ButtonPress-1>", self.canvas_press)
        self.cv.bind("<B1-Motion>", self.canvas_drag)
        if not self._bars_running:
            self._bars_running = True
            self.animate_bars()
        if not self._game_tick_running:
            self._game_tick_running = True
            self.root.after(20000, self.tick_game_times)

    def compose_scene(self, W, H):
        scene = render_aurora(self.sx(W), self.sx(H))

        def card(box, radius, **kw):
            x0, y0, x1, y1 = box
            scene.alpha_composite(self.gi(x1 - x0, y1 - y0, radius, **kw), (self.sx(x0), self.sx(y0)))

        card(self.LEFT_CARD, 26, fill=(255, 255, 255, 16))
        card(self.EVENTS_CARD, 26, fill=(255, 255, 255, 16))
        card(self.MEDIA_CARD, 26, fill=(255, 255, 255, 12))
        card(self.ACTIVITY_CARD, 26, fill=(8, 8, 26, 120), border=(255, 255, 255, 40))
        tw, th = self.TILE_SIZE
        for i in range(len(EVENTS)):
            x, y = self.tile_origin(i)
            scene.alpha_composite(self.gi(tw, th, 16, fill=(255, 255, 255, 14), border=(255, 255, 255, 36)),
                                  (self.sx(x), self.sx(y)))
        cw, ch = self.CHIP_SIZE
        for i in range(len(MEDIA_APPS)):
            x, y = self.chip_origin(i)
            scene.alpha_composite(self.gi(cw, ch, 12, fill=(255, 255, 255, 14), border=(255, 255, 255, 30)),
                                  (self.sx(x), self.sx(y)))
        d = self.sx(self.RING_SIZE)
        cx, cy = self.sx(self.RING_CENTER[0]), self.sx(self.RING_CENTER[1])
        ring = render_ring(d, max(2, self.sx(4)))
        pad = self.sx(46)
        glow = Image.new("RGBA", (d + 2 * pad, d + 2 * pad), (0, 0, 0, 0))
        glow.alpha_composite(ring, (pad, pad))
        glow = glow.filter(ImageFilter.GaussianBlur(self.sx(18)))
        glow.putalpha(glow.getchannel("A").point(lambda v: v * 6 // 10))
        scene.alpha_composite(glow, (cx - d // 2 - pad, cy - d // 2 - pad))
        scene.alpha_composite(ring, (cx - d // 2, cy - d // 2))
        self.scene_img = scene.convert("RGB")
        self.scene_photo = self.photo(self.scene_img)

    def build_chip_images(self):
        styles = {
            "None": ((255, 255, 255, 18), (255, 255, 255, 40), "none"),
            "Play": ((47, 227, 198, 52), (80, 240, 215, 120), "play"),
            "Pause": ((255, 93, 143, 62), (255, 125, 170, 125), "pause"),
        }
        self.chip_imgs = {}
        for state, (fill, border, icon) in styles.items():
            chip = self.gi(34, 34, 11, fill=fill, border=border, sheen=10)
            path = self.asset_dir / f"{icon}.png"
            if path.exists():
                try:
                    g = self.sx(16)
                    glyph = Image.open(path).convert("RGBA").resize((g, g), Image.Resampling.LANCZOS)
                    off = (chip.width - g) // 2
                    chip.alpha_composite(glyph, (off, off))
                except Exception:
                    pass
            self.chip_imgs[state] = self.photo(chip)

    HEADER_LEFT_LIMIT = 190

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
        labels = [tr("Auto-update"), tr("Run on startup"), tr("Active")]
        status_longest = max((tr(t) for t in ("VALORANT not running", "VALORANT running", "Stopped", "Starting...")),
                             key=lambda t: self.font_for(10, True).measure(t))
        natural = [int(self.font_for(10, True).measure(t) / self.S) for t in labels + [status_longest]]
        room = (x - 8) - self.HEADER_LEFT_LIMIT
        needed = sum(n + 56 for n in natural) + 3 * 8
        cut = max(0, -(-(needed - room) // 4))
        limits = [max(40, n - cut) for n in natural]
        x = self.toggle_pill(x - 8, cy, labels[0], self.auto_update_var,
                             lambda: self.set_auto_update_enabled(self.auto_update_var.get()), "t_update", limits[0])
        x = self.toggle_pill(x - 8, cy, labels[1], self.startup_var,
                             lambda: self.set_startup(self.startup_var.get()), "t_startup", limits[1])
        x = self.toggle_pill(x - 8, cy, labels[2], self.active_var,
                             lambda: self.set_active(self.active_var.get()), "t_active", limits[2])
        self.build_status_pill(x - 8, cy, limits[3])

    def round_button(self, right, cy, tag, icon, command, danger=False):
        d = 36
        x0 = right - d
        normal = self.photo(self.gi(d, d, d // 2, fill=(255, 255, 255, 18), border=(255, 255, 255, 44)))
        hot = (255, 93, 143, 90) if danger else (255, 255, 255, 40)
        hover_img = self.photo(self.gi(d, d, d // 2, fill=hot, border=(255, 255, 255, 70)))
        bg = self.cv.create_image(x0, cy, image=normal, anchor="w", tags=(tag, "nodrag"))
        if icon:
            self.cv.create_image(x0 + d // 2, cy, image=icon, tags=(tag, "nodrag"))
        self.make_clickable(tag, command, lambda on: self.cv.itemconfig(bg, image=hover_img if on else normal))
        return x0

    def toggle_pill(self, right, cy, label, var, command, tag, limit=None):
        cv = self.cv
        font = self.F(10, True)
        if limit:
            label = self.fit(label, limit * self.S, self.font_for(10, True))
        w = int(self.font_for(10, True).measure(label) / self.S) + 56
        h = 36
        x0 = right - w
        off = self.photo(self.gi(w, h, h // 2, fill=(255, 255, 255, 14), border=(255, 255, 255, 38)))
        on = self.photo(self.gi(w, h, h // 2, fill=(47, 227, 198, 40), border=(80, 240, 215, 125)))
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

    def switch_photo(self, state):
        cache = self.__dict__.setdefault("_switch_cache", {})
        if state not in cache:
            sw = self.gi(40, 22, 11, fill=(47, 227, 198, 90) if state else (255, 255, 255, 26),
                         border=(80, 240, 215, 160) if state else (255, 255, 255, 60), sheen=0)
            scale = 4
            knob = Image.new("RGBA", (sw.width * scale, sw.height * scale), (0, 0, 0, 0))
            dia = int(sw.height * 0.64 * scale)
            pad = int(sw.height * 0.18 * scale)
            kx = sw.width * scale - dia - pad if state else pad
            ky = (sw.height * scale - dia) // 2
            ImageDraw.Draw(knob).ellipse((kx, ky, kx + dia, ky + dia),
                                         fill=(255, 255, 255, 245) if state else (200, 198, 230, 235))
            sw.alpha_composite(knob.resize(sw.size, Image.Resampling.LANCZOS))
            cache[state] = self.photo(sw)
        return cache[state]

    def build_status_pill(self, right, cy, limit=None):
        cv = self.cv
        font = self.F(10, True)
        longest = max((tr(t) for t in ("VALORANT not running", "VALORANT running", "Stopped", "Starting...")),
                      key=lambda t: self.font_for(10, True).measure(t))
        self._status_limit = limit
        w = min(int(self.font_for(10, True).measure(longest) / self.S), limit or 10 ** 6) + 56
        h = 36
        x0 = right - w
        bg = self.photo(self.gi(w, h, h // 2, fill=(255, 255, 255, 14), border=(255, 255, 255, 38)))
        cv.create_image(x0, cy, image=bg, anchor="w")
        self.status_dot = cv.create_oval(x0 + 17, cy - 5, x0 + 27, cy + 5, width=2, fill=self.MUTED, outline=self.MUTED)
        self.status_text = cv.create_text(x0 + 38, cy, text=self.status_fit(tr("Starting...")), anchor="w", font=font, fill=self.MUTED)

    def status_fit(self, text):
        limit = self._status_limit
        return self.fit(text, limit * self.S, self.font_for(10, True)) if limit else text

    def build_now_playing_card(self):
        """Music area: status pill, rotating disc cover, title/artist and previous / play-pause / next."""
        cv = self.cv
        cx, cy = self.RING_CENTER
        self.build_np_pill(46, 108)
        self._disc_d = self.sx(self.DISC_SIZE)
        self.disc_item = cv.create_image(cx, cy, image=self.current_disc_image())
        cv.create_image(cx, cy, image=self.disc_overlay_photo())
        self._np_font_title = self.font_for(15, True)
        self._np_font_artist = self.font_for(10)
        self.np_title = cv.create_text(cx, 424, text="", fill=self.TEXT, font=self.F(15, True))
        self.np_artist = cv.create_text(cx, 448, text="", fill=self.MUTED, font=self.F(10))
        self.np_btn = {}
        for tag, kinds, x, d in (("np_prev", ("prev",), 94, 46), ("np_toggle", ("play", "pause"), 178, 64),
                                 ("np_next", ("next",), 262, 46)):
            imgs = {(k, st): self.photo(control_button_image(k, self.sx(d), st))
                    for k in kinds for st in ("normal", "hot", "dim")}
            item = cv.create_image(x, 524, image=imgs[(kinds[0], "dim")], tags=(tag, "nodrag"))
            self.np_btn[tag] = {"item": item, "imgs": imgs, "hover": False}
            self.make_clickable(tag, lambda t=tag: self.np_press(t), lambda on, t=tag: self.np_hover(t, on))
        self.refresh_np()

    def build_np_pill(self, x0, cy):
        """Small status pill: a mini equalizer and a short text. Teal = playing, pink = paused by VibePause."""
        cv = self.cv
        f = self.font_for(9, True)
        texts = [tr(t) for t in ("Waiting for VALORANT", "In match", "In the menu", "Paused for your match",
                                 "VibePause is off", "VALORANT is open", "Match ended")]
        w = int(min(252, max(120, max(f.measure(t) for t in texts) / self.S + 52)))
        h = 30
        self._pill_text_w = self.sx(w - 46)
        self._pill_font = f
        tints = {"idle": ((255, 255, 255, 14), (255, 255, 255, 38)),
                 "play": ((47, 227, 198, 34), (80, 240, 215, 105)),
                 "pause": ((255, 93, 143, 40), (255, 125, 170, 105))}
        self.pill_items = {"bg": cv.create_image(x0, cy, image=self.photo(self.gi(w, h, h // 2, fill=tints["idle"][0], border=tints["idle"][1])), anchor="w")}
        self.pill_bgs = {k: self.photo(self.gi(w, h, h // 2, fill=v[0], border=v[1])) for k, v in tints.items()}
        cv.itemconfig(self.pill_items["bg"], image=self.pill_bgs["idle"])
        self.pill_bar_x = [x0 + 15 + i * 5 for i in range(4)]
        self.pill_cy = cy
        self.pill_bars = [cv.create_line(x, cy - 2, x, cy + 2, width=3, capstyle="round", fill=self.MUTED)
                          for x in self.pill_bar_x]
        self._eq_flat = True
        self.pill_items["text"] = cv.create_text(x0 + 38, cy, text="", anchor="w", font=self.F(9, True), fill=self.MUTED)

    def disc_overlay_photo(self):
        if "overlay" not in self._np_photos:
            self._np_photos["overlay"] = self.photo(disc_overlay(self.sx(self.DISC_SIZE)))
        return self._np_photos["overlay"]

    def placeholder_photo(self):
        if "placeholder" not in self._np_photos:
            d = self.sx(self.DISC_SIZE)
            self._np_photos["placeholder"] = self.photo(disc_frame(placeholder_cover(d), disc_mask(d), 0))
        return self._np_photos["placeholder"]

    def current_disc_image(self):
        if self._disc_ready and self.spin_cover and self._disc_tk:
            return self._disc_tk[self._disc_idx % len(self._disc_tk)]
        return self._disc_static or self.placeholder_photo()

    def set_disc_image(self, photo):
        try:
            self.cv.itemconfig(self.disc_item, image=photo)
        except tk.TclError:
            pass

    def build_events(self):
        cv = self.cv
        cv.create_text(374, 108, text=tr("Music behaviour"), fill=self.TEXT, font=self.F(13, True), anchor="w")
        reset_icon = self.img("reset")
        d = 30
        rx = 1012 - 22 - d
        normal = self.photo(self.gi(d, d, d // 2, fill=(255, 255, 255, 18), border=(255, 255, 255, 44)))
        hot = self.photo(self.gi(d, d, d // 2, fill=(255, 255, 255, 44), border=(255, 255, 255, 70)))
        rbg = cv.create_image(rx, 108, image=normal, anchor="w", tags=("reset", "nodrag"))
        if reset_icon:
            cv.create_image(rx + d // 2, 108, image=reset_icon, tags=("reset", "nodrag"))
        self.make_clickable("reset", self.reset, lambda on: cv.itemconfig(rbg, image=hot if on else normal))
        self.build_mode_switch(rx - 12)

        tw, th = self.TILE_SIZE
        clear = self.photo(Image.new("RGBA", (self.sx(tw), self.sx(th)), (0, 0, 0, 0)))
        name_font = self.font_for(11, True)
        desc_font = self.font_for(9)
        self.vol_widgets = {}
        for i, (name, desc) in enumerate(EVENTS):
            x, y = self.tile_origin(i)
            tag = f"tile{i}"
            tags = (tag, "nodrag")
            ptags = tags + ("pm",)          # shown in pause mode
            cv.create_image(x, y, image=clear, anchor="nw", tags=tags)
            cv.create_text(x + 20, y + 25, text=tr(name), fill=self.TEXT, font=name_font, anchor="w", tags=tags)
            cv.create_text(x + 20, y + 46, text=self.fit(tr(desc), self.sx(tw - 20 - 20 - 34 - 10), desc_font), fill=self.MUTED,
                           font=desc_font, anchor="w", tags=ptags)
            v = tk.StringVar(value=self.actions[name])
            self.action_vars[name] = v
            self.action_button[name] = cv.create_image(x + tw - 20 - 34, y + 17, image=self.chip_imgs["None"],
                                                       anchor="nw", tags=ptags)
            self.refresh_action(name, v)
            self.make_clickable(tag, lambda n=name, var=v: self.cycle_choice(n, var))
            self.build_volume_widget(i, name, x, y)
        self.apply_mode_visibility()

    # ---- pause / volume mode ----
    def set_language_choice(self, code):
        if code == self.language or code not in LANG_CODES:
            return
        self.language = code
        self.language_chosen = True
        set_language(code)
        self.save()
        reopen = self.settings_open
        self.rebuild_ui()
        if reopen:
            self.root.after(60, self.toggle_settings)

    def rebuild_ui(self):
        """Redraw the whole window in the current language, keeping its live state."""
        self.close_settings()
        self.close_tray_popup()
        try:
            self.cv.destroy()
        except tk.TclError:
            pass
        self.action_vars, self.action_button, self.vol_widgets = {}, {}, {}
        self.build()
        self.status_update()
        self.refresh_np()
        self.refresh_game_ui()
        self._tray_state = None
        self.update_tray()

    def build_mode_switch(self, right):
        cv = self.cv
        w, h, cy = 176, 30, 108
        x0 = right - w
        half = w // 2
        base = self.gi(w, h, h // 2, fill=(255, 255, 255, 14), border=(255, 255, 255, 38))
        imgs = {}
        for mode in (MODE_PAUSE, MODE_VOLUME):
            img = base.copy()
            seg = self.gi(half - 4, h - 6, (h - 6) // 2, fill=(47, 227, 198, 52), border=(80, 240, 215, 125))
            img.alpha_composite(seg, (self.sx(2 + (0 if mode == MODE_PAUSE else half)), self.sx(3)))
            imgs[mode] = self.photo(img)
        tags = ("modesw", "nodrag")
        bg = cv.create_image(x0, cy, image=imgs[self.mode], anchor="w", tags=tags)
        t_pause = cv.create_text(x0 + half // 2, cy, text=tr("Pause"), font=self.F(9, True), tags=tags)
        t_vol = cv.create_text(x0 + half + half // 2, cy, text=tr("Volume"), font=self.F(9, True), tags=tags)
        for tag, mode, left in (("mode_p", MODE_PAUSE, x0), ("mode_v", MODE_VOLUME, x0 + half)):
            cv.create_image(left, cy - h // 2, image=self.photo_clear(self.sx(half), self.sx(h)), anchor="nw",
                            tags=(tag, "nodrag"))
            self.make_clickable(tag, lambda m=mode: self.set_mode(m))
        self._mode_items = (bg, t_pause, t_vol, imgs)

    def apply_mode_visibility(self):
        cv = self.cv
        cv.itemconfigure("pm", state="normal" if self.mode == MODE_PAUSE else "hidden")
        cv.itemconfigure("vm", state="normal" if self.mode == MODE_VOLUME else "hidden")
        bg, t_pause, t_vol, imgs = self._mode_items
        cv.itemconfig(bg, image=imgs[self.mode])
        cv.itemconfig(t_pause, fill=self.TEXT if self.mode == MODE_PAUSE else self.MUTED)
        cv.itemconfig(t_vol, fill=self.TEXT if self.mode == MODE_VOLUME else self.MUTED)

    def set_mode(self, mode):
        if mode == self.mode:
            return
        if mode == MODE_VOLUME and not AUDIO_AVAILABLE:
            self.log_line("Volume mode is not available in this build")
            return
        self.mode = mode
        self.apply_mode_visibility()
        self.save()
        # Leaving a mode undoes it: resume music that was paused, or put volumes back.
        threading.Thread(target=self.controller.release, daemon=True).start()
        if mode == MODE_VOLUME:
            self.log_line(tr("Volume mode: drag to set each event's volume. Click the percentage to leave an event unchanged."))

    def build_volume_widget(self, i, name, x, y):
        """A drawn slider for one tile (volume mode). Click the percentage to leave the event unchanged."""
        cv = self.cv
        tw, _ = self.TILE_SIZE
        x0, x1, ty = x + 20, x + tw - 20, y + 51
        vtags = ("vm", "nodrag")
        label = cv.create_text(x1, y + 25, text="", anchor="e", font=self.F(10, True), tags=vtags + (f"vlabel{i}",))
        cv.create_line(x0, ty, x1, ty, width=6, capstyle="round", fill=self.PANEL3, tags=vtags)
        fill = cv.create_line(x0, ty, x0, ty, width=6, capstyle="round", fill=self.GREEN, tags=vtags)
        knob = cv.create_oval(x0 - 8, ty - 8, x0 + 8, ty + 8, fill="#f1efff", outline=self.BLUE, width=2, tags=vtags)
        stag = f"vslider{i}"
        cv.create_image(x0 - 10, ty - 14, image=self.photo_clear(self.sx(x1 - x0 + 20), self.sx(28)), anchor="nw",
                        tags=vtags + (stag,))
        self.vol_widgets[name] = {"label": label, "fill": fill, "knob": knob, "x0": x0, "x1": x1, "ty": ty}

        def level_at(e):
            return max(0, min(100, round((e.x / self.S - x0) / (x1 - x0) * 100)))

        def drag(e):
            self.volumes[name] = level_at(e)
            self.refresh_volume(name)

        def release(_e):
            self.save()

        cv.tag_bind(stag, "<Button-1>", drag)
        cv.tag_bind(stag, "<B1-Motion>", drag)
        cv.tag_bind(stag, "<ButtonRelease-1>", release)
        cv.tag_bind(stag, "<Enter>", lambda e: cv.config(cursor="sb_h_double_arrow"))
        cv.tag_bind(stag, "<Leave>", lambda e: cv.config(cursor=""))
        last = {"level": DEFAULT_VOLUMES[name]}

        def toggle_unchanged():
            if self.volumes.get(name) is None:
                self.volumes[name] = last["level"]
            else:
                last["level"] = self.volumes[name]
                self.volumes[name] = None
            self.refresh_volume(name)
            self.save()

        self.make_clickable(f"vlabel{i}", toggle_unchanged)
        self.refresh_volume(name)

    def refresh_volume(self, name):
        w = self.vol_widgets.get(name)
        if not w:
            return
        cv = self.cv
        level = self.volumes.get(name)
        if level is None:
            cv.itemconfig(w["label"], text=tr("No change"), fill=self.FAINT)
            cv.itemconfig(w["fill"], fill=self.FAINT)
            cv.itemconfig(w["knob"], fill=self.FAINT, outline=self.BORDER)
            px = w["x0"]
        else:
            cv.itemconfig(w["label"], text=f"{level}%", fill=self.TEXT)
            cv.itemconfig(w["fill"], fill=self.GREEN)
            cv.itemconfig(w["knob"], fill="#f1efff", outline=self.BLUE)
            px = w["x0"] + (w["x1"] - w["x0"]) * level / 100
        cv.coords(w["fill"], w["x0"], w["ty"], px, w["ty"])
        cv.coords(w["knob"], px - 8, w["ty"] - 8, px + 8, w["ty"] + 8)

    def refresh_action(self, event, var):
        value = var.get()
        self.cv.itemconfig(self.action_button[event], image=self.chip_imgs.get(value, self.chip_imgs["None"]))

    def cycle_choice(self, event, var):
        if self.mode != MODE_PAUSE:
            return
        order = ["None", "Play", "Pause"]
        value = order[(order.index(var.get()) + 1) % len(order)]
        var.set(value)
        self.actions[event] = value
        self.refresh_action(event, var)
        self.save()
        self.log_line(f"{tr(event)}: {tr(value)}")

    def build_media_card(self):
        cv = self.cv
        cv.create_text(374, 474, text=tr("Supported media"), fill=self.TEXT, font=self.F(13, True), anchor="w")
        keys = {"Google Chrome": ("chrome", "Chrome"), "YouTube Music": ("youtube_music", "YouTube Music"),
                "Apple Music": ("apple_music", "Apple Music"), "Spotify": ("spotify", "Spotify")}
        for i, name in enumerate(MEDIA_APPS):
            x, y = self.chip_origin(i)
            key, label = keys[name]
            icon = self.img(key)
            if icon:
                cv.create_image(x + 10, y + 18, image=icon, anchor="w")
            cv.create_text(x + 36, y + 18, text=label, fill=self.TEXT, font=self.F(9), anchor="w")

    def build_activity_card(self):
        """Game status: the current VALORANT state in large text and the last few game events."""
        cv = self.cv
        cv.create_text(712, 474, text=tr("Game status"), fill=self.TEXT, font=self.F(13, True), anchor="w")
        self.game_state_item = cv.create_text(712, 506, text="", anchor="w", font=self.F(15, True), fill=self.TEXT)
        cv.create_line(712, 529, 990, 529, fill=self.PANEL3)
        self.game_row_font = self.font_for(9)
        self.game_rows = [(cv.create_text(712, 551 + i * 22, text="", anchor="w", font=self.F(9), fill=self.MUTED),
                           cv.create_text(990, 551 + i * 22, text="", anchor="e", font=self.F(9), fill=self.FAINT))
                          for i in range(self.GAME_ROWS)]

    def game_sentence(self, key, action=None, history=False):
        """Short human sentence for a state, plus what VibePause did to the music when it acted."""
        text = tr((GAME_HISTORY_TEXT.get(key) if history else None) or GAME_STATES[key][0])
        action = str(action or "")
        if action == "Pause":
            text += " - " + tr("music paused")
        elif action == "Play":
            text += " - " + tr("music resumed")
        elif action.endswith("%"):
            text += " - " + tr("volume") + " " + action
        return text

    def ago_text(self, ts):
        secs = max(0, int(time.time() - ts))
        if secs < 60:
            return tr("just now")
        if secs < 3600:
            return tr("{n} min ago").replace("{n}", str(secs // 60))
        return time.strftime("%H:%M", time.localtime(ts))

    def set_game_state(self, key, action=None, record=False):
        self.game_state, self.game_action = key, action
        if record:
            self.game_events.append((time.time(), key, action))
            del self.game_events[:-20]
        self.refresh_game_ui()

    def effective_game_state(self):
        return "off" if not self.active else self.game_state

    def refresh_game_ui(self):
        """The one place the pill and the Game status card are drawn from, so they always agree."""
        if self.cv is None or not self.pill_items:
            return
        key = self.effective_game_state()
        # Pill on the music card
        paused = (self._paused_by_app and bool(self.np_key) and self.np_status != "playing"
                  and key not in ("waiting", "off"))
        if paused:
            text, color, tint = tr("Paused for your match"), self.RED, "pause"
        else:
            text = tr(GAME_STATES[key][1])
            color, tint = (self.GREEN, "play") if self.np_status == "playing" else (self.MUTED, "idle")
        self.cv.itemconfig(self.pill_items["text"], text=self.fit(text, self._pill_text_w, self._pill_font), fill=color)
        self.cv.itemconfig(self.pill_items["bg"], image=self.pill_bgs[tint])
        for item in self.pill_bars:
            self.cv.itemconfig(item, fill=color)
        self.bars_active = self.np_status == "playing"
        self.refresh_game_card(key)

    def refresh_game_card(self, key=None):
        key = key or self.effective_game_state()
        text = self.game_sentence(key, self.game_action if key == self.game_state else None)
        size = self.fit_size(text, 278, 15, True, 10)
        color = self.RED if key == "dead" else (self.MUTED if key in ("waiting", "off") else self.TEXT)
        self.cv.itemconfig(self.game_state_item, text=self.fit(text, self.sx(278), self.font_for(size, True)),
                           font=self.F(size, True), fill=color)
        newest = self.game_events[::-1][:self.GAME_ROWS]
        for i, (left, right) in enumerate(self.game_rows):
            if i < len(newest):
                ts, k, action = newest[i]
                when = self.ago_text(ts)
                room = self.sx(278) - self.game_row_font.measure(when) - self.sx(12)
                self.cv.itemconfig(left, text=self.fit(self.game_sentence(k, action, history=True), room, self.game_row_font),
                                   fill=self.TEXT if i == 0 else "#b4b2d6")
                self.cv.itemconfig(right, text=when)
            else:
                self.cv.itemconfig(left, text=tr("No game events yet") if (i == 0 and not newest) else "", fill=self.MUTED)
                self.cv.itemconfig(right, text="")

    def tick_game_times(self):
        """Keep "2 min ago" fresh while the window is on screen."""
        try:
            if self.root.winfo_viewable() and self.game_events:
                self.refresh_game_card()
            self.root.after(20000, self.tick_game_times)
        except tk.TclError:
            self._game_tick_running = False

    def animate_bars(self):
        """The one UI animation timer: the pill's mini equalizer and the spinning disc.
        About 22 fps while the window is visible; while it is hidden or minimized nothing is drawn and
        the timer only checks, slowly, whether it is visible again."""
        delay = 45
        try:
            if self.root.winfo_viewable():
                now = time.monotonic()
                self.tick_equalizer(now)
                self.tick_disc(now)
                self.kick_cover()
            else:
                self._disc_last_t = None
                delay = 400
        except tk.TclError:
            self._bars_running = False
            return
        except Exception as e:
            write_error_log(f"Animation: {type(e).__name__}: {e}")
        try:
            self.root.after(delay, self.animate_bars)
        except tk.TclError:
            pass

    def tick_equalizer(self, now):
        if not self.pill_bars:
            return
        if self.bars_active:
            for i, item in enumerate(self.pill_bars):
                half = 2 + 6 * abs(math.sin(now * 3.1 + i * 1.3)) * (0.6 + 0.4 * abs(math.sin(now * 1.1 + i)))
                self.cv.coords(item, self.pill_bar_x[i], self.pill_cy - half, self.pill_bar_x[i], self.pill_cy + half)
            self._eq_flat = False
        elif not self._eq_flat:
            for i, item in enumerate(self.pill_bars):
                self.cv.coords(item, self.pill_bar_x[i], self.pill_cy - 2, self.pill_bar_x[i], self.pill_cy + 2)
            self._eq_flat = True

    def tick_disc(self, now):
        """Advance the disc only while music is really playing; paused = frozen at the current angle."""
        if not (self.spin_cover and self._disc_ready and self._disc_tk and self.np_key and self.np_status == "playing"):
            self._disc_last_t = None
            return
        dt = 0.0 if self._disc_last_t is None else min(now - self._disc_last_t, 0.25)
        self._disc_last_t = now
        self._disc_angle = (self._disc_angle + dt * 360.0 / SPIN_PERIOD) % 360.0
        idx = int(self._disc_angle // DISC_STEP) % len(self._disc_tk)
        if idx != self._disc_idx:
            self._disc_idx = idx
            self.set_disc_image(self._disc_tk[idx])

    # ---- cover: render once per track, off the UI thread ----
    def begin_cover(self, key, thumb):
        """A new track (or its artwork arriving late): drop the old frames and prepare the new ones."""
        self._cover_gen += 1
        self._np_thumb = thumb
        self._disc_angle, self._disc_idx, self._disc_last_t = 0.0, 0, None
        self.set_disc_image(self.placeholder_photo())      # nothing may still show the images freed below
        self._disc_ready = False
        self._disc_tk, self._disc_pending, self._disc_static = [], [], None
        self._cover_job = (self._cover_gen, key, thumb) if key else None
        self.kick_cover()

    def kick_cover(self):
        job = self._cover_job
        if not job:
            return
        try:
            if not self.root.winfo_viewable():      # hidden in the tray: render when it is shown again
                return
        except tk.TclError:
            return
        self._cover_job = None
        gen, _key, thumb = job
        if gen == self._cover_gen:
            threading.Thread(target=self.cover_worker, args=(gen, thumb, self.spin_cover, self._disc_d), daemon=True).start()

    def cover_worker(self, gen, thumb, spin, d):
        """Background thread: PIL work only. PhotoImages are made on the UI thread."""
        try:
            sq = cover_frames_source(thumb, d) if thumb is not None else placeholder_cover(d)
            mask = disc_mask(d)
            self.event("disc_static", (gen, disc_frame(sq, mask, 0)))
            if not spin:
                return
            frames = []
            for i in range(DISC_FRAMES):
                if gen != self._cover_gen:
                    return
                frames.append(disc_frame(sq, mask, i * DISC_STEP))
            self.event("disc_frames", (gen, frames))
        except Exception as e:
            write_error_log(f"Cover render: {type(e).__name__}: {e}")

    def on_disc_static(self, gen, image):
        if gen != self._cover_gen:
            return
        self._disc_static = ImageTk.PhotoImage(image)
        if not self._disc_ready:
            self.set_disc_image(self._disc_static)

    def on_disc_frames(self, gen, frames):
        if gen != self._cover_gen or not self.spin_cover:
            return
        self._disc_pending, self._disc_tk = list(frames), []
        self.convert_frames(gen)

    def convert_frames(self, gen):
        """Turn rendered frames into PhotoImages a few at a time so the window never stalls."""
        if gen != self._cover_gen:
            return
        for _ in range(4):
            if not self._disc_pending:
                break
            self._disc_tk.append(ImageTk.PhotoImage(self._disc_pending.pop(0)))
        if self._disc_pending:
            self.root.after(8, lambda: self.convert_frames(gen))
        else:
            self._disc_ready = True
            self._disc_idx = 0

    def apply_spin_setting(self):
        """Spinning cover switched on or off while a track is shown."""
        self._cover_gen += 1                                # cancels any render in progress
        if not self.spin_cover:
            self._disc_ready = False
            if self._disc_static is not None:
                self.set_disc_image(self._disc_static)
            self._disc_tk, self._disc_pending = [], []      # frames freed; the static cover stays
        elif self.np_key:
            self._cover_job = (self._cover_gen, self.np_key, self._np_thumb)
            self.kick_cover()

    def set_spin_cover(self, on):
        self.spin_cover = bool(on)
        self.save()
        self.log_line("Spinning cover: " + ("on" if self.spin_cover else "off"))
        self.apply_spin_setting()

    # ---- now-playing data ----
    def apply_nowplaying(self, snap):
        status = snap.get("status", "none")
        title, artist = snap.get("title", ""), snap.get("artist", "")
        has = status != "none" and status != "unavailable" and (status in ("playing", "paused") or bool(title or artist))
        key = snap.get("key") if has else None
        prev_key = self.np_key
        self.np_key = key
        self.np_title_text, self.np_artist_text = (title, artist) if has else ("", "")
        self.np_status = status if (has or status == "unavailable") else "none"
        self.np_caps = (bool(snap.get("can_prev")), bool(snap.get("can_toggle")), bool(snap.get("can_next"))) if has else (False, False, False)
        if key != prev_key:
            self.begin_cover(key, snap.get("thumb"))
        elif key and snap.get("thumb") is not None:
            self.begin_cover(key, snap["thumb"])             # artwork arrived after the title
        if not key:
            self._paused_by_app = False                      # the player is gone: nothing left to resume
        elif self.np_status == "playing" and self._paused_by_app and time.monotonic() - self._paused_at > 2.0:
            self._paused_by_app = False                      # the person resumed it themselves
        self.refresh_np()
        self.refresh_game_ui()

    def refresh_np(self):
        if not self.np_btn:
            return
        if self.np_status == "unavailable":
            title, artist = tr("Media status unavailable"), ""
        elif self.np_key:
            title, artist = self.np_title_text or tr("Unknown track"), self.np_artist_text
        else:
            title, artist = tr("Nothing playing"), tr("Play something in a media app")
        width = self.sx(264)
        self.cv.itemconfig(self.np_title, text=self.fit(title, width, self._np_font_title),
                           fill=self.TEXT if self.np_key else self.MUTED)
        self.cv.itemconfig(self.np_artist, text=self.fit(artist, width, self._np_font_artist))
        self.refresh_np_buttons()

    def np_enabled(self, tag):
        index = {"np_prev": 0, "np_toggle": 1, "np_next": 2}[tag]
        return bool(self.np_key) and self.np_caps[index] and time.monotonic() >= self.np_flash_until

    def refresh_np_buttons(self):
        for tag, b in self.np_btn.items():
            kind = ("pause" if self.np_status == "playing" else "play") if tag == "np_toggle" else tag[3:]
            state = "dim" if not self.np_enabled(tag) else ("hot" if b["hover"] else "normal")
            self.cv.itemconfig(b["item"], image=b["imgs"][(kind, state)])

    def np_hover(self, tag, on):
        if tag in self.np_btn:
            self.np_btn[tag]["hover"] = on
            self.refresh_np_buttons()

    def np_press(self, tag):
        if not self.legal_accepted or self.np_busy or not self.np_enabled(tag):
            return
        action = {"np_prev": "prev", "np_toggle": "toggle", "np_next": "next"}[tag]
        if action == "toggle":
            self.controller.paused_by_us = False        # the person took over; don't resume it for them later
            self._paused_by_app = False
        self.np_busy = True
        threading.Thread(target=self.np_control_worker, args=(action,), daemon=True).start()

    def np_control_worker(self, action):
        try:
            ok = np_control(action)
        except Exception as e:
            write_error_log(f"Media control {action}: {type(e).__name__}: {e}")
            ok = False
        self.event("np_result", (action, ok))

    def on_np_result(self, action, ok):
        self.np_busy = False
        NP_WAKE.set()
        if not ok:      # False = the player refused it, None = no session any more
            self.log_line(f"Media control '{action}' was not accepted by the player")
            self.np_flash_until = time.monotonic() + 0.7
            self.refresh_np_buttons()
            self.root.after(750, self.refresh_np_buttons)

    def on_music_event(self, value):
        """VibePause itself paused or resumed the music (auto-pause during a match)."""
        if value == "Paused":
            self._paused_by_app, self._paused_at = True, time.monotonic()
            self.np_status = "paused" if self.np_key else self.np_status
        else:
            self._paused_by_app = False
            if self.np_key:
                self.np_status = "playing"
        NP_WAKE.set()
        self.refresh_np()
        self.refresh_game_ui()

    def start_media_watch(self):
        if self._media_watch_started:
            return
        self._media_watch_started = True
        threading.Thread(target=self.media_watch, daemon=True).start()

    def media_watch(self):
        """Watcher thread. Sleeps until a media event wakes it (or NP_POLL passes), asks the media loop
        for a snapshot, and tells the UI only when something changed. Artwork is read once per track."""
        if not GSMTC_AVAILABLE:
            self.event("nowplaying", {"status": "unavailable"})
            return
        st = {"key": None, "tries": 0, "thumb": False}

        def want_thumb(key):
            if key != st["key"]:
                return True
            return not st["thumb"] and st["tries"] < 6      # artwork often arrives a moment after the title

        last = None
        while True:
            NP_WAKE.clear()
            try:
                snap = MEDIA.run(_np_snapshot(want_thumb), timeout=10)
            except Exception as e:
                snap = None
                write_error_log(f"Now playing: {type(e).__name__}: {e}")
            if snap is not None:
                key = snap.get("key")
                if key != st["key"]:
                    st.update(key=key, tries=0, thumb=False)
                if snap.pop("thumb_tried", False):
                    st["tries"] += 1
                    st["thumb"] = snap.get("thumb") is not None
                sig = tuple(snap.get(k) for k in ("status", "key", "title", "artist", "can_prev", "can_toggle", "can_next"))
                if snap.get("thumb") is not None or sig != last:
                    last = sig
                    self.event("nowplaying", snap)
            NP_WAKE.wait(NP_POLL)
            time.sleep(0.15)                                # let a burst of events settle into one refresh

    def trash_photo(self):
        cache = self.__dict__.setdefault("_settings_cache", {})
        if "trash" not in cache:
            size = self.sx(18)
            big = size * 4
            img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            u = big / 18
            color = (255, 93, 143, 255)
            w = max(2, int(round(1.6 * u)))
            d.rounded_rectangle((3.5 * u, 5.5 * u, 14.5 * u, 6.8 * u), radius=0.6 * u, fill=color)
            d.rounded_rectangle((7 * u, 3.2 * u, 11 * u, 5.5 * u), radius=0.8 * u, outline=color, width=w)
            d.rounded_rectangle((4.8 * u, 7.2 * u, 13.2 * u, 15.6 * u), radius=1.6 * u, outline=color, width=w)
            for x in (7.6, 10.4):
                d.line((x * u, 9.4 * u, x * u, 13.4 * u), fill=color, width=max(2, int(round(1.2 * u))))
            cache["trash"] = self.photo(img.resize((size, size), Image.Resampling.LANCZOS))
        return cache["trash"]

    def warm_settings(self):
        if not self.settings_open:
            self.toggle_settings()
            self.close_settings()

    def toggle_settings(self):
        if self.settings_open:
            self.close_settings()
            return
        self.settings_open = True
        W, H = 330, 554
        x, y = self.WIN_W - 28 - W, 70
        cache = self.__dict__.setdefault("_settings_cache", {})
        if "base" not in cache:
            crop = self.scene_img.crop((self.sx(x), self.sx(y), self.sx(x) + self.sx(W), self.sx(y) + self.sx(H))).convert("RGBA")
            blurred = crop.filter(ImageFilter.GaussianBlur(self.sx(8)))
            mask = rounded_mask((self.sx(W), self.sx(H)), self.sx(26))
            base = Image.composite(blurred, crop, mask)
            base.alpha_composite(self.gi(W, H, 26, fill=(14, 14, 36, 205), border=(255, 255, 255, 70), sheen=14))
            cache["base"] = self.photo(base)
        cv = ScaledCanvas(self.root, self.S, width=self.sx(W), height=self.sx(H), bg=self.BG, bd=0, highlightthickness=0)
        cv.place(x=self.sx(x), y=self.sx(y))
        cv.create_image(0, 0, image=cache["base"], anchor="nw")
        self.settings_overlay = cv
        cv.create_text(24, 34, text=tr("Settings"), fill=self.TEXT, font=self.F(14, True), anchor="w")

        tray_label = cv.create_text(24, 82, text=tr("Close button sends to tray"), fill=self.TEXT, font=self.F(10),
                                    anchor="w", tags=("sw",), width=W - 24 - 40 - 24 - 10)
        switch = cv.create_image(W - 24 - 40, 71, image=self.switch_photo(bool(self.close_tray_var.get())), anchor="nw", tags=("sw",))
        cv.create_image(0, 56, image=self.photo_clear(self.sx(W), self.sx(52)), anchor="nw", tags=("sw",))

        def flip():
            self.close_tray_var.set(not self.close_tray_var.get())
            cv.itemconfig(switch, image=self.switch_photo(bool(self.close_tray_var.get())))
            self.set_close_to_tray()

        self.make_clickable("sw", flip, cv=cv)
        label_box = cv.bbox(tray_label)
        note_y = max(104, int(label_box[3] / self.S) + 5) if label_box else 104
        cv.create_text(24, note_y, text=tr("Off: the X button exits VibePause completely."), fill=self.MUTED,
                       font=self.F(9), anchor="nw", width=282)

        cv.create_text(24, 150, text=tr("Spinning cover"), fill=self.TEXT, font=self.F(10),
                                    anchor="w", tags=("sw2",), width=W - 24 - 40 - 24 - 10)
        spin_switch = cv.create_image(W - 24 - 40, 139, image=self.switch_photo(self.spin_cover), anchor="nw", tags=("sw2",))
        cv.create_image(0, 132, image=self.photo_clear(self.sx(W), self.sx(36)), anchor="nw", tags=("sw2",))

        def flip_spin():
            self.set_spin_cover(not self.spin_cover)
            cv.itemconfig(spin_switch, image=self.switch_photo(self.spin_cover))

        self.make_clickable("sw2", flip_spin, cv=cv)

        cv.create_text(24, 178, text=tr("Event delay"), fill=self.TEXT, font=self.F(10), anchor="w")
        self.delay_settings = tk.StringVar(value=str(self.delay))
        vcmd = (self.root.register(lambda v: v == "" or (v.isdigit() and len(v) <= 5)), "%P")
        entry = tk.Entry(cv, textvariable=self.delay_settings, width=9, bg=self.PANEL2, fg=self.TEXT,
                         insertbackground="white", relief="flat", bd=0, validate="key", validatecommand=vcmd,
                         selectbackground="#2f6fd6", selectforeground="white", font=self.F(11),
                         highlightthickness=1, highlightbackground=self.BORDER, highlightcolor=self.GREEN,
                         takefocus=True, exportselection=False)
        cv.create_window(24, 196, window=entry, anchor="nw", width=110, height=34)

        def select_all(e):
            e.widget.select_range(0, "end"); e.widget.icursor("end"); return "break"
        entry.bind("<Control-a>", select_all)
        entry.bind("<Control-A>", select_all)
        entry.bind("<Return>", lambda e: self.save_settings_page())
        entry.bind("<Button-1>", lambda e: e.widget.focus_set())
        def focus_entry():
            try:
                entry.focus_force()
                entry.select_range(0, "end")
            except tk.TclError:
                pass
        entry.after(50, focus_entry)
        cv.create_text(148, 213, text=tr("milliseconds"), fill=self.MUTED, font=self.F(9), anchor="w")

        def button(tag, top, label, command, fill, border, color, x=24, w=282, h=40, size=10):
            key = (tag, w, h)
            if key not in cache:
                cache[key] = (self.photo(self.gi(w, h, 16, fill=fill, border=border)),
                              self.photo(self.gi(w, h, 16, fill=fill[:3] + (fill[3] + 36,), border=border)))
            normal, hot = cache[key]
            bg = cv.create_image(x, top, image=normal, anchor="nw", tags=(tag,))
            txt = cv.create_text(x + w // 2, top + h // 2, text=label, fill=color,
                                 font=self.F(self.fit_size(label, w - 20, size, True), True), tags=(tag,))
            self.make_clickable(tag, command, lambda on: cv.itemconfig(bg, image=hot if on else normal), cv=cv)
            return txt

        # ---- Language ----
        def open_language_menu():
            menu = tk.Menu(self.root, tearoff=0, bg=self.PANEL2, fg=self.TEXT, activebackground=self.PANEL3,
                           activeforeground=self.TEXT, bd=0, relief="flat", font=self.F(10))
            for code, native in LANGUAGES:
                menu.add_command(label=("\u2713  " if code == self.language else "     ") + native,
                                 command=lambda c=code: self.root.after(10, lambda: self.set_language_choice(c)))
            try:
                menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
            finally:
                menu.grab_release()

        title_end = 24 + int(self.font_for(14, True).measure(tr("Settings")) / self.S)
        lang_w = max(96, min(150, W - 24 - title_end - 14 - 24))
        button("lang", 18, dict(LANGUAGES).get(self.language, "English") + " \u25be", open_language_menu,
               (255, 255, 255, 14), (255, 255, 255, 44), self.TEXT, x=W - 24 - lang_w, w=lang_w, h=30, size=9)

        # ---- Hotkey (off by default; can always be cleared) ----
        HK_HINT = "Click the box, then press Ctrl, Alt or Shift plus a key. Applies right away."
        cv.create_text(24, 258, text=tr("Hotkey: turn VibePause on/off"), fill=self.TEXT, font=self.F(10), anchor="w")
        hk = {"capturing": False}

        def show_hotkey():
            cv.itemconfig(hk_text, text=self.hotkey or tr("None"), fill=self.TEXT if self.hotkey else self.MUTED)

        def note(message, color=None):
            cv.itemconfig(hk_hint, text=message, fill=color or self.MUTED)

        def finish_capture():
            hk["capturing"] = False
            cv.unbind("<KeyPress>")
            if self.hotkey and not self.hotkeys.spec:
                self.hotkeys.start(self.hotkey)
            show_hotkey()

        def on_key(e):
            if e.keysym == "Escape":
                finish_capture()
                note(HK_HINT)
                return "break"
            if e.keysym in TK_MODIFIER_KEYSYMS:
                return "break"
            spec, problem = hotkey_from_event(e.state, e.keysym)
            if problem:
                note(problem, self.RED)
                return "break"
            ok, message = self.set_hotkey(spec)
            finish_capture()
            note(message, self.GREEN if ok else self.RED)
            return "break"

        def start_capture():
            if hk["capturing"]:
                return
            hk["capturing"] = True
            self.hotkeys.stop()      # so pressing the current combination doesn't toggle VibePause meanwhile
            cv.itemconfig(hk_text, text=tr("Press keys..."), fill=self.BLUE)
            note("Press the combination now. Esc cancels.")
            cv.bind("<KeyPress>", on_key)
            cv.focus_force()

        def clear_hotkey():
            if hk["capturing"]:
                hk["capturing"] = False
                cv.unbind("<KeyPress>")
            ok, message = self.set_hotkey("")
            show_hotkey()
            note(message, self.GREEN)

        hk_text = button("hk", 274, "", start_capture, (255, 255, 255, 14), (255, 255, 255, 44), self.TEXT, x=24, w=230, h=36)
        button("hkclear", 274, "", clear_hotkey, (255, 93, 143, 30), (255, 125, 170, 90), self.RED, x=262, w=44, h=36)
        cv.create_image(262 + 22, 274 + 18, image=self.trash_photo(), tags=("hkclear",))
        hk_hint = cv.create_text(24, 320, text=HK_HINT, fill=self.MUTED, font=self.F(8), anchor="nw", width=282)
        show_hotkey()

        # ---- Updates + support ----
        button("upd", 362, tr("Check for updates"), self.check_for_updates, (255, 255, 255, 18), (255, 255, 255, 50), self.TEXT)
        self.update_status_item = cv.create_text(24, 416, text=f"VibePause {APP_VERSION}", fill=self.MUTED,
                                                 font=self.F(8), anchor="nw", width=282)
        button("logdir", 452, tr("Open log folder"), self.open_log_folder, (255, 255, 255, 14), (255, 255, 255, 44),
               self.TEXT, x=24, w=137, h=36, size=9)
        button("diag", 452, tr("Copy diagnostics"), self.copy_diagnostics, (255, 255, 255, 14), (255, 255, 255, 44),
               self.TEXT, x=169, w=137, h=36, size=9)
        button("save", 498, tr("Save settings"), self.save_settings_page, (255, 93, 143, 62), (255, 125, 170, 125), self.RED)

    def check_for_updates(self):
        """Settings > CHECK FOR UPDATES. Runs the network work off the UI thread."""
        if self._update_busy:
            return
        self._update_busy = True
        self._set_update_status("Checking for updates...", self.BLUE)
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _set_update_status(self, text, color=None):
        if self.settings_open and hasattr(self, "update_status_item"):
            try:
                self.settings_overlay.itemconfig(self.update_status_item, text=text, fill=color or self.MUTED)
            except tk.TclError:
                pass

    def _check_for_updates_worker(self):
        try:
            result = check_for_update(APP_VERSION)
            if result[0] == "update":
                self.event("update", ("available",) + result[1:])
            else:
                self.event("update", ("current", result[1]))
        except UpdateError as e:
            self.event("update", ("error", str(e)))
        except Exception as e:
            write_error_log(f"Update check: {type(e).__name__}: {e}")
            self.event("update", ("error", "Can't check for updates right now. Try again later."))

    def handle_update_event(self, value):
        kind = value[0]
        if kind == "current":
            self._update_busy = False
            msg = f"No update found. VibePause {APP_VERSION} is the latest version."
            self._set_update_status(msg, self.GREEN)
            self.log_line(msg)
        elif kind == "available":
            self._update_busy = False
            _, latest, url, size, digest, notes = value
            self._set_update_status(f"Update found: VibePause {latest} is available.", self.GREEN)
            self.log_line(f"Update found: {latest} (current {APP_VERSION})")

            self.bring_forward()
            answer = messagebox.askyesno(
                "VibePause Update",
                self.update_prompt_text(latest, notes, "Download and install it now?", show_current=True),
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

    def bring_forward(self):
        try:
            if not self.root.winfo_viewable():
                self._show()
        except tk.TclError:
            pass

    def background_update_checker(self, stop):
        """Background thread for periodic update checks"""
        while not stop.is_set():
            try:
                current_time = time.time()
                if current_time - self.last_update_check >= UPDATE_CHECK_INTERVAL:
                    self.last_update_check = current_time
                    result = self._silent_check_for_updates()
                    if result is None:
                        # Back off 5m, 10m, 20m ... up to the normal 4h interval instead of
                        # hammering GitHub (and the log) every few minutes.
                        self._update_failures += 1
                        delay = min(UPDATE_CHECK_INTERVAL, UPDATE_RETRY_DELAY * 2 ** min(self._update_failures - 1, 10))
                        self.last_update_check = current_time - UPDATE_CHECK_INTERVAL + delay
                    else:
                        self._update_failures = 0
                        if result[0]:
                            self._pending_update = result[1:]

                if stop.is_set():
                    break
                pending = self._pending_update
                if (pending and pending[0] != self.declined_update and not self.valorant_running
                        and not self._update_busy):
                    self._pending_update = None
                    self.event("update_prompt", pending)

                # Wait interruptibly so shutdown wakes the checker immediately.
                if stop.wait(60):
                    break
            except Exception as e:
                write_error_log(f"Background update check: {type(e).__name__}: {e}")
                if stop.wait(60):
                    break

    def _silent_check_for_updates(self):
        """Silently check for updates. Returns (update_available, version, url, size, digest), or None if the check failed."""
        try:
            result = check_for_update(APP_VERSION)
            if result[0] == "update":
                return True, result[1], result[2], result[3], result[4], result[5]
            return False, result[1], "", 0, "", ""
        except Exception:
            return None

    def update_prompt_text(self, latest, notes, question, show_current=False):
        text = f"VibePause {latest} is available."
        if show_current:
            text += f"\n\nCurrent version: {APP_VERSION}\nNew version: {latest}"
        if notes:
            text += f"\n\nWhat's new:\n{notes}"
        return text + f"\n\n{question}"

    def _show_update_notification(self, version_info):
        """Show update notification when auto-update is enabled"""
        version, url, size, digest, notes = version_info
        self.bring_forward()
        result = messagebox.askyesno(
            "Update Available",
            self.update_prompt_text(version, notes, "Would you like to download and install it now?"),
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
            done, last_pct, ctype = 0, -1, ""
            with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as out:
                ctype = (resp.headers.get("Content-Type") or "").lower()
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
                write_error_log(f"Update download: received {done} bytes, expected {expected_size} "
                                f"(Content-Type: {ctype or 'unknown'})")
                if "text/html" in ctype:      # a web page (error or quota page), not the file
                    raise UpdateError("The download server sent a web page instead of the installer. Please try again later.")
                raise UpdateError("The downloaded installer is incomplete. Please try again.")
            verify_installer(path, digest)
            self.event("update", ("downloaded", path, latest))
        except UpdateError as e:
            self.discard_file(path)
            self.event("update", ("error", str(e)))
        except Exception as e:
            self.discard_file(path)
            write_error_log(f"Update download: {type(e).__name__}: {e}")
            self.event("update", ("error", "Update download failed. Try again later."))

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
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(f'ping -n 4 127.0.0.1 >nul & "{path}" /UPDATE', shell=True, close_fds=True,
                             creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
            self.complete_exit()   # stop monitoring, remove tray icon, quit so the installer can replace files
        except Exception as e:
            self._update_busy = False
            write_error_log(f"Launch installer: {type(e).__name__}: {e}")
            self._set_update_status("Could not start the installer.", self.RED)

    def start_auto_update_checker(self):
        """Start the background update checking thread"""
        if not self.legal_accepted:
            return
        if not self._auto_update_running:
            self._auto_update_running = True
            self._auto_update_stop = threading.Event()
            self.auto_update_thread = threading.Thread(
                target=self.background_update_checker,
                args=(self._auto_update_stop,),
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
        """True only if the user accepted the exact Terms and Privacy Policy text bundled now."""
        return read_settings().get(LEGAL_ACCEPTANCE_KEY) == legal_fingerprint()

    def save_legal_acceptance(self):
        """Record acceptance of the current documents, replacing any older acceptance."""
        d = read_settings()
        for k in [k for k in d if k.startswith("legal_accepted")]:
            del d[k]   # drop acceptances of earlier versions of the documents
        d[LEGAL_ACCEPTANCE_KEY] = legal_fingerprint()
        write_settings(d)

    def make_popup(self, w, h, *, track_attr=None, bind_raise=False, topmost=False):
        """Shared setup for a borderless popup window: creates the Toplevel, centers it over
        the main window (or the screen, if the main window isn't viewable yet), and returns
        (win, pw, ph) for the caller to draw into. Used by the language picker, Terms screen
        and exit confirm, which all look and behave the same way up to this point."""
        pw, ph = self.sx(w), self.sx(h)
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.configure(bg=self.BG)
        if topmost:
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
        if track_attr:
            setattr(self, track_attr, win)               # lets raise_legal_popup / re-open checks find it
        if bind_raise:
            self.root.bind("<FocusIn>", self.raise_legal_popup, add="+")
            self.root.bind("<Map>", self.raise_legal_popup, add="+")
        if self.root.winfo_viewable():
            win.transient(self.root)
            x = self.root.winfo_x() + (self.root.winfo_width() - pw) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - ph) // 2
        else:
            x = (win.winfo_screenwidth() - pw) // 2
            y = (win.winfo_screenheight() - ph) // 2
        win.geometry(f"{pw}x{ph}+{max(0, x)}+{max(0, y)}")
        return win, pw, ph

    def bind_popup_drag(self, win, cv, zone=84):
        """Lets the user drag a borderless popup by its top strip (the first `zone` px)."""
        def press(e):
            win._drag = (e.x_root - win.winfo_x(), e.y_root - win.winfo_y()) if e.y < self.sx(zone) else None

        def drag(e):
            if win._drag:
                win.geometry(f"+{e.x_root - win._drag[0]}+{e.y_root - win._drag[1]}")

        win._drag = None
        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)

    def show_language_popup(self, on_done):
        """First-run screen: choose the language. Styled like the Terms screen."""
        H = 470
        win, pw, ph = self.make_popup(560, H, track_attr="_legal_win", bind_raise=True)

        scene_photo = self.photo(render_aurora(pw, ph).convert("RGB"))
        cv = ScaledCanvas(win, self.S, width=pw, height=ph, bg=self.BG, bd=0, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=scene_photo, anchor="nw")
        cv.photos = [scene_photo]
        logo = self.img("vibepause_logo_32")
        if logo:
            cv.create_image(28, 40, image=logo, anchor="w")
        cv.create_text(72, 32, text="Choose your language", fill=self.TEXT, font=self.F(15, True), anchor="w")
        cv.create_text(72, 56, text="Idioma  \u00b7  Langue  \u00b7  Sprache  \u00b7  \u8a00\u8a9e  \u00b7  \u8bed\u8a00  \u00b7  \uc5b8\uc5b4",
                       fill=self.MUTED, font=self.F(9), anchor="w")

        self.bind_popup_drag(win, cv)

        def choose(code):
            self.language = code
            self.language_chosen = True
            set_language(code)
            self.save()
            self._legal_win = None
            win.destroy()
            self.rebuild_ui()                       # apply the language to the main window
            on_done()

        win.protocol("WM_DELETE_WINDOW", lambda: choose(self.language))
        bw, bh, gap = 160, 44, 12
        normal = self.photo(self.gi(bw, bh, 16, fill=(255, 255, 255, 14), border=(255, 255, 255, 44)))
        hot = self.photo(self.gi(bw, bh, 16, fill=(255, 255, 255, 44), border=(255, 255, 255, 90)))
        current = self.photo(self.gi(bw, bh, 16, fill=(47, 227, 198, 40), border=(80, 240, 215, 125)))
        for i, (code, native) in enumerate(LANGUAGES):
            left, top = 28 + (i % 3) * (bw + gap), 110 + (i // 3) * (bh + gap)
            tag = f"lang_{i}"
            is_current = code == self.language
            bg = cv.create_image(left, top, image=current if is_current else normal, anchor="nw", tags=(tag,))
            cv.create_text(left + bw // 2, top + bh // 2, text=native, fill=self.TEXT, font=self.F(10, True), tags=(tag,))
            self.make_clickable(tag, lambda c=code: choose(c),
                                lambda on, b=bg, n=(current if is_current else normal): cv.itemconfig(b, image=hot if on else n),
                                cv=cv)
        cv.create_text(28, H - 34, text="You can change this later in Settings.", fill=self.MUTED, font=self.F(9), anchor="w")

    def show_legal_popup(self):
        win, pw, ph = self.make_popup(640, 592, track_attr="_legal_win", bind_raise=True)
        # Whenever the user comes back to VibePause (Alt+Tab, taskbar, tray) bring the Terms forward.
        win.protocol("WM_DELETE_WINDOW", self.complete_exit)

        CARD = (28, 142, 612, 484)
        scene = render_aurora(pw, ph)
        scene.alpha_composite(self.gi(CARD[2] - CARD[0], CARD[3] - CARD[1], 22, fill=(16, 16, 40, 255),
                                      border=(255, 255, 255, 50), sheen=0), (self.sx(CARD[0]), self.sx(CARD[1])))
        scene_photo = self.photo(scene.convert("RGB"))
        cv = ScaledCanvas(win, self.S, width=pw, height=ph, bg=self.BG, bd=0, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=scene_photo, anchor="nw")

        logo = self.img("vibepause_logo_32")
        if logo:
            cv.create_image(28, 40, image=logo, anchor="w")
        cv.create_text(72, 32, text=tr("Before you start"), fill=self.TEXT, font=self.F(15, True), anchor="w")
        cv.create_text(72, 56, text=tr("Read both documents to the end to unlock I Agree."), fill=self.MUTED,
                       font=self.F(9), anchor="w")

        self.bind_popup_drag(win, cv)

        docs = {
            "terms": ("TERMS_AND_CONDITIONS.md", tr("Terms and Conditions")),
            "privacy": ("PRIVACY_POLICY.md", tr("Privacy Policy")),
        }
        read = {"terms": False, "privacy": False}
        current = {"doc": "terms"}

        TX, TY, TW, TH = CARD[0] + 14, CARD[1] + 12, 540, CARD[3] - CARD[1] - 24
        text_widget = tk.Text(cv, bg="#101028", fg="#c8c6e6", insertbackground="white", relief="flat", bd=0,
                              highlightthickness=0, font=self.F(10), wrap="word", padx=8, pady=6,
                              spacing1=2, spacing3=4, cursor="arrow", takefocus=False)
        cv.create_window(TX, TY, window=text_widget, anchor="nw", width=TW, height=TH)
        text_widget.tag_configure("h1", font=self.F(15, True), foreground="#f1efff", spacing1=4, spacing3=10)
        text_widget.tag_configure("h2", font=self.F(12, True), foreground="#f1efff", spacing1=14, spacing3=4)
        text_widget.tag_configure("h3", font=self.F(10, True), foreground="#f1efff", spacing1=10, spacing3=2)
        text_widget.tag_configure("bullet", lmargin1=14, lmargin2=28)

        track_x, track_y0, track_y1 = CARD[2] - 16, TY + 6, TY + TH - 6
        cv.create_line(track_x, track_y0, track_x, track_y1, width=4, capstyle="round", fill="#24244a", tags=("sb",))
        thumb = cv.create_line(track_x, track_y0, track_x, track_y1, width=4, capstyle="round", fill="#6f6d98", tags=("sb",))

        def tab_state():
            for key, item in tab_items.items():
                cv.itemconfig(item["bg"], image=tab_on if key == current["doc"] else tab_off)
                cv.itemconfig(item["text"], fill=self.TEXT if key == current["doc"] else self.MUTED)
                cv.itemconfig(item["tick"], text="✓" if read[key] else "")

        def refresh_ready():
            ok = all(read.values())
            cv.itemconfig(agree_bg, image=agree_on if ok else agree_off)
            cv.itemconfig(agree_text, fill=self.RED if ok else self.FAINT)
            if ok:
                cv.itemconfig(hint, text=tr("Thanks. You can accept now."), fill=self.GREEN)
            else:
                left = [docs[k][1] for k, v in read.items() if not v]
                cv.itemconfig(hint, text=tr("Still to read:") + " " + " / ".join(left), fill=self.MUTED)

        def on_scroll(first, last):
            first, last = float(first), float(last)
            span = track_y1 - track_y0
            y0 = track_y0 + first * span
            y1 = max(y0 + 28, track_y0 + last * span)
            cv.coords(thumb, track_x, y0, track_x, min(y1, track_y1))
            if last >= 0.995 and not read[current["doc"]]:
                read[current["doc"]] = True
                tab_state()
                refresh_ready()

        text_widget.config(yscrollcommand=on_scroll)

        def drag_bar(e):
            frac = (e.y / self.S - track_y0) / (track_y1 - track_y0)
            text_widget.yview_moveto(max(0.0, min(1.0, frac - 0.08)))

        cv.tag_bind("sb", "<Button-1>", drag_bar)
        cv.tag_bind("sb", "<B1-Motion>", drag_bar)

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

        def show_doc(which):
            current["doc"] = which
            filename, title = docs[which]
            text_widget.config(state="normal")
            text_widget.delete("1.0", "end")
            render_markdown(read_doc(filename, title))
            text_widget.config(state="disabled")
            text_widget.yview_moveto(0)
            tab_state()
            win.after(60, lambda: on_scroll(*text_widget.yview()))

        tab_on = self.photo(self.gi(268, 36, 18, fill=(255, 255, 255, 40), border=(255, 255, 255, 90)))
        tab_off = self.photo(self.gi(268, 36, 18, fill=(255, 255, 255, 12), border=(255, 255, 255, 36)))
        tab_items = {}
        for i, key in enumerate(("terms", "privacy")):
            left = 28 + i * 280
            tag = f"tab_{key}"
            bg = cv.create_image(left, 92, image=tab_off, anchor="nw", tags=(tag,))
            text = cv.create_text(left + 134, 110, text=docs[key][1], font=self.F(10, True), tags=(tag,))
            tick = cv.create_text(left + 248, 110, text="", fill=self.GREEN, font=self.F(11, True), tags=(tag,))
            tab_items[key] = {"bg": bg, "text": text, "tick": tick}
            self.make_clickable(tag, lambda k=key: show_doc(k), cv=cv)

        hint = cv.create_text(28, 506, text="", font=self.F(9), anchor="w")

        def button(tag, left, label, width, fill, border):
            normal = self.photo(self.gi(width, 44, 18, fill=fill, border=border))
            bg = cv.create_image(left, 528, image=normal, anchor="nw", tags=(tag,))
            text = cv.create_text(left + width // 2, 550, text=label, font=self.F(11, True), tags=(tag,))
            return normal, bg, text

        exit_img, exit_bg, exit_text = button("decline", 28, tr("Exit"), 130, (255, 255, 255, 14), (255, 255, 255, 44))
        cv.itemconfig(exit_text, fill=self.MUTED)
        self.make_clickable("decline", self.complete_exit, cv=cv)

        agree_off, agree_bg, agree_text = button("agree", 612 - 200, tr("I Agree"), 200, (255, 255, 255, 10), (255, 255, 255, 30))
        agree_on = self.photo(self.gi(200, 44, 18, fill=(255, 93, 143, 70), border=(255, 125, 170, 135)))

        def accept_legal():
            if not all(read.values()):
                return
            self.save_legal_acceptance()
            self._legal_win = None
            win.destroy()
            self.begin_operation()

        self.make_clickable("agree", accept_legal, cv=cv)
        show_doc("terms")
        refresh_ready()
        cv.photos = [scene_photo]

        def finish_setup():
            try:
                round_window(user32.GetParent(win.winfo_id()) or win.winfo_id(), pw, ph, self.sx(12)) if os.name == "nt" else None
                # No grab_set(): an app-wide grab blocked the tray menu and taskbar close, so if the
                # dialog ever ended up behind another window the app could not even be exited.
                win.attributes("-topmost", True)
                win.lift()
                win.focus_force()
            except tk.TclError:
                pass

        win.after(100, finish_setup)

    def close_settings(self):
        self.settings_open = False
        if hasattr(self, "settings_overlay"):
            self.settings_overlay.destroy()
        # Capturing a new hotkey pauses the current one; make sure it is back whenever Settings closes.
        if self.legal_accepted and self.hotkey and not self.hotkeys.spec:
            self.hotkeys.start(self.hotkey)

    def set_hotkey(self, spec):
        """Apply and save a new hotkey ('' = none). Returns (ok, message)."""
        previous = self.hotkey
        if spec and not self.hotkeys.start(spec):
            if previous:
                self.hotkeys.start(previous)    # keep the old one working
            return False, f"{spec} is already used by another program. Try a different combination."
        if not spec:
            self.hotkeys.stop()
        self.hotkey = spec
        self.save()
        return True, (f"Hotkey set to {spec}." if spec else "Hotkey cleared. VibePause has no hotkey.")

    def open_log_folder(self):
        try:
            APPDATA.mkdir(parents=True, exist_ok=True)
            os.startfile(str(APPDATA))
            self._set_update_status("Opened the VibePause folder (error.log and settings.json).", self.GREEN)
        except Exception as e:
            write_error_log(f"Open folder: {type(e).__name__}: {e}")
            self._set_update_status("Could not open the folder.", self.RED)

    def build_diagnostics(self):
        """Plain-text report the user can paste into a GitHub issue. Copied to the clipboard only,
        never sent anywhere. The Windows user name is removed from file paths."""
        def scrub(text):
            for home in {os.path.expanduser("~"), os.path.expanduser("~").replace("\\", "/")}:
                if home and home != "~":
                    text = re.sub(re.escape(home), "~", text, flags=re.I)
            return text

        try:
            error_tail = (APPDATA / "error.log").read_text(encoding="utf-8", errors="replace")[-3000:].strip()
        except OSError:
            error_tail = "(no error.log)"
        lines = [
            f"VibePause {APP_VERSION} ({'installed build' if getattr(sys, 'frozen', False) else 'running from source'})",
            f"Windows: {platform.platform()}",
            f"Display scale: {self.S}",
            f"VALORANT running: {self.valorant_running}",
            f"VALORANT log found: {LOG.exists()}",
            f"VibePause active: {self.active}",
            f"Game status: {self.effective_game_state()}",
            f"Event delay: {self.delay} ms | start with Windows: {self.startup} | close to tray: {self.close_to_tray} "
            f"| auto-update: {self.auto_update_enabled} | hotkey: {self.hotkey or 'none'}",
            "Actions: " + ", ".join(f"{k}={v}" for k, v in self.actions.items()),
            "",
            "Recent activity:",
            *(self.log_lines[-15:] or ["(none)"]),
            "",
            "error.log (last part):",
            error_tail,
        ]
        return scrub("\n".join(lines))

    def copy_diagnostics(self):
        try:
            text = self.build_diagnostics()
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            self._set_update_status("Diagnostics copied. Paste them into your GitHub issue.", self.GREEN)
        except Exception as e:
            write_error_log(f"Copy diagnostics: {type(e).__name__}: {e}")
            self._set_update_status("Could not copy diagnostics.", self.RED)

    def reset(self):
        self.actions = DEFAULT_ACTIONS.copy()
        for k, v in self.action_vars.items():
            v.set(self.actions[k])
            self.refresh_action(k, v)
        self.volumes = DEFAULT_VOLUMES.copy()
        for k in self.vol_widgets:
            self.refresh_volume(k)
        self.delay = 0
        self.save()
        self.log_line("Reset to default")

    def save_settings_page(self):
        self.delay = clean_delay(self.delay_settings.get())
        self.save()
        self.log_line("Settings saved")
        self.close_settings()

    def start_monitoring(self):
        if not self.legal_accepted:
            return
        self.actions = {k: v.get() for k, v in self.action_vars.items()}
        self.save()
        self.running = True
        self.set_game_state("open" if self.valorant_running else "waiting")   # the monitor restarts from scratch
        self.controller.start()
        self.status_update(True)
        self.log_line("VibePause started automatically")

    def stop_monitoring(self):
        self.running = False
        self.controller.stop()
        threading.Thread(target=self.release_music, daemon=True).start()
        self.status_update(False)
        self.log_line("VibePause stopped")

    def release_music(self):
        if self.controller.release():
            self.event("music", "Playing")

    def status_update(self, active=None):
        if not self.running:
            text, color = "Stopped", self.MUTED
        elif self.valorant_running:
            text, color = "VALORANT running", self.GREEN
        else:
            text, color = "VALORANT not running", self.MUTED
        self.cv.itemconfig(self.status_text, text=self.status_fit(tr(text)), fill=color)
        self.cv.itemconfig(self.status_dot, fill=color, outline=color)
        self.refresh_game_ui()
        self.update_tray()

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
                    self.event("cmd", "quit")
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
        elif kind == "update_prompt":
            self._show_update_notification(value)
        elif kind == "event":
            event, action = value
            if event in EVENT_STATES:
                self.set_game_state(EVENT_STATES[event], action, record=True)
            self.log_line(f"{now}  {tr(event)}  [{tr(action)}]")
        elif kind == "music":
            self.on_music_event(value)
            self.log_line(f"{now}  {tr('Music')}: {tr(value)}")
        elif kind == "nowplaying":
            self.apply_nowplaying(value)
        elif kind == "np_result":
            self.on_np_result(*value)
        elif kind == "disc_static":
            self.on_disc_static(*value)
        elif kind == "disc_frames":
            self.on_disc_frames(*value)
        elif kind == "volume":
            self.log_line(f"{now}  {tr('Volume')}: {value}%")
        elif kind == "valorant":
            running = bool(value)
            self.valorant_running = running
            previous, self._valorant_seen = self._valorant_seen, running
            if previous is None:
                if running:
                    self.set_game_state("open", record=True)
                else:
                    self.set_game_state("waiting")
            elif running != previous:
                self.set_game_state("open" if running else "waiting", record=True)
            self.status_update()
        else:
            text = f"{now}  {value}"
            if str(value).startswith("Manual:"):
                self.log_line(text)          # user-triggered: always show
            else:
                self.log_line_throttled(text)

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
                    msg = f"Internal error ({kind}): {type(e).__name__}: {e}"
                    write_error_log(msg)
                    try:
                        self.log_line(msg)
                    except Exception:
                        pass
        finally:
            self.root.after(80, self.process)

    _LOG_TS = re.compile(r"^\d{2}:\d{2}:\d{2}\s+")

    def log_line(self, text):
        # Everything lands here for "Copy diagnostics" (Recent activity); the window itself only shows
        # game events (Game status). Back-to-back identical lines (ignoring the timestamp) collapse
        # into one line with a counter, so a repeating failure shows as "... (x5)".
        key = self._LOG_TS.sub("", text)
        if self.log_lines and key == self._last_log_key:
            self._last_log_count += 1
            self.log_lines[-1] = f"{text} (x{self._last_log_count})"
        else:
            self._last_log_key, self._last_log_count = key, 1
            self.log_lines.append(text)
            del self.log_lines[:-200]

    LOG_THROTTLE = 300  # seconds before the same status/error message may appear again

    def log_line_throttled(self, text, cooldown=None):
        """Show an automatic status or error message at most once per cooldown window, even
        when other lines appear in between (e.g. "Waiting for Valorant..." alternating with
        "Monitoring Valorant..." or a failing monitor restarting over and over)."""
        key = self._LOG_TS.sub("", text)
        now = time.monotonic()
        seen = self.__dict__.setdefault("_throttled_logs", {})
        last = seen.get(key)
        if last is not None and now - last < (self.LOG_THROTTLE if cooldown is None else cooldown):
            return
        if len(seen) > 100:
            seen.clear()
        seen[key] = now
        self.log_line(text)

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
            pystray.MenuItem(tr("Open VibePause"), lambda icon, item: self.event("cmd", "open"), default=True),
            pystray.MenuItem(tr("Active"), lambda icon, item: self.event("cmd", "toggle_active"),
                             checked=lambda item: self.active),
            pystray.MenuItem(tr("Exit VibePause"), lambda icon, item: self.event("cmd", "exit")),
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
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def update_tray(self):
        icon = self.tray_icon
        if not icon:
            return
        if not self.running:
            label = tr("Stopped")
        elif self.valorant_running:
            label = tr("VALORANT running")
        else:
            label = tr("Waiting for VALORANT")
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
        popup = self.tray_popup
        self.tray_popup = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

    def show_tray_popup(self, px, py):
        self.close_tray_popup()
        W, H = 252, 200
        pw, ph = self.sx(W), self.sx(H)
        win = tk.Toplevel(self.root)
        self.tray_popup = win
        win.overrideredirect(True)
        win.configure(bg=self.BG)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = min(max(8, px - pw // 2), sw - pw - 8)
        y = py - ph - 14 if py > sh // 2 else py + 14
        y = min(max(8, y), sh - ph - 8)
        win.geometry(f"{pw}x{ph}+{x}+{y}")

        panel = render_aurora(pw, ph)
        panel.alpha_composite(self.gi(W, H, 8, fill=(255, 255, 255, 22), border=(255, 255, 255, 64)))
        photos = [ImageTk.PhotoImage(panel.convert("RGB"))]
        cv = ScaledCanvas(win, self.S, width=pw, height=ph, bg=self.BG, bd=0, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=photos[0], anchor="nw")

        logo = self.img("vibepause_logo_24")
        if logo:
            cv.create_image(18, 30, image=logo, anchor="w")
        cv.create_text(50, 24, text="VibePause", fill=self.TEXT, font=self.F(12, True), anchor="w")
        if not self.running:
            label, color = tr("Stopped"), self.MUTED
        elif self.valorant_running:
            label, color = tr("VALORANT running"), self.GREEN
        else:
            label, color = tr("Waiting for VALORANT"), self.MUTED
        cv.create_oval(50, 40, 58, 48, fill=color, outline=color)
        cv.create_text(65, 44, text=label, fill=color, font=self.F(9), anchor="w")
        cv.create_line(16, 62, W - 16, 62, fill="#4a4a7a")

        hover = ImageTk.PhotoImage(self.gi(W - 16, 38, 11, fill=(255, 255, 255, 34), border=(255, 255, 255, 0), sheen=0))
        photos.append(hover)

        def row(i, text, command, with_switch=False):
            top = 70 + i * 42
            tag = f"row{i}"
            shade = cv.create_image(8, top, image=hover, anchor="nw", state="hidden", tags=(tag,))
            cv.create_text(24, top + 19, text=text, fill=self.TEXT, font=self.F(11), anchor="w", tags=(tag,))
            if with_switch:
                cv.create_image(W - 24, top + 19, image=self.switch_photo(bool(self.active)), anchor="e", tags=(tag,))
            cv.create_image(8, top, image=self.photo_clear(self.sx(W - 16), self.sx(38)), anchor="nw", tags=(tag,))
            cv.tag_bind(tag, "<Enter>", lambda e: (cv.itemconfig(shade, state="normal"), cv.config(cursor="hand2")))
            cv.tag_bind(tag, "<Leave>", lambda e: (cv.itemconfig(shade, state="hidden"), cv.config(cursor="")))
            cv.tag_bind(tag, "<Button-1>", lambda e: (self.close_tray_popup(), command()))

        row(0, tr("Active"), lambda: self.set_active_from_tray(not self.active), with_switch=True)
        row(1, tr("Open VibePause"), self._show)
        row(2, tr("Exit VibePause"), self.confirm_exit)
        cv.photos = photos

        state = {"entered": False, "outside": 0, "age": 0}

        def watch():
            if self.tray_popup is not win:
                return
            try:
                mx, my = win.winfo_pointerxy()
                inside = win.winfo_rootx() <= mx <= win.winfo_rootx() + pw and win.winfo_rooty() <= my <= win.winfo_rooty() + ph
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
                round_window(handle, pw, ph, self.sx(8))
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
            self.confirm_exit()          # asked for by the person (tray menu)
        elif cmd == "quit":
            self.complete_exit()         # asked for by a second copy or the installer: no question

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
        self.raise_legal_popup()

    def raise_legal_popup(self, *_):
        """Keep the Terms dialog in front. It is a borderless window, so Windows does not
        bring it forward with the main window (no taskbar button / Alt+Tab entry of its own)."""
        win = self._legal_win
        if win is None:
            return
        try:
            if not win.winfo_exists():
                self._legal_win = None
                return
            win.deiconify()
            win.attributes("-topmost", True)
            win.lift()
            win.focus_force()
        except tk.TclError:
            self._legal_win = None

    def on_window_close(self):
        # Closing the app while the Terms are still unanswered counts as declining them.
        if not self.legal_accepted:
            self.complete_exit()
            return
        # "Close to Tray" ticked: hide to the tray. Unticked: quit completely.
        if self.close_to_tray and TRAY_AVAILABLE:
            self.hide_window()
        else:
            self.confirm_exit()

    def confirm_exit(self):
        """Ask "are you sure?" before quitting. Hiding to the tray never asks, and neither does a
        second copy or the installer asking this one to quit (that uses complete_exit directly)."""
        existing = self._quit_win
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass
        W, H = 440, 230
        win, pw, ph = self.make_popup(W, H, track_attr="_quit_win", topmost=True)

        scene = render_aurora(pw, ph)
        scene.alpha_composite(self.gi(W - 24, H - 24, 22, fill=(16, 16, 40, 235), border=(255, 255, 255, 50), sheen=10),
                              (self.sx(12), self.sx(12)))
        scene_photo = self.photo(scene.convert("RGB"))
        cv = ScaledCanvas(win, self.S, width=pw, height=ph, bg=self.BG, bd=0, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=scene_photo, anchor="nw")
        cv.photos = [scene_photo]
        logo = self.img("vibepause_logo_32")
        if logo:
            cv.create_image(36, 52, image=logo, anchor="w")
        cv.create_text(80, 52, text=tr("Quit VibePause?"), fill=self.TEXT, font=self.F(15, True), anchor="w")
        cv.create_text(36, 98, text=tr("VibePause will stop controlling your music until you open it again."),
                       fill=self.MUTED, font=self.F(10), anchor="nw", width=W - 72)

        def close_dialog():
            self._quit_win = None
            try:
                win.destroy()
            except tk.TclError:
                pass

        def quit_now():
            close_dialog()
            self.complete_exit()

        def make_button(tag, left, label, fill, border, color, command):
            bw, bh, top = 176, 44, H - 76
            normal = self.photo(self.gi(bw, bh, 18, fill=fill, border=border))
            hot = self.photo(self.gi(bw, bh, 18, fill=fill[:3] + (min(255, fill[3] + 36),), border=border))
            bg = cv.create_image(left, top, image=normal, anchor="nw", tags=(tag,))
            cv.create_text(left + bw // 2, top + bh // 2, text=label, fill=color, font=self.F(11, True), tags=(tag,))
            self.make_clickable(tag, command, lambda on: cv.itemconfig(bg, image=hot if on else normal), cv=cv)

        make_button("quit_cancel", 36, tr("Cancel"), (255, 255, 255, 14), (255, 255, 255, 44), self.TEXT, close_dialog)
        make_button("quit_ok", W - 36 - 176, tr("Quit"), (255, 93, 143, 62), (255, 125, 170, 125), self.RED, quit_now)
        win.bind("<Escape>", lambda e: close_dialog())
        win.bind("<Return>", lambda e: quit_now())
        win.protocol("WM_DELETE_WINDOW", close_dialog)
        win.lift()
        win.after(30, win.focus_force)

    def complete_exit(self):
        # Shutdown must be fast and must never wait on network I/O from the UI.
        self.controller.stop()
        releaser = threading.Thread(target=self.controller.release, daemon=True)
        releaser.start()
        releaser.join(2.5)
        self.stop_auto_update_checker()
        self.hotkeys.stop()

        if self.tray_icon:
            try:
                self.tray_icon.visible = False
                self.tray_icon.stop()
            except Exception:
                pass
            thread = self.tray_thread
            if thread is not None:
                thread.join(1.0)
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
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    user32.GetParent.restype = c_void_p;            user32.GetParent.argtypes = [c_void_p]
    user32.GetWindowLongPtrW.restype = c_ssize_t;   user32.GetWindowLongPtrW.argtypes = [c_void_p, c_int]
    user32.SetWindowLongPtrW.restype = c_ssize_t;   user32.SetWindowLongPtrW.argtypes = [c_void_p, c_int, c_ssize_t]
    user32.SetWindowPos.restype = c_int;            user32.SetWindowPos.argtypes = [c_void_p, c_void_p, c_int, c_int, c_int, c_int, c_uint]
    user32.SendMessageW.restype = c_ssize_t;        user32.SendMessageW.argtypes = [c_void_p, c_uint, c_size_t, c_void_p]
    user32.SetWindowRgn.restype = c_int;            user32.SetWindowRgn.argtypes = [c_void_p, c_void_p, c_int]
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