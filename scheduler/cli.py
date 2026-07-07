"""
Command-line entry point.

Pipeline:  load -> auto-assign teachers -> preflight -> solve -> validate -> render.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .assigner import (AssignmentError, assign_teachers, build_units,
                       preflight)
from .loader import load_school
from .render import (quality_report, render_all_classes, render_all_teachers)
from .solver import diagnose, solve
from .validator import is_acceptable, validate


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
    ap.add_argument("--mode", choices=["strict", "relaxed", "custom"],
                    help="Override compliance mode from the JSON.")
    ap.add_argument("--relax", default="",
                    help="Comma-separated rule ids to relax (implies --mode custom).")
    args = ap.parse_args(argv)

    school = load_school(args.input)
    if args.relax:
        school.compliance.mode = "custom"
        school.compliance.relax |= set(args.relax.split(","))
    if args.mode:
        school.compliance.mode = args.mode

    # 1. Units + teacher assignment.
    units = build_units(school)
    try:
        teacher_of, assign_warnings = assign_teachers(
            school, units,
            allow_overload=school.compliance.is_relaxed("teacher_weekly_cap"))
    except AssignmentError as e:
        print(f"REJECTED (assignment): {e}", file=sys.stderr)
        return 2
    for w in assign_warnings:
        print(f"WARNING ({w['rule']}): {w['message']}  [{w['law']}]",
              file=sys.stderr)

    # 2. Preflight feasibility — reject obviously impossible inputs early.
    fatal, legal_pre = preflight(school, units, teacher_of)
    if fatal:
        print("REJECTED — the input cannot produce a timetable:",
              file=sys.stderr)
        for p in fatal:
            print(f"  • {p}", file=sys.stderr)
        return 2
    for w in legal_pre:
        print(f"WARNING ({w['rule']}): {w['message']}", file=sys.stderr)

    # 3. Solve.
    print(f"Solving {school.year}: {len(school.classes)} classes, "
          f"{len(school.teachers)} teachers, "
          f"{sum(c.weekly_total for c in school.classes.values())} weekly lessons …",
          file=sys.stderr)
    result = solve(school, units, teacher_of, args.max_seconds, args.workers)
    print(f"Status: {result.status}  "
          f"(objective={result.objective:.0f}, {result.wall_time:.2f}s)",
          file=sys.stderr)

    if result.status not in ("OPTIMAL", "FEASIBLE"):
        print("REJECTED — no timetable satisfies every enforced rule.",
              file=sys.stderr)
        if result.status == "INFEASIBLE":
            print("Why (a minimal conflicting set of rules):", file=sys.stderr)
            for d in diagnose(school, units, teacher_of,
                              max_seconds=min(args.max_seconds, 25)):
                print(f"  • {d['message']}", file=sys.stderr)
            print("Fix any item above, or relax it via --mode relaxed / "
                  "--relax <rule>.", file=sys.stderr)
        else:
            print("Solver timed out; raise --max-seconds and retry.",
                  file=sys.stderr)
        return 3

    # 4. Validate the produced schedule independently (defence in depth).
    report = validate(school, result.lessons)
    if report["hard"] or not is_acceptable(school, report):
        print("REJECTED — produced schedule failed validation:", file=sys.stderr)
        for x in report["hard"]:
            print(f"  • {x}", file=sys.stderr)
        for v in report["legal"]:
            print(f"  • {v['message']}", file=sys.stderr)
        return 4
    if report["legal"]:
        print("EMERGENCY SCHEDULE — deviations from the regulations "
              "(allowed by the chosen compliance mode):", file=sys.stderr)
        for v in report["legal"]:
            print(f"  • {v['message']}  [{v['law']}]", file=sys.stderr)

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
