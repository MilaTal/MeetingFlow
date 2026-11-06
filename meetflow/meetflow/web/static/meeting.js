// Страница встречи для читателя — вариант Б прототипа 1 (выбор владельца 13.10.26, стенд 8020; задание, раздел 3 и
// дополнение «Шапка страницы встречи»). Адрес — #meetings/<id>.
// Одна строка инструментов над документом: «← Протоколы» (или «← Реестр»), метка состояния, путь точками. Кнопки со значками
// «Задачи встречи N», «План следующей», «⋯» — сразу за заголовком встречи, к которой относятся
// (принцип владельца 13.10.26 «действие — рядом со своим объектом»: у правого края строки было непонятно, чьи они; образец —
// Планёрка d74d93a). «Замечаний» на странице встречи нет (решение владелицы 17.10.2026, п. 4): технические замечания —
// справкой администратору в «Подготовке встречи», там же «Поправить». Вкладка «Договорённости встречи» — всем ролям
// (решение владелицы 20.10.2026, п. 3; с 19.10.2026 было — только администраторам), в режиме «в тени» — администраторам. Заголовок один — сам документ. Документ — на всю
// ширину, страница прокручивается целиком. Кнопки открывают панель справа (до 400 px), она не закрывает документ,
// сворачивается «Свернуть ▾» и Esc. Сборка, приёмка черновика, источники — в «Подготовке встречи» (#meetings/<id>/protocol,
// прежний экран), здесь их нет: ни плашек, ни липкой полосы, ни счётчика секунд.

const ВСТРЕЧА_ЗНАКИ = {
  tasks: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 8h8M12 16h8"/></svg>',
  plan: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
  agreements: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 12l4 4 10-10"/></svg>',
  notes: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/></svg>',
  // «Скачать .docx» и «Правка» — кнопками в ряду (п. 1 замечаний владелицы 21.10.2026); те же значки у Планёрки (.i-down, .i-edit)
  docx: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19h14"/></svg>',
  edit: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>',
};

// Пункт списка задач (не таблицы): номер «1.» того же размера, что формулировка, серым #71717a; висячий отступ — формулировка и
// строка «исполнитель · срок · открыть в реестре» выровнены по началу формулировки; нумерация сквозная и при свёрнутом списке
// («Показать все» продолжает счёт — номер вписан в пункт). Поручение владельца 13.10.26 для обеих систем (через «Мониторинг»).
function пунктЗадачи(t, i, ссылка) {
  return `<div class="tl-item"><span class="tl-n">${i + 1}.</span><div class="tl-body"><div class="tl-text">${esc(t.description)}</div>
    <div class="tl-sub">${taskResponsibleHtml(t)} · ${esc(taskDueText(t) || "без срока")} · <a href="#dashboard?task=${t.id}">${ссылка}</a></div></div></div>`;
}

// Панель «Договорённости встречи» (19.10.2026, Е11 списка отставания; образец — «Договорённости планёрки» Планёрки 78c5250):
// записи реестра этой встречи по видам. Точка «под вопросом» с причиной — как в реестре задач; в документ такие записи не
// идут. Пусто — «Договорённостей нет.» только здесь; в документе протокола пустоты не пишется.
function панельДоговорённостейВстречи(записи, дата) {
  const виды = ["решение", "правило работы", "открытый вопрос", "обсуждено без решения"];
  const ЗАГОЛОВКИ = { "решение": "Решения", "правило работы": "Правила работы", "открытый вопрос": "Открытые вопросы",
    "обсуждено без решения": "Обсуждено без решения" };
  const группы = виды.map(вид => {
    const свои = записи.filter(a => a.kind === вид);
    if (!свои.length) return "";
    return `<div class="reg-sub" style="margin:12px 0 0">${esc(ЗАГОЛОВКИ[вид])}</div>
      ${свои.map(a => `<div class="tl-item"><div class="tl-body"><div class="tl-text">${esc(a.text)}${a.under_question && isAdmin()
        ? ` <a class="task-doubt-dot uq-dot" href="#razbor" title="${esc("под вопросом: " + a.under_question + " — решить в «Разборе»")}" aria-label="${esc("под вопросом: " + a.under_question)}"></a>` : ""}</div>
        <div class="tl-sub">${a.project ? esc(a.project) + " · " : ""}${esc(a.status)}</div></div></div>`).join("")}`;
  }).join("");
  return `<h2>Договорённости встречи ${esc(дата)}</h2>${группы || '<div class="reg-sub">Договорённостей нет.</div>'}
    <a href="#agreements">Реестр договорённостей</a>`;
}

// ---- Одна страница встречи (пакет Б, 05.11.2026) ---------------------------------------------------------------
// #meetings/N — вкладка «Протокол», если он есть, иначе «План»; #meetings/N/protocol и #meetings/N/planprep —
// адреса тех же вкладок. Основа — прежняя страница читателя; сборка, материалы, замечания и действия встречи
// переехали в одну строку инструментов и одну правую панель. Цвета и вид — прежние классы (.mt-*, .src-*, .doc-*).
let _открытаяПанельВстречи = "";
let _страницаВстречиId = "";

function вёлВстречиТекст(m) {
  const текст = m.leader_user_id
    ? (allUsers.find(u => u.id === m.leader_user_id)?.full_name || "")
    : (m.leader_speaker || "");
  return /^говорящий\s*\d*$/i.test(текст.trim()) ? "" : текст;
}

