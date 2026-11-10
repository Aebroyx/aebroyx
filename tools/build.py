"""Build every SVG the profile README shows, in a dark and a light version.

    python tools/build.py

Reads profile.json (what the card says) and cache/stats.json (GitHub numbers
from fetch_stats.py) and assets/art.json (the picture, from make_art.py) and
writes into generated/:

  card_{dark,light}.svg          the terminal card: ASCII picture + info panel
  button_<name>_{dark,light}.svg one image per link button
  pacman_{dark,light}.svg        Pac-Man graph recoloured to the card palette
                                 (only when the Pac-Man action left dist/)

No third-party packages needed. GitHub shows README SVGs as plain images, so
everything here is static SVG with CSS/SMIL animation: no scripts, no hover.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "generated"
CFG = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
STATS = ROOT / "cache" / "stats.json"

FONT = ("'JetBrains Mono','SF Mono',Menlo,Consolas,'DejaVu Sans Mono',"
        "'Liberation Mono',monospace")

# Same glyph set as the GlyphField background on sangalabror.aebroyx.dev.
FIELD_GLYPHS = "{}[]()<>/\\|=+-*&^%$#@!?;:~.0123456789abcdefABCDEF"

# Purple and neon green, after EVA-01. "tones" colour the ASCII picture (see
# tools/make_art.py): d outline, 1/2/3 deep/mid/light purple, g green,
# h highlight, e highlight that pulses green.
THEMES = {
    "dark": {
        "bg": "#0c0a12", "border": "#2a2140", "fg": "#cfc8e0",
        "key": "#b48cff", "acc": "#8bff3a", "value": "#efeafc", "dots": "#4b3f66",
        "add": "#8bff3a", "del": "#ff5c7a",
        "field": "#8c82aa", "field_opacity": 0.12, "flash": ("#b48cff", "#8bff3a"),
        "tones": {"d": "#4a3a6e", "1": "#8550d8", "2": "#ad7cf5", "3": "#dcc4ff",
                  "g": "#8bff3a", "h": "#efe6ff", "e": "#efe6ff"},
        # Pac-Man (github-dark) colour -> card colour
        "pacman": {"#0d1117": "#0c0a12", "#161b22": "#191426", "#0e4429": "#3b1f6e",
                   "#006d32": "#6b3fb0", "#26a641": "#5fc21f", "#39d353": "#8bff3a"},
    },
    "light": {
        "bg": "#ffffff", "border": "#ddd5ee", "fg": "#2a2440",
        "key": "#6b35c9", "acc": "#2f8a00", "value": "#1d1830", "dots": "#aaa2c0",
        "add": "#2f8a00", "del": "#cf222e",
        "field": "#6b6385", "field_opacity": 0.12, "flash": ("#6b35c9", "#2f8a00"),
        "tones": {"d": "#3a2a55", "1": "#4a2385", "2": "#7440c4", "3": "#a57de8",
                  "g": "#3fa000", "h": "#b9a3ea", "e": "#b9a3ea"},
        # Pac-Man (github light) colour -> card colour
        "pacman": {"#ebedf0": "#efeaf7", "#9be9a8": "#d6c4f7", "#40c463": "#9a62d6",
                   "#30a14e": "#6fcf2a", "#216e39": "#3c9a00"},
    },
}

# The SP logo (portfolio button icon) on its 14 x 8 grid: 512 / 14 = 36.57,
# the size of every block in the portfolio's SP_WHITE.svg.
SP_LOGO = """
######..#####.
#.....##....#.
#......#.....#
.#####.#....#.
......######..
......#.......
#.....#.......
.#####........
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def bitmap(art: str) -> list[str]:
    return [row for row in art.strip("\n").split("\n")]


def num(n: float) -> str:
    return f"{n:.2f}".rstrip("0").rstrip(".")


def xs(x0: float, step: float, count: int) -> str:
    """One x per character, so columns line up whatever monospace font loads."""
    return " ".join(num(x0 + i * step) for i in range(count))


# --- Card layout --------------------------------------------------------------
CARD_W = 976
PAD = 24
ART_W = 396
PANEL_X = PAD + ART_W + 28
PANEL_FONT = 15
PANEL_CW = 9.0                      # one panel column
PANEL_COLS = 56                     # PANEL_X + 56 * 9 + PAD == CARD_W
LINE = 20

