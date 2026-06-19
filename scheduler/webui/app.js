/* Դասացուցակ — timetable builder UI
   All scheduling happens server-side (Python CP-SAT); this file is the editor
   and the result renderer. State mirrors the JSON schema the solver expects. */

const DAYS = {
  hy: ["Երկուշաբթի", "Երեքշաբթի", "Չորեքշաբթի", "Հինգշաբթի", "Ուրբաթ"],
  en: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
};
const DAYS_SHORT = { hy: ["Երկ", "Երք", "Չրք", "Հնգ", "Ուր"], en: ["Mon", "Tue", "Wed", "Thu", "Fri"] };
const PP = { hy: "Դ", en: "P" };
const ROOM_TYPES = ["classroom", "lab_physics", "lab_chemistry", "lab_biology", "computer", "gym", "resource"];
const ROOM_TYPE_LABEL = {
  hy: { classroom: "Սովորական", lab_physics: "Ֆիզ. լաբ.", lab_chemistry: "Քիմ. լաբ.", lab_biology: "Կենս. լաբ.", computer: "Համակարգչային", gym: "Մարզադահլիճ", resource: "Ռեսուրս" },
  en: { classroom: "Classroom", lab_physics: "Physics lab", lab_chemistry: "Chemistry lab", lab_biology: "Biology lab", computer: "Computer", gym: "Gym", resource: "Resource" },
};
const ROLE_LABEL = {
  hy: { primary: "Տարրական (18ժ)", subject: "Առարկայական (20ժ)", admin: "Վարչական" },
  en: { primary: "Primary (18h)", subject: "Subject (20h)", admin: "Admin" },
};

const I18N = {
  hy: {
    tagline: "Դպրոցի դասացուցակ կազմող", loadSample: "Բեռնել նմուշը", import: "Ներմուծել",
    export: "Արտահանել", generate: "Կազմել դասացուցակը", solving: "Կազմվում է…",
    navSettings: "Կարգավորումներ", navSubjects: "Առարկաներ", navRooms: "Սենյակներ",
    navClasses: "Դասարաններ", navTeachers: "Ուսուցիչներ", navResult: "Դասացուցակ",
    add: "Ավելացնել", remove: "Հեռացնել",
  },
  en: {
    tagline: "School timetable builder", loadSample: "Load sample", import: "Import",
    export: "Export", generate: "Generate timetable", solving: "Generating…",
    navSettings: "Settings", navSubjects: "Subjects", navRooms: "Rooms",
    navClasses: "Classes", navTeachers: "Teachers", navResult: "Timetable",
    add: "Add", remove: "Remove",
  },
};

const state = {
  lang: "hy",
  maxSeconds: 20,
  school: blankSchool(),
  defaults: null,
  result: null,        // {status, objective, wall_time, lessons, violations, quality}
  resultView: "classes",
  resultPick: null,
  section: "settings",
  _ids: 0,
};

function blankSchool() {
  return { year: "", periods_per_day: 7, reserved_break_period: null,
           subjects: {}, rooms: {}, classes: {}, teachers: {}, assignments: [] };
}
function uid(prefix) { state._ids += 1; return `${prefix}${Date.now().toString(36).slice(-4)}${state._ids}`; }
function t(k) { return (I18N[state.lang][k]) || k; }
function nm(obj) { return state.lang === "hy" ? (obj.name_hy || obj.name_en || "") : (obj.name_en || obj.name_hy || ""); }

/* ---------------- tiny DOM helpers ---------------- */
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else if (v === true) n.setAttribute(k, "");
    else if (v !== false && v != null) n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
  return n;
}
const $ = (sel, root = document) => root.querySelector(sel);
const panel = () => $("#panel");
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function toast(msg, bad = false) {
  const tn = $("#toast"); tn.textContent = msg; tn.className = "toast" + (bad ? " bad" : "");
  tn.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (tn.hidden = true), 3200);
}

/* ---------------- derived lists ---------------- */
const subjectEntries = () => Object.entries(state.school.subjects);
const roomEntries = () => Object.entries(state.school.rooms);
const classEntries = () => Object.entries(state.school.classes);
const teacherEntries = () => Object.entries(state.school.teachers);
function definedRoomTypes() {
  const s = new Set(roomEntries().map(([, r]) => r.type).filter(Boolean));
  return Array.from(s);
}
function gradeCeiling(grade) {
  const d = state.defaults && state.defaults.grade_rules[String(grade)];
  return d ? d.max_weekly_load : 34;
}

/* ================= SECTIONS ================= */
function render() {
  // chrome i18n
  document.querySelectorAll("[data-i18n]").forEach(n => n.textContent = t(n.dataset.i18n));
  // nav active
  document.querySelectorAll(".rail button").forEach(b => b.classList.toggle("on", b.dataset.sec === state.section));
  $("#nav-result").disabled = !state.result;
  document.querySelectorAll("#lang-toggle button").forEach(b => b.classList.toggle("on", b.dataset.lang === state.lang));
  const p = panel(); clear(p);
  ({ settings: secSettings, subjects: secSubjects, rooms: secRooms,
     classes: secClasses, teachers: secTeachers, result: secResult }[state.section])();
  saveLocal();
}

