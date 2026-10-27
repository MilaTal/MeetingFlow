// Реестр задач — вариант В прототипа 1 (выбор владельца 13.10.26; стенд 8020, пункты 4.2, 5, 6, 6.1 задания).
// Готовые виды со счётчиками; одна строка поиска с чипами; фильтр по колонке — щелчком по её заголовку; поиск — только по
// задачам (сервер, GET /tasks/search), по умолчанию активные, закрытые — словами «закрытые задачи»; найденное, чипы и вид
// сохраняются в браузере пользователя до «Сбросить». Строка задачи ведёт на встречу; действия — в меню «⋯».
// Подключается после app.js и заменяет прежнюю страницу реестра (routes.dashboard).

const РЕЕСТР_КЛЮЧ = "erp-registry-search";
const РЕЕСТР_ВИДЫ = [["all", "Все в работе"], ["over", "Просроченные"], ["nodue", "Без срока"], ["mine", "Мои"]];
// «Под вопросом» — задачи, в которых усомнился код. С 20.10.2026 (решение владелицы, как в Планёрке; переворачивает 17.10.2026
// «не в счёте «В работе»»): в реестре они в «Все в работе» обычными строками с пометкой «под вопросом», у администратора в
// строке — «Подтвердить» и «Снять»; для разбора — страница «Под вопросом» в блоке администратора левого меню (#pod) с числом.
// Вида «Под вопросом» в реестре нет; на «Экране встречи» таких задач нет. Остальным ролям сервер такие задачи по-прежнему не
// отдаёт (решения 15.10 и 17.10.2026). Не подтверждена за срок (7 дней, «Мониторинг» → «Настройки») — снимается сама.
// Участнику и директору `source_anchor` не отдаётся (цитаты — служебные, 16.10.26): у них задачу узнают по `under_question_label`,
// которую сервер с 20.10.2026 отдаёт всем ролям
const задачаПодВопросом = (t) => !!(t && t.status === "active" && (ПОМЕТКИ_ВОПРОСА.includes(t.source_anchor) || t.under_question_label));
// «Завершённые» — не вкладка, а тихая ссылка у правого края строки видов (согласовано с «Мониторингом» 13.10.26):
// значок архива 15 px, 13 px, #71717a, без числа; на узком экране — только значок. Вид "closed", прежний адрес #dashboard/done
// и поиск «закрытые задачи» работают как раньше; над списком — строка «Завершённые · ← к задачам в работе».
const РЕЕСТР_ЗАКРЫТЫЕ = "Завершённые";   // только выполненные: снятые не показываются нигде (решение владелицы 26.10.2026)
const РЕЕСТР_АРХИВ_ЗНАЧОК = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/></svg>';
const РЕЕСТР_ПОДСКАЗКА = "Ищет по формулировке, исполнителю, проекту и комментарию. Ищет только задачи в работе. Для завершённых допишите «закрытые задачи». Фильтр по колонке — " +
  "щелчок по её заголовку. Найденное остаётся и после перехода на другие страницы — до «Сбросить».";

function реестрПрочитать() {
  try {
    const s = JSON.parse(localStorage.getItem(РЕЕСТР_КЛЮЧ) || "null");
    if (s && typeof s === "object") return { view: s.view || "all", q: s.q || "", chips: Array.isArray(s.chips) ? s.chips : [] };
  } catch (e) { /* хранилище недоступно — состояние по умолчанию */ }
  return { view: "all", q: "", chips: [] };
}

function реестрСохранить(s) {
  try { localStorage.setItem(РЕЕСТР_КЛЮЧ, JSON.stringify({ view: s.view, q: s.q, chips: s.chips })); } catch (e) { /* без сохранения */ }
}

function реестрСегодня() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function реестрОтветственный(t) {
  return t.responsible_text || (t.responsible_user_id && человекКоманды(t.responsible_user_id)?.full_name) || "";
}

// Отбор «Ответственный» (дефект от владелицы 20.10.2026, как в Планёрке): в списке все, на ком есть задачи в текущем виде,
// по частям через «/»; задачи без исполнителя — вариантом «Не назначен» (раньше их в списке не было вовсе); запись
// «Команды» «не подтверждён» — с той же пометкой, что на экране «Команды». Значение чипа — само имя, как в колонке.
const РЕЕСТР_НЕ_НАЗНАЧЕН = "Не назначен";
function реестрИсполнителиОтбора(t) {
  const части = реестрЧасти(реестрОтветственный(t));
  return части.length ? части : [РЕЕСТР_НЕ_НАЗНАЧЕН];
}
function реестрВариантыИсполнителей(задачи) {
  const н = (x) => String(x || "").trim().toLowerCase().replace(/ё/g, "е");
  const неПодтв = new Set();
  for (const t of задачи) {
    const части = реестрИсполнителиОтбора(t);
    const кто = t.responsible_user_id ? человекКоманды(t.responsible_user_id) : null;
    for (const v of части) {
      const человек = кто && (части.length === 1 || н(кто.full_name) === н(v)) ? кто : всяКоманда.find(u => н(u.full_name) === н(v));
      if (человек && человек.is_confirmed === false) неПодтв.add(v);
    }
  }
  return [...new Set(задачи.flatMap(реестрИсполнителиОтбора))]
    .sort((a, b) => (a === РЕЕСТР_НЕ_НАЗНАЧЕН) - (b === РЕЕСТР_НЕ_НАЗНАЧЕН) || a.localeCompare(b, "ru"))
    .map(v => ({ v, не_подтверждён: неПодтв.has(v) }));
}

function реестрПросрочена(t) {
  return t.status === "active" && t.due_date && String(t.due_date).slice(0, 10) < реестрСегодня();
}

function реестрМоя(t) {
  // Ответ «Мониторинга» 13.10.26: по связи с учётной записью или по фамилии в тексте ответственного; «не назначен» — не мои
  if (!me) return false;
  if (!t.responsible_user_id && !(t.responsible_text || "").trim()) return false;
  if (t.responsible_user_id === me.id) return true;
  const ф = (me.full_name || "").split(/\s+/)[0];
  return !!ф && (t.responsible_text || "").includes(ф);
}

// ДД.ММ.ГГГГ → ГГГГ-ММ-ДД (или "" — не дата)
function реестрДата(s) {
  const m = String(s || "").trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  return m ? `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` : "";
}

// Владелец 15.10.26: «если в колонке несколько перечисленных через / слов — ФИО или названий, — при фильтре выбирать, если
// поиск идёт по любому из них». «Барч/Быстрова/Минеев» — это три значения: в списке фильтра каждое отдельно, задача
// подходит, если выбранное — любое из них.
function реестрЧасти(v) {
  return String(v || "").split("/").map(x => x.trim()).filter(Boolean);
}

