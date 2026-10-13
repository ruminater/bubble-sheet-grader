"""A picture of what the reader saw, for checking a sheet by eye."""

from __future__ import annotations

import io

import pymupdf
from PIL import Image, ImageDraw

from .reader import FILLED, Page, _question_slots
from .sheet import render

GREEN = (22, 150, 70)
RED = (210, 40, 40)
BLUE = (40, 90, 220)
ORANGE = (235, 140, 0)


def render_page(page: Page, key: dict[int, str] | None) -> bytes:
    pixels = render(pymupdf.open(stream=page.pdf, filetype="pdf")[page.index])
    img = Image.fromarray(pixels.astype("uint8")).convert("RGB")
    draw = ImageDraw.Draw(img)
    r = 11
    for q, u_a, v in _question_slots(page.side):
        a = page.answers.get(q)
        k = (key or {}).get(q)
        if a is None:
            continue
        for c, letter in enumerate("ABCDE"):
            x, y = page.reg.to_page(u_a + c, v)
            box = (x - r, y - r, x + r, y + r)
            filled = a.choice == letter or (
                a.flag == "multiple" and a.scores[c] >= FILLED
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
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