/* ---- browser auto-save: your work survives closing the tab ---- */
const LS_KEY = "dasatsutsak.v1";
function saveLocal() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      school: state.school, lang: state.lang, maxSeconds: state.maxSeconds,
    }));
  } catch (e) { /* private mode / quota — ignore */ }
}
function loadLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    return obj && obj.school ? obj : null;
  } catch (e) { return null; }
}
function clearLocal() { try { localStorage.removeItem(LS_KEY); } catch (e) {} }
function debounce(fn, ms) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }
function head(title, sub, ...actions) {
  return el("div", { class: "sec-head" },
    el("div", {}, el("h2", {}, title), sub ? el("p", { class: "sub" }, sub) : null),
    actions.length ? el("div", {}, ...actions) : null);
}

/* ---- Settings ---- */
function secSettings() {
  const s = state.school;
  const breakSel = el("select", { on: { change: e => { s.reserved_break_period = e.target.value ? +e.target.value : null; } } },
    el("option", { value: "" }, state.lang === "hy" ? "Չկա" : "None"));
  for (let p = 1; p <= s.periods_per_day; p++) {
    const o = el("option", { value: p }, `${PP[state.lang]}${p}`);
    if (s.reserved_break_period === p) o.setAttribute("selected", "");
    breakSel.append(o);
  }
  panel().append(
    head(state.lang === "hy" ? "Կարգավորումներ" : "Settings",
      state.lang === "hy" ? "Ուսումնական տարվա հիմնական պարամետրերը։ Թվերը կարող եք փոխել ձեր դպրոցին համապատասխան։"
                          : "Basic parameters for the school year. Every number here is adjustable."),
    el("div", { class: "card" },
      el("div", { class: "grid2" },
        field(state.lang === "hy" ? "Ուսումնական տարի" : "School year",
          el("input", { type: "text", value: s.year, placeholder: "2024-2025",
            on: { input: e => (s.year = e.target.value) } })),
        field(state.lang === "hy" ? "Դասաժամեր օրական" : "Periods per day",
          el("input", { type: "number", min: 1, max: 12, value: s.periods_per_day,
            on: { input: e => { s.periods_per_day = Math.max(1, +e.target.value || 1); render(); } } })),
        field(state.lang === "hy" ? "Ընդմիջման ֆիքսված ժամ" : "Reserved break period", breakSel,
          state.lang === "hy" ? "Ընտրեք, եթե դպրոցը պահում է ազատ ընդմիջման ժամ" : "For schools that keep a fixed free period"),
        field(state.lang === "hy" ? "Հաշվարկի ժամանակը (վրկ)" : "Solver time budget (s)",
          el("input", { type: "number", min: 3, max: 120, value: state.maxSeconds,
            on: { input: e => (state.maxSeconds = Math.max(3, +e.target.value || 20)) } }),
          state.lang === "hy" ? "Ավելի շատ ժամանակ = ավելի հարթ դասացուցակ" : "More time = a more polished timetable"),
      )),
    el("div", { class: "card" },
      el("span", { class: "eyebrow" }, state.lang === "hy" ? "Կանոնակարգային հիմք" : "Regulatory basis"),
      el("p", { class: "sub", style: "margin-top:8px" },
        state.lang === "hy"
          ? "Ուսուցչի շաբաթական բեռնվածությունը՝ 18ժ (տարրական) / 20ժ, աշակերտի շաբաթական ծանրաբեռնվածությունը՝ ըստ դասարանի (մինչև 34 դաս/շաբաթ), 5-օրյա շաբաթ։ Բոլոր սահմանները կարգավորելի են։"
          : "Teacher load 18h (primary) / 20h, student weekly load graduated by grade (up to 34/week), 5-day week. All limits are configurable.")),
  );
}
function field(label, control, hint) {
  return el("div", { class: "field" }, el("label", {}, label), control, hint ? el("div", { class: "hint" }, hint) : null);
}

