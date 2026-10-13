"""Reading sheets made by the Bubble Sheet Creator (bubblesheets/ in this repository).

Those sheets describe themselves, so nothing about a particular sheet is kept
here: omr_layout.py (a copy of the Creator's layout.py) turns the code strips
along the top and bottom edges into every bubble's position.

Reading one scanned page:

1. Find every solid square on it: a window solid black inside and white
   around, which no text, bubble, dash or code cell can imitate (a filled
   bubble is round, and too small to fill the window).
2. Take each four that form a rectangle of a sheet's shape: 7.4 by 9.9 inches
   between square centres for a full page, 7.4 by 4.4 for a half. A half page
   scanned alone, on Letter settings, sideways, or still uncut beside its
   twin, all come down to this.
3. For each, try the four ways round it could be. The right one has the sync
   bits and a matching CRC in both strips; a page none of them fits is not one
   of these sheets, and the 16485 reader gets a go.
4. Stand the scan upright (quarter turns) and fit a perspective transform
   from the sheet's corners to the scan's, which cancels shift, scale,
   rotation and keystone at once.
5. Find the timing dash at both ends of every bubble row and record how far
   each sits from where the transform put it. A roller-fed copier stretches
   a page unevenly, and those offsets, blended across the row, follow it.
6. Score each bubble as in reader.py: darkness inside it, less the median of
   bubbles of the same kind on the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from . import omr_layout as L

DPI = 150
SAMPLE_R = 0.055  # inches; the printed bubble's radius is 0.085
MAX_SQUARES = 16


def _px(inches: float) -> float:
    return inches * DPI


def _homography(src, dst) -> np.ndarray:
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(a, float), np.array(b, float))
    return np.append(h, 1.0).reshape(3, 3)


def _apply(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    p = H @ np.array([x, y, 1.0])
    return p[0] / p[2], p[1] / p[2]


@dataclass
class Registration:
    turns: int  # quarter turns (np.rot90) that stand the scan upright
    paper: L.Paper
    H: np.ndarray  # sheet inches -> upright scan pixels
    left: np.ndarray  # per row: (dx, dy) of the left timing dash from where H put it
    right: np.ndarray
    corners: list[tuple[float, float]]  # TL, TR, BL, BR in the upright scan
    dashes_found: int

    def to_page(self, x: float, row: int) -> tuple[float, float]:
        """Sheet inches across, bubble row -> upright scan pixels."""
        px, py = _apply(self.H, x, self.paper.row_y(row))
        t = (x - L.FID_X[0]) / (L.FID_X[1] - L.FID_X[0])
        d = (1 - t) * self.left[row] + t * self.right[row]
        return px + d[0], py + d[1]

    def crop(self, shape: tuple[int, int]) -> tuple[int, int, int, int]:
        """The sheet's own area of the upright scan, for showing it alone: (x0, y0, x1, y1)."""
        pts = [_apply(self.H, x, y) for x in (0.0, L.PAGE_W) for y in (0.0, self.paper.height)]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        h, w = shape
        return (max(0, int(min(xs))), max(0, int(min(ys))), min(w, int(max(xs))), min(h, int(max(ys))))


# ------------------------------------------------------------ corner squares


def _box_sums(ii: np.ndarray, half: int, m: int, h: int, w: int) -> np.ndarray:
    """Sum of a (2*half+1)^2 box centred on every (y, x) in [m, h-m) x [m, w-m)."""
    y0, y1, x0, x1 = m - half, h - m - half, m - half, w - m - half
    s = 2 * half + 1
    return ii[y0 + s : y1 + s, x0 + s : x1 + s] - ii[y0:y1, x0 + s : x1 + s] - ii[y0 + s : y1 + s, x0:x1] + ii[y0:y1, x0:x1]


