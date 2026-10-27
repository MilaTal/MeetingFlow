// «Подготовка встречи» — путь встречи слева (прототип 1, вариант Б; задание владельца 13.10.26, раздел 4).
// Адреса — #meetings/<id>/protocol и #meetings/<id>/planprep (прежние экраны сборки, приёмки и источников справа).
// Путь — отдельной колонкой ВНЕ области документа: прежние экраны перерисовывают себя сами, колонка от этого не пропадает.
// Состояние встречи показано один раз — здесь: решение по черновику — на шаге «Ждёт решения» (прежний баннер приёмки
// спрятан, его кнопка вызывается отсюда), сбой — на шаге, где он случился. Вместо счётчика секунд — время начала и
// длительность; при долгой сборке — «что делать».

let _путьТаймер = null;
let _путьВстречи = null;          // последний путь — шапка берёт из него состояние («ждёт решения» → черновик)
let _замечанияОткрыты = false;
let _путьОткрыт = false;          // путь на узком экране — раскрыт ли (переживает обновление раз в 15 с)    // на подготовке замечания свёрнуты, пока их не открыли кнопкой «Замечания N»

const ПУТЬ_ЧТО_ДЕЛАТЬ = "Обычно черновик собирается за 1–5 минут. Если дольше получаса — откройте «Систему → Мониторинг»: " +
  "модель могла замолчать (система сама перейдёт на запасную точку или повторит сборку, когда модель ответит). Сменить " +
  "модель — «Система → Модели». Зависшую сборку снимает перезапуск сервера: она продолжится сама с готовых шагов.";

function путьДата(iso) { return iso ? fmtRuDateTime(iso).replace(" в ", " ") : ""; }

function путьHtml(p) {
  // У будущей встречи пути протокола нет (решение владелицы 21.10.2026, «Проект нового пути»): протокол собирается после
  // неё, а шаги «запись — черновик — решение» до её дня читались как отставание и вели в «создать протокол».
  const д = new Date();
  const сегодня = `${д.getFullYear()}-${String(д.getMonth() + 1).padStart(2, "0")}-${String(д.getDate()).padStart(2, "0")}`;
  if (String(p.date).slice(0, 10) > сегодня && !p.steps.some(ш => ш.k === "saved" && ш.state === "готово")) {
    return `<button type="button" class="path-head" aria-expanded="${_путьОткрыт}">Встреча ${esc(fmtRuDate(p.date))}<span class="path-now"> · ещё не прошла</span></button>
      <div class="path path-future reg-sub">Встреча ещё не прошла. После неё — протокол.</div>
      <div class="path-links"><a href="#meetings/${p.meeting_id}">страница встречи</a> · <a href="#meetings/${p.meeting_id}/planprep">план встречи</a></div>`;
  }
  const шаги = p.steps.map(ш => {
    const текущий = ш.k === p.current;
    const класс = ш.state === "готово" ? "done" : ш.state === "сбой" ? "fail" : текущий ? "now" : "todo";
    let ещё = "";
    if (ш.k === "decision" && ш.state === "ждёт решения" && !isAdmin()) {
      ещё = `<div class="reg-sub">решение по черновику — за администратором</div>`;
    } else if (ш.k === "decision" && ш.state === "ждёт решения") {
      ещё = `<div class="path-act"><button type="button" class="btn-line" id="path-accept">Принять с замечаниями</button>
        <span class="reg-sub">или дождаться новой сборки${p.steps.find(x => x.k === "draft" && x.state === "идёт") ? " — она уже идёт" : ""}</span></div>`;
    }
    if (ш.k === "draft" && ш.state === "идёт") {
      ещё = `<div class="reg-sub">идёт с ${esc(путьДата(ш.at))} · <span class="tip"><button type="button" class="link tip-link" aria-label="Что делать при долгой сборке">что делать</button><span class="tip-body" role="tooltip">${esc(ПУТЬ_ЧТО_ДЕЛАТЬ)}</span></span></div>`;
    }
    const сбой = ш.failure ? `<div class="path-fail">${esc(ш.failure.что)}<span class="reg-sub">Система: ${esc(ш.failure.сама)}. Вы: ${esc(ш.failure.человек)}.</span></div>` : "";
    return `<li class="path-step path-${класс}"${текущий ? ' aria-current="step"' : ""}>
      <span class="path-dot" aria-hidden="true"></span>
      <div class="path-body"><div class="path-title">${esc(ш.title)}</div>
        ${ш.at && ш.state !== "идёт" ? `<div class="reg-sub">${esc(путьДата(ш.at))}</div>` : ""}
        ${ш.detail && ш.state !== "идёт" ? `<div class="reg-sub">${esc(ш.detail)}</div>` : ш.state === "идёт" && ш.k !== "draft" ? `<div class="reg-sub">${esc(ш.detail)}</div>` : ""}
        ${ещё}${сбой}</div></li>`;
  }).join("");
  // На узком экране путь свёрнут в одну строку с текущим шагом — раскрывается нажатием (снимок на 400 px: путь занимал весь
  // первый экран, документ начинался ниже). На широком — всегда раскрыт, строка-кнопка выглядит заголовком.
  const сейчас = p.steps.find(ш => ш.k === p.current);
  return `<button type="button" class="path-head" aria-expanded="${_путьОткрыт}">Путь встречи ${esc(fmtRuDate(p.date))}${сейчас ? `<span class="path-now"> · ${esc(сейчас.title)}${сейчас.state && сейчас.state !== "ждёт" ? `: ${esc(сейчас.state)}` : ""}</span>` : ""}</button><ol class="path">${шаги}</ol>
    <div class="path-links"><a href="#meetings/${p.meeting_id}">страница встречи</a> · <a href="#meetings/${p.meeting_id}/protocol">протокол</a> · <a href="#meetings/${p.meeting_id}/planprep">план встречи</a></div>`;
}

