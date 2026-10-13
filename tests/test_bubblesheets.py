"""Sheets from the Bubble Sheet Creator (bubblesheets/ in this repository).

The two sample scans are made by bubblesheets/bin/make_sample.py: filled in
by code and put through a copier's faults (rotation, scale, shift, uneven
stretch, grey paper, noise, a page upside down). The answers below are the
ones that script writes.
"""

import filecmp
import io
import pathlib
import unittest

import numpy as np
import pymupdf
from PIL import Image

from bubblegrader import omr_layout as OL
from bubblegrader.app import app
from bubblegrader.grade import grade
from bubblegrader.reader import read_pdf

HERE = pathlib.Path(__file__).parent
SAMPLES = HERE.parent / "samples"
EXAM = SAMPLES / "bubblesheet-exam-70.pdf"
MIXED = SAMPLES / "bubblesheet-mixed-2page.pdf"
QUIZ = SAMPLES / "bubblesheet-quiz-half.pdf"
# The Creator's layout.py: beside this project, or in creator/ when both share one repository.
MAKER_LAYOUT = next(
    (p for p in (HERE.parent.parent / "bubblesheets" / "bubblesheets" / "layout.py",
                 HERE.parent / "creator" / "bubblesheets" / "layout.py") if p.exists()),
    HERE.parent.parent / "bubblesheets" / "bubblesheets" / "layout.py",
)

