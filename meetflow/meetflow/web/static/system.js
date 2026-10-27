// «Система» — оформление «Линия с элементами» (одобрено владельцем 13.10.26; стенд 8020; дополнение, «Остальные экраны»).
// - Состояние службы — точка 8 px: залитая цветом текста — работает; пустая со сливовой обводкой — требует внимания;
//   неисправное всегда на виду (первым, а не под «Показать все»), рядом — ссылка «как исправить».
// - Сообщения — строками: значок (треугольник — сбой, «i» — сведения), текст, время, «Подробнее» и «Закрыть» ссылками,
//   «Закрыть все» внизу.
// - «Ожидает ввода» — строками «раздел — что ждёт — перейти».
// - Пояснения вкладок — за «i» у заголовка «Система», а не строками над содержимым.
// Данные и запросы прежние (те же адреса сервера); меняется только вид. Подключается после nav.js.

const СЛУЖБА_ТОЧКА = {
  ok: ["svc-ok", "работает"],
  bad: ["svc-bad", "требует внимания"],
  off: ["svc-off", "выключено"],
  check: ["svc-check", "проверяется"],
};

// Выравнивание вида 17.10.26 (решение владельца): состояние службы — плашкой, как у Планёрки стенда (`monState` в
// app.js: «живо» / «нет» / «выкл.» — sv-pill); прежняя замена плашки точкой стенда ERP снята.

// Вводная строка вкладки — за «i» у заголовка (см. наблюдатель ниже)
monLead = function (text) {           // eslint-disable-line no-global-assign
  return `<div class="mon-lead-tip" hidden>${esc(text)}</div>`;
};

// Где исправлять — по имени службы
const СЛУЖБА_КАК_ИСПРАВИТЬ = [
  [/^Модель/, "#models"],
  [/Папка-приёмник/, "#live?folder=1"],
  [/Очередь распознавания|Распознавание/, "#system/messages"],
  [/База данных|Автобэкап/, "#system/static"],
  [/голос/i, "#voices"],
];

const _живойМониторинг = renderMonitoringLive;
renderMonitoringLive = function () {  // eslint-disable-line no-global-assign
  _живойМониторинг();
  const $box = document.getElementById("monitoring-panel");
  const таблица = $box?.querySelector(".mon-table");
  if (!таблица) return;
  // «проверка» модели — тоже точкой
  таблица.querySelectorAll(".badge").forEach(b => { if (/проверка/.test(b.textContent)) b.className = "badge badge-neutral sv-pill"; });
  const tbody = таблица.querySelector("tbody");
  const строки = [...tbody.querySelectorAll("tr")];
  const плохие = строки.filter(tr => tr.querySelector(".svc-bad, .badge-danger"));
  плохие.reverse().forEach(tr => {
    tr.classList.add("svc-bad-row");
    tbody.insertBefore(tr, tbody.firstChild);      // неисправное — первым: «Показать все» прячет хвост, а не его
    const имя = tr.querySelector(".mon-label")?.textContent || "";
    const куда = (СЛУЖБА_КАК_ИСПРАВИТЬ.find(([re]) => re.test(имя)) || [null, "#system/messages"])[1];
    const заметка = tr.querySelector(".mon-note");
    if (заметка && !заметка.querySelector(".svc-fix")) заметка.insertAdjacentHTML("beforeend", ` <a class="svc-fix" href="${куда}">как исправить</a>`);
  });
};

// ---- Сообщения ------------------------------------------------------------------------------------------------
const ЗНАК_ВНИМАНИЕ = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>';
const ЗНАК_СВЕДЕНИЯ = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>';

// «Удалить все» технические сообщения — два подтверждения подряд (решение владельца 17.10.26, как С6 «Удалить задачу
// насовсем»). Текст одинаков в обеих системах.
async function подтвердитьУдалениеСообщений() {
  if (!(await confirmDialog(`Удалить все технические сообщения — и открытые, и закрытые?

Удаление необратимо — сообщения будут удалены из базы. Удалить?`, "Удалить все"))) return false;
  return confirmDialog(`Точно удалить насовсем? Вернуть сообщения будет нельзя.

Останутся служебные записи, на которых держится работа системы: отметки «уже предупреждали» (похожие написания, файлы не-записи в папке-приёмнике), пометки «сборка протокола не удалась» у встреч, текст задач, убранных чисткой, и сбои, из которых «Мониторинг» считает статистику. На экране их не будет.`, "Удалить насовсем");
}

