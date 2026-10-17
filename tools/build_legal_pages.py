"""Build the website's legal pages from the Markdown sources, so the app and the website never drift apart.

    pip install markdown
    python tools/build_legal_pages.py

Sources                              ->  Pages
src/PRIVACY_POLICY.md                ->  docs/privacy.html
src/TERMS_AND_CONDITIONS.md          ->  docs/terms.html
COOKIE_POLICY.md                     ->  docs/cookies.html

Edit the Markdown, then run this script and commit the generated pages.
"""
import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://tanveer-exe.github.io/VibePause/"
PAGES = [
    ("src/PRIVACY_POLICY.md", "privacy.html", "Privacy Policy", "Privacy"),
    ("src/TERMS_AND_CONDITIONS.md", "terms.html", "Terms and Conditions", "Terms"),
    ("COOKIE_POLICY.md", "cookies.html", "Cookie Policy", "Cookies"),
]

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | VibePause</title>
<meta name="description" content="{title} for VibePause, the free and open-source Windows companion for VALORANT.">
<meta name="theme-color" content="#0a0a1c">
<link rel="canonical" href="{site}{filename}">
<link rel="icon" href="favicon.png">
<link rel="stylesheet" href="legal.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="wrap">
  <nav aria-label="Main">
    <a class="brand" href="index.html"><img src="logo.png" alt="">VibePause</a>
    <div class="navlinks">
{navlinks}
    </div>
  </nav>
  <main id="main">
    <article>
{body}
    </article>
  </main>
  <footer>
    <ul>
      <li><a href="index.html">Home</a></li>
      <li><a href="https://github.com/Tanveer-exe/VibePause">GitHub</a></li>
      <li><a href="https://github.com/Tanveer-exe/VibePause/issues">Contact (GitHub issues)</a></li>
    </ul>
    <p>VibePause is a free, non-commercial, open-source project by tanveer-exe (an individual, India). It isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. VALORANT and Riot Games are trademarks or registered trademarks of Riot Games, Inc.</p>
  </footer>
</div>
</body>
</html>
"""


def build():
    for src, out, title, label in PAGES:
        text = (ROOT / src).read_text(encoding="utf-8")
        # Make bare web addresses clickable (the Markdown stays plain so the app shows it as typed).
        text = re.sub(r'(?<![<"=/\w])(https?://[^\s<>)]+[^\s<>).,;:])', r'<\1>', text)
        body = markdown.markdown(text, extensions=["sane_lists"])
        body = "\n".join("      " + line if line else line for line in body.splitlines())
        links = []
        for _, o, _, lab in PAGES:
            cur = ' aria-current="page"' if o == out else ""
            links.append(f'      <a href="{o}"{cur}>{html.escape(lab)}</a>')
        page = TEMPLATE.format(title=html.escape(title), site=SITE, filename=out,
                               navlinks="\n".join(links), body=body.strip("\n"))
        (ROOT / "docs" / out).write_text(page, encoding="utf-8", newline="\n")
        print("wrote docs/" + out)


if __name__ == "__main__":
    build()
