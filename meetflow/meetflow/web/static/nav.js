// Навигация — вариант Б прототипа 1 (выбор владельца 13.10.26, стенд 8020).
// Три главных пункта: «Протоколы», «Реестр задач», «Статус проекта». Ниже черты, только администратору: «Команда»,
// «Конфликты», «Система» («Подготовка встречи» с 21.10.2026 — главным пунктом рядом со «Встречами по проекту»; с 28.10.2026 —
// вторым пунктом за «Реестром встреч», решение владелицы). «Система» — один пункт вместо «Параметров системы», «Мониторинга
// RealTime», «Моделей», «Единиц встреч», «Базы голосов»: прежние экраны стали её вкладками (их код не переписан).
// Подключается после app.js и registry.js.

const _экранВстреч = routes.meetings;      // прежний экран встречи: подготовка протокола и плана (список рисует renderProtocols)

// ---- Лента «Протоколы» ---------------------------------------------------------------------------------------
function протоколСостояние(m) {
  if (m.status === "cancelled") return { текст: "встреча отменена", знак: "" };     // 21.10.2026, О9
  if (m.building) return { текст: "идёт сборка", знак: "clock" };
  if (m.draft_pending) return { текст: "черновик ждёт решения", знак: "clock", акцент: true };
  if (m.has_minutes) return { текст: "протокол готов", знак: "check" };
  const с = m.состояние_протокола || "";
  if (/запис/i.test(с)) return { текст: "ждёт запись", знак: "clock" };
  return { текст: с || "протокола нет", знак: "" };
}

const НАВ_ЗНАКИ = {
  clock: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>',
  doc: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 15h7"/></svg>',
  list: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 8h8M12 16h8"/></svg>',
  chart: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 19h16"/><path d="M5 15l4-5 4 3 6-7"/></svg>',
};

// «Реестр встреч» (до 28.10.2026 — «Встречи по проекту», переименован решением владелицы) — как старый список (владелец 14.10.26, перенос из Планёрки 79120fc: «сделай как старый, но с учётом
// требований к дизайну, сейчас это сплошное поле без навигации»): заголовок с пояснением; разделы «Последние встречи» и
// «Архив — старше N недель» с заголовком и числом; строка открывает встречу щелчком в любом месте (строка — ссылка
// целиком). Оформление — новое.
// С 21.10.2026 (решения владелицы, «Проект нового пути»): формы «Создать встречу» здесь нет — одна точка создания,
// «Подготовка встречи» (две точки входа к одной встрече — главный источник дублей; так появились №26 и №27 на 22.10). Вместо
// тупиковой ссылки «открыть в «Подготовке»» (участник попадал обратно) — «Ближайшая встреча … — план встречи» всем ролям.
const НЕДЕЛЬ_ДО_АРХИВА = 4;          // у ERP настройки нет — как у Планёрки по умолчанию

// «старше 4 недель» (родительный) и «за последние 4 недели» (винительный)
function недельРод(n) { return n % 10 === 1 && n % 100 !== 11 ? "недели" : "недель"; }
function недельВин(n) {
  if (n % 10 === 1 && n % 100 !== 11) return "неделю";
  return n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "недели" : "недель";
}

function датаISO(д) {
  return `${д.getFullYear()}-${String(д.getMonth() + 1).padStart(2, "0")}-${String(д.getDate()).padStart(2, "0")}`;
}

// Ближайшая встреча — первая неотменённая с сегодняшнего дня (сегодняшняя тоже: её план ещё нужен)
// Две встречи на дату (Д9, проходы 2–3, 21.10.2026): прежде бралась меньшая по номеру, даже пустая, а план был у другой.
// Теперь — та, что с планом, иначе меньший номер (то же правило, что «оставить» при сводке и у папки-приёмника, О10).
function ближайшаяВстреча(встречи, сегодня) {
  return встречи.filter(m => m.status !== "cancelled" && m.date >= сегодня)
    .sort((a, b) => a.date.localeCompare(b.date) || (b.has_plan ? 1 : 0) - (a.has_plan ? 1 : 0) || a.id - b.id)[0] || null;
}