function панельМатериаловHtml({ id, tab, источники, материалы, встреча, admin }) {
  const вид = src => src.kind === "recording" ? "запись" : src.kind === "transcript" ? "расшифровка"
    : src.kind === "protocol" ? "заметки" : src.kind === "notes" ? "заметки секретаря" : fileTag(src.original_filename);
  const источникиHtml = (источники || []).map(src => sourceRow(вид(src), esc(src.original_filename),
    src.status ? esc(src.status) : "",
    `<span class="src-icons">${src.local_transcript ? `<a class="btn-icon src-download" href="/meetings/${id}/sources/${src.id}/export" download title="Выгрузить расшифровку в Word" aria-label="Выгрузить расшифровку в Word">${ICON_DOWNLOAD}</a>` : ""}${admin ? `<button class="btn-icon src-delete delete-source-btn" data-id="${src.id}" title="Удалить файл" aria-label="Удалить файл">${ICON_TRASH}</button>` : ""}</span>`)).join("")
    || `<div class="src-empty">Пока нет.</div>`;
  const материалыHtml = (материалы || []).map(m => sourceRow("материал", esc(m.original_filename),
    [m.description ? esc(m.description) : "", m.added_at ? `добавлен ${esc(fmtRuDateTime(m.added_at))}` : ""].filter(Boolean).join(" · "),
    // удаляет автор или администратор (как в прежней панели плана)
    (admin || (me && m.uploaded_by_user_id === me.id))
      ? `<button class="btn-icon src-delete delete-material-btn" data-id="${m.id}" title="Удалить материал" aria-label="Удалить материал">${ICON_TRASH}</button>` : "")).join("")
    || `<div class="src-empty">Пока нет.</div>`;
  const вёл = вёлВстречиТекст(встреча);
  const цель = tab === "plan" ? "к плану" : "к протоколу";
  return `<h2>Материалы встречи ${esc(fmtRuDate(встреча.date))}</h2>
    <div class="hstack" style="margin:0 0 8px">
      <label class="btn btn-sm">+ Добавить материал <span class="page-sub">${цель}</span><input type="file" id="meeting-material-file" multiple hidden></label>
      ${tab === "protocol" ? `<button type="button" class="link" id="meeting-paste-open">Вставить текст</button>` : ""}
    </div>
    <div class="page-sub">Файл можно перетащить на страницу.</div>
    <div id="meeting-material-progress" class="src-hint"></div>
    ${tab === "plan" ? `<input type="text" id="meeting-material-desc" class="src-desc" placeholder="Описание для следующего файла — если нужно">` : ""}
    <div id="meeting-paste-box" class="src-paste" hidden>
      <textarea id="meeting-paste-text" rows="6" placeholder="Вставьте заметки или расшифровку встречи"></textarea>
      <div class="hstack"><button type="button" class="btn-sm" id="meeting-paste-add">Добавить текст</button></div>
    </div>
    <div class="reg-sub" style="margin-top:12px">К протоколу · ${(источники || []).length}</div>
    ${источникиHtml}
    <div class="reg-sub" style="margin-top:12px">К плану · ${(материалы || []).length}</div>
    ${материалыHtml}
    ${(встреча.project_label || вёл) ? `<div class="reg-sub" style="margin-top:12px">${встреча.project_label ? `Проект: ${esc(встреча.project_label)}` : ""}${встреча.project_label && вёл ? " · " : ""}${вёл ? `Вёл встречу: ${esc(вёл)}` : ""}</div>` : ""}`;
}

function подключитьМатериалы(id, tab) {
  const file = document.getElementById("meeting-material-file");
  file?.addEventListener("change", async (e) => {
    if (!e.target.files.length) return;
    const progress = document.getElementById("meeting-material-progress");
    if (progress) progress.textContent = "Загружаю: " + Array.from(e.target.files).map(f => f.name).join(", ") + "…";
    const url = tab === "plan" ? `/meetings/${id}/materials` : `/meetings/${id}/sources`;
    const extra = tab === "plan" ? { description: document.getElementById("meeting-material-desc")?.value || "" } : {};
    await uploadFile(url, "meeting-material-file", extra,
      tab === "plan" ? "Материал добавлен" : "Файлы добавлены",
      () => renderMeetingReader(id, tab), true,
      tab === "plan" ? { progressId: "meeting-material-progress" }
        : { mediaAsRecording: true, progressId: "meeting-material-progress" });
  });
  document.getElementById("meeting-paste-open")?.addEventListener("click", () => {
    const box = document.getElementById("meeting-paste-box");
    box.hidden = !box.hidden;
    if (!box.hidden) document.getElementById("meeting-paste-text").focus();
  });
  if (tab === "protocol") wirePasteText("meeting-paste", `/meetings/${id}/sources/text`, () => renderMeetingReader(id, tab));
  document.querySelectorAll(".delete-source-btn").forEach(btn => btn.addEventListener("click", async () => {
    if (!(await confirmDialog("Удалить этот файл с заметками? Восстановить его нельзя.", "Удалить"))) return;
    try {
      await api(`/meetings/${id}/sources/${btn.dataset.id}`, { method: "DELETE" });
      toast("Файл удалён");
      renderMeetingReader(id, tab);
    } catch (e) { toast(e.message, true); }
  }));
  document.querySelectorAll(".delete-material-btn").forEach(btn => btn.addEventListener("click", async () => {
    if (!(await confirmDialog("Удалить этот материал? Восстановить его нельзя.", "Удалить"))) return;
    try {
      await api(`/meetings/${id}/materials/${btn.dataset.id}`, { method: "DELETE" });
      toast("Материал удалён");
      renderMeetingReader(id, tab);
    } catch (e) { toast(e.message, true); }
  }));
}

function панельЗамечанийHtml(протокол) {
  const дата = esc(fmtRuDate(протокол.date || ""));
  const notes = протокол.minor_findings || [];
  if (!notes.length) return `<h2>Замечания встречи ${дата}</h2><div class="reg-sub">Замечаний нет.</div>`;
  // Тот же список и те же действия, что у панели замечаний документа (reviewNotesLayout): берём её разметку, не
  // переписывая правила показа. Заголовок «Свернуть» здесь не нужен — сворачивает вся панель.
  const holder = document.createElement("div");
  holder.innerHTML = reviewNotesLayout({ content_md: протокол.content_md || "", minor_findings: notes }, "");
  const body = holder.querySelector(".review-notes .rn-body");
  return `<h2>Замечания встречи ${дата}</h2>${body ? body.innerHTML : ""}`;
}

