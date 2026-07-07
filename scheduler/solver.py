"""The timetabling engine, built on Google OR-Tools CP-SAT.

Places *units* on the weekly grid:
  class    – whole-class lessons;
  split    – subgroup lessons (a class divided in two for splittable subjects);
  elective – cross-class stream groups (grades 10-12 հոսքեր), organised in
             *bands*: groups in the same band hold disjoint students and may
             run in parallel; any elective lesson blocks its member classes'
             regular lessons in that slot.

Two enforcement levels:
  physical rules  – always hard (nobody in two places, room capacity,
                    curriculum hours delivered exactly);
  legal rules     – hard in strict compliance mode, heavily-penalised soft
                    constraints in relaxed/custom mode (emergency schedules).

`diagnose()` explains infeasibility: it rebuilds the model with an assumption
literal guarding every legal-rule family and every capacity, asks CP-SAT for a
sufficient set of assumptions for infeasibility (an unsat core), and returns
human-readable reasons.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from . import curriculum as C
from .models import School, Unit


@dataclass
class PlacedLesson:
    class_id: str
    subject_id: str
    teacher_id: str
    day: int
    period: int
    room_id: str
    kind: str = "class"          # class | split | elective
    subgroup: int = 0            # 1|2 for split lessons
    group_id: str = ""           # elective group id


@dataclass
class SolveResult:
    status: str
    lessons: list
    objective: float
    wall_time: float
    relaxed_rules: list = field(default_factory=list)


# ==========================================================================
# model construction (shared by solve() and diagnose())
# ==========================================================================
class _Model:
    def __init__(self, school: School, units: list[Unit], teacher_of: dict,
                 diagnose: bool = False):
        self.school = school
        self.units = units
        self.teacher_of = teacher_of
        self.diagnose = diagnose
        self.m = cp_model.CpModel()
        self.obj = []
        self.assumptions = {}    # literal index -> {"rule","label","message"}
        self._assump_cache = {}
        self.relaxed_used = set()
        self._build()

    # ---- rule handling ---------------------------------------------------
    def _mode(self, rule: str) -> str:
        """'hard' | 'soft' | 'guarded' for a relaxable rule."""
        if self.school.compliance.is_relaxed(rule):
            self.relaxed_used.add(rule)
            return "soft"
        return "guarded" if self.diagnose else "hard"

    def _guard(self, rule: str, label: str, message: str):
        key = (rule, label)
        if key not in self._assump_cache:
            lit = self.m.NewBoolVar(f"a_{rule}_{len(self._assump_cache)}")
            self.m.AddAssumption(lit)
            self._assump_cache[key] = lit
            self.assumptions[lit.Index()] = {
                "rule": rule, "label": label, "message": message}
        return self._assump_cache[key]

    def _cap_leq(self, rule: str, label: str, message: str,
                 expr, cap: int, slack_ub: int, name: str):
        """expr <= cap, with the rule's enforcement level applied."""
        mode = self._mode(rule)
        if mode == "hard":
            self.m.Add(expr <= cap)
        elif mode == "guarded":
            self.m.Add(expr <= cap).OnlyEnforceIf(self._guard(rule, label, message))
        else:  # soft
            over = self.m.NewIntVar(0, max(slack_ub, 1), name)
            self.m.Add(expr <= cap + over)
            self.obj.append(C.RELAX_PENALTY * over)

    # ---- construction ----------------------------------------------------
    def _build(self):
        s, m = self.school, self.m
        days = range(s.n_days)
        periods = range(1, s.periods_per_day + 1)
        brk = s.reserved_break_period
        avail_mode = self._mode("teacher_availability")

        # ---- variables ----------------------------------------------------
        x = {}
        for u in self.units:
            teacher = s.teachers[self.teacher_of[u.uid]]
            for d in days:
                for p in periods:
                    if brk is not None and p == brk:
                        continue
                    ok = teacher.can_work(d, p)
                    if not ok and avail_mode == "hard":
                        continue                       # fast path: no variable
                    v = m.NewBoolVar(f"x_{u.uid}_{d}_{p}")
                    x[(u.uid, d, p)] = v
                    if not ok:
                        if avail_mode == "soft":
                            self.obj.append(C.RELAX_PENALTY * v)
                        else:  # guarded
                            lit = self._guard(
                                "teacher_availability", teacher.id,
                                f"Teacher {teacher.name}'s availability "
                                f"(their assigned hours don't fit their available slots)")
                            m.Add(v == 0).OnlyEnforceIf(lit)
        self.x = x
        uvars = defaultdict(dict)          # uid -> {(d,p): var}
        for (uid, d, p), v in x.items():
            uvars[uid][(d, p)] = v
        self.uvars = uvars
        by_uid = {u.uid: u for u in self.units}

        # ---- curriculum hours exact ----------------------------------------
        for u in self.units:
            vs = list(uvars[u.uid].values())
            owner = u.class_id or u.group_id
            if self.diagnose:
                lit = self._guard("demand", owner,
                                  f"The required weekly hours of {owner} "
                                  f"(this schedule's demand itself)")
                m.Add(sum(vs) == u.hours).OnlyEnforceIf(lit)
            else:
                m.Add(sum(vs) == u.hours)

        # ---- per-class occupancy (incl. subgroups and elective bands) ------
        whole = defaultdict(list)          # cid -> [units]
        splitg = defaultdict(list)         # (cid, g) -> [units]
        egroups = defaultdict(list)        # gid -> [units]
        for u in self.units:
            if u.kind == "class":
                whole[u.class_id].append(u)
            elif u.kind == "split":
                splitg[(u.class_id, u.subgroup)].append(u)
            else:
                egroups[u.group_id].append(u)

        # an elective group never has two of its own lessons in one slot
        for gid, us in egroups.items():
            for d in days:
                for p in periods:
                    vs = [uvars[u.uid].get((d, p)) for u in us]
                    vs = [v for v in vs if v is not None]
                    if len(vs) > 1:
                        m.Add(sum(vs) <= 1)

        # band_active == 1 iff any lesson of the class's groups in that band
        # is running (blocks the class's regular lessons + counts one lesson
        # of student load).
        band_cache = {}

        def band_active(cid, band, d, p):
            gids = tuple(sorted(g.id for g in s.groups_of_class(cid)
                                if g.band == band))
            key = (band, gids, d, p)
            if key in band_cache:
                return band_cache[key]
            vs = [uvars[u.uid].get((d, p)) for gid in gids
                  for u in egroups.get(gid, [])]
            vs = [v for v in vs if v is not None]
            if not vs:
                band_cache[key] = None
                return None
            b = m.NewBoolVar(f"band_{band}_{gids[0]}_{d}_{p}")
            m.AddMaxEquality(b, vs)
            band_cache[key] = b
            return b

        self._occ = {}          # (cid, g, d, p) -> list of 0/1 terms

        def occ_terms(cid, g, d, p):
            key = (cid, g, d, p)
            if key not in self._occ:
                terms = [uvars[u.uid][(d, p)] for u in whole[cid]
                         if (d, p) in uvars[u.uid]]
                terms += [uvars[u.uid][(d, p)] for u in splitg[(cid, g)]
                          if (d, p) in uvars[u.uid]]
                for band in s.bands_of_class(cid):
                    b = band_active(cid, band, d, p)
                    if b is not None:
                        terms.append(b)
                self._occ[key] = terms
            return self._occ[key]

        split_classes = {cid for (cid, g) in splitg}
        for cls in s.classes.values():
            gs = (1, 2) if cls.id in split_classes else (1,)
            for d in days:
                for p in periods:
                    for g in gs:
                        terms = occ_terms(cls.id, g, d, p)
                        if len(terms) > 1:
                            m.Add(sum(terms) <= 1)      # physical: one place at a time

        # ---- student daily / weekly load caps ------------------------------
        for cls in s.classes.values():
            rule = s.grade_rules[cls.grade]
            gs = (1, 2) if cls.id in split_classes else (1,)
            for g in gs:
                day_sums = []
                for d in days:
                    terms = [t for p in periods for t in occ_terms(cls.id, g, d, p)]
                    if not terms:
                        continue
                    expr = sum(terms)
                    day_sums.append(expr)
                    self._cap_leq(
                        "student_daily_cap", cls.id,
                        f"Class {cls.id}: max {rule.max_lessons_per_day} "
                        f"lessons/day (grade {cls.grade})",
                        expr, rule.max_lessons_per_day, s.periods_per_day,
                        f"od_{cls.id}_{g}_{d}")
                if day_sums:
                    self._cap_leq(
                        "student_weekly_cap", cls.id,
                        f"Class {cls.id}: weekly ceiling "
                        f"{rule.max_weekly_load} lessons (grade {cls.grade})",
                        sum(day_sums), rule.max_weekly_load,
                        s.n_days * s.periods_per_day, f"ow_{cls.id}_{g}")

        # ---- band sync: all groups of a band meet at the same slots ---------
        sync_mode = self._mode("band_sync")
        bands = defaultdict(list)
        for gid, us in egroups.items():
            band = us[0].band
            bands[band].append(gid)
        for band, gids in bands.items():
            if len(gids) < 2:
                continue
            for d in days:
                for p in periods:
                    sums = []
                    for gid in gids:
                        vs = [uvars[u.uid][(d, p)] for u in egroups[gid]
                              if (d, p) in uvars[u.uid]]
                        sums.append(sum(vs) if vs else 0)
                    ref = sums[0]
                    for other in sums[1:]:
                        if sync_mode == "hard":
                            m.Add(ref == other)
                        elif sync_mode == "guarded":
                            lit = self._guard(
                                "band_sync", band,
                                f"Band '{band}': its stream groups must meet "
                                f"at the same time slots (check that their "
                                f"weekly totals match)")
                            m.Add(ref == other).OnlyEnforceIf(lit)
                        else:
                            dv = m.NewIntVar(0, 1, f"sync_{band}_{d}_{p}_{len(self.obj)}")
                            m.Add(dv >= ref - other)
                            m.Add(dv >= other - ref)
                            self.obj.append(C.RELAX_PENALTY * dv)

        # ---- split pairing: both halves busy together ----------------------
        pair_mode = self._mode("split_pairing")
        for cid in split_classes:
            for d in days:
                for p in periods:
                    v1 = [uvars[u.uid][(d, p)] for u in splitg[(cid, 1)]
                          if (d, p) in uvars[u.uid]]
                    v2 = [uvars[u.uid][(d, p)] for u in splitg[(cid, 2)]
                          if (d, p) in uvars[u.uid]]
                    if not v1 and not v2:
                        continue
                    if pair_mode == "hard":
                        m.Add(sum(v1) == sum(v2))
                    elif pair_mode == "guarded":
                        lit = self._guard(
                            "split_pairing", cid,
                            f"Class {cid}: subgroup lessons must run in pairs "
                            f"(no half-class left unsupervised)")
                        m.Add(sum(v1) == sum(v2)).OnlyEnforceIf(lit)
                    else:
                        dv = m.NewIntVar(0, 1, f"pair_{cid}_{d}_{p}")
                        m.Add(dv >= sum(v1) - sum(v2))
                        m.Add(dv >= sum(v2) - sum(v1))
                        self.obj.append(C.RELAX_PENALTY * dv)

        # ---- subject per-day / consecutive limits --------------------------
        for u in self.units:
            subj = s.subjects[u.subject_id]
            for d in days:
                day_vars = {p: uvars[u.uid][(d, p)] for p in periods
                            if (d, p) in uvars[u.uid]}
                if not day_vars:
                    continue
                self._cap_leq(
                    "subject_daily_rules", u.label(),
                    f"{u.label()}: at most {subj.max_per_day}/day, "
                    f"{subj.max_consecutive} in a row",
                    sum(day_vars.values()), subj.max_per_day,
                    s.periods_per_day, f"mpd_{u.uid}_{d}")
                win = subj.max_consecutive + 1
                for start in range(1, s.periods_per_day - win + 2):
                    window = [day_vars[pp] for pp in range(start, start + win)
                              if pp in day_vars]
                    if len(window) == win:
                        self._cap_leq(
                            "subject_daily_rules", u.label(),
                            f"{u.label()}: at most {subj.max_consecutive} "
                            f"consecutive lessons",
                            sum(window), subj.max_consecutive, win,
                            f"mc_{u.uid}_{d}_{start}")

        # ---- teacher: one place at a time (physical) ------------------------
        self.teacher_slots = defaultdict(lambda: defaultdict(list))
        for (uid, d, p), v in x.items():
            self.teacher_slots[self.teacher_of[uid]][(d, p)].append(v)
        for slots in self.teacher_slots.values():
            for vs in slots.values():
                if len(vs) > 1:
                    m.Add(sum(vs) <= 1)

        # ---- rooms (physical) -----------------------------------------------
        # specialised rooms: concurrent demand <= number of such rooms
        type_vars = defaultdict(lambda: defaultdict(list))
        generic_vars = defaultdict(list)
        for (uid, d, p), v in x.items():
            rt = s.subjects[by_uid[uid].subject_id].requires_room_type
            if rt:
                type_vars[rt][(d, p)].append(v)
            else:
                generic_vars[(d, p)].append(v)
        for rt, slots in type_vars.items():
            ncap = len(s.rooms_of_type(rt))
            for slot, vs in slots.items():
                if self.diagnose:
                    lit = self._guard(
                        "room_capacity", rt,
                        f"Only {ncap} room(s) of type '{rt}' exist")
                    m.Add(sum(vs) <= ncap).OnlyEnforceIf(lit)
                elif len(vs) > ncap:
                    m.Add(sum(vs) <= ncap)
        # ordinary classrooms: every simultaneous generic lesson needs one
        ncls = len(s.rooms_of_type("classroom"))
        for slot, vs in generic_vars.items():
            if self.diagnose:
                lit = self._guard("room_capacity", "classroom",
                                  f"Only {ncls} ordinary classroom(s) exist "
                                  f"(each subgroup / elective group needs its own)")
                m.Add(sum(vs) <= ncls).OnlyEnforceIf(lit)
            elif len(vs) > ncls:
                m.Add(sum(vs) <= ncls)

        # classes sharing one home room can't both hold a whole-class,
        # non-specialised lesson there at once
        home_groups = defaultdict(list)
        for cls in s.classes.values():
            if cls.home_room:
                home_groups[cls.home_room].append(cls.id)
        for cids in home_groups.values():
            if len(cids) < 2:
                continue
            for d in days:
                for p in periods:
                    vs = [uvars[u.uid][(d, p)]
                          for cid in cids for u in whole[cid]
                          if not s.subjects[u.subject_id].requires_room_type
                          and (d, p) in uvars[u.uid]]
                    if len(vs) > 1:
                        m.Add(sum(vs) <= 1)

        # ---- objective (only meaningful in solve mode) -----------------------
        if not self.diagnose:
            self._objective(whole, splitg, split_classes)
        m.Minimize(sum(self.obj) if self.obj else 0)

    # ---- soft quality objective -------------------------------------------
    def _objective(self, whole, splitg, split_classes):
        s, m, x = self.school, self.m, self.x
        W = s.weights
        n = s.periods_per_day
        days = range(s.n_days)
        periods = range(1, n + 1)
        by_uid = {u.uid: u for u in self.units}

        # teacher gaps
        for tid, slots in self.teacher_slots.items():
            for d in days:
                busy = {}
                for p in periods:
                    vs = slots.get((d, p), [])
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
                self.obj.append(W["teacher_gaps"] * gaps)

        # hard subjects in the morning + PE not last
        for (uid, d, p), var in x.items():
            subj = s.subjects[by_uid[uid].subject_id]
            if subj.difficulty >= C.HARD_THRESHOLD and p > C.MORNING_LAST_PERIOD:
                self.obj.append(W["hard_in_morning"] * subj.difficulty
                                * (p - C.MORNING_LAST_PERIOD) * var)
            if subj.is_pe and p == n:
                self.obj.append(W["pe_last_period"] * var)

        # even daily load per class (subgroup-1 student path)
        for cls in s.classes.values():
            target = round(cls.weekly_total / s.n_days)
            for d in days:
                terms = [t for p in periods
                         for t in self._occ.get((cls.id, 1, d, p), [])]
                if not terms:
                    continue
                dev = m.NewIntVar(0, n, f"cdev_{cls.id}_{d}")
                m.Add(dev >= sum(terms) - target)
                m.Add(dev >= target - sum(terms))
                self.obj.append(W["class_balance"] * dev)

        # even daily load per teacher
        loads = defaultdict(int)
        for uid, tid in self.teacher_of.items():
            loads[tid] += by_uid[uid].hours
        for tid, slots in self.teacher_slots.items():
            target = round(loads[tid] / s.n_days) if loads[tid] else 0
            for d in days:
                vs = [v for (dd, p), lst in slots.items() if dd == d for v in lst]
                if not vs:
                    continue
                dev = m.NewIntVar(0, n, f"tdev_{tid}_{d}")
                m.Add(dev >= sum(vs) - target)
                m.Add(dev >= target - sum(vs))
                self.obj.append(W["teacher_balance"] * dev)

        # hard subjects not clustered on one day
        for cls in s.classes.values():
            for d in days:
                hard_vars = [self.uvars[u.uid][(d, p)]
                             for u in whole[cls.id] + splitg.get((cls.id, 1), [])
                             for p in periods
                             if s.subjects[u.subject_id].difficulty >= C.HARD_THRESHOLD
                             and (d, p) in self.uvars[u.uid]]
                if not hard_vars:
                    continue
                over = m.NewIntVar(0, n, f"hard_over_{cls.id}_{d}")
                m.Add(over >= sum(hard_vars) - C.HARD_PER_DAY_SOFT_CAP)
                self.obj.append(W["hard_cluster"] * over)


