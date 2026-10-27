// «Разбор» — одна вкладка вместо «Конфликтов», «Под вопросом» и «Возможных поручений» (решение владелицы 25.10.2026,
// вариант А исследования «Конфликты, Под вопросом, Возможные поручения — один разбор»).
//
// Файл-близнец: webapp/frontend/razbor.js и planerka/webapp/frontend/razbor.js совпадают до байта (сторож —
// scripts/proverka_zerkalnosti_pravok.py). Общие функции систем (api, esc, fmtRuDate, toast, confirmDialog, $main,
// показатьЗначки, обновитьЗначки, loadAndRenderConflicts) у обеих одинаковы по имени.
//
// Устройство. Пункт меню один, число у него — всё открытое в «Разборе» (`/badges` → razbor). Внутри — полоса видов, как
// вкладки внутри страницы, без новых пунктов меню: «Все» (по умолчанию), «Задачи», «Люди и голоса», «Проекты и
// справочники», «Договорённости», «Система». Очередь одна и идёт по влиянию на рабочий реестр, затем по сроку (сервер,
// `services/razbor.очередь`): сначала строки задач — задача под вопросом и возможное поручение («поручение или нет»,
// решения «В задачу» / «Убрать»), ниже карточки прежней очереди «Конфликтов» тем же кодом, что и раньше (кнопки, «это он»,
// группы по видам), отобранные по виду. Технические сбои — видом «Система», не скрываются и считаются в норму.
// Норма 15 — на весь «Разбор», строкой в шапке. Пакетное решение: отметить несколько строк одного вида одной встречи —
// одно решение на все (`/razbor/batch`, каждая строка решается тем же кодом, что поодиночке).
// Прежние адреса #conflicts, #pod, #possible, #registry/pod ведут сюда с нужным видом (`РАЗБОР_СТАРЫЕ_АДРЕСА`).

const ВИДЫ_РАЗБОРА = [["all", "Все"], ["tasks", "Задачи"], ["people", "Люди и голоса"], ["projects", "Проекты и справочники"],
  ["agree", "Договорённости"], ["system", "Система"]];
// Прежний адрес → вид «Разбора»: старые ссылки из «Мониторинга», писем и закладок не ломаются
const РАЗБОР_СТАРЫЕ_АДРЕСА = { conflicts: "all", pod: "tasks", possible: "tasks" };
// Отбор карточек прежней очереди по виду «Разбора»: { вид, поля } — поле карточки → вид (таблица сервера ВИД_ПОЛЯ)
var разборОтбор = null;

function адресРазбора(старый) {
  return "#razbor/" + (РАЗБОР_СТАРЫЕ_АДРЕСА[старый] || "all");
}

// Карточки прежней очереди, видные в выбранном виде; вне «Разбора» — все, как были
function отобратьДляРазбора(карточки) {
  if (!разборОтбор || разборОтбор.вид === "all" || !location.hash.startsWith("#razbor")) return карточки;
  return (карточки || []).filter(к => (разборОтбор.поля[к.field] || "tasks") === разборОтбор.вид);
}

const ЧТО_ЭТО_РАЗБОРА = { task: "Под вопросом", possible: "Возможное поручение" };

function срокСтрокиРазбора(с) {
  if (!с.expires_at) return '<span class="page-sub">без срока</span>';
  const дата = fmtRuDate(String(с.expires_at).slice(0, 10));
  // срок уже вышел — строка уйдёт при ближайшем почасовом проходе чистки; меньше суток — «истечёт завтра»
  if (new Date(с.expires_at + "Z").getTime() <= Date.now()) return `<span class="badge badge-warning" title="Срок ${esc(дата)} вышел — уйдёт по правилу своего вида при ближайшей чистке">срок вышел</span>`;
  return с.expires_tomorrow ? `<span class="badge badge-warning" title="Уйдёт по правилу своего вида ${esc(дата)}">истечёт завтра</span>`
    : `<span class="page-sub">до ${esc(дата)}</span>`;
}

