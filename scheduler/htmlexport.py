"""
Optional HTML export: a single self-contained, printable .html file holding
every class timetable and every teacher timetable as colour-coded grids.

This is a *bonus* output. The CLI wraps the call in try/except, so a problem
here never affects the real (text/JSON) deliverables.

    export_html(school, lessons, path, lang)
"""
from __future__ import annotations

import html
from collections import defaultdict

from .models import School
from .solver import PlacedLesson

PERIOD_PREFIX = {"hy": "Դ", "en": "P"}
HARD_THRESHOLD = 4  # subjects with difficulty >= this are tinted as "hard"


def _t(lang: str, hy: str, en: str) -> str:
    return hy if lang == "hy" else en


def _subject_name(school: School, sid: str, lang: str) -> str:
    s = school.subjects[sid]
    return s.name_hy if lang == "hy" else (s.name_en or s.name_hy)


def _grid_index(lessons, key_fn):
    """Map (day, period) -> PlacedLesson for one entity."""
    g: dict[tuple, PlacedLesson] = {}
    for L in lessons:
        k = key_fn(L)
        if k is not None:
            g[(L.day, L.period)] = L
    return g


def _class_cell(school, L, lang):
    if L is None:
        return '<td class="empty">—</td>'
    name = html.escape(_subject_name(school, L.subject_id, lang))
    subj = school.subjects[L.subject_id]
    room = school.rooms[L.room_id]
    cls = "cell hard" if subj.difficulty >= HARD_THRESHOLD else "cell"
    extra = ""
    # show room only when it is a specialised room (matches the text renderer)
    if subj.requires_room_type:
        extra = f'<span class="room">{html.escape(room.name)}</span>'
    teacher = html.escape(school.teachers[L.teacher_id].name)
    return f'<td class="{cls}"><span class="subj">{name}</span>{extra}<span class="who">{teacher}</span></td>'


def _teacher_cell(school, L, lang):
    if L is None:
        return '<td class="empty">—</td>'
    name = html.escape(_subject_name(school, L.subject_id, lang))
    subj = school.subjects[L.subject_id]
    cls = "cell hard" if subj.difficulty >= HARD_THRESHOLD else "cell"
    cid = html.escape(L.class_id)
    return f'<td class="{cls}"><span class="who">{cid}</span><span class="subj">{name}</span></td>'


def _table(school, grid, lang, cell_fn):
    pp = PERIOD_PREFIX[lang]
    rb = school.reserved_break_period
    head = "".join(f"<th>{html.escape(school.day_name(d, lang))}</th>"
                   for d in range(school.n_days))
    rows = []
    for p in range(1, school.periods_per_day + 1):
        if rb is not None and p == rb:
            label = _t(lang, "ընդմիջում", "break")
            span = school.n_days
            rows.append(
                f'<tr><th>{pp}{p}</th>'
                f'<td class="break" colspan="{span}">{label}</td></tr>')
            continue
        cells = "".join(cell_fn(school, grid.get((d, p)), lang)
                        for d in range(school.n_days))
        rows.append(f"<tr><th>{pp}{p}</th>{cells}</tr>")
    return (f'<table><thead><tr><th class="corner"></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def export_html(school: School, lessons: list[PlacedLesson],
                path: str, lang: str = "hy") -> None:
    title = _t(lang,
               f"Դասացուցակ — {school.year}",
               f"Timetable — {school.year}")
    h_classes = _t(lang, "Դասարանների դասացուցակ", "Class timetables")
    h_teachers = _t(lang, "Ուսուցիչների դասացուցակ", "Teacher timetables")
    load_lbl = _t(lang, "Շաբաթական ծանրաբեռնվածություն", "Weekly load")

    parts: list[str] = []

    # ---- per-class grids -------------------------------------------------
    parts.append(f"<h2>{html.escape(h_classes)}</h2>")
    for cid in sorted(school.classes):
        grid = _grid_index(lessons, lambda L, c=cid: L if L.class_id == c else None)
        parts.append(f'<section><h3>{html.escape(cid)}</h3>'
                     + _table(school, grid, lang, _class_cell) + "</section>")

    # ---- per-teacher grids ----------------------------------------------
    parts.append(f"<h2>{html.escape(h_teachers)}</h2>")
    load = defaultdict(int)
    for L in lessons:
        load[L.teacher_id] += 1
    for tid in sorted(school.teachers, key=lambda t: school.teachers[t].name):
        teacher = school.teachers[tid]
        if load[tid] == 0:
            continue
        grid = _grid_index(lessons, lambda L, t=tid: L if L.teacher_id == t else None)
        cap = teacher.resolved_cap()
        parts.append(
            f'<section><h3>{html.escape(teacher.name)} '
            f'<small>{load_lbl}: {load[tid]}/{cap}</small></h3>'
            + _table(school, grid, lang, _teacher_cell) + "</section>")

    body = "\n".join(parts)
    doc = _PAGE.replace("{{TITLE}}", html.escape(title)).replace("{{BODY}}", body)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)


_PAGE = """<!DOCTYPE html>
<html lang="hy">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
  :root { --line:#d8dee9; --hard:#fde8e4; --break:#eef3fb; --ink:#1f2933;
          --muted:#6b7280; --accent:#2f5d8a; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Noto Sans Armenian", Segoe UI, Roboto, sans-serif;
         color: var(--ink); margin: 0; padding: 24px; background:#fff; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 18px; margin: 28px 0 8px; color: var(--accent);
       border-bottom: 2px solid var(--accent); padding-bottom: 4px; }
  h3 { font-size: 15px; margin: 18px 0 6px; }
  h3 small { font-weight: 400; color: var(--muted); font-size: 12px; }
  section { break-inside: avoid; page-break-inside: avoid; margin-bottom: 6px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 6px;
          table-layout: fixed; }
  th, td { border: 1px solid var(--line); padding: 5px 6px; font-size: 12px;
           vertical-align: top; text-align: left; }
  thead th { background: var(--accent); color: #fff; text-align: center;
             font-weight: 600; }
  tbody th { background: #f3f5f8; text-align: center; width: 42px;
             color: var(--muted); font-weight: 600; }
  td.empty { color: #c2c8d0; text-align: center; }
  td.break { background: var(--break); text-align: center; color: var(--muted);
             font-style: italic; }
  td.cell.hard { background: var(--hard); }
  .subj { display: block; font-weight: 600; }
  .who  { display: block; color: var(--muted); font-size: 11px; }
  .room { display: block; color: var(--accent); font-size: 11px; }
  .legend { font-size: 12px; color: var(--muted); margin: 4px 0 0; }
  .legend .swatch { display:inline-block; width:11px; height:11px;
                    background:var(--hard); border:1px solid #e6b9af;
                    vertical-align:middle; margin-right:4px; }
  @media print { body { padding: 0; } h2 { page-break-before: auto; } }
</style>
</head>
<body>
<h1>{{TITLE}}</h1>
<p class="legend"><span class="swatch"></span>
  <span lang="hy">գունավորված = դժվար առարկա</span></p>
{{BODY}}
</body>
</html>
"""
