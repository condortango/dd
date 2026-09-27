#!/usr/bin/env python3
"""Copy HTML notes into _site/ and refresh the README page list.

The README block between the pages markers is rewritten in place.
Anything outside that block is left alone.
"""

import html
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
README = ROOT / "README.md"
START = "<!-- pages:start -->"
END = "<!-- pages:end -->"
SKIP_DIRS = {".git", "_site", ".github"}


@dataclass(frozen=True)
class Note:
    rel: Path
    title: str
    date: str

    @property
    def url(self) -> str:
        return pages_base() + quote(self.rel.as_posix(), safe="/")

    @property
    def href(self) -> str:
        return quote(self.rel.as_posix(), safe="/")


def pages_base() -> str:
    override = os.environ.get("PAGES_BASE")
    if override:
        return override.rstrip("/") + "/"
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not match:
        raise SystemExit("set PAGES_BASE; origin is not a github.com repo")
    owner, repo = match.group(1), match.group(2)
    return f"https://{owner}.github.io/{repo}/"


def iter_notes():
    for path in sorted(ROOT.rglob("*.html")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        if rel.as_posix() == "index.html":
            continue
        yield path


def title_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if not match:
        return path.stem.replace("-", " ")
    raw = re.sub(r"\s+", " ", match.group(1)).strip()
    return html.unescape(raw)


def date_of(rel: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cs", "--", rel.as_posix()],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        out = ""
    if out:
        return out
    stamp = (ROOT / rel).stat().st_mtime
    return subprocess.check_output(
        ["date", "-u", "-d", f"@{int(stamp)}", "+%Y-%m-%d"], text=True
    ).strip()


def notes() -> list[Note]:
    found = [Note(path.relative_to(ROOT), title_of(path), "") for path in iter_notes()]
    dated = [Note(note.rel, note.title, date_of(note.rel)) for note in found]
    return sorted(dated, key=lambda note: (note.date, note.rel.as_posix()), reverse=True)


def copy_notes(items: list[Note]) -> None:
    if SITE.exists():
        for child in SITE.rglob("*"):
            if child.is_file():
                child.unlink()
    SITE.mkdir(parents=True, exist_ok=True)
    for note in items:
        src = ROOT / note.rel
        dest = SITE / note.rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())


def render_index(items: list[Note]) -> str:
    if items:
        rows = "\n".join(
            f'    <li><a href="{html.escape(note.href, quote=True)}">{html.escape(note.title)}</a>'
            f"<time>{html.escape(note.date)}</time></li>"
            for note in items
        )
    else:
        rows = "    <li>No notes yet.</li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dd</title>
<style>
  :root {{ --ink:#1b1f24; --muted:#5b6470; --rule:#c9ccd1; --accent:#0f2d52; --gold:#9a7b3f; --paper:#fbfaf7; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#e9e7e2; color:var(--ink); font-family: Georgia, "Times New Roman", serif; line-height:1.5; }}
  .page {{ max-width:720px; margin:40px auto; background:var(--paper); padding:48px 56px 40px; box-shadow:0 2px 18px rgba(0,0,0,.12); }}
  .mark {{ font-family: "Helvetica Neue", Arial, sans-serif; letter-spacing:.32em; text-transform:uppercase; font-size:13px; color:var(--accent); font-weight:700; }}
  .mark small {{ display:block; letter-spacing:.18em; color:var(--gold); font-weight:600; font-size:10.5px; margin-top:4px; }}
  h1 {{ font-size:28px; font-weight:normal; color:var(--accent); margin:22px 0 8px; }}
  p.dek {{ color:var(--muted); margin:0 0 28px; }}
  ul {{ list-style:none; padding:0; margin:0; }}
  li {{ border-top:1px solid var(--rule); padding:14px 0; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  time {{ display:block; font-family:"Helvetica Neue", Arial, sans-serif; font-size:12px; color:var(--muted); margin-top:4px; }}
</style>
</head>
<body>
<main class="page">
  <div class="mark">Condortango<small>Due diligence</small></div>
  <h1>Notes</h1>
  <p class="dek">Published from this repository on each push to main.</p>
  <ul>
{rows}
  </ul>
</main>
</body>
</html>
"""


def markdown_item(note: Note) -> str:
    title = note.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"- [{title}]({note.url}) ({note.date})"


def readme_block(items: list[Note]) -> str:
    body = "\n".join(markdown_item(note) for note in items) if items else "No notes yet."
    return f"{START}\n\n## Notes\n\n{body}\n\n{END}\n"


def fresh_readme(base: str, block: str) -> str:
    return f"# dd\n\nNotes published at <{base.rstrip('/')}>.\n\n{block}"


def update_readme(items: list[Note]) -> None:
    block = readme_block(items)
    if README.exists():
        current = README.read_text(encoding="utf-8")
        if START in current and END in current:
            pre, rest = current.split(START, 1)
            _, post = rest.split(END, 1)
            text = pre + block.rstrip("\n") + post
            if not text.endswith("\n"):
                text += "\n"
        else:
            if not current.endswith("\n"):
                current += "\n"
            text = current + "\n" + block
    else:
        text = fresh_readme(pages_base(), block)
    if README.exists() and README.read_text(encoding="utf-8") == text:
        print("README unchanged")
        return
    README.write_text(text, encoding="utf-8")
    print("README updated")


def main() -> None:
    items = notes()
    copy_notes(items)
    (SITE / "index.html").write_text(render_index(items), encoding="utf-8")
    update_readme(items)
    print(f"site: {pages_base()}")
    for note in items:
        print(f"  {note.date}  {note.rel.as_posix()}")


if __name__ == "__main__":
    main()
