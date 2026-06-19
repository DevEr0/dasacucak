"""
Command-line entry point.

Pipeline:  load -> auto-assign teachers -> preflight -> solve -> validate -> render.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .assigner import AssignmentError, build_assignments, preflight
from .loader import load_school
from .render import (quality_report, render_all_classes, render_all_teachers)
from .solver import solve
from .validator import validate


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Armenian school timetable generator (CP-SAT).")
    ap.add_argument("input", help="Path to the school JSON file.")
    ap.add_argument("--lang", choices=["hy", "en"], default="hy")
    ap.add_argument("--max-seconds", type=float, default=30.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out-dir", help="Write timetables/JSON to this directory.")
    ap.add_argument("--quiet", action="store_true",
                    help="Only print summary, not full timetables.")
    args = ap.parse_args(argv)

    school = load_school(args.input)

    # 1. Teacher assignment (uses explicit assignments + auto-fills the rest).
    try:
        assignments = build_assignments(school)
    except AssignmentError as e:
        print(f"REJECTED (assignment): {e}", file=sys.stderr)
        return 2

    # 2. Preflight feasibility — reject obviously impossible inputs early.
    problems = preflight(school, assignments)
    if problems:
        print("REJECTED — the input cannot produce a legal timetable:",
              file=sys.stderr)
        for p in problems:
            print(f"  • {p}", file=sys.stderr)
        return 2

    # 3. Solve.
    print(f"Solving {school.year}: {len(school.classes)} classes, "
          f"{len(school.teachers)} teachers, "
          f"{sum(c.weekly_total for c in school.classes.values())} weekly lessons …",
          file=sys.stderr)
    result = solve(school, assignments, args.max_seconds, args.workers)
    print(f"Status: {result.status}  "
          f"(objective={result.objective:.0f}, {result.wall_time:.2f}s)",
          file=sys.stderr)

    if result.status not in ("OPTIMAL", "FEASIBLE"):
        print("REJECTED — no timetable satisfies all hard constraints.",
              file=sys.stderr)
        print("Loosen a constraint (teacher availability, room count, "
              "max lessons/day) and retry.", file=sys.stderr)
        return 3

    # 4. Validate the produced schedule independently (defence in depth).
    violations = validate(school, result.lessons)
    if violations:
        print("REJECTED — produced schedule failed validation:", file=sys.stderr)
        for x in violations:
            print(f"  • {x}", file=sys.stderr)
        return 4

    # 5. Render.
    classes_txt = render_all_classes(school, result.lessons, args.lang)
    teachers_txt = render_all_teachers(school, result.lessons, args.lang)
    report_txt = quality_report(school, result.lessons, args.lang)

    if not args.quiet:
        print(classes_txt)
        print("\n" + "#" * 60 + "\n")
        print(teachers_txt)
        print()
    print(report_txt)

    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        _write(args.out_dir, "classes.txt", classes_txt)
        _write(args.out_dir, "teachers.txt", teachers_txt)
        _write(args.out_dir, "quality.txt", report_txt)
        _write(args.out_dir, "schedule.json",
               json.dumps([vars(L) for L in result.lessons],
                          ensure_ascii=False, indent=2))
        try:
            from .htmlexport import export_html
            export_html(school, result.lessons,
                        os.path.join(args.out_dir, "timetable.html"), args.lang)
        except Exception as e:  # HTML is a bonus; never fail the run for it
            print(f"(HTML export skipped: {e})", file=sys.stderr)
        print(f"\nFiles written to {args.out_dir}/", file=sys.stderr)

    return 0


def _write(d, name, content):
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        fh.write(content)


if __name__ == "__main__":
    raise SystemExit(main())
