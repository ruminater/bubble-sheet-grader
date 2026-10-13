"""The layout, the code strips, the PDFs and the web page.

Whether the grader reads these sheets is tested in scantron/tests/test_bubblesheets.py,
against scans made by bin/make_sample.py.
"""

import filecmp
import pathlib
import unittest

import pymupdf

from bubblesheets import layout as L
from bubblesheets.app import app
from bubblesheets.render import pdf
from bubblesheets.standard import STANDARD

# The grader's copy of layout.py: beside this project, or at the top of the repository
# when this project is its creator/ folder.
_UP = pathlib.Path(__file__).parent.parent.parent
GRADER_COPY = next((p for p in (_UP / "scantron" / "scantron" / "omr_layout.py", _UP / "bubblegrader" / "omr_layout.py")
                    if p.exists()), _UP / "scantron" / "scantron" / "omr_layout.py")
MIXED = L.Spec((L.Section(20, 2, "truefalse"), L.Section(30), L.Section(10, 10)), id_digits=9, name_letters=13)


class CodeTest(unittest.TestCase):
    def test_round_trip(self):
        for spec in [s.spec for s in STANDARD] + [MIXED]:
            pages = L.layout(spec)
            for p in pages:
                self.assertEqual(L.decode(L.encode(spec, p.index, len(pages))), (spec, p.index, len(pages)))

    def test_any_one_wrong_cell_is_refused(self):
        bits = L.encode(MIXED, 0, 1)
        for i in range(L.CODE_BITS):
            bad = list(bits)
            bad[i] ^= 1
            self.assertIsNone(L.decode(bad), f"cell {i}")

    def test_blank_strip_is_refused(self):
        self.assertIsNone(L.decode([0] * L.CODE_BITS))
        self.assertIsNone(L.decode([1] * L.CODE_BITS))


class BubblesTest(unittest.TestCase):
    """What faculty type for a section's bubbles."""

    def test_what_people_type(self):
        cases = {"A-E": (5, "letters"), "a-d": (4, "letters"), "A B C": (3, "letters"), "ABCDEFGHIJ": (10, "letters"),
                 "1-5": (5, "numbers"), "1,2,3,4": (4, "numbers"), "T/F": (2, "truefalse"), "true false": (2, "truefalse"),
                 "tf": (2, "truefalse"), "Y/N": (2, "yesno"), "Yes/No": (2, "yesno"), "A–D": (4, "letters")}
        for text, want in cases.items():
            self.assertEqual(L.parse_bubbles(text), want, text)

    def test_what_cannot_print_says_so(self):
        for text in ("B-E", "A-K", "1-10", "X", "", "maybe"):
            with self.assertRaises(ValueError, msg=text):
                L.parse_bubbles(text)

    def test_typed_form_round_trips(self):
        for text in ("A-E", "A-J", "1-5", "T/F", "Y/N"):
            choices, labels = L.parse_bubbles(text)
            self.assertEqual(L.Section(10, choices, labels).typed, text)

    def test_yes_no_in_the_code(self):
        spec = L.Spec((L.Section(10, 2, "yesno"), L.Section(10)), id_digits=9, name_letters=13)
        self.assertEqual(L.decode(L.encode(spec, 0, 1)), (spec, 0, 1))
        self.assertEqual(spec.choice_labels, "YNABCDE")


