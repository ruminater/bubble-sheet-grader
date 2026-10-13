"""A test pack for trying the Creator's sheets in the grader by hand.

    .venv/bin/python bin/make_test_pack.py ~/Desktop/"Bubble Sheet Test Pack"

Writes:

- Filled-in scans to upload to the Scantron Grader, one test per PDF (or a
  key PDF and a students PDF), made the way bin/make_sample.py makes the
  grader's own samples: filled by code, then put through a copier's faults.
- EXPECTED RESULTS.html: for each test, what the grader should report, worked
  out here from what was written on each sheet, not by asking the grader.
- Blank sheets to print, fill in by hand and scan: the real paper test.

Everything is made up. Nothing here is a real student.
"""

from __future__ import annotations

import html
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import make_sample as M  # noqa: E402

from bubblesheets import layout as L  # noqa: E402
from bubblesheets import settings  # noqa: E402
from bubblesheets.render import pdf  # noqa: E402
from bubblesheets.standard import STANDARD  # noqa: E402

NAME, ID = 13, 9


def _key(spec: L.Spec, seed: int) -> dict[int, str]:
    rng = np.random.default_rng(seed)
    return {q: (lab := spec.section_of(q).choice_labels)[rng.integers(len(lab))]
            for q in range(1, spec.questions + 1)}


def _wrong(spec: L.Spec, q: int, a: str) -> str:
    lab = spec.section_of(q).choice_labels
    return lab[(lab.index(a) + 1) % len(lab)]


def _student(spec, key, seed, name, sid, miss, marks=None):
    """A student who misses `miss` questions at random, plus any special marks."""
    rng = np.random.default_rng(seed)
    answers = dict(key)
    for q in rng.choice(sorted(key), size=miss, replace=False):
        answers[int(q)] = _wrong(spec, int(q), key[int(q)])
    return {"answers": answers, "marks": marks or {}, "name": name, "id": sid}


def _expect(key, st):
    """Score, and the marks a person should check, from what was written."""
    score, flags = 0, []
    for q, k in key.items():
        marks = st["marks"].get(q)
        if marks is None:
            score += st["answers"].get(q) == k
            continue
        firm = [lab for lab, how in marks if how == "firm"]
        faint = [lab for lab, how in marks if how in ("x", "light")]
        if len(firm) > 1:
            flags.append(f"Q{q} multiple (no credit)")
        elif firm:
            score += firm[0] == k
        elif faint:
            score += faint[0] == k
            flags.append(f"Q{q} light ({faint[0]})")
    return score, flags


def _scans(spec, title, sheets, seed, distort):
    """Filled pages of every sheet, scanned. distort: one tuple per page, cycled."""
    rng = np.random.default_rng(seed)
    lay = L.layout(spec)
    pages, n = [], 0
    for st in sheets:
        for pl, img in zip(lay, M._blank_pages(spec, title)):
            if st is not None:
                M._write(img, pl, st)
            pages.append(M._scan(img, rng, *distort[n % len(distort)]))
            n += 1
    return M._to_pdf(pages)


CROOKED = [(0, 1.2, 0.985, (9, -14), 0.004), (0, -2.4, 1.01, (-20, 12), 0.008),
           (2, 1.7, 0.97, (14, 22), 0.006), (0, -0.6, 0.99, (4, 6), 0.003),
           (0, 2.8, 1.0, (-8, -6), 0.007), (2, -1.1, 0.98, (6, 10), 0.005)]
DUPLEX = [(0, -0.8, 0.99, (5, 5), 0.003), (2, 1.1, 0.99, (-8, 3), 0.005),
          (0, 2.0, 1.0, (0, -10), 0.007), (2, -1.5, 0.98, (12, 0), 0.004)]

TRICKS = "two bubbles on one question, an X, a faint mark, and a changed answer half erased"