// Проект и подпроект задачи (MeetFlow, справочник проектов 27.10.2026): «Проект – Подпроект» или «Проект». Приставка
// формулировки — как приставка «Проект: » ERP (её ставит извлечение по темам), только из полей задачи, на экране.
function реестрМеткаПроекта(t) {
  if (!t.project_root) return "";
  return t.subproject ? `${t.project_root} – ${t.subproject}` : t.project_root;
}
function реестрПриставка(t) {
  const метка = выбранныйПроект() ? (t.subproject ? реестрМеткаПроекта(t) : "") : реестрМеткаПроекта(t);
  if (!метка) return "";
  const нр = s => String(s || "").toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ").trim();
  const текст = нр(t.description);
  if (текст.startsWith(нр(метка) + ":") || текст.startsWith(нр(t.subproject || t.project_root) + ":")) return "";
  return `${метка}: `;
}
// Пункты отбора проекта над реестром: при выбранном проекте — «Весь проект X», подпроекты, «без подпроекта» (вид ERP
// `фильтрПроектаHtml`); при «Все проекты» — проекты и подпроекты подписью «Проект – Подпроект»
function реестрПунктыПроекта() {
  const id = выбранныйПроект();
  const все = Array.isArray(_проекты) ? _проекты : [];
  if (!id) return [{ v: "", l: "Все проекты" }, ...все.map(п => ({ v: п.label || п.name, l: п.label || п.name }))];
  const п = все.find(x => x.id === id);
  if (!п) return [];
  const своя = п.label || п.name;
  const подпроекты = все.filter(x => (x.label || "").startsWith(своя + " – ") && x.id !== id);
  if (!подпроекты.length) return [];
  return [{ v: "", l: `Весь проект ${своя}` }, ...подпроекты.map(x => ({ v: x.label, l: x.label.slice(своя.length + 3) })),
    { v: "__none__", l: "без подпроекта" }];
}

function реестрПрименитьЧипы(list, chips) {
  const нр = s => String(s || "").toLowerCase().replace(/ё/g, "е");
  return chips.reduce((acc, c) => acc.filter(t => {
    if (c.k === "who") return реестрИсполнителиОтбора(t).includes(c.v);
    if (c.k === "meet") return String(t.source_meeting_id) === String(c.v);
    if (c.k === "proj") {
      if (c.v === "__none__") return t.project_id === выбранныйПроект();
      const метка = реестрМеткаПроекта(t);
      return c.v === "" ? !t.subproject : (метка === c.v || метка.startsWith(c.v + " – "));
    }
    if (c.k === "text") return нр(t.description).includes(нр(c.v));
    if (c.k === "comment") return нр(t.last_comment).includes(нр(c.v));
    if (c.k === "due") {
      if (c.v === "просрочено") return реестрПросрочена(t);
      if (c.v === "без срока") return !taskDueText(t);
      const d = String(t.due_date || "").slice(0, 10);
      return !!d && (!c.from || d >= c.from) && (!c.to || d <= c.to);
    }
    if (c.k === "set") {
      const d = String(t.date_set || "").slice(0, 10);
      return !!d && (!c.from || d >= c.from) && (!c.to || d <= c.to);
    }
    if (c.k === "closed") {               // «Закрыта с — по» в «Завершённых» (21.10.2026: прежде меню не открывалось)
      const d = String(t.date_closed || "").slice(0, 10);
      return !!d && (!c.from || d >= c.from) && (!c.to || d <= c.to);
    }
    return true;
  }), list);
}

function реестрПрименитьВид(list, view) {
  if (view === "closed") return list.filter(t => t.status !== "active");
  if (view === "pod") return list.filter(задачаПодВопросом);         // страница «Под вопросом» (#pod)
  const активные = list.filter(t => t.status === "active");          // с задачами «под вопросом» — с пометкой (20.10.2026)
  if (view === "over") return активные.filter(реестрПросрочена);
  if (view === "nodue") return активные.filter(t => !taskDueText(t));
  if (view === "mine") return активные.filter(реестрМоя);
  return активные;
}

// Найденное поиском: с 20.10.2026 задачи «под вопросом» и так в видах реестра (с пометкой) — правило то же, что у видов.
// Сервер отдаёт такие задачи только администратору.
function реестрНайденныеВВиде(list, view) {
  return реестрПрименитьВид(list, view);
}

function реестрСтрокаНаВстречу(t) {
  if (!t.source_meeting_id || !t.source_meeting_date) return "";
  return ` · <a href="#meetings/${t.source_meeting_id}?from=reg" class="reg-meet">встреча ${esc(fmtRuDate(t.source_meeting_date))} · протокол</a>`;
}

// Последний комментарий — «дд.мм.гггг · текст», без вводного слова (владелец 13.10.26); в ячейке «Комментарии», как на 8000
function реестрКомментарий(t) {
  if (!t.last_comment) return "";
  const дата = t.last_comment_date ? `${fmtRuDate(t.last_comment_date)} · ` : "";
  return `<div class="task-note-text" title="${esc(t.last_comment)}">${esc(дата)}${esc(t.last_comment)}</div>`;
}

// «Итог» закрытой задачи (решение владельца 13.10.26) — «выполнена»: снятые не показываются нигде (решение владелицы
// 26.10.2026, переворачивает «выполнена или снята»), сервер их не отдаёт
function реестрИтог(t) {
  return t.status === "done" ? "выполнена" : "";
}

// Описание и под ним «поставлена дд.мм.гггг» — разметка 8000 (taskDescHtml). Ссылка на встречу и проект — та же подпись: на 8000
// их нет, на стенде строка ведёт на встречу (задание стенда, п. 4.2) — убрать значило бы потерять переход (вопрос владельцу).
function реестрОписание(t, closed) {
  const части = [];
  if (t.date_set) части.push(`поставлена ${esc(fmtRuDate(t.date_set))}`);
  // проект и подпроект — приставкой «Проект – Подпроект:» перед формулировкой (MeetFlow, 27.10.2026), не подписью
  const встреча = реестрСтрокаНаВстречу(t);
  const под = части.join(" · ") + встреча;
  // у закрытых колонки «Комментарии» нет (решение 13.10.26) — последний комментарий не теряется: служебной строкой под задачей
  const коммент = closed && t.last_comment
    ? `<span class="doc-cell-sub">${t.last_comment_date ? esc(fmtRuDate(t.last_comment_date)) + " · " : ""}${esc(t.last_comment)}</span>` : "";
  // задача под вопросом — точкой сразу за текстом (15.10.26), а не словами в подписи
  // «оперативная» — пометка человеком одним нажатием, подсказка — ссылкой в подписи (решение владелицы 26.10.2026,
  // operativnaya.js — близнец Планёрки); менять пометку может тот, кто правит задачи (в ERP — администратор)
  const можно = isAdmin() && !closed;
  const ссылка = оперативнаяСсылка(t, можно);
  const приставка = реестрПриставка(t);
  return `${приставка ? `<span class="task-project-prefix">${esc(приставка)}</span>` : ""}${esc(t.description)}${точкаВопроса(t)}${оперативнаяМетка(t, можно)}${под || ссылка ? ` <span class="doc-cell-sub">${под ? под + ссылка : ссылка.replace(/^ · /, "")}</span>` : ""}${коммент ? ` ${коммент}` : ""}`;
}

