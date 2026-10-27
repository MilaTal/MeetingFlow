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

async function renderMeetingReader(id) {
  const откуда = new URLSearchParams(location.hash.split("?")[1] || "").get("from");
  const [встреча, протокол, встречи, задачи] = await Promise.all([
    // задачи своей встречи, а не весь реестр (скорость страниц, 18.10.2026)
    api(`/meetings/${id}`), api(`/meetings/${id}/minutes`), api("/meetings"), api(`/tasks?meeting_id=${id}`),
  ]);
  // Встреча без протокола (предстоящая): прежняя страница встречи показывала её План — показываем его же (аудит 13.10.26:
  // страница была пустой, План был доступен только с подготовки, участнику — никак)
  const планЭтой = протокол.available ? null : await api(`/meetings/${id}/plan`).catch(() => null);
  // «План следующей» — без отменённых встреч (21.10.2026, О9)
  const следующая = встречи.filter(m => m.status !== "cancelled" && m.date > встреча.date).sort((a, b) => a.date.localeCompare(b.date))[0] || null;
  const мои = задачи.filter(t => t.source_meeting_id === Number(id));
  // Договорённости встречи — всем ролям (решение владелицы 20.10.2026, п. 3); в режиме «в тени» сервер не-администратору
  // отдаёт пустой список с `mode: "shadow"` — тогда кнопки нет, как прежде
  const ответДоговорённостей = протокол.available
    ? await api(`/agreements?meeting_id=${id}`).catch(() => ({ items: [], mode: "shadow" })) : null;
  const договорённости = ответДоговорённостей && (isAdmin() || ответДоговорённостей.mode === "on")
    ? (ответДоговорённостей.items || []) : null;
  const сведения = встречи.find(m => m.id === Number(id)) || встреча;
  const состояние = сведения.building ? "идёт сборка" : сведения.draft_pending ? "черновик ждёт решения"
    : протокол.available ? "протокол готов" : (сведения.состояние_протокола || "протокола нет");
  const назад = откуда === "reg" ? `<a href="#dashboard" class="mt-back">← Реестр</a>` : `<a href="#meetings" class="mt-back">← Встречи по проекту</a>`;
  const кнопка = (k, знак, текст, n) => `<button type="button" class="mt-btn" data-drawer="${k}" aria-expanded="false">${знак}${esc(текст)}${n !== undefined ? ` <span class="n">${n}</span>` : ""}</button>`;
  const естьПлан = !!(планЭтой && планЭтой.available);
  const заголовок = протокол.available ? `Протокол встречи ${fmtRuDate(встреча.date)}`
    : естьПлан ? `План встречи ${fmtRuDate(встреча.date)}` : `Встреча ${fmtRuDate(встреча.date)}`;
  // Состояние уже стоит меткой в строке инструментов — под заголовком его не повторяем (аудит 13.10.26: было дважды)
  const подпись = протокол.available
    ? `собран ${esc(fmtRuDateTime(протокол.generated_at))}${сведения.draft_pending ? " · есть черновик новой сборки — решение в подготовке встречи" : ""}${протокол.build_note ? ` · ${esc(протокол.build_note)}` : ""}`
    : сведения.draft_pending ? "Это черновик — решение по нему принимается в подготовке встречи"
    : естьПлан && планЭтой.generated_at ? `план собран ${esc(fmtRuDateTime(планЭтой.generated_at))} · протокола пока нет` : "";
  // Встреча без протокола: материалы к её Плану может добавить любой (так было на прежней странице встречи; сервер разрешает
  // всем ролям) — ссылка видна всем (второй проход аудита 13.10.26: у участника пути к этому не было)
  // Строка состояния над документом («собран …», «черновик…», метка состояния) — только администратору (правило владельца
  // 13.10.26 «документы чистые»; образец — Планёрка 848effe): рабочей группе документ начинается с заголовка и текста.
  const админ = isAdmin();
  const подписьВидна = админ ? подпись : "";
  // Будущая встреча (ещё не прошла): пути протокола нет — ни «подготовки протокола», ни «создать протокол» (решение владелицы
  // 21.10.2026, О7); вместо него — «Встреча ещё не прошла. После неё — протокол.»
  const д = new Date();
  const сегодня = `${д.getFullYear()}-${String(д.getMonth() + 1).padStart(2, "0")}-${String(д.getDate()).padStart(2, "0")}`;
  const будущая = String(встреча.date).slice(0, 10) > сегодня;
  // Д1 (проход 4, 21.10.2026): у прошедшей встречи «Материалы к плану — добавить файл» открывал план ЭТОЙ встречи, и файл
  // уходил в план прошедшей, а не ближайшей. У прошедшей ссылка ведёт к плану ближайшей встречи (сегодняшняя — ещё не прошла).
  const прошла = String(встреча.date).slice(0, 10) < сегодня;
  const ближайшая = прошла ? ближайшаяВстреча(встречи, сегодня) : null;
  const кБлижайшей = ближайшая ? `<a href="#meetings/${ближайшая.id}/planprep">материалы к плану ближайшей встречи ${esc(fmtRuDate(ближайшая.date))}</a>` : "";
  // Строка под заголовком — частями через « · » (21.10.2026: «подготовка встречи» и «материалы к плану» склеивались в
  // «подготовка встречиматериалы к плану», когда строки состояния не было)
  const частиПодписи = [подписьВидна,
    сведения.status === "cancelled" ? "встреча отменена" : "",
    !протокол.available && будущая ? "Встреча ещё не прошла. После неё — протокол." : "",
    canPrepare() && !будущая && (сведения.draft_pending || !протокол.available) ? `<a href="#meetings/${id}/protocol">подготовка встречи</a>` : "",
    !протокол.available && сведения.status !== "cancelled"
      ? (прошла ? кБлижайшей
        : canPrepare() ? `<a href="#meetings/${id}/planprep">план встречи</a>` : `<a href="#meetings/${id}/planprep">материалы к плану</a>`) : ""];
  const строкаПодписи = частиПодписи.filter(Boolean).join(" · ");
  // Правка на полотне (решение владелицы 24.10.2026): «Правка» — переключатель «Просмотр / Правка» здесь же, на странице
  // встречи (прежде — ссылка в подготовку, к панели «Точечная правка»). Протокол, а без протокола — план; не в архиве.
  const рубежАрхива = new Date();
  рубежАрхива.setDate(рубежАрхива.getDate() - ARCHIVE_CUTOFF_DAYS);
  const основаПолотна = протокол.available ? `/meetings/${id}/minutes` : естьПлан ? `/meetings/${id}/plan` : "";
  const правкаДоступна = админ && !!основаПолотна && new Date(встреча.date) >= рубежАрхива;
  const режимПолотна = правкаДоступна ? полотноРежим(основаПолотна) : "view";
  $main.innerHTML = `
    <div class="mt-bar">
      ${назад}
      ${админ ? `<span class="mt-state${сведения.draft_pending ? " mt-state-acc" : ""}">${esc(состояние)}</span>` : ""}
    </div>
    <div class="mt-layout doc-with-notes">
      <article class="mt-doc">
        <div class="mt-title-row"><h1 class="mt-title">${esc(заголовок)}</h1>
          <span class="mt-acts">
            ${кнопка("tasks", ВСТРЕЧА_ЗНАКИ.tasks, "Задачи встречи", мои.length)}
            ${договорённости ? кнопка("agreements", ВСТРЕЧА_ЗНАКИ.agreements, "Договорённости встречи", договорённости.length) : ""}
            ${кнопка("plan", ВСТРЕЧА_ЗНАКИ.plan, "План следующей")}
            ${/* «Скачать .docx» и «Правка» — в ряду кнопок, а не в «⋯» (п. 1 замечаний владелицы 21.10.2026); в «⋯» — редкое */ ""}
            ${протокол.available ? `<a class="mt-btn" id="reader-docx" href="/meetings/${id}/minutes/export" target="_blank">${ВСТРЕЧА_ЗНАКИ.docx}Скачать .docx</a>`
              : естьПлан ? `<a class="mt-btn" id="reader-docx" href="/meetings/${id}/plan/export" target="_blank">${ВСТРЕЧА_ЗНАКИ.docx}Скачать .docx</a>` : ""}
            ${/* «Сформировать протокол по вложенным материалам» (дефект Планёрки 22.10.2026, у нас так же): автосборка не прошла —
                  протокола нет, сборка не идёт, черновик не ждёт решения, встреча прошла и не отменена. В ряду кнопок (21.10.2026) */ ""}
            ${!протокол.available && canPrepare() && !будущая && сведения.status !== "cancelled" && !сведения.building && !сведения.draft_pending
              ? `<button type="button" class="mt-btn" id="reader-build" title="Платно, по источникам встречи — спросит подтверждение">${ВСТРЕЧА_ЗНАКИ.notes}Сформировать протокол по вложенным материалам</button>` : ""}
            ${правкаДоступна ? полотноПереключатель(основаПолотна, режимПолотна, "reader-edit") : ""}
            <button type="button" class="mt-btn" data-drawer="more" aria-label="Ещё" aria-expanded="false">⋯</button>
          </span></div>
        ${строкаПодписи ? `<div class="mt-sub">${строкаПодписи}</div>` : ""}
        ${протокол.available ? `<div class="mt-text doc-render doc-content" id="mt-doc-text">${renderDocHtml(протокол.content_md)}</div>`
          : естьПлан ? `<div class="mt-text doc-render doc-content" id="mt-doc-text">${renderDocHtml(планЭтой.content_md)}</div>` : ""}
        ${/* Список под документом убран (19.10.2026, Е12 списка отставания; в Планёрке — 16.10.26 «не нужен»): задачи встречи —
              в самом протоколе одной таблицей и в панели «Задачи встречи» */ ""}
        ${/* «Проверить после сохранения» (линия локальной машины, 15.10.26; сведение 18.10.26) — служебный блок под документом,
              только администраторам; правка текста — в «Подготовке встречи» */ ""}
        ${админ && протокол.available ? `<div id="post-save-check" hidden></div>` : ""}
      </article>
      <aside class="mt-drawer" id="mt-drawer" hidden aria-label="Панель встречи"></aside>
    </div>`;

  const $d = document.getElementById("mt-drawer");
  const открыть = async (k, кнопка) => {
    document.querySelectorAll(".mt-btn[data-drawer]").forEach(b => b.setAttribute("aria-expanded", "false"));
    if ($d.dataset.k === k && !$d.hidden) { $d.hidden = true; $d.dataset.k = ""; return; }
    $d.dataset.k = k;
    кнопка.setAttribute("aria-expanded", "true");
    let тело = "";
    if (k === "tasks") {
      тело = `<h2>Задачи встречи ${esc(fmtRuDate(встреча.date))}</h2>${мои.length ? `<div data-list="meeting-tasks" data-list-item=".tl-item">${мои.map((t, i) =>
        пунктЗадачи(t, i, "открыть в реестре")).join("")}</div>`
        + `<button type="button" class="link" id="mt-all-tasks">Все задачи встречи в реестре</button>` : '<div class="reg-sub">Задач с этой встречи нет.</div>'}`;
    } else if (k === "agreements") {
      тело = панельДоговорённостейВстречи(договорённости || [], fmtRuDate(встреча.date));
    } else if (k === "plan") {
      if (!следующая) тело = `<h2>План следующей встречи</h2><div class="reg-sub">Следующая встреча ещё не заведена.</div>`;
      else {
        const план = await api(`/meetings/${следующая.id}/plan`);
        // Д14 (проход 4, 21.10.2026): ссылка на встречу — сверху, под заголовком (была только внизу длинной панели)
        тело = `<h2>План встречи ${esc(fmtRuDate(следующая.date))}</h2>
          <a class="mt-plan-link" href="#meetings/${следующая.id}">встреча ${esc(fmtRuDate(следующая.date))}</a>${план.available
          ? `<div class="doc-render mt-plan doc-content">${renderDocHtml(план.content_md)}</div>` : `<div class="reg-sub">${esc(план.message || "Плана пока нет")}</div>`}`;
      }
    } else if (k === "more") {
      // «Говорящий N» — номер голоса в записи, не человек: не показываем (задание, раздел 6; аудит 13.10.26)
      const вёлТекст = сведения.leader_user_id ? (allUsers.find(u => u.id === сведения.leader_user_id)?.full_name || "") : (сведения.leader_speaker || "");
      const вёл = /^говорящий\s*\d*$/i.test(вёлТекст.trim()) ? "" : вёлТекст;
      const документ = протокол.available ? протокол : естьПлан ? планЭтой : null;
      const источники = (документ && документ.sources || []).map(s => `«${esc(s.original_filename)}»`).join(", ");
      // «Скачать .docx» и «Правка» — кнопками в ряду (21.10.2026); здесь — редкое: переходы в подготовку и справка
      тело = `<h2>Ещё</h2>
        ${canPrepare() && !будущая ? `<a href="#meetings/${id}/protocol">Сборка протокола — в подготовке встречи</a>` : ""}
        ${!прошла ? `<a href="#meetings/${id}/planprep">${canPrepare() ? "План этой встречи — подготовка" : "Материалы к плану — добавить файл"}</a>`
          : ближайшая ? `<a href="#meetings/${ближайшая.id}/planprep">Материалы к плану ближайшей встречи ${esc(fmtRuDate(ближайшая.date))} — добавить файл</a>`
          : canPrepare() ? `<a href="#prep">Ближайшая встреча не заведена — «Подготовка встречи»</a>` : ""}
        ${вёл ? `<div class="reg-sub">Вёл встречу: ${esc(вёл)}</div>` : ""}
        ${isAdmin() && документ && документ.generated_at ? `<div class="reg-sub">Собран ${esc(fmtRuDateTime(документ.generated_at))}${источники ? ` · источники: ${источники}` : ""}</div>` : ""}`;
    }
    // «Свернуть» — в шапке панели справа от заголовка, акцентом системы (правка владелицы 20.10.2026, как в Планёрке): заголовок
    // панели переносится в шапку, шапка прилипает к верху — кнопка на виду и при прокрутке длинного списка.
    $d.innerHTML = `<div class="mt-drawer-head"><button type="button" class="mt-close" id="mt-close" aria-expanded="true" aria-controls="mt-drawer" title="Свернуть панель (Esc)">Свернуть ▾</button></div>${тело}`;
    const заголовокПанели = $d.querySelector(":scope > h2");
    if (заголовокПанели) $d.querySelector(".mt-drawer-head").prepend(заголовокПанели);
    $d.hidden = false;
    // Панель задач лежит поверх документа — но под строкой заголовка с кнопками, иначе их не нажать (замер 13.10.26 при 1280:
    // панель закрывала «Задачи встречи» и «План следующей»). Высота строки заголовка меняется с шириной — считаем по месту.
    const ряд = $main.querySelector(".mt-title-row"), слой = $main.querySelector(".mt-layout");
    $d.style.top = k === "tasks" && ряд && слой && getComputedStyle($d).position === "absolute"
      ? `${Math.round(ряд.getBoundingClientRect().bottom - слой.getBoundingClientRect().top + 8)}px` : "";
    document.getElementById("mt-close").addEventListener("click", () => { $d.hidden = true; $d.dataset.k = ""; кнопка.setAttribute("aria-expanded", "false"); });
    document.getElementById("mt-all-tasks")?.addEventListener("click", () => реестрПоВстрече(id, встреча.date));
  };
  // Заголовок один (дополнение «Шапка страницы встречи»): первая строка самого документа его повторяла — прячем её
  const спрятатьПервуюСтроку = (док) => {
    const перваяСтрока = док?.firstElementChild?.classList.contains("doc-protocol") ? док.firstElementChild.firstElementChild : док?.firstElementChild;
    if (перваяСтрока && /^(Протокол|План).{0,40}\d{2}\.\d{2}\.\d{2,4}\s*$/.test(перваяСтрока.textContent.trim())) перваяСтрока.hidden = true;
  };
  спрятатьПервуюСтроку($main.querySelector(".mt-text"));
  // Материалы — действующие источники встречи; запись, чей файл удалён после распознавания, сама материалом не считается (её
  // текст — в расшифровке). Есть — сборка в «Подготовке встречи» той же кнопкой и с тем же подтверждением, что «Пересобрать»
  // (там виден её ход); нет — отказ словами здесь же, сервер отвечает тем же (prepare-minutes). 22.10.2026, как в Планёрке.
  document.getElementById("reader-build")?.addEventListener("click", async () => {
    let источники = [];
    try { источники = await api(`/meetings/${id}/sources`); } catch (e) { toast(e.message, true); return; }
    if (!(источники || []).some(s => !s.removed_at)) {
      toast("Собирать протокол не из чего: к встрече не приложены ни расшифровка, ни запись, ни заметки. Добавьте файл в «Источниках» подготовки встречи — протокол соберётся сам.", true);
      return;
    }
    try { sessionStorage.setItem("buildOnOpen", String(id)); } catch (e) { /* без памяти — кнопка в подготовке */ }
    location.hash = `#meetings/${id}/protocol`;
  });
  // ссылки ряда («Скачать .docx», «Правка») панель не открывают — обработчик только у кнопок панели (21.10.2026)
  document.querySelectorAll(".mt-btn[data-drawer]").forEach(b => b.addEventListener("click", () => открыть(b.dataset.drawer, b)));
  const наEsc = ev => {
    if (ev.key !== "Escape") return;
    if (!document.getElementById("mt-drawer")) { document.removeEventListener("keydown", наEsc); return; }
    $d.hidden = true; $d.dataset.k = "";
  };
  // Слушатель прежнего показа снимается (18.10.2026): при повторном заходе на встречу он оставался — панель новой страницы
  // есть, и проверка «ушли со страницы» его не снимала; за день переходов их копились десятки
  if (renderMeetingReader._наEsc) document.removeEventListener("keydown", renderMeetingReader._наEsc);
  renderMeetingReader._наEsc = наEsc;
  document.addEventListener("keydown", наEsc);
  // администратору — путь точками в строке; участнику ничего (ни разметки, ни запроса). У будущей встречи пути протокола нет
  // (О7) — точек «Запись принята…» до её дня тоже нет (Д15, проход 2, 21.10.2026)
  if (!будущая || протокол.available) путьТочками(id);
  if (админ && протокол.available) загрузитьПроверкуПослеСохранения(id, { blockId: "minutes-block", canEdit: false });
  полотноПодключитьПереключатель($main, () => renderMeetingReader(id));
  if (режимПолотна === "edit") {
    // место на экране держит обёртка `сПрокруткойНаМесте` (строка действия — первым якорем, 26.10.2026); прежний возврат
    // scrollY здесь же перебивал якорь и после перерисовки отменял его
    const перерисовать = () => renderMeetingReader(id);
    await полотноВключить(document.getElementById("mt-doc-text"), { base: основаПолотна,
      md: протокол.available ? протокол.content_md : планЭтой.content_md, перерисовать, встреча: id, после: спрятатьПервуюСтроку });
  }
}

