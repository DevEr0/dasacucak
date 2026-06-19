"""
Smoke test: solve the sample school, confirm it is legal, and confirm the
validator actually *rejects* a tampered schedule. Run with:

    python3 -m scheduler.tests
"""
from __future__ import annotations

from .loader import load_school
from .assigner import build_assignments, preflight
from .solver import solve, PlacedLesson
from .validator import validate


def main() -> int:
    school = load_school("data/sample_school.json")
    assignments = build_assignments(school)
    preflight(school, assignments)
    res = solve(school, assignments, max_seconds=20, workers=8)
    assert res.lessons, f"solver returned no lessons (status={res.status})"
    print(f"[ok] solved: {res.status}, {len(res.lessons)} lessons")

    # 1. clean schedule is legal
    clean = validate(school, res.lessons)
    assert clean == [], f"clean schedule unexpectedly invalid: {clean[:3]}"
    print("[ok] clean schedule passes validation")

    # 2. a duplicated lesson is caught
    f = res.lessons[0]
    dup = res.lessons + [PlacedLesson(f.class_id, f.subject_id, f.teacher_id,
                                      f.day, f.period, f.room_id)]
    assert validate(school, dup), "validator missed a duplicated lesson"
    print("[ok] duplicated lesson rejected")

    # 3. a missing lesson (curriculum shortfall) is caught
    short = res.lessons[1:]
    assert any("CURRICULUM" in v for v in validate(school, short)), \
        "validator missed a curriculum shortfall"
    print("[ok] curriculum shortfall rejected")

    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
