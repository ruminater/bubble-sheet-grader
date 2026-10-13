"""Made-up filled-in scans of Bubble Sheet Creator sheets, for the grader's tests.

    .venv/bin/python bin/make_sample.py ../scantron/samples

Each sheet is drawn by render.py, filled in the way students fill them (firm
pencil, a light X, two bubbles, a half-erased change of mind), then put
through what a copier and scanner do to a page: a few degrees of rotation,
a percent or two of scale, a shift, uneven stretch down the page, grey paper,
noise and speckle, pages fed upside down or sideways, and half pages scanned
cut, uncut, and on Letter settings. The result is a PDF of JPEG pages, like a
copier's scan-to-PDF.

Everything is seeded, so the files come out the same each time. The answers
written are listed in the grader's tests (scantron/tests/test_bubblesheets.py).
"""

from __future__ import annotations

import io
import pathlib
import random
import sys

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from bubblesheets import layout as L  # noqa: E402
from bubblesheets import settings  # noqa: E402

# Samples are shared: whatever this installation prints at the foot of its
# sheets, the samples carry the plain default.
settings.FOOTER = "Bubble Sheet Creator"
from bubblesheets.render import pdf  # noqa: E402

DPI = 200  # drawn and distorted at this
SCAN_DPI = 150  # saved at this, as a copier's default scan
R = L.BUBBLE_D / 2 * DPI


def _blank_pages(spec: L.Spec, title: str) -> list[Image.Image]:
    doc = pymupdf.open(stream=pdf(spec, title, "TEST 101"), filetype="pdf")
    out = []
    for pg in doc:
        pix = pg.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY)
        out.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    return out


def _fill(draw, b: L.Bubble, how: str, rng: random.Random, oy: float):
    x, y = b.x * DPI, (b.y + oy) * DPI
    if how == "firm":  # pencil: dark, a little short of the outline here and there
        r = R * rng.uniform(0.82, 0.95)
        draw.ellipse((x - r, y - r * 0.95, x + r, y + r * 0.95), fill=rng.randint(45, 80))
    elif how == "light":  # faint, but filled
        r = R * 0.85
        draw.ellipse((x - r, y - r, x + r, y + r), fill=150)
    elif how == "x":
        d = R * 0.9
        draw.line((x - d, y - d, x + d, y + d), fill=60, width=4)
        draw.line((x - d, y + d, x + d, y - d), fill=60, width=4)
    elif how == "erased":  # rubbed out, a grey smudge left
        r = R * 0.85
        draw.ellipse((x - r, y - r, x + r, y + r), fill=215)


def _write(img, pl: L.PageLayout, sheet: dict, oy: float = 0.0):
    """Fill one sheet's page in. sheet: answers, marks, id, name, key."""
    rng = random.Random(repr(sorted(sheet.get("answers", {}).items())) + sheet.get("id", ""))
    draw = ImageDraw.Draw(img)
    answers, marks = sheet.get("answers", {}), sheet.get("marks", {})
    for q in pl.questions:
        by_label = {b.label: b for b in q.bubbles}
        for label, how in marks.get(q.number, [(answers.get(q.number), "firm")]):
            if label:
                _fill(draw, by_label[label], how, rng, oy)
    for g in pl.grids:
        text = sheet.get("id", "") if g.kind == "id" else sheet.get("name", "")
        for col, ch in zip(g.columns, text):
            if ch != " ":
                _fill(draw, col[g.alphabet.index(ch)], "firm", rng, oy)
    if pl.key and sheet.get("key"):
        _fill(draw, pl.key, "firm", rng, oy)


