"""Drawing a sheet as a PDF, from layout.py's positions.

Only solid black on white: no grey fills, no colour, nothing a black-and-white
copier turns into dither. The corner squares, timing dashes and code strips
are the marks the grader reads; everything else is for the student.

A half-page sheet is drawn twice on each Letter page, with a cut line between.
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from . import layout as L
from . import settings
from .layout import PageLayout, Spec

PT = 72  # points per inch
NAME = "Bubble Sheet Creator"


def _xy(x: float, y: float) -> tuple[float, float]:
    """Sheet inches (from top-left, y down) to PDF points (from bottom-left).

    A half sheet in the lower half of the page is drawn with the canvas moved
    down, so every sheet is drawn from its own top-left corner.
    """
    return x * PT, (L.PAGE_H - y) * PT


def _rect(c, x, y, w, h, fill=1, stroke=0):
    """A rectangle given its centre in sheet inches."""
    px, py = _xy(x - w / 2, y + h / 2)
    c.rect(px, py, w * PT, h * PT, fill=fill, stroke=stroke)


def _text(c, x, y, s, size, font="Helvetica", align="left"):
    px, py = _xy(x, y)
    c.setFont(font, size)
    if align == "right":
        c.drawRightString(px, py, s)
    elif align == "centre":
        c.drawCentredString(px, py, s)
    else:
        c.drawString(px, py, s)


def _line(c, x0, y0, x1, y1, width=0.6):
    c.setLineWidth(width)
    c.line(*_xy(x0, y0), *_xy(x1, y1))


def _bubble(c, b: L.Bubble):
    px, py = _xy(b.x, b.y)
    c.setLineWidth(0.7)
    c.circle(px, py, L.BUBBLE_D / 2 * PT, stroke=1, fill=0)
    if b.label:
        c.setFont("Helvetica", 5.6)
        c.drawCentredString(px, py - 2.0, b.label)


def _registration(c, spec: Spec, page: PageLayout):
    paper = page.paper
    for x in L.FID_X:
        for y in paper.fid_y:
            _rect(c, x, y, L.FID, L.FID)
    for r in range(paper.rows):
        for x in L.FID_X:
            _rect(c, x, paper.row_y(r), L.DASH_W, L.DASH_H)
    bits = L.encode(spec, page.index, page.count)
    for bit, (x, y) in zip(bits, L.code_cells(paper)):
        if bit:
            _rect(c, x, y, L.CODE_CELL, L.CODE_H)


def _how_to_fill(c, x, y, size):
    """The fill instruction with a filled bubble to copy; returns where it ends."""
    said = "Use a No. 2 pencil or a dark pen. Fill the bubble completely:"
    _text(c, x, y, said, size)
    x += stringWidth(said, "Helvetica", size) / PT + 0.09
    px, py = _xy(x, y - size / 2 / PT * 0.75)
    c.circle(px, py, 0.05 * PT, stroke=1, fill=1)
    return x + 0.09


def _header(c, spec: Spec, page: PageLayout, title: str, course: str):
    left, right = L.CONTENT_X0, L.CONTENT_X1
    if page.paper.id == "half":
        _text(c, left, 0.9, "Name", 8.5)
        _line(c, left + 0.4, 0.92, left + 3.3, 0.92)
        head = " · ".join(x for x in (title, course) if x) or "Answer Sheet"
        _text(c, right, 0.9, head, 9.5, "Helvetica-Bold", align="right")
        x = _how_to_fill(c, left, 1.07, 6.5)
        _text(c, x, 1.07, "Erase cleanly. Do not mark the black squares, edge marks or code strips.", 6.5)
        return
    if page.index == 0:
        _text(c, left, 0.98, title or "Answer Sheet", 13, "Helvetica-Bold")
        if course:
            _text(c, right, 0.98, course, 10, align="right")
        _text(c, left, 1.3, "Name", 9)
        _line(c, left + 0.42, 1.32, left + 3.6, 1.32)
        _text(c, left + 3.8, 1.3, "Date", 9)
        _line(c, left + 4.15, 1.32, left + 5.3, 1.32)
        _text(c, left + 5.45, 1.3, "Section", 9)
        _line(c, left + 6.0, 1.32, right, 1.32)
        if not page.notes:  # otherwise the instructions box says it
            x = _how_to_fill(c, left, 1.5, 7)
            _text(c, x, 1.5, "Erase cleanly. Do not mark the black squares, edge marks or code strips.", 7)
    else:
        _text(c, left, 0.98, f"{title or 'Answer Sheet'} (continued)", 12, "Helvetica-Bold")
        _text(c, right, 0.98, f"Page {page.index + 1} of {page.count}", 10, align="right")
        _text(c, left, 1.32, "Name", 9)
        _line(c, left + 0.42, 1.34, left + 3.6, 1.34)


def _notes(c, page: PageLayout):
    """The instructions box beside the grids, with right and wrong marks drawn."""
    if not page.notes:
        return
    x0, x1, r0, r1 = page.notes
    paper = page.paper
    top, bottom = paper.row_y(r0) - 0.12, paper.row_y(r1) + 0.1
    c.setLineWidth(0.6)
    px, py = _xy(x0, bottom)
    c.roundRect(px, py, (x1 - x0) * PT, (bottom - top) * PT, 4, stroke=1, fill=0)
    _text(c, (x0 + x1) / 2, paper.row_y(r0) + 0.03, "HOW TO MARK THIS SHEET", 6.5, "Helvetica-Bold", align="centre")
    lines = [
        "Use a No. 2 pencil or a dark pen.",
        "Fill one bubble completely for each answer.",
        "To change an answer, erase it completely.",
        "Write your student ID in the boxes, then",
        "fill the matching bubble under each digit.",
        "Do not mark the black squares, the marks",
        "down the edges, or the code strips.",
    ]
    y = paper.row_y(r0) + 0.27
    for s in lines:
        _text(c, x0 + 0.14, y, s, 7.5)
        y += 0.165
    # Right and wrong, drawn, along the foot of the box.
    y = min(y + 0.12, bottom - 0.2)
    r = L.BUBBLE_D / 2 * PT
    xs = x0 + 0.2
    _text(c, xs, y + 0.03, "Right", 7, "Helvetica-Bold")
    px, py = _xy(xs + 0.5, y)
    c.circle(px, py, r, stroke=1, fill=1)
    xs += 0.85
    _text(c, xs, y + 0.03, "Wrong", 7, "Helvetica-Bold")
    for i in range(4):
        cx = xs + 0.55 + i * 0.3
        px, py = _xy(cx, y)
        c.setLineWidth(0.7)
        c.circle(px, py, r, stroke=1, fill=0)
        d = r * 0.6
        c.setLineWidth(1.1)
        if i == 0:  # a tick
            c.line(px - d, py, px - d / 3, py - d)
            c.line(px - d / 3, py - d, px + d, py + d)
        elif i == 1:  # an X
            c.line(px - d, py - d, px + d, py + d)
            c.line(px - d, py + d, px + d, py - d)
        elif i == 2:  # a dot
            c.circle(px, py, r * 0.3, stroke=0, fill=1)
        else:  # half filled
            p = c.beginPath()
            p.moveTo(px, py - r)
            p.arcTo(px - r, py - r, px + r, py + r, startAng=-90, extent=180)
            p.close()
            c.drawPath(p, stroke=0, fill=1)


def _grid(c, page: PageLayout, g: L.Grid):
    paper = page.paper
    c.setLineWidth(0.6)
    top = paper.row_y(g.heading_row) - 0.12
    bottom = paper.row_y(g.last_row) + 0.13
    px, py = _xy(g.x0 - 0.05, bottom)
    c.roundRect(px, py, (g.x1 - g.x0 + 0.1) * PT, (bottom - top) * PT, 4, stroke=1, fill=0)
    _text(c, (g.x0 + g.x1) / 2, paper.row_y(g.heading_row) + 0.03, g.title, 6.5,
          "Helvetica-Bold", align="centre")
    for col in g.columns:
        x = col[0].x
        px, py = _xy(x - 0.1, paper.row_y(g.box_row) + 0.09)
        c.rect(px, py, 0.2 * PT, 0.18 * PT, stroke=1, fill=0)
        for b in col:
            _bubble(c, b)


def _questions(c, page: PageLayout):
    paper = page.paper
    for lab in page.labels:
        # A narrow column (true/false) has room for the part number only.
        room = (page.questions and max(b.x for q in page.questions if q.x == lab.x for b in q.bubbles)
                + L.BUBBLE_D / 2 - lab.x - 0.04)
        text = lab.text if stringWidth(lab.text, "Helvetica-Bold", 6.5) / PT <= room else lab.text.split(" · ")[0]
        _text(c, lab.x + 0.04, paper.row_y(lab.row) + 0.03, text, 6.5, "Helvetica-Bold")
    for q in page.questions:
        _text(c, q.x + L.NUMBER_W - 0.07, paper.row_y(q.row) + 0.035, str(q.number), 7.5,
              "Helvetica-Bold", align="right")
        for b in q.bubbles:
            _bubble(c, b)


def _key(c, page: PageLayout):
    k = page.key
    if not k:
        return
    _bubble(c, k)
    _text(c, k.x + 0.13, k.y - 0.01, "ANSWER KEY", 6.5, "Helvetica-Bold")
    _text(c, k.x + 0.13, k.y + 0.075, "instructor only", 5.5)


def _footer(c, spec: Spec, page: PageLayout):
    paper = page.paper
    y = paper.row_y(paper.rows - 1) + 0.27
    where = f" · page {page.index + 1} of {page.count}" if page.count > 1 else ""
    _text(c, L.PAGE_W / 2, y, f"{spec.describe()}{where} · {settings.FOOTER}",
          5.5, align="centre")


def _sheet(c, spec: Spec, page: PageLayout, title: str, course: str):
    _registration(c, spec, page)
    _header(c, spec, page, title, course)
    _notes(c, page)
    for g in page.grids:
        _grid(c, page, g)
    _questions(c, page)
    _key(c, page)
    _footer(c, spec, page)


def _cut_line(c):
    y = L.PAGE_H / 2
    c.saveState()
    c.setDash(4, 3)
    _line(c, 0.3, y, 3.6, y, 0.5)
    _line(c, 4.9, y, 8.2, y, 0.5)
    c.restoreState()
    _text(c, L.PAGE_W / 2, y + 0.03, "cut here", 7, align="centre")


def draw_page(c, spec: Spec, page: PageLayout, title: str = "", course: str = ""):
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    if page.paper.per_page == 2:
        _sheet(c, spec, page, title, course)
        c.saveState()
        c.translate(0, -page.paper.height * PT)
        _sheet(c, spec, page, title, course)
        c.restoreState()
        _cut_line(c)
    else:
        _sheet(c, spec, page, title, course)
    c.showPage()


def pdf(spec: Spec, title: str = "", course: str = "", copies: int = 1) -> bytes:
    """The sheet, every page of it, `copies` times over (a half page: copies Letter pages)."""
    problems = spec.problems()
    if problems:
        raise ValueError(" ".join(problems))
    pages = L.layout(spec)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, pageCompression=1)
    c.setTitle(title or "Answer Sheet")
    c.setAuthor(NAME)
    c.setSubject(spec.describe())
    for _ in range(max(1, copies)):
        for p in pages:
            draw_page(c, spec, p, title, course)
    c.save()
    return buf.getvalue()
