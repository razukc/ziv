"""Generate docs/devpost_thumbnail.png — the Devpost Project-overview thumbnail.

The same branded card as docs/social_preview.png (social_preview.py), re-set
for Devpost's overview step: 3:2 (their recommended ratio) at 1500x1000, and
with the stack line — Nemotron-3-Nano-Omni on Nebius Token Factory — spelled
out, per the organizers' tip to make the required tools impossible to miss.

Run:  python tools/devpost_thumbnail.py     (needs playwright + chromium)
Out:  docs/devpost_thumbnail.png (1500x1000)
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "devpost_thumbnail.png"

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
    width: 1500px; height: 1000px; overflow: hidden;
    background: linear-gradient(135deg, #0e1116 0%, #101821 55%, #0d1a16 100%);
    color: #e8edf4; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 44px; text-align: center;
  }}
  .row {{ display: flex; align-items: center; gap: 64px; white-space: nowrap; }}
  .mark {{ display: flex; gap: 44px; }}
  .cell {{ display: grid; grid-template-columns: 60px 60px; gap: 18px; }}
  .dot {{
    width: 60px; height: 60px; border-radius: 50%;
    border: 3px solid #263041; background: transparent;
  }}
  .dot.on {{ background: #6ee7b7; border-color: #6ee7b7; box-shadow: 0 0 34px rgba(110,231,183,.5); }}
  .letter {{ text-align: center; color: #8b98ab; font-size: 32px; margin-top: 14px; letter-spacing: 2px; }}
  h1 {{ font-size: 170px; letter-spacing: 12px; font-weight: 700; }}
  .tag {{ font-size: 58px; font-weight: 600; white-space: nowrap; }}
  .tag em {{ color: #6ee7b7; font-style: normal; }}
  .stack {{ font-size: 34px; color: #8b98ab; white-space: nowrap; }}
  .stack b {{ color: #e8edf4; font-weight: 600; }}
</style></head>
<body>
  <div class="row">
    <div class="mark">{cells}</div>
    <h1>Ziv</h1>
  </div>
  <div class="tag">Messages you can feel. <em>Nobody else can see.</em></div>
  <div class="stack"><b>Nemotron-3-Nano-Omni</b> on <b>Nebius Token Factory</b> — speech in, vibro-braille out</div>
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
        page = browser.new_page(viewport={"width": 1500, "height": 1000})
        page.set_content(html)
        page.screenshot(path=str(OUT))
        browser.close()
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
