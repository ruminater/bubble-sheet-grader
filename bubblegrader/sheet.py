"""Reading one page of a Scantron form 16485 (General Purpose Answer Sheet).

Every bubble on the form sits on a 1/6-inch lattice anchored to the timing
marks: rows are mark indices, columns are 1/6-inch steps away from the mark
column. So a page is registered by finding its timing marks and fitting a line
through them, which gives the origin, the scale and any skew of the scan. A
bubble is then located by (u, v) = (lattice columns from the marks, mark
index), with no image-wide alignment step.

Side 1 has its marks on the left edge, side 2 on the right.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf

DPI = 150
PITCH = DPI / 6  # one lattice step: 1/6 inch
MARK_DARK = 110  # a timing mark pixel is darker than this
BUBBLE_R = 6.0  # radius sampled inside a bubble; printed outline is ~9.5


@dataclass
class Registration:
    side: int  # 1 or 2
    ox: float  # centre of mark 0, pixels
    oy: float
    b: float  # pixels per mark index, down the page
    e: float  # sideways drift per mark index (skew)
    marks: int  # how many marks were found

    def to_page(self, u: float, v: float) -> tuple[float, float]:
        """Lattice (u columns right of the marks, v mark index) -> pixels."""
        x = self.ox + v * self.e + u * self.b
        y = self.oy + v * self.b - u * self.e
        return x, y


def render(page: pymupdf.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    return img.astype(np.float32)


def _runs(flags: np.ndarray, min_len: int, max_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(np.append(flags, False)):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if min_len <= i - start <= max_len:
                out.append((start, i - 1))
            start = None
    return out


def _find_marks(img: np.ndarray, x0: int, x1: int) -> list[tuple[float, float]]:
    """Timing marks in the strip x0..x1: [(x_centre, y_centre)]."""
    strip = img[:, x0:x1] < MARK_DARK
    rows = strip.mean(axis=1) > 0.2
    marks = []
    for ys, ye in _runs(rows, int(PITCH * 0.2), int(PITCH * 0.55)):
        block = strip[ys : ye + 1]
        cols = np.where(block.mean(axis=0) > 0.5)[0]
        if len(cols) < PITCH * 0.6:  # marks are ~1 lattice step wide
            continue
        marks.append((x0 + (cols[0] + cols[-1]) / 2, (ys + ye) / 2))
    return marks


def register(img: np.ndarray) -> Registration:
    h, w = img.shape
    edge = int(PITCH * 3.5)
    left = _find_marks(img, 0, edge)
    right = _find_marks(img, w - edge, w)
    side, marks = (1, left) if len(left) >= len(right) else (2, right)
    if len(marks) < 30:
        raise ValueError(
            f"found only {len(marks)} timing marks; this does not look like a form 16485 page"
        )
    # Mark 0 is the top one. Missing marks (the one hidden by the grey divider
    # bar, say) are skipped by rounding each mark to its nearest index.
    y0 = marks[0][1]
    idx = np.array([round((y - y0) / PITCH) for _, y in marks], float)
    xs = np.array([x for x, _ in marks])
    ys = np.array([y for _, y in marks])
    b, oy = np.polyfit(idx, ys, 1)
    e, ox = np.polyfit(idx, xs, 1)
    return Registration(side, ox, oy, b, e, len(marks))


_yy, _xx = np.mgrid[-8:9, -8:9]
_DISC = np.hypot(_yy, _xx) <= BUBBLE_R


def darkness(img: np.ndarray, reg: Registration, u: float, v: float) -> float:
    """Mean darkness (0 white .. 255 black) inside the bubble at (u, v)."""
    x, y = reg.to_page(u, v)
    xi, yi = int(round(x)), int(round(y))
    patch = img[yi - 8 : yi + 9, xi - 8 : xi + 9]
    if patch.shape != _DISC.shape:
        return 0.0
    return float(255 - patch[_DISC].mean())