async function показатьПуть(id) {
  let $a = document.getElementById("prep-path");
  const $shell = document.querySelector(".main");
  if (!$a) {
    $a = document.createElement("aside");
    $a.id = "prep-path";
    $a.className = "prep-path";
    $a.setAttribute("aria-label", "Путь встречи");
    $shell.insertBefore($a, $shell.firstChild);
  }
  $shell.classList.add("with-path");
  let p;
  try { p = await api(`/meetings/${id}/path`); } catch (e) { $a.innerHTML = `<div class="reg-sub">${esc(e.message)}</div>`; return; }
  $a.innerHTML = путьHtml(p);
  $a.classList.toggle("open", _путьОткрыт);
  $a.querySelector(".path-head")?.addEventListener("click", ev => {
    _путьОткрыт = !_путьОткрыт;
    $a.classList.toggle("open", _путьОткрыт);
    ev.currentTarget.setAttribute("aria-expanded", String(_путьОткрыт));
  });
  _путьВстречи = p;
  // Тем же порядком, что наблюдатель (дефект 21.10.2026): при прямой загрузке адреса путь приходил раньше «Материалов»,
  // шапка собиралась без них и падала на кнопке «Замечания»
  назадВПодготовку(); обустроитьМатериалы(); шапкаПодготовки();
  document.getElementById("path-accept")?.addEventListener("click", async () => {
    const старая = document.getElementById("accept-draft-banner-btn");
    if (старая) { старая.click(); return; }
    try {
      await api(`/meetings/${id}/accept-draft`, { method: "POST" });
      toast("Протокол принят с замечаниями — задачи заведены в реестр");
      render();
    } catch (e) { toast(e.message, true); }
  });
}

function убратьПуть() {
  clearInterval(_путьТаймер);
  _путьТаймер = null;
  document.getElementById("prep-path")?.remove();
  document.querySelector(".main")?.classList.remove("with-path");
}