function строкаЗадачиРазбора(с) {
  const встреча = с.meeting_id ? `<a href="#meetings/${с.meeting_id}">${esc(с.meeting_date ? fmtRuDate(с.meeting_date) : "встреча")}</a>` : '<span class="page-sub">—</span>';
  const ключ = `${с.source}:${с.meeting_id || ""}`;
  return `<tr data-rz-source="${с.source}" data-rz-id="${с.id}" data-rz-key="${esc(ключ)}">
    <td class="rz-pick"><input type="checkbox" class="rz-check" aria-label="Выбрать строку для пакетного решения"></td>
    <td class="c-due" data-label="Встреча">${встреча}</td>
    <td class="task-desc-cell" data-label="Формулировка"><span class="task-desc-text">${esc(с.title)}</span>${с.why ? `<span class="sub">${esc(с.why)}</span>` : ""}</td>
    <td data-label="Что это">${esc(ЧТО_ЭТО_РАЗБОРА[с.source] || с.source)}</td>
    <td data-label="Срок">${срокСтрокиРазбора(с)}</td>
    <td class="rz-act" data-label="Решение"><button class="btn-primary btn-sm rz-yes" type="button">В задачу</button>
      <button class="btn-sm rz-no" type="button">Убрать</button></td></tr>`;
}

async function решитьВРазборе(источник, номера, действие) {
  const итог = await api("/razbor/batch", { method: "POST", auth: true, json: { source: источник, ids: номера, action: действие } });
  if (итог.errors && итог.errors.length) toast(`Решено ${итог.done} из ${итог.total}. ${итог.errors.join("; ")}`, true);
  else if (номера.length > 1) toast(`Решено строк: ${итог.done}`);
  return итог;
}

async function renderRazbor(rest) {
  const вид = ВИДЫ_РАЗБОРА.some(([в]) => в === (rest || [])[0]) ? rest[0] : "all";
  const мой = location.hash;
  let д;
  try { д = await api("/razbor", { auth: true }); }
  catch (e) { $main.innerHTML = `<h1>Разбор</h1><div class="card">Не удалось получить список: ${esc(e.message)}</div>`; return; }
  if (location.hash !== мой) return;          // ушли на другой экран, пока список грузился
  _значки.razbor = д.total;
  показатьЗначки();
  разборОтбор = { вид, поля: д.fields || {} };
  const числоВида = в => в === "all" ? д.total : ((д.by_view || {})[в] || 0);
  const полоса = ВИДЫ_РАЗБОРА.map(([в, подпись]) => `<a class="rz-view${в === вид ? " rz-view-on" : ""}" href="#razbor/${в}" data-view="${в}"`
    + `${в === вид ? ' aria-current="page"' : ""}>${esc(подпись)} <span class="n">${числоВида(в)}</span></a>`).join("");
  const строки = (вид === "all" || вид === "tasks") ? (д.items || []).filter(с => с.source !== "card") : [];
  $main.innerHTML = `<div class="toolbar" id="razbor-toolbar"><span class="tb-title">Разбор</span>
      <span class="tip" tabindex="0" role="button" aria-label="Что здесь"><span class="tip-ico" aria-hidden="true">i</span><span class="tip-body" role="tooltip">Всё, что ждёт решения человека, — одной очередью: сначала то, что меняет задачи и исполнителей, затем по сроку. Строка живёт ${д.days} дней; за день до конца — «истечёт завтра», после — уходит по правилу своего вида. Несколько строк одного вида одной встречи можно решить разом: отметьте их и выберите решение. Голос решается на странице «Разбор голосов».</span></span>
      <span class="tb-spacer"></span>
      <span class="page-sub" id="razbor-norm">Открыто <b>${д.total}</b> (норма ≤ ${д.norm})${д.over ? ' <span class="badge badge-warning">больше нормы</span>' : ""}${д.expires_tomorrow ? ` · истечёт завтра: <b>${д.expires_tomorrow}</b>` : ""}</span></div>
    <nav class="rz-views" id="razbor-views" aria-label="Виды разбора">${полоса}</nav>
    ${строки.length ? `<div class="card card-output" id="razbor-tasks"><div class="rz-batch" id="rz-batch" hidden>
        <span id="rz-batch-n"></span>
        <button class="btn-primary btn-sm" id="rz-batch-yes" type="button">В задачу — выбранные</button>
        <button class="btn-sm" id="rz-batch-no" type="button">Убрать — выбранные</button>
        <span class="page-sub" id="rz-batch-hint"></span></div>
      <div class="table-scroll"><table class="agreements-table rz-table">
      <thead><tr><th></th><th>Встреча</th><th>Формулировка</th><th>Что это</th><th>Срок</th><th>Решение</th></tr></thead>
      <tbody>${строки.map(строкаЗадачиРазбора).join("")}</tbody></table></div></div>` : ""}
    ${вид === "people" ? `<div class="page-sub rz-note">${isSuperAdmin()
      ? `Подсказку голоса лучше решить на слух: «Прослушать и решить» в карточке открывает этого говорящего на странице <a href="#services/voice-review" data-rz-voice>«Разбор голосов»</a>.`
      : "Прослушать голос может суперадминистратор на странице «Разбор голосов»; без прослушивания подсказку решают кнопки карточки."}</div>` : ""}
    <div id="conflicts-list" class="card empty-state" data-list="conflicts" data-list-item=".conflict-card">Загрузка…</div>`;
  // «Разбор голосов» у систем по разным адресам: в Планёрке — вкладка «Технических служб», в ERP — свой пункт меню
  document.querySelector("[data-rz-voice]")?.setAttribute("href", адресРазбораГолосов());
  навестиСтрокиРазбора();
  await loadAndRenderConflicts();
  if (location.hash !== мой) return;
  const $list = document.getElementById("conflicts-list");
  if ($list && !$list.querySelector(".conflict-card")) {
    $list.className = строки.length ? "" : "card";
    $list.innerHTML = строки.length ? "" : `<div class="empty-state" id="razbor-empty">В этом виде открытого нет.</div>`;
    return;
  }
  упорядочитьГруппыРазбора($list, д.items || []);
  голосВКарточкахРазбора($list, д.items || []);
  пакетКарточекРазбора($list, д.items || []);
}

