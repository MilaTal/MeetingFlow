// Тема планёрки (решения владелицы 24.10.2026, Р1–Р6). Файл-близнец: одинаков до байта в Планёрке и ERP — системы
// выглядят одинаково. Две части: карточка «Темы планёрок» в «Параметры системы» → «Настройки» (суперадминистратор:
// добавить, изменить, выключить; удаления нет) и выпадающий список «Тема планёрки» в строке инструментов подготовки
// встречи (необязательно, можно «без темы»). Выбор человека — «вручную»: сильнее дня недели и шапки эталона секретаря.
// Пользуется общими функциями страницы: api, esc, toast, isSuperAdmin, isAdmin, fmtRuDateTime.

const ТЕМА_ДНИ = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const ТЕМА_ИСТОЧНИК = { "по дню недели": "по дню недели", "из эталона": "из шапки эталона секретаря", "вручную": "выбрано вручную" };
// Слова темы — по системе (дефекты экранов перед видео 25.10.2026, п. 4): в Планёрке «Тема планёрки», в ERP это встреча —
// «Тема встречи». Система — атрибут `data-sistema` у <html> в index.html каждой системы; файл остаётся близнецом до байта.
const ТЕМА_СЛОВА = document.documentElement.dataset.sistema === "erp"
  ? { тема: "Тема встречи", темы: "Темы встреч" }
  : { тема: "Тема планёрки", темы: "Темы планёрок" };
let _темыКэш = null;
let _темыКогда = 0;

function темаСтили() {
  if (document.getElementById("tema-css")) return;
  const s = document.createElement("style");
  s.id = "tema-css";
  s.textContent = `.topic-slot{display:inline-flex;align-items:center;gap:6px;font-size:13px;white-space:nowrap}
.topic-slot select{font-size:13px;padding:3px 6px;max-width:220px}
.topic-slot .topic-src{color:#8a8f98;font-size:12px}
.topic-row{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-bottom:1px solid #eef0f3;flex-wrap:wrap}
.topic-row .topic-n{font-weight:600;min-width:150px}
.topic-row .topic-d{color:#5f6670;font-size:13px;flex:1}
.topic-off{color:#8a8f98}
.topic-days{display:flex;gap:10px;flex-wrap:wrap}
.topic-days label{display:inline-flex;gap:4px;align-items:center;font-weight:400}
.topic-form textarea{width:100%;min-height:64px}`;
  document.head.appendChild(s);
}

async function темыСписок(свежий) {
  if (!свежий && _темыКэш && Date.now() - _темыКогда < 30000) return _темыКэш;
  _темыКэш = (await api("/meeting-topics", { auth: true })).topics || [];
  _темыКогда = Date.now();
  return _темыКэш;
}

function темаДниСловами(дни) {
  return (дни || []).length ? дни.map(d => ТЕМА_ДНИ[d - 1]).join(", ") : "без дня недели";
}

// --- «Настройки» → карточка «Темы планёрок» ---------------------------------------------------------------------------
async function карточкаТемПланёрок($куда) {
  if (!$куда || !isSuperAdmin()) return;
  темаСтили();
  const $к = document.createElement("div");
  $к.className = "card stack";
  $к.id = "meeting-topics-card";
  $куда.appendChild($к);
  await темыКарточкаНарисовать($к);
}

