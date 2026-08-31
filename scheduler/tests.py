"""
Smoke tests: solve the sample school (splits + streams included), confirm it
is legal, confirm the validator rejects tampered schedules, and exercise the
relaxed compliance mode and the infeasibility diagnoser. Run with:

    python3 -m scheduler.tests
"""
from __future__ import annotations

import copy

from .loader import build_school, load_school
from .assigner import AssignmentError, assign_teachers, build_units, preflight
from .solver import PlacedLesson, diagnose, solve
from .validator import is_acceptable, validate


def _solve(school, max_seconds=40):
    units = build_units(school)
    teacher_of, warns = assign_teachers(
        school, units,
        allow_overload=school.compliance.is_relaxed("teacher_weekly_cap"))
    fatal, _legal = preflight(school, units, teacher_of)
    assert not fatal, f"preflight fatal: {fatal[:3]}"
    return units, teacher_of, warns, solve(school, units, teacher_of,
                                           max_seconds=max_seconds, workers=8)


def main() -> int:
    school = load_school("data/sample_school.json")
    units, teacher_of, _w, res = _solve(school)
    assert res.lessons, f"solver returned no lessons (status={res.status})"
    print(f"[ok] solved: {res.status}, {len(res.lessons)} lessons")

    # 1. clean schedule is fully legal (strict mode sample)
    clean = validate(school, res.lessons)
    assert clean["hard"] == [], f"hard violations: {clean['hard'][:3]}"
    assert clean["legal"] == [], f"legal violations: {clean['legal'][:3]}"
    assert is_acceptable(school, clean)
    print("[ok] clean schedule passes validation")

    # 2. split subgroups exist, are paired, and use two different teachers
    splits = [L for L in res.lessons if L.kind == "split"]
    assert splits, "sample should produce split lessons for 7Ա"
    slots1 = {(L.day, L.period) for L in splits if L.subgroup == 1}
    slots2 = {(L.day, L.period) for L in splits if L.subgroup == 2}
    assert slots1 == slots2, "subgroup slots are not paired"
    eng = {L.subgroup: L.teacher_id for L in splits if L.subject_id == "anglerent"}
    assert eng.get(1) != eng.get(2), "both English subgroups share one teacher"
    print(f"[ok] {len(splits)} split lessons, paired, separate teachers")

    # 3. stream (elective) lessons run in synchronised parallel bands
    el = [L for L in res.lessons if L.kind == "elective"]
    assert el, "sample should produce stream lessons"
    by_slot = {}
    for L in el:
        by_slot.setdefault((L.day, L.period), set()).add(L.group_id)
    assert all(gs == {"g10_sci", "g10_hum"} for gs in by_slot.values()), \
        "stream groups not synchronised"
    # stream subject is separate from the class's own lessons in that subject
    own_alg = [L for L in res.lessons
               if L.kind == "class" and L.class_id == "10Ա"
               and L.subject_id == "hanrahashiv"]
    assert len(own_alg) == 2, "class' own algebra hours were displaced"
    print(f"[ok] {len(el)} stream lessons in {len(by_slot)} synced band slots")

    # 4. a duplicated lesson is caught
    f = next(L for L in res.lessons if L.kind == "class")
    dup = res.lessons + [PlacedLesson(f.class_id, f.subject_id, f.teacher_id,
                                      f.day, f.period, f.room_id)]
    assert validate(school, dup)["hard"], "validator missed a duplicated lesson"
    print("[ok] duplicated lesson rejected")

    # 5. a missing lesson (curriculum shortfall) is caught
    short = res.lessons[1:]
    assert any("CURRICULUM" in v for v in validate(school, short)["hard"]), \
        "validator missed a curriculum shortfall"
    print("[ok] curriculum shortfall rejected")

    # 6. relaxed mode: shrink a teacher's availability so strict is impossible,
    #    then confirm relaxed mode still produces a (reported) schedule
    broken = copy.deepcopy(school)
    pe = broken.teachers["pe1"]
    pe.available_periods_by_day = {d: [1, 2] for d in range(5)}  # 10 slots < load
    b_units = build_units(broken)
    b_tof, _ = assign_teachers(broken, b_units)
    fatal, _ = preflight(broken, b_units, b_tof)
    assert fatal, "preflight should flag the availability shortfall"
    broken.compliance.mode = "relaxed"
    b_res = solve(broken, b_units, b_tof, max_seconds=40, workers=8)
    assert b_res.status in ("OPTIMAL", "FEASIBLE"), b_res.status
    rep = validate(broken, b_res.lessons)
    assert rep["hard"] == []
    assert any(v["rule"] == "teacher_availability" for v in rep["legal"])
    assert is_acceptable(broken, rep)
    print(f"[ok] relaxed mode: emergency schedule with "
          f"{len(rep['legal'])} reported deviations")

    # 7. diagnosis names the true culprits on an impossible input
    raw = {
        "year": "diag", "periods_per_day": 7,
        "subjects": {"math": {"name_hy": "Մաթ"}, "arm": {"name_hy": "Հայոց"}},
        "rooms": {"r1": {"name": "201", "type": "classroom"}},
        "classes": {"A": {"grade": 7, "home_room": "r1",
                          "weekly_hours": {"math": 5, "arm": 5}}},
        "teachers": {
            "t1": {"name": "T1", "qualified_subjects": ["math"],
                   "available_periods_by_day": {str(d): [1] for d in range(5)}},
            "t2": {"name": "T2", "qualified_subjects": ["arm"],
                   "available_periods_by_day": {str(d): [1] for d in range(5)}},
        },
    }
    ds = build_school(raw)
    d_units = build_units(ds)
    d_tof, _ = assign_teachers(ds, d_units)
    diag = diagnose(ds, d_units, d_tof, max_seconds=20)
    rules = {d["rule"] for d in diag}
    assert "teacher_availability" in rules, f"diagnosis missed cause: {diag}"
    print(f"[ok] diagnosis: {len(diag)} minimal conflict items")

    # 8. qualified_classes restricts which classes a teacher may be assigned
    raw2 = {
        "year": "qc", "periods_per_day": 6,
        "subjects": {"math": {"name_hy": "Մաթ"}},
        "rooms": {"r1": {"name": "101", "type": "classroom"},
                 "r2": {"name": "102", "type": "classroom"}},
        "classes": {
            "A": {"grade": 5, "home_room": "r1", "weekly_hours": {"math": 3}},
            "B": {"grade": 5, "home_room": "r2", "weekly_hours": {"math": 3}},
        },
        "teachers": {
            "t1": {"name": "T1", "qualified_subjects": ["math"], "qualified_classes": ["A"]},
        },
    }
    qs = build_school(raw2)
    qc_units = build_units(qs)
    try:
        assign_teachers(qs, qc_units)
        assert False, "expected AssignmentError: t1 is not qualified for class B"
    except AssignmentError as e:
        assert "B" in str(e)
    print("[ok] qualified_classes blocks an out-of-scope auto-assignment")

    # adding a second, unrestricted teacher fixes it
    raw2["teachers"]["t2"] = {"name": "T2", "qualified_subjects": ["math"]}
    qs2 = build_school(raw2)
    qc_units2 = build_units(qs2)
    tof2, _ = assign_teachers(qs2, qc_units2)
    assert tof2["C:A:math"] == "t1"
    assert tof2["C:B:math"] == "t2"
    print("[ok] qualified_classes: auto-assignment routes B to the unrestricted teacher")

    # validator independently rejects a hand-edited swap that breaks it
    res2 = solve(qs2, qc_units2, tof2, max_seconds=10, workers=4)
    assert res2.lessons, "qualified_classes sample should solve"
    tampered = [PlacedLesson("B", L.subject_id, "t1", L.day, L.period, L.room_id)
               if L.class_id == "B" else L for L in res2.lessons]
    rep2 = validate(qs2, tampered)
    assert any("QUALIFICATION" in v for v in rep2["hard"]), \
        "validator missed a teacher assigned outside their qualified classes"
    print("[ok] validator rejects a teacher placed outside their qualified classes")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