function этоПодготовка() {
  const [r, id, вид] = currentRouteParts();
  return r === "meetings" && id && (вид === "protocol" || вид === "planprep") ? id : null;
}

async function следитьЗаПутём() {
  const id = этоПодготовка();
  // Путь — всем, кто готовит встречу (решение владелицы 21.10.2026: «Подготовка встречи» — всем ролям; было — администратору)
  if (!id || !canPrepare()) { убратьПуть(); return; }
  await показатьПуть(id);
  clearInterval(_путьТаймер);
  _путьТаймер = setInterval(() => { if (этоПодготовка() === id) показатьПуть(id); else убратьПуть(); }, 15000);
}

// ---- Материалы — панелью справа вместо липкой полосы источников (задание, раздел 4) ------------------------------
// Прежняя полоса уже умеет всё: список источников, «+ добавить» (файл, запись, текст), «удалить все», сборку. Её не
// переписываем: переносим её панель в правую колонку, полосу прячем, «Собрать заново» — ссылкой с пометкой «платно» и
// подтверждением (нажимает прежнюю кнопку сборки), «удалить все» — «Перевыбрать файлы». Прежний экран перерисовывает себя
// сам — перенос повторяется после каждой перерисовки (наблюдатель за #main).
// Подпись ссылки «Собрать заново» по скрытой кнопке сборки (дефект, решение владелицы 20.10.2026: пересборку в фон не отдаём,
// пользователь видит, что машина работает). Кнопка в спрятанной полосе считает «Генерирую… (N сек)» / «В очереди… (N сек)»
// от реального начала сборки; ссылка показывает то же словами Планёрки (панель «Материалы»): «Идёт сборка с ЧЧ:ММ, N мин».
// `идёт` — на время сборки ссылка неактивна, повторное нажатие нового запроса не запускает.
function подписьСсылкиСборки(кнопка, заново, сейчас = Date.now()) {
  const текст = String(кнопка?.textContent || "");
  if (/^Идёт сборка с |^В очереди с /.test(текст)) return { текст, идёт: true };
  const очередь = /В очереди/.test(текст);
  if (!очередь && !/Генерирую/.test(текст)) return { текст: заново ? "Собрать заново" : "Собрать", идёт: false };
  const сек = Number((текст.match(/\((\d+)\s*сек\)/) || [])[1] || 0);
  const чч = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit" }).format(new Date(сейчас - сек * 1000));
  return { текст: `${очередь ? "В очереди" : "Идёт сборка"} с ${чч}, ${Math.floor(сек / 60)} мин`, идёт: true };
}

