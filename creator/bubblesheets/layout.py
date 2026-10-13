"""The bubble sheet format: where everything is on a page, and the code that says so.

This file is the whole contract between the sheet maker (bubblesheets/) and the
grader (scantron/). scantron/scantron/omr_layout.py is a byte-for-byte copy,
and a test in each project fails if the two drift. Change it here, copy it there.

A sheet describes itself. Two strips of black and white cells, along the top
and bottom edges, carry the sheet's settings (its sections, ID digits, name
letters, paper, page number), so the grader rebuilds the exact layout from the
paper alone: there is no registry of custom sheets to keep, and a sheet made
years ago still grades.

Registration is by four solid corner squares (a perspective fit, so rotation,
scale, shift and keystone from a copier or scanner cancel out) and a timing
dash on every bubble row down both edges, which corrects the uneven stretch a
roller-fed copier puts into a page. Everything is solid black on white, so a
sheet survives a black-and-white copier, and copies of copies.

A sheet is a full Letter page, or a half page: two to a Letter page, to be
cut apart. Each half carries its own squares, dashes and strips, so a half
reads alone, whichever way it is scanned, and an uncut page reads as two.

Printed sheets outlive code: an arrangement, once printed, never changes.
A different arrangement is a new FORMAT number, and layout() keeps answering
for the old ones. Format 1 (2026-10-13, one strip, full pages only) was never
printed and is not read.

Units are inches from the sheet's top-left corner, y down. Bubbles sit on
rows ROW_PITCH apart, from the paper's first row down.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

FORMAT = 3

PAGE_W, PAGE_H = 8.5, 11.0  # the Letter page a sheet is printed on

# Corner squares: side, and the centres' x. Their y depends on the paper.
FID = 0.25
FID_X = (0.55, 7.95)

ROW_PITCH = 0.20
DASH_W, DASH_H = 0.20, 0.08  # timing dashes, at the corner squares' x

# The code strips, between the top corner squares and between the bottom
# ones. Cells are shorter than a corner square so a run of black cells can
# never be taken for one.
CODE_X0 = 1.25  # left edge of cell 0
CODE_CELL = 0.125
CODE_H = 0.12
STRIP_BITS = 48
CODE_BITS = 2 * STRIP_BITS
SYNC_TOP = (1, 0, 1, 1)
SYNC_BOTTOM = (1, 1, 0, 1)  # each strip also ends in a 1

CONTENT_X0, CONTENT_X1 = 0.95, 7.55

BUBBLE_D = 0.17
CHOICE_PITCH = 0.24  # bubble to bubble, across a question or a grid
NUMBER_W = 0.32  # room for the question number, left of the first bubble
COL_GAP = 0.20  # least space between question columns
GRID_GAP = 0.30  # between the name grid, the ID grid and what is beside them
BLOCK = 5  # questions run in blocks of five, a blank row between

LABEL_SETS = {
    "letters": "ABCDEFGHIJ",
    "numbers": "123456789",
    "truefalse": "TF",
    "yesno": "YN",
}
TWO_WAY = {"truefalse": ("True/False", "T/F"), "yesno": ("Yes/No", "Y/N")}
NAME_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"

MAX_QUESTIONS = 250
MAX_SECTIONS = 4
MAX_PAGES = 4
MAX_ID = 12
MAX_NAME = 20


@dataclass(frozen=True)
class Paper:
    id: str
    label: str
    height: float  # of one sheet
    fid_y: tuple[float, float]
    row0_y: float
    rows: int
    per_page: int  # sheets printed on one Letter page

    def row_y(self, row: float) -> float:
        return self.row0_y + row * ROW_PITCH


PAPERS = {
    "full": Paper("full", "Full page", 11.0, (0.55, 10.45), 1.70, 42, 1),
    "half": Paper("half", "Half page", 5.5, (0.55, 4.95), 1.25, 17, 2),
}
PAPER_CODES = ("full", "half")


# ------------------------------------------------------------- the settings


@dataclass(frozen=True)
class Section:
    """A run of questions with the same bubbles."""

    questions: int
    choices: int = 5
    labels: str = "letters"  # a key of LABEL_SETS

    @property
    def choice_labels(self) -> str:
        return LABEL_SETS[self.labels][: self.choices]

    def describe(self) -> str:
        if self.labels in TWO_WAY:
            return TWO_WAY[self.labels][0]
        labels = self.choice_labels
        return f"{labels[0]}–{labels[-1]}"

    @property
    def typed(self) -> str:
        """The bubbles as a person types them: A-E, 1-5, T/F, Y/N."""
        if self.labels in TWO_WAY:
            return TWO_WAY[self.labels][1]
        labels = self.choice_labels
        return f"{labels[0]}-{labels[-1]}"

    def problems(self) -> list[str]:
        if self.labels not in LABEL_SETS:
            return ["Choose letters, numbers, true/false or yes/no for the bubble labels."]
        top = len(LABEL_SETS[self.labels])
        if self.labels in TWO_WAY:
            return [] if self.choices == 2 else [f"{TWO_WAY[self.labels][0]} questions have exactly two bubbles."]
        if not 2 <= self.choices <= top:
            return [f"Choices per question must be 2 to {top} with {self.labels}."]
        return []


def parse_bubbles(text: str) -> tuple[int, str]:
    """(choices, labels) from what a person types for a section's bubbles.

    Takes A-E, a-e, ABCDE, A B C D E, A,B,C; 1-5, 12345; T/F, TF, True/False;
    Y/N, Yes/No. Letters run from A (up to J) and numbers from 1 (up to 9),
    because every bubble's label is one character, and the code strips carry
    a kind of label, not the labels themselves. Raises ValueError, in words.
    """
    t = "".join(text.upper().split())
    t = t.replace("–", "-").replace("—", "-")
    for labels, (long, short) in TWO_WAY.items():
        if t in (short.replace("/", ""), short, short.replace("/", "-"), short.replace("/", ","),
                 long.upper(), long.upper().replace("/", "-"), long.upper().replace("/", ""),
                 long.upper().replace("/", ",")):
            return 2, labels
    if "-" in t:
        parts = t.split("-")
        if len(parts) == 2 and len(parts[0]) == 1 and len(parts[1]) == 1:
            a, b = parts
            for labels in ("letters", "numbers"):
                pool = LABEL_SETS[labels]
                if a == pool[0] and b in pool[1:]:
                    return pool.index(b) + 1, labels
    else:
        seq = t.replace(",", "").replace("/", "")
        for labels in ("letters", "numbers"):
            pool = LABEL_SETS[labels]
            if len(seq) >= 2 and pool.startswith(seq):
                return len(seq), labels
    raise ValueError(
        f"\"{text.strip()}\" is not a set of bubbles this sheet can print. Type A-E (letters from A, "
        "up to J), 1-5 (numbers from 1, up to 9), T/F or Y/N."
    )


@dataclass(frozen=True)
class Spec:
    """Everything that decides a sheet's layout. The code strips carry all of it."""

    sections: tuple[Section, ...] = (Section(50),)
    id_digits: int = 0
    name_letters: int = 0
    key_bubble: bool = True
    paper: str = "full"

    @classmethod
    def simple(cls, questions: int, choices: int = 5, labels: str = "letters", **kw) -> "Spec":
        return cls(sections=(Section(questions, choices, labels),), **kw)

    @property
    def questions(self) -> int:
        return sum(s.questions for s in self.sections)

    @property
    def sheet_paper(self) -> Paper:
        return PAPERS[self.paper]

    def section_of(self, question: int) -> Section:
        for s in self.sections:
            if question <= s.questions:
                return s
            question -= s.questions
        raise IndexError(question)

    @property
    def choice_labels(self) -> str:
        """Every label the sheet uses, in order of first use."""
        out = ""
        for s in self.sections:
            out += "".join(c for c in s.choice_labels if c not in out)
        return out

    def problems(self) -> list[str]:
        """Why this spec cannot be printed, in words for the person choosing it."""
        out = []
        if self.paper not in PAPERS:
            return ["Choose a full page or a half page."]
        if not 1 <= len(self.sections) <= MAX_SECTIONS:
            out.append(f"A sheet has 1 to {MAX_SECTIONS} sections.")
        for i, s in enumerate(self.sections, 1):
            where = f"Section {i}: " if len(self.sections) > 1 else ""
            out += [where + p for p in s.problems()]
            if s.questions < 1:
                out.append(f"{where}give it at least one question.")
        if not 1 <= self.questions <= MAX_QUESTIONS:
            out.append(f"A sheet holds 1 to {MAX_QUESTIONS} questions in all.")
        if not 0 <= self.id_digits <= MAX_ID:
            out.append(f"Student ID digits must be 0 (none) to {MAX_ID}.")
        if not (self.name_letters == 0 or 4 <= self.name_letters <= MAX_NAME):
            out.append(f"Name letters must be 0 (no name grid) or 4 to {MAX_NAME}.")
        if out:
            return out
        try:
            pages = layout(self)
        except ValueError as exc:
            return [str(exc)]
        if self.paper == "half" and len(pages) > 1:
            fits = len(pages[0].questions)
            out.append(
                f"A half page holds {fits} questions with these settings, not {self.questions}. "
                "Use fewer questions, or a full page."
            )
        elif len(pages) > MAX_PAGES:
            out.append(
                f"That needs {len(pages)} pages; a sheet can be at most {MAX_PAGES}. "
                "Use fewer questions, fewer choices, or drop the name grid."
            )
        return out

    def describe(self) -> str:
        if len(self.sections) == 1:
            parts = [f"{self.questions} questions, {self.sections[0].describe()}"]
        else:
            parts = [f"{self.questions} questions in {len(self.sections)} sections ("
                     + ", ".join(f"{s.questions} {s.describe()}" for s in self.sections) + ")"]
        if self.id_digits:
            parts.append(f"{self.id_digits}-digit ID")
        if self.name_letters:
            parts.append(f"{self.name_letters}-letter name")
        if self.paper == "half":
            parts.append("half page")
        return " · ".join(parts)


