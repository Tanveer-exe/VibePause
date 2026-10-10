# PyInstaller spec: one-folder build (fast start, fewer antivirus false positives
# than --onefile). Assets are bundled and resolved via sys._MEIPASS at runtime.
from PyInstaller.utils.hooks import collect_all
datas = [
    ("assets", "assets"),
    ("VibePause.ico", "."),
    ("TERMS_AND_CONDITIONS.md", "."),
    ("PRIVACY_POLICY.md", "."),
    ("lang", "lang"),
]
binaries, hiddenimports = [], ["pystray._win32"]
for pkg in ("pystray", "PIL", "winrt.runtime", "winrt.windows.media.control",
            "winrt.windows.foundation", "winrt.windows.foundation.collections",
            "pycaw", "comtypes", "psutil"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(["VibePause.pyw"], pathex=[], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VibePause",
          console=False, icon="VibePause.ico", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="VibePause", upx=False)
