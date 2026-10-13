"""Scantron 882-E and Apperson DataLink 3000 (#20420): real scans, 2026-10-13.

samples/scantron-882e.pdf, scanned portrait on Letter: a blank side 1, the
key (KEY bubbled, 1-20 ABCDE four times), Student A, Student B, and one
blank side 2. Student A double-marks 7 (A and B), X's out 9 and slashes
18-20; 100 and 20 are bubbled in the subjective score. Student B has only
pencil lines drawn through the bubbles, and 80 and 5 bubbled.

samples/apperson-20420.pdf, scanned sideways on Legal: a blank sheet, the
key (Key and Test Version A bubbled, 1-10 ABCDE twice), a student with ID
012, and a second blank.
"""

import pathlib
import unittest

import pymupdf

from bubblegrader import forms
from bubblegrader.app import app
from bubblegrader.grade import grade
from bubblegrader.reader import read_pdf
from bubblegrader.sheet import render

SAMPLES = pathlib.Path(__file__).parent.parent / "samples"
F882 = SAMPLES / "scantron-882e.pdf"
APPERSON = SAMPLES / "apperson-20420.pdf"


def answers(sheet, n):
    a = sheet.answers
    return "".join(a[q].choice or "-" for q in range(1, n + 1))


class Scantron882ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets, cls.problems = read_pdf(F882.read_bytes(), "882")

    def test_four_sheets_and_the_back_joins_the_last(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(len(self.sheets), 4)
        self.assertTrue(all(s.form == "Scantron form 882-E" for s in self.sheets))
        self.assertEqual(sorted(self.sheets[3].pages), [1, 2])

    def test_blank(self):
        self.assertTrue(self.sheets[0].is_blank)

    def test_key(self):
        self.assertEqual([s.key_marked for s in self.sheets], [False, True, False, False])
        self.assertEqual(answers(self.sheets[1], 22), "ABCDE" * 4 + "--")
        self.assertFalse([q for q, a in self.sheets[1].answers.items() if a.flag])

    def test_student_a(self):
        a = self.sheets[2]
        self.assertEqual(answers(a, 20), "CBDDEABC-EABC-E-B---")
        self.assertEqual(a.answers[7].flag, "multiple")

    def test_pencil_lines_are_not_answers(self):
        b = self.sheets[3].answers
        read = {q: a.choice for q, a in b.items() if a.choice}
        self.assertTrue(all(b[q].flag == "light" for q in read), read)

    def test_subjective_score(self):
        self.assertEqual([s.points for s in self.sheets], [None, None, 120, 85])

    def test_grade(self):
        g = grade(self.sheets[1], self.sheets[2:], [])
        self.assertEqual(g.results[0].score, 11)
        self.assertTrue(g.has_points)

    def test_upside_down(self):
        doc = pymupdf.open(F882)
        doc[1].set_rotation((doc[1].rotation + 180) % 360)
        f = forms.find(render(doc[1]))
        self.assertEqual((f.form.id, f.side.side), ("882-E", 1))


class AppersonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheets, cls.problems = read_pdf(APPERSON.read_bytes(), "apperson")

    def test_sheets(self):
        self.assertEqual(self.problems, [])
        self.assertEqual(len(self.sheets), 4)
        self.assertEqual([s.is_blank for s in self.sheets], [True, False, False, True])

    def test_key(self):
        k = self.sheets[1]
        self.assertTrue(k.key_marked)
        self.assertEqual(k.version, "A")
        self.assertEqual(answers(k, 12), "ABCDE" * 2 + "--")

    def test_student(self):
        s = self.sheets[2]
        self.assertFalse(s.key_marked)
        self.assertEqual((s.student_id, s.version), ("012", "A"))
        self.assertEqual(answers(s, 13)[:4] + answers(s, 13)[7:], "ACCE" + "CD-ABC")
        self.assertEqual(s.answers[7].flag, "multiple")

    def test_blank_has_no_version(self):
        self.assertEqual(self.sheets[3].version, "")


class NotTheseFormsTest(unittest.TestCase):
    def test_16485_and_creator_pages_are_left_alone(self):
        for name in ("sample-key-and-students.pdf", "bubblesheet-exam-70.pdf"):
            doc = pymupdf.open(SAMPLES / name)
            for page in list(doc)[:2]:
                self.assertIsNone(forms.find(render(page)), name)


class UploadTest(unittest.TestCase):
    """The key is found by its KEY bubble, and the CSV carries the subjective score."""

    def test_882e(self):
        c = app.test_client()
        r = c.post("/grade", data={"students": (open(F882, "rb"), "882.pdf")},
                   content_type="multipart/form-data")
        page = c.get(r.location).get_data(as_text=True)
        self.assertIn("the sheet with its KEY bubble filled", page)
        self.assertIn("Subjective", page)
        rows = c.get(f"{r.location}/download/csv").data.decode("utf-8-sig").splitlines()
        self.assertIn("Subjective points", rows[0])
        self.assertIn(",120,", rows[2] + rows[3])

    def test_apperson(self):
        c = app.test_client()
        r = c.post("/grade", data={"students": (open(APPERSON, "rb"), "app.pdf")},
                   content_type="multipart/form-data")
        rows = c.get(f"{r.location}/download/csv").data.decode("utf-8-sig").splitlines()
        self.assertTrue(rows[0].startswith("Name,Student ID"))
        self.assertTrue(rows[2].startswith(",012,"), rows[2])


if __name__ == "__main__":
    unittest.main()
