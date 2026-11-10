"""Build every SVG the profile README shows, in a dark and a light version.

    python tools/build.py

Reads profile.json (what the card says) and cache/stats.json (GitHub numbers
from fetch_stats.py) and writes into generated/:

  card_{dark,light}.svg          the terminal card: SP logo + info panel
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
LOGO_GLYPHS = "#@%&$0B8DHMNQW"

THEMES = {
    "dark": {
        "bg": "#0f0d17", "border": "#2b2640", "fg": "#c9c6d9",
        "key": "#9d8afa", "value": "#ece9fb", "dots": "#4a4560",
        "add": "#3fb950", "del": "#f85149",
        "field": "#8a86a0", "field_opacity": 0.16, "flash": "#cecafb",
        "logo": ("#8A73F9", "#B4A3FB", "#E8E4FD"),
        "linkedin": "#4493f8", "email": "#e8e4fd",
        # Pac-Man (github-dark) colour -> card colour
        "pacman": {"#0d1117": "#0f0d17", "#161b22": "#1a1726", "#0e4429": "#2e2457",
                   "#006d32": "#4b3a9e", "#26a641": "#6f58e6", "#39d353": "#b4a3fb"},
    },
    "light": {
        "bg": "#ffffff", "border": "#ddd8ee", "fg": "#2a2638",
        "key": "#6a4ff0", "value": "#1f1b2e", "dots": "#aaa5be",
        "add": "#1a7f37", "del": "#cf222e",
        "field": "#6b6680", "field_opacity": 0.2, "flash": "#6a4ff0",
        "logo": ("#4f33d6", "#7a62f5", "#a08cfa"),
        "linkedin": "#0a66c2", "email": "#8A73F9",
        # Pac-Man (github light) colour -> card colour
        "pacman": {"#ebedf0": "#eeebf7", "#9be9a8": "#d9d1fd", "#40c463": "#b4a3fb",
                   "#30a14e": "#8a73f9", "#216e39": "#5b3fe0"},
    },
}

# The SP logo is drawn on a 14 x 8 grid (512 / 14 = 36.57, the size of every
# block in public/SP_WHITE.svg). The two rounded corners are handled below.
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
ROUNDED = {(0, 0): "top-left", (12, 0): "top-right"}


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

ART_COLS = 66
ART_CW = ART_W / ART_COLS           # 6px
ART_LH = 2 * ART_CW                 # a logo block = 4 cols x 2 rows = square
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
    cursor = ('<tspan class="value">█<animate attributeName="fill-opacity" values="1;0" '
              'dur="1.1s" calcMode="discrete" repeatCount="indefinite"/></tspan>')
    out.append(render_row([("> ", "key")], top + i * LINE, cursor, extra_chars=1))
    return "\n".join(out), (i + 1) * LINE


# --- Logo art -----------------------------------------------------------------
def build_art(top: float, height: float, c: dict) -> str:
    rng = random.Random(7)              # fixed seed: the art doesn't churn each day
    rows = int(height // ART_LH)
    y0 = top + (height - rows * ART_LH) / 2
    logo = bitmap(SP_LOGO)
    lc0 = (ART_COLS - len(logo[0]) * 4) // 2
    lr0 = (rows - len(logo) * 2) // 2

    logo_cells = set()
    for py, line in enumerate(logo):
        for px, ch in enumerate(line):
            if ch != "#":
                continue
            for dx in range(4):
                for dy in range(2):
                    corner = ROUNDED.get((px, py))
                    if dy == 0 and ((corner == "top-left" and dx == 0) or
                                    (corner == "top-right" and dx == 3)):
                        continue
                    logo_cells.add((lc0 + px * 4 + dx, lr0 + py * 2 + dy))

    def near_logo(col: int, row: int) -> bool:
        return any((col + dx, row + dy) in logo_cells for dx in range(-3, 4) for dy in range(-2, 3))

    field_rows, logo_rows, field_cells = [], [], []
    for r in range(rows):
        y = num(y0 + r * ART_LH + ART_LH * 0.78)
        f, l = [], []
        for col in range(ART_COLS):
            if (col, r) in logo_cells:
                f.append(" ")
                l.append(rng.choice(LOGO_GLYPHS))
            elif near_logo(col, r):
                f.append(" ")
                l.append(" ")
            else:
                g = rng.choice(FIELD_GLYPHS)
                f.append(g)
                l.append(" ")
                field_cells.append((col, r, g, y))
        x = xs(PAD, ART_CW, ART_COLS)
        field_rows.append(f'<text x="{x}" y="{y}">{esc("".join(f))}</text>')
        if "".join(l).strip():
            logo_rows.append(f'<text x="{x}" y="{y}">{esc("".join(l))}</text>')

    # A few field glyphs light up now and then, like the site background.
    flickers = []
    for col, r, g, y in rng.sample(field_cells, 42):
        dur = rng.uniform(5, 11)
        flickers.append(
            f'<text x="{num(PAD + col * ART_CW)}" y="{y}" fill="{c["flash"]}" opacity="0">{esc(g)}'
            f'<animate attributeName="opacity" values="0;0;.95;0" keyTimes="0;.8;.84;1" '
            f'dur="{dur:.1f}s" begin="{rng.uniform(0, 8):.1f}s" repeatCount="indefinite"/></text>')

    lx, ly = PAD + lc0 * ART_CW, y0 + lr0 * ART_LH
    lw, lh = len(logo[0]) * 4 * ART_CW, len(logo) * 2 * ART_LH
    cx, cy = lx + lw / 2, ly + lh / 2
    a, b, e = c["logo"]

    return f"""<defs>
