"""The web page: the standard sheets to print, and a form to make your own.

Nothing is stored. A sheet is its settings, which travel in the address, so a
custom sheet can be bookmarked or sent to a colleague as a link, and the PDF
is drawn fresh each time it is asked for.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pymupdf
from flask import Flask, Response, abort, jsonify, render_template_string, request

from . import layout as L
from . import settings
from .render import NAME, pdf
from .standard import BY_ID, ID_DIGITS, NAME_LETTERS, STANDARD

app = Flask(__name__)

GRADER_URL = settings.GRADER_URL
MAX_COPIES = 100
PREVIEW_DPI = 72

# Suggestions offered as a section's bubbles are typed; anything parse_bubbles takes is fine.
SUGGESTIONS = ["A-E", "A-D", "T/F", "Y/N", "A-C", "A-J", "1-5", "1-4"]


@app.after_request
def _headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(request.args.get(name, default))
    except ValueError:
        return default
    return max(lo, min(hi, v))


def _ticked(box: str) -> bool:
    """A checkbox: ticked by default on a fresh page.

    A form submitted with the box unticked sends nothing for it, so once the
    form has been submitted (s1 is there), absent means unticked. A link from
    before the ID was a checkbox says id_digits=N instead.
    """
    if box == "id" and "id" not in request.args and "id_digits" in request.args:
        return request.args.get("id_digits") not in ("", "0")
    return request.args.get(box, "1" if "s1" not in request.args else "") == "1"


def _sections() -> tuple[tuple[L.Section, ...], list[str], list[str]]:
    """Sections 1-4 from the query string, what was typed for each row's bubbles, and problems.

    A section with no questions is left out. Bubbles are typed (A-E, 1-5,
    T/F, Y/N); a section whose bubbles cannot be read becomes A-E for the
    preview, with the problem said, so nothing prints until it is fixed.
    """
    out, typed, problems = [], [], []
    for i in range(1, L.MAX_SECTIONS + 1):
        n = _int(f"s{i}", 0 if i > 1 else 50, 0, L.MAX_QUESTIONS)
        text = request.args.get(f"k{i}", "").strip()[:20] or "A-E"
        if ":" in text:  # links made before bubbles were typed: letters:5
            labels, _, count = text.partition(":")
            if labels in L.LABEL_SETS and count.isdigit():
                text = L.Section(1, int(count), labels).typed
        typed.append(text)
        try:
            choices, labels = L.parse_bubbles(text)
        except ValueError as exc:
            if n:
                problems.append((f"Section {i}: " if i > 1 else "") + str(exc))
            choices, labels = 5, "letters"
        if n:
            out.append(L.Section(n, choices, labels))
    return tuple(out) or (L.Section(50),), typed, problems


def _custom() -> tuple[L.Spec, str, str, int, list[str], list[str]]:
    """The form's settings, from the query string.

    Every sheet has a bubbled name, so results always come back with names:
    the grader cannot read handwriting. That rules out half pages, since a
    name grid is taller than one; the format can still describe them.
    """
    sections, typed, problems = _sections()
    spec = L.Spec(
        sections=sections,
        id_digits=ID_DIGITS if _ticked("id") else 0,
        name_letters=_int("name_letters", NAME_LETTERS, 4, L.MAX_NAME),
        # A form submitted without the box ticked sends no "key" at all.
        key_bubble=_ticked("key"),
    )
    title = request.args.get("title", "").strip()[:80]
    course = request.args.get("course", "").strip()[:80]
    return spec, title, course, _int("copies", 1, 1, MAX_COPIES), typed, problems


def _summary(spec: L.Spec, typed_problems: list[str] = ()) -> dict:
    problems = list(typed_problems) + spec.problems()
    if problems:
        return {"problems": problems, "pages": 0, "describe": spec.describe(), "fits": ""}
    pages = len(L.layout(spec))
    room = L.capacity(spec)
    last = spec.sections[-1].describe()
    if pages == 1:
        fits = "Fits on one side of one page."
    else:
        fits = f"{pages} pages: print double-sided, and scan every page."
    if pages == 1 and room > spec.questions:
        fits += f" There is room for {room} questions here, if the last section were {last} to the end."
    return {"problems": [], "pages": pages, "describe": spec.describe(), "fits": fits}


def _filename(title: str, spec: L.Spec) -> str:
    base = re.sub(r"[^A-Za-z0-9 _.-]+", "", title).strip() or "Answer sheet"
    what = re.sub(r"[^A-Za-z0-9 ,_.()-]+", "-", spec.describe().replace(" · ", ", "))
    return f"{base} - {what}.pdf"


@lru_cache(maxsize=256)
def _pdf(spec: L.Spec, title: str, course: str, copies: int = 1) -> bytes:
    return pdf(spec, title, course, copies)


@lru_cache(maxsize=256)
def _png(spec: L.Spec, title: str, course: str, page: int) -> bytes:
    doc = pymupdf.open(stream=_pdf(spec, title, course), filetype="pdf")
    return doc[page].get_pixmap(dpi=PREVIEW_DPI).tobytes("png")


def _send_pdf(data: bytes, name: str, inline: bool) -> Response:
    how = "inline" if inline else "attachment"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{how}; filename="{name}"'})


@app.get("/")
def index():
    spec, title, course, copies, typed, problems = _custom()
    counts = [_int(f"s{i}", 0 if i > 1 else 50, 0, L.MAX_QUESTIONS) for i in range(1, L.MAX_SECTIONS + 1)]
    rows = [(i, counts[i - 1] or "", typed[i - 1]) for i in range(1, L.MAX_SECTIONS + 1)]
    return render_template_string(
        PAGE, standard=STANDARD, spec=spec, title=title, course=course, copies=copies,
        rows=rows, suggestions=SUGGESTIONS, s=_summary(spec, problems), query=request.query_string.decode(),
        L=L, grader=GRADER_URL, max_copies=MAX_COPIES, name=NAME, id_digits=ID_DIGITS,
    )


@app.get("/info")
def info():
    spec, *_, problems = _custom()
    return jsonify(_summary(spec, problems))


@app.get("/sheet.pdf")
def custom_pdf():
    spec, title, course, copies, _, typed_problems = _custom()
    problems = typed_problems + spec.problems()
    if problems:
        return Response(" ".join(problems), status=400, mimetype="text/plain")
    data = _pdf(spec, title, course, copies)
    return _send_pdf(data, _filename(title, spec), request.args.get("view") == "1")


@app.get("/preview/<int:page>.png")
def custom_png(page):
    spec, title, course, _, _, typed_problems = _custom()
    if typed_problems or spec.problems() or not 1 <= page <= len(L.layout(spec)):
        abort(404)
    return Response(_png(spec, title, course, page - 1), mimetype="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@app.get("/standard/<sid>.pdf")
def standard_pdf(sid):
    s = BY_ID.get(sid) or abort(404)
    copies = _int("copies", 1, 1, MAX_COPIES)
    return _send_pdf(_pdf(s.spec, "", "", copies), _filename(f"{s.kind} answer sheet", s.spec),
                     request.args.get("view") == "1")


@app.get("/standard/<sid>.png")
def standard_png(sid):
    s = BY_ID.get(sid) or abort(404)
    return Response(_png(s.spec, "", "", 0), mimetype="image/png",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/health")
def health():
    return jsonify(ok=True)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ name }}</title>
<style>
:root { --ink:#1d2330; --muted:#5d6675; --line:#dfe3ea; --bg:#f6f7f9; --card:#fff;
        --accent:#4f2d7f; --soft:#faf7fd; --bad:#b3261e; }
* { box-sizing:border-box; }
[hidden] { display:none !important; }
body { margin:0; font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       color:var(--ink); background:var(--bg); }
header { background:var(--accent); color:#fff; padding:14px 24px; display:flex;
         justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
header a { color:#fff; text-decoration:none; }
header .brand { font-weight:600; font-size:18px; }
header .to { font-size:14px; border:1px solid rgba(255,255,255,.6); border-radius:8px; padding:5px 12px; }
main { max-width:1150px; margin:24px auto; padding:0 16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:20px 24px; margin-bottom:20px; }
h1 { font-size:22px; margin:0 0 6px; } h2 { font-size:18px; margin:0 0 4px; }
.lede { margin:0 0 16px; color:var(--muted); }
.lib { display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); }
.sheet { display:flex; flex-direction:column; border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--card); }
.sheet a.thumb { display:block; background:#eef0f4; padding:8px; border-bottom:1px solid var(--line); }
.sheet img { display:block; width:100%; aspect-ratio:8.5/11; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.15); }
.sheet .body { padding:8px 10px 10px; display:flex; flex-direction:column; gap:4px; flex:1; }
.sheet b { font-size:15px; } .sheet p { margin:0; font-size:13px; color:var(--muted); flex:1; }
button, .btn { background:var(--accent); color:#fff; border:0; border-radius:8px; padding:9px 16px;
               font-size:15px; cursor:pointer; text-decoration:none; display:inline-block; text-align:center; }
button:disabled { opacity:.45; cursor:default; }
.btn.secondary, button.secondary { background:#fff; color:var(--accent); border:1px solid var(--accent); }
.btn.small, button.small { padding:5px 10px; font-size:13px; }
.maker { display:grid; grid-template-columns:minmax(280px,370px) 1fr; gap:24px; align-items:start; }
@media (max-width:780px) { .maker { grid-template-columns:1fr; } }
form label { display:block; margin:0 0 12px; font-weight:600; font-size:14px; }
form label span.hint { font-weight:400; color:var(--muted); }
form input[type=text], form input[type=number], form select { display:block; width:100%; margin-top:4px;
  padding:8px 10px; border:1px solid var(--line); border-radius:8px; font-size:15px; background:#fff; }
form .row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
fieldset { border:1px solid var(--line); border-radius:10px; padding:10px 12px 4px; margin:0 0 12px; }
legend { font-weight:600; font-size:14px; padding:0 4px; }
.sec { display:grid; grid-template-columns:auto 82px 1fr auto; gap:8px; align-items:end; margin-bottom:8px; }
.sec .n { font-weight:600; font-size:13px; color:var(--muted); padding-bottom:10px; }
.sec label { margin:0; font-size:12px; font-weight:400; color:var(--muted); }
.sec .rm { background:none; color:var(--muted); border:0; padding:8px 4px; font-size:20px; line-height:1; }
form label.check { display:flex; gap:8px; align-items:flex-start; font-weight:400; }
form label.check input { margin-top:4px; }
.status { background:var(--soft); border-radius:8px; padding:10px 12px; margin:4px 0 12px; font-size:14px; }
.error { background:#fdecea; color:var(--bad); border-radius:8px; padding:10px 12px; margin:4px 0 12px; font-size:14px; }
.actions { display:flex; gap:8px; flex-wrap:wrap; }
.previews { display:flex; gap:14px; flex-wrap:wrap; background:#eef0f4; border-radius:10px; padding:14px; min-height:200px; }
.previews img { width:min(100%, 440px); aspect-ratio:8.5/11; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.18); }
.tips { columns:2 300px; column-gap:32px; padding-left:20px; margin:8px 0 0; }
.tips li { margin-bottom:8px; break-inside:avoid; }
</style></head>
<body>
<header>
  <a class="brand" href="/">{{ name }}</a>
  <a class="to" href="{{ grader }}">Grade scanned sheets &rarr;</a>
</header>
<main>

<div class="card">
  <h1>Answer sheets you print yourself</h1>
  <p class="lede" style="margin:0">Print one, then copy it on any black-and-white copier. The
  <a href="{{ grader }}">Scantron Grader</a> reads them from a scanned PDF, even crooked, shrunk or
  upside down: the black corner squares and edge marks tell it where every bubble is, and the
  code strips top and bottom tell it which sheet it is looking at.</p>
</div>

<div class="card">
  <h2>Standard sheets</h2>
  <p class="lede">One side of a full page each, with a bubbled name, a 9-digit student ID and an ANSWER
  KEY bubble. Every sheet has a bubbled name so your results come back with names on them. Click a
  picture to open the PDF.</p>
  <div class="lib">
  {% for s in standard %}
    <div class="sheet">
      <a class="thumb" href="/standard/{{ s.id }}.pdf?view=1" target="_blank" rel="noopener">
        <img src="/standard/{{ s.id }}.png" alt="{{ s.kind }} answer sheet" loading="lazy"></a>
      <div class="body">
        <b>{{ s.kind }}</b>
        <p>{{ s.blurb }}</p>
        <a class="btn small" href="/standard/{{ s.id }}.pdf">Download PDF</a>
      </div>
    </div>
  {% endfor %}
  </div>
</div>

<div class="card" id="make">
  <h2>Make your own</h2>
  <p class="lede">Build the questions in sections: say 20 true/false, then 30 A–E. Numbering runs on
  from one section to the next, and a longer test continues on the back. The link in your address bar keeps these
  settings, so you can bookmark it or send it to a colleague.</p>
  <div class="maker">
    <form method="get" action="/#make" id="f">
      <label>Title on the sheet <span class="hint">(optional)</span>
        <input type="text" name="title" value="{{ title }}" maxlength="80" placeholder="e.g. BIOL 1406 Exam 2"></label>
      <label>Course, section or instructor <span class="hint">(optional)</span>
        <input type="text" name="course" value="{{ course }}" maxlength="80" placeholder="e.g. Dr. Smith, Section 010"></label>

      <fieldset id="sections"><legend>Questions</legend>
      {% for i, n, k in rows %}
        <div class="sec" data-i="{{ i }}" {% if i > 1 and not n %}data-empty="1"{% endif %}>
          <span class="n">{{ i }}</span>
          <label>How many<input type="number" name="s{{ i }}" value="{{ n }}" min="0" max="{{ L.MAX_QUESTIONS }}" {% if i == 1 %}required{% endif %}></label>
          <label>Bubbles<input type="text" name="k{{ i }}" value="{{ k }}" list="bubble-kinds"
            maxlength="20" placeholder="A-E" autocomplete="off" spellcheck="false"></label>
          {% if i > 1 %}<button type="button" class="rm" title="Remove this section" aria-label="Remove section {{ i }}">&times;</button>{% else %}<span></span>{% endif %}
        </div>
      {% endfor %}
        <datalist id="bubble-kinds">{% for v in suggestions %}<option value="{{ v }}">{% endfor %}</datalist>
        <p class="hint" style="margin:0 0 8px;font-size:13px;color:var(--muted)">Type the bubbles: <b>A-E</b>,
          <b>A-D</b>, <b>1-5</b>, <b>T/F</b> or <b>Y/N</b>. Letters run up to J, numbers up to 9.</p>
        <p style="margin:0 0 8px"><button type="button" class="small secondary" id="add">+ Add a section</button></p>
      </fieldset>

      <label>Name letters <span class="hint">(13 leaves room for two A–E columns)</span>
        <input type="number" name="name_letters" value="{{ spec.name_letters }}" min="4" max="{{ L.MAX_NAME }}"></label>
      <label class="check"><input type="checkbox" name="id" value="1" {{ 'checked' if spec.id_digits }}>
        <span>A <b>student ID</b> grid ({{ id_digits }} digits), for matching results to the gradebook</span></label>
      <label class="check"><input type="checkbox" name="key" value="1" {{ 'checked' if spec.key_bubble }}>
        <span>An <b>ANSWER KEY</b> bubble, so the key can go in the same pile as the students' sheets</span></label>
      <label>Copies in the PDF <span class="hint">(1 to copy on a copier; more to send to a printer)</span>
        <input type="number" name="copies" value="{{ copies }}" min="1" max="{{ max_copies }}"></label>

      <div id="status">
      {% if s.problems %}<div class="error">{% for p in s.problems %}{{ p }} {% endfor %}</div>
      {% else %}<div class="status"><b>{{ s.describe }}</b><br>{{ s.fits }}</div>{% endif %}
      </div>
      <div class="actions">
        <button type="submit" formaction="/sheet.pdf" id="dl" {{ 'disabled' if s.problems }}>Download PDF</button>
        <button type="submit" class="secondary" id="refresh">Update preview</button>
      </div>
    </form>
    <div class="previews" id="previews" aria-live="polite">
      {% if not s.problems %}{% for n in range(1, s.pages + 1) %}
        <img src="/preview/{{ n }}.png?{{ query }}" alt="Page {{ n }} of the sheet">
      {% endfor %}{% endif %}
    </div>
  </div>
</div>

<div class="card">
  <h2>Printing, scanning and grading</h2>
  <ul class="tips">
    <li><b>Print at actual size</b> (100%), on white Letter paper. "Fit to page" still grades, but
      leaves less margin for a crooked copy.</li>
    <li><b>Copy on any black-and-white copier.</b> Copies of copies are fine. Keep the four corner
      squares, the marks down both edges and the code strips on the paper; a copy that cuts one off
      cannot be read.</li>
    <li><b>Longer tests</b> continue on a second page: print double-sided on one sheet of paper. Scan both sides; the grader
      puts the pages of each sheet back together.</li>
    <li><b>Students</b> use a No. 2 pencil or a dark pen and fill each bubble completely. Stray marks
      and light erasures are ignored; two filled bubbles earn no credit and are listed for you to check.</li>
    <li><b>The key</b> is an ordinary sheet with ANSWER KEY bubbled. Put it anywhere in the pile, or
      upload it separately. Then scan to PDF at 150 dpi or more and upload to the
      <a href="{{ grader }}">Scantron Grader</a>.</li>
  </ul>
</div>

</main>
<script>
// Keep the preview in step with the form, and show only the sections in use.
// Without JavaScript all four section rows show (an empty one is ignored), and
// "Update preview" redraws with a page load.
(function () {
  var f = document.getElementById('f'), box = document.getElementById('previews'),
      status = document.getElementById('status'), dl = document.getElementById('dl'),
      add = document.getElementById('add'), timer = null;
  var rows = Array.prototype.slice.call(document.querySelectorAll('.sec'));
  document.getElementById('refresh').style.display = 'none';
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function shown() { return rows.filter(function (r) { return !r.hidden; }); }
  function sync() { add.hidden = shown().length >= rows.length; }
  rows.forEach(function (r) { if (r.dataset.empty) r.hidden = true; });
  sync();
  add.addEventListener('click', function () {
    var next = rows.filter(function (r) { return r.hidden; })[0];
    if (!next) return;
    next.hidden = false;
    var n = next.querySelector('input');
    if (!n.value || n.value === '0') n.value = 10;
    sync(); later(50); n.focus();
  });
  rows.forEach(function (r) {
    var rm = r.querySelector('.rm');
    if (rm) rm.addEventListener('click', function () {
      // Close the gap: move the later sections up one, then hide the last.
      var vis = shown(), at = vis.indexOf(r);
      for (var i = at; i < vis.length - 1; i++) {
        vis[i].querySelector('input').value = vis[i + 1].querySelector('input').value;
        vis[i].querySelector('input[name^="k"]').value = vis[i + 1].querySelector('input[name^="k"]').value;
      }
      var last = vis[vis.length - 1];
      last.querySelector('input').value = '';
      last.querySelector('input[name^="k"]').value = 'A-E';
      last.hidden = true;
      sync(); later(50);
    });
  });
  function query() {
    var p = new URLSearchParams(new FormData(f));
    rows.forEach(function (r) { if (r.hidden) { p.delete('s' + r.dataset.i); p.delete('k' + r.dataset.i); } });
    if (!f.key.checked) p.set('key', '0');
    if (!f.id.checked) p.set('id', '0');
    return p.toString();
  }
  function update() {
    var q = query();
    history.replaceState(null, '', '/?' + q + '#make');
    fetch('/info?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (d.problems.length) {
        status.innerHTML = '<div class="error">' + esc(d.problems.join(' ')) + '</div>';
        dl.disabled = true;
        return;
      }
      dl.disabled = false;
      status.innerHTML = '<div class="status"><b>' + esc(d.describe) + '</b><br>' + esc(d.fits) + '</div>';
      var html = '';
      for (var n = 1; n <= d.pages; n++)
        html += '<img src="/preview/' + n + '.png?' + q + '" alt="Page ' + n + ' of the sheet">';
      box.innerHTML = html;
    });
  }
  function later(ms) { clearTimeout(timer); timer = setTimeout(update, ms); }
  f.addEventListener('input', function () { later(350); });
  f.addEventListener('change', function () { later(50); });
  // The download takes the visible sections only.
  f.addEventListener('submit', function (e) {
    e.preventDefault();
    window.location.href = '/sheet.pdf?' + query();
  });
})();
</script>
</body></html>"""
