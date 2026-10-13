"""The web page: upload a key and student sheets, see the results.

Everything stays in this process's memory. Nothing is written to disk, and a
run is forgotten after RUN_HOURS or when the app stops.

Run on one machine for its own user, it needs no login. Shared on a network,
it takes one password for everyone (SCANTRON_PASSWORD), and each run is
visible only to the browser session that uploaded it: colleagues share the
tool, not each other's students.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque

from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

from . import exports
from .grade import Grading, grade
from .overlay import render_page
from .reader import Sheet, read_pdf

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=500 * 1024 * 1024,
    SECRET_KEY=secrets.token_hex(32),  # new each start, which signs everyone out
    SESSION_COOKIE_SAMESITE="Lax",
    PASSWORD="",  # empty: no login, for use on one machine
)

RUN_HOURS = 4
MAX_RUNS = 40  # across all users; the oldest go first
MAX_RUNS_EACH = 5

RUNS: OrderedDict[str, tuple[str, float, Grading]] = OrderedDict()  # run -> (owner, created, grading)
_lock = threading.Lock()

LOGIN_TRIES, LOGIN_WINDOW = 8, 300  # per address, per five minutes
_tries: dict[str, deque] = defaultdict(deque)


def configure(password: str = "", https: bool = False) -> None:
    app.config["PASSWORD"] = password
    app.config["SESSION_COOKIE_SECURE"] = https


def _client() -> str:
    # Behind Cloudflare Tunnel every request arrives from localhost, so trust
    # its header for the real address; nobody else can set it on loopback.
    if request.remote_addr in ("127.0.0.1", "::1"):
        return request.headers.get("CF-Connecting-IP") or request.remote_addr
    return request.remote_addr or "?"


def _user() -> str:
    if "uid" not in session:
        session["uid"] = secrets.token_hex(16)
    return session["uid"]


@app.before_request
def _gate():
    if not app.config["PASSWORD"] or request.endpoint in ("login", "static"):
        return None
    if not session.get("ok"):
        return redirect(url_for("login", next=request.path))
    return None


@app.after_request
def _headers(resp):
    # Pages carry student names and scores: never cache them anywhere.
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.route("/login", methods=["GET", "POST"])
def login():
    if not app.config["PASSWORD"]:
        return redirect(url_for("index"))
    error = None
    nxt = request.values.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    if request.method == "POST":
        tries, now = _tries[_client()], time.time()
        while tries and tries[0] < now - LOGIN_WINDOW:
            tries.popleft()
        if len(tries) >= LOGIN_TRIES:
            error = "Too many attempts. Wait a few minutes and try again."
        elif hmac.compare_digest(
            request.form.get("password", "").encode(), app.config["PASSWORD"].encode()
        ):
            session.clear()
            session["ok"] = True
            session.permanent = False
            return redirect(nxt)
        else:
            tries.append(now)
            error = "That password is not right."
    return render_template_string(PAGE, body="login", error=error, nxt=nxt, locked=True)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login") if app.config["PASSWORD"] else url_for("index"))


def _prune(now: float) -> None:
    for run in [r for r, (_, t, _) in RUNS.items() if now - t > RUN_HOURS * 3600]:
        del RUNS[run]


def _pick_key(sheets: list[Sheet]) -> tuple[Sheet | None, list[Sheet], str]:
    named = [s for s in sheets if s.name.replace(" ", "").upper() == "KEY"]
    if named:
        key = named[0]
        return key, [s for s in sheets if s is not key], "the sheet named KEY"
    if sheets:
        return sheets[0], sheets[1:], "the first sheet in the upload"
    return None, [], ""


@app.get("/")
def index():
    return render_template_string(PAGE, body="upload", error=request.args.get("error"))


@app.post("/grade")
def do_grade():
    key_files = [f for f in request.files.getlist("key") if f.filename]
    student_files = [f for f in request.files.getlist("students") if f.filename]
    if not student_files and not key_files:
        return redirect(url_for("index", error="Choose at least one PDF."))

    problems: list[str] = []

    def read_all(files):
        out = []
        for f in files:
            try:
                sheets, probs = read_pdf(f.read(), f.filename)
            except Exception:  # not a PDF, or a damaged one
                problems.append(f"{f.filename}: could not be opened as a PDF, skipped.")
                continue
            out.extend(sheets)
            problems.extend(probs)
        return out

    key_sheets = [s for s in read_all(key_files) if not s.is_blank]
    all_students = read_all(student_files)
    blanks = [s for s in all_students if s.is_blank]
    students = [s for s in all_students if not s.is_blank]
    for s in blanks:
        problems.append(f"{s.source}, sheet {s.number}: blank sheet, skipped.")

    if key_sheets:
        key, key_note = key_sheets[0], "the key file"
        if len(key_sheets) > 1:
            problems.append("The key file had more than one sheet; used the first.")
    else:
        key, students, key_note = _pick_key(students)
    if key is None:
        return redirect(url_for("index", error="No answered sheets found in the upload."))

    for n, s in enumerate(students, 1):  # number students in upload order
        s.number = n
    g = grade(key, students, problems)
    g.key_warnings.insert(0, f"Key taken from {key_note}.")
    g.title = request.form.get("title", "").strip()[:120]
    g.course = request.form.get("course", "").strip()[:120]
    g.sources = [f.filename for f in key_files + student_files]
    if not g.key_answers:
        return redirect(url_for("index", error="The key sheet has no answers marked."))

    run, user, now = secrets.token_urlsafe(12), _user(), time.time()
    with _lock:
        _prune(now)
        mine = [r for r, (owner, _, _) in RUNS.items() if owner == user]
        for old in mine[: max(0, len(mine) - MAX_RUNS_EACH + 1)]:
            del RUNS[old]
        RUNS[run] = (user, now, g)
        while len(RUNS) > MAX_RUNS:
            RUNS.popitem(last=False)
    return redirect(url_for("results", run=run))


def _get(run: str) -> Grading:
    with _lock:
        _prune(time.time())
        entry = RUNS.get(run)
    # Someone else's run is reported exactly like one that does not exist.
    if entry is None or entry[0] != session.get("uid"):
        abort(404)
    return entry[2]


@app.errorhandler(404)
def _missing(_):
    msg = (
        f"Those results are gone. Results are kept for {RUN_HOURS} hours, only in the "
        "browser that uploaded them, and are cleared when the grader restarts. "
        "Download the Excel or PDF files to keep them."
    )
    return render_template_string(PAGE, body="upload", error=msg), 404


@app.errorhandler(413)
def _too_big(_):
    return render_template_string(PAGE, body="upload", error="That upload is over 500 MB. Split it into smaller PDFs."), 413


@app.get("/r/<run>")
def results(run):
    g = _get(run)
    order = request.args.get("sort", "sheet")
    rows = list(g.results)
    if order == "name":
        rows.sort(key=lambda r: r.label.lower())
    elif order == "score":
        rows.sort(key=lambda r: -r.score)
    flagged = [(r, q, f) for r in g.results for q, f in sorted(r.flags.items())]
    return render_template_string(
        PAGE,
        body="results",
        g=g,
        run=run,
        rows=rows,
        order=order,
        stats=g.stats(),
        flagged=flagged,
        choices=list("ABCDE"),
    )


@app.get("/r/<run>/sheet/<int:n>")
def sheet_view(run, n):
    g = _get(run)
    if n == 0:
        result, sheet = None, g.key
    else:
        result = next((r for r in g.results if r.sheet.number == n), None)
        if result is None:
            abort(404)
        sheet = result.sheet
    return render_template_string(PAGE, body="sheet", g=g, run=run, n=n, sheet=sheet, r=result)


@app.get("/r/<run>/sheet/<int:n>/side<int:side>.png")
def sheet_png(run, n, side):
    g = _get(run)
    sheet = g.key if n == 0 else next((r.sheet for r in g.results if r.sheet.number == n), None)
    page = sheet and (sheet.side1 if side == 1 else sheet.side2)
    if not page:
        abort(404)
    return Response(render_page(page, None if n == 0 else g.key_answers), mimetype="image/png")


DOWNLOADS = {
    "csv": ("text/csv; charset=utf-8", "csv", "", exports.to_csv),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx", "", exports.to_xlsx),
    "report.pdf": ("application/pdf", "pdf", " class report", exports.to_pdf_report),
    "students.pdf": ("application/pdf", "pdf", " student pages", exports.to_pdf_students),
}


@app.get("/r/<run>/download/<kind>")
def download(run, kind):
    g = _get(run)
    if kind not in DOWNLOADS:
        abort(404)
    mime, ext, suffix, build = DOWNLOADS[kind]
    name = exports.filename(g, ext, suffix)
    return Response(
        build(g),
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scantron Grader</title>
<style>
:root { --ink:#1d2330; --muted:#5d6675; --line:#dfe3ea; --bg:#f6f7f9; --card:#fff;
        --accent:#4f2d7f; --good:#167a3e; --bad:#b3261e; --warn:#a15c00; --warnbg:#fff4e0; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color:var(--ink); background:var(--bg); }
header { background:var(--accent); color:#fff; padding:14px 24px; }
header { display:flex; justify-content:space-between; align-items:center; }
header .signout button { background:transparent; border:1px solid rgba(255,255,255,.6); padding:5px 12px; font-size:13px; }
header a { color:#fff; text-decoration:none; font-weight:600; font-size:18px; }
main { max-width:1100px; margin:24px auto; padding:0 16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-bottom:20px; }
h1 { font-size:22px; margin:0 0 12px; } h2 { font-size:17px; margin:0 0 12px; }
.muted { color:var(--muted); }
label.drop { display:block; border:2px dashed var(--line); border-radius:10px; padding:18px; margin:10px 0 18px; }
label.drop strong { display:block; margin-bottom:6px; }
button, .btn { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:10px 18px;
               font-size:15px; cursor:pointer; text-decoration:none; display:inline-block; }
.btn.secondary { background:#fff; color:var(--accent); border:1px solid var(--accent); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.stats { display:flex; flex-wrap:wrap; gap:12px; }
.stat { flex:1 1 120px; background:var(--bg); border-radius:8px; padding:10px 14px; }
.stat b { display:block; font-size:22px; }
.warn { background:var(--warnbg); color:var(--warn); border-radius:8px; padding:10px 14px; margin-bottom:12px; }
.warn ul { margin:4px 0 0; padding-left:20px; }
.error { background:#fdecea; color:var(--bad); border-radius:8px; padding:10px 14px; margin-bottom:12px; }
.ok { color:var(--good); font-weight:600; } .no { color:var(--bad); font-weight:600; }
.flag { color:var(--warn); font-weight:600; }
.keycell { font-weight:700; }
.resp { font-family:ui-monospace, Menlo, monospace; letter-spacing:1px; }
.sheetimgs { display:flex; flex-wrap:wrap; gap:16px; }
.sheetimgs img { max-width:100%; width:520px; border:1px solid var(--line); border-radius:6px; }
.legend span { margin-right:14px; }
.fields { display:flex; gap:16px; flex-wrap:wrap; margin-top:8px; }
.fields label { flex:1 1 240px; }
.fields input { width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; font-size:15px; margin-top:4px; }
/* The downloads are what a person came for, and they were losing to the page:
   the same card shell, the same heading weight and the same hairline border as
   Key, Students and Item analysis, so four large targets read as more furniture.
   The card is now the one accented block on the page, and each file is a raised
   tile with a mark on it rather than a bordered rectangle. */
.getit { border:2px solid var(--accent); background:#faf7fd; }
.getit h2 { color:var(--accent); margin-bottom:2px; }
.getit .lede { margin:0 0 14px; font-size:14px; color:var(--muted); }
.downloads { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(235px,1fr)); }
.dl { display:flex; gap:12px; align-items:flex-start; background:var(--card);
      border:1px solid var(--line); border-radius:10px; padding:14px 16px;
      text-decoration:none; color:var(--ink); box-shadow:0 1px 2px rgba(29,35,48,.06);
      transition:transform .12s ease, box-shadow .12s ease, border-color .12s ease; }
.dl:hover, .dl:focus-visible { border-color:var(--accent); transform:translateY(-2px);
      box-shadow:0 6px 18px rgba(79,45,127,.20); outline:none; }
.dl .mark { flex:0 0 auto; width:30px; height:30px; border-radius:50%; background:var(--accent);
      color:#fff; display:grid; place-items:center; font-size:15px; font-weight:700; line-height:1; }
.dl b { display:block; color:var(--accent); font-size:15px; }
.dl span.what { display:block; }
.dl span.note { display:block; font-size:13px; color:var(--muted); margin-top:2px; }
.actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:4px; }
.scroll { overflow-x:auto; }
footer { max-width:1100px; margin:0 auto 24px; padding:0 16px; font-size:12px; color:var(--muted); }
@media print { header, footer, .actions, .noprint { display:none; } body { background:#fff; } .card { border:0; padding:0; } }
</style></head>
<body><header><a href="/">Scantron Grader</a>
{% if config.PASSWORD and not locked %}<form method="post" action="/logout" class="signout"><button>Sign out</button></form>{% endif %}
</header><main>
{% include body %}
</main>
<footer>Independent open-source software (MIT License). Not affiliated with, endorsed by or
sponsored by Scantron Corporation. Scantron is a registered trademark of Scantron Corporation,
used here only to name the answer sheet this tool reads.</footer>
</body></html>"""