def tests():
    """(file stem, what it tests, spec, key, key in its own file?, students, distortions)."""
    out = []

    ae = next(s for s in STANDARD if s.id == "ae").spec
    k = _key(ae, 1)
    tricky = {2: [("A", "firm"), ("C", "firm")], 6: [(k[6], "x")], 9: [(k[9], "light")],
              7: [(_wrong(ae, 7, k[7]), "erased"), (k[7], "firm")], 4: []}
    out.append(("1 Standard A-E", "The standard A–E sheet (70). The key is in the pile, second, with ANSWER KEY "
                "bubbled. One page is upside down; one sheet is blank and should be skipped. "
                f"OKAFOR BEN has {TRICKS}, and leaves Q4 blank.",
                ae, k, False, [
                    _student(ae, k, 11, "NGUYEN AN", "100000001", 4),
                    {"answers": k, "marks": {}, "name": "", "id": "", "key": True},
                    _student(ae, k, 12, "OKAFOR BEN", "100000002", 3, tricky),
                    _student(ae, k, 13, "LOPEZ MARIA", "100000003", 12),
                    None,
                    _student(ae, k, 14, "SMITH JO", "100000004", 0),
                ], CROOKED))

    tf = next(s for s in STANDARD if s.id == "tf").spec
    k = _key(tf, 2)
    out.append(("2 Standard True-False", "The standard True/False sheet (105). Key first, with ANSWER KEY bubbled.",
                tf, k, False, [
                    {"answers": k, "marks": {}, "name": "", "id": "", "key": True},
                    _student(tf, k, 21, "BROWN ALEX", "200000001", 5),
                    _student(tf, k, 22, "DAVIS SAM", "200000002", 20),
                    _student(tf, k, 23, "WILSON KIM", "200000003", 1),
                ], CROOKED))

    aj = next(s for s in STANDARD if s.id == "aj").spec
    k = _key(aj, 3)
    out.append(("3 Standard A-J", "The standard A–J sheet (35). The key is a PDF of its own: upload "
                "'3 Standard A-J KEY.pdf' as the answer key and the other as the students.",
                aj, k, True, [
                    _student(aj, k, 31, "TAYLOR CHRIS", "300000001", 2),
                    _student(aj, k, 32, "MOORE PAT", "300000002", 9),
                ], CROOKED))

    mixed = L.Spec((L.Section(20, 2, "truefalse"), L.Section(30, 5, "letters"),
                    L.Section(10, 2, "yesno"), L.Section(10, 4, "numbers")), id_digits=ID, name_letters=NAME)
    k = _key(mixed, 4)
    out.append(("4 Sections TF AE YN 1-4", "A custom sheet in four sections: 20 True/False, 30 A–E, 10 Yes/No, "
                "10 numbered 1–4, all on one side. Key last, with ANSWER KEY bubbled.",
                mixed, k, False, [
                    _student(mixed, k, 41, "GARCIA ELENA", "400000001", 6),
                    _student(mixed, k, 42, "LEE JUN", "400000002", 0),
                    _student(mixed, k, 43, "KHAN SARA", "400000003", 15),
                    {"answers": k, "marks": {}, "name": "", "id": "", "key": True},
                ], CROOKED))

    long = L.Spec.simple(100, id_digits=ID, name_letters=NAME)
    k = _key(long, 5)
    out.append(("5 Two-sided 100 A-E", "A custom 100-question A–E sheet: 70 on the front, 30 on the back, "
                "scanned duplex (front, back, front, back; every back upside down, as a duplex scan often "
                "comes out). Key first, with ANSWER KEY bubbled.",
                long, k, False, [
                    {"answers": k, "marks": {}, "name": "", "id": "", "key": True},
                    _student(long, k, 51, "ADAMS RUTH", "500000001", 7),
                    _student(long, k, 52, "CLARK OMAR", "500000002", 25),
                ], DUPLEX))
    return out


