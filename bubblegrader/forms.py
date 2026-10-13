"""Reading printed vendor forms that carry one timing mark per row down one edge.

Scantron 882-E and Apperson DataLink 3000 #20420 are read here; form 16485
(sheet.py) and Bubble Sheet Creator sheets (omr.py) have readers of their own.

Both forms put a column of short dashes down one long edge, one per bubble
row, 1/6 inch apart. Reading one scanned page:

1. Find every small solid blob, in the scan as it is and turned a quarter.
2. Take a vertical column of dashes of one form's size: the timing track.
   The bubbles are to the right of the track when the sheet is upright, so
   more ink to its left means the scan is upside down.
3. Number the dashes down the track, skipping any a mark or smudge hid, and
   slide that pattern along each form side's own pattern of dashes (the
   gaps tell an 882-E side 1 from side 2, and an Apperson from a 16485,
   whose marks are the same size but run without a gap). The best fit
   names the form and side and says which row each dash is.
4. Fit a line through the dashes: that gives the origin, the scale and the
   skew, and every bubble is placed by (u, v) = (pitches right of the
   track, row), as for form 16485 in sheet.py.

Bubble positions were measured from blank scans of each form (2026-10-13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .sheet import DPI, PITCH, Registration

INK = 170  # darker than this is ink: the Apperson's marks print mid-grey


@dataclass(frozen=True)
class Side:
    """One side of a form, in lattice units: v rows down the track, u pitches right of it."""

    side: int
    marks: frozenset[int]  # rows that carry a timing dash
    anchor: int  # a row whose dash must be found: the one after a gap, or a tall one
    questions: tuple[tuple[int, float, tuple[float, ...]], ...]  # (question, v, u per choice)
    key: tuple[float, float] | None = None  # (u, v) of the bubble that marks the key sheet
    key_peers: tuple[tuple[float, float], ...] = ()  # empty bubbles beside it, to judge it by
    id_columns: tuple[tuple[float, tuple[float, ...]], ...] = ()  # (u, v per digit 0-9)
    version: tuple[tuple[str, float, float], ...] = ()  # (letter, u, v)
    points: tuple[tuple[int, float, float], ...] = ()  # (value, u, v): subjective score bubbles
    mark_v: dict[int, float] = field(default_factory=dict)  # a dash printed off its row: where it is


@dataclass(frozen=True)
class Form:
    id: str
    label: str
    choices: str
    mark_w: tuple[float, float]  # inches, a timing dash's width across the track
    mark_h: tuple[float, float]  # inches, its height along it
    filled: float  # a bubble this much darker than an empty one is marked
    light: float  # a mark lighter than this is read, and flagged for a look
    sides: tuple[Side, ...]

    def side(self, n: int) -> Side:
        return next(s for s in self.sides if s.side == n)

    @property
    def last_question(self) -> int:
        return max(q for s in self.sides for q, _, _ in s.questions)


def _column(first_q: int, v0: float, us: tuple[float, ...], n: int) -> list:
    return [(first_q + k, v0 + k, us) for k in range(n)]


# Scantron 882-E. Side 1, from the top: four rows of subjective score
# bubbles (rows 0-3), the KEY row (5, a tall dash) whose fifth bubble marks
# the key, then questions 1-50 on rows 6-55. Side 2: the KEY row again
# (0) and questions 51-100 on rows 1-50. Each bubble sits 0.16 of a row
# below its dash, which is thin and prints along the row's top.
_882_U = (3.29, 5.27, 7.26, 9.24, 11.22)
_882_DV = 0.16
F882E = Form(
    id="882-E",
    label="Scantron form 882-E",
    choices="ABCDE",
    mark_w=(0.18, 0.23),
    mark_h=(0.012, 0.15),
    filled=35,  # a blank side reads under 8; pencil 47-79; a stray line 20-43
    light=45,
    sides=(
        Side(
            1,
            frozenset([0, 1, 2, 3, *range(5, 56)]),
            5,
            tuple(_column(1, 6 + _882_DV, _882_U, 50)),
            key=(_882_U[4], 5 + _882_DV),
            key_peers=tuple((u, 5 + _882_DV) for u in _882_U[:3]),
            points=tuple(
                (val, _882_U[c], r + _882_DV)
                for r, row in enumerate(((100, 90, 80, 70, 60), (50, 40, 30, 20, 10),
                                         (9, 8, 7, 6, 5), (4, 3, 2, 1, 0)))
                for c, val in enumerate(row)
            ),
        ),
        Side(
            2,
            frozenset(range(0, 51)),
            0,
            tuple(_column(51, 1 + _882_DV, _882_U, 50)),
            key=(_882_U[4], _882_DV),
            key_peers=tuple((u, _882_DV) for u in _882_U[:3]),
        ),
    ),
)

# Apperson DataLink 3000, reorder #20420. One side. Rows 0-57 run the full
# height: questions 93-150 in the right column; the Student ID and Test ID
# grids (digits 0-9 on rows 1-10) above questions 1-46 and 47-92, which
# start on row 12. The Key / Verify / Rescore / Test Version row sits off
# the lattice, 5.78 rows above row 0, and so does its dash (counted as row -6).
_APP_U = (2.24, 3.76, 5.26, 6.77, 8.28)
_APP_TOP = -5.78


def _shift(us: tuple[float, ...], d: float) -> tuple[float, ...]:
    return tuple(round(u + d, 2) for u in us)


APPERSON = Form(
    id="apperson-20420",
    label="Apperson DataLink 3000 (#20420)",
    choices="ABCDE",
    mark_w=(0.14, 0.185),
    mark_h=(0.04, 0.095),
    filled=25,  # its pencil scans lighter: a blank side reads under 19, marks 31-100
    light=35,
    sides=(
        Side(
            1,
            frozenset([-6, *range(0, 59)]),
            -6,
            tuple(
                _column(1, 12, _APP_U, 46)
                + _column(47, 12, _shift(_APP_U, 10.58), 46)
                + _column(93, 0, _shift(_APP_U, 21.15), 58)
            ),
            key=(3.78, _APP_TOP),
            key_peers=((9.82, _APP_TOP), (15.81, _APP_TOP)),  # Verify, Rescore
            id_columns=tuple((round(2.24 + 1.51 * c, 2), tuple(range(1, 11))) for c in range(9)),
            version=tuple(zip("ABCD", (21.86, 23.36, 24.87, 26.38), [_APP_TOP] * 4)),
            mark_v={-6: _APP_TOP},
        ),
    ),
)

FORMS = (F882E, APPERSON)


# --- finding the track -------------------------------------------------------


def _blobs(mask: np.ndarray, max_size: int) -> list[tuple[int, int, int, int, int]]:
    """Connected blobs no bigger than max_size either way: (x0, y0, x1, y1, area).

    Horizontal runs are joined row to row. Anything that grows past max_size
    (a grid border, a heading bar) is dropped as soon as it does, which keeps
    this quick on a page of text.
    """
    h, _ = mask.shape
    parent: list[int] = []
    box: list[list[int]] = []
    big: list[bool] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    pad = np.zeros((h, 1), np.int8)
    d = np.diff(np.hstack([pad, mask.astype(np.int8), pad]), axis=1)
    prev: list[tuple[int, int, int]] = []
    for y in range(h):
        starts = np.flatnonzero(d[y] == 1)
        ends = np.flatnonzero(d[y] == -1)
        cur = []
        j = 0
        for s, e in zip(starts.tolist(), ends.tolist()):
            while j < len(prev) and prev[j][1] <= s:
                j += 1
            k, root = j, -1
            while k < len(prev) and prev[k][0] < e:
                r = find(prev[k][2])
                if root < 0:
                    root = r
                elif r != root:
                    parent[r] = root
                    a, b = box[root], box[r]
                    box[root] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                    big[root] = big[root] or big[r]
                k += 1
            if root < 0:
                root = len(parent)
                parent.append(root)
                box.append([s, y, e - 1, y, 0])
                big.append(False)
            b = box[root]
            b[0], b[2], b[3], b[4] = min(b[0], s), max(b[2], e - 1), y, b[4] + e - s
            if b[2] - b[0] > max_size or b[3] - b[1] > max_size:
                big[root] = True
            cur.append((s, e, root))
        prev = cur
    return [tuple(box[i]) for i in range(len(parent)) if find(i) == i and not big[i]]


@dataclass
class Track:
    turns: int  # quarter turns (np.rot90) that stand the scan upright
    marks: list[tuple[float, float, float, float]]  # (x, y, w, h) in the upright scan


def _half_turn(marks, shape):
    """The same marks in np.rot90(img, 2), for marks found in img."""
    h, w = shape
    return [(w - 1 - x, h - 1 - y, mw, mh) for x, y, mw, mh in marks]


def _tracks(scans: list[tuple[np.ndarray, list]], form: Form) -> list[Track]:
    """Every vertical column of this form's dashes, in the scan and turned a quarter.

    scans: (the scan turned k quarters, its blobs) for k = 0 and 1.
    """
    out = []
    for k, (im, dash) in enumerate(scans):
        wmin, wmax = (v * DPI for v in form.mark_w)
        hmin, hmax = (v * DPI for v in form.mark_h)
        cand = []
        for x0, y0, x1, y1, area in dash:
            w, h = x1 - x0 + 1, y1 - y0 + 1
            if wmin <= w <= wmax and hmin <= h <= hmax and area >= 0.6 * w * h:
                cand.append(((x0 + x1) / 2, (y0 + y1) / 2, w, h, y0))
        if len(cand) < 20:
            continue
        xs = np.array([c[0] for c in cand])
        # The densest x: a track drifts a few pixels down a skewed page.
        best = max(xs, key=lambda x: int(np.sum(np.abs(xs - x) < 0.06 * DPI)))
        col = [c for c in cand if abs(c[0] - best) < 0.1 * DPI]
        if len(col) < 20:
            continue
        # Refit the column as a line and keep what lies on it.
        cx = np.polyfit([c[1] for c in col], [c[0] for c in col], 1)
        col = [c for c in cand if abs(c[0] - np.polyval(cx, c[1])) < 0.05 * DPI]
        marks = sorted(((c[0], c[1], c[2], c[3]) for c in col), key=lambda m: m[1])
        # Bubbles lie to the right of an upright track.
        xt = float(np.median([m[0] for m in marks]))
        ya, yb = int(marks[0][1]), int(marks[-1][1])
        span = int(2.5 * DPI)
        right = (im[ya:yb, int(xt + 0.25 * DPI): int(xt) + span] < INK).mean() if xt + 0.25 * DPI < im.shape[1] else 0
        lo = max(0, int(xt) - span)
        left = (im[ya:yb, lo: max(lo, int(xt - 0.25 * DPI))] < INK).mean() if xt - 0.25 * DPI > 0 else 0
        turns = k if right >= left else k + 2
        if turns != k:
            marks = sorted(_half_turn(marks, im.shape), key=lambda m: m[1])
        # A tall dash's centre is not its row's: its top is, as for a thin one.
        thin = float(np.median([m[3] for m in marks]))
        marks = [(x, y - h / 2 + thin / 2 if h > 1.6 * thin else y, w, h) for x, y, w, h in marks]
        out.append(Track(turns, marks))
    return out


def _number(marks) -> tuple[list[int], float]:
    """Each dash's row, counted from the first, and the pitch in pixels."""
    ys = np.array([m[1] for m in marks])
    gaps = np.diff(ys)
    steps = gaps[(gaps > 0.7 * PITCH) & (gaps < 1.3 * PITCH)]
    pitch = float(np.median(steps)) if len(steps) else PITCH
    idx = [int(round((y - ys[0]) / pitch)) for y in ys]
    # Refit against the rough numbering, which removes most of the drift.
    b, a = np.polyfit(idx, ys, 1)
    return [int(round((y - a) / b)) for y in ys], float(b)