async function темыКарточкаНарисовать($к, правка) {
  let темы;
  try { темы = await темыСписок(true); }
  catch (e) { $к.innerHTML = `<div class="page-sub">${ТЕМА_СЛОВА.темы}: список не получен — ${esc(e.message)}</div>`; return; }
  const строки = темы.map(т => `<div class="topic-row${т.is_active ? "" : " topic-off"}">
      <span class="topic-n">${esc(т.name)}</span>
      <span class="topic-d">${esc(темаДниСловами(т.weekdays))} · разделов ${т.sections.length || "— общие"}${т.carry_same_topic ? " · переходящие с прошлой встречи той же темы" : ""}${т.is_active ? "" : " · выключена"}</span>
      <button type="button" class="btn-sm" data-topic-edit="${т.id}">Изменить</button>
      <button type="button" class="btn-sm" data-topic-toggle="${т.id}">${т.is_active ? "Выключить" : "Включить"}</button></div>`).join("");
  $к.innerHTML = `<div class="doc-heading">${ТЕМА_СЛОВА.темы}</div>
    <div class="page-sub">Решения владелицы 24.10.2026: тема — самостоятельная сущность. День недели темы ставит её по умолчанию
      всем встречам этого дня; шапка эталона секретаря уточняет тему молча; выбор человека на подготовке встречи сильнее
      обоих. Разделы темы заменяют общий скелет протокола, тема пишется в шапку протокола. Удаления нет — тема выключается.</div>
    ${строки || `<div class="page-sub">Тем пока нет — поле «${ТЕМА_СЛОВА.тема}» у встреч пустое.</div>`}
    <div id="topic-form-slot"></div>
    <div><button type="button" class="btn-primary" id="topic-add-btn">+ Добавить тему</button></div>`;
  $к.querySelector("#topic-add-btn").addEventListener("click", () => темаФорма($к, null));
  $к.querySelectorAll("[data-topic-edit]").forEach(b => b.addEventListener("click", () =>
    темаФорма($к, темы.find(т => String(т.id) === b.dataset.topicEdit))));
  $к.querySelectorAll("[data-topic-toggle]").forEach(b => b.addEventListener("click", async () => {
    const т = темы.find(x => String(x.id) === b.dataset.topicToggle);
    b.disabled = true;
    try {
      await api(`/meeting-topics/${т.id}`, { method: "PATCH", auth: true, json: { is_active: !т.is_active } });
      toast(т.is_active ? `Тема «${т.name}» выключена` : `Тема «${т.name}» включена`);
      await темыКарточкаНарисовать($к);
    } catch (e) { toast(e.message, true); b.disabled = false; }
  }));
  if (правка !== undefined) темаФорма($к, правка);
}

function темаФорма($к, т) {
  const $м = $к.querySelector("#topic-form-slot");
  const строки = (список) => esc((список || []).join("\n"));
  $м.innerHTML = `<div class="card stack topic-form">
      <div class="doc-heading">${т ? `Тема «${esc(т.name)}»` : "Новая тема"}</div>
      <div class="field"><label for="topic-name">Название</label><input type="text" id="topic-name" value="${esc(т ? т.name : "")}"></div>
      <div class="field"><label>Дни недели — тема ставится по умолчанию всем встречам этих дней (можно ни одного)</label>
        <div class="topic-days">${ТЕМА_ДНИ.map((д, i) => `<label><input type="checkbox" data-topic-day="${i + 1}"${т && т.weekdays.includes(i + 1) ? " checked" : ""}>${д}</label>`).join("")}</div></div>
      <div class="field"><label for="topic-sections">Структура протокола — разделы по порядку, по одному в строке (пусто — общие разделы; «Задачи» собирает программа)</label>
        <textarea id="topic-sections">${строки(т && т.sections)}</textarea></div>
      <div class="field"><label for="topic-heads">Как называется в шапке секретаря — по одному в строке (кроме названия темы)</label>
        <textarea id="topic-heads">${строки(т && т.head_names)}</textarea></div>
      <div class="field"><label for="topic-objects">Объекты и их порядок — по одному в строке (абзац на объект)</label>
        <textarea id="topic-objects">${строки(т && т.objects)}</textarea></div>
      <div class="field"><label for="topic-hint">Что важно для этой темы — короткий блок подсказки сборки</label>
        <textarea id="topic-hint">${esc(т ? т.hint : "")}</textarea></div>
      <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="topic-carry"${т && т.carry_same_topic ? " checked" : ""}>
        Переходящие задачи и сводка — с прошлой встречи той же темы, а не со вчерашней</label>
      <div style="display:flex;gap:8px"><button type="button" class="btn-primary" id="topic-save">Сохранить</button>
        <button type="button" class="btn-sm" id="topic-cancel">Отмена</button></div></div>`;
  const список = (id) => (document.getElementById(id).value || "").split("\n").map(s => s.trim()).filter(Boolean);
  $м.querySelector("#topic-cancel").addEventListener("click", () => { $м.innerHTML = ""; });
  $м.querySelector("#topic-save").addEventListener("click", async (e) => {
    const кн = e.currentTarget;
    const данные = {
      name: (document.getElementById("topic-name").value || "").trim(),
      weekdays: [...$м.querySelectorAll("[data-topic-day]")].filter(x => x.checked).map(x => parseInt(x.dataset.topicDay, 10)),
      sections: список("topic-sections"), head_names: список("topic-heads"), objects: список("topic-objects"),
      hint: (document.getElementById("topic-hint").value || "").trim(),
      carry_same_topic: document.getElementById("topic-carry").checked,
    };
    if (!данные.name) { toast("Название темы не задано", true); return; }
    кн.disabled = true;
    try {
      await api(т ? `/meeting-topics/${т.id}` : "/meeting-topics", { method: т ? "PATCH" : "POST", auth: true, json: данные });
      toast(т ? `Тема «${данные.name}» сохранена` : `Тема «${данные.name}» добавлена`);
      await темыКарточкаНарисовать($к);
    } catch (err) { toast(err.message, true); кн.disabled = false; }
  });
}