LOGIN = """
<div class="card" style="max-width:420px;margin:60px auto">
<h1>Sign in</h1>
<p class="muted">Ask the person who runs this grader for the password.</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post" action="/login">
  <input type="hidden" name="next" value="{{ nxt }}">
  <div class="fields"><label><strong>Password</strong><br>
    <input type="password" name="password" autofocus autocomplete="current-password"></label></div>
  <p><button type="submit">Sign in</button></p>
</form>
</div>
"""

UPLOAD = """
<div class="card">
<h1>Grade a set of bubble sheets</h1>
<p class="muted">Scantron form 16485, scanned to PDF. Results are held in memory for {{ run_hours }} hours,
visible only in this browser, and never saved; download what you want to keep.</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post" action="/grade" enctype="multipart/form-data">
  <div class="fields">
    <label><strong>Test name</strong> <span class="muted">(optional)</span><br>
      <input type="text" name="title" placeholder="e.g. Exam 2"></label>
    <label><strong>Course or section</strong> <span class="muted">(optional)</span><br>
      <input type="text" name="course" placeholder="e.g. BIOL 1406-010"></label>
  </div>
  <label class="drop"><strong>Answer key</strong>
    <span class="muted">A PDF of the key sheet. Optional: leave it empty if the key is inside the
    student file, either named KEY in the name grid or as the first sheet.</span><br><br>
    <input type="file" name="key" accept="application/pdf">
  </label>
  <label class="drop"><strong>Student sheets</strong>
    <span class="muted">One or more PDFs. Scan both sides if the test goes past question 120 or
    you want names read; blank sheets are skipped.</span><br><br>
    <input type="file" name="students" accept="application/pdf" multiple>
  </label>
  <button type="submit">Grade</button>
</form>
</div>
"""

