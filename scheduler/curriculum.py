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

# --------------------------------------------------------------------------
# Splittable subjects (a class may be divided into two subgroups for these).
# Per common ՀՀ practice / the user's school: foreign languages, the native
# language, and IT split by default.  Override per subject with `splittable`.
# --------------------------------------------------------------------------
SPLIT_DEFAULT = {
    "anglerent", "rusac_lezu", "otar_lezu", "franserent", "germaneren",
    "hayoc_lezu", "mayreni",
    "informatika",
}

# --------------------------------------------------------------------------
# Legal ceilings from the RA Law "On General Education" (HO-160-N, 10.07.2009)
# --------------------------------------------------------------------------
LEGAL_TEACHER_MAX = 22        # Art. 25(3): full academic workload <= 22 h/week
LEGAL_ADMIN_FULLTIME_MAX = 8  # Art. 25(4): full-time admin concurrent teaching <= 8 h
LEGAL_ADMIN_PARTTIME_MAX = 14 # Art. 25(4): part-time admin <= 14 h

# --------------------------------------------------------------------------
# Rules that MAY be softened in relaxed ("emergency") compliance mode.
# Every one is annotated with its regulatory basis so violations can be
# reported precisely.  Physical rules (double-booking, room capacity,
# curriculum hours) are never relaxable.
# --------------------------------------------------------------------------
RELAXABLE_RULES = {
    "student_daily_cap": {
        "hy": "Աշակերտի օրական դասերի առավելագույնը",
        "en": "Student max lessons per day",
        "law": "State standard for general education (HO-160-N Art. 6, 7)",
    },
    "student_weekly_cap": {
        "hy": "Աշակերտի շաբաթական ծանրաբեռնվածության առաստաղը",
        "en": "Student weekly load ceiling",
        "law": "Background curriculum / state standard (HO-160-N Art. 6(4))",
    },
    "teacher_weekly_cap": {
        "hy": "Ուսուցչի շաբաթական դրույքաչափը",
        "en": "Teacher weekly load cap",
        "law": "HO-160-N Art. 25(3): ≤ 22 class hours/week (full rate)",
    },
    "teacher_availability": {
        "hy": "Ուսուցչի հասանելիության ժամերը",
        "en": "Teacher availability",
        "law": "Employment contract / internal rules (HO-160-N Art. 27)",
    },
    "subject_daily_rules": {
        "hy": "Առարկայի օրական/անընդմեջ սահմանները",
        "en": "Subject per-day / consecutive limits",
        "law": "Sanitary-pedagogical norms (state standard, HO-160-N Art. 6)",
    },
    "band_sync": {
        "hy": "Հոսքային խմբերի համաժամանակյա դասերը",
        "en": "Stream groups of one band meet simultaneously",
        "law": "Organisational norm — no student left idle mid-day",
    },
    "split_pairing": {
        "hy": "Ենթախմբերի զույգված դասավանդումը",
        "en": "Subgroup pairing (both halves busy together)",
        "law": "Organisational norm — no unsupervised half-class mid-day",
    },
}

RELAX_PENALTY = 1000   # objective cost of one violation of a relaxed rule