# The picture sits flush with the card's left and bottom edges and runs up to
# the panel; its top and right edges fade out into the glyph field.
ART = json.loads((ROOT / "assets" / "art.json").read_text(encoding="utf-8"))
IMG_W = PANEL_X - 12
ART_CW = IMG_W / ART["cols"]
ART_LH = 2 * ART_CW                 # character cells are twice as tall as wide
ART_FONT = ART_CW / 0.6

assert PANEL_X + PANEL_COLS * PANEL_CW + PAD == CARD_W


# --- Info panel ---------------------------------------------------------------
class Fill:
    """Stretchy run of one character, sized so every row is PANEL_COLS wide."""

    def __init__(self, char: str = ".", cls: str = "dots") -> None:
        self.char, self.cls = char, cls


def key(name: str) -> list:
    out = []
    for i, part in enumerate(name.split(".")):
        if i:
            out.append((".", None))
        out.append((part, "key"))
    return out


def kv(name: str, value: str) -> list:
    return [(". ", "dots"), *key(name), (": ", None), Fill(), (" ", None), (value, "value")]


def rule(label: str, cls: str | None = None, lead: str = "") -> list:
    return [(lead, "dots"), (label, cls), (" ", None), Fill("─")]


def layout(segs: list) -> list[tuple[str, str | None]]:
    fills = [s for s in segs if isinstance(s, Fill)]
    fixed = sum(len(s[0]) for s in segs if not isinstance(s, Fill))
    slack = PANEL_COLS - fixed
    if fills and slack < len(fills):
        text = "".join(s[0] for s in segs if not isinstance(s, Fill))
        raise SystemExit(f"Too long for the card ({fixed} of {PANEL_COLS} columns), "
                         f"shorten it in profile.json: {text!r}")
    out = []
    for i, s in enumerate(segs):
        if isinstance(s, Fill):
            n = fills.index(s)
            width = slack // len(fills) + (1 if n < slack % len(fills) else 0)
            out.append((s.char * width, s.cls))
        elif s[0]:
            out.append(s)
    return out


def uptime() -> str:
    start = dt.date.fromisoformat(CFG["uptime_since"])
    today = dt.date.today()
    y, m, d = today.year - start.year, today.month - start.month, today.day - start.day
    if d < 0:
        m -= 1
        d += (today.replace(day=1) - dt.timedelta(days=1)).day
    if m < 0:
        y, m = y - 1, m + 12
    unit = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{unit(y, 'year')}, {unit(m, 'month')}, {unit(d, 'day')}"


def stats() -> dict[str, str]:
    names = ("repos", "contributed", "stars", "commits", "followers", "loc", "added", "deleted")
    raw = json.loads(STATS.read_text()) if STATS.exists() else {}
    return {k: f"{raw[k]:,}" if isinstance(raw.get(k), int) else "--" for k in names}


def panel_rows() -> list[list | None]:
    st = stats()
    rows: list[list | None] = [rule(CFG["title"], "title")]
    for item in CFG["info"]:
        rows.append(None if item is None else kv(item[0], item[1].replace("{uptime}", uptime())))
    rows += [None, rule("Contact", lead="- ")]
    rows += [kv(k, v) for k, v in CFG["contact"]]
    rows += [None, rule("GitHub Stats", lead="- ")]
    rows.append([(". ", "dots"), *key("Repos"), (": ", None), Fill(), (" ", None),
                 (st["repos"], "value"), (" {", None), ("Contributed", "key"), (": ", None),
                 (st["contributed"], "value"), ("} | ", None), *key("Stars"), (": ", None),
                 Fill(), (" ", None), (st["stars"], "value")])
    rows.append([(". ", "dots"), *key("Commits"), (": ", None), Fill(), (" ", None),
                 (st["commits"], "value"), (" | ", None), *key("Followers"), (": ", None),
                 Fill(), (" ", None), (st["followers"], "value")])
    rows.append([(". ", "dots"), *key("Lines of Code"), (": ", None), Fill(), (" ", None),
                 (st["loc"], "value"), (" ( ", None), (st["added"] + "++", "add"),
                 (", ", None), (st["deleted"] + "--", "del"), (" )", None)])
    return rows


