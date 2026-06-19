"""The timetabling engine, built on Google OR-Tools CP-SAT."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ortools.sat.python import cp_model

from . import curriculum as C
from .models import School, TeachingAssignment


@dataclass
class PlacedLesson:
    class_id: str
    subject_id: str
    teacher_id: str
    day: int
    period: int
    room_id: str


@dataclass
class SolveResult:
    status: str
    lessons: list
    objective: float
    wall_time: float


def solve(school: School, assignments: list[TeachingAssignment],
          max_seconds: float = 30.0, workers: int = 8) -> SolveResult:
    m = cp_model.CpModel()
    days = range(school.n_days)
    periods = range(1, school.periods_per_day + 1)
    brk = school.reserved_break_period
    teacher_of = {(a.class_id, a.subject_id): a.teacher_id for a in assignments}

    x = {}
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if hrs <= 0:
                continue
            teacher = school.teachers[teacher_of[(cls.id, sid)]]
            for d in days:
                for p in periods:
                    if brk is not None and p == brk:
                        continue
                    if not teacher.can_work(d, p):
                        continue
                    x[(cls.id, sid, d, p)] = m.NewBoolVar(f"x_{cls.id}_{sid}_{d}_{p}")

    def xs(cid=None, sid=None, d=None, p=None):
        for key, var in x.items():
            kc, ks, kd, kp = key
            if cid is not None and kc != cid:
                continue
            if sid is not None and ks != sid:
                continue
            if d is not None and kd != d:
                continue
            if p is not None and kp != p:
                continue
            yield key, var

    # (A) curriculum hours exact
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if hrs > 0:
                m.Add(sum(v for _, v in xs(cid=cls.id, sid=sid)) == hrs)

    # (B) class: <=1 lesson per slot
    for cls in school.classes.values():
        for d in days:
            for p in periods:
                vs = [v for _, v in xs(cid=cls.id, d=d, p=p)]
                if vs:
                    m.Add(sum(vs) <= 1)

    # (D) grade max lessons/day
    for cls in school.classes.values():
        cap = school.grade_rules[cls.grade].max_lessons_per_day
        for d in days:
            vs = [v for _, v in xs(cid=cls.id, d=d)]
            if vs:
                m.Add(sum(vs) <= cap)

    # (E) subject max/day + (F) consecutive run limit
    for cls in school.classes.values():
        for sid, hrs in cls.weekly_hours.items():
            if hrs <= 0:
                continue
            subj = school.subjects[sid]
            for d in days:
                day_vars = {p: v for (_, _, _, p), v in xs(cid=cls.id, sid=sid, d=d)}
                if day_vars:
                    m.Add(sum(day_vars.values()) <= subj.max_per_day)
                win = subj.max_consecutive + 1
                for start in range(1, school.periods_per_day - win + 2):
                    window = [day_vars[pp] for pp in range(start, start + win)
                              if pp in day_vars]
                    if len(window) == win:
                        m.Add(sum(window) <= subj.max_consecutive)

    # (G) teacher: <=1 class per slot
    teacher_lessons = defaultdict(list)
    for (cid, sid, d, p), var in x.items():
        teacher_lessons[teacher_of[(cid, sid)]].append((cid, sid, d, p, var))
    for items in teacher_lessons.values():
        by_slot = defaultdict(list)
        for cid, sid, d, p, var in items:
            by_slot[(d, p)].append(var)
        for slot_vars in by_slot.values():
            if len(slot_vars) > 1:
                m.Add(sum(slot_vars) <= 1)

    # (I) specialised rooms: concurrent demand <= number of such rooms
    type_vars = defaultdict(lambda: defaultdict(list))
    for (cid, sid, d, p), var in x.items():
        rt = school.subjects[sid].requires_room_type
        if rt:
            type_vars[rt][(d, p)].append(var)
    for rt, slots in type_vars.items():
        ncap = len(school.rooms_of_type(rt))
        for slot_vars in slots.values():
            m.Add(sum(slot_vars) <= ncap)

    # shared home rooms
    home_groups = defaultdict(list)
    for cls in school.classes.values():
        home_groups[cls.home_room].append(cls.id)
    for cids in home_groups.values():
        if len(cids) < 2:
            continue
        for d in days:
            for p in periods:
                vs = [var for cid in cids
                      for (_, sid, _, _), var in xs(cid=cid, d=d, p=p)
                      if not school.subjects[sid].requires_room_type]
                if len(vs) > 1:
                    m.Add(sum(vs) <= 1)

    # ---- objective -------------------------------------------------------
    W = school.weights
    obj = []
    n = school.periods_per_day

    # teacher gaps
    for tid, items in teacher_lessons.items():
        slot_to_vars = defaultdict(list)
        for cid, sid, d, p, var in items:
            slot_to_vars[(d, p)].append(var)
        for d in days:
            busy = {}
            for p in periods:
                vs = slot_to_vars.get((d, p), [])
                if not vs:
                    continue
                b = m.NewBoolVar(f"busy_{tid}_{d}_{p}")
                m.Add(b == sum(vs))
                busy[p] = b
            if len(busy) < 2:
                continue
            load = m.NewIntVar(0, n, f"load_{tid}_{d}")
            m.Add(load == sum(busy.values()))
            work = m.NewBoolVar(f"work_{tid}_{d}")
            m.Add(load >= 1).OnlyEnforceIf(work)
            m.Add(load == 0).OnlyEnforceIf(work.Not())
            first = m.NewIntVar(0, n, f"first_{tid}_{d}")
            last = m.NewIntVar(0, n, f"last_{tid}_{d}")
            for p, b in busy.items():
                m.Add(last >= p).OnlyEnforceIf(b)
                m.Add(first <= p).OnlyEnforceIf(b)
            gaps = m.NewIntVar(0, n, f"gaps_{tid}_{d}")
            m.Add(gaps >= last - first + 1 - load).OnlyEnforceIf(work)
            obj.append(W["teacher_gaps"] * gaps)

    # hard subjects in the morning
    for (cid, sid, d, p), var in x.items():
        diff = school.subjects[sid].difficulty
        if diff >= C.HARD_THRESHOLD and p > C.MORNING_LAST_PERIOD:
            obj.append(W["hard_in_morning"] * diff * (p - C.MORNING_LAST_PERIOD) * var)

    # even daily load per class
    for cls in school.classes.values():
        target = round(cls.weekly_total / school.n_days)
        for d in days:
            vs = [v for _, v in xs(cid=cls.id, d=d)]
            if not vs:
                continue
            dev = m.NewIntVar(0, n, f"cdev_{cls.id}_{d}")
            m.Add(dev >= sum(vs) - target)
            m.Add(dev >= target - sum(vs))
            obj.append(W["class_balance"] * dev)

    # even daily load per teacher
    for tid, items in teacher_lessons.items():
        whrs = len({(c, s) for c, s, *_ in items})  # placeholder, recomputed below
        whrs = sum(school.classes[c].weekly_hours.get(s, 0)
                   for c, s in {(c, s) for c, s, *_ in items})
        target = round(whrs / school.n_days) if whrs else 0
        byday = defaultdict(list)
        for cid, sid, d, p, var in items:
            byday[d].append(var)
        for d in days:
            vs = byday.get(d, [])
            if not vs:
                continue
            dev = m.NewIntVar(0, n, f"tdev_{tid}_{d}")
            m.Add(dev >= sum(vs) - target)
            m.Add(dev >= target - sum(vs))
            obj.append(W["teacher_balance"] * dev)

    # PE not in the last period
    for (cid, sid, d, p), var in x.items():
        if school.subjects[sid].is_pe and p == school.periods_per_day:
            obj.append(W["pe_last_period"] * var)

    # hard subjects not clustered on a single day
    for cls in school.classes.values():
        for d in days:
            hard_vars = [v for (c, s, dd, p), v in x.items()
                         if c == cls.id and dd == d
                         and school.subjects[s].difficulty >= C.HARD_THRESHOLD]
            if not hard_vars:
                continue
            over = m.NewIntVar(0, n, f"hard_over_{cls.id}_{d}")
            m.Add(over >= sum(hard_vars) - C.HARD_PER_DAY_SOFT_CAP)
            obj.append(W["hard_cluster"] * over)

    m.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    status = solver.Solve(m)

    lessons = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        lessons = _extract(school, x, teacher_of, solver)
    return SolveResult(solver.StatusName(status), lessons,
                       solver.ObjectiveValue() if lessons else 0.0, solver.WallTime())


def _extract(school, x, teacher_of, solver):
    chosen = [(cid, sid, d, p) for (cid, sid, d, p), var in x.items()
              if solver.Value(var) == 1]
    rooms_by_type = {rt: [r.id for r in school.rooms_of_type(rt)]
                     for rt in {s.requires_room_type for s in school.subjects.values()
                                if s.requires_room_type}}
    used = defaultdict(set)
    placed = []
    for cid, sid, d, p in chosen:
        rt = school.subjects[sid].requires_room_type
        if rt:
            free = next((rid for rid in rooms_by_type[rt] if rid not in used[(rt, d, p)]),
                        rooms_by_type[rt][0])
            used[(rt, d, p)].add(free)
            room_id = free
        else:
            room_id = school.classes[cid].home_room
        placed.append(PlacedLesson(cid, sid, teacher_of[(cid, sid)], d, p, room_id))
    placed.sort(key=lambda L: (L.class_id, L.day, L.period))
    return placed
