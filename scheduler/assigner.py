"""Build lesson units (whole-class / subgroup / elective), assign teachers to
them, and preflight-check structural feasibility before the solver runs."""
from __future__ import annotations

from collections import defaultdict

from . import curriculum as C
from .models import School, Unit


class AssignmentError(Exception):
    pass


def _unit_classes(u: Unit) -> tuple:
    """The class id(s) a unit's students belong to (elective groups draw from
    several classes at once)."""
    if u.kind == "elective":
        return u.member_classes
    return (u.class_id,)


# --------------------------------------------------------------------------
# 1. Units
# --------------------------------------------------------------------------
def build_units(school: School) -> list[Unit]:
    """Everything that must be placed on the grid, exactly once per kind."""
    units: list[Unit] = []
    for cls in school.classes.values():
        split_ids = cls.split_subject_ids(school.subjects)
        for sid, hrs in cls.weekly_hours.items():
            if hrs <= 0:
                continue
            if sid in split_ids:
                for g in (1, 2):
                    units.append(Unit(uid=f"S:{cls.id}:{sid}:{g}", kind="split",
                                      subject_id=sid, hours=hrs,
                                      class_id=cls.id, subgroup=g))
            else:
                units.append(Unit(uid=f"C:{cls.id}:{sid}", kind="class",
                                  subject_id=sid, hours=hrs, class_id=cls.id))
    for grp in school.elective_groups.values():
        for sid, hrs in grp.weekly_hours.items():
            if hrs <= 0:
                continue
            units.append(Unit(uid=f"E:{grp.id}:{sid}", kind="elective",
                              subject_id=sid, hours=hrs, group_id=grp.id,
                              member_classes=tuple(grp.member_classes),
                              band=grp.band))
    return units