async function renderMeetingReader(id, запрошеннаяВкладка) {
  const откуда = new URLSearchParams(location.hash.split("?")[1] || "").get("from");
  if (_страницаВстречиId !== String(id)) { _открытаяПанельВстречи = ""; _страницаВстречиId = String(id); }
  const [встреча, протокол, план, источники, материалы, встречи, задачи] = await Promise.all([
    api(`/meetings/${id}`), api(`/meetings/${id}/minutes`), api(`/meetings/${id}/plan`),
    api(`/meetings/${id}/sources`).catch(() => []), api(`/meetings/${id}/materials`).catch(() => []),
    api("/meetings"), api(`/tasks?meeting_id=${id}`),
  ]);
  // Д2.1 (решение владелицы 05.11.2026): открытие встречи ставит проект вкладки. При «Все проекты» выбор
  // остаётся, а проект встречи называется в шапке. Перерисовки нет — данные уже загружены по встрече.
  const проектВстречи = Number(встреча.project_id || 0);
  if (проектВстречи && выбранныйПроект() !== 0 && Number(выбранныйПроект()) !== проектВстречи) {
    localStorage.setItem("currentProjectId", String(проектВстречи));
    sessionStorage.setItem("currentProjectId", String(проектВстречи));
    записатьПроектВАдрес(проектВстречи);
  }
  const генерация = canPrepare() ? await api(`/meetings/${id}/generation`).catch(() => ({})) : {};
  const ответДоговорённостей = протокол.available
    ? await api(`/agreements?meeting_id=${id}`).catch(() => ({ items: [], mode: "shadow" })) : null;
  const договорённости = ответДоговорённостей && (isAdmin() || ответДоговорённостей.mode === "on")
    ? (ответДоговорённостей.items || []) : null;
  const hasMin = !!протокол.available;
  const hasPlan = !!план.available;
  const сегодня = сегодняISO();
  const дата = String(встреча.date).slice(0, 10);
  const будущая = дата > сегодня;
  const прошла = дата < сегодня;
  const отменена = встреча.status === "cancelled";
  const админ = isAdmin();
  const готовит = canPrepare();
  // Вкладки: протокол — только если он есть; план — если он есть или встреча ещё не прошла (её можно собрать).
  // У прошедшей встречи вкладки без документа нет (Б1).
  // Сегодня и впереди вкладка «Протокол» доступна и без документа: после сегодняшней встречи источник и сборку
  // добавляют отсюда. У прошедшей встречи вкладки без документа нет (Б1).
  // Д8.1 (решение владелицы 05.11.2026): у прошедшей встречи без протокола вкладка «Протокол» открыта и принимает файл.
  const показПротокола = true;
  const показПлана = hasPlan || !прошла;      // у будущей и сегодняшней план можно собрать, даже если плана ещё нет
  let tab = запрошеннаяВкладка === "protocol" || запрошеннаяВкладка === "plan" ? запрошеннаяВкладка : (hasMin || прошла ? "protocol" : "plan");
  if (tab === "protocol" && !показПротокола && показПлана) tab = "plan";
  if (tab === "plan" && !показПлана && показПротокола) tab = "protocol";
  const документ = tab === "protocol" ? (hasMin ? протокол : null) : (hasPlan ? план : null);
  const заголовок = tab === "protocol" && hasMin ? `Протокол встречи ${fmtRuDate(встреча.date)}`
    : tab === "plan" && hasPlan ? `План встречи ${fmtRuDate(встреча.date)}`
    : `Встреча ${fmtRuDate(встреча.date)}`;
  const мои = задачи.filter(t => t.source_meeting_id === Number(id));
  const следующая = встречи.filter(m => m.status !== "cancelled" && String(m.date).slice(0, 10) > дата)
    .sort((a, b) => a.date.localeCompare(b.date))[0] || null;
  const состояние = отменена ? "встреча отменена" : встреча.building ? "идёт сборка"
    : встреча.draft_pending ? "черновик ждёт решения" : hasMin ? "протокол готов"
    : (встреча.состояние_протокола || "протокола нет");
  let назад = откуда === "reg" ? `<a href="#dashboard" class="mt-back">← Реестр задач</a>`
    : откуда === "prep" ? `<a href="#prep" class="mt-back">← Подготовка встречи</a>`
    : `<a href="#meetings" class="mt-back">← Реестр встреч</a>`;
  // Старый ?from=<номер встречи> (ссылки «план следующей», материалы к плану) — возврат на ту встречу, как прежде.
  if (/^\d+$/.test(откуда || "")) {
    let источник = null;
    try { источник = await api(`/meetings/${откуда}`); } catch (e) { /* встреча могла уйти — остаётся реестр */ }
    if (источник) назад = `<a href="#meetings/${откуда}" class="mt-back">← План ${esc(fmtRuDate(источник.date))}</a>`;
  }
  // Число у кнопки: у «Материалов» ноль не пишем (А6), у задач и договорённостей ноль значим — «как сейчас».
  const кнопка = (k, знак, текст, n, ноль = false) => `<button type="button" class="mt-btn" data-drawer="${k}" aria-expanded="false">${знак}${esc(текст)}${n !== undefined && (n || ноль) ? ` <span class="n">${n}</span>` : ""}</button>`;
  const замечания = hasMin ? (протокол.minor_findings || []).filter(n => !n.dismissed).length : 0;
  const всего = (источники || []).length + (материалы || []).length;
  const подписьПротокола = hasMin ? "Пересобрать протокол" : "Сформировать протокол";
  const подписьПлана = hasPlan ? "Переформировать план встречи" : "Сформировать план встречи";
  const подписьГлавной = tab === "protocol" ? подписьПротокола : подписьПлана;
  const главная = tab === "protocol"
    ? (!будущая && !отменена && готовит && (tab !== "protocol" || !hasMin || isAdmin()) ? `<button type="button" class="btn-primary" id="reader-main-btn"${генерация.running || генерация.queued ? " disabled" : ""}>${подписьГлавной}</button>` : "")
    : (готовит && !отменена ? `<button type="button" class="btn-primary" id="reader-main-btn"${генерация.running || генерация.queued ? " disabled" : ""}>${подписьГлавной}</button>` : "");
  const экспорт = документ ? (tab === "protocol" ? `/meetings/${id}/minutes/export` : `/meetings/${id}/plan/export`) : "";
  const основаПолотна = документ ? (tab === "protocol" ? `/meetings/${id}/minutes` : `/meetings/${id}/plan`) : "";
  const рубежАрхива = new Date(); рубежАрхива.setDate(рубежАрхива.getDate() - ARCHIVE_CUTOFF_DAYS);
  const правкаДоступна = админ && !!основаПолотна && дата >= датаISO(рубежАрхива);
  const режимПолотна = правкаДоступна ? полотноРежим(основаПолотна) : "view";
  const новее = tab === "plan" && hasPlan ? Number(план.newer_materials || 0) : 0;
  const плашкаНовее = !новее ? ""
    : готовит && !отменена && !генерация.running
      ? `<button type="button" class="link" id="reader-plan-newer">Есть материалы новее плана (${новее}) — переформировать?</button>`
      : `<span class="page-sub">Есть материалы новее плана (${новее})</span>`;
  const подпись = админ && документ
    ? (tab === "protocol"
      ? `собран ${esc(fmtRuDateTime(протокол.generated_at))}${протокол.build_note ? ` · ${esc(протокол.build_note)}` : ""}`
      : `план собран ${esc(fmtRuDateTime(план.generated_at))}`)
    : "";
  // «Протокол соберётся сам» — только если сервер подтвердил автозапуск (находка 4). Старый сервер поля не отдаёт —
  // тогда нейтрально: «сам или по кнопке», а не ложное «автозапуск выключен».
  const автозапуск = typeof встреча.autorun === "boolean" ? встреча.autorun : null;
  const какСоберётся = автозапуск === true ? "протокол соберётся сам."
    : автозапуск === false ? "затем нажмите «Сформировать протокол»: автозапуск выключен."
    : "протокол соберётся сам или по кнопке «Сформировать протокол».";
  const пустойТекст = tab === "protocol"
    ? (отменена ? "Встреча отменена — протокола нет."
      : будущая ? "Встреча ещё не прошла. После неё — протокол."
      : !готовит ? "Протокола этой встречи пока нет."
      : !(источники || []).length ? `Протокола пока нет. Добавьте материал в «Материалах» — ${какСоберётся}`
      : автозапуск === true ? "Протокола пока нет. Материалы уже приложены — протокол соберётся сам."
      : автозапуск === false ? "Протокола пока нет. Материалы приложены — нажмите «Сформировать протокол»: автозапуск выключен."
      : "Протокола пока нет. Материалы приложены — протокол соберётся сам или по кнопке «Сформировать протокол».")
    : (отменена ? "Встреча отменена — плана и материалов у неё нет."
      : готовит ? "Плана пока нет. Нажмите «Сформировать план встречи» вверху."
      : "Плана пока нет.");
  const баннерЧерновика = встреча.draft_pending && админ
    ? `<div class="card" id="reader-draft-banner"><div><b>Черновик ждёт решения.</b></div>
        <div class="page-sub" style="margin:6px 0">Сохранить его можно здесь — это одна точка решения; в пути встречи тот же шаг.</div>
        <button type="button" class="btn-sm btn-primary" id="reader-accept-draft">Сохранить протокол с замечаниями</button></div>` : "";

  $main.innerHTML = `
    <div class="mt-bar">
      ${назад}
      ${админ ? `<span class="mt-state${встреча.draft_pending ? " mt-state-acc" : ""}">${esc(состояние)}</span>` : ""}
    </div>
    <div class="mt-title-row"><h1 class="mt-title">${esc(заголовок)}</h1></div>
    ${подпись ? `<div class="mt-sub">${esc(подпись)}</div>` : ""}
    <div class="doc-head prep-bar" id="meeting-tools">
      ${показПротокола ? `<a class="doc-tab${tab === "protocol" ? " doc-tab-on" : ""}" href="#meetings/${id}/protocol${откуда ? `?from=${esc(откуда)}` : ""}">Протокол</a>` : ""}
      ${показПлана ? `<a class="doc-tab${tab === "plan" ? " doc-tab-on" : ""}" href="#meetings/${id}/planprep${откуда ? `?from=${esc(откуда)}` : ""}">План</a>` : ""}
      ${главная}
      ${кнопка("materials", ВСТРЕЧА_ЗНАКИ.notes, "Материалы", всего)}
      ${кнопка("tasks", ВСТРЕЧА_ЗНАКИ.tasks, "Задачи", мои.length, true)}
      ${договорённости ? кнопка("agreements", ВСТРЕЧА_ЗНАКИ.agreements, "Договорённости", договорённости.length, true) : ""}
      ${/* «План следующей» и «Замечания» — в «⋯»: строка не должна быть шире окна (05.11.2026) */ ""}
      ${документ ? `<a class="mt-btn" href="${экспорт}" target="_blank">${ВСТРЕЧА_ЗНАКИ.docx}Скачать .docx</a>` : ""}
      ${правкаДоступна ? полотноПереключатель(основаПолотна, режимПолотна, "reader-edit") : ""}
      ${плашкаНовее}
      ${админ ? `<span class="reg-menu-wrap"><button type="button" class="mt-btn" id="meeting-more" aria-label="Ещё" aria-haspopup="menu">⋯</button></span>` : ""}
    </div>
    <div class="mt-layout">
      <article class="mt-doc">
        ${баннерЧерновика}
        <div class="stack">
          <div id="verify-findings-minutes"></div>
          <div id="verify-findings-plan"></div>
          ${документ ? `<div class="mt-text doc-render doc-content" id="mt-doc-text">${renderDocHtml(документ.content_md)}</div>`
            : `<div class="card empty-state">${esc(пустойТекст)}</div>`}
        </div>
        ${админ && hasMin ? `<div id="post-save-check" hidden></div>` : ""}
      </article>
      <aside class="mt-drawer" id="mt-drawer" hidden aria-label="Панель встречи"></aside>
    </div>`;

  const спрятатьПервуюСтроку = (док) => {
    const перваяСтрока = док?.firstElementChild?.classList.contains("doc-protocol") ? док.firstElementChild.firstElementChild : док?.firstElementChild;
    if (перваяСтрока && /^(Протокол|План).{0,40}\d{2}\.\d{2}\.\d{2,4}\s*$/.test(перваяСтрока.textContent.trim())) перваяСтрока.hidden = true;
  };
  спрятатьПервуюСтроку($main.querySelector(".mt-text"));
  // «Поправить» у замечания (панель справа) правит документ этой страницы (решение владелицы 24.10.2026).
  if (документ) _полотнаЭкрана.set("mt-doc-text", { base: основаПолотна, перерисовать: () => renderMeetingReader(id, tab) });
  const $d = document.getElementById("mt-drawer");
  const открыть = async (k, кнопка) => {
    document.querySelectorAll(".mt-btn[data-drawer]").forEach(b => b.setAttribute("aria-expanded", "false"));
    if ($d.dataset.k === k && !$d.hidden) {
      $d.hidden = true; $d.dataset.k = ""; _открытаяПанельВстречи = ""; return;
    }
    $d.dataset.k = k;
    кнопка?.setAttribute("aria-expanded", "true");
    let тело = "";
    if (k === "tasks") {
      тело = `<h2>Задачи встречи ${esc(fmtRuDate(встреча.date))}</h2>${мои.length ? `<div data-list="meeting-tasks" data-list-item=".tl-item">${мои.map((t, i) =>
        пунктЗадачи(t, i, "открыть в реестре")).join("")}</div><button type="button" class="link" id="mt-all-tasks">Все задачи встречи в реестре</button>`
        : '<div class="reg-sub">Задач с этой встречи нет.</div>'}`;
    } else if (k === "agreements") {
      тело = панельДоговорённостейВстречи(договорённости || [], fmtRuDate(встреча.date));
    } else if (k === "plan") {
      if (!следующая) тело = `<h2>План следующей встречи</h2><div class="reg-sub">Следующая встреча ещё не заведена.</div>`;
      else {
        const планСледующей = await api(`/meetings/${следующая.id}/plan`);
        тело = `<h2>План встречи ${esc(fmtRuDate(следующая.date))}</h2>
          <a class="mt-plan-link" href="#meetings/${следующая.id}">встреча ${esc(fmtRuDate(следующая.date))}</a>${планСледующей.available
          ? `<div class="doc-render mt-plan doc-content">${renderDocHtml(планСледующей.content_md)}</div>` : `<div class="reg-sub">${esc(планСледующей.message || "Плана пока нет")}</div>`}`;
      }
    } else if (k === "materials") {
      _открытаяПанельВстречи = "materials";
      тело = панельМатериаловHtml({ id, tab, источники, материалы, встреча, admin: админ });
    } else if (k === "notes") {
      тело = панельЗамечанийHtml({ ...протокол, date: встреча.date });
    }
    $d.innerHTML = `<div class="mt-drawer-head"><button type="button" class="mt-close" id="mt-close" aria-expanded="true" aria-controls="mt-drawer" title="Свернуть панель (Esc)">Свернуть ▾</button></div>${тело}`;
    const заголовокПанели = $d.querySelector(":scope > h2");
    if (заголовокПанели) $d.querySelector(".mt-drawer-head").prepend(заголовокПанели);
    $d.hidden = false;
    const ряд = $main.querySelector(".mt-title-row"), слой = $main.querySelector(".mt-layout");
    $d.style.top = k === "tasks" && ряд && слой && getComputedStyle($d).position === "absolute"
      ? `${Math.round(ряд.getBoundingClientRect().bottom - слой.getBoundingClientRect().top + 8)}px` : "";
    if (k === "materials") подключитьМатериалы(id, tab);
    document.getElementById("mt-close").addEventListener("click", () => {
      $d.hidden = true; $d.dataset.k = ""; _открытаяПанельВстречи = "";
      кнопка?.setAttribute("aria-expanded", "false");
    });
    document.getElementById("mt-all-tasks")?.addEventListener("click", () => реестрПоВстрече(id, встреча.date));
  };
  document.querySelectorAll(".mt-btn[data-drawer]").forEach(b => b.addEventListener("click", () => открыть(b.dataset.drawer, b)));
  // «⋯» — одно меню со встречей (Б4): те же пункты, что в реестре и подготовке.
  const допПункты = [{ act: "plan-next", label: "План следующей" }];
  if (админ && hasMin) допПункты.push({ act: "notes", label: `Замечания${замечания ? ` — ${замечания}` : ""}` });
  document.getElementById("meeting-more")?.addEventListener("click", () => менюВстречи(document.getElementById("meeting-more"), встреча,
    { все: встречи, перерисовать: () => renderMeetingReader(id, tab), доп: допПункты,
      приВыборе: (акт) => {
        const к = document.querySelector(`.mt-btn[data-drawer="${акт === "plan-next" ? "plan" : "notes"}"]`);
        открыть(акт === "plan-next" ? "plan" : "notes", к);
      } }));
  const наEsc = ev => {
    if (ev.key !== "Escape") return;
    if (!document.getElementById("mt-drawer")) { document.removeEventListener("keydown", наEsc); return; }
    $d.hidden = true; $d.dataset.k = ""; _открытаяПанельВстречи = "";
  };
  if (renderMeetingReader._наEsc) document.removeEventListener("keydown", renderMeetingReader._наEsc);
  renderMeetingReader._наEsc = наEsc;
  document.addEventListener("keydown", наEsc);
  if (готовит) путьТочками(id);
  if (админ && hasMin) загрузитьПроверкуПослеСохранения(id, { blockId: "minutes-block", canEdit: false });
  полотноПодключитьПереключатель($main, () => renderMeetingReader(id, tab));
  if (режимПолотна === "edit" && документ) {
    const перерисовать = () => renderMeetingReader(id, tab);
    let заметка = null;
    try { заметка = JSON.parse(sessionStorage.getItem("polotnoNote") || "null"); sessionStorage.removeItem("polotnoNote"); }
    catch (e) { заметка = null; }
    if (заметка && заметка.base !== основаПолотна) заметка = null;
    await полотноВключить(document.getElementById("mt-doc-text"), { base: основаПолотна,
      md: документ.content_md, перерисовать, встреча: id, заметка, после: спрятатьПервуюСтроку });
  }
  // Ход сборки, начатой раньше и пережившей переход: тот же экран показывает её и после возврата.
  const видСборки = генерация.kind || (tab === "plan" ? "plan" : "minutes");
  if (генерация.running || генерация.queued) {
    const дляПротокола = видСборки !== "plan";
    показатьХодСборки(id, { findingsId: дляПротокола ? "verify-findings-minutes" : "verify-findings-plan",
      btnId: (дляПротокола ? "protocol" : "plan") === tab ? "reader-main-btn" : "__нет_кнопки__",
      since: генерация.since, queued: генерация.queued && !генерация.running, lines: генерация.queue_lines });
    начатьСлежениеЗаСборкой(id, () => renderMeetingReader(id, дляПротокола ? "protocol" : "plan"));
  }
  // Черновик — одна точка решения: баннер над документом; тот же шаг есть в карточке пути.
  document.getElementById("reader-accept-draft")?.addEventListener("click", async () => {
    if (!(await confirmDialog("Сохранить протокол как есть, с замечаниями проверки? Задачи и статусы из него применятся.", "Сохранить"))) return;
    try {
      await api(`/meetings/${id}/accept-draft`, { method: "POST" });
      toast("Протокол сохранён с замечаниями");
      renderMeetingReader(id, tab);
    } catch (e) { toast(e.message, true); }
  });
  // Главная кнопка: одно подтверждение о платном вызове, с источниками и предупреждением о другой встрече того же дня
  // (05.11.2026, находка 1). Второго окна нет — прежняя кнопка скрытой полосы не нажимается.
  document.getElementById("reader-main-btn")?.addEventListener("click", async () => {
    const другаяНаДату = встречи.find(x => x.id !== встреча.id && x.date === дата && x.status !== "cancelled");
    if (tab === "protocol") {
      if (hasMin && протокол.hand_edited) { toast(ПЕРЕСБОРКА_ЗАПРЕЩЕНА, true); return; }
      const живые = (источники || []).filter(s => !s.removed_at);
      if (!живые.length) {
        toast("Собирать протокол не из чего: к встрече не приложены ни расшифровка, ни запись, ни заметки. Добавьте файл в «Материалах».", true);
        return;
      }
      const имена = живые.map(s => s.original_filename || "вставленный текст").join("\n  • ");
      const предупреждение = другаяНаДату
        ? `\n\nНа эту дату есть ещё встреча ${fmtRuDate(другаяНаДату.date)}${cleanLabel(другаяНаДату.label) ? ` «${cleanLabel(другаяНаДату.label)}»` : ""} — записи другой встречи того же дня по содержанию не отличить. Проверьте источники.`
        : "\n\nПроверьте, что это записи именно этой встречи.";
      const вопрос = `${подписьПротокола} — встреча ${fmtRuDate(встреча.date)}?\n  • ${имена}${предупреждение}\n\nЭто платный вызов модели, 1–5 минут.`;
      if (!(await confirmDialog(вопрос, "Собрать"))) return;
      runMeetingGeneration({ id, btnId: "reader-main-btn",
        endpoint: `/meetings/${id}/prepare-minutes?confirm=1${hasMin ? "&rebuild=true" : ""}`,
        findingsId: "verify-findings-minutes", idleLabel: подписьПротокола, okToast: "Протокол сохранён",
        partialToast: `Протокол сохранён, но Дорожная карта/Сводка не обновились — ${conflictsRef()}`,
        rerender: () => renderMeetingReader(id, "protocol") });
    } else {
      const имена = (материалы || []).map(m => m.original_filename).filter(Boolean).join("\n  • ");
      const предупреждение = другаяНаДату
        ? `\n\nНа эту дату есть ещё встреча ${fmtRuDate(другаяНаДату.date)}${cleanLabel(другаяНаДату.label) ? ` «${cleanLabel(другаяНаДату.label)}»` : ""} — её материалы сюда не попадут.`
        : "";
      const вопрос = `${подписьПлана} — встреча ${fmtRuDate(встреча.date)}?${имена ? `\n  • ${имена}` : ""}${предупреждение}\n\nЭто платный вызов модели, 1–5 минут. План сохраняется сразу, прежняя версия не удаляется — остаётся в базе.${hasPlan && план.hand_edited ? ПРЕДУПРЕЖДЕНИЕ_РУЧНЫХ_ПРАВОК : ""}`;
      if (!(await confirmDialog(вопрос, "Собрать"))) return;
      runMeetingGeneration({ id, btnId: "reader-main-btn", endpoint: `/meetings/${id}/prepare-plan?confirm=1`,
        findingsId: "verify-findings-plan", idleLabel: подписьПлана, okToast: "План сохранён",
        partialToast: `План сохранён, но Дорожная карта/Сводка не обновились — ${conflictsRef()}`,
        rerender: () => renderMeetingReader(id, "plan") });
    }
  });
  document.getElementById("reader-plan-newer")?.addEventListener("click", () => {
    if (document.getElementById("reader-main-btn")?.disabled) { toast("Сейчас идёт сборка — новые материалы войдут в следующую; переформировать можно после неё"); return; }
    document.getElementById("reader-main-btn")?.click();
  });
  // Панель, открытая до перерисовки (например, «Материалы» после загрузки), остаётся открытой.
  if (_открытаяПанельВстречи) {
    const b = document.querySelector(`.mt-btn[data-drawer="${_открытаяПанельВстречи}"]`);
    if (b) открыть(_открытаяПанельВстречи, b);
  }
}

