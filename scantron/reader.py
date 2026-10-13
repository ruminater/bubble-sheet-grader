"""Turning registered pages into answers and names.

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

from .sheet import Registration, darkness, register, render

CHOICES = "ABCDE"

# A filled bubble scores 70-150 above the page's own blank level; printed
# letters, stray smudges and good erasures stay under 30.
FILLED = 45
# A second bubble at least this fraction as dark as the darkest one makes the
# answer ambiguous, which is flagged for a person to look at.
MULTI_RATIO = 0.6
LIGHT = 70  # answers read, but fainter than this, are flagged


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
    side: int
    reg: Registration
    pdf: bytes  # the whole upload, shared by its pages; re-rendered for the scan view
    answers: dict[int, Answer] = field(default_factory=dict)
    name: str = ""
    name_flags: list[int] = field(default_factory=list)  # character rows needing a look

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


def read_page(page: pymupdf.Page, index: int, pdf: bytes) -> Page:
    # The rendered image is 8 MB a page, so it is dropped once read.
    img = render(page)
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
    return out


@dataclass
class Sheet:
    """One physical answer sheet: side 1, and side 2 when it was scanned."""

    number: int  # 1-based position in the upload
    source: str
    side1: Page | None = None
    side2: Page | None = None

    @property
    def name(self) -> str:
        return self.side2.name if self.side2 else ""

    @property
    def answers(self) -> dict[int, Answer]:
        out = {}
        for p in (self.side1, self.side2):
            if p:
                out.update(p.answers)
        return out

    @property
    def is_blank(self) -> bool:
        return not self.name and not any(a.choice for a in self.answers.values())


def read_pdf(data: bytes, source: str) -> tuple[list[Sheet], list[str]]:
    """Read every page; pair each side 1 with the side 2 that follows it.

    Returns the sheets and a list of problems (pages that could not be read).
    """
    doc = pymupdf.open(stream=data, filetype="pdf")
    sheets: list[Sheet] = []
    problems: list[str] = []
    for i, pg in enumerate(doc):
        try:
            p = read_page(pg, i, data)
        except ValueError as exc:
            problems.append(f"{source}, page {i + 1}: {exc}")
            continue
        if p.side == 1 or not sheets or sheets[-1].side2 is not None:
            sheets.append(Sheet(len(sheets) + 1, source))
        if p.side == 1:
            sheets[-1].side1 = p
        else:
            sheets[-1].side2 = p
    return sheets, problems