def page(results) -> str:
    rows = []
    for stem, what, files, key_note, students in results:
        trs = "".join(
            f"<tr><td>{html.escape(n)}</td><td>{sid}</td><td class=n>{sc} / {pos}</td>"
            f"<td class=n>{100 * sc / pos:.1f}%</td><td>{html.escape('; '.join(fl)) or ''}</td></tr>"
            for n, sid, sc, pos, fl in students)
        rows.append(
            f"<section><h2>{html.escape(stem)}</h2><p>{html.escape(what)}</p>"
            f"<p class=files>Upload: {' + '.join(html.escape(f) for f in files)}</p>"
            f"<p>The notes should say the key was taken from <b>{html.escape(key_note)}</b>.</p>"
            f"<table><tr><th>Name</th><th>Student ID</th><th>Score</th><th>Percent</th><th>To check</th></tr>"
            f"{trs}</table></section>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Bubble Sheet Test Pack: expected results</title>
<style>body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#1d2330}}
h1{{font-size:22px}} h2{{font-size:17px;margin:28px 0 4px;color:#4f2d7f}} table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #dfe3ea}} th{{color:#5d6675}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.files{{font-family:ui-monospace,Menlo,monospace;font-size:13px;background:#f6f7f9;padding:6px 10px;border-radius:6px}}
ol li{{margin-bottom:6px}}</style></head><body>
<h1>Bubble Sheet Test Pack: expected results</h1>
<ol>
<li>Open the grader at <a href="{settings.GRADER_URL}">{settings.GRADER_URL}</a>.</li>
<li>For each test below, upload the files named, grade, and compare the roster with the table:
names, IDs and scores should match exactly. "To check" lists the marks the grader should flag for a
person to confirm.</li>
<li>Open a student's sheet in the grader to see the rings drawn over the scan.</li>
<li>Then the paper test: print a blank from the <b>Blank sheets to print</b> folder, copy it on the
office copier, fill in a key and a few students by hand, scan to PDF, and grade.</li>
</ol>
<p>The scans are made by code and put through a copier's faults (tilted a few degrees, shrunk or
stretched a little, shifted, uneven stretch down the page, grey paper and specks, some pages upside
down). All names and IDs are made up.</p>
{''.join(rows)}
</body></html>"""


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "Bubble Sheet Test Pack").expanduser()
    blanks = out / "Blank sheets to print"
    blanks.mkdir(parents=True, exist_ok=True)
    results = []
    for n, (stem, what, spec, key, separate, sheets, distort) in enumerate(tests()):
        title = stem.split(" ", 1)[1]
        key_sheet = {"answers": key, "marks": {}, "name": "", "id": "", "key": True}
        if separate:
            (out / f"{stem} KEY.pdf").write_bytes(_scans(spec, title, [key_sheet], 100 + n, distort))
            files = [f"{stem} KEY.pdf (answer key)", f"{stem} STUDENTS.pdf (student sheets)"]
            (out / f"{stem} STUDENTS.pdf").write_bytes(_scans(spec, title, sheets, 200 + n, distort))
            key_note = "the key file"
        else:
            (out / f"{stem}.pdf").write_bytes(_scans(spec, title, sheets, 200 + n, distort))
            files = [f"{stem}.pdf (student sheets; leave the key box empty)"]
            key_note = "the sheet with ANSWER KEY bubbled"
        students = []
        for st in sheets:
            if st is None or st.get("key"):
                continue
            sc, fl = _expect(key, st)
            students.append((st["name"], st["id"], sc, len(key), fl))
        students.sort(key=lambda s: s[0])
        results.append((stem, what, files, key_note, students))
        (blanks / f"{stem} blank.pdf").write_bytes(pdf(spec, title))
        print(f"  {stem}: {len(students)} students")
    (out / "EXPECTED RESULTS.html").write_text(page(results))
    print(f"Wrote the test pack to {out}")


if __name__ == "__main__":
    main()
