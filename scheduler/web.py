"""
Local web app: a browser UI for building a school and generating its timetable.

Run:
    python3 -m scheduler.web
then open http://127.0.0.1:5000

The Python CP-SAT solver runs server-side; the browser only handles data entry
and displaying results, so nothing about the scheduling logic changes — this is
the same pipeline the CLI uses (assign → preflight → solve → validate).
"""
from __future__ import annotations

import json
import os
import tempfile

from flask import Flask, jsonify, request, send_from_directory

from . import curriculum as C
from .assigner import AssignmentError, build_assignments, preflight
from .htmlexport import export_html
from .loader import build_school
from .solver import solve
from .validator import validate

HERE = os.path.dirname(__file__)
WEBUI = os.path.join(HERE, "webui")
SAMPLE = os.path.join(os.path.dirname(HERE), "data", "sample_school.json")

app = Flask(__name__, static_folder=WEBUI, static_url_path="")


@app.get("/")
def index():
    return send_from_directory(WEBUI, "index.html")


@app.get("/api/sample")
def sample():
    with open(SAMPLE, encoding="utf-8") as fh:
        return jsonify(json.load(fh))


@app.get("/api/defaults")
def defaults():
    """Expose curriculum defaults so the UI can show sensible hints."""
    return jsonify({
        "grade_rules": {str(g): vars(GradeRuleLite(g)) for g in range(1, 13)},
        "hard_threshold": C.HARD_THRESHOLD,
        "morning_last_period": C.MORNING_LAST_PERIOD,
        "roles": ["primary", "subject", "admin"],
        "weights_default": C.WEIGHTS_DEFAULT,
    })


class GradeRuleLite:
    def __init__(self, g):
        r = C.GRADE_RULES_DEFAULT.get(g, {"max_lessons_per_day": 7,
                                          "max_weekly_load": 34})
        self.max_lessons_per_day = r["max_lessons_per_day"]
        self.max_weekly_load = r["max_weekly_load"]


@app.post("/api/solve")
def api_solve():
    body = request.get_json(force=True)
    raw = body.get("school", {})
    max_seconds = int(body.get("max_seconds", 20))
    workers = int(body.get("workers", 8))

    try:
        school = build_school(raw)
    except Exception as e:  # malformed input from the editor
        return jsonify({"ok": False, "stage": "input",
                        "message": f"The school could not be read: {e}"})

    try:
        assignments = build_assignments(school)
    except AssignmentError as e:
        return jsonify({"ok": False, "stage": "assignment", "message": str(e)})

    problems = preflight(school, assignments)
    if problems:
        return jsonify({"ok": False, "stage": "preflight", "problems": problems})

    result = solve(school, assignments, max_seconds, workers)
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        return jsonify({"ok": False, "stage": "infeasible",
                        "message": "No timetable satisfies all hard constraints. "
                                   "Loosen a limit (teacher availability, room "
                                   "count, lessons/day) and try again."})

    violations = validate(school, result.lessons)
    lessons = [vars(L) for L in result.lessons]

    return jsonify({
        "ok": True,
        "status": result.status,
        "objective": result.objective,
        "wall_time": result.wall_time,
        "violations": violations,
        "lessons": lessons,
        "quality": _quality(school, result.lessons),
    })


@app.post("/api/export/html")
def api_export_html():
    body = request.get_json(force=True)
    raw = body.get("school", {})
    lang = body.get("lang", "hy")
    lessons_raw = body.get("lessons", [])
    school = build_school(raw)
    from .solver import PlacedLesson
    lessons = [PlacedLesson(**L) for L in lessons_raw]
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        export_html(school, lessons, path, lang)
        with open(path, encoding="utf-8") as fh:
            return jsonify({"html": fh.read()})
    finally:
        os.unlink(path)


def _quality(school, lessons):
    from collections import defaultdict
    by_td = defaultdict(list)        # (teacher, day) -> [periods]
    class_daily = defaultdict(lambda: [0] * school.n_days)
    afternoon_hard = 0
    for L in lessons:
        by_td[(L.teacher_id, L.day)].append(L.period)
        class_daily[L.class_id][L.day] += 1
        subj = school.subjects[L.subject_id]
        if subj.difficulty >= C.HARD_THRESHOLD and L.period > C.MORNING_LAST_PERIOD:
            afternoon_hard += 1
    gaps = 0
    for periods in by_td.values():
        if len(periods) > 1:
            gaps += (max(periods) - min(periods) + 1) - len(periods)
    return {
        "teacher_gaps": gaps,
        "afternoon_hard": afternoon_hard,
        "class_daily": {cid: days for cid, days in class_daily.items()},
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Timetable generator web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    print(f"\n  Դասացուցակ — open http://{args.host}:{args.port} in your browser\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