/* ---- Subjects ---- */
function secSubjects() {
  const rows = subjectEntries().map(([sid, s]) => {
    const rtSel = el("select", { on: { change: e => (s.requires_room_type = e.target.value || null) } },
      el("option", { value: "" }, state.lang === "hy" ? "—" : "—"));
    ROOM_TYPES.forEach(rt => {
      const o = el("option", { value: rt }, ROOM_TYPE_LABEL[state.lang][rt]);
      if (s.requires_room_type === rt) o.setAttribute("selected", "");
      rtSel.append(o);
    });
    return el("tr", {},
      el("td", {}, el("span", { class: "id-pill" }, sid)),
      el("td", {}, el("input", { type: "text", value: s.name_hy || "", placeholder: "Հայերեն",
        on: { input: e => (s.name_hy = e.target.value) } })),
      el("td", {}, el("input", { type: "text", value: s.name_en || "", placeholder: "English",
        on: { input: e => (s.name_en = e.target.value) } })),
      el("td", { class: "num" }, el("input", { type: "number", min: 1, max: 5, value: s.difficulty ?? 3, class: "cell",
        on: { input: e => (s.difficulty = clampInt(e.target.value, 1, 5, 3)) } })),
      el("td", {}, rtSel),
      el("td", { class: "num" }, checkbox(!!s.is_pe, v => (s.is_pe = v))),
      el("td", { class: "num" }, el("input", { type: "number", min: 1, max: 4, value: s.max_consecutive ?? 1, class: "cell",
        on: { input: e => (s.max_consecutive = clampInt(e.target.value, 1, 4, 1)) } })),
      el("td", { class: "num" }, el("input", { type: "number", min: 1, max: 4, value: s.max_per_day ?? 1, class: "cell",
        on: { input: e => (s.max_per_day = clampInt(e.target.value, 1, 4, 1)) } })),
      el("td", { class: "act" }, rmBtn(() => { delete state.school.subjects[sid]; cleanupSubject(sid); render(); })),
    );
  });
  const H = state.lang === "hy"
    ? ["ID", "Անվանումը", "English", "Դժվ.", "Սենյակ", "Ֆիզկ.", "Իրար հետև", "Օրական"]
    : ["ID", "Name", "English", "Diff.", "Room", "PE", "Consec.", "Per day"];
  panel().append(
    head(t("navSubjects"),
      state.lang === "hy" ? "Դպրոցի առարկաները։ «Դժվ.» = դժվարություն 1–5 (4–5-ը դրվում են առավոտյան)։ «Սենյակ» = պարտադիր մասնագիտացված սենյակ։"
                          : "School subjects. Diff. = difficulty 1–5 (4–5 get morning slots). Room = required specialised room."),
    dataTable(H, rows, 9),
    el("div", { class: "addrow" }, el("button", { class: "btn subtle small", on: { click: addSubject } }, "+ " + t("add"))),
  );
}
function addSubject() {
  const id = uid("s");
  state.school.subjects[id] = { name_hy: "", name_en: "", difficulty: 3, requires_room_type: null, is_pe: false, max_consecutive: 1, max_per_day: 1 };
  render();
}
function cleanupSubject(sid) {
  for (const [, c] of classEntries()) delete c.weekly_hours[sid];
  for (const [, tt] of teacherEntries()) tt.qualified_subjects = (tt.qualified_subjects || []).filter(x => x !== sid);
}

/* ---- Rooms ---- */
function secRooms() {
  const rows = roomEntries().map(([rid, r]) => {
    const typeSel = el("select", { on: { change: e => (r.type = e.target.value) } });
    ROOM_TYPES.forEach(rt => {
      const o = el("option", { value: rt }, ROOM_TYPE_LABEL[state.lang][rt]);
      if (r.type === rt) o.setAttribute("selected", "");
      typeSel.append(o);
    });
    return el("tr", {},
      el("td", {}, el("span", { class: "id-pill" }, rid)),
      el("td", {}, el("input", { type: "text", value: r.name || "", placeholder: state.lang === "hy" ? "Անվանումը" : "Name",
        on: { input: e => (r.name = e.target.value) } })),
      el("td", {}, typeSel),
      el("td", { class: "act" }, rmBtn(() => { delete state.school.rooms[rid]; cleanupRoom(rid); render(); })),
    );
  });
  const H = state.lang === "hy" ? ["ID", "Անվանումը", "Տեսակը"] : ["ID", "Name", "Type"];
  panel().append(
    head(t("navRooms"),
      state.lang === "hy" ? "Դասասենյակները և մասնագիտացված սենյակները (լաբորատորիա, մարզադահլիճ, համակարգչային)։"
                          : "Classrooms and specialised rooms (labs, gym, computer room)."),
    dataTable(H, rows, 4),
    el("div", { class: "addrow" }, el("button", { class: "btn subtle small", on: { click: addRoom } }, "+ " + t("add"))),
  );
}
function addRoom() {
  const id = uid("r");
  state.school.rooms[id] = { name: "", type: "classroom" };
  render();
}
function cleanupRoom(rid) {
  for (const [, c] of classEntries()) if (c.home_room === rid) c.home_room = "";
}

