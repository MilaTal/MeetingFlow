/* MeetFlow — интерфейс без сборки (как в исходных проектах).
   Правила экрана: номер для человека с 1, внутренний id скрыт; системные
   сообщения не в рабочих вкладках; кнопок, на которые нет прав, нет вовсе;
   пользователю — понятные фразы; всё экранируется (урок XSS через #search). */
"use strict";
const S = { theme: null, project: null, role: "member", name: "", auth: false };
const ROLE_RU = { member: "Участник", director: "Директор", project_admin: "Админ проекта", super_admin: "Супер-админ" };
// заняты проектами-примерами и пресетами: индиго и зелёные; для новых проектов — нижний ряд
const PALETTES = { emerald: "#1f845a", indigo: "#6863bf", forest: "#2f4f41", polaris: "#008060", sage: "#4b6358", meadow: "#257e52" };
const PALETTES_NEW = { petrol: "#1d5e69", ocean: "#245a8c", slate: "#46586f", graphite: "#3f4249", ochre: "#8a5a12", clay: "#a14e36", copper: "#8c5232", claret: "#7d3045" };
const ACTOR = { meeting: ["actor-model", "со встречи"], web_form: ["actor-operator", "вручную"],
  member_note: ["actor-operator", "комментарий"], system: ["actor-store", "система"] };
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isAdmin = () => (S.theme?.permissions?.admin || ["project_admin", "super_admin"]).includes(S.role);
const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* приватное окно */ } } };

// чтение, начатое до смены экрана, в экран не возвращается (находки стенда 10 и 14, ERP 9b3ecd1): перехват innerHTML
// ставился заново каждой отрисовкой и пропускал запись любой, в том числе устаревшей — реестр рисовался поверх «Конфликтов»
class Stale extends Error {}
let renderSeq = 0;
// «Инструкция оператору — внешние модели» (решение владельца 14.10.26, текст одинаковый в ERP и Планёрке; ответ 15.10.26 — так же в MeetFlow)
const KEY_HELP = "Внешняя модель работает за пределами контура компании. Ей уходит текст встречи, заметки и состав команды. Запись голоса не уходит никогда — распознавание всегда идёт на своей машине. Ключ вводится один раз: после сохранения он больше не показывается, видно только «ключ задан · …XXXX». Перед сохранением нажмите «Проверить связь». Подробно — «Как подключить внешнюю модель» внизу страницы.";
const EXTERNAL_HELP = `<div class="stack sub" style="margin-top:8px">
<p><strong>Когда нужна внешняя модель.</strong> Внешняя модель — обходной путь для сборки протокола, когда своя модель недоступна или справляется хуже. Голос она не получает: распознавание речи принимает только модели на своей машине, внешнюю туда поставить нельзя.</p>
<p><strong>Что уходит наружу.</strong> Текст встречи после распознавания, заметки секретаря, состав команды и названия проектов. Больше ничего.</p>
<p><strong>Как подключить.</strong></p><ol>
<li>Откройте «Список подключений» и нажмите «+ Новое подключение модели».</li>
<li>Выберите тип подключения: OpenRouter или «Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик».</li>
<li>Адрес: выберите из подсказки или впишите адрес поставщика, начинается с https.</li>
<li>Модель: имя модели так, как его пишет поставщик.</li>
<li>Ключ: выберите «значение» и вставьте ключ, полученный у поставщика. Если ключ уже лежит в переменной окружения на машине, выберите «имя переменной окружения» и впишите её имя.</li>
<li>Нажмите «Проверить связь». Ответ «живо» и время ответа — можно сохранять. «Ключ не принят поставщиком» — проверьте ключ и срок его действия.</li>
<li>Нажмите «Сохранить». Подключение появится в списке с пометкой «внешняя».</li>
<li>Поставьте подключение в роль: «Генерация черновика» или «Проверка черновика». Само в роль оно не встаёт.</li></ol>
<p><strong>Два способа подключения, оба рабочие.</strong> Через OpenRouter: тип подключения OpenRouter, адрес https://openrouter.ai/api, ключ OpenRouter, модель — любая из каталога OpenRouter, имя так, как оно записано в каталоге. Напрямую через API поставщика, например DeepSeek: тип подключения «Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик», адрес https://api.deepseek.com, модель deepseek-flash, ключ DeepSeek. Можно завести оба подключения: одно поставить в роль основным, второе — запасным. Если основное не ответит, вызов уйдёт на запасное.</p>
<p><strong>Как заменить или убрать ключ.</strong> В строке подключения — «Заменить ключ» или «Удалить ключ». Прежний ключ после замены не восстанавливается. «Откатить последнее изменение» ключ не трогает.</p>
<p><strong>Что важно.</strong> Ключ не пишите в комментарии, письма и переписку: в системе он хранится отдельно и наружу не показывается. Потолки цены и числа вызовов действуют и на внешнюю модель. Расход видно на вкладке «Расход» в «Параметрах системы». Если протокол собран внешней моделью, в «Системных сообщениях» появится строка об этом. В самом протоколе пометки нет. Если в компании выход в интернет идёт через прокси, в поле «Прокси — для внешней точки» должен стоять вариант «системный» — так по умолчанию. Ключи видит и меняет только супер-администратор.</p></div>`;
async function api(path, opts = {}) {
  const seq = renderSeq, read = !opts.method || opts.method === "GET";
  const headers = { "X-User-Role": S.role, "X-User-Name": encodeURIComponent(S.name), "X-Requested-With": "MeetFlow", ...(opts.headers || {}) };
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, { ...opts, headers });
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (r.status === 401 && S.auth && !path.startsWith("/api/auth/")) { showLogin(); }
  if (read && seq !== renderSeq) throw new Stale("экран сменился");
  if (!r.ok) throw new Error((data && data.detail && (typeof data.detail === "string" ? data.detail : "Проверьте введённые данные.")) || "Не получилось.");
  return data;
}
function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 4000);
}
const fmtDate = (iso) => esc(iso ? String(iso).slice(0, 10).split("-").reverse().join(".") : "—"); // глубина защиты (ревью)
// дата и время — дд.мм.гггг чч:мм (правило владельца 09.10.26)
const fmtDateTime = (iso) => iso ? `${fmtDate(iso)} ${esc(String(iso).replace("T", " ").slice(11, 16))}` : "—";
// Длинные списки (владелец 13.10.26, находка стенда 17): не больше 7 строк, на низком окне от 5, остальное свёрнуто;
// раскрытое — в ленте 480 px с прокруткой по вертикали и горизонтали. Нумерация в свёрнутой части продолжается.
const listLimit = () => (window.innerHeight < 720 ? 5 : 7);
const moreTail = (n, inner) => `<details class="more-list"><summary class="disclosure-summary">Показать ещё ${n}</summary><div class="ribbon">${inner}</div></details>`;
const moreItems = (items, render) => { const n = listLimit(), rest = items.slice(n);
  return items.slice(0, n).map((x, i) => render(x, i)).join("") + (rest.length ? moreTail(rest.length, rest.map((x, i) => render(x, i + n)).join("")) : ""); };
const moreRows = (head, items, render) => { const n = listLimit(), rest = items.slice(n);
  return `<table>${head}${items.slice(0, n).map((x, i) => render(x, i)).join("")}</table>` + (rest.length ? moreTail(rest.length, `<table>${head}${rest.map((x, i) => render(x, i + n)).join("")}</table>`) : ""); };