async function renderProtocols() {
  const админ = isAdmin();
  // Владелец 15.10.26: «сделай для страницы Встречи такой же дизайн-подход, как для Планёрки (её «Список планёрок»), только
  // оставь цвета и элементы дизайна как для ERP». Как у Планёрки: заголовок с пояснением отдельной строкой; в строке — месяц
  // у первой встречи месяца, дата полужирным, ссылки «Протокол» и «Встреча», название, состояние, «задач N» справа; строка
  // открывается щелчком в любом месте. Будущие даты в списке не показываются (у Планёрки — решение владельца 15.10.26
  // «будущее не надо показывать»): над списком — ближайшая встреча и её план.
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>Реестр встреч</h1>
      <div class="feed-sub">Нажмите на строку, чтобы открыть встречу и её протокол.${canPrepare() ? " Новая встреча заводится в «Подготовке встречи»." : ""}</div></div></div>
    <div id="nearest-slot"></div>
    <div id="proto-list"><div class="card empty-state">Загрузка…</div></div>`;
  const встречи = await api("/meetings");
  const $l = document.getElementById("proto-list");
  if (!$l) return;
  const сегодня = датаISO(new Date());
  const ближайшая = ближайшаяВстреча(встречи, сегодня);
  const $n = document.getElementById("nearest-slot");
  if ($n) {
    $n.innerHTML = ближайшая
      ? `<div class="nearest-line"><a id="nearest-link" href="#meetings/${ближайшая.id}/planprep">Ближайшая встреча ${esc(fmtRuDate(ближайшая.date))} — план встречи</a>${ближайшая.has_plan ? "" : ' <span class="prep-muted">(плана пока нет)</span>'}</div>`
      : canPrepare() ? `<div class="nearest-line prep-muted" id="nearest-link">Ближайшей встречи нет — заведите её в <a href="#prep">«Подготовке встречи»</a>.</div>` : "";
  }
  if (!встречи.length) {
    $l.innerHTML = `<div class="card empty-state reg-empty">${НАВ_ЗНАКИ.doc}<div class="reg-empty-title">Встреч пока нет</div>${canPrepare() ? '<div>Заведите встречу в <a href="#prep">«Подготовке встречи»</a>.</div>' : ""}</div>`;
    return;
  }
  const рубеж = new Date(); рубеж.setDate(рубеж.getDate() - НЕДЕЛЬ_ДО_АРХИВА * 7);
  const рубежISO = датаISO(рубеж);
  const по_дате = встречи.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  const будущие = по_дате.filter(m => m.date > сегодня && m.status !== "cancelled");
  const прошедшие = по_дате.filter(m => m.date <= сегодня);
  const свежие = прошедшие.filter(m => m.date >= рубежISO), архив = прошедшие.filter(m => m.date < рубежISO);
  let месяцПрежний = "";
  const строка = m => {
    const с = протоколСостояние(m);
    const месяц = new Date(m.date).toLocaleDateString("ru-RU", { month: "long", year: "numeric" }).replace(" г.", "");
    const месяцЯчейка = месяц === месяцПрежний ? "" : месяц;
    месяцПрежний = месяц;
    // Название встречи — как в прежней таблице (в том числе пометка «дата ориентировочная»; аудит 13.10.26)
    const название = cleanLabel(m.label);
    return `<li><div class="proto-row" data-href="#meetings/${m.id}">
        <span class="proto-month">${esc(месяцЯчейка)}</span>
        <a class="proto-date" href="#meetings/${m.id}">${esc(fmtRuDate(m.date))}</a>
        <span class="proto-acts"><a href="#meetings/${m.id}/protocol">Протокол</a><a href="#meetings/${m.id}">Встреча</a></span>
        ${название ? `<span class="proto-label">${esc(название)}</span>` : ""}
        ${(!выбранныйПроект() && m.project_label) || m.subproject ? `<span class="proto-label">${esc(выбранныйПроект() ? m.subproject : m.project_label)}</span>` : ""}
        <span class="proto-state${с.акцент ? " proto-state-acc" : ""}">${НАВ_ЗНАКИ[с.знак] || ""}${esc(с.текст)}</span>
        ${m.предложена_пересборка && isAdmin() ? `<a class="proto-state proto-state-acc" href="#razbor" title="Пришёл источник, добавляющий новое. Протокол правили вручную, встреча старше пяти рабочих дней или автопересборок уже две — сами не пересобираем. Решение — в «Разборе»">есть новые материалы — пересобрать?</a>` : ""}
        <span class="proto-tasks">задач ${m.tasks_count || 0}</span></div></li>`;
  };
  const список = (строки, ключ) => { месяцПрежний = ""; return `<div class="card reg-card feed-list"><ul class="proto-feed" data-list="${ключ}">${строки.map(строка).join("")}</ul></div>`; };
  const заСрок = НЕДЕЛЬ_ДО_АРХИВА === 1 ? "за последнюю неделю" : `за последние ${НЕДЕЛЬ_ДО_АРХИВА} ${недельВин(НЕДЕЛЬ_ДО_АРХИВА)}`;
  const старше = `${НЕДЕЛЬ_ДО_АРХИВА} ${недельРод(НЕДЕЛЬ_ДО_АРХИВА)}`;
  const ещёБудущих = будущие.filter(m => !ближайшая || m.id !== ближайшая.id).length;
  // «Последние» — только когда они есть (как у Планёрки); иначе архив открыт сразу
  $l.innerHTML = `${свежие.length ? `<h2 class="feed-section">Последние встречи <span class="cnt">${свежие.length}</span> <span class="feed-h-note">${заСрок}</span></h2>
      ${список(свежие, "protocols")}` : ""}
    ${архив.length ? `<details class="feed-archive"${свежие.length ? "" : " open"}><summary class="feed-section">Архив — встречи старше ${старше} <span class="cnt">${архив.length}</span></summary>
      ${список(архив, "protocols-archive")}</details>` : ""}
    ${ещёБудущих && canPrepare() ? `<div class="feed-sub feed-future">Ещё встреч на будущие даты: ${ещёБудущих} — в <a href="#prep">«Подготовке встречи»</a>.</div>` : ""}`;
  // Строка открывает встречу щелчком в любом месте; ссылки внутри строки работают сами
  $l.querySelectorAll(".proto-row").forEach(р => р.addEventListener("click", (e) => {
    if (e.target.closest("a, button")) return;
    location.hash = р.dataset.href;
  }));
}

routes.meetings = (rest) => (rest && rest[0]) ? _экранВстреч(rest) : renderProtocols();

// ---- «Подготовка встречи» — администратор: ближайшая встреча, единственная точка создания, сведение дублей -------------
// Новый путь (решения владелицы 21.10.2026, «Проект нового пути»; исследование: Fellow, Teams/Loop, YouTrack, Stripe):
//   * сверху одна карточка «Ближайшая встреча: ДД.ММ.ГГГГ, день недели · план собран … · материалов N» и одна главная кнопка
//     «Открыть план встречи»; встреча, заведённая системой, — с пометкой «дата предложена системой · изменить дату»;
//   * будущей встречи нет — «Создать встречу» с подставленной датой (обычный шаг встреч, как у «Плана следующей»); после
//     создания — сразу в план этой встречи;
//   * «Другая дата…» раскрывает форму; при выборе занятой даты сразу (до отправки, `GET /meetings/date-check`): «На … уже
//     есть встреча — план собран. Открыть её», «Создать» неактивна; вторая встреча в тот же день — только галочкой
//     «Вторая встреча в этот день», название необязательно (О1–О3; О2 изменено 24.10.2026, дополнение владелицы: было «с
//     названием»). Повтор «Создать» при обрыве сети — тот же ключ, та же встреча (О4);
//   * таблица: «План встречи» и «Протокол»; у будущей встречи вместо «создать протокол» — «встреча ещё не прошла»; пометки
//     «дата предложена системой», «две встречи на дату», «отменена» (старые, до 23.10.2026); у дубля — «Свести в одну»
//     (единственное новое подтверждение, О9): с 23.10.2026 опустевшая встреча удаляется, «Вернуть» у отменённой убрано
//     (решение владелицы: «отмена без удаления только добавляет лишних строк»).
// Права (решение владелицы 21.10.2026, «будут все пользователи делать»): экран — всем ролям, первым пунктом меню; создать
// встречу, приложить файлы, собрать план и протокол может каждый — с теми же защитами (одна встреча на дату, предупреждение
// о дубле до отправки, ключ повтора, занятая кнопка на время сборки). «Свести в одну», «Удалить встречу», «Вернуть на новую
// дату» и «изменить дату» — администраторам (сервер: require_admin), участнику этих кнопок нет.
let _ключФормыВстречи = null;
function ключФормыВстречи(новый = false) {
  if (новый || !_ключФормыВстречи) _ключФормыВстречи = `prep-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return _ключФормыВстречи;
}