# --------------------------------------------------------------------------
# 2. Teacher assignment
# --------------------------------------------------------------------------
def assign_teachers(school: School, units: list[Unit],
                    allow_overload: bool = False):
    """Return (teacher_of: uid -> teacher_id, warnings: list[dict]).

    Explicit `assignments` from the input are honoured first; the rest is
    filled greedily (hardest/longest first, consolidating a class's subject
    under one teacher, diversifying the two subgroups of a split subject so
    they *can* run in parallel).

    allow_overload=True (relaxed compliance): a teacher over their cap is a
    reported warning instead of a fatal error — for emergency scheduling.
    """
    explicit = {}
    for a in school.assignments:
        if a.group_id:
            explicit[f"E:{a.group_id}:{a.subject_id}"] = a.teacher_id
        elif a.subgroup:
            explicit[f"S:{a.class_id}:{a.subject_id}:{a.subgroup}"] = a.teacher_id
        else:
            explicit[f"C:{a.class_id}:{a.subject_id}"] = a.teacher_id
            # an old-style pin on a now-split subject pins subgroup 1
            explicit.setdefault(f"S:{a.class_id}:{a.subject_id}:1", a.teacher_id)

    teacher_of: dict[str, str] = {}
    load = {tid: 0 for tid in school.teachers}
    warnings: list[dict] = []
    by_uid = {u.uid: u for u in units}

    for uid, tid in explicit.items():
        u = by_uid.get(uid)
        if u is None:
            continue
        if tid not in school.teachers:
            raise AssignmentError(f"Pinned teacher '{tid}' ({uid}) does not exist.")
        teacher_of[uid] = tid
        load[tid] += u.hours

    todo = [u for u in units if u.uid not in teacher_of]
    todo.sort(key=lambda u: (-u.hours,
                             -school.subjects[u.subject_id].difficulty,
                             u.uid))

    for u in todo:
        sid = u.subject_id
        unit_classes = _unit_classes(u)
        subject_qualified = [t for t in school.teachers.values()
                             if sid in t.qualified_subjects]
        if not subject_qualified:
            raise AssignmentError(
                f"No teacher is qualified for subject '{sid}' ({u.label()}).")
        qualified = [t for t in subject_qualified
                    if all(t.can_teach(sid, cid) for cid in unit_classes)]
        if not qualified:
            raise AssignmentError(
                f"No teacher qualified for '{sid}' is allowed to teach it to "
                f"{', '.join(unit_classes)} ({u.label()}). Qualified for the "
                f"subject: {[t.id for t in subject_qualified]}. Widen one of "
                f"their allowed classes for '{sid}', or add another qualified "
                f"teacher.")
        fits = [t for t in qualified if load[t.id] + u.hours <= t.resolved_cap()]
        if not fits and not allow_overload:
            raise AssignmentError(
                f"Every qualified teacher for '{sid}' would exceed their weekly "
                f"cap if they took {u.label()} ({u.hours} h). "
                f"Qualified: {[t.id for t in qualified]}. "
                f"Add a teacher, raise a cap, or switch compliance to relaxed.")
        pool = fits or qualified

        # split subgroup 2: prefer a DIFFERENT teacher than subgroup 1,
        # so both halves can take the same subject at the same time.
        if u.kind == "split" and u.subgroup == 2:
            other = teacher_of.get(f"S:{u.class_id}:{sid}:1")
            diverse = [t for t in pool if t.id != other]
            if diverse:
                pool = diverse
        else:
            # consolidate: keep a subject with a teacher who already teaches it
            already = [t for t in pool if any(
                by_uid[x].subject_id == sid for x, tt in teacher_of.items()
                if tt == t.id)]
            if already:
                pool = already

        chosen = min(pool, key=lambda t: load[t.id])
        teacher_of[u.uid] = chosen.id
        load[chosen.id] += u.hours

    for t in school.teachers.values():
        cap = t.resolved_cap()
        if load[t.id] > cap:
            warnings.append({
                "rule": "teacher_weekly_cap",
                "message": f"{t.name}: assigned {load[t.id]} h/week, cap {cap} h.",
                "law": C.RELAXABLE_RULES["teacher_weekly_cap"]["law"],
            })
        if load[t.id] > C.LEGAL_TEACHER_MAX:
            warnings.append({
                "rule": "teacher_weekly_cap",
                "message": (f"{t.name}: {load[t.id]} h/week exceeds the legal "
                            f"maximum of {C.LEGAL_TEACHER_MAX} h."),
                "law": "HO-160-N Art. 25(3)",
            })
    return teacher_of, warnings


# --------------------------------------------------------------------------
# 3. Preflight
# --------------------------------------------------------------------------
def _class_week_load(school: School, cid: str, subgroup: int) -> int:
    """Weekly lessons a student of `cid` (in the given subgroup) sits through:
    whole-class + their subgroup's split lessons + one group per band."""
    cls = school.classes[cid]
    split_ids = cls.split_subject_ids(school.subjects)
    base = sum(h for s, h in cls.weekly_hours.items())
    # split subjects count once for the student (their own subgroup)
    # base already counts them once, so nothing extra
    band_hours = defaultdict(int)
    for g in school.groups_of_class(cid):
        band_hours[g.band] = max(band_hours[g.band], g.weekly_total)
    return base + sum(band_hours.values())