// Строка реестра в работе — 1 в 1 со строкой старого реестра рабочей ERP (renderTaskTable, порт 8000): № | Описание (ниже
// «поставлена дд.мм.гггг») | Ответственный | Срок | Комментарии (последний и «Актуализировать» таблеткой) | карандаш | галочка
// (квадраты 30×30). Колонки «Статус на дату» нет (владелец 13.10.26: «задача в реестре активных — значит в работе»);
// просрочка — служебной строкой под сроком.
// Колонки действий реестра — как в ERP (18.10.26): эта строка — образец для Планёрки (замечание владелицы 18.10.2026, повторное:
// в Планёрке пропали ✎ ✓ 🗑). «Актуализировать» · ✎ (.task-edit-desc) · ✓ (.task-done в .task-done-cell) · 🗑 (.task-delete);
// сторож — tests/test_kolonki_deystviy_reestra_1810.py, маркеры — scripts/proverka_zerkalnosti_pravok.py.
// Кнопки «Подтвердить» / «Снять» (19.10.2026, перенос из Планёрки 18.10): администратору, с отменой за 2 с, как у ✓. С 20.10.2026
// (решение владелицы) — в любой строке задачи «под вопросом»: в «Все в работе», в найденном поиском и на странице «Под вопросом».
// Тот же смысл, что ответ на карточку (POST /tasks/{id}/under-question). После действия вид реестра остаётся (`реестрОставитьВид`).
// С 25.10.2026 (решение владелицы, «Разбор» — одна вкладка) задача под вопросом решается в одном месте — «Разборе»: в строке
// реестра вместо кнопок — ссылка «решить в «Разборе»» (перевёрнуто 25.10.2026, как в Планёрке).
let реестрОставитьВид = null;
function кнопкиПодВопросомHtml(t) {
  return `<span class="pod-acts"><a class="pod-razbor" href="#razbor/tasks" data-task="${t.id}" title="Подтвердить или снять — в «Разборе», вид «Задачи»">решить в «Разборе»</a></span>`;
}

