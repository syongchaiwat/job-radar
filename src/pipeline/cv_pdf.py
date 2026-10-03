"""Renders a CV draft (Markdown) to a styled A4 PDF.

Pipeline: Markdown -> structured HTML (this module) -> cv_style.css -> headless
Chrome --print-to-pdf. The layout rules (margins, fonts, sizes, gaps) live in
cv_style.css and were measured from the hand-made Canva CV, so tweaking the
look is a CSS edit, not a code change.

The drafts follow cv_template.md's shape, which plain Markdown can't express
visually (e.g. a date right-aligned on the title line), so this parses that
shape instead of generic Markdown:

    # Name                                  -> header, photo on the left
    Label: value · Label: value             -> contact lines, labels bolded
    ## Section                              -> section heading with a rule
    **Title** — Organisation                -> entry title (+ subtitle line)
    *Sep 2025 – Present*                    -> date, moved onto the title line
    Website: https://...                    -> small line
    - bullet / - **Label:** text            -> bullets (label styled per section)
    - **Award** (Org, Aug 2018): text.      -> Grants & Awards entry with date

Anything unrecognised falls back to normal Markdown rendering.
"""
import html
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STYLE_PATH = Path(__file__).resolve().parent / "cv_style.css"
PHOTO_PATH = REPO_ROOT / "cv_profile" / "photo.jpg"  # gitignored, optional
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

_md = MarkdownIt("commonmark", {"html": False})
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_DATE_LINE = re.compile(rf"^\*([^*]*\d{{4}}[^*]*|[^*]*Present[^*]*)\*$")
_DATE_TAIL = re.compile(rf"(?:{_MONTH}\s+)?\d{{4}}(?:\s*[–-]\s*(?:(?:{_MONTH}\s+)?\d{{4}}|Present))?$|{_MONTH}\s*[–-]\s*{_MONTH}\s+\d{{4}}$")
_AWARD = re.compile(r"^\*\*(.+?)\*\*\s*\((.+?)\):\s*(.+)$")


_LINKABLE = re.compile(r"(?<![\w/@.])((?:https?://|www\.)[^\s<]+[^\s<.,;)]|[\w.+-]+@[\w-]+\.[\w.-]+[a-z])")


def _inline(text: str) -> str:
    return _md.renderInline(text)


def _linked(text: str) -> str:
    """Inline Markdown plus bare URLs/emails as underlined links (contact + website lines)."""
    rendered = _inline(text)
    if "<a " in rendered:
        return rendered

    def link(m: re.Match) -> str:
        target = m.group(1)
        href = f"mailto:{target}" if "@" in target and "://" not in target else (
            target if target.startswith("http") else f"https://{target}")
        return f'<a href="{href}">{target}</a>'

    return _LINKABLE.sub(link, rendered)


def _date(text: str) -> str:
    # Canva CV style: plain hyphens in date ranges
    return html.escape(text.replace("–", "-").replace("—", "-"))


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_linked(it)}</li>" for it in items) + "</ul>"


def _header(name: str, contact_lines: list[str]) -> str:
    rows = []
    for line in contact_lines:
        parts = []
        for part in [p.strip() for p in line.split("·") if p.strip()]:
            label, sep, value = part.partition(":")
            if sep and len(label) < 25:
                parts.append(f"<span><b>{html.escape(label)}</b>: {_linked(value.strip())}</span>")
            else:
                parts.append(f"<span>{_linked(part)}</span>")
        rows.append(f'<div class="contact-row">{"".join(parts)}</div>')
    photo = ""
    if PHOTO_PATH.exists():
        photo = f'<img class="photo" src="{PHOTO_PATH.as_uri()}" alt="">'
    return (
        f'<header class="cv-header">{photo}<div>'
        f'<h1>{html.escape(name)}</h1>{"".join(rows)}</div></header>'
    )


def _entry(lines: list[str], section: str) -> str:
    """A block of non-bullet lines starting with **Title**: title row + extras."""
    title_line, rest = lines[0], lines[1:]
    date = ""
    subtitle_lines, small_lines, group_lines = [], [], []
    for line in rest:
        m = _DATE_LINE.match(line)
        if m and not date:
            date = _date(m.group(1))
        elif line.lower().startswith("website:"):
            small_lines.append(line)
        elif re.fullmatch(r"[*_]{1,3}[^*_]+:[*_]{1,3}", line):
            group_lines.append(line.strip("*_"))
        else:
            subtitle_lines.append(line)

    m = re.match(r"^\*\*(.+?)\*\*\s*(.*)$", title_line)
    title, after = (m.group(1), m.group(2)) if m else (title_line, "")
    after = after.strip()
    meta = ""
    if after.startswith(("—", "-", "–")):
        org = after.lstrip("—–- ").strip()
        if section == "education":
            subtitle_lines.insert(0, org)  # degree bold, institution on its own line
        else:
            title = f"{title} - {org}"
    elif after:
        meta = f' <span class="meta">{_linked(after)}</span>'

    out = [f'<div class="entry-head"><span class="entry-title">{_inline(title)}</span>{meta}'
           f'<span class="entry-date">{date}</span></div>']
    out += [f'<div class="entry-sub">{_inline(s)}</div>' for s in subtitle_lines]
    out += [f'<div class="entry-small">{_linked(s)}</div>' for s in small_lines]
    out += [f'<div class="entry-group">{_inline(g)}</div>' for g in group_lines]
    return "".join(out)