// ---- Путь встречи точками в строке инструментов — вариант Б (решение владельца 13.10.26, дополнение «Линия») -------------
// Только администратору: участнику — ни разметки, ни запроса (сервер путь не отдаёт: /meetings/{id}/path — require_admin).
// В строке после метки состояния — точки на тонкой линии и подпись последнего шага; по щелчку весь путь всплывает карточкой
// поверх документа (документ не сдвигается). Карточка — вне строки инструментов: у строки своя прокрутка вбок, и карточку
// внутри неё обрезало бы. Закрывается Esc, щелчком мимо и повторным щелчком; при смене экрана снимается.
async function путьТочками(id) {
  // Путь — всем, кто готовит встречу (05.11.2026, Б1): на одной странице его видят и участники; сервер отдаёт /path
  // вошедшему. Метка состояния в строке остаётся только администратору, поэтому путь вставляем и без неё.
  if (!canPrepare()) return;
  let p;
  try { p = await api(`/meetings/${id}/path`); } catch (e) { return; }
  const $bar = $main.querySelector(".mt-bar");
  const $state = $bar?.querySelector(".mt-state");
  if (!$bar || $bar.querySelector(".mt-path")) return;
  const сбой = p.steps.find(ш => ш.state === "сбой");
  const текущий = p.steps.find(ш => ш.k === p.current);
  const подпись = (сбой || текущий || p.steps[p.steps.length - 1]).title;
  const точки = p.steps.map(ш => {
    const пропущен = ш.k === "decision" && ш.state === "готово" && /не требовалось/.test(ш.detail || "");
    const вид = ш.state === "сбой" ? "fail" : пропущен ? "skip" : ш.state === "готово" ? "done" : ш.k === p.current ? "now" : "todo";
    return `<span class="mp-dot mp-${вид}"></span>`;
  }).join("");
  const путьHtmlКнопки = `<button type="button" class="mt-path${сбой ? " mt-path-fail" : ""}" aria-expanded="false"
    aria-haspopup="dialog" aria-label="Путь встречи: ${esc(подпись)}"><span class="mp-line" aria-hidden="true">${точки}</span><span class="mp-label">Путь: ${esc(подпись)}</span></button>`;
  if ($state) $state.insertAdjacentHTML("afterend", путьHtmlКнопки);
  else $bar.insertAdjacentHTML("beforeend", путьHtmlКнопки);
  const $btn = $bar.querySelector(".mt-path");
  let $card = null;
  const поставить = () => {
    if (!$card) return;
    const r = $btn.getBoundingClientRect();
    const ширина = Math.min(330, innerWidth - 32);
    $card.style.width = `${ширина}px`;
    $card.style.top = `${Math.round($bar.getBoundingClientRect().bottom + 6)}px`;   // под строкой инструментов, не на ней
    $card.style.left = `${Math.round(Math.max(16, Math.min(r.left, innerWidth - ширина - 16)))}px`;
  };
  const закрыть = () => {
    if (!$card) return;
    $card.remove(); $card = null;
    $btn.setAttribute("aria-expanded", "false");
    document.removeEventListener("keydown", наEsc); document.removeEventListener("click", мимо, true);
    window.removeEventListener("scroll", поставить, true); window.removeEventListener("resize", поставить);
  };
  const наEsc = ev => { if (ev.key === "Escape") { закрыть(); $btn.focus(); } };
  const мимо = ev => { if ($card && !$card.contains(ev.target) && !$btn.contains(ev.target)) закрыть(); };
  $btn.addEventListener("click", () => {
    if ($card) { закрыть(); return; }
    $card = document.createElement("div");
    $card.className = "mt-path-card";
    $card.setAttribute("role", "dialog");
    $card.setAttribute("aria-label", "Путь встречи");
    $card.innerHTML = путьHtml(p);
    $card.querySelector(".path-head")?.setAttribute("tabindex", "-1");
    document.body.appendChild($card);
    поставить();
    $btn.setAttribute("aria-expanded", "true");
    document.addEventListener("keydown", наEsc);
    document.addEventListener("click", мимо, true);
    window.addEventListener("scroll", поставить, true);
    window.addEventListener("resize", поставить);
    $card.querySelector("#path-accept")?.addEventListener("click", async () => {
      try {
        await api(`/meetings/${id}/accept-draft`, { method: "POST" });
        toast("Протокол принят с замечаниями — задачи заведены в реестр");
        закрыть(); render();
      } catch (e) { toast(e.message, true); }
    });
  });
  window.addEventListener("hashchange", закрыть, { once: true });
}