def render_row(parts: list[tuple[str, str | None]], y: float,
               extra: str = "", extra_chars: int = 0) -> str:
    count = sum(len(t) for t, _ in parts) + extra_chars
    spans = "".join(f'<tspan class="{c}">{esc(t)}</tspan>' if c else esc(t) for t, c in parts)
    return f'<text x="{xs(PANEL_X, PANEL_CW, count)}" y="{num(y)}">{spans}{extra}</text>'


def build_panel(top: float) -> tuple[str, float]:
    rows = panel_rows()
    out = []
    for i, row in enumerate(rows):
        y = top + i * LINE
        parts = [(".", "dots")] if row is None else layout(row)
        out.append(render_row(parts, y))
    # A prompt waiting for input, with a blinking block cursor.
    i = len(rows) + 1
    cursor = ('<tspan class="acc">█<animate attributeName="fill-opacity" values="1;0" '
              'dur="1.1s" calcMode="discrete" repeatCount="indefinite"/></tspan>')
    out.append(render_row([("> ", "acc")], top + i * LINE, cursor, extra_chars=1))
    return "\n".join(out), (i + 1) * LINE


# --- Picture ------------------------------------------------------------------
def colored_row(chars: str, tones: str, cls_prefix: str = "t") -> str:
    """Runs of one tone become one tspan; spaces join whichever run they sit in."""
    out, run, run_tone = [], "", None
    for ch, t in zip(chars, tones):
        if ch != " " and t != run_tone and run:
            out.append(f'<tspan class="{cls_prefix}{run_tone}">{esc(run)}</tspan>' if run_tone else esc(run))
            run = ""
        if ch != " ":
            run_tone = t
        run += ch
    if run:
        out.append(f'<tspan class="{cls_prefix}{run_tone}">{esc(run)}</tspan>' if run_tone else esc(run))
    return "".join(out)