# ==========================================================================
# public API
# ==========================================================================
def solve(school: School, units: list[Unit], teacher_of: dict,
          max_seconds: float = 30.0, workers: int = 8) -> SolveResult:
    model = _Model(school, units, teacher_of, diagnose=False)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    status = solver.Solve(model.m)

    lessons = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        lessons = _extract(school, units, teacher_of, model.x, solver)
    return SolveResult(solver.StatusName(status), lessons,
                       solver.ObjectiveValue() if lessons else 0.0,
                       solver.WallTime(), sorted(model.relaxed_used))


def diagnose(school: School, units: list[Unit], teacher_of: dict,
             max_seconds: float = 20.0) -> list[dict]:
    """Explain WHY no legal timetable exists.

    Returns a list of {"rule", "label", "message"}: a sufficient set of
    constraint groups that together make the problem infeasible (a CP-SAT
    unsat core).  Fixing/relaxing items from this set is what can restore
    feasibility.  Empty list => could not pinpoint (e.g. solver timeout).
    """
    model = _Model(school, units, teacher_of, diagnose=True)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = 1   # required for unsat cores
    status = solver.Solve(model.m)
    if status != cp_model.INFEASIBLE:
        return []
    core = list(dict.fromkeys(solver.SufficientAssumptionsForInfeasibility()))

    # ---- deletion-based minimisation: drop assumptions one by one and keep
    # only those the infeasibility truly needs.  Generic families (the demand
    # itself, broad caps) are tried for deletion first, so the surviving core
    # names the most specific causes.
    lit_by_index = {lit.Index(): lit for lit in model._assump_cache.values()}
    generic = {"demand": 0, "student_weekly_cap": 1, "student_daily_cap": 2,
               "subject_daily_rules": 3, "room_capacity": 4}
    core.sort(key=lambda i: generic.get(model.assumptions[i]["rule"], 9))
    model.m.ClearAssumptions()
    kept = list(core)
    tester = cp_model.CpSolver()
    tester.parameters.max_time_in_seconds = max(2.0, max_seconds / 8)
    tester.parameters.num_search_workers = 1
    for idx in list(core):
        trial = [i for i in kept if i != idx]
        if not trial:
            break
        model.m.ClearAssumptions()
        model.m.AddAssumptions([lit_by_index[i] for i in trial])
        # disabled families (not assumed) leave their guarded constraints off
        if tester.Solve(model.m) == cp_model.INFEASIBLE:
            kept = trial            # still impossible without it -> not a cause

    out, seen = [], set()
    for idx in kept:
        info = model.assumptions.get(idx)
        if info and (info["rule"], info["label"]) not in seen:
            seen.add((info["rule"], info["label"]))
            out.append(info)
    return out