/* ---- Classes: meta + curriculum matrix (signature) ---- */
function secClasses() {
  const subs = subjectEntries();
  const cls = classEntries();
  panel().append(head(t("navClasses"),
    state.lang === "hy" ? "Ուսումնական պլանը՝ դասարան × առարկա = շաբաթական ժամ։ Տողի գումարը կարմրում է, եթե անցնում է դասարանի առավելագույն շաբաթական բեռը։"
                        : "The curriculum: class × subject = weekly hours. A row total turns red if it exceeds the grade's weekly ceiling."));

  if (!subs.length) {
    panel().append(
      el("div", { class: "empty-note" }, state.lang === "hy" ? "Նախ ավելացրեք առարկաներ։" : "Add subjects first."),
      classAddRow());
    return;
  }

  const thead = el("tr", {},
    el("th", { class: "corner rowhead" }, state.lang === "hy" ? "Դասարան" : "Class"));
  subs.forEach(([sid, s]) => thead.append(el("th", { class: "subjcol", title: nm(s) || sid }, nm(s) || sid)));
  thead.append(el("th", { class: "totcol" }, state.lang === "hy" ? "Գումար" : "Total"));
  thead.append(el("th", { class: "totcol" }, ""));

  const body = el("tbody");
  cls.forEach(([cid, c]) => {
    const homeSel = el("select", { title: state.lang === "hy" ? "Հիմնական սենյակ" : "Home room",
      on: { change: e => (c.home_room = e.target.value) } });
    homeSel.append(el("option", { value: "" }, "—"));
    roomEntries().forEach(([rid, r]) => {
      const o = el("option", { value: rid }, r.name || rid);
      if (c.home_room === rid) o.setAttribute("selected", "");
      homeSel.append(o);
    });
    const totalCell = el("td", { class: "total" });
    const rowhead = el("th", { class: "rowhead" },
      el("input", { type: "text", value: cid, class: "cid", style: "width:70px;font-weight:700",
        title: state.lang === "hy" ? "Դասարանի անունը" : "Class name",
        on: { change: e => renameClass(cid, e.target.value) } }),
      el("div", { class: "meta" },
        el("input", { type: "number", min: 1, max: 12, value: c.grade, title: state.lang === "hy" ? "Դասարան (թիվ)" : "Grade",
          on: { input: e => { c.grade = clampInt(e.target.value, 1, 12, c.grade); recalcRow(); } } }),
        homeSel));

    const tr = el("tr", {}, rowhead);
    function recalcRow() {
      const total = subs.reduce((a, [sid]) => a + (c.weekly_hours[sid] || 0), 0);
      const ceil = gradeCeiling(c.grade);
      totalCell.textContent = `${total}/${ceil}`;
      totalCell.classList.toggle("over", total > ceil);
    }
    subs.forEach(([sid]) => {
      const cell = el("td", { class: "hourcell" });
      const inp = el("input", { type: "number", min: 0, max: 12, class: "cell",
        value: c.weekly_hours[sid] || "",
        on: { input: e => {
          const v = clampInt(e.target.value, 0, 12, 0);
          if (v) c.weekly_hours[sid] = v; else delete c.weekly_hours[sid];
          cell.classList.toggle("has", !!v); recalcRow();
        } } });
      if (c.weekly_hours[sid]) cell.classList.add("has");
      cell.append(inp); tr.append(cell);
    });
    tr.append(totalCell);
    tr.append(el("td", { class: "actcell" }, rmBtn(() => { delete state.school.classes[cid]; render(); })));
    recalcRow();
    body.append(tr);
  });

  const table = el("table", { class: "matrix" }, el("thead", {}, thead), body,
    el("tfoot", {}, el("tr", {}, el("td", { colspan: subs.length + 3 },
      state.lang === "hy" ? "Դատարկ վանդակ = առարկան չի դասավանդվում այդ դասարանում" : "Empty cell = subject not taught in that class"))));
  panel().append(el("div", { class: "matrix-wrap" }, table), classAddRow());
}
function classAddRow() {
  return el("div", { class: "addrow" },
    el("button", { class: "btn subtle small", on: { click: addClass } }, "+ " + t("add")),
    el("button", { class: "btn subtle small", on: { click: addGrades1to12 } },
      state.lang === "hy" ? "Ավելացնել 1–12 դասարանները" : "Add grades 1–12"));
}
function addClass() {
  const id = nextClassName();
  state.school.classes[id] = { grade: 7, home_room: "", weekly_hours: {} };
  render();
}
function addGrades1to12() {
  let added = 0;
  for (let g = 1; g <= 12; g++) {
    const name = String(g);
    if (state.school.classes[name]) continue;     // don't clobber an existing class
    state.school.classes[name] = { grade: g, home_room: "", weekly_hours: {} };
    added++;
  }
  render();
  toast(state.lang === "hy"
    ? (added ? `Ավելացվեց ${added} դասարան` : "Բոլոր 1–12 դասարաններն արդեն կան")
    : (added ? `Added ${added} class${added === 1 ? "" : "es"}` : "Grades 1–12 already exist"));
}
function nextClassName() {
  let i = Object.keys(state.school.classes).length + 1;
  let name = `Դ${i}`;
  while (state.school.classes[name]) { i++; name = `Դ${i}`; }
  return name;
}
function renameClass(oldId, newId) {
  newId = (newId || "").trim();
  if (!newId || newId === oldId) { render(); return; }
  if (state.school.classes[newId]) { toast(state.lang === "hy" ? "Այդ անունն արդեն կա" : "That name already exists", true); render(); return; }
  const obj = state.school.classes[oldId];
  delete state.school.classes[oldId];
  state.school.classes[newId] = obj;
  render();
}