// ---- Путь встречи точками в строке инструментов — вариант Б (решение владельца 13.10.26, дополнение «Линия») -------------
// Только администратору: участнику — ни разметки, ни запроса (сервер путь не отдаёт: /meetings/{id}/path — require_admin).
// В строке после метки состояния — точки на тонкой линии и подпись последнего шага; по щелчку весь путь всплывает карточкой
// поверх документа (документ не сдвигается). Карточка — вне строки инструментов: у строки своя прокрутка вбок, и карточку
// внутри неё обрезало бы. Закрывается Esc, щелчком мимо и повторным щелчком; при смене экрана снимается.
async function путьТочками(id) {
  if (!isAdmin()) return;
  let p;
  try { p = await api(`/meetings/${id}/path`); } catch (e) { return; }
  const $bar = $main.querySelector(".mt-bar");
  const $state = $bar?.querySelector(".mt-state");
  if (!$state || $bar.querySelector(".mt-path")) return;
  const сбой = p.steps.find(ш => ш.state === "сбой");
  const текущий = p.steps.find(ш => ш.k === p.current);
  const подпись = (сбой || текущий || p.steps[p.steps.length - 1]).title;
  const точки = p.steps.map(ш => {
    const пропущен = ш.k === "decision" && ш.state === "готово" && /не требовалось/.test(ш.detail || "");
    const вид = ш.state === "сбой" ? "fail" : пропущен ? "skip" : ш.state === "готово" ? "done" : ш.k === p.current ? "now" : "todo";
    return `<span class="mp-dot mp-${вид}"></span>`;
  }).join("");
  $state.insertAdjacentHTML("afterend", `<button type="button" class="mt-path${сбой ? " mt-path-fail" : ""}" aria-expanded="false"
    aria-haspopup="dialog" aria-label="Путь встречи: ${esc(подпись)}"><span class="mp-line" aria-hidden="true">${точки}</span><span class="mp-label">${esc(подпись)}</span></button>`);
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
  if (rest[1] === "protocol") return _экранВстреч(rest);
  if (rest[1] === "planprep") return _экранВстреч([rest[0]]);
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
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>Договорённости</h1>
      <div class="feed-sub">Решения, правила работы, открытые вопросы и обсуждённое без решения. Договорённость с понятным действием и
        исполнителем — задача, она в реестре задач. ${data.mode === "on"
        ? "В протоколе — решения и открытые вопросы обычными предложениями в разделах тем." : "Режим «в тени»: в протокол строки не идут."}</div></div></div>
    <div class="card hstack" id="agr-filter" style="gap:8px;padding:12px 16px;margin:0 0 16px">
      ${/* фильтр проекта — всегда, один компонент с Планёркой (решения владелицы 25.10.2026, пп. 1–2): «Весь проект …» — все
            записи без отбора, ниже подпроекты проекта системы и «без подпроекта», если подпроекты есть */ ""}
      ${фильтрПроектаHtml("agr-project", { все: (data.project_filter || {}).all || "Весь Проект ERP", варианты: (data.project_filter || {}).options || [],
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