class LayoutTest(unittest.TestCase):
    def test_standard_sheets_fill_their_page(self):
        for s in STANDARD:
            self.assertEqual(s.spec.problems(), [], s.id)
            self.assertEqual(L.capacity(s.spec), s.spec.questions, s.id)
            self.assertEqual(len(L.layout(s.spec)), 1, s.id)

    def test_capacities(self):
        got = {s.id: s.spec.questions for s in STANDARD}
        self.assertEqual(got, {"ae": 70, "tf": 105, "aj": 35})

    def test_every_standard_sheet_has_a_name(self):
        for s in STANDARD:
            self.assertEqual(s.spec.name_letters, 13, s.id)
            self.assertEqual(s.spec.paper, "full", s.id)

    def test_name_panel(self):
        """Name over ID down the left, key beside the ID, questions full height beside them."""
        page = L.layout(STANDARD[0].spec)[0]
        name, sid = page.grids
        self.assertEqual((name.heading_row, sid.heading_row), (0, name.last_row + 2))
        self.assertEqual(page.key.row, sid.columns[0][0].row)
        self.assertGreater(min(q.x for q in page.questions), max(name.x1, sid.x1))
        self.assertEqual(min(q.row for q in page.questions), 0)

    def test_columns_are_regular(self):
        """Every column starts on the same row and, on a full one-kind page, holds the same count."""
        for s in STANDARD:
            qs = L.layout(s.spec)[0].questions
            by_col: dict[float, list[L.Question]] = {}
            for q in qs:
                by_col.setdefault(round(q.x, 3), []).append(q)
            self.assertEqual(len({min(q.row for q in c) for c in by_col.values()}), 1, s.id)
            self.assertEqual(len({len(c) for c in by_col.values()}), 1, s.id)
            xs = sorted(by_col)
            steps = {round(b - a, 2) for a, b in zip(xs, xs[1:])}
            self.assertLessEqual(len(steps), 1, s.id)

    def test_every_question_once(self):
        for spec in [s.spec for s in STANDARD] + [MIXED]:
            nums = [q.number for p in L.layout(spec) for q in p.questions]
            self.assertEqual(nums, list(range(1, spec.questions + 1)))

    def test_sections_keep_their_bubbles(self):
        pages = L.layout(MIXED)
        page = pages[0]
        labels = {q.number: "".join(b.label for b in q.bubbles) for p in pages for q in p.questions}
        self.assertEqual((labels[1], labels[21], labels[51]), ("TF", "ABCDE", "ABCDEFGHIJ"))
        self.assertEqual([lab.text for lab in page.labels][:2], ["PART 1 · 1–20", "PART 2 · 21–50"])
        self.assertEqual(MIXED.choice_labels, "TFABCDEGHIJ")  # F once: true/false and letters share it

    def test_nothing_overlaps(self):
        for spec in [s.spec for s in STANDARD] + [MIXED]:
            for p in L.layout(spec):
                spots = [(round(b.x, 3), b.row) for q in p.questions for b in q.bubbles]
                spots += [(round(b.x, 3), b.row) for g in p.grids for col in g.columns for b in col]
                spots += [(round(lab.x, 3), lab.row) for lab in p.labels]
                if p.key:
                    spots.append((round(p.key.x, 3), p.key.row))
                self.assertEqual(len(spots), len(set(spots)))
                rows = [r for _, r in spots]
                self.assertTrue(min(rows) >= 0 and max(rows) < p.paper.rows)
                xs = [x for x, _ in spots]
                self.assertTrue(L.CONTENT_X0 <= min(xs) and max(xs) < L.CONTENT_X1)

    def test_problems_in_words(self):
        self.assertIn("exactly two", L.Spec.simple(50, 4, "truefalse").problems()[0])
        self.assertIn("A half page holds 30", L.Spec.simple(40, id_digits=9, paper="half").problems()[0])
        self.assertIn("name grid does not fit on a half page",
                      L.Spec.simple(10, name_letters=10, paper="half").problems()[0])
        self.assertIn("needs 5 pages", L.Spec.simple(250, 10, id_digits=12, name_letters=20).problems()[0])


class PdfTest(unittest.TestCase):
    def test_pages_and_copies(self):
        spec = L.Spec.simple(200, id_digits=9)
        self.assertEqual(len(pymupdf.open(stream=pdf(spec, "T"), filetype="pdf")), 2)
        self.assertEqual(len(pymupdf.open(stream=pdf(spec, "T", copies=3), filetype="pdf")), 6)

    def test_half_page_prints_two_to_a_page(self):
        doc = pymupdf.open(stream=pdf(L.Spec.simple(30, id_digits=9, paper="half"), "Quiz"), filetype="pdf")
        self.assertEqual(len(doc), 1)
        self.assertEqual(doc[0].get_text().count("STUDENT ID"), 2)
        self.assertIn("cut here", doc[0].get_text())

    def test_refuses_what_does_not_fit(self):
        with self.assertRaises(ValueError):
            pdf(L.Spec.simple(250, 10, id_digits=12, name_letters=20))