// Порции списка (решение владелицы 18.10.2026): по умолчанию открытые за 7 дней, по 50; «Показать ещё» — следующие 50,
// в том числе раньше окна. Состояние живёт до следующего полного обновления списка.
let _сообщенияПоказаны = [];
loadAndRenderSystemMessages = async function (ещё = false) {   // eslint-disable-line no-global-assign
  const $box = document.getElementById("system-messages");
  if ($box && !$box.dataset.list) { $box.dataset.list = "messages"; $box.dataset.listItem = "[data-error-id]"; }
  if (!$box) return;
  let items, total = 0, порция;
  const последнее = ещё === true ? _сообщенияПоказаны[_сообщенияПоказаны.length - 1] : null;
  try {
    ({ items: порция, total } = await api(последнее
      ? `/project-status/errors?with_total=1&all_period=true&before=${encodeURIComponent(последнее.created_at)}&before_id=${последнее.id}`
      : "/project-status/errors?with_total=1", {}));
  }
  catch (e) { $box.className = "card empty-state"; $box.textContent = "Не удалось загрузить системные сообщения."; return; }
  items = _сообщенияПоказаны = последнее ? _сообщенияПоказаны.concat(порция) : порция;
  const ещёЕсть = порция.length >= 50 || !последнее;   // полная порция — дальше есть; окно кончилось — кнопка к более ранним
  if (!последнее) updateConflictsBadge({ errors: total }, { толькоНезаполненные: true });   // число — из этого же ответа (18.10.2026)
  if (!items.length) {
    $box.className = "card empty-state";
    $box.innerHTML = `<div class="reg-empty"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path class="acc" d="M9 14l2 2 4-4"/></svg><div class="reg-empty-title">Системных сообщений нет</div><div class="reg-sub">Новые появятся здесь сами.</div></div>`;
    return;
  }
  $box.className = "card sm-card";
  // Сбой — то, что пришло с технической трассой (исключение в коде); остальное — сведения о том, что система сделала сама
  const сбой = e => !!(e.traceback && e.traceback.trim());
  $box.innerHTML = (!последнее && total > items.length
      ? `<div class="sm-more reg-sub">Показаны последние ${items.length} из ${total} открытых за 7 дней.</div>` : "")
    + items.map(e => `
    <div class="sm-row" data-error-id="${e.id}">
      <span class="sm-ico ${сбой(e) ? "sm-warn" : "sm-info"}" role="img" aria-label="${сбой(e) ? "сбой" : "сведения"}">${сбой(e) ? ЗНАК_ВНИМАНИЕ : ЗНАК_СВЕДЕНИЯ}</span>
      <div class="sm-body">
        <div class="sm-text">${esc(humanizeSystemMessage(e))}</div>
        <div class="reg-sub">${esc(fmtDate(e.created_at))} · ${esc(SYSTEM_SOURCE_LABELS[e.source] || e.source)}${e.context ? " · " + esc(e.context) : ""}</div>
        <pre class="sys-details" hidden>${esc(e.message)}${e.traceback ? "\n\n" + esc(e.traceback) : ""}</pre>
      </div>
      <span class="sm-acts"><button type="button" class="link sm-more-btn">Подробнее</button><button type="button" class="link system-resolve">Закрыть</button></span>
    </div>`).join("")
    + `<div class="sm-foot">${ещёЕсть ? `<button type="button" class="link" id="sm-more-msgs" style="margin-right:16px">Показать ещё${
      items.length < 50 || последнее ? " — более ранние" : ""}</button>` : ""}<button type="button" class="link" id="sm-close-all">Закрыть все (${items.length})</button>`
    + (isSuperAdmin() ? `<button type="button" class="link sm-delete-all" id="sm-delete-all" style="margin-left:16px">Удалить все</button>` : "") + `</div>`;
  document.getElementById("sm-more-msgs")?.addEventListener("click", () => loadAndRenderSystemMessages(true));
  $box.querySelectorAll(".sm-more-btn").forEach(b => b.addEventListener("click", () => {
    const pre = b.closest(".sm-row").querySelector(".sys-details");
    pre.hidden = !pre.hidden;
    b.textContent = pre.hidden ? "Подробнее" : "Свернуть";
  }));
  const закрыть = id => api(`/project-status/errors/${id}/resolve`, { method: "POST" });
  $box.querySelectorAll(".system-resolve").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await закрыть(btn.closest("[data-error-id]").dataset.errorId); await loadAndRenderSystemMessages(); }
    catch (err) { toast(err.message, true); btn.disabled = false; }
  }));
  document.getElementById("sm-close-all")?.addEventListener("click", async (ev) => {
    const ids = items.map(e => e.id);
    if (!(await confirmDialog(`Закрыть все показанные сообщения (${ids.length})? Закрывайте, когда они разобраны.`, "Закрыть все"))) return;
    ev.target.disabled = true;
    let ошибок = 0;
    for (const id of ids) { try { await закрыть(id); } catch (e) { ошибок++; } }   // по одному: тем же путём, что «Закрыть»
    toast(ошибок ? `Закрыто ${ids.length - ошибок} из ${ids.length}` : `Закрыто: ${ids.length}`, !!ошибок);
    await loadAndRenderSystemMessages();
  });
  // «Удалить все» (решение владельца 17.10.26): насовсем, только супер-админ, два подтверждения подряд — как С6
  document.getElementById("sm-delete-all")?.addEventListener("click", async (ev) => {
    if (!(await подтвердитьУдалениеСообщений())) return;
    ev.target.disabled = true;
    try {
      const { count } = await api("/project-status/errors/delete-all", { method: "POST", json: { confirm: true } });
      toast(`Удалено сообщений: ${count}`);
    } catch (e) { toast(e.message, true); ev.target.disabled = false; }
    await loadAndRenderSystemMessages();
  });
};