def capacity(spec: Spec) -> int:
    """How many questions the first page holds, laid out like the last section."""
    last = spec.sections[-1]
    more = replace(last, questions=MAX_QUESTIONS)
    pages = layout(replace(spec, sections=spec.sections[:-1] + (more,)))
    return len(pages[0].questions)


# ----------------------------------------------------------------- the code

# A section's bubbles as one 5-bit number: 0 true/false, 1-9 letters with
# 2-10 choices, 10-17 numbers with 2-9, 18 yes/no. New kinds take new numbers
# (up to 31); a number once given never changes meaning.
def _kind(s: Section) -> int:
    if s.labels == "truefalse":
        return 0
    if s.labels == "yesno":
        return 18
    if s.labels == "letters":
        return s.choices - 1
    return s.choices + 8


def _unkind(k: int) -> tuple[int, str] | None:
    if k == 0:
        return 2, "truefalse"
    if 1 <= k <= 9:
        return k + 1, "letters"
    if 10 <= k <= 17:
        return k - 8, "numbers"
    if k == 18:
        return 2, "yesno"
    return None


def _crc8(bits: list[int]) -> int:
    crc = 0xFF
    for b in bits:
        top = (crc >> 7) & 1
        crc = (crc << 1) & 0xFF
        if top ^ b:
            crc ^= 0x07
    return crc


