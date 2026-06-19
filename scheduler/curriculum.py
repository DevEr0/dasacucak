"""Armenian-curriculum defaults (fallbacks; real numbers come from the JSON input)."""

GRADE_RULES_DEFAULT = {
    1:  {"max_lessons_per_day": 4, "max_weekly_load": 22},
    2:  {"max_lessons_per_day": 5, "max_weekly_load": 24},
    3:  {"max_lessons_per_day": 5, "max_weekly_load": 25},
    4:  {"max_lessons_per_day": 5, "max_weekly_load": 26},
    5:  {"max_lessons_per_day": 6, "max_weekly_load": 28},
    6:  {"max_lessons_per_day": 6, "max_weekly_load": 30},
    7:  {"max_lessons_per_day": 7, "max_weekly_load": 32},
    8:  {"max_lessons_per_day": 7, "max_weekly_load": 33},
    9:  {"max_lessons_per_day": 7, "max_weekly_load": 34},
    10: {"max_lessons_per_day": 7, "max_weekly_load": 35},
    11: {"max_lessons_per_day": 7, "max_weekly_load": 36},
    12: {"max_lessons_per_day": 7, "max_weekly_load": 36},
}

DIFFICULTY_DEFAULT = {
    "hayoc_lezu": 4, "mayreni": 4, "grakanutyun": 3,
    "matematika": 5, "hanrahashiv": 5, "erkrachaputyun": 5,
    "fizika": 5, "kimia": 5, "kensabanutyun": 3, "bnagitutyun": 3,
    "ashxarhagrutyun": 3, "rusac_lezu": 4, "anglerent": 4, "otar_lezu": 4,
    "hayoc_patmutyun": 3, "hamashxarhayin_patmutyun": 3, "hasarakagitutyun": 3,
    "informatika": 3, "kerparvest": 2, "erazhshtutyun": 2, "texnologia": 2,
    "fizkultura": 1, "shaxmat": 2, "neraqakan": 2, "nzp": 2,
}

ROOM_TYPE_DEFAULT = {
    "fizika": "lab_physics",
    "kimia": "lab_chemistry",
    "kensabanutyun": "lab_biology",
    "informatika": "computer",
    "fizkultura": "gym",
    "neraqakan": "resource",
}

PE_SUBJECTS = {"fizkultura"}

WEIGHTS_DEFAULT = {
    "teacher_gaps": 6,
    "hard_in_morning": 3,
    "class_balance": 4,
    "teacher_balance": 2,
    "pe_last_period": 2,
    "hard_cluster": 3,
}

HARD_PER_DAY_SOFT_CAP = 3
HARD_THRESHOLD = 4
MORNING_LAST_PERIOD = 4