def _squares(dark: np.ndarray) -> list[tuple[float, float]]:
    """Centres of the solid squares anywhere on the page, strongest first."""
    h, w = dark.shape
    f = _px(L.FID)
    inner, ring_in, ring_out = int(0.4 * f), int(0.65 * f), int(0.85 * f)
    m = ring_out
    if h <= 2 * m + 2 or w <= 2 * m + 2:
        return []
    ii = np.zeros((h + 1, w + 1))
    ii[1:, 1:] = dark.cumsum(0).cumsum(1)
    a = _box_sums(ii, inner, m, h, w) / (2 * inner + 1) ** 2
    ring = (_box_sums(ii, ring_out, m, h, w) - _box_sums(ii, ring_in, m, h, w)) / (
        (2 * ring_out + 1) ** 2 - (2 * ring_in + 1) ** 2)
    score = np.where((a >= 0.9) & (ring <= 0.2), a - ring, 0.0)
    out = []
    r = int(0.7 * f)
    while len(out) < MAX_SQUARES:
        y, x = np.unravel_index(int(np.argmax(score)), score.shape)
        if score[y, x] <= 0:
            break
        score[max(0, y - 2 * r) : y + 2 * r + 1, max(0, x - 2 * r) : x + 2 * r + 1] = 0
        cy, cx = y + m, x + m
        patch = dark[max(0, cy - r) : cy + r + 1, max(0, cx - r) : cx + r + 1]
        ys, xs = np.nonzero(patch)
        out.append((max(0, cx - r) + xs.mean(), max(0, cy - r) + ys.mean()))
    return out


def _rectangles(pts: list[tuple[float, float]]):
    """Each four squares that make a sheet's rectangle: (paper, corners in order round it)."""
    across = L.FID_X[1] - L.FID_X[0]
    for combo in combinations(range(len(pts)), 4):
        p = np.array([pts[i] for i in combo])
        c = p.mean(axis=0)
        p = p[np.argsort(np.arctan2(p[:, 1] - c[1], p[:, 0] - c[0]))]  # in order round it
        d1, d2 = np.linalg.norm(p[2] - p[0]), np.linalg.norm(p[3] - p[1])
        if abs(d1 - d2) > 0.03 * max(d1, d2):
            continue
        if np.linalg.norm((p[0] + p[2]) / 2 - (p[1] + p[3]) / 2) > 0.02 * d1:
            continue
        a, b = np.linalg.norm(p[1] - p[0]), np.linalg.norm(p[2] - p[1])
        for paper in L.PAPERS.values():
            down = paper.fid_y[1] - paper.fid_y[0]
            want = max(across, down) / min(across, down)
            if abs(max(a, b) / min(a, b) - want) > 0.03 * want:
                continue
            scale = max(a, b) / _px(max(across, down))
            if 0.7 <= scale <= 1.3:
                yield paper, [tuple(q) for q in p], combo


# ------------------------------------------------------------------ reading


def _mean_box(img: np.ndarray, x: float, y: float, half: int) -> float:
    xi, yi = int(round(x)), int(round(y))
    patch = img[max(0, yi - half) : yi + half + 1, max(0, xi - half) : xi + half + 1]
    return float(patch.mean()) if patch.size else 255.0


def _code(img, H, paper, white, black):
    mid = (white + black) / 2
    half = max(1, int(_px(0.03)))
    bits = [int(_mean_box(img, *_apply(H, x, y), half) < mid) for x, y in L.code_cells(paper)]
    got = L.decode(bits)
    return got if got and got[0].paper == paper.id else None


def _dash_offsets(img, H, paper, x_in, thr) -> tuple[np.ndarray, int]:
    """Per row, the timing dash's offset from where H puts it; smoothed, gaps filled."""
    hx, hy = int(_px(0.16)), int(_px(0.085))
    need = 0.3 * _px(L.DASH_W) * _px(L.DASH_H)
    cap = _px(0.1)
    raw = np.full((paper.rows, 2), np.nan)
    for r in range(paper.rows):
        px, py = _apply(H, x_in, paper.row_y(r))
        x0, y0 = int(px) - hx, int(py) - hy
        patch = img[max(0, y0) : y0 + 2 * hy + 1, max(0, x0) : x0 + 2 * hx + 1] < thr
        ys, xs = np.nonzero(patch)
        if len(xs) < need:
            continue
        d = (max(0, x0) + xs.mean() - px, max(0, y0) + ys.mean() - py)
        if abs(d[0]) < cap and abs(d[1]) < cap:
            raw[r] = d
    found = int((~np.isnan(raw[:, 0])).sum())
    out = np.zeros((paper.rows, 2))
    fallback = np.nanmedian(raw, axis=0) if found else np.zeros(2)
    for r in range(paper.rows):
        near = raw[max(0, r - 2) : r + 3]
        near = near[~np.isnan(near[:, 0])]
        out[r] = np.median(near, axis=0) if len(near) else fallback
    return out, found