def _put(bits: list[int], value: int, width: int) -> None:
    bits.extend((value >> (width - 1 - i)) & 1 for i in range(width))


class _Reader:
    def __init__(self, bits):
        self.bits, self.pos = bits, 0

    def take(self, width: int) -> int:
        v = 0
        for b in self.bits[self.pos : self.pos + width]:
            v = (v << 1) | b
        self.pos += width
        return v


PAYLOAD = 78  # bits, then a CRC-8: 86 in all, 43 in each strip


def encode(spec: Spec, page: int, pages: int) -> list[int]:
    """The CODE_BITS cells for one page (page counts from 0); 1 is black.

    The first STRIP_BITS go along the top edge, the rest along the bottom.
    """
    body: list[int] = []
    _put(body, FORMAT, 3)
    _put(body, page, 2)
    _put(body, pages - 1, 2)
    _put(body, PAPER_CODES.index(spec.paper), 1)
    _put(body, spec.id_digits, 4)
    _put(body, spec.name_letters, 5)
    _put(body, int(spec.key_bubble), 1)
    _put(body, len(spec.sections) - 1, 2)
    for i in range(MAX_SECTIONS):
        s = spec.sections[i] if i < len(spec.sections) else None
        _put(body, s.questions if s else 0, 8)
        _put(body, _kind(s) if s else 0, 5)
    _put(body, 0, PAYLOAD - len(body))  # reserved
    _put(body, _crc8(body), 8)
    half = len(body) // 2
    bits = list(SYNC_TOP) + body[:half] + [1] + list(SYNC_BOTTOM) + body[half:] + [1]
    assert len(bits) == CODE_BITS
    return bits