function обустроитьМатериалы() {
  const id = этоПодготовка();
  if (!id) return;
  const панель = document.getElementById("src-panel") || document.getElementById("plan-src-panel");
  const полоса = панель?.closest(".src-bar-wrap");
  if (!панель || !полоса || полоса.dataset.prep === "1") return;
  полоса.dataset.prep = "1";
  полоса.querySelector(".src-bar")?.setAttribute("hidden", "");
  полоса.classList.add("prep-materials");
  // Число — как в прежней полосе («N источников»: у плана в него входят и протокол, и кандидаты, не только файлы); нет числа —
  // по кнопкам удаления источников и материалов (аудит 13.10.26: у плана считались только источники — всегда 0)
  // только «N источник(а/ов)»: при одном–двух источниках в подписи стоит имя файла, и число из даты в нём давало «Материалы 8»
  // (второй проход аудита 13.10.26)
  const чип = полоса.querySelector(".src-bar-chip")?.textContent.match(/^\s*(\d+)\s+источник/);
  // заголовок панели «Источники протокола · N» — число и для участника: кнопок удаления у него нет (21.10.2026, «Подготовка» всем)
  const вЗаголовке = панель.querySelector(".src-panel-head")?.textContent.match(/·\s*(\d+)/);
  // У плана — число файлов-материалов (Д11, проходы 1–4, 21.10.2026): «Материалы 3» считало протокол, задачи и вопросы, а
  // внутри стояло «Материалы к встрече · 0». Протокол, задачи и вопросы — в группе «Из системы» той же панели.
  const сколько = панель.dataset.files !== undefined ? Number(панель.dataset.files)
    : чип ? Number(чип[1]) : вЗаголовке ? Number(вЗаголовке[1])
    : панель.querySelectorAll(".delete-source-btn, .delete-material-btn").length;
  // ссылки шапки прежнего экрана: «План» — на подготовку плана, а не на страницу читателя
  $main.querySelectorAll(`.doc-tabs a[href="#meetings/${id}"]`).forEach(a => a.setAttribute("href", `#meetings/${id}/planprep`));
  // кнопка «Материалы N» — в строке шапки
  const шапка = $main.querySelector(".doc-head");
  if (шапка && !$main.querySelector(".prep-mat-btn")) {      // кнопка могла уже переехать к заголовку (шапкаПодготовки)
    шапка.insertAdjacentHTML("beforeend", `<button type="button" class="mt-btn prep-mat-btn" aria-expanded="false">${ВСТРЕЧА_ЗНАКИ.notes}Материалы <span class="n">${сколько}</span></button>`);
    шапка.querySelector(".prep-mat-btn").addEventListener("click", ev => {
      const открыто = !панель.hidden;
      панель.hidden = открыто;
      ev.currentTarget.setAttribute("aria-expanded", открыто ? "false" : "true");
    });
  }
  // «+ Добавить файл» и «Собрать заново (платно)» — внутрь панели
  // У протокола «+ добавить» — меню `.src-add`, у плана — кнопка файла `.src-add-file`, и у панели плана нет строки инструментов.
  // Аудит 13.10.26: перенос шёл только при строке инструментов — на подготовке плана «+ добавить файл» и «Подготовить /
  // Пересобрать план» оставались в спрятанной полосе, план нельзя было ни собрать, ни дополнить.
  const добавить = полоса.querySelector(".src-add, .src-add-file");
  const инструменты = панель.querySelector(".src-panel-tools");
  if (добавить && !панель.querySelector(".prep-tools")) {
    const место = document.createElement("div");
    место.className = "prep-tools";
    место.appendChild(добавить);
    const кнопкаСборки = полоса.querySelector("#prepare-minutes-btn, #prepare-plan-btn");
    // У плана своя главная кнопка — первой наверху экрана, вне панелей (решение владелицы 21.10.2026); второй, ссылкой в
    // панели, не нужно. Ссылка остаётся у протокола.
    if (кнопкаСборки && кнопкаСборки.id !== "prepare-plan-btn") {
      const ссылка = document.createElement("button");
      ссылка.type = "button";
      ссылка.className = "link";
      // «заново» — по исходной подписи кнопки или по тому, что протокол уже есть (во время сборки кнопка пишет «Генерирую…»)
      const заново = /Пересобрать|Пересоздать|заново/i.test(кнопкаСборки.textContent) || кнопкаСборки.title.includes("Новая версия");
      // Подпись и состояние — вслед за скрытой кнопкой (20.10.2026): прежде подпись вычислялась один раз, во время сборки не
      // менялась, и ссылка оставалась нажимаемой. Наблюдатель ловит тики кнопки, тикер раз в секунду — смену минут.
      const обновить = () => {
        const с = подписьСсылкиСборки(кнопкаСборки, заново);
        if (ссылка.textContent !== с.текст) ссылка.textContent = с.текст;
        ссылка.disabled = с.идёт || кнопкаСборки.disabled;
      };
      обновить();
      const наблюдатель = new MutationObserver(обновить);
      наблюдатель.observe(кнопкаСборки, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });
      const тикер = setInterval(() => {
        if (!ссылка.isConnected) { clearInterval(тикер); наблюдатель.disconnect(); return; }   // экран перерисован — следит новая ссылка
        обновить();
      }, 1000);
      ссылка.addEventListener("click", async () => {
        if (подписьСсылкиСборки(кнопкаСборки, заново).идёт) return;
        const вопрос = заново
          ? "Собрать документ заново? Это платный вызов модели, 1–5 минут. Прежняя версия заменится, только если новая пройдёт проверку."
          : "Собрать документ? Это платный вызов модели, 1–5 минут.";
        if (!(await confirmDialog(вопрос, заново ? "Собрать заново" : "Собрать"))) return;
        кнопкаСборки.disabled = false;
        кнопкаСборки.click();
      });
      место.appendChild(ссылка);
      место.insertAdjacentHTML("beforeend", '<span class="reg-sub">платно</span>');
    }
    место.insertAdjacentHTML("beforeend", '<span class="reg-sub">или перетащите файл на страницу</span>');
    панель.insertBefore(место, инструменты ? (панель.children[1] || null) : панель.firstChild);
  }
  const сброс = панель.querySelector("#reset-sources-btn");
  if (сброс) сброс.textContent = "Перевыбрать файлы";
  if (шапка && шапка.nextElementSibling !== полоса) шапка.after(полоса);     // панель открывается под шапкой, а не внизу страницы
}

