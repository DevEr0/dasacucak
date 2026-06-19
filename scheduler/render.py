"""Render timetables to text in the requested format (Armenian or English)."""
from __future__ import annotations

from collections import defaultdict

from .models import School
from .solver import PlacedLesson

PERIOD_PREFIX = {"hy": "Դ", "en": "P"}


def _subject_name(school: School, sid: str, lang: str) -> str:
    s = school.subjects[sid]
    return s.name_hy if lang == "hy" else (s.name_en or s.name_hy)


def _grid(lessons, key):
    """index lessons -> {(day,period): lesson} for one class or teacher."""
    g = {}
    for L in lessons:
        if key(L):
            g[(L.day, L.period)] = L
    return g


def render_class(school: School, lessons: list[PlacedLesson], cid: str,
                 lang: str = "hy") -> str:
    pp = PERIOD_PREFIX[lang]
    g = _grid(lessons, lambda L: L.class_id == cid)
    out = [f"=== {cid} ({school.year}) ==="]
    for d in range(school.n_days):
        out.append(school.day_name(d, lang))
        for p in range(1, school.periods_per_day + 1):
            if school.reserved_break_period == p:
                out.append(f"{pp}{p} {'—— ընդմիջում ——' if lang=='hy' else '—— break ——'}")
                continue
            L = g.get((d, p))
            if L:
                name = _subject_name(school, L.subject_id, lang)
                room = school.rooms[L.room_id].name
                # show room only when it's a specialised room
                tag = "" if school.subjects[L.subject_id].requires_room_type is None \
                    else f"  [{room}]"
                out.append(f"{pp}{p} {name}{tag}")
            else:
                out.append(f"{pp}{p} —")
        out.append("")
    return "\n".join(out)


def render_teacher(school: School, lessons: list[PlacedLesson], tid: str,
                   lang: str = "hy") -> str:
    pp = PERIOD_PREFIX[lang]
    teacher = school.teachers[tid]
    g = _grid(lessons, lambda L: L.teacher_id == tid)
    load = sum(1 for L in lessons if L.teacher_id == tid)
    cap = teacher.resolved_cap()
    out = [f"=== {teacher.name} ==="]
    for d in range(school.n_days):
        out.append(school.day_name(d, lang))
        for p in range(1, school.periods_per_day + 1):
            L = g.get((d, p))
            if L:
                name = _subject_name(school, L.subject_id, lang)
                out.append(f"{pp}{p} {L.class_id} {name}")
            else:
                out.append(f"{pp}{p} —")
        out.append("")
    label = "Շաբաթական ծանրաբեռնվածություն" if lang == "hy" else "Weekly load"
    out.append(f"{label}: {load}/{cap}")
    return "\n".join(out)


def render_all_classes(school, lessons, lang="hy") -> str:
    return "\n".join(render_class(school, lessons, cid, lang)
                     for cid in school.classes)


def render_all_teachers(school, lessons, lang="hy") -> str:
    # only teachers who actually teach
    active = {L.teacher_id for L in lessons}
    return "\n".join(render_teacher(school, lessons, tid, lang)
                     for tid in school.teachers if tid in active)


def quality_report(school: School, lessons: list[PlacedLesson],
                   lang: str = "hy") -> str:
    """Human-readable summary of how good (not just legal) the timetable is."""
    # teacher gaps
    total_gaps = 0
    for tid in school.teachers:
        byday = defaultdict(list)
        for L in lessons:
            if L.teacher_id == tid:
                byday[L.day].append(L.period)
        for ps in byday.values():
            if len(ps) >= 2:
                total_gaps += (max(ps) - min(ps) + 1) - len(ps)

    # class daily spread
    spreads = []
    for cls in school.classes.values():
        counts = [0] * school.n_days
        for L in lessons:
            if L.class_id == cls.id:
                counts[L.day] += 1
        spreads.append((cls.id, counts, max(counts) - min(counts)))

    # afternoon hard subjects
    from . import curriculum as C
    aft_hard = sum(1 for L in lessons
                   if school.subjects[L.subject_id].difficulty >= C.HARD_THRESHOLD
                   and L.period > C.MORNING_LAST_PERIOD)

    lines = ["=== Որակի ամփոփում ===" if lang == "hy" else "=== Quality summary ==="]
    g = "Ուսուցիչների ընդհանուր պատուհաններ" if lang == "hy" else "Total teacher gaps"
    a = "Դժվար առարկաներ կեսօրից հետո" if lang == "hy" else "Hard subjects in the afternoon"
    lines.append(f"{g}: {total_gaps}")
    lines.append(f"{a}: {aft_hard}")
    head = "Դասարանների օրական բեռնվածություն (Երկ→Ուրբ)" if lang == "hy" \
        else "Class daily load (Mon→Fri)"
    lines.append(head + ":")
    for cid, counts, spread in spreads:
        flag = " ⚠" if spread > 2 else ""
        lines.append(f"  {cid}: {counts}  (Δ={spread}){flag}")
    return "\n".join(lines)