def decode(bits: list[int]) -> tuple[Spec, int, int] | None:
    """(spec, page from 0, pages) from the cells read off a page, or None."""
    if len(bits) != CODE_BITS:
        return None
    top, bottom = bits[:STRIP_BITS], bits[STRIP_BITS:]
    if tuple(top[:4]) != SYNC_TOP or tuple(bottom[:4]) != SYNC_BOTTOM or top[-1] != 1 or bottom[-1] != 1:
        return None
    body = top[4:-1] + bottom[4:-1]
    if _Reader(body[PAYLOAD:]).take(8) != _crc8(body[:PAYLOAD]):
        return None
    r = _Reader(body)
    if r.take(3) != FORMAT:
        return None
    page, pages = r.take(2), r.take(2) + 1
    paper = r.take(1)
    id_digits, name_letters, key = r.take(4), r.take(5), bool(r.take(1))
    count = r.take(2) + 1
    sections = []
    for i in range(MAX_SECTIONS):
        n, kind = r.take(8), _unkind(r.take(5))
        if i < count:
            if kind is None or n < 1:
                return None
            sections.append(Section(n, *kind))
    spec = Spec(tuple(sections), id_digits, name_letters, key, PAPER_CODES[paper])
    return spec, page, pages


def code_cells(paper: Paper) -> list[tuple[float, float]]:
    """Centre of every code cell, in the order encode() gives the bits."""
    xs = [CODE_X0 + (i + 0.5) * CODE_CELL for i in range(STRIP_BITS)]
    return [(x, paper.fid_y[0]) for x in xs] + [(x, paper.fid_y[1]) for x in xs]


# --------------------------------------------------------------- the layout


@dataclass
class Bubble:
    x: float  # centre, inches
    row: int
    label: str
    y: float  # centre, inches


@dataclass
class Question:
    number: int
    x: float  # left edge of the number's space
    row: int
    bubbles: list[Bubble]


@dataclass
class Label:
    """A section's heading, on a row of its own above its first question."""

    text: str
    x: float
    row: int


@dataclass
class Grid:
    """A name or ID grid: one bubble to fill in each column."""

    kind: str  # "name" or "id"
    title: str
    x0: float  # left edge of the first column's write-in box
    x1: float
    alphabet: str
    columns: list[list[Bubble]]  # columns[c][k] is alphabet[k] in column c
    heading_row: int = 0
    box_row: int = 1

    @property
    def last_row(self) -> int:
        return self.columns[0][-1].row


@dataclass
class PageLayout:
    index: int  # from 0
    count: int
    paper: Paper
    questions: list[Question] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    grids: list[Grid] = field(default_factory=list)
    key: Bubble | None = None
    # Room beside the grids for printed instructions: (left, right, first row, last row).
    notes: tuple[float, float, int, int] | None = None


MIXED_GAP = 0.35  # most space between columns when a sheet mixes sections
KEY_TEXT_W = 1.25  # the words beside the answer-key bubble
NOTES_MIN_W = 2.4