def _match(idx: list[int], side: Side) -> tuple[int, int, int]:
    """Best (score, shift, extra dashes) sliding the found rows along this side's pattern.

    A dash the pattern does not have counts against a fit three times over: a
    dash can hide under a smudge, but none appears where the form has none.
    """
    found = set(idx)
    best = (-10**9, 0, 0)
    for s in range(side.anchor - max(found), side.anchor - min(found) + 1):
        moved = {i + s for i in found}
        if side.anchor not in moved:
            continue
        hit = len(moved & side.marks)
        extra = len(moved - side.marks)
        score = hit - 3 * extra
        if score > best[0]:
            best = (score, s, extra)
    return best


@dataclass
class Found:
    form: Form
    side: Side
    turns: int
    reg: Registration
    image: np.ndarray = field(repr=False)  # the upright scan


def find(img: np.ndarray) -> Found | None:
    """The form and side on this scanned page, registered; None if it is neither form."""
    best = None
    scans = [(im, _blobs(im < INK, int(0.3 * DPI))) for im in (img, np.rot90(img))]
    for form in FORMS:
        for t in _tracks(scans, form):
            idx, _ = _number(t.marks)
            for side in form.sides:
                score, shift, extra = _match(idx, side)
                need = len(side.marks)
                if extra > 2 or score < 0.85 * need:
                    continue
                if best is None or score / need > best[0]:
                    best = (score / need, form, side, t, [i + shift for i in idx])
    if best is None:
        return None
    _, form, side, t, rows = best
    up = np.ascontiguousarray(np.rot90(img, t.turns))
    v = np.array([side.mark_v.get(r, r) for r in rows], float)
    xs = np.array([m[0] for m in t.marks])
    ys = np.array([m[1] for m in t.marks])
    b, oy = np.polyfit(v, ys, 1)
    e, ox = np.polyfit(v, xs, 1)
    reg = Registration(side.side, float(ox), float(oy), float(b), float(e), len(rows))
    return Found(form, side, t.turns, reg, up)