/* ---- Teachers ---- */
function secTeachers() {
  const subs = subjectEntries();
  const rows = teacherEntries().map(([tid, tch]) => {
    tch.qualified_subjects = tch.qualified_subjects || [];
    tch.available_days = tch.available_days || [];
    tch.available_periods = tch.available_periods || [];

    // qualified subjects as chips + add dropdown
    const chips = el("div", { class: "chips" });
    tch.qualified_subjects.forEach(sid => {
      const s = state.school.subjects[sid];
      chips.append(el("span", { class: "chip" }, (s ? nm(s) : sid),
        el("button", { title: t("remove"), on: { click: () => { tch.qualified_subjects = tch.qualified_subjects.filter(x => x !== sid); render(); } } }, "×")));
    });
    const remaining = subs.filter(([sid]) => !tch.qualified_subjects.includes(sid));
    if (remaining.length) {
      const sel = el("select", { class: "chip add", style: "appearance:auto;border-radius:20px",
        on: { change: e => { if (e.target.value) { tch.qualified_subjects.push(e.target.value); render(); } } } },
        el("option", { value: "" }, "+ " + (state.lang === "hy" ? "առարկա" : "subject")));
      remaining.forEach(([sid, s]) => sel.append(el("option", { value: sid }, nm(s) || sid)));
      chips.append(sel);
    }

    const roleSel = el("select", { on: { change: e => (tch.role = e.target.value) } });
    ["primary", "subject", "admin"].forEach(r => {
      const o = el("option", { value: r }, ROLE_LABEL[state.lang][r]);
      if ((tch.role || "subject") === r) o.setAttribute("selected", "");
      roleSel.append(o);
    });

    // availability: per-weekday choose-your-periods editor
    const availCell = availabilityEditor(tch, periodsPerDay());

    return el("tr", {},
      el("td", {}, el("input", { type: "text", value: tch.name || "", placeholder: state.lang === "hy" ? "Անուն Ազգանուն" : "Full name",
        on: { input: e => (tch.name = e.target.value) } })),
      el("td", { style: "min-width:230px" }, chips),
      el("td", {}, roleSel),
      el("td", { class: "num" }, el("input", { type: "number", min: 1, max: 36, class: "cell",
        value: tch.max_weekly_load ?? "", placeholder: state.lang === "hy" ? "ավտո" : "auto",
        title: state.lang === "hy" ? "Դատարկ = ըստ դերի (18/20)" : "Empty = by role (18/20)",
        on: { input: e => (tch.max_weekly_load = e.target.value ? clampInt(e.target.value, 1, 36, null) : null) } })),
      el("td", {}, availCell),
      el("td", { class: "act" }, rmBtn(() => { delete state.school.teachers[tid]; render(); })),
    );
  });
  const H = state.lang === "hy"
    ? ["Անուն", "Որակավորում (առարկաներ)", "Դեր", "Բեռ/շաբ", "Հասանելիություն"]
    : ["Name", "Qualified subjects", "Role", "Load/wk", "Availability"];
  panel().append(
    head(t("navTeachers"),
      state.lang === "hy" ? "Ուսուցիչներն ու իրենց որակավորումները։ Դասերն ինքնաշխատ բաշխվում են որակավորման հիման վրա, եթե ձեռքով չեք ամրագրում։"
                          : "Teachers and their qualifications. Lessons are auto-assigned from qualifications unless you pin them."),
    dataTable(H, rows, 6),
    el("p", { class: "sub", style: "margin-top:8px" },
      state.lang === "hy"
        ? "Հասանելիություն․ սեղմեք օրվա պիտակին՝ ամբողջ օրն անջատելու/միացնելու համար, կամ առանձին ժամերի վրա։ Լրացված = հասանելի (լռելյայն՝ բոլոր ժամերը)։"
        : "Availability: click a weekday label to switch the whole day off/on, or click individual periods. Filled = available (default is every period)."),
    el("div", { class: "addrow" }, el("button", { class: "btn subtle small", on: { click: addTeacher } }, "+ " + t("add"))),
  );
}

/* periods available in the current school (used to size the availability grid) */
function periodsPerDay() { return Math.max(1, state.school.periods_per_day || 7); }

/* Build the per-weekday period editor for one teacher. */
function availabilityEditor(tch, P) {
  migrateAvailability(tch, P);
  const map = tch.available_periods_by_day;
  const box = el("div", { class: "availbox" });
  for (let d = 0; d < 5; d++) {
    const dayOff = Object.prototype.hasOwnProperty.call(map, d) && (map[d] || []).length === 0;
    const allowed = dayAllowed(tch, d, P);
    const row = el("div", { class: "avail-day" + (dayOff ? " off" : "") });
    row.append(el("button", { type: "button", title: DAYS[state.lang][d],
      class: "avail-daylabel" + (dayOff ? "" : " on"),
      on: { click: () => toggleDayFull(tch, d, P) } }, DAYS_SHORT[state.lang][d]));
    const pills = el("div", { class: "avail-pills" });
    for (let p = 1; p <= P; p++) {
      const on = !dayOff && allowed.has(p);
      pills.append(el("button", { type: "button", title: PP[state.lang] + p,
        class: "avail-pill" + (on ? " on" : ""),
        on: { click: () => togglePeriod(tch, d, p, P) } }, String(p)));
    }
    row.append(pills);
    box.append(row);
  }
  return box;
}

/* Periods allowed for a day, as a Set. Absent day => every period. */
function dayAllowed(tch, d, P) {
  const map = tch.available_periods_by_day || {};
  if (Object.prototype.hasOwnProperty.call(map, d)) return new Set(map[d] || []);
  return new Set(Array.from({ length: P }, (_, i) => i + 1));
}

/* Toggle a single period for one weekday. */
function togglePeriod(tch, d, period, P) {
  const map = tch.available_periods_by_day = tch.available_periods_by_day || {};
  const cur = dayAllowed(tch, d, P);
  if (cur.has(period)) cur.delete(period); else cur.add(period);
  const arr = Array.from(cur).sort((a, b) => a - b);
  if (arr.length === P) delete map[d];   // full day => default (store nothing)
  else map[d] = arr;                      // [] => whole day off
  render();
}

/* Toggle a whole weekday off/on. */
function toggleDayFull(tch, d, P) {
  const map = tch.available_periods_by_day = tch.available_periods_by_day || {};
  const dayOff = Object.prototype.hasOwnProperty.call(map, d) && (map[d] || []).length === 0;
  if (dayOff) delete map[d];   // turn the day fully on
  else map[d] = [];            // turn the day fully off
  render();
}

/* One-time conversion of legacy available_days/available_periods into the
   per-weekday model so older data (and the sample) shows correctly. */
