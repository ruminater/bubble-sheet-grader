# Bubble Sheet Creator

Answer sheets you print yourself and copy on any black-and-white copier, in place of buying
pre-printed forms. One page offers ready-made sheets (A–E, True/False, A–J) and a form for your
own: up to four sections of different kinds of question (say 20 true/false, then 30 A–E),
bubbles typed as `A-E`, `1-5`, `T/F` or `Y/N`, a bubbled name, an optional 9-digit student ID,
and an ANSWER KEY bubble so the key can go in the same pile as the students' sheets.

The **Bubble Sheet Grader** in this repository reads the scanned sheets: names, IDs and every
answer, from pages that are crooked, shrunk, stretched or upside down. No LLM and no network;
nothing is stored.

## How a sheet is read

- **It describes itself.** Strips of black and white cells along the top and bottom edges carry
  the sheet's settings and a checksum, so the grader rebuilds the layout from the paper alone.
  There is no registry of custom sheets to keep.
- **Four solid corner squares** give a perspective fit, which cancels shift, scale, rotation and
  keystone from a copier or scanner.
- **A timing mark on every row, down both edges**, corrects the uneven stretch a roller-fed copier
  puts into a page.
- **Solid black on white only**, so copies of copies still read.

`bubblesheets/layout.py` is the whole format, and the grader carries an identical copy; a test in
each fails if they differ.

## Running it

Python 3.10 or newer.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m bubblesheets                                      # http://127.0.0.1:8773/
```

On Windows: `py -m venv .venv`, then `.venv\Scripts\python -m pip install -r requirements.txt`
and `.venv\Scripts\python -m bubblesheets`.

Copy `bubblesheets.env.example` to `bubblesheets.env` to set the line printed at the foot of every
sheet and the address of your grader. It holds nothing private and serves no student data, so it
can sit on a network as it is (`BUBBLESHEETS_HOST=0.0.0.0`).

## Printing and scanning

- Print at actual size (100%) on white Letter paper, then copy on any black-and-white copier.
- Keep the corner squares, the edge marks and the code strips on the paper.
- Students fill each bubble completely with a No. 2 pencil or a dark pen.
- Scan to PDF at 150 dpi or more and upload to the grader. A test longer than one side continues
  on the back: print double-sided and scan both sides.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python bin/make_test_pack.py "Bubble Sheet Test Pack"   # filled scans and expected results, to try by hand
```

Everything in the samples and the test pack is made up by code. No real student's sheet is in
this repository, and none should ever be committed.