// Подсказка голоса → «Разбор голосов» (замечание владелицы 26.10.2026: «она никуда не ведёт, и прослушать голос не
// предлагают. Оптимально сделать пересылку на вкладку «Разбор голосов»»). Где говорящий на странице, говорит сервер
// (`golos` строки карточки: вид «На проверку» / «Опознанные и решённые» и ключ блока «проект|дата|встреча|метка»). Главное
// действие карточки — «Прослушать и решить», первым в столбце действий; «Принять» / «Оставить» остаются вторыми — решение
// без прослушивания допустимо. Материала нет (говорящий скрыт из «На проверку») — подпись «отрывка нет — решить можно
// здесь»; администратору (страница — суперадминистратора) — «прослушать может суперадминистратор». Решение на странице
// закрывает карточку само (`закрыть_разобранные_подсказки`), число в меню обновляется там же.
var голосКФокусу = null;                 // { klyuch, vid, label } — говорящий, к которому ведёт «Прослушать и решить»
const ключГолоса = (к) => [к.project, к.ref, к.meeting_key, к.label].map(x => x || "").join("|");

// «Разбор голосов» у систем по разным адресам: в Планёрке — раздел «Технических служб», в ERP — свой пункт меню
function адресРазбораГолосов() {
  return document.querySelector('[data-route="voice-review"]') ? "#voice-review" : "#services/voice-review";
}

function голосВКарточкахРазбора($list, строки) {
  строки.filter(с => с.source === "card" && с.golos).forEach(с => {
    const к = $list.querySelector(`.conflict-card[data-id="${с.id}"]`);
    const первая = к?.querySelector(".conflict-accept, .conflict-reject");
    if (!первая || к.querySelector(".rz-listen, .rz-listen-note")) return;
    const г = с.golos;
    if (г.slushat && г.vid) {
      const кн = document.createElement("button");
      кн.type = "button";
      кн.className = "btn-sm btn-primary rz-listen";
      кн.textContent = "Прослушать и решить";
      кн.title = `Открыть «${г.label}» на странице «Разбор голосов»: послушать и решить, кто это`;
      кн.addEventListener("click", () => {
        голосКФокусу = { klyuch: г.klyuch, vid: г.vid, label: г.label };
        vrВид = г.vid;
        location.hash = адресРазбораГолосов();
      });
      первая.parentNode.insertBefore(кн, первая.parentNode.firstElementChild);
      к.querySelectorAll(".conflict-accept.btn-primary").forEach(б => б.classList.remove("btn-primary"));
      return;
    }
    const подпись = document.createElement("div");
    подпись.className = "page-sub rz-listen-note";
    подпись.textContent = г.slushat ? "отрывка нет — решить можно здесь" : "прослушать может суперадминистратор";
    (к.querySelector(".cf-main") || к).appendChild(подпись);
  });
}

