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
    splittable: bool = False                 # may be taught to a class in two subgroups

    @property
    def name(self) -> str:
        return self.name_hy or self.name_en or self.id


@dataclass
class SchoolClass:
    id: str
    grade: int
    home_room: str
    weekly_hours: dict = field(default_factory=dict)
    split: bool = False                      # class is big enough to split subgroup subjects
    split_subjects: Optional[list] = None    # explicit override; None => all splittable subjects

    @property
    def weekly_total(self) -> int:
        return sum(self.weekly_hours.values())

    def split_subject_ids(self, subjects: dict) -> set:
        """Which of this class's subjects are taught in two subgroups."""
        if not self.split:
            return set()
        if self.split_subjects is not None:
            return {s for s in self.split_subjects if s in self.weekly_hours}
        return {s for s in self.weekly_hours
                if s in subjects and subjects[s].splittable}


@dataclass
class Teacher:
    id: str
    name: str
    qualified_subjects: list = field(default_factory=list)
    role: str = "subject"                    # primary | subject | admin
    max_weekly_load: Optional[int] = None
    available_days: list = field(default_factory=list)        # legacy (kept for back-compat)
    available_periods: list = field(default_factory=list)     # legacy (kept for back-compat)
    # Preferred availability model: per-weekday list of periods the teacher can work.
    # Maps day index (0=Mon) -> sorted list of available period numbers.
    #   * a day ABSENT from the map  -> available every period that day (the default);
    #   * a day mapped to []          -> unavailable the whole day.
    available_periods_by_day: dict = field(default_factory=dict)
    # Per-subject class/stream restriction: maps a qualified subject id to the
    # list of scopes this teacher may teach THAT subject to. A scope is either
    # a regular class id (e.g. "7Ա") or an elective/stream group's own id
    # (e.g. "g10_sci"), letting a teacher be qualified for a stream directly
    # without listing every class that feeds into it.
    #   * a subject ABSENT from the map (or mapped to []) -> no restriction for
    #     that subject (may teach it to any class/stream, the default);
    #   * a subject mapped to a non-empty list -> only those scopes for that
    #     subject.
    # This lets one teacher be scoped differently per subject, e.g. classes
    # 5–7 for math but only 9–11 for physics, or a specific stream for an
    # elective.
    qualified_classes_by_subject: dict = field(default_factory=dict)

    def resolved_cap(self) -> int:
        if self.max_weekly_load is not None:
            return self.max_weekly_load
        return {"primary": 18, "subject": 20, "admin": 12}.get(self.role, 20)

    def can_teach(self, subject_id: str, scope_id: str) -> bool:
        """True if this teacher may be assigned `subject_id` for `scope_id`
        (a class id, or an elective/stream group's own id). Requires the
        subject to be in `qualified_subjects`; if that subject has a scope
        list in `qualified_classes_by_subject`, `scope_id` must be in it,
        otherwise (no list, or empty list) any class/stream is allowed."""
        if subject_id not in self.qualified_subjects:
            return False
        allowed = self.qualified_classes_by_subject.get(subject_id)
        return not allowed or scope_id in allowed

    def can_work(self, day_idx: int, period: int) -> bool:
        # Per-weekday model takes precedence when present.
        if self.available_periods_by_day:
            if day_idx in self.available_periods_by_day:
                return period in self.available_periods_by_day[day_idx]
            return True  # day not listed => available all periods
        # Legacy fallback for older data files.
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
    subgroup: int = 0        # 0 = whole class; 1|2 pins one subgroup of a split subject
    group_id: str = ""       # non-empty pins an elective group's subject


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
    elective_groups: dict = field(default_factory=dict)   # id -> ElectiveGroup
    compliance: "Compliance" = None
    skip_streams: bool = False                            # ignore electives entirely

    def __post_init__(self):
        if self.compliance is None:
            self.compliance = Compliance()

    def groups_of_class(self, cid: str) -> list:
        return [g for g in self.elective_groups.values() if g.has_class(cid)]

    def bands_of_class(self, cid: str) -> list:
        return sorted({g.band for g in self.groups_of_class(cid)})

    @property
    def n_days(self) -> int:
        return len(self.days_en)

    def day_name(self, idx: int, lang: str = "hy") -> str:
        return (self.days_hy if lang == "hy" else self.days_en)[idx]

    def rooms_of_type(self, room_type: str) -> list:
        return [r for r in self.rooms.values() if r.type == room_type]