function md(mdText) { // минимальный markdown: заголовки, таблицы, курсив, списки
  const out = []; let table = [];
  const flush = () => { if (!table.length) return;
    const rows = table.filter((r) => !/^\s*\|?[\s:-]+\|/.test(r) || /[^\s|:-]/.test(r));
    out.push("<table>" + rows.map((r, i) => "<tr>" + r.trim().replace(/^\||\|$/g, "").split("|")
      .map((c) => (i === 0 ? `<th>${esc(c.trim())}</th>` : `<td>${esc(c.trim())}</td>`)).join("") + "</tr>").join("") + "</table>");
    table = []; };
  // строчная разметка — после экранирования: **жирный**, *курсив*
  const inline = (t) => esc(t).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, '<em class="sub-inline">$1</em>');
  let list = [];
  const flushList = () => { if (list.length) { out.push(`<ul>${list.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>`); list = []; } };
  for (const line of mdText.split("\n")) {
    if (/^\s*\|.*\|\s*$/.test(line)) { flushList(); if (!/^\s*\|[\s:|-]+\|\s*$/.test(line)) table.push(line); continue; }
    flush();
    let m;
    if ((m = line.match(/^\s*[-*]\s+(.*)$/))) { list.push(m[1]); continue; }
    flushList();
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) out.push(`<h${m[1].length + 1}>${esc(m[2])}</h${m[1].length + 1}>`);
    else if ((m = line.match(/^\*\*(.+)\*\*$/))) out.push(`<p class="part-label"><strong>${esc(m[1])}</strong></p>`);
    else if ((m = line.match(/^\*([^*].*)\*$/))) out.push(`<p class="doc-sources-line">${esc(m[1])}</p>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  flushList(); flush(); return out.join("\n");
}

const routes = {
  async tasks() {
    const view = store.get("tasks-view", "active");
    const rows = await api(`/api/projects/${S.project}/tasks?status=${view}`);
    const tabs = ["active", "done", "dropped"].map((v) => `<button class="btn ${v === view ? "btn-primary" : ""}" data-view="${v}">${
      { active: "В работе", done: "Выполненные", dropped: "Снятые" }[v]}</button>`).join("");
    const body = rows.length ? `<div class="table-wrap" id="tasks-frame"><table><tr><th>№</th><th>Задача</th><th>Ответственный</th><th>Срок</th><th>Комментарий</th><th></th></tr>${
      rows.map((t) => {
        const mine = S.name && S.name === t.assignee;
        const can = isAdmin() || S.role === "director" || mine;
        return `<tr><td class="no" title="Внутренний номер: ${esc(t.id)}">${esc(t.no)}<small>${fmtDate(t.date_set)}</small></td>
          <td>${esc(t.description)}${t.doubt_reason ? `<span class="doubt-dot" title="под вопросом: ${esc(t.doubt_label || t.doubt_reason)} — карточка в «Конфликтах»" aria-label="под вопросом"></span>` : ""}${t.source_quote ? `<span class="sub">«${esc(t.source_quote.slice(0, 160))}»</span>` : ""}${t.source_meeting_id ? `<a class="sub task-meeting" href="#meeting/${esc(t.source_meeting_id)}">встреча ${fmtDate(t.meeting_date)} — протокол</a>` : ""}</td>
          <td>${esc(t.assignee || "Не назначен")}</td><td${t.overdue ? ' class="overdue" title="Просрочено: порог в «Параметры системы → Пороги»"' : ""}>${esc(t.due_text || t.due_date || "—")}</td><td>${esc(t.last_comment || "")}</td>
          <td>${can && view === "active" ? `<button class="btn" data-done="${t.id}">Выполнено</button>` : ""}
              ${can && view !== "active" ? `<button class="btn btn-ghost" data-back="${t.id}">Вернуть</button>` : ""}</td></tr>`;
      }).join("")}</table></div>` : `<p class="empty">Задач нет.</p>`;
    // поиска на странице реестра нет — решение владельца 12.10.26 (убран из ERP и Планёрки); страница «Поиск» работает
    $("#main").innerHTML = `<h1>${esc(S.theme.vocabulary.nav_tasks || S.theme.vocabulary.registry)}</h1><div class="row" style="margin-bottom:16px">${tabs}</div><div class="card-output">${body}</div>`;
    // в таблице — до 7 строк (решение 09.10.26): высота рамки считается от низа окна
    const fitRows = () => { const fr = $("#tasks-frame"); if (!fr) return;
      const trs = [...fr.querySelectorAll("tr")]; if (trs.length < 2) return;
      const head = trs[0].offsetHeight, rowsH = trs.slice(1, 8).reduce((a, r) => a + r.offsetHeight, 0);
      const room = window.innerHeight - fr.getBoundingClientRect().top - 36;
      const minH = head + trs.slice(1, 6).reduce((a, r) => a + r.offsetHeight, 0);   // от 5 строк (стенд 17)
      fr.style.maxHeight = Math.max(minH, Math.min(head + rowsH, room)) + "px"; fr.style.overflowY = "auto"; };
    fitRows(); window.onresize = fitRows;
    $("#main").querySelectorAll("[data-view]").forEach((b) => b.onclick = () => { store.set("tasks-view", b.dataset.view); render(); });
    $("#main").querySelectorAll("[data-done]").forEach((b) => b.onclick = () => undoable(b, b.dataset.done, "done"));
    $("#main").querySelectorAll("[data-back]").forEach((b) => b.onclick = async () => { await api(`/api/tasks/${b.dataset.back}`, { method: "PATCH", json: { status: "active" } }); render(); });
  },

  async search() {
    const hints = ["задачи с ответственным (ФИО)", "в этой задаче есть о ...", "было ли упомянуто", "протокол встречи от", "информация о"];
    const q = store.get("search-q", "");
    $("#main").innerHTML = `<h1>${esc(S.theme.vocabulary.search || "Поиск по проекту")}</h1>
      <div class="card stack"><div class="row"><input id="sq" style="flex:1;min-width:240px" placeholder="Слово, ФИО или дата встречи" value="${esc(q)}">
      <button class="btn btn-primary" id="sgo">Найти</button>${q ? '<button class="btn btn-ghost" id="sreset">✕ Сбросить</button>' : ""}</div>
      <div class="row">${hints.map((h) => `<button class="btn btn-ghost" data-hint="${esc(h.replace(/\s*\(.*\)|\.{2,}/g, ""))}">${esc(h)}</button>`).join("")}</div></div>
      <div id="sres"></div>`;
    const run = async () => {
      const v = $("#sq").value.trim(); store.set("search-q", v);
      if (!v) { $("#sres").innerHTML = ""; return; }
      const r = await api(`/api/projects/${S.project}/search?q=${encodeURIComponent(v)}`);
      const kind = { protocol: "протокол", source: "источник", task: "задача", unit: "из записи" };
      $("#sres").innerHTML = r.problem ? `<div class="card-output"><p class="empty">${esc(r.problem)}</p></div>`
        : !r.results.length ? `<div class="card-output"><p class="empty">Ничего не найдено. Проверьте написание или попробуйте другое слово.</p></div>`
        : `<div class="card-output"><p class="sub">Найдено: ${esc(r.total)}</p>${r.results.map((x) => `<div class="note"><span class="badge">${esc(kind[x.type] || x.type)}</span> <span class="meta">${fmtDate(x.meeting_date)}</span> ${x.type === "protocol" || x.type === "source" || x.type === "unit" ? `<a href="#meeting/${esc(x.id)}">открыть встречу</a>` : ""}<q>${esc(x.snippet)}</q></div>`).join("")}</div>`;
    };
    $("#sgo").onclick = run;
    $("#sq").onkeydown = (e) => { if (e.key === "Enter") run(); };
    const rs = $("#sreset"); if (rs) rs.onclick = () => { store.set("search-q", ""); render(); };
    $("#main").querySelectorAll("[data-hint]").forEach((b) => b.onclick = () => { $("#sq").value = b.dataset.hint + " "; $("#sq").focus(); });
    if (q) run();
  },

  async roadmap() {
    const tab = S.statusTab || "summary";
    const s = await api(`/api/projects/${S.project}/summary`);
    const r = tab === "roadmap" ? await api(`/api/projects/${S.project}/roadmap`) : null;
    const tabs = `<div class="row" style="margin-bottom:10px"><button class="btn ${tab === "summary" ? "btn-primary" : ""}" data-status-tab="summary">Сводка</button>
      <button class="btn ${tab === "roadmap" ? "btn-primary" : ""}" data-status-tab="roadmap">Дорожная карта</button></div>`;
    const card = (t, v, sub = "") => `<div class="card-output"><div class="sub">${esc(t)}</div><div style="font-size:24px;font-weight:600">${esc(v)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`;
    const summary = `<div class="card-output"><h2 style="margin-top:0">Задачи</h2>
        <div class="row" style="gap:12px;flex-wrap:wrap">${card("В работе", s.tasks_active, `просрочено ${s.tasks_overdue} · без срока ${s.tasks_no_due}`)}
        ${card("Выполнено", s.tasks_done)}${card("Снято", s.tasks_dropped)}</div></div>
      <div class="card-output"><h2 style="margin-top:0">Решения и вопросы</h2>
        <div class="row" style="gap:12px;flex-wrap:wrap">${card("Действует решений", s.decisions)}${card("Договорённостей", s.agreements)}
        ${card("Открытых вопросов", s.questions)}${card("Вех", s.milestones)}</div></div>
      <div class="card-output"><h2 style="margin-top:0">Встречи</h2>
        <div class="row" style="gap:12px;flex-wrap:wrap">${card("Всего", s.meetings)}${card("С протоколом", s.with_protocol)}
        ${card("Последняя", s.last_meeting ? fmtDate(s.last_meeting) : "—")}</div></div>`;
    $("#main").innerHTML = `<h1>Статус проекта</h1>
      ${tabs}
      ${r ? `<div class="row" style="margin-bottom:8px"><a class="btn" href="/api/projects/${encodeURIComponent(S.project)}/roadmap.docx">Скачать .docx</a></div>` : ""}
      ${tab === "roadmap" ? `<p class="page-sub">Собирается из реестра задач и записей встреч при каждом открытии — всегда актуальна. Решено не значит сделано: решения стоят в «Действует».</p>
      <article class="doc-content">${md(r.markdown.split("\n").slice(1).join("\n"))}</article>` : `<p class="page-sub">Цифры по проекту на сейчас; «Дорожная карта» — тот же срез текстом.</p>${summary}`}`;
    $("#main").querySelectorAll("[data-status-tab]").forEach((b) => b.onclick = () => { S.statusTab = b.dataset.statusTab; render(); });
  },

  async meetings() {
    const rows = await api(`/api/projects/${S.project}/meetings`);
    const form = isAdmin() ? `<div class="card stack"><h2 style="margin:0">Новая ${esc(S.theme.vocabulary.meeting)}</h2>
      <div class="row"><input id="m-date" type="date" required><input id="m-label" placeholder="Название (необязательно)">
      <button class="btn btn-primary" id="m-add">Создать</button></div></div>` : "";
    $("#main").innerHTML = `<h1>${esc(S.theme.vocabulary.meetings)}</h1>${form}<div class="card-output">${rows.length ?
      moreRows("<tr><th>Дата</th><th>Название</th></tr>", rows, (m) => `<tr><td><a href="#meeting/${m.id}">${fmtDate(m.date)}</a>${m.has_protocol ? ` <a class="sub" href="#meeting/${m.id}">протокол →</a>` : ' <span class="sub">протокола нет</span>'}</td>
      <td>${esc(m.label)}</td></tr>`) : `<p class="empty">Встреч пока нет.</p>`}</div>`;
    const add = $("#m-add");
    if (add) add.onclick = async () => { try { await api(`/api/projects/${S.project}/meetings`, { method: "POST", json: { date: $("#m-date").value, label: $("#m-label").value } }); render(); } catch (e) { toast(e.message); } };
  },

  async agreements() { // «Договорённости» — отдельный экран, как в ERP: решения, договорённости, вопросы, вехи
    const K = { decision: "Решение", agreement: "Договорённость", open_question: "Открытый вопрос",
      milestone: "Веха", clarification: "Уточнение" };
    const st = S.agr || (S.agr = { kind: "", status: "open", since: "", till: "" });
    const q = new URLSearchParams();
    if (st.kind) q.set("kind", st.kind);
    q.set("status", st.status);
    if (st.since) q.set("since", st.since);
    if (st.till) q.set("till", st.till);
    const rows = await api(`/api/projects/${S.project}/agreements?${q}`);
    const opts = [["", "Все виды"], ...Object.entries(K)].map(([v, t]) => `<option value="${v}"${st.kind === v ? " selected" : ""}>${t}</option>`).join("");
    const list = rows.length ? rows.map((r) => `<div class="card-output"><div class="row" style="justify-content:space-between;align-items:baseline">
        <span><span class="badge">${esc(r.kind_ru)}</span> ${r.meeting_date ? `<a class="sub" href="#meeting/${r.meeting_id}">${fmtDate(r.meeting_date)} — протокол</a>` : ""}</span>
        <span class="sub">${esc({ open: "открыто", active: "действует", closed: "закрыто", replaced: "заменено", removed: "убрано" }[r.status] || r.status)}${r.planned_date ? ` · срок ${fmtDate(r.planned_date)}` : ""}</span></div>
      <div>${esc(r.text)}</div>${r.quote ? `<q class="sub">${esc(r.quote)}</q>` : ""}</div>`).join("")
      : `<p class="empty">По этим условиям договорённостей нет.</p>`;
    $("#main").innerHTML = `<h1>Договорённости</h1>
      <p class="page-sub">Решения, договорённости, открытые вопросы и вехи из записей встреч. Договорённость с понятным действием и исполнителем — задача, она в реестре задач.</p>
      <div class="card"><div class="row" style="gap:10px;align-items:end">
        <label class="sub">Вид<select id="agr-kind" style="min-width:190px">${opts}</select></label>
        <label class="sub">Открытые<select id="agr-status" style="min-width:190px"><option value="open"${st.status === "open" ? " selected" : ""}>Открытые и действующие</option><option value="all"${st.status === "all" ? " selected" : ""}>Все</option></select></label>
        <label class="sub">С<input id="agr-since" type="date" value="${esc(st.since)}"></label>
        <label class="sub">По<input id="agr-till" type="date" value="${esc(st.till)}"></label>
        <button class="btn btn-ghost" id="agr-reset">Сбросить</button></div></div>
      <p class="sub">Найдено: ${rows.length}.</p>${list}`;
    const upd = () => { S.agr = { kind: $("#agr-kind").value, status: $("#agr-status").value,
      since: $("#agr-since").value, till: $("#agr-till").value }; render(); };
    $("#agr-kind").onchange = upd; $("#agr-status").onchange = upd;
    $("#agr-since").onchange = upd; $("#agr-till").onchange = upd;
    $("#agr-reset").onclick = () => { S.agr = { kind: "", status: "open", since: "", till: "" }; render(); };
  },

  async projects() { // справочник проектов и подпроектов — как структура ERP; данные заводят пользователи
    const rows = await api("/api/projects");
    const byId = new Map(rows.map((p) => [p.id, p]));
    const children = (id) => rows.filter((p) => (p.parent_id || 0) === id);
    const ordered = [];
    const walk = (parent, depth) => children(parent).forEach((p) => { ordered.push({ ...p, depth }); walk(p.id, depth + 1); });
    walk(0, 0);
    rows.filter((p) => !byId.has(p.parent_id || 0)).forEach((p) => { if (!ordered.some((x) => x.id === p.id)) ordered.push({ ...p, depth: 0 }); });
    const opts = (self, cur) => `<option value="0">— без надпроекта —</option>` + rows.filter((p) => p.id !== self)
      .map((p) => `<option value="${p.id}"${Number(cur || 0) === p.id ? " selected" : ""}>${esc(p.name)}</option>`).join("");
    const row = (p) => `<tr${p.archived ? ' class="sub"' : ""}><td style="padding-left:${8 + p.depth * 18}px">
        <input data-pname="${p.id}" value="${esc(p.name)}" style="min-width:220px"></td>
      <td><input data-palias="${p.id}" value="${esc((p.aliases || []).join(", "))}" placeholder="варианты написания" style="min-width:200px"></td>
      <td><select data-pparent="${p.id}">${opts(p.id, p.parent_id)}</select></td>
      <td>${p.archived ? `<span class="sub">в архиве</span>` : "активен"}</td>
      <td><button class="btn btn-ghost" data-psave="${p.id}">Сохранить</button>
        <button class="btn btn-ghost" data-parch="${p.id}">${p.archived ? "Вернуть" : "В архив"}</button></td></tr>`;
    $("#main").innerHTML = `<h1>Проекты</h1>
      <p class="page-sub">Проекты и подпроекты. Варианты написания помогают распознаванию и поиску; архив скрывает проект из списка выбора.</p>
      ${isAdmin() ? `<div class="card stack"><h2 style="margin:0">Новый проект</h2><div class="row">
        <input id="pj-name" placeholder="Название"><input id="pj-alias" placeholder="Варианты через запятую">
        <select id="pj-parent"><option value="0">— без надпроекта —</option>${rows.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
        <button class="btn btn-primary" id="pj-add">Создать</button></div></div>` : ""}
      <div class="card-output" style="overflow-x:auto"><table><tr><th>Название</th><th>Варианты написания</th><th>Надпроект</th><th>Состояние</th><th></th></tr>
      ${ordered.length ? ordered.map(row).join("") : `<tr><td colspan="5" class="empty">Проектов пока нет.</td></tr>`}</table></div>`;
    const add = $("#pj-add");
    if (add) add.onclick = async () => { try {
      await api("/api/projects", { method: "POST", json: { name: $("#pj-name").value,
        aliases: $("#pj-alias").value.split(",").map((x) => x.trim()).filter(Boolean), parent_id: Number($("#pj-parent").value) } });
      toast("Проект заведён."); location.reload();
    } catch (e) { toast(e.message); } };
    $("#main").querySelectorAll("[data-psave]").forEach((b) => b.onclick = async () => {
      const id = Number(b.dataset.psave);
      try { await api(`/api/projects/${id}`, { method: "PATCH", json: {
        name: $(`[data-pname="${id}"]`).value,
        aliases: $(`[data-palias="${id}"]`).value.split(",").map((x) => x.trim()).filter(Boolean),
        parent_id: Number($(`[data-pparent="${id}"]`).value),
        archived: !!(rows.find((p) => p.id === id) || {}).archived } });
        toast("Сохранено."); location.reload();
      } catch (e) { toast(e.message); } });
    $("#main").querySelectorAll("[data-parch]").forEach((b) => b.onclick = async () => {
      const p = rows.find((x) => x.id === Number(b.dataset.parch));
      try { await api(`/api/projects/${p.id}`, { method: "PATCH", json: { name: p.name, aliases: p.aliases || [],
        parent_id: p.parent_id || 0, archived: !p.archived } }); toast(p.archived ? "Проект возвращён." : "Проект в архиве."); location.reload(); } catch (e) { toast(e.message); } });
  },

  async help() { // «Как пользоваться» — короткая памятка, как в ERP
    $("#main").innerHTML = `<h1>Как пользоваться</h1>
      <div class="card stack"><p>Около трёх минут: свои задачи и отметка по ним, встречи и протоколы, реестр задач, «Статус проекта» и поиск.</p>
      <p><b>Задачи.</b> «Реестр задач по проекту» — вкладки «В работе», «Выполненные», «Снятые». Свою задачу можно закрыть кнопкой «Выполнено».</p>
      <p><b>Встречи.</b> «Встречи по проекту» — дата и протокол. На встрече видно источники, протокол, замечания проверки и задачи встречи.</p>
      <p><b>Голоса.</b> Запись распознаётся локально; говорящие подписываются «Говорящий N», а подтверждённые голоса — ФИО из «Команды». Спорные голоса разбирает супер-администратор в «Разборе голосов».</p>
      <p><b>Договорённости.</b> Решения, договорённости, открытые вопросы и вехи — отдельным экраном с отбором по виду и дате.</p>
      <p class="sub">Вопросы — администратору проекта.</p></div>`;
  },

  async prep() { // «Подготовка встречи» — как в ERP: ближайшая встреча, план, материалы, протокол
    const rows = await api(`/api/projects/${S.project}/prep`);
    const today = new Date().toISOString().slice(0, 10);
    const future = rows.find((r) => (r.date || "") >= today);
    const nearest = future || rows[0] || null;
    const nearestWord = future ? "Ближайшая встреча" : "Последняя встреча";
    const form = isAdmin() ? `<div class="card stack"><h2 style="margin:0">Новая встреча</h2>
      <div class="row"><input id="p-date" type="date" required><input id="p-label" placeholder="Название (необязательно)">
      <button class="btn btn-primary" id="p-add">Создать</button></div></div>` : "";
    const row = (m) => `<tr><td><a href="#plan/${m.id}">${fmtDate(m.date)}</a>${m.has_protocol ? ` <a class="sub" href="#meeting/${m.id}">протокол →</a>` : ' <span class="sub">протокола нет</span>'}</td><td>${esc(m.label || m.topic || "—")}</td>
      <td>${m.has_plan ? "план собран" : `<span class="sub">плана нет</span>`}</td>
      <td>${esc(m.sources || 0)}</td><td><a class="btn btn-ghost" href="#plan/${m.id}">Открыть план</a></td></tr>`;
    $("#main").innerHTML = `<h1>Подготовка встречи</h1>
      <p class="page-sub">Ближайшая встреча и её план. Новая встреча заводится здесь — одна на дату.</p>
      ${nearest ? `<div class="card stack"><h2 style="margin:0">${nearestWord}: ${fmtDate(nearest.date)}${nearest.label ? " — " + esc(nearest.label) : ""}</h2>
        <p class="sub">${nearest.has_plan ? "план собран" : "плана пока нет"} · материалов ${esc(nearest.sources || 0)}${nearest.topic ? ` · тема: ${esc(nearest.topic)}` : ""}</p>
        <div class="row"><a class="btn btn-primary" href="#plan/${nearest.id}">${nearest.has_plan ? "Открыть план" : "Собрать план"}</a>
        ${nearest.has_protocol ? `<a class="btn" href="#meeting/${nearest.id}">Протокол</a>` : ""}</div></div>` : `<p class="empty">Встреч пока нет — заведите первую.</p>`}
      ${form}
      <div class="card-output"><table><tr><th>Дата</th><th>Название</th><th>План</th><th>Материалов</th><th></th></tr>
      ${rows.length ? rows.map(row).join("") : `<tr><td colspan="5" class="empty">Встреч пока нет.</td></tr>`}</table></div>`;
    const add = $("#p-add");
    if (add) add.onclick = async () => { try { await api(`/api/projects/${S.project}/meetings`, { method: "POST", json: { date: $("#p-date").value, label: $("#p-label").value } }); render(); } catch (e) { toast(e.message); } };
  },

  async plan(id) { // план встречи до её начала — разделы пишет модель, шапку — код
    const p = await api(`/api/meetings/${id}/plan`);
    const srcs = await api(`/api/meetings/${id}/sources`);
    $("#main").innerHTML = `<p><a href="#prep">← Подготовка встречи</a></p>
      <div class="row" style="align-items:baseline"><h1 style="margin:0">План встречи ${fmtDate(p.date)}</h1></div>
      <div class="row" style="margin-bottom:8px"><a class="btn btn-primary" href="#plan/${id}">План</a><a class="btn" href="#meeting/${id}">Протокол</a></div>
      ${p.built_at ? `<p class="sub">собран ${esc(String(p.built_at).slice(0, 16).replace("T", " "))}</p>` : ""}
      <div class="card stack"><label class="sub">Тема встречи<input id="pl-topic" value="${esc(p.topic || "")}" placeholder="без темы"></label>
        ${isAdmin() ? `<div class="row"><button class="btn btn-primary" id="pl-build">${p.markdown ? "Пересобрать план" : "Собрать план"}</button><button class="btn" id="pl-topic-save">Сохранить тему</button><span class="sub" id="pl-state"></span></div>` : ""}
        ${srcs.length ? `<div class="sub">Материалы: ${srcs.map((s) => esc(s.name)).join("; ")}</div>` : `<div class="sub">Материалов к встрече пока нет.</div>`}</div>
      ${p.markdown ? `<article class="doc-content">${md(p.markdown)}</article>` : `<p class="empty">Плана пока нет.${isAdmin() ? " Нажмите «Собрать план»." : ""}</p>`}`;
    const saveTopic = async () => { try { await api(`/api/meetings/${id}/topic`, { method: "POST", json: { topic: $("#pl-topic").value } }); toast("Тема сохранена."); render(); } catch (e) { toast(e.message); } };
    const ts = $("#pl-topic-save"); if (ts) ts.onclick = saveTopic;
    const build = $("#pl-build");
    if (build) build.onclick = async () => { const st = $("#pl-state"); build.disabled = true; st.textContent = "собираю…";
      try { const r = await api(`/api/meetings/${id}/plan/build`, { method: "POST" }); toast(`План собран, вызовов ${r.calls}, ${String(r.cost_usd).replace(".", ",")} $`); render(); }
      catch (e) { build.disabled = false; st.textContent = ""; toast(e.message); } };
  },

  async meeting(id) {
    const srcs = await api(`/api/meetings/${id}/sources`);
    const rec = await api(`/api/meetings/${id}/recognition`).catch(() => null);
    const pl = await api(`/api/meetings/${id}/plan`).catch(() => null);
    let proto = null; try { proto = await api(`/api/meetings/${id}/protocol`); } catch { /* ещё нет */ }
    const notes = (proto && proto.review_notes) || [];
    const versions = isAdmin() ? await api(`/api/meetings/${id}/protocol/versions`).catch(() => []) : [];
    const editing = S.protoEditId === Number(id);
    const editor = proto && editing ? `<div class="card stack"><div class="sub">Правка текста протокола. «Готово» сохранит новую версию, прежняя останется в истории.</div>
      <textarea id="proto-md" style="width:100%;min-height:420px;font-family:inherit;font-size:14px">${esc(proto.markdown)}</textarea>
      <div class="row"><button class="btn btn-primary" id="proto-save">Готово</button><button class="btn" id="proto-cancel">Отменить</button></div></div>` : "";
    const mtasks = await api(`/api/meetings/${id}/tasks`);   // задачи этой встречи (стенд 5)
    const ST = { active: "в работе", done: "выполнена", dropped: "снята" };
    $("#main").innerHTML = `<p><a href="#meetings">← ${esc(S.theme.vocabulary.meetings)}</a></p>
      <h1>${esc(S.theme.vocabulary.protocol)}</h1>
      <div class="row" style="margin-bottom:8px"><a class="btn" href="#plan/${id}">План</a><a class="btn btn-primary" href="#meeting/${id}">Протокол</a>${isAdmin() && proto ? `<button class="btn" id="proto-edit-toggle">${editing ? "Просмотр" : "Правка"}</button>` : ""}<a class="btn btn-ghost" href="#meetings">Все встречи</a></div>
      <p class="sub">${pl && pl.topic ? `Тема: ${esc(pl.topic)} · ` : ""}${proto && proto.leader ? `Вёл встречу: ${esc(proto.leader)} · ` : ""}${proto && proto.built_at ? `собран ${esc(String(proto.built_at).slice(0, 16).replace("T", " "))} · ` : ""}материалов ${srcs.length}</p>
      <div class="card stack"><div class="dropzone" id="drop">Перетащите файлы встречи сюда или <label style="text-decoration:underline;cursor:pointer">выберите<input type="file" id="file" multiple hidden></label></div>
      ${srcs.length ? `<div>${srcs.map((s) => `<span class="badge">${esc({ transcript: "расшифровка", notes: "заметки", other: "материал" }[s.kind] || s.kind)}</span> ${esc(s.name)}${s.local_asr ? ` <a class="btn-link" href="/api/meetings/${encodeURIComponent(id)}/sources/${encodeURIComponent(s.id)}/export" title="Расшифровка распознана здесь — выгрузить в Word">.docx</a>` : ""}`).join("<br>")}</div>` : ""}
      ${rec && (rec.route || rec.error) ? `<p class="sub" id="asr-line">Распознавание: ${rec.error ? esc(rec.error) : `${esc(rec.route || rec.model || "точка не записана")} · реплик ${esc(rec.segments ?? "—")} · говорящих ${esc(rec.speakers ?? "—")} · подписано строк ${esc(rec.signed_lines ?? "—")}${rec.diarization_seconds != null ? ` · разделение ${esc(rec.diarization_seconds)} с` : ""}${rec.voice_samples ? ` · отпечатков в общую базу ${esc(rec.voice_samples)}` : ""}`}</p>` : ""}
      ${isAdmin() ? `<div class="row" style="gap:10px;align-items:center"><button class="btn btn-primary" id="run">${proto ? "Пересобрать протокол" : "Сформировать протокол"}</button><span class="sub" id="build-state" role="status"></span></div>` : ""}</div>
      ${proto ? `${editor || `<div class="doc-with-notes"><div><div class="row" style="justify-content:flex-end;margin-bottom:8px"><a class="btn" href="/api/meetings/${encodeURIComponent(id)}/protocol.docx">Скачать .docx</a></div>
      <article class="doc-content">${md(proto.markdown)}</article></div>
      ${isAdmin() ? `<aside class="notes-panel"><h2 style="margin-top:0">Замечания проверки · ${notes.length}</h2>${notes.length ? notes.map((n) => `<div class="note">${n.by === "код" ? `<span class="badge">проверка кодом</span> ` : ""}${esc(n.issue)}${n.quote ? `<q>${esc(n.quote)}</q>` : ""}</div>`).join("") : `<p class="empty">Замечаний нет.</p>`}</aside>` : ""}</div>`}
      ${versions.length ? `<details class="more-list"><summary class="disclosure-summary">Версии · ${versions.length}</summary><div class="ribbon">${versions.map((v) => `<div class="note">вер. ${esc(v.version)} · ${esc(v.model || "")} · ${esc(String(v.built_at || "").slice(0, 16))}${isAdmin() ? ` <button class="btn-link" data-proto-restore="${esc(v.version)}">Вернуть</button>` : ""}</div>`).join("")}</div></details>` : ""}` : `<p class="empty">Протокола пока нет.</p>`}
      ${mtasks.length ? `<div class="card-output"><h2 style="margin-top:0">Задачи встречи · ${mtasks.length}</h2>${moreItems(mtasks, (t) => `<div class="note">${esc(t.description)} <span class="sub">— ${esc(t.assignee || "не назначен")} · ${esc(ST[t.status] || t.status)}</span>${t.doubt_reason ? `<span class="doubt-dot" title="под вопросом: ${esc(t.doubt_reason)} — карточка в «Конфликтах»" aria-label="под вопросом"></span>` : ""} <a class="sub" href="#tasks">в реестре →</a></div>`)}</div>` : ""}
      ${proto && proto.units && proto.units.length ? `<div class="card-output"><h2 style="margin-top:0">${esc(S.theme.vocabulary.units || "Из записи встречи")}: решения, договорённости, вопросы, вехи</h2>
        <p class="sub">Собрано из записи с цитатой. Протокол при этом не меняется. Убранное можно вернуть.</p>
        ${moreItems(proto.units, (u) => `<div class="note"><span class="badge">${esc(u.kind_ru)}</span> ${u.ts ? `<span class="meta">${esc(u.ts)}</span>` : ""} ${esc(u.text)}
          ${u.status !== "open" && u.status !== "active" ? `<span class="sub">${esc({ closed: "закрыто", replaced: "заменено", removed: "убрано" }[u.status] || u.status)}${u.why && u.status !== "removed" ? " — " + esc(u.why) : ""}</span>` : ""}
          ${u.roles.length ? `<span class="sub">${u.roles.map((r) => esc(r.role + ": " + r.person)).join(" · ")}</span>` : ""}
          <q>${esc(u.quote)}</q>
          ${isAdmin() ? (u.status === "removed" || u.status === "closed" || u.status === "replaced" ? `<button class="btn btn-ghost" data-ureturn="${u.id}">Вернуть</button>` : `<button class="btn btn-ghost btn-danger" data-uremove="${u.id}">Убрать</button>`) : ""}</div>`)}</div>` : ""}`;
    const upload = async (files) => { for (const f of files) { const fd = new FormData(); fd.append("file", f);
      try { const r = await api(`/api/meetings/${id}/sources`, { method: "POST", body: fd }); toast(r.status === "duplicate" ? `«${f.name}» уже загружен` : `«${f.name}» принят`); } catch (e) { toast(e.message); } } render(); };
    $("#file").onchange = (e) => upload(e.target.files);
    const dz = $("#drop");
    document.ondragover = (e) => { e.preventDefault(); dz.classList.add("drag-over"); };
    document.ondragleave = () => dz.classList.remove("drag-over");
    document.ondrop = (e) => { e.preventDefault(); dz.classList.remove("drag-over"); upload(e.dataTransfer.files); };
    $("#main").querySelectorAll("[data-uremove]").forEach((b) => b.onclick = async () => { try { await api(`/api/units/${b.dataset.uremove}/remove`, { method: "POST" }); toast("Пункт убран. Его можно вернуть."); render(); } catch (e) { toast(e.message); } });
    $("#main").querySelectorAll("[data-ureturn]").forEach((b) => b.onclick = async () => { try { await api(`/api/units/${b.dataset.ureturn}/return`, { method: "POST" }); toast("Пункт возвращён."); render(); } catch (e) { toast(e.message); } });
    const et = $("#proto-edit-toggle");
    if (et) et.onclick = () => { S.protoEditId = editing ? null : Number(id); render(); };
    const ps = $("#proto-save");
    if (ps) ps.onclick = async () => { try { const r = await api(`/api/meetings/${id}/protocol/edit`, { method: "POST", json: { markdown: $("#proto-md").value } }); S.protoEditId = null; toast(`Сохранено, версия ${r.version}.`); render(); } catch (e) { toast(e.message); } };
    const pc = $("#proto-cancel");
    if (pc) pc.onclick = () => { S.protoEditId = null; render(); };
    $("#main").querySelectorAll("[data-proto-restore]").forEach((b) => b.onclick = async () => { try { const r = await api(`/api/meetings/${id}/protocol/restore`, { method: "POST", json: { version: Number(b.dataset.protoRestore) } }); toast(`Версия ${b.dataset.protoRestore} возвращена, новая версия ${r.version}.`); render(); } catch (e) { toast(e.message); } });
    // Состояние сборки — одной строкой рядом с кнопкой, из очереди в базе (находки стенда 3, 4, 41): «в очереди, N-я»
    // или «идёт с чч:мм», без счётчика секунд; видно и после перезагрузки страницы. Кнопка ставит сборку в очередь.
    const run = $("#run"), bst = $("#build-state");
    const showBuild = (st) => {
      if (!bst) return;
      const busy = st.status === "queued" || st.status === "running";
      if (run) { run.disabled = busy; }
      bst.innerHTML = st.status === "running" ? `идёт сборка с ${esc(String(st.started_at || "").slice(11, 16))}`
        : st.status === "queued" ? `в очереди сборок${st.position > 1 ? `, ${esc(st.position)}-я` : ""}${st.not_before ? ` · не раньше ${esc(String(st.not_before).slice(11, 16))}` : ""}` : "";
      return busy;
    };
    const watchBuild = async () => {
      let was = false;
      for (;;) {
        let st; try { st = await api(`/api/meetings/${id}/build`); } catch { return; }   // экран сменился — не следим
        const busy = showBuild(st);
        if (!busy) { if (was) { toast("Протокол собран."); render(); } return; }
        was = true; await new Promise((ok) => setTimeout(ok, 3000));
      }
    };
    if (run) run.onclick = async () => { run.disabled = true;
      try { showBuild(await api(`/api/meetings/${id}/enqueue`, { method: "POST" })); watchBuild(); }
      catch (e) { run.disabled = false; toast(e.message); } };
    watchBuild();
  },

  async team() {
    const rows = await api(`/api/projects/${S.project}/people`);
    // своя команда — фамилия и имя; внешняя — организация и роль, ФИО не обязательно (решение 03.10.26)
    $("#main").innerHTML = `<h1>${esc(S.theme.vocabulary.team)}</h1>${isAdmin() ? `<div class="card row"><input id="p-name" placeholder="Фамилия Имя (внешнему — как называют)"><input id="p-role" placeholder="Роль на проекте"><input id="p-dept" placeholder="Отдел"><input id="p-org" placeholder="Организация (для внешних)"><label class="row" style="gap:6px"><input type="checkbox" id="p-ext"> внешняя команда</label><button class="btn btn-primary" id="p-add">Завести</button></div>` : ""}
      <div class="card-output">${rows.length ? moreRows("<tr><th>№</th><th>ФИО</th><th>Роль</th><th>Отдел</th><th>Организация</th></tr>", rows, (p, i) => `<tr><td class="no">${i + 1}</td><td>${esc(p.full_name)}${p.confirmed ? "" : ' <span class="badge">не подтверждён</span>'}${p.external ? ' <span class="badge">внешний</span>' : ""}</td><td>${esc(p.role)}</td><td>${esc(p.department)}</td><td>${esc(p.organization || "")}</td></tr>`) : `<p class="empty">Команда пуста.</p>`}</div>`;
    const add = $("#p-add");
    // новый человек сверяется с «Командой» до записи: совпала фамилия — вопрос «тот же или новый?» (письмо 13)
    const send = (confirm_new) => api(`/api/projects/${S.project}/people`, { method: "POST", json: { full_name: $("#p-name").value, role: $("#p-role").value, department: $("#p-dept").value, organization: $("#p-org").value, external: $("#p-ext").checked, confirm_new } });
    if (add) add.onclick = async () => {
      try { await send(false); render(); }
      catch (e) {
        if (/подтвердите/.test(e.message) && window.confirm(`${e.message}\n\nЗавести как нового человека?`)) {
          try { await send(true); render(); } catch (e2) { toast(e2.message); }
        } else toast(e.message);
      } };
  },

  async cards() {
    const rows = await api(`/api/projects/${S.project}/cards`);
    // Категории — как вкладки ERP «Разбор»; норма открытых — 15.
    const CAT = { tasks: ["assign_person", "task_doubt", "due_unconfirmed"],
      people: ["assign_person"], projects: [], agreements: ["review_finding"], system: ["technical"] };
    const cur = S.cardsTab || "all";
    const visible = cur === "all" ? rows : rows.filter((c) => (CAT[cur] || []).includes(c.kind));
    const count = (key) => key === "all" ? rows.length : rows.filter((c) => (CAT[key] || []).includes(c.kind)).length;
    const tabs = [["all", "Все"], ["tasks", "Задачи"], ["people", "Люди и голоса"],
      ["projects", "Проекты и справочники"], ["agreements", "Договорённости"], ["system", "Система"]]
      .map(([k, t]) => `<button class="btn ${cur === k ? "btn-primary" : ""}" data-card-tab="${k}">${t}${count(k) ? ` · ${count(k)}` : ""}</button>`).join("");
    const why = { no_verbatim_quote: "нет дословной цитаты", no_assignee: "исполнитель не назван", assignee_not_in_team: "человека нет в Команде",
      assignee_ambiguous: "неясно, о ком речь", duplicate: "похоже на существующую задачу", question_not_assignment: "это вопрос, а не поручение",
      negation_in_quote: "в цитате отрицание", suspicious_instruction: "в тексте похоже на внедрённую инструкцию",
      report_not_assignment: "похоже на отчёт о сделанном, а не на поручение",
      same_or_new: "рядом признак, что это может быть другой человек",
      department_without_head: "назван отдел, а руководителя у отдела нет" };
    const st = { done: "выполнено", dropped: "снято" };
    const body = (c) => {
      const p = c.payload;
      // срок модели не прозвучал рядом с поручением: задача без срока, «Подтвердить» ставит предложенный (12.10.26)
      if (c.kind === "due_unconfirmed") return `<span class="sub">${esc(p.evidence_quote || "")}</span>
        <div class="row"><button class="btn btn-primary" data-r="${c.id}" data-s="accepted">Поставить срок ${esc(p.proposed_text || "")}</button>
        <button class="btn btn-ghost" data-r="${c.id}" data-s="rejected">Оставить без срока</button></div>`;
      // задача уже в реестре и в протоколе под вопросом (решение владельца 15.10.26): подтвердить, снять или дубль
      if (c.kind === "task_doubt") return `<span class="sub">Задача уже в реестре и в протоколе. Подтвердите её или снимите.${p.candidates && p.candidates.length ? " Если исполнитель другой — выберите его." : ""}</span>
        ${(p.candidates || []).map((x) => `<div class="row"><button class="btn" data-r="${c.id}" data-s="accepted" data-choice="${esc(x.id != null ? x.id : x.name)}">${esc(x.name)}</button>
          <span class="sub">${x.hints && x.hints.length ? x.hints.map(esc).join(" · ") : ""}</span></div>`).join("")}
        <div class="row">${(p.buttons || [{ action: "accept", label: "Подтвердить" }, { action: "custom", label: "Своя формулировка" }, { action: "reject", label: "Не задача" }])
          .map((b, i) => `<button class="btn ${i === 0 ? "btn-primary" : b.action === "duplicate" ? "btn-ghost" : ""}" data-doubt-act="${esc(b.action)}" data-card="${c.id}">${esc(b.label)}</button>`).join(" ")}</div>
        <div class="row" hidden id="custom-${c.id}"><input id="custom-text-${c.id}" placeholder="Своя формулировка задачи" value="${esc(p.description || "")}" style="min-width:360px"><button class="btn btn-primary" data-doubt-save="${c.id}">Сохранить формулировку</button></div>`;
      // задача уже заведена без исполнителя; выбор ставит исполнителя в неё (решение владельца 03.10.26, письмо 30)
      if (c.kind === "assign_person") return `<span class="sub">Задача уже в реестре без исполнителя. ${p.reason === "same_or_new" ? `Тот же человек или новый? Рядом: ${(p.marks || []).map(esc).join(", ")}.` : p.reason === "unknown" ? `«${esc(p.mention || "")}» нет в «Команде». Назначьте исполнителя в реестре или заведите нового.` : "Кто из них? Подсказки только упорядочивают список."}</span>
        ${(p.candidates || []).map((x) => `<div class="row"><button class="btn ${p.reason === "same_or_new" ? "btn-primary" : ""}" data-r="${c.id}" data-s="accepted" data-choice="${esc(x.id != null ? x.id : x.name)}">${p.reason === "same_or_new" ? "Это он: " : ""}${esc(x.name)}</button>
          <span class="sub">${x.hints && x.hints.length ? x.hints.map(esc).join(" · ") : ""}</span></div>`).join("")}
        ${p.reason === "same_or_new" || p.reason === "unknown" ? `<div class="row"><input id="nn-${c.id}" placeholder="Новый человек: как называют" value="${esc(p.mention || "")}"><input id="no-${c.id}" placeholder="Организация"><input id="nr-${c.id}" placeholder="Роль на проекте">
          <button class="btn" data-new="${c.id}">Завести нового и назначить</button></div>` : ""}
        <div class="row"><button class="btn btn-ghost" data-r="${c.id}" data-s="rejected">Оставить без исполнителя</button></div>`;
      if (p.marks && p.marks.length && p.candidates && p.candidates.length) return `<span class="sub">Тот же человек или новый? Рядом: ${p.marks.map(esc).join(", ")}. Ответ «это он» запомнится, и в следующий раз вопроса не будет.</span>
        <div class="row">${p.candidates.map((x) => `<button class="btn btn-primary" data-r="${c.id}" data-s="accepted" data-choice="${esc(x.id != null ? x.id : x.name)}">Это он: ${esc(x.name)}</button>`).join("")}
        <a class="btn" href="#team">Новый человек — завести в «Команде»</a>
        <button class="btn btn-ghost" data-r="${c.id}" data-s="rejected">Не человек</button></div>`;
      if (p.candidates && p.candidates.length) return `<span class="sub">О ком речь? Выберите — задача заведётся на этого человека. Подсказки только упорядочивают список.</span>
        ${p.candidates.map((x) => `<div class="row"><button class="btn" data-r="${c.id}" data-s="accepted" data-choice="${esc(x.id != null ? x.id : x.name)}">${esc(x.name)}</button>
          <span class="sub">${x.hints.length ? x.hints.map(esc).join(" · ") : "подсказок нет"}</span></div>`).join("")}
        <div class="row"><button class="btn btn-ghost" data-r="${c.id}" data-s="rejected">Не задача</button></div>`;
      const list = p.closings ? `<ol>${p.closings.map((x) => `<li>${esc(st[x.status] || x.status)}: «${esc(x.quote)}»</li>`).join("")}</ol>` : "";
      return `${list}<div class="row"><button class="btn btn-primary" data-r="${c.id}" data-s="accepted">Подтвердить</button>
        <button class="btn" data-r="${c.id}" data-s="rejected">Не нужно</button></div>`;
    };
    $("#main").innerHTML = `<h1>Разбор</h1><p class="page-sub">Здесь только то, что система не решила сама. «Подтвердить» выполняет предложенное: заводит задачу или применяет закрытие.</p>
      <p class="sub">Открыто ${rows.length} (норма ≤ 15)${rows.length > 15 ? ' <span class="overdue">— больше нормы</span>' : ""}.</p>
      <div class="row" style="margin-bottom:10px">${tabs}</div>
      ${visible.length ? moreItems(visible, (c) => `<div class="card-output stack"><strong>${esc(c.title)}</strong>
        ${c.payload.reasons ? `<span class="sub">Почему: ${c.payload.reasons.map((r) => esc(why[r] || r)).join(", ")}</span>` : ""}
        ${c.payload.quote ? `<q class="sub">${esc(c.payload.quote)}</q>` : ""}
        ${body(c)}</div>`) : `<p class="empty">${rows.length ? "В этой вкладке пусто." : "Очередь пуста."}</p>`}`;
    $("#main").querySelectorAll("[data-card-tab]").forEach((b) => b.onclick = () => { S.cardsTab = b.dataset.cardTab; render(); });
    $("#main").querySelectorAll("[data-new]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.new;
      try {
        await api(`/api/cards/${id}/resolve`, { method: "POST", json: { status: "accepted", new_full_name: $(`#nn-${id}`).value, new_organization: $(`#no-${id}`).value, new_role: $(`#nr-${id}`).value } });
        toast("Новый человек заведён и назначен исполнителем."); render();
      } catch (e) { toast(e.message); } });
    // карточка «под вопросом»: кнопки из общей таблицы (Подтвердить / Своя формулировка / Не задача / Это дубль)
    const doubtAct = async (cid, action, resolution = "") => {
      try { await api(`/api/cards/${cid}/resolve`, { method: "POST", json: { status: action === "accept" || action === "custom" ? "accepted" : "rejected", action, resolution } });
        toast("Решение записано."); render(); } catch (e) { toast(e.message); } };
    $("#main").querySelectorAll("[data-doubt-act]").forEach((b) => b.onclick = () => {
      if (b.dataset.doubtAct === "custom") { const row = $(`#custom-${b.dataset.card}`); row.hidden = false; $(`#custom-text-${b.dataset.card}`).focus(); return; }
      doubtAct(b.dataset.card, b.dataset.doubtAct); });
    $("#main").querySelectorAll("[data-doubt-save]").forEach((b) => b.onclick = () => doubtAct(b.dataset.doubtSave, "custom", $(`#custom-text-${b.dataset.doubtSave}`).value));
    $("#main").querySelectorAll("[data-r]").forEach((b) => b.onclick = async () => {
      try {
        const r = await api(`/api/cards/${b.dataset.r}/resolve`, { method: "POST", json: { status: b.dataset.s, choice: b.dataset.choice || "", resolution: b.dataset.res || "" } });
        toast(r.rule ? `Решение записано. Правило: ${r.rule}` : "Решение записано."); render();
      } catch (e) { toast(e.message); } });
  },

  async decisions() {
    const rows = await api(`/api/projects/${S.project}/decisions`);
    $("#main").innerHTML = `<h1>Реестр решений</h1><div class="card-output">${rows.length ? moreRows("<tr><th>Что</th><th>Решение</th><th>Почему</th><th>Когда</th></tr>", rows, (d) => `<tr><td>${esc(d.what)}</td><td>${esc(d.decision)}</td><td>${esc(d.why)}</td><td>${fmtDate(d.at)}</td></tr>`) : `<p class="empty">Решений пока нет.</p>`}</div>`;
  },

  // «Модели» — отдельный пункт левой панели супер-администратора (владелец 09.10.26); рисует тот же код, что
  // была вкладка мониторинга, только без полосы вкладок.
  async models() { return routes.monitoring("models", true, "Модели"); },

  async voices() { // «База голосов» — отдельный пункт меню, как в ERP; путь к базе — здесь же, по паролю
    await routes.monitoring("voices", true, "База голосов");
    const st = await api("/api/monitoring/voice-base");
    $("#main").insertAdjacentHTML("beforeend", `<div class="card stack"><h2 style="margin:0">Файл базы голосов</h2>
      <div class="sub">Путь к файлу общей базы (например voices.db). База только читается. Смена — по паролю супер-администратора.</div>
      <input id="vb-path" placeholder="Полный путь к файлу базы" value="${esc(st.path || "")}"><input id="vb-repeat" placeholder="Повторите путь">
      ${S.auth ? "" : '<input id="vb-login" placeholder="Логин супер-администратора">'}<input id="vb-pass" type="password" placeholder="Пароль супер-администратора" autocomplete="current-password">
      <button class="btn btn-primary" id="vb-save">Сохранить путь</button></div>`);
    $("#vb-save").onclick = async () => { try { await api("/api/settings/voice-base", { method: "POST", json: { path: $("#vb-path").value, path_repeat: $("#vb-repeat").value, login: ($("#vb-login") || {}).value || "", current_password: $("#vb-pass").value } }); toast("Путь к базе голосов сохранён."); render(); } catch (e) { toast(e.message); } };
  },

  async "voice-review"(tab) { // «Разбор голосов» 1:1 с ERP: очередь новых отпечатков и решённые
    const done = tab === "done";
    const d = await api(`/api/monitoring/voice-review?tab=${done ? "done" : "queue"}`);
    const err = d.error ? `<p class="overdue">${esc(d.error)}</p>` : "";
    const tabs = `<div class="row"><a class="btn ${done ? "" : "btn-primary"}" href="#voice-review">На проверку${d.klasterov != null && !done ? ` · ${esc(d.klasterov)}` : ""}</a>
      <a class="btn ${done ? "btn-primary" : ""}" href="#voice-review/done">Опознанные и решённые${done ? ` · ${esc(d.klasterov || 0)}` : ""}</a></div>`;
    const rule = d.pravilo ? `Правило: «опознан» при близости не ниже ${String(d.pravilo.porog).replace(".", ",")} и отрыве от второго кандидата не ниже ${String(d.pravilo.otryv).replace(".", ",")}, «вероятно» — от ${String(d.pravilo.podskazka).replace(".", ",")}; речи у говорящего — не меньше ${esc(d.pravilo.min_sek)} с.` : "";
    const etalon = d.etalon ? ` Эталон сейчас: людей ${esc(d.etalon.lyudey)}, отпечатков ${esc(d.etalon.otpechatkov)}.` : "";
    const head = done
      ? `<h1>Разбор голосов</h1><p class="page-sub">Принятые правилом и решённые человеком — только просмотр. «Не он» у принятого правилом возвращает говорящего в очередь.</p>${tabs}
         <p class="sub">Кластеров ${esc(d.klasterov || 0)}, отпечатков ${esc(d.otpechatkov || 0)}; по правилу ${esc(d.po_pravilu || 0)}, человеком ${esc(d.lyudmi || 0)}.</p>`
      : `<h1>Разбор голосов</h1><p class="page-sub">Новые отпечатки общей базы голосов — кто говорит. «Это он» и «Другой человек» кладут отпечатки в центр человека; «Не он» и «Шум» больше не предлагаются. Отрывок хранится только до решения.</p>${tabs}
         <p class="sub">Ждут разбора: ${esc(d.klasterov || 0)} говорящих, отпечатков ${esc(d.otpechatkov || 0)}, с отрывком ${esc(d.s_otryvkom || 0)}. ${rule}${etalon} Без материала для проверки: ${esc(d.bez_materiala || 0)}.</p>`;
    const clip = (o) => o.otryvok
      ? `<audio controls preload="none" style="width:100%;max-width:420px" src="/api/monitoring/voice-review/clip/${encodeURIComponent(o.id)}"></audio>`
      : "";
    const speaker = (k) => `<div class="card-output"><div class="row" style="justify-content:space-between;align-items:baseline">
        <b>${esc(k.label || "Говорящий")}</b><span class="sub">${esc(k.data || k.ref || "")}${k.meeting_key ? ` · встреча ${esc(k.meeting_key)}` : ""} · ${esc(k.vsego || 0)} отп.${k.seconds != null ? ` · ${esc(k.seconds)} с` : ""}</span></div>
      ${k.prichina ? `<div class="sub">${esc(k.prichina)}</div>` : ""}
      ${(k.otpechatki || []).map((o) => `<div class="note"><span class="meta">${esc(o.vremya || "")}</span> ${esc(o.phrase || "")}${clip(o)}</div>`).join("")}
      <div class="row" style="margin-top:8px">${k.ids && k.ids.length ? `<button class="btn btn-primary" data-vr-yes="${k.ids.join(",")}" data-vr-name="${esc(k.kandidat || "")}">Это он${k.kandidat ? ` — ${esc(k.kandidat)}` : ""}</button>
        ${k.dva_kandidata && k.second ? `<button class="btn" data-vr-yes="${k.ids.join(",")}" data-vr-name="${esc(k.second)}">Это ${esc(k.second)}</button>` : ""}
        <button class="btn" data-vr-other="${k.ids.join(",")}">Другой человек</button>
        <button class="btn btn-ghost" data-vr-no="${k.ids.join(",")}">Не он</button>
        <button class="btn btn-ghost" data-vr-noise="${k.ids.join(",")}">Шум / не голос</button>` : `<span class="sub">решение уже принято</span>`}</div></div>`;
    const groups = (d.gruppy || []).map((g) => `<h2>${esc(g.imya || "Похоже на кого-то")}</h2>${(g.klastery || []).map(speaker).join("")}`).join("");
    const decided = (d.klastery || []).map((k) => `<div class="card-output"><div class="row" style="justify-content:space-between;align-items:baseline">
        <b>${esc(k.label || "Говорящий")}</b><span class="sub">${esc(k.data || k.ref || "")} · ${esc(k.vsego || 0)} отп. · ${esc(k.reshenie_tekst || k.reshenie || "")}</span></div>
      <div>${k.imya ? `<b>${esc(k.imya)}</b>` : "—"}${k.pravilo ? `<span class="sub"> · ${esc(k.pravilo)}</span>` : ""}${k.kto ? `<span class="sub"> · решил ${esc(k.kto)} ${esc(k.kogda || "")}</span>` : ""}</div>
      ${k.ne_on && k.ids && k.ids.length ? `<div class="row"><button class="btn btn-ghost" data-vr-dismiss="${k.ids.join(",")}">Не он</button></div>` : ""}</div>`).join("");
    $("#main").innerHTML = `${head}${err}${done ? (decided || '<p class="empty">Решённых пока нет.</p>') : (groups || '<p class="empty">Непонятных голосов нет — разбирать нечего.</p>')}`;
    const act = async (ids, decision, name = "") => { try { await api("/api/monitoring/voice-review/apply", { method: "POST", json: { ids: ids.split(",").map(Number), decision, name } }); toast("Решение записано."); render(); } catch (e) { toast(e.message); } };
    $("#main").querySelectorAll("[data-vr-yes]").forEach((b) => b.onclick = () => act(b.dataset.vrYes, "yes", b.dataset.vrName || ""));
    $("#main").querySelectorAll("[data-vr-no]").forEach((b) => b.onclick = () => act(b.dataset.vrNo, "no"));
    $("#main").querySelectorAll("[data-vr-noise]").forEach((b) => b.onclick = () => act(b.dataset.vrNoise, "noise"));
    $("#main").querySelectorAll("[data-vr-other]").forEach((b) => b.onclick = () => { const n = prompt("ФИО из «Команды», кем оказался говорящий:"); if (n && n.trim()) act(b.dataset.vrOther, "other", n.trim()); });
    $("#main").querySelectorAll("[data-vr-dismiss]").forEach((b) => b.onclick = async () => { try { await api("/api/monitoring/voice-review/dismiss", { method: "POST", json: { ids: b.dataset.vrDismiss.split(",").map(Number) } }); toast("Возвращён в очередь."); render(); } catch (e) { toast(e.message); } });
  },

  async teamshared() { // общая «Команда» Планёрки и ERP — только чтение (задание 24.10.2026, раздел 0)
    const st = await api("/api/monitoring/team-shared");
    const rows = st.people_all || [];
    const state = !st.enabled ? "выключена" : st.ok ? "доступна, только чтение"
      : `<span class="overdue">${esc(st.detail || "недоступна")}</span>`;
    $("#main").innerHTML = `<h1>Общая команда</h1>
      <div class="card-output"><table>
        <tr><th>Что</th><th>Значение</th></tr>
        <tr><td>Файл общей базы</td><td class="meta">${st.path ? esc(st.path) : "не задан — путь берётся из «Базы голосов»"}</td></tr>
        <tr><td>Состояние</td><td>${state}</td></tr>
        ${st.ok ? `<tr><td>Людей</td><td>${esc(st.people)}</td></tr>
        <tr><td>Подтверждены</td><td>${esc(st.people_confirmed)}</td></tr>
        <tr><td>Внутренних</td><td>${esc(st.internal)}</td></tr>
        <tr><td>Внешних</td><td>${esc(st.external)}</td></tr>
        <tr><td>Внешних подтверждены человеком</td><td>${esc(st.external_confirmed)}</td></tr>
        <tr><td>Внешних ждут подтверждения</td><td>${esc(st.external_waiting)}</td></tr>` : ""}
      </table>
      <p class="sub">Общая «Команда» одна у Планёрки и ERP. Внутренние подтверждены всегда; внешний идёт в работу, только если его подтвердил человек. MeetFlow её только читает, решения по людям принимаются в «Команде» Планёрки и ERP. Файл ищется по пути TEAM_SHARED_PATH, иначе рядом с базой голосов.</p></div>
      ${rows.length ? `<div class="card-output"><h2 style="margin-top:0">Люди</h2>${moreRows("<tr><th>№</th><th>ФИО</th><th>Роль</th><th>Отдел</th><th>Организация</th></tr>", rows, (p, i) => `<tr><td class="no">${i + 1}</td><td>${esc(p.full_name)}${p.external ? (p.confirmed ? ' <span class="badge">внешний</span>' : ' <span class="badge">внешний, не подтверждён человеком</span>') : ""}</td><td>${esc(p.role || "")}</td><td>${esc(p.department || "")}</td><td>${esc(p.organization || "")}</td></tr>`)}</div>` : ""}`;
  },

  async monitoring(tab, solo = false, title = "", prefix = "") {
    // горизонтальные вкладки под разные задачи мониторинга (по образцу «Технических служб» Планёрки)
    if (!solo) { location.replace(tab === "models" ? "#models" : "#live"); return; }   // прежний «Мониторинг» — теперь «Мониторинг RealTime» и «Параметры системы»
    const cur = ["models", "voices", "runs", "cost", "todo"].includes(tab) ? tab : "models";
    const kv = (rows) => `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
    let body = "";
    if (cur === "models") {
      // Модели (решение владельца 09.10.26) — пульт оператора маршрутов: роли (основная, запасные), справочник
      // подключений (завести заранее, даже без адреса; изменить; проверить до сохранения; удалить), журнал и откат.
      // Только супер-администратору, права проверяет сервер.
      const d = await api("/api/monitoring/models");
      S.routes = d;
      const ROLE = d.role_titles || { asr: "Распознавание речи", generate: "Генерация черновика", verify: "Проверка черновика" };
      const st = (s) => s.startsWith("выведена") ? `<span class="overdue">${esc(s)}</span>` : s === "основная" ? `<strong>${esc(s)}</strong>` : esc(s);
      const shortModel = m => String(m || "").split(String.fromCharCode(92)).join("/").replace(/^.*models--[^/]*--([^/]+)[/]snapshots[/].*$/, "$1");
      const opts = d.options || {};
      const can = (role) => role === "asr" ? d.asr_switchable : d.switchable;
      // все роли видны всегда: роль без точек — «не настроена», вызовов нет (модели по умолчанию нет, 13.10.26)
      const order = ["generate", "verify", "asr", "guard"];
      const eps = d.endpoints || [];
      const fieldText = (e) => { const f = e.fields || {}; return [shortModel(f.model), f.callable, f.url, f.path ? "папка " + f.path : "", f.device ? "device " + f.device : ""].filter(Boolean).join(" · "); };
      const ACT = { use: "основная", add: "запасная", remove: "убрана из роли", new: "новое подключение", edit: "изменено", delete: "удалено", rollback: "откат", presets: "справочник заготовок", key_set: "ключ задан", key_replace: "ключ заменён", key_delete: "ключ удалён" };
      const nDraft = eps.filter((e) => e.missing).length;
      const word = (n) => n % 10 === 1 && n % 100 !== 11 ? "подключение" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "подключения" : "подключений";
      body = !d.editable ? `<p class="page-sub page-sub-wide">${esc(d.note)}</p>` : `<p class="page-sub page-sub-wide">Маршрутизация по ролям: вызов обслуживает первая доступная точка цепочки, остальные — резерв по порядку. Отказ точки (нет соединения, 5xx/429 после повторов, таймаут, 401–404) выводит её на ${esc(d.cooldown_sec)} с (circuit breaker), вызов переходит к следующей. Изменения пишутся в файл атомарно и применяются без перезапуска. Когда применится смена: идущий вызов дожидается своего ответа, следующий идёт на новую модель; если в это время собирается протокол, через 15 минут и после конца сборки он соберётся заново на новой модели — о смене и о пересборке будет системное сообщение.${d.switchable ? "" : " " + esc(d.note)} Файл: <span class="meta">${esc(d.path)}</span></p>
        ${order.map((role) => { const pts = d.roles[role] || []; const o = opts[role] || [];
          const spare = o.filter((x) => !pts.some((p) => p.name === x.name));
          const pick = pts.length ? spare : o;
          return `<div class="card-output"><h2 style="margin-top:0">${esc(ROLE[role] || role)}</h2>
          ${can(role) && pick.length ? `<div class="row" style="margin-bottom:10px; gap:8px; align-items:center; flex-wrap:wrap"><span class="sub">Резерв из реестра:</span>
            <select data-route-pick="${esc(role)}" style="min-width:280px">${pick.map((x) => `<option value="${esc(x.name)}">${esc(x.name)} — ${esc(shortModel(x.model) || x.kind)}</option>`).join("")}</select>
            ${pts.length ? `<button class="btn btn-outline" data-route-pick-add="${esc(role)}">Добавить запасной</button>` : `<button class="btn btn-outline" data-route-pick-apply="${esc(role)}">Сделать основной</button>`}</div>`
            : o.length ? "" : '<p class="sub">В реестре нет готовых точек этого рода — заведите подключение в «Списке подключений».</p>'}
          ${pts.length ? `<table><tr><th></th><th>Точка</th><th>Модель</th><th>Сервер</th><th>Состояние</th></tr>${pts.map((p, i) => `<tr class="${i === 0 ? "route-row-on" : ""}">
            <td style="width:34px; text-align:center">${i === 0 ? '<span class="route-radio on" title="Основная" aria-label="основная"></span>'
              : can(role) ? `<button class="route-radio" data-route-use="${esc(role)}|${esc(p.name)}" title="Сделать основной" aria-label="Сделать основной: ${esc(p.name)}"></button>` : ""}</td>
            <td class="meta">${esc(p.name)} <button class="btn-link" data-route-remove="${esc(role)}|${esc(p.name)}">Убрать</button></td><td title="${esc(p.model)}">${esc(shortModel(p.model))}</td><td class="meta">${esc(p.url || p.kind)}</td>
            <td>${p.state.startsWith("выведена") ? st(p.state) : i === 0 ? `<span class="route-state-on">${esc(p.state)}</span>` : `<span class="sub">${esc(p.state)}</span>`}</td></tr>`).join("")}</table>`
            : role === "verify" && d.verify_fallback ? `<p>модель черновика: <span class="meta">${esc(d.verify_fallback)}</span></p><p class="sub">отдельная модель проверки не назначена — проверяет модель черновика; чтобы назначить свою, выберите подключение и нажмите «Сделать основной»</p>`
            : `<p class="sub"><span class="overdue">не настроена</span> — ${role === "guard" ? "досмотра нет, реплики к системе решает правило" : "вызовов нет: выберите подключение и нажмите «Сделать основной»"}.</p>`}</div>`; }).join("")}
        ${(d.provider_spend || []).length ? `<div class="card-output"><h2 style="margin-top:0">Расход по поставщикам за месяц</h2>${d.provider_spend.map((x) => `<div class="${x.state === "stop" || x.state === "warn" ? "overdue" : "sub"}">${esc(x.label)}</div>`).join("")}</div>` : ""}
        ${order.length ? `<div class="row"><button class="btn btn-outline" id="route-check">Проверить все точки в ролях</button></div><div id="route-check-out" class="sub"></div>` : ""}
        <div class="card-output"><h2 style="margin-top:0">Список подключений</h2>
          <p class="sub">Реестр точек вызова (endpoints в models.json). Текст: openai — OpenAI-совместимый сервер, ollama, openrouter. Распознавание: faster-whisper — модель на этой машине, python — функция «модуль:функция», asr-service — HTTP-сервис во внутренней сети. В вызовах участвуют только точки, назначенные в роли. Точка без обязательных полей имеет статус «не настроено» и в роль не назначается. Секреты в файле не хранятся: key_env — имя переменной окружения.</p>
          <details class="model-book"${S.routesBookOpen ? " open" : ""}><summary class="disclosure-summary">Показать список — ${eps.length} ${word(eps.length)}${nDraft ? `, из них не настроено ${nDraft}` : ""}</summary>
          <table><tr><th>Имя</th><th>Параметры</th><th>Где используется</th></tr>${eps.map((e) => `<tr><td class="meta">${esc(e.name)} <button class="btn-link" data-ep-edit="${esc(e.name)}">Изменить</button> <button class="btn-link btn-link-danger" data-ep-delete="${esc(e.name)}">Удалить</button><div class="sub">${esc(e.kind_title)}</div></td>
            <td>${esc(fieldText(e) || "—")}${e.external ? ' <span class="sub">· внешняя</span>' : ""}${e.key ? `<div class="sub">${esc(e.key)} · <button class="btn-link" data-ep-key="${esc(e.name)}">Заменить ключ</button> <button class="btn-link" data-ep-key-del="${esc(e.name)}">Удалить ключ</button></div>` : ""}${e.tariff ? `<div class="sub">${esc(e.tariff.text)}</div>` : ""}${e.fields && e.fields.note ? `<div class="sub">${esc(e.fields.note)}</div>` : ""}</td>
            <td>${e.missing ? `<span class="overdue">не настроено</span><div class="sub">${esc(e.missing)}</div>` : e.roles.length ? esc(e.roles.map((r) => ROLE[r] || r).join(", ")) : "готово, не в ролях"}</td></tr>`).join("")}</table></details>
          <div class="row" style="margin-top:10px; gap:8px"><button class="btn btn-outline" data-ep-new="text">+ Новое подключение модели</button><button class="btn btn-outline" data-ep-new="asr">+ Новое подключение распознавания</button></div>
          <div id="ep-form"></div></div>
        <div class="card-output"><details class="model-help"><summary class="disclosure-summary">Как подключить внешнюю модель</summary>${EXTERNAL_HELP}</details></div>
        <div class="card-output"><h2 style="margin-top:0">Журнал изменений</h2>
          <p class="sub">Источник — models.log.jsonl. Перед каждой записью файла прежняя версия сохраняется в models.history/ (до 30 версий); откат восстанавливает последнюю сохранённую, повторный — предыдущую.</p>
          ${(d.history || []).length ? `${moreRows("", d.history, (h) => `<tr><td class="meta">${esc(h.at || "")}</td><td>${esc(ACT[h.action || "use"] || h.action)}${h.role ? " — " + esc(ROLE[h.role] || h.role) : ""}${h.point ? ": " + esc(h.point) : ""}</td><td>${esc(h.by || "")}</td></tr>`)}` : '<p class="sub">Записей нет.</p>'}
          <div class="row" style="margin-top:10px; gap:8px; align-items:center"><button class="btn btn-outline" id="route-rollback"${d.versions ? "" : " disabled"}>Откатить последнее изменение</button><span class="sub">Версий в models.history: ${esc(d.versions || 0)}</span></div></div>`;
    } else if (cur === "voices") {
      const v = await api("/api/monitoring/voice-base");
      const dict = (d) => d ? Object.entries(d).map(([k, n]) => `${esc(k)}: ${esc(n)}`).join(" · ") : "—";
      const rec = v.last_recognition || {};
      const people = v.people_list || [];
      const recs = v.recordings || [];
      const writers = Object.entries(v.by_project || {});
      body = `<div class="card-output">${kv([["Файл базы", v.path ? `<span class="meta">${esc(v.path)}</span>` : "не задан — укажите ниже"],
        ["Состояние", v.ok ? "доступна, только чтение" : `<span class="overdue">${esc(v.detail || "недоступна")}</span>`],
        ...(v.ok ? [["Отпечатков голоса", esc(v.samples)], ["Из них привязаны к человеку", esc(v.samples_linked)],
          ["Людей в базе", esc(v.people)], ["Подтверждены", esc(v.people_confirmed)], ["Ждут подтверждения", esc(v.people_waiting)],
          ["Модели отпечатка", dict(v.embedding_models)], ["По проектам", dict(v.by_project)],
          ["Последний отпечаток", v.last_sample_at ? `<span class="meta">${esc(v.last_sample_at)}</span>` : "—"],
          ["Размер", `${esc(v.size_kb)} КБ · журнал ${esc(v.journal_mode)}`]] : [])])}
        <p class="sub">База общая для проектов и здесь только читается. Голос не покидает машину.</p></div>
      <div class="card-output"><h2 style="margin-top:0">Протокол последнего распознавания</h2>
        ${rec.route || rec.error ? `<table><tr><th>Запись</th><th>Точка</th><th>Итог</th></tr>
          <tr><td class="meta">${esc(rec.file || "—")}</td><td class="meta">${esc(rec.route || rec.model || "точка не записана")}</td>
          <td>${rec.error ? `<span class="overdue">${esc(rec.error)}</span>` : `реплик ${esc(rec.segments ?? "—")} · говорящих ${esc(rec.speakers ?? "—")} · подписано ${esc(rec.signed_lines ?? "—")} · отпечатков ${esc(rec.voice_samples ?? 0)}${rec.diarization_seconds != null ? ` · разделение ${esc(rec.diarization_seconds)} с` : ""}`}</td></tr></table>
          <p class="sub">${esc(rec.ts || "")}</p>` : `<p class="empty">Распознаваний ещё не было.</p>`}</div>
      <div class="card-output"><h2 style="margin-top:0">Кто пишет в базу</h2>
        ${writers.length ? `<table><tr><th>Проект</th><th>Отпечатков</th></tr>${writers.map(([k, n]) => `<tr><td class="meta">${esc(k)}</td><td>${esc(n)}</td></tr>`).join("")}</table>` : `<p class="empty">Пока никто.</p>`}
        <p class="sub">Планёрка, ERP и MeetFlow пишут в одну базу; людей заводит и подтверждает оператор.</p></div>
      <div class="card-output"><h2 style="margin-top:0">Подтверждённые люди · ${people.length}</h2>
        ${people.length ? moreRows("<tr><th>ФИО</th><th>Написания</th><th>Подтверждён</th></tr>", people,
          (p) => `<tr><td>${esc(p.full_name)}</td><td class="sub">${esc(p.aliases || "—")}</td><td class="meta">${esc(p.confirmed_at || "—")}</td></tr>`)
          : `<p class="empty">Никого не подтвердили.</p>`}</div>
      <div class="card-output"><h2 style="margin-top:0">С каких записей</h2>
        ${recs.length ? moreRows("<tr><th>Проект · запись</th><th>Отпечатков</th><th>Речи</th><th>Снято</th></tr>", recs,
          (r) => `<tr><td class="meta">${esc(r.project)} · ${esc(r.ref)}</td><td>${esc(r.samples)}</td><td>${esc(Math.round((r.seconds || 0) / 60))} мин</td><td class="meta">${esc(String(r.last || "").slice(0, 16))}</td></tr>`)
          : `<p class="empty">Записей с отпечатками пока нет.</p>`}</div>`;
    } else if (cur === "runs" || cur === "cost") {
      const days = Number(store.get("runs-days", "7"));
      const r = await api(`/api/monitoring/runs?days=${days}`);
      const lim = r.limits || {};
      const tbl = (d, cap) => `<h2>${cap}</h2>${Object.keys(d).length ? `<table><tr><th>${cap === "По дням" ? "День" : cap === "По моделям" ? "Модель" : "Назначение"}</th><th>Вызовов</th><th>$</th><th>Секунд</th><th>Знаков</th></tr>${Object.entries(d).map(([k, x]) => `<tr><td class="meta">${esc(k)}</td><td>${esc(x.calls)}</td><td>${esc(x.cost_usd)}</td><td>${esc(x.seconds)}</td><td>${esc(x.chars)}</td></tr>`).join("")}</table>` : '<p class="empty">Нет данных.</p>'}`;
      body = `<div class="row" style="margin-bottom:12px">${[1, 7, 30].map((d) => `<button class="btn ${d === days ? "btn-primary" : ""}" data-days="${d}">${d === 1 ? "Сутки" : d + " дней"}</button>`).join("")}</div>
        ${cur === "cost" ? `<div class="card-output">${kv([["Вызовов модели", esc(r.calls)], ["Расход", `${esc(r.cost_usd)} $`],
          ["Стоимость успешного прогона", r.cost_per_success_usd != null ? `${esc(r.cost_per_success_usd)} $` : "—"],
          ["Битых строк журнала", esc(r.broken_lines)]])}<p class="sub">${esc(r.note)}</p></div>
        <div class="card-output">${tbl(r.by_purpose, "По назначению")}${tbl(r.by_model, "По моделям")}${tbl(r.by_day, "По дням")}</div>` : `<div class="card-output">${kv([
          ["Прогонов", `${esc(r.runs_total ?? 0)}, из них остановлено по пределу ${esc(r.runs_stopped ?? 0)}`],
          ["Сбоев вызова", esc(r.errors ?? 0)],
          ["Потолки на прогон", `вызовов ${esc(lim.max_calls)} (+${esc(lim.verify_reserve)} на проверку), ${esc(lim.max_cost_usd)} $, ${esc(lim.max_chars_per_call)} знаков, ${esc(lim.max_seconds)} с`]])}</div>
        <div class="card-output"><h2 style="margin-top:0">Последние прогоны</h2>${r.runs && r.runs.length ? `<table><tr><th>Когда</th><th>Встреча</th><th>Итог</th><th>Вызовов</th><th>$</th><th>Задач</th><th>На разбор</th><th>Закрыто</th></tr>${r.runs.map((x) => `<tr><td class="meta">${esc(String(x.ts).replace("T", " "))}</td><td>${esc(x.meeting_id)}</td><td>${x.status === "ok" ? "готово" : x.status === "stopped_by_limit" ? '<span class="overdue">остановлено по пределу</span>' : esc(x.status)}</td><td>${esc(x.calls)}</td><td>${esc(x.cost_usd)}</td><td>${esc(x.added ?? "—")}</td><td>${esc(x.held ?? "—")}</td><td>${esc(x.closed ?? "—")}</td></tr>`).join("")}</table>` : '<p class="empty">Прогонов не было.</p>'}</div>`}`;
    } else {
      const m = await api("/api/monitoring");
      body = `<div class="card-output">${m.todo.length ? m.todo.map((t) => `<div class="sub meta">${esc(t)}</div>`).join("") : '<p class="empty">Заглушек нет.</p>'}</div>`;
    }
    $("#main").innerHTML = `<h1>${esc(title || "Модели")}</h1>${prefix}${body}`;
    $("#main").querySelectorAll("[data-days]").forEach((b) => b.onclick = () => { store.set("runs-days", b.dataset.days); render(); });
    // Пульт моделей: каждое действие — запрос, затем перерисовка; ошибка сервера — в подсказке
    const book = $("#main").querySelector("details.model-book");
    if (book) book.ontoggle = () => { S.routesBookOpen = book.open; };
    const routeAct = async (b, path, json, ok) => {
      b.disabled = true;
      try { await api("/api/monitoring/models" + path, { method: "POST", json }); if (ok) toast(ok); render(); }
      catch (e) { b.disabled = false; toast(e.message); }
    };
    const pick = (role) => $("#main").querySelector(`[data-route-pick="${role}"]`);
    $("#main").querySelectorAll("[data-route-use]").forEach((b) => b.onclick = () => {
      const [role, point] = b.dataset.routeUse.split("|");
      routeAct(b, "/use", { role, point }, `Основная точка — ${point}`);
    });
    $("#main").querySelectorAll("[data-route-remove]").forEach((b) => b.onclick = () => {
      const [role, point] = b.dataset.routeRemove.split("|");
      routeAct(b, "/role", { role, point, action: "remove" }, `«${point}» убрана из роли`);
    });
    $("#main").querySelectorAll("[data-route-pick-apply]").forEach((b) => b.onclick = () => {
      const sel = pick(b.dataset.routePickApply);
      if (sel) routeAct(b, "/use", { role: b.dataset.routePickApply, point: sel.value }, `Основная точка — ${sel.value}`);
    });
    $("#main").querySelectorAll("[data-route-pick-add]").forEach((b) => b.onclick = () => {
      const sel = pick(b.dataset.routePickAdd);
      if (sel) routeAct(b, "/role", { role: b.dataset.routePickAdd, point: sel.value, action: "add" }, `«${sel.value}» — запасная`);
    });
    $("#main").querySelectorAll("[data-ep-delete]").forEach((b) => b.onclick = () => {
      if (!confirm(`Удалить подключение «${b.dataset.epDelete}»? Прежняя версия файла сохранится, её можно вернуть откатом.`)) return;
      routeAct(b, "/endpoint/delete", { name: b.dataset.epDelete, fields: {} }, `Подключение «${b.dataset.epDelete}» удалено`);
    });
    const rb = $("#route-rollback");
    if (rb) rb.onclick = () => routeAct(rb, "/rollback", {}, "Файл маршрутов возвращён к прежней версии");
    const epForm = $("#ep-form");
    const openEpForm = (group, ep) => {
      const kinds = (S.routes || {}).kinds || {};
      const list = Object.keys(kinds).filter((k) => kinds[k].for === group);
      let kind = ep ? ep.kind : list[0];
      const draw = () => {
        const fields = (kinds[kind] || {}).fields || [];
        const tf = ep && ep.tariff && ep.tariff.origin === "точка" ? ep.tariff.form || {} : {};
        const val = (k) => ep && ep.kind === kind ? ((ep.fields || {})[k] ?? tf[k] ?? "") : "";
        const keySrc = (epForm.querySelector('[data-f="key_source"]') || {}).value || val("key_source") || "env";
        const hints = (kinds[kind] || {}).url_hints || [];
        const info = (t) => t ? ` <span class="info-i" title="${esc(t)}" aria-label="${esc(t)}" tabindex="0">i</span>` : "";
        epForm.innerHTML = `<div class="card stack" style="margin-top:12px"><h2 style="margin:0">${ep ? `Подключение «${esc(ep.name)}»` : group === "asr" ? "Новое подключение распознавания" : "Новое подключение модели"}</h2>
          <label class="sub">Имя подключения<input data-f="name" value="${esc(ep ? ep.name : "")}" placeholder="${group === "asr" ? "whisper-medium" : "deepseek-flash"}"></label>
          <label class="sub">Тип подключения<select data-f="kind">${list.map((k) => `<option value="${esc(k)}"${k === kind ? " selected" : ""}>${esc(kinds[k].title)}</option>`).join("")}</select></label>
          ${fields.filter((f) => !(f.key === "key_env" && keySrc === "value")).map((f) => `<label class="sub">${esc(f.label)}${f.required ? "" : " — необязательно"}${info(f.help)}${f.choices
            ? `<select data-f="${esc(f.key)}">${f.choices.map((c) => `<option value="${esc(c)}"${(String(val(f.key)) || f.default || f.choices[0]) === c ? " selected" : ""}>${esc((f.choice_titles || {})[c] || c)}</option>`).join("")}</select>`
            : `<input data-f="${esc(f.key)}" value="${esc(String(val(f.key) || (ep ? "" : f.default || "")))}" placeholder="${esc(f.hint || "")}"${f.key === "url" && hints.length ? ' list="url-hints"' : ""}>`}</label>
            ${f.key === "key_source" && keySrc === "value" ? `<label class="sub">Ключ${info(KEY_HELP)}<input data-k type="password" autocomplete="off" placeholder="${esc(ep && ep.key ? ep.key + " — пусто: не менять" : "вставьте ключ поставщика")}"></label>` : ""}`).join("")}
          ${hints.length ? `<datalist id="url-hints">${hints.map((h) => `<option value="${esc(h.url)}">${esc(h.title)}</option>`).join("")}</datalist>` : ""}
          <label class="sub">Пояснение — необязательно<input data-f="note" value="${esc(ep && ep.fields ? ep.fields.note || "" : "")}" placeholder="например: адрес задаёт оператор"></label>
          <p class="sub">Обязательное поле можно оставить пустым — подключение сохранится заготовкой «не настроено».</p>
          <div class="row" style="gap:10px; align-items:center"><button class="btn btn-outline" data-ep-test>Проверить связь</button><button class="btn btn-primary" data-ep-save>Сохранить</button><button class="btn-link" data-ep-cancel>Отмена</button></div>
          <div class="sub" data-ep-out></div></div>`;
        const read = () => { const o = {}; epForm.querySelectorAll("[data-f]").forEach((i) => { o[i.dataset.f] = i.value.trim(); }); return o; };
        epForm.querySelector('[data-f="kind"]').onchange = (e) => { kind = e.target.value; draw(); };
        const ks = epForm.querySelector('[data-f="key_source"]'); if (ks) ks.onchange = () => draw();
        const keyVal = () => ((epForm.querySelector("[data-k]") || {}).value || "").trim();
        epForm.querySelector("[data-ep-cancel]").onclick = () => { epForm.innerHTML = ""; };
        const out = epForm.querySelector("[data-ep-out]");
        const tb = epForm.querySelector("[data-ep-test]");
        tb.onclick = async () => {
          tb.disabled = true; out.textContent = "Проверяем…";
          try { const f = read(); const r = await api("/api/monitoring/models/endpoint/test", { method: "POST", json: { name: f.name || "проверка", old_name: ep ? ep.name : "", fields: f, key_value: keyVal() } });
            out.innerHTML = `${r.ok ? "работает" : '<span class="overdue">нет</span>'} — ${esc(r.detail)}`; }
          catch (e) { out.textContent = e.message; }
          finally { tb.disabled = false; }
        };
        const sb = epForm.querySelector("[data-ep-save]");
        sb.onclick = () => { const f = read(); routeAct(sb, "/endpoint", { name: f.name, old_name: ep ? ep.name : "", fields: f, key_value: keyVal() }, `Подключение «${f.name}» сохранено`); };
        epForm.scrollIntoView({ block: "nearest" });
      };
      draw();
    };
    $("#main").querySelectorAll("[data-ep-new]").forEach((b) => b.onclick = () => openEpForm(b.dataset.epNew, null));
    $("#main").querySelectorAll("[data-ep-key]").forEach((b) => b.onclick = () => {
      const v = (prompt(`Новый ключ для «${b.dataset.epKey}». Прежний ключ после замены не восстанавливается.`) || "").trim();
      if (v) routeAct(b, "/endpoint/key", { name: b.dataset.epKey, key_value: v }, "Ключ заменён");
    });
    $("#main").querySelectorAll("[data-ep-key-del]").forEach((b) => b.onclick = () => {
      if (confirm(`Удалить ключ подключения «${b.dataset.epKeyDel}»? Вызовы на него пойдут без ключа.`)) routeAct(b, "/endpoint/key", { name: b.dataset.epKeyDel, key_value: "" }, "Ключ удалён");
    });
    $("#main").querySelectorAll("[data-ep-edit]").forEach((b) => b.onclick = () => {
      const ep = ((S.routes || {}).endpoints || []).find((x) => x.name === b.dataset.epEdit);
      const kinds = (S.routes || {}).kinds || {};
      if (ep) openEpForm((kinds[ep.kind] || {}).for || "text", ep);
    });
    const chk = $("#route-check");
    if (chk) chk.onclick = async () => {
      chk.disabled = true;
      const out = $("#route-check-out");
      out.textContent = "Проверяем — короткий запрос на каждую точку…";
      // опрос идёт фоном (стенд 12): ответ — за полсекунды, итог дочитывается раз в секунду, пока опрос не кончится
      const show = (r) => { out.innerHTML = (r.results.length ? r.results.map((x) => `${x.ok ? "работает" : '<span class="overdue">нет</span>'} — ${esc(x.name)}: ${esc(x.detail)}`).join("<br>") : "")
        + (r.running ? `<br><span class="sub">опрос идёт${r.age_sec != null ? ` · выше — итог ${esc(Math.round(r.age_sec))} с назад` : ""}</span>` : (r.age_sec != null ? `<br><span class="sub">итог ${esc(Math.round(r.age_sec))} с назад</span>` : "")); };
      try {
        let r = await api("/api/monitoring/models/check", { method: "POST" });
        for (let i = 0; r.running && i < 600; i++) { show(r); await new Promise((ok) => setTimeout(ok, 1000)); r = await api("/api/monitoring/models/status"); }
        show(r);
      } catch (e) { out.textContent = e.message; }
      finally { chk.disabled = false; }
    };
  },

  async live() { // «Мониторинг RealTime» — как в Проекте ERP: службы, папка-приёмник, автозапуск; обновление раз в 30 с
    const d = await api(`/api/monitoring/live${S.project ? `?pid=${S.project}` : ""}`);
    const stc = (x) => x === "живо" ? `<span class="route-state-on">${x}</span>` : x === "нет" ? `<span class="overdue">${x}</span>` : `<span class="sub">${x}</span>`;
    const i = d.intake; const pname = esc(($("#project").selectedOptions[0] || {}).textContent || "");
    const q = d.queue;
    $("#main").innerHTML = `<h1>Мониторинг RealTime</h1>
      <p class="page-sub">${d.awaiting_total ? `<a href="#system/awaiting">Ждёт ввода от оператора: ${esc(d.awaiting_total)}</a>` : "Ввода от оператора ничего не ждёт."} · <span class="meta" id="live-clock"></span></p>
      <div class="card-output"><h2 style="margin-top:0">Службы</h2><table><tr><th>Служба</th><th>Состояние</th><th>Подробно</th></tr>${d.services.map((r) => `<tr><td>${esc(r.name)}</td><td>${stc(r.state)}</td><td class="sub">${esc(r.detail)}</td></tr>`).join("")}</table>
      ${d.recognition_queue ? `<h2>Очередь распознавания на машине</h2><p class="sub">${d.recognition_queue.configured
        ? (d.recognition_queue.holder ? `сейчас распознаёт ${esc({ planerka: "Планёрка", erp: "Проект ERP", meetflow: "MeetFlow" }[d.recognition_queue.holder] || d.recognition_queue.holder)}: ${esc(d.recognition_queue.job || "—")} с ${fmtDate(d.recognition_queue.since)} ${esc(String(d.recognition_queue.since || "").slice(11, 16))}${d.recognition_queue.stale ? ' <span class="overdue">· без отметки дольше срока — будет снята</span>' : ""}` : "свободна — запись берётся сразу")
          + ` · ждут: Планёрка ${esc((d.recognition_queue.waiting || {}).planerka || 0)}, Проект ERP ${esc((d.recognition_queue.waiting || {}).erp || 0)}`
        : "общая очередь не настроена — задайте путь к базе голосов (рядом с ней лежит файл очереди)"}</p>` : ""}
      ${i ? `<h2>Папка-приёмник проекта «${pname}»</h2>
        <div class="sub">Сейчас: ${i.folder ? `<span class="meta">${esc(i.folder)}</span>` : "не задана"}. Меняется в два шага: адрес и его повтор — система покажет, что заберёт первый проход, — затем пароль супер-администратора. Пустое поле — выключить папку. Нельзя: корень диска, домашняя папка, «Документы», «Рабочий стол», «Загрузки», папка приложения; непустая папка — только с файлом-меткой.</div>
        <div class="row"><input id="wf-path" style="flex:1;min-width:280px" placeholder="Полный адрес, например D:\\Встречи\\Приёмник" value="${esc(i.folder || "")}"><input id="wf-repeat" style="flex:1;min-width:220px" placeholder="Повторите адрес"><button class="btn btn-primary" id="wf-save">Сменить папку</button></div>
        <div id="wf-confirm"></div>
        <div class="row" style="margin-top:10px"><span class="sub">Обход папки, секунд:</span><input id="wf-int" type="number" min="${esc(d.min_interval)}" max="86400" step="10" value="${esc(i.interval)}" style="width:120px"><button class="btn" id="wf-int-save">Сохранить интервал</button><span class="sub">сейчас ${esc(i.interval)} с — ${esc(i.interval_source)}</span></div>` : '<p class="sub">Выберите проект внизу левой панели — у каждого проекта своя папка-приёмник.</p>'}</div>
      ${i ? `<div class="card-output"><h2 style="margin-top:0">Автозапуск Протокола</h2><div class="sub">Сейчас: ${i.autorun ? "включён — расшифровка из папки сразу даёт протокол" : "выключен — протокол формирует администратор кнопкой"}.</div><div class="row" style="margin-top:8px"><button class="btn" id="ar-toggle">${i.autorun ? "Выключить" : "Включить"}</button></div></div>` : ""}
      <div class="card-output"><h2 style="margin-top:0">Распознавание записей</h2>${d.recognition.length ? `<table><tr><th>Запись</th><th>Встреча</th><th>Когда</th></tr>${d.recognition.map((x) => `<tr><td class="meta">${esc(x.name)}</td><td>${fmtDate(x.date)}</td><td class="meta">${esc(String(x.created_at).replace("T", " "))}</td></tr>`).join("")}</table>` : '<p class="empty">Записей ещё не распознавали.</p>'}</div>
      <div class="card-output"><h2 style="margin-top:0">Очередь</h2><dl class="kv"><dt>Задачи под вопросом</dt><dd>${esc(q.tasks_doubt_open)} · <a href="#cards">разобрать</a></dd><dt>Карточки «Конфликтов»</dt><dd>ждут ${esc(q.cards_open)} · решено за сутки ${esc(q.cards_resolved_day)} · <a href="#cards">разобрать</a></dd>
        <dt>Системные сообщения</dt><dd>${esc(q.tech_open)} · <a href="#system/messages">открыть</a></dd></dl></div>`;
    const clock = () => { const c = $("#live-clock"); if (c) c.textContent = "обновлено " + new Date().toLocaleTimeString("ru-RU"); }; clock();
    clearInterval(S.liveTimer);
    S.liveTimer = setInterval(() => { if (!location.hash.startsWith("#live")) { clearInterval(S.liveTimer); return; }
      const a = document.activeElement; if (a && /INPUT|SELECT|TEXTAREA/.test(a.tagName)) return; render(); }, 30000);
    if (!i) return;
    const post = async (url, json, ok) => { try { const r = await api(url, { method: "POST", json }); if (ok) { toast(ok); render(); } return r; } catch (e) { toast(e.message); return null; } };
    $("#wf-save").onclick = async () => {
      const json = { path: $("#wf-path").value, path_repeat: $("#wf-repeat").value };
      const r = await post(`/api/projects/${S.project}/settings/watch-folder`, json);
      if (!r || !r.confirm_needed) return;
      const pv = r.preview;
      $("#wf-confirm").innerHTML = `<div class="card stack" style="margin-top:10px"><strong>${esc(r.question)}</strong>
        ${pv && pv.examples.length ? `<div class="sub">Например: ${pv.examples.map(esc).join(", ")}</div>` : ""}${pv && pv.no_date.length ? `<div class="sub">Без одной даты в имени — не заберёт: ${pv.no_date.map(esc).join(", ")}</div>` : ""}
        <div class="sub">Смена папки-приёмника выполняется по паролю супер-администратора.</div>
        <div class="row">${S.auth ? "" : '<input id="wf-login" placeholder="Логин супер-администратора">'}<input id="wf-pass" type="password" placeholder="Ваш пароль" autocomplete="current-password">
        <button class="btn btn-primary" id="wf-ok">${json.path.trim() ? "Сделать папкой-приёмником" : "Выключить"}</button><button class="btn-link" id="wf-cancel">Отмена</button></div></div>`;
      $("#wf-cancel").onclick = () => { $("#wf-confirm").innerHTML = ""; };
      $("#wf-ok").onclick = () => post(`/api/projects/${S.project}/settings/watch-folder`, { ...json, confirm: true, login: ($("#wf-login") || {}).value || "", current_password: $("#wf-pass").value },
        json.path.trim() ? "Папка-приёмник сменена." : "Папка-приёмник выключена.");
    };
    $("#wf-int-save").onclick = () => post(`/api/projects/${S.project}/settings/watch-interval`, { seconds: Number($("#wf-int").value) }, "Интервал обхода сохранён.");
    $("#ar-toggle").onclick = () => post(`/api/projects/${S.project}/settings/autorun`, { enabled: !i.autorun }, i.autorun ? "Автозапуск выключен." : "Автозапуск включён.");
  },

  async system(tab) { // «Параметры системы» — вкладки как в Проекте ERP; «Пороги» — как в Планёрке
    const TABS = { runs: "Прогоны", cost: "Расход", decisions: "Реестр решений", data: "Состояние базы", static: "Диск и доступы",
      messages: "Системные сообщения", awaiting: "Ожидает ввода от оператора", thresholds: "Пороги", todo: "Заглушки" };
    const cur = TABS[tab] ? tab : (TABS[store.get("sys-tab", "runs")] ? store.get("sys-tab", "runs") : "runs");
    store.set("sys-tab", cur);
    const bar = `<div class="seg-tabs" role="tablist">${Object.entries(TABS).map(([k, v]) => `<a class="seg-tab" role="tab" href="#system/${k}" aria-selected="${k === cur}">${v}</a>`).join("")}</div>`;
    if (cur === "runs" || cur === "cost" || cur === "todo") return routes.monitoring(cur, true, "Параметры системы", bar);
    const kv = (rows) => `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const post = async (url, json, ok) => { try { await api(url, { method: "POST", json }); toast(ok); render(); } catch (e) { toast(e.message); } };
    let body = "";
    if (cur === "decisions") {
      const [dec, rules] = await Promise.all([api("/api/monitoring/decisions"), api("/api/monitoring/rules")]);
      body = `<div class="card-output"><h2 style="margin-top:0">Реестр решений</h2>${dec.length ? moreRows("<tr><th>Проект</th><th>Что</th><th>Решение</th><th>Почему</th><th>Когда</th></tr>", dec, (x) => `<tr><td>${esc(x.project || "общее")}</td><td>${esc(x.what)}</td><td>${esc(x.decision)}</td><td>${esc(x.why)}</td><td>${fmtDate(x.at)}</td></tr>`) : '<p class="empty">Решений пока нет.</p>'}</div>
        <div class="card-output"><h2 style="margin-top:0">Правила из решений оператора</h2><p class="sub">Правило появляется после двух одинаковых ответов, только для «это не задача». Отменённое можно вернуть.</p>${rules.length ? `<table><tr><th>Проект</th><th>Вид</th><th>Ключ</th><th>Состояние</th><th>Применено</th><th></th></tr>${rules.map((x) => `<tr><td>${esc(x.project || "")}</td><td>${esc(x.kind)}</td><td class="meta">${esc(x.key)}</td><td>${x.revoked_at ? "отменено" : x.active ? "действует" : "копит ответы"}</td><td>${esc(x.applied_count)}</td><td>${x.revoked_at ? `<button class="btn-link" data-rule="${x.id}" data-act="restore">Вернуть</button>` : `<button class="btn-link btn-link-danger" data-rule="${x.id}" data-act="revoke">Отменить</button>`}</td></tr>`).join("")}</table>` : '<p class="empty">Правил нет.</p>'}</div>`;
    } else if (cur === "data") {
      const rows = await api("/api/monitoring/data-state");
      const dict = (d) => Object.keys(d).length ? Object.entries(d).map(([k, n]) => `${esc({ active: "в работе", done: "выполнено", dropped: "снято", transcript: "расшифровки", notes: "заметки", other: "материалы", meeting: "по встрече", web_form: "вручную", operator: "оператором" }[k] || k)}: ${esc(n)}`).join(" · ") : "—";
      body = rows.length ? rows.map((r) => `<div class="card-output"><h2 style="margin-top:0">${esc(r.project)}</h2>${kv([["Встречи", `${esc(r.meetings)}, с протоколом ${esc(r.with_protocol)}`], ["Источники", dict(r.sources)], ["Задачи", dict(r.tasks)], ["Закрытия — откуда", dict(r.closed_by)], ["Люди", `${esc(r.people)}, не подтверждены ${esc(r.people_unconfirmed)}, внешние ${esc(r.people_external)}`], ["Единицы встреч", esc(r.units)]])}</div>`).join("") : '<p class="empty">Проектов нет.</p>';
    } else if (cur === "static") {
      const d = await api("/api/monitoring/static");
      const b = d.backup, a = d.access;
      body = `<div class="card-output"><h2 style="margin-top:0">Диск</h2>${kv([["База", `<span class="meta">${esc(d.disk.db)}</span> · ${esc(d.disk.db_kb)} КБ`], ["Журнал вызовов модели", d.disk.journal ? `<span class="meta">${esc(d.disk.journal)}</span> · ${esc(d.disk.journal_kb)} КБ` : "—"], ["Копии базы", `<span class="meta">${esc(d.disk.backups_dir)}</span> · ${esc(d.disk.backups_kb)} КБ`]])}</div>
        <div class="card-output"><h2 style="margin-top:0">Автобэкап</h2>${kv([["Состояние", !b.enabled ? "выключен (MEETFLOW_BACKUP=off)" : b.running ? "работает" : '<span class="overdue">поток не запущен</span>'], ["Правило", `раз в ${esc(b.hours)} ч, хранить ${esc(b.keep)} автокопий; ручные копии ротация не трогает`], ["Последние копии", b.files.length ? b.files.slice(0, 5).map((f) => `<span class="meta">${esc(f.name)}</span> ${esc(f.size_kb)} КБ`).join("<br>") : "копий нет"]])}<div class="row"><button class="btn" id="bk-now">Снять копию сейчас</button></div></div>
        <div class="card-output"><h2 style="margin-top:0">Доступ и роли</h2>${kv([["Вход по паролю", a.auth_required ? "включён — рабочий режим" : "выключен — тестовый режим, роль выбирается на экране"], ["Адрес сервера", `<span class="meta">${esc(a.host)}</span>`], ["Роли темы", a.roles.map((r) => esc(ROLE_RU[r] || r)).join(", ")]])}
          ${a.accounts.length ? `<table><tr><th>Логин</th><th>ФИО</th><th>Роль</th><th>Последний вход</th><th>Блокировка</th></tr>${a.accounts.map((x) => `<tr><td class="meta">${esc(x.login)}</td><td>${esc(x.full_name)}</td><td>${esc(ROLE_RU[x.role] || x.role)}</td><td class="meta">${esc(String(x.last_login_at || "—").replace("T", " "))}</td><td>${x.locked_until ? `<span class="overdue">до ${esc(String(x.locked_until).replace("T", " "))}</span>` : "—"}</td></tr>`).join("")}</table>` : '<p class="sub">Учётных записей нет. Без записи супер-администратора с паролем нельзя включить вход и сменить папку-приёмник.</p>'}
          <h2>Выдать доступ или сменить пароль</h2><div class="row"><input id="ac-login" placeholder="Логин"><input id="ac-name" placeholder="ФИО"><select id="ac-role">${a.roles.map((r) => `<option value="${esc(r)}">${esc(ROLE_RU[r] || r)}</option>`).join("")}</select><input id="ac-pass" type="password" placeholder="Пароль, не короче 8 знаков" autocomplete="new-password"><button class="btn btn-primary" id="ac-save">Сохранить</button></div></div>
        <div class="card-output"><h2 style="margin-top:0">Модели и пределы</h2>${kv([["Инструмент", esc(d.models.tool)], ["Генерирует", esc(d.models.generator || "по маршрутам")], ["Проверяет", esc(d.models.verifier || "по маршрутам")], ["Потолок ответа", `${esc(d.models.max_answer_tokens)} токенов`], ["Потолки прогона (тема)", Object.entries(d.models.budget || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ") || "—"]])}</div>`;
    } else if (cur === "messages") {
      const rows = await api("/api/monitoring/system-messages");
      body = `<div class="card-output">${rows.length ? `<div class="row" style="justify-content:flex-start"><button class="btn" id="msg-all">Закрыть все</button></div>${moreItems(rows, (t) => `<div class="note">${esc(t.title)} <span class="sub meta">${fmtDateTime(t.created_at)}</span>${Object.keys(t.payload || {}).length ? `<span class="sub">${Object.entries(t.payload).map(([k, v]) => `${esc(k)}: ${esc(typeof v === "object" ? JSON.stringify(v) : v)}`).join(" · ")}</span>` : ""} <button class="btn-link" data-msg="${t.id}">Закрыть</button></div>`)}` : '<p class="empty">Системных сообщений нет.</p>'}<p class="sub">Неразобранные закрываются сами через срок хранения (MEETFLOW_SYSTEM_MESSAGES_KEEP_DAYS, по умолчанию 2 дня).</p></div>`;
    } else if (cur === "awaiting") {
      const r = await api("/api/monitoring/awaiting-input");
      body = `<div class="row" style="justify-content:flex-start"><button class="btn" id="aw-refresh">Обновить список</button></div>${r.groups.map((g) => `<div class="card-output"><h2 style="margin-top:0">${esc(g.title)} · ${esc(g.count)}</h2>${kv([["Что нужно", esc(g.need)], ["Если не ответить", esc(g.if_not)]])}${g.items && g.items.length ? `<div class="sub">${g.items.map(esc).join("<br>")}</div>` : ""}${g.count ? `<a href="${esc(g.link)}">перейти</a>` : ""}</div>`).join("")}`;
    } else if (cur === "thresholds") {
      const t = await api("/api/settings/thresholds");
      body = `<div class="card stack"><h2 style="margin:0">Пороги</h2><p class="sub">Меняются без перезапуска; каждое изменение — в системных сообщениях.</p>
        <label class="sub">Подсветка просрочки — через сколько РАБОЧИХ дней после срока задача считается просроченной<input id="th-overdue" type="number" min="1" max="60" value="${esc(t.overdue_highlight_working_days)}" style="width:120px"></label>
        <label class="sub">Удаление нерешённой карточки «Конфликтов» — через сколько дней (0 — не снимать; сейчас ${esc(t.card_cleanup_source)})<input id="th-drop" type="number" min="0" max="365" value="${esc(t.card_cleanup_days)}" style="width:120px"></label>
        <label class="sub"><input id="th-doubt" type="checkbox" ${t.show_doubt_mark ? "checked" : ""}> Отметка «под вопросом» в реестре — точка у задачи, только администраторам (на время пилота; карточки и счётчик остаются)</label>
        <div class="row"><button class="btn btn-primary" id="th-save">Сохранить</button></div></div>`;
    }
    $("#main").innerHTML = `<h1>Параметры системы</h1>${bar}${body}`;
    $("#main").querySelectorAll("[data-rule]").forEach((b) => b.onclick = () => post(`/api/monitoring/rules/${b.dataset.rule}/${b.dataset.act}`, {}, b.dataset.act === "revoke" ? "Правило отменено." : "Правило возвращено."));
    const bk = $("#bk-now"); if (bk) bk.onclick = () => post("/api/monitoring/backup-now", {}, "Копия базы снята.");
    const ac = $("#ac-save"); if (ac) ac.onclick = () => post("/api/monitoring/accounts", { login: $("#ac-login").value, full_name: $("#ac-name").value, role: $("#ac-role").value, password: $("#ac-pass").value }, "Доступ сохранён.");
    $("#main").querySelectorAll("[data-msg]").forEach((b) => b.onclick = () => post(`/api/monitoring/system-messages/${b.dataset.msg}/close`, {}, "Сообщение закрыто."));
    const all = $("#msg-all"); if (all) all.onclick = () => post("/api/monitoring/system-messages/close-all", {}, "Все сообщения закрыты.");
    const aw = $("#aw-refresh"); if (aw) aw.onclick = () => render();
    const th = $("#th-save"); if (th) th.onclick = () => post("/api/settings/thresholds", { overdue_highlight_working_days: Number($("#th-overdue").value), card_cleanup_days: Number($("#th-drop").value), show_doubt_mark: $("#th-doubt").checked }, "Пороги сохранены.");
  },

  async settings() { location.replace("#live"); },   // прежний экран «Настройки»: папка, обход и автозапуск — на «Мониторинге RealTime»

  async design() {
    const cur = document.documentElement.dataset.palette;
    $("#main").innerHTML = `<h1>Оформление</h1><div class="card stack"><h2 style="margin:0">Палитра</h2>${[["Проекты-примеры и пресеты", PALETTES], ["Для новых проектов", PALETTES_NEW]].map(([cap, set]) => `<div class="sub">${cap}</div><div class="swatches">${Object.entries(set).map(([k, v]) => `<button class="swatch" style="background:${v}" title="${k}" aria-label="Палитра ${k}" aria-pressed="${k === cur}" data-p="${k}"></button>`).join("")}</div>`).join("")}
      <h2 style="margin:0">Тема</h2><div class="row">${["auto", "light", "dark"].map((t) => `<button class="btn" data-t="${t}">${{ auto: "Как в системе", light: "Светлая", dark: "Тёмная" }[t]}</button>`).join("")}</div>
      <h2 style="margin:0">Метки исполнителей</h2><div class="row">${Object.values(ACTOR).map(([c, t]) => `<span class="actor ${c}">${t}</span>`).join("")}<span class="actor actor-local">локальное распознавание</span><span class="actor actor-admin">супер-админ</span></div></div>`;
    $("#main").querySelectorAll("[data-p]").forEach((b) => b.onclick = () => { document.documentElement.dataset.palette = b.dataset.p; store.set("palette", b.dataset.p); render(); });
    $("#main").querySelectorAll("[data-t]").forEach((b) => b.onclick = () => { if (b.dataset.t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = b.dataset.t; store.set("theme", b.dataset.t); });
  },
};

