"""
Independent validation of a finished timetable.

This deliberately does NOT trust the solver: give it any list of placed lessons
(including a hand-edited one) and it re-checks every hard rule from scratch,
returning a list of violations. Empty list == the schedule is legal.
"""
from __future__ import annotations

from collections import defaultdict

from .models import School
from .solver import PlacedLesson


def validate(school: School, lessons: list[PlacedLesson]) -> list[str]:
    v: list[str] = []
    L = lessons

    # ---- curriculum hours met exactly ------------------------------------
    got: dict[tuple, int] = defaultdict(int)
    for x in L:
        got[(x.class_id, x.subject_id)] += 1
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if got.get((cls.id, sid), 0) != hrs:
                v.append(f"CURRICULUM: {cls.id}/{sid} has {got.get((cls.id, sid), 0)} "
                         f"lessons, curriculum requires {hrs}.")
    # stray lessons not in the curriculum
    valid_pairs = {(c.id, s) for c in school.classes.values()
                   for s in c.weekly_hours}
    for (cid, sid), cnt in got.items():
        if (cid, sid) not in valid_pairs:
            v.append(f"CURRICULUM: {cid}/{sid} is scheduled but not in the curriculum.")

    # ---- class conflicts + daily/weekly load -----------------------------
    class_slot: dict[tuple, list] = defaultdict(list)
    class_day: dict[tuple, int] = defaultdict(int)
    class_week: dict[str, int] = defaultdict(int)
    for x in L:
        class_slot[(x.class_id, x.day, x.period)].append(x.subject_id)
        class_day[(x.class_id, x.day)] += 1
        class_week[x.class_id] += 1
    for (cid, d, p), subs in class_slot.items():
        if len(subs) > 1:
            v.append(f"CLASS CONFLICT: {cid} has {len(subs)} lessons at day {d} period {p}: {subs}.")
    for cls in school.classes.values():
        rule = school.grade_rules[cls.grade]
        for d in range(school.n_days):
            if class_day[(cls.id, d)] > rule.max_lessons_per_day:
                v.append(f"CLASS DAILY LOAD: {cls.id} has {class_day[(cls.id, d)]} lessons "
                         f"on {school.day_name(d, 'en')}, max {rule.max_lessons_per_day}.")
        if class_week[cls.id] > rule.max_weekly_load:
            v.append(f"CLASS WEEKLY LOAD: {cls.id} has {class_week[cls.id]} lessons/week, "
                     f"max {rule.max_weekly_load}.")

    # ---- teacher conflicts + load + availability -------------------------
    t_slot: dict[tuple, list] = defaultdict(list)
    t_week: dict[str, int] = defaultdict(int)
    for x in L:
        t_slot[(x.teacher_id, x.day, x.period)].append((x.class_id, x.subject_id))
        t_week[x.teacher_id] += 1
    for (tid, d, p), items in t_slot.items():
        if len(items) > 1:
            v.append(f"TEACHER CONFLICT: {school.teachers[tid].name} teaches "
                     f"{len(items)} classes at day {d} period {p}: {items}.")
        teacher = school.teachers[tid]
        if not teacher.can_work(d, p):
            v.append(f"AVAILABILITY: {teacher.name} scheduled at day {d} period {p} "
                     f"but is marked unavailable.")
    for tid, load in t_week.items():
        cap = school.teachers[tid].resolved_cap()
        if load > cap:
            v.append(f"TEACHER LOAD: {school.teachers[tid].name} has {load} h/week, cap {cap}.")

    # ---- room conflicts + room requirements ------------------------------
    r_slot: dict[tuple, list] = defaultdict(list)
    for x in L:
        r_slot[(x.room_id, x.day, x.period)].append((x.class_id, x.subject_id))
        subj = school.subjects[x.subject_id]
        room = school.rooms.get(x.room_id)
        if room is None:
            v.append(f"ROOM: {x.class_id}/{x.subject_id} uses unknown room '{x.room_id}'.")
            continue
        if subj.requires_room_type and room.type != subj.requires_room_type:
            v.append(f"ROOM REQUIREMENT: {x.class_id}/{x.subject_id} needs a "
                     f"'{subj.requires_room_type}' room but is in '{room.id}' ({room.type}).")
    for (rid, d, p), items in r_slot.items():
        if len(items) > 1:
            v.append(f"ROOM CONFLICT: room {rid} hosts {len(items)} lessons at "
                     f"day {d} period {p}: {items}.")

    # ---- reserved break kept empty ---------------------------------------
    if school.reserved_break_period is not None:
        for x in L:
            if x.period == school.reserved_break_period:
                v.append(f"BREAK: {x.class_id}/{x.subject_id} placed in the reserved "
                         f"break period {x.period}.")

    return v
