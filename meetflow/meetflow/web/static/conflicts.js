// «Конфликты» — очередь строками (оформление «Линия с элементами», одобрено владельцем 13.10.26; стенд 8020).
// Слева значок вида: человек — исполнитель, календарь — срок, звуковая волна — голос и записи, лист — замечание проверки,
// список — задача. В строке заголовок 14,5/500, цитата 13 px курсивом, одно действие в рамке и «⋯» с остальными. Фильтры по
// видам — в строке инструментов со счётчиками. Служебных слов и внутренних номеров нет.
// Карточки рисует прежний код (у каждого вида свои кнопки и обработчики) — здесь они перестраиваются после отрисовки,
// обработчики остаются на тех же кнопках.

const КОНФЛИКТ_ВИДЫ = {
  // задачи под вопросом — первыми (решение владельца 15.10.26); значок — как у задач
  question: { label: "Задачи под вопросом", ico: "" },
  person: { label: "Исполнитель", ico: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/></svg>' },
  due: { label: "Срок", ico: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>' },
  voice: { label: "Голос и записи", ico: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2"/></svg>' },
  review: { label: "Замечания проверки", ico: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/></svg>' },
  // Реестр договорённостей — своей группой, как в Планёрке (решения владелицы 21.10.2026, пункт 5)
  agree: { label: "Договорённости", ico: "" },
  task: { label: "Задачи", ico: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 7l2 2 3-3M4 15l2 2 3-3M12 8h8M12 16h8"/></svg>' },
  // «Говорящий N» без подтверждённого ФИО (решение владельца 17.10.26): решить по такой карточке нельзя — группа последней,
  // свёрнута и сама не открывается; карточки не удаляются
  voicewait: { label: "Ждут опознания голоса", ico: "" },
};

КОНФЛИКТ_ВИДЫ.question.ico = КОНФЛИКТ_ВИДЫ.task.ico;
КОНФЛИКТ_ВИДЫ.voicewait.ico = КОНФЛИКТ_ВИДЫ.voice.ico;
КОНФЛИКТ_ВИДЫ.agree.ico = КОНФЛИКТ_ВИДЫ.review.ico;

function конфликтВид(card) {
  const f = card.dataset.field || "", src = card.dataset.src || "";
  if ((window.конфликтыДанные || new Map()).get(String(card.dataset.id))?.voice_wait) return "voicewait";
  if (f === "ungrounded_task") return "question";
  if (f.startsWith("agreement_")) return "agree";
  if (src === "review_finding" || f === "external_unheard") return "review";   // внешний без звучания (24.10.2026) — к замечаниям
  if (f === "no_tasks_with_assignment_lines") return "task";
  if (src === "due_notes_vs_record") return "due";
  if (f === "due_date" || src === "deadline_check") return "due";
  if (f === "held_recording" || src === "unconfirmed_person" || /voice|speaker|recording/.test(f + src)) return "voice";
  if (f === "responsible") return "person";
  return "task";
}

// «Что прозвучало» — цитата из текста системы (Планёрка bc998cf, владелец 15.10.26: «сейчас нет контекста, по которому
// понять, какой выбор сделан… сократи текст в описании, добавь контекст, о чём была речь»). Образцы — как у Планёрки:
// «Цитата: «…»», «назван «X» — «…»», «встречи дд.мм.гг: «…»», «← «…»»; иначе — первая цитата в «…» длиннее 15 знаков.
// Метки времени убираются, длина — не больше 220 знаков.
function конфликтЦитата(текст) {
  const т = String(текст || "");
  const м = т.match(/Цитата:\s*«([^»]+)»/) || т.match(/назван[аы]? «[^»]+» — «([^»]+)»/) || т.match(/встреч[аи] \d\d\.\d\d\.\d\d(?:\d\d)?:\s*«([^»]+)»/)
    || т.match(/← «([^»]+)»/) || т.match(/«([^»]{16,})»/);
  if (!м) return "";
  // строка таблицы документа («…|не назначен|В работе») — через «·», а не чертами разметки
  let ц = м[1].replace(/\b\d{1,2}:\d{2}(?::\d{2})?\s*/g, "").replace(/\s*\|\s*/g, " · ").replace(/\s+/g, " ").trim()
    .replace(/^·\s*|\s*·$/g, "");
  if (ц.length > 220) ц = ц.slice(0, 219).replace(/\s+\S*$/, "") + "…";
  return ц;
}

// Карточка-вопрос (Планёрка bc998cf): заголовок — задача или имя; «что прозвучало»; короткий вопрос основным цветом; кнопки
// называют исход («Принять: X» — только если X предложен; «Оставить: X» — выбор среди вариантов, а не тихое закрытие;
// «Указать другого»); полный текст системы и уверенность — в «i». Обработчики кнопок — те же, меняются только подписи.
function конфликтВопрос(card, c) {
  if (!c) return;
  const полный = String(c.evidence_quote || "").trim();
  const цитата = конфликтЦитата(полный);
  const подпись = (v) => датаРу((typeof conflictValueLabel === "function" ? conflictValueLabel(c.field, v) : v) || "");   // даты — дд.мм.гггг
  const имя = c.current_value || "";
  const общая = [...card.querySelectorAll(":scope > .hstack")].some(h => /Сейчас:/.test(h.textContent));
  let заголовок = null, вопрос = "";
  if (c.source === "unconfirmed_person") {
    if (c.identity === "same_or_new") { заголовок = `«${имя}» — тот же человек или новый?`; вопрос = "Это тот же человек из «Команды» или новый?"; }
    else if (c.identity) { заголовок = `«${имя}» — о ком речь?`; вопрос = "Кто это из «Команды»? Под имя подходят несколько человек — выберите."; }
    else { заголовок = `${имя} — неподтверждённая запись в «Команде»`; вопрос = "Это реальный сотрудник?"; }
  } else if (общая) {
    заголовок = c.task_description || CONFLICT_FIELD_LABELS[c.field] || "Задача";
    const сейчас = подпись(c.current_value), пред = подпись(c.proposed_value);
    вопрос = c.field === "responsible" ? `Кто исполнитель? ${сейчас ? `Сейчас записан «${сейчас}».` : "Исполнитель не назначен."}`
      : c.field === "due_date" ? `Какой срок? ${сейчас ? `Сейчас — ${сейчас}.` : "Срока нет."}`
      : c.field === "status" ? `Какой статус? ${сейчас ? `Сейчас — «${сейчас}».` : ""}`
      : `${CONFLICT_FIELD_LABELS[c.field] || "Значение"}: что оставить?${сейчас ? ` Сейчас — «${сейчас}».` : ""}`;
    if (пред) вопрос += ` Предлагается «${пред}».`;
    card.querySelectorAll(".conflict-accept").forEach(b => { if (/^Принять предложенное$/.test(b.textContent.trim())) b.textContent = `Принять: ${пред}`; });
    card.querySelectorAll(".conflict-reject").forEach(b => { if (/^Оставить как есть$/.test(b.textContent.trim()))
      b.textContent = сейчас ? `Оставить: ${сейчас}` : (c.field === "responsible" ? "Оставить без исполнителя" : "Оставить без изменений"); });
    card.querySelectorAll(".conflict-custom").forEach(b => { if (/^Указать своё$/.test(b.textContent.trim()))
      b.textContent = c.field === "responsible" ? "Указать другого" : c.field === "due_date" ? "Указать другой срок" : "Указать своё"; });
  }
  // Текст карточки: всё, кроме рядов кнопок, уходит в «i»; на виду — заголовок, «что прозвучало», вопрос
  const ряды = [...card.children].filter(э => э.classList.contains("hstack") && э.querySelector("button, a.btn-sm, a.btn"));
  const текст = [...card.children].filter(э => !ряды.includes(э) && !э.classList.contains("cf-ico"));
  const прежнийЗаголовок = card.querySelector("b")?.textContent.trim() || "";
  if (!заголовок && !цитата && полный.length <= 220) return;          // короткая карточка — как есть
  const уверенность = c.confidence && typeof CONFLICT_CONFIDENCE_LABELS === "object"
    ? `Уверенность: ${CONFLICT_CONFIDENCE_LABELS[c.confidence] || c.confidence}. ` : "";
  const подробно = (уверенность + полный).trim();
  const короткий = цитата || (полный.length > 220 ? полный.slice(0, 219).replace(/\s+\S*$/, "") + "…" : полный);
  const блок = document.createElement("div");
  блок.className = "cf-q";
  блок.innerHTML = `<div><b>${esc(заголовок || прежнийЗаголовок)}</b>${подробно ? ` <span class="tip"><button type="button" class="tip-ico" aria-label="Полный текст">i</button><span class="tip-body" role="tooltip">${esc(подробно)}</span></span>` : ""}</div>`
    + (короткий ? `<div class="page-sub cf-quote">${цитата ? `«${esc(короткий)}»` : esc(короткий)}</div>` : "")
    + (вопрос ? `<div class="cf-question">${esc(вопрос)}</div>` : "");
  // У прочих видов (замечание проверки, кусок записи…) в тексте бывают ссылки и пометки — их оставляем, сокращаем только
  // длинное пояснение; у вопросов (люди, общая карточка поля) текст целиком заменяется вопросом.
  if (заголовок) текст.forEach(э => э.remove());
  else текст.filter(э => э.classList.contains("page-sub") && э.textContent.trim() === полный).forEach(э => э.remove()),
       текст.filter(э => э.querySelector("b") && !э.classList.contains("page-sub")).slice(0, 1).forEach(э => э.remove());
  card.insertBefore(блок, ряды[0] || null);
}

// Тихое закрытие — отказ, который лишь снимает вопрос и на сервере ничего не меняет (проверено по task_conflicts.py: статус
// «отклонена», без других последствий). «Не заводить», «Удалить запись» и подобные — решения, они остаются действиями.
const КОНФЛИКТ_ТИХИЕ = /^(Принято к сведению|Оставить как есть|Понятно, учту отдельно|Пока оставить неподтверждённым|Оставить без исполнителя|Пока не заводить)$/;

// «Это Белошапка Алексей Николаевич · ОТЛ» → «Это Белошапка А. Н.»; полное ФИО — первым в подсказке (как у Планёрки f3d2ea5)
function конфликтКороткоеИмя(кнопка) {
  const м = (кнопка.textContent || "").replace(/\s+/g, " ").trim().match(/^Это (.+?)(?: · (.*))?$/);
  if (!м) return;
  const части = м[1].split(" ").filter(Boolean);
  if (части.length < 2) return;
  кнопка.title = [м[1], м[2], кнопка.title].filter(Boolean).filter((x, i, a) => a.indexOf(x) === i).join(" · ");
  кнопка.textContent = `Это ${части[0]} ${части.slice(1).map(ч => ч[0].toUpperCase() + ".").join(" ")}`;
}

// Строка «Конфликтов» — как у Планёрки (итоговая раскладка 15.10.26, «сделать так же»): значок | описание ≤ 68 знаков |
// столбец действий 300 px. В столбце сверху вниз: варианты «Это …» → прочие действия → тихое закрытие (отступ 22) →
// значки строкой. Кнопки строк действий переезжают в столбец вместе со своими обработчиками.
function конфликтСтолбец(card) {
  const основа = document.createElement("div");
  основа.className = "cf-main";
  [...card.childNodes].filter(n => !(n.nodeType === 1 && n.classList.contains("cf-ico"))).forEach(n => основа.appendChild(n));
  card.appendChild(основа);
  const ряды = [...основа.querySelectorAll(":scope > .hstack")].filter(р => р.querySelector("button, a.btn-sm, a.btn"));
  if (!ряды.length) return;
  const все = [];
  ряды.forEach(р => { все.push(...р.children); р.remove(); });
  const значки = все.filter(э => э.classList.contains("ri"));
  const варианты = все.filter(э => э.classList.contains("identity-pick"));
  const тихие = все.filter(э => !значки.includes(э) && э.classList.contains("conflict-reject")
    && КОНФЛИКТ_ТИХИЕ.test((э.textContent || "").replace(/\s+/g, " ").trim()));
  const прочие = все.filter(э => !значки.includes(э) && !варианты.includes(э) && !тихие.includes(э));
  варианты.forEach(э => { конфликтКороткоеИмя(э); э.classList.add("cf-opt"); });
  тихие.forEach(э => э.classList.add("cf-dismiss"));
  [...варианты, ...прочие].forEach(э => { э.classList.remove("btn-primary", "link"); э.classList.add("cf-btn"); });
  const столбец = document.createElement("div");
  столбец.className = "cf-act";
  столбец.append(...варианты, ...прочие, ...тихие);
  // Значков в столбце нет (Планёрка 4277201, владелец: «иконка удалить только одна и в странной точке… она точно должна быть
  // там?»): одинокая корзина не говорит, что удалится. Значок становится тихим текстом последней строкой, тот же обработчик;
  // при наведении — цвет тревоги. У неподтверждённой записи — «Удалить из «Команды»».
  значки.forEach(э => {
    const подпись = card.dataset.source === "unconfirmed_person" && э.classList.contains("ri-delete")
      ? "Удалить из «Команды»" : (э.getAttribute("aria-label") || э.title || э.textContent || "").trim();
    э.className = э.className.split(" ").filter(к => !/^ri(-|$)/.test(к)).join(" ");
    э.classList.add("cf-dismiss", "cf-dismiss-danger");
    э.textContent = подпись;
    э.removeAttribute("aria-label");
    столбец.appendChild(э);
  });
  card.appendChild(столбец);
}

// «Понятно, закрыть все (N)» под заголовком группы справа (Планёрка 37b0329): закрывает карточки группы с тихим закрытием
// тем же запросом, что их кнопки; подтверждение называет число и сколько из них закроется без выбора человека.
function конфликтЗакрытьВсе(секция) {
  const тело = секция.querySelector(".cf-group-body");
  const закрываемые = [...тело.querySelectorAll(".conflict-card")].filter(к => к.querySelector(".cf-dismiss"));
  if (закрываемые.length < 2) return;
  секция.querySelector(".cf-group-head").insertAdjacentHTML("afterend",
    `<div class="cf-close-all-row"><button type="button" class="btn-sm cf-close-all">Понятно, закрыть все (${закрываемые.length})</button></div>`);
  секция.querySelector(".cf-close-all").addEventListener("click", async (e) => {
    const кнопка = e.currentTarget;
    const сВыбором = закрываемые.filter(к => к.querySelector(".identity-pick")).length;
    if (!(await confirmDialog(`Закрыть ${закрываемые.length} карточек группы «${секция.querySelector(".cf-group-head").textContent.replace(/[›\d\s]+$/, "").replace(/^›\s*/, "").trim()}»?`
      + (сВыбором ? `\n\nВ ${сВыбором} из них предложен выбор человека — они закроются без выбора.` : ""), "Закрыть все"))) return;
    кнопка.disabled = true;
    let закрыто = 0;
    for (const к of закрываемые) {
      try { await api(`/task-conflicts/${к.dataset.id}`, { method: "PATCH", json: { action: "reject", custom_value: null } }); закрыто++; }
      catch (err) { /* одна неудачная не останавливает остальные — итог в сообщении */ }
    }
    await loadAndRenderConflicts();
    toast(`Закрыто карточек: ${закрыто} из ${закрываемые.length}`, закрыто < закрываемые.length);
  });
}

// Открытые группы — на время сеанса страницы: после решения карточки список перерисовывается, открытое остаётся открытым
const конфликтыОткрыты = new Set();

function перестроитьКонфликты() {
  const $list = document.getElementById("conflicts-list");
  if (!$list || $list.dataset.lined === "1") return;
  const карточки = [...$list.querySelectorAll(".conflict-card")];
  if (!карточки.length) return;
  $list.dataset.lined = "1";
  const счёт = {};
  карточки.forEach(card => {
    const вид = конфликтВид(card);
    счёт[вид] = (счёт[вид] || 0) + 1;
    card.dataset.kindLine = вид;
    card.classList.add("cf-row");
    // заголовок без внутреннего номера задачи
    const b = card.querySelector("b");
    if (b) b.innerHTML = b.innerHTML.replace(/Задача №\d+/g, "Задача").replace(/\s*№\d+\b/g, "");
    // кнопки: первая — в рамке, остальные (кроме кандидатов тёзок) — в «⋯»
    const ряд = [...card.querySelectorAll(".hstack")].filter(h => h.querySelector("button")).pop();   // ряд действий, а не «Сейчас → Предлагается»
    // даты — дд.мм.гггг, без ISO (дополнение, раздел 6)
    card.querySelectorAll("b, .page-sub, div").forEach(el => {
      if (el.children.length === 0 && /\b\d{4}-\d{2}-\d{2}\b/.test(el.textContent)) {
        el.textContent = el.textContent.replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, "$3.$2.$1");
      }
    });
    const кнопки = ряд ? [...ряд.querySelectorAll("button")] : [];
    // У тёзок кандидаты «Это …» остаются кнопками («Линия»: «у тёзок — кнопки с кандидатами»). Аудит 13.10.26: проверялись
    // несуществующие классы, и все кандидаты, кроме первого, уходили в «⋯». Кнопки кандидатов — `.identity-pick`.
    // Прочие решения — на виду рядом с главным, а не в «⋯» (владелец 13.10.26 в Планёрке, 0c17b53; одинаковый вид обеих
    // систем). «Удалить», «Отклонить», «Закрыть» — значками с подсказкой; остальное — короткой ссылкой.
    if (кнопки.length > 1 && !card.querySelector(".identity-pick")) {
      кнопки.slice(1).forEach(k => {
        const текст = (k.textContent || "").replace(/\s+/g, " ").trim();
        const значок = /^Удалить/i.test(текст) ? "ri-delete" : /^(Отклонить|Не он|Это не)/i.test(текст) ? "ri-reject"
          : /^(Закрыть|Снять)/i.test(текст) ? "ri-close" : "";
        k.classList.remove("btn-sm", "btn-primary");
        if (значок) { k.classList.add("ri", значок); k.title = k.title || текст; k.setAttribute("aria-label", текст); }
        else k.classList.add("link");
      });
    }
    card.insertAdjacentHTML("afterbegin", `<span class="cf-ico" aria-hidden="true">${КОНФЛИКТ_ВИДЫ[вид].ico}</span>`);
    конфликтВопрос(card, (window.конфликтыДанные || new Map()).get(String(card.dataset.id)));
    конфликтСтолбец(card);
  });
  // Группы по видам, каждая свёрнута до заголовка с числом карточек и открывается щелчком; по умолчанию открыта первая
  // непустая (решение владельца 13.10.26 для обеих систем). В открытой группе — карточек по высоте окна и «Показать все»:
  // тело группы — свой список для общего правила свёртки (data-list), общий список «Конфликтов» им больше не является.
  // Прежние фильтры-вкладки по видам заменены заголовками групп — те же виды и те же числа.
  delete $list.dataset.list;
  delete $list.dataset.listItem;
  const виды = Object.keys(КОНФЛИКТ_ВИДЫ).filter(k => счёт[k]);
  // сама открывается первая непустая группа, кроме «Ждут опознания голоса» — она открывается только щелчком
  if (!виды.some(k => конфликтыОткрыты.has(k))) { конфликтыОткрыты.clear(); const перв = виды.find(k => k !== "voicewait"); if (перв) конфликтыОткрыты.add(перв); }
  const группы = виды.map(k => {
    const г = document.createElement("section");
    г.className = "cf-group";
    г.dataset.k = k;
    const открыта = конфликтыОткрыты.has(k);
    г.innerHTML = `<button type="button" class="cf-group-head" aria-expanded="${открыта}"><span class="cf-chev" aria-hidden="true">›</span>`
      + `${КОНФЛИКТ_ВИДЫ[k].label}<span class="n">${счёт[k]}</span></button>`
      + `<div class="cf-group-body" data-list="cf-${k}" data-list-item=".conflict-card"${открыта ? "" : " hidden"}></div>`;
    const тело = г.querySelector(".cf-group-body");
    карточки.filter(card => card.dataset.kindLine === k).forEach(card => тело.appendChild(card));   // обработчики кнопок — с карточкой
    г.querySelector(".cf-group-head").addEventListener("click", ev => {
      const кн = ev.currentTarget, откр = кн.getAttribute("aria-expanded") !== "true";
      кн.setAttribute("aria-expanded", String(откр));
      тело.hidden = !откр;
      if (откр) { конфликтыОткрыты.add(k); тело._поОкну?.(); } else конфликтыОткрыты.delete(k);
    });
    конфликтЗакрытьВсе(г);
    return г;
  });
  $list.replaceChildren(...группы);
  свернутьДлинныеСписки($list);
}

const _конфликтыПрежние = loadAndRenderConflicts;
loadAndRenderConflicts = async function () {          // eslint-disable-line no-global-assign
  const $list = document.getElementById("conflicts-list");
  if ($list) delete $list.dataset.lined;              // список перерисуется заново — перестроить и его
  await _конфликтыПрежние();
  перестроитьКонфликты();
};

const _страницаКонфликтов = routes.conflicts;
routes.conflicts = async (rest) => {
  await _страницаКонфликтов(rest);
  $main.querySelector(".page-sub")?.remove();          // длинная подпись — за «i» (дополнение, «Подсказки — за значком i»)
  const h = $main.querySelector("h1");
  if (h && !h.nextElementSibling?.classList.contains("tip")) {
    h.insertAdjacentHTML("beforeend", ` <span class="tip"><button type="button" class="tip-ico" aria-label="Что здесь">i</button><span class="tip-body" role="tooltip">Находки, которые нужно решить вручную: кто исполнитель, срок, голос и записи, замечания проверки, задачи без опоры в записи. По каждой — одно основное действие, остальные в «⋯».</span></span>`);
  }
};
