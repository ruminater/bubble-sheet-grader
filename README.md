# Bubble Sheet Creator & Grader

Two small local web tools that work together, for when no dedicated answer-sheet reader is to hand:

- **Bubble Sheet Creator** ([`creator/`](creator/)) makes answer sheets you print yourself and
  copy on any black-and-white copier, in place of buying pre-printed forms: ready-made A–E,
  True/False and A–J sheets, or your own with up to four sections of different kinds of question
  (`A-E`, `1-5`, `T/F`, `Y/N`), a bubbled name, a student ID and an ANSWER KEY bubble.
- **Bubble Sheet Grader** (this folder) grades scanned PDFs of those sheets, and of three printed
  forms: Scantron® **form 16485** (General Purpose Answer Sheet), Scantron® **form 882-E**, and the
  Apperson **DataLink 3000** (reorder #20420). Upload the key and the student sheets; get scores,
  an item analysis, a list of marks a person should check, and Excel, PDF and CSV files.

No LLM, no network. Everything happens in memory on the machine running it; nothing is saved
to disk and closing the app forgets every upload.

> **Independent open-source project.** This is not an official Scantron or Apperson product and
> is not affiliated with, endorsed by or sponsored by Scantron Corporation or Apperson. See
> [Trademarks](#trademarks).

The rest of this page is about the grader. The Creator has its own
[README](creator/README.md); it starts with `python -m bubblesheets` from `creator/` and
answers on http://127.0.0.1:8773/.

It needs **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/)). It runs
on macOS, Windows and Linux. The double-click launcher and the background service below are
macOS only; everywhere else, start it with `python -m bubblegrader` as shown.

## Running it

### macOS

Double-click **`Bubble Sheet Grader.command`** in Finder. The first run creates `.venv/` and
installs the packages it needs; after that it starts in seconds and opens
http://127.0.0.1:8765/. If macOS says the file is from an unidentified developer, right-click
it, choose **Open**, then **Open** again. From a terminal the same thing is:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m bubblegrader
```

### Windows

In PowerShell or Command Prompt, from this folder:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # once
.venv\Scripts\python -m bubblegrader
```

Your browser opens http://127.0.0.1:8765/. Leave the window open while you use the grader and
press Ctrl+C in it to stop. Next time, only the last line is needed. If `py` is not found,
install Python from python.org with **Add python.exe to PATH** ticked, or use `python` in its
place.

### Linux

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/python -m bubblegrader
```

To move it to another computer, copy this folder without `.venv/` and set it up again there.

## Sharing it with colleagues (macOS)

One Mac that stays on can run the grader for everyone, who then open it in their own browser.

1. **Set it up.** Put this folder on that Mac, copy `grader.env.example` to `grader.env`,
   and set `GRADER_PASSWORD` to something of 10+ characters. The grader refuses to go on the
   network without one.
2. **Start it as a service.** Run `./service/install.sh` from this folder. It starts the grader
   now and at every login, restarts it if it stops, and prints the address to share, such as
   `http://<this computer's address>:8765/`. `./service/uninstall.sh` undoes it; the log is
   `~/Library/Logs/bubble-sheet-grader.log`. The first time, macOS asks whether Python may accept
   incoming connections: allow it.
3. **Keep the Mac awake and signed in.** In System Settings, turn on *Prevent automatic
   sleeping* (Energy) and *Automatically log in* (Users & Groups), so it comes back after a
   power cut.

On Windows or Linux, the same settings in `grader.env` (`GRADER_HOST=0.0.0.0` and a
password) put it on the network when started with `python -m bubblegrader`; keeping it running is
up to you.

What colleagues get: one shared password; results visible only in the browser that uploaded
them; results kept in memory for 4 hours, then forgotten, and never written to disk; pages
marked not to be cached. They should download the Excel or PDF to keep anything.

**Before real student data goes through it**, decide how people reach it. Plain `http://`
on a shared network means the password and every page of names and scores cross the
network unencrypted. Options, best first:

- **Cloudflare Tunnel with Cloudflare Access**, at an address on a domain you control.
  It gives https, works on and off site, opens no ports on the host, and Access can
  restrict sign-in to named email addresses before anyone sees the password page. Set
  `GRADER_HTTPS=1`. The tunnel runs as `cloudflared` on the host; the Access policy is a
  dashboard step.
- **Tailscale** on the host and on each colleague's machine: encrypted, but everyone installs it.
- **Local network only, over http**: works today, with the exposure above. Only if your IT
  department agrees.

Check your institution's rules on where student records may be held, whichever route you
choose.

## What you get

Give the test a name and course on the upload page; they head every output and name the files
(`BIOL 1406-010 Exam 2 class report 2026-09-30.pdf`). Rosters are alphabetical, since the name
grid is LAST FIRST, with unnamed sheets last.