// Обычный шаг встреч — как на сервере (`next_plan.usual_step_days`): медиана последних интервалов, от 1 до 14 дней, иначе 7
function предложеннаяДата(живые, сегодня) {
  const даты = живые.map(m => m.date).sort().reverse().slice(0, 6);
  const интервалы = даты.slice(1).map((д, i) => Math.round((new Date(даты[i]) - new Date(д)) / 86400000)).filter(x => x > 0).sort((a, b) => a - b);
  let шаг = интервалы.length ? интервалы[Math.floor((интервалы.length - 1) / 2)] : 7;
  if (интервалы.length && интервалы.length % 2 === 0) шаг = Math.floor((интервалы[интервалы.length / 2 - 1] + интервалы[интервалы.length / 2]) / 2);
  шаг = Math.min(Math.max(шаг, 1), 14);
  const д = даты.length ? new Date(даты[0]) : new Date();
  do { д.setDate(д.getDate() + шаг); } while (датаISO(д) <= сегодня);
  return датаISO(д);
}

function деньНедели(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("ru-RU", { weekday: "long" });
}

// «Создать проект» на «Подготовке встречи» (MeetFlow, решение владелицы 28.10.2026): название и необязательный надпроект — как
// в «Параметры системы → Проекты»; заводит тот же адрес POST /projects-list с теми же правами (суперадминистратор, сервер —
// `need_super`), поэтому блок виден только ему. После создания выбор проектов перечитывается, новый проект становится текущим.
function создатьПроектHtml() {
  if (!isSuperAdmin()) return "";
  const надпроекты = _проекты.map(п => `<option value="${п.id}">${esc(п.label || п.name)}</option>`).join("");
  return `<h2 class="feed-section">Создать проект</h2>
    <div class="card prep-new-project" id="prep-new-project">
      <form id="prep-project-form" autocomplete="off">
        <input type="text" id="prep-project-name" placeholder="Название проекта" aria-label="Название проекта" maxlength="200">
        <label>Надпроект <select id="prep-project-parent"><option value="">— проект верхнего уровня —</option>${надпроекты}</select></label>
        <button type="submit" class="btn-primary btn-sm" id="prep-project-btn">Создать проект</button>
      </form>
      <div class="page-sub">Новый проект сразу появится в выборе «Проект» вверху левой панели и станет текущим. Варианты написания,
        архив и надпроект меняются в «Параметры системы → Проекты».</div>
    </div>`;
}
function подключитьСозданиеПроекта() {
  const $f = document.getElementById("prep-project-form");
  if (!$f) return;
  $f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const $кнопка = document.getElementById("prep-project-btn");
    const имя = document.getElementById("prep-project-name").value.trim();
    if (!имя) { toast("Укажите название проекта", true); return; }
    if ($кнопка.disabled) return;                 // двойной щелчок не заводит два проекта
    $кнопка.disabled = true;
    try {
      const п = await api("/projects-list", { method: "POST", json: { name: имя,
        parent_id: Number(document.getElementById("prep-project-parent").value) || null } });
      toast(`Проект «${п.label || п.name}» создан`);
      await загрузитьПроекты();
      выбратьПроект(п.id);
    } catch (e) { $кнопка.disabled = false; toast(e.message, true); }
  });
}
// «Подготовка встречи» при «Все проекты» (решение владелицы 28.10.2026): вместо голой подсказки «выберите проект» — выбор
// действующего проекта (тот же механизм, что #project-select: `выбратьПроект`) и «Создать проект»
function renderPrepВыборПроекта() {
  const проекты = _проекты;
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>Подготовка встречи</h1>
      <div class="feed-sub">Встреча заводится в одном проекте. Выберите проект — откроются его ближайшая встреча и план.</div></div></div>
    <div class="card prep-project-pick" id="prep-project-pick">${проекты.length
      ? `<label for="prep-project-select">Проект</label>
        <select id="prep-project-select"><option value="">— выберите проект —</option>${проекты.map(п =>
          `<option value="${п.id}">${"   ".repeat(п.level || 0)}${п.level ? "– " : ""}${esc(п.name)}</option>`).join("")}</select>`
      : `<span class="page-sub">Проектов пока нет${isSuperAdmin() ? " — создайте первый ниже." : " — его заводит суперадминистратор."}</span>`}</div>
    ${создатьПроектHtml()}`;
  document.getElementById("prep-project-select")?.addEventListener("change", (e) => { if (e.target.value) выбратьПроект(e.target.value); });
  подключитьСозданиеПроекта();
}

async function renderPrep() {
  if (!canPrepare()) { location.replace("#meetings"); return; }     // никто не выбран в «Вы работаете как»
  // MeetFlow: встреча заводится в одном проекте. При «Все проекты» — выбор проекта и «Создать проект», а не голая подсказка
  // (решение владелицы 28.10.2026; было — `нуженПроект("Подготовка встречи")`)
  if (!выбранныйПроект()) { renderPrepВыборПроекта(); return; }
  const админ = isAdmin();
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>Подготовка встречи</h1>
      <div class="feed-sub">Ближайшая встреча и её план. Новая встреча заводится здесь — одна на дату.</div></div></div>
    <div id="prep-body"><div class="card empty-state">Загрузка…</div></div>`;
  const встречи = await api("/meetings");
  const $b = document.getElementById("prep-body");
  if (!$b) return;
  const сегодня = датаISO(new Date());
  const авто = m => m.label === "дата ориентировочная";
  // Д13 (проходы 1 и 3, 21.10.2026): вторая встреча в тот же день заводится только галочкой — она не дубль, и «Свести в одну»
  // ей не предлагается. Дубль — две и больше встреч на дату без своего названия (№26 «дата ориентировочная» и №27 без
  // названия на 22.10). Название — в ячейке даты: вторую встречу видно отличной от первой. С 24.10.2026 (дополнение
  // владелицы) название второй встречи необязательно: вторая по подтверждению отличается признаком `second_same_day`,
  // который сервер хранит у встречи, — без названия она тоже не дубль.
  const своёНазвание = m => !авто(m) && !!cleanLabel(m.label);
  const отдельная = m => !авто(m) && (!!cleanLabel(m.label) || !!m.second_same_day);
  const разобрать = (все) => {
    const живые = все.filter(m => m.status !== "cancelled");
    const наДату = {};
    живые.forEach(m => { (наДату[m.date] = наДату[m.date] || []).push(m); });
    const безНазвания = (дата) => (наДату[дата] || []).filter(m => !отдельная(m));
    return { живые, наДату, безНазвания, дубль: (дата) => безНазвания(дата).length > 1, ближайшая: ближайшаяВстреча(все, сегодня) };
  };
  const { живые, наДату, безНазвания, дубль: дубльДаты, ближайшая } = разобрать(встречи);
  // Какую из дублей на дату оставить: с планом (меньший номер), иначе меньший номер — как у папки-приёмника (О10)
  const остаётся = (дата) => { const те = безНазвания(дата).slice().sort((a, b) => a.id - b.id); return те.find(m => m.has_plan) || те[0]; };
  const предложено = предложеннаяДата(живые, сегодня);
  const карточкаHtml = (все) => {
    const р = разобрать(все), б = р.ближайшая, шаг = предложеннаяДата(р.живые, сегодня);
    return б
    ? `<div class="card prep-nearest" id="prep-nearest">
        <div class="prep-nearest-text">
          <div class="prep-nearest-title">Ближайшая встреча: ${esc(fmtRuDate(б.date))}, ${esc(деньНедели(б.date))}${своёНазвание(б) ? ` — ${esc(cleanLabel(б.label))}` : ""}</div>
          <div class="prep-nearest-sub">${б.building ? "идёт сборка · " : ""}${б.has_plan ? `план собран ${esc(fmtRuDateTime(б.plan_generated_at))}` : "плана пока нет"} · материалов ${б.materials_count || 0}${авто(б)
            ? ` · дата предложена системой${админ ? ` · <button type="button" class="link" id="prep-change-date" data-edit-date="${б.id}" data-date="${esc(б.date)}">изменить дату</button>` : ""}` : ""}${р.дубль(б.date)
            ? ` · <span class="prep-mark prep-mark-acc">${админ ? "на эту дату две встречи — сведите их в одну в таблице ниже" : "на эту дату две встречи — свести их в одну может администратор"}</span>` : ""}</div>
        </div>
        <a class="btn btn-primary" id="prep-open-plan" href="#meetings/${б.id}/planprep">Открыть план встречи</a>
      </div>`
    : `<div class="card prep-nearest" id="prep-nearest">
        <div class="prep-nearest-text">
          <div class="prep-nearest-title">Будущей встречи пока нет</div>
          <div class="prep-nearest-sub">Обычный шаг встреч — следующая ${esc(fmtRuDate(шаг))}, ${esc(деньНедели(шаг))}</div>
        </div>
        <button type="button" class="btn-primary" id="prep-create" data-date="${шаг}">Создать встречу ${esc(fmtRuDate(шаг))}</button>
      </div>`;
  };
  const карточка = карточкаHtml(встречи);
  const форма = `<button type="button" class="link" id="prep-other-date" aria-expanded="false" aria-controls="prep-new-form">Другая дата…</button>
    <form class="card prep-new" id="prep-new-form" autocomplete="off" hidden>
      <input type="date" id="prep-new-date" aria-label="Дата встречи" min="2020-01-01" max="2099-12-31">
      <input type="text" id="prep-new-label" placeholder="Название (необязательно)" aria-label="Название встречи">
      <label class="prep-second" id="prep-second-row" hidden><input type="checkbox" id="prep-second"> Вторая встреча в этот день</label>
      <button type="submit" class="btn-primary btn-sm" id="prep-new-btn">Создать встречу</button>
      <div class="prep-date-warn" id="prep-date-warn" role="status" hidden></div>
    </form>`;
  const рубеж = new Date(); рубеж.setDate(рубеж.getDate() - НЕДЕЛЬ_ДО_АРХИВА * 7);
  const рубежISO = датаISO(рубеж);
  const по_дате = встречи.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  const свежие = по_дате.filter(m => m.date >= рубежISO), архив = по_дате.filter(m => m.date < рубежISO);
  const строка = m => {
    const отменена = m.status === "cancelled";
    const будущая = m.date > сегодня;
    const двеНаДату = !отменена && (наДату[m.date] || []).length > 1;
    const дубль = двеНаДату && дубльДаты(m.date) && !отдельная(m);
    const ближняя = !!ближайшая && ближайшая.id === m.id;
    // Д9: идущая сборка видна в списке; Д14: ближайшая выделена; Д13: вторая встреча (с названием или по подтверждению) —
    // без акцента и без сводки
    const пометки = [ближняя ? '<span class="prep-mark prep-mark-acc">ближайшая</span>' : "",
      m.building && !отменена ? '<span class="prep-mark prep-mark-acc">идёт сборка</span>' : "",
      авто(m) && !отменена ? '<span class="prep-mark">дата предложена системой</span>' : "",
      дубль ? '<span class="prep-mark prep-mark-acc">две встречи на дату</span>' : двеНаДату ? '<span class="prep-mark">две встречи на дату</span>' : "",
      отменена ? '<span class="prep-mark">отменена</span>' : ""].join("");
    const план = отменена ? '<span class="prep-muted">—</span>'
      : `<a href="#meetings/${m.id}/planprep">${m.has_plan ? `план собран ${esc(fmtRuDate(String(m.plan_generated_at || "").slice(0, 10)))}` : "сформировать план"}</a>`;
    const протокол = отменена ? '<span class="prep-muted">—</span>'
      : m.has_minutes ? `<a href="#meetings/${m.id}/protocol">протокол готов</a>`
      : будущая ? '<span class="prep-muted">встреча ещё не прошла</span>'
      : `<a href="#meetings/${m.id}/protocol">${esc(m.состояние_протокола || "собрать протокол")}</a>`;
    const оставить = дубль ? остаётся(m.date) : null;
    // «Свести в одну» — администраторам (решение владелицы 21.10.2026; сервер — require_admin). «Вернуть» у отменённой
    // (Д3, 21.10.2026) убрано 23.10.2026: отмены больше нет, ошибочная сводка возвращается «Вернуть на новую дату» у
    // встречи-получателя (решение владелицы)
    const действие = !админ || отменена ? ""
      : дубль && оставить && оставить.id !== m.id
        ? `<button type="button" class="btn-sm" data-merge="${m.id}" data-keep="${оставить.id}" data-has-plan="${m.has_plan ? 1 : ""}" title="Оставить №${оставить.id}, перенести материалы из №${m.id}, опустевшую №${m.id} ${m.has_plan ? "отменить (у неё собран план)" : "удалить"}">Свести в одну</button>` : "";
    // Д8 (проходы 1 и 3): отдельной колонки «Название» нет — название в ячейке даты, ячейка переносится; кнопки не уходят
    // за правый край при ширине до 1440 px
    return `<tr data-meeting-id="${m.id}" class="${[отменена ? "prep-cancelled" : "", ближняя ? "prep-nearest-row" : ""].filter(Boolean).join(" ")}">
      <td>${esc(fmtRuDate(m.date))} <span class="prep-muted">№${m.id}</span>${своёНазвание(m) ? ` <span class="prep-label">${esc(cleanLabel(m.label))}</span>` : ""}${пометки}</td>
      <td>${план}</td><td>${протокол}</td>
      <td>${действие}</td></tr>`;
  };
  const таблица = строки => `<div class="card card-output"><div class="table-scroll"><table class="meetings-table prep-table">
      <thead><tr><th>Дата</th><th>План встречи</th><th>Протокол</th><th></th></tr></thead>
      <tbody>${строки.map(строка).join("")}</tbody></table></div></div>`;
  $b.innerHTML = `${карточка}${форма}
    ${свежие.length ? `<h2 class="feed-section">Будущие и последние встречи <span class="cnt">${свежие.length}</span> <span class="feed-h-note">за последние ${НЕДЕЛЬ_ДО_АРХИВА} ${недельВин(НЕДЕЛЬ_ДО_АРХИВА)}</span></h2>${таблица(свежие)}` : ""}
    ${архив.length ? `<details class="feed-archive"${свежие.length ? "" : " open"}><summary class="feed-section">Архив — встречи старше ${НЕДЕЛЬ_ДО_АРХИВА} ${недельРод(НЕДЕЛЬ_ДО_АРХИВА)} <span class="cnt">${архив.length}</span></summary>${таблица(архив)}</details>` : ""}
    ${создатьПроектHtml()}`;
  подключитьСозданиеПроекта();                     // «Создать проект» — в конце страницы (решение владелицы 28.10.2026)

  // --- создание: одна точка, предупреждение до отправки, ключ повтора
  const перейтиВПлан = (mid) => { location.hash = `#meetings/${mid}/planprep`; };
  const открытьЕё = async (занятая) => {
    // «Открыть её» на дату автоматической встречи снимает «дата ориентировочная» (О3): дату подтвердил человек
    if (занятая && занятая.auto) { try { await api(`/meetings/${занятая.id}/confirm-date`, { method: "POST" }); } catch (e) { /* открыть и так */ } }
    перейтиВПлан(занятая.id);
  };
  const $warn = document.getElementById("prep-date-warn");
  const показатьЗанято = (занятая) => {
    $warn.innerHTML = `На ${esc(fmtRuDate(занятая.date))} уже есть встреча${занятая.label && !занятая.auto ? ` «${esc(занятая.label)}»` : ""} — ${занятая.has_plan ? "план собран" : "плана пока нет"}${занятая.auto ? " (дата предложена системой)" : ""}. <button type="button" class="link" id="prep-open-existing">Открыть её</button>`;
    $warn.hidden = false;
    document.getElementById("prep-open-existing").addEventListener("click", () => открытьЕё(занятая));
  };
  const создать = async ({ date, label, second_same_day, кнопка }) => {
    if (кнопка.disabled) return;                  // двойной щелчок не заводит две встречи (О4)
    кнопка.disabled = true;
    try {
      const встреча = await api("/meetings", { method: "POST", json: { date, label: label || null, second_same_day: !!second_same_day,
                                                                      request_key: ключФормыВстречи() } });
      ключФормыВстречи(true);
      toast("Встреча создана");
      перейтиВПлан(встреча.id);
    } catch (e) {
      кнопка.disabled = false;                     // обрыв сети: ключ тот же — повтор вернёт ту же встречу
      if (e.data && e.data.existing) {
        const форма = document.getElementById("prep-new-form");
        if (форма.hidden) { форма.hidden = false; document.getElementById("prep-other-date").setAttribute("aria-expanded", "true"); }
        document.getElementById("prep-new-date").value = date;
        document.getElementById("prep-second-row").hidden = false;
        показатьЗанято(e.data.existing);
        обновитьКарточку();
      }
      toast(e.message, true);
    }
  };
  // Д9 (проход 3, 21.10.2026): старая вкладка после отказа «дата занята» показывала «Будущей встречи пока нет» — карточка
  // перечитывается с сервера и называет встречу, занявшую дату. Кнопка карточки — через общий обработчик: карточка новая.
  const обновитьКарточку = async () => {
    try {
      const свежие = await api("/meetings");
      document.getElementById("prep-nearest")?.replaceWith(Object.assign(document.createElement("div"), { innerHTML: карточкаHtml(свежие) }).firstElementChild);
    } catch (e) { /* без связи — карточка прежняя, предупреждение у формы уже есть */ }
  };
  $b.addEventListener("click", (ev) => {
    const к = ev.target.closest("#prep-create");
    if (к) создать({ date: к.dataset.date, кнопка: к });
  });
  document.getElementById("prep-other-date").addEventListener("click", (ev) => {
    const форма = document.getElementById("prep-new-form");
    форма.hidden = !форма.hidden;
    ev.currentTarget.setAttribute("aria-expanded", String(!форма.hidden));
    if (!форма.hidden) document.getElementById("prep-new-date").focus();
  });
  const $дата = document.getElementById("prep-new-date"), $название = document.getElementById("prep-new-label");
  const $вторая = document.getElementById("prep-second"), $кнопка = document.getElementById("prep-new-btn");
  let занята = null;
  const можноСоздать = () => {
    // дата занята — «Создать» неактивна, пока не отмечена вторая встреча (О1). Название необязательно и для второй встречи
    // (дополнение владелицы 24.10.2026, О2 изменено; было — кнопка неактивна без названия и подпись «обязательно»)
    $кнопка.disabled = !!занята && !$вторая.checked;
  };
  // Д15 (проход 3): при наборе даты с клавиатуры поле меняется на каждой цифре года («0002-10-22», «0020-…», «0202-…») —
  // проверка шла на каждую. Теперь — одна, после паузы и только по полному году.
  let _таймерПроверкиДаты = null;
  $дата.addEventListener("change", () => {
    занята = null; $warn.hidden = true; document.getElementById("prep-second-row").hidden = true; $вторая.checked = false;
    можноСоздать();
    clearTimeout(_таймерПроверкиДаты);
    if (!$дата.value || Number($дата.value.slice(0, 4)) < 2020) return;
    const проверяем = $дата.value;
    _таймерПроверкиДаты = setTimeout(async () => {
      try {
        const ответ = await api(`/meetings/date-check?date=${encodeURIComponent(проверяем)}`);
        if ($дата.value !== проверяем) return;                 // за время ответа дату сменили — ответ устарел
        if (ответ.busy && ответ.meetings.length) {
          занята = ответ.meetings[0];
          показатьЗанято(занята);
          document.getElementById("prep-second-row").hidden = false;
        }
      } catch (e) { /* проверка — подсказка; сервер всё равно откажет */ }
      можноСоздать();
    }, 400);
  });
  $вторая.addEventListener("change", () => { можноСоздать(); if ($вторая.checked) $название.focus(); });
  $название.addEventListener("input", можноСоздать);
  document.getElementById("prep-new-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!$дата.value) { toast("Укажите дату встречи", true); return; }
    создать({ date: $дата.value, label: $название.value.trim(), second_same_day: $вторая.checked, кнопка: $кнопка });
  });

  // --- «Свести в одну» (О9; решение владелицы 23.10.2026): материалы переезжают, одинаковые не задваиваются, опустевшая
  // встреча удаляется — отменённой больше не остаётся. Ошибочную сводку возвращают «Вернуть на новую дату» у получателя.
  $b.querySelectorAll("[data-merge]").forEach(btn => btn.addEventListener("click", async () => {
    const из = btn.dataset.merge, оставить = btn.dataset.keep;
    // у опустевшей с планом встречи — отмена вместо удаления (решение владелицы 23.10.2026): план сохраняется
    const судьба = btn.dataset.hasPlan ? "у неё собран план — она отменится, план сохранится, встреча уйдёт из списков" : "удалится";
    if (!(await confirmDialog(`Свести встречу №${из} в №${оставить}? Материалы перенесутся в №${оставить}, опустевшая встреча №${из} ${судьба}. Вернуть материалы можно будет на новую дату.`, "Свести в одну"))) return;
    btn.disabled = true;
    try {
      const итог = await api(`/meetings/${из}/merge`, { method: "POST", json: { to: Number(оставить) } });
      const одинаковых = итог.skipped_same ? `, одинаковых не задвоено: ${итог.skipped_same}` : "";
      toast(итог.deleted ? `Встреча №${из} сведена в №${оставить} и удалена. Перенесено материалов: ${итог.moved}${одинаковых}`
        : итог.cancelled ? `Встреча №${из} сведена в №${оставить} и отменена — план сохранён. Перенесено материалов: ${итог.moved}${одинаковых}`
        : `Материалы перенесены в №${оставить}: ${итог.moved}. ${итог.detail || ""}`, !итог.deleted && !итог.cancelled);
      render();
    } catch (e) { btn.disabled = false; toast(e.message, true); }
  }));
}
routes.prep = renderPrep;