EXAM_KEY = {q: "ABCDE"[(q * 7 + q // 3) % 5] for q in range(1, 71)}
MIXED_KEY = {q: "TF"[(q * 5 + q // 3) % 2] if q <= 40 else "ABCD"[(q * 3 + q // 4) % 4] for q in range(1, 121)}
QUIZ_KEY = {q: "ABCDE"[(q * 2 + q // 5) % 5] for q in range(1, 31)}


class LayoutCopyTest(unittest.TestCase):
    @unittest.skipUnless(MAKER_LAYOUT.exists(), "the Bubble Sheet Creator is not beside this project")
    def test_layout_is_the_makers(self):
        mine = pathlib.Path(OL.__file__)
        self.assertTrue(
            filecmp.cmp(mine, MAKER_LAYOUT, shallow=False),
            f"{mine.name} differs from {MAKER_LAYOUT}; copy the maker's over it.",
        )


class ExamTest(unittest.TestCase):
    """The standard A-E sheet (70 questions, name and ID): key, two students, a blank."""

    @classmethod
    def setUpClass(cls):
        cls.sheets, cls.problems = read_pdf(EXAM.read_bytes(), "exam")

    def test_every_page_registers(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(len(self.sheets), 4)
        self.assertTrue(all(p.reg.dashes_found == 2 * p.reg.paper.rows for s in self.sheets for p in s.ordered))

    def test_key(self):
        key = self.sheets[0]
        self.assertTrue(key.key_marked)
        self.assertEqual({q: a.choice for q, a in key.answers.items()}, EXAM_KEY)
        self.assertFalse(any(s.key_marked for s in self.sheets[1:]))

    def test_names_and_ids(self):
        self.assertEqual([s.student_id for s in self.sheets], ["", "123456789", "987654321", ""])
        self.assertEqual([s.name for s in self.sheets], ["", "NGUYEN AN", "OKAFOR BEN", ""])

    def test_upside_down_page(self):
        self.assertEqual(self.sheets[2].side1.turns, 2)

    def test_marks(self):
        b = self.sheets[2].answers
        self.assertEqual((b[2].choice, b[2].flag), ("C", "multiple"))
        self.assertEqual(b[4].choice, "")
        self.assertEqual((b[6].choice, b[6].flag), (EXAM_KEY[6], "light"))  # an X
        self.assertEqual((b[7].choice, b[7].flag), (EXAM_KEY[7], ""))  # half-erased beside it
        self.assertEqual((b[9].choice, b[9].flag), (EXAM_KEY[9], "light"))

    def test_blank_sheet(self):
        self.assertTrue(self.sheets[3].is_blank)

    def test_scores(self):
        g = grade(self.sheets[0], self.sheets[1:3], [])
        self.assertEqual([r.score for r in g.results], [66, 68])
        self.assertEqual([r.label for r in g.results], ["NGUYEN AN", "OKAFOR BEN"])
        self.assertEqual(g.choices, "ABCDE")
        self.assertEqual(g.skipped, [])


class TwoPageTest(unittest.TestCase):
    """120 questions in two sections (40 true/false, 80 A-D), a name grid and an ID:
    two pages per sheet, scanned duplex."""

    @classmethod
    def setUpClass(cls):
        cls.sheets, cls.problems = read_pdf(MIXED.read_bytes(), "mixed")

    def test_pages_pair_into_sheets(self):
        self.assertEqual(self.problems, [])
        self.assertEqual([sorted(s.pages) for s in self.sheets], [[1, 2]] * 3)

    def test_names_and_ids(self):
        self.assertEqual([s.name for s in self.sheets], ["", "GARCIA MARIA", "SMITH JO"])
        self.assertEqual(self.sheets[1].student_id, "555000111")

    def test_sections(self):
        self.assertEqual({q: a.choice for q, a in self.sheets[0].answers.items()}, MIXED_KEY)
        g = grade(self.sheets[0], self.sheets[1:], [])
        self.assertEqual([r.score for r in g.results], [116, 120])
        self.assertEqual(g.choices, "TFABCD")

    def test_missing_page_is_reported(self):
        sheet = self.sheets[1]
        page2 = sheet.pages.pop(2)
        try:
            g = grade(self.sheets[0], [sheet], [])
            self.assertEqual(len(g.skipped), 1)
            self.assertIn("page 2 was not in the upload", g.skipped[0])
        finally:
            sheet.pages[2] = page2


class HalfPageTest(unittest.TestCase):
    """Half pages: an uncut Letter page (two sheets), then cut halves scanned at
    half-letter upside down, sideways, and laid on Letter-size glass."""

    @classmethod
    def setUpClass(cls):
        cls.sheets, cls.problems = read_pdf(QUIZ.read_bytes(), "quiz")

    def test_uncut_page_is_two_sheets(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(len(self.sheets), 5)
        self.assertEqual([s.first.index for s in self.sheets], [0, 0, 1, 2, 3])
        self.assertTrue(self.sheets[0].key_marked)

    def test_every_way_round(self):
        self.assertEqual([s.student_id for s in self.sheets[1:]],
                         ["111111111", "222222222", "333333333", "444444444"])
        self.assertEqual([s.first.turns for s in self.sheets], [0, 0, 2, 3, 0])

    def test_scores(self):
        g = grade(self.sheets[0], self.sheets[1:], [])
        self.assertEqual({q: a for q, a in g.key_answers.items()}, QUIZ_KEY)
        self.assertEqual([r.score for r in g.results], [29, 28, 30, 29])

    def test_each_half_shown_alone(self):
        from PIL import Image
        from bubblegrader.overlay import render_page
        img = Image.open(io.BytesIO(render_page(self.sheets[1].first, QUIZ_KEY)))
        self.assertLess(img.height, img.width)  # a half, not the whole Letter page


class WorseScanTest(unittest.TestCase):
    """The key page turned four more degrees and shrunk to 93%, as a careless copy would."""

    def test_reads_the_same(self):
        doc = pymupdf.open(EXAM)
        pix = doc[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        w, h = img.size
        small = img.resize((int(w * 0.93), int(h * 0.93)), Image.BILINEAR)
        canvas = Image.new("L", (w, h), 235)
        canvas.paste(small, (int(w * 0.04), int(h * 0.03)))
        worse = canvas.rotate(4, resample=Image.BILINEAR, fillcolor=235)
        buf = io.BytesIO()
        worse.save(buf, "PNG")
        out = pymupdf.open()
        page = out.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=buf.getvalue())
        sheets, problems = read_pdf(out.tobytes(), "worse")
        self.assertEqual(problems, [])
        self.assertEqual({q: a.choice for q, a in sheets[0].answers.items()}, EXAM_KEY)

    def test_not_a_sheet(self):
        out = pymupdf.open()
        out.new_page(width=612, height=792).insert_text((72, 72), "A letter, not a bubble sheet.")
        sheets, problems = read_pdf(out.tobytes(), "letter")
        self.assertEqual(sheets, [])
        self.assertIn("neither a form 16485 page nor a Bubble Sheet Creator sheet", problems[0])


class UploadTest(unittest.TestCase):
    """Through the web page: the ANSWER KEY bubble picks the key, and the CSV carries IDs."""

    @classmethod
    def setUpClass(cls):
        c = app.test_client()
        r = c.post(
            "/grade",
            data={"students": (open(EXAM, "rb"), "exam.pdf"), "title": "Exam", "course": "TEST 101"},
            content_type="multipart/form-data",
        )
        cls.client, cls.base = c, r.location

    def test_key_from_bubble(self):
        page = self.client.get(self.base).get_data(as_text=True)
        self.assertIn("the sheet with ANSWER KEY bubbled", page)
        self.assertIn("OKAFOR BEN", page)

    def test_csv(self):
        rows = self.client.get(f"{self.base}/download/csv").data.decode("utf-8-sig").splitlines()
        self.assertTrue(rows[0].startswith("Name,Student ID,Sheet,Score"))
        self.assertTrue(rows[2].startswith("NGUYEN AN,123456789,1,66,70,94.3"))

    def test_sheet_view_and_downloads(self):
        self.assertEqual(self.client.get(f"{self.base}/sheet/2").status_code, 200)
        self.assertEqual(self.client.get(f"{self.base}/sheet/2/side1.png").status_code, 200)
        for kind in ("xlsx", "report.pdf", "students.pdf"):
            self.assertEqual(self.client.get(f"{self.base}/download/{kind}").status_code, 200, kind)


if __name__ == "__main__":
    unittest.main()
