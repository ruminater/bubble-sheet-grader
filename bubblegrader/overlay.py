"""A picture of what the reader saw, for checking a sheet by eye."""

from __future__ import annotations

import io

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

from .reader import FILLED, FILLED_OMR, Page
from .sheet import render

GREEN = (22, 150, 70)
RED = (210, 40, 40)
BLUE = (40, 90, 220)
ORANGE = (235, 140, 0)


def render_page(page: Page, key: dict[int, str] | None) -> bytes:
    pixels = render(pymupdf.open(stream=page.pdf, filetype="pdf")[page.index])
    pixels = np.rot90(pixels, page.turns)  # upright, as it was read
    img = Image.fromarray(np.ascontiguousarray(pixels).astype("uint8")).convert("RGB")
    draw = ImageDraw.Draw(img)
    r = 11 if page.spec is None else 13
    if page.spec:
        filled_at = FILLED_OMR
    else:
        filled_at = page.form.filled if page.form else FILLED
    for q, centres in page.positions.items():
        a = page.answers.get(q)
        k = (key or {}).get(q)
        if a is None:
            continue
        for c, (letter, (x, y)) in enumerate(zip(page.qlabels.get(q, page.choices), centres)):
            box = (x - r, y - r, x + r, y + r)
            filled = a.choice == letter or (
                a.flag == "multiple" and a.scores[c] >= filled_at
            )
            if filled:
                if a.flag:
                    colour = ORANGE
                elif k is None:
                    colour = BLUE
                else:
                    colour = GREEN if letter == k else RED
                draw.ellipse(box, outline=colour, width=3)
            elif k == letter and a.choice != k:
                draw.ellipse(box, outline=BLUE, width=2)
    if page.crop:  # one half of an uncut page, say: show that sheet alone
        img = img.crop(page.crop)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
