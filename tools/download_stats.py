#!/usr/bin/env python3
"""Record the installer's total GitHub download count once a day and redraw docs/downloads.svg.

No third-party packages. Run by .github/workflows/download-stats.yml.
Data lives in docs/downloads.csv (one row per UTC day: date,downloads).
"""
import csv
import datetime as dt
import json
import math
import os
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

REPO = os.environ.get("GITHUB_REPOSITORY", "Tanveer-exe/VibePause")
ASSET = "VibePause_Setup.exe"
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "docs" / "downloads.csv"
SVG_PATH = ROOT / "docs" / "downloads.svg"


def fetch_total():
    """Sum the download count of the installer across all published releases."""
    total, page = 0, 1
    while True:
        url = f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "vibepause-download-stats"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            releases = json.load(r)
        if not releases:
            return total
        for rel in releases:
            if rel.get("draft"):
                continue
            for asset in rel.get("assets", []):
                if asset.get("name") == ASSET:
                    total += int(asset.get("download_count") or 0)
        page += 1


def load_rows():
    if not CSV_PATH.exists():
        return {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {r["date"]: int(r["downloads"]) for r in csv.DictReader(f)}


def save_rows(rows):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["date", "downloads"])
        for d in sorted(rows):
            w.writerow([d, rows[d]])


def nice_step(top, ticks=4):
    raw = max(top, 1) / ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def build_svg(rows):
    W, H = 720, 280
    L, R, T, B = 56, 24, 64, 40
    pts = sorted(rows.items())
    n = len(pts)
    latest = pts[-1][1] if pts else 0
    step = nice_step(max([v for _, v in pts] + [1]))
    ymax = step * math.ceil(max([v for _, v in pts] + [1]) / step)
    pw, ph = W - L - R, H - T - B

    def x(i):
        return L + (pw / 2 if n == 1 else pw * i / (n - 1))

    def y(v):
        return T + ph - ph * v / ymax

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-labelledby="t d" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
        f'<title id="t">VibePause installer downloads over time</title>',
        f'<desc id="d">Line chart of total installer downloads. Latest total: {latest:,}.</desc>',
        f'<rect width="{W}" height="{H}" rx="14" fill="#0f1923"/>',
        f'<text x="{L}" y="30" font-size="16" font-weight="600" fill="#ece8e1">Installer downloads</text>',
        f'<text x="{L}" y="50" font-size="12" fill="#9aa7b2">Total so far: {latest:,}'
        + (f' &#183; updated {escape(pts[-1][0])} (UTC)' if pts else "") + '</text>',
    ]
    v = 0
    while v <= ymax:
        yy = y(v)
        out.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W - R}" y2="{yy:.1f}" stroke="#ffffff" stroke-opacity="0.08"/>')
        out.append(f'<text x="{L - 8}" y="{yy + 4:.1f}" font-size="11" text-anchor="end" fill="#9aa7b2">{int(v):,}</text>')
        v += step
    if n >= 2:
        path = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
        out.append(f'<polygon points="{L},{T + ph} {path} {x(n - 1):.1f},{T + ph}" fill="#3ddbc4" fill-opacity="0.12"/>')
        out.append(f'<polyline points="{path}" fill="none" stroke="#3ddbc4" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
    out.append(f'<circle cx="{x(n - 1):.1f}" cy="{y(latest):.1f}" r="4" fill="#3ddbc4"/>')
    if n >= 1:
        out.append(f'<text x="{x(0):.1f}" y="{H - 14}" font-size="11" text-anchor="{"middle" if n == 1 else "start"}" fill="#9aa7b2">{escape(pts[0][0])}</text>')
    if n >= 2:
        out.append(f'<text x="{x(n - 1):.1f}" y="{H - 14}" font-size="11" text-anchor="end" fill="#9aa7b2">{escape(pts[-1][0])}</text>')
    if n < 2:
        out.append(f'<text x="{W / 2}" y="{T + ph / 2}" font-size="13" text-anchor="middle" fill="#9aa7b2">Collecting data. The line appears after the second daily update.</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    rows = load_rows()
    rows[dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")] = fetch_total()
    save_rows(rows)
    SVG_PATH.write_text(build_svg(rows), encoding="utf-8")
    print(f"Recorded {max(rows.values()):,} total downloads over {len(rows)} day(s).")


if __name__ == "__main__":
    main()