def _grid(paper: Paper, kind: str, title: str, x0: float, n: int, alphabet: str, row0: int = 0) -> Grid:
    """A grid whose heading is on row0, write-in boxes on the next row, bubbles below."""
    cols = [
        [Bubble(x0 + 0.11 + c * CHOICE_PITCH, row0 + 2 + k, ch, paper.row_y(row0 + 2 + k))
         for k, ch in enumerate(alphabet)]
        for c in range(n)
    ]
    return Grid(kind, title, x0, x0 + (n - 1) * CHOICE_PITCH + 0.22, alphabet, cols, row0, row0 + 1)


KEY_LABEL_W = 0.78  # "ANSWER KEY" beside its bubble, from the bubble's left edge


def _panel(spec: Spec, paper: Paper, first: "PageLayout") -> float:
    """The name grid down the left, the ID grid under it, the key beside the ID.

    Returns where the question columns may start. Every question column then
    runs the page's full height beside the panel.
    """
    name = _grid(paper, "name", "LAST NAME, FIRST NAME", CONTENT_X0, spec.name_letters, NAME_ALPHABET)
    if name.last_row >= paper.rows:
        raise ValueError("A name grid does not fit on a half page. Use a full page.")
    first.grids.append(name)
    right = name.x1
    below = name.last_row + 2
    if spec.id_digits:
        sid = _grid(paper, "id", "STUDENT ID", CONTENT_X0, spec.id_digits, DIGITS, below)
        if sid.last_row >= paper.rows:
            raise ValueError("The ID grid does not fit under the name grid.")
        first.grids.append(sid)
        right = max(right, sid.x1)
        if spec.key_bubble:
            # Beside the ID's first row of digits: a long ID pushes the questions right.
            x, row = sid.x1 + 0.12, sid.columns[0][0].row
            first.key = Bubble(x + BUBBLE_D / 2, row, "", paper.row_y(row))
    elif spec.key_bubble:
        first.key = Bubble(CONTENT_X0 + BUBBLE_D / 2, below, "", paper.row_y(below))
    if first.key and first.key.row >= paper.rows:
        raise ValueError("The ANSWER KEY bubble does not fit under the grids. Use fewer ID digits.")
    if first.key:
        right = max(right, first.key.x - BUBBLE_D / 2 + KEY_LABEL_W)
    return right + GRID_GAP


def _colw(s: Section) -> float:
    return NUMBER_W + (len(s.choice_labels) - 1) * CHOICE_PITCH + BUBBLE_D


