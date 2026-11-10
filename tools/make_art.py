"""Turn a picture into the coloured ASCII art shown on the card.

Run this once on your own computer whenever you want a new picture; the
GitHub Action only reads the result (assets/art.json), so it never needs the
picture or Pillow.

    pip install pillow
    python tools/make_art.py path/to/picture.jpg --glow 0.42,0.33

Works best with a figure on a plain white background. Every character gets a
tone: d (dark outline), 1/2/3 (deep/mid/light purple), g (neon green),
h (white highlight) or e (highlight that pulses green, picked with --glow as
x,y fractions of the picture, e.g. an eye).
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAMP = " .:-=+*#%@"                  # sparse -> dense


def background_mask(im: Image.Image, white: int) -> list[list[bool]]:
    """White pixels connected to the picture's edge (white inside the figure, like an eye, is not background)."""
    w, h = im.size
    px = im.load()
    is_white = [[min(px[x, y]) >= white for x in range(w)] for y in range(h)]
    bg = [[False] * w for _ in range(h)]
    queue = deque((x, y) for x in range(w) for y in (0, h - 1)) + deque((x, y) for y in range(h) for x in (0, w - 1))
    while queue:
        x, y = queue.popleft()
        if 0 <= x < w and 0 <= y < h and is_white[y][x] and not bg[y][x]:
            bg[y][x] = True
            queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return bg, is_white


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cols", type=int, default=96)
    ap.add_argument("--white", type=int, default=215, help="how light counts as background")
    ap.add_argument("--glow", help="x,y (0-1) of a highlight that should pulse green")
    args = ap.parse_args()

    im = Image.open(args.image).convert("RGB")
    w, h = im.size
    cols = args.cols
    rows = round(cols * h / w / 2)   # a character cell is twice as tall as it is wide
    bg, is_white = background_mask(im, args.white)
    px = im.load()
    glow = tuple(float(v) for v in args.glow.split(",")) if args.glow else None

    # First pass: tone and brightness for every cell.
    cells = {}
    for r in range(rows):
        for c in range(cols):
            x0, x1 = c * w // cols, (c + 1) * w // cols
            y0, y1 = r * h // rows, (r + 1) * h // rows
            cell = [(x, y) for y in range(y0, y1) for x in range(x0, x1)]
            fig = [(x, y) for x, y in cell if not bg[y][x]]
            if len(fig) < len(cell) * 0.45:
                continue
            n_hi = sum(is_white[y][x] for x, y in fig)
            rr, gg, bb = (sum(px[x, y][i] for x, y in fig) / len(fig) for i in range(3))
            lum = 0.299 * rr + 0.587 * gg + 0.114 * bb
            if n_hi > len(fig) * 0.5:
                near = glow and abs((c + .5) / cols - glow[0]) < .06 and abs((r + .5) / rows - glow[1]) < .06
                tone = "e" if near else "h"
            elif gg > rr + 30 and gg > bb + 20:
                tone = "g"
            elif lum < 32:
                tone = "d"                  # black ink: stays a gap, like the outlines
            elif lum < 90:
                tone = "1"                  # shadows, incl. the orange chest -> deep purple
            elif lum < 150:
                tone = "2"
            else:
                tone = "3"
            cells[c, r] = (tone, lum)

    # Spread brightness over the dense half of the ramp so the figure reads
    # as solid, with texture coming from relative (not absolute) brightness.
    lums = sorted(l for t, l in cells.values() if t != "d")
    def density(lum: float) -> str:
        rank = sum(1 for l in lums if l <= lum) / max(1, len(lums))
        return RAMP[4 + min(5, int(rank * 6))]

    chars, tones = [], []
    for r in range(rows):
        line, tone_line = [], []
        for c in range(cols):
            tone, lum = cells.get((c, r), (".", 0))
            if tone == ".":
                ch = " "
            elif tone == "d":
                ch = "."
            elif tone in "ghe":
                ch = "@" if tone != "g" else "#"
            else:
                ch = density(lum)
            line.append(ch)
            tone_line.append(tone)
        chars.append("".join(line))
        tones.append("".join(tone_line))

    out = ROOT / "assets" / "art.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"cols": cols, "rows": rows, "chars": chars, "tones": tones}, indent=1))
    print("\n".join(chars))
    print(f"wrote {out.relative_to(ROOT)} ({cols} x {rows})")


if __name__ == "__main__":
    main()