// ---- Ожидает ввода ----------------------------------------------------------------------------------------------
renderAwaitingTab = async function () {   // eslint-disable-line no-global-assign
  const $box = document.getElementById("awaiting-panel");
  if (!$box) return;
  $box.className = "card empty-state";
  $box.textContent = "Загрузка…";
  let data;
  try { data = await api("/project-status/awaiting-input", {}); }
  catch (e) { $box.className = "card"; $box.textContent = `Не удалось получить список: ${e.message}`; return; }
  if (!data.groups.length) {
    $box.className = "card empty-state";
    $box.innerHTML = `<div class="reg-empty"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h9l4 4v14H6z"/><path class="acc" d="M9 14l2 2 4-4"/></svg><div class="reg-empty-title">Ничего не ждёт ответа</div><div class="reg-sub">Список обновится сам, когда что-то появится.</div></div>`;
    return;
  }
  $box.className = "card sm-card";
  $box.dataset.list = "awaiting"; $box.dataset.listItem = ".aw-row";     // общая свёртка: не больше 7 строк, остальное — «Показать все»
  $box.innerHTML = monLead(`${data.note} Всего ждёт ответа: ${data.total}.`) + data.groups.map(g => {
    const состав = (g.details || []).length ? g.details.map(d => `${esc(d.label)} — ${d.count}`).join(" · ") : "";
    const пример = (g.examples || []).length ? `например: ${g.examples.map(x => `«${esc(x)}»`).join(", ")}` : "";
    return `<div class="aw-row">
      <div class="aw-what"><b>${esc(g.title)}</b> <span class="n">${g.count}</span>
        <div class="reg-sub">${esc(g.what)}${g.oldest ? ` · самое старое — ${esc(g.oldest)}` : ""}</div>
        <div class="reg-sub">Если не ответить: ${esc(g.consequence)}${состав ? ` · ${состав}` : ""}${пример ? ` · ${пример}` : ""}</div></div>
      <a class="aw-go" href="${g.where}">${esc(g.where_text || "перейти")}</a>
    </div>`;
  }).join("") + `<div class="sm-foot"><button type="button" class="link" id="awaiting-reload">Обновить список</button></div>`;
  document.getElementById("awaiting-reload")?.addEventListener("click", renderAwaitingTab);
};