def _award(item: str) -> str | None:
    m = _AWARD.match(item)
    if not m:
        return None
    title, paren, text = m.groups()
    dm = _DATE_TAIL.search(paren)
    date = _date(dm.group(0)) if dm else ""
    org = paren[: dm.start()].rstrip(", ").strip() if dm else paren
    text = text.strip()
    text = text[:1].upper() + text[1:]
    if org:
        text = f"{text.rstrip('.')} ({org})."
    return (f'<div class="entry"><div class="entry-head"><span class="entry-title">{_inline(title)}</span>'
            f'<span class="entry-date">{date}</span></div><div class="entry-sub">{_inline(text)}</div></div>')


def markdown_to_html(markdown: str, density: int = 0) -> str:
    markdown = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)
    lines = [ln.rstrip() for ln in markdown.splitlines()]

    body: list[str] = []
    section = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("# "):
            contact = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("#"):
                if lines[i].strip():
                    contact.append(lines[i].strip())
                i += 1
            body.append(_header(line[2:].strip(), contact))
            continue

        if line.startswith("## "):
            if section:
                body.append("</section>")
            heading = line[3:].strip()
            section = re.sub(r"[^a-z]+", "-", heading.lower()).strip("-")
            body.append(f'<section class="{section}"><h2>{html.escape(heading)}</h2>')
            i += 1
            continue

        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            awards = [_award(it) for it in items] if "award" in section else []
            if awards and all(awards):
                body.extend(awards)
            else:
                body.append(_ul(items))
            continue

        block = []
        while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("#", "- ")):
            block.append(lines[i].strip())
            i += 1
        if block[0].startswith("**"):
            # entry: title block + the bullet list right after it, kept together
            entry = _entry(block, section)
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            bullets = ""
            if j < len(lines) and lines[j].strip().startswith("- "):
                items = []
                while j < len(lines) and lines[j].strip().startswith("- "):
                    items.append(lines[j].strip()[2:])
                    j += 1
                bullets = _ul(items)
                i = j
            body.append(f'<div class="entry">{entry}{bullets}</div>')
        elif re.fullmatch(r"[*_]{1,3}[^*_]+:[*_]{1,3}", block[0]) and len(block) == 1:
            body.append(f'<div class="entry-group">{_inline(block[0].strip("*_"))}</div>')
        else:
            body.append(f"<p>{_inline(' '.join(block))}</p>")

    if section:
        body.append("</section>")
    style = STYLE_PATH.read_text()
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link href="https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,400;0,500;0,700;1,400;1,700&display=block" rel="stylesheet">'
        f"<style>{style}</style></head><body class=\"density-{density}\">{''.join(body)}</body></html>"
    )


def _chrome() -> str:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    found = shutil.which("google-chrome") or shutil.which("chromium")
    if not found:
        raise RuntimeError("Google Chrome not found; it's needed to print the PDF.")
    return found


MAX_DENSITY = 3  # cv_style.css: .density-1 tighter gaps, -2 smaller text, -3 smaller top/bottom margins


def page_count(pdf_path: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", Path(pdf_path).read_bytes()))


def markdown_to_pdf(markdown: str, out_path: Path, max_pages: int | None = 2) -> Path:
    """Print the CV; if it runs past max_pages, retry at tighter densities.
    Falls back to the tightest version (and more pages) rather than cutting content."""
    for density in range(MAX_DENSITY + 1):
        _print(markdown_to_html(markdown, density), Path(out_path))
        if max_pages is None or page_count(out_path) <= max_pages:
            break
    return Path(out_path).resolve()


def _print(page_html: str, out_path: Path, timeout: float = 60) -> Path:
    out_path = Path(out_path).resolve()
    out_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "cv.html"
        html_path.write_text(page_html)
        proc = subprocess.Popen(
            [
                _chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                "--allow-file-access-from-files",
                "--virtual-time-budget=5000",  # let the Roboto webfont load before printing
                f"--user-data-dir={tmp}/profile",
                f"--print-to-pdf={out_path}",
                html_path.as_uri(),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Headless Chrome on macOS sometimes writes the PDF and then never exits,
        # so wait for a finished file (non-empty, size stable) instead of the process.
        try:
            deadline = time.monotonic() + timeout
            last_size = -1
            while time.monotonic() < deadline:
                if proc.poll() is not None and not out_path.exists():
                    raise RuntimeError("Chrome exited without writing the PDF.")
                size = out_path.stat().st_size if out_path.exists() else 0
                if size > 0 and size == last_size and out_path.read_bytes()[-1024:].rstrip().endswith(b"%%EOF"):
                    break
                last_size = size
                time.sleep(0.5)
            else:
                raise RuntimeError("Timed out waiting for Chrome to print the PDF.")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    return out_path
