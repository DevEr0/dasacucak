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
    """Map (day, period) -> [PlacedLesson] for one entity (slots may hold
    several lessons: paired subgroups, parallel elective groups)."""
    g: dict[tuple, list] = {}
    for L in lessons:
        if key_fn(L) is not None:
            g.setdefault((L.day, L.period), []).append(L)
    for ls in g.values():
        ls.sort(key=lambda L: (L.subgroup, L.group_id))
    return g


def _lesson_tag(school, L, lang):
    """Subject name decorated with subgroup / elective-group markers."""
    name = _subject_name(school, L.subject_id, lang)
    if L.kind == "split":
        name += _t(lang, f" (խումբ {L.subgroup})", f" (group {L.subgroup})")
    if L.kind == "elective":
        grp = school.elective_groups.get(L.group_id)
        name = f"«{grp.name if grp else L.group_id}» {name}"
    return html.escape(name)


def _class_cell(school, ls, lang):
    if not ls:
        return '<td class="empty">—</td>'
    hard = any(school.subjects[L.subject_id].difficulty >= HARD_THRESHOLD
               for L in ls)
    cls = "cell hard" if hard else "cell"
    inner = []
    for L in ls:
        subj = school.subjects[L.subject_id]
        extra = ""
        if subj.requires_room_type:
            room = school.rooms.get(L.room_id)
            extra = ('<span class="room">'
                     + html.escape(room.name if room else L.room_id) + '</span>')
        teacher = html.escape(school.teachers[L.teacher_id].name)
        inner.append('<span class="subj">' + _lesson_tag(school, L, lang)
                     + '</span>' + extra
                     + '<span class="who">' + teacher + '</span>')
    return f'<td class="{cls}">' + '<hr class="pair">'.join(inner) + '</td>'


def _teacher_cell(school, ls, lang):
    if not ls:
        return '<td class="empty">—</td>'
    L = ls[0]
    subj = school.subjects[L.subject_id]
    cls = "cell hard" if subj.difficulty >= HARD_THRESHOLD else "cell"
    who = L.class_id
    if L.kind == "elective":
        grp = school.elective_groups.get(L.group_id)
        who = f"«{grp.name if grp else L.group_id}»"
    elif L.kind == "split":
        who += f"/{L.subgroup}"
    name = html.escape(_subject_name(school, L.subject_id, lang))
    return (f'<td class="{cls}"><span class="who">{html.escape(who)}</span>'
            f'<span class="subj">{name}</span></td>')


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
    from .render import lessons_of_class
    for cid in sorted(school.classes):
        mine = lessons_of_class(school, lessons, cid)
        grid = _grid_index(mine, lambda L: L)
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
  hr.pair { border: 0; border-top: 1px dashed var(--line); margin: 4px 0; }
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
