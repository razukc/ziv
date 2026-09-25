"""Generate docs/social_preview.png — the 1280x640 GitHub social preview.

Branded card in the dev-band palette: Ziv wordmark, the tagline, the three
proof points, and the actual Z-I-V name mark drawn as braille dot grids
(dot patterns from the plan / generated timing spec — the same cells the
wrist plays as the prefix mark).

Run:  python tools/social_preview.py     (needs playwright + chromium)
Out:  docs/social_preview.png (1280x640)
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "social_preview.png"

#: Real braille dot grids for the name mark (dot numbering 1-6: left column
#: 1,3,5 top-to-bottom; right column 2,4,6). Matches the plan's Z-I-V spec.
CELLS = {
    "Z": {1, 3, 5, 6},
    "I": {2, 4},
    "V": {1, 2, 3, 6},
}

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ margin: 0; box-sizing: border-box; }}
  body {{
    width: 1280px; height: 640px; overflow: hidden;
    background: linear-gradient(135deg, #0e1116 0%, #101821 55%, #0d1a16 100%);
    color: #e8edf4; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 30px; text-align: center;
  }}
  .row {{ display: flex; align-items: center; gap: 56px; white-space: nowrap; }}
  .mark {{ display: flex; gap: 38px; }}
  .cell {{ display: grid; grid-template-columns: 52px 52px; gap: 16px; }}
  .dot {{
    width: 52px; height: 52px; border-radius: 50%;
    border: 3px solid #263041; background: transparent;
  }}
  .dot.on {{ background: #6ee7b7; border-color: #6ee7b7; box-shadow: 0 0 30px rgba(110,231,183,.5); }}
  .letter {{ text-align: center; color: #8b98ab; font-size: 28px; margin-top: 12px; letter-spacing: 2px; }}
  h1 {{ font-size: 150px; letter-spacing: 10px; font-weight: 700; }}
  .tag {{ font-size: 48px; font-weight: 600; white-space: nowrap; }}
  .tag em {{ color: #6ee7b7; font-style: normal; }}
  .proofs {{ font-size: 27px; color: #8b98ab; white-space: nowrap; }}
  .proofs b {{ color: #e8edf4; font-weight: 600; }}
  .judges {{ font-size: 25px; color: #6ee7b7; white-space: nowrap; }}
</style></head>
<body>
  <div class="row">
    <div class="mark">{cells}</div>
    <h1>Ziv</h1>
  </div>
  <div class="tag">Messages you can feel. <em>Nobody else can see.</em></div>
  <div class="proofs"><b>speech in, vibro-braille out</b> &nbsp;·&nbsp; queue-don't-interrupt &nbsp;·&nbsp; durable schedule &nbsp;·&nbsp; one timing source</div>
  <div class="judges">judges: JUDGE_REPRO.md — every claim, proven</div>
</body></html>
"""


def cells_html() -> str:
    blocks = []
    for letter, dots in CELLS.items():
        dots_html = []
        for n in range(1, 7):
            cls = "dot on" if n in dots else "dot"
            dots_html.append(f'<div class="{cls}"></div>')
        blocks.append(
            '<div><div class="cell">' + "".join(dots_html) + "</div>"
            f'<div class="letter">{letter}</div></div>'
        )
    return "".join(blocks)


def main() -> int:
    html = HTML.format(cells=cells_html())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 640})
        page.set_content(html)
        page.screenshot(path=str(OUT))
        browser.close()
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
