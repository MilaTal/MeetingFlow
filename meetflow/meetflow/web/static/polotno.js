// Правка на полотне — единственный способ правки документа (решение владелицы 24.10.2026 после пробы на :8015: «Правка на
// полотне — выглядит хорошо, делаем так… все части, где у нас уже есть правка на панели, оттуда убрать и заменить везде на
// правку на полотне»; дополнение того же дня — статус, новая задача и снятие тоже в таблице задач протокола).
//
// Документ остаётся показом. Переключатель «Просмотр / Правка» стоит там, где была кнопка «Правка». В режиме «Правка»:
// щелчок по абзацу, пункту или заголовку — поле на месте той же ширины (Enter — сохранить, Shift+Enter — новая строка,
// Esc — отмена); ячейки таблицы задач — формулировка, исполнитель (подсказки из «Команды», отдел — текстом), срок
// дд.мм.гггг с проверкой; значок статуса в строке — «в работе / выполнена / снята» (снята — с причиной на месте; снятая
// строка уходит из таблицы и больше нигде не показывается — решение владелицы 26.10.2026, сервер её не отдаёт в показе);
// «+ задача» внизу таблицы поручений встречи; сомнительные строки встречи (задачи «под
// вопросом» и «Возможные поручения») — курсивом на своём месте по порядку обсуждения, правятся на месте как обычные, «В
// задачу» сохраняет поправленное и подтверждает одной транзакцией, «Убрать» — снимает (в документе, просмотре и Word их
// нет); таблетка «оперативная» рядом со статусом — пометка задачи одним нажатием (решение владелицы 26.10.2026: раздел
// «Оперативные задачи» таблицы протокола собирает показ); реестр корректировок — под документом. Строки «из материала» и абзацы, собранные при показе, помечены и не
// правятся. Сервер: POST <документ>/edits — набор правок одной транзакцией (`services/pravka_polotno.py`).
//
// Сеанс правки (решение владелицы 24.10.2026, п. 3): правки текста копятся в черновике, «Готово» делает из него новую
// действующую версию (прежняя — в базе), «Отменить правки» — убирает черновик. Пока «Готово» не нажато, «Просмотр» и Word —
// прежняя версия. Поля задач уходят в реестр сразу, строку протокола следом меняет реестр (п. 2). Отдельный модуль: при
// переходе на редактор (п. 1) заменяется целиком.
//
// Файл — близнец в Планёрке и ERP (frontend/polotno.js), сверяется аудитом зеркальности до байта. Опирается на общие для
// обеих систем `api`, `esc`, `toast`, `confirmDialog`, `fmtRuDateTime`, `allUsers` и `renderDocHtml(md, { источник: true })`.

const ППОДСКАЗКА = "Щёлкните по абзацу, формулировке, исполнителю, сроку или статусу задачи. Enter — сохранить, Esc — отменить.";
const ПСТАТУСЫ = [["active", "в работе"], ["done", "выполнена"], ["dropped", "снята"]];

function полотноКлюч(base) { return `polotno:${base}`; }
function полотноРежим(base, новый) {
  if (новый) {
    try { sessionStorage.setItem(полотноКлюч(base), новый); } catch (e) { /* без памяти вкладки — режим до перерисовки */ }
    return новый;
  }
  try { return sessionStorage.getItem(полотноКлюч(base)) === "edit" ? "edit" : "view"; } catch (e) { return "view"; }
}
// Переключатель на месте прежней кнопки «Правка»: два положения, нажатое — «pill-on»
function полотноПереключатель(base, режим, класс = "") {
  return `<span class="pp-switch ${класс}"${класс ? ` id="${класс}"` : ""} role="group" aria-label="Режим документа" data-pp-base="${esc(base)}">`
    + [["view", "Просмотр"], ["edit", "Правка"]].map(([к, имя]) =>
      `<button type="button" class="pill${к === режим ? " pill-on" : ""}" data-pp-mode="${к}" aria-pressed="${к === режим}">${имя}</button>`).join("")
    + `</span>`;
}
// Щелчок по переключателю: режим запоминается для документа, экран перерисовывается его же функцией
function полотноПодключитьПереключатель(корень, перерисовать) {
  (корень || document).querySelectorAll(".pp-switch [data-pp-mode]").forEach(b => b.addEventListener("click", () => {
    const base = b.closest(".pp-switch").dataset.ppBase;
    if (b.dataset.ppMode === полотноРежим(base)) return;
    полотноРежим(base, b.dataset.ppMode);
    перерисовать();
  }));
}