function migrateAvailability(tch, P) {
  const cur = tch.available_periods_by_day;
  if (cur && typeof cur === "object" && !Array.isArray(cur)) return;  // already new-style
  const map = {};
  const days = (tch.available_days && tch.available_days.length) ? tch.available_days.slice() : [0, 1, 2, 3, 4];
  const periods = (tch.available_periods && tch.available_periods.length) ? tch.available_periods.slice() : null;
  for (let d = 0; d < 5; d++) {
    if (!days.includes(d)) { map[d] = []; continue; }      // legacy day-off
    if (periods) {
      const allowed = periods.filter(p => p >= 1 && p <= P).sort((a, b) => a - b);
      if (allowed.length !== P) map[d] = allowed;           // legacy period restriction
    }
  }
  tch.available_periods_by_day = map;
  tch.available_days = [];
  tch.available_periods = [];
}
function addTeacher() {
  const id = uid("t");
  state.school.teachers[id] = { name: "", qualified_subjects: [], role: "subject",
    max_weekly_load: null, available_days: [], available_periods: [], available_periods_by_day: {} };
  render();
}

/* ---- shared widgets ---- */
function dataTable(headers, rows, ncols) {
  const thead = el("thead", {}, el("tr", {}, ...headers.map(h => el("th", {}, h)), el("th", {}, "")));
  const tbody = el("tbody", {}, ...rows);
  if (!rows.length) tbody.append(el("tr", {}, el("td", { colspan: ncols, style: "text-align:center;color:var(--ink-faint);padding:24px" },
    state.lang === "hy" ? "Դեռ ոչինչ չկա" : "Nothing yet")));
  return el("div", { class: "tablewrap" }, el("table", { class: "data" }, thead, tbody));
}
function rmBtn(fn) { return el("button", { class: "btn danger tiny", title: t("remove"), on: { click: fn } }, "✕"); }
function checkbox(checked, fn) {
  const c = el("input", { type: "checkbox", on: { change: e => fn(e.target.checked) } });
  if (checked) c.setAttribute("checked", "");
  return c;
}
function clampInt(v, lo, hi, dflt) { const n = parseInt(v, 10); if (isNaN(n)) return dflt; return Math.min(hi, Math.max(lo, n)); }

/* ================= RESULT ================= */
function secResult() {
  const r = state.result;
  if (!r) { panel().append(el("div", { class: "empty-note" }, state.lang === "hy" ? "Դեռ կազմված դասացուցակ չկա։" : "No timetable yet.")); return; }

  const legal = r.violations.length === 0;
  const banner = el("div", { class: "banner " + (legal ? "ok" : "bad") },
    el("span", { class: "dot" }),
    el("div", {}, el("div", {}, legal
      ? (state.lang === "hy" ? "Օրինական դասացուցակ — բոլոր կանոնները պահպանված են" : "Legal timetable — every rule satisfied")
      : (state.lang === "hy" ? "Դասացուցակը խախտում է կանոնները" : "Timetable violates rules")),
      legal ? null : el("ul", { class: "vlist" }, ...r.violations.slice(0, 12).map(v => el("li", {}, v)))));

  const stat = (k, v, good) => el("div", { class: "stat" + (good ? " good" : "") }, el("div", { class: "k" }, k), el("div", { class: "v" }, v));
  const stats = el("div", { class: "stats" },
    stat(state.lang === "hy" ? "Կարգավիճակ" : "Status", r.status === "OPTIMAL" ? (state.lang === "hy" ? "Օպտիմալ" : "Optimal") : (state.lang === "hy" ? "Վավեր" : "Feasible")),
    stat(state.lang === "hy" ? "Ուս. պատուհաններ" : "Teacher gaps", r.quality.teacher_gaps, r.quality.teacher_gaps === 0),
    stat(state.lang === "hy" ? "Դժվար (կեսօրից հետո)" : "Hard (afternoon)", r.quality.afternoon_hard, r.quality.afternoon_hard === 0),
    stat(state.lang === "hy" ? "Հաշվարկ (վրկ)" : "Solve (s)", r.wall_time.toFixed(1)));

  // controls
  const viewBar = el("div", { class: "pillbar" },
    el("button", { class: state.resultView === "classes" ? "on" : "", on: { click: () => { state.resultView = "classes"; state.resultPick = null; render(); } } }, t("navClasses")),
    el("button", { class: state.resultView === "teachers" ? "on" : "", on: { click: () => { state.resultView = "teachers"; state.resultPick = null; render(); } } }, t("navTeachers")));

  const picker = el("select", { on: { change: e => { state.resultPick = e.target.value; renderGrid(); } } });
  const items = state.resultView === "classes"
    ? classEntries().map(([cid]) => [cid, cid])
    : teacherEntries().filter(([tid]) => r.lessons.some(L => L.teacher_id === tid))
        .map(([tid, tt]) => [tid, tt.name || tid]).sort((a, b) => a[1].localeCompare(b[1], "hy"));
  if (!state.resultPick && items.length) state.resultPick = items[0][0];
  items.forEach(([val, label]) => { const o = el("option", { value: val }, label); if (val === state.resultPick) o.setAttribute("selected", ""); picker.append(o); });

  const dl = el("div", { class: "dl" },
    el("button", { class: "btn subtle small", on: { click: downloadHTML } }, "↓ HTML"),
    el("button", { class: "btn subtle small", on: { click: downloadJSON } }, "↓ JSON"));

  const controls = el("div", { class: "result-controls" }, viewBar, picker, el("span", { class: "spacer" }), dl);
  const gridHost = el("div", { id: "grid-host" });

  panel().append(
    head(t("navResult"), state.school.year ? `${state.school.year}` : "", el("button", { class: "btn primary small", on: { click: solve } }, "↻ " + t("generate"))),
    banner, stats, controls, gridHost,
    el("div", { class: "legend" }, el("span", {}, el("span", { class: "sw", style: "background:var(--hard)" }), state.lang === "hy" ? "դժվար առարկա" : "hard subject")),
  );
  renderGrid();
}

