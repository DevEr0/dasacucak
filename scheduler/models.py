"""Data models for the Armenian school timetabling system."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

DEFAULT_DAYS_HY = ["Երկուշաբթի", "Երեքշաբթի", "Չորեքշաբթի", "Հինգշաբթի", "Ուրբաթ"]
DEFAULT_DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


@dataclass
class Subject:
    id: str
    name_hy: str
    name_en: str = ""
    difficulty: int = 3                      # 1 light .. 5 very demanding
    requires_room_type: Optional[str] = None
    is_pe: bool = False
    max_consecutive: int = 1
    max_per_day: int = 1

    @property
    def name(self) -> str:
        return self.name_hy or self.name_en or self.id


@dataclass
class SchoolClass:
    id: str
    grade: int
    home_room: str
    weekly_hours: dict = field(default_factory=dict)

    @property
    def weekly_total(self) -> int:
        return sum(self.weekly_hours.values())


@dataclass
class Teacher:
    id: str
    name: str
    qualified_subjects: list = field(default_factory=list)
    role: str = "subject"                    # primary | subject | admin
    max_weekly_load: Optional[int] = None
    available_days: list = field(default_factory=list)
    available_periods: list = field(default_factory=list)

    def resolved_cap(self) -> int:
        if self.max_weekly_load is not None:
            return self.max_weekly_load
        return {"primary": 18, "subject": 20, "admin": 12}.get(self.role, 20)

    def can_work(self, day_idx: int, period: int) -> bool:
        if self.available_days and day_idx not in self.available_days:
            return False
        if self.available_periods and period not in self.available_periods:
            return False
        return True


@dataclass
class Room:
    id: str
    name: str
    type: str = "classroom"
    capacity: Optional[int] = None


@dataclass
class TeachingAssignment:
    class_id: str
    subject_id: str
    teacher_id: str


@dataclass
class GradeRule:
    grade: int
    max_lessons_per_day: int
    max_weekly_load: int


@dataclass
class School:
    year: str
    days_hy: list
    days_en: list
    periods_per_day: int
    reserved_break_period: Optional[int]
    grade_rules: dict
    subjects: dict
    classes: dict
    teachers: dict
    rooms: dict
    assignments: list
    weights: dict = field(default_factory=dict)

    @property
    def n_days(self) -> int:
        return len(self.days_en)

    def day_name(self, idx: int, lang: str = "hy") -> str:
        return (self.days_hy if lang == "hy" else self.days_en)[idx]

    def rooms_of_type(self, room_type: str) -> list:
        return [r for r in self.rooms.values() if r.type == room_type]
