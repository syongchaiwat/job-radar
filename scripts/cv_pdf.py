"""Render a CV draft (.md) to a styled A4 PDF next to it.

Usage:
    python scripts/cv_pdf.py cv_drafts/<draft>.md            # writes cv_drafts/<draft>.pdf
    python scripts/cv_pdf.py cv_drafts/<draft>.md --html     # also writes the HTML, for tweaking the CSS

Layout rules live in src/cv/style.css. Photo: cv_profile/photo.jpg (optional, gitignored).
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.cv.pdf import markdown_to_html, markdown_to_pdf, page_count  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--html", action="store_true", help="Also write the intermediate HTML")
    parser.add_argument("--max-pages", type=int, default=2, help="Tighten spacing to fit this many pages (0 = no limit)")
    args = parser.parse_args()

    markdown = args.draft.read_text()
    if args.html:
        args.draft.with_suffix(".html").write_text(markdown_to_html(markdown))
    out = markdown_to_pdf(markdown, args.draft.with_suffix(".pdf"), max_pages=args.max_pages or None)
    print(f"Wrote {out} ({page_count(out)} pages)")


if __name__ == "__main__":
    main()