def _turn_point(x: float, y: float, h: int, w: int) -> tuple[float, float]:
    """Where pixel (x, y) of an h-by-w image lands after np.rot90(img, 1)."""
    return y, w - 1 - x


def _upright(img, corners):
    """Quarter turns that put TL->TR pointing right; the turned image and corners."""
    (x0, y0), (x1, y1) = corners[0], corners[1]
    angle = np.degrees(np.arctan2(y1 - y0, x1 - x0))  # y down: 90 means pointing down
    turns = int(round(angle / 90)) % 4  # np.rot90 turns anticlockwise on screen
    up, pts = img, list(corners)
    for _ in range(turns):
        h, w = up.shape
        pts = [_turn_point(x, y, h, w) for x, y in pts]
        up = np.rot90(up)
    return turns, np.ascontiguousarray(up), pts


@dataclass
class Found:
    reg: Registration
    image: np.ndarray  # the scan, upright
    spec: L.Spec
    page: int  # from 0
    pages: int


def find(img: np.ndarray) -> list[Found]:
    """Every Bubble Sheet Creator sheet on one scanned page, top to bottom; often one, two for an uncut half page."""
    white = float(np.percentile(img, 95))
    thr = 0.5 * white
    dark = img < thr
    squares = _squares(dark)
    used: set[int] = set()
    out = []
    for paper, ring, combo in _rectangles(squares):
        if used & set(combo):
            continue
        black = float(np.mean([_mean_box(img, x, y, int(_px(0.06))) for x, y in ring]))
        src = [(L.FID_X[0], paper.fid_y[0]), (L.FID_X[1], paper.fid_y[0]),
               (L.FID_X[1], paper.fid_y[1]), (L.FID_X[0], paper.fid_y[1])]  # round the sheet
        for k in range(4):
            for order in (ring, ring[::-1]):  # whichever way round the angles ran
                pts = order[k:] + order[:k]
                H = _homography(src, pts)
                got = _code(img, H, paper, white, black)
                if got is None:
                    continue
                spec, page, pages = got
                tl, tr, br, bl = pts
                turns, up, (tl, tr, bl, br) = _upright(img, [tl, tr, bl, br])
                corners = [tl, tr, bl, br]
                Hu = _homography(src, [tl, tr, br, bl])
                left, nl = _dash_offsets(up, Hu, paper, L.FID_X[0], thr)
                right, nr = _dash_offsets(up, Hu, paper, L.FID_X[1], thr)
                reg = Registration(turns, paper, Hu, left, right, corners, nl + nr)
                out.append((pts[0][1] + pts[0][0] * 1e-3, Found(reg, up, spec, page, pages)))
                used |= set(combo)
                break
            else:
                continue
            break
    # Top of the scan first, as a person reads an uncut page.
    return [f for _, f in sorted(out, key=lambda t: t[0])]


_DISC_HALF = int(np.ceil(_px(SAMPLE_R))) + 1
_yy, _xx = np.mgrid[-_DISC_HALF : _DISC_HALF + 1, -_DISC_HALF : _DISC_HALF + 1]
_DISC = np.hypot(_yy, _xx) <= _px(SAMPLE_R)


def darkness(img: np.ndarray, reg: Registration, x: float, row: int) -> float:
    """Mean darkness (0 white .. 255 black) inside the bubble centred at x on row."""
    px, py = reg.to_page(x, row)
    xi, yi = int(round(px)), int(round(py))
    patch = img[yi - _DISC_HALF : yi + _DISC_HALF + 1, xi - _DISC_HALF : xi + _DISC_HALF + 1]
    if patch.shape != _DISC.shape:
        return 0.0
    return float(255 - patch[_DISC].mean())