// ---- «Система» — вкладки ------------------------------------------------------------------------------------
// Аудит 13.10.26 (владелец: «дашбордов мониторинга вообще нет»): «Прогоны», «Расход», «Состояние базы», «Диск и доступы»
// жили вторым уровнем — мелкими кнопками внутри вкладки «Параметры», и их не находили. Прежние экраны — вкладками «Системы»
// (задание, раздел 1), поэтому каждая панель прежних «Параметров системы» — своя вкладка; «Параметры» влились в «Диск и
// доступы» (там «Доступ и роли» и переключатель рабочего режима); адрес #system/params ведёт туда же.
const СИСТЕМА_ВКЛАДКИ = [
  { k: "messages", label: "Системные сообщения", href: "#system/messages", badge: "errors" },
  { k: "awaiting", label: "Ожидает ввода от оператора", href: "#system/awaiting", badge: "awaiting" },
  { k: "runs", label: "Прогоны", href: "#system/runs" },
  { k: "cost", label: "Расход", href: "#system/cost" },
  { k: "data", label: "Состояние базы", href: "#system/data" },
  { k: "static", label: "Диск и доступы", href: "#system/static" },
  // «Настройки» — вкладкой ряда, как в Планёрке (отчёт ЛМ 23.10.2026: «Параметры системы» → «Настройки» не открывалась —
  // вкладки в ряду не было, прежняя кнопка спрятана с 13.10.2026); на ней карточка «Проект системы»
  { k: "settings", label: "Настройки", href: "#system/settings" },
  { k: "decisions", label: "Реестр решений", href: "#system/decisions" },
  // MeetFlow: проектов несколько — завести, переименовать, убрать в архив (разрешённое отличие от ERP, 27.10.2026)
  { k: "projects", label: "Проекты", href: "#system/projects" },
  { k: "units", label: "Единицы встреч (тест)", href: "#units", толькоЕдиницы: true },
];
// «Мониторинг RealTime», «Модели», «База голосов» — с 14.10.26 своими пунктами слева в блоке супер-администратора (владелец:
// «для супер админа вынесено влево — мониторинг реал тайм, база голосов, технические службы, модели; всё остальное — в
// горизонтальные вкладки»), вкладками «Параметров системы» больше не показываются
const СИСТЕМА_МАРШРУТЫ = new Set(["system", "units", "awaiting"]);
// Вкладка «Системы» → кнопка прежней страницы «Параметры системы», которая открывает её панель (кнопки сами спрятаны)
const СИСТЕМА_ПАНЕЛИ = { messages: "mon-tab-errors", decisions: "mon-tab-decisions", runs: "mon-tab-runs", cost: "mon-tab-cost",
                         data: "mon-tab-data", static: "mon-tab-static", settings: "mon-tab-settings" };