def layout(spec: Spec) -> list[PageLayout]:
    """Every page of the sheet, with every bubble placed. Raises ValueError if it cannot fit.

    Every question column on a page starts on the same row, so the page reads
    as a regular grid. With a name grid, the name and ID grids stand in a
    panel down the left of page 1 and the questions run full height beside
    it. With only an ID, a full page puts it in a band across the top, with
    printed instructions and the ANSWER KEY bubble beside it; a half page
    stands it at the left. With more than one section, each section opens
    with a heading row.
    """
    paper = spec.sheet_paper
    first = PageLayout(0, 0, paper)

    x = CONTENT_X0
    if spec.name_letters:
        q_x0, q_row0 = _panel(spec, paper, first), 0
    elif spec.id_digits:
        first.grids.append(_grid(paper, "id", "STUDENT ID", x, spec.id_digits, DIGITS))
        x = first.grids[-1].x1 + GRID_GAP

    if spec.name_letters:
        pass
    elif paper.id == "half" and first.grids:
        # Grids at the left, the key under the last one, questions beside them.
        if spec.key_bubble:
            g = first.grids[-1]
            row = g.last_row + 2
            if row >= paper.rows:
                raise ValueError("The ANSWER KEY bubble does not fit under the grids.")
            first.key = Bubble(g.x0 + BUBBLE_D / 2, row, "", paper.row_y(row))
            x = max(x, g.x0 + BUBBLE_D + KEY_TEXT_W + GRID_GAP)
        q_x0, q_row0 = x, 0
    elif first.grids:
        # A band across the top: grids, then instructions with the key below them.
        band_last = max(g.last_row for g in first.grids)
        if spec.key_bubble:
            first.key = Bubble(x + BUBBLE_D / 2, band_last, "", paper.row_y(band_last))
        if CONTENT_X1 - x >= NOTES_MIN_W:
            first.notes = (x, CONTENT_X1, 0, band_last - (2 if spec.key_bubble else 0))
        q_x0, q_row0 = CONTENT_X0, band_last + 2
    else:
        if spec.key_bubble:
            first.key = Bubble(CONTENT_X0 + BUBBLE_D / 2, 0, "", paper.row_y(0))
        q_x0, q_row0 = CONTENT_X0, 2 if spec.key_bubble else 0

    # The questions as a stream of blocks; a section's first block carries its heading.
    headed = len(spec.sections) > 1
    blocks: list[tuple[str, Section, list[int]]] = []
    q = 1
    for i, s in enumerate(spec.sections, 1):
        nums = list(range(q, q + s.questions))
        q += s.questions
        for b in range(0, len(nums), BLOCK):
            head = ""
            if headed and b == 0:
                span = f"{nums[0]}–{nums[-1]}" if len(nums) > 1 else str(nums[0])
                head = f"PART {i} · {span}"
            blocks.append((head, s, nums[b : b + BLOCK]))

    # Columns are as wide as the widest section in them. One kind of question
    # gives columns spread evenly across the page, as many as fit; mixed
    # sections pack at least COL_GAP apart and spread only a little, so a
    # narrow true/false column does not leave a hole beside it.
    widest = max(_colw(s) for s in spec.sections)

    def spacing(width: float) -> float:
        if len(spec.sections) > 1:
            return MIXED_GAP
        n = max(1, int((width + COL_GAP + 1e-9) // (widest + COL_GAP)))
        return (width - n * widest) / (n - 1) if n > 1 else COL_GAP

    pages = [first]
    page, x0, row0 = first, q_x0, q_row0
    k = 0
    while k < len(blocks):
        width = CONTENT_X1 - x0
        if widest > width + 1e-9 and page is first and paper.id == "half":
            raise ValueError(
                "That many choices do not fit beside the ID grid on a half page. "
                "Use fewer choices, fewer ID digits, or a full page."
            )
        cols: list[tuple[float, list[tuple[int, int]]]] = []  # (width, [(block, row)])
        used = 0.0
        while k < len(blocks):
            start, r, placed = k, row0, []
            while k < len(blocks):
                head, s, nums = blocks[k]
                need = len(nums) + (1 if head else 0)
                if r + need - 1 >= paper.rows:
                    break
                placed.append((k, r))
                r += need + 1
                k += 1
            if not placed:
                break
            w = max(_colw(blocks[i][1]) for i, _ in placed)
            if used + (COL_GAP if cols else 0) + w > width + 1e-9:
                k = start  # this column goes on the next page
                break
            used += (COL_GAP if cols else 0) + w
            cols.append((w, placed))
        spare = width - sum(w for w, _ in cols)
        gap = min(spacing(width), spare / (len(cols) - 1)) if len(cols) > 1 else 0.0
        x = x0
        for w, placed in cols:
            for i, r in placed:
                head, s, nums = blocks[i]
                if head:
                    page.labels.append(Label(head, x, r))
                    r += 1
                for j, n in enumerate(nums):
                    bubbles = [
                        Bubble(x + NUMBER_W + BUBBLE_D / 2 + c * CHOICE_PITCH, r + j, lab, paper.row_y(r + j))
                        for c, lab in enumerate(s.choice_labels)
                    ]
                    page.questions.append(Question(n, x, r + j, bubbles))
            x += w + gap
        if k < len(blocks):
            if len(pages) > MAX_PAGES or (not cols and page is not first):
                break  # far past any sheet worth printing, or nothing fits a whole page
            page = PageLayout(len(pages), 0, paper)
            pages.append(page)
            x0, row0 = CONTENT_X0, 0
    for p in pages:
        p.count = len(pages)
    return pages