// «← Встречи» на экранах подготовки вёл в ленту «Протоколы» — назад отсюда значит в «Подготовку встречи» (аудит 13.10.26)
function назадВПодготовку() {
  // «Подготовка встречи» с 21.10.2026 — всем ролям (решение владелицы): назад — в неё у каждого, кто готовит встречу
  if (!canPrepare()) return;
  $main.querySelectorAll('a[href="#meetings"]').forEach(a => {
    if (/Встречи/.test(a.textContent)) { a.setAttribute("href", "#prep"); a.textContent = "← Подготовка"; }
  });
}

// «Поправить» со страницы встречи: на подготовке протокола открыть правку этого же замечания (второй проход аудита 13.10.26:
// переход был, правка — нет, замечание приходилось искать заново)
function открытьОтложеннуюПравку() {
  let ждёт = null;
  try { ждёт = JSON.parse(sessionStorage.getItem("noteToFix") || "null"); } catch (e) { return; }
  if (!ждёт) return;
  const кнопка = document.querySelector(`.rn-item[data-run="${ждёт.run}"][data-idx="${ждёт.idx}"] [data-note-act="fix"]`);
  if (!кнопка) return;
  try { sessionStorage.removeItem("noteToFix"); } catch (e) { /* без памяти */ }
  кнопка.click();
}