def _extract(school, units, teacher_of, x, solver):
    by_uid = {u.uid: u for u in units}
    chosen = [(uid, d, p) for (uid, d, p), var in x.items()
              if solver.Value(var) == 1]

    # room assignment: specialised first, then whole-class home rooms, then
    # subgroups / electives into any free ordinary classroom.
    used = defaultdict(set)                     # (d,p) -> {room ids}
    typed_pool = {rt: [r.id for r in school.rooms_of_type(rt)]
                  for rt in {s.requires_room_type
                             for s in school.subjects.values()
                             if s.requires_room_type}}
    classrooms = [r.id for r in school.rooms_of_type("classroom")]

    def pick(pool, d, p):
        for rid in pool:
            if rid not in used[(d, p)]:
                used[(d, p)].add(rid)
                return rid
        return pool[0] if pool else ""

    def order(item):
        uid, d, p = item
        u = by_uid[uid]
        rt = school.subjects[u.subject_id].requires_room_type
        return 0 if rt else (1 if u.kind == "class" else 2)
    chosen.sort(key=order)

    placed = []
    for uid, d, p in chosen:
        u = by_uid[uid]
        rt = school.subjects[u.subject_id].requires_room_type
        if rt:
            room_id = pick(typed_pool.get(rt, []), d, p)
        elif u.kind == "class":
            room_id = school.classes[u.class_id].home_room or pick(classrooms, d, p)
            used[(d, p)].add(room_id)
        else:
            home = school.classes[u.class_id].home_room if u.class_id else ""
            if home and home not in used[(d, p)]:
                used[(d, p)].add(home)
                room_id = home
            else:
                room_id = pick(classrooms, d, p)
        placed.append(PlacedLesson(
            class_id=u.class_id, subject_id=u.subject_id,
            teacher_id=teacher_of[uid], day=d, period=p, room_id=room_id,
            kind=u.kind, subgroup=u.subgroup, group_id=u.group_id))
    placed.sort(key=lambda L: (L.class_id or L.group_id, L.day, L.period, L.subgroup))
    return placed