function renderGrid() {
  const host = $("#grid-host"); if (!host) return; clear(host);
  const r = state.result, s = state.school;
  const nDays = 5, lang = state.lang;
  const pick = state.resultPick;
  const filt = state.resultView === "classes" ? (L => L.class_id === pick) : (L => L.teacher_id === pick);
  const cell = {};  // (day,period) -> lesson
  r.lessons.filter(filt).forEach(L => { cell[`${L.day}:${L.period}`] = L; });

  const thead = el("tr", {}, el("th", {}, ""));
  for (let d = 0; d < nDays; d++) thead.append(el("th", {}, DAYS[lang][d]));
  const body = el("tbody");
  for (let p = 1; p <= s.periods_per_day; p++) {
    const tr = el("tr", {}, el("th", {}, `${PP[lang]}${p}`));
    if (s.reserved_break_period === p) {
      tr.append(el("td", { class: "brk", colspan: nDays }, lang === "hy" ? "ընդմիջում" : "break"));
      body.append(tr); continue;
    }
    for (let d = 0; d < nDays; d++) {
      const L = cell[`${d}:${p}`];
      if (!L) { tr.append(el("td", { class: "empty" }, "—")); continue; }
      const subj = s.subjects[L.subject_id] || {};
      const hard = (subj.difficulty || 3) >= (state.defaults ? state.defaults.hard_threshold : 4);
      const td = el("td", { class: "lesson" + (hard ? " hard" : "") });
      if (state.resultView === "classes") {
        td.append(el("span", { class: "s" }, nm(subj) || L.subject_id));
        if (subj.requires_room_type) { const room = s.rooms[L.room_id]; td.append(el("span", { class: "r" }, room ? room.name : L.room_id)); }
        const tch = s.teachers[L.teacher_id]; td.append(el("span", { class: "m" }, tch ? tch.name : L.teacher_id));
      } else {
        td.append(el("span", { class: "m", style: "font-weight:700;color:var(--ink)" }, L.class_id));
        td.append(el("span", { class: "s", style: "font-weight:500" }, nm(subj) || L.subject_id));
      }
      tr.append(td);
    }
    body.append(tr);
  }
  // teacher weekly load footer
  let footer = null;
  if (state.resultView === "teachers") {
    const load = r.lessons.filter(filt).length;
    footer = el("div", { class: "matrix-meta", style: "margin-top:10px" },
      (lang === "hy" ? "Շաբաթական ծանրաբեռնվածություն՝ " : "Weekly load: ") + load);
  }
  host.append(el("div", { class: "tt-wrap" }, el("table", { class: "tt" }, el("thead", {}, thead), body)), footer);
}

/* ================= ACTIONS ================= */
async function solve() {
  const probs = quickCheck();
  if (probs) { toast(probs, true); return; }
  showOverlay(true);
  try {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), 90000); // 90s max
    const res = await fetch("/api/solve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ school: state.school, max_seconds: state.maxSeconds, workers: 8 }),
      signal: ctrl.signal,
    });
    clearTimeout(id);
    const data = await res.json();
    if (!data.ok) { showOverlay(false); reportProblem(data); return; }
    state.result = data; state.resultView = "classes"; state.resultPick = null; state.section = "result";
    showOverlay(false); render();
    toast(data.violations.length === 0
      ? (state.lang === "hy" ? "Դասացուցակը պատրաստ է" : "Timetable ready")
      : (state.lang === "hy" ? "Կազմվեց, բայց կան խախտումներ" : "Generated, but with violations"), data.violations.length > 0);
  } catch (e) { showOverlay(false); toast((state.lang === "hy" ? "Սխալ՝ " : "Error: ") + e.message, true); }
}
function quickCheck() {
  const s = state.school;
  if (!Object.keys(s.subjects).length) return state.lang === "hy" ? "Ավելացրեք գոնե մեկ առարկա" : "Add at least one subject";
  if (!Object.keys(s.rooms).length) return state.lang === "hy" ? "Ավելացրեք գոնե մեկ սենյակ" : "Add at least one room";
  if (!Object.keys(s.classes).length) return state.lang === "hy" ? "Ավելացրեք գոնե մեկ դասարան" : "Add at least one class";
  if (!Object.keys(s.teachers).length) return state.lang === "hy" ? "Ավելացրեք գոնե մեկ ուսուցիչ" : "Add at least one teacher";
  const anyHours = classEntries().some(([, c]) => Object.keys(c.weekly_hours).length);
  if (!anyHours) return state.lang === "hy" ? "Լրացրեք ուսումնական պլանը (ժամերը)" : "Fill in the curriculum hours";
  return null;
}
function reportProblem(data) {
  if (data.stage === "preflight" && data.problems) {
    state.result = { status: "—", objective: 0, wall_time: 0, lessons: [], violations: data.problems, quality: { teacher_gaps: 0, afternoon_hard: 0, class_daily: {} } };
    state.section = "result"; render();
    toast(state.lang === "hy" ? "Մուտքը կազմված չէ լուծելի դասացուցակի համար" : "Input can't yield a legal timetable", true);
    return;
  }
  const msg = data.message || (state.lang === "hy" ? "Չհաջողվեց կազմել" : "Could not generate");
  toast(msg, true);
}