RESULTS = """
{% set s = stats %}
<div class="card">
  <h1>{{ g.heading }}</h1>
  {% if g.course %}<p class="muted" style="margin-top:-8px">{{ g.course }}</p>{% endif %}
  <div class="stats">
    <div class="stat"><span class="muted">Students</span><b>{{ s.count or 0 }}</b></div>
    <div class="stat"><span class="muted">Questions</span><b>{{ g.questions|length }}</b></div>
    {% if s %}
    <div class="stat"><span class="muted">Mean</span><b>{{ '%.1f'|format(s.mean) }}%</b></div>
    <div class="stat"><span class="muted">Median</span><b>{{ '%.1f'|format(s.median) }}%</b></div>
    <div class="stat"><span class="muted">High / Low</span><b>{{ '%.0f'|format(s.high) }} / {{ '%.0f'|format(s.low) }}</b></div>
    {% endif %}
  </div>
  <div class="actions" style="margin-top:16px">
    <a class="btn" href="#get">Download the results</a>
    <a class="btn secondary" href="/r/{{ run }}/sheet/0">View key sheet</a>
    <a class="btn secondary" href="javascript:print()">Print</a>
    <a class="btn secondary" href="/">Grade another set</a>
  </div>
</div>

<div class="card getit noprint" id="get">
  <h2>Download the results</h2>
  <p class="lede">Nothing here is saved on the machine. Take what you need before you close the page.</p>
  <div class="downloads">
    <a class="dl" href="/r/{{ run }}/download/xlsx"><span class="mark" aria-hidden="true">&darr;</span><span class="what"><b>Excel workbook</b><span class="note">Summary with chart, scores, colour-coded responses, item analysis, marks to check</span></span></a>
    <a class="dl" href="/r/{{ run }}/download/report.pdf"><span class="mark" aria-hidden="true">&darr;</span><span class="what"><b>Class report (PDF)</b><span class="note">Summary, distribution, roster, marks to check, item analysis</span></span></a>
    <a class="dl" href="/r/{{ run }}/download/students.pdf"><span class="mark" aria-hidden="true">&darr;</span><span class="what"><b>Student pages (PDF)</b><span class="note">One page per student: score, their answers against the key</span></span></a>
    <a class="dl" href="/r/{{ run }}/download/csv"><span class="mark" aria-hidden="true">&darr;</span><span class="what"><b>CSV</b><span class="note">Plain table for the gradebook or another program</span></span></a>
  </div>
</div>

{% if g.key_warnings or g.skipped %}
<div class="warn"><strong>Notes</strong><ul>
  {% for w in g.key_warnings %}<li>{{ w }}</li>{% endfor %}
  {% for w in g.skipped %}<li>{{ w }}</li>{% endfor %}
</ul></div>
{% endif %}

<div class="card">
  <h2>Key</h2>
  <p class="resp">{% for q in g.questions %}{{ q }}{{ g.key_answers[q] }}{% if not loop.last %} · {% endif %}{% endfor %}</p>
</div>

<div class="card">
  <h2>Students</h2>
  <p class="muted noprint">Sort by
    <a href="?sort=sheet">sheet order</a> · <a href="?sort=name">name</a> · <a href="?sort=score">score</a></p>
  <div class="scroll"><table>
    <tr><th class="num">#</th><th>Name</th><th class="num">Score</th><th class="num">%</th><th>Check</th><th>Responses (wrong in lower case, - blank, * multiple)</th></tr>
    {% for r in rows %}
    <tr>
      <td class="num">{{ r.sheet.number }}</td>
      <td><a href="/r/{{ run }}/sheet/{{ r.sheet.number }}">{{ r.label }}</a></td>
      <td class="num">{{ r.score }} / {{ r.possible }}</td>
      <td class="num">{{ '%.1f'|format(r.percent) }}</td>
      <td>{% if r.flags %}<span class="flag">{{ r.flags|length }} to check</span>{% endif %}</td>
      <td class="resp">{% for q in g.questions %}{% set a = r.responses[q] %}{% if q in r.correct %}{{ a }}{% elif a %}{{ a|lower }}{% else %}-{% endif %}{% if loop.index % 10 == 0 %} {% endif %}{% endfor %}</td>
    </tr>
    {% endfor %}
  </table></div>
</div>

{% if flagged %}
<div class="card">
  <h2>Marks to check by eye</h2>
  <p class="muted">"Multiple" means two bubbles were filled and the question earned no credit, as a
  machine would score it. "Light" means the mark was faint or an X; it was read and scored, but a
  person should confirm it.</p>
  <table>
    <tr><th>Student</th><th class="num">Question</th><th>Issue</th><th>Read as</th><th>Key</th></tr>
    {% for r, q, f in flagged %}
    <tr><td><a href="/r/{{ run }}/sheet/{{ r.sheet.number }}">{{ r.label }}</a></td><td class="num">{{ q }}</td>
        <td class="flag">{{ f }}</td><td>{{ r.responses[q] if r.responses[q] != '*' else 'two bubbles' }}</td><td>{{ g.key_answers[q] }}</td></tr>
    {% endfor %}
  </table>
</div>
{% endif %}

<div class="card">
  <h2>Item analysis</h2>
  <p class="muted">How each question performed. Discrimination compares the top and bottom thirds
  by score; near zero or negative is worth a look at the question or the key.</p>
  <div class="scroll"><table>
    <tr><th class="num">Q</th><th>Key</th><th class="num">% correct</th>
      {% for c in choices %}<th class="num">{{ c }}</th>{% endfor %}<th class="num">Blank</th><th class="num">Multi</th><th class="num">Discrim.</th></tr>
    {% for it in g.items %}
    {% set n = g.results|length %}
    <tr>
      <td class="num">{{ it.question }}</td><td class="keycell">{{ it.key }}</td>
      <td class="num">{{ '%.0f'|format(100 * it.correct / n) if n else '' }}</td>
      {% for c in choices %}<td class="num {{ 'keycell' if c == it.key }}">{{ it.counts[c] or '' }}</td>{% endfor %}
      <td class="num">{{ it.counts[''] or '' }}</td><td class="num">{{ it.counts['*'] or '' }}</td>
      <td class="num">{% if it.discrimination is not none %}{{ '%.2f'|format(it.discrimination) }}{% endif %}</td>
    </tr>
    {% endfor %}
  </table></div>
</div>
"""