// Решение владельца 14.10.26 (вариант В из трёх): все вкладки видны, при нехватке места лишние переносятся на вторую
// строку; меню «Ещё ▾» убрано (прежде, 13.10.26, — четыре частых вкладки в строке, редкие — в «Ещё ▾»). Линия ряда —
// одна, под последней строкой; активная вкладка — подчёркивание акцентом.
function системаВкладкиHtml(текущая) {
  const все = СИСТЕМА_ВКЛАДКИ.filter(t => !t.толькоЕдиницы || _unitsOn);
  const ссылка = t => `<a href="${t.href}" class="${t.k === текущая ? "on" : ""}"${t.k === текущая ? ' aria-current="page"' : ""}>${esc(t.label)}${t.badge ? `<span class="n tab-badge" data-badge="${t.badge}"></span>` : ""}</a>`;
  return `<div class="sys-head"><h1>Параметры системы</h1></div><nav class="reg-views sys-tabs" aria-label="Разделы системы">${
    все.map(ссылка).join("")}</nav>`;
}

function вставитьВкладки(текущая) {
  $main.querySelectorAll(":scope > .sys-head, :scope > .sys-tabs").forEach(el => el.remove());   // повторный вызов — не дубль
  const старый = $main.querySelector("h1");
  if (старый) старый.closest(".doc-head")?.classList.add("sys-old-head");
  if (старый) старый.hidden = true;
  $main.insertAdjacentHTML("afterbegin", системаВкладкиHtml(текущая));
  updateConflictsBadge({}, { толькоНезаполненные: true });   // повторная вставка вкладок — без нового запроса (18.10.2026)
}