<g id="field">{"".join(field_rows)}</g>
<g id="logo">{"".join(logo_rows)}</g>
<linearGradient id="logoFill" gradientUnits="userSpaceOnUse" x1="{num(lx)}" y1="{num(ly)}" x2="{num(lx + lw)}" y2="{num(ly + lh)}">
  <stop offset="0" stop-color="{a}"/><stop offset=".55" stop-color="{b}"/><stop offset="1" stop-color="{e}"/>
</linearGradient>
<linearGradient id="sheen" gradientUnits="userSpaceOnUse" x1="{num(lx - 110)}" y1="{num(ly)}" x2="{num(lx)}" y2="{num(ly + 70)}">
  <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  <animateTransform attributeName="gradientTransform" type="translate" values="0 0;{num(lw + 110)} 0;{num(lw + 110)} 0" keyTimes="0;.22;1" dur="7s" begin="1.4s" repeatCount="indefinite"/>
</linearGradient>
<radialGradient id="fadeGrad" cx=".5" cy=".5" r=".6">
  <stop offset=".45" stop-color="#fff"/><stop offset="1" stop-color="#000"/>
</radialGradient>
<mask id="fade" maskUnits="userSpaceOnUse" x="{PAD}" y="{num(top)}" width="{ART_W}" height="{num(height)}">
  <rect x="{PAD}" y="{num(top)}" width="{ART_W}" height="{num(height)}" fill="url(#fadeGrad)"/>
</mask>
<filter id="soft" filterUnits="userSpaceOnUse" x="{PAD}" y="{num(top)}" width="{ART_W}" height="{num(height)}">
  <feGaussianBlur stdDeviation="7"/>
</filter>
<mask id="ripple" maskUnits="userSpaceOnUse" x="{PAD}" y="{num(top)}" width="{ART_W}" height="{num(height)}">
  <circle cx="{num(cx)}" cy="{num(cy)}" r="0" fill="none" stroke="#fff" stroke-width="30" filter="url(#soft)">
    <animate attributeName="r" values="60;380;380" keyTimes="0;.42;1" dur="6s" begin="3s" repeatCount="indefinite"/>
    <animate attributeName="stroke-opacity" values="1;0;0" keyTimes="0;.42;1" dur="6s" begin="3s" repeatCount="indefinite"/>
  </circle>
</mask>
</defs>
<g mask="url(#fade)" font-size="{num(ART_FONT)}px">
  <use href="#field" fill="{c['field']}" opacity="{c['field_opacity']}"/>
  <g mask="url(#ripple)"><use href="#field" fill="{c['flash']}"/></g>
  {"".join(flickers)}
</g>
<g font-size="{num(ART_FONT)}px" font-weight="bold">
  <use href="#logo" fill="url(#logoFill)"/>
  <use href="#logo" fill="url(#sheen)"/>
</g>"""


def build_card(theme: str) -> str:
    c = THEMES[theme]
    top = PAD + 6
    panel, panel_h = build_panel(top + PANEL_FONT)
    height = round(top + panel_h + PAD)
    art = build_art(PAD, height - 2 * PAD, c)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{CARD_W}" height="{height}" viewBox="0 0 {CARD_W} {height}" font-family="{FONT}">
<title>{esc(CFG['title'])}</title>
<style>
text {{white-space: pre;}}
.panel {{fill: {c['fg']};}}
.key {{fill: {c['key']};}}
.title {{fill: {c['key']}; font-weight: bold;}}
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
GAP = 12
BTN_W = (CARD_W - 2 * GAP) / 3
SLOT_W = CARD_W / 3
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
    accent = {"portfolio": c["key"], "linkedin": c["linkedin"], "email": c["email"]}[name]
    x = slot * GAP / 3              # where this button sits inside its third of the row
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