def build_art(height: float, c: dict) -> str:
    rng = random.Random(7)              # fixed seed: the art doesn't churn each day
    total = int(height // ART_LH) + 1
    off = max(0, total - ART["rows"])   # grid row where the picture starts
    field_w = PANEL_X - 12
    field_cols = int(field_w // ART_CW)

    def row_y(r: int) -> float:         # rows are counted up from the card's bottom
        return height - (total - r) * ART_LH + ART_LH * 0.78

    def in_figure(col: int, r: int) -> bool:
        pr = r - off
        return 0 <= pr < ART["rows"] and 0 <= col < ART["cols"] and ART["tones"][pr][col] != "."

    field_rows, field_cells = [], []
    for r in range(total):
        y = row_y(r)
        if y < 0:
            continue
        line = []
        for col in range(field_cols):
            busy = any(in_figure(col + dx, r + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            g = " " if busy else rng.choice(FIELD_GLYPHS)
            line.append(g)
            if g != " ":
                field_cells.append((col, y, g))
        field_rows.append(f'<text x="{xs(0, ART_CW, field_cols)}" y="{num(y)}">{esc("".join(line))}</text>')

    art_rows, plain_rows, eye = [], [], []
    for pr, (chars, tones) in enumerate(zip(ART["chars"], ART["tones"])):
        if not chars.strip():
            continue
        y = num(row_y(pr + off))
        x = xs(0, ART_CW, len(chars))
        art_rows.append(f'<text x="{x}" y="{y}">{colored_row(chars, tones)}</text>')
        plain_rows.append(f'<text x="{x}" y="{y}">{esc(chars)}</text>')
        eye += [(col * ART_CW, row_y(pr + off)) for col, t in enumerate(tones) if t == "e"]

    # Field glyphs light up now and then, in both colours.
    flickers = []
    for i, (col, y, g) in enumerate(rng.sample(field_cells, min(46, len(field_cells)))):
        flickers.append(
            f'<text x="{num(col * ART_CW)}" y="{num(y)}" fill="{c["flash"][i % 2]}" opacity="0">{esc(g)}'
            f'<animate attributeName="opacity" values="0;0;.95;0" keyTimes="0;.8;.84;1" '
            f'dur="{rng.uniform(5, 11):.1f}s" begin="{rng.uniform(0, 8):.1f}s" repeatCount="indefinite"/></text>')

    img_top = row_y(off) - ART_LH * 0.78
    if eye:
        ex = sum(x for x, _ in eye) / len(eye) + ART_CW / 2
        ey = sum(y for _, y in eye) / len(eye) - ART_LH * 0.3
    else:
        ex, ey = IMG_W / 2, (img_top + height) / 2
    tone_css = "\n".join(f".t{k} {{fill: {v};}}" for k, v in c["tones"].items())

    return f"""<style>
{tone_css}
.te {{animation: eye 2.6s ease-in-out infinite;}}
@keyframes eye {{50% {{fill: {c['acc']};}}}}
</style>
<defs>
<clipPath id="card"><rect width="{CARD_W}" height="{num(height)}" rx="14"/></clipPath>
<g id="field">{"".join(field_rows)}</g>
<radialGradient id="fieldGrad" cx=".45" cy=".4" r=".65">
  <stop offset=".35" stop-color="#fff"/><stop offset="1" stop-color="#000"/>
</radialGradient>
<mask id="fieldFade" maskUnits="userSpaceOnUse" x="0" y="0" width="{num(field_w)}" height="{num(height)}">
  <rect width="{num(field_w)}" height="{num(height)}" fill="url(#fieldGrad)"/>
</mask>
<linearGradient id="topGrad" gradientUnits="userSpaceOnUse" x1="0" y1="{num(img_top)}" x2="0" y2="{num(img_top + 70)}">
  <stop offset="0" stop-color="#000"/><stop offset="1" stop-color="#fff"/>
</linearGradient>
<linearGradient id="rightGrad" gradientUnits="userSpaceOnUse" x1="{num(IMG_W - 70)}" y1="0" x2="{num(IMG_W)}" y2="0">
  <stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/>
</linearGradient>
<mask id="rightFade" maskUnits="userSpaceOnUse" x="0" y="0" width="{CARD_W}" height="{num(height)}">
  <rect width="{num(IMG_W)}" height="{num(height)}" fill="url(#rightGrad)"/>
</mask>
<mask id="artFade" maskUnits="userSpaceOnUse" x="0" y="0" width="{CARD_W}" height="{num(height)}">
  <g mask="url(#rightFade)"><rect width="{num(IMG_W)}" height="{num(height)}" fill="url(#topGrad)"/></g>
</mask>
<linearGradient id="sheen" gradientUnits="userSpaceOnUse" x1="-130" y1="{num(img_top)}" x2="0" y2="{num(img_top + 90)}">
  <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".7"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  <animateTransform attributeName="gradientTransform" type="translate" values="0 0;{num(IMG_W + 260)} 0;{num(IMG_W + 260)} 0" keyTimes="0;.24;1" dur="8s" begin="1.4s" repeatCount="indefinite"/>
</linearGradient>
<filter id="soft" filterUnits="userSpaceOnUse" x="0" y="0" width="{CARD_W}" height="{num(height)}">
  <feGaussianBlur stdDeviation="7"/>
</filter>
<mask id="ripple" maskUnits="userSpaceOnUse" x="0" y="0" width="{num(field_w)}" height="{num(height)}">
  <circle cx="{num(ex)}" cy="{num(ey)}" r="0" fill="none" stroke="#fff" stroke-width="30" filter="url(#soft)">
    <animate attributeName="r" values="20;440;440" keyTimes="0;.45;1" dur="6s" begin="2.6s" repeatCount="indefinite"/>
    <animate attributeName="stroke-opacity" values="1;0;0" keyTimes="0;.45;1" dur="6s" begin="2.6s" repeatCount="indefinite"/>
  </circle>
</mask>
</defs>
<g clip-path="url(#card)" font-size="{num(ART_FONT)}px">
  <g mask="url(#fieldFade)">
    <use href="#field" fill="{c['field']}" opacity="{c['field_opacity']}"/>
    <g mask="url(#ripple)"><use href="#field" fill="{c['acc']}" opacity=".9"/></g>
    {"".join(flickers)}
  </g>
  <circle cx="{num(ex)}" cy="{num(ey)}" r="14" fill="{c['acc']}" opacity=".25" filter="url(#soft)">
    <animate attributeName="opacity" values=".1;.6;.1" dur="2.6s" repeatCount="indefinite"/>
  </circle>
  <g mask="url(#artFade)" font-weight="bold">
    {"".join(art_rows)}
    <g fill="url(#sheen)">{"".join(plain_rows)}</g>
  </g>
</g>"""


def build_card(theme: str) -> str:
    c = THEMES[theme]
    top = PAD + 6
    panel, panel_h = build_panel(top + PANEL_FONT)
    height = round(top + panel_h + PAD)
    art = build_art(height, c)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}" height="{height}" viewBox="0 0 {CARD_W} {height}" font-family="{FONT}">
<title>{esc(CFG['title'])}</title>
<style>
text {{white-space: pre;}}
.panel {{fill: {c['fg']};}}
.key {{fill: {c['key']};}}
.title {{fill: {c['acc']}; font-weight: bold;}}
.acc {{fill: {c['acc']};}}
.value {{fill: {c['value']};}}
.dots {{fill: {c['dots']};}}
.add {{fill: {c['add']};}}
.del {{fill: {c['del']};}}
</style>
<rect x=".5" y=".5" width="{CARD_W - 1}" height="{height - 1}" rx="14" fill="{c['bg']}" stroke="{c['border']}"/>
{art}
<g class="panel" font-size="{PANEL_FONT}px">
{panel}
</g>
</svg>
"""


# --- Link buttons -------------------------------------------------------------
# Each button is its own image, one equal share of the card's width; the gaps
# between them are drawn inside the images so the row lines up with the card.
GAP = 12
BTN_COUNT = len(CFG["buttons"])
BTN_W = (CARD_W - (BTN_COUNT - 1) * GAP) / BTN_COUNT
SLOT_W = CARD_W / BTN_COUNT
BTN_H = 56
PX = 2                               # one icon pixel

ICONS = {
    "portfolio": SP_LOGO,
    "linkedin": """
.#######.
#########
#.##.####
#########
#.##...##
#.##.#.##
#.##.#.##
#########
.#######.
""",
    "email": """
############
##........##
#.#......#.#
#..#....#..#
#...####...#
#..........#
#..........#
############
""",
}
BADGE = """
.##.
####
####
.##.
"""


def pixel_path(art: str, scale: int = PX) -> str:
    d = []
    for y, row in enumerate(bitmap(art)):
        x = 0
        while x < len(row):
            if row[x] == "#":
                start = x
                while x < len(row) and row[x] == "#":
                    x += 1
                d.append(f"M{start * scale} {y * scale}h{(x - start) * scale}v{scale}h{-(x - start) * scale}z")
            else:
                x += 1
    return "".join(d)


def icon_markup(name: str, accent: str) -> str:
    path = pixel_path(ICONS[name])
    h = len(bitmap(ICONS[name])) * PX
    if name == "portfolio":
        # A light bar scans down the logo every few seconds.
        return (f'<clipPath id="ic"><path d="{path}"/></clipPath>'
                f'<path d="{path}" fill="{accent}"/>'
                f'<g clip-path="url(#ic)"><rect x="0" y="-4" width="40" height="3" fill="#fff" opacity=".8">'
                f'<animate attributeName="y" values="-4;{h + 2};{h + 2}" keyTimes="0;.3;1" dur="3.2s" repeatCount="indefinite"/>'
                f'</rect></g>')
    if name == "linkedin":
        return (f'<g><animateTransform attributeName="transform" type="translate" '
                f'values="0 0;0 -2;0 0" keyTimes="0;.82;.9" dur="2.4s" calcMode="discrete" repeatCount="indefinite"/>'
                f'<path d="{path}" fill="{accent}"/></g>')
    # email: rattles, then a notification dot blinks on the corner
    w = len(bitmap(ICONS[name])[0]) * PX
    return (f'<g><animateTransform attributeName="transform" type="translate" '
            f'values="0 0;-2 0;2 0;-2 0;2 0;0 0" keyTimes="0;.7;.74;.78;.82;.86" dur="3s" '
            f'calcMode="discrete" repeatCount="indefinite"/>'
            f'<path d="{path}" fill="{accent}"/>'
            f'<path transform="translate({w - 4} -4)" d="{pixel_path(BADGE)}" fill="#f85149" opacity="0">'
            f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.72;.95;1" dur="3s" '
            f'calcMode="discrete" repeatCount="indefinite"/></path></g>')


def build_button(theme: str, slot: int) -> str:
    c = THEMES[theme]
    name, label = CFG["buttons"][slot]
    accent = {"portfolio": c["acc"], "linkedin": c["key"], "email": c["key"]}[name]
    x = slot * GAP / BTN_COUNT      # where this button sits inside its share of the row
    art = bitmap(ICONS[name])
    icon_w, icon_h = len(art[0]) * PX, len(art) * PX
    font = 15
    label_w = len(label) * font * 0.6 + (len(label) - 1) * 2
    left = x + (BTN_W - icon_w - 12 - label_w) / 2
    mid = (BTN_H - 4) / 2
    bar_x, bar_w = x + 16, BTN_W - 32
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{num(SLOT_W)}" height="{BTN_H}" viewBox="0 0 {num(SLOT_W)} {BTN_H}" font-family="{FONT}">
<defs>
<clipPath id="bar"><rect x="{num(bar_x)}" y="{BTN_H - 8}" width="{num(bar_w)}" height="2" rx="1"/></clipPath>
<linearGradient id="glow"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<rect x="{num(x + .5)}" y=".5" width="{num(BTN_W - 1)}" height="{BTN_H - 1}" rx="10" fill="{c['bg']}" stroke="{c['border']}"/>
<rect x="{num(bar_x)}" y="{BTN_H - 8}" width="{num(bar_w)}" height="2" rx="1" fill="{accent}" opacity=".7"/>
<g clip-path="url(#bar)"><rect x="{num(bar_x - 90)}" y="{BTN_H - 8}" width="90" height="2" fill="url(#glow)">
<animate attributeName="x" values="{num(bar_x - 90)};{num(bar_x + bar_w)};{num(bar_x + bar_w)}" keyTimes="0;.35;1" dur="4.5s" begin="{slot * 0.5}s" repeatCount="indefinite"/>
</rect></g>
<g transform="translate({num(left)} {num(mid - icon_h / 2)})">{icon_markup(name, accent)}</g>
<text x="{num(left + icon_w + 12)}" y="{num(mid + font * 0.36)}" font-size="{font}px" letter-spacing="2" fill="{c['fg']}">{esc(label)}</text>
</svg>
"""


# --- Pac-Man ------------------------------------------------------------------
def recolor_pacman() -> list[str]:
    written = []
    for theme, src in (("dark", "pacman-contribution-graph-dark.svg"),
                       ("light", "pacman-contribution-graph.svg")):
        path = ROOT / "dist" / src
        if not path.exists():
            continue
        svg = path.read_text(encoding="utf-8")
        for old, new in THEMES[theme]["pacman"].items():
            svg = re.sub(re.escape(old), new, svg, flags=re.IGNORECASE)
        out = OUT / f"pacman_{theme}.svg"
        out.write_text(svg, encoding="utf-8")
        written.append(out.name)
    return written


def main() -> None:
    OUT.mkdir(exist_ok=True)
    print(f"uptime: {uptime()} | stats: {'cache/stats.json' if STATS.exists() else 'none yet, showing --'}")
    for theme in THEMES:
        (OUT / f"card_{theme}.svg").write_text(build_card(theme), encoding="utf-8")
        for slot, (name, _) in enumerate(CFG["buttons"]):
            (OUT / f"button_{name}_{theme}.svg").write_text(build_button(theme, slot), encoding="utf-8")
    pac = recolor_pacman()
    print("pacman:", ", ".join(pac) if pac else "skipped (no dist/ from the Pac-Man action)")
    for f in sorted(OUT.glob("*.svg")):
        print(f"  {f.name:32} {f.stat().st_size:>8,} bytes")


if __name__ == "__main__":
    main()