// Маршруты: #meetings — лента; #meetings/<id> — страница встречи; #meetings/<id>/protocol и #meetings/<id>/planprep —
// подготовка встречи (прежние экраны: сборка, приёмка, источники, точечная правка).
routes.meetings = (rest) => {
  if (!rest || !rest[0]) return renderProtocols();
  // Прежние адреса открывают ту же одну страницу нужной вкладкой (пакет Б, Б1).
  if (rest[1] === "protocol") return renderMeetingReader(rest[0], "protocol");
  if (rest[1] === "planprep") return renderMeetingReader(rest[0], "plan");
  return renderMeetingReader(rest[0]);
};

// Перерисовки мимо render() держат прокрутку на месте (18.10.26, `сПрокруткойНаМесте`): встреча.
renderMeetingReader = сПрокруткойНаМесте(renderMeetingReader);

// ---- Реестр договорённостей (19.10.2026, Е2 списка отставания; как «Договорённости» Планёрки) ----------------------------
// Всем ролям (решение владелицы 20.10.2026, п. 3): служебное — цитату, номер строки, отметку «под вопросом» с причиной и сами
// записи «под вопросом» — сервер отдаёт только администраторам; в режиме «в тени» не-администратору — пустой список.
// С 21.10.2026 (решения владелицы, пункт 5: «как в Планёрке, проверить по факту всё») — экран Планёрки `renderAgreements`:
// отбор по проекту, виду (с «Открытые: вопросы и без решения») и датам, поиск, «Сбросить»; таблица «Дата · Проект · Вид · Что
// решили · Кто решил · Статус» с подписью темы под формулировкой и пометкой «заменена записью №N»; точка «под вопросом» —
// ссылкой в «Конфликты», только администратору; пустота объяснена («в тени», «выберите себя»). Было: список «дата · вид ·
// формулировка · статус», отбор только по виду, поиск через 400 мс.
// Е21 (19.10.2026): сервер сразу отдаёт 7 строк и общее число, снизу — «Показать все (N)»; по кнопке остальное подгружается
// целиком (`offset`, `limit=0`) и список раскрывается общей свёрткой таблиц (`collapseLongTable`: рамка со своим ползунком,
// «Свернуть список»); «развёрнуто» держится по ключу до смены вкладки или отбора. Поиск — на сервере по всей базе
// (`agreements.отбор_реестра`): по вводу через 300 мс и по Enter, плашки «Искали: …» — как в реестре задач.
const AGREEMENT_KIND_LABELS = { "решение": "Решение", "правило работы": "Правило работы", "открытый вопрос": "Открытый вопрос",
  "обсуждено без решения": "Обсуждено без решения" };