function реестрСтрока(t, i, closed, вид) {
  const due = taskDueText(t);
  const данные = `data-task-id="${t.id}" data-proj-id="${t.project_id || ""}" data-desc="${esc(t.description)}" data-resp="${esc(реестрОтветственный(t))}" data-status="${esc(t.status)}" data-due="${t.due_date ? esc(String(t.due_date).slice(0, 10).split("-").reverse().join(".")) : ""}"`;
  // Срок переходящей задачи — как у секретаря (решение владелицы 24.10.2026, как Планёрка): текущий срок, под ним тихо —
  // «перенесено с дд.мм.гггг» (первоначальный); все переносы — в истории задачи
  const перенесено = t.due_original && t.due_original !== t.due_date
    ? ` <span class="doc-cell-sub" title="Первоначальный срок задачи; переносы — в истории задачи">перенесено с ${esc(fmtRuDate(t.due_original))}</span>` : "";
  const срок = `${due ? esc(due) : '<span class="page-sub">—</span>'}${реестрПросрочена(t) ? ' <span class="doc-cell-sub reg-over">просрочена</span>' : ""}${перенесено}`;
  const подсказка = t.due_phrase ? "как прозвучало: " + t.due_phrase : (t.status_detail || "");
  if (closed) {
    return `
    <tr ${данные}>
      <td class="task-num-cell"><span class="task-num">${i + 1}</span></td>
      <td class="task-desc-cell">${реестрОписание(t, true)}</td>
      <td class="task-resp-cell" data-label="Ответственный">${taskResponsibleHtml(t)}</td>
      <td class="task-due-cell" data-label="Срок">${due ? esc(due) : '<span class="page-sub">—</span>'}</td>
      <td class="task-due-cell task-closed-cell" data-label="Закрыта">${esc(fmtRuDate(t.date_closed))}</td>
      <td class="task-result-cell" data-label="Итог">${реестрИтог(t)}</td>
      ${isAdmin() ? `<td class="task-act-cell"><button class="btn-sm task-revert" data-id="${t.id}" title="Вернуть задачу в работу">Вернуть</button><button class="btn-icon task-delete" data-id="${t.id}" title="Удалить задачу насовсем" aria-label="Удалить задачу насовсем">&#128465;</button></td>` : ""}
    </tr>`;
  }
  return `
    <tr ${данные}>
      <td class="task-num-cell"><span class="task-num">${i + 1}</span></td>
      <td class="task-desc-cell">${реестрОписание(t, false)}</td>
      <td class="task-resp-cell" data-label="Ответственный">${taskResponsibleHtml(t)}</td>
      <td class="task-due-cell" data-label="Срок"${подсказка ? ` title="${esc(подсказка)}"` : ""}>${срок}</td>
      <td class="task-note-cell" data-label="Комментарии">
        ${реестрКомментарий(t)}
        ${canActualize(t) ? `<button class="btn-sm task-note" data-id="${t.id}">Актуализировать</button>` : ""}
        ${isAdmin() && задачаПодВопросом(t) ? кнопкиПодВопросомHtml(t) : ""}
      </td>
      ${isAdmin() ? `<td class="task-act-cell"><div class="task-actions">
        <button class="btn-icon task-edit-desc" data-id="${t.id}" title="Изменить задачу" aria-label="Изменить задачу">&#9998;</button>
      </div></td>
      <td class="task-act-cell task-done-cell">
        <button class="btn-icon task-done" data-id="${t.id}" title="Выполнено" aria-label="Выполнено">&#10003;</button>
        <button class="btn-icon task-delete" data-id="${t.id}" title="Удалить задачу насовсем" aria-label="Удалить задачу насовсем">&#128465;</button>
      </td>` : ""}
    </tr>`;
}

// Меню отбора по колонке реестра — общее для реестра, «Под вопросом» и «Экрана встречи» (правка владелицы 20.10.2026: на Экране
// отбор по колонкам, как в реестре). `база` — задачи, из которых берутся значения; `поставитьЧипы(чипы)` — ставит плашки (каждая
// заменяет прежнюю того же рода) и перерисовывает; `снять(ключи)` — снимает плашки колонки (пункт «Все — снять отбор»).
// Дефект владелицы 21.10.2026 (на «Экране планёрки», правило 13.10 — системы одинаковы): пункта возврата в меню не было, меню жило
// в шапке и на Экране обрезалось рамкой доски при одной строке (130 px из 461), фокус уходил на первую кнопку. Теперь меню — в body
// (position: fixed), место и высота по окну (`местоМенюКолонки`), первым пунктом «Все — снять отбор»; фокус получает только поле
// ввода, без прокрутки рамок. Колонка «Закрыта» в «Завершённых» прежде меню не открывала (ключа `closed` не было).
const КЛЮЧИ_КОЛОНОК_РЕЕСТРА = { text: ["text", "set"], who: ["who"], proj: ["proj"], due: ["due"], comment: ["comment"], closed: ["closed"] };
let _менюКолонки = null;
function закрытьМенюКолонки() {
  if (!_менюКолонки) return;
  _менюКолонки._кнопка?.setAttribute("aria-expanded", "false");
  _менюКолонки.remove();
  _менюКолонки = null;
}
// Где поставить меню: кнопка — прямоугольник заголовка, размер — меню без ограничений, окно — {w, h}. Под заголовком, если
// меню там помещается или внизу места не меньше, чем вверху; иначе над ним. Высота — до края окна с полем 8 px.
function местоМенюКолонки(кнопка, размер, окно, справа) {
  const поле = 8, зазор = 4;
  const ниже = окно.h - кнопка.bottom - зазор - поле, выше = кнопка.top - зазор - поле;
  const вверх = !(ниже >= размер.h || ниже >= выше);
  const maxHeight = Math.max(120, Math.floor(вверх ? выше : ниже));
  const высота = Math.min(размер.h, maxHeight);
  const top = вверх ? Math.max(поле, кнопка.top - зазор - высота) : кнопка.bottom + зазор;
  const left = Math.min(Math.max(поле, справа ? кнопка.right - размер.w : кнопка.left), окно.w - размер.w - поле);
  return { top: Math.round(top), left: Math.round(Math.max(поле, left)), maxHeight, вверх };
}
function открытьФильтрКолонки(кнопка, k, база, поставитьЧипыСнаружи, снятьСнаружи = null) {
  const тоЖе = _менюКолонки && _менюКолонки._кнопка === кнопка;
  закрытьМенюКолонки();
  if (тоЖе) return;                                          // повторный щелчок по тому же заголовку — закрыть
  const поставитьЧипы = (чипы) => { закрытьМенюКолонки(); поставитьЧипыСнаружи(чипы); };
  const снять = (ключи) => { закрытьМенюКолонки(); if (снятьСнаружи) снятьСнаружи(ключи); };
  const диапазон = (подпись) => `<label>${подпись} с<input type="text" id="reg-f-from" placeholder="ДД.ММ.ГГГГ"></label><label>по<input type="text" id="reg-f-to" placeholder="ДД.ММ.ГГГГ"></label>`;
  const box = document.createElement("div");
  box.className = "reg-filter col-menu";
  box.setAttribute("role", "menu");
  if (k === "who") {
    // все исполнители вида, «не подтверждён» с пометкой, «Не назначен» последним (`реестрВариантыИсполнителей`, 20.10.2026)
    const люди = реестрВариантыИсполнителей(база);
    box.innerHTML = люди.map(o => `<button type="button" data-v="${esc(o.v)}">${esc(o.v)}${o.не_подтверждён ? ' <span class="badge badge-neutral" title="Запись «Команды» не подтверждена">Не подтверждён</span>' : ""}</button>`).join("") || "<span class=\"reg-sub\">ответственных нет</span>";
    box.querySelectorAll("button").forEach(b => b.addEventListener("click", () => поставитьЧипы([{ k: "who", v: b.dataset.v, label: `Ответственный: ${b.dataset.v}` }])));
  } else if (k === "proj") {
    const проекты = [...new Set(база.flatMap(t => реестрЧасти(t.project_name)))].sort((a, b) => a.localeCompare(b, "ru"));
    box.innerHTML = проекты.map(v => `<button type="button" data-v="${esc(v)}">${esc(v)}</button>`).join("") +
      `<button type="button" data-v="">без проекта</button>`;
    box.querySelectorAll("button").forEach(b => b.addEventListener("click", () =>
      поставитьЧипы([{ k: "proj", v: b.dataset.v, label: `Проект: ${b.dataset.v || "не указан"}` }])));
  } else if (k === "text" || k === "comment") {
    box.innerHTML = `<label>${k === "text" ? "Формулировка содержит" : "Комментарий содержит"}<input type="text" id="reg-f-text"></label>
      ${k === "text" ? диапазон("Поставлена") : ""}
      <button type="button" class="btn-sm" id="reg-f-ok">Применить</button>`;
    box.querySelector("#reg-f-ok").addEventListener("click", () => {
      const v = box.querySelector("#reg-f-text").value.trim();
      const чипы = [];
      if (v) чипы.push({ k, v, label: `${k === "text" ? "Содержит" : "Комментарий"}: ${v}` });
      if (k === "text") {
        const from = реестрДата(box.querySelector("#reg-f-from").value), to = реестрДата(box.querySelector("#reg-f-to").value);
        if (from || to) чипы.push({ k: "set", from, to,
          label: `Поставлена ${from ? "с " + fmtRuDate(from) : ""} ${to ? "по " + fmtRuDate(to) : ""}`.replace(/\s+/g, " ").trim() });
      }
      if (чипы.length) поставитьЧипы(чипы);
    });
  } else if (k === "due") {
    box.innerHTML = `<button type="button" data-v="просрочено">просрочено</button><button type="button" data-v="без срока">без срока</button>
      ${диапазон("Срок")}
      <button type="button" class="btn-sm" id="reg-f-ok">Применить</button>`;
    box.querySelectorAll("button[data-v]").forEach(b => b.addEventListener("click", () => поставитьЧипы([{ k: "due", v: b.dataset.v, label: `Срок: ${b.dataset.v}` }])));
    box.querySelector("#reg-f-ok").addEventListener("click", () => {
      const from = реестрДата(box.querySelector("#reg-f-from").value), to = реестрДата(box.querySelector("#reg-f-to").value);
      if (from || to) поставитьЧипы([{ k: "due", v: "range", from, to,
        label: `Срок ${from ? "с " + fmtRuDate(from) : ""} ${to ? "по " + fmtRuDate(to) : ""}`.replace(/\s+/g, " ").trim() }]);
    });
  } else if (k === "closed") {
    box.innerHTML = `${диапазон("Закрыта")}<button type="button" class="btn-sm" id="reg-f-ok">Применить</button>`;
    box.querySelector("#reg-f-ok").addEventListener("click", () => {
      const from = реестрДата(box.querySelector("#reg-f-from").value), to = реестрДата(box.querySelector("#reg-f-to").value);
      if (from || to) поставитьЧипы([{ k: "closed", v: "range", from, to,
        label: `Закрыта ${from ? "с " + fmtRuDate(from) : ""} ${to ? "по " + fmtRuDate(to) : ""}`.replace(/\s+/g, " ").trim() }]);
    });
  } else {
    return;
  }
  box.insertAdjacentHTML("afterbegin", `<button type="button" class="col-menu-all" data-col-all>Все — снять отбор</button>`);
  box.querySelector("[data-col-all]").addEventListener("click", () => снять(КЛЮЧИ_КОЛОНОК_РЕЕСТРА[k] || [k]));
  box._кнопка = кнопка;
  document.body.appendChild(box);
  const справа = k === "due" || k === "comment" || k === "closed";
  box._поставить = () => {
    box.style.maxHeight = "";
    const м = местоМенюКолонки(кнопка.getBoundingClientRect(), { w: box.offsetWidth, h: box.scrollHeight },
      { w: window.innerWidth, h: window.innerHeight }, справа);
    Object.assign(box.style, { top: м.top + "px", left: м.left + "px", maxHeight: м.maxHeight + "px" });
  };
  box._поставить();
  кнопка.setAttribute("aria-expanded", "true");
  box.querySelector("#reg-f-text")?.focus({ preventScroll: true });     // только поле «содержит», как в Планёрке
  _менюКолонки = box;
}
// Плашки выбранного отбора — одна разметка на все таблицы ERP; «×» снимает свою плашку. `сброс` — «Сбросить» в конце строки
// плашек (страница «Под вопросом»: другого «Сбросить» там нет; 21.10.2026).
function плашкиОтбораHtml(чипы, сброс = false) {
  return чипы.map((c, i) => `<button type="button" class="chip" data-rm="${i}" aria-label="Снять фильтр ${esc(c.label)}">${esc(c.label)} <span aria-hidden="true">×</span></button>`).join("")
    + (сброс && чипы.length ? `<button type="button" class="link search-reset-link" data-chips-reset>Сбросить</button>` : "");
}
// Меню колонки закрывается щелчком мимо него и мимо заголовков, Esc (фокус — обратно на заголовок), сменой экрана (hashchange).
// Прокрутка страницы или рамки и смена размера окна переставляют меню к заголовку; заголовок ушёл из окна или исчез — закрывается.
function переставитьМенюКолонки() {
  const кнопка = _менюКолонки?._кнопка;
  if (!кнопка) return;
  const р = кнопка.isConnected ? кнопка.getBoundingClientRect() : null;
  if (!р || р.bottom < 0 || р.top > window.innerHeight || (!р.width && !р.height)) { закрытьМенюКолонки(); return; }
  _менюКолонки._поставить();
}
document.addEventListener("click", (e) => {
  if (!_менюКолонки || _менюКолонки.contains(e.target) || e.target.closest(".reg-col")) return;
  закрытьМенюКолонки();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !_менюКолонки) return;
  const кнопка = _менюКолонки._кнопка;
  закрытьМенюКолонки();
  кнопка?.focus({ preventScroll: true });
});
document.addEventListener("scroll", (e) => { if (_менюКолонки && !_менюКолонки.contains(e.target)) переставитьМенюКолонки(); }, true);
window.addEventListener("resize", переставитьМенюКолонки);
window.addEventListener("hashchange", закрытьМенюКолонки);


// «Под вопросом» — отдельная страница блока администратора (решение владелицы 20.10.2026, как в Планёрке): тот же список,
// строки, ✎ ✓ 🗑 и «Подтвердить» / «Снять», что были во вкладке реестра (19.10.2026), — код реестра в режиме страницы
// (`опции.страница === "pod"`): без поиска и видов, с отбором по колонкам; состояние не пишется в память реестра.
// Отбор страницы «Под вопросом» — вне перерисовки (21.10.2026: после «Подтвердить» / «Снять» отбор терялся); в память реестра не пишется
const ОТБОР_POD = { chips: [] };
async function renderPodVoprosom() {
  return renderRegistry({ страница: "pod" });
}

async function renderRegistry(опции = {}) {
  await обновитьОтметкуВопроса();
  const страница = !!(опции && опции.страница === "pod");
  // отбор страницы «Под вопросом» живёт в `ОТБОР_POD` и переживает перерисовку («Подтвердить» / «Снять»; 21.10.2026)
  const s = страница ? { view: "pod", q: "", chips: ОТБОР_POD.chips } : реестрПрочитать();
  // При входе на страницу — всегда «Все в работе», только активные задачи (владелец 13.10.26 в Планёрке, 3eb12b8; правило
  // одинакового вида обеих систем). Прежде восстанавливался последний вид; внутри страницы виды переключаются как раньше,
  // найденное словами остаётся до «Сбросить».
  // Перерисовка того же экрана после действия (`_тотЖеЭкран`, app.js) держит вид — замер на стенде 25.10.2026 до правки:
  // «Мои» (7 строк) после «Сохранить» в «Актуализировать» становился «Все в работе» (22), как и в Планёрке.
  s.view = страница ? "pod" : (реестрОставитьВид || (_тотЖеЭкран ? s.view : "all"));
  реестрОставитьВид = null;
  if (!страница && currentRouteParts()[1] === "done") { s.view = "closed"; }       // прежний адрес #dashboard/done
  // прежний адрес вкладки «Под вопросом» «#dashboard/pod» ведёт на страницу «#pod» (render, 20.10.2026)
  const фокус = Number(new URLSearchParams((location.hash.split("?")[1] || "")).get("task")) || null;
  // Строки-заголовка нет; экран и так назван пунктом меню (владелец 13.10.26 в Планёрке, c066c81). С 20.10.2026 (решение
  // владелицы, по образцу «Экрана встречи», одинаково с Планёркой): поиск — главным, первым на плашке, во всю свободную длину и
  // крупнее (`.live-views .scr-search`); за ним «Сбросить» и «Искать везде»; виды — выпадающим списком (`.live-view-select`);
  // «i» и «Завершённые» — справа; «Например: …» — строкой ниже; плашки отбора — отдельной строкой (прежде — в поле).
  $main.innerHTML = страница ? `<div class="feed-head"><div class="feed-head-text"><h1>Под вопросом</h1>
      <div class="feed-sub">Задачи, в которых усомнился код. Они уже в реестре и стоят в «Все в работе» с пометкой «под вопросом».
        «Подтвердить» — задача остаётся в работе без пометки; «Снять» — задача снимается. Без решения за тот же срок, что у нерешённых карточек «Конфликтов», снимается сама.</div></div></div>
    <div class="live-chips" id="reg-chips" hidden></div>
    <div id="reg-list" class="card card-output reg-card"><div class="empty-state">Загрузка…</div></div>` : `<div class="reg-top reg-top-poisk">
    <div class="live-views reg-live-views" aria-label="Актуализировать задачи из реестра">
      <div class="reg-search scr-search"><input type="search" id="reg-q" placeholder="Поиск: слова задачи, фамилия или проект" value="${esc(s.q)}" autocomplete="off" aria-label="Поиск по реестру задач"></div>
      <button type="button" class="link search-reset-link" id="reg-reset">Сбросить</button>
      ${/* «Искать везде» — полнотекстовый поиск по тому же запросу в окне справа (решение владелицы 17.10.2026) */ ""}
      ${кнопкаИскатьВездеHtml()}
      <select class="live-view-select" id="reg-view" aria-label="Вид списка задач"></select>
      <select class="live-view-select" id="reg-proj" aria-label="Проект и подпроект" hidden></select>
      <span class="tip"><button type="button" class="tip-ico" aria-label="Как искать">i</button><span class="tip-body" role="tooltip">${esc(РЕЕСТР_ПОДСКАЗКА)} ${esc(ПОДСКАЗКА_МАРКЕРОВ)}</span></span>
      <button type="button" class="reg-archive" id="reg-archive" aria-label="${РЕЕСТР_ЗАКРЫТЫЕ} задачи" title="${РЕЕСТР_ЗАКРЫТЫЕ} задачи">${РЕЕСТР_АРХИВ_ЗНАЧОК}<span class="reg-archive-t">${РЕЕСТР_ЗАКРЫТЫЕ}</span></button>
    </div></div>
    ${рядПримеровHtml("reg-examples")}
    <div class="live-chips" id="reg-chips" hidden></div>
    <div id="reg-markers"></div>
    <div class="reg-closed-head" id="reg-closed-head" hidden><b>${РЕЕСТР_ЗАКРЫТЫЕ}</b> · <button type="button" class="link" id="reg-back">← к задачам в работе</button></div>
    <div id="reg-list" class="card card-output reg-card"><div class="empty-state">Загрузка…</div></div>`;

  let активные = [], закрытые = null, найдено = null;
  let маркеры = null;      // плашки «Искали: …» последнего поиска (решение владелицы 17.10.2026)
  // Архив — порциями по 50, новые сверху по дате закрытия (скорость страниц, решение владелицы 18.10.2026): прежде
  // «Завершённые» грузили все закрытые разом. Дальше — кнопкой «Показать ещё»; число — отдельным COUNT.
  // Найти закрытую задачу можно и поиском — он серверный (`/tasks/search` со словами «закрытые задачи»).
  let курсорАрхива = null, всегоЗакрытых = 0;
  const загрузитьЗакрытые = async () => {
    if (закрытые) return закрытые;
    const [порция, число] = await Promise.all([api("/tasks/closed"), api("/tasks/closed/count")]);
    закрытые = порция.items || [];
    курсорАрхива = порция.next_cursor || null;
    всегоЗакрытых = число.count || 0;
    return закрытые;
  };
  const загрузитьЕщёЗакрытые = async () => {
    if (!курсорАрхива) return;
    const порция = await api(`/tasks/closed?cursor=${encodeURIComponent(курсорАрхива)}`);
    закрытые = закрытые.concat(порция.items || []);
    курсорАрхива = порция.next_cursor || null;
  };
  [активные] = await Promise.all([api("/tasks?status=active"), примерыМаркеров()]);   // примеры маркеров — сразу (17.10.2026)

  const искать = async () => {
    if (!s.q.trim()) { найдено = null; маркеры = null; return; }
    const слова = s.view === "closed" && !/закрыт[а-яё]*\s+задач/i.test(s.q) ? `${s.q} закрытые задачи` : s.q;
    try {
      const r = await api(`/tasks/search?q=${encodeURIComponent(слова)}`);
      найдено = r.needs_detail ? [] : (r.tasks || []);
      найдено.нужноУточнить = !!r.needs_detail || !!r.problem;
      найдено.проблема = r.problem || "";
      маркеры = r.markers || null;
      // «закрытые задачи» словами в поле (п. 6) — показываем закрытые: в виде «Все в работе» вид их отбрасывал, и запрос
      // «НЭР закрытые задачи» давал «задач нет», хотя сервер нашёл (проверка поля проекта на стенде 13.10.26)
      if (r.closed_included && s.view !== "closed") s.view = "closed";
    } catch (e) { найдено = []; маркеры = null; toast(e.message, true); }
  };

  const показать = async () => {
    if (s.view === "mine" && !me) s.view = "all";              // пользователь не выбран — вида «Мои» нет
    if (s.view === "pod" && !isAdmin()) s.view = "all";        // «Под вопросом» — только администратору
    if (!страница) реестрСохранить(s); else ОТБОР_POD.chips = s.chips;
    закрытьМенюКолонки();
    const база = найдено ? найдено : (s.view === "closed" ? await загрузитьЗакрытые() : активные);
    const closed = s.view === "closed";
    let list = найдено ? реестрНайденныеВВиде(база, s.view) : реестрПрименитьВид(база, s.view);
    list = реестрПрименитьЧипы(list, s.chips);
    // счётчики видов — по активным с учётом чипов, без поиска (вид — готовый срез реестра)
    const счёт = v => реестрПрименитьЧипы(реестрПрименитьВид(активные, v), s.chips).length;
    // Число у пункта меню «Под вопросом» — из этого же списка, без запроса (как у «Конфликтов», 20.10.2026)
    if (isAdmin()) updateConflictsBadge({ pod: реестрПрименитьВид(активные, "pod").length });
    if (!страница) {
    // Виды — выпадающим списком (решение владелицы 20.10.2026, как на «Экране встречи»): по умолчанию «Все в работе · N»;
    // «Под вопросом» в списке нет (решение владелицы 20.10.2026): они в «Все в работе» с пометкой, разбор — пунктом меню;
    // открытые «Завершённые» — пунктом списка, вход в них — значком справа, как прежде.
    document.getElementById("reg-view").innerHTML = РЕЕСТР_ВИДЫ.filter(([k]) => k !== "mine" || me).map(([k, l]) =>
      `<option value="${k}"${s.view === k ? " selected" : ""}>${l} · ${счёт(k)}</option>`).join("")   // и у «Мои» — число, как в Планёрке (25.10.2026)
      + (closed ? `<option value="closed" selected>${РЕЕСТР_ЗАКРЫТЫЕ}</option>` : "");
    показатьПлашкиМаркеров(document.getElementById("reg-markers"), маркеры, async (qq) => {
      s.q = qq; document.getElementById("reg-q").value = qq; await искать(); показать();
    });
    document.getElementById("reg-archive").hidden = closed;
    document.getElementById("reg-closed-head").hidden = !closed;
    }
    document.getElementById("reg-chips").hidden = !s.chips.length;
    document.getElementById("reg-chips").innerHTML = плашкиОтбораHtml(s.chips, страница);
    const $list = document.getElementById("reg-list");
    // Пустые колонки, у которых во всех строках одно значение, не показываются (задание, п. 5)
    // «Проект» — только когда он есть хотя бы у одной показанной задачи (решение владельца 13.10.26: у задач ERP проект почти
    // не звучит — замер 1 из 151, — и пустая колонка не должна занимать место)
    // Заголовок колонки — щелчком открывает фильтр по ней (вариант В, задание стенда п. 6); кнопка в заголовке выглядит как
    // текст заголовка 8000
    const шапка = (k, title, cls, подсказка = "") => `<th class="${cls}"${подсказка ? ` title="${подсказка}"` : ""}><button type="button" class="reg-col" data-col="${k}" aria-haspopup="true" aria-expanded="false">${title}</button></th>`;
    const админ = isAdmin();
    // Закрытые — одна таблица (решение владельца 13.10.26): № | Задача | Ответственный | Срок | Закрыта | Итог, по дате закрытия,
    // новые сверху; шапка серая. Активные — колонки старого реестра 8000 без «Статуса на дату».
    const заголовокТаблицы = closed
      ? `<thead><tr><th class="task-num-cell" title="Номер по порядку в этой таблице">№</th>${шапка("text", "Задача", "task-desc-cell")}${шапка("who", "Ответственный", "task-resp-cell")}<th class="task-due-cell" title="Срок выполнения">Срок</th>${шапка("closed", "Закрыта", "task-due-cell task-closed-cell", "Дата закрытия или снятия")}<th class="task-result-cell">Итог</th>${админ ? '<th class="task-act-cell"></th>' : ""}</tr></thead>`
      : `<thead><tr><th class="task-num-cell" title="Номер по порядку в этой таблице">№</th>${шапка("text", "Описание", "task-desc-cell")}${шапка("who", "Ответственный", "task-resp-cell")}${шапка("due", "Срок", "task-due-cell", "Срок выполнения")}${шапка("comment", "Комментарии", "task-note-cell", "Комментарии и выполнение: последняя отметка и кнопка «Актуализировать»")}${админ ? '<th class="task-act-cell"></th><th class="task-act-cell"></th>' : ""}</tr></thead>`;
    if (!list.length) {
      const почему = найдено && найдено.нужноУточнить ? (найдено.проблема || "Уточните запрос: в нём нет слов для поиска.")
        : (s.q || s.chips.length ? "По запросу задач нет." : closed ? "Завершённых задач нет." : страница ? "Задач под вопросом нет." : "Задач в этом виде нет.");
      const пусто = `<div class="empty-state reg-empty"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path class="acc" d="M9 14l2 2 4-4"/></svg><div class="reg-empty-title">${esc(почему)}</div></div>`;
      // При отборе по колонкам шапка остаётся и в пустом списке — меню колонки снова открывается, «Все — снять отбор» под рукой
      // (21.10.2026, как в Планёрке: прежде пустой результат убирал таблицу вместе с заголовками — замер: меню «Срок» не открыть)
      $list.innerHTML = s.chips.length
        ? `<div class="table-scroll"><table class="task-table reg-old${closed ? " reg-closed" : ""}">${заголовокТаблицы}<tbody><tr><td colspan="8">${пусто}</td></tr></tbody></table></div>`
        : пусто;
    } else {
      $list.innerHTML = `<div class="table-scroll"><table class="task-table reg-old${closed ? " reg-closed" : ""}">
        ${заголовокТаблицы}
        <tbody>${list.map((t, i) => реестрСтрока(t, i, closed, closed ? undefined : s.view)).join("")}</tbody></table></div>`;
      if (closed && !найдено && курсорАрхива) {
        $list.insertAdjacentHTML("beforeend", `<div class="reg-sub reg-archive-more">Показано ${закрытые.length} из ${всегоЗакрытых} ·
          <button type="button" class="link" id="reg-archive-more">Показать ещё</button></div>`);
        document.getElementById("reg-archive-more").addEventListener("click", async () => {
          try { await загрузитьЕщёЗакрытые(); } catch (e) { toast(e.message, true); }
          показать();
        });
      }
      // 7 строк — решение владельца 09.10.26. Страница «Под вопросом» — ровно 7, а не по месту, и свой ключ раскрытости
      // (решение владелицы 20.10.2026, п. 2: строка с «Подтвердить» и «Снять» высокая, по месту выходило 5)
      if (!фокус) collapseLongTable($list.querySelector("tbody"), ПРЕДЕЛ_РЕЕСТРА, страница ? "pod-tasks" : "reg-tasks", 0, страница ? false : null);
      wireTaskActions();
      привязатьСтроки($list);
      if (фокус) {
        const row = $list.querySelector(`tr[data-task-id="${фокус}"]`);
        if (row) { row.classList.add("reg-focus"); row.scrollIntoView({ block: "center" }); }
      }
    }
    if (!страница) {
    {
      const пункты = реестрПунктыПроекта();
      const $p = document.getElementById("reg-proj");
      const чип = s.chips.find(c => c.k === "proj");
      $p.hidden = !пункты.length;
      $p.innerHTML = пункты.map(o => `<option value="${esc(o.v)}"${(чип ? чип.v : "") === o.v ? " selected" : ""}>${esc(o.l)}</option>`).join("");
      $p.onchange = (e) => {
        const v = e.target.value;
        const о = пункты.find(x => x.v === v);
        s.chips = s.chips.filter(c => c.k !== "proj").concat(v ? [{ k: "proj", v, label: `Проект: ${о ? о.l : v}` }] : []);
        показать();
      };
    }
    document.getElementById("reg-view").onchange = async (e) => {
      s.view = e.target.value;
      if (s.q) await искать();
      показать();
    };
    document.getElementById("reg-archive").onclick = async () => { s.view = "closed"; if (s.q) await искать(); показать(); };
    document.getElementById("reg-back").onclick = async () => {
      // слова «закрытые задачи» в поле снова включили бы закрытый вид — при возврате к задачам в работе они снимаются
      s.q = s.q.replace(/закрыт[а-яё]*\s+задач[а-яё]*/gi, "").replace(/\s+/g, " ").trim();
      document.getElementById("reg-q").value = s.q;
      s.view = "all"; await искать(); показать();
    };
    }
    document.querySelectorAll("#reg-chips [data-rm]").forEach(b => b.addEventListener("click", () => { s.chips.splice(+b.dataset.rm, 1); показать(); }));
    document.querySelector("#reg-chips [data-chips-reset]")?.addEventListener("click", () => { s.chips = []; показать(); });
    document.querySelectorAll(".reg-col").forEach(b => b.addEventListener("click", ev => { ev.stopPropagation(); открытьФильтр(b, b.dataset.col); }));
  };

  // Меню отбора по колонке — общее с «Экраном встречи» (`открытьФильтрКолонки`, 20.10.2026)
  const поставитьЧипы = (чипы) => { for (const чип of чипы) s.chips = s.chips.filter(c => c.k !== чип.k).concat(чип); показать(); };
  const снятьЧипы = (ключи) => { s.chips = s.chips.filter(c => !ключи.includes(c.k)); показать(); };
  // на странице «Под вопросом» значения меню — из её задач (20.10.2026)
  const открытьФильтр = (кнопка, k) => открытьФильтрКолонки(кнопка, k, s.view === "closed" ? (закрытые || [])
    : страница ? реестрПрименитьВид(активные, "pod") : активные, поставитьЧипы, снятьЧипы);

  function привязатьСтроки($list) {
    $list.querySelectorAll(".reg-more").forEach(b => b.addEventListener("click", ev => {
      ev.stopPropagation();
      const menu = b.nextElementSibling;
      const открыто = !menu.hidden;
      document.querySelectorAll(".reg-menu").forEach(m => { m.hidden = true; });
      menu.hidden = открыто;
      if (!menu.hidden) {
        const закрыть = e => { if (!menu.contains(e.target)) { menu.hidden = true; document.removeEventListener("click", закрыть); } };
        setTimeout(() => document.addEventListener("click", закрыть), 0);
      }
    }));
    $list.querySelectorAll(".reg-menu button").forEach(b => b.addEventListener("click", () => { b.closest(".reg-menu").hidden = true; }));
    // «Подтвердить» / «Снять» во вкладке «Под вопросом» (19.10.26, как в Планёрке) — с отсчётом и «Отменить», как у галочки
    $list.querySelectorAll(".task-pod").forEach(b => b.addEventListener("click", () => {
      const подтвердить = b.dataset.pod === "confirm";
      startUndoCountdown({
        anchor: b,
        text: (n) => `${подтвердить ? "Подтверждено" : "Снято"} через ${n}с`,
        onCommit: async () => {
          try {
            await api(`/tasks/${b.dataset.id}/under-question`, { method: "POST", json: { action: b.dataset.pod } });
            toast(подтвердить ? "Задача подтверждена — она в работе" : "Задача снята");
            if (!подтвердить || страница) await погаситьСтроку(b);     // подтверждённая в «Все в работе» остаётся строкой, без пометки
            реестрОставитьВид = страница ? null : s.view;
            updateConflictsBadge();                                  // свежее число у пункта меню «Под вопросом»
            render();
          } catch (e) { toast(e.message, true); }
        },
      });
    }));
    // «Выполнено» (галочка) — отсчёт с «Отменить» общим механизмом 8000: wireTaskActions → wireTaskDoneCell
    $list.querySelectorAll(".task-revert").forEach(b => b.addEventListener("click", async () => {
      try { await api(`/tasks/${b.dataset.id}/revert`, { method: "POST" }); toast("Задача возвращена в работу"); await погаситьСтроку(b); render(); }
      catch (e) { toast(e.message, true); }
    }));
    // «Удалить насовсем» (владелец 15.10.26 через Планёрку bb3e9de): только админу, после подтверждения; снять задачу можно и
    // без удаления — она останется в «Завершённых»
    $list.querySelectorAll(".task-delete").forEach(b => b.addEventListener("click", async () => {
      const описание = (b.closest("tr")?.querySelector(".task-desc-cell")?.innerText || "").split("\n")[0].slice(0, 200);
      // Решение владельца 17.10.26 (С6 сведения): только с явным подтверждением в окне, текст — владельца
      if (!(await confirmDialog(`«${описание}»

Удаление необратимо — задача и её история будут удалены. Удалить?`, "Удалить насовсем"))) return;
      try { await api(`/tasks/${b.dataset.id}`, { method: "DELETE" }); toast("Задача удалена"); await погаситьСтроку(b); render(); }
      catch (e) { toast(e.message, true); }
    }));
  }

  if (страница) { await показать(); return; }
  const $q = document.getElementById("reg-q");
  let таймер = null;
  $q.addEventListener("input", () => {
    clearTimeout(таймер);
    таймер = setTimeout(async () => { s.q = $q.value; await искать(); показать(); }, 400);
  });
  $q.addEventListener("keydown", async ev => {
    if (ev.key === "Enter") { clearTimeout(таймер); s.q = $q.value; await искать(); показать(); }
  });
  // «Искать везде» и кнопки-примеры маркеров (решение владелицы 17.10.2026, одинаково с Планёркой)
  подключитьПоискВезде({ поле: $q, ряд: document.getElementById("reg-examples"),
    кнопка: document.querySelector(".reg-top [data-search-everywhere]"),
    искать: async () => { clearTimeout(таймер); s.q = $q.value; await искать(); показать(); } });
  document.getElementById("reg-reset").addEventListener("click", async () => {
    s.q = ""; s.chips = []; s.view = "all"; найдено = null; маркеры = null; $q.value = "";
    if (location.hash !== "#dashboard") history.replaceState(null, "", "#dashboard");
    показать();
  });
  if (s.q) await искать();
  await показать();
}

// Фильтр «Все задачи встречи в реестре» со страницы встречи: чип «Встреча: ДД.ММ.ГГГГ».
function реестрПоВстрече(meetingId, dateIso) {
  const s = реестрПрочитать();
  s.chips = s.chips.filter(c => c.k !== "meet").concat({ k: "meet", v: String(meetingId), label: `Встреча: ${fmtRuDate(dateIso)}` });
  реестрСохранить(s);
  location.hash = "#dashboard";
}

routes.dashboard = renderRegistry;
routes.pod = () => renderPodVoprosom();      // «Под вопросом» — пункт блока администратора (решение владелицы 20.10.2026)

// Перерисовки мимо render() держат прокрутку на месте (18.10.26, `сПрокруткойНаМесте`): реестр задач.
renderRegistry = сПрокруткойНаМесте(renderRegistry);