// Отложенное действие с отменой (находка стенда 11, Планёрка cd4b265, 71c9f10): уход с экрана и закрытие вкладки
// ПРИМЕНЯЮТ, а не теряют изменение; отменяет только «Отменить». Ожидающие смены — в одном списке.
const pendingChange = new Map();          // id задачи → { status, timer }
function sendChange(id, keepalive = false) {
  const p = pendingChange.get(id);
  if (!p) return Promise.resolve();
  clearInterval(p.timer); pendingChange.delete(id);
  if (keepalive) {                        // закрытие вкладки: запрос доживёт и после выгрузки страницы
    try { fetch(`/api/tasks/${id}`, { method: "PATCH", keepalive: true, body: JSON.stringify({ status: p.status }),
      headers: { "Content-Type": "application/json", "X-User-Role": S.role, "X-User-Name": encodeURIComponent(S.name), "X-Requested-With": "MeetFlow" } }); } catch { /* вкладка уже закрыта */ }
    return Promise.resolve();
  }
  return api(`/api/tasks/${id}`, { method: "PATCH", json: { status: p.status } }).catch((e) => toast(e.message));
}
const flushChanges = (keepalive = false) => Promise.all([...pendingChange.keys()].map((id) => sendChange(id, keepalive)));
function undoable(btn, id, status) { // «Выполнено через 2 с — Отменить»
  flushChanges();                         // повторный вызов сначала отправляет прежнюю смену
  let left = 2; btn.textContent = `Отменить (${left})`;
  const timer = setInterval(async () => { left -= 1;
    if (left > 0) { btn.textContent = `Отменить (${left})`; return; }
    await sendChange(id);
    render(); }, 1000);
  pendingChange.set(id, { status, timer });
  btn.onclick = () => { const p = pendingChange.get(id); if (p) { clearInterval(p.timer); pendingChange.delete(id); } render(); };
}
window.addEventListener("pagehide", () => flushChanges(true));