def preflight(school: School, units: list[Unit], teacher_of: dict):
    """Return (fatal, legal).  `fatal` – structurally impossible regardless of
    compliance mode; `legal` – regulatory-cap breaches (fatal only in strict
    mode; reported as deviations in relaxed mode)."""
    fatal: list[str] = []
    legal: list[dict] = []
    n_slots = school.n_days * school.periods_per_day
    if school.reserved_break_period is not None:
        n_slots -= school.n_days
    relaxed = school.compliance.is_relaxed

    # elective sanity ------------------------------------------------------
    for grp in school.elective_groups.values():
        if not grp.member_classes:
            fatal.append(f"Elective group {grp.name}: no member classes "
                         f"(or none that exist).")
        if not grp.weekly_hours:
            fatal.append(f"Elective group {grp.name}: no weekly hours set.")
    by_band = defaultdict(list)
    for grp in school.elective_groups.values():
        by_band[grp.band].append(grp)
    for band, grps in by_band.items():
        totals = {g.weekly_total for g in grps}
        if len(totals) > 1:
            legal.append({
                "rule": "student_weekly_cap",
                "message": (f"Band '{band}': groups have different weekly totals "
                            f"{sorted(totals)} — students in smaller groups will "
                            f"have free slots while others study."),
                "law": "Consistency warning",
            })

    # student load ---------------------------------------------------------
    for cls in school.classes.values():
        rule = school.grade_rules[cls.grade]
        week = _class_week_load(school, cls.id, 1)
        if week > rule.max_weekly_load:
            item = {
                "rule": "student_weekly_cap",
                "message": (f"Class {cls.id}: {week} lessons/week (incl. electives) "
                            f"exceeds the grade-{cls.grade} ceiling "
                            f"{rule.max_weekly_load}."),
                "law": C.RELAXABLE_RULES["student_weekly_cap"]["law"],
            }
            (legal if relaxed("student_weekly_cap") else fatal).append(
                item if relaxed("student_weekly_cap") else item["message"])
        cap_slots = min(rule.max_lessons_per_day * school.n_days, n_slots) \
            if not relaxed("student_daily_cap") else n_slots
        if week > cap_slots:
            fatal.append(f"Class {cls.id}: {week} weekly lessons physically can't "
                         f"fit in {cap_slots} available slots.")

    # teacher qualified_classes_by_subject sanity ---------------------------
    for t in school.teachers.values():
        for sid, cls_list in t.qualified_classes_by_subject.items():
            unknown = [c for c in cls_list if c not in school.classes]
            if unknown:
                fatal.append(f"Teacher {t.name}: qualified_classes_by_subject "
                             f"for '{sid}' references unknown class(es) "
                             f"{', '.join(unknown)}.")

    # teacher load ---------------------------------------------------------
    load = defaultdict(int)
    by_uid = {u.uid: u for u in units}
    for uid, tid in teacher_of.items():
        load[tid] += by_uid[uid].hours
    for t in school.teachers.values():
        if load[t.id] > n_slots:
            fatal.append(f"Teacher {t.name}: {load[t.id]} h/week can't fit in "
                         f"{n_slots} slots.")
        free = sum(1 for d in range(school.n_days)
                   for p in range(1, school.periods_per_day + 1)
                   if t.can_work(d, p)
                   and p != school.reserved_break_period)
        if load[t.id] > free and not relaxed("teacher_availability"):
            fatal.append(f"Teacher {t.name}: {load[t.id]} h/week assigned, but "
                         f"only available for {free} slots. Widen availability "
                         f"or reassign lessons.")

    # rooms ----------------------------------------------------------------
    for u in units:
        rt = school.subjects[u.subject_id].requires_room_type
        if rt and not school.rooms_of_type(rt):
            fatal.append(f"{u.label()} needs a '{rt}' room; none exists.")
    type_demand = defaultdict(int)
    generic_demand = 0
    for u in units:
        rt = school.subjects[u.subject_id].requires_room_type
        if rt:
            type_demand[rt] += u.hours
        else:
            generic_demand += u.hours
    for rt, demand in type_demand.items():
        cap = len(school.rooms_of_type(rt)) * n_slots
        if demand > cap:
            fatal.append(f"'{rt}' rooms: weekly demand {demand} > capacity {cap}. "
                         f"Add such a room or reduce hours.")
    n_classrooms = len(school.rooms_of_type("classroom"))
    if generic_demand > n_classrooms * n_slots:
        fatal.append(f"Ordinary classrooms: weekly demand {generic_demand} > "
                     f"capacity {n_classrooms * n_slots}. Split subgroups and "
                     f"elective groups each need their own room.")

    return fatal, legal