SHEET = """
<div class="card">
  <p class="noprint"><a href="/r/{{ run }}">&larr; Back to results</a></p>
  <h1>{% if n == 0 %}Key sheet{% else %}{{ r.label }}{% endif %}</h1>
  {% if r %}<p><b>{{ r.score }} / {{ r.possible }}</b> ({{ '%.1f'|format(r.percent) }}%)</p>{% endif %}
  <p class="legend muted">
    {% if n == 0 %}<span style="color:#2858dc">&#9711; read as the answer</span>
    {% else %}<span style="color:#167a3e">&#9711; correct</span><span style="color:#d22828">&#9711; wrong</span>
    <span style="color:#2858dc">&#9711; the right answer, where missed</span>{% endif %}
    <span style="color:#eb8c00">&#9711; to check</span>
  </p>
  <div class="sheetimgs">
    {% if sheet.side1 %}<img src="/r/{{ run }}/sheet/{{ n }}/side1.png" alt="Side 1 as read">{% endif %}
    {% if sheet.side2 %}<img src="/r/{{ run }}/sheet/{{ n }}/side2.png" alt="Side 2 as read">{% endif %}
  </div>
  <p class="muted">From {{ sheet.source }}{% if sheet.side1 %}, page {{ sheet.side1.index + 1 }}{% endif %}{% if sheet.side2 %}{{ ' and' if sheet.side1 else ', page' }} {{ sheet.side2.index + 1 }}{% endif %}.</p>
</div>
"""

# Flask's include needs named templates; register the three bodies.
from jinja2 import DictLoader  # noqa: E402

app.jinja_loader = DictLoader({"login": LOGIN, "upload": UPLOAD, "results": RESULTS, "sheet": SHEET})
app.jinja_env.globals["run_hours"] = RUN_HOURS