// ---- Пояснения — за «i» у заголовка «Система» ----------------------------------------------------------------------
// Вводные строки вкладок (monLead) и статичные пояснения над списками переносятся в одну подсказку у заголовка.
const ПОЯСНЕНИЯ_ВКЛАДОК = ["#system-messages-wrap > .page-sub", "#awaiting-wrap > .page-sub"];
function пояснитьЗаЗначком() {
  const h = $main.querySelector(".sys-head h1");
  if (!h) return;
  // сама строка-источник спрятана (hidden), смотрим, видна ли её панель
  const видимые = [...$main.querySelectorAll(".mon-lead-tip")].filter(el => el.parentElement && !el.parentElement.closest("[hidden]"))
    // уже спрятанное пояснение тоже считается — смотрим на его панель, иначе на следующем проходе подсказка пропадала
    .concat(ПОЯСНЕНИЯ_ВКЛАДОК.flatMap(sel => [...$main.querySelectorAll(sel)]).filter(el => el.parentElement && !el.parentElement.closest("[hidden]")));
  const текст = видимые.map(el => el.textContent.trim()).filter(Boolean).join(" ");
  видимые.forEach(el => { if (el.classList.contains("page-sub")) el.hidden = true; });
  let tip = h.querySelector(".tip");
  if (!текст) { tip?.remove(); return; }
  if (!tip) {
    h.insertAdjacentHTML("beforeend", ` <span class="tip"><button type="button" class="tip-ico" aria-label="Что на этой вкладке">i</button><span class="tip-body" role="tooltip"></span></span>`);
    tip = h.querySelector(".tip");
  }
  const тело = tip.querySelector(".tip-body");
  if (тело.textContent !== текст) тело.textContent = текст;
}
// Пояснения внутри разделов (не состояние, а «что это за раздел») — за «i» у заголовка раздела. Строки состояния
// («Система ждёт ввода…», «идёт распознавание…») остаются на виду: это данные, а не пояснение.
const ПОЯСНЕНИЕ_РАЗДЕЛА = /^(Разные очереди|Что уже разобрано|Ваши ответы на карточки|Похож ли файл)/;
function пояснитьРазделы() {
  $main.querySelectorAll(".mon-section .mon-lead:not([data-tipped])").forEach(lead => {
    if (!ПОЯСНЕНИЕ_РАЗДЕЛА.test(lead.textContent.trim())) return;
    const h3 = lead.closest(".mon-section")?.querySelector("h3");
    if (!h3) return;
    lead.dataset.tipped = "1";
    lead.hidden = true;
    h3.insertAdjacentHTML("beforeend", ` <span class="tip"><button type="button" class="tip-ico" aria-label="Что в этом разделе">i</button><span class="tip-body" role="tooltip">${esc(lead.textContent.trim())}</span></span>`);
  });
}

// Список подключений «Моделей» раскрывается своей кнопкой («Показать список — N подключений»); раскрытый — в ленте прокрутки
// (владелец 13.10.26: при раскрытии — прокрутка). Таблица лежала прямо в раскрывающемся блоке: 12 строк — 1822 px страницы.
function лентаПодключений() {
  $main.querySelectorAll(".model-book > table").forEach(t => {
    const рамка = document.createElement("div");
    рамка.className = "table-scroll model-book-scroll";
    t.parentNode.insertBefore(рамка, t);
    рамка.appendChild(t);
  });
}

let _пояснениеКадр = 0;
new MutationObserver(() => {
  if (!["system", "live", "models", "voices", "units"].includes(currentRouteParts()[0])) return;
  cancelAnimationFrame(_пояснениеКадр);
  _пояснениеКадр = requestAnimationFrame(() => { пояснитьЗаЗначком(); пояснитьРазделы(); лентаПодключений(); });
}).observe(document.getElementById("main"), { childList: true, subtree: true });

// «как исправить» у папки-приёмника — к полю пути на этой же вкладке
window.addEventListener("hashchange", () => {
  if (location.hash === "#live?folder=1") setTimeout(() => document.getElementById("watch-folder-input")?.focus(), 1500);
});