def _scan(img: Image.Image, rng: np.random.Generator, turn: int, angle: float, scale: float,
          shift: tuple[float, float], stretch: float) -> Image.Image:
    """What a copier does to a page, then grey paper and noise. turn: quarter turns."""
    a = np.asarray(img, np.float32)
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # Inverse map: output pixel -> source pixel. Rotation and scale about the
    # centre, a shift, and a vertical stretch growing down the page.
    cx, cy = w / 2, h / 2
    t = np.deg2rad(angle)
    dx, dy = (xx - cx - shift[0]) / scale, (yy - cy - shift[1]) / scale
    sx = np.cos(t) * dx + np.sin(t) * dy + cx
    sy = -np.sin(t) * dx + np.cos(t) * dy + cy
    sy = sy - stretch * (sy / h) ** 2 * h
    xi, yi = np.rint(sx).astype(int), np.rint(sy).astype(int)
    inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    out = np.full_like(a, 255.0)
    out[inside] = a[yi[inside], xi[inside]]
    out = 22 + out * (232 - 22) / 255  # toner is not quite black, paper not quite white
    out += rng.normal(0, 6, out.shape)
    specks = rng.random(out.shape) < 0.0004
    out[specks] = rng.uniform(40, 120, specks.sum())
    page = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    page = page.resize((w * SCAN_DPI // DPI, h * SCAN_DPI // DPI), Image.BILINEAR)
    return page.rotate(90 * turn, expand=True) if turn else page


def _to_pdf(pages: list[Image.Image]) -> bytes:
    doc = pymupdf.open()
    for im in pages:
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=60, dpi=(SCAN_DPI, SCAN_DPI))
        w, h = im.size[0] * 72 / SCAN_DPI, im.size[1] * 72 / SCAN_DPI
        pg = doc.new_page(width=w, height=h)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    return doc.tobytes(deflate=True)


def _wrong(label: str, labels: str) -> str:
    return labels[(labels.index(label) + 1) % len(labels)]


# The answers the grader's tests expect. Keep scantron/tests/test_bubblesheets.py in step.
EXAM = L.Spec.simple(70, id_digits=9, name_letters=13)
EXAM_KEY = {q: "ABCDE"[(q * 7 + q // 3) % 5] for q in range(1, 71)}
MIXED = L.Spec((L.Section(40, 2, "truefalse"), L.Section(80, 4)), id_digits=9, name_letters=13)
MIXED_KEY = {q: "TF"[(q * 5 + q // 3) % 2] if q <= 40 else "ABCD"[(q * 3 + q // 4) % 4] for q in range(1, 121)}
QUIZ = L.Spec.simple(30, id_digits=9, paper="half")
QUIZ_KEY = {q: "ABCDE"[(q * 2 + q // 5) % 5] for q in range(1, 31)}


def exam() -> bytes:
    """Key and two students on the 70-question standard A-E sheet, and a blank sheet."""
    nprng = np.random.default_rng(7)
    a = dict(EXAM_KEY)
    for q in (3, 10, 50, 66):  # student A misses four
        a[q] = _wrong(a[q], "ABCDE")
    b_marks = {
        2: [("A", "firm"), ("C", "firm")],  # two bubbles: multiple, no credit
        4: [],  # left blank
        6: [(EXAM_KEY[6], "x")],  # an X: read, flagged light
        7: [(_wrong(EXAM_KEY[7], "ABCDE"), "erased"), (EXAM_KEY[7], "firm")],  # changed mind
        9: [(EXAM_KEY[9], "light")],
    }
    plan = [
        ({"answers": EXAM_KEY, "key": True}, (0, 1.2, 0.985, (9, -14), 0.004)),
        ({"answers": a, "id": "123456789", "name": "NGUYEN AN"}, (0, -2.4, 1.01, (-20, 12), 0.008)),
        ({"answers": EXAM_KEY, "marks": b_marks, "id": "987654321", "name": "OKAFOR BEN"},
         (2, 1.7, 0.97, (14, 22), 0.006)),
        ({}, (0, 0.5, 1.0, (0, 0), 0.0)),  # a blank sheet in the pile
    ]
    pl = L.layout(EXAM)[0]
    pages = []
    for sheet, d in plan:
        img = _blank_pages(EXAM, "Sample Exam")[0]
        _write(img, pl, sheet)
        pages.append(_scan(img, nprng, *d))
    return _to_pdf(pages)


def mixed() -> bytes:
    """Two pages, a true/false section and an A-D section, a name grid: scanned duplex."""
    nprng = np.random.default_rng(11)
    c = dict(MIXED_KEY)
    for q in (1, 2, 119, 120):
        c[q] = _wrong(c[q], "TF" if q <= 40 else "ABCD")
    plan = [
        ({"answers": MIXED_KEY, "key": True}, [(0, -0.8, 0.99, (5, 5), 0.003), (2, 1.1, 0.99, (-8, 3), 0.005)]),
        ({"answers": c, "name": "GARCIA MARIA", "id": "555000111"},
         [(0, 2.0, 1.0, (0, -10), 0.007), (2, -1.5, 0.98, (12, 0), 0.004)]),
        ({"answers": MIXED_KEY, "name": "SMITH JO"}, [(0, -1.0, 1.015, (-6, 8), 0.005), (0, 0.7, 1.0, (3, 3), 0.002)]),
    ]
    lay = L.layout(MIXED)
    pages = []
    for sheet, distort in plan:
        for pl, img, d in zip(lay, _blank_pages(MIXED, "Sample Final"), distort):
            _write(img, pl, sheet)
            pages.append(_scan(img, nprng, *d))
    return _to_pdf(pages)


def quiz() -> bytes:
    """Half pages: one uncut (key on top, a student below) and three cut halves scanned three ways."""
    nprng = np.random.default_rng(13)
    pl = L.layout(QUIZ)[0]
    half = int(L.PAGE_H / 2 * DPI)

    def letter_page(top: dict, bottom: dict) -> Image.Image:
        img = _blank_pages(QUIZ, "Quiz 4")[0]
        _write(img, pl, top)
        _write(img, pl, bottom, oy=L.PAGE_H / 2)
        return img

    def cut(sheet: dict) -> Image.Image:
        img = letter_page(sheet, {})
        return img.crop((0, 0, img.width, half))

    s1 = dict(QUIZ_KEY); s1[5] = _wrong(s1[5], "ABCDE")
    s2 = dict(QUIZ_KEY); s2[30] = _wrong(s2[30], "ABCDE"); s2[29] = _wrong(s2[29], "ABCDE")
    s3 = dict(QUIZ_KEY)
    s4 = dict(QUIZ_KEY); del s4[1]
    pages = [
        # Uncut: the key on top, student 111111111 below.
        _scan(letter_page({"answers": QUIZ_KEY, "key": True}, {"answers": s1, "id": "111111111"}),
              nprng, 0, 0.9, 0.99, (6, -4), 0.004),
        # Cut, half-letter, fed upside down.
        _scan(cut({"answers": s2, "id": "222222222"}), nprng, 2, -1.8, 1.0, (8, 6), 0.003),
        # Cut, half-letter, fed sideways.
        _scan(cut({"answers": s3, "id": "333333333"}), nprng, 1, 1.3, 0.99, (-5, 4), 0.003),
    ]
    # Cut, laid on the glass and scanned on Letter settings: the half and white below.
    sheet = cut({"answers": s4, "id": "444444444"})
    glass = Image.new("L", (sheet.width, int(L.PAGE_H * DPI)), 255)
    glass.paste(sheet, (0, int(0.4 * DPI)))
    pages.append(_scan(glass, nprng, 0, -2.2, 1.0, (10, 0), 0.0))
    return _to_pdf(pages)


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("bubblesheet-*.pdf"):
        old.unlink()
    (out / "bubblesheet-exam-70.pdf").write_bytes(exam())
    (out / "bubblesheet-mixed-2page.pdf").write_bytes(mixed())
    (out / "bubblesheet-quiz-half.pdf").write_bytes(quiz())
    print(f"Wrote three sample scans to {out}")


if __name__ == "__main__":
    main()