const ппОдной = (т) => String(т || "").replace(/\s+/g, " ").trim();
// Сверка «этот абзац хранится в документе»: пробелы любые, дата дд.мм.гггг совпадает с дд.мм.гг (показ дописывает век)
const ппСверка = (т) => ппОдной(т).replace(/(\b\d{2}\.\d{2}\.)20(\d{2})(?!\d)/g, "$1$2");
function ппЗначение(el) {
  const начало = ппОдной(el.dataset.pre || "");
  const всё = ппОдной(el.dataset.src);
  return начало && всё.startsWith(начало) ? всё.slice(начало.length).trim() : всё;
}
function ппСрок(значение) {
  const т = String(значение || "").trim();
  if (!т || т.toLowerCase() === "не указан") return { ok: true, value: "" };
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(т);
  if (!m) return { ok: false, msg: "Срок — в виде дд.мм.гггг, например 30.10.2026" };
  const d = new Date(+m[3], +m[2] - 1, +m[1]);
  if (d.getFullYear() !== +m[3] || d.getMonth() !== +m[2] - 1 || d.getDate() !== +m[1]) return { ok: false, msg: "Такой даты нет в календаре" };
  return { ok: true, value: т };
}
// Строка остаётся на своём месте экрана, когда открывается или закрывается поле на месте (26.10.2026, «страница откатывается»):
// поле в ячейке меняет раскладку таблицы — колонки пересчитывают ширины, строки над полем становятся ниже или выше, и
// строка уезжала (замер: на 104 px при открытии поля исполнителя). Сдвиг возвращается прокруткой окна.
function ппДержатьМесто(эл, действие) {
  const до = эл && эл.isConnected ? эл.getBoundingClientRect().top : null;
  действие();
  if (до === null || !эл.isConnected) return;
  const сдвиг = эл.getBoundingClientRect().top - до;
  if (Math.abs(сдвиг) > 1) window.scrollBy(0, сдвиг);
}
function ппАвтоВысота(ta) { ta.style.height = "auto"; ta.style.height = Math.max(ta.scrollHeight + 2, 38) + "px"; }
const ппСтрокаТаблицы = (т) => (String(т || "").trim().startsWith("|")
  ? String(т).trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()).filter(Boolean).join(" · ") : String(т || ""));
function ппКолонки(таб) {
  const шапка = [...таб.querySelectorAll("thead th")].map(th => th.textContent.trim().toLowerCase());
  const найти = (...слова) => шапка.findIndex(т => слова.some(с => т.includes(с)));
  return { шапка, описание: найти("задач", "описан", "формулир", "поручен"), исполнитель: найти("ответствен", "исполнит"),
    срок: найти("срок") };
}
function ппСписокЛюдей() {
  if (document.getElementById("pp-people")) return;
  const список = document.createElement("datalist");
  список.id = "pp-people";
  список.innerHTML = (typeof allUsers !== "undefined" ? allUsers : []).filter(u => u.is_active !== false && !u.is_external)
    .map(u => `<option value="${esc(u.full_name)}">`).join("");
  document.body.appendChild(список);
}

// Место решения задачи «под вопросом» и возможного поручения — «Разбор» (решение владелицы 25.10.2026). Курсив и «В задачу /
// Убрать» на полотне остаются — это правка документа (24.10.2026), решение пишется в те же данные, что и в «Разборе»; рядом
// ссылка на общую очередь.
const РЕШИТЬ_В_РАЗБОРЕ = ` <a class="pp-razbor" href="#razbor/tasks" title="Задачи под вопросом и возможные поручения всех встреч — в одной очереди">решить в «Разборе»</a>`;

// Включить правку на полотне. опц: { base — адрес документа (/meetings/5/minutes), md — текст показа, подготовить(md),
// перерисовать() — экран после сохранения, встреча — номер встречи документа (своя таблица поручений), место — куда
// положить реестр корректировок (иначе — после документа),
// заметка — { quote } открыть поле у абзаца с этим фрагментом, послеСохранения(ответ), после(док) — дообработка показа }.