function обёрнуть(маршрут, вкладка) {
  const исходная = routes[маршрут];
  routes[маршрут] = async (rest) => {
    // Вкладки — сразу, по шапке, которую прежний экран рисует до загрузки, и ещё раз после неё (если экран
    // перерисовал себя целиком): раньше вкладки появлялись через 0,7 с и экран прыгал (замер переходов 13.10.26).
    const идёт = исходная(rest);
    if (currentRouteParts()[0] === маршрут) вставитьВкладки(вкладка);
    await идёт;
    if (currentRouteParts()[0] === маршрут) вставитьВкладки(вкладка);   // ушли раньше, чем страница дорисовалась, — не вставляем в чужую
  };
}
["units"].forEach(м => обёрнуть(м, м));   // 14.10.26: live, models, voices — свои пункты слева, без вкладок

const _параметрыСистемы = routes.system;
routes.system = async (rest) => {
  let вкладка = (rest && rest[0]) || "messages";
  if (вкладка === "params") вкладка = "static";          // прежний адрес «Параметров»
  if (вкладка === "projects") { await renderProjectsAdmin(); return; }
  const адрес = location.hash;
  // Шапка «Системы» — сразу по шапке прежнего экрана, которую он рисует до загрузки; после загрузки — ещё раз
  // (раньше 0,7 с стоял заголовок «Параметры системы» с прежними кнопками, потом экран прыгал — замер 13.10.26).
  const обустроить = () => {
    const внутри = $main.querySelector(".hstack");
    if (внутри) внутри.hidden = true;                    // все прежние кнопки панелей продублированы вкладками «Системы»
    // «Видно только супер-админу…» — служебная подпись. Убираем именно её: прежде удалялась первая подпись на экране, и второй
    // проход уносил пояснение «Технические сбои…» на «Сообщениях» (аудит 13.10.26)
    [...$main.querySelectorAll(".page-sub")].filter(el => /Видно только супер-админу/.test(el.textContent)).forEach(el => el.remove());
    $main.querySelectorAll('a[href="#razbor"]').forEach(a => a.closest(".hstack")?.remove());
    вставитьВкладки(вкладка);
  };
  const идёт = _параметрыСистемы(вкладка === "awaiting" ? ["awaiting"] : []);
  обустроить();
  await идёт;
  if (location.hash !== адрес) return;                                   // ушли раньше, чем страница дорисовалась
  const кнопка = СИСТЕМА_ПАНЕЛИ[вкладка];
  if (кнопка && кнопка !== "mon-tab-runs") document.getElementById(кнопка)?.click();   // «Прогоны» открыты по умолчанию
  обустроить();
  // «Включить рабочий режим» — из боковой колонки сюда (задание, раздел 1); живёт на «Диске и доступах» рядом с «Доступом и ролями»
  if (вкладка === "static" && !$main.querySelector(".sys-mode")) {
    const режим = document.getElementById("mode-switch-testing");
    if (режим && !режим.hidden) {
      const место = document.createElement("div");
      место.className = "card card-output sys-mode";
      место.innerHTML = `<div class="reg-sub">Сейчас — тестовый режим: вход по ФИО, без пароля.</div>`;
      const кнопка = режим.cloneNode(true);
      кнопка.id = "mode-switch-testing-sys";
      кнопка.hidden = false;
      кнопка.addEventListener("click", () => режим.click());
      место.appendChild(кнопка);
      $main.appendChild(место);
    }
  }
  вставитьВкладки(вкладка);
};
routes.awaiting = () => { location.replace("#system/awaiting"); };

