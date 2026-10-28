#!/usr/bin/env python3
"""
Render the Devpost gallery media for Ziv:
  1. hero.svg      -> hero.png (JPG later for upload-compression pass)
  2. flow.png      - sender -> relay model -> audio cue on the wrist
  3. haptics.png   - the turn lifecycle as felt on the phone
  4. architecture.png - wrist device + wearer-hosted relay + memory
  5. proof.png     - hermetic tests + drift guard
  6. honesty.png   - what is built vs next revision
All captions/titles live in GALLERY at the top. Post-render we print a
copy-paste block for the Devpost gallery.
"""
from __future__ import annotations

import base64
import io
import math
import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = HERE  # media/*.png next to this script

# ----------------------------------------------------------------  palette
BG      = "#0e1116"
PANEL   = "#161c24"
LINE    = "#263041"
FG      = "#e8edf4"
DIM     = "#8b98ab"
ACCENT  = "#6ee7b7"
WARN    = "#fbbf24"
RED     = "#f87171"
BLUE    = "#60a5fa"
TEAL    = "#2dd4bf"

# ----------------------------------------------------------------  base svg
def _hbitems(scale):
    return [
        ("credit-card",  "wave-fin", "bear", "wind-streak"),
        ("credit-card",  "truck-front", "whale", "wind-streak"),
        ("credit-card",  "laptop", "tortoise", "wind-streak"),
        ("credit-card",  "map", "deer", "wind-streak"),
        ("credit-card",  "compass", "swan", "wind-streak"),
        ("credit-card",  "hat-cowboy", "hedgehog", "wind-streak"),
        ("credit-card",  "calendar", "rabbit", "wind-streak"),
        ("credit-card",  "bell", "fox", "wind-streak"),
    ]

def svg_hero(title_text, sub_text, dark=True):
    """One inline SVG: title band over the Ziv device banner."""
    bg = "#0b0e12" if dark else "#f5f7fa"
    panel = "#171c23" if dark else "#ffffff"
    fg = "#e8edf4" if dark else "#0f141b"
    dim = "#8b98ab" if dark else "#5c6b7d"
    accent = "#6ee7b7"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900"
     viewBox="0 0 1400 900" text-rendering="geometricPrecision" font-family="system-ui,-apple-system,'Segoe UI',sans-serif">
  <rect x="0" y="0" width="1400" height="900" fill="{bg}"/>

  <!-- title band -->
  <rect x="0" y="0" width="1400" height="360" fill="{panel}"/>
  <rect x="0" y="360" width="1400" height="2" fill="{accent}"/>

  <text x="80" y="240" font-size="96" font-weight="800" fill="{fg}" letter-spacing="-1">
    {title_text}
  </text>
  <text x="80" y="312" font-size="34" fill="{dim}">
    {sub_text}
  </text>
  <text x="80" y="348" font-size="22" fill="{accent}">
    Wearable AI you feel, not read
  </text>

  <!-- tag chip -->
  <g transform="translate(1180,210)">
    <rect x="0" y="0" width="200" height="120" rx="16" fill="{bg}"/>
    <rect x="12" y="12" width="176" height="96" rx="10" fill="{accent}" opacity="0.12"/>
    <text x="100" y="52" font-size="30" font-weight="700" fill="{accent}" text-anchor="middle">ZIV</text>
    <text x="100" y="86" font-size="18" fill="{dim}" text-anchor="middle">dev band prototype</text>
  </g>

  <!-- device graphic: curved wrist band with braille cell -->
  <g transform="translate(700,640)">
    <path d="M -260 0 q 260 -180 520 0" stroke="{fg}" stroke-width="6"
          fill="none" stroke-linecap="round" opacity="0.5"/>
    <rect x="-280" y="-36" width="560" height="72" rx="36" fill="{panel}"
          stroke="{LINE}" stroke-width="2"/>
    <rect x="-270" y="-26" width="540" height="52" rx="26" fill="{bg}"/>

    <!-- braille cells across the band -->
    <g font-size="30" text-anchor="middle" fill="{accent}" font-weight="700">
      <circle cx="-180" cy="0" r="22" fill="{BG}" stroke="{accent}" stroke-width="2"/>
      <circle cx="-60"  cy="0" r="22" fill="{BG}" stroke="{WARN}" stroke-width="2"/>
      <circle cx="60"   cy="0" r="22" fill="{BG}" stroke="{RED}" stroke-width="2"/>
      <circle cx="180"  cy="0" r="22" fill="{bg}" stroke="{accent}" stroke-width="2" opacity="0.4"/>
    </g>

    <!-- toggle + caret -->
    <rect x="220" y="-18" width="46" height="36" rx="8" fill="{accent}" opacity="0.12"/>
    <circle cx="244" cy="0" r="12" fill="{accent}"/>
    <path d="M 0 -6 l 18 12 l -18 12 z" fill="{fg}"/>
  </g>

  <text x="700" y="770" font-size="24" fill="{dim}" text-anchor="middle">
    Vibro-braille: a private message you feel as a timed buzzing pattern
  </text>