# --------------------------------------------------------------------------
# Units: everything the solver can place is one of these three kinds.
#   class    – a whole-class lesson (the classic case)
#   split    – one subgroup (1 or 2) of a class, for splittable subjects
#   elective – a cross-class stream/elective group (grades 10-12 հոսքեր)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Unit:
    uid: str
    kind: str                    # "class" | "split" | "elective"
    subject_id: str
    hours: int
    class_id: str = ""           # class / split kinds
    subgroup: int = 0            # 1 | 2 for split
    group_id: str = ""           # elective kind
    member_classes: tuple = ()   # elective kind
    band: str = ""               # elective kind

    def label(self) -> str:
        if self.kind == "split":
            return f"{self.class_id}/{self.subject_id}#g{self.subgroup}"
        if self.kind == "elective":
            return f"{self.group_id}/{self.subject_id}"
        return f"{self.class_id}/{self.subject_id}"


# --------------------------------------------------------------------------
# Teacher qualification scope ids.
#
# A "scope id" is what appears in Teacher.qualified_classes_by_subject lists:
#   * a plain class id (e.g. "7Ա")                       -> a whole-class/
#     split lesson for that class;
#   * "group_id::class_id" (e.g. "g10_sci::11Ա")          -> ONE member
#     class's share of a stream/elective group's lecture.
#
# A stream/elective lecture is a single shared session for ALL its member
# classes at once, so a teacher only covers it if they are qualified for
# EVERY one of its member classes within that specific stream — being
# qualified for "11Ա" in general does not imply "11Ա in the Science stream",
# and being qualified for the Science stream via one class does not cover a
# DIFFERENT class also enrolled in that same stream. This lets a school
# record, e.g., that a teacher can teach the Science stream to grade 11 but
# not to grade 10, even though both grades share that one named stream.
# --------------------------------------------------------------------------
def elective_scope_id(group_id: str, class_id: str) -> str:
    return f"{group_id}::{class_id}"


def unit_scope_ids(u: Unit) -> tuple:
    """The scope id(s) that must ALL be covered by a teacher's per-subject
    allowed list for them to be assignable to this unit."""
    if u.kind == "elective":
        return tuple(elective_scope_id(u.group_id, cid) for cid in u.member_classes)
    return (u.class_id,)


@dataclass
class ElectiveGroup:
    """A stream/elective group: students drawn from several classes who meet
    together for their chosen subjects.  Groups that share member classes but
    have DISJOINT student sets are put in the same *band* and may run in
    parallel; groups in different bands never overlap for a shared class.

    Per-subject class override: `subject_classes` is an optional dict
    {subject_id: [class_id, ...]} that, when present for a subject, replaces
    `member_classes` for THAT subject's lessons only.

    Shared (common) subjects are detected AUTOMATICALLY at build time: if
    the same subject appears in multiple groups of the same band, it becomes
    one merged lecture (one unit, one teacher, one time slot, union of
    member classes). No manual marking needed."""
    id: str
    name: str
    band: str
    member_classes: list = field(default_factory=list)
    weekly_hours: dict = field(default_factory=dict)
    subject_classes: dict = field(default_factory=dict)  # subject -> [class_ids]

    def members_for_subject(self, sid: str) -> list:
        """Which classes attend THIS subject's lecture in this group."""
        return self.subject_classes.get(sid) or self.member_classes

    def has_class(self, cid: str) -> bool:
        """True if `cid` participates in at least one subject of this group."""
        if cid in self.member_classes:
            return True
        return any(cid in cls for cls in self.subject_classes.values())

    @property
    def weekly_total(self) -> int:
        return sum(self.weekly_hours.values())

    def weekly_total_for_class(self, cid: str) -> int:
        """How many hours per week a student of `cid` would attend in this
        group (only the subjects where `cid` is a member)."""
        total = 0
        for sid, hrs in self.weekly_hours.items():
            if cid in self.members_for_subject(sid):
                total += hrs
        return total


@dataclass
class Compliance:
    """How strictly the legal/regulatory rules are enforced.

    mode:
      strict  – every legal rule is a hard constraint (default);
      custom  – rules in `relax` become heavily-penalised soft constraints;
      relaxed – every relaxable rule is soft (emergency mode: the schedule is
                always produced if physically possible, and every deviation
                from the regulations is reported).
    Physical rules (nobody in two places at once, room capacity, curriculum
    hours) are ALWAYS hard.
    """
    mode: str = "strict"
    relax: set = field(default_factory=set)

    def is_relaxed(self, rule: str) -> bool:
        if self.mode == "relaxed":
            return True
        if self.mode == "custom":
            return rule in self.relax
        return False
