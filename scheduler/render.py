"""Render timetables to text in the requested format (Armenian or English)."""
from __future__ import annotations

from collections import defaultdict

from .models import School
from .solver import PlacedLesson

PERIOD_PREFIX = {"hy": "Դ", "en": "P"}


def _subject_name(school: School, sid: str, lang: str) -> str:
    s = school.subjects[sid]
    return s.name_hy if lang == "hy" else (s.name_en or s.name_hy)


def lessons_of_class(school: School, lessons, cid: str):
    """All lessons a student of `cid` may sit in: whole-class, both subgroups
    (labelled), and every elective lesson of a group containing the class."""
    out = []
    for L in lessons:
        if L.kind == "elective":
            grp = school.elective_groups.get(L.group_id)
            if grp and cid in grp.member_classes:
                out.append(L)
        elif L.class_id == cid:
            out.append(L)
    return out


def _slot_lists(lessons):
    g = defaultdict(list)
    for L in lessons:
        g[(L.day, L.period)].append(L)
    return g


def _lesson_text(school: School, L: PlacedLesson, lang: str) -> str:
    name = _subject_name(school, L.subject_id, lang)
    bits = [name]
    if L.kind == "split":
        bits.append(f"(խումբ {L.subgroup})" if lang == "hy" else f"(group {L.subgroup})")
    if L.kind == "elective":
        grp = school.elective_groups.get(L.group_id)
        gname = grp.name if grp else L.group_id
        bits.insert(0, f"«{gname}»")
    if school.subjects[L.subject_id].requires_room_type:
        room = school.rooms.get(L.room_id)
        bits.append(f"[{room.name if room else L.room_id}]")
    return " ".join(bits)


def render_class(school: School, lessons: list[PlacedLesson], cid: str,
                 lang: str = "hy") -> str:
    pp = PERIOD_PREFIX[lang]
    g = _slot_lists(lessons_of_class(school, lessons, cid))
    out = [f"=== {cid} ({school.year}) ==="]
    for d in range(school.n_days):
        out.append(school.day_name(d, lang))
        for p in range(1, school.periods_per_day + 1):
            if school.reserved_break_period == p:
                out.append(f"{pp}{p} {'—— ընդմիջում ——' if lang=='hy' else '—— break ——'}")
                continue
            ls = sorted(g.get((d, p), []), key=lambda L: (L.subgroup, L.group_id))
            if ls:
                out.append(f"{pp}{p} " + "  |  ".join(_lesson_text(school, L, lang)
                                                      for L in ls))
            else:
                out.append(f"{pp}{p} —")
        out.append("")
    return "\n".join(out)


def render_teacher(school: School, lessons: list[PlacedLesson], tid: str,
                   lang: str = "hy") -> str:
    pp = PERIOD_PREFIX[lang]
    teacher = school.teachers[tid]
    mine = [L for L in lessons if L.teacher_id == tid]
    g = _slot_lists(mine)
    cap = teacher.resolved_cap()
    out = [f"=== {teacher.name} ==="]
    for d in range(school.n_days):
        out.append(school.day_name(d, lang))
        for p in range(1, school.periods_per_day + 1):
            ls = g.get((d, p), [])
            if ls:
                L = ls[0]
                who = L.class_id or (school.elective_groups[L.group_id].name
                                     if L.group_id in school.elective_groups
                                     else L.group_id)
                if L.kind == "split":
                    who += f"/{L.subgroup}"
                out.append(f"{pp}{p} {who} {_subject_name(school, L.subject_id, lang)}")
            else:
                out.append(f"{pp}{p} —")
        out.append("")
    label = "Շաբաթական ծանրաբեռնվածություն" if lang == "hy" else "Weekly load"
    out.append(f"{label}: {len(mine)}/{cap}")
    return "\n".join(out)


def render_group(school: School, lessons, gid: str, lang: str = "hy") -> str:
    grp = school.elective_groups[gid]
    pp = PERIOD_PREFIX[lang]
    g = _slot_lists([L for L in lessons if L.group_id == gid])
    out = [f"=== «{grp.name}» ({', '.join(grp.member_classes)}) ==="]
    for d in range(school.n_days):
        out.append(school.day_name(d, lang))
        for p in range(1, school.periods_per_day + 1):
            ls = g.get((d, p), [])
            out.append(f"{pp}{p} " + (_lesson_text(school, ls[0], lang) if ls else "—"))
        out.append("")
    return "\n".join(out)


def render_all_classes(school, lessons, lang="hy") -> str:
    parts = [render_class(school, lessons, cid, lang) for cid in school.classes]
    parts += [render_group(school, lessons, gid, lang)
              for gid in school.elective_groups]
    return "\n".join(parts)


def render_all_teachers(school, lessons, lang="hy") -> str:
    active = {L.teacher_id for L in lessons}
    return "\n".join(render_teacher(school, lessons, tid, lang)
                     for tid in school.teachers if tid in active)


def quality_report(school: School, lessons: list[PlacedLesson],
                   lang: str = "hy") -> str:
    """Human-readable summary of how good (not just legal) the timetable is."""
    total_gaps = 0
    for tid in school.teachers:
        byday = defaultdict(list)
        for L in lessons:
            if L.teacher_id == tid:
                byday[L.day].append(L.period)
        for ps in byday.values():
            if len(ps) >= 2:
                total_gaps += (max(ps) - min(ps) + 1) - len(ps)

    spreads = []
    for cls in school.classes.values():
        counts = [0] * school.n_days
        seen = set()
        for L in lessons_of_class(school, lessons, cls.id):
            key = (L.day, L.period)
            if L.subgroup == 2 or key in seen:
                continue
            seen.add(key)
            counts[L.day] += 1
        spreads.append((cls.id, counts, max(counts) - min(counts)))

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
