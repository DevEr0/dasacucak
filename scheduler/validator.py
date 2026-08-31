"""
Independent validation of a finished timetable.

Deliberately does NOT trust the solver: give it any list of placed lessons
(including a hand-edited one) and it re-checks every rule from scratch.

Returns a dict:
  {"hard":  [str, ...],      # physical impossibilities — never acceptable
   "legal": [{"rule", "message", "law"}, ...]}   # regulatory deviations —
                                # reject in strict mode, report in relaxed.
"""
from __future__ import annotations

from collections import defaultdict

from . import curriculum as C
from .assigner import build_units
from .models import School, elective_scope_id
from .solver import PlacedLesson


def _legal(rule: str, message: str, law: str = "") -> dict:
    law = law or C.RELAXABLE_RULES.get(rule, {}).get("law", "")
    return {"rule": rule, "message": message, "law": law}


def _lkey(L: PlacedLesson):
    if L.kind == "elective":
        return ("E", L.group_id, L.subject_id)
    if L.kind == "split" or L.subgroup:
        return ("S", L.class_id, L.subject_id, L.subgroup)
    return ("C", L.class_id, L.subject_id)


def validate(school: School, lessons: list[PlacedLesson]) -> dict:
    hard: list[str] = []
    legal: list[dict] = []
    L = lessons
    units = build_units(school)
    ukey = {}
    for u in units:
        if u.kind == "elective":
            ukey[("E", u.group_id, u.subject_id)] = u
        elif u.kind == "split":
            ukey[("S", u.class_id, u.subject_id, u.subgroup)] = u
        else:
            ukey[("C", u.class_id, u.subject_id)] = u

    # ---- curriculum hours met exactly, no stray lessons -------------------
    got = defaultdict(int)
    for x in L:
        got[_lkey(x)] += 1
    for key, u in ukey.items():
        if got.get(key, 0) != u.hours:
            hard.append(f"CURRICULUM: {u.label()} has {got.get(key, 0)} lessons, "
                        f"requires {u.hours}.")
    for key, cnt in got.items():
        if key not in ukey:
            hard.append(f"CURRICULUM: {key} is scheduled but not in the "
                        f"curriculum / elective plan.")

    groups = school.elective_groups

    # ---- per-student occupancy: whole ∪ subgroup ∪ elective bands ----------
    # For class c and subgroup g, a student sits in: whole-class lessons,
    # subgroup-g lessons, and (per band) at most one parallel elective slot.
    slot_whole = defaultdict(list)          # (cid,d,p) -> lessons
    slot_split = defaultdict(list)          # (cid,g,d,p)
    slot_band = defaultdict(set)            # (cid,band,d,p) -> {group ids}
    teach_slot = defaultdict(list)
    room_slot = defaultdict(list)
    group_slot = defaultdict(list)

    for x in L:
        teach_slot[(x.teacher_id, x.day, x.period)].append(x)
        room_slot[(x.room_id, x.day, x.period)].append(x)
        if x.kind == "elective":
            grp = groups.get(x.group_id)
            if grp is None:
                hard.append(f"ELECTIVE: unknown group '{x.group_id}'.")
                continue
            group_slot[(x.group_id, x.day, x.period)].append(x)
            for cid in grp.member_classes:
                slot_band[(cid, grp.band, x.day, x.period)].add(x.group_id)
        elif x.subgroup:
            slot_split[(x.class_id, x.subgroup, x.day, x.period)].append(x)
        else:
            slot_whole[(x.class_id, x.day, x.period)].append(x)

    for (gid, d, p), xs in group_slot.items():
        if len(xs) > 1:
            hard.append(f"ELECTIVE CONFLICT: group {gid} has {len(xs)} lessons "
                        f"at day {d} period {p}.")

    split_classes = {c.id for c in school.classes.values()
                     if c.split_subject_ids(school.subjects)}
    day_load = defaultdict(int)             # (cid, g, d)
    for cls in school.classes.values():
        gs = (1, 2) if cls.id in split_classes else (1,)
        bands = school.bands_of_class(cls.id)
        for d in range(school.n_days):
            for p in range(1, school.periods_per_day + 1):
                for g in gs:
                    n = len(slot_whole.get((cls.id, d, p), []))
                    n += len(slot_split.get((cls.id, g, d, p), []))
                    n += sum(1 for b in bands
                             if slot_band.get((cls.id, b, d, p)))
                    if n > 1:
                        hard.append(f"CLASS CONFLICT: {cls.id} (subgroup {g}) "
                                    f"has {n} simultaneous lessons at day {d} "
                                    f"period {p} (regular/subgroup/elective overlap).")
                    if n:
                        day_load[(cls.id, g, d)] += 1

    # ---- band sync ------------------------------------------------------------
    band_groups = defaultdict(set)
    for grp in groups.values():
        band_groups[grp.band].add(grp.id)
    gslot_count = defaultdict(int)
    for (gid, d, p), xs in group_slot.items():
        gslot_count[(gid, d, p)] = len(xs)
    for band, gids in band_groups.items():
        if len(gids) < 2:
            continue
        for d in range(school.n_days):
            for p in range(1, school.periods_per_day + 1):
                active = {gid for gid in gids if gslot_count.get((gid, d, p))}
                if active and active != gids:
                    idle = ", ".join(sorted(gids - active))
                    legal.append(_legal(
                        "band_sync",
                        f"Band '{band}': at day {d} period {p} only "
                        f"{', '.join(sorted(active))} meets; students of "
                        f"{idle} are left idle."))

    # ---- split pairing ------------------------------------------------------
    for cid in split_classes:
        for d in range(school.n_days):
            for p in range(1, school.periods_per_day + 1):
                n1 = len(slot_split.get((cid, 1, d, p), []))
                n2 = len(slot_split.get((cid, 2, d, p), []))
                if n1 != n2:
                    legal.append(_legal(
                        "split_pairing",
                        f"{cid}: subgroups unpaired at day {d} period {p} "
                        f"(one half has a lesson, the other is idle)."))

    # ---- student daily / weekly caps ---------------------------------------
    for cls in school.classes.values():
        rule = school.grade_rules[cls.grade]
        gs = (1, 2) if cls.id in split_classes else (1,)
        for g in gs:
            week = 0
            for d in range(school.n_days):
                n = day_load.get((cls.id, g, d), 0)
                week += n
                if n > rule.max_lessons_per_day:
                    legal.append(_legal(
                        "student_daily_cap",
                        f"{cls.id}: {n} lessons on {school.day_name(d, 'en')}, "
                        f"max {rule.max_lessons_per_day} for grade {cls.grade}."))
            if week > rule.max_weekly_load:
                legal.append(_legal(
                    "student_weekly_cap",
                    f"{cls.id}: {week} lessons/week, "
                    f"max {rule.max_weekly_load} for grade {cls.grade}."))

    # ---- subject per-day / consecutive limits -------------------------------
    per_day = defaultdict(list)
    for x in L:
        per_day[(_lkey(x), x.day)].append(x.period)
    for (key, d), ps in per_day.items():
        u = ukey.get(key)
        if u is None:
            continue
        subj = school.subjects[u.subject_id]
        if len(ps) > subj.max_per_day:
            legal.append(_legal(
                "subject_daily_rules",
                f"{u.label()}: {len(ps)} lessons on day {d}, "
                f"max {subj.max_per_day}/day."))
        ps = sorted(ps)
        run = 1
        for a, b in zip(ps, ps[1:]):
            run = run + 1 if b == a + 1 else 1
            if run > subj.max_consecutive:
                legal.append(_legal(
                    "subject_daily_rules",
                    f"{u.label()}: more than {subj.max_consecutive} "
                    f"consecutive lessons on day {d}."))
                break

    # ---- teacher conflicts, availability, load -------------------------------
    t_week = defaultdict(int)
    for (tid, d, p), xs in teach_slot.items():
        t_week[tid] += 1 if xs else 0
        t_week[tid] += len(xs) - 1          # count every lesson
        if len(xs) > 1:
            hard.append(f"TEACHER CONFLICT: {school.teachers[tid].name} teaches "
                        f"{len(xs)} lessons at day {d} period {p}.")
        if not school.teachers[tid].can_work(d, p):
            legal.append(_legal(
                "teacher_availability",
                f"{school.teachers[tid].name} scheduled at day {d} period {p} "
                f"but is marked unavailable."))
    for tid, load in t_week.items():
        t = school.teachers[tid]
        cap = t.resolved_cap()
        if load > cap:
            legal.append(_legal(
                "teacher_weekly_cap",
                f"{t.name}: {load} h/week, cap {cap} h."))
        if load > C.LEGAL_TEACHER_MAX:
            legal.append(_legal(
                "teacher_weekly_cap",
                f"{t.name}: {load} h/week exceeds the legal maximum "
                f"{C.LEGAL_TEACHER_MAX} h.", "HO-160-N Art. 25(3)"))

    # ---- teacher qualified classes (per subject) ---------------------------
    for x in L:
        t = school.teachers.get(x.teacher_id)
        if t is None:
            hard.append(f"TEACHER: unknown teacher '{x.teacher_id}' assigned to "
                        f"{x.class_id or x.group_id}/{x.subject_id}.")
            continue
        # a stream/elective lecture is shared by ALL its member classes at
        # once, so the teacher must be qualified for the stream in EVERY one
        # of them (one composite scope per member class); a whole-class/split
        # lesson just checks the class id.
        if x.kind == "elective":
            grp = groups.get(x.group_id)
            member_classes = grp.member_classes if grp else []
            scope_ids = [elective_scope_id(x.group_id, cid) for cid in member_classes]
        else:
            scope_ids = [x.class_id]
        bad = [c for c in scope_ids if not t.can_teach(x.subject_id, c)]
        if bad:
            if x.subject_id not in t.qualified_subjects:
                hard.append(f"QUALIFICATION: {t.name} is not qualified to teach "
                            f"'{x.subject_id}' at all — assigned to "
                            f"{', '.join(bad)} at day {x.day} period {x.period}.")
            else:
                allowed = t.qualified_classes_by_subject.get(x.subject_id)
                hard.append(f"QUALIFICATION: {t.name} is qualified for "
                            f"'{x.subject_id}' only in {', '.join(allowed)} — "
                            f"not covering {', '.join(bad)} at day {x.day} "
                            f"period {x.period}.")

    # ---- rooms ----------------------------------------------------------------
    for x in L:
        subj = school.subjects.get(x.subject_id)
        room = school.rooms.get(x.room_id)
        if room is None:
            hard.append(f"ROOM: {x.class_id or x.group_id}/{x.subject_id} uses "
                        f"unknown room '{x.room_id}'.")
            continue
        if subj and subj.requires_room_type and room.type != subj.requires_room_type:
            hard.append(f"ROOM REQUIREMENT: {x.class_id or x.group_id}/"
                        f"{x.subject_id} needs '{subj.requires_room_type}' "
                        f"but is in '{room.id}' ({room.type}).")
    for (rid, d, p), xs in room_slot.items():
        if len(xs) > 1:
            hard.append(f"ROOM CONFLICT: room {rid} hosts {len(xs)} lessons at "
                        f"day {d} period {p}.")

    # ---- reserved break --------------------------------------------------------
    if school.reserved_break_period is not None:
        for x in L:
            if x.period == school.reserved_break_period:
                hard.append(f"BREAK: {x.class_id or x.group_id}/{x.subject_id} "
                            f"placed in the reserved break period {x.period}.")

    return {"hard": hard, "legal": legal}


def is_acceptable(school: School, report: dict) -> bool:
    """Hard violations are never OK.  Legal deviations are OK only if the
    corresponding rule was relaxed by the chosen compliance mode."""
    if report["hard"]:
        return False
    return all(school.compliance.is_relaxed(v["rule"]) for v in report["legal"])