// На странице «Разбор голосов» — к блоку говорящего: прокрутка и подсветка на пару секунд. Не нашёлся в своём виде (правило
// успело принять его при открытии страницы или решение пришло из другой системы) — второй вид; нет и там — словами.
function подсветитьГолос() {
  const ф = голосКФокусу;
  if (!ф) return;
  if (!location.hash.includes("voice-review")) { голосКФокусу = null; return; }   // ушли со страницы, пока она грузилась
  if (!document.getElementById("vr-body")) return;
  const э = [...document.querySelectorAll("#vr-body [data-vr-key]")].find(у => у.dataset.vrKey === ф.klyuch);
  if (!э && !ф.второйВид) {
    ф.второйВид = true;
    vrВид = vrВид === "resheno" ? "proverka" : "resheno";
    renderVoiceReview();
    return;
  }
  голосКФокусу = null;
  if (!э) { toast(`«${ф.label}» на странице не найден — уже решён или отрывка нет; решить можно в «Разборе» кнопками карточки`, true); return; }
  // Показ страницы после отрисовки ставит прокрутку наверх и сворачивает длинные таблицы (решённых бывает до 300 строк) —
  // к блоку идём после этого: свёрнутую строку раскрывает «Показать все» её таблицы
  setTimeout(() => {
    if (э.hidden) э.closest("tbody")?.querySelector(".more-row button, .more-row a")?.click();
    if (э.hidden) э.hidden = false;
    э.scrollIntoView({ block: "center" });
    э.classList.add("rz-focus");
    setTimeout(() => э.classList.remove("rz-focus"), 2500);
  }, 0);
}

function сФокусомГолоса(отрисовать) {
  return async function (...аргументы) {
    await отрисовать(...аргументы);
    подсветитьГолос();
  };
}

// Одна очередь: группы карточек (их рисует прежний код системы) встают в порядке очереди сервера — по самой ранней своей
// карточке, то есть по влиянию на реестр и сроку. Внутри группы порядок и сворачивание прежние.
function упорядочитьГруппыРазбора($list, строки) {
  const место = new Map(строки.filter(с => с.source === "card").map((с, i) => [String(с.id), i]));
  const ранг = (э) => Math.min(Infinity, ...[...(э.matches?.(".conflict-card[data-id]") ? [э] : []),
    ...э.querySelectorAll(".conflict-card[data-id]")].map(к => место.get(String(к.dataset.id)) ?? Infinity));
  const группы = [...$list.children];
  if (группы.length < 2) return;
  группы.map((э, i) => [э, ранг(э), i]).sort((а, б) => а[1] - б[1] || а[2] - б[2]).forEach(([э]) => $list.appendChild(э));
}

// Пакет карточек: отметка у каждой карточки, решение — «Принять» или «Оставить как есть» на все выбранные одного вида одной
// встречи. Вид и встреча — из очереди сервера (у систем разные атрибуты карточки), сервер проверяет то же самое.
function пакетКарточекРазбора($list, строки) {
  const поНомеру = new Map(строки.filter(с => с.source === "card").map(с => [String(с.id), с]));
  const карточки = [...$list.querySelectorAll(".conflict-card[data-id]")].filter(к => поНомеру.has(String(к.dataset.id)));
  if (карточки.length < 2) return;
  карточки.forEach(к => {
    const с = поНомеру.get(String(к.dataset.id));
    к.dataset.rzKey = `card:${с.kind}:${с.meeting_id || ""}`;
    const куда = к.querySelector(".cf-main") || к;
    куда.insertAdjacentHTML("afterbegin", `<label class="rz-card-pick"><input type="checkbox" class="rz-card-check" aria-label="Выбрать карточку для пакетного решения"> в пакет</label>`);
  });
  $list.insertAdjacentHTML("beforebegin", `<div class="card rz-batch" id="rz-card-batch" hidden><span id="rz-card-n"></span>
    <button class="btn-primary btn-sm" id="rz-card-yes" type="button">Принять — выбранные</button>
    <button class="btn-sm" id="rz-card-no" type="button">Оставить как есть — выбранные</button>
    <span class="page-sub" id="rz-card-hint"></span></div>`);
  const выбранные = () => карточки.filter(к => к.querySelector(".rz-card-check")?.checked);
  const обновить = () => {
    const в = выбранные();
    document.getElementById("rz-card-batch").hidden = в.length < 2;
    const один = new Set(в.map(к => к.dataset.rzKey)).size === 1;
    document.getElementById("rz-card-n").textContent = `Выбрано карточек: ${в.length}`;
    document.getElementById("rz-card-yes").disabled = !один;
    document.getElementById("rz-card-no").disabled = !один;
    document.getElementById("rz-card-hint").textContent = один ? "" : "Пакетное решение — для карточек одного вида одной встречи";
  };
  карточки.forEach(к => к.querySelector(".rz-card-check")?.addEventListener("change", обновить));
  const пакет = (действие, слово) => async () => {
    const в = выбранные();
    if (!(await confirmDialog(`${слово} — ${в.length} карточек одной встречи?`, слово))) return;
    try { await решитьВРазборе("card", в.map(к => Number(к.dataset.id)), действие); } catch (err) { toast(err.message, true); }
    await renderRazbor(currentRouteParts().slice(1));
    обновитьЗначки();
  };
  document.getElementById("rz-card-yes").addEventListener("click", пакет("to_task", "Принять"));
  document.getElementById("rz-card-no").addEventListener("click", пакет("drop", "Оставить как есть"));
}

