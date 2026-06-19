# Դասացուցակ — Armenian School Timetable Generator

A constraint-solving timetable generator for Armenian general-education schools
(հանրակրթական դպրոց). You describe the school — classes, the curriculum
(ուսումնական պլան), teachers and their qualifications, rooms — and it produces a
weekly timetable that satisfies every hard rule and is optimised for teacher gaps
and even daily load. Every finished schedule is then **independently re-validated**
and rejected if it breaks any rule.

It is built on Google OR-Tools **CP-SAT**, so all the conflict and curriculum
rules are real constraints (not a best-effort heuristic): if a legal timetable
exists, the solver finds one; if none exists, it tells you instead of producing a
broken result.

---

## Why these numbers (regulatory basis)

The defaults follow current ՀՀ ԿԳՄՍ (Ministry of Education, Science, Culture and
Sport) norms. **All of them are configurable per school / class / teacher** — the
values below are just the defaults applied when your input omits a field.

- **Teacher weekly load (դրույք):** the old 22-hour full-rate norm was replaced.
  The defaults are **18 h/week for primary-grade (1–4) teachers** and
  **20 h/week for subject (5–12) teachers**. Administrative staff who also teach
  default to a reduced cap (12 h). Each teacher can override this with
  `max_weekly_load`.
- **Student weekly load is graduated by grade, not a single number.** It rises
  with grade up to **34 lessons/week** in the upper grades, and is lower in the
  primary grades. Per-grade ceilings live in `scheduler/curriculum.py`
  (`GRADE_RULES_DEFAULT`) and can be edited.
- **5-day school week** (Mon–Fri) by default.
- **No forced lunch period.** Armenian schools generally use short breaks between
  lessons rather than a fixed lunch slot; an optional reserved-break period is
  supported if your school uses an extended-day (երկարօրյա) model — set
  `reserved_break_period`.

If your school’s plan differs, change the data — the program does not hard-code
any school’s specific hours.

---

## Two ways to use it

**1. Visual app (recommended for end users).** A browser UI where you enter the
whole school in forms and a curriculum grid, click **Generate timetable**, and
read the class/teacher timetables on screen — no JSON, no command line.

```bash
pip install -r requirements.txt
python3 -m scheduler.web
```

Then open **http://127.0.0.1:5000** in a browser. The app opens pre-filled with
the sample school so you can try it immediately; edit it, or start from your own
data. Use **Load sample / Import / Export** to move schools in and out as JSON.
The Python solver runs locally behind the page — nothing is sent anywhere.

The UI has five editors and a results view:

- **Settings** — year, periods/day, optional reserved break, solver time budget.
- **Subjects** — name (Armenian + English), difficulty 1–5, required room type,
  PE flag, repetition limits.
- **Rooms** — classrooms and specialised rooms (labs, gym, computer, resource).
- **Classes** — the **curriculum matrix**: classes down the side, subjects across
  the top, weekly hours in the cells; each row shows a running total that turns
  red if it passes the grade’s legal weekly ceiling.
- **Teachers** — name, qualified subjects (as chips), role (sets the 18/20 cap),
  optional load override, and available days.
- **Timetable** — a green “legal” banner (or the list of violations), quality
  stats (teacher gaps, solve time), switchable class/teacher grids, and
  **Download HTML / JSON**.

> To offer this as a hosted product, run it behind a real WSGI server
> (e.g. `gunicorn 'scheduler.web:app'`) instead of the built-in dev server.

**2. Command line (for automation / scripting).**

Requires Python 3.10+ and OR-Tools:

```bash
pip install ortools
```

Run on the bundled sample school:

```bash
python3 -m scheduler.cli data/sample_school.json --lang hy --out-dir out
```

Options:

| flag | meaning | default |
|------|---------|---------|
| `input` | path to the school JSON | (required) |
| `--lang` | `hy` (Armenian) or `en` | `hy` |
| `--max-seconds` | solver time budget | 30 |
| `--workers` | parallel solver workers | 8 |
| `--out-dir` | also write files here | (print only) |
| `--quiet` | print only the quality summary | off |

When `--out-dir` is given you get: `classes.txt`, `teachers.txt`, `quality.txt`,
`schedule.json` (machine-readable), and a printable `timetable.html`.

**Exit codes:** `0` success · `2` teacher assignment or preflight infeasible ·
`3` solver proved no legal timetable exists · `4` solver result failed
independent validation (should never happen — it is a safety net).

---

## Output format

Per class:

```text
=== 7Ա (2024-2025) ===
Երկուշաբթի
Դ1 Ֆիզիկա  [Ֆիզիկայի լաբ.]
Դ2 Հանրահաշիվ
...
```

Per teacher, with weekly load:

