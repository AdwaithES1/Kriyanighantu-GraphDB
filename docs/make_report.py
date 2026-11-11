"""Render docs/report.html to docs/report.pdf (A4).

Needs a Devanagari font; pass its folder and file if not on Windows:
  python docs/make_report.py [FONT_DIR] [FONT_FILE]     e.g.  /usr/share/fonts/truetype/noto NotoSansDevanagari-Regular.ttf
"""
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
FONT_DIR = sys.argv[1] if len(sys.argv) > 1 else "C:/Windows/Fonts"
FONT_FILE = sys.argv[2] if len(sys.argv) > 2 else "Nirmala.ttc"

CSS = f"""
@font-face {{ font-family: deva; src: url({FONT_FILE}); }}
* {{ font-family: sans-serif, deva; }}
body {{ font-size: 8.6pt; line-height: 1.32; color: #1d1d1f; }}
h1 {{ font-size: 16pt; margin: 0 0 2pt 0; color: #14365c; }}
.sub {{ font-size: 9.5pt; color: #555; margin: 0 0 6pt 0; }}
h2 {{ font-size: 10pt; color: #14365c; margin: 8pt 0 2pt 0; }}
p {{ margin: 0 0 4pt 0; }}
ol, ul {{ margin: 0 0 4pt 0; padding-left: 14pt; }}
li {{ margin: 0 0 1.5pt 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 2pt 0 5pt 0; }}
th, td {{ border: 0.5pt solid #b8c2cc; padding: 1.5pt 4pt; text-align: left; vertical-align: top; }}
th {{ color: #14365c; border-bottom: 1pt solid #14365c; }}
pre {{ font-family: monospace, deva; font-size: 7.6pt; border: 0.5pt solid #b8c2cc; padding: 4pt; margin: 2pt 0 5pt 0; }}
code {{ font-family: monospace; font-size: 7.8pt; }}
"""


def main():
    html = (HERE / "report.html").read_text(encoding="utf-8")
    story = pymupdf.Story(html=html, user_css=CSS, archive=pymupdf.Archive(FONT_DIR))
    page = pymupdf.paper_rect("a4")
    area = page + (46, 42, -46, -42)
    out = HERE / "report.pdf"
    writer = pymupdf.DocumentWriter(str(out))
    pages, more = 0, True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    print(f"{out} ({pages} pages)")


if __name__ == "__main__":
    main()