| Download | What's in it |
|---|---|
| **Excel workbook** | *Summary* (figures, score distribution and chart, notes, files graded) · *Scores* (sortable roster, percent bars) · *Responses* (every answer, green right, red wrong, amber to check, frozen headers) · *Item Analysis* (choice counts, % correct colour scale, discrimination, plain-English notes) · *To Check*. Each sheet is set to print one page wide. |
| **Class report (PDF)** | Summary figures, distribution chart, notes and key; the roster; marks to check; item analysis. |
| **Student pages (PDF)** | One page per student to hand back: score, percent, class mean, and each answer beside the key. |
| **CSV** | One row per student, key row first, for a gradebook import. |

All four are built in `exports.py` from the same grading, so they always agree with the page.

## Scanning

- Scan to PDF at 150 dpi or better, grayscale. The copier's default document scan is fine.
  Pages may be crooked, upside down or sideways.
- Scan **every side that has answers or a name**. Side 1 then side 2 per sheet, which is what a
  duplex scan produces, and the grader puts each sheet's pages back together. On a 16485, side 2
  holds questions 121-240 and the name; single-sided scans work, and students then appear as
  "Sheet N (no name)" in upload order.
- **The key** goes in its own PDF, or anywhere in the student PDF: a Creator sheet, 882-E or
  Apperson sheet with its KEY bubble filled, a 16485 with **KEY** bubbled in the name grid, or
  else the first sheet. Blank sheets are skipped.

## How it reads a sheet

**Creator sheets** describe themselves. Strips of black and white cells along the top and bottom
edges carry the sheet's settings and a checksum, so the grader rebuilds the exact layout from the
paper alone, with no registry of custom sheets. Four solid corner squares give a perspective fit
(shift, scale, rotation and keystone), and a timing mark on every row, down both edges, corrects
the uneven stretch of a roller-fed copier. `bubblegrader/omr_layout.py` is the format and must
stay identical to `creator/bubblesheets/layout.py`; a test in each fails if they differ. Names,
the 9-digit student ID and every section's answers are read.

**Scantron 882-E and Apperson DataLink 3000** (`forms.py`) print one timing dash per bubble row
down one long edge. The grader finds every dash of each form's size, at any quarter turn and
anywhere on the glass, and the pattern of gaps in the dash track says which form and which side
it is. 882-E: the KEY bubble, 100 questions over two sides, and the instructor's subjective score
(shown and in the CSV, not added to the score); it has no bubbled name, so students are listed by
sheet number and the picture of the scan shows the handwritten name. Apperson: the Key bubble,
150 questions, the 9-digit student ID and the test version; a student whose version differs from
the key's is graded against it with a note.

**Form 16485:** every bubble sits on a 1/6-inch lattice tied to the black timing marks down one
edge (left on side 1, right on side 2). `sheet.py` finds those marks, fits a line through them,
and so knows the scan's position, scale and skew; each bubble is then addressed as (columns from
the marks, mark number). The layout constants are in `reader.py`'s docstring.

A bubble's score is how much darker it is than the page's own empty bubbles of the same column,
so pencil weight and scanner exposure don't matter. Per question the darkest bubble is the
answer, and:

- **blank** when nothing clears the fill threshold;
- **multiple** when a second bubble is at least 60% as dark. No credit, as on a machine;
- **light** when the answer is faint or an X. Scored as read, listed for a person to confirm.

A half-erased bubble next to a firm one is read as the firm one. Each sheet has a view that
draws what was read over the scan, so any doubt can be settled by eye.

## Not built yet

- The ID number and birth date grids on 16485's side 2 are not read.
- One key per run. There are no alternate versions (form A/B) and no multiple correct answers.
- Other vendors' forms each need a layout in `forms.py`, measured from a blank and a filled scan.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests          # macOS, Linux
.venv\Scripts\python -m unittest discover -s tests      # Windows
```

Every sample is made-up data. `samples/sample-key-and-students.pdf` (16485) is a blank sheet, a
key, and two students, one with deliberate double, blank, X'd and half-erased marks.
`samples/scantron-882e.pdf` and `samples/apperson-20420.pdf` are real scans of those forms filled
in with made-up answers. `samples/bubblesheet-*.pdf` are Creator sheets filled in and put through a
copier's faults by code (`creator/bin/make_sample.py`). **Real student scans must never be
committed.** Keep them outside this folder, or in `private/`, which is gitignored.

To see the output without installing anything, `samples/sample-class-report.pdf` and
`samples/sample-student-pages.pdf` are what the grader produces from that sample.

## Trademarks

Scantron® is a registered trademark of Scantron Corporation, and Apperson and DataLink are
trademarks of Apperson. The names are used here only to identify the answer sheets this
software reads (forms 16485 and 882-E, and the DataLink 3000 #20420). This project is
independent: it is not made, supported, endorsed or sponsored by Scantron Corporation or
Apperson, and includes none of their software or documentation. The sample scans show those
printed forms, filled in with made-up answers, only so the tests have real pages to read. Grading results come from this software
alone; check anything that matters by eye.

## License

MIT, for the grader and the Creator alike. See [LICENSE](LICENSE). The license covers this project's code only and grants no rights
in any third-party trademark.