function навестиСтрокиРазбора() {
  const $t = document.getElementById("razbor-tasks");
  if (!$t) return;
  const перерисовать = async () => { await renderRazbor(currentRouteParts().slice(1)); обновитьЗначки(); };
  $t.querySelectorAll("tr[data-rz-id]").forEach(tr => {
    const источник = tr.dataset.rzSource, номер = Number(tr.dataset.rzId);
    tr.querySelector(".rz-yes")?.addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try { await решитьВРазборе(источник, [номер], "to_task"); } catch (err) { toast(err.message, true); }
      await перерисовать();
    });
    tr.querySelector(".rz-no")?.addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try { await решитьВРазборе(источник, [номер], "drop"); } catch (err) { toast(err.message, true); }
      await перерисовать();
    });
  });
  // Пакет: строки одного вида одной встречи (сервер проверяет то же самое)
  const $bar = document.getElementById("rz-batch");
  const выбранные = () => [...$t.querySelectorAll("tr[data-rz-id]")].filter(tr => tr.querySelector(".rz-check")?.checked);
  const обновить = () => {
    const в = выбранные();
    $bar.hidden = в.length < 2;
    const один = new Set(в.map(tr => tr.dataset.rzKey)).size === 1;
    document.getElementById("rz-batch-n").textContent = `Выбрано: ${в.length}`;
    document.getElementById("rz-batch-yes").disabled = !один;
    document.getElementById("rz-batch-no").disabled = !один;
    document.getElementById("rz-batch-hint").textContent = один ? "" : "Пакетное решение — для строк одного вида одной встречи";
  };
  $t.querySelectorAll(".rz-check").forEach(ч => ч.addEventListener("change", обновить));
  const пакет = (действие, слово) => async () => {
    const в = выбранные();
    if (!(await confirmDialog(`${слово} — ${в.length} строк одной встречи?`, слово))) return;
    try { await решитьВРазборе(в[0].dataset.rzSource, в.map(tr => Number(tr.dataset.rzId)), действие); }
    catch (err) { toast(err.message, true); }
    await перерисовать();
  };
  document.getElementById("rz-batch-yes")?.addEventListener("click", пакет("to_task", "В задачу"));
  document.getElementById("rz-batch-no")?.addEventListener("click", пакет("drop", "Убрать"));
}

// Подсветка говорящего после отрисовки «Разбора голосов» (26.10.2026). В ERP таблица адресов запомнила прежнюю функцию —
// ей отдаётся обёрнутая; в Планёрке раздел зовёт renderVoiceReview по имени.
renderVoiceReview = сФокусомГолоса(renderVoiceReview);
if (typeof routes === "object" && routes && routes["voice-review"]) routes["voice-review"] = renderVoiceReview;

// Перерисовка «Разбора» после «В задачу» / «Убрать» и пакетного решения держит прокрутку и фокус на месте (владелица
// 26.10.2026: «страница откатывается наверх каждый раз»): renderRazbor шёл мимо обёртки `сПрокруткойНаМесте` — его
// перерисовка начиналась с пустого экрана, и окно оставалось наверху. Обёртка общая (app.js), файл — близнец.
renderRazbor = сПрокруткойНаМесте(renderRazbor);