class GraderCopyTest(unittest.TestCase):
    @unittest.skipUnless(GRADER_COPY.exists(), "the grader is not beside this project")
    def test_grader_has_this_layout(self):
        self.assertTrue(
            filecmp.cmp(L.__file__, GRADER_COPY, shallow=False),
            f"Copy bubblesheets/layout.py over {GRADER_COPY.name}, or the grader misreads new sheets.",
        )


class PageTest(unittest.TestCase):
    def setUp(self):
        self.c = app.test_client()

    def test_index_lists_every_standard_sheet(self):
        page = self.c.get("/").get_data(as_text=True)
        self.assertIn("Bubble Sheet Creator", page)
        for s in STANDARD:
            self.assertIn(f"/standard/{s.id}.pdf", page)

    def test_downloads(self):
        r = self.c.get("/standard/ae.pdf")
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        r = self.c.get("/sheet.pdf?s1=30&k1=A-D&title=Quiz%203&id=1&key=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="Quiz 3 - 30 questions, A-D, 9-digit ID, 13-letter name.pdf"',
                      r.headers["Content-Disposition"])
        self.assertEqual(self.c.get("/standard/nope.pdf").status_code, 404)

    def test_sections_from_the_form(self):
        d = self.c.get("/info?s1=20&k1=truefalse:2&s2=30&k2=letters:5&s3=&k3=letters:5&id_digits=9&key=1").get_json()
        self.assertEqual(d["problems"], [])
        self.assertEqual(d["describe"], "50 questions in 2 sections (20 True/False, 30 A–E) · 9-digit ID · 13-letter name")

    def test_always_a_name(self):
        """No name grid, and no half page, can be asked for: the grader needs names."""
        for q in ("name_letters=0", "paper=half", ""):
            d = self.c.get(f"/info?s1=30&{q}").get_json()
            self.assertRegex(d["describe"], r"\d+-letter name")
            self.assertNotIn("half page", d["describe"])

    def test_typed_bubbles(self):
        d = self.c.get("/info?s1=10&k1=t/f&s2=10&k2=1-4&s3=5&k3=y/n").get_json()
        self.assertEqual(d["problems"], [])
        self.assertIn("(10 True/False, 10 1–4, 5 Yes/No)", d["describe"])
        d = self.c.get("/info?s1=10&k1=A-E&s2=10&k2=B-F").get_json()
        self.assertTrue(d["problems"][0].startswith('Section 2: "B-F" is not a set of bubbles'))
        self.assertEqual(self.c.get("/sheet.pdf?s1=10&k1=B-F").status_code, 400)
        page = self.c.get("/?s1=10&k1=1-4").get_data(as_text=True)
        self.assertIn('value="1-4"', page)

    def test_student_id_box(self):
        """Nine digits or none; ticked on a fresh page, and on old links with id_digits."""
        describe = lambda q: self.c.get(f"/info?{q}").get_json()["describe"]
        self.assertIn("9-digit ID", describe(""))
        self.assertIn("9-digit ID", describe("s1=30&id=1"))
        self.assertNotIn("ID", describe("s1=30&id=0"))
        self.assertNotIn("ID", describe("s1=30"))  # the form sent without the box ticked
        self.assertIn("9-digit ID", describe("s1=30&id_digits=8"))
        self.assertNotIn("ID", describe("s1=30&id_digits=0"))

    def test_key_box_unticked(self):
        text = pymupdf.open(stream=self.c.get("/sheet.pdf?s1=10&key=0").data, filetype="pdf")[0].get_text()
        self.assertNotIn("ANSWER KEY", text)
        text = pymupdf.open(stream=self.c.get("/sheet.pdf").data, filetype="pdf")[0].get_text()
        self.assertIn("ANSWER KEY", text)

    def test_what_does_not_fit_says_why(self):
        q = "s1=250&k1=letters:10&id_digits=12&name_letters=20"
        d = self.c.get(f"/info?{q}").get_json()
        self.assertEqual(d["pages"], 0)
        self.assertTrue(d["problems"])
        self.assertEqual(self.c.get(f"/sheet.pdf?{q}").status_code, 400)

    def test_previews(self):
        r = self.c.get("/preview/2.png?s1=200")
        self.assertEqual(r.mimetype, "image/png")
        self.assertEqual(self.c.get("/preview/3.png?s1=200").status_code, 404)


if __name__ == "__main__":
    unittest.main()