```text
=== Անի Հարությունյան ===
Երկուշաբթի
Դ1 7Ա Մաթեմատիկա
Դ2 8Բ Մաթեմատիկա
...
Շաբաթական ծանրաբեռնվածություն: 19/20
```

(With `--lang en` the same layout uses `P1`, `Monday`, `Weekly load: 19/20`.)

---

## Input format

A single JSON object. Fields left out fall back to the curriculum defaults.

```jsonc
{
  "year": "2024-2025",
  "periods_per_day": 7,
  "reserved_break_period": null,        // or e.g. 4 to keep period 4 free

  "subjects": {
    "fizika":   {"name_hy": "Ֆիզիկա", "name_en": "Physics",
                 "difficulty": 5, "requires_room_type": "lab_physics"},
    "fizkultura": {"name_hy": "Ֆիզկուլտուրա", "is_pe": true,
                   "requires_room_type": "gym"}
    // difficulty 1..5; requires_room_type ties a subject to a room type
  },

  "rooms": {
    "lab1": {"name": "Ֆիզիկայի լաբ.", "type": "lab_physics"},
    "c7a":  {"name": "Կաբ. 7Ա", "type": "classroom", "home_for": "7Ա"}
  },

  "classes": {
    "7Ա": {"grade": 7, "home_room": "c7a",
           "weekly_hours": {"fizika": 2, "hanrahashiv": 3, "...": 1}}
  },

  "teachers": {
    "t_math": {"name": "Անի Հարությունյան",
               "qualified_subjects": ["hanrahashiv", "erkrachapatutyun"],
               "role": "subject",            // primary | subject | admin
               "max_weekly_load": 20,        // optional override
               "available_days": [0,1,2,3,4],     // optional (0=Mon)
               "available_periods": [1,2,3,4,5,6,7]}// optional
  },

  "assignments": []   // leave empty to auto-assign teachers from qualifications,
                      // or pin specific class+subject -> teacher mappings
}
```

**Teacher assignment is automatic.** If `assignments` is empty, the program reads
each teacher’s `qualified_subjects` and assigns lessons greedily (hardest subjects
first, consolidating a class’s subject under one teacher, never exceeding a cap).
To pin a specific teacher to a class+subject, add entries to `assignments`.

---

## Constraints

**Hard (always enforced; a schedule that breaks any of these is impossible or
rejected):**

- curriculum weekly hours met **exactly** for every class+subject;
- teacher weekly load ≤ that teacher’s cap (18/20/admin or override);
- no teacher, class, or room double-booked in the same slot;
- lab / gym / computer / resource subjects placed only in matching rooms, and a
  specialised room is never overbooked beyond how many exist;
- inclusive-education (ներառական) sessions scheduled like any other lesson;
- class daily lessons ≤ grade limit; class weekly lessons ≤ grade ceiling;
- teacher availability (days / periods) respected;
- reserved break period (if set) kept empty;
- same subject not repeated back-to-back beyond its `max_consecutive`.

**Soft (optimised, weighted — see `WEIGHTS_DEFAULT` in `curriculum.py`):**

- minimise teacher gaps (պատուհաններ);
- place difficult subjects (difficulty ≥ 4) in the morning;
- avoid clustering too many hard subjects on one day;
- keep PE off the end of an already-heavy day;
- balance each class’s load evenly across Mon–Fri;
- balance each teacher’s load across the week.

Edit the weights to change priorities (e.g. raise `teacher_gaps` to fight
windows harder, or `class_balance` for flatter days).

---

## Validation

`scheduler/validator.py` re-checks a finished timetable **from scratch**, without
trusting the solver. It takes any list of placed lessons — including a
hand-edited one — and returns the list of violations (empty ⇒ legal). It catches:
curriculum mismatches and stray lessons, class/teacher/room conflicts, daily and
weekly load overruns, teacher load over cap, availability breaches, wrong room
types, and lessons placed in the reserved break.

This is what lets you safely **edit a generated schedule by hand** and re-check it.

---

## Project layout

```
scheduler/
  models.py       data classes (School, Teacher, Subject, Room, …)
  curriculum.py   default grade rules, difficulty, room types, weights
  loader.py       read JSON -> School, apply defaults
  assigner.py     auto-assign teachers + feasibility preflight
  solver.py       CP-SAT model: hard constraints + weighted objective
  validator.py    independent re-validation of a finished timetable
  render.py       text timetables (hy/en) + quality report
  htmlexport.py   optional printable HTML
  cli.py          command-line entry point
  web.py          local web app (Flask) — the visual UI backend
  webui/          the browser UI (index.html, app.css, app.js)
  tests.py        smoke test (solve + validation rejection)
data/
  sample_school.json   realistic illustrative dataset (grades 7–8)
```

> The sample school’s hours and teachers are **illustrative**. For real use,
> replace `weekly_hours` with your school’s official ուսումնական պլան and enter
> your actual staff, qualifications, and rooms.
