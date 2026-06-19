"""Load a school definition from JSON and fill in curriculum defaults."""
from __future__ import annotations

import json

from . import curriculum as C
from .models import (DEFAULT_DAYS_EN, DEFAULT_DAYS_HY, GradeRule, Room, School,
                     SchoolClass, Subject, Teacher, TeachingAssignment)


def load_school(path: str) -> School:
    with open(path, encoding="utf-8") as fh:
        return build_school(json.load(fh))


def _parse_periods_by_day(raw_val) -> dict:
    """Normalize {"0": [1,2,3], ...} (JSON string keys) into {0: [1,2,3], ...}."""
    out: dict = {}
    if isinstance(raw_val, dict):
        for k, v in raw_val.items():
            try:
                day = int(k)
            except (TypeError, ValueError):
                continue
            periods = sorted({int(p) for p in (v or [])})
            out[day] = periods
    return out


def build_school(raw: dict) -> School:
    subjects = {
        sid: Subject(
            id=sid,
            name_hy=s.get("name_hy", sid),
            name_en=s.get("name_en", ""),
            difficulty=s.get("difficulty", C.DIFFICULTY_DEFAULT.get(sid, 3)),
            requires_room_type=s.get("requires_room_type", C.ROOM_TYPE_DEFAULT.get(sid)),
            is_pe=s.get("is_pe", sid in C.PE_SUBJECTS),
            max_consecutive=s.get("max_consecutive", 1),
            max_per_day=s.get("max_per_day", 1),
        )
        for sid, s in raw["subjects"].items()
    }

    rooms = {
        rid: Room(id=rid, name=r.get("name", rid),
                  type=r.get("type", "classroom"), capacity=r.get("capacity"))
        for rid, r in raw["rooms"].items()
    }

    classes = {
        cid: SchoolClass(id=cid, grade=c["grade"], home_room=c["home_room"],
                         weekly_hours=dict(c["weekly_hours"]))
        for cid, c in raw["classes"].items()
    }

    teachers = {
        tid: Teacher(
            id=tid, name=t.get("name", tid),
            qualified_subjects=list(t.get("qualified_subjects", [])),
            role=t.get("role", "subject"),
            max_weekly_load=t.get("max_weekly_load"),
            available_days=list(t.get("available_days", [])),
            available_periods=list(t.get("available_periods", [])),
            available_periods_by_day=_parse_periods_by_day(
                t.get("available_periods_by_day", {})),
        )
        for tid, t in raw["teachers"].items()
    }

    assignments = [TeachingAssignment(a["class_id"], a["subject_id"], a["teacher_id"])
                   for a in raw.get("assignments", [])]

    grade_rules = {}
    overrides = raw.get("grade_rules", {})
    for g in {c.grade for c in classes.values()}:
        base = dict(C.GRADE_RULES_DEFAULT.get(g, {"max_lessons_per_day": 7,
                                                  "max_weekly_load": 34}))
        base.update(overrides.get(str(g), {}))
        grade_rules[g] = GradeRule(g, base["max_lessons_per_day"], base["max_weekly_load"])

    weights = dict(C.WEIGHTS_DEFAULT)
    weights.update(raw.get("weights", {}))

    sc = raw.get("school", {})
    return School(
        year=sc.get("year", raw.get("year", "")),
        days_hy=sc.get("days_hy", DEFAULT_DAYS_HY),
        days_en=sc.get("days_en", DEFAULT_DAYS_EN),
        periods_per_day=sc.get("periods_per_day", raw.get("periods_per_day", 7)),
        reserved_break_period=sc.get("reserved_break_period"),
        grade_rules=grade_rules, subjects=subjects, classes=classes,
        teachers=teachers, rooms=rooms, assignments=assignments, weights=weights,
    )