// ---- Шапка подготовки — «Линия» (дополнение «Шапка страницы встречи и подготовки», 13.10.26) ---------------------------
// Один заголовок — сам документ: «Протокол встречи ДД.ММ.ГГГГ» / «Черновик протокола ДД.ММ.ГГГГ» / «План встречи ДД.ММ.ГГГГ»,
// под ним одна приглушённая строка состояния. Над ним одна строка инструментов: «← Подготовка встречи», «Протокол · План»,
// справа «Замечания N», «Материалы N», «Скачать .docx», «Правка» — горизонтальным рядом кнопок (пп. 1–2 замечаний владелицы
// 21.10.2026: прежде «Скачать .docx» и «Правка» прятались в «⋯», и выгрузку в Word не находили). «⋯» больше нет: редкого
// в нём не осталось («Изменить дату» стоит в строке инструментов). Дата — только в заголовке. Документ — на всю ширину
// без внутренней прокрутки: прежде его теснили путь слева и замечания справа (замер 13.10.26: 268 px). Кнопки и обработчики
// прежние — переносятся, не пишутся заново.
function шапкаПодготовки() {
  const id = этоПодготовка();
  const шапка = $main.querySelector(".doc-head");
  if (!id || !шапка) return;
  const [, , вид] = currentRouteParts();
  const h1 = шапка.querySelector("h1");
  const дата = (h1?.textContent.match(/\d{2}\.\d{2}\.\d{4}/) || [""])[0];
  const мета = шапка.querySelector(".doc-head-meta");
  const решение = _путьВстречи && String(_путьВстречи.meeting_id) === String(id)
    && _путьВстречи.steps.some(ш => ш.k === "decision" && ш.state === "ждёт решения");
  const заголовок = вид === "planprep" ? `План встречи ${дата}` : решение ? `Черновик протокола ${дата}` : `Протокол встречи ${дата}`;
  const состояние = вид === "protocol" && решение ? "Черновик — решение принимается на шаге «Ждёт решения» слева"
    : (мета?.textContent.trim() || "");
  if (!шапка.dataset.line) {
    шапка.dataset.line = "1";
    шапка.classList.add("prep-bar");
    if (h1) h1.hidden = true;
    if (мета) мета.hidden = true;
    const назад = шапка.querySelector("a.btn");
    if (назад) {
      назад.classList.remove("btn", "btn-sm"); назад.classList.add("mt-back");
      // «Подготовка встречи» — всем ролям (решение владелицы 21.10.2026): назад — в неё у каждого
      назад.textContent = "← Подготовка встречи";
      назад.setAttribute("href", "#prep");
    }
    // «Скачать .docx» и «Правка» — кнопками в ряду рядом с «Замечаниями» и «Материалами», а не в «⋯» (пп. 1–2 замечаний
    // владелицы 21.10.2026). Узлы переносятся, а не пишутся заново: «Правка» — переключатель правки на полотне (polotno.js).
    const скачать = шапка.querySelector('a.btn[href$="/export"]');
    if (скачать) {
      скачать.classList.remove("btn", "btn-sm");
      скачать.classList.add("mt-btn", "prep-docx-btn");
      скачать.innerHTML = `${ВСТРЕЧА_ЗНАКИ.docx}Скачать .docx`;
    }
    // «Правка» — переключатель «Просмотр / Правка» правки на полотне (решение владелицы 24.10.2026): переносится как есть
    const правка = шапка.querySelector(".pp-switch");
    if (правка) правка.classList.add("prep-edit-btn");
    // «Замечания N» — кнопкой в строке; на подготовке свёрнуты, документ на всю ширину
    const заметки = $main.querySelector(".doc-with-notes");
    const число = (заметки?.querySelector(".rn-head")?.textContent.match(/\d+/) || [""])[0];
    // «Замечания» — справка администратору (решение владелицы 17.10.2026); «Подготовка» с 21.10.2026 открыта всем —
    // участнику панели и кнопки нет, документ на всю ширину
    if (заметки && !isAdmin()) заметки.classList.add("rn-collapsed");
    if (заметки && isAdmin()) {
      заметки.classList.toggle("rn-collapsed", !_замечанияОткрыты);
      // Перед «Материалами», если они уже есть; нет — в конец шапки (дефект 21.10.2026: при прямой загрузке «Материалов» ещё
      // не было, кнопка не вставлялась, а следующая строка падала на null). Порядок в строке действий ставится ниже.
      const кнопкаЗамечаний = `<button type="button" class="mt-btn prep-notes-btn" aria-expanded="${_замечанияОткрыты}">${ВСТРЕЧА_ЗНАКИ.notes}Замечания <span class="n">${число}</span></button>`;
      const материалы = шапка.querySelector(".prep-mat-btn");
      if (материалы) материалы.insertAdjacentHTML("beforebegin", кнопкаЗамечаний);
      else шапка.insertAdjacentHTML("beforeend", кнопкаЗамечаний);
      шапка.querySelector(".prep-notes-btn").addEventListener("click", ev => {
        _замечанияОткрыты = !_замечанияОткрыты;
        $main.querySelector(".doc-with-notes")?.classList.toggle("rn-collapsed", !_замечанияОткрыты);
        ev.currentTarget.setAttribute("aria-expanded", String(_замечанияОткрыты));
      });
    }
    $main.querySelector(".doc-compact")?.classList.add("prep-doc");
  }
  // Заголовок документа и строка состояния — над документом (обновляются: путь приходит позже шапки)
  let $t = $main.querySelector(".prep-title");
  if (!$t) {
    $t = document.createElement("div");
    $t.className = "prep-title";
    const куда = $main.querySelector(".doc-compact") || шапка.nextElementSibling;
    куда?.parentNode.insertBefore($t, куда);
  }
  if (!$t.querySelector(".mt-title-row")) {
    // «собран дд.мм.гггг…» — в строке заголовка справа, мелко (владелец 13.10.26: рабочая область больше, без пустых строк)
    $t.innerHTML = '<div class="mt-title-row"><h1 class="mt-title"></h1><span class="mt-acts"></span><span class="mt-sub" hidden></span></div>';
  }
  const $h = $t.querySelector(".mt-title");
  if ($h.textContent !== заголовок) $h.textContent = заголовок;
  const $s = $t.querySelector(".mt-sub");
  if ($s.textContent !== состояние) $s.textContent = состояние;
  $s.hidden = !состояние;
  // «Замечания», «Материалы», «Скачать .docx», «Правка» — сразу за выбранной встречей, к которой относятся, а не у правого края
  // строки инструментов (принцип владельца 13.10.26 «действие — рядом со своим объектом»; образец — Планёрка d74d93a)
  const $acts = $t.querySelector(".mt-acts");
  const РЯД = [".prep-notes-btn", ".prep-mat-btn", ".prep-docx-btn", ".prep-edit-btn"];
  шапка.querySelectorAll(РЯД.map(с => `:scope > ${с}`).join(", ")).forEach(k => $acts.appendChild(k));
  // Порядок один при любом порядке прихода (21.10.2026: «Материалы», пришедшие после шапки, вставали в конец ряда)
  РЯД.forEach(с => { const к = $acts.querySelector(`:scope > ${с}`); if (к) $acts.appendChild(к); });
  // Заголовок один: первая строка самого документа («Протокол встречи …», «План встречи …») повторяла его — прячем её
  const первая = $main.querySelector(".prep-doc .doc-content .doc-title");   // протокол обёрнут в .doc-protocol (13.10.26)
  if (первая && /^(Протокол|План|Черновик).{0,40}\d{2}\.\d{2}\.\d{4}\s*$/.test(первая.textContent.trim())) первая.hidden = true;
  // «Вёл встречу» — справочная строка — в строке заголовка справа (13.10.26: рабочая область больше; прежде — отдельной
  // строкой под заголовком, 31 px до документа)
  const вёл = $main.querySelector(":scope > .meeting-leader");
  const $ряд = $t.querySelector(".mt-title-row");
  if (вёл && вёл.parentElement !== $ряд) $ряд.appendChild(вёл);
}

// Раз за кадр, а не на каждую мутацию (18.10.2026)
let _подготовкаКадр = 0;
function проходПодготовки() {
  if (этоПодготовка()) { назадВПодготовку(); обустроитьМатериалы(); шапкаПодготовки(); открытьОтложеннуюПравку(); }
}
const _наблюдатель = new MutationObserver(() => {
  if (_подготовкаКадр) return;
  _подготовкаКадр = requestAnimationFrame(() => {
    _подготовкаКадр = 0;
    проходПодготовки();
  });
});
// Первый проход — сразу при подключении (21.10.2026): при прямой загрузке #meetings/N/protocol первая перерисовка могла
// пройти раньше DOMContentLoaded, и наблюдатель её не видел
function подключитьНаблюдатель() {
  _наблюдатель.observe(document.getElementById("main"), { childList: true });
  проходПодготовки();
}
document.addEventListener("DOMContentLoaded", подключитьНаблюдатель);

window.addEventListener("hashchange", следитьЗаПутём);
document.addEventListener("DOMContentLoaded", () => setTimeout(следитьЗаПутём, 1500));