// Пункт меню «Система» подсвечен на всех своих вкладках (зовёт render() в app.js)
function навАктивный(маршрут) {
  if (СИСТЕМА_МАРШРУТЫ.has(маршрут)) return "system";
  const [, , вид] = currentRouteParts();
  if (маршрут === "meetings" && (вид === "protocol" || вид === "planprep")) return canPrepare() ? "prep" : "meetings";   // подготовка — у участника пункта нет
  return маршрут;
}

// Узкий экран: меню сворачивается в строку с кнопкой «Меню»
window.addEventListener("hashchange", () => document.querySelector(".app-shell")?.classList.remove("nav-open"));
document.addEventListener("DOMContentLoaded", () => {
  const кнопка = document.getElementById("nav-toggle");
  кнопка?.addEventListener("click", () => {
    const shell = document.querySelector(".app-shell");
    shell.classList.toggle("nav-open");
    кнопка.setAttribute("aria-expanded", shell.classList.contains("nav-open") ? "true" : "false");
  });
});

// «Модели» — единственное место, где показаны модели (оформление «Линия»; решение владельца 13.10.26 убрать дубль с «Диска и
// доступов»). Модель Карты и Сводки в ролях не назначается — она задаётся отдельно; прежде её было видно только в разделе
// «Модели и пределы» на «Диске и доступах», теперь — здесь, отдельной строкой под ролями.
const _моделиСистемы = routes.models;
routes.models = async (rest) => {
  await _моделиСистемы(rest);
  if (currentRouteParts()[0] !== "models" || $main.querySelector(".mr-roadmap")) return;
  let ml = null;
  try { ml = (await api("/project-status/monitoring", { вне_показа: true })).models_limits; } catch (e) { return; }
  if (!ml || currentRouteParts()[0] !== "models") return;
  const куда = [...$main.querySelectorAll("h3")].find(h => /Список подключений/.test(h.textContent));
  const блок = `<div class="card card-output mon-section mr-roadmap"><h3>Карта и Сводка</h3>
    <div class="mon-note">Карта и Сводка: <b>${esc(ml.roadmap || "модель черновика")}</b>. Отдельной роли нет: без переменной
    QWEN_ROADMAP_MODEL — модель черновика; переменная меняется при перезапуске.</div></div>`;
  if (куда) куда.insertAdjacentHTML("beforebegin", блок);      // перед «Списком подключений», после ролей
  else $main.insertAdjacentHTML("beforeend", блок);
};

