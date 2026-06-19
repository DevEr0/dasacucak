"""Turn teacher qualifications into concrete teaching assignments + preflight checks."""
from __future__ import annotations

from collections import defaultdict

from .models import School, TeachingAssignment


class AssignmentError(Exception):
    pass


def build_assignments(school: School) -> list[TeachingAssignment]:
    explicit = {(a.class_id, a.subject_id): a for a in school.assignments}
    result = list(explicit.values())

    load = {tid: 0 for tid in school.teachers}
    for a in result:
        load[a.teacher_id] += school.classes[a.class_id].weekly_hours.get(a.subject_id, 0)

    needs = []
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if hrs > 0 and (cls.id, sid) not in explicit:
                needs.append((hrs, cls.id, sid))
    needs.sort(reverse=True)

    for hrs, cid, sid in needs:
        candidates = [t for t in school.teachers.values()
                      if sid in t.qualified_subjects
                      and load[t.id] + hrs <= t.resolved_cap()]
        if not candidates:
            qualified = [t.id for t in school.teachers.values()
                         if sid in t.qualified_subjects]
            if not qualified:
                raise AssignmentError(
                    f"No teacher is qualified for subject '{sid}' (class {cid}).")
            raise AssignmentError(
                f"Every qualified teacher for '{sid}' would exceed the legal cap "
                f"if they took class {cid} ({hrs} h). Qualified: {qualified}.")
        already = [t for t in candidates
                   if any(a.subject_id == sid and a.teacher_id == t.id for a in result)]
        pool = already or candidates
        chosen = min(pool, key=lambda t: load[t.id])
        result.append(TeachingAssignment(cid, sid, chosen.id))
        load[chosen.id] += hrs

    return result


def preflight(school: School, assignments: list[TeachingAssignment]) -> list[str]:
    problems = []
    n_slots = school.n_days * school.periods_per_day

    for cls in school.classes.values():
        rule = school.grade_rules[cls.grade]
        total = cls.weekly_total
        if total > rule.max_weekly_load:
            problems.append(f"Class {cls.id}: curriculum {total} h/week exceeds grade "
                            f"{cls.grade} ceiling {rule.max_weekly_load} h.")
        capacity = rule.max_lessons_per_day * school.n_days
        if school.reserved_break_period is not None:
            capacity -= school.n_days
        if total > capacity:
            problems.append(f"Class {cls.id}: {total} lessons can't fit in "
                            f"{rule.max_lessons_per_day}/day × {school.n_days} days.")

    load = {tid: 0 for tid in school.teachers}
    for a in assignments:
        load[a.teacher_id] += school.classes[a.class_id].weekly_hours.get(a.subject_id, 0)
    for t in school.teachers.values():
        if load[t.id] > t.resolved_cap():
            problems.append(f"Teacher {t.name}: {load[t.id]} h > cap {t.resolved_cap()} h.")

    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if hrs <= 0:
                continue
            rt = school.subjects[sid].requires_room_type
            if rt and not school.rooms_of_type(rt):
                problems.append(f"Subject {sid} (class {cls.id}) needs a '{rt}' room; none exists.")

    type_demand = defaultdict(int)
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            rt = school.subjects[sid].requires_room_type
            if rt:
                type_demand[rt] += hrs
    for rt, demand in type_demand.items():
        cap = len(school.rooms_of_type(rt)) * n_slots
        if demand > cap:
            problems.append(f"'{rt}' rooms: demand {demand} > weekly capacity {cap}.")

    return problems
