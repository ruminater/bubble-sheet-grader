"""Turning registered pages into answers and names.

Two kinds of sheet are read: Scantron form 16485, laid out below, and sheets
from the Bubble Sheet Creator, which carry their own layout (see omr.py). Each
page is tried as a Bubble Sheet Creator page first: that test is cheap and
cannot pass by accident, since it needs four corner squares and a code strip
with a matching checksum.

Layout of form 16485 in lattice units (see sheet.py). Each block of ten
questions uses every other mark: the bubble rows, with the printed A B C D E
header on the row between.

Side 1: marks on the left. Question 1's A bubble is at u=3.05, mark 21;
        question 61's at mark 43. Six columns of questions, 8 units apart.
Side 2: marks on the right. Question 121's A bubble is at u=-46.2, mark 22;
        question 181's at mark 44. The name grid is above: one row per
        character from mark 2 to mark 20, A at u=-5 through Z at u=-30, and a
        blank "space" bubble at u=-4.

The ID number and birth date grids on side 2 are not read yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pymupdf

from . import forms, omr
from . import omr_layout as OL
from .sheet import Registration, darkness, register, render

CHOICES = "ABCDE"

# A filled bubble scores 70-150 above the page's own blank level; printed
# letters, stray smudges and good erasures stay under 30.
FILLED = 45
# A second bubble at least this fraction as dark as the darkest one makes the
# answer ambiguous, which is flagged for a person to look at.
MULTI_RATIO = 0.6
LIGHT = 70  # answers read, but fainter than this, are flagged
# Bubble Sheet Creator pages print no letters heavy enough to matter: an empty
# bubble reads within a few points of its own column's level, and a rubbed-out
# mark about 15. So a lighter mark counts there, which lets an X through to be
# flagged as light rather than read as blank.
FILLED_OMR = 35


def _question_slots(side: int) -> list[tuple[int, float, int]]:
    """[(question number, u of bubble A, mark index)] for one side."""
    if side == 1:
        first_q, u_a, rows = 1, 3.05, (21, 43)
    else:
        first_q, u_a, rows = 121, -46.2, (22, 44)
    slots = []
    for block, v0 in enumerate(rows):
        for col in range(6):
            for k in range(10):
                q = first_q + block * 60 + col * 10 + k
                slots.append((q, u_a + 8 * col, v0 + 2 * k))
    return slots


NAME_ROWS = range(2, 21)
NAME_ALPHABET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # index 0 is the space bubble


def _name_u(i: int) -> float:
    return -4.0 - i


@dataclass
class Answer:
    question: int
    choice: str  # "" when blank; the darkest bubble otherwise
    scores: list[float]
    flag: str = ""  # "", "multiple", "light"


@dataclass
class Page:
    index: int  # page number in the PDF, from 0
    side: int  # 16485: side 1 or 2. Bubble Sheet Creator: page of the sheet, from 1
    reg: Registration | omr.Registration
    pdf: bytes  # the whole upload, shared by its pages; re-rendered for the scan view
    answers: dict[int, Answer] = field(default_factory=dict)
    name: str = ""
    name_flags: list[int] = field(default_factory=list)  # character rows needing a look
    student_id: str = ""
    id_flags: list[int] = field(default_factory=list)  # ID digits needing a look
    key_marked: bool = False  # the ANSWER KEY bubble is filled
    spec: OL.Spec | None = None  # None for form 16485
    form: forms.Form | None = None  # a vendor form other than 16485 (forms.py)
    points: int | None = None  # 882-E: the subjective score bubbled by the instructor
    version: str = ""  # Apperson: the Test Version bubbled
    pages: int = 2  # pages (sides) in a whole sheet of this kind
    choices: str = CHOICES
    turns: int = 0  # quarter turns that stand the scan upright
    crop: tuple[int, int, int, int] | None = None  # the sheet's area of the upright scan
    qlabels: dict[int, str] = field(default_factory=dict)  # each question's bubbles, when not `choices`
    # Bubble centres in the upright scan, for drawing what was read.
    positions: dict[int, list[tuple[float, float]]] = field(default_factory=dict)

    @property
    def marked(self) -> int:
        return sum(1 for a in self.answers.values() if a.choice)


def _baseline(img, reg, points):
    """Blank level per point: median over many bubbles of the same kind.

    Bubbles A and B carry printed T and F, so each choice column gets its own
    baseline. Most bubbles on any sheet are empty, so the median is the empty
    level even on a fully answered sheet (at most 1 in 5 per column is filled).
    """
    return float(np.median([darkness(img, reg, u, v) for u, v in points]))


def _pick(scores: list[float], filled: float = FILLED_OMR, light: float = LIGHT) -> tuple[int | None, str]:
    """(darkest bubble or None when blank, flag) for one question or grid column."""
    order = np.argsort(scores)[::-1]
    top = scores[order[0]]
    if top < filled:
        return None, ""
    second = scores[order[1]] if len(scores) > 1 else 0.0
    if second >= filled and second >= MULTI_RATIO * top:
        return int(order[0]), "multiple"
    if top < light:
        return int(order[0]), "light"
    return int(order[0]), ""


def _empty_levels(by_kind: dict, every: list[float]) -> dict:
    """Each kind of bubble's empty level, from those of its kind that look empty.

    A plain median of a kind fails when most of that kind are filled: a
    true/false key that is mostly T, or a student ID of 111111111. So first
    find the page's empty level from all its bubbles (most bubbles on any
    sheet are empty: at least half on true/false, nine in ten in an ID grid),
    then take each kind's median over the ones near it.
    """
    floor = float(np.percentile(every, 30)) if every else 0.0
    out = {}
    for kind, values in by_kind.items():
        empty = [v for v in values if v < floor + FILLED_OMR / 2]
        out[kind] = float(np.median(empty)) if len(empty) >= 3 else floor
    return out


def _grid_read(img, reg, grid: OL.Grid) -> tuple[str, list[int]]:
    """One character per column ("" for blank), and the columns to check."""
    n = len(grid.alphabet)
    per = [[omr.darkness(img, reg, b.x, b.row) for b in col] for col in grid.columns]
    levels = _empty_levels({k: [col[k] for col in per] for k in range(n)}, [d for col in per for d in col])
    base = [levels[k] for k in range(n)]
    chars, flags = [], []
    for c, col in enumerate(per):
        k, flag = _pick([d - base[i] for i, d in enumerate(col)])
        chars.append("" if k is None else grid.alphabet[k])
        if flag == "multiple":
            flags.append(c)
    return chars, flags


def _read_sheet(f: omr.Found, index: int, pdf: bytes) -> Page | None:
    reg, up, spec = f.reg, f.image, f.spec
    lay = OL.layout(spec)
    if f.page >= len(lay) or len(lay) != f.pages:
        return None
    pl = lay[f.page]
    out = Page(index, f.page + 1, reg, pdf, spec=spec, pages=f.pages,
               choices=spec.choice_labels, turns=reg.turns, crop=reg.crop(up.shape))

    # Each label's empty level, from the bubbles with that label on the page;
    # sections differ in their bubbles, so labels, not positions, are the kinds.
    dark = {q.number: [omr.darkness(up, reg, b.x, b.row) for b in q.bubbles] for q in pl.questions}
    every = [x for d in dark.values() for x in d] or [0.0]
    by_label: dict[str, list[float]] = {}
    for q in pl.questions:
        for b, d in zip(q.bubbles, dark[q.number]):
            by_label.setdefault(b.label, []).append(d)
    base = _empty_levels(by_label, every)
    for q in pl.questions:
        labels = "".join(b.label for b in q.bubbles)
        scores = [d - base[lab] for lab, d in zip(labels, dark[q.number])]
        k, flag = _pick(scores)
        out.answers[q.number] = Answer(q.number, "" if k is None else labels[k], scores, flag)
        out.positions[q.number] = [reg.to_page(b.x, b.row) for b in q.bubbles]
        out.qlabels[q.number] = labels

    for g in pl.grids:
        chars, flags = _grid_read(up, reg, g)
        if g.kind == "name":
            out.name = " ".join("".join(c or " " for c in chars).split())
            out.name_flags = flags
        else:
            digits = "".join(c or "_" for c in chars).rstrip("_")
            out.student_id = digits.lstrip("_") if not digits.strip("_") else digits
            out.id_flags = flags
    if pl.key:
        # An empty key bubble has no letter in it, so it sits below the
        # lettered bubbles' level; a filled one is far above it.
        floor = float(np.percentile(every, 30))
        out.key_marked = omr.darkness(up, reg, pl.key.x, pl.key.row) - floor >= FILLED_OMR
    return out


def _bubbles(img, reg, spots) -> list[float]:
    return [darkness(img, reg, u, v) for u, v in spots]


def _read_form(f: forms.Found, index: int, pdf: bytes) -> Page:
    """One side of an 882-E or Apperson form, placed by its timing track."""
    img, reg, side, form = f.image, f.reg, f.side, f.form
    out = Page(index, side.side, reg, pdf, form=form, pages=len(form.sides),
               choices=form.choices, turns=f.turns)
    n = len(form.choices)
    filled = form.filled
    dark = {q: _bubbles(img, reg, [(u, v) for u in us]) for q, v, us in side.questions}
    every = [d for ds in dark.values() for d in ds]
    # Each choice column prints its own letter, some darker than others, so
    # each column has its own empty level: the median of its lighter
    # bubbles. A side holds 50 to 150 questions, few of them in any one
    # column filled, so its lightest quarter is empty.
    base = {}
    for c in range(n):
        col = np.array([ds[c] for ds in dark.values()])
        low = col[col <= np.percentile(col, 25) + filled / 2]
        base[c] = float(np.median(low))
    for q, v, us in side.questions:
        scores = [d - base[c] for c, d in enumerate(dark[q])]
        # The forms shade bands of rows; a row's median bubble is an empty
        # one, since at most two of its five are filled, so it carries the band.
        band = float(np.median(scores))
        scores = [x - band for x in scores]
        k, flag = _pick(scores, filled, form.light)
        out.answers[q] = Answer(q, "" if k is None else form.choices[k], scores, flag)
        out.positions[q] = [reg.to_page(u, v) for u in us]
    if side.key:
        # Its neighbours on the row are seldom marked; the key bubble is judged against them.
        peers = float(np.median(_bubbles(img, reg, side.key_peers)))
        out.key_marked = darkness(img, reg, *side.key) - peers >= filled
    if side.id_columns:
        grid = [_bubbles(img, reg, [(u, v) for v in vs]) for u, vs in side.id_columns]
        levels = _empty_levels({k: [col[k] for col in grid] for k in range(10)}, [d for col in grid for d in col])
        digits = []
        for c, col in enumerate(grid):
            k, flag = _pick([d - levels[i] for i, d in enumerate(col)], filled)
            digits.append("_" if k is None else str(k))
            if flag == "multiple":
                out.id_flags.append(c)
        out.student_id = "".join(digits).strip("_")
    if side.version:
        d = _bubbles(img, reg, [(u, v) for _, u, v in side.version])
        k, _ = _pick([x - float(np.median(d)) for x in d], filled)
        out.version = "" if k is None else side.version[k][0]
    if side.points:
        # Values from different rows add up (100 + 20 is 120), so each row is
        # read on its own, against its own median: one bubble a row at most.
        rows: dict[float, list[tuple[int, float]]] = {}
        for val, u, v in side.points:
            rows.setdefault(v, []).append((val, darkness(img, reg, u, v)))
        total, any_marked = 0, False
        for cells in rows.values():
            mid = float(np.median([d for _, d in cells]))
            k, _ = _pick([d - mid for _, d in cells], filled)
            if k is not None:
                total, any_marked = total + cells[k][0], True
        out.points = total if any_marked else None
    return out


def read_page(page: pymupdf.Page, index: int, pdf: bytes) -> list[Page]:
    """The sheets on one scanned page: usually one; two for an uncut half page."""
    # The rendered image is 8 MB a page, so it is dropped once read.
    img = render(page)
    if (img < 128).mean() < 0.0002:
        return []  # blank paper: the back of a one-sided form, say
    made = [p for f in omr.find(img) if (p := _read_sheet(f, index, pdf))]
    if made:
        return made
    if found := forms.find(img):
        return [_read_form(found, index, pdf)]
    reg = register(img)
    out = Page(index, reg.side, reg, pdf)

    slots = _question_slots(reg.side)
    base = [_baseline(img, reg, [(u + c, v) for _, u, v in slots]) for c in range(5)]
    for q, u, v in slots:
        scores = [darkness(img, reg, u + c, v) - base[c] for c in range(5)]
        order = np.argsort(scores)[::-1]
        top, second = scores[order[0]], scores[order[1]]
        if top < FILLED:
            out.answers[q] = Answer(q, "", scores)
            continue
        flag = ""
        if second >= FILLED and second >= MULTI_RATIO * top:
            flag = "multiple"
        elif top < LIGHT:
            flag = "light"
        out.answers[q] = Answer(q, CHOICES[order[0]], scores, flag)
    for q, u, v in slots:
        out.positions[q] = [reg.to_page(u + c, v) for c in range(5)]

    if reg.side == 2:
        cols = range(len(NAME_ALPHABET))
        nbase = [
            _baseline(img, reg, [(_name_u(i), v) for v in NAME_ROWS]) for i in cols
        ]
        chars = []
        for row, v in enumerate(NAME_ROWS):
            s = [darkness(img, reg, _name_u(i), v) - nbase[i] for i in cols]
            order = np.argsort(s)[::-1]
            if s[order[0]] < FILLED:
                chars.append(" ")
                continue
            if s[order[1]] >= FILLED and s[order[1]] >= MULTI_RATIO * s[order[0]]:
                out.name_flags.append(row)
            chars.append(NAME_ALPHABET[order[0]])
        out.name = " ".join("".join(chars).split())
    return [out]


@dataclass
class Sheet:
    """One physical answer sheet: its pages (for form 16485, side 1 and side 2)."""

    number: int  # 1-based position in the upload
    source: str
    pages: dict[int, Page] = field(default_factory=dict)  # by side or page number, from 1

    @property
    def side1(self) -> Page | None:
        return self.pages.get(1)

    @property
    def side2(self) -> Page | None:
        return self.pages.get(2)

    @property
    def ordered(self) -> list[Page]:
        return [self.pages[k] for k in sorted(self.pages)]

    @property
    def first(self) -> Page:
        return self.ordered[0]

    @property
    def spec(self) -> OL.Spec | None:
        return self.first.spec if self.pages else None

    @property
    def vendor(self) -> forms.Form | None:
        return self.first.form if self.pages else None

    @property
    def form(self) -> str:
        if self.spec:
            return self.spec.describe()
        return self.vendor.label if self.vendor else "Scantron form 16485"

    @property
    def points(self) -> int | None:
        return next((p.points for p in self.ordered if p.points is not None), None)

    @property
    def version(self) -> str:
        return next((p.version for p in self.ordered if p.version), "")

    @property
    def choices(self) -> str:
        return self.first.choices if self.pages else CHOICES

    @property
    def name(self) -> str:
        return next((p.name for p in self.ordered if p.name), "")

    @property
    def student_id(self) -> str:
        return next((p.student_id for p in self.ordered if p.student_id), "")

    @property
    def key_marked(self) -> bool:
        return any(p.key_marked for p in self.pages.values())

    @property
    def answers(self) -> dict[int, Answer]:
        out = {}
        for p in self.ordered:
            out.update(p.answers)
        return out

    @property
    def is_blank(self) -> bool:
        return (not self.name and not self.student_id and not self.key_marked
                and not any(a.choice for a in self.answers.values()))

    def missing(self, questions: list[int]) -> list[str]:
        """Why some of these questions could not be read: pages not in the upload."""
        who = self.name or (f"ID {self.student_id}" if self.student_id else f"Sheet {self.number}")
        if self.vendor:
            out = []
            for side in self.vendor.sides:
                nums = [q for q, _, _ in side.questions if q in questions]
                if nums and side.side not in self.pages:
                    out.append(f"{who}: side {side.side} was not in the upload; "
                               f"questions {nums[0]}-{nums[-1]} scored as blank.")
            return out
        if self.spec is None:
            out = []
            if self.side1 is None and any(q <= 120 for q in questions):
                out.append(f"{who}: side 1 was not in the upload.")
            if self.side2 is None and any(q > 120 for q in questions):
                out.append(f"{who}: side 2 was not in the upload; questions 121+ scored as blank.")
            return out
        out = []
        for pl in OL.layout(self.spec):
            nums = [q.number for q in pl.questions if q.number in questions]
            if nums and pl.index + 1 not in self.pages:
                out.append(
                    f"{who}: page {pl.index + 1} was not in the upload; "
                    f"questions {nums[0]}-{nums[-1]} scored as blank."
                )
        return out


def _starts_sheet(p: Page, last: Sheet | None) -> bool:
    """Does this page begin a new sheet, or continue the one before it?

    A page continues the last sheet when it is the next page of the same kind
    of sheet; a duplex scan gives side 1, side 2, side 1, side 2...
    """
    if last is None or p.side == 1 or p.side in last.pages:
        return True
    if p.spec != last.spec or p.form is not last.first.form:
        return True
    if p.form is not None:
        return p.side - 1 not in last.pages
    return p.spec is not None and p.side - 1 not in last.pages


def read_pdf(data: bytes, source: str) -> tuple[list[Sheet], list[str]]:
    """Read every page; pair each side 1 with the side 2 that follows it.

    Returns the sheets and a list of problems (pages that could not be read).
    """
    doc = pymupdf.open(stream=data, filetype="pdf")
    sheets: list[Sheet] = []
    problems: list[str] = []
    for i, pg in enumerate(doc):
        try:
            found = read_page(pg, i, data)
        except ValueError as exc:
            problems.append(f"{source}, page {i + 1}: {exc}")
            continue
        for p in found:
            if _starts_sheet(p, sheets[-1] if sheets else None):
                sheets.append(Sheet(len(sheets) + 1, source))
            sheets[-1].pages[p.side] = p
    return sheets, problems