// --- Подготовка встречи → «Тема планёрки» ------------------------------------------------------------------------------
// Строка инструментов подготовки рисуется своим экраном; список ставится в неё после отрисовки (наблюдатель за страницей),
// чтобы правка экрана подготовки и тема не мешали друг другу. Планёрка — «.prep-toolbar» с выбором планёрки «#prep-pick»,
// ERP — строка «.doc-head.prep-bar» на адресе «#meetings/<номер>/protocol» или «…/planprep» (`этоПодготовка` prep.js).
function темаВстречиМесто() {
  const плн = document.querySelector(".prep-toolbar");
  if (плн) {
    const выбор = document.getElementById("prep-pick");
    return выбор ? { $бар: плн, id: выбор.value } : null;
  }
  const erp = document.querySelector(".doc-head.prep-bar");
  const m = location.hash.match(/^#meetings\/(\d+)\/(?:protocol|planprep)/);
  return erp && m ? { $бар: erp, id: m[1] } : null;
}

async function темаВстречиВставить() {
  const место = темаВстречиМесто();
  if (!место) return;
  const есть = место.$бар.querySelector(".topic-slot");
  if (есть && есть.dataset.meeting === String(место.id)) return;
  if (есть) есть.remove();
  темаСтили();
  const $с = document.createElement("span");
  $с.className = "topic-slot";
  $с.dataset.meeting = String(место.id);
  const ещё = место.$бар.querySelector(".tb-more");
  if (ещё) место.$бар.insertBefore($с, ещё); else место.$бар.appendChild($с);
  let темы, моя;
  try { [темы, моя] = await Promise.all([темыСписок(), api(`/meeting-topics/meeting/${место.id}`, { auth: true })]); }
  catch (e) { $с.remove(); return; }
  if (!$с.isConnected) return;
  const можно = (typeof isAdmin === "function" && isAdmin()) || (typeof isDirector === "function" && isDirector());
  const видимые = темы.filter(т => т.is_active || т.id === моя.topic_id);
  const откуда = моя.source ? [ТЕМА_ИСТОЧНИК[моя.source] || моя.source,
    моя.set_at && typeof fmtRuDateTime === "function" ? fmtRuDateTime(моя.set_at) : "",
    моя.source === "вручную" && моя.set_by ? моя.set_by : ""].filter(Boolean).join(" · ") : "";
  $с.innerHTML = `<label for="topic-pick">${ТЕМА_СЛОВА.тема}</label>
    <select id="topic-pick" aria-label="${ТЕМА_СЛОВА.тема}"${можно ? "" : " disabled"}${видимые.length ? "" : ' title="Список тем пуст — темы заводит суперадминистратор в «Настройках»"'}>
      <option value="">без темы</option>${видимые.map(т => `<option value="${т.id}"${т.id === моя.topic_id ? " selected" : ""}>${esc(т.name)}</option>`).join("")}</select>
    ${откуда ? `<span class="topic-src">${esc(откуда)}</span>` : ""}`;
  $с.querySelector("select").addEventListener("change", async (e) => {
    const $в = e.currentTarget;
    $в.disabled = true;
    try {
      const итог = await api(`/meeting-topics/meeting/${место.id}`, { method: "PUT", auth: true,
        json: { topic_id: $в.value ? parseInt($в.value, 10) : null } });
      toast(итог.name ? `${ТЕМА_СЛОВА.тема} — «${итог.name}»: протоколы, собранные после выбора, пойдут по ней` : `${ТЕМА_СЛОВА.тема} снята`);
      $с.remove();
      темаВстречиВставить();
    } catch (err) { toast(err.message, true); $в.disabled = false; }
  });
}

(function темаНаблюдать() {
  let ждёт = false;
  const пройти = () => { ждёт = false; темаВстречиВставить(); };
  new MutationObserver(() => { if (!ждёт) { ждёт = true; requestAnimationFrame(пройти); } })
    .observe(document.getElementById("main") || document.body, { childList: true, subtree: true });
  window.addEventListener("hashchange", () => setTimeout(темаВстречиВставить, 0));
})();