function showOverlay(on) { $("#overlay").hidden = !on; }

async function downloadHTML() {
  try {
    const res = await fetch("/api/export/html", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ school: state.school, lessons: state.result.lessons, lang: state.lang }),
    });
    const data = await res.json();
    saveBlob(data.html, "timetable.html", "text/html");
  } catch (e) { toast("HTML: " + e.message, true); }
}
function downloadJSON() {
  saveBlob(JSON.stringify(state.result.lessons, null, 2), "schedule.json", "application/json");
}
function saveBlob(text, name, type) {
  const a = el("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  document.body.append(a); a.click(); a.remove();
}

async function loadSample() {
  try {
    const res = await fetchWithTimeout("/api/sample");
    const raw = await res.json();
    state.school = normalize(raw); state.result = null; state.section = "settings";
    if (raw.periods_per_day) state.school.periods_per_day = raw.periods_per_day;
    render(); toast(state.lang === "hy" ? "Նմուշը բեռնված է" : "Sample loaded");
  } catch (e) { toast("Sample: " + e.message, true); }
}
function normalize(raw) {
  const s = blankSchool();
  s.year = raw.year || (raw.school && raw.school.year) || "";
  s.periods_per_day = raw.periods_per_day || (raw.school && raw.school.periods_per_day) || 7;
  s.reserved_break_period = raw.reserved_break_period ?? (raw.school && raw.school.reserved_break_period) ?? null;
  s.subjects = raw.subjects || {}; s.rooms = raw.rooms || {};
  s.classes = raw.classes || {}; s.teachers = raw.teachers || {};
  s.assignments = raw.assignments || [];
  for (const [, c] of Object.entries(s.classes)) c.weekly_hours = c.weekly_hours || {};
  return s;
}
function exportSchool() {
  const out = {
    year: state.school.year, periods_per_day: state.school.periods_per_day,
    reserved_break_period: state.school.reserved_break_period,
    subjects: state.school.subjects, rooms: state.school.rooms,
    classes: state.school.classes, teachers: state.school.teachers, assignments: state.school.assignments || [],
  };
  saveBlob(JSON.stringify(out, null, 2), (state.school.year || "school") + ".json", "application/json");
}
function importSchool(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try { state.school = normalize(JSON.parse(reader.result)); state.result = null; state.section = "settings"; render();
      toast(state.lang === "hy" ? "Ներմուծված է" : "Imported"); }
    catch (e) { toast((state.lang === "hy" ? "Անվավեր ֆայլ՝ " : "Invalid file: ") + e.message, true); }
  };
  reader.readAsText(file);
}

/* ================= WIRING ================= */
function wire() {
  document.querySelectorAll(".rail button").forEach(b => b.addEventListener("click", () => {
    if (b.disabled) return; state.section = b.dataset.sec; render();
  }));
  document.querySelectorAll("#lang-toggle button").forEach(b => b.addEventListener("click", () => {
    state.lang = b.dataset.lang; document.documentElement.lang = state.lang; render();
  }));
  $("#btn-sample").addEventListener("click", () => {
    if (hasWork() && !confirm(state.lang === "hy"
      ? "Սա կփոխարինի ձեր ընթացիկ տվյալները նմուշով։ Շարունակե՞լ։"
      : "This will replace your current data with the sample. Continue?")) return;
    loadSample();
  });
  $("#btn-generate").addEventListener("click", solve);
  $("#btn-export").addEventListener("click", exportSchool);
  $("#btn-import").addEventListener("click", () => $("#file-input").click());
  $("#file-input").addEventListener("change", e => { if (e.target.files[0]) importSchool(e.target.files[0]); e.target.value = ""; });
  // auto-save on every edit
  const save = debounce(saveLocal, 350);
  document.addEventListener("input", save);
  document.addEventListener("change", save);
}
function hasWork() {
  const s = state.school;
  return Object.keys(s.subjects).length || Object.keys(s.classes).length ||
         Object.keys(s.teachers).length || Object.keys(s.rooms).length;
}

function fetchWithTimeout(url, ms = 8000) {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { signal: ctrl.signal }).finally(() => clearTimeout(id));
}

async function init() {
  wire();
  try {
    state.defaults = await (await fetchWithTimeout("/api/defaults")).json();
  } catch (e) { state.defaults = null; }

  const saved = loadLocal();
  if (saved) {
    state.school = normalize(saved.school);
    if (saved.lang) { state.lang = saved.lang; document.documentElement.lang = state.lang; }
    if (saved.maxSeconds) state.maxSeconds = saved.maxSeconds;
    render();
    toast(state.lang === "hy" ? "Վերականգնվեց ձեր վերջին աշխատանքը" : "Restored your last work");
  } else {
    try { await loadSample(); } catch (e) {
      state.school = blankSchool(); render();
    }
  }
  // never leave a blank page no matter what
  if (!panel().children.length) { state.school = state.school || blankSchool(); render(); }
}
init();