async function полотноВключить(док, опц) {
  if (!док) return null;
  let ctx;
  try { ctx = await api(`${опц.base}/edit-context`, { auth: true }); }
  catch (e) { toast(e.message, true); return null; }
  if (!док.isConnected) return null;
  ппСписокЛюдей();
  // в режиме правки — текст черновика сеанса (если он есть), его отдаёт сервер уже в виде показа
  const показ = ctx.display_md != null ? ctx.display_md : (опц.md || "");
  const md = опц.подготовить ? опц.подготовить(показ) : показ;
  if (ctx.draft_note) toast(ctx.draft_note, true);
  док.setAttribute("data-no-collapse", "");     // в режиме правки таблица задач целиком: «+ задача» и курсивные строки видны
  док.innerHTML = renderDocHtml(md, { источник: true });
  док.classList.add("pp-edit");
  if (опц.после) опц.после(док);
  // Полоса режима и реестр корректировок — вокруг документа вместе с колонкой замечаний (ERP), а не внутри неё
  const рамка = док.closest(".doc-with-notes:not(.mt-layout)") || док;
  const исходник = ппСверка(ctx.source_md);
  const состояние = { флажок: true };
  const сохранить = async (ops) => {
    try {
      const ответ = await api(`${опц.base}/edits`, { method: "POST", auth: true,
        json: { version_id: ctx.version_id, ops, is_processing_error_fix: состояние.флажок } });
      toast(ops.some(о => о.kind === "block" || о.kind === "new_task" || о.kind === "confirm_possible")
        ? "Сохранено в черновик правок — «Готово» сделает новую версию" : "Сохранено в реестре и в строке протокола");
      if (опц.послеСохранения) await опц.послеСохранения(ответ);
      опц.перерисовать();
      return true;
    } catch (e) {
      // причина отказа — словами сервера (409 — с именем того, кто успел раньше); документ не изменился
      toast(`Правка не сохранена: ${e.message} Документ не изменился.`, true);
      if (e.status === 409) опц.перерисовать();
      return false;
    }
  };
  // Абзацы: собранные при показе (справка из материалов, разделы из единиц) в тексте документа не хранятся — не правятся
  let вСправке = false;
  док.querySelectorAll("[data-src], .doc-heading").forEach(el => {
    if (el.classList.contains("doc-heading")) вСправке = /^Справочно/i.test(el.textContent.trim());
    if (!el.dataset.src) return;
    if (вСправке || !исходник.includes(ппСверка(el.dataset.src))) {
      delete el.dataset.src; delete el.dataset.pre;
      el.classList.add("pp-fixed");
      el.title = "Собрано при показе из материалов или реестра — в тексте документа не хранится, не правится";
    }
  });
  // Строки таблиц задач → задача реестра
  const поСтроке = new Map(ctx.rows.map(r => [r.line, r]));
  let таблицаЗадач = null;
  док.querySelectorAll("table.doc-table").forEach(таб => {
    const кол = ппКолонки(таб);
    if (кол.описание < 0) return;
    let своих = 0;
    таб.querySelectorAll("tbody tr[data-line]").forEach(tr => {
      const r = поСтроке.get(tr.dataset.line);
      if (!r) return;
      const ячейка = tr.children[кол.описание];
      if (r.kind !== "task") {
        tr.classList.add(r.kind === "material" ? "pp-material" : "pp-unlinked");
        ячейка?.insertAdjacentHTML("beforeend", `<span class="doc-cell-sub pp-why">${esc(r.why)}</span>`);
        return;
      }
      своих += String(r.task.source_meeting_id) === String(опц.встреча) ? 1 : 0;
      tr.dataset.task = String(r.task.id);
      tr._pp = r;
      if (r.doubt) {
        // «под вопросом», уже стоящая строкой документа: курсивом, правка полей копится до «В задачу» (одна транзакция)
        tr.classList.add("pp-doubt");
        tr._ppd = { p: Object.assign({}, r.task, { source: "uq", mark: "под вопросом", why: r.doubt }), поля: {} };
        ячейка?.insertAdjacentHTML("beforeend", ` <span class="pp-dmark" title="${esc(r.doubt)}">под вопросом</span><span class="doc-cell-sub">${esc(r.doubt)}</span>`
          + `<span class="pp-acts pp-doubt-acts"><button type="button" class="btn-sm" data-pp-yes>В задачу</button>`
          + `<button type="button" class="btn-sm pp-del" data-pp-no>Убрать</button>${РЕШИТЬ_В_РАЗБОРЕ}</span>`);
      }
      [["описание", "description"], ["исполнитель", "responsible"], ["срок", "due"]].forEach(([к, поле]) => {
        const td = кол[к] >= 0 ? tr.children[кол[к]] : null;
        if (td) { td.classList.add("pp-cell"); td.dataset.field = поле; }
      });
      ячейка?.insertAdjacentHTML("beforeend", `<span class="pp-row-acts"><button type="button" class="pp-st pp-st-${esc(r.task.status)}" data-pp-st title="${esc(r.task.status_detail || "Статус задачи в реестре — щёлкните, чтобы изменить")}">${esc(r.task.status_label)}</button>`
        + `<button type="button" class="pp-st pp-op${r.task.operational ? " pp-op-on" : ""}" data-pp-op aria-pressed="${!!r.task.operational}" title="${r.task.operational
          ? "Оперативная задача — щёлкните, чтобы снять пометку" : "Отметить задачу оперативной — в протоколе она встанет в раздел «Оперативные задачи»"}">${r.task.operational ? "оперативная ✓" : "в оперативные"}</button>`
        + (r.in_doc ? "" : `<span class="doc-cell-sub">правка — только в реестре: строка собрана при показе</span>`) + `</span>`);
    });
    if (!таблицаЗадач || своих > таблицаЗадач.своих) таблицаЗадач = { таб, кол, своих };
  });
  // «+ задача» — последней строкой таблицы поручений встречи; сомнительные строки — курсивом на своём месте по порядку
  // обсуждения (после своей строки, что прозвучала раньше), места нет — в конце строк поручений встречи
  if (таблицаЗадач) {
    const { таб, кол } = таблицаЗадач;
    const n = кол.шапка.length;
    const tb = таб.querySelector("tbody");
    const своиСтроки = [...tb.querySelectorAll("tr[data-task]")].filter(tr => String(tr._pp.task.source_meeting_id) === String(опц.встреча));
    let конецСвоих = своиСтроки[своиСтроки.length - 1] || null;
    if (ctx.own_tasks) {
      const строка = `<tr class="pp-add-row"><td colspan="${n}"><button type="button" class="btn-link" data-pp-add>+ задача</button></td></tr>`;
      if (конецСвоих) { конецСвоих.insertAdjacentHTML("afterend", строка); конецСвоих = конецСвоих.nextElementSibling; }
      else tb.insertAdjacentHTML("beforeend", строка);
    }
    ctx.possible.forEach((p, i) => {
      const я = Array(n).fill("");
      я[кол.описание] = `<span class="pp-dval">${esc(p.description)}</span> <span class="pp-dmark" title="${esc(p.why)}">${esc(p.mark)}</span>`
        + `<span class="doc-cell-sub">${esc(p.why)}</span>`
        + `<span class="pp-acts pp-doubt-acts"><button type="button" class="btn-sm" data-pp-yes="${i}">В задачу</button>`
        + `<button type="button" class="btn-sm pp-del" data-pp-no="${i}">Убрать</button>${РЕШИТЬ_В_РАЗБОРЕ}</span>`;
      if (кол.исполнитель >= 0) я[кол.исполнитель] = `<span class="pp-dval">${esc(p.responsible || "не назначен")}</span>`;
      if (кол.срок >= 0) я[кол.срок] = `<span class="pp-dval">${esc(p.due || "не указан")}</span>`;
      const поля = { [кол.описание]: "description", [кол.исполнитель]: "responsible", [кол.срок]: "due" };
      const html = `<tr class="pp-doubt" data-possible="${i}">${я.map((c, j) => `<td${поля[j] ? ` class="pp-cell" data-field="${поля[j]}"` : ""}>${c}</td>`).join("")}</tr>`;
      // после своей строки (и уже вставленных за ней сомнительных), иначе — перед «+ задача» / в конце строк встречи
      let после = p.after_task_id ? tb.querySelector(`tr[data-task="${p.after_task_id}"]`) : null;
      while (после && после.nextElementSibling && после.nextElementSibling.classList.contains("pp-doubt")) после = после.nextElementSibling;
      const якорь = после || (ctx.own_tasks ? tb.querySelector("tr.pp-add-row") : null);
      if (после) после.insertAdjacentHTML("afterend", html);
      else if (якорь) якорь.insertAdjacentHTML("beforebegin", html);
      else if (конецСвоих) конецСвоих.insertAdjacentHTML("afterend", html);
      else tb.insertAdjacentHTML("beforeend", html);
      const tr = tb.querySelector(`tr[data-possible="${i}"]`);
      tr._ppd = { p, поля: {} };
    });
  } else if (ctx.own_tasks) {
    док.insertAdjacentHTML("beforeend", `<div class="pp-add-wrap"><button type="button" class="btn-link" data-pp-add>+ задача</button>
      <span class="doc-cell-sub">таблицы задач в документе нет — она появится с первой задачей</span></div>`);
  }
  // Таблица задач — в своей рамке прокрутки, как в показе (замечание владелицы 25.10.2026, «справа нарушение границы»): в показе
  // её оборачивает свёртка длинного списка (.table-scroll, прокрутка вбок), в правке свёртки нет — и таблица, которой не хватало
  // места, выходила за карточку (ERP при открытой панели «Замечаний», колонка документа 402 px: таблица 477 px). Рамка та же,
  // что у показа, — переносы и раскладка колонок (polotno.css, styles.css) держат таблицу в ширине, рамка — последний запас.
  док.querySelectorAll("table.doc-table").forEach(таб => {
    if (ппКолонки(таб).описание < 0 || таб.parentElement.classList.contains("table-scroll")) return;
    const р = document.createElement("div");
    р.className = "table-scroll";
    р.style.overflowX = "auto";
    таб.before(р);
    р.appendChild(таб);
  });
  // Полоса режима правки и реестр корректировок — вне документа
  const ч = ctx.draft;
  const состояниеЧерновика = !ч ? "Правок текста пока нет — действует сохранённая версия."
    : ч.stale ? "Документ пересобран после начала правки — черновик относится к прежней версии; его можно только отменить."
    : `Черновик правок: ${ч.edits} · с ${fmtRuDateTime(ч.since)}${ч.who ? " · " + ч.who : ""}. В просмотре и Word — прежняя версия до «Готово».`;
  рамка.insertAdjacentHTML("beforebegin", `<div class="pp-bar" data-pp-bar>
    <span class="pp-draft${ч ? " pp-draft-on" : ""}${ч && ч.stale ? " pp-draft-stale" : ""}">${esc(состояниеЧерновика)}</span>
    <span class="pp-acts pp-bar-acts">${ч && ч.stale ? "" : `<button type="button" class="btn-primary btn-sm" data-pp-finish>Готово</button>`}
      ${ч ? `<button type="button" class="btn-sm" data-pp-discard>Отменить правки</button>` : ""}</span>
    <span class="pp-hint">${esc(ППОДСКАЗКА)}</span>
    <label class="pp-fix"><input type="checkbox" data-pp-fix checked> исправление ошибки обработки, не переписывание факта</label></div>`);
  const полоса = рамка.previousElementSibling;
  полоса.querySelector("[data-pp-fix]").addEventListener("change", (e) => { состояние.флажок = e.target.checked; });
  // «Готово»: черновик — новой действующей версией; без черновика — просто выход из правки
  полоса.querySelector("[data-pp-finish]")?.addEventListener("click", async (e) => {
    if (занято()) { toast("Сначала сохраните или отмените открытое поле", true); return; }
    e.currentTarget.disabled = true;
    try {
      if (ч) {
        await api(`${опц.base}/edits/finish`, { method: "POST", auth: true, json: { version_id: ctx.version_id } });
        toast("Новая версия документа сохранена — прежняя осталась в базе");
      }
      полотноРежим(опц.base, "view");
      опц.перерисовать();
    } catch (err) { toast(`Правка не сохранена: ${err.message} Документ не изменился.`, true); e.currentTarget.disabled = false; }
  });
  полоса.querySelector("[data-pp-discard]")?.addEventListener("click", async () => {
    if (!(await confirmDialog("Отменить правки текста этого сеанса? Действующая версия не менялась; правки задач в реестре остаются.", "Отменить правки"))) return;
    try {
      await api(`${опц.base}/edits/discard`, { method: "POST", auth: true });
      toast("Черновик правок отменён");
      опц.перерисовать();
    } catch (err) { toast(err.message, true); }
  });
  const лог = document.createElement("section");
  лог.className = "card pp-log";
  лог.setAttribute("aria-label", "Реестр корректировок");
  лог.innerHTML = `<h2 class="pp-log-h">Реестр корректировок</h2>` + (ctx.log.length
    ? `<ul class="pp-log-list">${ctx.log.map(з => `<li><span class="pp-log-w">${esc(з.who)} · ${esc(fmtRuDateTime(з.when))}</span> — ${esc(з.place)}
        ${з.old || з.new ? `<div class="pp-was">было: ${esc(ппСтрокаТаблицы(з.old) || "—")}</div><div class="pp-now">стало: ${esc(ппСтрокаТаблицы(з.new) || "—")}</div>` : ""}</li>`).join("")}</ul>`
    : `<div class="pp-hint">Правок пока не было.</div>`)
    + `<details class="pp-ai"><summary>Попросить ИИ поправить словами</summary>
        <div class="pp-hint">Когда правка сложнее одного абзаца: опишите, что и где не так, — правку внесёт и сверит с источником
          модель. Это настоящий вызов, обычно от 1 до 15 минут, и он платный.</div>
        <textarea class="pp-inl" rows="2" data-pp-ai-text placeholder="Например: абзац про X обрывается, по источнику там ещё указано…"></textarea>
        <div class="pp-acts"><button type="button" class="btn-sm btn-primary" data-pp-ai>Отправить на обработку ИИ</button></div></details>`;
  (опц.место || рамка).insertAdjacentElement(опц.место ? "beforeend" : "afterend", лог);
  лог.querySelector("[data-pp-ai]").addEventListener("click", async (e) => {
    const кнопка = e.currentTarget;
    const request = лог.querySelector("[data-pp-ai-text]").value.trim();
    if (!request) { toast("Опишите, что и где поправить", true); return; }
    if (ч) { toast("Сначала «Готово» или «Отменить правки»: правка словами идёт в сохранённую версию, а не в черновик", true); return; }
    if (!(await confirmDialog("Отправить правку модели? Это платный вызов, обычно от 1 до 15 минут.", "Отправить"))) return;
    кнопка.disabled = true;
    кнопка.textContent = "Обрабатываю…";
    try {
      const итог = await api(`${опц.base}/correction-request`, { method: "POST", auth: true, json: { request } });
      if (итог.status === "verification_failed") toast("Правка не прошла проверку по источнику — уточните запрос или поправьте абзац на полотне", true);
      else { toast("Правка сохранена" + (итог.note ? ": " + итог.note : "")); опц.перерисовать(); }
    } catch (err) { toast(err.message, true); }
    finally { кнопка.disabled = false; кнопка.textContent = "Отправить на обработку ИИ"; }
  });

  const занято = () => !!док.querySelector(".pp-editor") || (ч && ч.stale);
  const опЗадачи = (r, поля) => Object.assign({ kind: "task", task_id: r.task.id, version: r.task.version,
    old_description: r.core || r.task.description, in_doc: !!r.in_doc }, поля);
  // Поле на месте: абзац, пункт, заголовок
  const блокНаМесте = (el) => {
    if (занято()) return;
    const значение = ппЗначение(el);
    const высота = el.getBoundingClientRect().height;
    const прежнее = el.innerHTML;
    const до = el.getBoundingClientRect().top;
    el.classList.add("pp-sel");
    el.innerHTML = `<span class="pp-editor"><textarea class="pp-inl" aria-label="Текст абзаца"></textarea>
      <span class="pp-acts"><button type="button" class="btn-primary btn-sm" data-pp-save>Сохранить</button><button type="button" class="btn-sm" data-pp-cancel>Отмена</button>
      <span class="pp-hint">Enter — сохранить, Shift+Enter — новая строка, Esc — отмена</span></span></span>`;
    const ta = el.querySelector("textarea");
    ta.value = значение;
    ta.style.height = Math.max(высота, 38) + "px";
    ппАвтоВысота(ta);
    ta.addEventListener("input", () => ппАвтоВысота(ta));
    ta.focus({ preventScroll: true });
    { const сдвиг = el.getBoundingClientRect().top - до; if (Math.abs(сдвиг) > 1) window.scrollBy(0, сдвиг); }
    const отмена = () => ппДержатьМесто(el, () => { el.innerHTML = прежнее; el.classList.remove("pp-sel"); });
    const готово = async () => {
      const новое = ta.value.trim();
      if (новое === значение) { отмена(); return; }
      if (!новое) { toast("Пустой абзац не сохраняется", true); return; }
      if (!(await сохранить([{ kind: "block", old: el.dataset.src, new: (el.dataset.pre || "") + новое }]))) ta.focus();
    };
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); готово(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); отмена(); }
    });
    el.querySelector("[data-pp-save]").addEventListener("click", готово);
    el.querySelector("[data-pp-cancel]").addEventListener("click", отмена);
  };
  // Набор полей на месте (ячейка, статус, новая задача): поля, ошибка, «Сохранить / Отмена», Enter / Esc
  const поляНаМесте = (куда, разметка, собрать, отменаПоля, доПоля = null) => {
    const якорь = куда.closest("tr") || куда;
    const до = доПоля !== null ? доПоля : якорь.getBoundingClientRect().top;
    // «Отмена» и Esc: строка на месте, фокус клавиатуры — на её значке статуса (поле, где он был, убрано)
    const отмена = () => {
      ппДержатьМесто(якорь, отменаПоля);
      if (якорь.isConnected && (!document.activeElement || document.activeElement === document.body)) {
        якорь.querySelector("[data-pp-st], button, a[href]")?.focus({ preventScroll: true });
      }
    };
    куда.insertAdjacentHTML("beforeend", `<span class="pp-editor">${разметка}<span class="pp-err" hidden></span>
      <span class="pp-acts"><button type="button" class="btn-primary btn-sm" data-pp-save>Сохранить</button><button type="button" class="btn-sm" data-pp-cancel>Отмена</button></span></span>`);
    const ред = куда.querySelector(".pp-editor");
    const ошибка = ред.querySelector(".pp-err");
    const сказать = (т) => { ошибка.textContent = т; ошибка.hidden = false; };
    const готово = async () => {
      const ops = собрать(сказать);
      if (ops === null) return;
      if (!ops.length) { отмена(); return; }
      await сохранить(ops);
    };
    ред.querySelectorAll("input, textarea, select").forEach(вход => {
      if (вход.tagName === "TEXTAREA") { ппАвтоВысота(вход); вход.addEventListener("input", () => ппАвтоВысота(вход)); }
      вход.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); готово(); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); отмена(); }
      });
    });
    ред.querySelector("[data-pp-save]").addEventListener("click", готово);
    ред.querySelector("[data-pp-cancel]").addEventListener("click", отмена);
    ред.querySelector("input, textarea, select")?.focus({ preventScroll: true });
    // раскладку таблицы правят и вызывающие (значение поля, ширина, высота) — место возвращается после них
    requestAnimationFrame(() => { if (якорь.isConnected) { const сдвиг = якорь.getBoundingClientRect().top - до; if (Math.abs(сдвиг) > 1) window.scrollBy(0, сдвиг); } });
    return ред;
  };
  const ячейкаСомнительной = (td) => {
    const d = td.closest("tr")._ppd;
    const поле = td.dataset.field;
    const значение = поле in d.поля ? d.поля[поле] : (d.p[поле] || "");
    const прежнее = td.innerHTML;
    td.classList.add("pp-sel");
    const отмена = () => { td.innerHTML = прежнее; td.classList.remove("pp-sel"); };
    const разметка = поле === "description" ? `<textarea class="pp-inl" aria-label="Формулировка задачи"></textarea>`
      : поле === "responsible" ? `<input class="pp-inl" list="pp-people" aria-label="Исполнитель" placeholder="ФИО из «Команды» или отдел">`
      : `<input class="pp-inl" inputmode="numeric" aria-label="Срок" placeholder="дд.мм.гггг" maxlength="10">`;
    const ред = поляНаМесте(td, разметка, (сказать) => {
      let новое = ред.querySelector(".pp-inl").value.trim();
      if (поле === "due") { const с = ппСрок(новое); if (!с.ok) { сказать(с.msg); return null; } новое = с.value; }
      if (поле === "description" && !новое) { сказать("Формулировка не может быть пустой"); return null; }
      d.поля[поле] = новое;
      td.innerHTML = прежнее;
      td.classList.remove("pp-sel");
      const место = td.querySelector(".pp-dval");
      if (место) место.textContent = новое || (поле === "due" ? "не указан" : поле === "responsible" ? "не назначен" : "");
      else td.insertAdjacentHTML("beforeend", `<span class="doc-cell-sub pp-pending">станет: ${esc(новое || "—")}</span>`);
      td.classList.add("pp-dirty");
      td.title = "Поправлено — сохранится вместе с «В задачу»";
      return null;
    }, отмена);
    ред.querySelector(".pp-inl").value = значение;
    if (поле === "description") ппАвтоВысота(ред.querySelector(".pp-inl"));
  };
  const ячейкаНаМесте = (td) => {
    if (занято()) return;
    if (td.closest("tr")._ppd) { ячейкаСомнительной(td); return; }
    const r = td.closest("tr")._pp;
    const поле = td.dataset.field;
    const значение = поле === "description" ? (r.core || r.task.description) : поле === "due" ? r.task.due : r.task.responsible;
    const прежнее = td.innerHTML;
    const ширина = td.getBoundingClientRect().width;
    const доЯчейки = td.closest("tr").getBoundingClientRect().top;
    td.classList.add("pp-sel");
    td.innerHTML = "";
    const поля = {
      description: `<textarea class="pp-inl" aria-label="Формулировка задачи"></textarea>`,
      responsible: `<input class="pp-inl" list="pp-people" aria-label="Исполнитель" placeholder="ФИО из «Команды» или отдел">`,
      due: `<input class="pp-inl" inputmode="numeric" aria-label="Срок" placeholder="дд.мм.гггг" maxlength="10">`,
    };
    const отмена = () => { td.innerHTML = прежнее; td.classList.remove("pp-sel"); };
    const ред = поляНаМесте(td, поля[поле], (сказать) => {
      let новое = вход.value.trim();
      if (поле === "due") { const с = ппСрок(новое); if (!с.ok) { сказать(с.msg); return null; } новое = с.value; }
      if (поле === "description" && !новое) { сказать("Формулировка не может быть пустой"); return null; }
      return новое === (значение || "") ? [] : [опЗадачи(r, { [поле]: новое })];
    }, отмена, доЯчейки);
    const вход = ред.querySelector(".pp-inl");
    вход.value = значение || "";
    if (поле !== "description") вход.style.minWidth = Math.min(Math.max(ширина, 150), 260) + "px";
    else ппАвтоВысота(вход);
  };
  const статусНаМесте = (кнопка) => {
    if (занято()) return;
    const tr = кнопка.closest("tr");
    const r = tr._pp;
    const место = кнопка.closest(".pp-row-acts");
    const отмена = () => { место.querySelector(".pp-editor")?.remove(); };
    const ред = поляНаМесте(место, `<span class="pp-st-menu" role="radiogroup" aria-label="Статус задачи">${ПСТАТУСЫ.map(([к, имя]) =>
        `<label><input type="radio" name="pp-st-${r.task.id}" value="${к}"${к === r.task.status ? " checked" : ""}> ${имя}</label>`).join("")}</span>
      <input class="pp-inl pp-reason" aria-label="Причина снятия" placeholder="Причина снятия — обязательно" hidden>`, (сказать) => {
      const код = ред.querySelector("input[type=radio]:checked")?.value;
      const причина = ред.querySelector(".pp-reason").value.trim();
      if (код === "dropped" && !причина) { сказать("Укажите причину снятия — задача снимается с причиной, не удаляется"); return null; }
      if (код === r.task.status && код !== "dropped") return [];
      return [опЗадачи(r, { status: код, reason: код === "dropped" ? причина : null })];
    }, отмена);
    const причина = ред.querySelector(".pp-reason");
    const показатьПричину = () => {
      ппДержатьМесто(tr, () => { причина.hidden = ред.querySelector("input[type=radio]:checked")?.value !== "dropped"; });
      if (!причина.hidden) причина.focus({ preventScroll: true });
    };
    ред.querySelectorAll("input[type=radio]").forEach(x => x.addEventListener("change", показатьПричину));
    // снятых строк в таблице нет (26.10.2026) — фокус на выбранном статусе
    ред.querySelector("input[type=radio]:checked")?.focus({ preventScroll: true });
  };
  const новаяЗадача = (кнопка) => {
    if (занято()) return;
    const место = кнопка.closest("td, .pp-add-wrap");
    кнопка.hidden = true;
    const отмена = () => { место.querySelector(".pp-editor")?.remove(); кнопка.hidden = false; };
    const ред = поляНаМесте(место, `<span class="pp-new">
        <textarea class="pp-inl" data-f="description" aria-label="Формулировка новой задачи" placeholder="Формулировка задачи"></textarea>
        <input class="pp-inl" data-f="responsible" list="pp-people" aria-label="Исполнитель" placeholder="Исполнитель: ФИО из «Команды» или отдел">
        <input class="pp-inl" data-f="due" inputmode="numeric" aria-label="Срок" placeholder="Срок дд.мм.гггг" maxlength="10"></span>`, (сказать) => {
      const з = (f) => ред.querySelector(`[data-f="${f}"]`).value.trim();
      if (!з("description")) { сказать("Формулировка не может быть пустой"); return null; }
      const с = ппСрок(з("due"));
      if (!с.ok) { сказать(с.msg); return null; }
      return [{ kind: "new_task", description: з("description"), responsible: з("responsible"), due: с.value }];
    }, отмена);
    return ред;
  };

  док.addEventListener("click", async (e) => {
    const к = (s) => e.target.closest(s);
    if (к("[data-pp-st]")) { статусНаМесте(к("[data-pp-st]")); return; }
    if (к("[data-pp-op]")) {
      if (занято()) { toast("Сначала сохраните или отмените открытое поле", true); return; }
      const r = к("tr")._pp;
      к("[data-pp-op]").disabled = true;
      await сохранить([опЗадачи(r, { operational: !r.task.operational })]);
      return;
    }
    if (к("[data-pp-add]")) { новаяЗадача(к("[data-pp-add]")); return; }
    if (к("[data-pp-yes]")) {
      if (занято()) { toast("Сначала сохраните или отмените открытое поле", true); return; }
      const { p, поля } = к("tr")._ppd;
      await сохранить([Object.assign({ kind: "confirm_possible", source: p.source, id: p.id, task_id: p.source === "uq" ? p.id : null,
        version: p.version }, поля)]);
      return;
    }
    if (к("[data-pp-no]")) {
      const { p } = к("tr")._ppd;
      const итог = p.source === "uq" ? "задача будет снята с причиной «не поручение — решение секретаря»" : "строка получит «не задача»";
      if (!(await confirmDialog(`Убрать «${p.description}»? ${итог[0].toUpperCase() + итог.slice(1)}.`, "Убрать"))) return;
      await сохранить([{ kind: "drop_possible", source: p.source, id: p.id, task_id: p.source === "uq" ? p.id : null, version: p.version }]);
      return;
    }
    if (к(".pp-editor, button, a, input, textarea, select, label")) return;
    const ячейка = к("td.pp-cell");
    if (ячейка) { ячейкаНаМесте(ячейка); return; }
    const блок = к("[data-src]");
    if (блок) блокНаМесте(блок);
  });
  // «Поправить» у замечания: поле открывается у абзаца с фрагментом замечания
  if (опц.заметка && опц.заметка.quote) {
    const часть = String(опц.заметка.quote).split("|").map(x => x.trim()).filter(x => x.length > 3).sort((a, b) => b.length - a.length)[0] || "";
    const цель = часть && [...док.querySelectorAll("[data-src]")].find(el => ппСверка(el.dataset.src).includes(ппСверка(часть)));
    if (цель) { цель.scrollIntoView({ block: "center" }); блокНаМесте(цель); }
    else toast("Фрагмента замечания в тексте нет — поправьте нужный абзац щелчком", true);
  }
  return ctx;
}