async function render() {
  // защита от гонки: медленный ответ прошлого экрана не перерисовывает новый
  const seq = ++renderSeq;
  if (pendingChange.size) await flushChanges();   // уход с экрана — отложенная смена отправляется сразу (стенд 11)
  const main = $("#main");
  const realSet = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML").set;
  Object.defineProperty(main, "innerHTML", { configurable: true, set(v) { if (seq === renderSeq) realSet.call(main, v); },
    get() { return Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML").get.call(main); } });
  const [route, arg] = (location.hash.slice(1) || "tasks").split("/");
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.route === (route === "meeting" ? "meetings" : route)) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-admin]").forEach((el) => (el.hidden = !isAdmin()));
  document.querySelectorAll("[data-super]").forEach((el) => (el.hidden = S.role !== "super_admin"));
  // мониторинг — общесистемный экран: модели и службы нужны и до первого проекта (09.10.26)
  if (!S.project && !["design", "monitoring", "models", "live", "system", "voices", "teamshared"].includes(route)) { $("#main").innerHTML = `<h1>Нет проекта</h1><p class="page-sub">Создайте проект: python -m meetflow new-project "Имя" --theme it_product --db &lt;та же база, что у сервера&gt;.</p>`; return; }
  try { await (routes[route] || routes.tasks)(arg); } catch (e) {
    if (e instanceof Stale || seq !== renderSeq) return;
    $("#main").innerHTML = `<h1>Не получилось открыть раздел</h1><p class="page-sub">${esc(e.message)}</p>`; }
  if (seq !== renderSeq) return;      // экран уже другой — плашку и обработчики не трогаем
  // стенд без модели виден на каждом экране (письмо meeting-registry 01/19)
  if (S.theme && S.theme.stand) $("#main").insertAdjacentHTML("afterbegin",
    `<p class="stand-banner" role="status">Стенд без модели: протоколы собирает заглушка, а не модель. Для работы нужен MEETFLOW_LLM=routes, ollama или openrouter.</p>`);
}

function showLogin() {
  const scr = $("#login-screen"); scr.hidden = false;
  $("#login-form").onsubmit = async (e) => { e.preventDefault();
    try { await api("/api/auth/login", { method: "POST", json: { login: $("#login-name").value, password: $("#login-password").value } });
      scr.hidden = true; $("#login-password").value = ""; boot(); }
    catch (err) { const el = $("#login-error"); el.hidden = false; el.textContent = err.message; } };
}

async function updateAwaitingBadge() {
  const b = $("#awaiting-badge"); if (!b) return;
  if (S.role !== "super_admin") { b.textContent = ""; return; }
  try { const r = await api("/api/monitoring/awaiting-input"); b.textContent = r.total ? ` · ${r.total}` : ""; } catch { b.textContent = ""; }
}

function bindModeSwitch() { // как в ERP: «Включить рабочий режим (вход по логину)» / «Переключить на тестовый режим»
  const btn = $("#mode-switch"); if (!btn) return;
  btn.hidden = S.role !== "super_admin";
  btn.textContent = S.auth ? "Переключить на тестовый режим" : "Включить рабочий режим (вход по логину)";
  btn.onclick = async () => {
    const turnOn = !S.auth;
    if (!window.confirm(turnOn ? "Включить вход по логину и паролю? Потребуется логин и пароль супер-администратора." : "Выключить вход по паролю? Роль снова будет выбираться на экране.")) return;
    const login = turnOn ? window.prompt("Логин супер-администратора") || "" : "";
    const pass = await askPassword(); if (pass === null) return;
    try { await api("/api/auth/mode", { method: "POST", json: { auth_required: turnOn, login, password: pass } }); toast(turnOn ? "Вход по паролю включён." : "Тестовый режим."); boot(); }
    catch (e) { toast(e.message); } };
}

function askPassword() { // пароль — в поле со скрытием, а не в window.prompt
  return new Promise((resolve) => {
    const box = document.createElement("div"); box.className = "login-screen";
    box.innerHTML = `<form class="card stack login-card"><strong>Пароль супер-администратора</strong><input type="password" autocomplete="current-password"><div class="row"><button class="btn btn-primary" type="submit">Подтвердить</button><button class="btn-link" type="button">Отмена</button></div></form>`;
    document.body.appendChild(box); const inp = box.querySelector("input"); inp.focus();
    box.querySelector("form").onsubmit = (e) => { e.preventDefault(); const v = inp.value; box.remove(); resolve(v); };
    box.querySelector("button[type=button]").onclick = () => { box.remove(); resolve(null); };
  });
}

async function boot() {
  const mode = await api("/api/auth/mode");
  S.auth = !!mode.auth_required;
  if (S.auth) {
    try { const me = await api("/api/auth/me"); S.role = me.role; S.name = me.name; }
    catch { showLogin(); return; }
  }
  S.theme = await api("/api/theme");
  const projects = await api("/api/projects");
  // в шапке — имя текущего проекта из базы и его тематика; название
  // проекта-примера в тему не зашивается (правка 03.10.26)
  const showBrand = () => {
    const p = projects.find((x) => x.id === S.project);
    const name = p ? p.name : S.theme.vocabulary.app_title;
    $("#app-title").textContent = name; $("#app-subtitle").textContent = ""; // только имя проекта
    document.title = name;
  };
  document.documentElement.dataset.palette = store.get("palette", S.theme.design.palette);
  const th = store.get("theme", S.theme.design.dark === "auto" ? "auto" : S.theme.design.dark);
  if (th !== "auto") document.documentElement.dataset.theme = th;
  // подписи левой панели — отдельные слова темы nav_*, как в Проекте ERP и Планёрке (владелец 11.10.26); заголовки
  // страниц и протокола по-прежнему берут registry / meetings / roadmap / search
  const V = S.theme.vocabulary;
  $('[data-route="tasks"]').textContent = V.nav_tasks || V.registry; $('[data-route="meetings"]').textContent = V.nav_meetings || V.meetings;
  $('[data-route="search"]').textContent = V.nav_search || V.search || "Поиск по проекту";
  $('[data-route="roadmap"]').textContent = V.nav_roadmap || V.roadmap || "Дорожная карта";
  $('[data-route="cards"]').textContent = "Разбор"; $('[data-route="team"]').textContent = S.theme.vocabulary.team;
  if (!S.auth) { S.role = store.get("role", "member"); S.name = store.get("name", ""); }
  $("#test-identity").hidden = S.auth; $("#auth-identity").hidden = !S.auth;
  if (S.auth) { $("#auth-identity").innerHTML = `Вы вошли: ${esc(S.name)} · ${esc(ROLE_RU[S.role] || S.role)} · <button class="btn-link" id="logout">Выйти</button>`;
    $("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.reload(); }; }
  const roleSel = $("#role"); roleSel.innerHTML = S.theme.roles.map((r) => `<option value="${esc(r)}">${esc(ROLE_RU[r] || r)}</option>`).join("");
  roleSel.value = S.role; roleSel.onchange = () => { S.role = roleSel.value; store.set("role", S.role); bindModeSwitch(); updateAwaitingBadge(); render(); };
  const nm = $("#username"); nm.value = S.name; nm.onchange = () => { S.name = nm.value.trim(); store.set("name", S.name); render(); };
  const visibleProjects = projects.filter((p) => !p.archived);
  const ps = $("#project"); ps.innerHTML = visibleProjects.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  S.project = Number(store.get("project", visibleProjects[0]?.id || 0)) || visibleProjects[0]?.id || null;
  if (!visibleProjects.some((p) => p.id === S.project)) S.project = visibleProjects[0]?.id || null;
  if (S.project) ps.value = S.project;
  showBrand();
  ps.onchange = () => { S.project = Number(ps.value); store.set("project", ps.value); showBrand(); render(); };
  bindModeSwitch(); updateAwaitingBadge();
  window.addEventListener("unhandledrejection", (e) => { if (e.reason instanceof Stale) e.preventDefault(); });   // устаревшее чтение — не ошибка
  window.onhashchange = render; render();
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".toast").forEach((t) => t.remove()); });
boot().catch((e) => { $("#main").innerHTML = `<h1>Сервер недоступен</h1><p class="page-sub">${esc(e.message)}</p>`; });