// Перерисовки мимо render() держат прокрутку на месте (18.10.26, `сПрокруткойНаМесте`): список встреч, «Подготовка».
renderProtocols = сПрокруткойНаМесте(renderProtocols);
renderPrep = сПрокруткойНаМесте(renderPrep);


// «Параметры системы» → «Проекты» (MeetFlow, 27.10.2026). В ERP проект один и задаётся на «Настройках»; в MeetFlow их
// несколько — это одно из двух разрешённых отличий. Папка-приёмник у каждого проекта своя: задаётся на «Мониторинге
// RealTime», когда проект выбран вверху левой панели.
async function renderProjectsAdmin() {
  // Справочник проектов и подпроектов (ЛМ 6c6933f, возвращён 27.10.2026): проект, под ним подпроекты; у подпроекта —
  // надпроект. Варианты написания, архив и возврат. Выбор проекта вверху левой панели показывает проект с подпроектами.
  $main.innerHTML = системаВкладкиHtml("projects") + `<div class="page-sub">Проекты и подпроекты компании. Новый проект сразу
    появляется в выборе вверху левой панели; проект показывается вместе со своими подпроектами. Подпроект — проект с
    надпроектом. Проект в архиве из выбора убирается, его встречи и задачи сохраняются.</div>
    <div class="card"><form id="prj-new" class="hstack" style="flex-wrap:wrap; gap:8px">
      <input id="prj-new-name" placeholder="Название проекта или подпроекта" maxlength="200" style="min-width:240px">
      <input id="prj-new-aliases" placeholder="Варианты написания через «;»" maxlength="2000" style="min-width:240px">
      <label>Надпроект <select id="prj-new-parent"><option value="">— проект верхнего уровня —</option></select></label>
      <button class="btn-sm btn-primary" type="submit">Завести</button></form></div>
    <div id="prj-list" class="card empty-state">Загрузка…</div>`;
  const список = document.getElementById("prj-list");
  const варианты = (rows, свой, выбран) => '<option value="">— нет (проект верхнего уровня) —</option>' + rows
    .filter(x => !x.archived && x.id !== свой && !(x.label || "").startsWith((rows.find(r => r.id === свой) || {}).label + " – "))
    .map(x => `<option value="${x.id}"${x.id === выбран ? " selected" : ""}>${esc(x.label || x.name)}</option>`).join("");
  const нарисовать = async () => {
    let rows;
    try { rows = await api("/projects-list/all"); } catch (err) { список.textContent = "Не удалось загрузить: " + err.message; return; }
    список.classList.remove("empty-state");
    document.getElementById("prj-new-parent").innerHTML = варианты(rows, null, null).replace("— нет (проект верхнего уровня) —", "— проект верхнего уровня —");
    список.innerHTML = `<table class="tbl"><thead><tr><th>Проект</th><th>Надпроект</th><th>Варианты написания</th><th>Встреч</th>
      <th>Активных задач</th><th>Папка-приёмник</th><th></th></tr></thead><tbody>${rows.map(p => `<tr data-id="${p.id}">
      <td style="padding-left:${8 + 18 * (p.level || 0)}px">${p.level ? "– " : ""}<input class="prj-name" value="${esc(p.name)}" maxlength="200"${p.archived ? " disabled" : ""}>${p.archived ? ' <span class="page-sub">в архиве</span>' : ""}</td>
      <td><select class="prj-parent"${p.archived ? " disabled" : ""}>${варианты(rows, p.id, p.parent_id)}</select></td>
      <td><input class="prj-aliases" value="${esc((p.aliases || []).join("; "))}" maxlength="2000"${p.archived ? " disabled" : ""}></td>
      <td>${p.meetings}</td><td>${p.active_tasks}</td><td>${p.watch_folder ? esc(p.watch_folder) : "не задана"}</td>
      <td class="hstack">${p.archived ? `<button class="btn-sm prj-restore">Вернуть из архива</button>`
        : `<button class="btn-sm prj-save">Сохранить</button><button class="btn-sm prj-archive">В архив</button>`}</td></tr>`).join("")}</tbody></table>`;
    список.querySelectorAll("tr[data-id]").forEach(tr => {
      const id = tr.dataset.id;
      const изменить = async (тело, текст) => {
        try { await api(`/projects-list/${id}`, { method: "PATCH", json: тело }); toast(текст); await загрузитьПроекты(); await нарисовать(); }
        catch (err) { toast(err.message, true); }
      };
      tr.querySelector(".prj-save")?.addEventListener("click", () => изменить(
        { name: tr.querySelector(".prj-name").value, aliases: tr.querySelector(".prj-aliases").value,
          parent_id: Number(tr.querySelector(".prj-parent").value) || null }, "Проект сохранён"));
      tr.querySelector(".prj-archive")?.addEventListener("click", () => {
        if (confirm("Убрать в архив? Встречи и задачи сохранятся, папка-приёмник выключится.")) изменить({ archived: true }, "Проект в архиве");
      });
      tr.querySelector(".prj-restore")?.addEventListener("click", () => изменить({ archived: false }, "Проект возвращён"));
    });
  };
  document.getElementById("prj-new").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/projects-list", { method: "POST", json: { name: document.getElementById("prj-new-name").value,
        aliases: document.getElementById("prj-new-aliases").value,
        parent_id: Number(document.getElementById("prj-new-parent").value) || null } });
      toast("Заведено");
      document.getElementById("prj-new-name").value = ""; document.getElementById("prj-new-aliases").value = "";
      await загрузитьПроекты(); await нарисовать();
    } catch (err) { toast(err.message, true); }
  });
  await нарисовать();
}