</svg>"""
    return svg

def svg_flow():
    """Sender -> relay -> phone. Three stages with arrows."""
    cols = [
        ("1", "SENDER", "A typed message,\nor a scheduled intent", FG, DIM),
        ("2", "RELAY", "One turn, end to end.\nA scheduled intent is\ncomposed by Nemotron first.", ACCENT, BG),
        ("3", "PHONE", "Either way, the reply\nfeels like timed braille", WARN, BG),
    ]
    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" '
        f'viewBox="0 0 1400 900" text-rendering="geometricPrecision" '
        f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">')

    parts.append(f'<rect x="0" y="0" width="1400" height="900" fill="{BG}"/>')

    x_cursor = 60
    card_w = 340
    for num, name, body, fg, sub in cols:
        x = x_cursor
        y = 300
        parts.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="300" rx="20" '
                     f'fill="{PANEL}" stroke="{LINE}"/>')
        parts.append(f'<rect x="{x+12}" y="{y+12}" width="{card_w-24}" height="60" '
                     f'rx="12" fill="{sub}"/>')
        parts.append(f'<text x="{x+card_w/2}" y="{y+48}" font-size="30" font-weight="800" '
                     f'fill="{fg}" text-anchor="middle">{num}</text>')
        parts.append(f'<text x="{x+card_w/2}" y="{y+96}" font-size="30" font-weight="700" '
                     f'fill="{FG}" text-anchor="middle">{name}</text>')
        # body lines
        for i, line in enumerate(body.split("\n")):
            parts.append(f'<text x="{x+card_w/2}" y="{y+150 + i*44}" font-size="24" '
                         f'fill="{DIM}" text-anchor="middle">{line}</text>')
        if num != "3":
            # arrow
            ax = x + card_w + 30
            ay = y + 150
            parts.append(f'<circle cx="{ax}" cy="{ay}" r="10" fill="{ACCENT}"/>')
            parts.append(f'<line x1="{x+card_w}" y1="{ay}" x2="{ax+30}" y2="{ay}" '
                         f'stroke="{ACCENT}" stroke-width="3"/>')
        x_cursor += card_w + 80

    parts.append('<text x="700" y="770" font-size="28" fill="DIM" text-anchor="middle">'
                 'A typed message goes one path: the relay, one turn, the phone.</text>')
    parts.append('</svg>')
    return "".join(parts)

def svg_haptics():
    """Turn lifecycle on the phone: cue -> processing ticks -> cells -> close."""
    seq = [
        ("1", "ARRIVAL CUE",  "the name mark, then a\nshort double tap", ACCENT),
        ("2", "PROCESSING",   "a soft repeating tick\nwhile the relay works", TEAL),
        ("3", "SPELLING",     "braille, the layer\nfor readers", WARN),
        ("4", "CLOSE",        "the end beat:\nthe turn is done", RED),
        ("5", "QUEUED",       "if the phone is busy,\nyour message waits its turn", BLUE),
    ]
    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" '
        'viewBox="0 0 1400 900" text-rendering="geometricPrecision" '
        'font-family="system-ui,-apple-system,Segoe UI,sans-serif">')
    parts.append(f'<rect x="0" y="0" width="1400" height="900" fill="{BG}"/>')

    x_cursor = 40
    card_w = 220
    gap = 60
    for num, name, body, color in seq:
        x = x_cursor
        y = 320
        parts.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="260" rx="20" '
                     f'fill="{PANEL}" stroke="{LINE}"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="56" rx="20" '
                     f'fill="{color}"/>')
        parts.append(f'<rect x="{x}" y="{y+18}" width="{card_w}" height="38" '
                     f'fill="{color}" opacity="0.3"/>')
        parts.append(f'<text x="{x+card_w/2}" y="{y+42}" font-size="26" font-weight="800" '
                     f'fill="{BG}" text-anchor="middle">{num}</text>')
        parts.append(f'<text x="{x+card_w/2}" y="{y+118}" font-size="26" font-weight="700" '
                     f'fill="{FG}" text-anchor="middle">{name}</text>')
        for i, line in enumerate(body.split("\n")):
            parts.append(f'<text x="{x+card_w/2}" y="{y+168+i*38}" font-size="21" '
                         f'fill="{DIM}" text-anchor="middle">{line}</text>')
        if num != "5":
            ax = x + card_w
            ay = y + 130
            parts.append(f'<line x1="{ax}" y1="{ay}" x2="{ax+gap}" y2="{ay}" '
                         f'stroke="{LINE}" stroke-width="3"/>')
            parts.append(f'<polygon points="{ax+gap-8},{ay-9} {ax+gap},{ay} {ax+gap-8},{ay+9}" '
                         f'fill="{LINE}"/>')
        x_cursor += card_w + gap

    parts.append('<text x="700" y="610" font-size="20" fill="DIM" text-anchor="middle">'
                 'Cues, ticks and close need no braille literacy; braille text is the layer for readers.</text>')
    parts.append('<text x="700" y="770" font-size="28" fill="DIM" text-anchor="middle">'
                 'The reply does not “arrive” as a line. It arrives as a timed feeling — cue, ticks, spell, close.</text>')
    parts.append('</svg>')
    return "".join(parts)

def svg_architecture():
    """Wrist device + wearer-hosted relay + memory."""
    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" '
        'viewBox="0 0 1400 900" text-rendering="geometricPrecision" '
        'font-family="system-ui,-apple-system,Segoe UI,sans-serif">')
    parts.append(f'<rect x="0" y="0" width="1400" height="900" fill="{BG}"/>')

    # three pillars
    pillars = [
        (120,  "PHONE", "today", GREEN,
         ["Phone app demo",
          "Timed vibro-braille output",
          "Queue-don't-interrupt gate",
          "Auto-redial on the close",
          "Live queue + refusal badge",
          "Capped inbox + memory"]),
        (560,  "RELAY", "one turn", BLUE,
         ["FastAPI device relay",
          "One turn, end to end",
          "Queue-don't-interrupt gate",
          "Generated timing source",
          "Runs on our infra now",
          "Transparent path"]),
        (1000, "MEMORY", "remembers", WARN,
         ["Per-wearer memory files",
          "Atomic JSON writes",
          "Capped persistent inbox",
          "Stored, not dropped",
          "Corrupt-file recovery",
          "Replays on next attach"]),
    ]
    for x, name, tag, color, lines in pillars:
        y = 240
        y = 232
        parts.append(f'<rect x="{x}" y="{y}" width="300" height="520" rx="20" '
                     f'fill="{PANEL}" stroke="{LINE}"/>')
        parts.append(f'<rect x="{x}" y="{y}" width="300" height="72" rx="20" fill="{color}"/>')
        parts.append(f'<rect x="{x}" y="{y+16}" width="300" height="56" '
                     f'fill="{color}" opacity="0.25"/>')
        parts.append(f'<text x="{x+150}" y="{y+40}" font-size="34" font-weight="800" '
                     f'fill="{BG}" text-anchor="middle">{name}</text>')
        parts.append(f'<text x="{x+150}" y="{y+72}" font-size="22" fill="{BG}" '
                     f'text-anchor="middle" opacity="0.9">{tag}</text>')
        for i, line in enumerate(lines):
            fill = DIM if i >= 4 else FG
            parts.append(f'<text x="{x+150}" y="{y+138+i*44}" font-size="24" '
                         f'fill="{fill}" text-anchor="middle">{line}</text>')

    parts.append('<text x="700" y="820" font-size="26" fill="DIM" text-anchor="middle">'
                 'Phone, relay, and memory — built now. The wrist device is the next revision.</text>')
    parts.append('</svg>')
    return "".join(parts)

def svg_proof():
    """Hermetic tests + drift guard."""
    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" '
        'viewBox="0 0 1400 900" text-rendering="geometricPrecision" '
        'font-family="system-ui,-apple-system,Segoe UI,sans-serif">')
    parts.append(f'<rect x="0" y="0" width="1400" height="900" fill="{BG}"/>')

    parts.append(f'<rect x="80" y="120" width="1240" height="620" rx="24" '
                 f'fill="{PANEL}" stroke="{LINE}"/>')

    # left: tests
    parts.append(f'<text x="200" y="210" font-size="34" font-weight="800" fill="{ACCENT}">'
                 'Hermetic proof, not screenshots</text>')
    tests = [
        ("230 hermetic tests", "the turn journey, gate, refusal, redial, memory, inbox, auth"),
        ("timing tests", "phone, firmware header, and tests share one derivation"),
        ("store tests", "inbox, memory, schedule — atomic, capped, corrupt-tolerant"),
    ]
    y = 270
    for head, body in tests:
        parts.append(f'<rect x="200" y="{y}" width="1080" height="70" rx="14" '
                     f'fill="{BG}" stroke="{LINE}"/>')
        parts.append(f'<text x="222" y="{y+34}" font-size="22" font-weight="700" fill="{FG}">{head}</text>')
        parts.append(f'<text x="222" y="{y+58}" font-size="20" fill="{DIM}">{body}</text>')
        y += 90

    # right: drift guard
    xg = 200
    parts.append(f'<text x="{1400-200}" y="210" font-size="34" font-weight="800" fill="{WARN}"'
                 ' text-anchor="end">One timing source, enforced</text>')
    parts.append(f'<circle cx="{1400-200}" cy="360" r="130" fill="{WARN}" opacity="0.08"/>')
    parts.append(f'<circle cx="{1400-200}" cy="360" r="90" fill="{WARN}" opacity="0.16"/>')
    parts.append(f'<circle cx="{1400-200}" cy="360" r="56" fill="{WARN}"/>')
    parts.append(f'<text x="{1400-200}" y="356" font-size="28" font-weight="800" fill="{BG}" '
                 'text-anchor="middle">drift</text>')
    parts.append(f'<text x="{1400-200}" y="388" font-size="22" fill="{BG}" '
                 'text-anchor="middle">guard</text>')
    parts.append(f'<text x="{1400-200}" y="520" font-size="22" fill="{DIM}" text-anchor="middle">'
                 'Any hand edit to generated timing fails the guard.</text>')

    parts.append('</svg>')
    return "".join(parts)

def svg_honesty():
    """What is built vs next revision."""
    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" '
        'viewBox="0 0 1400 900" text-rendering="geometricPrecision" '
        'font-family="system-ui,-apple-system,Segoe UI,sans-serif">')
    parts.append(f'<rect x="0" y="0" width="1400" height="900" fill="{BG}"/>')

    # left column: built
    parts.append(f'<rect x="80" y="140" width="560" height="620" rx="20" '
                 f'fill="{PANEL}" stroke="{ACCENT}"/>')
    parts.append(f'<rect x="80" y="140" width="560" height="72" rx="20" fill="{ACCENT}"/>')
    parts.append(f'<rect x="80" y="200" width="560" height="12" fill="{ACCENT}" opacity="0.3"/>')
    parts.append(f'<text x="360" y="184" font-size="32" font-weight="800" fill="{BG}" '
                 'text-anchor="middle">Built now</text>')
    built = [
        "A typed message or a model-composed intent — one turn",
        "Attention cues need no braille literacy",
        "Queue-don’t-interrupt gate (429, visual refusal)",
        "Sender-side auto-redial on the freeing close",
        "Live queue + refusal badge",
        "Wearer memory + capped inbox",
        "Hermetic tests green; timing drift guard enforced",
    ]
    y = 232
    for line in built:
        parts.append(f'<text x="110" y="{y}" font-size="22" fill="{FG}">• {line}</text>')
        y += 52

    # right column: next
    parts.append(f'<rect x="760" y="140" width="560" height="620" rx="20" '
                 f'fill="{PANEL}" stroke="{WARN}"/>')
    parts.append(f'<rect x="760" y="140" width="560" height="72" rx="20" fill="{WARN}"/>')
    parts.append(f'<rect x="760" y="200" width="560" height="12" fill="{WARN}" opacity="0.3"/>')
    parts.append(f'<text x="1040" y="184" font-size="32" font-weight="800" fill="{BG}" '
                 'text-anchor="middle">Next revision</text>')
    next_items = [
        ("Wrist device", "ESP32-S3 + DRV2605L + 6 LRA motors"),
        ("Hardware-gated mic", "Push-to-talk becomes physical"),
        ("Braille chord input", "6 chord keys"),
        ("Wearer-hosted relay", "Data under the wearer’s control"),
    ]
    y = 232
    for head, sub in next_items:
        parts.append(f'<text x="790" y="{y}" font-size="24" font-weight="700" fill="{WARN}">{head}</text>')
        parts.append(f'<text x="790" y="{y+30}" font-size="20" fill="{DIM}">{sub}</text>')
        y += 90

    parts.append('<text x="700" y="830" font-size="24" fill="DIM" text-anchor="middle">'
                 'What is claimed is what is built. The wrist shape is scoped honestly, not faked.</text>')
    parts.append('</svg>')
    return "".join(parts)

def svg_to_png_bytes(svg: str) -> bytes:
    """Convert an SVG string to RGBA PNG bytes using cairosvg if present, else
    render a PIL equivalent from a tiny internal representation used above.
    Since cairosvg is not installed on this machine, we fall back to rendering
    the SVG as a PIL image via its vector primitives rewritten into PIL calls.
    """
    raise NotImplementedError("cairosvg not installed — use the PIL render path")

# ----------------------------------------------------------------  PIL renders
def _truetype(path, size):
    for cand in (path,):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()

def _monospace(size):
    return ImageFont.truetype(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "segoesb.ttf"), size) if os.path.exists(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "segoesb.ttf")) else ImageFont.load_default()

def _font_regular(size):
    for cand in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "segoeui.ttf"),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "arial.ttf"),
    ):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()

def _font_bold(size):
    for cand in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "segoeuib.ttf"),
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "arialbd.ttf"),
    ):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()

def _font_black(size):
    for cand in (
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Fonts", "segoeuib.ttf"),
    ):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()

def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def rounded(draw, xy, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius, fill=fill, outline=outline, width=width)

def draw_card(draw, x, y, w, h, radius, fill=PANEL, border=LINE):
    draw.rounded_rectangle([x, y, x + w, y + h], radius,
                           fill=fill, outline=border, width=2)

def text_center(draw, cx, y, s, font, fill=FG):
    bbox = draw.textbbox((0, 0), s, font=font)
    draw.text((cx - (bbox[2] - bbox[0]) / 2, y), s, font=font, fill=fill)

def text_lines(draw, x, y, lines, font, fill=DIM, spacing=40):
    for i, line in enumerate(lines):
        draw.text((x, y + i * spacing), line, font=font, fill=fill)

# ----------------------------------------------------------------  shared slide system
# Every slide uses this geometry and type scale, so the six images read as one set.
W, H = 1400, 900
MARGIN = 96
CONTENT_W = W - 2 * MARGIN            # 1208
CARD_W, CARD_H = 360, 400
CARD_GAP = 64
CARD_TOP = 300
STRIP_H = 76
BODY_FONT = 22
BODY_LEAD = 38
CAPTION_Y = 800
CAPTION_FONT = 24
HEADER_RULE_Y = 152

def grid_x(col):
    """Card column x on the shared 3-column grid: 96, 520, 944."""
    return MARGIN + col * (CARD_W + CARD_GAP)

def slide_header(d, title, subtitle):
    """Same title/subtitle/rule block on every content slide."""
    d.text((MARGIN, 54), title, font=_font_black(38), fill=hexrgb(FG))
    d.text((MARGIN, 108), subtitle, font=_font_regular(20), fill=hexrgb(DIM))
    d.line([MARGIN, HEADER_RULE_Y, W - MARGIN, HEADER_RULE_Y], fill=hexrgb(LINE), width=2)

def card(d, x, color, name, body=None, tag=None, number=None):
    """One card, one shape: same size, same strip, same body type on every slide."""
    y = CARD_TOP
    fill = hexrgb(color)
    draw_card(d, x, y, CARD_W, CARD_H, 20, fill=PANEL, border=LINE)
    d.rounded_rectangle([x, y, x + CARD_W, y + STRIP_H], 20, fill=fill)
    d.rounded_rectangle([x, y + STRIP_H - 20, x + CARD_W, y + STRIP_H], 0, fill=fill)
    if tag:
        text_center(d, x + CARD_W / 2, y + 12, name, _font_bold(26), hexrgb(BG))
        text_center(d, x + CARD_W / 2, y + 44, tag, _font_regular(18), hexrgb(BG))
    else:
        text_center(d, x + CARD_W / 2, y + 22, name, _font_bold(26), hexrgb(BG))
    if number:
        d.ellipse([x + 14, y + 20, x + 50, y + 56], fill=hexrgb(BG))
        text_center(d, x + 32, y + 25, str(number), _font_bold(18), fill)
    if body:
        by = y + STRIP_H + 36
        for line in body:
            text_center(d, x + CARD_W / 2, by, line, _font_regular(BODY_FONT), hexrgb(FG))
            by += BODY_LEAD

def arrow_between(d, left_col, right_col, color=ACCENT):
    x1 = grid_x(left_col) + CARD_W
    x2 = grid_x(right_col)
    y = CARD_TOP + CARD_H / 2
    c = hexrgb(color)
    d.line([x1 + 10, y, x2 - 14, y], fill=c, width=3)
    d.polygon([(x2 - 14, y - 9), (x2, y), (x2 - 14, y + 9)], fill=c)

def _wrap(d, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textbbox((0, 0), trial, font=font)[2] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def slide_caption(d, text, align="center", x0=MARGIN, max_w=CONTENT_W):
    """Same caption line position and type on every slide."""
    font = _font_bold(CAPTION_FONT)
    yy = CAPTION_Y
    for line in _wrap(d, text, font, max_w):
        if align == "center":
            text_center(d, x0 + max_w / 2, yy, line, font, hexrgb(DIM))
        else:
            d.text((x0, yy), line, font=font, fill=hexrgb(DIM))
        yy += 40

def _blank():
    return Image.new("RGB", (W, H), hexrgb(BG))

def render_hero():
    """Cover slide: the title band, the three beats, and the phone that carries them."""
    img = _blank()
    d = ImageDraw.Draw(img)
    # band: the cover's one difference from the content slides. It stops above the
    # shared card row so everything below sits on the same grid as the other five.
    d.rectangle([0, 0, W, 260], fill=hexrgb(PANEL))
    d.rectangle([0, 260, W, 262], fill=hexrgb(ACCENT))
    d.text((MARGIN, 44), "Ziv", font=_font_black(84), fill=hexrgb(FG))
    d.text((MARGIN, 170), "A haptic message channel for deaf-blind users",
           font=_font_regular(28), fill=hexrgb(DIM))
    d.text((MARGIN, 216), "Messages you can feel. Private by touch.",
           font=_font_regular(20), fill=hexrgb(ACCENT))

    # badge
    cx, cy, cw, ch = 1100, 60, 244, 140
    d.rounded_rectangle([cx, cy, cx + cw, cy + ch], 16, fill=hexrgb(BG))
    d.rounded_rectangle([cx + 12, cy + 12, cx + cw - 12, cy + ch - 12], 10,
                        fill=hexrgb(ACCENT))
    text_center(d, cx + cw / 2, cy + 52, "ZIV", _font_bold(30), hexrgb(BG))
    text_center(d, cx + cw / 2, cy + 95, "dev band prototype",
                _font_regular(17), hexrgb(BG))

    # left column: what the project is and who it is for, on the shared card row.
    # The beats live on the haptics slide; the cover carries the framing instead.
    blocks = [
        ("WHAT IT IS", [
            "An agent answers as timed tactile",
            "patterns you feel; the console shows the text.",
        ]),
        ("WHO IT IS FOR", [
            "Deaf-blind users first; the same private",
            "channel serves hands-busy, noisy, and",
            "shared-space moments.",
        ]),
    ]
    by = CARD_TOP
    for label, lines in blocks:
        d.text((MARGIN, by), label, font=_font_bold(20), fill=hexrgb(ACCENT))
        d.line([MARGIN, by + 36, MARGIN + 520, by + 36], fill=hexrgb(LINE), width=2)
        ly = by + 58
        for line in lines:
            d.text((MARGIN, ly), line, font=_font_regular(BODY_FONT), fill=hexrgb(FG))
            ly += BODY_LEAD
        by = ly + 36
    d.text((MARGIN, by), "Demo band is a phone; the wrist band is next.",
           font=_font_regular(BODY_FONT), fill=hexrgb(WARN))

    # phone mock: the frame occupies exactly the third card slot (same column,
    # same row, same footprint as a card)
    frame = 18
    phone_w = CARD_W - 2 * frame
    phone_h = CARD_H - 2 * frame
    px = grid_x(2) + frame
    py = CARD_TOP + frame
    border = hexrgb(LINE)
    panel = hexrgb(PANEL)
    bgc = hexrgb(BG)
    accent = hexrgb(ACCENT)
    dim = hexrgb(DIM)
    warn = hexrgb(WARN)

    d.rounded_rectangle([px - frame, py - frame, px + phone_w + frame,
                         py + phone_h + frame], 28, fill=panel, outline=border, width=3)
    d.rounded_rectangle([px, py, px + phone_w, py + phone_h], 18, fill=bgc)

    d.rounded_rectangle([px, py, px + phone_w, py + 70], 18, fill=accent)
    d.rounded_rectangle([px, py + 18, px + phone_w, py + 52], 0, fill=accent)
    text_center(d, px + phone_w / 2, py + 38, "ZIV", _font_black(24), bgc)

    d.rounded_rectangle([px + 18, py + 90, px + phone_w - 18, py + 150], 12,
                        fill=panel, outline=border, width=1)
    text_center(d, px + phone_w / 2, py + 108, "A reply is being assembled",
                _font_bold(16), accent)
    text_center(d, px + phone_w / 2, py + 130, "feel the timed braille below",
                _font_regular(14), dim)

    cell_d = 52
    cell_gap = 12
    cells_top = py + 172
    cells_x0 = px + (phone_w - (3 * cell_d + 2 * cell_gap)) // 2
    for i, col in enumerate([accent, warn, hexrgb(RED)]):
        cxp = cells_x0 + i * (cell_d + cell_gap)
        d.ellipse([cxp, cells_top, cxp + cell_d, cells_top + cell_d],
                  outline=col, width=4)
        d.ellipse([cxp + 10, cells_top + 10, cxp + cell_d - 10, cells_top + cell_d - 10],
                  fill=bgc)
    text_center(d, px + phone_w / 2, cells_top + cell_d + 16,
                "feel the reply as it spells out", _font_regular(14), dim)
    text_center(d, px + phone_w / 2, cells_top + cell_d + 32,
                "one character at a time", _font_regular(14), dim)

    chip_w = 188
    chip_h = 50
    chip_y = cells_top + cell_d + 60
    d.rounded_rectangle([px + 18, chip_y, px + 18 + chip_w / 2, chip_y + chip_h], 10,
                        fill=accent)
    d.rounded_rectangle([px + 18 + chip_w / 2, chip_y, px + 18 + chip_w, chip_y + chip_h],
                        10, fill=bgc, outline=border, width=1)
    text_center(d, px + 18 + chip_w / 4, chip_y + 9, "CUR", _font_black(10), bgc)
    text_center(d, px + 18 + chip_w / 4, chip_y + 29, "spelling", _font_regular(14), bgc)
    d.rounded_rectangle([px + phone_w - 18 - chip_w / 2, chip_y, px + phone_w - 18,
                         chip_y + chip_h], 10, fill=warn)
    d.rounded_rectangle([px + phone_w - 18 - chip_w, chip_y,
                         px + phone_w - 18 - chip_w / 2, chip_y + chip_h], 10,
                        fill=bgc, outline=border, width=1)
    text_center(d, px + phone_w - 18 - chip_w / 4, chip_y + 9, "Q", _font_black(10), bgc)
    text_center(d, px + phone_w - 18 - chip_w / 4, chip_y + 29, "1 queued",
                _font_regular(14), bgc)
    for slot_x0 in (px + 18 + chip_w / 2, px + phone_w - 18 - chip_w):
        slot_cx = slot_x0 + chip_w / 4
        slot_cy = chip_y + chip_h / 2
        for col in range(2):
            for row in range(3):
                dx = slot_cx - 9 + col * 18
                dy = slot_cy - 13 + row * 13
                d.ellipse([dx - 2.5, dy - 2.5, dx + 2.5, dy + 2.5], fill=border)

    d.rectangle([px - frame, py - frame, px + phone_w + frame, py + phone_h + frame],
                outline=dim, width=1)

    slide_caption(d, "A haptic message channel for deaf-blind users, and anyone who "
                     "needs a private, glance-free reply.",
                  align="left", max_w=760)
    return img

def render_flow():
    img = _blank()
    d = ImageDraw.Draw(img)
    slide_header(d, "One reply, one turn",
                 "What carries a message — and why nothing else can cut in.")
    card(d, grid_x(0), ACCENT, "SENDER",
         ["A typed message,", "or a scheduled intent"], number=1)
    card(d, grid_x(1), BLUE, "RELAY",
         ["One turn, end to end.", "A scheduled intent is", "composed by Nemotron",
          "first."], number=2)
    card(d, grid_x(2), WARN, "PHONE",
         ["Either way, the reply", "feels like timed braille"], number=3)
    arrow_between(d, 0, 1)
    arrow_between(d, 1, 2)
    slide_caption(d, "How a reply travels: a typed message takes one turn, a scheduled "
                     "intent is composed by Nemotron first. One turn at a time keeps it legible.")
    return img

def render_haptics():
    img = _blank()
    d = ImageDraw.Draw(img)
    slide_header(d, "What the reply feels like",
                 "Three beats a wearer can follow — cue, spell, close — from early-years "
                 "deaf-blind practice.")
    card(d, grid_x(0), TEAL, "CUE",
         ["The name mark, then a", "short double tap.", "Cues work from minute",
          "one — no braille needed."], number=1)
    card(d, grid_x(1), WARN, "SPELLING",
         ["Processing ticks while", "the relay works, then", "braille cells, one",
          "character at a time.", "Braille text is the", "layer for readers."], number=2)
    card(d, grid_x(2), RED, "CLOSE",
         ["The end beat: the turn", "is done, and a queued", "message gets its turn",
          "next."], number=3)
    slide_caption(d, "Cues need no braille literacy; braille is the layer for readers. "
                     "Ticks mark the relay's work, then a close; queued messages wait.")
    return img

def render_architecture():
    img = _blank()
    d = ImageDraw.Draw(img)
    slide_header(d, "Phone, relay, and memory",
                 "Everything a message needs, running today on parts you can run yourself.")
    card(d, grid_x(0), ACCENT, "PHONE",
         ["Phone app demo", "Timed vibro-braille", "Queue-don’t-interrupt",
          "Auto-redial on close", "Live queue + badge", "Capped inbox + memory"],
         tag="today")
    card(d, grid_x(1), BLUE, "RELAY",
         ["FastAPI device relay", "One turn, end to end", "Generated timing",
          "Runs on our infra now", "Transparent path"],
         tag="one turn")
    card(d, grid_x(2), WARN, "MEMORY",
         ["Per-wearer memory", "Atomic JSON writes", "Capped persistent inbox",
          "Stored, not dropped", "Corrupt-file recovery", "Replays on next attach"],
         tag="remembers")
    slide_caption(d, "Phone, relay, and memory — the built-today architecture. The wrist "
                     "device and wearer-hosted relay are the next revision.")
    return img

def render_proof():
    img = _blank()
    d = ImageDraw.Draw(img)
    slide_header(d, "Hermetic proof, not screenshots",
                 "Why the claims hold — and why the felt timing can't silently change "
                 "under the wearer.")
    card(d, grid_x(0), ACCENT, "230 hermetic tests",
         ["The turn journey, queue", "gate, refusal, redial,", "memory, inbox, auth."])
    card(d, grid_x(1), TEAL, "timing tests",
         ["Phone, firmware header", "and tests share one", "derivation."])
    card(d, grid_x(2), WARN, "drift guard",
         ["One generated timing", "source; any hand edit", "fails the guard."])
    slide_caption(d, "Proven in code, not screenshots: 230 hermetic tests, plus a drift "
                     "guard so the felt pattern can't change under the wearer.")
    return img

def render_honesty():
    img = _blank()
    d = ImageDraw.Draw(img)
    slide_header(d, "What is built, and what is not",
                 "The wearer can't afford a demo that over-claims, so every claim is split here.")
    pair_x = (W - (2 * CARD_W + CARD_GAP)) / 2
    card(d, pair_x, ACCENT, "Built now",
         ["Vibro-braille on a phone", "Queue-don’t-interrupt gate",
          "Auto-redial on the close", "Live queue + refusal badge",
          "Wearer memory + inbox", "230 hermetic tests green", "Timing drift guard"])
    card(d, pair_x + CARD_W + CARD_GAP, WARN, "Next revision",
         ["Wrist device", "Hardware-gated mic", "Braille chord input",
          "Wearer-hosted relay"])
    slide_caption(d, "Built now: vibro-braille on a phone, queue gate, auto-redial, badge, "
                     "memory, inbox, and green tests. A wrist device is the next revision.")
    return img

def draw_text_fit(d, x, y, s, font, fill, max_w, line_spacing=8):
    """Draw wrapped text starting at (x, y), no autosize."""
    words = s.split()
    lines = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textbbox((0, 0), trial, font=font)[2] <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    yy = y
    for line in lines:
        d.text((x, yy), line, font=font, fill=fill)
        bbox = d.textbbox((0, 0), line, font=font)
        yy += (bbox[3] - bbox[1]) + line_spacing

def draw_text_fit_phone(d, x, y, max_w, s, font, fill, line_spacing=8):
    """Phone-frame inner caption helper."""
    return draw_text_fit(d, x, y, s, font, fill, max_w, line_spacing)

def save_png(img, name):
    out = os.path.join(OUT, name)
    img.save(out, "PNG")
    print(f"wrote {out}  ({img.size[0]}x{img.size[1]})")

def png_to_jpg(img, quality=92):
    bg = img.convert("RGBA").getpixel((0, 0))
    flat = Image.new("RGB", img.size, bg)
    flat.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
    buf = io.BytesIO()
    flat.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()

# ----------------------------------------------------------------  captions
GALLERY = [
    {
        "file": "hero.png",
        "title": "Ziv — a private haptic message channel",
        "caption": "A haptic message channel for deaf-blind users, and anyone who needs a private, glance-free reply. Phone demo today; wrist band next.",
    },
    {
        "file": "flow.png",
        "title": "One path, one turn, one feeling",
        "caption": "How a reply travels: a typed message takes one turn, a scheduled intent is composed by Nemotron first. One turn at a time keeps it legible.",
    },
    {
        "file": "haptics.png",
        "title": "The reply feels like timed braille",
        "caption": "Cues need no braille literacy; braille is the layer for readers. Ticks mark the relay's work, then a close; queued messages wait.",
    },
    {
        "file": "architecture.png",
        "title": "Phone, relay, and memory",
        "caption": "Phone, relay, and memory — the built-today architecture. The wrist device and wearer-hosted relay are the next revision.",
    },
    {
        "file": "proof.png",
        "title": "Hermetic proof, enforced by the drift guard",
        "caption": "Proven in code, not screenshots: 230 hermetic tests, plus a drift guard so the felt pattern can't change under the wearer.",
    },
    {
        "file": "honesty.png",
        "title": "What is built vs next revision",
        "caption": "Built now: vibro-braille on a phone, queue gate, auto-redial, badge, memory, inbox, and green tests. A wrist device is the next revision.",
    },
]

CAPTION_CHARS = {
    item["file"]: len(item["caption"])
    for item in GALLERY
}

def _print_caption_check():
    print("\n=== Caption length check (Devpost 140-char limit) ===\n")
    for item in GALLERY:
        ok = "OK" if CAPTION_CHARS[item["file"]] <= 140 else "OVER 140"
        print(f"[{item['file']}] {CAPTION_CHARS[item['file']]} chars {ok}\n  {item['caption']}\n")

def _print_layout_check():
    """Print a plain-English layout pass so I do not have to re-transcribe the rendered PNGs by hand."""
    print("\n=== Layout pass: one shared system across all six slides ===\n")
    print(f"geometry: {W}x{H}; margins {MARGIN}; content width {CONTENT_W}")
    print(f"cards: {CARD_W}x{CARD_H} at y={CARD_TOP}, gap {CARD_GAP}, columns at "
          f"x={grid_x(0)}/{grid_x(1)}/{grid_x(2)}")
    print(f"card strip: {STRIP_H}px tall, name centred in BG colour (bold 26), "
          f"optional tag (18) or step number badge")
    print(f"card body: centred, {BODY_FONT}px, lead {BODY_LEAD}")
    print(f"slide header: title (black 38) at y=54, subtitle (20) at y=108, "
          f"rule at y={HEADER_RULE_Y}")
    print(f"caption: bold {CAPTION_FONT} at y={CAPTION_Y}, centred for the five content "
          f"slides, left-aligned in the cover's left column")
    print()
    print("hero.png (cover: distinct band, but the same grid underneath)")
    print("  band (0-260): title 'Ziv', subtitle 'A haptic message channel for deaf-blind users',")
    print("        tagline 'Messages you can feel. Private by touch.'")
    print("  band right: ZIV / dev band prototype badge")
    print("  from the shared card row down:")
    print("    col 1-2: 'WHAT IT IS' (an agent answers as timed tactile patterns;")
    print("             the console shows the text) + 'WHO IT IS FOR' (deaf-blind users first;")
    print("             hands-busy, noisy, shared-space moments)")
    print("             + 'Demo band is a phone; the wrist band is next.'")
    print("    col 3  : phone frame occupying exactly one card slot")
    print("  caption at the shared baseline, left column only")
    print()
    print("flow.png")
    print("  subtitle: what carries a message, and why nothing else can cut in")
    print("  3 cards on columns 1-3: SENDER / RELAY / PHONE, arrows between, step numbers")
    print("  caption: 'How a reply travels: ...' (one turn at a time keeps it legible)")
    print()
    print("haptics.png")
    print("  subtitle: three beats a wearer can follow, from early-years deaf-blind practice")
    print("  3 cards: CUE / SPELLING / CLOSE, step numbers")
    print("  CUE card carries layer one: cues work from minute one, no braille literacy")
    print("  SPELLING card carries the relay's ticks (not the model's) + layer two for readers")
    print("  caption: 'Cues need no braille literacy; braille is the layer for readers. ...'")
    print()
    print("architecture.png")
    print("  subtitle: everything a message needs, running today on parts you can run")
    print("  3 cards with tags: PHONE (today) / RELAY (one turn) / MEMORY (remembers)")
    print("  caption: 'Phone, relay, and memory — the built-today architecture. ...'")
    print()
    print("proof.png")
    print("  subtitle: why the claims hold, and why the felt timing can't change under the wearer")
    print("  3 cards: 230 hermetic tests / timing tests / drift guard")
    print("  caption: 'Proven in code, not screenshots: ...'")
    print()
    print("honesty.png")
    print("  subtitle: the wearer can't afford a demo that over-claims")
    print("  2 cards centred as a pair: 'Built now' (7 rows) / 'Next revision' (4 rows)")
    print("  caption: 'Built now: vibro-braille on a phone, queue gate, ...'")
    print()



# ------------------------------------------------------------- caption docs
# Every caption-bearing doc in media/ is written from GALLERY above, so the
# pack cannot quote retired copy: change a caption here and re-run the script.

DOC_BANNER = ("Generated by `media/make_gallery.py` from its `GALLERY` caption list. "
              "Re-running that script rewrites this file \u2014 edit the captions there, not here.")

SLIDE_NOTES = {
    "hero.png": "cover \u2014 what Ziv is and who it is for; the dev band is drawn as a phone",
    "flow.png": "one path, one turn: sender, relay, phone (card 3 is PHONE, not wrist)",
    "haptics.png": "the turn as felt: cue, ticks while the relay works, braille for readers, close",
    "architecture.png": "phone, relay and memory \u2014 the built-today architecture",
    "proof.png": "230 hermetic tests, one timing derivation, and the drift guard",
    "honesty.png": "built now and next revision, side by side",
}

ORDER = [
    ("hero", "what it is"),
    ("flow", "how a reply travels"),
    ("haptics", "what the reply feels like"),
    ("architecture", "what is built today"),
    ("proof", "why the claims hold"),
    ("honesty", "what is next"),
]

NOT_CLAIMED = (
    "None of the captions claim the wrist device, hardware mic, chord input, or\n"
    "wearer-hosted relay as part of this submission. They are mentioned only as the\n"
    "next revision, exactly as described in the project story."
)

def _slug(fname, ext):
    """hero.png -> 'hero' (ext='') or 'hero.mp4' (ext='.mp4')."""
    return fname.replace(".png", ext)

def _caption(fname):
    for item in GALLERY:
        if item["file"] == fname:
            return item["caption"]
    raise KeyError(fname)

def doc_galleries():
    out = ["# Ziv \u2014 Devpost gallery", "",
           "One Devpost gallery entry per slide: file, title, caption.", "",
           DOC_BANNER, "", "---", ""]
    for item in GALLERY:
        out += [f"**{item['file']}**",
                f"Title: {item['title']}",
                f"Caption: {item['caption']}", ""]
    out += ["### Caption lengths (chars)", ""]
    out += [f"- {_slug(item['file'], '')}: {len(item['caption'])}" for item in GALLERY]
    out += ["", "All within the 140-char Devpost gallery caption limit.", "",
            "---", "", "## What is not claimed here", "", NOT_CLAIMED]
    return "\n".join(out) + "\n"

def doc_videos():
    out = ["# Ziv \u2014 Devpost videos", "",
           "Six videos, one per gallery slide: 1400x900, 15 seconds each, H.264.",
           "Each is the looping visual of its slide, so its title and description are",
           "that slide's title and caption, unchanged. The haptics video is the turn as",
           "felt: the relay's processing ticks, then braille cells for readers; the cue",
           "and close need no braille literacy.", "",
           DOC_BANNER, "", "Files in `media/`:"]
    out += [f"- `{_slug(item['file'], '.mp4')}`" for item in GALLERY]
    out += ["", "---", ""]
    for item in GALLERY:
        out += [f"## {_slug(item['file'], '.mp4')}",
                f"Title: {item['title']}",
                f"Description: {item['caption']}", ""]
    return "\n".join(out) + "\n"

def doc_remarketing():
    out = ["# Caption remarketing", "",
           "The conservative caption set, taken verbatim from the slide captions in",
           "`media/make_gallery.py`.", "",
           "Rules that produce them:",
           "- the demo today is a phone app that feels the reply as timed vibro-braille;",
           "- the wrist band and a wearer-hosted relay are the next revision, never a",
           "  current claim;",
           "- the word \"wrist\" appears only inside next-revision framing;",
           "- the processing ticks are the relay's work, not the model thinking;",
           "- cues need no braille literacy; braille text is the layer for readers.", "",
           DOC_BANNER, "", "---", "", "## Gallery captions", ""]
    for item in GALLERY:
        out += [f"**{_slug(item['file'], '')}**",
                f"Title: {item['title']}",
                f"Caption: {item['caption']}", ""]
    out += ["---", "", "## Video descriptions", "",
            "The videos are the same six slides, so their descriptions are the same",
            "captions:", ""]
    for item in GALLERY:
        out += [f"**{_slug(item['file'], '.mp4')}**",
                f"Description: {item['caption']}", ""]
    out += ["---", "", "## What I would not say", "",
            "- \"wearable\" as a product claim",
            "- \"wrist\" as if it is the current demo surface",
            "- \"speak to the device\", or anything that implies the hardware mic exists now",
            "- any caption that sounds like a prompt-to-wearable demo"]
    return "\n".join(out) + "\n"

def doc_pack():
    out = ["# Ziv \u2014 Devpost media pack", "",
           "Everything is in `media/` next to this file.", "",
           DOC_BANNER, "", "## What's in the folder", "",
           "Gallery images (1400x900 PNG + JPG):"]
    out += [f"- `{item['file']}` / `{_slug(item['file'], '.jpg')}`" for item in GALLERY]
    out += ["", "Videos (1400x900, 15 seconds each, H.264):"]
    out += [f"- `{_slug(item['file'], '.mp4')}`" for item in GALLERY]
    out += ["", "Caption/placement reference:",
            "- `galleries.md` \u2014 gallery images: file, title, caption, caption length",
            "- `videos.md` \u2014 videos: file, title, description", "",
            "## Caption lengths", "", "All gallery captions are under 140 characters:"]
    out += [f"- {_slug(item['file'], '')}: {len(item['caption'])}" for item in GALLERY]
    out += ["", "## Lead visual", "",
            "Lead with `hero.png` / `hero.mp4`. The cover says what Ziv is and who it is",
            "for:", "", f"> {_caption('hero.png')}", "",
            "## Suggested ordering", ""]
    out += [f"{n}. {name} \u2014 {why}" for n, (name, why) in enumerate(ORDER, 1)]
    out += ["", "That ordering is the same order the gallery captions are written in.", "",
            "## Gallery image notes", ""]
    out += [f"- `{item['file']}` \u2014 {SLIDE_NOTES[item['file']]}" for item in GALLERY]
    out += ["", "## What is not claimed here", "", NOT_CLAIMED]
    return "\n".join(out) + "\n"

def doc_review_html():
    import html as _html
    cards = []
    for item in GALLERY:
        cards.append(
            "  <section class=\"card\">\r\n"
            f"    <div class=\"name\">{item['file']} \u2014 {_html.escape(item['title'])}</div>\r\n"
            f"    <div class=\"stage\"><img src=\"{item['file']}\" alt=\"{_slug(item['file'], '')}\" /></div>\r\n"
            f"    <div class=\"caption\">{_html.escape(item['caption'])}\r\n"
            f"      <br/><b>Shows:</b> {_html.escape(SLIDE_NOTES[item['file']])}</div>\r\n"
            "  </section>")
    body = "\r\n".join(cards)
    return (
        "<!doctype html>\r\n<html lang=\"en\">\r\n<head>\r\n<meta charset=\"utf-8\" />\r\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\r\n"
        "<title>Ziv \u2014 Devpost slides</title>\r\n<style>\r\n"
        ":root{--bg:#0b0e12;--panel:#10141a;--line:#232a33;--fg:#e8ecf2;--dim:#9aa4b2}\r\n"
        "*{box-sizing:border-box}\r\nhtml,body{margin:0;background:var(--bg);color:var(--fg)}\r\n"
        "body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;padding:24px 28px 80px}\r\n"
        "h1{font-size:22px;margin:0 0 6px}\r\n.sub{color:var(--dim);margin:0 0 22px;font-size:14px}\r\n"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:18px}\r\n"
        ".card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}\r\n"
        ".name{font-size:13px;letter-spacing:.6px;text-transform:uppercase;color:var(--dim);padding:10px 14px 8px;border-bottom:1px solid var(--line);background:#0c1116}\r\n"
        ".stage{background:#000;display:flex;align-items:center;justify-content:center}\r\n"
        ".stage img{max-width:100%;max-height:620px;display:block}\r\n"
        ".caption{padding:10px 14px 14px;font-size:12px;color:var(--dim);line-height:1.55}\r\n"
        "</style>\r\n</head>\r\n<body>\r\n<h1>Ziv \u2014 Devpost gallery slides</h1>\r\n"
        "<p class=\"sub\">1400\u00d7900 renders, with the title and caption Devpost is given (same list: media/make_gallery.py).</p>\r\n"
        "<div class=\"grid\">\r\n" + body + "\r\n</div>\r\n</body>\r\n</html>\r\n"
    )

def write_docs():
    """Write every caption-bearing doc from GALLERY. Returns the names written."""
    docs = {
        "galleries.md": doc_galleries(),
        "videos.md": doc_videos(),
        "caption_remarketing.md": doc_remarketing(),
        "devpost_pack.md": doc_pack(),
        "review_slides.html": doc_review_html(),
    }
    for name, text in docs.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return list(docs)

def main():
    print("Rendering Ziv Devpost gallery media …")
    save_png(render_hero(), "hero.png")
    save_png(render_flow(), "flow.png")
    save_png(render_haptics(), "haptics.png")
    save_png(render_architecture(), "architecture.png")
    save_png(render_proof(), "proof.png")
    save_png(render_honesty(), "honesty.png")

    _print_layout_check()

    print("\n=== Devpost gallery block ===\n")
    for item in GALLERY:
        print(f"[{item['file']}]")
        print(f"  TITLE   : {item['title']}")
        print(f"  CAPTION : {item['caption']}")
        print()
    _print_caption_check()

    print("\n=== Caption docs ===\n")
    for name in write_docs():
        print(f"wrote media/{name}")
    print("\nNOTE: text placement should be verified by reloading the PNGs after this run,\nnot by a string-in-bytes scan on the encoded image files.\n")
    print("If the new architecture slide needs further edits, do that in render_architecture() directly.\n")
    print("Done.")

if __name__ == "__main__":
    main()