const AGREEMENT_OPEN_FILTER = "открытые";   // директору вместе с открытыми вопросами — «обсуждено без решения» (17.10.26)
const ПЕРВАЯ_ПОРЦИЯ_ДОГОВОРЁННОСТЕЙ = ПРЕДЕЛ_РЕЕСТРА;
const КЛЮЧ_ДОГОВОРЁННОСТЕЙ = "agreements";

async function renderAgreements() {
  if (!renderAgreements.filters) {
    const парам = new URLSearchParams(location.hash.split("?")[1] || "");
    renderAgreements.filters = { project: "", kind: парам.get("kind") || "", date_from: "", date_to: "", q: парам.get("q") || "" };
  }
  const f = renderAgreements.filters;
  const адрес = (доп) => "/agreements?" + new URLSearchParams([...Object.entries(f).filter(([, v]) => v), ...Object.entries(доп)]).toString();
  const раскрыт = expandedLists.has(КЛЮЧ_ДОГОВОРЁННОСТЕЙ);
  const data = await api(адрес({ limit: раскрыт ? "0" : String(ПЕРВАЯ_ПОРЦИЯ_ДОГОВОРЁННОСТЕЙ) }));
  const опция = (v, sel, label) => `<option value="${esc(v)}"${v === sel ? " selected" : ""}>${esc(label ?? v)}</option>`;
  const строкаHtml = (a) => {
    const точка = a.under_question && isAdmin()
      ? ` <a class="task-doubt-dot uq-dot" href="#razbor" title="${esc("под вопросом: " + a.under_question + " — решить в «Разборе»")}" aria-label="${esc("под вопросом: " + a.under_question)}"></a>` : "";
    const кто = [a.decided_by ? "решил: " + a.decided_by : "", a.agreed_by ? "согласились: " + a.agreed_by : "",
      a.proposed_by ? "предложил: " + a.proposed_by : ""].filter(Boolean).join("; ");
    return `<tr data-agreement-id="${a.id}">
      <td class="c-due" data-label="Дата"><a href="#meetings/${a.meeting_id}">${esc(fmtRuDate(a.date))}</a></td>
      <td data-label="Подпроект">${a.subproject ? esc(a.subproject) : '<span class="page-sub">—</span>'}</td>
      <td data-label="Вид">${esc(AGREEMENT_KIND_LABELS[a.kind] || a.kind)}</td>
      <td class="task-desc-cell" data-label="Что решили"><span class="task-desc-text">${esc(a.text)}</span>${точка}${a.topic ? ` <span class="doc-cell-sub">${esc(a.topic)}</span>` : ""}</td>
      <td data-label="Кто решил">${кто ? esc(кто) : '<span class="page-sub">—</span>'}</td>
      <td data-label="Статус">${esc(a.status)}${a.replaced_by_id ? ` <span class="page-sub">(${a.status === "решено позже" ? "решение — запись" : "заменена записью"} №${a.replaced_by_id})</span>` : ""}</td>
    </tr>`;
  };
  const всего = data.total ?? data.items.length;
  const кнопкаЕщё = всего > data.items.length
    ? `<tr class="more-row"><td colspan="6" style="text-align:center; padding:12px 8px;"><button class="btn-sm" type="button" data-agr-more>Показать все (${data.total})</button></td></tr>` : "";
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>Договорённости по проекту</h1>
      <div class="feed-sub">Решения, правила работы, открытые вопросы и обсуждённое без решения. Договорённость с понятным действием и
        исполнителем — задача, она в реестре задач. ${data.mode === "on"
        ? "В протоколе — решения и открытые вопросы обычными предложениями в разделах тем." : "Режим «в тени»: в протокол строки не идут."}</div></div></div>
    <div class="card hstack" id="agr-filter" style="gap:8px;padding:12px 16px;margin:0 0 16px">
      ${/* фильтр проекта — всегда, один компонент с Планёркой (решения владелицы 25.10.2026, пп. 1–2): «Весь проект …» — все
            записи без отбора, ниже подпроекты проекта системы и «без подпроекта», если подпроекты есть */ ""}
      ${фильтрПроектаHtml("agr-project", { все: (data.project_filter || {}).all || "Все записи проекта", варианты: (data.project_filter || {}).options || [],
        без: (data.project_filter || {}).none || "", безЗначение: (data.project_filter || {}).none_value || "__none__", выбран: f.project })}
      <select id="agr-kind" aria-label="Вид" style="width:auto"><option value="">Все виды</option>${опция(AGREEMENT_OPEN_FILTER, f.kind, "Открытые: вопросы и без решения")}${(data.kinds || []).map(k => опция(k, f.kind, AGREEMENT_KIND_LABELS[k])).join("")}</select>
      <label>с <input type="date" id="agr-from" value="${esc(f.date_from)}" style="width:150px"></label>
      <label>по <input type="date" id="agr-to" value="${esc(f.date_to)}" style="width:150px"></label>
      <input type="search" id="agr-q" value="${esc(f.q)}" placeholder="Поиск: слова, проект, фамилия или дата" aria-label="Найти договорённость" autocomplete="off" style="flex:1 1 260px;width:auto">
      <button type="button" class="link search-reset-link" id="agr-reset">Сбросить</button></div>
    <div id="agr-markers"></div>
    ${!isAdmin() && data.mode === "shadow"
      ? `<div class="card reg-card"><div class="empty-state" id="agreements-empty">Реестр договорённостей пока ведётся в тени — откроется всем, когда суперадминистратор включит договорённости.</div></div>`
      : !isAdmin() && !me ? `<div class="card reg-card"><div class="empty-state" id="agreements-empty">Выберите себя в «Вы работаете как», чтобы открыть реестр договорённостей.</div></div>`
      : data.items.length ? `<div class="card reg-card"><div class="table-scroll"><table class="agreements-table">
      <thead><tr><th>Дата</th><th title="Подпроект проекта системы; пусто — запись относится ко всему проекту">Подпроект</th><th>Вид</th><th>Что решили</th><th>Кто решил</th><th>Статус</th></tr></thead>
      <tbody>${data.items.map(строкаHtml).join("")}${кнопкаЕщё}</tbody></table></div></div>`
      : `<div class="card reg-card"><div class="empty-state" id="agreements-empty">${Object.values(f).some(Boolean) ? "Договорённостей по этим условиям нет." : "Договорённостей пока нет."}</div></div>`}`;
  const tbody = $main.querySelector(".agreements-table tbody");
  const раскрыть = () => {
    tbody.querySelector("tr.more-row")?.remove();
    expandedLists.add(КЛЮЧ_ДОГОВОРЁННОСТЕЙ);
    collapseLongTable(tbody, LONG_LIST_LIMIT, КЛЮЧ_ДОГОВОРЁННОСТЕЙ);
  };
  if (раскрыт && tbody) раскрыть();
  tbody?.querySelector("[data-agr-more]")?.addEventListener("click", async (e) => {
    const кнопка = e.currentTarget;
    кнопка.disabled = true;
    try {
      const ещё = await api(адрес({ offset: String(data.items.length), limit: "0" }));
      data.items = data.items.concat(ещё.items || []);
      tbody.querySelector("tr.more-row")?.insertAdjacentHTML("beforebegin", (ещё.items || []).map(строкаHtml).join(""));
      раскрыть();
    } catch (err) { toast(err.message, true); кнопка.disabled = false; }
  });
  const применить = async ({ сФокусом = false } = {}) => {
    const поле = document.getElementById("agr-q");
    const поз = поле ? поле.selectionStart : null;
    Object.assign(f, { project: document.getElementById("agr-project").value, kind: document.getElementById("agr-kind").value,
      date_from: document.getElementById("agr-from").value, date_to: document.getElementById("agr-to").value, q: поле.value.trim() });
    expandedLists.delete(КЛЮЧ_ДОГОВОРЁННОСТЕЙ);       // новый отбор или поиск — снова первые 7 и «Показать все (N)»
    if (location.hash !== "#agreements") history.replaceState(null, "", "#agreements");
    await render();
    if (сФокусом) { const n = document.getElementById("agr-q"); if (n) { n.focus(); if (поз !== null) n.setSelectionRange(поз, поз); } }
  };
  показатьПлашкиМаркеров(document.getElementById("agr-markers"), data.markers || null, (qq) => {
    document.getElementById("agr-q").value = qq; применить();
  });
  let таймер = null;
  document.getElementById("agr-q")?.addEventListener("input", () => {
    clearTimeout(таймер);
    таймер = setTimeout(() => применить({ сФокусом: true }), 300);
  });
  document.getElementById("agr-q")?.addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(таймер); применить({ сФокусом: true }); } });
  ["agr-project", "agr-kind", "agr-from", "agr-to"].forEach(id => document.getElementById(id)?.addEventListener("change", () => применить()));
  document.getElementById("agr-reset")?.addEventListener("click", () => {
    clearTimeout(таймер); renderAgreements.filters = null; expandedLists.delete(КЛЮЧ_ДОГОВОРЁННОСТЕЙ);
    if (location.hash !== "#agreements") history.replaceState(null, "", "#agreements");
    render();
  });
}
routes.agreements = renderAgreements;
