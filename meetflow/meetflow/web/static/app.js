// Фронтенд — обычный vanilla JS, без сборки (решение 11.09.26, см. DECISIONS.md).
// Один файл: роутинг по хешу, рендер вида в #main, fetch к тому же origin.

const $main = document.getElementById("main");
// Текущий вошедший пользователь (после входа по логину и паролю — решение 19.09.26).
let me = null;
let whoamiПредупреждали = false;   // предупреждение о ненайденном выборе — один раз на страницу
// Обязателен ли вход (переключает админ, по умолчанию выключен до продуктива). Узнаём при старте.
let authRequired = false;

// --- Длинные списки — показываем первые N, остальное по кнопке ------------
// Решение 15.09.26 (пользователь): пролистывать 50 строк подряд нереально
// — любая таблица/список длиннее LONG_LIST_LIMIT строк сворачивается,
// снизу кнопка «Показать все (N)», раскрывающая остальное без перезапроса.
// Предел свёртки списков — 8 записей, не меньше 5 (указание владельца 09.10.26: «сворачивать после
// 8 записей — примени это правило к любому новому экрану; от 5 до 8 записей, зависит от доступной на
// один экран высоты, остальное сразу сворачивать»). «Или меньше» даёт расчёт по месту: список доходит
// до низа экрана и не уходит под край. Правило одно для ТАБЛИЦ и для СПИСКОВ (см. ниже).
// Порог «длинного» списка — 7: короче не сворачивается. Сколько строк показать у длинного — по высоте окна, без
// потолка (владелец 13.10.26 через «Мониторинг»: «столько, сколько помещается до нижнего края окна без прокрутки
// страницы; строка «Найдено … · Показать все» видна; не меньше 5; на высоком окне больше 7; при изменении окна —
// пересчёт»). Это уточняет прежнее «обычно не более 7 элементов списка» (13.10.26, было 8).
const LONG_LIST_LIMIT = 7;
const ЗАПАС_СНИЗУ = 40;           // воздух под карточкой, чтобы список не упирался в край
const ЗАПАС_ДО_КРАЯ = 16;         // свёрнутый список по окну: от низа карточки до края окна (13.10.26)

// Подгонка свёрнутого списка к окну по ФАКТУ, а не по средней строке: показываем записи по одной, пока низ рамки
// (карточка с «Показать все» и «Найдено …») не ниже края окна. Высота строк разная, а положение карточки на момент
// расчёта ещё не окончательное — замер, а не прогноз. `показать(n)` открывает первые n записей и прячет остальные.
function подогнатьПоОкну(рамка, всего, показать, запас = 0) {
  const край = window.innerHeight - ЗАПАС_ДО_КРАЯ - запас;
  const страница = () => document.documentElement.scrollHeight;
  let n = Math.min(всего, минимумСтрок());
  показать(n);
  // «Без прокрутки страницы»: если при пяти строках страница ещё помещается, то и дальше не должна прокручиваться —
  // под списком бывает ещё блок (свёрнутый архив протоколов), он тоже остаётся в окне. Если страница длинная и так
  // (подготовка, «Система» с несколькими таблицами), мерило — только низ своей карточки.
  const беречьСтраницу = страница() <= window.innerHeight;
  while (n < всего) {
    показать(n + 1);
    if (рамка.getBoundingClientRect().bottom > край || (беречьСтраницу && страница() > window.innerHeight)) { показать(n); break; }
    n += 1;
  }
  return n;
}
// Предел для реестров задач с описаниями (владелец 09.10.26: «в соответствующих таблицах с описанием
// сделать количество активных строк с реестрами задач 7 — тогда точно должно поместиться всё»). Речь про
// экраны, где под таблицей появляется блок полнотекстового поиска: семь строк оставляют ему место.
const ПРЕДЕЛ_РЕЕСТРА = 7;
// Нижняя граница для этих же экранов — 4, а не общие 5: строки в реестре задач бывают очень высокими
// (формулировка плюс комментарий — замер дал до 230 px), и при пяти таких строках блок поиска уходил за
// край экрана. Владелец 09.10.26 просил именно «чтобы визуально помещалась вся инфа», поиск показан — он
// и важнее седьмой строки.
const РЕЕСТР_МИНИМУМ_СТРОК = 4;
const СТРОКА_ПО_УМОЛЧАНИЮ = 70;   // пока ни одна строка ещё не отрисована
const МИНИМУМ_СТРОК = 5;          // меньше не показываем даже на низком окне
// На узком экране (до 768 px) — минимум 3 (владелец 13.10.26): пять высоких строк уводили «Показать все» ниже края окна
const УЗКИЙ_ЭКРАН = 768;
const МИНИМУМ_СТРОК_УЗКО = 3;
function минимумСтрок() { return window.innerWidth < УЗКИЙ_ЭКРАН ? МИНИМУМ_СТРОК_УЗКО : МИНИМУМ_СТРОК; }

// Сколько строк показать, чтобы список доходил до низа экрана. Постоянное число не годится: оно либо
// оставляет пустоту на большом экране, либо не помещается на маленьком (замечание владельца 02.10.26).
// Сколько строк реестра поместится вместе с блоком поиска под ним. Считаем от верха таблицы до низа
// окна, вычитая её шапку, отбивку снизу и высоту блока поиска, и делим на РЕАЛЬНУЮ высоту строки —
// поэтому на любой высоте окна выходит столько строк, сколько действительно влезает (владелец 09.10.26:
// «убедиться, что вся инфа визуально помещается»). Общий `сколькоВлезет` для этих экранов не годится: он
// считает от низа карточки, а карточка в момент расчёта ещё полная.
function сколько_строк_реестра(таблица, запас = 0) {
  if (!таблица) return ПРЕДЕЛ_РЕЕСТРА;
  const карточка = таблица.closest(".card") || таблица;
  const шапка = таблица.querySelector("thead");
  const строки = [...таблица.querySelectorAll("tbody tr")].filter(tr => !tr.classList.contains("more-row"));
  const доступно = window.innerHeight - карточка.getBoundingClientRect().top
    - (шапка ? шапка.getBoundingClientRect().height : 0) - 50 - запас;   // 50 — подвал карточки и отбивки (замер)
  // Складываем РЕАЛЬНЫЕ высоты строк, а не делим на среднюю: в реестре задач строки очень разные —
  // у одной формулировка в две строки, у другой ещё и комментарий (замер: от 85 до 230 px). Средняя
  // врала бы в обе стороны.
  let сумма = 0, помещается = 0;
  for (const строка of строки) {
    const высота = строка.getBoundingClientRect().height;
    if (высота <= 0) continue;
    if (сумма + высота > доступно) break;
    сумма += высота;
    помещается += 1;
  }
  return Math.max(минимумСтрок(), помещается);
}

function сколькоВлезет(tbody, rows, запас = 0) {
  const карточка = tbody.closest(".card") || tbody.closest("table");
  if (!карточка) return LONG_LIST_LIMIT;
  const верх = карточка.getBoundingClientRect().top;
  const шапка = tbody.closest("table")?.querySelector("thead");
  const высотаШапки = шапка ? шапка.getBoundingClientRect().height : 0;
  const видимые = rows.map(r => r.getBoundingClientRect().height).filter(h => h > 0);
  const высотаСтроки = видимые.length
    ? видимые.sort((a, b) => a - b)[Math.floor(видимые.length / 2)]
    : СТРОКА_ПО_УМОЛЧАНИЮ;
  const место = window.innerHeight - верх - ЗАПАС_СНИЗУ - высотаШапки - 45;  // 45 — строка «Показать все»
  return Math.max(минимумСтрок(), Math.floor(место / Math.max(высотаСтроки, 1)));
}

// Расчёт по месту всегда промахивается: высота строки разная (65–86 px у одного реестра), а положение
// карточки на момент расчёта ещё не окончательное. После сборки делаем один проход и довыдаём строки,
// пока под карточкой остаётся больше чем на строку свободного места (замер 02.10.26: расчёт дал 7 строк
// и 177 px пустоты, доводка — 9 и 37 px).

// Общий проход: свернуть ВСЕ длинные таблицы страницы, а не только те, которые сворачивали вручную.
// Указание владельца 05.10.26 — «единообразно для всех мониторов с окнами»: служебные разделы
// («Службы», «База голосов», «Ожидает ввода», «Прогоны») до этого не сворачивались вовсе и уходили
// простынёй на несколько экранов.
function свернутьДлинныеТаблицы(root = document) {
  const где = root && root.querySelectorAll ? root : document;
  const маршрут = (typeof currentRouteParts === "function" ? currentRouteParts().join("/") : "page");
  let номер = 0;
  где.querySelectorAll("table").forEach(table => {
    номер += 1;
    if (table.closest("[data-no-collapse]")) return;   // уже под своим «Показать список» (09.10.26)
    const tbody = table.tBodies && table.tBodies[0];
    if (!tbody) return;
    if (tbody.querySelector(".more-row, .collapse-row")) return;     // уже свёрнута — не трогаем
    const rows = [...tbody.children].filter(el => el.tagName === "TR");
    if (rows.length <= LONG_LIST_LIMIT) return;
    collapseLongTable(tbody, LONG_LIST_LIMIT, `auto-${маршрут}-${номер}`);
  });
}

// --- Свёртка длинных СПИСКОВ (не таблиц) — то же правило (владелец 09.10.26) ----------------------
//
// «На мониторинге — список с единицами встреч — сворачивать после 8 записей»; дальше это правило
// распространяется на любой экран: показываем 5–8 записей по высоте окна, остальное сразу прячем за
// кнопкой «Показать все». Экран помечает список двумя атрибутами — общий проход находит его сам, и
// новому экрану не нужен отдельный код свёртки:
//   data-list="имя"          — ключ состояния: «развёрнуто» переживает перерисовку страницы (как у таблиц);
//   data-list-item=".класс"  — что считать записью списка; без него записью считается прямой ребёнок.
// Про таблицы это уже работало (свернутьДлинныеТаблицы), про списки из блоков — нет: на «Единицах
// встречи» их бывает под три десятка, и карточка уходила на несколько экранов.

// Группа без видимых записей прячется вместе со своим заголовком: список единиц разложен по видам
// («Решение», «Договорённость»…), и пустой заголовок на экране читался бы как «здесь ничего нет».
function спрятатьПустыеГруппы(контейнер, селектор) {
  [...контейнер.children].forEach(ребёнок => {
    if (!ребёнок.classList.contains("unit-group") && !ребёнок.hasAttribute("data-list-group")) return;
    const свои = селектор ? [...ребёнок.querySelectorAll(селектор)] : [...ребёнок.children];
    ребёнок.hidden = свои.length > 0 && свои.every(з => з.hidden);
  });
}

function свернутьСписок(контейнер, записи, селектор, ключ) {
  // Сколько показать — по окну, от пяти записей (13.10.26: потолка в 7 нет); лишние пересчитываются подгонкой
  let лишние = записи.slice(минимумСтрок());
  if (!лишние.length) return;
  const рамка = контейнер.closest(".card") || контейнер;
  let кнопка = null;
  const показатьЗаписи = (n) => {
    записи.forEach((з, i) => { з.hidden = i >= n; });
    спрятатьПустыеГруппы(контейнер, селектор);
    if (кнопка) кнопка.hidden = n >= записи.length;
  };
  контейнер._поОкну = () => {
    if (!кнопка || !кнопка.isConnected) return;
    раскрытьГруппы();
    const n = подогнатьПоОкну(рамка, записи.length, показатьЗаписи);
    лишние = записи.slice(n);
  };

  const раскрытьГруппы = () => [...контейнер.children].forEach(ребёнок => {
    if (ребёнок.classList.contains("unit-group") || ребёнок.hasAttribute("data-list-group")) ребёнок.hidden = false;
  });

  function кнопкаПоказать() {
    const строка = document.createElement("div");
    строка.className = "list-more";     // по этой пометке общий проход понимает, что список уже свёрнут
    кнопка = строка;
    строка.innerHTML = `<div style="text-align:center; padding:12px 8px;"><button class="btn-sm" type="button">Показать все (${записи.length})</button></div>`;
    строка.querySelector("button").addEventListener("click", () => {
      лишние.forEach(з => { з.hidden = false; });
      раскрытьГруппы();
      строка.remove();
      if (ключ) expandedLists.add(ключ);
      кнопкаСвернуть();
    });
    контейнер.appendChild(строка);
  }

  function кнопкаСвернуть() {
    const строка = document.createElement("div");
    строка.className = "list-collapse";
    строка.innerHTML = `<div style="text-align:center; padding:8px;"><button class="btn-icon" type="button" title="Свернуть список" aria-label="Свернуть список">&#8963;</button></div>`;
    строка.querySelector("button").addEventListener("click", () => {
      лишние.forEach(з => { з.hidden = true; });
      спрятатьПустыеГруппы(контейнер, селектор);
      строка.remove();
      if (ключ) expandedLists.delete(ключ);
      кнопкаПоказать();
      контейнер._поОкну();
    });
    контейнер.appendChild(строка);
  }

  лишние.forEach(з => { з.hidden = true; });
  спрятатьПустыеГруппы(контейнер, селектор);
  if (ключ && expandedLists.has(ключ)) {         // список уже разворачивали — страница перерисовалась
    лишние.forEach(з => { з.hidden = false; });
    раскрытьГруппы();
    кнопкаСвернуть();
  } else {
    кнопкаПоказать();
    контейнер._поОкну();
  }
}

// Общий проход по всем помеченным спискам страницы — как у таблиц, вызывается после отрисовки.
function свернутьДлинныеСписки(root = document) {
  const где = root && root.querySelectorAll ? root : document;
  где.querySelectorAll("[data-list]").forEach(контейнер => {
    const уже = [...контейнер.children].some(ребёнок =>
      ребёнок.classList.contains("list-more") || ребёнок.classList.contains("list-collapse"));
    if (уже) return;                                   // уже свёрнут — не трогаем
    const селектор = контейнер.dataset.listItem || "";
    const записи = (селектор ? [...контейнер.querySelectorAll(селектор)] : [...контейнер.children])
      .filter(э => э.nodeType === 1);
    if (записи.length <= LONG_LIST_LIMIT) return;
    свернутьСписок(контейнер, записи, селектор, контейнер.dataset.list || "");
  });
}


// Раскрытый длинный СПИСОК — в своей ленте прокрутки, как таблица (владелец 13.10.26: «при раскрытии скроллинг вертикальный
// и горизонтальный, где применимо»). Раньше «Показать все» у списков из блоков просто дописывало записи в страницу. Обёртка —
// вне блока правила выше: он обязан совпадать у ERP и Планёрки.
const _свернутьСписокБезЛенты = свернутьСписок;
свернутьСписок = function (контейнер, записи, селектор, ключ) {   // eslint-disable-line no-func-assign
  _свернутьСписокБезЛенты(контейнер, записи, селектор, ключ);
  const лента = () => {
    const раскрыт = !!контейнер.querySelector(":scope > .list-collapse");
    const нужна = раскрыт && записи.length > SCROLL_STRIP_THRESHOLD;
    контейнер.classList.toggle("list-strip", нужна);
    if (!нужна) контейнер.scrollTop = 0;
  };
  лента();
  контейнер.addEventListener("click", ev => {
    // кнопка к этому моменту уже снята со страницы (обработчик кнопки убирает свою строку) — ищем по её строке
    if (ev.target.closest(".list-more, .list-collapse")) setTimeout(лента, 0);
  });
};

// Решение 17.09.26 (жалоба) — любое действие в строке (Выполнено,
// комментарий, правка) вызывает render(), который перестраивает страницу
// с нуля — список каждый раз схлопывался обратно, приходилось заново
// жать «Показать все» после любого клика. Держим состояние «развёрнуто»
// отдельно от разметки, по стабильному ключу списка (id таблицы) — оно
// переживает повторный render() того же маршрута. Сбрасывается только
// при переходе на другую вкладку — см. render(), сравнение route.
const expandedLists = new Set();

// Прокрутка переживает перерисовку (владелица 18.10.26: «после „Выполнено“ список сразу возвращается на исходную точку —
// приходится заново искать место»; то же после «Актуализировать», ✎ и любых окон правки, «Подтвердить/Снять», ответа на
// карточку). Прежде запоминалась только прокрутка окна, а раскрытый реестр прокручивается в СВОЕЙ рамке (.table-scroll,
// .scroll-pane, .list-scroll): после перерисовки рамка рождалась заново со scrollTop = 0. Теперь до перерисовки снимаются
// прокрутка окна и каждой прокрученной рамки вместе с якорем — первыми видимыми строками (номер задачи, карточки, человека),
// после — рамка находится снова и строка-якорь встаёт на прежнее место. Исчезнувшая строка (выполнена, снята, удалена)
// якорем не служит — берётся следующая. Функции одинаковы в Планёрке и ERP до знака.
const РАМКИ_ПРОКРУТКИ = ".table-scroll, .scroll-pane, .list-scroll, [data-list], .work-aside-body, .units-body";
// 26.10.2026: строки таблицы задач документа на полотне (tr[data-task]) и строки «Разбора» (tr[data-rz-id]) — тоже якоря
const СТРОКИ_ЯКОРЯ = "tr[data-task-id], .live-task-row[data-task-id], .conflict-card[data-id], tr[data-user-id], tr[data-project-id], tr[data-meeting-id], tr[data-agreement-id], .psc-task[data-id], tr[data-task], tr[data-rz-id]";
const АТРИБУТЫ_ЯКОРЯ = ["data-task-id", "data-user-id", "data-project-id", "data-meeting-id", "data-agreement-id", "data-task", "data-rz-id"];
function прокручиваемыеРамки() {
  return [...$main.querySelectorAll(РАМКИ_ПРОКРУТКИ)].filter(р => р.scrollHeight > р.clientHeight + 1);
}
function ключЯкоря(э) {
  // с именем элемента: [data-task="5"] — и строка полотна, и ссылка «решить в «Разборе»» в строке реестра (26.10.2026)
  for (const а of АТРИБУТЫ_ЯКОРЯ) if (э.hasAttribute(а)) return `${э.tagName.toLowerCase()}[${а}="${CSS.escape(э.getAttribute(а))}"]`;
  return `.${э.classList.contains("psc-task") ? "psc-task" : "conflict-card"}[data-id="${CSS.escape(э.dataset.id || "")}"]`;
}
function ключРамки(р, i) {
  const таблица = р.querySelector("table[id]");
  return [р.id || "", таблица ? таблица.id : "", р.dataset.list || "", р.className, i].join("|");
}
function якоряВидимого(рамка) {
  const верх = рамка ? рамка.getBoundingClientRect().top : 0;
  const низ = рамка ? рамка.getBoundingClientRect().bottom : window.innerHeight;
  const якоря = [];
  for (const э of (рамка || $main).querySelectorAll(СТРОКИ_ЯКОРЯ)) {
    // Якорь окна — только строка вне прокручиваемой рамки: строка в рамке едет вместе с рамкой
    if (!рамка) { const своя = э.parentElement && э.parentElement.closest(РАМКИ_ПРОКРУТКИ); if (своя && своя.scrollHeight > своя.clientHeight + 1) continue; }
    const r = э.getBoundingClientRect();
    if (r.height <= 0 || r.bottom <= верх + 1) continue;
    if (r.top >= низ) break;
    якоря.push({ ключ: ключЯкоря(э), сдвиг: r.top - верх });
    if (якоря.length >= 5) break;
  }
  return якоря;
}
function запомнитьПрокрутку() {
  const снимок = { адрес: location.hash, окно: window.scrollY, якоряОкна: window.scrollY > 0 ? якоряВидимого(null) : [], рамки: [] };
  const рамки = прокручиваемыеРамки();
  рамки.forEach((р, i) => {
    if (р.scrollTop > 0) снимок.рамки.push({ ключ: ключРамки(р, i), i, класс: р.className, top: р.scrollTop, якоря: якоряВидимого(р) });
  });
  // Строка, по которой действие, — первым якорем (26.10.2026): она и остаётся на своём месте экрана, даже если строки над ней
  // после перерисовки стали ниже или выше (сменился исполнитель — таблица пересчитала ширины колонок, замер: строка уезжала на
  // 167 px). Исчезла строка (выполнена, снята) — работают прежние якоря.
  const з = запомнитьФокус();
  const строка = з && $main.querySelector(з.ключи[0]);
  if (строка && строка.getBoundingClientRect().height > 0) {
    const р = строка.parentElement && строка.parentElement.closest(РАМКИ_ПРОКРУТКИ);
    const свояРамка = р && р.scrollHeight > р.clientHeight + 1 ? р : null;
    const верх = свояРамка ? свояРамка.getBoundingClientRect().top : 0;
    const низ = свояРамка ? свояРамка.getBoundingClientRect().bottom : window.innerHeight;
    const r = строка.getBoundingClientRect();
    if (r.bottom > верх && r.top < низ) {
      const якорь = { ключ: з.ключи[0], сдвиг: r.top - верх };
      if (!свояРамка) { if (window.scrollY > 0) снимок.якоряОкна.unshift(якорь); }
      else { const запись = снимок.рамки.find(x => x.i === рамки.indexOf(свояРамка)); if (запись) запись.якоря.unshift(якорь); }
    }
  }
  return снимок;
}
function поставитьПоЯкорю(рамка, якоря) {
  for (const я of якоря) {
    const э = (рамка || $main).querySelector(я.ключ);
    if (!э || э.getBoundingClientRect().height <= 0) continue;
    const верх = рамка ? рамка.getBoundingClientRect().top : 0;
    const сдвиг = Math.round(э.getBoundingClientRect().top - верх - я.сдвиг);
    if (рамка) рамка.scrollTop += сдвиг; else window.scrollBy(0, сдвиг);
    return true;
  }
  return false;
}
function вернутьРамки(снимок, толькоСброшенные = false) {
  if (!снимок || снимок.адрес !== location.hash) return;
  const рамки = прокручиваемыеРамки();
  снимок.рамки.forEach(з => {
    const р = рамки.find((x, i) => ключРамки(x, i) === з.ключ) || (рамки[з.i] && рамки[з.i].className === з.класс ? рамки[з.i] : null);
    if (!р || (толькоСброшенные && р.scrollTop > 0)) return;
    р.scrollTop = з.top;
    поставитьПоЯкорю(р, з.якоря);
  });
}
function вернутьПрокрутку(снимок) {
  if (!снимок || снимок.адрес !== location.hash) return;
  window.scrollTo(0, снимок.окно);
  поставитьПоЯкорю(null, снимок.якоряОкна);
  вернутьРамки(снимок);
  // Рамка, которая становится прокручиваемой уже после отрисовки (раскрытый список «Разбора» получает свою высоту следом),
  // в момент возврата ещё не прокручивается — её место возвращается следующим кадром и ещё раз чуть позже (26.10.2026:
  // «Разбор» после «В задачу» — рамка 311 → 0). Только рамки, оставшиеся в 0: прокрутку человека не перебиваем.
  if (снимок.рамки.length) {
    requestAnimationFrame(() => вернутьРамки(снимок, true));
    setTimeout(() => вернутьРамки(снимок, true), 200);
  }
}
// Свёртка и раскрытие длинных списков идут проходом через 150 мс после последней перемены страницы (наблюдатель ниже): строка
// и рамка, раскрытые этим проходом, получают место и фокус после него — `доделатьВозврат` в конце прохода, не позже 2 с.
let _отложенныйВозврат = null;
function отложитьВозврат(снимок, фокус) { _отложенныйВозврат = { снимок, фокус, до: Date.now() + 2000 }; }
function доделатьВозврат() {
  const з = _отложенныйВозврат;
  _отложенныйВозврат = null;
  if (!з || Date.now() > з.до || !з.снимок || з.снимок.адрес !== location.hash) return;
  вернутьРамки(з.снимок, true);
  вернутьФокус(з.фокус);
}
// Обёртка для перерисовок мимо render() (страница встречи после правки, «Команда», «Конфликты» после ответа): снимок до,
// возврат после. Вложенный вызов и вызов изнутри render() снимка не делают — его делает внешний.
let _прокруткаГлубина = 0;
// Прокрутка на месте после действия по строке задачи (владелица 26.10.2026: «При выборе каких-то действий по строчке задачи —
// страница откатывается наверх каждый раз… Сделать, чтобы оставалось на месте»). Причина — перерисовка экрана целиком: она
// начиналась с заставки «Загрузка…» вместо всего $main, страница на время запроса становилась в одну строку, и браузер
// сбрасывал прокрутку окна в 0; снимок 18.10.26 возвращал её только после ответа сервера, а у «Разбора» (renderRazbor мимо
// обёртки) не возвращал вовсе. Замер на стенде до правки: протокол на полотне Планёрки — scrollY 2718 → 0 на время
// перерисовки, «Разбор» — рамка списка 289–311 → 0 после действия, «Протокол» подготовки ERP — 3725 → 0 окончательно (полотно
// не ждали). Теперь на время перерисовки того же экрана: прежнее содержимое стоит до новой
// отрисовки (`заставкаЗагрузки` её не ставит), высота $main держится (`удержатьВысоту`) — прокрутка окна не обнуляется ни
// на кадр; после — снимок прокрутки и якоря, затем фокус клавиатуры на той же строке (`вернутьФокус`), исчезнувшая строка
// (выполнена, снята) отдаёт фокус соседней. Функции одинаковы в Планёрке и ERP до знака.
let _перерисовкаНаМесте = false;
function заставкаЗагрузки(html = `<div class="empty-state">Загрузка…</div>`) {
  if (_перерисовкаНаМесте && $main.firstElementChild) return;
  $main.innerHTML = html;
}
function удержатьВысоту() {
  const прежняя = $main.style.minHeight;
  $main.style.minHeight = Math.ceil($main.getBoundingClientRect().height) + "px";
  let отпущена = false;
  return () => { if (!отпущена) { отпущена = true; $main.style.minHeight = прежняя; } };
}
// Строка, по которой было последнее действие (щелчок внутри строки): окно правки уводит фокус из строки, а ответ приходит
// уже после его закрытия
let _строкаДействия = null;
function описатьСтроку(р) {
  const ключи = [ключЯкоря(р)];
  for (let с = р.nextElementSibling; с && ключи.length < 4; с = с.nextElementSibling) if (с.matches(СТРОКИ_ЯКОРЯ)) ключи.push(ключЯкоря(с));
  let п = р.previousElementSibling;
  while (п && !п.matches(СТРОКИ_ЯКОРЯ)) п = п.previousElementSibling;
  if (п) ключи.push(ключЯкоря(п));
  return { ключи, когда: Date.now() };
}
document.addEventListener("click", (e) => {
  const р = e.target && e.target.closest ? e.target.closest(СТРОКИ_ЯКОРЯ) : null;
  if (р && $main.contains(р)) _строкаДействия = описатьСтроку(р);
}, true);
function запомнитьФокус() {
  const а = document.activeElement;
  const р = а && а !== document.body && $main.contains(а) ? а.closest(СТРОКИ_ЯКОРЯ) : null;
  if (р) return описатьСтроку(р);
  return _строкаДействия && Date.now() - _строкаДействия.когда < 120000 ? _строкаДействия : null;
}
function вернутьФокус(з) {
  if (!з) return;
  const а = document.activeElement;
  if (а && а !== document.body && а.isConnected) return;      // фокус жив (поле, окно) — не перехватываем
  for (const к of з.ключи) {
    const р = $main.querySelector(к);
    if (!р || р.getBoundingClientRect().height <= 0) continue;
    const ц = [...р.querySelectorAll("button, a[href], input, select, textarea, [tabindex]")]
      .find(x => !x.disabled && x.tabIndex >= 0 && x.getBoundingClientRect().height > 0);
    if (ц) ц.focus({ preventScroll: true });
    else { if (!р.hasAttribute("tabindex")) р.setAttribute("tabindex", "-1"); р.focus({ preventScroll: true }); }
    return;
  }
}
function сПрокруткойНаМесте(fn) {
  return async function (...аргументы) {
    if (_прокруткаГлубина > 0) return fn.apply(this, аргументы);
    const снимок = запомнитьПрокрутку();
    const фокус = запомнитьФокус();
    const отпустить = удержатьВысоту();
    _прокруткаГлубина += 1;
    _перерисовкаНаМесте = true;
    try { return await fn.apply(this, аргументы); }
    finally { _прокруткаГлубина -= 1; _перерисовкаНаМесте = false; вернутьПрокрутку(снимок); отпустить(); вернутьФокус(фокус); отложитьВозврат(снимок, фокус); }
  };
}
// Строка, над которой выполнено действие, гаснет на месте до перерисовки (✓ после отсчёта отмены, 🗑, «Снять»): видно, что
// ушла именно она, а соседние строки после перерисовки остаются там, где были.
function погаситьСтроку(э) {
  const строка = э && э.closest && э.closest(СТРОКИ_ЯКОРЯ);
  if (строка) строка.classList.add("row-gone");
  return new Promise(готово => setTimeout(готово, строка ? 220 : 0));
}
// Перерисовки мимо render() держат прокрутку на месте (18.10.26, `сПрокруткойНаМесте`; объявления функций всплывают — присваивание работает и здесь, до них): протокол и страница встречи после правки, «Команда», «Конфликты» после ответа, «Единицы», «Статус».
renderMeetingProtocol = сПрокруткойНаМесте(renderMeetingProtocol);
renderMeetingDetail = сПрокруткойНаМесте(renderMeetingDetail);
renderTeam = сПрокруткойНаМесте(renderTeam);
renderTeamList = сПрокруткойНаМесте(renderTeamList);
loadAndRenderConflicts = сПрокруткойНаМесте(loadAndRenderConflicts);
renderUnitsBoard = сПрокруткойНаМесте(renderUnitsBoard);
renderStatus = сПрокруткойНаМесте(renderStatus);

// Решение 16.09.26: разворачивание «Показать все» на действительно
// длинном списке (>SCROLL_STRIP_THRESHOLD строк, например реестр
// задач — 100+) раньше просто дописывало все строки подряд, раздувая
// страницу до огромной длины. Теперь в этом случае разворачиваем не в
// саму страницу, а в собственную ленту прокрутки ограниченной высоты —
// прокручивается список, а не вся страница целиком.
const SCROLL_STRIP_THRESHOLD = 10;
const SCROLL_STRIP_MAX_HEIGHT = "480px";

// `поОкну`: null — как прежде (предел LONG_LIST_LIMIT — по месту, иначе ровно `limit`); false — ровно `limit` строк, даже если
// он равен LONG_LIST_LIMIT (страница «Под вопросом», решение владелицы 20.10.2026: «сворачивать после 7 строк»).
function collapseLongTable(tbody, limit = LONG_LIST_LIMIT, key = null, запас = 0, поОкну = null) {
  if (!tbody) return;
  // Плашка «Показать все» прежней свёртки этой таблицы (узкий экран, 14.10.26) — убрать: таблицу перерисовали
  const прежнийХозяин = tbody.closest(".table-scroll") || tbody.closest("table");
  if (прежнийХозяин && прежнийХозяин.nextElementSibling && прежнийХозяин.nextElementSibling.classList.contains("more-sticky")) {
    прежнийХозяин.nextElementSibling.remove();
  }
  const rows = Array.from(tbody.children).filter(el => el.tagName === "TR");
  const поМесту = поОкну === null ? limit === LONG_LIST_LIMIT : !!поОкну;
  // По месту — от пяти строк, дальше подгонка к окну после свёртки (13.10.26: потолка в 7 больше нет).
  if (поМесту) limit = минимумСтрок();             // на узком экране — от трёх (13.10.26, как у Планёрки)
  // Реестры с блоком поиска (владелец 09.10.26: «семь строк — тогда точно должно поместиться всё»):
  // семь — предел СВЕРХУ, а на низком окне он уточняется вниз по высоте с учётом запаса под блок поиска
  // (его высота передаётся в `запас`), иначе блок уезжает за край, а правило владельца — «от 5 до 8
  // записей, зависит от доступной на один экран высоты».
  if (запас > 0 && !поМесту) limit = Math.max(РЕЕСТР_МИНИМУМ_СТРОК, Math.min(limit, сколько_строк_реестра(tbody.closest("table"), запас)));
  if (rows.length <= limit) return;
  const extra = rows.slice(limit);
  const cols = rows[0].children.length;
  // Свёрнутый список по высоте окна (13.10.26, как у Планёрки fb363ad): строки по одной до края окна, пересчёт при
  // изменении окна и после дорисовки (подогнатьСвёрнутыеКОкну)
  let moreRow = null;
  let плашка = null;
  const рамкаТаблицы = tbody.closest(".card") || tbody.closest("table");
  const показатьСтроки = (n) => {
    rows.forEach((r, i) => { r.hidden = i >= n; });
    if (moreRow) moreRow.hidden = n >= rows.length;
    if (плашка) плашка.hidden = n >= rows.length;
  };
  // Пересчёт при изменении окна — только у свёрнутого списка (у раскрытого строки и так все)
  tbody._поОкну = () => {
    if (!поМесту || !moreRow || !moreRow.isConnected) return;
    // Рамка прокрутки 70 % окна, поставленная до свёртки, держала бы низ карточки на месте — подгонка показала бы все строки
    const рамкаПрокр = tbody.closest(".table-scroll");
    if (рамкаПрокр) { рамкаПрокр.style.maxHeight = ""; рамкаПрокр.style.overflowY = ""; }
    const n = подогнатьПоОкну(рамкаТаблицы, rows.length, показатьСтроки, запас);
    extra.length = 0;
    rows.slice(n).forEach(r => extra.push(r));
  };
  // Горизонтальная прокрутка нужна и СВЁРНУТОМУ списку (указание владельца 05.10.26): иначе на узком
  // экране правые колонки с кнопками обрезаются и до них нет никакого способа добраться. Вертикальную
  // ленту 480 px у свёрнутого списка не ставим — решение 01.10.26.
  enableHorizontalScroll(tbody);

  // Решение 01.10.26 (жалоба владельца, скрины реестра): после «Свернуть» лента прокрутки оставалась — 480px,
  // свой ползунок и отступ справа, свёрнутый список обрезался. Ленту ставим при разворачивании и снимаем при
  // сворачивании; обёртку и ползунок создаём один раз, а не при каждом разворачивании.
  let stripHost = null;
  function clearScrollStrip() {
    if (!stripHost) return;
    stripHost.style.maxHeight = "";
    stripHost.style.overflowY = "";
    stripHost.style.overflowX = "";
    stripHost.scrollTop = 0;
    stripHost.classList.remove("custom-scroll-host");
    stripHost.dispatchEvent(new Event("scroll")); // ползунок прячется сам: прокручивать нечего
  }

  function enableHorizontalScroll(tbody) {
    let host = tbody.closest(".table-scroll");
    if (!host) {
      const table = tbody.closest("table");
      host = document.createElement("div");
      host.className = "table-scroll";
      table.parentNode.insertBefore(host, table);
      host.appendChild(table);
    }
    host.style.overflowX = "auto";
  }

  function setupScrollStripIfNeeded() {
    if (rows.length <= SCROLL_STRIP_THRESHOLD) return;
    if (stripHost) {
      stripHost.classList.add("custom-scroll-host");
      stripHost.style.maxHeight = SCROLL_STRIP_MAX_HEIGHT;
      stripHost.style.overflowY = "auto";
      stripHost.style.overflowX = "auto";
      stripHost.dispatchEvent(new Event("scroll"));
      return;
    }
    let scrollHost = tbody.closest(".table-scroll");
    if (!scrollHost) {
      // Таблица без готовой обёртки .table-scroll (архив встреч,
      // команда и т.п.) — раньше здесь ставили display:block ПРЯМО на
      // <table>, а это сбивает её со `width:100%` (см. table { width:
      // 100% } в styles.css) на сжатие по контенту — баг, жалоба
      // 16.09.26 (таблица «съезжала» влево, справа пустое место).
      // Оборачиваем в свою же служебную обёртку-div вместо того, чтобы
      // портить сам элемент таблицы — тот же приём, что уже надёжно
      // работает у .table-scroll.
      const table = tbody.closest("table");
      scrollHost = document.createElement("div");
      table.parentNode.insertBefore(scrollHost, table);
      scrollHost.appendChild(table);
    }
    scrollHost.style.maxHeight = SCROLL_STRIP_MAX_HEIGHT;
    scrollHost.style.overflowY = "auto";
    scrollHost.style.overflowX = "auto"; // .table-scroll больше не задаёт это в CSS (см. styles.css) — здесь высота реальная, поэтому не ломает sticky
    attachCustomScrollThumb(scrollHost);
    stripHost = scrollHost;
  }

  function showMoreRow() {
    moreRow = document.createElement("tr");
    moreRow.className = "more-row";     // по этой пометке общий проход понимает, что список уже свёрнут
    moreRow.innerHTML = `<td colspan="${cols}" style="text-align:center; padding:12px 8px;">
      <button class="btn-sm" type="button">Показать все (${rows.length})</button></td>`;
    // Узкий экран (< 768, решение владельца 14.10.26, п. 8): «Показать все» прилипает к низу окна. Строка таблицы этого
    // не умеет, когда таблица в обёртке с прокруткой вбок (прилипание считается от обёртки, а не от окна; «Команда» на
    // 400 px шире экрана). Поэтому под обёрткой — плашка с той же кнопкой: на узком видна она, на широком — строка (CSS
    // решает, какая); одно нажатие убирает обе. Способ Планёрки 19d7f17 — в обеих системах одинаково.
    const хозяин = tbody.closest(".table-scroll") || tbody.closest("table");
    if (хозяин.nextElementSibling && хозяин.nextElementSibling.classList.contains("more-sticky")) хозяин.nextElementSibling.remove();
    плашка = document.createElement("div");
    плашка.className = "more-sticky";
    плашка.innerHTML = `<button class="btn-sm" type="button">Показать все (${rows.length})</button>`;
    хозяин.after(плашка);
    const показатьВсе = () => {
      extra.forEach(r => { r.hidden = false; });
      moreRow.remove();
      плашка.remove();
      if (key) expandedLists.add(key);
      setupScrollStripIfNeeded();
      showCollapseRow();
    };
    moreRow.querySelector("button").addEventListener("click", показатьВсе);
    плашка.querySelector("button").addEventListener("click", показатьВсе);
    tbody.appendChild(moreRow);
  }

  // Решение 17.09.26 (жалоба) — маленькая пиктограмма-подсказка «свернуть
  // обратно», доступная пока список развёрнут, а не только неявный
  // способ (например прокрутка вверх) — пользователь явно попросил
  // именно пиктограмму, не текстовую ссылку.
  function showCollapseRow() {
    const collapseRow = document.createElement("tr");
    collapseRow.className = "collapse-row";
    collapseRow.innerHTML = `<td colspan="${cols}" style="text-align:center; padding:8px;">
      <button class="btn-icon" type="button" title="Свернуть список" aria-label="Свернуть список">&#8963;</button></td>`;
    collapseRow.querySelector("button").addEventListener("click", () => {
      extra.forEach(r => { r.hidden = true; });
      collapseRow.remove();
      clearScrollStrip();
      enableHorizontalScroll(tbody);   // лента снята, но горизонтальная прокрутка нужна и свёрнутому списку
      if (key) expandedLists.delete(key);
      showMoreRow();
      tbody._поОкну();
    });
    tbody.appendChild(collapseRow);
  }

  if (key && expandedLists.has(key)) {
    extra.forEach(r => { r.hidden = false; });
    setupScrollStripIfNeeded();
    showCollapseRow();
  } else {
    extra.forEach(r => { r.hidden = true; });
    showMoreRow();
    // Доводка по окну (13.10.26): строки по одной, пока карточка вместе с «Показать все» не дошла до края окна
    if (поМесту) tbody._поОкну();
  }
}

// Решение 16.09.26 — свой ползунок прокрутки вместо стилизации
// браузерного через ::-webkit-scrollbar-thumb. Несколько попыток задать
// min-height/max-height на псевдоэлементе (в т.ч. с :vertical и
// !important) не дали устойчивого результата — на длинных списках
// (реестр задач, 100+ строк) браузер всё равно считал высоту ползунка
// пропорционально длине содержимого и результат оставался маленьким,
// хотя на списке покороче (Команда, 23 строки) естественный размер и
// без CSS уже был крупным — визуальной разницы это не убирало. Здесь
// размер и позиция полностью в своих руках — не зависит от того, как
// конкретный браузер трактует нестандартные scrollbar-псевдоэлементы.
const CUSTOM_SCROLL_THUMB_MIN_PX = 104;

function attachCustomScrollThumb(scrollHost) {
  scrollHost.classList.add("custom-scroll-host");

  // Решение 17.09.26 (корневая причина «ползунок зафиксирован сверху,
  // визуально не виден» — воспроизведено числами: при scrollTop=8000
  // ползунок реально рендерился на -7918px от видимой области, т.е.
  // физически улетал за пределы экрана). track/thumb раньше были ДЕТЬМИ
  // самого scrollHost — элемента с overflow-y:auto. position:absolute НЕ
  // освобождает от скролла собственного контейнера: браузер всё равно
  // сдвигает абсолютно позиционированного потомка вместе со scrollTop
  // родителя, как и обычный контент. Отсюда и мнимая «работоспособность»
  // перетаскивания — математика scrollTop верна, а сам видимый элемент
  // прокручивается вместе с таблицей и после первого же пикселя скролла
  // оказывается вне экрана. Правильная техника оверлей-скроллбара — держать
  // track/thumb СНАРУЖИ прокручиваемого элемента, в общем непрокручиваемом
  // предке. Оборачиваем scrollHost в отдельный wrapper и вешаем track на
  // wrapper, а не на сам scrollHost.
  const wrapper = document.createElement("div");
  wrapper.className = "custom-scroll-wrapper";
  wrapper.style.position = "relative";
  scrollHost.parentNode.insertBefore(wrapper, scrollHost);
  wrapper.appendChild(scrollHost);

  const track = document.createElement("div");
  track.className = "custom-scroll-track";
  const thumb = document.createElement("div");
  thumb.className = "custom-scroll-thumb";
  track.appendChild(thumb);
  wrapper.appendChild(track);

  function layout() {
    const trackHeight = scrollHost.clientHeight;
    const scrollable = scrollHost.scrollHeight - scrollHost.clientHeight;
    if (scrollable <= 0) { track.hidden = true; return; }
    track.hidden = false;
    const thumbHeight = Math.min(trackHeight, Math.max(CUSTOM_SCROLL_THUMB_MIN_PX, trackHeight * trackHeight / scrollHost.scrollHeight));
    thumb.style.height = thumbHeight + "px";
    const maxThumbTop = trackHeight - thumbHeight;
    const top = (scrollHost.scrollTop / scrollable) * maxThumbTop;
    thumb.style.top = top + "px";
  }
  layout();
  scrollHost.addEventListener("scroll", layout);

  let dragStartY = null, dragStartScrollTop = 0;
  // Слушатели документа — только на время перетаскивания (скорость страниц, 18.10.2026): прежде каждая свёрнутая таблица
  // навсегда вешала на document свои mousemove и mouseup, и за день переходов их копились сотни — каждое движение мыши
  // проходило через все. Теперь они снимаются при отпускании кнопки.
  const начатьПеретаскивание = () => {
    document.addEventListener("mousemove", перетаскивание);
    document.addEventListener("mouseup", отпустить);
  };
  thumb.addEventListener("mousedown", (e) => {
    dragStartY = e.clientY;
    dragStartScrollTop = scrollHost.scrollTop;
    document.body.style.userSelect = "none";
    начатьПеретаскивание();
    e.preventDefault();
  });
  // Решение 16.09.26 (баг): у track стоял pointer-events:none — кликабелен
  // был только сам ползунок (8px шириной, часто меньше высоты видимой
  // области). Клик рядом с ползунком, но не точно по нему (естественное
  // движение — ткнуть ниже, туда, куда хочешь прокрутить) не делал вообще
  // ничего, клик проваливался в таблицу под ним. Отсюда жалоба «ползунок
  // зафиксирован сверху» — на самом деле пользователь просто не мог попасть
  // именно в текущий прямоугольник ползунка. Теперь клик по пустой полосе
  // трека сразу переставляет ползунок центром на точку клика и продолжает
  // как обычное перетаскивание оттуда — так же ведёт себя нативный скроллбар.
  track.addEventListener("mousedown", (e) => {
    if (e.target === thumb) return;
    const trackHeight = scrollHost.clientHeight;
    const scrollable = scrollHost.scrollHeight - scrollHost.clientHeight;
    const thumbHeight = thumb.offsetHeight;
    const maxThumbTop = trackHeight - thumbHeight;
    if (maxThumbTop <= 0) return;
    const trackRect = track.getBoundingClientRect();
    const clickY = e.clientY - trackRect.top;
    const targetThumbTop = Math.min(maxThumbTop, Math.max(0, clickY - thumbHeight / 2));
    scrollHost.scrollTop = (targetThumbTop / maxThumbTop) * scrollable;
    layout();
    dragStartY = e.clientY;
    dragStartScrollTop = scrollHost.scrollTop;
    document.body.style.userSelect = "none";
    начатьПеретаскивание();
    e.preventDefault();
  });
  function перетаскивание(e) {
    if (dragStartY === null) return;
    const trackHeight = scrollHost.clientHeight;
    const scrollable = scrollHost.scrollHeight - scrollHost.clientHeight;
    const thumbHeight = thumb.offsetHeight;
    const maxThumbTop = trackHeight - thumbHeight;
    if (maxThumbTop <= 0) return;
    const deltaPx = e.clientY - dragStartY;
    const deltaScroll = (deltaPx / maxThumbTop) * scrollable;
    scrollHost.scrollTop = dragStartScrollTop + deltaScroll;
    // Решение 16.09.26 (баг): раньше позиция ползунка обновлялась только
    // через событие "scroll" на scrollHost — но при перетаскивании самого
    // ползунка программная установка scrollTop не всегда успевает вызвать
    // "scroll" синхронно на каждый шаг мыши, из-за чего список реально
    // прокручивался, а ползунок визуально оставался зафиксирован сверху
    // (жалоба пользователя, воспроизведено прямой отправкой mousedown/
    // mousemove/mouseup: scrollTop менялся 0 → 7114, thumb.style.top
    // оставался "0px"). Вызываем layout() напрямую, не полагаясь только
    // на "scroll".
    layout();
  }
  function отпустить() {
    dragStartY = null;
    document.body.style.userSelect = "";
    document.removeEventListener("mousemove", перетаскивание);
    document.removeEventListener("mouseup", отпустить);
  }
}

function collapseLongCardList(container, limit = LONG_LIST_LIMIT) {
  if (!container) return;
  const items = Array.from(container.children);
  if (items.length <= limit) return;
  const extra = items.slice(limit);
  extra.forEach(el => { el.hidden = true; });
  // По центру, отступ 12 px — как строка «Показать все» в других списках (14.10.26, по замечанию владельца в Планёрке
  // ec15401: там кнопка стояла у левого края; здесь было то же — блок с отступом 8px 0 у левого края карточки).
  const строка = document.createElement("div");
  строка.className = "list-more";
  строка.innerHTML = `<div style="text-align:center; padding:12px 8px;"><button class="btn-sm" type="button">Показать все (${items.length})</button></div>`;
  строка.querySelector("button").addEventListener("click", () => {
    extra.forEach(el => { el.hidden = false; });
    строка.remove();
  });
  container.appendChild(строка);
}

// --- API helper ---------------------------------------------------------

// Переходы между экранами (стенд 13.10.26, находка стенда Планёрки, проверено замером на 8020). Экраны грузятся
// асинхронно: ушли с экрана, пока шёл его запрос, — ответ приходил позже и прежний экран дорисовывался поверх нового.
// При ответе 300–600 мс и переходе «встреча → Статус» через 150 мс «Статус» затирался встречей, а затем оставался
// ПУСТЫМ: его собственный ответ писал в чужую разметку. Сверка номера показа в render() ловила только один порядок
// событий. Поэтому чтение данных, начатое до перехода, после перехода в экран не возвращается: продолжение такого
// запроса не выполняется. Изменяющие запросы (POST/PATCH/DELETE) не трогаются никогда — их итог (сообщение,
// перерисовка) нужен и после перехода. Фоновые чтения, итог которых нужен на любом экране, — с { вне_показа: true }.
let _переходов = 0;           // растёт в render() при смене адреса (не при перерисовке того же экрана)
// Тот же экран перерисовывается после действия («Сохранить» в «Актуализировать», ✓, правка), а не открыт заново — экран
// держит свой вид (дефекты экранов перед видео 25.10.2026, п. 2: вид реестра «Мои» сбрасывался на «В работе»).
let _тотЖеЭкран = false;

// --- Замок на данных задачи (19.10.26, хаос-тесты X6) ----------------------------------------------------------------
// Две одновременные правки одной задачи проходили обе: вторая молча затирала первую, «Выполнено» и «Удалить» разом
// проходили оба. Теперь сервер пишет только при совпадении версии, которую видел экран (`services/task_version.py`).
// Версии запоминаются из каждого ответа /tasks… (список, архив, найденное, сама задача, ответ на правку), и любая
// изменяющая ручка задачи получает версию сама — ни один экран (реестр, «Под вопросом», «Экран планёрки», задачи
// встречи) не забудет её передать. Отметка исполнителя («Актуализировать», /note) версию не берёт: она дописывает
// историю, а не правит поля. Отказ 409/404 — текст сервера показывает вызвавший экран, затем задача перечитывается и
// экран перерисовывается на месте (render хранит прокрутку); открытое окно правки не закрывается — после него.
const ВЕРСИИ_ЗАДАЧ = new Map();
const _ПРАВКА_ЗАДАЧИ = /^\/tasks\/(\d+)(?:\/(status|responsible|description|due-date|due|project|revert|under-question|operational))?$/;

function правкаЗадачиПуть(path, opts) {
  const метод = String(opts.method || "GET").toUpperCase();
  if (метод === "GET") return null;
  const m = _ПРАВКА_ЗАДАЧИ.exec(String(path).split("?")[0]);
  if (!m) return null;
  const id = Number(m[1]);
  const версия = ВЕРСИИ_ЗАДАЧ.get(id);
  if (версия == null) return { id, path, метод };
  if (opts.json && typeof opts.json === "object" && !Array.isArray(opts.json)) {
    if (!("version" in opts.json)) opts.json = Object.assign({}, opts.json, { version: версия });
    return { id, path, метод };
  }
  if (метод === "DELETE" || m[2] === "revert") {
    return { id, path: `${path}${String(path).includes("?") ? "&" : "?"}version=${версия}`, метод };
  }
  return { id, path, метод };
}

function запомнитьВерсииЗадач(path, данные) {
  if (!String(path).startsWith("/tasks") || !данные || typeof данные !== "object") return;
  const положить = (x) => {
    if (x && typeof x === "object" && Number.isInteger(x.id) && Number.isInteger(x.version)) ВЕРСИИ_ЗАДАЧ.set(x.id, x.version);
  };
  if (Array.isArray(данные)) { данные.forEach(положить); return; }
  положить(данные);
  (Array.isArray(данные.items) ? данные.items : []).forEach(положить);
  (Array.isArray(данные.closed_tasks) ? данные.closed_tasks : []).forEach(положить);
}

function перечитатьЗадачуПослеОтказа(id) {
  setTimeout(async () => {
    try { await api(`/tasks/${id}`); } catch (e) { ВЕРСИИ_ЗАДАЧ.delete(id); }
    const перерисовать = () => (document.querySelector(".modal-overlay") ? setTimeout(перерисовать, 400) : render());
    перерисовать();
  }, 0);
}

async function api(path, opts = {}) {
  const переход = _переходов;
  const устарел = () => (opts.method || "GET") === "GET" && !opts.вне_показа && переход !== _переходов;
  try {
    const ответ = await _apiЗапрос(path, opts);
    if (устарел()) return new Promise(() => {});
    return ответ;
  } catch (e) {
    if (устарел()) return new Promise(() => {});
    throw e;
  }
}

async function _apiЗапрос(path, opts = {}) {
  const правка = правкаЗадачиПуть(path, opts);      // замок на данных задачи (19.10.26)
  if (правка) path = правка.path;
  const headers = Object.assign({}, opts.headers || {});
  // Личность определяет сессия (HttpOnly-cookie, браузер шлёт её сам) — заголовка
  // X-User-Id больше нет. Изменяющие запросы несут защитный заголовок
  // (защита от подделки межсайтовых запросов, см. app/deps.py).
  if ((opts.method || "GET") !== "GET") headers["X-Requested-With"] = "erp-webapp";
  // Режим тестирования (вход выключен): личность — выбор в списке, как раньше.
  if (!authRequired && me) headers["X-User-Id"] = String(me.id);
  // Многопроектность MeetFlow (разрешённое отличие от ERP, 27.10.2026): выбранный проект — заголовком, 0 — «Все проекты»
  headers["X-Project-Id"] = String(выбранныйПроект());
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
  }
  // Решение 18.09.26 — обрыв соединения (fetch кидает TypeError, ответа
  // нет вовсе) раньше оставлял «Загрузка…» навсегда или голое «Failed to
  // fetch». Безопасные GET повторяются автоматически (до 2 раз, 1с и 2с
  // паузы); изменяющие запросы (POST/PATCH/DELETE) НЕ повторяются — ответа
  // нет, но сервер мог успеть выполнить действие, повтор дал бы дубль.
  const method = opts.method || "GET";
  const attempts = method === "GET" ? 3 : 1;
  let res;
  for (let i = 0; i < attempts; i++) {
    try {
      res = await fetch(path, { method, headers, body: opts.body });
      break;
    } catch (netErr) {
      if (i < attempts - 1) { await new Promise(r => setTimeout(r, 1000 * (i + 1))); continue; }
      throw new Error("Нет соединения с сервером. Проверьте подключение и повторите.");
    }
  }
  if (!res.ok) {
    if (res.status === 401 && authRequired) { showLogin("Сессия истекла — войдите снова"); throw new Error("Требуется вход"); }
    if (res.status === 403 && res.headers.get("X-Auth-Reason") === "password_change_required") {
      forcePasswordChange(); throw new Error("Сначала смените временный пароль");
    }
    if (res.status === 403 && authRequired) перечитатьПрава();     // роль могла смениться (задание 23.10.2026)
    let msg = `${res.status} ${res.statusText}`;
    let j = null;
    try {
      j = await res.json();
      // FastAPI отдаёт "detail" строкой для обычных HTTPException, но
      // массивом объектов для встроенной 422-валидации (например, нечисловой
      // {id} в пути — "/meetings/abc") — раньше это превращалось в
      // "[object Object]" в UI (решение 16.09.26, найдено хаос-тестированием).
      if (typeof j.detail === "string") msg = j.detail;
      // Без технической подкладки (находка Планёрки «30», п. 7): префикс проверки и английские сообщения — по-русски.
      else if (Array.isArray(j.detail) && j.detail.length) msg = j.detail.map(d => {
        const m = String(d.msg || "").replace(/^Value error,\s*/, "");
        if (m === "Field required") return "Не заполнено обязательное поле";
        if (/^String should have at most/.test(m)) return "Слишком длинный текст";
        if (/^String should have at least/.test(m)) return "Слишком короткий текст";
        return m || "Проверьте введённые данные";
      }).join("; ");
    } catch (e) {}
    const ошибка = new Error(msg);
    ошибка.status = res.status;
    ошибка.data = j;            // весь ответ отказа: «дата занята» несёт номер встречи (`existing_id`, 21.10.2026)
    if (правка && (res.status === 409 || res.status === 404)) перечитатьЗадачуПослеОтказа(правка.id);
    throw ошибка;
  }
  // 204 (например DELETE) приходит с телом "null" и Content-Type:
  // application/json (FastAPI/Starlette так собирают пустой ответ) — но
  // тело пустое, res.json() падает с SyntaxError. Раньше это ломало
  // успешные удаления: catch ловил ошибку парсинга вместо showing
  // success, UI не обновлялся, повторный клик по уже удалённой строке
  // давал второй, другой по смыслу 404 (решение 14.09.26, найдено живым
  // тестированием).
  if (res.status === 204) {
    if (правка && правка.метод === "DELETE") ВЕРСИИ_ЗАДАЧ.delete(правка.id);
    return null;
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    const данные = await res.json();
    запомнитьВерсииЗадач(path, данные);
    return данные;
  }
  return res;
}

function toast(message, isError) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  document.body.appendChild(el);
  // «Линия» (13.10.26): уведомление исчезает само через 2–3 с; ошибку держим дольше — её надо успеть прочитать
  setTimeout(() => el.remove(), isError ? 4000 : 2500);
}

// Решение 16.09.26 — правка задачи (текст + ответственный) раньше шла
// двумя последовательными native prompt() подряд: пользователь не
// понимал, что после первого диалога появится второй, и уходил после
// первого же «Отмена»/Enter. Один экран с обоими полями — понятнее,
// хотя и требует своей вёрстки (native prompt() умеет только одно поле).
function openModal(title, fieldsHtml, onSave) {
  // Двойной щелчок по кнопке, открывающей окно, открывал два одинаковых окна одно поверх другого (хаос-проверка 14.10.26,
  // находка Планёрки 0e79042; у ERP — «Актуализировать», «Изменить задачу», «Изменить участника»). Окна открываются часто
  // после запроса к серверу, и проверка в обработчике двойной щелчок не ловит — поэтому здесь: окно с тем же заголовком
  // заменяется, а не дублируется. Окно поверх другого окна с ДРУГИМ заголовком (подтверждение) — по-прежнему можно.
  document.querySelectorAll(".modal-overlay").forEach(прежнее => {
    if (прежнее.dataset.title === title) прежнее.remove();
  });
  const overlay = document.createElement("div");
  overlay.dataset.title = title;
  overlay.className = "modal-overlay";
  overlay.setAttribute("role", "dialog"); overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = `
    <div class="modal-card card">
      <h2 style="margin-top:0">${esc(title)}</h2>
      ${fieldsHtml}
      <div class="hstack" style="justify-content:flex-end; margin-top:12px">
        <button class="btn-sm" id="modal-cancel">Отмена</button>
        <button class="btn-primary btn-sm" id="modal-save">Сохранить</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  // Владелец 15.10.26: «по умолчанию при переходе сразу выпадает какой-то список из кэша» — подсказки автозаполнения браузера
  // (Яндекс, Chrome) с сохранёнными именами под полем «Фамилия». autocomplete="off" Chromium для полей ФИО не соблюдает,
  // а окно сразу ставит курсор в первое поле. Поле в момент фокуса — только для чтения (на нём браузер список не
  // открывает), сразу после — снова редактируемое; печатать можно сразу.
  overlay.querySelectorAll('input[autocomplete="off"]').forEach(поле => {
    поле.readOnly = true;
    поле.addEventListener("focus", () => setTimeout(() => { поле.readOnly = false; }, 0));
    // Страховка (находка Планёрки 0ec20e1): при программном фокусе событие focus приходит не всегда (встроенный браузер),
    // поле оставалось только для чтения — первая клавиша снимает запрет до того, как символ попадёт в поле
    поле.addEventListener("keydown", () => { поле.readOnly = false; });
    поле.addEventListener("blur", () => { поле.readOnly = true; });
  });
  // Таблица внутри окна тоже прокручивается: окна бывают с длинными списками (владелец 05.10.26).
  обеспечитьПрокруткуТаблиц(overlay);
  const close = () => { overlay.remove(); window.removeEventListener("hashchange", close); document.removeEventListener("keydown", onKey); };
  // Escape — на document, а не на окне: после клика по заголовку фокус уходит на страницу и окно не закрывалось (обход 02.10
  // вечер). Закрывается только верхнее окно.
  const onKey = (e) => { if (e.key === "Escape" && [...document.querySelectorAll(".modal-overlay")].pop() === overlay) close(); };
  document.addEventListener("keydown", onKey);
  // Письмо 47 Планёрки (02.10.26): окно жило в теле страницы и переживало смену экрана — висело поверх нового и сохраняло
  // оттуда. Ушли с экрана — окно закрывается.
  window.addEventListener("hashchange", close);
  // Решение 17.09.26 — закрытие по клику на фон убрано совсем: жалоба
  // (Яндекс.Браузер, только при замене УЖЕ ЗАПОЛНЕННОГО поля «Ответственный»,
  // без видимой подсказки автозаполнения) не удалось воспроизвести и
  // точно диагностировать. Это была необязательная удобная мелочь, не
  // требование — риск потери введённого текста важнее, чем эта мелочь.
  // «Отмена» остаётся единственным способом закрыть без сохранения.
  overlay.querySelector("#modal-cancel").addEventListener("click", close);
  const doSave = async () => {
    const saveBtn = overlay.querySelector("#modal-save");
    if (saveBtn.disabled) return;
    saveBtn.disabled = true;
    try {
      await onSave(overlay);
      close();
    } catch (e) {
      toast(e.message, true);
      saveBtn.disabled = false;
    }
  };
  overlay.querySelector("#modal-save").addEventListener("click", doSave);
  // Решение 17.09.26 (жалоба: Enter не сохраняет) — раньше у формы вообще
  // не было обработчика клавиш, окно не обёрнуто в <form>, поэтому Enter
  // в обычном текстовом поле по умолчанию ничего не делает. В однострочном
  // input — Enter сохраняет (как обычно ожидается от формы из одного
  // поля). В многострочном textarea Enter должен оставаться переносом
  // строки — сохраняет только Ctrl/Cmd+Enter, иначе не дать бы человеку
  // вписать многострочный текст без случайного сохранения на середине.
  overlay.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const isTextarea = e.target.tagName === "TEXTAREA";
    if (isTextarea && !(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    doSave();
  });
  return overlay;
}

// Решение 18.09.26 — замена нативного confirm(): он недоступен в части
// сред (браузерная автоматизация, встроенные окна), не стилизуется и
// блокирует поток. Возвращает Promise<boolean>. «Отмена» — единственный
// способ отказаться (клик по фону не закрывает, как и у openModal).
function confirmDialog(message, okLabel = "Продолжить") {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card card">
        <div class="page-sub" style="color: var(--text); white-space: pre-line; margin-bottom: 4px">${esc(message)}</div>
        <div class="hstack" style="justify-content:flex-end; margin-top:12px">
          <button class="btn-sm" id="confirm-cancel">Отмена</button>
          <button class="btn-primary btn-sm" id="confirm-ok">${esc(okLabel)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    // Письмо 48 Планёрки (02.10.26): окна мимо общего механизма висели при смене экрана и не закрывались Escape. Закрытие —
    // это «отменено»: иначе вызывающий код ждал бы ответа вечно.
    const done = (v) => { overlay.remove(); window.removeEventListener("hashchange", cancel); document.removeEventListener("keydown", onKey); resolve(v); };
    const cancel = () => done(false);
    const onKey = (e) => { if (e.key === "Escape") cancel(); };
    window.addEventListener("hashchange", cancel);
    document.addEventListener("keydown", onKey);
    overlay.querySelector("#confirm-cancel").addEventListener("click", () => done(false));
    overlay.querySelector("#confirm-ok").addEventListener("click", () => done(true));
    overlay.querySelector("#confirm-ok").focus();
  });
}

// Запрос собственного пароля (для выключения входа в рабочем режиме). Возвращает строку или null при отмене.
function passwordDialog(message, okLabel = "Продолжить") {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card card">
        <div class="page-sub" style="color: var(--text); white-space: pre-line; margin-bottom: 8px">${esc(message)}</div>
        <div class="field"><label>Ваш пароль <span class="req">*</span></label><input type="password" id="pwd-dialog-input" autocomplete="current-password"></div>
        <div class="hstack" style="justify-content:flex-end; margin-top:12px">
          <button class="btn-sm" id="pwd-cancel">Отмена</button>
          <button class="btn-primary btn-sm" id="pwd-ok">${esc(okLabel)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector("#pwd-dialog-input");
    const done = (v) => { overlay.remove(); window.removeEventListener("hashchange", cancel); document.removeEventListener("keydown", onKey); resolve(v); };
    const cancel = () => done(null);                 // смена экрана или Escape — «отменено» (письмо 48 Планёрки)
    const onKey = (e) => { if (e.key === "Escape") cancel(); };
    window.addEventListener("hashchange", cancel);
    document.addEventListener("keydown", onKey);
    overlay.querySelector("#pwd-cancel").addEventListener("click", () => done(null));
    overlay.querySelector("#pwd-ok").addEventListener("click", () => done(input.value || null));
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(input.value || null); });
    input.focus();
  });
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ISO YYYY-MM-DD -> ДД.ММ.ГГГГ, для заголовков. Год четырёхзначный (задача владельца 07.10.26:
// «формат датирования — день.месяц.год (DD.MM.YYYY)»): «26» на экране читается как 1926, а на экране
// даты и даты в выгрузке не должны расходиться — иначе один и тот же документ выглядит по-разному.
function fmtRuDate(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso || "";
  return `${m[3]}.${m[2]}.${m[1]}`;
}

// Дата и время — для строки «Откуда» над сгенерированным документом (решение 30.09.26). Та же
// явная зона Europe/Moscow, что у fmtDate (не полагаемся на часовой пояс браузера смотрящего —
// первая версия этой функции вытаскивала цифры из ISO-строки регэкспом без пересчёта зоны вовсе,
// час совпадал бы только у смотрящего из Москвы). Формат короче, чем у fmtDate — без секунд; год
// четырёхзначный (задача владельца 07.10.26).
function fmtRuDateTime(iso) {
  if (!iso) return "";
  const dt = new Date(iso + "Z").toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
  return dt.replace(",", " в");
}

// --- Вход по логину и паролю (решение 19.09.26) ---------------------------

let allUsers = [];
// Вся «Команда», включая записи «не подтверждён» (дефект от владелицы 20.10.2026): `allUsers` без них — для «Вы работаете
// как», а исполнителя задачи по номеру ищем здесь, иначе задача на записи «не подтверждён» стояла в реестре «user #N» и
// не попадала в отбор «Ответственный».
let всяКоманда = [];
function человекКоманды(id) {
  return всяКоманда.find(u => u.id === id) || allUsers.find(u => u.id === id) || null;
}

// ---- Форма «Фамилия / Имя / Отчество / Роль на проекте …» (Доработки 2, 20.09.26). Одно правило на сервере
// (app/services/names.problem); здесь оно повторено только ради подсказки до отправки. Один и тот же набор полей — в «Команде»
// и в окне «Уточнить ФИО или роль и подтвердить» в «Конфликтах».
const EXTERNAL_ORG_HINT = "У внешнего контакта укажите организацию и роль на проекте: по ним его отличают от тёзок из других организаций («Иван» из ТМК и «Иван» из Газпрома — разные люди).";
const EXTERNAL_ROLE_HINT = "У внешнего контакта неполное имя — так бывает, но тогда заполните «Роль на проекте», чтобы его можно было отличить от других.";
// Внешний одним словом без инициала («Кравчук», «Тимофей») — только с явным «да» и причиной (решение владелицы 24.10.2026, п. 7).
// Правило на сервере — `app/services/vneshnie_kontakty.причина_экрана`; здесь оно повторено ради подсказки до отправки.
const EXTERNAL_ONEWORD_HINT = "У внешнего контакта указано одно слово. Добавьте имя или инициал (к имени — фамилию). Если известно только это слово, отметьте «Да, известно только одно слово» и напишите причину — например, «так он подписывается в переписке».";
const ONEWORD_MIN_REASON = 5;
function внешнийОднимСловом(v) {
  const токены = [v.last, v.first, v.patr].join(" ").replace(/\([^)]*\)/g, " ").match(/[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*\.?/g) || [];
  const инициалы = токены.filter(т => т.replace(/\.$/, "").length === 1 || (т.endsWith(".") && т.replace(/\.$/, "").length <= 2));
  return токены.length - инициалы.length <= 1 && инициалы.length === 0;
}

// Выбор команды — общий для всех форм человека: «Завести», правка карандашом, «Уточнить» в «Конфликтах» (15.10.26). Подписи —
// те же, что на вкладках «Команды», чтобы было видно, куда человек попадёт после сохранения. Вид одинаков с Планёркой.
function kindSwitchHtml(p, external) {
  return `<div class="kind-switch" role="radiogroup" aria-label="Команда">
      <label class="kind-opt"><input type="radio" name="${p}-kind" id="${p}-int" value="internal"${external ? "" : " checked"}>
        <span><b>Внутренняя команда</b><span class="kind-sub">сотрудник компании</span></span></label>
      <label class="kind-opt" title="Внешнему контакту достаточно фамилии или имени, но нужны организация и роль на проекте"><input type="radio" name="${p}-kind" id="${p}-ext" value="external"${external ? " checked" : ""}>
        <span><b>Внешняя команда</b><span class="kind-sub">заказчик, контрагент, подрядчик</span></span></label>
    </div>`;
}

function identityFieldsHtml(p, v = {}, opts = {}) {
  const val = (x) => esc(x || "");
  // opts.fixedExternal (true/false): вид записи задан вкладкой «Внутренняя | Внешняя команда» (02.10.26) — флажок не нужен,
  // но остаётся скрытым полем: его читают проверка и подсказки, как и в окне «Уточнить ФИО» без вкладок.
  const fixed = typeof opts.fixedExternal === "boolean";
  const ext = fixed ? opts.fixedExternal : !!v.external;
  // Сведение 18.10.26: форма стенда (плотная, ФИО строкой, поля во всю ширину); выбор команды — двумя вариантами
  // линии локальной машины (замечание владельца 15.10.26), id «-ext» сохранён.
  // Плотная форма (владелец 14.10.26, как у Планёрки a2d52c2): признак «Внешний контакт» — плашкой сверху, ФИО в одну строку,
  // остальное парами. Поля и правила проверки прежние.
  return `
    ${fixed ? `<input type="checkbox" id="${p}-ext" hidden${ext ? " checked" : ""}>`
      : kindSwitchHtml(p, ext)}
    <div class="field-trio">
      <div class="field"><label for="${p}-last">Фамилия <span class="req" id="${p}-star-last">*</span></label>
        <input type="text" id="${p}-last" autocomplete="off" maxlength="200" placeholder="Иванов" value="${val(v.last)}"></div>
      <div class="field"><label for="${p}-first">Имя <span class="req" id="${p}-star-first">*</span></label>
        <input type="text" id="${p}-first" autocomplete="off" maxlength="200" placeholder="Пётр — полностью" value="${val(v.first)}"></div>
      <div class="field"><label for="${p}-patr">Отчество</label>
        <input type="text" id="${p}-patr" autocomplete="off" maxlength="200" placeholder="необязательно" value="${val(v.patr)}"></div>
    </div>
    <!-- Должность и роль на проекте — многострочные, во всю ширину, до 1000 знаков (замечание владельца 15.10.26, как у
         Планёрки 07fa99b); в паре остались отдел и организация -->
    <div class="field field-wide"><label for="${p}-pos">Должность</label>
      <textarea class="role-text" id="${p}-pos" rows="3" maxlength="1000" placeholder="например, «Менеджер»">${val(v.position)}</textarea></div>
    <div class="field field-wide"><label for="${p}-prole">Роль на проекте <span class="req" id="${p}-star-role" hidden>*</span></label>
      <textarea class="role-text" id="${p}-prole" rows="3" maxlength="1000" placeholder="чем занят в наших проектах">${val(v.projectRole)}</textarea></div>
    <div class="field-pair">
      <div class="field"><label for="${p}-dept">Отдел</label>
        <input type="text" id="${p}-dept" autocomplete="off" maxlength="200" value="${val(v.department)}"></div>
      <div class="field"><label for="${p}-org">Организация <span class="req" id="${p}-star-org" hidden>*</span></label>
        <input type="text" id="${p}-org" autocomplete="off" maxlength="200" placeholder="для внешнего контакта" value="${val(v.organization)}"></div>
    </div>
    <!-- Внешний одним словом — явное «да» и причина (решение владелицы 24.10.2026, п. 7); видно, только когда нужно -->
    <div class="field field-wide" id="${p}-oneword-box" hidden>
      <label><input type="checkbox" id="${p}-oneword"${v.nameShortReason ? " checked" : ""}> Да, известно только одно слово</label>
      <input type="text" id="${p}-oneword-why" autocomplete="off" maxlength="300" placeholder="причина — например, «так он подписывается в переписке»" value="${val(v.nameShortReason)}">
    </div>
    <div class="form-hint" id="${p}-hint" role="status" hidden></div>`;
}

function readIdentityForm(p) {
  const g = (k) => (document.getElementById(`${p}-${k}`)?.value || "").trim().replace(/\s+/g, " ");
  const v = { last: g("last"), first: g("first"), patr: g("patr"), projectRole: g("prole"), position: g("pos"), department: g("dept"),
              organization: g("org"), external: !!document.getElementById(`${p}-ext`)?.checked,
              onewordOk: !!document.getElementById(`${p}-oneword`)?.checked, onewordWhy: g("oneword-why") };
  v.fullName = [v.last, v.first, v.patr].filter(Boolean).join(" ");
  // причина уходит на сервер, только если отмечено «да» и запись действительно одним словом (24.10.2026)
  v.nameShortReason = v.external && v.onewordOk && внешнийОднимСловом(v) ? v.onewordWhy : "";
  return v;
}

// Возвращает подсказку (что именно дописать и почему) или null, если запись можно сохранять.
function identityProblem(v) {
  const bad = /[\d_@#%*=+<>\/\\|\[\]{}()!?;:"«»]/;
  if (bad.test([v.last, v.first, v.patr].join(" "))) return "В имени не должно быть цифр и служебных знаков — только буквы.";
  if (v.external) {
    if (!v.last && !v.first) return "Укажите хотя бы фамилию или имя контакта.";
    if (!v.projectRole || !v.organization) return EXTERNAL_ORG_HINT;
    if (внешнийОднимСловом(v) && (!v.onewordOk || (v.onewordWhy || "").length < ONEWORD_MIN_REASON)) return EXTERNAL_ONEWORD_HINT;
    return null;
  }
  if (!v.last && !v.first && !v.patr) return "Укажите фамилию и имя сотрудника (либо фамилию и роль на проекте).";
  if (/^(?:[А-ЯЁA-Z]\.){1,2}$/.test(v.first) || /^[А-ЯЁA-Z]$/.test(v.first))
    return /^А\.?$/.test(v.first)
      ? `Вместо инициала «${v.first}» укажите имя полностью: «${v.last} ${v.first}» — это и Алексей, и Андрей.`
      : `Вместо инициала «${v.first}» укажите имя полностью: по одному инициалу человека не отличить от однофамильца.`;
  if (v.last && !v.first) {
    // Решение владельца 05.10.26: фамилия без имени допустима, если заполнена роль на проекте — так
    // приходит из записей встреч («Петрукевич»), и роль на проекте отличает человека от однофамильца.
    // Без роли запись не принимаем и просим дозавести имя ИЛИ роль — то же правило, что на сервере.
    return v.projectRole ? null
      : "Добавьте имя или роль на проекте: по одной фамилии человека не отличить от однофамильца, а роль на проекте отличает.";
  }
  if (!v.last) return "Добавьте фамилию: одно имя (и имя с отчеством) может совпасть у нескольких сотрудников.";
  return checkFullName(v.fullName);
}

// Живая подсказка и «живые» звёздочки: у внешнего контакта с неполным именем звёздочка появляется у «Роли на проекте»,
// а у уже заполненного из «Фамилия»/«Имя» снимается со второго поля.
function wireIdentityHints(p) {
  const el = (k) => document.getElementById(`${p}-${k}`);
  const update = () => {
    const v = readIdentityForm(p);
    const anyName = !!(v.last || v.first);
    // У сотрудника звёздочка «Имя» снимается, если заполнена роль на проекте: фамилия + роль
    // достаточно (решение владельца 05.10.26). Тогда же подсвечивается «Роль на проекте» — она и
    // есть вторая половина правила «имя ИЛИ роль».
    const roleAsSecond = !v.external && !!v.last && !v.first;
    el("star-last").hidden = v.external ? anyName : false;
    el("star-first").hidden = v.external ? anyName : !!v.projectRole;
    el("star-role").hidden = !(v.external || roleAsSecond);
    el("star-org").hidden = !v.external;
    const box = el("oneword-box");
    if (box) box.hidden = !(v.external && (v.last || v.first) && внешнийОднимСловом(v));   // 24.10.2026
    const problem = identityProblem(v);            // и при пустой форме: «Укажите фамилию и имя сотрудника.»
    const hint = el("hint");
    hint.hidden = !problem;
    hint.textContent = problem || "";
  };
  ["last", "first", "patr", "prole", "pos", "dept", "org", "oneword-why"].forEach(k => el(k)?.addEventListener("input", update));
  el("oneword")?.addEventListener("change", update);
  el("ext").addEventListener("change", update);
  el("int")?.addEventListener("change", update);        // у переключателя второй вариант — своё событие (15.10.26)
  // Решение 22.09.26: подсказку при первой отрисовке показываем, только если форма уже пришла с данными
  // (окно «Уточнить» для существующей неполной записи) — на пустой форме нового участника подсказка
  // «Укажите фамилию и имя» не должна появляться раньше, чем человек хоть что-то ввёл (найдено на скриншоте).
  const initial = readIdentityForm(p);
  const hasData = initial.last || initial.first || initial.patr || initial.projectRole || initial.position || initial.department
    || (initial.external && !el("ext").hidden);
  if (hasData) {
    update();
  } else {
    // Внешнему контакту обязательна фамилия ИЛИ имя (+ роль при неполном имени) — звёздочек у полей нет, правило в пояснении.
    el("star-last").hidden = initial.external;
    el("star-first").hidden = initial.external;
    el("star-role").hidden = !initial.external;
    el("star-org").hidden = !initial.external;
    el("hint").hidden = true;
  }
  return update;
}

function showIdentityHint(p, text) {
  const hint = document.getElementById(`${p}-hint`);
  if (hint) { hint.hidden = false; hint.textContent = text; }
}

const COMMON_FIRST_NAMES = new Set(["артём", "артем", "иван", "пётр", "петр", "сергей", "андрей", "алексей", "дмитрий", "михаил", "николай", "максим", "егор",
  "игорь", "олег", "антон", "кирилл", "денис", "виктор", "владимир", "станислав", "константин", "роман", "юрий", "илья", "павел", "евгений", "александр",
  "мария", "анна", "елена", "ольга", "татьяна", "наталья", "ирина", "светлана", "юлия", "анастасия", "екатерина", "оксана", "людмила", "марина", "юля",
  "настя", "света", "маша", "катя", "оля", "костя", "саша", "женя", "миша", "дима"]);

// Решение владельца 24.09.26 (реальный случай — «Антону Дмитриевичу», дательный падеж): та же
// логика, что и app/services/draft_guards.py::guess_nominative (питоновский и JS-варианты
// поддерживаются как общий, параллельно реализованный на двух языках хелпер — не общий код,
// общее ПРАВИЛО). Подстановка принимается, только если результат есть в `known` (словоформы
// ФИО из «Команды проекта») — иначе нельзя надёжно отличить уже именительный женский падеж
// («Марина» и так оканчивается на «-а») от родительного мужского («Антона» → «Антон»).
const NOM_ENDINGS = [
  ["ом", ""], ["ем", "ь"],
  ["ой", "а"],
  ["у", ""], ["у", "а"],
  ["ю", ""], ["ю", "ь"],
  ["а", ""],
  ["я", ""], ["я", "ь"],
  ["е", "а"],
  ["ы", "а"],
  ["и", "я"],
];

function guessNominative(word, known) {
  const w = (word || "").trim();
  if (w.length < 3) return word;
  const wl = w.toLowerCase().replace(/ё/g, "е");
  if (known.has(wl)) return word;
  for (const [suffix, replacement] of NOM_ENDINGS) {
    if (!wl.endsWith(suffix)) continue;
    const guess = wl.slice(0, wl.length - suffix.length) + replacement;
    if (guess.length >= 2 && known.has(guess)) return guess.charAt(0).toUpperCase() + guess.slice(1);
  }
  return word;
}

// Строит множество известных словоформ ФИО (фамилия/имя/отчество каждого) из «Команды проекта» — база
// для guessNominative: угадывать падеж есть смысл, только сверяясь с реальными именами в команде.
function rosterNameTokens(users) {
  const known = new Set();
  for (const u of users || []) {
    for (const part of (u.full_name || "").split(/\s+/)) {
      if (part) known.add(part.toLowerCase().replace(/ё/g, "е"));
    }
  }
  return known;
}

function splitPersonName(name, known) {
  const raw = (name || "").trim().split(/\s+/).filter(Boolean);
  if (!raw.length) return {};
  const norm = known ? raw.map(w => guessNominative(w, known)) : raw;
  if (raw.length === 1) {
    // одно слово: известное имя → «Имя», иначе (по умолчанию) → «Фамилия» — так, например, «Швец» не попадает в поле «Имя»
    return COMMON_FIRST_NAMES.has(norm[0].toLowerCase()) ? { first: norm[0] } : { last: norm[0] };
  }
  // Классификация по содержанию (падеж уже снят в norm), а не по позиции слова во фразе —
  // раньше первое слово ВСЕГДА шло в «Фамилия», второе — в «Имя», даже когда по факту было
  // наоборот («Антону Дмитриевичу» — имя и отчество без фамилии вообще).
  const roles = norm.map(w => {
    if (isPatronymic(w)) return "patr";
    if (COMMON_FIRST_NAMES.has(w.toLowerCase())) return "first";
    return null;
  });
  if (roles.some(r => r)) {
    const patr = norm.filter((_, i) => roles[i] === "patr").map(patronymicNominative).join(" ") || undefined;
    const firstIdx = roles.indexOf("first");
    const first = firstIdx >= 0 ? norm[firstIdx] : undefined;
    const last = norm.filter((_, i) => roles[i] !== "patr" && i !== firstIdx).join(" ") || undefined;
    return { last, first, patr };
  }
  // Ничего не классифицировалось по содержанию — прежнее поведение по умолчанию (позиционно).
  if (raw.length >= 3) return { last: norm[0], first: norm[1], patr: norm.slice(2).join(" ") };
  return { last: norm[0], first: norm[1] };
}

// Проверка ФИО (зеркало app/services/names.py, решение 20.09.26): обязательны Фамилия и Имя. Возвращает подсказку или null.
const NAME_FORMAT_HINT = "Укажите Фамилию и Имя, например: «Иванова Мария» (отчество можно добавить третьим словом).";
// Решение владельца 24.09.26: отчество узнаётся по своему суффиксу («-вич», «-вна»…) даже в
// падеже, который сам по себе не совпал ни с одним словом «Команды проекта» (guessNominative
// не может угадать то, чего в базе вообще нет — например, отчество не заведено на карточке
// сотрудника). Суффикс отчества — закрытый, устойчивый список окончаний, поэтому короткий
// падежный хвост после него («-у», «-а», «-ем», «-е»…) можно снять без обращения к «Команде».
const PATRONYMIC_RE = /(вич|ьич|вна|чна|ична|инична|оглы|кызы)([ауеыи]|ом|ем|ой)?$/i;
function isPatronymic(w) { return PATRONYMIC_RE.test(w || ""); }
// Отчество «по существу» — суффикс СРАЗУ ПОСЛЕ корня известного имени, то же правило, что на сервере
// (`app/services/names.py`). Проверки по одному окончанию мало: фамилии «Петрукевич», «Абрамович»
// оканчиваются на «-евич» и принимались за отчество — из-за этого форма отвергала верный ввод
// «Петрукевич Алексей» с подсказкой про порядок слов (найдено 05.10.26 по живому скриншоту).
// Алгоритм намеренно повторяет серверный: подсказка до отправки и ответ API должны совпадать.
const PATRONYMIC_ROOTS = ["александр", "алексе", "анатол", "андре", "антон", "аркад", "артем", "артур", "борис",
  "вадим", "валент", "валер", "васил", "виктор", "витал", "владимир", "владислав", "вячеслав", "геннад", "георг",
  "григор", "денис", "дмитри", "евген", "егор", "иван", "игор", "иль", "кирилл", "константин", "леонид", "льв",
  "макс", "михайл", "михал", "никит", "никола", "олег", "павл", "петр", "роман", "руслан", "семен", "серге",
  "станислав", "степан", "тимур", "тимофе", "федор", "эдуард", "юр", "яковл", "ярослав", "кузьм", "лук", "фом"];
const PATRONYMIC_END_RE = /(?:ович|евич|ьич|ич|овна|евна|ична|инична)$/i;
function isPatronymicWord(w) {
  const word = (w || "").trim();
  if (/(?:оглы|кызы)$/i.test(word)) return true;
  const low = word.toLowerCase().replace(/ё/g, "е").replace(/ъ/g, "ь");
  if (low.length <= 5) return false;
  const m = PATRONYMIC_END_RE.exec(low);
  if (!m) return false;
  const stem = low.slice(0, m.index);
  return PATRONYMIC_ROOTS.some(r => stem === r || (stem.length >= 3 && (r.startsWith(stem) || stem.startsWith(r))));
}
// Отчество в именительном падеже — суффикс сам себе граница, падежный хвост после него просто
// отбрасывается (без сверки с «Командой», см. isPatronymic выше): «Дмитриевичу» → «Дмитриевич».
function patronymicNominative(w) {
  const m = PATRONYMIC_RE.exec(w || "");
  return m && m[2] ? w.slice(0, w.length - m[2].length) : w;
}
function checkFullName(text) {
  const t = (text || "").trim().replace(/\s+/g, " ");
  if (!t) return "Введите ФИО. " + NAME_FORMAT_HINT;
  if (/[\d_@#%*=+<>\/\|\[\]{}()!?;:"«»]/.test(t)) return "В имени не должно быть цифр и служебных знаков — только буквы. " + NAME_FORMAT_HINT;
  if (/(?:^|\s)(?:отдел|служба|группа|управление|департамент|команда|дирекция|бухгалтерия|производство|закупки|склад|ото|ит)(?:\s|$)/i.test(t))
    return "Похоже, это название отдела или группы, а не человека. Команда проекта — это люди: " + NAME_FORMAT_HINT;
  const w = t.split(" ");
  if (w.length === 1) return "Одного слова недостаточно: по одной фамилии или одному имени человека не отличить от однофамильцев и тёзок. " + NAME_FORMAT_HINT;
  if (/^(?:[А-ЯЁA-Z]\.){1,2}$/.test(w[1])) return "Вместо имени указаны инициалы — напишите имя полностью. " + NAME_FORMAT_HINT;
  if (!w.every(x => /^[А-ЯЁA-Z][а-яёa-z]+(?:-[А-ЯЁA-Z][а-яёa-z]+)?$/.test(x))) return "Каждое слово должно начинаться с заглавной буквы и состоять только из букв. " + NAME_FORMAT_HINT;
  if (w.length > 3) return "Слишком много слов. " + NAME_FORMAT_HINT;
  // isPatronymicWord — строгая проверка (корень + суффикс). Прежняя проверка по одному окончанию
  // принимала за отчество фамилии на «-евич» и отвергала верный ввод.
  if (isPatronymicWord(w[0]) || (isPatronymicWord(w[1]) && !isPatronymicWord(w[0]))) return "Похоже, указаны имя и отчество без фамилии (или другой порядок слов). Порядок: Фамилия Имя [Отчество]. " + NAME_FORMAT_HINT;
  return null;
}

async function loadUsersForWhoAmI() {
  let список;
  try {
    список = await api("/users", { вне_показа: true });
  } catch (e) {
    // Сбой запроса список НЕ очищает: раньше здесь стояло `allUsers = []`, и мигнувшая сеть (или
    // перезапуск сервера) обнуляла список людей — вместе с ним молча пропадал выбор в «Вы работаете
    // как» и права (09.10.26). Нет свежих данных — работаем с прежними.
    return;
  }
  if (!Array.isArray(список)) return;                     // ответ не список — выбор и список не трогаем
  всяКоманда = список.slice();
  allUsers = список.filter(u => u.is_confirmed !== false && u.is_active !== false);   // неподтверждённые контакты не входят в «Вы работаете как»
  if (typeof fillWhoAmI === "function") fillWhoAmI();
  // Рабочий режим: роль вошедшего — из свежего списка «Команды», как `currentUser` Планёрки, а не из ответа входа,
  // запомненного один раз (задание 23.10.2026: смена роли не убирала пункты суперадминистратора до перезагрузки)
  if (authRequired && me) {
    const свежий = всяКоманда.find(u => String(u.id) === String(me.id));
    if (свежий && свежий.access_role && свежий.access_role !== me.access_role) me = Object.assign({}, me, { access_role: свежий.access_role });
  }
  if (typeof применитьМенюПоРоли === "function") применитьМенюПоРоли();
}

// Что делать с прежним выбором в «Вы работаете как», когда список людей только что загрузился
// (09.10.26). Отдельной функцией — чтобы правило проверялось тестом без браузера:
//   • человек есть в списке — показываем его (обычный случай);
//   • человека в списке нет — выбор СОХРАНЯЕМ и говорим об этом (вариантом «нет в списке команды»),
//     а не сбрасываем молча: прежний код возвращал поле к «— не выбран —» и терял права.
function whoamiРешение(прежний, users, запомненнаяМетка) {
  const id = String(прежний || "");
  if (!id) return { значение: "", вариант: "", предупредить: false };
  if (users.some(u => String(u.id) === id)) return { значение: id, вариант: "", предупредить: false };
  // Человека в свежем списке нет — выбор СОХРАНЯЕМ и говорим об этом словами. Метка из памяти точнее;
  // если её ещё не успели запомнить (выбор сделан до 09.10.26), всё равно показываем вариант — пустое
  // поле читалось бы как «ничего не выбрано», а права при этом терялись молча.
  const метка = запомненнаяМетка || "Выбранный человек";
  return { значение: id, вариант: `${метка} — нет в списке команды`, предупредить: true };
}

// Прокрутка таблиц (указание владельца 05.10.26: «в окнах с большими таблицами везде сделать
// горизонтальный и вертикальный скроллинг»). Проверяем ФАКТ: таблица шире своего места — включаем
// горизонтальную прокрутку; выше 70 % экрана — вертикальную с ограничением высоты. Ограничение нужно
// именно вместе с горизонтальной: без него «прилипший» заголовок цепляется к рамке, а не к экрану, и
// уезжает вместе со страницей (это и было причиной, по которой прокрутку отсюда когда-то убрали).
const TABLE_SCROLL_MAX_HEIGHT = "70vh";

function обеспечитьПрокруткуТаблиц(root = document) {
  const где = root && root.querySelectorAll ? root : document;
  где.querySelectorAll("table").forEach(table => {
    if (table.classList.contains("mon-table")) return;          // служебные таблицы панелей — своя логика ширин
    if (table.closest(".doc-content")) return;                  // текст документа, не таблица данных
    let host = table.parentElement && table.parentElement.classList.contains("table-scroll")
      ? table.parentElement : null;
    const ширинаМеста = host ? host.clientWidth : table.clientWidth;
    const нужнаГоризонталь = table.scrollWidth > ширинаМеста + 2;
    // Свёрнутый список (есть строка «Показать все») высоту уже держит свёртка — рамка ему не нужна: при строках выше прежних
    // (значки 36 px, 13.10.26) она обрезала кнопку «Показать все». Прокрутка в рамке — только раскрытому (Планёрка c066c81).
    const свёрнута = !!table.querySelector("tr.list-more, tr.more-row");
    if (свёрнута && host) { host.style.maxHeight = ""; host.style.overflowY = ""; }
    const нужнаВертикаль = !свёрнута && table.offsetHeight > window.innerHeight * 0.7;
    // Прокрутку вбок снимаем, когда она больше не нужна (14.10.26): прежде она только ставилась — реестр на 400 px держал
    // overflow-x:auto, поставленный при прежней ширине, хотя таблица влезала (330 = 330). Рамка с overflow — свой
    // контейнер прокрутки, и строка «Показать все» прилипала к нему, а не к низу окна (решение владельца 14.10.26, п. 8).
    if (host && !нужнаГоризонталь) host.style.overflowX = "";
    if (!нужнаГоризонталь && !нужнаВертикаль) return;
    if (!host) {
      // Таблица без обёртки (архив встреч, «Команда» и т.п.): оборачиваем в div, а НЕ ставим
      // display:block на саму таблицу — от этого она теряет width:100 % и «съезжает» влево.
      host = document.createElement("div");
      host.className = "table-scroll";
      table.parentNode.insertBefore(host, table);
      host.appendChild(table);
    }
    if (нужнаГоризонталь) host.style.overflowX = "auto";
    if (нужнаВертикаль) {
      host.style.maxHeight = TABLE_SCROLL_MAX_HEIGHT;
      host.style.overflowY = "auto";
    }
  });
}

// Пересчёт при изменении окна: на узком экране таблица перестаёт помещаться, и без пересчёта
// прокрутки не появится — а именно её владелец и просил.
let _таблицыПрокруткаТаймер = null;
// Свёрнутые списки — по высоте окна (13.10.26): сколько строк помещается, столько и видно. Пересчёт и при изменении окна,
// и после дорисовки: блок над списком догружается позже свёртки («Система»: карточка служб), и подгонка, сделанная раньше,
// оставляла последнюю строку за краем (замер 1280×1024: 80 px). Подгонка меняет только `hidden` — наблюдатель её не ловит.
function подогнатьСвёрнутыеКОкну() {
  // Пересчёт по окну прокрутку списка не трогает (18.10.26): он зовётся и таймерами — значки раз в 60 с меняют DOM
  document.querySelectorAll("tbody, [data-list], .cf-list, .cf-group, #voice-pending, #live-tasks-list").forEach(э => {
    if (!э._поОкну) return;
    const было = э.scrollTop;
    э._поОкну();
    if (э.scrollTop !== было) э.scrollTop = было;
  });
}
window.addEventListener("resize", () => {
  clearTimeout(_таблицыПрокруткаТаймер);
  _таблицыПрокруткаТаймер = setTimeout(() => {
    подогнатьСвёрнутыеКОкну();
    обеспечитьПрокруткуТаблиц();
    свернутьДлинныеТаблицы();
    свернутьДлинныеСписки();
  }, 150);
});
// Любая новая таблица на экране — окно, подгрузка списка, обновление панели — тоже повод пересчитать
// прокрутку, а не только отрисовка страницы: мест, где появляется таблица, много, и каждое легко
// забыть. Наблюдатель срабатывает часто, поэтому пересчёт отложен (владелец 05.10.26).
new MutationObserver(() => {
  clearTimeout(_таблицыПрокруткаТаймер);
  _таблицыПрокруткаТаймер = setTimeout(() => {
    обеспечитьПрокруткуТаблиц();
    свернутьДлинныеТаблицы();
    свернутьДлинныеСписки();
    подогнатьСвёрнутыеКОкну();
    доделатьВозврат();               // место и фокус строки, раскрытой этим проходом (26.10.2026)
  }, 150);
}).observe(document.body, { childList: true, subtree: true });


function isAdmin() {
  return !!me && (me.access_role === "project_admin" || me.access_role === "super_admin");
}

// «Подготовка встречи» — всем ролям (решение владелицы 21.10.2026: «будут все пользователи делать»): завести встречу,
// приложить файлы, собрать план и протокол может любой, кто выбран в «Вы работаете как» или вошёл. Удаление источников,
// точечная правка, приёмка черновика, отмена встречи и «Свести в одну» — по-прежнему `isAdmin()`; права проверяет сервер.
function canPrepare() {
  return !!me;
}

// Пункты левого меню блока суперадминистратора — по роли, одним местом (задание 23.10.2026: «Разбор голосов» оставался в меню
// у участника на стенде ЛМ 22.10.2026). Видимость ставит `применитьМенюПоРоли` — при показе, при переключении «Вы работаете
// как», после загрузки списка людей и после отказа сервера 403. Тот же перечень по смыслу — `пунктыМенюПоРоли` Планёрки.
const МЕНЮ_СУПЕРАДМИНА = ["nav-system", "nav-live", "nav-models", "nav-voices", "nav-voice-review", "nav-design", "nav-sa-hr"];
function пунктыМенюПоРоли(роль) {
  const супер = роль === "super_admin";
  return Object.fromEntries(МЕНЮ_СУПЕРАДМИНА.map(id => [id, супер]));
}
function применитьМенюПоРоли() {
  for (const [id, виден] of Object.entries(пунктыМенюПоРоли(me && me.access_role))) {
    const el = document.getElementById(id);
    if (el) {
      el.hidden = !виден;
      if (!виден) el.removeAttribute("aria-current");
    }
  }
}

// Рабочий режим: права могли смениться, пока окно открыто (роль поменяли в «Команде»), — сервер отвечает 403, а запомненный
// при входе `me` ещё со старой ролью. Перечитываем, кто вошёл, и сразу приводим меню к роли (задание 23.10.2026).
let _праваПеречитываются = null;
async function перечитатьПрава() {
  if (_праваПеречитываются) return _праваПеречитываются;
  _праваПеречитываются = (async () => {
    try {
      const res = await fetch("/auth/me");
      if (!res.ok) return;
      const свежий = await res.json();
      if (me && свежий && String(свежий.id) === String(me.id) && свежий.access_role !== me.access_role) {
        me = Object.assign({}, me, свежий);
        применитьМенюПоРоли();
        render();
      }
    } catch (e) { /* нет связи — меню останется до следующего запроса */ }
    finally { _праваПеречитываются = null; }
  })();
  return _праваПеречитываются;
}

function isSuperAdmin() {
  // «Параметры системы» и переключатель входа — решение 22.09.26 (ERROR_REGISTRY.md F12): мониторинг ошибок
  // — не работа администратора, который ведёт встречи. «Конфликты» с 23.09.26 (F14) видит и админ (isAdmin).
  return !!me && me.access_role === "super_admin";
}

// Куда отсылать за подробностями сбоя в тексте тоста/панели — «Конфликты» видит только супер-админ,
// остальным (включая обычного администратора проекта) текст без ссылки, но с понятным адресатом.
function conflictsRef() {
  // Системные сообщения (технические подробности) живут на «Параметры системы» — своя страница с 23.09.26.
  return isSuperAdmin() ? "Подробности — на странице «Параметры системы»." : "Передано супер-администратору.";
}

// --- Проект (многопроектность MeetFlow — одно из двух разрешённых отличий от ERP, 27.10.2026) --------------------------
// Выбор — внизу левой панели над «Вы работаете как»: «Все проекты» и проекты по имени. Шапка — «Проект — <название>» или
// «Все проекты компании»; выбор помнится в браузере. Разделы, которые работают по одному проекту (подготовка встречи,
// план, статус), при «Все проекты» просят выбрать проект.
let _проекты = [];
function выбранныйПроект() {
  const v = Number(localStorage.getItem("currentProjectId") || 0);
  return Number.isFinite(v) && v > 0 ? v : 0;
}
function названиеСистемы() {
  const id = выбранныйПроект();
  const п = _проекты.find(x => x.id === id);
  if (id && п) return `Проект — ${п.label || п.name}`;          // подпроект — «Проект — Проект – Подпроект»
  return id ? "MeetFlow" : "Все проекты компании";
}
function показатьНазваниеПроекта() {
  const имя = названиеСистемы();
  document.title = имя;
  const $b = document.querySelector(".sidebar .brand");
  if ($b) $b.textContent = имя;
}
async function загрузитьПроекты() {
  try { _проекты = await api("/projects-list", { вне_показа: true }); } catch (e) { _проекты = _проекты || []; }
  if (!Array.isArray(_проекты)) _проекты = [];
  // сохранённый проект пропал (архив, удалён) — первый проект, а не пустой экран; проектов нет — «Все проекты»
  if (выбранныйПроект() && !_проекты.some(x => x.id === выбранныйПроект())) {
    localStorage.setItem("currentProjectId", String(_проекты.length ? _проекты[0].id : 0));
  }
  if (localStorage.getItem("currentProjectId") === null && _проекты.length) localStorage.setItem("currentProjectId", String(_проекты[0].id));
  const $s = document.getElementById("project-select");
  if ($s) {
    // проект, под ним его подпроекты с отступом (справочник проектов, 27.10.2026); выбор проекта — вместе с подпроектами
    $s.innerHTML = '<option value="0">Все проекты</option>' + _проекты.map(п =>
      `<option value="${п.id}">${"\u00a0\u00a0\u00a0".repeat(п.level || 0)}${п.level ? "– " : ""}${esc(п.name)}</option>`).join("");
    $s.value = String(выбранныйПроект());
  }
  показатьНазваниеПроекта();
}
function нуженПроект(заголовок) {
  // раздел по одному проекту при «Все проекты» — просьба выбрать проект (как у прежнего MeetFlow, 9c14cb6)
  if (выбранныйПроект()) return false;
  $main.innerHTML = `<div class="feed-head"><div class="feed-head-text"><h1>${esc(заголовок)}</h1>
      <div class="feed-sub">Этот раздел работает по одному проекту — выберите его внизу левой панели. «Все проекты» есть во встречах, реестре задач и договорённостях.</div></div></div>`;
  return true;
}
document.getElementById("project-select")?.addEventListener("change", (e) => {
  localStorage.setItem("currentProjectId", String(Number(e.target.value) || 0));
  показатьНазваниеПроекта();
  render();
});

function showLogin(message) {
  me = null;
  document.getElementById("app-shell").hidden = true;
  document.getElementById("main").innerHTML = "";
  document.getElementById("staleness-banner").innerHTML = "";
  показатьКтоВошёл(null);
  renderLoginScreen(message || "");
}

// --- Экран входа (решения владелицы 18.10.2026, перенос из Планёрки 19.10.2026) ------------------------------------
// Карточка входа поверх заставки-каркаса: шапка, левое меню, пустые блоки страницы. За карточкой НЕ живая
// страница — до входа данные не грузятся и в браузер не попадают (сервер отвечает 401 на всё, кроме входа).
// По умолчанию — «Войти»: логин, пароль, галочка «Помнить на этом компьютере 30 дней». Рядом — «Первый вход —
// завести аккаунт»: выбор своего ФИО из «Команды» (только те, у кого логин ещё не привязан), логин, пароль.
// Ошибка — одна строка. Выбор ФИО в браузере не запоминается: в следующий раз человек входит по логину.
// Отличие от Планёрки одно: запросы экрана входа идут fetch напрямую (`входЗапрос`), а не через api() — у ERP api() на
// любой 401 сам открывает экран входа «Сессия истекла», а здесь 401 — это «неверный логин или пароль».

function каркасВходаHtml() {
  const пункты = Array.from({ length: 7 }, (_, i) => `<span class="lsk-bar lsk-nav${i === 3 ? " lsk-gap" : ""}"></span>`).join("");
  const строки = Array.from({ length: 6 }, () => `<span class="lsk-bar lsk-row"></span>`).join("");
  return `<div class="login-skeleton" aria-hidden="true">
    <div class="lsk-side"><span class="lsk-bar lsk-brand"></span><span class="lsk-bar lsk-brand-sub"></span>${пункты}</div>
    <div class="lsk-main"><span class="lsk-bar lsk-h1"></span><span class="lsk-bar lsk-sub"></span>
      <div class="lsk-block">${строки}</div><div class="lsk-block lsk-block-low">${строки}</div></div>
  </div>`;
}

// Пустой результат поиска ФИО при первом входе (замечание владелицы со стенда Планёрки 18.10.2026): человек с уже
// заведённым аккаунтом в списке скрыт по правилу, и написание тут ни при чём. У кого привязан логин, не раскрываем.
const ПУСТО_ПЕРВЫЙ_ВХОД = 'В списке свободных имён такого нет. Если вы уже заводили аккаунт — войдите на вкладке '
  + '«<button type="button" class="login-link" data-to-enter>Войти</button>». Если нет — обратитесь к администратору.';

async function входЗапрос(path, json) {
  const res = await fetch(path, json === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "erp-webapp" },
    body: JSON.stringify(json) });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Не удалось войти. Повторите попытку.");
  return j;
}

function renderLoginScreen(message = "") {
  document.getElementById("app-shell")?.setAttribute("hidden", "");
  document.getElementById("login-screen")?.remove();
  const экран = document.createElement("div");
  экран.id = "login-screen";
  экран.className = "login-screen";
  экран.innerHTML = `${каркасВходаHtml()}<div class="login-veil"></div>
    <div class="login-card card" role="dialog" aria-labelledby="login-title">
      <h1 id="login-title">${esc(названиеСистемы())}</h1>
      <div class="login-tabs" role="tablist">
        <button type="button" class="login-tab is-on" data-login-tab="enter" role="tab">Войти</button>
        <button type="button" class="login-tab" data-login-tab="first" role="tab">Первый вход — завести аккаунт</button>
      </div>
      <div class="login-note" id="login-shared-note" hidden>Общий пароль ещё не задан — обратитесь к администратору</div>
      <form class="login-pane" id="login-pane-enter" autocomplete="on">
        <div class="field"><label for="login-login">Логин</label>
          <input id="login-login" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="часть вашей почты до «@»"></div>
        <div class="field"><label for="login-password">Пароль</label>
          <input id="login-password" type="password" autocomplete="current-password"></div>
        <label class="login-remember"><input type="checkbox" id="login-remember"> Помнить на этом компьютере 30 дней</label>
        <div class="login-error" id="login-error" role="alert">${esc(message)}</div>
        <button type="submit" class="btn-primary login-submit" id="login-submit">Войти</button>
      </form>
      <form class="login-pane" id="login-pane-first" hidden autocomplete="off">
        <div class="login-step" id="first-step-name">
          <div class="field"><label for="first-search">Шаг 1. Найдите своё ФИО</label>
            <input id="first-search" name="pl-first-pick" type="text" placeholder="Начните вводить фамилию" autocomplete="first-login-no-autofill" autocorrect="off" autocapitalize="off" spellcheck="false">
            <div class="login-hint login-hint-under">Только сотрудники команды без заведённого аккаунта</div></div>
          <div class="login-people" id="first-people" role="listbox"></div>
        </div>
        <div class="login-step" id="first-step-pass" hidden>
          <div class="login-chosen">Шаг 2. <b id="first-chosen-name"></b> <button type="button" class="login-link" id="first-rechoose">выбрать другое имя</button></div>
          <!-- Поля первого входа браузер не заполняет (замечание владелицы со стенда 18.10.2026): своё name/id без слов
               login/username, у пароля new-password — сохранённый пароль не подставится. «Войти» подстановку сохраняет. -->
          <div class="field"><label for="pl-fv-ident">Логин</label>
            <input id="pl-fv-ident" name="pl-fv-ident" type="text" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="часть вашей почты до «@»"></div>
          <div class="field"><label for="pl-fv-secret">Пароль</label>
            <input id="pl-fv-secret" name="pl-fv-secret" type="password" autocomplete="new-password"></div>
          <div class="login-hint">Участникам — общий пароль. Администраторам — личный: его выдаёт суперадмин.</div>
          <label class="login-remember"><input type="checkbox" id="first-remember"> Помнить на этом компьютере 30 дней</label>
        </div>
        <div class="login-error" id="first-error" role="alert"></div>
        <button type="submit" class="btn-primary login-submit" id="first-submit" hidden>Завести и войти</button>
      </form>
    </div>`;
  document.body.appendChild(экран);
  const $ = (id) => экран.querySelector("#" + id);
  let люди = [], выбран = null;

  const вкладка = (какая) => {
    экран.querySelectorAll(".login-tab").forEach(t => t.classList.toggle("is-on", t.dataset.loginTab === какая));
    $("login-pane-enter").hidden = какая !== "enter";
    $("login-pane-first").hidden = какая !== "first";
    if (какая === "first") очиститьШаг2();
    (какая === "enter" ? $("login-login") : (выбран ? $("pl-fv-ident") : $("first-search"))).focus();
  };
  экран.querySelectorAll(".login-tab").forEach(t => t.addEventListener("click", () => вкладка(t.dataset.loginTab)));

  const список = () => {
    const q = $("first-search").value.trim().toLowerCase().replace(/ё/g, "е");
    const найдено = люди.filter(p => !q || p.full_name.toLowerCase().replace(/ё/g, "е").includes(q)).slice(0, 8);
    $("first-people").innerHTML = найдено.length
      ? найдено.map(p => `<button type="button" class="login-person" data-id="${p.id}" role="option">${esc(p.full_name)}</button>`).join("")
      : `<div class="login-hint" id="first-empty">${ПУСТО_ПЕРВЫЙ_ВХОД}</div>`;
  };
  // Шаг 2 всегда начинается с пустых полей: при выборе ФИО, «выбрать другое имя» и переходе на вкладку первого входа
  // стираются логин, пароль, галочка и ошибка — иначе там оставались значения прошлого входа (замечание со стенда 18.10.2026).
  const очиститьШаг2 = () => {
    $("pl-fv-ident").classList.remove("is-empty");
    $("pl-fv-secret").classList.remove("is-empty");
    $("pl-fv-ident").value = "";
    $("pl-fv-secret").value = "";
    $("first-remember").checked = false;
    $("first-error").textContent = "";
  };
  const выбрать = (p) => {
    выбран = p;
    очиститьШаг2();
    $("first-chosen-name").textContent = p ? p.full_name : "";
    $("first-step-name").hidden = !!p;
    $("first-step-pass").hidden = !p;
    $("first-submit").hidden = !p;
    $("first-error").textContent = "";
    (p ? $("pl-fv-ident") : $("first-search")).focus();
  };
  $("first-search").addEventListener("input", список);
  // Ссылка «Войти» в сообщении о пустом результате переключает вкладку (замечание владелицы со стенда 18.10.2026)
  $("first-people").addEventListener("click", (e) => { if (e.target.closest("[data-to-enter]")) вкладка("enter"); });
  $("first-people").addEventListener("click", (e) => {
    const кнопка = e.target.closest(".login-person");
    if (кнопка) выбрать(люди.find(p => String(p.id) === кнопка.dataset.id) || null);
  });
  $("first-rechoose").addEventListener("click", () => выбрать(null));

  // Экрану входа до входа нужны только ФИО без привязанного логина и признак «общий пароль задан».
  входЗапрос("/auth/first-login/people").then((ответ) => {
    люди = ответ.people || [];
    $("login-shared-note").hidden = !!ответ.shared_password_set;
    список();
  }).catch(() => список());

  // Пустые поля проверяются ДО отправки (замечание владелицы со стенда 18.10.2026): «Введите логин» / «Введите пароль»,
  // поле подсвечено и в фокусе, запрос не уходит и в счётчик попыток не идёт. Единая «Неверный логин или пароль» —
  // только ответ сервера на заполненную форму.
  const пустоеПоле = (поляИСообщения, $ошибка) => {
    for (const [поле, текст] of поляИСообщения) {
      const пусто = поле.type === "password" ? !поле.value : !поле.value.trim();
      поле.classList.toggle("is-empty", пусто);
      if (пусто) { $ошибка.textContent = текст; поле.focus(); return true; }
    }
    return false;
  };
  экран.querySelectorAll(".login-pane input").forEach(i => i.addEventListener("input", () => i.classList.remove("is-empty")));
  $("login-pane-enter").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    if (пустоеПоле([[$("login-login"), "Введите логин"], [$("login-password"), "Введите пароль"]], $("login-error"))) return;
    try {
      await входЗапрос("/auth/login", { login: $("login-login").value.trim(),
        password: $("login-password").value, remember: $("login-remember").checked });
      location.reload();
    } catch (err) { $("login-error").textContent = err.message || "Не удалось войти"; $("login-password").value = ""; }
  });
  $("login-pane-first").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!выбран) return;
    $("first-error").textContent = "";
    if (пустоеПоле([[$("pl-fv-ident"), "Введите логин"], [$("pl-fv-secret"), "Введите пароль"]], $("first-error"))) return;
    try {
      await входЗапрос("/auth/first-login", { user_id: выбран.id, login: $("pl-fv-ident").value.trim(),
        password: $("pl-fv-secret").value, remember: $("first-remember").checked });
      location.reload();
    } catch (err) { $("first-error").textContent = err.message || "Не удалось войти"; }
  });
  $("login-login").focus();
}

// Значок «показать пароль» (решение владелицы 19.10.2026) — во всех полях пароля: экран входа, первый вход, смена своего и
// временного пароля, общий пароль, подтверждение паролем. Кнопка `type="button"` (форму не отправляет, Enter её не нажимает),
// подписи для чтения с экрана «Показать пароль» / «Скрыть пароль», состояние — aria-pressed. Повторный вызов поле не трогает
// (метка data-eye).
const ГЛАЗ_ПОКАЗАТЬ = "Показать пароль", ГЛАЗ_СКРЫТЬ = "Скрыть пароль";
function приделатьГлаз(корень) {
  if (!корень) return;
  корень.querySelectorAll('input[type="password"]:not([data-eye])').forEach(поле => {
    поле.dataset.eye = "1";
    const обёртка = document.createElement("span");
    обёртка.className = "pw-wrap";
    поле.parentNode.insertBefore(обёртка, поле);
    обёртка.appendChild(поле);
    const глаз = document.createElement("button");
    глаз.type = "button";
    глаз.className = "pw-eye";
    глаз.setAttribute("aria-label", ГЛАЗ_ПОКАЗАТЬ);
    глаз.setAttribute("aria-pressed", "false");
    глаз.title = ГЛАЗ_ПОКАЗАТЬ;
    if (поле.id) глаз.setAttribute("aria-controls", поле.id);
    глаз.addEventListener("click", () => {
      const показан = поле.type === "text";
      поле.type = показан ? "password" : "text";
      const надпись = показан ? ГЛАЗ_ПОКАЗАТЬ : ГЛАЗ_СКРЫТЬ;
      глаз.setAttribute("aria-label", надпись);
      глаз.setAttribute("aria-pressed", показан ? "false" : "true");
      глаз.title = надпись;
      поле.focus();
    });
    обёртка.appendChild(глаз);
  });
}
// В ERP окна с паролем рисуются в разных местах (экран входа, «Задайте свой пароль», общий пароль, подтверждение паролем) —
// помощник ставит наблюдатель за документом, без правки каждой формы. Сам помощник — близнец Планёрки (сведение 19.10.2026).
new MutationObserver((записи) => {
  for (const з of записи) for (const у of з.addedNodes) {
    if (у.nodeType !== 1) continue;
    приделатьГлаз(у.matches && у.matches('input[type="password"]') ? у.parentNode : у);
  }
}).observe(document.documentElement, { childList: true, subtree: true });

// «Вы — <ФИО> (<роль словами>)» вверху после входа (18.10.2026). Только в рабочем режиме.
function показатьКтоВошёл(u) {
  const место = document.getElementById("whoami-top");
  if (!место) return;
  место.hidden = !u;
  место.textContent = u ? `Вы — ${u.full_name} (${u.role_words || "участник"})` : "";
}

async function startApp(user) {
  me = user;
  await загрузитьПроекты();
  document.getElementById("login-screen")?.remove();
  document.getElementById("app-shell").hidden = false;
  показатьКтоВошёл(user);
  document.getElementById("whoami-testing").hidden = true;
  document.getElementById("whoami-auth").hidden = false;
  updateModeSwitch();
  document.getElementById("user-name").textContent = user.full_name;
  document.getElementById("user-role").textContent =
    (user.access_role === "super_admin" ? "Супер-админ" : user.access_role === "project_admin" ? "Админ проекта" : "Участник")
    + (user.role ? " · " + user.role : "");
  // Участник входит по общему паролю — свой пароль ему менять нечего (18.10.2026, как в Планёрке)
  const общий = ["member", "director"].includes(user.access_role);
  const $смена = document.getElementById("change-password-btn");
  if ($смена) $смена.hidden = общий;
  применитьМенюПоРоли();   // и до смены временного пароля меню — по роли вошедшего (задание 23.10.2026)
  if (user.must_change_password) { forcePasswordChange(); return; }
  await loadUsersForWhoAmI();
  render();
}

function fillWhoAmI() {
  const $sel = document.getElementById("whoami-select");
  if (!$sel || authRequired) return;
  const current = $sel.value || localStorage.getItem("currentUserId") || "";
  $sel.innerHTML = '<option value="">— не выбран —</option>' + allUsers.map(
    u => `<option value="${u.id}">${esc(u.full_name)}${u.access_role === "super_admin" ? " (супер-админ)" : u.access_role === "project_admin" ? " (админ)" : ""}</option>`
  ).join("");
  const решение = whoamiРешение(current, allUsers, localStorage.getItem("currentUserLabel"));
  if (решение.вариант) {
    // Выбранного человека в свежем списке нет: показываем его отдельным вариантом и говорим словами.
    // Молчаливый сброс до «— не выбран —» терял права (09.10.26: «поле сразу обнулялось»).
    $sel.insertAdjacentHTML("beforeend", `<option value="${esc(решение.значение)}">${esc(решение.вариант)}</option>`);
  }
  $sel.value = решение.значение;
  // Метку выбранного человека запоминаем рядом с id, как только список её подтвердил: тогда следующая
  // неудачная загрузка списка её уже не потеряет (09.10.26).
  if (решение.значение && allUsers.some(u => String(u.id) === решение.значение)) {
    localStorage.setItem("currentUserLabel", ($sel.selectedOptions[0] || {}).textContent?.trim() || "");
  }
  // Личность берём из списка; если человека там нет, но выбор сохранён — оставляем прежний объект,
  // иначе права пропадали бы вместе с обнулением поля.
  me = allUsers.find(u => String(u.id) === $sel.value)
    || (me && String(me.id) === String($sel.value) ? me : null);
  if (решение.предупредить && !whoamiПредупреждали) {
    whoamiПредупреждали = true;
    toast("Выбранный человек не найден в списке команды — выбор сохранён, проверьте «Команду»", true);
  }
}

// Режим тестирования (вход выключен): пользователя выбирают в списке — как до 19.09.26.
async function startTestingMode() {
  document.getElementById("login-screen")?.remove();
  await загрузитьПроекты();
  показатьКтоВошёл(null);
  document.getElementById("app-shell").hidden = false;
  document.getElementById("whoami-auth").hidden = true;
  document.getElementById("whoami-testing").hidden = false;
  await loadUsersForWhoAmI();
  fillWhoAmI();
  updateModeSwitch();
  render();
}

document.getElementById("whoami-select")?.addEventListener("change", (e) => {
  localStorage.setItem("currentUserId", e.target.value);
  // Метку человека помним рядом с id: если список людей не загрузится или человека в нём не окажется,
  // поле всё равно покажет, кто выбран, — иначе выбор выглядел бы сброшенным (09.10.26).
  const выбранный = allUsers.find(u => String(u.id) === e.target.value);
  localStorage.setItem("currentUserLabel", выбранный ? (e.target.selectedOptions[0] || {}).textContent?.trim() || выбранный.full_name : "");
  me = выбранный || null;
  применитьМенюПоРоли();   // меню — сразу, до перерисовки экрана (задание 23.10.2026)
  updateModeSwitch();
  render(); // права (кнопка «Готовь план» и др.) должны отразиться сразу — найдено живым тестом 11.09.26
});

document.getElementById("logout-btn")?.addEventListener("click", async () => {
  try { await fetch("/auth/logout", { method: "POST", headers: { "X-Requested-With": "erp-webapp" } }); } catch (e) {}
  showLogin();
});

// Смена собственного пароля. При временном пароле (forced) окно нельзя закрыть без смены:
// сервер до смены всё равно не пускает никуда, кроме этого окна и «Выйти».
function openPasswordDialog(forced) {
  // Временный пароль выдал суперадмин («Выдать доступ» или «Сбросить пароль»), он действует 24 часа. Свой пароль человек
  // придумывает здесь сам (решение владелицы 19.10.2026, вариант Б).
  const overlay = openModal(forced ? "Задайте свой пароль" : "Смена пароля", `
    ${forced ? '<div class="page-sub" style="margin-bottom:12px">Временный пароль выдал суперадмин. Работать с ним нельзя — придумайте свой: его не увидит никто, в базе хранится только хэш.</div>' : ""}
    <div class="field"><label for="pw-old">${forced ? "Временный пароль" : "Текущий пароль"}</label><input type="password" id="pw-old" autocomplete="${forced ? "one-time-code" : "current-password"}"></div>
    <div class="field"><label for="pw-new">${forced ? "Свой новый пароль" : "Новый пароль"}</label><input type="password" id="pw-new" autocomplete="new-password"></div>
    <div class="field"><label for="pw-new2">Повторите новый пароль</label><input type="password" id="pw-new2" autocomplete="new-password"></div>
  `, async (ov) => {
    // Тексты и порядок проверок — как на экране «Задайте свой пароль» Планёрки (сведение 19.10.2026)
    const oldPw = ov.querySelector("#pw-old").value, newPw = ov.querySelector("#pw-new").value;
    if (!oldPw) throw new Error(forced ? "Введите временный пароль" : "Введите текущий пароль");
    if (!newPw) throw new Error("Введите новый пароль");
    if (newPw !== ov.querySelector("#pw-new2").value) throw new Error("Новые пароли не совпадают");
    await api("/auth/change-password", { method: "POST", json: { old_password: oldPw, new_password: newPw } });
    toast("Пароль изменён");
    if (me) me.must_change_password = false;
    if (forced) { await loadUsersForWhoAmI(); render(); }
  });
  if (forced) overlay.querySelector("#modal-cancel").remove();
  overlay.querySelector("#pw-old").focus();
}

let _forcedDialogOpen = false;
function forcePasswordChange() {
  if (_forcedDialogOpen) return;
  _forcedDialogOpen = true;
  openPasswordDialog(true);
  const obs = new MutationObserver(() => {
    if (!document.querySelector(".modal-overlay")) { _forcedDialogOpen = false; obs.disconnect(); }
  });
  obs.observe(document.body, { childList: true });
}

document.getElementById("change-password-btn")?.addEventListener("click", () => openPasswordDialog(false));

// «Как пользоваться» (Е17, 20.10.2026; образец — Планёрка, решение владелицы 18.10.2026): обучающее видео ERP для участника —
// 2–3 минуты нарезок со своими экранами ERP и подписями, без голоса, на вымышленных людях и проектах. Пункт — в самом низу
// блока «Вы работаете как», виден всем ролям. Файл лежит рядом с фронтом и отдаётся статикой; версия в адресе — та же
// ступень, что у app.js, чтобы новый ролик не застрял в кэше.
const ВИДЕО_КАК_ПОЛЬЗОВАТЬСЯ = "media/kak_polzovatsya.mp4?v=20261018v73";
async function renderHelp() {
  $main.innerHTML = `
    <div class="doc-head"><h1>Как пользоваться</h1></div>
    <section class="card help-card">
      <video class="help-video" id="help-video" controls preload="metadata" playsinline src="${ВИДЕО_КАК_ПОЛЬЗОВАТЬСЯ}">
        Браузер не показывает видео. <a href="${ВИДЕО_КАК_ПОЛЬЗОВАТЬСЯ}">Открыть файл</a>.
      </video>
      <div class="page-sub help-sub">Около трёх минут: свои задачи и отметка по ним, встречи и протоколы, реестр задач,
        «Статус проекта» и поиск. Видео записано до 21.10.2026: «Экрана встречи», который в нём показан, в меню больше нет.
        Вопросы — администратору проекта.</div>
    </section>`;
}

// --- router ---------------------------------------------------------------

const routes = {
  // dashboard — реестр задач: ставит registry.js (`routes.dashboard = renderRegistry`); прежний renderDashboard удалён 18.10.2026
  meetings: renderMeetings,
  team: renderTeam,
  search: renderSearch,
  status: renderStatus,
  conflicts: renderConflicts,
  system: renderSystemParams,
  live: renderMonitoringRealtime,
  models: renderModelsPage,
  awaiting: renderAwaitingInput,
  units: renderUnitsBoard,
  voices: renderVoiceBase,
  possible: renderVozmozhnye,   // «Возможные поручения» — администраторам (решение владелицы 24.10.2026)
  // «Разбор» — одна вкладка вместо «Конфликтов», «Под вопросом» и «Возможных поручений» (решение владелицы 25.10.2026);
  // функция — в razbor.js (близнец), он грузится позже, поэтому вызов через обёртку
  razbor: (rest) => renderRazbor(rest),
  "voice-review": renderVoiceReview,   // «Разбор голосов» — суперадминистратору (задание владелицы 21.10.2026)
  help: renderHelp,            // «Как пользоваться» — всем ролям (Е17, 20.10.2026)
};

function navigate(route) {
  location.hash = route;
}

function currentRouteParts() {
  return (location.hash || "#dashboard").slice(1).split("?")[0].split("/");
}

let _lastRenderedRoute = null;
let _lastRenderedHash = null;
// 30.09.26 (найдено при проверке «Конфликтов»): два показа могут идти одновременно — смена пользователя
// и переход на другую страницу в одно мгновение. Данные первого приходили позже и попадали в экран
// второго: не находили своих элементов, и обработчик ошибки заменял всю страницу «Ошибкой загрузки»;
// без ошибки старый экран мог молча затереть новый. Решает только самый свежий показ.
let _renderSeq = 0;
let _renderDoneSeq = 0;

let _unitsOn = null;

async function render() {
  const seq = ++_renderSeq;
  const [route, ...rest] = currentRouteParts();
  // Решение 17.09.26 — render() вызывается и при смене вкладки
  // (hashchange), и напрямую из обработчиков действий (Выполнено,
  // комментарий, правка) для обновления текущего экрана без смены хеша.
  // Список развёрнутых таблиц (expandedLists) должен сбрасываться только
  // в первом случае — сравниваем маршрут с прошлым рендером, не хешем.
  const sameRoute = route === _lastRenderedRoute;
  // Жалоба 17.09.26 — тот же самый render() внутри страницы полностью
  // пересобирает #main, и браузер сбрасывал прокрутку в начало списка
  // после любого действия (Выполнено/комментарий/правка) — неудобно
  // работать с задачами в конце длинного списка. Запоминаем позицию
  // прокрутки ДО пересборки и восстанавливаем ПОСЛЕ — но только если это
  // тот же маршрут (обновление на месте), не настоящий переход на другую
  // вкладку, где начинать сверху — ожидаемо и правильно.
  const fullHash = (location.hash || "#dashboard").split("?")[0];
  const sameHash = fullHash === _lastRenderedHash;
  _lastRenderedHash = fullHash;
  if (!sameHash) _переходов++;     // ответы, запрошенные прежним экраном, сюда уже не попадут (api())
  _тотЖеЭкран = sameHash;
  const scrollY = sameHash ? window.scrollY : 0;
  // Прокрутка внутри рамок (реестр, «Единицы») — так же, как окна (обход 02.10 вечер: после «✓» и «Актуализировать» лента
  // реестра возвращалась к началу). По порядку рамок на экране: тот же маршрут — та же раскладка.
  const FRAMES = ".table-scroll, .units-body";
  const frameTops = sameHash ? [...$main.querySelectorAll(FRAMES)].map(el => el.scrollTop) : [];
  // Поверх порядка рамок — строка-якорь (18.10.26, см. `запомнитьПрокрутку`): исчезнувшая строка не сдвигает соседние
  const снимокПрокрутки = sameHash ? запомнитьПрокрутку() : null;
  // Тот же экран — прежнее содержимое и высота держатся до новой отрисовки, фокус возвращается на строку (26.10.2026)
  const фокусДо = sameHash ? запомнитьФокус() : null;
  const отпуститьВысоту = sameHash ? удержатьВысоту() : () => {};
  if (!sameRoute) {
    expandedLists.clear();
    _lastRenderedRoute = route;
  }
  // Пункт меню, подсвеченный для маршрута: вкладки «Системы» подсвечивают «Систему» (nav.js, стенд 13.10.26)
  const пункт = typeof навАктивный === "function" ? навАктивный(route) : route;
  $main.dataset.screen = пункт;      // экран — для стилей по разделам (экраны супер-администратора, 14.10.26)
  document.querySelectorAll(".nav-item").forEach(el => {
    el.classList.toggle("active", el.dataset.route === пункт);
    if (el.dataset.route === пункт) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  document.getElementById("help-link")?.classList.toggle("active", route === "help");
  // Решение 17.09.26 — вкладка «Конфликты» (сами расхождения, текстовая очередь) видна админу и
  // супер-админу. Решение 22.09.26 (F12) сузило было до супер-админа, но 23.09.26 уточнено: сама
  // очередь конфликтов — как раньше, для обеих админских ролей; только «Системные сообщения» и
  // «Параметры системы» (страница «system», ссылка внизу «Конфликтов») остаются супер-админу.
  const $conflictsNav = document.querySelector('.nav-item[data-route="conflicts"]');
  if ($conflictsNav) $conflictsNav.hidden = !isAdmin();
  // «Команда» — администраторам (владелец 14.10.26, вопрос 1: участнику не показывать — в меню и по прямому адресу)
  const $teamNav = document.querySelector('.nav-item[data-route="team"]');
  if ($teamNav) $teamNav.hidden = !isAdmin();
  // «Подготовка встречи» — всем ролям (решение владелицы 21.10.2026; с 13.10.26 было — администратору). С 25.10.2026 — пунктом
  // блока под чертой, рядом с «Командой» (решение владелицы): сменилось место, права те же
  const $prepNav = document.getElementById("nav-prep");
  if ($prepNav) $prepNav.hidden = false;
  // «Договорённости» — пункт блока пользователей, всем ролям (решение владелицы 20.10.2026, п. 3; с 19.10.2026 — только
  // администраторам): прятать нечего
  // «Под вопросом» — пункт блока администратора с числом (решение владелицы 20.10.2026; было вкладкой реестра с 19.10.2026)
  const $podNav = document.getElementById("nav-pod");
  if ($podNav) $podNav.hidden = !isAdmin();
  // «Разбор» — один пункт вместо трёх, админам (решение владелицы 25.10.2026)
  const $razborNav = document.getElementById("nav-razbor");
  if ($razborNav) $razborNav.hidden = !isAdmin();
  // «Возможные поручения» — пункт блока администратора со счётчиком неразобранных (решение владелицы 24.10.2026)
  const $possibleNav = document.getElementById("nav-possible");
  if ($possibleNav) $possibleNav.hidden = !isAdmin();
  // Решение 23.09.26 — отдельный пункт «Параметры системы» (системные сообщения + живая панель
  // метрик) за своей чертой внизу левого меню, виден только супер-админу; сама страница «Конфликты»
  // (текстовая очередь) — выше, для обеих админских ролей, без изменений.
  // Блок суперадминистратора — «Параметры системы», «Мониторинг RealTime», «Модели», «База голосов», «Разбор голосов» и
  // черта блока — одной функцией по роли (задание 23.10.2026)
  применитьМенюПоРоли();
  // Единицы — за выключателем сервера (владелец 03.10.26: в прод пока не запускаем); выключены — табло в меню нет.
  if (_unitsOn === null) { try { _unitsOn = !!(await api("/units/enabled")).enabled; } catch (e) { _unitsOn = false; } }
  // «Модели» — отдельный пункт слева, супер-админу (владелец 09.10.26). «Ожидает ввода от оператора» переехал
  // горизонтальной вкладкой в «Параметры системы».
  // Меню тремя блоками по ролям (владелец 14.10.26): черта блока — только тому, кто видит его пункты; подписей блоков нет
  // черта второго блока — администраторам: с 14.10.26 «Команду» участник не видит, у него в блоке пусто
  // С 25.10.2026 в блоке и «Подготовка встречи» всем ролям — черта видна всем, у кого в блоке есть видимый пункт
  const $adminHr = document.getElementById("nav-admin-hr");
  if ($adminHr) $adminHr.hidden = !(isAdmin() || ($prepNav && !$prepNav.hidden));
  document.querySelectorAll(".nav-item[hidden]").forEach(el => el.removeAttribute("aria-current"));
  if (route === "conflicts" && !isAdmin()) { location.replace("#dashboard"); return; }     // цикл 2: hash оставался #conflicts
  if (route === "team" && !isAdmin()) { location.replace("#dashboard"); return; }          // владелец 14.10.26: и по прямому адресу
  if (route === "pod" && !isAdmin()) { location.replace("#dashboard"); return; }           // «Под вопросом» — админам (20.10.2026)
  if (route === "possible" && !isAdmin()) { location.replace("#dashboard"); return; }      // «Возможные поручения» — админам (24.10.2026)
  if (route === "razbor" && !isAdmin()) { location.replace("#dashboard"); return; }        // «Разбор» — админам (25.10.2026)
  // прежний адрес вкладки «Под вопросом» — с 25.10.2026 в «Разбор», вид «Задачи» (было — «#pod»)
  if (route === "dashboard" && rest[0] === "pod") { location.replace(адресРазбора("pod")); return; }
  // «Конфликты», «Под вопросом», «Возможные поручения» — одна вкладка «Разбор» (решение владелицы 25.10.2026): прежние адреса
  // ведут в нужный вид, ссылки из «Мониторинга», писем и закладок не ломаются
  if (["conflicts", "pod", "possible"].includes(route)) { location.replace(адресРазбора(route)); return; }
  if ((route === "system" || route === "voices" || route === "voice-review" || route === "live" || route === "units" || route === "awaiting" || route === "models" || route === "design") && !isSuperAdmin()) { location.replace("#dashboard"); return; }
  if (route === "units" && !_unitsOn) { location.replace("#dashboard"); return; }
  // «Экран встречи» убран (решение владелицы 21.10.2026): старые ссылки — на «Встречи по проекту» и страницу встречи
  if (route === "screen") { location.replace(rest[0] ? `#meetings/${rest[0]}` : "#meetings"); return; }
  // Неизвестный адрес — на реестр задач. Прежде — на прежнюю страницу реестра (renderDashboard), а не на новую (аудит 13.10.26)
  const fn = routes[route] || routes.dashboard;   // routes.dashboard — реестр (registry.js); прежний renderDashboard удалён 18.10.2026
  let failed = null;
  _прокруткаГлубина += 1;
  _перерисовкаНаМесте = sameHash;
  try {
    await fn(rest);
    обеспечитьПрокруткуТаблиц();     // таблицы шире места
    свернутьДлинныеТаблицы();        // 8 записей и кнопка «Показать все» — на всех экранах — с горизонтальной прокруткой (владелец 05.10.26, предел 8 — 09.10.26)
  свернутьДлинныеСписки();         // то же правило для списков из блоков: единицы встречи, карточки, сообщения
  } catch (e) {
    failed = e;
  } finally { _прокруткаГлубина -= 1; _перерисовкаНаМесте = false; if (seq !== _renderSeq) отпуститьВысоту(); }
  if (seq !== _renderSeq) {
    // Уже начат более свежий показ — этот устарел: ни его результат, ни его ошибку не показываем. Если
    // свежий успел закончиться раньше, поздний мог затереть его экран — перерисовать текущую страницу.
    if (_renderDoneSeq === _renderSeq) render();
    return;
  }
  _renderDoneSeq = seq;
  if (failed) {
    const e = failed;
    const shown = route === "meetings" && rest[0] && e.message === "Не найдено" ? "Встреча не найдена" : e.message;
    $main.innerHTML = `<div class="card"><div>Ошибка загрузки: ${esc(shown)}</div>
      <div class="hstack" style="margin-top:12px"><button class="btn-sm" id="reload-page-btn">Повторить</button><a class="btn btn-sm" href="#meetings">К списку встреч</a><a class="btn btn-sm" href="#dashboard">На главную</a></div></div>`;
    document.getElementById("reload-page-btn")?.addEventListener("click", () => render());
  }
  window.scrollTo(0, sameHash ? scrollY : 0);   // переход список → протокол/встреча начинается с заголовка
  if (frameTops.length) $main.querySelectorAll(FRAMES).forEach((el, k) => { if (frameTops[k]) el.scrollTop = frameTops[k]; });
  if (sameHash) { вернутьПрокрутку(снимокПрокрутки); отпуститьВысоту(); вернутьФокус(фокусДо); отложитьВозврат(снимокПрокрутки, фокусДо); }
  // Строка о пересчёте Карты и Сводки живёт только на «Статусе проекта» (4.1 задания 13.10.26) — с 18.10.2026 и запросы
  // `staleness` и `refresh-status` идут только там, а не на каждом переходе; начатый опрос идущего пересчёта
  // (`_refreshPollTimer`) продолжается сам и на других страницах.
  if (route === "status") checkStaleness(); else $stalenessBanner.innerHTML = "";
  if (isAdmin()) updateConflictsBadge({}, { толькоНезаполненные: true });   // на переходе значки не запрашиваются (18.10.2026)
}

document.getElementById("nav")?.addEventListener("click", (e) => {
  const item = e.target.closest(".nav-item");
  // Пункт-ссылку переводит сама ссылка (18.10.2026): у пунктов, где data-route ≠ href, второй переход давал второй показ
  // подряд — первым чужой страницы. Пункт без ссылки — как прежде.
  if (!item || (item.getAttribute("href") || "").startsWith("#")) return;
  navigate(item.dataset.route);
});

window.addEventListener("hashchange", render);
// Кнопки-«span» (подсказки поиска, «Сбросить поиск») доступны с клавиатуры: Enter и пробел нажимают их
document.addEventListener("keydown", (e) => {
  const t = e.target;
  if ((e.key === "Enter" || e.key === " ") && t && t.matches && t.matches('[role="button"][tabindex]')) { e.preventDefault(); t.click(); }
});
window.addEventListener("DOMContentLoaded", async () => {
  try {
    const modeRes = await fetch("/auth/mode");
    authRequired = modeRes.ok ? !!(await modeRes.json()).auth_required : false;
  } catch (e) { authRequired = false; }
  if (!authRequired) { await startTestingMode(); return; }
  let user = null;
  try {
    const res = await fetch("/auth/me");
    if (res.ok) user = await res.json();
  } catch (e) { /* нет связи — покажем вход, там понятное сообщение при попытке войти */ }
  if (!user) { showLogin(); return; }
  await startApp(user);
});

// --- Баннер устаревания Карты/Сводки ---------------------------------------
// Решение 14.09.26: закрытие/создание задачи не триггерит пересчёт Карты/
// Сводки автоматически — раньше пользователь мог не заметить расхождение,
// уйти на другую страницу и забыть. Баннер живёт ВНЕ #main (index.html),
// поэтому переживает смену страницы — проверяется заново при каждой
// навигации через render(), не только на «Статус проекта».
const $stalenessBanner = document.getElementById("staleness-banner");

// Решение 16.09.26 — раньше клик «Обновить» держал запрос открытым на
// всё время пересчёта Карты/Сводки (штатно до ~15 мин на попытку,
// реалистично может растянуться сильно дольше при перегрузке
// провайдера) — пользователь смотрел на «Обновляю… 238с» без разницы
// между «ещё считает» и «завис», единственное восстановление —
// перезапуск сервера. Теперь /project-status/refresh запускает пересчёт
// в фоне на сервере и сразу отвечает; статус опрашивается отдельной
// ручкой — переживает переход между вкладками и перезагрузку страницы,
// не только текущий клик. `_refreshPollTimer` — чтобы не плодить
// параллельные опросы при каждой навигации (checkStaleness вызывается
// на каждый render()).
let _refreshPollTimer = null;

// Решение 16.09.26, уточнение пользователя: общий баннер (виден на любой
// странице) НЕ должен выглядеть как «идёт процесс, подождите» с тикающим
// счётчиком секунд — это как раз создаёт ложное ощущение, что нужно
// стоять и ждать. Как только фон подтверждённо запущен, баннер один раз
// спокойно сообщает «идёт в фоне, можно работать дальше» и на этом
// затихает — статичный, без счётчика, без «дизейбленной» кнопки-таймера.
// Живой счётчик остаётся ТОЛЬКО в заметке на самой странице «Статус
// проекта» — там человек специально пришёл смотреть именно эти
// документы, и ему как раз нужно знать, сколько ещё ждать.
function renderCalmRefreshBanner() {
  // Дизайн — .banner-progress (styles.css): не предупреждение, а статус процесса.
  $stalenessBanner.innerHTML = `
    <div class="card banner-progress" role="status" aria-live="polite">
      <span class="banner-spinner" aria-hidden="true"></span>
      <span><strong>Идёт обновление Дорожной карты и Сводки</strong> — можно продолжать работу, остальные разделы не затронуты.</span>
    </div>`;
}

async function pollRefreshStatus() {
  clearTimeout(_refreshPollTimer);
  let status;
  try { status = await api("/project-status/refresh-status", { вне_показа: true }); } catch (e) { return; }
  показатьХодПересчёта(status);
  if (status.status === "queued") {          // очередь сборок (14.10.26): Карта и Сводка ждут протоколы
    const note = document.getElementById("status-refresh-note");
    if (note) note.textContent = "Пересчёт Карты и Сводки в очереди сборок — начнётся после протоколов. Показана последняя сохранённая версия.";
    _refreshPollTimer = setTimeout(pollRefreshStatus, 5000);
    return;
  }
  if (status.status !== "running") {
    if (status.status === "done") {
      const result = status.result || {};
      if (result.status === "saved") toast("Дорожная карта и Сводка обновлены");
      else if (result.status === "verification_failed") toast("Не удалось обновить — черновик не прошёл проверку, попробуйте ещё раз", true);
      else toast("Не удалось обновить Карту и Сводку. " + conflictsRef(), true);
    } else if (status.status === "error") {
      toast("Пересчёт Карты и Сводки не удался. " + conflictsRef(), true);
    }
    checkStaleness();
    if (currentRouteParts()[0] === "status") render();
    return;
  }
  const note = document.getElementById("status-refresh-note");
  if (note) note.textContent = `Ещё идёт пересчёт Карты и Сводки (${status.elapsed_seconds}с)${status.likely_stuck ? " — необычно долго, но ещё может завершиться" : ""} — показана последняя сохранённая версия. Остальные разделы работают как обычно.`;
  _refreshPollTimer = setTimeout(pollRefreshStatus, 5000);
}

function склонИзменений(n) {
  const д = n % 100, е = n % 10;
  if (д >= 11 && д <= 14) return "изменений";
  return е === 1 ? "изменение" : (е >= 2 && е <= 4) ? "изменения" : "изменений";
}

async function checkStaleness() {
  let data, refreshStatus;
  try {
    [data, refreshStatus] = await Promise.all([
      api("/project-status/staleness"),
      api("/project-status/refresh-status"),
    ]);
  } catch (e) { return; }

  // Пункт 4.1 задания (стенд 13.10.26): строка о пересчёте Карты и Сводки — только на «Статусе проекта». На остальных
  // страницах она занимала первый экран и звала к платному действию там, где Карта не нужна.
  if (currentRouteParts()[0] !== "status") {
    $stalenessBanner.innerHTML = "";
    if (refreshStatus.status === "running" || refreshStatus.status === "queued") { clearTimeout(_refreshPollTimer); _refreshPollTimer = setTimeout(pollRefreshStatus, 5000); }
    return;
  }
  показатьХодПересчёта(refreshStatus);
  if (refreshStatus.status === "running" || refreshStatus.status === "queued") {
    renderCalmRefreshBanner();
    const note = document.getElementById("status-refresh-note");
    if (note) note.textContent = `Ещё идёт пересчёт Карты и Сводки (${refreshStatus.elapsed_seconds}с) — показана последняя сохранённая версия, подождите. Остальные разделы работают как обычно.`;
    clearTimeout(_refreshPollTimer);
    _refreshPollTimer = setTimeout(pollRefreshStatus, 5000);
    return;
  }

  // Последний пересчёт не прошёл проверку — сказать прямо, а не только «мог устареть» (тест двух циклов 01.10.26:
  // причина уходила лишь в системные сообщения супер-админа, администратор проекта не знал, что Карта не обновилась).
  // «не удался», а не «не прошёл проверку»: причина бывает и другой — нет ключа модели, сеть (обход 02.10 вечер).
  const failed = refreshStatus.status === "error";
  if (!data.stale && !failed) { $stalenessBanner.innerHTML = ""; return; }
  // До 20.10.2026 текст различался по роли (решение 14.09.26): участнику кнопки не было и писалось «Обновление доступно
  // администратору проекта». Решение владелицы 19.10.2026 — пересчёт по кнопке для всех категорий (перерыв 60 мин, кроме
  // суперадмина, ставит сервер) — строка одна для всех.
  // Конкретно: что отстаёт и насколько (задание, раздел 6).
  const message = failed
    ? `Последний пересчёт Карты и Сводки${refreshStatus.finished_at ? " (" + esc(fmtRuDateTime(refreshStatus.finished_at)) + ")" : ""} не удался — текст не обновлён.`
    : data.reason === "not_generated_yet" ? "Карты и Сводки ещё нет."
    : `Карта и Сводка отстают на ${data.changed_tasks_count} ${склонИзменений(data.changed_tasks_count)} задач.`;
  // Что значит строка — за «i» (дефект владелицы 20.10.2026: значок был голым `span aria-hidden` без текста и не раскрывался
  // ничем). Механизм общий: `.tip` > `button.tip-ico` + `.tip-body`, как у «i» в «Общем пароле» (`подсказкаПаролейHtml`).
  const цена = "«Обновить» здесь и «Пересчитать» в шапке — один и тот же платный пересчёт, несколько минут; между " +
    "пересчётами по кнопке перерыв 60 мин (кроме суперадминистратора). После протокола пересчёт идёт сам.";
  const подсказка = failed
    ? `Карта и Сводка остались в прежней версии: последний пересчёт не удался. ${цена}`
    : data.reason === "not_generated_yet"
      ? `Карта и Сводка ещё ни разу не собирались. ${цена}`
      : `Карта и Сводка собраны до последних изменений задач: ${data.changed_tasks_count} ${склонИзменений(data.changed_tasks_count)} не учтены. ${цена}`;
  // Платное действие — не основной кнопкой (задание, раздел 6): ссылкой, с ценой и временем рядом.
  const refreshBtn = `<button class="link" id="staleness-refresh-btn">Обновить</button><span class="reg-sub">платный пересчёт, 2–3 мин</span>`;
  // Одна приглушённая строка со значком, без цветной плашки (оформление «Линия с элементами», 13.10.26).
  $stalenessBanner.innerHTML = `
    <div class="quiet-line" role="status">
      <span class="tip"><button type="button" class="tip-ico" aria-label="Что значит эта строка">i</button><span class="tip-body" role="tooltip">${esc(подсказка)}</span></span>
      <span>${message}</span>
      ${refreshBtn}
    </div>`;
  // «Обновить» — тот же путь, что «Пересчитать» в шапке (20.10.2026): одна функция, одна ручка, перерыв и замок — на сервере.
  // Прежний свой обработчик ответа не читал: на `pause` рисовал «Идёт обновление…», а опрос тут же кончался тостом
  // «обновлены» — ложный успех.
  document.getElementById("staleness-refresh-btn")?.addEventListener("click", () => запуститьПересчёт());
}

// --- Дашборд ---------------------------------------------------------------

function taskResponsibleHtml(t) {
  return t.responsible_text ? esc(t.responsible_text)
    : t.responsible_user_id ? esc(человекКоманды(t.responsible_user_id)?.full_name || "user #" + t.responsible_user_id)
    : '<span class="page-sub">Не назначен</span>';
}

// Срок — из поля срока; у старых задач он бывает только в тексте статуса («В работе, до 15.10.26»).
// Правило владельца 12.10.26: срок в день совещания — «сегодня (дд.мм.гггг)», не голой датой (её путают с датой постановки);
// срок «к следующему совещанию» — дата + «(оценка)». Как прозвучало на совещании — во всплывающей подсказке.
function taskDueText(t) {
  if (t.due_date) {
    const d = fmtRuDate(t.due_date);
    // Списки задач (реестр, панели) — срок без слова «сегодня», просто дата (владелец 13.10.26); «сегодня (дата)» остаётся только
    // в протоколе той встречи, где срок так прозвучал (решение 12.10.26) — там его пишет сервер, не эта функция
    if (t.due_kind === "оценка") return `${d} (оценка)`;
    return d;
  }
  const m = String(t.status_detail || "").match(/до\s+(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)/);
  return m ? m[1] : "";
}

// Номер и дата постановки — одна ячейка (владелец 02.10.26: «рядом с номером тонко прописана дата её постановки»).
// Номер — по порядку с 1 в этой таблице, внутренний номер задачи человеку не показывается (правило владельца 24.09.26,
// возвращено 02.10.26 вечером: «нумерация для пользователя всегда с 1-цы во всех таблицах, внутренний номер не показываем»).
// «Актуализировать» — ответственный задачи, админ проекта и супер-админ (решение владельца 02.10.26, письмо 49 Планёрки).
// Кому можно — считает сервер (`can_actualize` в списке задач, правило `task_service.is_responsible`); своей копии правила здесь
// нет (обход 02.10 вечер: две копии давали одни и те же ложные отказы). Сервер всё равно проверит запрос.
function canActualize(t) {
  if (isAdmin()) return true;
  return t.can_actualize === true;
}

// Задача под вопросом (решение владельца 15.10.26, обе системы одинаково): «без опоры в записи» / «не найдено в записи» — в
// реестре не текстом, а небольшой неброской точкой приглушённого цвета, без текста; подсказка при наведении «под вопросом:
// <причина> — решить в «Разборе»». Видна только администраторам; выключатель на пилот — «Мониторинг» (по умолчанию вкл.).
const ПОМЕТКИ_ВОПРОСА = ["не найдено в записи", "без опоры в записи"];
let отметкаВопроса = true;                      // до ответа сервера — как по умолчанию
async function обновитьОтметкуВопроса() {
  // выключатель читают все роли: пометку «под вопросом» с 20.10.2026 видят все (решение владелицы); нет доступа — по умолчанию
  // Сведение 18.10.26: выключатель — ручка линии локальной машины `/project-status/under-question-mark` ({enabled})
  try { отметкаВопроса = (await api("/project-status/under-question-mark", { вне_показа: true })).enabled !== false; }
  catch (e) { /* остаётся прежнее */ }
  отметкаПодВопросомВключена = отметкаВопроса;
}
function точкаВопроса(t) {
  // всем ролям с 20.10.2026 (решение владелицы): участнику `source_anchor` пуст, задачу узнают по `under_question_label`
  if (!отметкаВопроса || !задачаПодВопросом(t)) return "";
  // подпись причины — с сервера (общая таблица doubt_labels, одинаковая с Планёркой; поле линии локальной машины)
  // С 20.10.2026 (решение владелицы, как в Планёрке): задача «под вопросом» стоит в «Все в работе», пометка — заметная, но
  // спокойная: та же точка и слово «под вопросом» приглушённым цветом (без новых цветов); причина — подсказкой; ведёт на
  // «Разбор», вид «Задачи» (с 25.10.2026, решение владелицы: одно место решения; прежде — страница «Под вопросом», ещё раньше —
  // точка-ссылка на «Конфликты»).
  const подсказка = `под вопросом: ${t.under_question_label || t.source_anchor}${isAdmin()
    ? " — решить в «Разборе»" : " — ждёт подтверждения администратора"}`;
  // точка — ссылкой на «Разбор» у администратора; у остальных ролей его нет — точка без ссылки
  const точка = isAdmin() ? `<a href="#razbor/tasks" class="q-dot uq-dot" title="${esc(подсказка)}" aria-label="${esc(подсказка)}"></a>`
    : `<span class="q-dot uq-dot" title="${esc(подсказка)}" aria-label="${esc(подсказка)}"></span>`;
  return ` ${точка}<span class="uq-label" title="${esc(подсказка)}">под вопросом</span>`;
}

// Формулировка и под ней тонко «поставлена ДД.ММ.ГГ» — как в реестре «Данных проекта» и в .docx (владелец 02.10.26: «сделай
// подписи — поставлена дата — как в «Данных проекта», везде по реестрам, единообразно»). Раньше дата стояла под номером.
// Задача «под вопросом» (ответы владельца 15.10.26, так же, как в Планёрке): «без опоры в записи» (04.10.26) и «не найдено
// в записи» (документ 14, п. 4д). Текстовой подписи под формулировкой больше нет — маленькая приглушённая точка перед ней,
// причина во всплывающей подсказке. Только администраторам; участник не видит ничего. Временная на пилот: выключатель на
// «Мониторинге» (`/project-status/under-question-mark`, по умолчанию включён).
let отметкаПодВопросомВключена = true;
const ПРИЧИНЫ_ПОД_ВОПРОСОМ = ["не найдено в записи", "без опоры в записи"];

function отметкаПодВопросом(t) {
  if (!t || !ПРИЧИНЫ_ПОД_ВОПРОСОМ.includes(t.source_anchor) || !isAdmin() || !отметкаПодВопросомВключена) return "";
  if (t.status && t.status !== "active") return "";
  // Подпись — по общей с Планёркой таблице `doubt_labels` (15.10.26); карточка обязательна у каждой такой задачи.
  const подсказка = `под вопросом: ${t.under_question_label || t.source_anchor} — решить в «Разборе»`;
  return `<span class="uq-dot" title="${esc(подсказка)}" aria-label="${esc(подсказка)}"></span>`;
}

function taskDescHtml(t) {
  const d = fmtRuDate(t.date_set);
  // Сведение 18.10.26: точка «под вопросом» — линии локальной машины (`отметкаПодВопросом`), перед формулировкой
  return `${отметкаПодВопросом(t)}${esc(t.description)}${d ? ` <span class="doc-cell-sub">поставлена ${esc(d)}</span>` : ""}`;
}

// Решение 17.09.26 — «Выполнено» раньше срабатывало по одному клику
// сразу, в общей группе с «Комментарий»/«Изменить текст» — случайный
// промах мимо соседней кнопки мог закрыть задачу непреднамеренно.
// Теперь своя колонка последней (осознанный клик отдельно от прочих
// действий) и отсрочка с возможностью отменить — реальный запрос на
// закрытие уходит только по истечении отсчёта. Первая версия меняла
// содержимое самой ячейки — раздвигало высоту строки таблицы (жалоба
// пользователя). Теперь — плавающая подсказка поверх страницы
// (position:fixed, привязана к кнопке через getBoundingClientRect,
// не участвует в потоке документа), кнопка на время отсчёта просто
// дизейблится на месте.
const DONE_UNDO_SECONDS = 2;

// Отложенное действие с «Отменить» — ОДИН механизм на «Выполнено» и смену роли (письмо 47 Планёрки, 02.10.26: у двух
// раздельно написанных механизмов нашлись пять общих бед). Подсказка: прижата к видимой области (не уходит за край окна и
// не ложится на левое меню), пересчитывается на любой прокрутке, включая прокрутку внутри рамок; при уходе с экрана
// снимается (само действие уходит — выбор осознанный); второй отсчёт в той же строке не стартует, кнопки строки на время
// отсчёта недоступны.
function startUndoCountdown({ anchor, text, onCommit, onCancel }) {
  const row = anchor.closest("tr") || anchor.parentElement;
  if (row?.dataset.pending) return false;
  if (row) row.dataset.pending = "1";
  row?.classList.add("row-pending");
  const locked = row ? [...row.querySelectorAll("button, select")].filter(el => !el.disabled) : [anchor];
  locked.forEach(el => { el.disabled = true; });
  const popup = document.createElement("div");
  popup.className = "task-done-popup";
  let remaining = DONE_UNDO_SECONDS;
  popup.innerHTML = `<span class="task-done-countdown">${esc(text(remaining))}</span>
    <button class="btn-sm task-done-undo" type="button">Отменить</button>`;
  document.body.appendChild(popup);
  const nav = document.querySelector(".sidebar");
  const place = () => {
    if (!anchor.isConnected) { popup.remove(); return; }
    const r = anchor.getBoundingClientRect();
    const w = popup.offsetWidth, h = popup.offsetHeight;
    const minLeft = (nav ? Math.max(0, nav.getBoundingClientRect().right) : 0) + 8;
    let left = r.left - 10 - w;                      // слева от кнопки, как раньше
    if (left < minLeft) left = Math.min(r.right + 10, innerWidth - w - 8);   // не помещается — справа
    left = Math.max(minLeft, Math.min(left, innerWidth - w - 8));
    const top = Math.max(8, Math.min(r.top + r.height / 2 - h / 2, innerHeight - h - 8));
    popup.style.left = `${left}px`; popup.style.top = `${top}px`;
  };
  popup.style.transform = "none"; popup.style.marginLeft = "0";
  place();
  const onScroll = () => place();
  window.addEventListener("scroll", onScroll, { passive: true, capture: true });
  window.addEventListener("resize", onScroll, { passive: true });
  const onLeave = () => popup.remove();
  window.addEventListener("hashchange", onLeave, { once: true });
  const tick = setInterval(() => {
    remaining -= 1;
    const c = popup.querySelector(".task-done-countdown");
    if (c) c.textContent = text(Math.max(remaining, 0));
    place();
  }, 1000);
  const cleanup = () => {
    clearInterval(tick);
    window.removeEventListener("scroll", onScroll, { capture: true });
    window.removeEventListener("resize", onScroll);
    window.removeEventListener("hashchange", onLeave);
    popup.remove();
    if (row) { delete row.dataset.pending; row.classList.remove("row-pending"); }
    locked.forEach(el => { if (el.isConnected) el.disabled = false; });
  };
  const timer = setTimeout(() => { cleanup(); onCommit(); }, DONE_UNDO_SECONDS * 1000);
  popup.querySelector(".task-done-undo").addEventListener("click", () => { clearTimeout(timer); cleanup(); onCancel?.(); });
  return true;
}

function startDelayedRoleChange(sel, users) {
  const u = users.find(x => String(x.id) === sel.dataset.id);
  const prev = sel.dataset.prev, newRole = sel.value;
  const label = sel.selectedOptions[0]?.textContent || newRole;
  const started = startUndoCountdown({
    anchor: sel,
    text: (n) => `«${u.full_name}»: ${label} через ${n}с`,
    onCommit: async () => {
      try {
        await api(`/users/${u.id}`, { method: "PATCH", json: { access_role: newRole } });
        toast(`Роль изменена: «${u.full_name}» — ${label}`);
        await loadUsersForWhoAmI();
        if (currentRouteParts()[0] === "team") renderTeam();
      } catch (e) { toast(e.message, true); if (sel.isConnected) sel.value = prev; }
    },
    onCancel: () => {
      if (sel.isConnected) sel.value = prev;       // экран не должен врать: запрос не ушёл — в списке прежняя роль
      toast("Смена роли отменена");
    },
  });
  if (!started) sel.value = prev;
}

function wireTaskDoneCell(cell) {
  const btn = cell.querySelector(".task-done");
  if (!btn) return;
  const taskId = btn.dataset.id;
  btn.addEventListener("click", () => startDelayedDone(taskId, btn));
}

function startDelayedDone(taskId, btn) {
  startUndoCountdown({
    anchor: btn,
    text: (n) => `Выполнено через ${n}с`,
    onCommit: async () => {
      try {
        await api(`/tasks/${taskId}/status`, { method: "PATCH", json: { new_status: "done" } });
        toast("Статус обновлён");
        await погаситьСтроку(btn);
        render();
      } catch (e) { toast(e.message, true); }
    },
  });
}

function wireTaskActions() {
  $main.querySelectorAll(".task-done-cell").forEach(wireTaskDoneCell);
  // «Отметиться» — всем ролям (решение владельца 02.10.26, по письму 39 Планёрки): готовый ответ в один клик или свой
  // текст. Статус меняет только ведущий: отметка участника приходит ему карточкой в «Конфликты».
  $main.querySelectorAll(".task-note").forEach(btn => btn.addEventListener("click", () => {
    // Здесь текст только ПОКАЗЫВАЕТСЯ (с подписью «поставлена …» — так задачу узнают; замечание владельца 07.10.26), не
    // сохраняется — поэтому из ячейки. Окно «Изменить задачу» ниже сохраняет формулировку и берёт её из данных строки.
    // Аудит 13.10.26: в строке нового реестра (registry.js) ячейка — `.reg-desc`, а не `.task-desc-cell`; обработчик падал на
    // null, окно «Актуализировать» не открывалось
    // строка таблицы или строка ленты «Экрана встречи» (.live-task-row с data-desc, 19.10.2026)
    const row = btn.closest("tr, .live-task-row");
    const ячейка = row.querySelector(".task-desc-cell")?.cloneNode(true);
    ячейка?.querySelectorAll(".reg-meet").forEach(a => a.remove());       // ссылка «встреча … · протокол» — не текст задачи
    const taskText = ячейка ? ячейка.textContent.replace(/\s*·\s*$/, "").trim()
      : [row.querySelector(".reg-text")?.textContent, подписьБезСсылки(row.querySelector(".reg-sub"))].filter(Boolean).join(" — ").trim()
        || row.dataset.desc || "";
    const kinds = [["done", "Сделано — проверьте"], ["on_track", "Идёт по плану"], ["reschedule", "Нужен перенос срока"], ["question", "Есть вопрос"]];
    let kind = "text";
    const overlay = openModal("Актуализировать", `
      <div class="page-sub" style="margin-bottom:8px">${esc(taskText)}</div>
      <div class="hstack note-kinds" style="flex-wrap:wrap; gap:6px; margin-bottom:8px">
        ${kinds.map(([k, label]) => `<button type="button" class="btn-sm note-kind" data-kind="${k}">${esc(label)}</button>`).join("")}
      </div>
      <div class="field" id="note-due-field" hidden><label>Перенести срок до</label><input type="text" id="note-due" placeholder="ДД.ММ.ГГГГ" autocomplete="off"></div>
      <div class="field"><textarea id="note-text" rows="3" placeholder="Как идёт дело — своими словами (можно вместе с готовым ответом)"></textarea></div>
      ${isAdmin() ? "" : `<div class="page-sub">Отметку увидит ведущий; статус задачи меняет он.</div>`}
    `, async (ov) => {
      const text = ov.querySelector("#note-text").value.trim();
      const due = ov.querySelector("#note-due").value.trim();
      if (kind === "text" && !text) throw new Error("Выберите готовый ответ или напишите, как идёт дело");
      if (kind === "question" && !text) throw new Error("Напишите вопрос — ведущему нужно понять, о чём он");
      await api(`/tasks/${btn.dataset.id}/note`, { method: "POST", json: { kind, text: text || null, due_date: kind === "reschedule" ? (due || null) : null } });
      toast(isAdmin() ? "Отметка сохранена" : "Отметка сохранена — ведущий её увидит");
      render();
    });
    overlay.querySelectorAll(".note-kind").forEach(b => b.addEventListener("click", () => {
      const on = kind !== b.dataset.kind;
      overlay.querySelectorAll(".note-kind").forEach(x => x.classList.remove("btn-primary"));
      kind = on ? b.dataset.kind : "text";
      if (on) b.classList.add("btn-primary");
      overlay.querySelector("#note-due-field").hidden = kind !== "reschedule";
      if (kind === "reschedule") overlay.querySelector("#note-due").focus();
    }));
    overlay.querySelector("#note-text").focus();
  }));
  // Точечная ручная правка формулировки задачи (решение 14.09.26) — не
  // всегда формулировка ИИ пригодна для использования как есть. С
  // 16.09.26 тем же экраном правится и «Ответственный» — отдельной
  // пиктограммы решили не заводить (запрос пользователя). Сначала было
  // два последовательных prompt() подряд — пользователь не понимал, что
  // за первым диалогом идёт второй; теперь одно модальное окно с обоими
  // полями сразу. Ручка PATCH /tasks/{id}/responsible уже существовала в
  // бэкенде, фронт её просто не вызывал.
  // Решение 17.09.26 — добавлено поле «Статус» вместо отдельного блока
  // «Задачи без подтверждённого статуса» (убран, см. renderDashboard) —
  // прямая правка вместо неявного сигнала по накопленным пропускам.
  // Список — только обязательные значения (сам enum TaskStatus), не
  // свободный текст, по просьбе пользователя.
  const STATUS_OPTIONS = [
    ["active", "В работе"],
    ["done", "Выполнено"],
    ["dropped", "Снято"],
  ];
  $main.querySelectorAll(".task-edit-desc").forEach(btn => btn.addEventListener("click", async () => {
    const row = btn.closest("tr");
    // Проект — выбором из справочника, не свободным текстом (решение владельца 13.10.26)
    let проекты = [];
    try { проекты = await справочникПроектов(); } catch (e) { /* справочник недоступен — поле проекта без выбора */ }
    const currentProject = row.dataset.projId || "";
    // Стенд 13.10.26 (находка «Мониторинга»): формулировка бралась из textContent ячейки — вместе с подписью «поставлена
    // дд.мм.гг» и пометками «не найдено в записи» / «без опоры в записи»; правка текста сохраняла этот хвост в саму задачу.
    // Теперь — из данных задачи. Ответственный — так же: в ячейке бывает «user #N» и подпись «Не назначен».
    const currentText = row.dataset.desc || "";
    const currentResponsible = row.dataset.resp || "";
    const currentStatus = row.dataset.status || "active";
    const currentDue = row.dataset.due || "";
    const overlay = openModal("Изменить задачу", `
      <div class="field"><label>Формулировка задачи</label><textarea id="modal-description" rows="3">${esc(currentText)}</textarea></div>
      <div class="field"><label>Ответственный</label><input type="text" id="modal-responsible" value="${esc(currentResponsible)}" placeholder="Не назначен" autocomplete="off"></div>
      <div class="field"><label>Статус</label><select id="modal-status">
        ${STATUS_OPTIONS.map(([v, label]) => `<option value="${v}"${v === currentStatus ? " selected" : ""}>${esc(label)}</option>`).join("")}
      </select></div>
      <div class="field"><label>Срок</label><input type="text" id="modal-due" value="${esc(currentDue)}" placeholder="ДД.ММ.ГГГГ, пусто — без срока" autocomplete="off"></div>
      ${проекты.length ? `<div class="field"><label for="modal-project">Проект и подпроект</label><select id="modal-project">
        <option value="">— не указан —</option>
        ${проекты.map(п => `<option value="${п.id}"${String(п.id) === currentProject ? " selected" : ""}>${esc(п.name)}</option>`).join("")}
      </select></div>` : ""}
    `, async (ov) => {
      const description = ov.querySelector("#modal-description").value.trim();
      const responsible = ov.querySelector("#modal-responsible").value.trim();
      const status = ov.querySelector("#modal-status").value;
      const due = ov.querySelector("#modal-due").value.trim();
      const project = ov.querySelector("#modal-project") ? ov.querySelector("#modal-project").value : currentProject;
      // Обход 02.10 вечер: пустая формулировка молча пропускалась, окно закрывалось с «Задача обновлена» — ничего не сохранив.
      if (!description) throw new Error("Формулировка задачи не может быть пустой");
      if (description === currentText && responsible === currentResponsible && status === currentStatus && due === currentDue
          && project === currentProject) {
        throw new Error("Изменений нет — поправьте поле или закройте окно");
      }
      if (due !== currentDue) {      // срок — первым: ошибка в дате не должна оставить остальные правки наполовину
        await api(`/tasks/${btn.dataset.id}/due`, { method: "PATCH", json: { due_date: due || null } });
      }
      if (description && description !== currentText) {
        await api(`/tasks/${btn.dataset.id}/description`, { method: "PATCH", json: { description } });
      }
      if (responsible !== currentResponsible) {
        await api(`/tasks/${btn.dataset.id}/responsible`, { method: "PATCH", json: { responsible_text: responsible || null } });
      }
      if (status !== currentStatus) {
        await api(`/tasks/${btn.dataset.id}/status`, { method: "PATCH", json: { new_status: status } });
      }
      if (project !== currentProject) {
        await api(`/tasks/${btn.dataset.id}/project`, { method: "PATCH", json: { project_id: project ? Number(project) : null } });
      }
      toast("Задача обновлена");
      render();
    });
    overlay.querySelector("#modal-description").focus();
  }));
}

// Подпись строки реестра без ссылки «встреча … · протокол» — для окна «Актуализировать» (второй проход аудита 13.10.26)
function подписьБезСсылки(el) {
  if (!el) return "";
  const копия = el.cloneNode(true);
  копия.querySelectorAll("a.reg-meet").forEach(a => a.remove());
  return копия.textContent.replace(/(\s*·\s*)+/g, " · ").replace(/^\s*·\s*|\s*·\s*$/g, "").trim();
}

// Справочник проектов компании (13.10.26) — один раз за загрузку страницы: меняется командой на сервере, не из экрана
let _справочникПроектов = null;
async function справочникПроектов() {
  if (!_справочникПроектов) _справочникПроектов = await api("/tasks/projects", { вне_показа: true });
  return _справочникПроектов;
}

// --- Встречи -----------------------------------------------------------

// Ищет ДД.ММ или ДД.ММ.ГГ(ГГ) прямо в имени файла — решение 12.09.26,
// защита от загрузки источника не в ту встречу (реальный случай:
// файл «...22.06.docx» загружен во встречу с датой 12.09). Возвращает
// ISO-дату или null, если в имени файла дат нет/не распозналась.
// Даты в имени файла — тот же разбор, что на сервере (`meeting_service.dates_in_name`, 30.09.26, по находке
// Планёрки «08», разд. 1): год первым, найденное вымарывается перед следующим шаблоном, расширение отрезается,
// год ±1 от года встречи, шесть цифр подряд — не дата. Прежний разбор здесь ждал день первым и только точку:
// «2026_09_05» не проверялся вовсе, а «Договор … 12.09.2019» давал ложный вопрос «не та встреча?».
const _NAME_DATE_PATTERNS = [
  // Разделители внутри даты одинаковые (\2), иначе «2026 15.07» из «10.09.2026 11.05» читалось датой (30.09.26).
  ["ymd", /(?<!\d)(\d{4})([._\- ])(\d{1,2})\2(\d{1,2})(?!\d)/g],
  ["dmy", /(?<!\d)(\d{1,2})([._\- ])(\d{1,2})\2(\d{4}|\d{2})(?!\d)/g],
  ["dm", /(?<!\d)(\d{1,2})[._\-](\d{2})(?!\d)/g],
];

function datesInName(name, defaultYear) {
  let text = String(name || "").replace(/\.[0-9]*[A-Za-z][A-Za-z0-9]{0,6}$/, "");
  const out = [];
  for (const [kind, rx] of _NAME_DATE_PATTERNS) {
    if (kind === "dm" && out.length) break;   // есть полная дата — «ЧЧ.ММ» рядом с ней это время
    text = text.replace(rx, (m, ...g) => {
      const [a, b, c] = kind === "dm" ? [g[0], g[1], null] : [g[0], g[2], g[3]];   // g[1] у полных дат — разделитель
      let y, mo, d;
      if (kind === "ymd") { y = +a; mo = +b; d = +c; }
      else if (kind === "dmy") { d = +a; mo = +b; y = +c; if (y < 100) y += 2000; }
      else { d = +a; mo = +b; y = defaultYear; }
      if (Math.abs(y - defaultYear) <= 1) {
        const dt = new Date(Date.UTC(y, mo - 1, d));
        if (dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d) {
          const iso = `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          if (!out.includes(iso)) out.push(iso);
        }
      }
      return "#".repeat(m.length);
    });
  }
  return out;
}

function daysBetween(iso1, iso2) {
  return Math.abs((new Date(iso1) - new Date(iso2)) / 86400000);
}

async function renderMeetings(rest) {
  if (rest[0] && rest[1] === "protocol") return renderMeetingProtocol(rest[0]);
  // «Единицы» на время тестирования — табло супер-админа, со страницы встречи убраны (владелец 02.10.26)
  if (rest[0] && rest[1] === "units") { location.replace(isSuperAdmin() ? `#units/${rest[0]}` : `#meetings/${rest[0]}`); return; }
  if (rest[0]) return renderMeetingDetail(rest[0]);

  // Список встреч рисует nav.js (`renderProtocols`), создание встречи — одна точка, «Подготовка встречи» (`renderPrep`,
  // решение владелицы 21.10.2026). Прежний список с формой создания и строкой «открыть · создать протокол» удалён: его
  // читала только прежняя «Подготовка», которая его больше не вызывает.
  location.replace("#meetings");
}

const ARCHIVE_CUTOFF_DAYS = 28;


const VERIFY_CATEGORY_LABELS = { "тема": "Не по теме источника", "атрибуция": "Не подтверждено источником", "подкладка": "Замечания", "формат": "Формат", "тон": "Тон" };

// Страница встречи (решение 19.09.26, файл «Бизнес задачи в работе с проектом.docx»): два независимых
// раздела. «План встречи» — собирается из трёх блоков (протокол прошлой встречи, материалы к этой
// встрече, актуальные задачи); ни один блок не обязателен. «Протокол встречи» — после проведения:
// заметки/транскрипция этой встречи (файл или вставленный текст) → Протокол, без Плана следующей.

// Вставка текста вместо файла: заметки часто просто копируют из чата или блокнота.

function wirePasteText(idPrefix, endpoint, onDone) {
  const btn = document.getElementById(`${idPrefix}-add`);
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const ta = document.getElementById(`${idPrefix}-text`);
    const text = ta.value.trim();
    if (text.length < 20) { toast("Вставьте текст заметок или транскрипции (не короче 20 символов)", true); return; }
    btn.disabled = true;
    try {
      const result = await api(endpoint, { method: "POST", json: { text } });
      toast("Текст добавлен как источник");
      if (result && result.relevance_warnings && result.relevance_warnings.length) {
        toast("Возможно, не тот текст — " + result.relevance_warnings.join(" "), true);
      }
      onDone();
    } catch (e) { toast(e.message, true); btn.disabled = false; }
  });
}

// --- Состояние сборки на экране (12.10.26) --------------------------------------------------------
// Сборку ведёт СЕРВЕР, а экран лишь показывает её ход. Пока это жило только в замыкании обработчика
// кнопки, любое переключение экрана или окна «сбрасывало» показ: кнопка возвращалась в исходный вид,
// будто ничего не запускалось, а повтор упирался в «уже выполняется» (живой случай владельца: протокол
// 08.10 пересобирался, человек переключал вкладки — и круг «Документ не подготовлен → Повторить → то
// же самое»). Теперь состояние переживает перерисовку: экран спрашивает сервер
// (`GET /meetings/{id}/generation`) и продолжает показывать ход сборки.
const идущиеСборки = new Map();          // id (строка) → {startedAt, тикер}
let _слежениеЗаСборкой = null;

// Очередь сборок (14.10.26): строки «собирается: …, шаг …» и «в очереди: N, перед вашей — …» готовит сервер.
function строкиОчереди(очередь) {
  return ((очередь && очередь.строки) || []).join("; ");
}

function показатьХодСборки(id, { findingsId, btnId, since, queued, lines } = {}) {
  const box = document.getElementById(findingsId || "verify-findings-minutes");
  // 21.10.2026: здесь стояла строка с несуществующей переменной `queue` (сведение 18.10) — показ хода сборки падал
  // ReferenceError, и повторное нажатие во время сборки выглядело сбоем «Документ не подготовлен»
  if (box) {
    const с_каких = since ? ` — начата в ${esc(fmtRuDateTime(String(since).replace(/Z$/, "")))}` : "";
    const очередь = (lines || []).length ? `<div class="page-sub" id="gen-queue-lines" style="margin:6px 0">${(lines || []).map(esc).join("<br>")}</div>` : "";
    box.innerHTML = `<div class="card" role="status">
      <div><b>${queued ? "Сборка в очереди" : "Сборка идёт"}</b>${queued ? "" : с_каких}</div>${очередь}
      <div class="page-sub" style="margin:6px 0">Это не сбой и не «ничего не запускалось»: документ собирает
        сервер, и переключение экранов ему не мешает. Результат появится на этом экране сам.</div>
      <div class="hstack"><button class="btn-sm" id="gen-check-now">Проверить сейчас</button></div></div>`;
    document.getElementById("gen-check-now")?.addEventListener("click", () => перерисоватьЭкранВстречи(id));
  }
  // Счётчик на кнопке считаем от РЕАЛЬНОГО начала сборки (его сообщил сервер), а не от момента, когда
  // экран о ней узнал: иначе после переключения вкладки он показывал бы «0 сек» про сборку, идущую час.
  const начало = since ? new Date(String(since)).getTime() : NaN;
  const ключ = String(id);
  const запись = идущиеСборки.get(ключ) || { startedAt: Number.isFinite(начало) ? начало : Date.now() };
  запись.queued = !!queued;
  идущиеСборки.set(ключ, запись);
  if (!запись.тикер) {
    const b = document.getElementById(btnId || "prepare-minutes-btn");
    if (b) { b.disabled = true; b.textContent = queued ? "В очереди…" : "Генерирую…"; }
    запись.тикер = setInterval(() => {
      const кнопка = document.getElementById(btnId || "prepare-minutes-btn");
      if (!кнопка) { clearInterval(запись.тикер); запись.тикер = null; return; }   // человек ушёл на другой экран
      const сек = Math.max(0, Math.floor((Date.now() - запись.startedAt) / 1000));
      кнопка.textContent = запись.queued ? `В очереди… (${сек} сек)` : `Генерирую… (${сек} сек)`;
    }, 1000);
  }
}

function перерисоватьЭкранВстречи(id) {
  const route = (location.hash || "").replace(/^#/, "");
  return route.startsWith(`meetings/${id}/protocol`) ? renderMeetingProtocol(id) : renderMeetingDetail(id);
}

function остановитьСлежение(id) {
  clearInterval(_слежениеЗаСборкой);
  _слежениеЗаСборкой = null;
  const запись = идущиеСборки.get(String(id));
  if (запись && запись.тикер) clearInterval(запись.тикер);
  идущиеСборки.delete(String(id));
}

function начатьСлежениеЗаСборкой(id, redraw) {
  clearInterval(_слежениеЗаСборкой);
  _слежениеЗаСборкой = setInterval(async () => {
    const route = (location.hash || "").replace(/^#/, "");
    if (!route.startsWith(`meetings/${id}`)) { clearInterval(_слежениеЗаСборкой); return; }   // ушли с экрана
    let состояние;
    try { состояние = await api(`/meetings/${id}/generation`); } catch (e) { return; }        // нет связи — ждём
    const строки = document.getElementById("gen-queue-lines");
    if (строки && состояние.queue_lines) строки.innerHTML = состояние.queue_lines.map(esc).join("<br>");
    const запись = идущиеСборки.get(String(id));
    if (запись) запись.queued = !!состояние.queued && !состояние.running;
    if (состояние.running || состояние.queued) return;
    остановитьСлежение(id);
    redraw();     // сборка закончилась — экран покажет результат: протокол, замечания проверки, кнопки
  }, 10000);
}

// «Замечаний проверки: N — в карточках администратора» — та же формулировка, что у сервера (текст_замечаний).
function текстЗамечаний(result, документ = "Протокол") {
  const n = Number((result && result.findings_count) || 0);
  if (n) return `Замечаний проверки: ${n} — в карточках администратора`;
  return документ === "План" ? "Замечания проверки — мелкие, в журнале проверок" : "Замечания проверки — мелкие, под протоколом";
}

// Запуск генерации (Протокол или План): счётчик секунд, замечания верификации, итоговое сообщение.
async function runMeetingGeneration({ id, btnId, endpoint, findingsId, idleLabel, okToast, partialToast, rerender, onSaved }) {
  const redraw = rerender || ((v, f) => renderMeetingDetail(id, v, f));
  const btn = document.getElementById(btnId);
  btn.disabled = true;
  const startedAt = Date.now();
  let ждёмСервер = false;      // сборка уже идёт: кнопку не «возвращаем в исходный вид», показываем её ход
  const tick = () => {
    const sec = Math.floor((Date.now() - startedAt) / 1000);
    btn.textContent = `Генерирую… (${sec} сек)`;
    // Долгое ожидание — не сбой, но пользователю нужен выход: результат можно проверить, не дожидаясь ответа.
    // Д10: панель «дольше обычного» добавляется, а не затирает строку ожидания модели; пока сборка ждёт недоступную модель,
    // её не показываем — «при нагрузке на модель» спорило бы с «модель недоступна»
    if (sec === 600 && document.getElementById("gen-model-wait")?.hidden !== false) {
      const box = document.getElementById(findingsId);
      if (box) {
        box.insertAdjacentHTML("beforeend", generationSlowHtml());
        box.querySelector("#gen-slow button")?.addEventListener("click", () => redraw());
      }
    }
  };
  tick();
  const timer = setInterval(tick, 1000);
  // Панель источников раскрываем: внутри неё печатается и ход сборки, и замечания проверки, а сама она
  // по умолчанию свёрнута. Без этого результат проверки уходил бы в скрытый блок (09.10.26).
  openSourcePanel(document.getElementById(findingsId)?.closest(".src-bar-panel"));
  document.getElementById(findingsId).innerHTML =
    `<div class="page-sub" id="gen-wait-line" style="margin-top:8px">Идёт реальный вызов ИИ — обычно от минуты до 5, иногда дольше. Страница не зависла, просто ждём ответ.</div>
     <div class="form-hint" id="gen-model-wait" style="margin-top:8px" hidden></div>`;
  // Модель недоступна — сборка ждёт и продолжит сама (19.10.26, находка хаос-тестов 18.10, зеркально Планёрке): строку
  // пишет сервер (`waiting_model`), экран спрашивает её раз в 10 с, пока идёт кнопка.
  const ждётМодель = setInterval(async () => {
    const место = document.getElementById("gen-model-wait");
    if (!место) return;
    let с = null;
    try { с = await api(`/meetings/${id}/generation`); } catch (e) { return; }
    место.textContent = (с && с.waiting_model) || "";
    место.hidden = !(с && с.waiting_model);
    // Д10 (проход 2, 21.10.2026): «просто ждём ответ» и «модель недоступна» стояли рядом и спорили — пока сборка ждёт
    // модель, говорит одна строка сервера
    const строкаОжидания = document.getElementById("gen-wait-line");
    if (строкаОжидания) строкаОжидания.hidden = !!(с && с.waiting_model);
    const долго = document.getElementById("gen-slow");
    if (долго) долго.hidden = !!(с && с.waiting_model);
  }, 10000);
  try {
    const result = await api(endpoint, { method: "POST" });
    if (["already_running", "already_queued", "queued"].includes(result.status)) {
      // НЕ сбой: сборка уже идёт (её начали раньше — в этом окне, в другом или с другого экрана).
      // Показываем её ход и ждём результат — именно этого не хватало владельцу 12.10.26.
      // С 14.10.26 сборки идут одной очередью по датам встреч: «в очереди, место N» — тоже не сбой.
      ждёмСервер = true;
      const вОчереди = result.status !== "already_running";
      toast(result.reason || (вОчереди ? "Сборка в очереди — начнётся сама" : "Сборка уже идёт — показываю её ход"), false);
      показатьХодСборки(id, { findingsId, btnId, since: result.since, queued: вОчереди,
                              lines: (result.queue && result.queue.строки) || [] });
      начатьСлежениеЗаСборкой(id, redraw);
      return;
    }
    // Какой документ собирается — по адресу сборки: подписи «собран, но не сохранился» у Протокола и Плана свои.
    const документ = endpoint.includes("/prepare-plan") ? "План" : "Протокол";
    if (result.status === "verification_failed") {
      // С 15.10.26 (решения владельца) и Протокол, и План с замечаниями сохраняются сами; сюда документ попадает,
      // только если упало само сохранение.
      toast(result.save_failed
        ? `${документ} собран, но не сохранился${result.save_error ? ": " + result.save_error : ""} — сохраните его кнопкой над документом`
        : "Верификация нашла замечания — документ не сохранён, см. ниже", true);
      if (result.can_accept && result.verdict) result.verdict.can_accept = true;
      redraw(result.verdict, findingsId);
      return;
    }
    if (result.saved_with_findings) {
      // Решение владельца 15.10.26: протокол сохранён сразу, замечания проверки — карточками
      toast(`Протокол сохранён. Замечания проверки (${result.findings_count || 0}) — карточками в «Конфликтах»`, false);
    }
    const ru = result.roadmap_update;
    // Документ с замечаниями проверки сохранён сразу (15.10.26): число замечаний и где они — в том же сообщении.
    if (result.accepted_with_findings) okToast = okToast + ". " + текстЗамечаний(result, документ);
    if (ru && ru.status === "skipped") toast(okToast + ". Карта и Сводка уже пересчитываются — обновятся отдельно");
    else if (ru && ru.status === "queued") toast(okToast + ". Карта и Сводка обновятся после протоколов в очереди сборок");
    else if (ru && ["running", "started"].includes(ru.status)) toast(okToast + ". Карта и Сводка обновляются в фоне");
    else if (ru && ru.status !== "saved") toast(partialToast, true);
    else toast(okToast);
    // Похожие задачи, не заведённые повторно (30.09.26, по находке Планёрки) — раньше терялись
    // молча: и в ответе были, и на экране нигде не показывались.
    // С 30.09.26 два случая разные: дословный повтор просто не заводится, а совпадение только по
    // предмету уходит карточкой в «Конфликты» — решает человек, одна это задача или две.
    // Что изменилось в реестре (письмо Планёрки «35»: сервер перечислял последствия, экран их не читал — человек видел
    // «сохранён» и не знал, что задачи закрыты). Новые задачи, сменённые статусы и закрытые по источнику — сразу.
    const closedBySource = result.closed_by_source || [];
    if (result.new_tasks_count !== undefined || closedBySource.length) {
      const parts = [`новых задач: ${result.new_tasks_count || 0}`];
      if (result.status_changes_count) parts.push(`изменён статус: ${result.status_changes_count}`);
      if (closedBySource.length) parts.push(`закрыты по словам встречи: ${closedBySource.join(", ")} — вернуть можно в «Реестре задач»`);
      toast("В реестре: " + parts.join("; "), false);
    }
    // Закрытия остановлены пределом вызовов прогона — одной строкой в итоге сборки (заход 3 хаос-тестов, 20.10.2026)
    if (result.build_note) toast("Итог сборки: " + result.build_note, true);
    const dd = result.dropped_duplicate_tasks || [];
    const same = dd.filter(d => d.rule === "text"), similar = dd.filter(d => d.rule !== "text");
    if (same.length) {
      toast(`Повторы уже заведённых задач не заведены (${same.length}): ` +
        same.map(d => `«${d.description.slice(0, 60)}»`).join(", "));
    }
    if (similar.length) {
      toast(`Похожие задачи (${similar.length}) не заведены сами — ждут решения в «Конфликтах»: ` +
        similar.map(d => `«${d.description.slice(0, 60)}»`).join(", "), true);
    }
    const ug = result.ungrounded_tasks || [];
    if (ug.length) {
      toast(`Задачи без опоры в тексте встречи (${ug.length}) заведены с пометкой — проверьте их в «Конфликтах»: ` +
        ug.map(d => `«${d.description.slice(0, 60)}»`).join(", "), true);
    }
    if (similar.length || ug.length) updateConflictsBadge();
    остановитьСлежение(id);
    if (onSaved) onSaved(); else redraw();
  } catch (e) {
    остановитьСлежение(id);
    btn.disabled = false; btn.textContent = idleLabel;
    showGenerationFailure(id, findingsId, e.message, btnId, redraw);
  }
  finally {
    clearInterval(timer);
    clearInterval(ждётМодель);
    // Сборку ведёт сервер: если он уже собирает, кнопку в исходный вид не возвращаем — за неё
    // отвечает «Генерирую…» из показа хода сборки, иначе экран снова выглядит как «ничего не запускалось».
    if (ждёмСервер) btn.disabled = true;
  }
}

// Выход по сбою (запрос 20.09.26): при ошибке генерации человек видит не только красный тост, а понятный итог —
// что произошло, что НЕ потеряно и что можно сделать дальше, в одном месте под кнопкой.
function generationSlowHtml() {
  return `<div class="card failure-panel" id="gen-slow" role="status">
    <div><b>Генерация идёт дольше обычного</b></div>
    <div class="page-sub" style="margin:6px 0">Обычно это 1–5 минут, при нагрузке на модель — дольше. Страница не зависла. Можно подождать или проверить, не сохранился ли результат.</div>
    <div class="hstack"><button class="btn-sm">Проверить результат</button></div>
  </div>`;
}

function showGenerationFailure(id, findingsId, message, btnId, redraw) {
  const technical = /что-то пошло не так|Failed to fetch|NetworkError|Internal|50\d|Внутренняя ошибка/i.test(message || "");
  const box = document.getElementById(findingsId);
  toast(technical ? "Не удалось подготовить документ" : message, true);
  if (!box) return;
  box.innerHTML = `<div class="card failure-panel" role="alert">
    <div><b>${technical ? "Не удалось подготовить документ" : "Документ не подготовлен"}</b></div>
    <div class="page-sub" style="margin:6px 0">${esc(technical ? "Произошёл сбой при обращении к модели или серверу." : message)}
      Ничего не потеряно: загруженные заметки и материалы на месте, неполный документ не сохранён.</div>
    <div class="hstack" style="flex-wrap:wrap">
      <button class="btn-sm btn-primary" id="${findingsId}-retry">Повторить</button>
      <button class="btn-sm" id="${findingsId}-check">Проверить, не сохранилось ли</button>
      ${technical && isSuperAdmin() ? `<a class="btn btn-sm" href="#system">Технические подробности — «Параметры системы»</a>` : ""}
    </div>
  </div>`;
  // Д5 (проход 2, 21.10.2026): «Повторить» после обрыва нажимал скрытую кнопку сборки плана напрямую — платная сборка без
  // подтверждения. Повтор плана идёт через главную кнопку (она спрашивает); у протокола подтверждение — в самой кнопке.
  document.getElementById(`${findingsId}-retry`)?.addEventListener("click", () =>
    document.getElementById(btnId === "prepare-plan-btn" && document.getElementById("plan-main-btn") ? "plan-main-btn" : btnId)?.click());
  document.getElementById(`${findingsId}-check`)?.addEventListener("click", () => (redraw || (() => renderMeetingDetail(id)))());
}

// «Из чего собирается план» — единый список (решение владельца 01.10.26, третий заход: «визуальный хаос» — одно и то же
// показывалось тремя способами: метки, список с галочками, таблица файлов). Каждый источник — одна строка одного вида:
// метка типа, название, пояснение, действие справа. Как список источников в NotebookLM или вложения в Jira.
// Крестик рисуется, а не символом «✕»: тонкие наклонные линии глифа Windows сглаживает цветной каймой, и одинаковые
// кнопки выглядели то синими, то красными в зависимости от положения на экране (жалоба 01.10.26).
// Удаление источника — корзина, а не крестик: крестик в списке над полосой читался как «закрыть список», и владелец
// 01.10.26 закрывала просмотр источника, а получала «Удалить этот файл?». Закрыть — отдельная кнопка «Свернуть».
const ICON_TRASH = `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.2c.05.7.6 1.3 1.3 1.3h4c.7 0 1.25-.6 1.3-1.3L12 4M6.8 7v4.5M9.2 7v4.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`;
const ICON_X = `<svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/></svg>`;
// Выгрузка локально распознанной расшифровки в Word (задача владельца 12.10.26): стрелка в лоток.
const ICON_DOWNLOAD = `<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v7.5M5 6.8L8 9.8l3-3M3 12.5h10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`;

function sourceRow(tag, title, sub, action) {
  return `<div class="src-row"><span class="src-tag">${esc(tag)}</span>
    <div class="src-main"><div class="src-title">${title}</div>${sub ? `<div class="src-sub">${sub}</div>` : ""}</div>
    <div class="src-action">${action || ""}</div></div>`;
}

function shortName(name) {
  const n = (name || "текст").replace(/\.[a-z0-9]{1,5}$/i, "");
  return n.length > 28 ? n.slice(0, 27) + "…" : n;
}

function plural(n, one, few, many) {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
}

function fileTag(name) {
  const m = /\.([a-z0-9]{1,5})$/i.exec(name || "");
  return m ? m[1].toLowerCase() : "файл";
}

function planSourcesHtml(basis, meeting, materials, admin) {
  const p = basis.previous;
  let prev;
  if (p.state === "minutes") {
    prev = sourceRow("протокол", `Протокол встречи ${esc(fmtRuDate(p.date))}`, "прошлая встреча",
      `<a href="#meetings/${p.meeting_id}/protocol?from=${meeting.id}">открыть</a>`);
  } else if (p.state === "source") {
    prev = sourceRow("заметки", `Заметки встречи ${esc(fmtRuDate(p.date))}`, "Протокола ещё нет — создастся при сборке плана",
      admin ? `<a href="#meetings/${p.meeting_id}/protocol?from=${meeting.id}">создать сейчас</a>` : "");
  } else if (p.state === "none") {
    prev = sourceRow("протокол", `Протокола встречи ${esc(fmtRuDate(p.date))} нет`,
      p.used_date ? `возьмём более ранний: ${esc(fmtRuDate(p.used_date))}` : "более ранних протоколов нет",
      admin ? `<a href="#meetings/${p.meeting_id}/protocol?from=${meeting.id}">добавить заметки</a>` : "");
  } else {
    prev = sourceRow("протокол", "Прошлых встреч в базе нет", "", "");
  }
  const tasks = basis.candidates_count
    ? `<details class="src-details"><summary>${sourceRow("задачи", `Задачи к встрече · ${basis.candidates_count}`,
        "срок подошёл, договорились обсудить, свежие комментарии", `<span class="src-link">показать</span>`)}</summary>
        <ul class="src-sublist">${basis.candidates_preview.map(c =>
          `<li>${esc(c.description)} <span class="src-sub">— ${esc(c.reasons.join("; "))}</span></li>`).join("")}
        ${basis.candidates_count > basis.candidates_preview.length ? `<li class="src-sub">…и ещё ${basis.candidates_count - basis.candidates_preview.length}</li>` : ""}</ul></details>`
    : sourceRow("задачи", "Задач к встрече нет", "срок не наступил, к встрече не отмечены", "");
  // Открытые вопросы реестра договорённостей — тоже основа Плана (п. 7, решение владелицы 21.10.2026)
  const nq = basis.open_questions_count || 0;
  const вопросы = nq
    ? `<details class="src-details"><summary>${sourceRow("вопросы", `Открытые вопросы с прошлых встреч · ${nq}`,
        "из реестра договорённостей", `<span class="src-link">показать</span>`)}</summary>
        <ul class="src-sublist">${(basis.open_questions_preview || []).map(q =>
          `<li>${esc(q.text)} <span class="src-sub">— ${esc(fmtRuDate(q.date))}</span></li>`).join("")}
        ${nq > (basis.open_questions_preview || []).length ? `<li class="src-sub">…и ещё ${nq - (basis.open_questions_preview || []).length}</li>` : ""}</ul></details>`
    : "";
  const files = materials.length
    ? `<div id="materials-list">${materials.map(m => sourceRow(fileTag(m.original_filename), esc(m.original_filename || m.kind),
        m.description ? esc(m.description) : "",
        (admin || (me && m.uploaded_by_user_id === me.id))   // удаляет автор или администратор (хаос-тест 02.10.26)
          ? `<button class="btn-icon src-delete delete-material-btn" data-id="${m.id}" title="Удалить файл" aria-label="Удалить файл">${ICON_TRASH}</button>`
          : "")).join("")}</div>`
    // Д11 (проходы 1–4, 21.10.2026): подсказка звала добавить файл «слева» — кнопка с 21.10.2026 вверху экрана, у отменённой её нет
    : meeting.status === "cancelled" ? `<div class="src-empty">Файлов нет.</div>`
    : `<div class="src-empty">Файлов пока нет — добавьте кнопкой «+ Добавить материал» вверху или перетащите файл на страницу.</div>`;
  const fallback = basis.fallback === "summary" ? `<div class="src-empty">Всё пусто — План соберётся как сжатая Сводка проекта.</div>`
    : basis.fallback === "empty" ? `<div class="src-empty">Всё пусто, Сводки ещё нет — План получится пустым.</div>` : "";
  return `<div class="src-list">
      <div class="src-panel-head"><span>Из чего собирается план</span><button type="button" class="btn-sm src-close" data-close-panel>Свернуть ▾</button></div>
      <div class="src-group">Из системы</div>
      ${prev}${tasks}${вопросы}
      <div class="src-group">Материалы к встрече · ${materials.length}</div>
      ${files}
      ${fallback}
    </div>`;
}

// Маршрут с необязательным ?from=<id встречи>: откуда пришли на страницу протокола — туда и возвращаем (запрос 20.09.26).
function hashParts() {
  const [path, qs] = (location.hash || "#dashboard").slice(1).split("?");
  return { parts: path.split("/"), query: new URLSearchParams(qs || "") };
}

// Название встречи без служебной подписи «Встреча ДД.ММ.ГГ» (она дублирует дату)
function cleanLabel(label) { return label && !/^Встреча\s+\d/.test(label) ? label : ""; }

// Подписи ссылок на протокол «есть / нет» (protocolLink) жили только в прежнем списке встреч — убраны с ним
// (21.10.2026): у будущей встречи «создать протокол» сбивал с толку, в «Подготовке» теперь колонки «План встречи» и «Протокол».

// Страница «Протокол встречи» (запрос 20.09.26): отдельная вкладка вместо блока внутри страницы встречи. Сюда ведут ссылки из
// списка встреч и с плашки «План встречи»; параметр ?from=<id> возвращает человека туда, откуда он пришёл, — после
// сохранения Протокола возврат автоматический (без лишних кликов).
// «Вёл встречу» (02.10.26, письмо 45 Планёрки; владелец — вариант «отметка + Вёл встречу»). Опознаёт код по записи; рядом —
// откуда решение, в подсказке — почему. Админ поправляет выбором; «определить по записи» возвращает решение автоматике.
// На задачи не влияет: у нас ведущий бывает и исполнителем.
const LEADER_SOURCE_RU = { "запись": "по записи", "отметка": "по отметке в «Команде»", "вручную": "указан вручную" };
function meetingLeaderLine(m, admin) {
  if (!m.leader_source) return "";
  const who = m.leader_user_id ? (allUsers.find(u => u.id === m.leader_user_id)?.full_name || "—")
    : m.leader_speaker ? (/^(говорящий|спикер|speaker|участник)\s*\d+$/i.test(m.leader_speaker)
        ? `«${m.leader_speaker}» — в записи без имени` : `«${m.leader_speaker}» — нет в «Команде»`)
    : "не определён";
  const how = LEADER_SOURCE_RU[m.leader_source] || "";
  const pick = admin ? `<select id="meeting-leader-select" class="meeting-leader-select" aria-label="Кто вёл встречу">
      <option value="">${m.leader_source === "вручную" ? "определить по записи" : "изменить…"}</option>
      ${allUsers.filter(u => u.is_active && u.is_confirmed !== false).map(u => `<option value="${u.id}">${esc(u.full_name)}</option>`).join("")}
    </select>` : "";
  return `<div class="meeting-leader" title="${esc(m.leader_note || "")}">Вёл встречу: <b>${esc(who)}</b>${how ? ` <span class="page-sub">· ${esc(how)}</span>` : ""}${pick}</div>`;
}

// Единицы встречи (единицы вместо монолита, 02.10.26): решения, договорённости, уточнения, открытые вопросы, вехи и, возможно,
// пропущенные задачи — с цитатой из источника (берёт код), таймкодом и ролями людей. Извлечённое — кандидаты: в работу только
// после «Принять». Одним списком на странице встречи, не карточками в «Конфликтах» — на встречу их бывает под три десятка.
const UNIT_ORDER = ["Решение", "Договорённость", "Уточнение", "Открытый вопрос", "Веха", "Задача"];
const UNIT_ROLE_RU = { "ответственный": "ответственные", "участник": "участники", "влияющий": "влияющие" };
async function loadUnitsPanel(meetingId, admin) {
  const box = document.getElementById("units-panel");
  if (!box) return;
  let units = [];
  try { units = await api(`/meetings/${meetingId}/units`); } catch (e) { box.innerHTML = ""; return; }
  // Единицы прошлых встреч, закрытые этой (закрытие по голосу, решение владельца 02.10.26), — отдельной группой в конце.
  const closedHere = units.filter(u => u.closed_here);
  units = units.filter(u => !u.closed_here);
  const pending = units.filter(u => u.status === "кандидат");
  const head = `<div class="units-head"><h2>Единицы встречи</h2>
    <span class="page-sub">${units.length ? `${units.length}${pending.length ? ` · задач на решение ${pending.length}` : ""}` : "ещё не собраны"}</span>
    <span class="doc-head-spacer"></span>
    ${admin && pending.some(u => u.kind !== "Задача") ? `<button class="btn-sm" id="units-accept-all" title="Задачи-кандидаты заводятся только по одной">Принять все, кроме задач</button>` : ""}
    ${admin ? `<button class="btn-sm" id="units-extract" title="Платный вызов модели, около 0,01 $. После сохранения Протокола собирается сам">${units.length ? "Собрать заново" : "Собрать"}</button>` : ""}
  </div>`;
  const roleLine = (u) => Object.keys(UNIT_ROLE_RU).map(r => {
    const ps = u.roles.filter(x => x.role === r).map(x => esc(x.person));
    return ps.length ? `${UNIT_ROLE_RU[r]}: ${ps.join(", ")}` : "";
  }).filter(Boolean).join(" · ");
  const row = (u) => `<div class="unit-row" data-unit="${u.id}">
      <div class="unit-main"><div>${esc(u.statement)}</div>
        ${u.task_description ? `<div class="unit-sub">к задаче: ${esc(u.task_description)}${admin ? ` <button type="button" class="src-link-btn unit-unlink" title="Привязка неверна — единица останется, задача отвяжется">отвязать</button>` : ""}</div>` : ""}
        ${roleLine(u) ? `<div class="unit-sub">${roleLine(u)}</div>` : ""}
        ${u.quote ? `<div class="unit-quote">«${esc(u.quote.length > 260 ? u.quote.slice(0, 260) + "…" : u.quote)}»${u.ts ? ` <span class="unit-sub">${esc(u.ts)}</span>` : ""}</div>` : ""}
        ${u.closed_how ? `<div class="unit-sub">${esc(u.status)}${u.closed_how === "голос" ? ` по голосу на встрече ${esc(fmtRuDate(u.closed_meeting_date))}` : ""}${u.closed_note ? `: ${esc(u.closed_note)}` : ""}</div>
          ${u.closed_quote ? `<div class="unit-quote">«${esc(u.closed_quote.length > 260 ? u.closed_quote.slice(0, 260) + "…" : u.closed_quote)}»</div>` : ""}` : ""}
      </div>
      <div class="unit-act">${u.closed_how
        ? (admin && u.closed_how !== "дата" ? `<button class="btn-sm unit-reopen" title="Закрыто неверно — вернуть в открытые">Вернуть</button>` : `<span class="badge badge-neutral">${esc(u.status)}</span>`)
        : u.status === "кандидат"
        ? (admin ? `<button class="btn-sm unit-accept">${u.kind === "Задача" ? "Завести задачу" : "Принять"}</button><button class="btn-sm unit-reject">Отклонить</button>` : `<span class="badge badge-neutral">на подтверждении</span>`)
        : `<span class="badge badge-accent">${esc(u.status)}</span>${admin && ((u.kind !== "Задача" && ["действует", "открыт"].includes(u.status)) || (u.kind === "Задача" && u.status === "задача заведена" && u.auto))
            ? ` <button type="button" class="src-link-btn unit-reject" title="${u.kind === "Задача" ? "Задача заведена из записи ошибочно — снять её из реестра" : "Единица извлечена неверно — убрать"}">убрать</button>` : ""}`}</div>
    </div>`;
  const groups = UNIT_ORDER.map(k => {
    const list = units.filter(u => u.kind === k);
    return list.length ? `<div class="unit-group"><div class="unit-kind">${esc(k === "Задача" ? "Возможно, пропущенные задачи" : k)}</div>${list.map(row).join("")}</div>` : "";
  }).join("") + (closedHere.length ? `<div class="unit-group"><div class="unit-kind">Закрыто на этой встрече (единицы прошлых встреч)</div>${closedHere.map(row).join("")}</div>` : "");
  // место в списке переживает «Принять»/«Отклонить» (обход 02.10 вечер: из 55 единиц, идя по одной, список каждый раз
  // возвращался к началу)
  const keepTop = box.querySelector(".units-body")?.scrollTop || 0;
  box.innerHTML = `<div class="card card-output units-card">${head}<div class="units-body" data-list="units" data-list-item=".unit-row">${groups || `<div class="page-sub" style="margin:0">Единиц нет.</div>`}</div></div>`;
  const body = box.querySelector(".units-body");
  if (body) body.scrollTop = keepTop;
  const act = async (uid, action) => {
    try { await api(`/units/${uid}`, { method: "PATCH", json: { action } }); loadUnitsPanel(meetingId, admin); }
    catch (e) { toast(e.message, true); }
  };
  box.querySelectorAll(".unit-accept").forEach(b => b.addEventListener("click", () => act(b.closest(".unit-row").dataset.unit, "accept")));
  box.querySelectorAll(".unit-reject").forEach(b => b.addEventListener("click", () => act(b.closest(".unit-row").dataset.unit, "reject")));
  box.querySelectorAll(".unit-unlink").forEach(b => b.addEventListener("click", () => act(b.closest(".unit-row").dataset.unit, "unlink")));
  box.querySelectorAll(".unit-reopen").forEach(b => b.addEventListener("click", () => act(b.closest(".unit-row").dataset.unit, "reopen")));
  document.getElementById("units-accept-all")?.addEventListener("click", async () => {
    try { const r = await api(`/meetings/${meetingId}/units/accept-all`, { method: "POST" }); toast(`Принято: ${r.accepted}`); loadUnitsPanel(meetingId, admin); }
    catch (e) { toast(e.message, true); }
  });
  document.getElementById("units-extract")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Собираю…";
    try { const r = await api(`/meetings/${meetingId}/units/extract`, { method: "POST" }); toast(`Кандидатов: ${r.candidates}${r.closed ? ` · закрыто прошлых: ${r.closed}` : ""}`); }
    catch (err) { toast(err.message, true); }
    loadUnitsPanel(meetingId, admin);
  });
}

// Табло «Единицы встреч» — супер-админу на время тестирования (владелец 02.10.26: «спорные моменты и так в «Конфликтах»; единицы
// вынести в табло для супер-админа»). Выбор встречи — список встреч с Протоколом, по умолчанию последняя.
async function renderUnitsBoard(rest) {
  заставкаЗагрузки();   // тот же экран — прежнее содержимое до новой отрисовки (26.10.2026)
  // Только встречи, у которых единицы есть, с их числом; по месяцам — когда накопятся, список сворачивается по группам
  // (владелец 02.10.26: «зачем список встреч — там пусто; как будем сворачивать, когда накопятся»).
  const meetings = await api("/units/meetings");
  const id = +(rest && rest[0]) || (meetings[0] && meetings[0].id);
  const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
  const byMonth = [];
  meetings.forEach(m => {
    const key = MONTHS[+m.date.slice(5, 7) - 1] + " " + m.date.slice(0, 4);
    if (!byMonth.length || byMonth[byMonth.length - 1][0] !== key) byMonth.push([key, []]);
    byMonth[byMonth.length - 1][1].push(m);
  });
  const opt = (m) => `<option value="${m.id}"${m.id === id ? " selected" : ""}>${esc(fmtRuDate(m.date))} · единиц ${m.units}${
    m.label && !/^Встреча\s/.test(m.label) ? " — " + esc(m.label) : ""}</option>`;
  $main.innerHTML = `<div class="doc-head"><h1>Единицы встреч</h1>
      <span class="doc-head-meta">табло на время тестирования — видно только супер-админу</span></div>
    <div class="field" style="max-width:360px"><label for="units-meeting">Встреча</label>
      ${meetings.length ? `<select id="units-meeting">${byMonth.length > 1
        ? byMonth.map(([k, list]) => `<optgroup label="${esc(k)}">${list.map(opt).join("")}</optgroup>`).join("")
        : meetings.map(opt).join("")}</select>` : `<div class="page-sub">Единицы ещё ни у одной встречи не собраны.</div>`}</div>
    <div id="units-panel"></div>`;
  document.getElementById("units-meeting")?.addEventListener("change", (e) => { location.hash = `#units/${e.target.value}`; });
  if (id) loadUnitsPanel(id, true);
}

// Вкладка «Единицы» рядом с «План | Протокол» (владелец 02.10.26: на 01.10 — 55 единиц; под Протоколом страница была в два экрана).

// «Проверить после сохранения» (решение владельца 15.10.26). Протокол сохраняется сразу; то, что раньше человек решал
// до сохранения, — задачи, которые код не завёл сам, и замечания проверки — уходит карточками. Этот блок собирает их
// на странице встречи: решить задачу можно здесь одним нажатием (тот же запрос, что у карточки в «Конфликтах»),
// поправить текст — существующей точечной правкой. Блок служебный: только администраторам, вне документа (в docBlock
// и в выгрузку он не входит), и скрыт, когда проверять нечего. Зеркально Планёрке.
function открытьТочечнуюПравку(blockId) {
  const box = document.getElementById(`${blockId}-edit`);
  if (!box) return;
  box.open = true;
  box.scrollIntoView({ block: "start", behavior: "smooth" });
  document.getElementById(`${blockId}-find`)?.focus({ preventScroll: true });
}

async function загрузитьПроверкуПослеСохранения(id, { blockId, canEdit }) {
  const место = document.getElementById("post-save-check");
  if (!место) return;
  let данные;
  try { данные = await api(`/meetings/${id}/post-save-check`); } catch (e) { return; }   // нет связи — блок не нужен
  if (!данные || !данные.show) { место.hidden = true; место.innerHTML = ""; return; }
  const задачи = (данные.tasks || []).map(t => `<div class="psc-task" data-id="${t.id}" style="padding:8px 0;border-top:1px solid var(--border)">
      <div>«${esc(t.description)}»</div>
      ${t.registry_text ? `<div class="page-sub">В реестре похожая: «${esc(t.registry_text)}»</div>` : ""}
      ${t.why ? `<div class="page-sub" style="margin:4px 0">${esc(t.why)}</div>` : ""}
      <div class="hstack" style="margin-top:6px; flex-wrap:wrap">
        <button type="button" class="btn-sm btn-primary psc-act" data-id="${t.id}" data-action="accept">${esc(t.labels.accept)}</button>
        <button type="button" class="btn-sm psc-act" data-id="${t.id}" data-action="reject">${esc(t.labels.reject)}</button>
      </div></div>`).join("");
  const замечания = (данные.findings || []).map(f => {
    const текст = String(f.text || "");
    return `<li>${f.title ? `<b>${esc(f.title)}:</b> ` : ""}${esc(текст.length > 180 ? текст.slice(0, 180) + "…" : текст)}</li>`;
  }).join("");
  место.innerHTML = `<div class="card" style="border-left:4px solid var(--accent)">
    <div class="hstack" style="flex-wrap:wrap">
      <b>Проверить после сохранения</b>
      <span class="page-sub" style="margin:0">— видно администраторам, в протокол не входит</span>
      <span style="flex:1"></span>
      ${canEdit ? `<button type="button" class="btn-sm" id="psc-edit">Поправить текст</button>` : ""}
    </div>
    ${данные.tasks_count ? `<div style="margin-top:10px"><b>Задачи на подтверждение: ${данные.tasks_count}</b></div>
      <div class="page-sub" style="margin:4px 0">Протокол уже сохранён; эти задачи система сама в реестр не завела — решите по каждой.</div>
      ${задачи}` : ""}
    ${данные.findings_count ? `<div style="margin-top:10px"><b>Замечания проверки: ${данные.findings_count}</b>
      <a href="#razbor" class="page-sub">— открыть карточки</a></div>
      <ul style="margin:6px 0 0">${замечания}</ul>` : ""}
  </div>`;
  место.hidden = false;
  document.getElementById("psc-edit")?.addEventListener("click", () => открытьТочечнуюПравку(blockId));
  место.querySelectorAll(".psc-act").forEach(кнопка => кнопка.addEventListener("click", async () => {
    место.querySelectorAll(".psc-act").forEach(к => { к.disabled = true; });
    try {
      await api(`/task-conflicts/${кнопка.dataset.id}`, { method: "PATCH", json: { action: кнопка.dataset.action } });
      toast(`Карточка закрыта: «${кнопка.textContent.trim()}»`);
      updateConflictsBadge();
    } catch (e) { toast(e.message, true); }
    загрузитьПроверкуПослеСохранения(id, { blockId, canEdit });
  }));
}

async function renderMeetingProtocol(id, verdict, verdictFor) {
  const from = hashParts().query.get("from");
  заставкаЗагрузки();   // тот же экран — прежнее содержимое до новой отрисовки (26.10.2026)
  const [meeting, sources, minutes, planDoc] = await Promise.all([
    api(`/meetings/${id}`), api(`/meetings/${id}/sources`), api(`/meetings/${id}/minutes`), api(`/meetings/${id}/plan`),
  ]);
  const admin = isAdmin();
  const готовит = canPrepare();      // сборка и загрузка — всем ролям (решение владелицы 21.10.2026)
  // Состояние сборки спрашиваем у сервера при открытии экрана (12.10.26): протокол мог собираться,
  // пока человек был на другом экране или в другом окне, — и после возврата кнопка не должна выглядеть
  // так, будто ничего не запускалось, а «черновик не сохранён» не должен пропадать вместе с перерисовкой.
  let идётСборкаС = null;      // время начала сборки — для подсказки на полосе (панель источников свёрнута)
  let баннерПриёмки = "";      // решение, которое ждёт человека, показываем НАД документом, без раскрытия блоков
  if (готовит && !verdict) {
    try {
      const состояние = await api(`/meetings/${id}/generation`);
      if (состояние.pending && состояние.pending.minutes) {
        verdict = состояние.pending.minutes.verdict;
        // «Принять с замечаниями» разрешено, только если среди находок нет находок кода: флаг приходит
        // рядом с вердиктом и без переноса терялся — кнопка «Сохранить с замечаниями» не появлялась.
        if (состояние.pending.minutes.can_accept && verdict) verdict.can_accept = true;
      }
      if (состояние.running || состояние.queued) {
        идётСборкаС = состояние.since || true;
        показатьХодСборки(id, { findingsId: "verify-findings-minutes", btnId: "prepare-minutes-btn", since: состояние.since,
                                queued: состояние.queued && !состояние.running, lines: состояние.queue_lines });
        начатьСлежениеЗаСборкой(id, () => renderMeetingProtocol(id));
      }
      // Человек 12.10.26: «кнопка внутри блока „добавить документы“ — там её вообще не видно, максимально
      // неудобно». Решение, которое ждёт человека, выносим на видное место — баннером над документом:
      // раскрывать ничего не нужно. Лучшая практика: блокирующее решение — на виду, рядом с результатом.
      if (admin && verdict && verdict.can_accept) {      // приёмка черновика — администратору (accept-draft)
        const сколько = (verdict.findings || []).length;
        // Время сборки черновика — прямо в баннере (владелец 13.10.26: «не отображено корректное время»):
        // иначе на экране видно только время ПРЕЖНЕГО сохранённого протокола, и непонятно, к чему относится
        // ожидающий решения документ.
        const когда = состояние.pending.minutes.at
          ? ` Черновик собран ${esc(fmtRuDateTime(String(состояние.pending.minutes.at).replace(/Z$/, "")))}.`
          : "";
        баннерПриёмки = `<div class="card" id="accept-draft-banner" style="border-left:4px solid var(--accent)">
          <div><b>Протокол собран, но не сохранился${сколько ? ` (замечаний проверки: ${сколько})` : ""}.</b>${когда}</div>
          <div class="page-sub" style="margin:6px 0">${состояние.pending.minutes.save_error ? `Причина: ${esc(состояние.pending.minutes.save_error)}. ` : ""}Протокол
            сохраняется сразу; этот черновик остался, потому что само сохранение не прошло. Сохраните его кнопкой —
            замечания проверки уйдут карточками администратору. Пока он не сохранён, задачи из встречи в реестр не заводятся.</div>
          <div class="hstack" style="flex-wrap:wrap">
            <button class="btn-sm btn-primary" id="accept-draft-banner-btn">Сохранить протокол с замечаниями</button>
            <button class="btn-sm" id="accept-draft-banner-замечания">Показать замечания</button>
          </div></div>`;
      }
    } catch (e) { /* нет связи — экран покажет то, что уже загружено */ }
  }
  const archiveCutoff = new Date();
  archiveCutoff.setDate(archiveCutoff.getDate() - ARCHIVE_CUTOFF_DAYS);
  const isArchived = new Date(meeting.date) < archiveCutoff;
  let backLabel = "← Встречи", backHref = "#meetings";
  if (from) {
    try {
      const origin = await api(`/meetings/${from}`);
      backLabel = `← План ${fmtRuDate(origin.date)}`; backHref = `#meetings/${from}`;
    } catch (e) { /* источник перехода недоступен — остаётся возврат к самой встрече */ }
  }
  const hasMin = !!(minutes && minutes.available);
  const isFuture = new Date(meeting.date) > new Date();
  // Полоса «Источники · + добавить · Пересобрать» прилипает к низу экрана (решение владельца 01.10.26, вариант 3 из трёх
  // подходов лидеров рынка — плавающая полоса, как в Granola и Fathom). Раньше под Протоколом был свёрнутый блок
  // «Заметки этой встречи и пересборка протокола»: «Уже добавлено», загрузка с длинной подписью, «Вставить текст»,
  // «Удалить загруженные заметки» и кнопка отдельной карточкой — «и не видно, и не понятно». Статус источника
  // (решение 30.09.26) — в строке источника в списке над полосой.
  const showBar = готовит && !(isFuture && !hasMin);
  const draftVerdict = !!(verdict && ((verdict.findings && verdict.findings.length) || verdict.can_accept));
  // Панель источников при открытии страницы СВЁРНУТА (указание владельца 09.10.26: «старница открывает
  // сразу и окно Из чего собирается протокол — этот блок надо показывать свернутым по умолчанию»).
  // Прежде она раскрывалась сама, когда протокола ещё нет или у черновика есть замечания, — и на первой
  // сборке закрывала собой документ. Раскрывает её теперь либо человек («Источники» на полосе, «+ добавить»,
  // выбор файла, вставка текста), либо сама сборка — там внутри виден ход и замечания проверки
  // (см. openSourcePanel в runMeetingGeneration). О замечаниях, пока панель свёрнута, говорит подсказка
  // на полосе: молчать о непройденной проверке нельзя.
  const panelOpen = false;
  const sourceTag = (src) => src.kind === "recording" ? "запись" : src.kind === "transcript" ? "расшифровка"
    : src.kind === "protocol" ? "заметки" : src.kind === "notes" ? "заметки секретаря" : fileTag(src.original_filename);
  const chips = sources.length <= 2
    ? sources.map(src => `<span class="src-bar-chip"><span class="src-tag">${esc(sourceTag(src))}</span>${esc(shortName(src.original_filename))}</span>`).join("")
    : `<span class="src-bar-chip">${sources.length} ${plural(sources.length, "источник", "источника", "источников")}</span>`;
  const sourceBar = showBar ? `
    <div class="src-bar-wrap" id="source-drop-zone" data-drop-input="source-file">
      <div class="src-bar-panel" id="src-panel"${panelOpen ? "" : " hidden"}>
        <div class="src-panel-head"><span>Источники протокола · ${sources.length}</span>
          <span class="src-panel-tools">${sources.length && admin ? `<button type="button" class="src-link-btn" id="reset-sources-btn">удалить все</button>` : ""}
          <button type="button" class="btn-sm src-close" data-close-panel>Свернуть ▾</button></span></div>
        ${sources.length ? sources.map(src => sourceRow(sourceTag(src), esc(src.original_filename), src.status ? esc(src.status) : "",
            `<span class="src-icons">${src.local_transcript ? `<a class="btn-icon src-download" href="/meetings/${id}/sources/${src.id}/export" download title="Выгрузить в Word" aria-label="Выгрузить расшифровку в Word">${ICON_DOWNLOAD}</a>` : ""}${admin ? `<button class="btn-icon src-delete delete-source-btn" data-id="${src.id}" title="Удалить файл" aria-label="Удалить файл">${ICON_TRASH}</button>` : ""}</span>`)).join("")
          : `<div class="src-empty">Источников пока нет. Перетащите на полосу заметки, расшифровку или запись встречи — или «+ добавить».</div>`}
        <div class="src-paste" id="src-paste-box" hidden>
          <textarea id="src-paste-text" rows="6" placeholder="Вставьте заметки или расшифровку встречи"></textarea>
          <div class="hstack"><button type="button" class="btn-sm" id="src-paste-add">Добавить текст</button></div>
        </div>
        <div id="source-file-selected" class="src-hint"></div>
        <div id="verify-findings-minutes"></div>
      </div>
      <div class="src-bar">
        <span class="src-bar-label">Источники:</span>
        <button type="button" class="src-bar-sources" id="src-toggle" aria-expanded="${panelOpen}">${sources.length ? chips : `<span class="src-bar-chip">нет</span>`}<span class="src-bar-caret" aria-hidden="true">${panelOpen ? "▾" : "▴"}</span></button>
        <span class="src-add">
          <button type="button" class="btn-sm" id="src-add-btn" aria-haspopup="menu">+ добавить</button>
          <span class="src-add-menu" id="src-add-menu" role="menu" hidden>
            <label role="menuitem">Файл или запись<input type="file" id="source-file" multiple hidden></label>
            <button type="button" role="menuitem" id="src-add-text">Вставить текст</button>
          </span>
        </span>
        <span class="src-hint">или перетащите файл на страницу</span>
        ${идётСборкаС ? `<span class="src-hint" style="color:var(--accent)">Сборка идёт${идётСборкаС !== true ? ` — начата в ${esc(fmtRuDateTime(String(идётСборкаС).replace(/Z$/, "")))}` : ""}: результат появится на этом экране сам</span>` : ""}
        ${draftVerdict ? `<span class="src-hint" style="color:var(--danger)">Протокол собран, но не сохранился — сохранить можно кнопкой над документом</span>` : ""}
        <span class="src-bar-spacer"></span>
        <span class="src-hint" id="prepare-minutes-hint"></span>
        <button class="btn-primary" id="prepare-minutes-btn" disabled title="${hasMin ? "Новая версия станет текущей; прежняя версия не удаляется — остаётся в базе" : "Протокол сохранится с датой встречи, задачи и статусы применятся"}">${идётСборкаС ? "Генерирую…" : (hasMin ? "↻ Пересобрать протокол" : "Создать протокол")}</button>
      </div>
    </div>` : "";

  $main.innerHTML = `
    ${meetingDocHead({ backHref, backLabel, meeting, active: "protocol", hasPlan: !!(planDoc && planDoc.available), hasMin,
        generatedAt: hasMin ? minutes.generated_at : null, exportUrl: hasMin ? `/meetings/${id}/minutes/export` : null,
        editId: hasMin && !isArchived ? "minutes-block-edit" : null, editBase: `/meetings/${id}/minutes` })}
    ${meetingLeaderLine(meeting, admin)}
    ${hasMin
      ? `${баннерПриёмки}` + docBlock(minutes, `/meetings/${id}/minutes/export`, null, isArchived ? null : `/meetings/${id}/minutes`, "minutes-block", { hideSources: showBar, compact: true })
        + (admin ? `<div id="post-save-check" hidden></div>` : "")      // «Проверить после сохранения» — вне документа (15.10.26)
      : !готовит ? `<div class="card page-sub">Протокола этой встречи пока нет. Выберите себя в «Вы работаете как», чтобы добавить заметки и собрать протокол.</div>`
      : isFuture ? `<div class="card page-sub">Встреча ещё не проведена. Заметки или расшифровку можно добавить после встречи.</div>`
      // полосы внизу на подготовке нет с 17.10.2026 (её прячет prep.js) — источник добавляется в «Материалах» вверху (Д11)
      : `<div class="card empty-state">Протокола пока нет. Добавьте источник в «Материалах» вверху — протокол соберётся сам или по ссылке «Собрать».</div>`}
    ${sourceBar}
  `;
  if (hasMin && !isArchived) await подключитьПолотноДокумента("minutes-block", `/meetings/${id}/minutes`, minutes.content_md, () => renderMeetingProtocol(id), id);
  if (admin && hasMin) загрузитьПроверкуПослеСохранения(id, { blockId: "minutes-block", canEdit: !isArchived });
  document.getElementById("meeting-leader-select")?.addEventListener("change", async (e) => {
    const v = e.target.value;
    try {
      await api(`/meetings/${id}/leader`, { method: "PATCH", json: { user_id: v ? Number(v) : null } });
      toast(v ? "Ведущий указан вручную" : "Ведущий снова определяется по записи");
      renderMeetingProtocol(id);
    } catch (err) { toast(err.message, true); }
  });
  if (showBar) {
    const panel = document.getElementById("src-panel");
    const toggle = document.getElementById("src-toggle");
    const openPanel = (open) => {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.querySelector(".src-bar-caret").textContent = open ? "▾" : "▴";
    };
    toggle.addEventListener("click", () => openPanel(panel.hidden));
    const menu = document.getElementById("src-add-menu");
    document.getElementById("src-add-btn")?.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; });
    if (!window.__srcMenuCloser) {          // один обработчик на всё время жизни страницы, а не на каждый показ
      window.__srcMenuCloser = true;
      document.addEventListener("click", (e) => {
        const m = document.getElementById("src-add-menu");
        if (m && !e.target.closest(".src-add")) m.hidden = true;
      });
    }
    document.getElementById("src-add-text")?.addEventListener("click", () => {
      menu.hidden = true;
      openPanel(true);
      document.getElementById("src-paste-box").hidden = false;
      document.getElementById("src-paste-text").focus();
    });
    document.getElementById("source-file")?.addEventListener("change", () => { menu.hidden = true; openPanel(true); });
  }

  if (admin && verdict && verdict.findings && verdict.findings.length) {
    // Когда ОДНОВРЕМЕННО идёт новая сборка и ждёт решения черновик предыдущей попытки — говорим об этом
    // прямо (владелец 12.10.26: «в мониторинге и на экране такая разная и неточная инфо»). Иначе строка
    // «Генерирую… (N сек)» и «Черновик не сохранён» рядом читаются как противоречие.
    const пояснение = идётСборкаС
      ? `<div class="page-sub" style="margin:0 0 6px">Идёт НОВАЯ сборка этого документа${идётСборкаС !== true ? ` (начата в ${esc(fmtRuDateTime(String(идётСборкаС).replace(/Z$/, "")))})` : ""}.
          Ниже — черновик ПРЕДЫДУЩЕЙ попытки, он ждёт решения: его можно принять сейчас или дождаться новой сборки.</div>`
      : "";
    document.getElementById("verify-findings-minutes").innerHTML = `
      ${пояснение}
      <div class="page-sub" style="margin-top:8px">Протокол собран, но не сохранился. Замечания проверки этого черновика:</div>
      <ul>
        ${verdict.findings.map(f => `<li><b>${esc(VERIFY_CATEGORY_LABELS[f.category] || f.category || "Замечание")}:</b>
          «${esc(f.quote || "")}» — ${esc(f.issue || "")}</li>`).join("")}
      </ul>
      <div class="page-sub">После сохранения каждое существенное замечание станет карточкой администратора.</div>`;
  }

  if (admin && verdict && verdict.can_accept) {
    // Проверка отклонила черновик, но в нём нет находок кода (выдуманный человек, несуществующий номер): решает администратор.
    // Одно действие — две кнопки: баннер над документом (главное место, его видно всегда) и панель с
    // замечаниями (там читают подробности). Действие живёт в одной функции, чтобы кнопки не расходились.
    const принятьЧерновик = async () => {
      if (!(await confirmDialog("Сохранить протокол как есть, с замечаниями проверки? Задачи и статусы из него применятся.", "Сохранить"))) return;
      try {
        const saved = await api(`/meetings/${id}/accept-draft`, { method: "POST" });
        toast("Протокол сохранён с замечаниями. Карта и Сводка обновляются в фоне");
        const closed = (saved && saved.closed_by_source) || [];
        toast(`В реестре: новых задач: ${(saved && saved.new_tasks_count) || 0}` +
              (saved && saved.status_changes_count ? `; изменён статус: ${saved.status_changes_count}` : "") +
              (closed.length ? `; закрыты по словам встречи: ${closed.join(", ")} — вернуть можно в «Реестре задач»` : ""), false);
        if (from) location.hash = `#meetings/${from}`; else renderMeetingProtocol(id);
      } catch (err) { toast(err.message, true); }
    };
    document.getElementById("accept-draft-banner-btn")?.addEventListener("click", принятьЧерновик);
    document.getElementById("accept-draft-banner-замечания")?.addEventListener("click", () => {
      const панель = document.getElementById("src-panel");
      if (панель) { панель.hidden = false; document.getElementById("src-toggle")?.setAttribute("aria-expanded", "true"); }
      document.getElementById("verify-findings-minutes")?.scrollIntoView({ block: "center" });
    });
    const box = document.getElementById("verify-findings-minutes");
    if (box) {
      // Панель «Источники» НЕ раскрываем сами (живая проверка 12.10.26): будучи раскрытой, она накрывала
      // баннер с решением — а он и есть главное место. Панель открывает человек кнопкой «Показать
      // замечания» в баннере, когда хочет подробностей.
      // Кнопку приёмки здесь НЕ дублируем (владелец 12.10.26: «кнопка осталась внутри блока с доп.
      // документами — убери оттуда»): решение — в баннере над документом, тут только замечания и строка,
      // куда идти за решением.
      box.insertAdjacentHTML("beforeend",
        `<div class="page-sub" style="margin-top:8px">Принять или отклонить черновик можно кнопкой в баннере над документом.</div>`);
    }
  }

  if (готовит) {
    const sourceFileInput = document.getElementById("source-file");   // у ещё не проведённой встречи блока заметок нет
    if (sourceFileInput) sourceFileInput.addEventListener("change", async (e) => {
      if (!e.target.files.length) return;
      const meetingYear = parseInt(meeting.date.slice(0, 4), 10);
      for (const f of Array.from(e.target.files)) {
        const dates = datesInName(f.name, meetingYear);
        const fileDate = dates.length && dates.every(d => daysBetween(d, meeting.date) > 14) ? dates[0] : null;
        if (fileDate) {
          const ok = await confirmDialog(
            `Похоже, файл «${f.name}» датирован ${fmtRuDate(fileDate)}, а эта встреча — ${fmtRuDate(meeting.date)}.\n\n` +
            `Заметки и транскрипция на этой странице относятся именно к ЭТОЙ встрече — ` +
            `если файл на самом деле от другой встречи, добавьте его на странице той встречи. ` +
            `Всё равно загрузить сюда?`,
            "Загрузить сюда"
          );
          if (!ok) { e.target.value = ""; return; }
        }
      }
      const panel = document.getElementById("src-panel");
      if (panel) panel.hidden = false;
      document.getElementById("source-file-selected").textContent =
        "Загружаю: " + Array.from(e.target.files).map(f => f.name).join(", ") + "…";
      uploadFile(`/meetings/${id}/sources`, "source-file", {}, "Файлы добавлены", () => renderMeetingProtocol(id), true,
        { mediaAsRecording: true, progressId: "source-file-selected" });
    });
    wirePasteText("src-paste", `/meetings/${id}/sources/text`, () => renderMeetingProtocol(id));
    $main.querySelectorAll(".delete-source-btn").forEach(btn => btn.addEventListener("click", async () => {
      if (!(await confirmDialog("Удалить этот файл с заметками? Восстановить его нельзя.", "Удалить"))) return;
      try {
        await api(`/meetings/${id}/sources/${btn.dataset.id}`, { method: "DELETE" });
        toast("Файл удалён");
        renderMeetingProtocol(id);
      } catch (e) { toast(e.message, true); }
    }));
    const resetBtn = document.getElementById("reset-sources-btn");
    if (resetBtn) resetBtn.addEventListener("click", async () => {
      if (!(await confirmDialog("Удалить все добавленные заметки и файлы этой встречи и начать заново?", "Удалить"))) return;
      try {
        for (const s of sources) await api(`/meetings/${id}/sources/${s.id}`, { method: "DELETE" });
        toast("Очищено — добавьте новые заметки или файлы, затем «Подготовить протокол»");
        renderMeetingProtocol(id);
      } catch (e) { toast(e.message, true); }
    });
    const prepareMinutesBtn = document.getElementById("prepare-minutes-btn");
    const pasted = document.getElementById("src-paste-text");
    const hint = document.getElementById("prepare-minutes-hint");
    const refreshMinutesBtn = () => {
      if (!prepareMinutesBtn) return;
      const hasText = !!pasted && pasted.value.trim().length >= 20;
      prepareMinutesBtn.disabled = !(sources.length || hasText);
      hint.textContent = (sources.length || hasText) ? "" : "Сначала добавьте источник";
    };
    if (pasted) pasted.addEventListener("input", refreshMinutesBtn);
    refreshMinutesBtn();
    if (prepareMinutesBtn) prepareMinutesBtn.addEventListener("click", async () => {
      // протокол правил человек — моделью не пересобирается (решение владелицы 24.10.2026, п. 6), сервер отвечает тем же
      if (hasMin && minutes.hand_edited) { toast(ПЕРЕСБОРКА_ЗАПРЕЩЕНА, true); return; }
      if (hasMin && !(await confirmDialog("Пересобрать протокол по текущим заметкам? Новая версия станет текущей; прежняя версия не удаляется — остаётся в базе.", "Пересобрать"))) return;
      const text = pasted ? pasted.value.trim() : "";
      if (text.length >= 20) {          // вставленный текст добавляется сам — отдельно «Добавить текст» жать не нужно
        try { await api(`/meetings/${id}/sources/text`, { method: "POST", json: { text } }); pasted.value = ""; }
        catch (e) { toast(e.message, true); return; }
      }
      // F22 (24.09.26): подтверждение источника перед платной генерацией — человек видит файлы и дату встречи
      const srcNames = (sources || []).map(s => s.original_filename || "вставленный текст").join("\n  • ");
      if (!(await confirmDialog(`Создать протокол встречи ${fmtRuDate(meeting.date)} по этим источникам?\n  • ${srcNames || "вставленный текст"}\n\nПроверьте, что это записи именно этой встречи: запись другой встречи того же дня по содержанию не отличить.`))) return;
      runMeetingGeneration({
        id, btnId: "prepare-minutes-btn", endpoint: `/meetings/${id}/prepare-minutes?confirm=1${hasMin ? "&rebuild=true" : ""}`, findingsId: "verify-findings-minutes",
        idleLabel: hasMin ? "↻ Пересобрать протокол" : "Создать протокол",
        okToast: "Протокол сохранён",
        partialToast: `Протокол сохранён, но Дорожная карта/Сводка не обновились — ${conflictsRef()}`,
        rerender: (v, f) => renderMeetingProtocol(id, v, f),
        onSaved: from ? () => { location.hash = `#meetings/${from}`; } : null,
      });
    });
    // Пришли кнопкой «Сформировать протокол по вложенным материалам» со страницы встречи (22.10.2026, как в Планёрке): та же
    // кнопка, то же подтверждение. Отметка одноразовая — повторное открытие подготовки сборку не запускает.
    let собратьСразу = null;
    try { собратьСразу = sessionStorage.getItem("buildOnOpen"); sessionStorage.removeItem("buildOnOpen"); } catch (e) { собратьСразу = null; }
    if (собратьСразу === String(id) && !hasMin && prepareMinutesBtn && !prepareMinutesBtn.disabled) prepareMinutesBtn.click();
  }
}

// «План встречи» (#meetings/<id>/planprep) — новый путь (решения владелицы 21.10.2026, «Проект нового пути»):
//   * первой строкой на самом верху, вне всех панелей, — «Переформировать план встречи» (при пустом плане «Сформировать
//     план встречи»), рядом «+ Добавить материал» и «собран … · платно, 1–5 мин»; было — ссылка «Собрать заново» внутри
//     свёрнутой панели «Материалы», а пустой план просил нажать кнопку «на полосе внизу», которой на экране не было;
//   * «Есть материалы новее плана (N) — переформировать?» (п. 6): пересборка — только по кнопке, без платного вызова сам;
//   * во время сборки кнопка показывает «Идёт сборка с ЧЧ:ММ, N мин» и не нажимается (О5) — той же подписью, что ссылка
//     подготовки протокола (`подписьСсылкиСборки`, prep.js); сборку по-прежнему ведёт скрытая кнопка прежней полосы;
//   * панель «Из чего собирается план» после загрузки файла не сворачивается и страница не прыгает: открыта ли она —
//     помнится по встрече (`_панельПланаОткрыта`), перерисовка той же встречи идёт без заставки «Загрузка…»;
//   * платная сборка — через подтверждение, как прежде (решение 21.10.2026); текст подтверждения — правда о Плане: он
//     сохраняется сразу, прежняя версия остаётся в истории (с 15.10.26 «План — как Протокол»).
const _панельПланаОткрыта = new Set();

function сегодняISO() {
  const д = new Date();
  return `${д.getFullYear()}-${String(д.getMonth() + 1).padStart(2, "0")}-${String(д.getDate()).padStart(2, "0")}`;
}

async function renderMeetingDetail(id, verdict, verdictFor) {
  const ключ = String(id);
  const таЖе = !!$main.querySelector(`#plan-top[data-id="${CSS.escape(ключ)}"]`);
  const прокрутка = таЖе ? window.scrollY : 0;
  if (!таЖе) $main.innerHTML = `<div id="meeting-detail" class="empty-state">Загрузка…</div>`;
  const [meeting, materials, minutes, plan, basis] = await Promise.all([
    api(`/meetings/${id}`), api(`/meetings/${id}/materials`),
    api(`/meetings/${id}/minutes`), api(`/meetings/${id}/plan`),
    api(`/meetings/${id}/plan-basis`),
  ]);

  // Встреча в архиве (решение 14.09.26) — точечная правка не нужна и не предлагается: считаем, что
  // архивные встречи уже полностью зафиксированы. Тот же порог, что у списка встреч и бэкенда (28 дней).
  const archiveCutoff = new Date();
  archiveCutoff.setDate(archiveCutoff.getDate() - ARCHIVE_CUTOFF_DAYS);
  const isArchived = new Date(meeting.date) < archiveCutoff;
  const admin = isAdmin();
  const готовит = canPrepare();      // собрать план — всем ролям (решение владелицы 21.10.2026)
  const будущая = String(meeting.date).slice(0, 10) > сегодняISO();
  const отменена = meeting.status === "cancelled";
  // Д1, Д7 (проходы 1 и 4, 21.10.2026): план прошедшей встречи — не тот, куда несут материалы к ближайшей. Предупреждение
  // над «+ Добавить материал» и в окне платной сборки, со ссылкой на ближайшую встречу.
  const прошла = String(meeting.date).slice(0, 10) < сегодняISO();
  const ближайшая = прошла && !отменена ? ближайшаяВстреча(await api("/meetings").catch(() => []), сегодняISO()) : null;
  // То же, что на экране Протокола: сборку Плана ведёт сервер, и после переключения экранов экран
  // продолжает показывать её ход (12.10.26).
  let идётСборкаС = null;
  let баннерПриёмки = "";      // решение ждёт человека — показываем над документом Плана, как у Протокола
  let причинаСбоя = "";        // с 15.10.26 черновик Плана ждёт человека, только если упало само сохранение
  let ходСборки = null;        // сборка идёт — её ход показывается после отрисовки (нужны кнопка и поле замечаний)
  if (готовит && !verdict) {
    try {
      const состояние = await api(`/meetings/${id}/generation`);
      if (состояние.pending && состояние.pending.plan) {
        verdict = состояние.pending.plan.verdict;
        if (состояние.pending.plan.can_accept && verdict) verdict.can_accept = true;
        причинаСбоя = состояние.pending.plan.save_error || "";
      }
      if (состояние.running || состояние.queued) {
        идётСборкаС = состояние.since || true;
        ходСборки = { since: состояние.since, queued: состояние.queued && !состояние.running, lines: состояние.queue_lines };
      }
      if (admin && verdict && verdict.can_accept) {      // приёмка черновика — администратору (accept-draft)
        const сколько = (verdict.findings || []).length;
        // С 15.10.26 (решение владельца «План — как Протокол») План с замечаниями сохраняется сам; баннер — только
        // о сбое самого сохранения.
        баннерПриёмки = `<div class="card" id="accept-plan-banner" style="border-left:4px solid var(--accent)">
          <div><b>План собран, но не сохранился${сколько ? ` (замечаний проверки: ${сколько})` : ""}.</b></div>
          <div class="page-sub" style="margin:6px 0">${причинаСбоя ? `Причина: ${esc(причинаСбоя)}. ` : ""}План
            сохраняется сразу; этот черновик остался, потому что само сохранение не прошло. Сохраните его кнопкой —
            замечания проверки уйдут карточками администратору.</div>
          <div class="hstack" style="flex-wrap:wrap">
            <button class="btn-sm btn-primary" id="accept-plan-banner-btn">Сохранить план с замечаниями</button>
            <button class="btn-sm" id="accept-plan-banner-замечания">Показать замечания</button>
          </div></div>`;
      }
    } catch (e) { /* нет связи — экран покажет то, что уже загружено */ }
  }

  const hasPlan = !!(plan && plan.available);
  const подписьКнопки = hasPlan ? "Переформировать план встречи" : "Сформировать план встречи";
  const новее = hasPlan ? Number(plan.newer_materials || 0) : 0;
  const собран = hasPlan && plan.generated_at ? `собран ${fmtRuDateTime(plan.generated_at)}` : "плана пока нет";
  // Строка действий — первой на самом верху, вне всех панелей (уточнение владелицы 21.10.2026)
  // Д12 (проходы 1, 3, 4): плашка — ссылкой только там, где по ней можно переформировать; во время сборки и без права
  // готовить — простой строкой (прежде выглядела ссылкой и ничего не делала)
  const плашкаНовее = !новее ? ""
    : готовит && !отменена && !идётСборкаС ? `<button type="button" class="link plan-newer" id="plan-newer">Есть материалы новее плана (${новее}) — переформировать?</button>`
    : готовит && !отменена ? `<span class="plan-top-note">Есть материалы новее плана (${новее}) — войдут в следующую сборку</span>`
    : `<span class="plan-top-note">Есть материалы новее плана (${новее})</span>`;
  const планВерх = `<div class="plan-top" id="plan-top" data-id="${esc(ключ)}">
      ${готовит && !отменена ? `<button type="button" class="btn-primary" id="plan-main-btn">${подписьКнопки}</button>` : ""}
      ${отменена ? `<span class="plan-top-note plan-top-acc">Встреча отменена — материалы и план ведут у действующей встречи на эту дату</span>`
        : `<label class="btn btn-sm plan-add">+ Добавить материал<input type="file" id="material-file" multiple hidden></label>`}
      <span class="plan-top-note">${esc(собран)}${готовит && !отменена ? " · платно, 1–5 мин" : ""}</span>
      ${плашкаНовее}
      ${прошла && !отменена ? `<span class="plan-top-note plan-top-acc" id="plan-past-warn">Встреча ${esc(fmtRuDate(meeting.date))} уже прошла — материал попадёт в её план, а не в план ближайшей встречи.${ближайшая
        ? ` <a href="#meetings/${ближайшая.id}/planprep">План ближайшей встречи ${esc(fmtRuDate(ближайшая.date))}</a>` : ""}</span>` : ""}
    </div>`;
  // Полоса источников внизу экрана — как у Протокола (решение владельца 01.10.26: «единообразно»); на подготовке её прячет
  // prep.js, панель источников переезжает под шапку. «+ добавить файл» с 21.10.2026 — в строке действий наверху.
  const draftVerdict = !!(verdict && ((verdict.findings && verdict.findings.length) || verdict.can_accept));
  const panelOpen = _панельПланаОткрыта.has(ключ);
  const sourcesCount = (basis.previous.state === "minutes" || basis.previous.state === "source" || basis.previous.used_date ? 1 : 0)
    + (basis.candidates_count ? 1 : 0) + (basis.open_questions_count ? 1 : 0) + materials.length;
  const sourceBar = `
    <div class="src-bar-wrap" id="material-drop-zone" data-drop-input="material-file">
      <div class="src-bar-panel" id="plan-src-panel" data-files="${materials.length}"${panelOpen ? "" : " hidden"}>
        ${planSourcesHtml(basis, meeting, materials, готовит)}
        <input type="text" id="material-desc" class="src-desc" placeholder="Описание для следующего файла — если нужно">
        <div id="material-file-selected" class="src-hint"></div>
        <div id="verify-findings-plan"></div>
      </div>
      <div class="src-bar">
        <span class="src-bar-label">Источники:</span>
        <button type="button" class="src-bar-sources" id="plan-src-toggle" aria-expanded="${panelOpen}"><span class="src-bar-chip">${sourcesCount} ${plural(sourcesCount, "источник", "источника", "источников")}</span><span class="src-bar-caret" aria-hidden="true">${panelOpen ? "▾" : "▴"}</span></button>
        <span class="src-hint">файл можно перетащить на страницу</span>
        ${идётСборкаС ? `<span class="src-hint" style="color:var(--accent)">Сборка идёт${идётСборкаС !== true ? ` — начата в ${esc(fmtRuDateTime(String(идётСборкаС).replace(/Z$/, "")))}` : ""}: результат появится на этом экране сам</span>` : ""}
        ${draftVerdict ? `<span class="src-hint" style="color:var(--danger)">План собран, но не сохранился — сохранить можно кнопкой над документом</span>` : ""}
        <span class="src-bar-spacer"></span>
        ${готовит && !отменена ? `<button class="btn-primary" id="prepare-plan-btn" hidden title="${hasPlan ? "Новая версия станет текущей; прежняя версия не удаляется — остаётся в базе" : `План встречи ${esc(fmtRuDate(meeting.date))}`}">${идётСборкаС ? "Генерирую…" : подписьКнопки}</button>` : ""}
      </div>
    </div>`;

  $main.innerHTML = `
    ${планВерх}
    ${meetingDocHead({ backHref: "#meetings", backLabel: "← Встречи", meeting, active: "plan", hasPlan,
        hasMin: !!(minutes && minutes.available), generatedAt: hasPlan ? plan.generated_at : null,
        exportUrl: hasPlan ? `/meetings/${id}/plan/export` : null, editId: hasPlan && !isArchived ? "plan-block-edit" : null,
        editBase: `/meetings/${id}/plan`,
        безПротокола: будущая && !(minutes && minutes.available) })}
    ${hasPlan
      ? `${баннерПриёмки}` + docBlock(plan, `/meetings/${id}/plan/export`, null, isArchived ? null : `/meetings/${id}/plan`, "plan-block", { hideSources: true, compact: true })
      : баннерПриёмки ? баннерПриёмки       // первый План не сохранился — баннер и без прежней версии (15.10.26)
      : `<div class="card empty-state">${отменена ? "Встреча отменена — плана и материалов у неё нет: они у действующей встречи на эту дату."
          : идётСборкаС ? "План собирается — появится здесь сам."
          : готовит ? "Плана пока нет. Нажмите «Сформировать план встречи» вверху."
          : "Плана пока нет. Материалы к встрече можно добавить кнопкой «+ Добавить материал» вверху."}</div>`}

    ${isArchived ? `<div class="page-sub">Встреча в архиве (старше 4 недель) — правка недоступна.</div>` : ""}
    ${sourceBar}
  `;
  if (hasPlan && !isArchived) await подключитьПолотноДокумента("plan-block", `/meetings/${id}/plan`, plan.content_md, () => renderMeetingDetail(id), id);
  const панель = document.getElementById("plan-src-panel");
  // открыта ли панель — помним по встрече: кнопка «Источники», «Материалы N» подготовки, «Свернуть ▾», Esc, начало сборки
  new MutationObserver(() => { if (панель.hidden) _панельПланаОткрыта.delete(ключ); else _панельПланаОткрыта.add(ключ); })
    .observe(панель, { attributes: true, attributeFilter: ["hidden"] });
  document.getElementById("plan-src-toggle")?.addEventListener("click", (e) => {
    панель.hidden = !панель.hidden;
    e.currentTarget.setAttribute("aria-expanded", String(!панель.hidden));
    e.currentTarget.querySelector(".src-bar-caret").textContent = панель.hidden ? "▴" : "▾";
  });
  collapseLongCardList(document.getElementById("materials-list"), 8);
  if (ходСборки) {
    показатьХодСборки(id, { findingsId: "verify-findings-plan", btnId: "prepare-plan-btn", since: ходСборки.since,
                            queued: ходСборки.queued, lines: ходСборки.lines });
    начатьСлежениеЗаСборкой(id, () => renderMeetingDetail(id));
  }

  if (admin && verdict && verdict.findings && verdict.findings.length) {
    const targetId = "verify-findings-plan";
    document.getElementById(targetId).innerHTML = `
      <div class="page-sub" style="margin-top:8px">План собран, но не сохранился. Замечания проверки этого черновика:</div>
      <ul>
        ${verdict.findings.map(f => `<li><b>${esc(VERIFY_CATEGORY_LABELS[f.category] || f.category || "Замечание")}:</b>
          «${esc(f.quote || "")}» — ${esc(f.issue || "")}</li>`).join("")}
      </ul>
      <div class="page-sub">После сохранения каждое существенное замечание станет карточкой администратора.
        Можно и собрать заново кнопкой «${подписьКнопки}» вверху.</div>`;
  }

  if (admin && verdict && verdict.can_accept) {
    // То же решение, что и у Протокола (23.09.26, ответ владельца п.9): в черновике нет находок кода — принять решает администратор
    const принятьЧерновикПлана = async () => {
      if (!(await confirmDialog("Сохранить план как есть, с замечаниями проверки?", "Сохранить"))) return;
      try {
        const итог = await api(`/meetings/${id}/accept-plan-draft`, { method: "POST" });
        toast("План сохранён. " + текстЗамечаний(итог, "План"));
        renderMeetingDetail(id);
      } catch (e) { toast(e.message, true); }
    };
    document.getElementById("accept-plan-banner-btn")?.addEventListener("click", принятьЧерновикПлана);
    document.getElementById("accept-plan-banner-замечания")?.addEventListener("click", () => {
      панель.hidden = false;
      document.getElementById("verify-findings-plan")?.scrollIntoView({ block: "center" });
    });
    const box = document.getElementById("verify-findings-plan");
    if (box) {
      // Кнопку приёмки не дублируем и здесь — решение в баннере над документом (то же правило для обоих
      // документов, живой случай владельца 12.10.26).
      box.insertAdjacentHTML("beforeend",
        `<div class="page-sub" style="margin-top:8px">Принять или отклонить черновик можно кнопкой в баннере над документом.</div>`);
    }
  }

  const движок = document.getElementById("prepare-plan-btn");
  const главная = document.getElementById("plan-main-btn");
  if (готовит && движок && главная) {
    движок.addEventListener("click", () => runMeetingGeneration({
      id, btnId: "prepare-plan-btn", endpoint: `/meetings/${id}/prepare-plan?confirm=1`, findingsId: "verify-findings-plan",
      idleLabel: подписьКнопки,
      okToast: "План сохранён",
      partialToast: `План сохранён, но Дорожная карта/Сводка не обновились — ${conflictsRef()}`,
    }));
    // Подпись и состояние главной кнопки — вслед за скрытой кнопкой сборки: «Идёт сборка с ЧЧ:ММ, N мин», не нажимается (О5)
    const обновить = () => {
      const с = подписьСсылкиСборки(движок, hasPlan);
      const текст = с.идёт ? с.текст : подписьКнопки;
      if (главная.textContent !== текст) главная.textContent = текст;
      главная.disabled = с.идёт || (движок.disabled && /Генерирую|В очереди/.test(движок.textContent));
    };
    обновить();
    const наблюдатель = new MutationObserver(обновить);
    наблюдатель.observe(движок, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });
    const тикер = setInterval(() => {
      if (!главная.isConnected) { clearInterval(тикер); наблюдатель.disconnect(); return; }
      обновить();
    }, 1000);
    главная.addEventListener("click", async () => {
      if (главная.disabled || подписьСсылкиСборки(движок, hasPlan).идёт) return;
      // Д7 (проход 1, 21.10.2026): окно называет встречу и предупреждает, что она прошла; Д6 — не обещает истории версий,
      // которой на экране нет (прежняя версия плана в базе остаётся, просмотра версий пока нет)
      const название = cleanLabel(meeting.label) ? ` «${cleanLabel(meeting.label)}»` : "";
      const прошлаТекст = прошла ? `\n\nВстреча ${fmtRuDate(meeting.date)} уже прошла — план к прошедшей встрече обычно не нужен.${ближайшая
        ? ` Ближайшая встреча — ${fmtRuDate(ближайшая.date)}.` : ""}` : "";
      const вопрос = `${подписьКнопки} — встреча ${fmtRuDate(meeting.date)}${название}?${прошлаТекст}\n\nЭто платный вызов модели, 1–5 минут. План сохраняется сразу, прежняя версия не удаляется — остаётся в базе.${hasPlan && plan.hand_edited ? ПРЕДУПРЕЖДЕНИЕ_РУЧНЫХ_ПРАВОК : ""}`;
      if (!(await confirmDialog(вопрос, hasPlan ? "Переформировать" : "Сформировать"))) return;
      движок.disabled = false;
      движок.click();
    });
    document.getElementById("plan-newer")?.addEventListener("click", () => {
      // сборку начали уже после отрисовки (кнопка заняла себя сама) — плашка не молчит
      if (главная.disabled) { toast("Сейчас идёт сборка — новые материалы войдут в следующую; переформировать можно после неё"); return; }
      главная.click();
    });
  }

  document.getElementById("material-file")?.addEventListener("change", (e) => {
    if (!e.target.files.length) return;
    панель.hidden = false;                           // панель раскрыта и после перерисовки — помнится по встрече
    document.getElementById("material-file-selected").textContent =
      "Загружаю: " + Array.from(e.target.files).map(f => f.name).join(", ") + "…";
    uploadFile(`/meetings/${id}/materials`, "material-file",
      { description: document.getElementById("material-desc").value },
      "Материал добавлен", () => renderMeetingDetail(id), true);
  });
  $main.querySelectorAll(".delete-material-btn").forEach(btn => btn.addEventListener("click", async () => {
    if (!(await confirmDialog("Удалить этот материал? Восстановить его нельзя.", "Удалить"))) return;
    try {
      await api(`/meetings/${id}/materials/${btn.dataset.id}`, { method: "DELETE" });
      toast("Материал удалён");
      renderMeetingDetail(id);
    } catch (e) { toast(e.message, true); }
  }));
  if (таЖе) window.scrollTo(0, прокрутка);          // перерисовка той же встречи — страница не прыгает
}

// lastTaskChange (опционально) — решение 14.09.26: сам текст документа не
// трогаем (Протокол/План — исторический снимок по замыслу скиллов), но если
// в реестре задач что-то поменялось ПОСЛЕ генерации этого конкретного
// документа — показываем предупреждение рядом, а не молчим.
// editBaseUrl/blockId — решение 14.09.26 («механизм точечной правки»,
// см. DECISIONS.md): если заданы и пользователь admin, под документом
// рисуется панель ручной правки (найти/заменить один фрагмент, без ИИ)
// и правки через ограниченный ИИ-запрос (свободный текст + проверка по
// источнику). Не показывается на страницах без editBaseUrl (например,
// карточки «Данные проекта» — там это дублирующий, не канонический вид
// документа, редактировать нужно со страницы встречи/статуса).
// Решение 17.09.26 — раньше content_md выводился как сырой экранированный
// текст (esc()) внутри pre-wrap-блока: весь текст одним слитным полотном,
// без единого заголовка или списка, хотя сам текст СТРУКТУРНО построен по
// узнаваемым, но не совсем markdown, соглашениям: первая строка — название
// документа; короткая строка без конечной точки сама по себе (не часть
// таблицы/списка) — заголовок раздела; строки «— текст» — пункты списка
// (бывают и через пустую строку, и подряд без неё — оба варианта
// встречаются в реальных документах); `|...|` — уже настоящая markdown-
// таблица, эту часть парсить не пришлось. Разбирает и строит HTML —
// заголовки/списки/таблицы по-настоящему, не текстом с чёрточками.
function _isDocTableLine(line) {
  const s = line.trim();
  return s.startsWith("|") && s.endsWith("|") && s.length > 1;
}
function _isDocTableSeparator(line) {
  const cells = line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  return cells.every(c => /^-+$/.test(c));
}
function _parseDocTableRow(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
}

// Внутренний номер задачи → номер строки в таблице этого документа (с 1). Тот же разбор — в draft_guards.display_renumber_tables
// для Word.
function docShownIds(md) {
  const lines = String(md || "").split("\n");
  const shown = new Map();
  for (let k = 0, inTable = false, cnt = 0; k < lines.length; k++) {
    if (!_isDocTableLine(lines[k])) { inTable = false; continue; }
    if (_isDocTableSeparator(lines[k])) continue;
    const cells = _parseDocTableRow(lines[k]);
    if (!inTable) { inTable = /^№?\s*$/.test((cells[0] || "").trim()); cnt = 0; continue; }
    if (/^\d+$/.test((cells[0] || "").trim())) { cnt++; if (!shown.has(+cells[0].trim())) shown.set(+cells[0].trim(), cnt); }
  }
  return shown;
}

// «№135» в тексте — номером строки таблицы документа. Номер, которого в таблицах нет, но за которым идёт формулировка задачи
// («№45 Настроить правила обмена») — внутренний, человеку не показывается (обход 02.10 вечер: Протокол 17.09, раздел «Задачи
// без подтверждённого статуса»). «склад №1», «задача №999 не найдена» не трогаются — за номером нет заглавной буквы.
function hideTaskIds(text, shown) {
  return String(text || "").replace(/№\s?(\d+)(\s+(?=[А-ЯЁ«"]))?/g,
    (m, d, gap) => shown.has(+d) ? `№${shown.get(+d)}${gap || ""}` : (gap ? "" : m));
}

// Колонки таблицы задач по заголовкам: «№ | Описание/Задача | Ответственный | Срок/Закрыта | Комментарии/Статус/К встрече».
// Не таблица задач — null.
function taskTableCols(head) {
  const h = head.map(c => String(c || "").trim().toLowerCase());
  if (!/^№?$/.test(h[0]) || !/^(описание|задача)/.test(h[1] || "")) return null;
  const cls = h.map((c, i) => i === 0 ? "c-num" : /^(описание|задача)/.test(c) ? "c-desc" : /^ответствен/.test(c) ? "c-resp"
    : /^(срок|закрыта)/.test(c) ? "c-due" : "c-rest");
  // Нечему забрать остаток (План, 3 колонки) — его берёт ПОСЛЕДНЯЯ колонка: «Задача» той же ширины, что в соседних таблицах,
  // и «Ответственный» встаёт на ту же линию (владелец 03.10.26: остаток у «Описания» уводил «Ответственного» к правому краю).
  if (!cls.includes("c-rest")) cls[cls.length - 1] = "c-rest";
  return cls;
}

// Строка-раздел документа: «1 Название», «2. Название» — короткая, начинается с номера, без точки на конце.
// Это формат разделов Сводки и Дорожной карты (скилл project-briefing: «с номерами разделов без пунктуации,
// «1 Название», не markdown-заголовок»). Такой строкой раздел виден и когда документ пришёл слитным текстом,
// без пустой строки перед строкой (09.10.26). Список задач и сроки под правило не попадают: «1С:ERP …» идёт
// без пробела после номера, «10.10.26 …» — не «номер + слово», а дата.
function isDocSectionHeading(line) {
  const s = String(line || "").trim();
  if (!s || s.length >= 100) return false;
  if (!/^\d{1,2}[.)]?\s+[А-ЯЁA-Z«"]/.test(s)) return false;
  return !/[.!?:]\s*$/.test(s);
}

// Задача этой встречи в едином списке протокола (решение владелицы 18.10.2026, п. 3): сервер ставит в начале формулировки
// пометку «[new] » (draft_guards.NEW_TASK_MARK — только при показе, в базе её нет), экран рисует маленький значок «new».
// Тот же значок и та же пометка — у Планёрки (app.js, docNewMark).
function docNewMark(text) {
  const пометка = "[new] ";
  const строка = String(text || "").trim();
  if (!строка.startsWith(пометка)) return { текст: text, значок: "" };
  return { текст: строка.slice(пометка.length),
    значок: `<span class="doc-new" title="новая задача этой встречи" aria-label="новая задача этой встречи">new</span>` };
}

// Служебное слово договорённости в протоколе (решение владелицы 19.10.2026, по протоколу планёрки 19.10; как Планёрка):
// строка «Решили: …» / «Открытый вопрос: …» (и «— Решили: …» в пункте из строк) показывается словом «решили:» /
// «открытый вопрос:» — со строчной, курсивом, приглушённым цветом, не полужирным (класс doc-agree-label, theme-line.css).
// Раньше абзац попадал под правило «Метка: текст» и метка шла полужирной. Это вид при показе: текст документа не
// меняется, поэтому действует и для сохранённых протоколов. Тот же вид — в Word (md_to_docx) и у Планёрки.
function docAgreeHtml(text, inline) {
  const m = /^(Решили|Открытый вопрос):\s+(.+)$/.exec(String(text || "").trim());
  if (!m) return null;
  // 26.10.2026 (решение владелицы, обе системы): слова «Решили» в протоколе нет — строка «Решили: …» сохранённого
  // протокола показывается обычным предложением без метки, с заглавной буквы; «Открытый вопрос:» — как прежде.
  // «Открытый вопрос:» — тоже без метки (ответ владелицы 26.10.2026)
  if (m[1] === "Решили" || m[1] === "Открытый вопрос") return inline(m[2].charAt(0).toUpperCase() + m[2].slice(1));
  return `<span class="doc-agree-label">${m[1].toLowerCase()}:</span> ${inline(m[2])}`;
}

function renderDocHtml(md, опц) {
  // Правка на полотне (решение владелицы 24.10.2026, polotno.js): в режиме правки у абзаца, пункта, заголовка и строки
  // таблицы — исходный текст (data-src / data-line) и его неизменяемое начало (data-pre: «## », «**Метка** — », «— »).
  // В показе атрибутов нет.
  const ист = !!(опц && опц.источник);
  const атр = (raw, pre) => (ист ? ` data-src="${esc(raw)}" data-pre="${esc(pre || "")}"` : "");
  // Цикл 2: «### Раздел 2 — …» приходил посреди строки, а «- пункты» — слитно через точку: выносим на отдельные строки
  md = String(md || "")
    .replace(/([^\n])[ \t]+(#{2,4}[ \t]+\S)/g, "$1\n\n$2")
    .replace(/([.;:])[ \t]+-[ \t]+(?=[А-ЯЁA-Z«"])/g, "$1\n- ");
  const lines = String(md || "").split("\n");
  const n = lines.length;
  let i = 0;
  let isFirst = true;
  let html = "";

  // Пометки «*(…)*» — курсивом (тест двух циклов 01.10.26).
  // Номера задач человеку — по порядку с 1 в каждой таблице, внутренний номер не показывается (правило владельца 24.09.26,
  // возвращено 02.10.26 вечером). Ссылка «№135» в тексте — тем же номером, что у задачи в таблице документа; строка «—»
  // (задача ещё не в реестре) номера не получает и счёт не сбивает.
  const shownIds = docShownIds(md);
  // «**…**» — жирным: так код выделяет название темы протокола («**Тема:** текст», doc_format.темы_в_строку, 13.10.26)
  const fmt = (s) => hideTaskIds(esc(s)
    .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>"), shownIds);
  let regOpen = false;   // карточка «Реестр задач» протокола — от своего заголовка до конца документа

  const nextNonBlank = (from) => {
    let j = from;
    while (j < n && lines[j].trim() === "") j++;
    return j;
  };

  const flushPara = (buf) => {
    if (!buf.length) return;
    const text = buf.join(" ").replace(/\s+/g, " ").trim();
    if (!text) return;
    if (isFirst) {
      html += `<div class="doc-title">${esc(text)}</div>`;
      isFirst = false;
      return;
    }
    // «Предложение ассистента (не решение встречи) — …» в Сводке и Карте (решение владелицы 19.10.2026: оставить, но светлее
    // основного текста и курсивом — тот же приём, что у «решили:» в протоколе, токен --text-muted, 4,83:1; так же в Word)
    if (text.startsWith("Предложение ассистента (не решение встречи)")) { html += `<p class="doc-assistant"${атр(buf.join("\n"), "")}>${fmt(text)}</p>`; return; }
    // Посреди абзаца (находка локальной машины 19.10.2026): текст до пометки — обычным, от пометки до конца — тем же видом
    const гдеАссистент = text.indexOf("Предложение ассистента (не решение встречи)");
    if (гдеАссистент > 0) { html += `<p${атр(buf.join("\n"), "")}>${fmt(text.slice(0, гдеАссистент))}<span class="doc-assistant">${fmt(text.slice(гдеАссистент))}</span></p>`; return; }
    const сырой = buf.join("\n");
    const singleLine = buf.length === 1;
    const looksLikeHeading = singleLine && text.length < 100 && !/[.!?:]\s*$/.test(text);
    if (looksLikeHeading) {
      // Протокол: две таблицы задач показываются одной «Реестр задач» в карточке (решение владельца 13.10.26)
      if (text === "Реестр задач" && !regOpen) { html += `<section class="doc-reg">`; regOpen = true; }
      html += `<div class="doc-heading"${атр(сырой, "")}>${esc(text)}</div>`;
      return;
    }
    // Абзац темы протокола: название и текст в одной строке (владелец 13.10.26: «подзаголовок + абзац, абзац начинается
    // сразу в этой же строке»). Название — плашкой, без двоеточия.
    const themeMatch = /^\*\*([^*\n]{1,89}?):\*\*\s+(.+)$/.exec(text);
    if (themeMatch) {
      html += `<p class="doc-theme"${атр(сырой, сырой.slice(0, сырой.length - themeMatch[2].length))}><span class="doc-theme-name">${esc(themeMatch[1])}</span> ${fmt(themeMatch[2])}</p>`;
      return;
    }
    // Жалоба 17.09.26 (вторая) — абзацы вида «Название блока: пояснение…»
    // (напр. в Дорожной карте) визуально сливались в сплошной текст без
    // разделения на блоки. Метка до первого «:» выделяется жирным как
    // мини-заголовок блока, весь абзац дополнительно оформлен карточкой —
    // не трогает docx-экспорт (там это уже убирали по отдельной просьбе,
    // см. add_paragraph в md_to_docx.py), это фикс только фронтового вида.
    const договорённость = docAgreeHtml(text, fmt);
    if (договорённость) { html += `<p class="doc-agree"${атр(сырой, "")}>${договорённость}</p>`; return; }
    const labelMatch = /^([А-ЯЁA-Z][^:]{1,89}):\s+(.+)$/.exec(text);
    html += labelMatch
      ? `<div class="doc-block"${атр(сырой, "")}><strong>${esc(labelMatch[1])}:</strong> ${fmt(labelMatch[2])}</div>`
      : `<p${атр(сырой, "")}>${fmt(text)}</p>`;
  };

  let paraBuf = [];
  while (i < n) {
    const trimmed = lines[i].trim();

    if (trimmed === "") {
      flushPara(paraBuf); paraBuf = [];
      i++;
      continue;
    }

    if (_isDocTableLine(lines[i])) {
      flushPara(paraBuf); paraBuf = [];
      const rows = [];
      const сырыеСтроки = [];
      while (i < n && _isDocTableLine(lines[i])) {
        if (!_isDocTableSeparator(lines[i])) { rows.push(_parseDocTableRow(lines[i])); сырыеСтроки.push(lines[i].trim()); }
        i++;
      }
      if (rows.length) {
        // Номер в таблице — по порядку с 1 среди строк с номером (см. shownIds выше); «—» остаётся «—».
        const numberCol = /^№?\s*$/.test((rows[0][0] || "").trim()) ? 0 : -1;
        let seq = 0;
        // Таблица задач (реестры «Данных проекта», задачи Протокола и Плана) — те же доли колонок, что в реестре на главной
        // (владелец 02.10.26: «так хорошо, сделай аналогично по сходным таблицам»). Последняя текстовая колонка — остаток.
        const colCls = taskTableCols(rows[0]);
        // Колонка «Откуда» (единый итог из всех источников, 21.10.2026) — тонкой меткой: тот же doc-cell-sub, что у
        // «поставлена …» (токен --text-muted), новых стилей нет. Тот же приём — у Планёрки (app.js, docCell).
        const откудаCol = colCls ? rows[0].findIndex(c => String(c || "").trim().toLowerCase() === "откуда") : -1;
        html += `<table class="doc-table${colCls ? " doc-table-tasks" : ""}"><thead><tr>${rows[0].map((c, ci) => `<th${colCls ? ` class="${colCls[ci]}"` : ""}>${esc(c)}</th>`).join("")}</tr></thead>
          <tbody>${rows.slice(1).map((r, k) => `<tr${ист ? ` data-line="${esc(сырыеСтроки[k + 1])}"` : ""}>${r.map((c0, ci) => {
            const { текст: c, значок } = docNewMark(c0);      // значок «new» — задача этой встречи (18.10.2026)
            return ci === numberCol && /^\d+$/.test(c.trim())
              ? `<td>${++seq}</td>`
              : ci === откудаCol
                ? `<td><span class="doc-cell-sub">${fmt(c)}</span></td>`
              : c.includes("¦")       // «текст¦подпись» — подпись тонкой строкой под текстом (дата постановки, 02.10.26)
                ? `<td>${значок}${fmt(c.split("¦")[0])}<span class="doc-cell-sub">${fmt(c.split("¦").slice(1).join(" "))}</span></td>`
                : `<td>${значок}${fmt(c)}</td>`;
          }).join("")}</tr>`).join("")}</tbody></table>`;
      }
      isFirst = false;
      continue;
    }

    if (trimmed.startsWith("— ")) {
      flushPara(paraBuf); paraBuf = [];
      const items = [];
      const сырыеПункты = [];
      while (i < n) {
        const t = lines[i].trim();
        if (t.startsWith("— ")) { items.push(t.slice(2).trim()); сырыеПункты.push(t); i++; }
        else if (t === "" && lines[nextNonBlank(i)] !== undefined && lines[nextNonBlank(i)].trim().startsWith("— ")) { i = nextNonBlank(i); }
        else break;
      }
      html += `<ol class="doc-list">${items.map((it, k) => `<li${атр(сырыеПункты[k], сырыеПункты[k].slice(0, сырыеПункты[k].length - it.length))}>${docAgreeHtml(it, fmt) || fmt(it)}</li>`).join("")}</ol>`;
      isFirst = false;
      continue;
    }

    // Раздел Сводки и Дорожной карты — строка «1 Название» (формат скилла: номер без пунктуации). Разделом
    // считаем её и БЕЗ пустой строки перед ней (09.10.26): пересчёт 08.10 на новой модели вернул документ
    // подряд, без пустых строк, и без этого правила ВЕСЬ текст попадал в первый блок — то есть в «название
    // документа», и Сводка показывалась одной жирной строкой (жалоба владельца). Текст документа теперь
    // приводится к блочному виду при сохранении, а здесь — защита от слитного текста из любого источника,
    // включая ручную правку. Строк таблиц и списков это не касается: они разобраны выше.
    if (isDocSectionHeading(trimmed)) {
      flushPara(paraBuf); paraBuf = [];
      html += `<div class="doc-heading"${атр(trimmed, "")}>${esc(trimmed)}</div>`;
      isFirst = false;
      i++;
      continue;
    }

    paraBuf.push(trimmed);
    i++;
  }
  flushPara(paraBuf);
  if (regOpen) html += `</section>`;
  // Протокол — своё оформление (решение владельца 13.10.26, стили .doc-protocol): текст 15,5/1,4, темы, карточка реестра
  const firstLine = (lines.find(l => l.trim()) || "").trim();
  return /^(Протокол встречи|Черновик протокола)/.test(firstLine) ? `<div class="doc-protocol">${html}</div>` : html;
}

function docBlock(doc, exportUrl, lastTaskChange, editBaseUrl, blockId, opts = {}) {
  if (!doc.available) return `<div class="empty-state">${esc(doc.message)}</div>`;
  const stale = lastTaskChange && doc.generated_at && new Date(doc.generated_at) < new Date(lastTaskChange);
  // Панели «Точечная правка (админ)» больше нет (решение владелицы 24.10.2026): правка — на полотне (polotno.js)
  // «Откуда — собрано …» — строка состояния документа: только администратору (правило владельца 13.10.26 «документы чистые»)
  const sourcesLine = (!opts.hideSources && isAdmin() && doc.sources && doc.sources.length) ? `<div class="doc-sources-line">
      <b>Откуда</b> — собрано ${doc.generated_at ? fmtRuDateTime(doc.generated_at) : "автоматически"}.
      Источники: ${doc.sources.map(s => `«${esc(s.original_filename)}»`).join(", ")}.
    </div>` : "";
  return `<div class="card card-output stack${opts.compact ? " doc-compact" : ""}${opts.noBar ? " doc-nobar" : ""}">
    ${sourcesLine}
    ${stale ? `<div class="page-sub" style="color: var(--warning)">После последнего обновления документов текст мог устареть. Сверьтесь с текущим Реестром задач.</div>` : ""}
    ${reviewNotesLayout(doc, blockId ? `${blockId}-doc` : "")}
    ${opts.compact ? "" : `<div class="hstack"><a class="btn btn-sm" href="${exportUrl}" target="_blank">Скачать .docx</a></div>`}
  </div>`;
}

// Шапка страницы встречи — одна строка (решение владельца 01.10.26: «1/3 экрана занята служебными заголовками, текст и
// кнопки внизу»). Слева — назад, встреча и переключатель «План | Протокол» (два документа одной встречи — вкладки, а не
// отдельные строки-ссылки), справа — «Скачать .docx» и «Правка». Текст документа идёт сразу под ней и тянется на экран.
function meetingDocHead({ backHref, backLabel, meeting, active, hasPlan, hasMin, generatedAt, exportUrl, editId, editBase = "", безПротокола = false }) {
  const tab = (key, label, href, exists) => key === active
    ? `<span class="doc-tab doc-tab-on">${label}</span>`
    : `<a class="doc-tab${exists ? "" : " doc-tab-empty"}" href="${href}">${label}${exists ? "" : " · нет"}</a>`;
  return `<div class="doc-head">
    <a href="${backHref}" class="btn btn-sm">${esc(backLabel)}</a>
    <h1>Встреча ${esc(fmtRuDate(meeting.date))}${cleanLabel(meeting.label) ? " — " + esc(cleanLabel(meeting.label)) : ""}</h1>
    <nav class="doc-tabs">${tab("plan", "План", `#meetings/${meeting.id}`, hasPlan)}${безПротокола ? "" : tab("protocol", "Протокол", `#meetings/${meeting.id}/protocol`, hasMin)}</nav>
    ${generatedAt && isAdmin() ? `<span class="doc-head-meta">собран ${esc(fmtRuDateTime(generatedAt))}</span>` : ""}
    <span class="doc-head-spacer"></span>
    ${exportUrl ? `<a class="btn btn-sm" href="${exportUrl}" target="_blank">Скачать .docx</a>` : ""}
    ${editId && editBase && isAdmin() ? полотноПереключатель(editBase, полотноРежим(editBase), "prep-edit-switch") : ""}
    ${/* у отменённой дату не меняют (сервер — 400): кнопка была обманкой (Д3, проход 3, 21.10.2026) */ ""}
    ${isAdmin() && !hasMin && meeting.status !== "cancelled" && new Date(meeting.date) >= new Date(new Date().toDateString())
      ? `<button type="button" class="btn-sm" data-edit-date="${meeting.id}" data-date="${esc(String(meeting.date).slice(0, 10))}">Изменить дату</button>` : ""}
    ${/* «Удалить встречу» (решение владелицы 23.10.2026, вместо отмены): администратору, у встречи без протокола; что ещё
          держит встречу (план, материалы, задачи), сервер скажет до окна подтверждения */ ""}
    ${isAdmin() && !hasMin && meeting.status !== "cancelled"
      ? `<button type="button" class="btn-sm" data-delete-meeting="${meeting.id}" data-date="${esc(String(meeting.date).slice(0, 10))}">Удалить встречу</button>` : ""}
  </div>
  ${isAdmin() ? `<div class="plan-top-note" id="merged-note" data-merged-for="${meeting.id}" hidden></div>` : ""}`;
}

// «Удалить встречу» (решение владелицы 23.10.2026: «отмена без удаления только добавляет лишних строк»). Сначала сервер
// говорит, что держит встречу (`delete-check`) — тогда окна подтверждения нет, только объяснение; пустую — после
// подтверждения удаляет по-настоящему, след — строка в «Технических сообщениях». Держит только план встречи — вместо тупика
// окно предлагает «Отменить встречу» (решение владелицы 23.10.2026): план сохраняется, встреча уходит из списков, списка
// отменённых нет.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-delete-meeting]");
  if (!btn) return;
  const id = btn.dataset.deleteMeeting;
  try {
    const проверка = await api(`/meetings/${id}/delete-check`);
    if (!проверка.can_delete && проверка.can_cancel) {
      if (!(await confirmDialog(проверка.cancel_text, "Отменить встречу"))) return;
      await api(`/meetings/${id}/cancel-with-plan`, { method: "POST" });
      toast(`Встреча ${fmtRuDate(btn.dataset.date)} отменена — план сохранён`);
      location.hash = "#prep";
      return;
    }
    if (!проверка.can_delete) { toast(проверка.detail, true); return; }
    if (!(await confirmDialog(`Удалить встречу ${fmtRuDate(btn.dataset.date)}? Это нельзя отменить`, "Удалить"))) return;
    await api(`/meetings/${id}`, { method: "DELETE" });
    toast(`Встреча ${fmtRuDate(btn.dataset.date)} удалена`);
    location.hash = "#prep";
  } catch (err) { toast(err.message, true); }
});

// «Вернуть на новую дату» (Д3, решение владелицы 23.10.2026): у встречи-получателя видно, из каких встреч сведены материалы
// («из встречи от дд.мм.гггг (№N)»); администратор выбирает дату — сервер заводит встречу по правилу «одна встреча на дату»
// (занятая — отказ, встреча не заводится) и переносит в неё материалы этой сводки, файлы тоже. Строка заполняется после
// отрисовки шапки — шапка рисуется строкой, данные приходят отдельным запросом.
async function показатьСводки() {
  const $м = document.querySelector("[data-merged-for]");
  if (!$м || $м.dataset.filled) return;
  $м.dataset.filled = "1";
  const id = $м.dataset.mergedFor;
  let сводки = [];
  try { сводки = await api(`/meetings/${id}/merged`); } catch { return; }
  if (!сводки.length || !document.body.contains($м)) return;
  $м.innerHTML = сводки.map(с => `<div>Материалы из встречи от ${esc(fmtRuDate(с.from_date))} (№${с.from_id}) — ${с.count}, сведены сюда ${esc(fmtRuDateTime(с.moved_at))}.
    <button type="button" class="btn-sm" data-unmerge-from="${с.from_id}" data-unmerge-to="${id}" data-count="${с.count}">Вернуть на новую дату</button></div>`).join("");
  $м.hidden = false;
}
new MutationObserver(() => { if (document.querySelector("[data-merged-for]:not([data-filled])")) показатьСводки(); })
  .observe(document.body, { childList: true, subtree: true });

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-unmerge-from]");
  if (!btn) return;
  const ov = openModal("Вернуть на новую дату", `
    <div class="page-sub" style="margin:0 0 8px">Материалы этой сводки (${esc(btn.dataset.count)}) перенесутся во встречу на выбранную дату. На занятую дату встреча не заводится.</div>
    <div class="field"><label for="unmerge-date">Дата встречи</label><input type="date" id="unmerge-date" min="2020-01-01" max="2099-12-31"></div>`, async (o) => {
    const дата = o.querySelector("#unmerge-date").value;
    if (!дата) throw new Error("Укажите дату встречи");
    const итог = await api(`/meetings/${btn.dataset.unmergeTo}/unmerge`, { method: "POST", json: { from_id: Number(btn.dataset.unmergeFrom), date: дата } });
    toast(`Материалы (${итог.moved}) перенесены во встречу ${fmtRuDate(итог.meeting.date)}`);
    location.hash = `#meetings/${итог.meeting.id}/planprep`;
  });
  ov.querySelector("#unmerge-date").focus();
});

// Дата встречи, по которой ещё ничего нет (02.10.26): следующую встречу система заводит сама — через обычный шаг, с пометкой
// «дата ориентировочная»; если встреча будет в другой день, дату правят здесь. С Протоколом или источниками дата не меняется.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-edit-date]");
  if (!btn) return;
  const ov = openModal("Дата встречи", `
    <div class="field"><label for="meeting-date-input">Дата</label><input type="date" id="meeting-date-input" value="${esc(btn.dataset.date)}"></div>
    <div class="page-sub" style="margin:0">План этой встречи останется, дата в его заголовке поменяется.</div>`, async (o) => {
    const v = o.querySelector("#meeting-date-input").value;
    if (!v) throw new Error("Укажите дату");
    await api(`/meetings/${btn.dataset.editDate}/date`, { method: "PATCH", json: { date: v } });
    toast("Дата встречи изменена");
    render();
    // Д4 (проход 1, 21.10.2026): путь слева обновлялся раз в 15 с и показывал прежнюю дату — обновляем сразу
    if (typeof следитьЗаПутём === "function") следитьЗаПутём();
  });
  ov.querySelector("#meeting-date-input").focus();
});

// Замечания проверки — панель справа от документа, как комментарии в Word (решение владельца 01.10.26: список под
// документом мешал и не читался). Видны короткие заголовки до 6 слов; подробности и подсветка фрагмента — по клику.
// «Учтено» скрывает замечание для всех, «Вернуть» показывает снова. Обработчики — общие, на document (ниже).
function reviewNotesLayout(doc, docId = "") {
  const docHtml = `<div class="doc-content"${docId ? ` id="${docId}"` : ""}>${renderDocHtml(doc.content_md)}</div>`;
  const notes = doc.minor_findings || [];
  if (!notes.length) return docHtml;
  const open = notes.filter(n => !n.dismissed);
  const done = notes.filter(n => n.dismissed);
  const narrow = window.matchMedia("(max-width: 768px)").matches;
  let collapsed = narrow || !open.length;
  try { if (localStorage.getItem("reviewNotesCollapsed") === "1") collapsed = true; } catch (e) { /* без памяти — по умолчанию */ }
  // Карточка (второй заход 01.10.26, «фраза размыта»): что не так → где → почему. Без служебных строк; полный
  // разбор проверяющей модели — только по клику и свёрнут.
  // Действия у замечания (решение владельца 01.10.26: «решили принять, а кнопки нет»; без ИИ и без оплаты): кнопка
  // «согласиться» зависит от типа — «Снять задачу», «Статус не прозвучал», «Поправить»; у всех — «Оставить как есть».
  // Видны только у развёрнутого замечания. Решение уходит в «Реестр решений».
  const agree = { task: ["drop_task", "Снять задачу"], status: ["no_status", "Статус не прозвучал"], text: ["fix", "Поправить"] };
  const actions = (n) => !isAdmin() ? "" : n.dismissed
    ? (["seen", "keep", "fixed"].includes(n.outcome) ? `<div class="rn-actions"><button type="button" class="btn-sm" data-note-act="undo">Вернуть</button></div>` : "")
    : `<div class="rn-actions">
        <button type="button" class="btn-sm btn-primary" data-note-act="${agree[n.kind || "text"][0]}">${agree[n.kind || "text"][1]}</button>
        <button type="button" class="btn-sm" data-note-act="keep">Оставить как есть</button></div>`;
  const ids = docShownIds(doc.content_md);
  // Номер задачи в тексте замечания уже заменён сервером (review_notes.humanize_ids: номер строки таблицы или формулировка) —
  // второй раз здесь не пересчитываем, иначе «№1» превратился бы в номер строки задачи с внутренним номером 1.
  const h = (t) => esc(t);
  const item = (n) => `<li class="rn-item${n.dismissed ? " rn-dismissed" : ""}" data-quote="${esc(n.quote)}"
      data-run="${n.run_id}" data-idx="${n.idx}" data-kind="${esc(n.kind || "text")}" data-task-no="${n.task_no || ""}" data-task-shown="${ids.get(+n.task_no) || ""}">
      <button type="button" class="rn-title">${h(n.title || n.issue)}</button>
      ${n.quote ? `<div class="rn-where">${h(shortQuote(n.quote))}</div>` : ""}
      ${n.why ? `<div class="rn-why">${h(n.why)}</div>` : ""}
      <div class="rn-more" hidden>
        ${n.quote ? `<div class="rn-quote"><span class="rn-label">В тексте</span>«${h(cleanQuote(n.quote))}»</div>` : ""}
        ${n.issue && n.issue !== n.why ? `<details class="rn-full"><summary>Полный разбор</summary>${h(n.issue)}</details>` : ""}
      </div>
      ${n.dismissed && n.outcome_label ? `<div class="rn-outcome">${esc(n.outcome_label)}</div>` : ""}
      ${actions(n)}
    </li>`;
  return `<div class="doc-with-notes${collapsed ? " rn-collapsed" : ""}">
    ${docHtml}
    <aside class="review-notes">
      <button type="button" class="rn-head" aria-expanded="${!collapsed}">
        <span>Замечания · ${open.length}</span><span class="rn-chevron" aria-hidden="true">›</span>
      </button>
      <div class="rn-body">
        ${open.length ? `<ul class="rn-list" data-list="review-notes">${open.map(item).join("")}</ul>` : `<div class="rn-hint rn-all-done">Всё решено.</div>`}
        ${done.length ? `<details class="rn-done"><summary>Решённые · ${done.length}</summary>
          <ul class="rn-list">${done.map(item).join("")}</ul></details>` : ""}
      </div>
    </aside>
  </div>`;
}

// Цитата из строки таблицы приходит как «|116|Определить…|Очкивский…» — показываем без черт.
function cleanQuote(q) {
  // ячейка «116» строки таблицы — внутренний номер задачи, человеку не показывается (обход 02.10)
  return (q || "").split("|").map(x => x.trim()).filter(x => x && !/^№?\d+$/.test(x)).join(" · ");
}

// «Где» на карточке — начало цитаты, до 8 слов: чтобы отличить четыре одинаковых заголовка друг от друга.
function shortQuote(q) {
  const parts = (q || "").split("|").map(x => x.trim()).filter(x => x && !/^№?\d+$/.test(x));
  const text = (parts.sort((a, b) => b.length - a.length)[0] || "").replace(/\s+/g, " ");
  const words = text.split(" ");
  return words.length > 8 ? words.slice(0, 8).join(" ") + "…" : text;
}

function highlightQuote(docEl, quote) {
  docEl.querySelectorAll("mark.rn-hl").forEach(m => m.replaceWith(...m.childNodes));
  docEl.normalize();
  const parts = (quote || "").split("|").map(x => x.trim()).filter(x => x.length > 3);
  const q = (parts.sort((a, b) => b.length - a.length)[0] || "").replace(/\s+/g, " ").trim();
  if (!q) return false;
  // На экране даты документа — дд.мм.гггг (doc_format, 13.10.26), а цитата проверки — из хранимого текста с «13.10.26»
  const qLong = q.replace(/(^|[^\d.])(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])\.(\d{2})(?!\d|\.\d)/g, "$1$2.$3.20$4");
  for (const probe of [q, qLong, q.slice(0, 40), qLong.slice(0, 40)]) {
    const walker = document.createTreeWalker(docEl, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const at = node.nodeValue.indexOf(probe);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(node, at); range.setEnd(node, at + probe.length);
      const mark = document.createElement("mark");
      mark.className = "rn-hl";
      range.surroundContents(mark);
      mark.scrollIntoView({ block: "center", behavior: "smooth" });
      return true;
    }
  }
  return false;
}

document.addEventListener("click", async (e) => {
  const head = e.target.closest(".rn-head");
  if (head) {
    const box = head.closest(".doc-with-notes");
    const collapsed = box.classList.toggle("rn-collapsed");
    head.setAttribute("aria-expanded", String(!collapsed));
    try { localStorage.setItem("reviewNotesCollapsed", collapsed ? "1" : "0"); } catch (err) { /* не критично */ }
    return;
  }
  const title = e.target.closest(".rn-title");
  if (title) {
    const li = title.closest(".rn-item");
    const more = li.querySelector(".rn-more");
    const opening = more.hidden;
    li.closest(".review-notes").querySelectorAll(".rn-more").forEach(m => { m.hidden = true; });
    li.closest(".review-notes").querySelectorAll(".rn-item").forEach(x => x.classList.remove("rn-active"));
    const docEl = li.closest(".doc-with-notes").querySelector(".doc-content");
    if (opening) {
      more.hidden = false;
      li.classList.add("rn-active");
      const found = highlightQuote(docEl, li.dataset.quote);
      if (!found && li.dataset.quote && !more.querySelector(".rn-gone")) {
        more.insertAdjacentHTML("beforeend", `<div class="rn-gone">Фрагмента в тексте уже нет.</div>`);
      }
    } else {
      highlightQuote(docEl, "");
    }
    return;
  }
  const act = e.target.closest("[data-note-act]");
  if (act) {
    const li = act.closest(".rn-item");
    const action = act.dataset.noteAct;
    const url = `/review-notes/${li.dataset.run}/${li.dataset.idx}`;
    const what = shortQuote(li.dataset.quote) || "эта задача";
    if (action === "fix") { openFixForNote(li); return; }
    if (action === "drop_task" && !(await confirmDialog(`Снять задачу «${what}» в реестре и убрать её строку из Протокола?`, "Снять задачу"))) return;
    if (action === "no_status" && !(await confirmDialog(`${li.dataset.taskShown ? "Задача №" + li.dataset.taskShown : "Эта задача"}: в Протоколе поставить «не обсуждали», а в реестре снять придуманную формулировку статуса?`, "Да, не прозвучал"))) return;
    act.disabled = true;
    try {
      const r = await api(url, { method: "POST", json: { action } });
      toast(r.message || (action === "undo" ? "Замечание снова открыто" : "Решение записано"));
      render();
    } catch (err) { toast(err.message, true); act.disabled = false; }
  }
});

// Правка на полотне (решение владелицы 24.10.2026) — вместо панели «Точечная правка (админ)» под документом: переключатель
// «Просмотр / Правка» в шапке, правка по щелчку на месте (polotno.js, близнец Планёрки). Документы экрана запоминаются по
// blockId: «Поправить текст» блока «Проверить после сохранения» и «Поправить» у замечания включают режим правки своего
// документа; у замечания поле открывается у абзаца с его фрагментом, после сохранения замечание отмечается «поправлено
// вручную».
const _полотнаЭкрана = new Map();
// План встречи, который правил человек, при переформировании теряет правки — предупреждаем; протокол, который правил
// человек, моделью не пересобирается вовсе (решение владелицы 24.10.2026, п. 6)
const ПРЕДУПРЕЖДЕНИЕ_РУЧНЫХ_ПРАВОК = "\n\nЕсть ручные правки — они будут потеряны: новая версия собирается из источников заново. Прежняя версия и реестр корректировок останутся в базе.";
const ПЕРЕСБОРКА_ЗАПРЕЩЕНА = "Протокол правил человек — моделью он не пересобирается (решение владелицы 24.10.2026): правки человека сохраняются. Текст поправьте на полотне («Правка»).";

function подключитьПолотноДокумента(blockId, base, md, перерисовать, встреча) {
  if (!isAdmin()) return;
  _полотнаЭкрана.set(blockId, { base, перерисовать });
  полотноПодключитьПереключатель($main, перерисовать);
  if (полотноРежим(base) !== "edit") return;
  const док = document.getElementById(`${blockId}-doc`);
  let заметка = null;
  try { заметка = JSON.parse(sessionStorage.getItem("polotnoNote") || "null"); sessionStorage.removeItem("polotnoNote"); } catch (e) { заметка = null; }
  if (заметка && заметка.base !== base) заметка = null;
  // место на экране держит обёртка `сПрокруткойНаМесте` у перерисовки страницы (строка действия — первым якорем, 26.10.2026)
  const сохранитьПрокрутку = () => Promise.resolve(перерисовать());
  // ждём полотно (26.10.2026): обёртка прокрутки возвращала место, пока таблица задач была ещё в виде показа — короче,
  // и окно уезжало в 0 («Протокол» подготовки после «Сохранить» статуса: scrollY 3057 → 0)
  return полотноВключить(док, { base, md, перерисовать: сохранитьПрокрутку, встреча, заметка,
    послеСохранения: async () => {
      if (!заметка || !заметка.run) return;
      const з = заметка;
      заметка = null;
      try { await api(`/review-notes/${з.run}/${з.idx}`, { method: "POST", json: { action: "fixed" } }); }
      catch (err) { toast("Правка сохранена, но отметить замечание не удалось: " + err.message, true); }
    } });
}

function открытьТочечнуюПравку(blockId) {
  const д = _полотнаЭкрана.get(blockId);
  if (!д) return;
  полотноРежим(д.base, "edit");
  д.перерисовать();
}

// «Поправить» у замечания про текст: режим правки на полотне, поле — у абзаца с фрагментом замечания
function openFixForNote(li) {
  const blockId = (li.closest(".card-output")?.querySelector(".doc-content[id]")?.id || "").replace(/-doc$/, "");
  const д = _полотнаЭкрана.get(blockId);
  if (!д) { toast("Правка этого документа недоступна", true); return; }
  try { sessionStorage.setItem("polotnoNote", JSON.stringify({ base: д.base, quote: li.dataset.quote || "", run: li.dataset.run, idx: li.dataset.idx })); }
  catch (e) { /* без памяти вкладки — без поля у абзаца */ }
  полотноРежим(д.base, "edit");
  д.перерисовать();
}

// Приёмка файлов перетаскиванием (решение 30.09.26): раньше файлы заметок/материалов встречи
// добавлялись только выбором из папки через диалог — перетащить на страницу было нельзя. Работает
// поверх того же <input type="file">: подставляет перетащенные файлы в его .files и запускает
// существующий обработчик "change" (со всеми его проверками — например датой в имени файла), а не
// дублирует логику загрузки отдельным путём.

// «Свернуть» и Esc закрывают список источников над полосой (Протокол и План).
function closeSourcePanel(panel) {
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  const toggle = panel.closest(".src-bar-wrap")?.querySelector(".src-bar-sources");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "false");
    const caret = toggle.querySelector(".src-bar-caret");
    if (caret) caret.textContent = "▴";
  }
}
// Открыть панель источников программно. Единственный случай — начало сборки: ход сборки и замечания
// проверки печатаются внутри панели (verify-findings), а панель по умолчанию свёрнута (владелец 09.10.26).
// Человек в этот момент только что нажал кнопку — значит раскрытие ожидаемо, а не «само открылось».
function openSourcePanel(panel) {
  if (!panel || !panel.hidden) return;
  panel.hidden = false;
  const toggle = panel.closest(".src-bar-wrap")?.querySelector(".src-bar-sources");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "true");
    const caret = toggle.querySelector(".src-bar-caret");
    if (caret) caret.textContent = "▾";
  }
}
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-close-panel]");
  if (btn) closeSourcePanel(btn.closest(".src-bar-panel"));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") document.querySelectorAll(".src-bar-panel").forEach(closeSourcePanel);
});

// Перетаскивание на всю страницу (решение владельца 01.10.26: «а здесь никак не сделать перетаскиванием в область?»).
// На страницах Протокола и Плана файл можно бросить куда угодно: появляется подсказка во весь экран, файл уходит в поле
// загрузки полосы источников (`data-drop-input` у полосы). Обработчики ставятся один раз на всё время жизни страницы;
// на страницах без полосы перетаскивание не перехватывается.
function pageDropTarget() {
  const holder = document.querySelector("[data-drop-input]");
  return holder ? document.getElementById(holder.dataset.dropInput) : null;
}

(function wirePageDrop() {
  let depth = 0;
  const overlay = document.createElement("div");
  overlay.className = "page-drop-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `<div class="page-drop-box">Отпустите — файл добавится к источникам</div>`;
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(overlay));
  if (document.body) document.body.appendChild(overlay);
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  document.addEventListener("dragenter", (e) => {
    if (!hasFiles(e) || !pageDropTarget()) return;
    e.preventDefault();
    depth++;
    overlay.hidden = false;
  });
  document.addEventListener("dragover", (e) => { if (hasFiles(e) && pageDropTarget()) e.preventDefault(); });
  document.addEventListener("dragleave", (e) => {
    if (!hasFiles(e) || !pageDropTarget()) return;
    depth = Math.max(0, depth - 1);
    if (depth === 0) overlay.hidden = true;
  });
  document.addEventListener("drop", (e) => {
    const input = pageDropTarget();
    if (!hasFiles(e) || !input) return;
    e.preventDefault();
    depth = 0;
    overlay.hidden = true;
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    input.files = files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
})();

// Видео и звук — тот же список, что на сервере (`storage.MEDIA_EXTENSIONS`); совпадение сверяет
// тест tests/test_recording_upload_ui.py.
const MEDIA_EXTENSIONS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".ogg", ".flac"];

function isMediaFile(name) {
  const n = String(name || "").toLowerCase();
  return MEDIA_EXTENSIONS.some(ext => n.endsWith(ext));
}

// Незавершённые загрузки: запись встречи грузится минуты — закрытие вкладки её оборвёт, браузер переспросит.
let _uploadsInFlight = 0;
window.addEventListener("beforeunload", (e) => {
  if (_uploadsInFlight) { e.preventDefault(); e.returnValue = ""; }
});

// Один файл — XMLHttpRequest, а не fetch: только он сообщает, сколько уже отправлено (fetch хода загрузки не даёт).
function sendFile(url, fd, headers, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.setRequestHeader("X-Project-Id", String(выбранныйПроект()));
    if (onProgress) xhr.upload.addEventListener("progress", (ev) => { if (ev.lengthComputable) onProgress(ev.loaded, ev.total); });
    xhr.addEventListener("load", () => {
      let j = {};
      try { j = JSON.parse(xhr.responseText || "{}"); } catch (e) { /* не JSON — останется пустой ответ */ }
      if (xhr.status === 401 && authRequired) { showLogin("Сессия истекла — войдите снова"); reject(new Error("Требуется вход")); return; }
      if (xhr.status < 200 || xhr.status >= 300) { reject(new Error(j.detail || xhr.statusText || `ошибка ${xhr.status}`)); return; }
      resolve(j);
    });
    xhr.addEventListener("error", () => reject(new Error("связь с сервером прервалась — загрузка не завершена")));
    xhr.send(fd);
  });
}

// `options.mediaAsRecording` — файлы видео и звука уходят как запись встречи (kind=recording, на распознавание),
// остальные — как обычно (решение владельца 30.09.26: одна зона, система разбирает по типу файла).
// `options.progressId` — куда писать ход загрузки записи.
async function uploadFile(url, fileInputId, extraFields, successMsg, after, withAuth, options = {}) {
  const fileInput = document.getElementById(fileInputId);
  if (!fileInput.files.length) { toast("Выберите файл", true); return; }
  const headers = { "X-Requested-With": "erp-webapp" };
  if (!authRequired && me) headers["X-User-Id"] = String(me.id);
  const files = Array.from(fileInput.files);
  const startHash = location.hash;
  const $progress = options.progressId ? document.getElementById(options.progressId) : null;
  const mb = (n) => Math.round(n / 1024 / 1024);
  let okCount = 0;
  let autorunStarted = false;
  let recordingsQueued = 0;
  let noRecognition = false;
  const errors = [];
  const relevanceWarnings = [];
  // Файлы, которые приняты как МАТЕРИАЛЫ встречи (таблицы, презентации, pdf, картинки): сервер кладёт их
  // материалом, потому что текстом они не бывают, — человек должен увидеть, что файл не потерялся, и где
  // он теперь лежит (замечание владельца 05.10.26 про .xlsx).
  const materialNotes = [];
  _uploadsInFlight++;
  try {
    for (const file of files) {
      const recordingFile = options.mediaAsRecording && isMediaFile(file.name);
      const fd = new FormData();
      for (const [k, v] of Object.entries(extraFields)) fd.append(k, v);
      if (recordingFile) fd.append("kind", "recording");
      fd.append("file", file);
      const onProgress = recordingFile && $progress ? (loaded, total) => {
        const el = document.getElementById(options.progressId);   // страницу могли перерисовать — берём элемент заново
        if (el) el.textContent = `Загружаю запись «${file.name}»: ${Math.round(100 * loaded / total)}% (${mb(loaded)} из ${mb(total)} МБ). ` +
          "Не закрывайте вкладку до конца загрузки.";
      } : null;
      try {
        const j = await sendFile(url, fd, headers, onProgress);
        if (j.material && j.note) materialNotes.push(j.note);
        if (j.relevance_warnings && j.relevance_warnings.length) relevanceWarnings.push(`${file.name}: ${j.relevance_warnings.join(" ")}`);
        if (j.autorun) autorunStarted = true;
        if (j.queued) recordingsQueued++;
        if (j.queued && j.recognition_available === false) noRecognition = true;
        okCount++;
      } catch (e) { errors.push(`${file.name}: ${e.message}`); }
    }
  } finally {
    _uploadsInFlight--;
  }
  if (okCount) toast(errors.length ? `${successMsg} (${okCount}/${files.length})` : successMsg);
  if (materialNotes.length) toast(materialNotes.join(" "));
  if (errors.length) toast(errors.join("; "), true);
  // Автозапуск (решение 30.09.26): оператор должен узнать, что протокол уже собирается, не
  // догадываться по тишине — тот же урок, что у карточки записи вне длительности.
  if (autorunStarted) toast("Протокол собирается автоматически — откройте встречу через минуту-другую");
  // Постановка записи в очередь (30.09.26, по находке Планёрки «05», часть п.6) — тот же принцип.
  if (recordingsQueued && noRecognition) {
    toast("Запись принята. Распознать её на этом сервере сейчас нечем — администратор уведомлён; " +
      "распознается сама, как только инструменты установят. Нужно быстрее — вставьте транскрипцию текстом.", true);
  } else if (recordingsQueued) {
    toast(recordingsQueued > 1
      ? `Записи (${recordingsQueued}) поставлены в очередь на распознавание — ход виден в списке файлов встречи`
      : "Запись поставлена в очередь на распознавание — ход виден в списке файлов встречи");
  }
  // Проверка релевантности (23.09.26) — не блокирует, только предупреждает: файл уже загружен и его можно обработать,
  // но стоит перепроверить глазами, тот ли это файл (см. app/services/source_relevance.py).
  if (relevanceWarnings.length) toast("Возможно, не тот файл — " + relevanceWarnings.join(" · "), true);
  // Пока шла долгая загрузка, могли уйти на другую страницу — не выдёргиваем человека обратно.
  if (location.hash !== startHash) return;
  if (after) after(); else render();
}

// --- Команда -----------------------------------------------------------

async function renderTeam() {
  // Решение владельца 02.10.26: «команда проекта — завести — Внешняя команда — Внутренняя команда» — три вкладки в строке с
  // названием (как реестр задач; у Планёрки так же, её письмо 41): два списка и форма заведения отдельно — раньше форма
  // занимала первый экран, и список начинался ниже. Вкладка — в адресе (#team, #team/external, #team/new).
  const part = currentRouteParts()[1];
  const tab = part === "external" ? "external" : part === "new" ? "new" : "internal";
  const external = tab === "external";
  const head = `<div class="doc-head">
      <h1>Команда проекта</h1>
      <nav class="doc-tabs" role="tablist">
        <a class="doc-tab${tab === "internal" ? " doc-tab-on" : ""}" href="#team">Внутренняя команда</a>
        <a class="doc-tab${tab === "external" ? " doc-tab-on" : ""}" href="#team/external">Внешняя команда</a>
        <a class="doc-tab doc-tab-action${tab === "new" ? " doc-tab-on" : ""}" href="#team/new">Завести</a>
      </nav>
      <span class="doc-head-meta">${tab === "external" ? "заказчик, контрагент, подрядчик"
        : tab === "new" ? "новый человек в команде проекта" : "сотрудники компании"}</span>
    </div>`;
  // Владелец 14.10.26: «Завести» — окно второго слоя, как в Планёрке (a2d52c2). Пункт остаётся в строке вкладок (адрес
  // #team/new), но форма открывается окном поверх списка внутренней команды; адрес сменяется на #team без перерисовки.
  $main.innerHTML = head + `<div id="users-list" class="card empty-state">Загрузка…</div>`;
  $main.querySelector('a[href="#team/new"]')?.addEventListener("click", (e) => { e.preventDefault(); открытьЗаведениеУчастника(); });
  if (tab === "new") history.replaceState(null, "", "#team");
  await renderTeamList(external);
  if (tab === "new") открытьЗаведениеУчастника();
}

function открытьЗаведениеУчастника() {
  const ov = openModal("Новый участник команды", `
    ${identityFieldsHtml("nu")}
    ${isAdmin() ? `<div class="field-pair">
      <div class="field"><label for="new-user-email">Логин</label>
        <input type="text" id="new-user-email" placeholder="часть адреса до @" autocomplete="off" autocapitalize="none" spellcheck="false"></div>
      <div class="field"><label for="new-user-access">Права доступа в системе (не должность)</label>
        <select id="new-user-access"><option value="member">Участник — обычные права</option><option value="project_admin">Админ проекта — создаёт встречи и запускает генерацию</option>
        ${isSuperAdmin() ? `<option value="super_admin">Супер-админ — ещё и системные вкладки: мониторинг, параметры, база голосов</option>` : ""}</select></div>
    </div>` : ""}`, async (o) => {
    const v = readIdentityForm("nu");
    const problem = identityProblem(v);
    if (problem) {
      showIdentityHint("nu", problem);
      throw new Error("Запись не добавлена — посмотрите подсказку под формой");      // окно остаётся открытым
    }
    try {
      await api("/users", { method: "POST", json: {
        full_name: v.fullName,
        project_role: v.projectRole || null,
        role: v.position || null,
        department: v.department || null,
        is_external: v.external,
        organization: v.organization || null,
        name_short_reason: v.nameShortReason || null,
        email: (o.querySelector("#new-user-email")?.value || "").trim().toLowerCase() || null,
        access_role: o.querySelector("#new-user-access")?.value || "member",
      }});
    } catch (e) {
      showIdentityHint("nu", e.message);                 // сервер ответил 400/409 — та же по смыслу фраза остаётся под формой
      throw new Error("Запись не добавлена — посмотрите подсказку под формой");
    }
    toast(v.external ? "Внешний контакт заведён" : "Сотрудник заведён");
    await loadUsersForWhoAmI();
    // к списку, где появилась запись: на другой вкладке — переход, на этой же — перерисовка
    const куда = v.external ? "#team/external" : "#team";
    if (location.hash === куда) renderTeam(); else location.hash = куда;
  });
  ov.querySelector(".modal-card").classList.add("modal-wide");
  ov.querySelector("#modal-save").textContent = "Добавить";
  wireIdentityHints("nu");
  ov.querySelector("#nu-last")?.focus();
}

// «Должность и роль на проекте» — одной колонкой (владелец 02.10.26: «по контексту для нас это одно и то же»). В данных это два
// поля и остаются два: «роль на проекте» обязательна внешнему контакту с неполным именем и уходит модели при разборе встречи.
// Сверху — должность, под ней приглушённо — роль на проекте (если указана и не повторяет должность).
function teamPositionHtml(u) {
  const pos = (u.role || "").trim(), prole = (u.project_role || "").trim();
  if (!pos && !prole) return "—";
  if (!pos) return esc(prole);
  return esc(pos) + (prole && prole.toLowerCase() !== pos.toLowerCase() ? `<div class="team-prole-sub">${esc(prole)}</div>` : "");
}

// «Может вести встречу» (письмо 45 Планёрки, владелец 02.10.26). Формы правки человека нет — поэтому админу переключатель
// прямо под ФИО (строку он не удлиняет: высоту задаёт колонка входа); остальным — только пометка, если отметка стоит.
// Владелец 03.10.26: признак «может вести встречу» со страницы убран — ведущего определяет запись («кто больше всего говорит»).
function teamLeadHtml(u, admin) { return ""; }

async function renderTeamList(external) {
  const users = (await api("/users")).filter(u => !!u.is_external === external);
  const admin = isAdmin();
  const superAdmin = isSuperAdmin();
  const ROLE_LABEL = { super_admin: "Супер-админ", project_admin: "Админ", member: "Участник" };
  // Роль доступа (решение 22.09.26, F12): менять роль может только администратор; назначать/снимать
  // «Супер-админ» — только сам супер-админ (сервер проверяет то же самое, здесь — чтобы не звать зря).
  const roleCell = (u) => {
    const badge = `<span class="badge ${u.access_role === "member" ? "badge-neutral" : "badge-accent"}">${ROLE_LABEL[u.access_role] || u.access_role}</span>`;
    if (!admin || u.id === (me && me.id) || (u.access_role === "super_admin" && !superAdmin)) return badge;
    // Назначать администратора — только суперадмин (решение владелицы 18.10.2026, перенос 19.10.2026); внешним — только
    // «участник». Админу проекта поле выбора остаётся там, где он может снять роль администратора.
    if (u.is_external || (!superAdmin && u.access_role !== "project_admin")) return badge;
    // Роль показывается один раз (02.10.26): рядом со значком стояло то же слово в поле выбора — двойной текст в ячейке.
    return `<select class="team-role" data-id="${u.id}" aria-label="Права доступа">
      ${["member", "project_admin", ...(superAdmin ? ["super_admin"] : [])].map(r =>   // админу проекта «Супер-админ» не показывается (владелец 14.10.26)
        `<option value="${r}" ${u.access_role === r ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}
      </select>`;
  };
  // Вход (только админу): логин, состояние и действия. Пароли никто не видит и не вводит за
  // другого: сервер генерирует временный пароль и показывает его один раз (решение 19.09.26).
  // 19.10.2026 (вход по паролю, перенос из Планёрки): логин видит только суперадмин — сервер другим его не отдаёт; участник
  // входит по общему паролю — «Выдать доступ» и «Задать пароль» у него нет, состояние — «логин привязан / не привязан»;
  // личный пароль администратору выдаёт только суперадмин; внешним доступ не выдаётся никогда. Администратору в колонке
  // остаются состояние и «Отключить / Включить».
  const accessCell = (u) => {
    if (!admin) return "";
    const общий = ["member", "director"].includes(u.access_role);
    // «Выдать доступ» / «Сбросить пароль» — суперадмину, для администраторов и других суперадминов, кроме своей строки: свой
    // пароль — «Сменить пароль» (как в Планёрке, 19.10.2026)
    const ключи = superAdmin && !u.is_external && !общий && u.id !== (me && me.id);
    const kind = !u.is_active ? "off" : u.has_access ? "ok" : "none";
    const tip = !u.is_active ? "Учётная запись отключена" : u.is_external ? "Внешним участникам доступ не выдаётся"
      : общий ? (u.has_access ? "Логин привязан — вход по общему паролю" : "Логин не привязан")
      : u.has_access ? `Есть вход${u.login ? ": " + u.login : ""}` : "Нет входа";
    const state = !u.is_active ? '<span class="badge badge-neutral">Отключён</span>'
      : u.is_external ? '<span class="badge badge-neutral">Без доступа</span>'
      : общий ? (u.has_access ? '<span class="badge badge-accent">Логин привязан</span>' : '<span class="badge badge-neutral">Логин не привязан</span>')
      : u.has_access ? '<span class="badge badge-accent">Есть вход</span>' : '<span class="badge badge-neutral">Нет входа</span>';
    return `<td class="access-col">
      <span class="access-compact acc-${kind}" title="${esc(tip)}"><svg class="key-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/></svg></span>
      <div class="access-full"><div class="access-state">${state}${u.login ? ` <span class="page-sub" style="margin:0">${esc(u.login)}</span>` : ""}</div>
      ${/* Одно действие — один столбец во всех строках (владелец 02.10.26, письмо 42 Планёрки): у кнопок одинаковая ширина,
           обязательные — первыми, необязательная «Задать пароль» — последней; на месте «Отключить» у своей записи — невидимый
           двойник. Раньше двойник «Задать пароль» стоял первым и выталкивал остальные вправо и на вторую строку. */ ""}
      <div class="access-actions">
        ${ключи ? `<button class="btn-sm team-grant" data-id="${u.id}" data-has="${u.has_access ? 1 : 0}">${u.has_access ? "Сбросить пароль" : "Выдать доступ"}</button>` : ""}
        ${u.id === (me && me.id) ? `<button class="btn-sm btn-twin" tabindex="-1" aria-hidden="true">Отключить</button>`
          : `<button class="btn-sm team-active" data-id="${u.id}" data-active="${u.is_active ? 1 : 0}">${u.is_active ? "Отключить" : "Включить"}</button>`}
        ${u.id === (me && me.id) && !общий && !u.is_external && u.login ? `<button class="btn-sm team-setpwd" data-id="${u.id}">Задать пароль</button>` : ""}
      </div></div></td>`;
  };
  // Колонка входа свёрнута по умолчанию (запрос пользователя 19.09.26): в заголовке значок ключа, по клику — разворачивается.
  const accessExpanded = localStorage.getItem("teamAccessExpanded") === "1";
  document.getElementById("users-list").outerHTML = users.length
    ? `<div id="users-list" class="card card-output${admin && !accessExpanded ? " access-collapsed" : ""}"><div class="table-scroll"><table class="team-table"><thead><tr><th class="team-name">ФИО</th><th class="team-pos" title="Должность и роль на проекте">Должность и роль</th><th class="team-dept">${external ? "Организация" : "Отдел"}</th><th class="team-access">Доступ</th>${admin ? `<th class="c-act" aria-label="Изменить"></th><th class="c-del" aria-label="Удалить"></th><th class="access-col"><button type="button" class="access-toggle" id="access-toggle" aria-expanded="${accessExpanded}" title="${accessExpanded ? "Свернуть колонку входа" : "Показать вход по логину и паролю"}"><svg class="key-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3M14 9l2 2"/></svg><span class="access-toggle-label">Вход по логину и паролю</span><span class="access-chevron" aria-hidden="true">›</span></button>${superAdmin ? " " + подсказкаПаролейHtml() : ""}</th>` : ""}</tr></thead><tbody>
        ${users.map(u => `<tr data-user-id="${u.id}"><td><div class="team-cap-name">${esc(u.full_name)}${u.is_confirmed === false ? ` <span class="badge badge-neutral" title="Названа в Протоколе не полностью — уточните ФИО на странице «Конфликты»">Не подтверждён</span>` : ""}${teamLeadHtml(u, admin)}</div></td><td class="team-pos"><div class="team-cap-pos">${teamPositionHtml(u)}</div></td><td><div class="team-cap-dept">${esc(external ? ([u.organization, u.department].filter(Boolean).join(" · ") || "—") : (u.department || "—"))}</div></td>
          <td class="team-access">${roleCell(u)}</td>${admin ? `<td class="c-act"><button class="btn-icon user-edit" data-id="${u.id}" title="Изменить: опечатка, дополнить сведения" aria-label="Изменить">&#9998;</button>${/* «Подтвердить» у неподтверждённой записи, как в Планёрке (решение владелицы 24.10.2026, вариант «а») */ u.is_confirmed === false ? `<button class="btn-sm user-confirm" data-id="${u.id}" title="Отметить, что это реальный человек: запись начнёт использоваться, вопрос о ней в «Конфликтах» закроется">Подтвердить</button>` : ""}</td>
          <td class="c-del danger-action-cell"><button class="btn-icon danger-action user-delete" data-id="${u.id}" title="Удалить" aria-label="Удалить">&#128465;</button></td>` : ""}${accessCell(u)}</tr>`).join("")}
      </tbody></table></div></div>`
    : `<div id="users-list" class="card empty-state">${external ? "Внешних контактов пока нет." : "Сотрудников пока нет."}</div>`;
  collapseLongTable(document.querySelector("#users-list tbody"), LONG_LIST_LIMIT, "users-list");
  if (admin) {
    wireTeamEditButtons(users);
    wireTeamConfirmButtons(users);
    wireTeamAccessButtons(users);
    wireTeamDeleteButtons(users);
    const $toggle = document.getElementById("access-toggle");
    if ($toggle) $toggle.addEventListener("click", () => {
      const collapsed = document.getElementById("users-list").classList.toggle("access-collapsed");
      localStorage.setItem("teamAccessExpanded", collapsed ? "0" : "1");
      $toggle.setAttribute("aria-expanded", String(!collapsed));
      $toggle.title = collapsed ? "Показать вход по логину и паролю" : "Свернуть колонку входа";
    });
  }
}

// Переключение режима входа (решение 19.09.26): кнопка в левом меню, видна только администратору.
// Тестовый — вход по ФИО без пароля; рабочий — по логину и паролю. По умолчанию тестовый, до продуктива.
async function toggleAuthMode() {
  const turnOn = !authRequired;
  const question = turnOn
    ? "Включить рабочий режим? После включения все, включая вас, будут входить по логину и паролю (выбор по ФИО отключится). Убедитесь, что у вас самих задан пароль — иначе вы не сможете войти."
    : "Переключить на тестовый режим? Пользователя снова выбирают по ФИО, пароль не нужен. В продуктиве так нельзя.";
  if (!(await confirmDialog(question, turnOn ? "Включить рабочий режим" : "Включить тестовый режим"))) return;
  const body = { auth_required: turnOn };
  if (!turnOn && authRequired) {
    // Выключение входа в рабочем режиме требует собственного пароля администратора (защита от чужой сессии).
    const pwd = await passwordDialog("Чтобы выключить вход, подтвердите действие своим паролем.", "Подтвердить");
    if (!pwd) return;
    body.current_password = pwd;
  }
  try {
    await api("/auth/mode", { method: "POST", json: body });
    location.reload();
  } catch (e) { toast(e.message, true); }
}

// Кнопка переключения в левом меню видна только супер-администратору (решение 22.09.26, F12 — переключатель
// входа того же рода «сопровождение», что и «Конфликты», не работа администратора проекта).
function updateModeSwitch() {
  const show = isSuperAdmin();
  document.getElementById("mode-switch-testing").hidden = !show;
  document.getElementById("mode-switch-auth").hidden = !show;
}
document.getElementById("mode-switch-testing")?.addEventListener("click", toggleAuthMode);
document.getElementById("mode-switch-auth")?.addEventListener("click", toggleAuthMode);

function showCredentialsDialog(name, login, tempPassword, заголовок = "Доступ выдан") {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-card card">
      <h2 style="margin-top:0">${esc(заголовок)} — ${esc(name)}</h2>
      <div class="page-sub" style="margin-bottom:4px">Логин</div>
      <div class="cred-box">${esc(login)}</div>
      <div class="page-sub" style="margin-bottom:4px">Временный пароль — показан один раз, действует 24 часа</div>
      <div class="cred-box">${esc(tempPassword)}</div>
      <div class="page-sub" style="margin-top:8px">Передайте пароль человеку лично. При первом входе он обязан заменить его своим. Через 24 часа временный пароль перестанет действовать — понадобится новый сброс. Позже посмотреть его будет нельзя: в базе хранится только хэш.</div>
      <div class="hstack" style="justify-content:flex-end; margin-top:12px">
        <button class="btn-sm" id="cred-copy">Скопировать</button>
        <button class="btn-primary btn-sm" id="cred-done">Готово</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector("#cred-copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(`Логин: ${login}\nВременный пароль: ${tempPassword}`); toast("Скопировано"); }
    catch (e) { toast("Не удалось скопировать — выделите и скопируйте вручную", true); }
  });
  overlay.querySelector("#cred-done").addEventListener("click", () => overlay.remove());
}

// Правка записи «Команды» (указание владельца 05.10.26): опечатка в фамилии, дописать должность,
// отдел или роль на проекте. Доступна админу и супер-админу — сервер другим ролям правку не разрешает
// (`PATCH /users/{id}`), поэтому и карандаш рисуется только им. Права доступа здесь не меняются: для
// них в таблице свои средства, и правило «последнего администратора не понизить» живёт там же.
function wireTeamDeleteButtons(users) {
  // Удаление записи «Команды» (владелец 07.10.26: «добавить пиктограмму удалить — как в Планёрке»).
  // Спрашиваем подтверждение: действие необратимое, и вместе с записью снимаются привязки задач
  // (ответственный остаётся текстом) — сервер об этом отдельно предупреждает, если удалить нельзя.
  document.querySelectorAll(".user-delete").forEach(btn => btn.addEventListener("click", async () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    if (!u) return;
    if (!(await confirmDialog(`Удалить «${u.full_name}» из «Команды»? Это действие необратимо: в задачах `
                              + `ответственный останется текстом, а вход и привязки снимаются.`, "Удалить"))) return;
    try {
      await api(`/users/${u.id}`, { method: "DELETE" });
      toast(`Запись «${u.full_name}» удалена`);
      await loadUsersForWhoAmI();
      renderTeam();
    } catch (e) { toast(e.message, true); }
  }));
}

function wireTeamEditButtons(users) {
  document.querySelectorAll(".user-edit").forEach(btn => btn.addEventListener("click", () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    if (!u) return;
    const ov = openModal("Изменить запись: " + u.full_name, `
      <div class="page-sub" style="margin-bottom:8px">Поправьте опечатку или дополните сведения.
        Права доступа и вход — в самой таблице: они живут по своим правилам.</div>
      ${identityFieldsHtml("usr", { ...splitPersonName(u.full_name, null), projectRole: u.project_role,
                                    position: u.role, department: u.department,
                                    organization: u.organization, external: !!u.is_external,
                                    nameShortReason: u.name_short_reason })}
      ${isSuperAdmin() ? `<div class="field"><label for="modal-login">Логин</label><input type="text" id="modal-login" value="${esc(u.login || "")}" placeholder="часть почты до «@»; пусто — отвязать" autocomplete="off" autocapitalize="none" spellcheck="false">
        <div class="page-sub">Логин видит и меняет только суперадмин (решение владелицы 18.10.2026). Пустое значение отвязывает логин:
          человек снова появится в списке «Первый вход», его сессии завершатся.</div></div>` : ""}
    `, async (o) => {
      const v = readIdentityForm("usr");
      const $логин = o.querySelector("#modal-login");
      const логинПравка = $логин && $логин.value.trim() !== (u.login || "") ? { login: $логин.value.trim() } : {};
      // Неподтверждённую запись сохраняют и неполной — сервер проверяет правило только у подтверждённой (`_patch_user`).
      // Раньше форма требовала полного правила и здесь: сотрудника, ошибочно записанного внешним, нельзя было перевести
      // во внутреннюю команду, пока не дописано имя или роль (15.10.26). Подтверждают — в «Конфликтах», там правило в силе.
      const problem = u.is_confirmed === false ? null : identityProblem(v);
      if (problem) { showIdentityHint("usr", problem); throw new Error(problem); }
      await api(`/users/${u.id}`, { method: "PATCH", json: {
        full_name: v.fullName, project_role: v.projectRole || null, role: v.position || null,
        department: v.department || null, organization: v.organization || null, is_external: v.external, ...логинПравка,
        ...(v.nameShortReason ? { name_short_reason: v.nameShortReason } : {}),
      }});
      await loadUsersForWhoAmI();
      // Перевод между командами уносил строку с открытой вкладки молча — выглядело как «запись пропала». Теперь экран
      // переходит на вкладку его команды и говорит, куда перенесён (15.10.26).
      if (v.external !== !!u.is_external) {
        toast(`Запись сохранена. «${v.fullName}» перенесён ${v.external ? "во «Внешнюю команду»" : "во «Внутреннюю команду»"}`);
        location.hash = v.external ? "team/external" : "team";
      } else {
        toast("Запись сохранена");
        renderTeam();
      }
    });
    const _save = ov.querySelector("#modal-save");
    if (_save) _save.textContent = "Сохранить";
    ov.querySelector(".modal-card").classList.add("modal-wide");   // те же поля, что в «Новом участнике» (14.10.26)
    wireIdentityHints("usr");
    ov.querySelector("#usr-last").focus();
  }));
}

// Кнопка «Подтвердить» в строке неподтверждённой записи (решение владелицы 24.10.2026, вариант «а»; как «Подтвердить» в
// «Команде» Планёрки). «Подтверждён» — только человеком: засев и общая «Команда» больше не подтверждают сами, поэтому путь
// подтверждения нужен прямо в таблице, а не только в «Конфликтах». Окно в один шаг: те же поля, что у правки, и то же
// правило — внешнему одним словом без инициала нужно «да, известно только одно слово» с причиной; внутренних и внешних —
// одинаково. Сервер пишет источник подтверждения «экран», закрывает карточку о человеке и ставит ждавшие задачи при опоре.
function wireTeamConfirmButtons(users) {
  document.querySelectorAll(".user-confirm").forEach(btn => btn.addEventListener("click", () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    if (!u) return;
    const ov = openModal("Подтвердить: " + u.full_name, `
      <div class="page-sub" style="margin-bottom:8px">Проверьте, кто это, и подтвердите: до подтверждения запись не используется
        нигде — ни в подсказках, ни исполнителем задач.</div>
      ${identityFieldsHtml("cnf", { ...splitPersonName(u.full_name, null), projectRole: u.project_role,
                                    position: u.role, department: u.department,
                                    organization: u.organization, external: !!u.is_external,
                                    nameShortReason: u.name_short_reason })}
    `, async () => {
      const v = readIdentityForm("cnf");
      const problem = identityProblem(v);
      if (problem) { showIdentityHint("cnf", problem); throw new Error(problem); }
      await api(`/users/${u.id}`, { method: "PATCH", json: {
        full_name: v.fullName, project_role: v.projectRole || null, role: v.position || null,
        department: v.department || null, organization: v.organization || null, is_external: v.external,
        is_confirmed: true, ...(v.nameShortReason ? { name_short_reason: v.nameShortReason } : {}),
      }});
      await loadUsersForWhoAmI();
      toast("Запись подтверждена — вопрос о ней в «Конфликтах» закрыт");
      if (v.external !== !!u.is_external) location.hash = v.external ? "team/external" : "team";
      else renderTeam();
    });
    const _save = ov.querySelector("#modal-save");
    if (_save) _save.textContent = "Подтвердить";
    ov.querySelector(".modal-card").classList.add("modal-wide");
    wireIdentityHints("cnf");
    ov.querySelector("#cnf-last").focus();
  }));
}

function wireTeamAccessButtons(users) {
  document.querySelectorAll(".team-grant").forEach(btn => btn.addEventListener("click", async () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    const has = btn.dataset.has === "1";
    // Решение владелицы 19.10.2026, вариант Б «временный пароль»: «Выдать доступ» и «Сбросить пароль» показывают суперадмину
    // случайный временный пароль один раз (действует 24 часа, передать лично); при входе с ним — обязательная смена на свой.
    // Кнопки — только у суперадмина и только для администраторов. Сброс — та же ручка и тексты, что в Планёрке.
    const grant = async (email) => {
      const r = await api(`/users/${u.id}/access`, { method: "POST", json: { email: email || null } });
      showCredentialsDialog(u.full_name, r.login, r.temporary_password || r.temp_password);
      await loadUsersForWhoAmI();
      renderTeam();
    };
    if (has) {
      if (!(await confirmDialog(`Сбросить личный пароль — ${u.full_name}?\nЛогин останется прежним. Будет показан временный `
        + "пароль — передайте его лично; при следующем входе человек задаст свой. Его открытые сессии завершатся.",
        "Сбросить пароль"))) return;
      try {
        const res = await api("/auth/reset-password", { method: "POST", json: { user_id: u.id } });
        showCredentialsDialog(u.full_name, res.login, res.temporary_password, "Пароль сброшен");
      } catch (e) { toast(e.message, true); }
      return;
    }
    openModal("Выдать доступ", `
      <div class="page-sub" style="margin-bottom:8px">${esc(u.full_name)}</div>
      <div class="field"><label>Логин — часть адреса до @</label>
        <input type="text" id="grant-email" autocomplete="off" autocapitalize="none" spellcheck="false" value="${esc(u.email || "")}" placeholder="например ipetrukevich"></div>
    `, async (ov) => { await grant(ov.querySelector("#grant-email").value.trim()); }).querySelector("#grant-email").focus();
  }));
  // Форма ввода пароля (только администратор): свой пароль или пароль другого человека. Пароль вводит сам администратор
  // в этом окне; сервер проверяет требования и хранит только хэш.
  document.querySelectorAll(".team-setpwd").forEach(btn => btn.addEventListener("click", () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    const self = me && u.id === me.id;
    if (!self) return;   // личный пароль администратор задаёт только себе (19.10.2026)
    const ov = openModal("Задать свой пароль", `
      <div class="page-sub" style="margin-bottom:8px">${esc(u.full_name)}${u.login ? " — " + esc(u.login) : ""}</div>
      <div class="field"><label>Новый пароль <span class="req">*</span></label>
        <input type="password" id="setpwd-1" autocomplete="new-password"></div>
      <div class="field"><label>Повторите пароль <span class="req">*</span></label>
        <input type="password" id="setpwd-2" autocomplete="new-password"></div>
      <div class="field-hint">Не короче 10 символов, не только цифры, не совпадает с логином.</div>
    `, async (o) => {
      const a = o.querySelector("#setpwd-1").value, b = o.querySelector("#setpwd-2").value;
      if (a.length < 10) throw new Error("Пароль слишком короткий — минимум 10 символов");
      if (a !== b) throw new Error("Пароли не совпадают — введите одинаково в обоих полях");
      await api(`/users/${u.id}/password`, { method: "POST", json: { password: a } });
      toast("Ваш пароль сохранён");
    });
    ov.querySelector("#setpwd-1").focus();
  }));
  document.querySelectorAll(".team-active").forEach(btn => btn.addEventListener("click", async () => {
    const u = users.find(x => String(x.id) === btn.dataset.id);
    const activate = btn.dataset.active !== "1";
    // Письмо 44 Планёрки (02.10.26): у отключения есть невидимое на этом экране следствие — человек выпадает из сопоставления
    // имён при разборе встреч. Узнают об этом через неделю на чужом протоколе, поэтому говорим до нажатия.
    if (!activate && !(await confirmDialog(`Отключить «${u.full_name}»? Вход станет невозможен, текущие сессии завершатся. `
      + "Человека перестанут предлагать ответственным при разборе встреч. Вернуть — кнопкой «Включить» в этой же строке.", "Отключить"))) return;
    try {
      await api(`/users/${u.id}/active`, { method: "POST", json: { is_active: activate } });
      toast(activate ? "Учётная запись включена" : "Учётная запись отключена");
      await loadUsersForWhoAmI();
      renderTeam();
    } catch (e) { toast(e.message, true); }
  }));
  // Смена роли доступа (решение 22.09.26, F12) — сервер сам проверяет, что супер-админа назначает и
  // снимает только супер-админ и что нельзя понизить последнего активного носителя роли.
  // Письмо 43 Планёрки (02.10.26, «единообразие»): список в строке — самый тихий способ сменить самое дорогое на экране,
  // права. Смена уходит на сервер через DONE_UNDO_SECONDS: строка подсвечена, рядом — «Отменить» (тот же вид, что у
  // «Выполнено» в реестре). Отмена возвращает список к прежнему значению, запрос не уходит, следа в журнале нет. Ушли со
  // страницы до конца отсчёта — смена всё равно уходит: выбор осознанный, уход не отказ.
  document.querySelectorAll(".team-lead").forEach(box => box.addEventListener("change", async () => {
    try {
      await api(`/users/${box.dataset.id}`, { method: "PATCH", json: { leads_meetings: box.checked } });
      toast(box.checked ? "Отмечено: может вести встречу" : "Отметка «может вести встречу» снята");
    } catch (e) { box.checked = !box.checked; toast(e.message, true); }
  }));
  document.querySelectorAll(".team-role").forEach(sel => {
    sel.dataset.prev = sel.value;
    sel.addEventListener("change", () => startDelayedRoleChange(sel, users));
  });
}

// --- Поиск ---------------------------------------------------------------

// Гарантированный доступ (решение 11.09.26) — пять кнопок, каждая отдаёт
// уже сгенерированный и верифицированный документ напрямую, без риска
// «не найти» или получить случайный фрагмент, как может быть с поиском
// ниже. Открыто всем ролям.
// Отдельной страницы «Данные проекта» больше нет (владелец 07.10.26: «эта же информация дублируется на
// вкладке Статус проекта, дублирование не нужно»). Ряд документов оттуда повторял канонические места:
// «Сводка» и «Дорожная карта» — вкладки «Статус проекта», «Протокол» и «План» — страница встречи,
// «Активные» и «Завершённые» задачи — «Реестр задач по проекту». Уникальным там был только поиск — он
// переехал вкладкой «Поиск» на «Статус проекта».
//
// Старые адреса не ломаем: #search и #search/find/<запрос> перенаправляются на #status/search, чтобы
// закладки и ссылки из писем продолжали работать.
function renderSearch(rest) {
  const raw = rest[0] === "find" ? rest[1] : rest[0];
  let q = "";
  try { q = raw ? decodeURIComponent(raw) : ""; } catch (e) { q = raw || ""; }   // битая %-последовательность в адресе не должна ломать переход
  q = q.trim().slice(0, 300);
  location.replace(q ? `#status/search/find/${encodeURIComponent(q)}` : "#status/search");
}



async function renderSearchTab(q) {
  const data = await api("/search?q=" + encodeURIComponent(q));
  // Решение 17.09.26 (жалоба) — подсказки вида «... (ФИО)»/«... ...»
  // удобны как подпись на кнопке (поясняет, что дописать), но если
  // вставить в строку поиска дословно, скобки/многоточие остаются в
  // запросе и путают, что именно печатать дальше. В сам инпут кладём
  // очищенную версию (без скобок и их содержимого, без хвостового
  // многоточия), а подпись на кнопке — как была, без изменений.
  const chipSearchText = (label) => label
    .replace(/\s*\([^)]*\)\s*/g, " ")
    .replace(/\.{2,}\s*$/, "")
    .trim();
  // «Сбросить поиск» — только когда есть что сбрасывать (реальный
  // запрос уже введён), отдельный нейтральный стиль (.btn-ghost), чтобы
  // не путался с подсказками-чипами (решение 17.09.26).
  // Решение 19.09.26 — стиль «как уведомление» (образец Planerka): тот же тон
  // предупреждения, что у плашки «ничего не найдено», в паре с ней.
  // 15.10.26 (владелец через Планёрку cf0f764 / 1a8834a / 384ede0: «кнопку сбросить поиск перенести ближе к окну ввода…
  // сделай акцент по цвету, иначе не видно… и для ERP»): «Сбросить» — в строке поиска справа от поля, цветом акцента;
  // прежде «✕ Сбросить поиск» стояла строкой ниже, среди подсказок. Видна, только когда есть что сбрасывать.
  const сброс = document.getElementById("search-reset");
  if (сброс) сброс.hidden = !q;
  document.getElementById("search-suggestions").innerHTML = data.suggested_queries.map(
    s => `<span class="chip" role="button" tabindex="0" data-q="${esc(chipSearchText(s))}">${esc(s)}</span>`
  ).join("");
  // Решение 19.09.26 — подсказка сама по себе не запрос: слова подсказки системные.
  // Клик только подставляет их в поле и ставит курсор в конец — поиск начнётся,
  // когда пользователь допишет уточнение (например, ФИО) и нажмёт Enter.
  $main.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    const inp = document.getElementById("search-input");
    inp.value = c.dataset.q + " ";
    growSearchInput(inp);
    inp.focus();
    inp.setSelectionRange(inp.value.length, inp.value.length);
    document.getElementById("search-detail-hint").hidden = false;
  }));
  document.getElementById("search-reset")?.addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    navigate("search/find");
  });

  // Плашки маркеров «Искали: …» (решение владелицы 17.10.2026): крестик или выбор проекта — тот же поиск без плашки
  const искатьБезПлашки = (qq) => navigate(qq ? "search/find/" + encodeURIComponent(qq) : "search/find");
  показатьПлашкиМаркеров(document.getElementById("search-markers"), data.markers, искатьБезПлашки);
  if (data.deep) глубокийПоиск(q, document.getElementById("search-results"), (d) => {
    показатьПлашкиМаркеров(document.getElementById("search-markers"), d.markers, искатьБезПлашки);
    renderSearchResults(d.results, q, false, null, null, d.message);
  });
  else renderSearchResults(data.results, q, data.needs_detail, data.problem, null, data.message);

  // Поле поиска — многострочное с автопереносом (владелец 02.10.26: «строку для ввода расширь и сделай автоматический
  // перенос на новую строку при достижении границы»): растёт вниз вместе с текстом до пяти строк, дальше — прокрутка.
  // Enter — искать (как раньше); переносы при поиске заменяются пробелом.
  const input = document.getElementById("search-input");
  input.addEventListener("input", () => growSearchInput(input));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSearch(); } });
  document.getElementById("search-submit-btn")?.addEventListener("click", doSearch);
  growSearchInput(input);
  function doSearch() { navigate("search/find/" + encodeURIComponent(input.value.replace(/\s+/g, " ").trim().slice(0, 300))); }
}

function growSearchInput(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight + 2, 140) + "px";
  el.style.overflowY = el.scrollHeight + 2 > 140 ? "auto" : "hidden";
}

function renderSearchResults(results, q, needsDetail, problem, el = null, message = null) {
  el = el || document.getElementById("search-results");
  if (needsDetail) {
    el.innerHTML = problem      // несуществующая дата или «№0» (02.10.26)
      ? `<div class="search-empty"><b>${esc(problem)}.</b> Поправьте запрос и нажмите Enter.</div>`
      : `<div class="search-empty"><b>Уточните вопрос.</b> Это только начало запроса: допишите, что именно искать (например, ФИО ответственного или тему), и нажмите Enter.</div>`;
    return;
  }
  if (!results.length) {
    // Запрос введён, а не нашлось ни в документах, ни в расшифровках — этап 3 двухэтапного поиска (решение владелицы
    // 17.10.2026): одна фраза «По запросу информации нет», без технических пометок. Запроса нет — бледная подсказка.
    el.innerHTML = (q || "").trim()
      ? `<div class="search-empty">${esc(message || ПОИСК_ПУСТО)}</div>`
      : `<div class="empty-state">Введите запрос или выберите подсказку выше</div>`;
    return;
  }
  const typeLabel = { meeting_minutes: "Протокол встречи", plan: "План встречи", meeting_material: "Материал", task: "Задача", meeting_source: "Источник",
    agreement: "Договорённость" };
  el.innerHTML = results.map(r => r.source_type === "transcript_hit" ? находкаИзЗаписиHtml(r) : `
    <div class="card card-output">
      <div class="snippet-source">${esc(r.kind_label || typeLabel[r.source_type] || r.source_type)}${r.meeting_date && r.meeting_date !== "0000-00-00" ? " · " + esc(fmtRuDate(r.meeting_date)) : ""}
        ${r.is_current === false ? ' · <span class="badge badge-neutral">архив</span>' : ""}
        ${r.places > 1 ? ` · ещё ${r.places - 1} ${словоМест(r.places - 1)} в документе` : ""}
        ${r.meeting_id ? ` · <a class="snippet-open" href="#meetings/${r.meeting_id}${r.source_type === "meeting_minutes" ? "/protocol" : ""}">${r.source_type === "meeting_minutes" ? "открыть протокол" : "открыть встречу"}</a>` : ""}
        ${/* ссылки «история проекта» нет с 25.10.2026: вкладка «История проектов» убрана в обеих системах */ ""}</div>
      <div class="snippet-text">${отрывокНаходкиHtml(r)}</div>
    </div>`).join("");
  collapseLongCardList(el);
}
// Отрывок находки с отметками совпавших слов (дефект владелицы 20.10.2026): сервер режет отрывок вокруг лучшего места и
// отдаёт его кусками `snippet_parts`, совпавшие слова — `mark`, как в находках из записи. Функция совпадает в обеих системах.
function отрывокНаходкиHtml(r) {
  if (!Array.isArray(r.snippet_parts) || !r.snippet_parts.length) return esc(r.snippet);
  return r.snippet_parts.map(p => p.mark ? `<mark class="zapis-mark">${esc(p.text)}</mark>` : esc(p.text)).join("");
}
function словоМест(n) {
  if (n % 10 === 1 && n % 100 !== 11) return "место";
  if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return "места";
  return "мест";
}

// ---- Находка из записи: этап 2 двухэтапного поиска (решение владелицы 17.10.2026) ----
// Вид — как у протокола и одинаковый в ERP и Планёрке (различается только акцентный цвет). Всё содержимое собирает сервер
// дословно, без модели: шапка, говорящий (ФИО или «участник не определён»), время в записи, цитата с соседними репликами,
// найденное выделено; здесь только разметка. Функция совпадает в обеих системах.
const ПОИСК_ПУСТО = "По запросу информации нет";
const ПОИСК_ГЛУБОКИЙ = "Идёт глубокий поиск, подождите, пожалуйста";
// Ответы владелицы 17.10.2026 («полный круг»): лучшие находки — пересказ моделью сборки протокола, под ним свёрнутая
// дословная цитата «Как звучало в записи»; без пересказа (модель не назначена, вызов не удался, пересказ отброшен
// проверкой) — шапка и цитата развёрнутой; остальные находки — строкой шапки со ссылками. Технических пометок нет.
function находкаИзЗаписиHtml(r) {
  const куски = (parts) => (parts || []).map(p => p.mark ? `<mark class="zapis-mark">${esc(p.text)}</mark>` : esc(p.text)).join("");
  const h = r.header || {}, l = r.links || {};
  const ссылки = `<a href="${esc(l.meeting)}">${esc(l.meeting_label)}</a> · `
    + (l.protocol ? `<a href="${esc(l.protocol)}">открыть протокол</a>` : `<span>протокола пока нет</span>`);
  const шапка = `${esc(h.title)} ${esc(h.date)} · ${esc(h.project)}`;
  const кто = `${esc(r.speaker)}${r.time ? " · " + esc(r.time) : ""}`;
  if (r.brief) {
    return `<div class="card card-output zapis-card zapis-brief"><div class="zapis-head">${шапка}</div>
      <div class="zapis-meta">Из записи встречи · ${кто} · ${ссылки}</div></div>`;
  }
  const строки = (r.replicas || []).map(x => `<div class="zapis-line${x.hit ? " zapis-hit" : ""}">
      <span class="zapis-time">${esc(x.time || "")}</span><span class="zapis-who">${esc(x.speaker)}</span><span class="zapis-text">${куски(x.parts)}</span></div>`).join("");
  const цитата = `<div class="zapis-quote">${строки}</div>`;
  const тело = r.retell
    ? `<p class="zapis-retell">${esc(r.retell)}</p>
       <details class="zapis-details"${r.quote_collapsed ? "" : " open"}><summary>${esc(r.quote_title || "Как звучало в записи")}</summary>${цитата}</details>`
    : цитата;
  return `<div class="card card-output zapis-card"><div class="doc-content">
      <div class="zapis-head">${шапка}</div>
      <div class="zapis-meta">Из записи встречи · ${кто}</div>
      ${тело}
      <div class="zapis-links">${ссылки}</div>
    </div></div>`;
}
// Этап 2 двухэтапного поиска: пока ищется в расшифровках и пишется пересказ — «Идёт глубокий поиск, подождите,
// пожалуйста»; ответ — находки (этап 2) или «По запросу информации нет» (этап 3). Устаревший ответ (запрос сменили)
// не рисуется. Функция совпадает в обеих системах.
function глубокийПоиск(q, el, нарисовать) {
  el.innerHTML = `<div class="search-empty zapis-wait" role="status">${esc(ПОИСК_ГЛУБОКИЙ)}</div>`;
  el.dataset.deepQ = q;
  const свой = () => el.isConnected && el.dataset.deepQ === q;
  api("/search/deep?q=" + encodeURIComponent(q))
    .then(d => { if (свой()) нарисовать(d); })
    .catch(() => { if (свой()) el.innerHTML = `<div class="search-empty">Поиск не завершился. Попробуйте ещё раз.</div>`; });
}

// ---- Маркеры времени, проекта и ФИО в строке поиска (решение владелицы 17.10.2026) ----
// Разбор строки — на сервере (`query_markers.py`, близнец двух систем); здесь только подсказка у значка «i» и плашки
// «Искали: …» над итогом. Подсказка — та же строка, что `query_markers.ПОДСКАЗКА` (сторож в тестах). Крестик на плашке
// повторяет поиск без неё; у неоднозначного проекта — выбор из справочника, а не тихая подстановка. Функции совпадают
// в обеих системах.
const ПОДСКАЗКА_МАРКЕРОВ = "Кроме слов, в одной строке можно указать время, проект и ФИО. Время: «весной», «в сентябре», «в начале октября», «примерно два месяца назад», «на прошлой неделе», «вчера», «12.09.2026», «с 01.09 по 15.09». Проект: «для проекта …», «по проекту …», «проект …» — название из справочника проектов. ФИО — фамилия из «Команды». Например: «договор поставки весной для проекта Аккую», «Иванов про сроки примерно два месяца назад», «склад в сентябре по проекту …».";
function плашкиМаркеровHtml(m) {
  if (!m || !(m.chips || []).length) return "";
  const плашка = (c) => {
    if (c.kind === "words") return `<span class="qm-chip qm-words"><span class="qm-label">${esc(c.label)}</span></span>`;
    const заметка = c.relaxed ? `<span class="qm-note">снято: в это время не найдено</span>`
      : c.note ? `<span class="qm-note">${esc(c.note)}</span>` : "";
    const выбор = (c.choices || []).map(x =>
      `<button type="button" class="qm-choice" data-qm-q="${esc(x.query)}">${esc(x.label)}</button>`).join("");
    const классы = ["qm-chip", "qm-" + c.kind, c.relaxed ? "qm-relaxed" : "", c.similar ? "qm-similar" : ""].filter(Boolean).join(" ");
    return `<span class="${esc(классы)}"><span class="qm-label">${esc(c.label)}</span>${заметка}${выбор}`
      + `<button type="button" class="qm-x" data-qm-q="${esc(c.without || "")}" aria-label="Снять: ${esc(c.label)}" title="Снять и искать без этого">×</button></span>`;
  };
  return `<div class="qm-row" role="group" aria-label="Распознано в строке поиска"><span class="qm-cap">Искали:</span>`
    + m.chips.map(плашка).join("") + `</div>`
    + (m.message ? `<div class="qm-message" role="status">${esc(m.message)}</div>` : "");
}
// ---- Фильтр проекта — один компонент в обеих системах (решение владелицы 25.10.2026: «системы выглядят одинаково») ----
// Выпадающий список: первым пунктом — «всё» (значение "", без отбора), ниже варианты, последним — «без …», если подпись
// задана. Планёрка: «Все проекты» и проекты справочника. ERP: «Весь проект <проект системы>» (все записи), подпроекты, если
// есть, и «без подпроекта», если подпроекты есть (`podproekty.фильтр` сервера). Показывается всегда.
function фильтрПроектаHtml(id, { все, варианты = [], без = "", безЗначение = "__none__", выбран = "" } = {}) {
  const опция = (v, label) => `<option value="${esc(v)}"${v === выбран ? " selected" : ""}>${esc(label)}</option>`;
  return `<select id="${esc(id)}" class="project-filter" aria-label="Проект">${опция("", все || "Все проекты")}`
    + варианты.map(v => опция(v, v)).join("") + (без ? опция(безЗначение, без) : "") + `</select>`;
}
function показатьПлашкиМаркеров(el, m, искать) {
  if (!el) return;
  el.innerHTML = плашкиМаркеровHtml(m);
  el.querySelectorAll("[data-qm-q]").forEach(b => b.addEventListener("click", () => искать(b.dataset.qmQ)));
}

// ---- «Искать везде» и кнопки-подсказки маркеров у строки поиска по задачам (решение владелицы 17.10.2026) ----
// Строка поиска по задачам остаётся поиском по задачам. Рядом — «Искать везде»: окно справа с полнотекстовым поиском по
// тому же запросу (этап 1 `/search` → пусто — «Идёт глубокий поиск…» и `/search/deep` → «По запросу информации нет»);
// находки рисуют те же функции, что «Сводка» (`найденноеВОкне` → `renderSearchResults`, `находкаИзЗаписиHtml`), плашки —
// `показатьПлашкиМаркеров`. «Свернуть», Esc и смена экрана закрывают окно. Под строкой — кнопки-примеры маркеров: нажал —
// пример добавился в строку и поиск по задачам запустился. Примеры приходят с сервера (`GET /search/markers`, источник —
// `query_markers.ПРИМЕРЫ`, тот же модуль, что ПОДСКАЗКА), своего списка здесь нет. Функции совпадают в обеих системах.
let _примерыМаркеров = null;          // готовый список примеров (после первого ответа сервера)
let _примерыЗапрос = null;
function примерыМаркеров() {
  if (_примерыМаркеров) return Promise.resolve(_примерыМаркеров);
  if (!_примерыЗапрос) _примерыЗапрос = api("/search/markers")
    .then(d => (_примерыМаркеров = ((d && d.examples) || []).filter(Boolean)))
    .catch(() => { _примерыЗапрос = null; return []; });
  return _примерыЗапрос;
}
function добавитьПримерВСтроку(строка, пример) {
  const было = String(строка || "").replace(/\s+/g, " ").trim();
  if (!было) return пример;
  if (было.toLowerCase().includes(String(пример).toLowerCase())) return было;
  return (было + " " + пример).slice(0, 300);
}
function кнопкаИскатьВездеHtml() {
  return `<button type="button" class="btn-link search-everywhere" data-search-everywhere
    title="Полнотекстовый поиск по тому же запросу — в протоколах, материалах, задачах и записях">Искать везде</button>`;
}
function рядПримеровHtml(id) {
  return `<div class="qm-examples" id="${esc(id)}" role="group" aria-label="Примеры: время и проект в строке поиска"></div>`;
}
// `поле` — строка поиска по задачам, `ряд` — место для кнопок-примеров, `кнопка` — «Искать везде», `искать()` — запуск
// поиска по задачам этого экрана (тот же, что по Enter).
function подключитьПоискВезде({ поле, ряд, кнопка, искать }) {
  if (!поле) return;
  const нарисовать = (примеры) => {
    if (!ряд || !ряд.isConnected) return;
    ряд.innerHTML = примеры.length ? `<span class="qm-cap">Например:</span>` + примеры.map(п =>
      `<button type="button" class="qm-example" data-qm-example="${esc(п)}">${esc(п)}</button>`).join("") : "";
    ряд.querySelectorAll("[data-qm-example]").forEach(b => b.addEventListener("click", () => {
      поле.value = добавитьПримерВСтроку(поле.value, b.dataset.qmExample);
      искать();
    }));
  };
  if (ряд) { if (_примерыМаркеров) нарисовать(_примерыМаркеров); else примерыМаркеров().then(нарисовать); }
  if (кнопка) кнопка.addEventListener("click", () => окноИскатьВезде(поле.value));
}
function окноИскатьВезде(запрос) {
  const q = String(запрос || "").replace(/\s+/g, " ").trim().slice(0, 300);
  закрытьОкноИскатьВезде();
  const окно = document.createElement("aside");
  окно.className = "se-drawer";
  окно.id = "search-everywhere";
  окно.setAttribute("role", "dialog");
  окно.setAttribute("aria-label", "Искать везде");
  окно.innerHTML = `<div class="se-head"><b>Искать везде</b></div>
    <div class="se-sub">${q ? `По запросу «${esc(q)}» — в протоколах, материалах, задачах и записях встреч`
      : "Введите запрос в строке поиска и нажмите «Искать везде»."}</div>
    <div id="se-markers"></div>
    <div id="se-results"></div>
    <button type="button" class="btn-link se-close" id="se-close">Свернуть ▾</button>`;
  document.body.appendChild(окно);
  окно.querySelector("#se-close").addEventListener("click", закрытьОкноИскатьВезде);
  окноИскатьВезде._esc = (e) => { if (e.key === "Escape") закрытьОкноИскатьВезде(); };
  document.addEventListener("keydown", окноИскатьВезде._esc);
  window.addEventListener("hashchange", закрытьОкноИскатьВезде);
  if (q) искатьВОкне(q);
}
function закрытьОкноИскатьВезде() {
  document.getElementById("search-everywhere")?.remove();
  if (окноИскатьВезде._esc) document.removeEventListener("keydown", окноИскатьВезде._esc);
  window.removeEventListener("hashchange", закрытьОкноИскатьВезде);
}
async function искатьВОкне(q) {
  const $m = document.getElementById("se-markers"), $r = document.getElementById("se-results");
  if (!$r) return;
  const безПлашки = (qq) => окноИскатьВезде(qq);          // крестик плашки — тот же поиск без неё
  $r.innerHTML = `<div class="empty-state" role="status">Ищем…</div>`;
  let d;
  try { d = await api("/search?q=" + encodeURIComponent(q)); }
  catch (e) { if ($r.isConnected) $r.innerHTML = `<div class="search-empty">Поиск не завершился. Попробуйте ещё раз.</div>`; return; }
  if (!$r.isConnected) return;
  показатьПлашкиМаркеров($m, d && d.markers, безПлашки);
  if (d && d.deep) глубокийПоиск(q, $r, (dd) => { показатьПлашкиМаркеров($m, dd.markers, безПлашки); найденноеВОкне(dd, $r, q); });
  else найденноеВОкне(d || {}, $r, q);
}
// ---- конец блока «Искать везде» ----
// Находки в окне «Искать везде» — та же отрисовка, что во вкладке «Поиск» «Статуса проекта» (вместе с «Уточните вопрос»).
function найденноеВОкне(d, el, q) {
  renderSearchResults(d.results || [], q, !!d.needs_detail, d.problem || null, el, d.message);
}


// --- Статус проекта -------------------------------------------------------

// «Статус проекта» — вкладки «Сводка | Дорожная карта» в одной строке шапки (решение владельца 01.10.26: «уберём
// Дорожную карту снизу, сделаем вкладкой — внизу ей невозможно пользоваться»). Раньше оба документа шли друг под другом
// с кнопками «К Сводке» / «К Дорожной карте». Та же шапка, что у Плана и Протокола: вкладки, «собран …», справа
// «Скачать .docx» и «Правка»; текст на высоту экрана. Вкладка — в адресе (#status/roadmap), обновление её не сбрасывает.
async function renderStatus(rest) {
  // Три вкладки: поиск и два документа проекта. «Поиск» переехал сюда с убранной страницы «Данные
  // проекта» (владелец 07.10.26), а затем владелец попросил: «при попадании на Статус проекта переход
  // сразу на Поиск горизонтального выбора — первая кнопка поиск». Значит, при заходе по «#status» (без
  // вкладки в адресе) открывается поиск, и в ряду вкладок «Поиск» стоит первым: это самый частый вход
  // на страницу. Прямые адреса вкладок («#status/summary», «#status/roadmap») работают как раньше.
  const первый = rest && rest[0];
  const active = ["search", "summary", "roadmap"].includes(первый) ? первый : "search";
  const tab = (key, label) => key === active
    ? `<span class="doc-tab doc-tab-on">${label}</span>`
    : `<a class="doc-tab" href="#status/${key}">${label}</a>`;
  const вкладки = `<nav class="doc-tabs">${tab("search", "Поиск")}${tab("summary", "Сводка")}${tab("roadmap", "Дорожная карта")}</nav>`;
  // Кнопка «Пересчитать» — на главном экране раздела (решение владелицы 19.10.2026: «в разделе «Статус проекта»»): в шапке
  // раздела на каждой вкладке, включая «Поиск», с которого раздел открывается. Видна всем ролям, как и права ручки (решение владелицы 19.10.2026).
  // Строка хода — всем ролям, как и кнопка (20.10.2026, решение владелицы 19.10.2026 «для всех категорий»): участник видит,
  // идёт ли пересчёт и когда можно снова. Не-администратору сервер отдаёт только ход, время и перерыв (`_ход_для`).
  const строкаХода = `<span class="doc-head-meta" id="status-recalc-meta" aria-live="polite"></span>`;
  // все категории пользователей — решение владелицы 19.10.2026
  const кнопкаПересчёта = `<button type="button" class="btn-sm" id="status-recalc-btn" title="Пересобрать Сводку и Дорожную карту по всем встречам, задачам и договорённостям — платный расчёт, несколько минут; экран не блокируется">Пересчитать</button>`;
  if (active === "search") {
    // Адрес вкладки: «#status/search» или «#status/search/find/<запрос>» (старые «#search/find/…» сюда
    // перенаправляются в renderSearch).
    const raw = rest[1] === "find" ? rest[2] : rest[1];
    let q = "";
    try { q = raw ? decodeURIComponent(raw) : ""; } catch (e) { q = raw || ""; }
    q = q.trim().slice(0, 300);
    $main.innerHTML = `<div class="doc-head">
        <h1>Статус проекта</h1>
        ${вкладки}
        ${строкаХода}
        <span class="doc-head-spacer"></span>
        ${кнопкаПересчёта}
      </div>
      <div id="search-pane">
        <div class="search-row"><div class="card">
          <div class="search-box">
            <textarea id="search-input" rows="1" maxlength="300" placeholder="Например: было ли упомянуто…" aria-label="Поиск по проекту">${esc(q)}</textarea>
            <button type="button" class="search-submit" id="search-submit-btn" title="Искать (Enter)" aria-label="Искать">&#9166;</button>
          </div>
        </div><button type="button" class="link search-reset-link" id="search-reset" hidden>Сбросить</button>
        <span class="tip"><button type="button" class="tip-ico" aria-label="Как писать время, проект и ФИО">i</button><span class="tip-body" role="tooltip">${esc(ПОДСКАЗКА_МАРКЕРОВ)}</span></span></div>
        <div id="search-suggestions" class="hstack" style="margin-bottom:8px"></div>
        <div id="search-detail-hint" class="page-sub" style="margin:0 0 20px" hidden>Допишите уточнение (например, ФИО или тему) и нажмите Enter — сама подсказка поиском не считается.</div>
        <div id="search-markers"></div>
        <div id="search-results"></div>
      </div>`;
    wireRecalcButton();
    await renderSearchTab(q);
    return;
  }
  if (нуженПроект("Статус проекта")) return;          // MeetFlow: Сводка и Дорожная карта — по одному проекту
  заставкаЗагрузки();   // тот же экран — прежнее содержимое до новой отрисовки (26.10.2026)
  const [roadmap, summary] = await Promise.all([api("/project-status/roadmap"), api("/project-status/summary")]);
  const doc = active === "roadmap" ? roadmap : summary;
  const base = `/project-status/${active}`;
  const blockId = `${active}-block-doc`;
  $main.innerHTML = `<div class="doc-head">
      <h1>Статус проекта</h1>
      ${вкладки}
      ${doc.available && doc.generated_at && isAdmin() ? `<span class="doc-head-meta">собрана ${esc(fmtRuDateTime(doc.generated_at))}</span>` : ""}
      ${строкаХода}
      <span class="doc-head-spacer"></span>
      ${кнопкаПересчёта}
      ${doc.available ? `<a class="btn btn-sm" href="${base}/export?project_id=${выбранныйПроект()}" target="_blank">Скачать .docx</a>` : ""}
      ${doc.available && isAdmin() ? полотноПереключатель(base, полотноРежим(base)) : ""}
    </div>
    <div id="status-refresh-note" class="page-sub"></div>
    ${docBlock(doc, `${base}/export?project_id=${выбранныйПроект()}`, null, base, blockId, { compact: true, noBar: true })}`;
  if (doc.available) await подключитьПолотноДокумента(blockId, base, doc.content_md, () => renderStatus(rest), null);
  wireRecalcButton();
}

// Кнопка «Пересчитать» Сводки и Дорожной карты (задание владелицы 19.10.2026). В старой ERP пересчёт вызывался отдельно
// по необходимости — расчёт долгий (16.09.26: ручка `POST /project-status/refresh` ставит его в фон и сразу отвечает). До
// 18.10 кнопка «Обновить» была только в строке устаревания, и та показывалась лишь когда Карта отстала (≥ 5 правок задач
// или час), а с 13.10 — только на «Статусе проекта» ссылкой; после пересчёта по каждому протоколу строки почти никогда не
// было, и вызвать пересчёт было нечем. Теперь кнопка всегда стоит в шапке вкладок «Сводка» и «Дорожная карта»
// (администраторам — права ручки прежние, `require_admin`), рядом строка хода: идёт N мин / в очереди / последний
// пересчёт с датой и длительностью. Экран не блокируется. Второй расчёт поверх идущего не ставит сервер (замок — строка
// очереди сборок в базе, ответ `already`), кнопку на время расчёта не выключаем: замок на данных, а не на кнопке.
function строкаПересчёта(st) {
  if (!st) return "";
  const мин = (сек) => сек >= 60 ? `${Math.round(сек / 60)} мин` : `${сек} с`;
  if (st.status === "running") return `пересчёт идёт ${мин(st.elapsed_seconds || 0)}${st.likely_stuck ? " — необычно долго" : ""}`;
  if (st.status === "queued") return "пересчёт в очереди сборок — после протоколов";
  if (!st.finished_at) return "пересчёта ещё не было";
  const когда = fmtRuDateTime(st.finished_at);
  if (st.status === "error") return `последний пересчёт ${когда} не удался`;
  // Перерыв между пересчётами по кнопке (решение владелицы 19.10.2026, 60 мин) — когда можно снова
  if (st.next_manual_at && !isSuperAdmin()) return `пересчёт шёл ${мин(st.duration_seconds || 0)}, следующий — после ${времяМск(st.next_manual_at)}`;
  // Время удачного пересчёта уже стоит рядом («собрана …») — здесь только длительность: шапка остаётся одной строкой.
  return st.duration_seconds != null ? `пересчёт шёл ${мин(st.duration_seconds)}` : `последний пересчёт ${когда}`;
}

function времяМск(iso) {
  const полное = fmtRuDateTime(iso);                       // «19.10.2026 в 22:29»
  const сегодня = fmtRuDateTime(new Date().toISOString().slice(0, 19)).split(" в ")[0];
  const [день, время] = полное.split(" в ");
  return день === сегодня ? время : `${день} ${время}`;
}

function показатьХодПересчёта(st) {
  const el = document.getElementById("status-recalc-meta");
  if (el) el.textContent = строкаПересчёта(st);
}

async function wireRecalcButton() {
  const btn = document.getElementById("status-recalc-btn");
  if (!btn) return;
  try { показатьХодПересчёта(await api("/project-status/refresh-status", { вне_показа: true })); } catch (e) { /* строка хода — не обязательна */ }
  btn.addEventListener("click", () => запуститьПересчёт());
}

// Одно действие на две кнопки — «Пересчитать» в шапке «Статуса проекта» и «Обновить» в строке устаревания (20.10.2026).
// Права, перерыв 60 мин (кроме суперадмина) и замок «уже идёт» решает сервер; здесь — только честный ответ на экране.
async function запуститьПересчёт() {
  let st;
  try {
    st = await api("/project-status/refresh", { method: "POST" });
  } catch (e) { toast(e.message, true); return; }
  показатьХодПересчёта(st);
  if (st.pause) { toast(st.reason); return; }
  if (st.already) toast(st.status === "queued" ? "Пересчёт уже стоит в очереди — второй не нужен" : "Пересчёт уже идёт — второй не нужен");
  else toast("Пересчёт Сводки и Дорожной карты запущен — можно продолжать работу");
  renderCalmRefreshBanner();
  clearTimeout(_refreshPollTimer);
  _refreshPollTimer = setTimeout(pollRefreshStatus, 3000);
}

// --- Конфликты ---------------------------------------------------------
// Решение 17.09.26 — очередь находок, которые код не разрешает сам
// (сверка с файловым реестром, неоднозначности проверки источников,
// пробелы вроде «встреча в файлах есть, в вебаппе не заведена»). Раньше
// такие находки просто перечислялись в чате и терялись между сессиями.
// Три действия на карточку — тот же процесс, что уже вручную утверждался
// при сверке реестра, только теперь он persisted и не требует моего
// участия для каждого решения.
const CONFLICT_FIELD_LABELS = {
  project: "Проект",
  responsible: "Ответственный",
  status: "Статус",
  date_closed: "Дата закрытия",
  due_date: "Срок",
  member_note: "Отметка по задаче",
  missing_meeting: "Встреча не загружена в приложение",
  duplicate_task: "Похожая задача",
  ungrounded_task: "Задача без опоры в источнике",
  held_recording: "Запись встречи нетипичной длины",
  held_recording_breaks: "Распознавание обрывалось — повторить?",
  resettle_offer: "Появился источник — пересобрать протокол?",   // осадка источников (Е4, 19.10.26)
  external_unheard: "Внешний упомянут без звучания в записи",      // проверка тела протокола (24.10.2026, вариант «а»)
  transcript_loop: "Петля распознавания — переслушать запись",     // петли распознавания (26.10.2026)
  voice_hint: "Голос похож — подтвердить, кто это",   // подсказка опознания голоса (17.10.26)
  project_hint: "Проект по истории реестра — подтвердить",   // Е5, 19.10.2026 (как Планёрка 17.10.26)
  model_bad_format: "Модель ответила не в формате — проверить модель шага",
  model_not_ready: "Модель не готова к сборке — проверить модель роли",
  build_failed: "Протокол не собран — устранить причину и пересобрать",   // правило сбоя сборки (25.10.2026)
  rebuild_order: "Ранняя встреча собрана после поздних — сверить задачи",
  units_chunk_not_parsed: "Кусок записи не разобран моделью — пересобрать",
  later_protocols_first: "Протоколы поздних встреч собраны раньше — сверить задачи",
  // Реестр договорённостей — подписи Планёрки (решения владелицы 21.10.2026, пункт 5)
  agreement_doubt: "Договорённость под вопросом — подтвердить",
  agreement_replace: "Договорённость заменяет прежнюю — подтвердить",
  agreement_close: "Решение закрывает открытую запись — подтвердить",
  project_registry_question: "Вопрос по справочнику проектов",   // как Планёрка 24.10.2026 (6ac63ea)
};

// Косметика 17.09.26 (жалоба) — карточки конфликтов показывали значения
// как есть из БД: английские "active"/"done" для поля «Статус», и
// "high"/"medium"/"low" для уверенности — весь остальной интерфейс на
// русском, эти два места оставались единственным исключением.
const CONFLICT_STATUS_VALUE_LABELS = { active: "В работе", done: "Выполнено", dropped: "Снято" };
const CONFLICT_CONFIDENCE_LABELS = { high: "высокая", medium: "средняя", low: "низкая" };

function conflictValueLabel(field, value) {
  if (!value) return value;
  return field === "status" ? (CONFLICT_STATUS_VALUE_LABELS[value] || value) : value;
}

// Значки меню (решение владелицы 18.10.2026: «значки на каждом переходе — недостаточно снизилось»). На переходе между
// пунктами меню значки НЕ запрашиваются: `updateConflictsBadge({}, { толькоНезаполненные: true })` (конец `render()`,
// вкладки «Параметров системы») только ставит последнее известное число. Свежие числа — одним запросом `/badges`
// (чистый COUNT на сервере) раз в 60 секунд одним таймером на всё приложение (`запуститьЗначки`, скрытая вкладка запрос
// пропускает) и сразу после собственных действий пользователя (`updateConflictsBadge()` без числа). Страница, у которой
// число уже есть из своего списка, передаёт его в `числа` — без запроса.
//
// Решение 24.09.26 (реальная находка пользователя: бейдж «Конфликты» показывал 10, сама страница — «Открытых конфликтов
// нет»): у каждой страницы — свой бейдж, из того же источника, который она сама показывает.
var _значки = { conflicts: null, errors: null, awaiting: null, pod: null, voice_review: null, possible: null, razbor: null };   // razbor — «Разбор», всё открытое (25.10.2026)   // possible — «Возможные поручения» (24.10.2026)   // pod — «Под вопросом» (20.10.2026), voice_review — «Разбор голосов» (21.10.2026)   // var: render() может прийти раньше этой строки
var _значкиТаймер = null;
var _значкиЗапрос = null;
const ЗНАЧКИ_КАЖДЫЕ_МС = 60000;

function показатьЗначки() {
  const поставить = (места, n) => { if (n !== null && n !== undefined) места.forEach($б => { $б.textContent = n ? String(n) : ""; }); };
  поставить([document.getElementById("conflicts-badge")].filter(Boolean), _значки.conflicts);
  // «Под вопросом» — число у пункта меню администратора (решение владелицы 20.10.2026)
  if (isAdmin()) поставить([document.getElementById("pod-badge")].filter(Boolean), _значки.pod);
  if (isAdmin()) поставить([document.getElementById("possible-badge")].filter(Boolean), _значки.possible);   // «Возможные поручения»
  // «Разбор» — одно число вместо трёх: всё открытое в «Разборе» (решение владелицы 25.10.2026)
  if (isAdmin()) поставить([document.getElementById("razbor-badge")].filter(Boolean), _значки.razbor);
  if (!isSuperAdmin()) return;
  поставить([...document.querySelectorAll('.tab-badge[data-badge="awaiting"]')], _значки.awaiting);
  поставить([document.getElementById("voice-review-badge")].filter(Boolean), _значки.voice_review);   // «Разбор голосов»
  // Одно и то же число в трёх местах: пункт меню, кнопка «Параметры системы» и вкладка «Системные сообщения» (07.10.26)
  поставить([document.getElementById("system-badge"), ...document.querySelectorAll('.tab-badge[data-badge="errors"]')].filter(Boolean),
            _значки.errors);
}

function обновитьЗначки() {
  if (!isAdmin()) return Promise.resolve();
  if (_значкиЗапрос) return _значкиЗапрос;          // одновременные вызовы — один запрос
  _значкиЗапрос = (async () => {
    try {
      const [з, ждёт] = await Promise.all([api("/badges", {}),
        isSuperAdmin() ? api("/project-status/awaiting-input", {}).catch(() => null) : null]);
      if (з.conflicts !== null && з.conflicts !== undefined) _значки.conflicts = з.conflicts;
      if (з.system !== null && з.system !== undefined) _значки.errors = з.system;
      if (з.under_question !== null && з.under_question !== undefined) _значки.pod = з.under_question;
      if (з.possible !== null && з.possible !== undefined) _значки.possible = з.possible;   // «Возможные поручения» (24.10.2026)
      if (з.razbor !== null && з.razbor !== undefined) _значки.razbor = з.razbor;           // «Разбор» (25.10.2026)
      if (з.voice_review !== null && з.voice_review !== undefined) _значки.voice_review = з.voice_review;
      if (ждёт) _значки.awaiting = ждёт.total;
      показатьЗначки();
    } catch (e) { /* значки — не критично, тихо игнорируем */ }
    finally { _значкиЗапрос = null; }
  })();
  return _значкиЗапрос;
}

function запуститьЗначки() {
  if (_значкиТаймер || !isAdmin()) return;
  обновитьЗначки();
  _значкиТаймер = setInterval(() => { if (!document.hidden) обновитьЗначки(); }, ЗНАЧКИ_КАЖДЫЕ_МС);
}

async function updateConflictsBadge(числа = {}, { толькоНезаполненные = false } = {}) {
  let есть = false;
  for (const ключ of ["conflicts", "errors", "awaiting", "pod"]) {
    if (typeof числа[ключ] === "number") { _значки[ключ] = числа[ключ]; есть = true; }
  }
  if (есть || толькоНезаполненные) { показатьЗначки(); запуститьЗначки(); return; }
  return обновитьЗначки();                           // после действия пользователя — свежие числа
}

// Решение 23.09.26, уточнение после F12: сама очередь «Конфликты» (текстовые расхождения) —
// доступ админа и супер-админа, как было исходно до F12. «Системные сообщения» и «Параметры
// системы» — по-прежнему только супер-админу, вынесены на отдельную страницу «#system», сюда —
// только ссылка на неё за отсечкой, и то не всем, а только тем, кто её видит.
// Промпт «пять экранов», Экран 2 «Реестр решений — это я уже разбирал» (24.09.26): «любой исход —
// решение, и решение записывается». Раньше решённый конфликт просто исчезал со страницы — узнать,
// что и почему было решено, можно было только через базу. Переключатель на той же странице, не
// отдельный пункт меню — оба смотрят на одну и ту же сущность (TaskConflict), разный статус.
async function renderConflicts() {
  $main.innerHTML = `<h1>Конфликты</h1>
    <div class="page-sub">Находки, которые нужно решить вручную — сверка с файловым реестром,
      неоднозначности при проверке источников, пробелы в данных. По каждой — принять предложенное,
      оставить как есть, или вписать своё значение.</div>
    <div id="conflicts-list" class="card empty-state" data-list="conflicts" data-list-item=".conflict-card">Загрузка…</div>`;
  await loadAndRenderConflicts();
}

function setActiveTab($active, otherIds) {
  $active.classList.add("btn-primary");
  (Array.isArray(otherIds) ? otherIds : [otherIds]).forEach(id => document.getElementById(id)?.classList.remove("btn-primary"));
}

const NOT_A_TASK_DAYS = 21;   // как operator_rules.NOT_A_TASK_DAYS — подсказка у «Не заводить» (письмо 39 Планёрки)
const RESOLVED_STATUS_LABELS = { accepted: "принято предложенное", rejected: "оставлено как есть", custom: "указано своё" };

// «Реестр решений» — вкладка «Параметров системы» (решение владельца 01.10.26, «как в Планёрке»). С 15.10.26 — в стиле
// «Конфликтов» (владелец: «по реестру решений примени примерно такой же дизайн, как у Планёрки», её 5d034c7, 8e042d8, fde782a):
// группы с числом, свёрнуты до заголовка, открыта первая; в открытой — строки по высоте окна и «Показать все». Порядок по
// важности: действующие правила («Убрать») → снятые («Вернуть») → разобранные карточки. Строка как в «Конфликтах»: значок |
// суть, под ней смысл курсивом и служебная строка (вид · дата · применений) | мягкая кнопка справа. Служебные пояснения —
// в «i»; коды — подписями (раньше в строке стояло «review_finding»).
const РЕШЕНИЯ_ПОДПИСИ = {
  ...CONFLICT_FIELD_LABELS, review_finding: "Замечание проверки", unconfirmed_person: "Человек назван не полностью",
  no_tasks_with_assignment_lines: "Поручения в записи — задач нет", due_notes_vs_record: "Срок: заметки и запись расходятся",
  participant_ambiguous: "Непонятно, о ком речь", early_after_late: "Ранняя встреча собрана после поздних",
};
const решенияОткрыты = new Set();

function решениеПодпись(c) {
  if (c.field_label) return c.field_label;
  return РЕШЕНИЯ_ПОДПИСИ[c.source] || РЕШЕНИЯ_ПОДПИСИ[c.field] || "Карточка «Конфликтов»";
}

function решениеСтрока({ ico, title, quote, meta, act }) {
  return `<div class="cf-row conflict-card dec-row"><span class="cf-ico" aria-hidden="true">${ico}</span>
    <div class="cf-main"><div><b>${title}</b></div>${quote ? `<div class="page-sub">${quote}</div>` : ""}<div class="dec-meta">${meta}</div></div>
    ${act ? `<div class="cf-act">${act}</div>` : ""}</div>`;
}

async function loadAndRenderDecisionsTab() {
  const $box = document.getElementById("decisions-panel");
  if (!$box) return;
  $box.innerHTML = `<div class="dec-head"><b>Решения и правила</b> <span class="tip"><button type="button" class="tip-ico" aria-label="Что здесь">i</button><span class="tip-body" role="tooltip">Правила — ваши ответы на карточки «Конфликтов»: система применяет их сама и не спрашивает снова. Ответ решает только свою карточку; правилом он становится, когда вы ответили так же ${2} раза (защита от случайного нажатия), до этого правило «на паузе». Ошибочное правило можно убрать — вопрос вернётся карточкой; убранное — вернуть. «Применений» — встречи, где правило изменило сохранённый Протокол; подсказки модели и распознаванию не считаются, ноль не значит, что правило лишнее. Разобранные карточки — что и как решено; старые убираются из реестра сами.</span></span></div>
    <div id="decisions-list" class="card cf-list">Загрузка…</div>`;
  let rules = [], all = [], notes = [];
  try { [rules, all, notes] = await Promise.all([api("/operator-rules"), api("/task-conflicts?status=all", {}), api("/review-notes/decisions", {})]); }
  catch (e) { document.getElementById("decisions-list").textContent = "Не удалось загрузить реестр решений."; return; }
  const $list = document.getElementById("decisions-list");
  if (!$list) return;
  const знак = (k) => (КОНФЛИКТ_ВИДЫ[k] || КОНФЛИКТ_ВИДЫ.task).ico;
  const правило = (r) => {
    const what = r.kind === "same_person" ? `«${esc(r.shown_as)}» = ${esc(r.value || "")}` : `«${esc(r.shown_as)}»`;
    const мета = [`заведено ${esc(fmtRuDate(String(r.created_at || "").slice(0, 10)))}`,
      `применений ${r.applied_count || 0}${r.applied_count && r.last_applied_meeting ? ` (последнее — ${esc(r.last_applied_meeting)})` : ""}`];
    if (r.pending_answers != null) мета.push(`на паузе: ${r.pending_answers} из ${r.answers_needed} одинаковых ответов`);
    if (r.revoked_at) мета.push(`убрано ${esc(fmtRuDate(String(r.revoked_at).slice(0, 10)))}`);
    if (r.expired) мета.push("срок истёк");
    const act = !isAdmin() || r.expired ? "" : r.revoked_at
      ? `<button type="button" class="btn-sm" data-restore-rule="${r.id}">Вернуть</button>`
      : `<button type="button" class="btn-sm" data-revoke-rule="${r.id}">Убрать</button>`;
    return решениеСтрока({ ico: знак(r.kind === "not_a_task" ? "task" : "person"), title: what, quote: esc(r.kind_label), meta: мета.join(" · "), act });
  };
  const noteRows = notes.map(n => ({ resolved_at: n.at, created_at: n.at, status: "note", field_label: `Замечание · ${n.document}`,
    task_description: n.title, current_value: n.quote, outcome_label: n.outcome_label, resolution_note: n.by ? `решил(а): ${n.by}` : "" }));
  const разобранные = all.filter(c => c.status !== "open").concat(noteRows)
    .sort((a, b) => new Date(b.resolved_at || b.created_at) - new Date(a.resolved_at || a.created_at));
  const карточка = (c) => {
    // стрелка — только между непустыми значениями (Планёрка cdb0a3f: было «— → Гейко», «Дмитриев → —»)
    const значения = [c.current_value, c.proposed_value].filter(Boolean).map(esc).join(" → ");
    // «Разобранные карточки» — как карточка-вопрос (Планёрка bc998cf): «Непонятно, о ком речь: Дима» — «Дима у нас
    // занимается плёнкой»; без цитаты в тексте системы — значения через «→»
    const кто = c.task_description || c.current_value;
    const суть = esc(кто ? `${решениеПодпись(c)}: ${кто}` : решениеПодпись(c));
    const прозвучало = typeof конфликтЦитата === "function" ? конфликтЦитата(c.evidence_quote || "") : "";
    const цитата = прозвучало ? `«${esc(прозвучало)}»` : (c.task_description ? значения : (c.proposed_value ? esc(c.proposed_value) : ""));
    const мета = [esc(fmtRuDateTime(c.resolved_at)), esc(c.outcome_label || RESOLVED_STATUS_LABELS[c.status] || "")]   // вид — уже в заголовке
      .concat(c.resolution_note ? [esc(c.resolution_note)] : []).filter(Boolean).join(" · ");
    const вид = c.source === "review_finding" || c.status === "note" ? "review" : c.field === "responsible" ? "person"
      : c.field === "due_date" ? "due" : "task";
    return решениеСтрока({ ico: знак(вид), title: суть, quote: цитата, meta: мета });
  };
  const группы = [
    { k: "active", label: "Действующие правила", rows: rules.filter(r => !r.revoked_at && !r.expired).map(правило) },
    { k: "revoked", label: "Снятые правила", rows: rules.filter(r => r.revoked_at || r.expired).map(правило) },
    { k: "resolved", label: "Разобранные карточки", rows: разобранные.map(карточка) },
  ].filter(g => g.rows.length);
  if (!группы.length) { $list.className = "card empty-state"; $list.textContent = "Решений и правил пока нет."; return; }
  if (!группы.some(g => решенияОткрыты.has(g.k))) { решенияОткрыты.clear(); решенияОткрыты.add(группы[0].k); }
  $list.innerHTML = группы.map(g => {
    const открыта = решенияОткрыты.has(g.k);
    return `<section class="cf-group" data-k="${g.k}"><button type="button" class="cf-group-head" aria-expanded="${открыта}"><span class="cf-chev" aria-hidden="true">›</span>${g.label}<span class="n">${g.rows.length}</span></button>
      <div class="cf-group-body" data-list="dec-${g.k}" data-list-item=".dec-row"${открыта ? "" : " hidden"}>${g.rows.join("")}</div></section>`;
  }).join("");
  $list.querySelectorAll(".cf-group-head").forEach(кн => кн.addEventListener("click", () => {
    const откр = кн.getAttribute("aria-expanded") !== "true", тело = кн.nextElementSibling, k = кн.parentElement.dataset.k;
    кн.setAttribute("aria-expanded", String(откр));
    тело.hidden = !откр;
    if (откр) { решенияОткрыты.add(k); тело._поОкну?.(); } else решенияОткрыты.delete(k);
  }));
  свернутьДлинныеСписки($list);
  $list.querySelectorAll("[data-restore-rule]").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await api(`/operator-rules/${btn.dataset.restoreRule}/restore`, { method: "POST" }); }
    catch (e) { btn.disabled = false; toast(e.message || "Не удалось вернуть правило", true); return; }
    toast("Правило снова действует");
    loadAndRenderDecisionsTab();
  }));
  $list.querySelectorAll("[data-revoke-rule]").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await api(`/operator-rules/${btn.dataset.revokeRule}/revoke`, { method: "POST" }); }
    catch (e) { btn.disabled = false; toast(e.message || "Не удалось убрать правило", true); return; }
    toast("Правило убрано — вопрос снова придёт карточкой");
    loadAndRenderDecisionsTab();
  }));
}

// Промпт «пять экранов» (24.09.26; доразбито по замечанию владельца — «раздели на мониторинге по
// разным вкладкам по типам информации, сейчас вообще не понятно», со ссылкой на пример из
// Planerka, где «Мониторинг»/«Диск и доступы»/«Состояние базы» — отдельные пункты): один плоский
// грид на 6 разнородных блоков читать было невозможно. Пять вкладок по ТИПУ вопроса, не по
// частоте — «жива ли служба», «какого качества генерация», «сколько тратим», «чем система
// отвечает сейчас», «что меняется редко» — один и тот же ответ /project-status/monitoring на все,
// не пять походов в сеть.
const MONITORING_TABS = [
  { id: "mon-tab-runs", label: "Прогоны", panel: "monitoring-panel", render: "renderMonitoringRuns" },
  { id: "mon-tab-cost", label: "Расход", panel: "monitoring-panel", render: "renderMonitoringCost" },
  { id: "mon-tab-decisions", label: "Реестр решений", panel: "decisions-panel", render: "loadAndRenderDecisionsTab" },
  { id: "mon-tab-data", label: "Состояние базы", panel: "monitoring-panel", render: "renderMonitoringDataState" },
  { id: "mon-tab-static", label: "Диск и доступы", panel: "monitoring-panel", render: "renderMonitoringStatic" },
  // «Настройки» — как у Планёрки (решение владельца 15.10.26: выключатель отметки «под вопросом» — только здесь)
  { id: "mon-tab-settings", label: "Настройки", panel: "monitoring-panel", render: "renderSettingsTab" },
  // `badge` — у вкладки есть неразобранные сообщения: счётчик виден прямо на кнопке (владелец 07.10.26),
  // чтобы не открывать вкладку, чтобы понять, есть ли к ней вопрос.
  { id: "mon-tab-errors", label: "Системные сообщения", panel: "system-messages-wrap", render: "loadAndRenderSystemMessages",
    badge: "errors" },
  // Перенесена из левой панели (владелец 09.10.26); старый адрес #awaiting открывает эту вкладку.
  { id: "mon-tab-awaiting", label: "Ожидает ввода от оператора", panel: "awaiting-wrap", render: "renderAwaitingTab",
    badge: "awaiting" },
];

// Решение 24.09.26 (реальная находка владельца по скриншоту: «Системные сообщения» показывались
// одним и тем же списком под КАЖДОЙ вкладкой мониторинга — выглядело как будто список
// дублируется/относится к разным вкладкам, хотя он один общий). Теперь это ШЕСТАЯ вкладка того
// же переключателя, не постоянный блок под всеми остальными — виден только тогда, когда выбран.
async function renderSystemParams(rest) {
  $main.innerHTML = `<h1>Параметры системы</h1>
    <div class="page-sub">Видно только супер-админу — отдельный пункт левого меню под чертой.</div>
    <div class="hstack" style="margin-bottom:16px; flex-wrap:wrap">
      ${MONITORING_TABS.map((t, i) => `<button class="btn-sm${i === 0 ? " btn-primary" : ""}" id="${t.id}">${esc(t.label)}` +
        (t.badge ? ` <span class="tab-badge" data-badge="${t.badge}"></span>` : "") + `</button>`).join("")}
    </div>
    <div id="monitoring-panel" class="card empty-state">Загрузка…</div>
    <div id="decisions-panel" hidden></div>
    <div id="system-messages-wrap" hidden>
      <div class="page-sub">Технические сбои приложения (например, модель вернула ответ не в том формате). Показываются
        только здесь, в рабочих вкладках их нет. Когда сообщение разобрано — нажмите «Закрыть». По умолчанию видны открытые за 7 дней, более ранние — «Показать ещё»; старше срока хранения служебных журналов удаляются сами.</div>
      <div id="system-messages" class="card empty-state">Загрузка…</div>
    </div>
    <div id="awaiting-wrap" hidden>
      <div class="page-sub">Что система ждёт от человека — читается при открытии вкладки, ничего не меняет.</div>
      <div id="awaiting-panel" class="card empty-state">Загрузка…</div>
    </div>
    <div class="hstack" style="margin-top:16px"><a class="btn btn-sm" href="#razbor">← Разбор</a></div>`;
  MONITORING_TABS.forEach(t => {
    document.getElementById(t.id)?.addEventListener("click", async (e) => {
      setActiveTab(e.currentTarget, MONITORING_TABS.filter(o => o.id !== t.id).map(o => o.id));
      MONITORING_TABS.forEach(o => { document.getElementById(o.panel).hidden = o.panel !== t.panel; });
      // 30.09.26: вкладка показывала данные момента открытия страницы — после распознавания или закрытия
      // карточки там долго висело прежнее. Теперь каждый переход по вкладке берёт свежие данные.
      if (t.panel === "monitoring-panel") {
        try { _monitoringCache = await api("/project-status/monitoring", {}); }
        catch (err) { toast("Не удалось обновить данные: " + err.message, true); }
      }
      window[t.render]();
    });
  });
  await loadAndRenderMonitoring();
  let openErrors = false;
  try { openErrors = sessionStorage.getItem("openSystemErrors") === "1"; sessionStorage.removeItem("openSystemErrors"); } catch (err) { /* нет */ }
  if (openErrors) document.getElementById("mon-tab-errors")?.click();
  if ((rest || [])[0] === "awaiting") document.getElementById("mon-tab-awaiting")?.click();
}

// «Модели» — отдельный пункт левой панели супер-администратора (владелец 09.10.26: «выбор модели вынесем отдельной
// вкладкой на панели слева»). Раньше — карточка в «Мониторинге RealTime», где её теснили службы и очереди.
async function renderModelsPage() {
  $main.innerHTML = `<div class="doc-head"><h1>Модели</h1>
      <span class="doc-head-meta">маршруты моделей по ролям · резервные цепочки · реестр подключений · доступ super_admin</span></div>
    <div id="model-routes" class="card">Загрузка…</div>`;
  await renderModelRoutes(document.getElementById("model-routes"), "/project-status/models");
}

// Решение 23.09.26 (SUPER_ADMIN_MONITORING.md) — раньше это был только файл-документ с инструкцией
// «как проверить руками» (SQL-запросы, ls -la и т.п.); по замечанию пользователя вынесено прямо в
// интерфейс живой панелью — GET /project-status/monitoring, только супер-админу.
const ROLE_LABELS_RU = { super_admin: "супер-админ", project_admin: "админ проекта", member: "участник" };

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} КБ`;
  return `${(n / 1024 / 1024).toFixed(1)} МБ`;
}

// Время по Москве явно, а не по часовому поясу браузера (решение 30.09.26, по находке Планёрки в
// её реестре передач — «04», п.23: сервер хранит время в UTC без отметки зоны, браузер по
// умолчанию считает его местным и показывает не то время, если открывающий не в Москве). Раньше
// было "ru-RU" без timeZone — работало верно только пока у смотрящего тоже Москва на часах.
function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso + "Z").toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
}

let _monitoringCache = null;

// «Вернуть в распознавание» прямо со строки контроля (решение владельца 12.10.26). Права проверяет
// сервер — панель доступна только супер-администратору.
async function вернутьВРаспознавание(событие) {
  const кнопка = событие.currentTarget || событие;      // после await currentTarget = null (02.10.26)
  const job = Number(кнопка.dataset.resumeJob);
  if (!job) return;
  кнопка.disabled = true;
  try {
    const ответ = await api("/project-status/recognition/resume", { method: "POST", json: { job_id: job } });
    toast(ответ.detail || "Запись снова в очереди распознавания");
    await loadAndRenderMonitoring(renderMonitoringLive);
  } catch (e) {
    toast(e.message, true);
    кнопка.disabled = false;
  }
}

async function loadAndRenderMonitoring(renderFn = renderMonitoringRuns) {
  const $box = document.getElementById("monitoring-panel");
  if (!$box) return;
  try { _monitoringCache = await api("/project-status/monitoring", {}); }
  catch (e) { $box.className = "card empty-state"; $box.textContent = "Не удалось загрузить параметры системы."; return; }
  $box.className = "";
  renderFn();
}

// Норма открытых конфликтов (решение владелицы 18.10.2026, как в Планёрке): администратор разбирает около 15 карточек;
// больше — повод смотреть на работу системы. Больше нормы — спокойная плашка предупреждения из существующей палитры.
function нормаКонфликтовHtml(н) {
  if (!н) return "";
  const виды = Object.entries(н.by_kind || {}).map(([k, n]) => `${esc(CONFLICT_FIELD_LABELS[k] || "прочее")}: ${n}`).join(" · ");
  return `<div class="mon-lead" id="conflicts-norm-line">Открытых конфликтов: <b>${н.open}</b> (норма ≤ ${н.norm})${н.over
    ? ` <span class="badge badge-warning">больше нормы</span>` : ""}${виды ? ` · ${виды}` : ""}</div>`;
}

// Суперадмин один (решение владелицы 19.10.2026, восстановление пароля суперадмина «А + Б»): забытый пароль суперадмина
// сбрасывает другой суперадмин в «Команде». Пока суперадмин один — тихая строка рядом с нормой конфликтов, тем же видом,
// без новых цветов; кого назначить вторым, решает владелица. Два и больше (или ноль — тестовый режим) — строки нет.
function одинСуперадминHtml(n) {
  return n === 1 ? `<div class="mon-lead" id="superadmin-single-line">Суперадмин один — назначьте второго, чтобы было кому сбросить пароль</div>` : "";
}

// «Мониторинг RealTime» — отдельный пункт левого меню супер-админа (решение владельца 02.10.26: «Служба и очередь вынеси
// в вертикальную вкладку для супер-админа и назови Мониторинг RealTime»; у Планёрки так же). То, что меняется каждую минуту:
// службы, распознавание, очередь, автозапуск. Данные обновляются сами каждые 30 секунд, пока страница открыта; ввод в поле
// папки-приёмника обновление не перебивает.
let _liveTimer = null;
async function renderMonitoringRealtime() {
  $main.innerHTML = `<div class="doc-head"><h1>Мониторинг</h1>
      <span class="doc-head-meta" id="live-stamp">службы, распознавание, очередь, автозапуск — обновляется каждые 30 секунд</span></div>
    <div id="monitoring-panel" class="card empty-state">Загрузка…</div>`;
  await loadAndRenderMonitoring(renderMonitoringLive);
  clearInterval(_liveTimer);
  _liveTimer = setInterval(async () => {
    if (currentRouteParts()[0] !== "live") { clearInterval(_liveTimer); return; }
    const active = document.activeElement;
    if (active && active.closest && active.closest("#monitoring-panel") && /INPUT|TEXTAREA|SELECT/.test(active.tagName)) return;
    try { _monitoringCache = await api("/project-status/monitoring", {}); renderMonitoringLive(); } catch (e) { /* следующая попытка через 30 с */ }
  }, 30000);
}

// Панель «Параметры системы» по образцу Планёрки (решение владельца 30.09.26: «все вкладки под Планёрку»,
// снимки экрана её вехи 3). Каждая карточка — заголовок (иногда с меткой) и строки «название | значение |
// пояснение»; служба — «живо / нет / выкл.», где «выкл.» — нарочно выключенное, это не сбой.
// «Мониторинг»: расход за сегодня одной строкой (поручение владельца 15.10.26, п. 4); подробно — «Параметры системы → Расход»

// Предел расхода поставщика на месяц (решение владельца 15.10.26; общий с Планёркой tariffs.py). Без предела — только счёт;
// с пределом — 90 % предупреждение, 100 % вызовы этого поставщика остановлены (точки других поставщиков работают).
// У OpenRouter ключ общий для систем, а журнал у каждой свой — подпись (Планёрка e3cc4f8, согласовано с «Мониторингом»).
const ПОДПИСЬ_OPENROUTER = "только вызовы этой системы; общий счёт ключа — в кабинете поставщика";
// Д9 «Мониторинга» 15.10.26: деньги — одним видом на всех экранах расхода: запятая, 2–3 знака («0,00 $», «0,211 $»,
// «28,576 $»); рядом стояли «0.000 $» с точкой и «0,00 $» с запятой
const долларыРу = (v) => `${Number(v || 0).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 3 })} $`;
// «Задачи под вопросом: N» (решение владельца 15.10.26) и выключатель отметки в реестре — временный на пилот

// --- Общая «Команда» двух систем: карточка выключателя (решение владелицы 18.10.2026; одинакова в ERP и Планёрке) ---
// Параметр хранится в базе системы, меняет только суперадминистратор. Путь к общему файлу не показывается — только
// «найден / не найден» и последняя ошибка сверки без пути. TEAM_SHARED=off — аварийный выключатель, сильнее параметра.
function командаОбщаяКарточка(ст) {
  const параметр = ст.param !== false;
  return `<div class="card stack" id="team-shared-card">
      <div class="doc-heading">Общая «Команда» двух систем</div>
      <div>Сейчас: <b id="team-shared-state">${ст.enabled === true ? "Включена" : "Выключена"}</b></div>
      ${ст.env_off ? `<div class="page-sub"><b>Общая «Команда» аварийно выключена переменной TEAM_SHARED=off</b> — пока переменная задана,
        параметр не действует (параметр: ${параметр ? "включена" : "выключена"}).</div>` : ""}
      <div class="page-sub">Общий файл: ${ст.file_found ? "найден" : "не найден"}${ст.reason ? ` — ${esc(ст.reason)}` : ""}</div>
      ${ст.last_error ? `<div class="page-sub">Последняя ошибка сверки: ${esc(ст.last_error)}</div>` : ""}
      <div class="page-sub">Решение владелицы 18.10.2026: ФИО, должность, отдел, роль на проекте, организация и признак
        «внешний» у подтверждённых людей — одни на Проект ERP и Планёрку, правка в одной системе видна в другой. Вход, права
        и почта у каждой системы свои. Выключенная — система работает со своей «Командой», общий файл не открывается, уже
        перенесённые люди остаются. Меняет только суперадминистратор; смена записывается в технические сообщения.</div>
      <div><button class="btn-primary" id="team-shared-toggle-btn">${параметр ? "Выключить" : "Включить"}</button></div>
    </div>`;
}

function командаОбщаяПривязать(задать) {
  document.getElementById("team-shared-toggle-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const включить = btn.textContent.trim() === "Включить";
    btn.disabled = true;
    try {
      const ст = await задать(включить);
      const карточка = document.getElementById("team-shared-card");
      if (карточка) карточка.outerHTML = командаОбщаяКарточка(ст);
      командаОбщаяПривязать(задать);
      toast(включить ? "Общая «Команда» включена" : "Общая «Команда» выключена: система работает со своей «Командой»");
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

// --- «Сборка протокола»: режим извлечения поручений и режим договорённостей (19.10.2026, Е1 + Е2 списка отставания) ---
// Как карточки «Извлечение поручений» и «Договорённости» в «Настройках» Планёрки: меняет только суперадминистратор,
// действует со следующей сборки, собранные протоколы не пересобираются.
// --- Проект системы (задание 23.10.2026): по нему план встречи отбирает строки «из материала» ---
// ERP — система одного проекта. Не задан — проект встречи берётся из повестки; не определён и там — в план идут только задачи
// реестра и пункты по теме повестки, а в «Справочно» строка «Проект встречи не определён — укажите проект в «Параметрах
// системы»». Меняет только суперадминистратор; смена записывается в технические сообщения.
async function карточкаПроектаСистемы() {
  const $c = document.getElementById("system-project-card");
  if (!$c) return;
  let п;
  let подпроекты = { items: [] };
  try { п = await api("/project-status/system-project"); } catch (e) { $c.querySelector(".page-sub").textContent = e.message; return; }
  try { подпроекты = await api("/project-status/system-subprojects"); } catch (e) { /* справочник подпроектов не прочитан — поле пустое */ }
  $c.innerHTML = `<div class="doc-heading">Проект системы</div>
    <div class="field"><label for="system-project-name">Проект системы</label>
      <input type="text" id="system-project-name" value="${esc(п.name || "")}" placeholder="не задан — проект встречи берётся из повестки" autocomplete="off"></div>
    <div class="field"><label for="system-project-aliases">Варианты написания</label>
      <input type="text" id="system-project-aliases" value="${esc(п.aliases || "")}" placeholder="через «;» — как пишут в протоколах и на слух" autocomplete="off"></div>
    <div class="page-sub">По проекту системы план встречи отбирает строки «из материала»: в таблицу идут пункты, где назван этот
      проект (или вариант написания), задачи реестра и пункты по теме повестки; пункты про другие проекты — одной строкой
      «Прочие проекты из материала». Действует со следующей сборки плана, собранные планы не меняются.</div>
    <div><button class="btn-sm" id="system-project-save-btn">Сохранить проект</button></div>
    <div class="field"><label for="system-subprojects">Подпроекты проекта</label>
      <textarea id="system-subprojects" rows="3" placeholder="подпроектов нет — по одному названию в строке">${esc((подпроекты.items || []).map(x => x.name).join("\n"))}</textarea></div>
    <div class="page-sub">Подпроекты — те же записи, что на вкладке «Проекты» (проект с надпроектом): новое название здесь заводит
      подпроект, убранное уходит в архив, его встречи и задачи остаются при нём. Задача и встреча относятся к проекту всегда,
      подпроект — необязательно и только из этого списка. Нет подпроектов — фильтр проекта показывает один пункт
      «${esc(подпроекты.all || "Весь проект")}». Варианты написания подпроекта и надпроект — на вкладке «Проекты».</div>
    <div><button class="btn-sm" id="system-subprojects-save-btn">Сохранить подпроекты</button></div>`;
  document.getElementById("system-subprojects-save-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const items = document.getElementById("system-subprojects").value.split("\n").map(s => s.trim()).filter(Boolean).map(name => ({ name }));
      const ответ = await api("/project-status/system-subprojects", { method: "POST", json: { items } });
      toast((ответ.items || []).length ? `Подпроектов: ${ответ.items.length}` : "Подпроектов нет");
      карточкаПроектаСистемы();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
  document.getElementById("system-project-save-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const ответ = await api("/project-status/system-project", { method: "POST", json: {
        name: document.getElementById("system-project-name").value, aliases: document.getElementById("system-project-aliases").value } });
      toast(ответ.name ? `Проект системы: ${ответ.name} — со следующей сборки плана` : "Проект системы не задан");
      карточкаПроектаСистемы();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

const РЕЖИМЫ_ИЗВЛЕЧЕНИЯ = { topics: "по темам протокола", chunks: "кусками записи", draft: "только из черновика (прежний путь ERP)" };
async function карточкаНастроекСборки() {
  const $c = document.getElementById("sborka-settings-card");
  if (!$c) return;
  let н;
  try { н = await api("/agreements/settings"); } catch (e) { $c.querySelector(".page-sub").textContent = e.message; return; }
  $c.innerHTML = `<div class="doc-heading">Сборка протокола</div>
    <div>Поручения: <b id="extract-mode-state">${esc(РЕЖИМЫ_ИЗВЛЕЧЕНИЯ[н.extract_mode] || н.extract_mode)}</b></div>
    <div class="page-sub">По темам (по умолчанию, как в Планёрке) — после черновика отдельный вызов на каждую тему протокола,
      проект — только из справочника и только прозвучавший в теме. Кусками — тот же вызов по кускам записи. Только из
      черновика — прежний путь: задачи пишет один вызов сборки. Для сравнения на одной встрече.</div>
    <div class="field"><select id="extract-mode-select" aria-label="Режим извлечения поручений">${(н.extract_modes || Object.keys(РЕЖИМЫ_ИЗВЛЕЧЕНИЯ))
      .map(k => `<option value="${esc(k)}"${k === н.extract_mode ? " selected" : ""}>${esc(РЕЖИМЫ_ИЗВЛЕЧЕНИЯ[k] || k)}</option>`).join("")}</select>
      <button class="btn-sm" id="extract-mode-save-btn">Сохранить режим</button></div>
    <div style="margin-top:12px">Договорённости: <b id="agreements-mode-state">${н.agreements_mode === "on" ? "включены" : "в тени"}</b></div>
    <div class="page-sub">Включены — решения и открытые вопросы обычными предложениями (без «Решили» и «Открытый вопрос») в разделах тем протокола. В тени — реестр
      копится для администраторов, документ не меняется. Реестр и вкладка «Договорённости встречи» — только администраторам.</div>
    <div><button class="btn-primary" id="agreements-mode-toggle-btn">${н.agreements_mode === "on" ? "Перевести в тень" : "Включить"}</button></div>`;
  const задать = async (тело, текст) => {
    try { await api("/agreements/settings", { method: "POST", json: тело }); toast(текст); карточкаНастроекСборки(); }
    catch (e) { toast(e.message, true); }
  };
  document.getElementById("extract-mode-save-btn")?.addEventListener("click", () => {
    const v = document.getElementById("extract-mode-select").value;
    задать({ extract_mode: v }, `Поручения: ${РЕЖИМЫ_ИЗВЛЕЧЕНИЯ[v] || v} — со следующей сборки`);
  });
  document.getElementById("agreements-mode-toggle-btn")?.addEventListener("click", () => {
    const включить = н.agreements_mode !== "on";
    задать({ agreements_mode: включить ? "on" : "shadow" }, включить ? "Договорённости включены" : "Договорённости в тени");
  });
}

// Короткая инструкция к паролям — значок «i» рядом со строкой «Общий пароль» и у колонки входа «Команды» суперадмина
// (решение владелицы 19.10.2026). Значок — общий `.tip` / `.tip-ico` / `.tip-body`, как у остальных подсказок. Текст —
// близнец Планёрки до буквы (сведение 19.10.2026, взят из `ПОДСКАЗКА_ПАРОЛЕЙ` Планёрки, места названы для обеих систем).
const ПОДСКАЗКА_ПАРОЛЕЙ = "Все, кроме администраторов и суперадмина, входят по общему паролю — один на всех. Администраторы "
  + "и суперадмин — по личному, общий им не подходит. Общий пароль меняет суперадмин в строке «Общий пароль»: после смены "
  + "сессии всех, кто вошёл по общему паролю, завершатся, войти нужно по новому. Сбросить пароль администратору — «Сбросить "
  + "пароль» в «Команде», у его имени: временный пароль показывается один раз и действует 24 часа, передайте его лично; при "
  + "входе человек обязательно задаёт свой, и его не видит никто. Забыли пароль: кто входит по общему — к суперадмину за "
  + "общим паролем; администратор — к суперадмину за сбросом. Суперадмин забыл пароль: пароль сбрасывает другой суперадмин "
  + "в «Команде»; если других нет — техническая служба запускает на сервере скрипт сброса (временный пароль на 24 ч).";
function подсказкаПаролейHtml() {
  return `<span class="tip"><button type="button" class="tip-ico" aria-label="Как устроены пароли">i</button><span class="tip-body" role="tooltip">${esc(ПОДСКАЗКА_ПАРОЛЕЙ)}</span></span>`;
}

// Общий пароль участников (решение владелицы 18.10.2026, перенос из Планёрки 19.10.2026): задаёт и меняет только суперадмин.
// Сервер хранит только хэш и наружу отдаёт лишь «задан / не задан» и дату смены. Смена выводит всех, кто вошёл по общему
// паролю. С 19.10.2026 личный пароль суперадмина здесь не спрашивается (решение владелицы, как в Планёрке).
async function настроитьОбщийПароль() {
  const $состояние = document.getElementById("shared-password-state");
  const $кнопка = document.getElementById("settings-shared-password");
  if (!$состояние || !$кнопка) return;
  const показать = (s) => {
    $состояние.textContent = s.is_set ? `задан ${s.set_at || ""} — участникам; администраторы входят по личному`
      : "не задан — участники войти не могут";
    $кнопка.textContent = s.is_set ? "Сменить" : "Задать";
  };
  try { показать(await api("/project-status/shared-password")); } catch (e) { $кнопка.hidden = true; return; }
  $кнопка.addEventListener("click", () => {
    openModal("Общий пароль участников", `
      <div class="page-sub" style="margin-bottom:12px">Один пароль на всех участников. Администраторам он не подходит.
        После смены прежний пароль перестаёт действовать, все, кто вошёл по общему паролю, выйдут из системы и войдут уже по новому.</div>
      <div class="field"><label for="shared-new">Новый общий пароль <span class="req">*</span></label><input type="password" id="shared-new" autocomplete="new-password"></div>
      <div class="field"><label for="shared-new2">Повторите <span class="req">*</span></label><input type="password" id="shared-new2" autocomplete="new-password"></div>
    `, async (ov) => {
      // Без подтверждения личным паролем суперадмина (решение владелицы 19.10.2026): новый и повтор; проверки — как в Планёрке
      const новый = ov.querySelector("#shared-new").value, повтор = ov.querySelector("#shared-new2").value;
      if (!новый) throw new Error("Введите новый общий пароль");
      if (новый !== повтор) throw new Error("Пароли не совпадают");
      const ответ = await api("/project-status/shared-password", { method: "POST",
        json: { new_password: новый, repeat_password: повтор } });
      показать(ответ);
      toast(`Общий пароль сохранён. Вышли из системы: ${ответ.sessions_closed}`);
    });
  });
}

// «Параметры системы» → «Настройки»: отметка «под вопросом» в реестре (текст — как у Планёрки)
async function renderSettingsTab() {
  const $box = document.getElementById("monitoring-panel");
  if (!$box) return;
  let в = { mark_enabled: true };
  try { в = { mark_enabled: (await api("/project-status/under-question-mark")).enabled !== false }; } catch (e) { /* по умолчанию — включено */ }
  $box.className = "";                      // как у соседних вкладок: рамку даёт сама карточка
  $box.innerHTML = `<div class="card stack"><div class="field">
      <label style="display:flex; gap:8px; align-items:center"><input type="checkbox" id="setting-doubt-mark"${в.mark_enabled ? " checked" : ""}>
        Отметка «под вопросом» в реестре</label>
      <div class="page-sub">Неброская точка у задачи, заведённой под вопросом; видят только администраторы. Временная на пилот
        (решение владельца 15.10.2026). Выключенная — точки нет; карточки в «Конфликтах» и счётчики остаются.</div>
    </div></div>` +
    // Проект системы (задание 23.10.2026) — здесь, а не на «Диске и доступах»: записка ЛМ ведёт в «Настройки» (отчёт ЛМ
    // 23.10.2026 — карточку там не нашли); суперадминистратору
    (isSuperAdmin() ? `<div class="card stack" id="system-project-card"><div class="doc-heading">Проект системы</div><div class="page-sub">Загрузка…</div></div>` : "");
  if (isSuperAdmin()) карточкаПроектаСистемы();
  карточкаУзкогоПорога($box);       // выключатель узкого порога задачи (24.10.2026), суперадминистратору
  if (typeof карточкаТемПланёрок === "function") карточкаТемПланёрок($box);   // «Темы планёрок» (24.10.2026, tema.js)
  карточкаРаспознавания($box);     // словарь Whisper и «проект только при прозвучавшем» (24.10.2026)
  const ф = document.getElementById("setting-doubt-mark");
  ф.addEventListener("change", async () => {
    ф.disabled = true;
    try {
      const ответ = await api("/project-status/under-question-mark", { method: "POST", json: { enabled: ф.checked } });
      const итог = { mark_enabled: ответ.enabled !== false };
      отметкаВопроса = отметкаПодВопросомВключена = итог.mark_enabled;
      toast(итог.mark_enabled ? "Отметка «под вопросом» в реестре включена" : "Отметка «под вопросом» в реестре выключена");
    } catch (e) { ф.checked = !ф.checked; toast(e.message, true); }
    ф.disabled = false;
  });
}


function monSection(title, bodyHtml, chip) {
  return `<div class="card card-output mon-section"><h3>${esc(title)}${chip ? `<span class="mon-chip">${esc(chip)}</span>` : ""}</h3>${bodyHtml}</div>`;
}


// rows: [label, valueHtml, noteHtml] — значение и пояснение уже готовый HTML (экранирует вызывающий).
function monTable(rows) {
  return `<table class="mon-table mon-3"><tbody>${rows.filter(Boolean).map(([label, value, note]) =>
    `<tr><td class="mon-label">${esc(label)}</td><td class="mon-value">${value ?? "—"}</td><td class="mon-note">${note || ""}</td></tr>`).join("")}</tbody></table>`;
}

// Состояние — тем же значком, что в Планёрке (`svcRow`): «живо / нет / выкл.» плашкой, а не цветным
// текстом. Оформление служебных экранов у двух продуктов одно (указание владельца 05.10.26).
// Выравнивание вида 17.10.26 (решение владельца): плашки — как у Планёрки стенда: «живо» — успех, «нет» — тревога,
// «выкл.» — нейтральная, одним словом (sv-pill).
function monState(ok) {
  if (ok === true) return `<span class="badge badge-success sv-pill">живо</span>`;
  if (ok === false) return `<span class="badge badge-danger sv-pill">нет</span>`;
  return `<span class="badge badge-neutral sv-pill">выкл.</span>`;
}

function monLead(text) {
  return `<div class="mon-lead">${esc(text)}</div>`;
}

// «Ожидает ввода от оператора» — отдельная вкладка супер-админа (решение владельца 05.10.26: «пиши в
// мониторинг системы, если система ожидает какого-то ввода от оператора, иначе не понятно»). Панель
// «Мониторинг RealTime» отвечает «служба жива или нет», а эта — «что стоит и ждёт ответа человека»:
// сколько ждёт, чего именно, где ответить и что будет, если не ответить. Данные только читаются.
// С 09.10.26 — вкладка «Параметров системы»: старый адрес #awaiting ведёт туда.
async function renderAwaitingInput() {
  location.replace("#system/awaiting");
}

async function renderAwaitingTab() {
  const $box = document.getElementById("awaiting-panel");
  if (!$box) return;
  $box.className = "card empty-state";
  $box.textContent = "Загрузка…";
  let data;
  try {
    data = await api("/project-status/awaiting-input", {});
  } catch (e) {
    $box.className = "card";
    $box.textContent = `Не удалось получить список: ${e.message}`;
    return;
  }
  if (!data.groups.length) {
    $box.className = "card mon-section";
    $box.innerHTML = `<h3>Ничего не ждёт ответа<span class="mon-chip">Москва ${esc(moscowNow())}</span></h3>
      <div class="mon-lead">Все вопросы к человеку закрыты: карточек «Конфликтов» нет, записи распознаны,
        черновиков на принятие нет, технических сообщений нет. Список обновится сам, когда что-то появится.</div>`;
    return;
  }
  const карточки = data.groups.map(g => {
    const строки = monTable([
      ["Сколько ждёт", `<b>${g.count}</b>`, g.oldest ? `самое старое — ${esc(g.oldest)}` : ""],
      ["Что нужно", esc(g.what), ""],
      ["Если не ответить", esc(g.consequence), `<a href="${g.where}">${esc(g.where_text)}</a>`],
    ]);
    const подробности = (g.details || []).length
      ? `<div class="page-sub" style="margin:6px 0 0">Из чего состоит: ${g.details.map(d => `${esc(d.label)} — ${d.count}`).join(" · ")}</div>` : "";
    const примеры = (g.examples || []).length
      ? `<div class="page-sub" style="margin:6px 0 0">Например: ${g.examples.map(x => `«${esc(x)}»`).join(", ")}</div>` : "";
    return monSection(g.title, строки + подробности + примеры, `жал. ${g.count}`);
  }).join("");
  $box.className = "";
  $box.innerHTML = monLead(`${esc(data.note)} Всего ждёт ответа: ${data.total}.`)
    + (data.under_question ? `<div class="mon-lead">Задачи под вопросом: <b>${data.under_question}</b> — <a href="#razbor/tasks">«Разбор»</a>.</div>` : "") + карточки +
    `<div class="hstack" style="margin-top:10px"><button class="btn-sm" id="awaiting-reload">Обновить список</button>
      <span class="page-sub">Открыть «Мониторинг» — <a href="#live">службы и очереди</a></span></div>`;
  document.getElementById("awaiting-reload")?.addEventListener("click", renderAwaitingTab);
}

// Время по Москве для отбивки — тем же правилом, что в «Мониторинге», независимо от часового пояса машины.
function moscowNow() {
  return new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit",
    year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date());
}

// Экран «Разбор голосов» — блок суперадминистратора (задание владелицы 21.10.2026; близнец по смыслу в Планёрке).
// Новые отпечатки общей базы голосов, сгруппированные по говорящему встречи и по предполагаемому человеку. По каждому
// говорящему — отрывки (если вырезаны при распознавании), реплика, встреча и время, предложенное ФИО с косинусом и
// отрывом. Решение «Это он» / «Не он» / «Другой человек» (из «Команды») / «Шум / не голос» сразу меняет общую базу
// двух систем; отрывок после решения удаляется на сервере, подсказка голоса в «Конфликтах» закрывается сама.
// Галочка у отпечатка — входит ли он в решение: снятый остаётся на разбор. Отпечатки без строки на экране (больше 12 у
// говорящего или без отрывка и реплики) входят в решение всегда.
// 25.10.2026 (замечание владелицы): в очереди только непонятные — «вероятно» и «не узнан». Опознанные правилом к
// подтверждённому человеку сервер отмечает «принято по правилу» и в очередь не отдаёт. Два вида-переключателя внутри
// страницы: «На проверку» (по умолчанию; счётчик меню — только он) и «Опознанные и решённые» — принятые правилом и
// решённые людьми, только просмотр; у принятых правилом — «Не он» (вернуть в очередь «не узнан»).
// Отрывок: битый файл сервер не отдаёт (404 с причиной), плеер при ошибке воспроизведения заменяется словами
// «отрывок повреждён».
// 26.10.2026 (замечание владелицы: «зачем вывод „реплики нет“ и „отрывок не сохранён“ — не выводить»): сервер отдаёт
// только строки с отрывком или репликой, пустое место ячейки — пустая ячейка; говорящий, которому нечего дать послушать
// и прочитать, в «На проверку» не выводится, под шапкой — одна строка «без материала для проверки: N» при N > 0.
// «Это он» — по кандидату говорящего, если он однозначно находится в «Команде» (`kandidat_v_komande`): у «не узнан»
// и «вероятно» с предложенным кандидатом кнопка была серой.
// Два почти равных кандидата (решение владелицы 26.10.2026): у «не узнан», где отрыв меньше отрыва правила
// (`dva_kandidata` с сервера), вместо «Предложено: А — близость…, отрыв… (второй — Б, …)» — «Похож на: А (0,52) или
// Б (0,50)» и кнопки «Это А», «Это Б» (каждая — если кандидат однозначно в «Команде»: `kandidat_v_komande`,
// `vtoroy_v_komande`), «Не они», «Другой человек», «Шум». Решение уходит с именем выбранного из базы голосов и
// признаком, какой из двух выбран (`vybran`). У «вероятно» и при явном отрыве — как раньше.
const ГОЛОС_СТАТУС = { confirmed: "опознан по правилу", hint: "вероятно", none: "не узнан" };
const числоЗапятой = (x, n = 2) => (Number(x) || 0).toFixed(n).replace(".", ",");
const ВР_ВКЛ = { ряд: "rz-views", вкладка: "rz-view", вкл: "rz-view-on" };   // как вкладки видов «Разбора» в обеих системах (25.10.2026, дефекты экранов перед видео, п. 7)
let vrВид = "proverka";
// Статус говорящего — заметной меткой в шапке раздела, группы и говорящего, а не курсивом в конце строки (25.10.2026:
// «где искать блоки „не узнан“ — не вижу»). На проверку два раздела: «Вероятно» (серая зона) и «Не узнан».
const ГОЛОС_МЕТКА = { confirmed: "badge-success", hint: "badge-warning", none: "badge-danger" };
const меткаГолоса = (статус) => `<span class="badge ${ГОЛОС_МЕТКА[статус] || "badge-neutral"}">${esc(ГОЛОС_СТАТУС[статус] || статус || "")}</span>`;                 // «На проверку» | «Опознанные и решённые» (resheno)

async function отрывокАдрес(id) {
  // <audio src> не несёт заголовков личности режима тестирования — звук берём запросом и отдаём плееру ссылкой на blob
  const заголовки = (!authRequired && me) ? { "X-User-Id": String(me.id) } : {};
  const ответ = await fetch(`/voice/review/clip/${id}`, { headers: заголовки });
  if (!ответ.ok) {
    const т = await ответ.json().catch(() => ({}));
    throw new Error(т.detail || (ответ.status === 404 ? "отрывка нет" : `не удалось получить отрывок (${ответ.status})`));
  }
  return URL.createObjectURL(await ответ.blob());
}

async function renderVoiceReview() {
  const мой = location.hash;
  $main.innerHTML = `<h1>Разбор голосов</h1>
    <div class="page-sub">Новые отпечатки общей базы голосов Планёрки и ERP — кто говорит. Решение сразу меняет общую базу
      обеих систем: «Это он» и «Другой человек» кладут отпечатки в центр человека, «Не он» и «Шум» больше не предлагаются.
      Отрывок звука хранится только до решения. Говорящие, которых правило уже опознало к подтверждённому человеку, и уже
      решённые сюда не выводятся — они во втором виде «Опознанные и решённые».</div>
    <div id="vr-body" class="empty-state">Загрузка…</div>`;
  let д;
  try { д = await api("/voice/review", {}); }
  catch (e) { document.getElementById("vr-body").innerHTML = `<div class="card">Не удалось получить очередь: ${esc(e.message)}</div>`; return; }
  if (location.hash !== мой) return;          // ушли на другой экран, пока очередь грузилась
  _значки.voice_review = д.klasterov || 0;
  показатьЗначки();
  if (!д.configured) {
    document.getElementById("vr-body").outerHTML = `<div class="card" id="vr-body">Общая база голосов недоступна: ${esc(д.reason || "")}</div>`;
    return;
  }
  const п = д.pravilo || {};
  const рш = д.reshennye || { klasterov: 0, po_pravilu: 0, lyudmi: 0, klastery: [] };
  const вкладки = `<nav class="${ВР_ВКЛ.ряд} vr-vidy" role="tablist">
      <a class="${ВР_ВКЛ.вкладка}${vrВид === "proverka" ? " " + ВР_ВКЛ.вкл : ""}" href="${esc(мой)}" data-vid="proverka" role="tab">На проверку <span class="n">${д.klasterov}</span></a>
      <a class="${ВР_ВКЛ.вкладка}${vrВид === "resheno" ? " " + ВР_ВКЛ.вкл : ""}" href="${esc(мой)}" data-vid="resheno" role="tab">Опознанные и решённые <span class="n">${рш.klasterov}</span></a></nav>`;
  const решённыеHtml = `<div class="card">Опознаны по правилу без разбора: <b>${рш.po_pravilu}</b> говорящих, решены людьми: <b>${рш.lyudmi}</b>.
      Только просмотр. Принятые правилом в эталон не идут; если правило ошиблось — «Не он»: говорящий вернётся на проверку
      как «не узнан».${рш.klastery.length < рш.klasterov ? ` Показаны последние ${рш.klastery.length}.` : ""}</div>
    ${рш.klastery.length ? `<div class="table-scroll"><table class="doc-table vr-table"><thead><tr><th>Встреча</th><th>Говорящий</th><th>Решение</th><th>Кто это</th><th>Отпечатков</th><th>Основание</th><th>Когда</th><th></th></tr></thead><tbody>
      ${рш.klastery.map((к, н) => `<tr data-vr-key="${esc(ключГолоса(к))}"><td>${esc(к.vstrecha || к.data)}</td><td>${esc(к.label || "без метки")}</td><td>${esc(к.reshenie_tekst)}</td>
        <td>${esc(к.imya || "—")}</td><td>${к.vsego}</td><td class="page-sub">${esc(к.pravilo || к.kto || "")}</td><td>${esc(к.kogda || "")}</td>
        <td>${к.ne_on ? `<button class="btn-sm vr-ne-on" type="button" data-n="${н}">Не он</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : '<div class="card empty-state">Решённых и опознанных правилом пока нет.</div>'}`;
  const виды = ($тело) => {
    $тело.querySelectorAll(".vr-k").forEach(с => с.addEventListener("click", (e) => {
      e.preventDefault();
      document.getElementById(`vr-razdel-${с.dataset.k}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    $тело.querySelectorAll(".vr-vidy [data-vid]").forEach(в => в.addEventListener("click", (e) => {
      e.preventDefault();
      if (vrВид === в.dataset.vid) return;
      vrВид = в.dataset.vid;
      renderVoiceReview();
    }));
    $тело.querySelectorAll(".vr-ne-on").forEach(кн => кн.addEventListener("click", async () => {
      const к = рш.klastery[Number(кн.dataset.n)];
      кн.disabled = true;
      try {
        const итог = await api("/voice/review/ne-po-pravilu", { method: "POST", json: { ids: к.ids } });
        toast(`Возвращено на проверку как «не узнан»: отпечатков ${итог.vozvrasheno}`);
        renderVoiceReview();
      } catch (e) { кн.disabled = false; toast(e.message, true); }
    }));
  };
  if (vrВид === "resheno") {
    document.getElementById("vr-body").outerHTML = `<div id="vr-body">${вкладки}${решённыеHtml}</div>`;
    виды(document.getElementById("vr-body"));
    return;
  }
  const поСтатусу = (ст) => д.gruppy.filter(г => г.status === ст).reduce((n, г) => n + г.klastery.length, 0);
  const шапка = `<div class="card">Ждут разбора: <b>${д.klasterov}</b> говорящих —
    <a href="${esc(мой)}" class="vr-k" data-k="hint">${меткаГолоса("hint")} ${поСтатусу("hint")}</a>,
    <a href="${esc(мой)}" class="vr-k" data-k="none">${меткаГолоса("none")} ${поСтатусу("none")}</a>; отпечатков <b>${д.otpechatkov}</b>, с отрывком
    для прослушивания — <b>${д.s_otryvkom}</b>.<br>Предложение — по правилу опознания: «опознан» при близости не ниже
    ${числоЗапятой(п.porog)} и отрыве от второго кандидата не ниже ${числоЗапятой(п.otryv)}, «вероятно» — от ${числоЗапятой(п.podskazka)}.
    Эталон сейчас: людей ${д.etalon.lyudey}, отпечатков ${д.etalon.otpechatkov}.${д.etalon_net ? `<br>${esc(д.etalon_net)}` : ""}
    ${д.otryvki && д.otryvki.otryvki === false ? "<br>Вырезание отрывков выключено (VOICE_REVIEW_CLIPS=off): по отпечаткам — текст реплики и время." : ""}</div>`;
  const безМатериала = д.bez_materiala > 0 ? `<div class="page-sub vr-bez">без материала для проверки: ${д.bez_materiala}</div>` : "";
  if (!д.gruppy.length) {
    document.getElementById("vr-body").outerHTML = `<div id="vr-body">${вкладки}${шапка}${безМатериала}<div class="card empty-state">Непонятных голосов нет — разбирать нечего.</div></div>`;
    виды(document.getElementById("vr-body"));
    return;
  }
  // Аккаунт ВКС — подсказка, не имя (решение владелицы 25.10.2026, «имя сначала по голосу»): голос не опознан — готовое
  // предложение «аккаунт ВКС: Иванов?», человек из «Команды» уже выбран в «Другой человек…», подтверждение одним нажатием;
  // с аккаунта говорили несколько голосов — пометка, без предложения.
  const команда = (выбран = "") => (д.komanda || []).map(и => `<option value="${esc(и)}"${и === выбран ? " selected" : ""}>${esc(и)}</option>`).join("");
  const кластерHtml = (г, к, номер) => {
    const строки = к.otpechatki.map(о => `<tr>
        <td><input type="checkbox" class="vr-take" data-id="${о.id}" checked aria-label="Включить отпечаток в решение"></td>
        <td>${esc(о.vremya || "—")}</td><td>${числоЗапятой(о.seconds, 1)} с</td>
        <td>${о.phrase ? esc(о.phrase) : ""}</td>
        <td>${о.otryvok ? `<button class="btn-sm vr-play" type="button" data-id="${о.id}">Слушать</button>` : ""}</td></tr>`).join("");
    const предложено = к.kandidat
      ? `${esc(к.kandidat)} — близость ${числоЗапятой(к.cosine)}, отрыв ${числоЗапятой(к.gap)}${к.second ? ` (второй — ${esc(к.second)}, ${числоЗапятой(к.second_cosine)})` : ""}`
      : "кандидата нет";
    const можноЭтоОн = !!к.kandidat && !!к.kandidat_v_komande;
    const можноЭтоБ = !!к.second && !!к.vtoroy_v_komande;
    const неВКоманде = "нет в «Команде» полным ФИО — выберите в «Другой человек»";
    let строкаКандидата = `Предложено: ${предложено}`;
    let кнопкиКандидата = `<button class="btn-primary vr-do" type="button" data-r="yes" ${можноЭтоОн ? "" : "disabled"}
          title="${esc(можноЭтоОн ? "Подтвердить: это " + к.kandidat_v_komande : (к.kandidat ? неВКоманде : "Кандидата нет — выберите «Другой человек»"))}">Это он</button>
        <button class="btn-sm vr-do" type="button" data-r="no" ${к.kandidat ? "" : "disabled"}>Не он</button>`;
    if (к.dva_kandidata) {
      // два почти равных — оба на равных, кнопка на каждого (решение владелицы 26.10.2026)
      строкаКандидата = `Похож на: ${esc(к.kandidat)} (${числоЗапятой(к.cosine)}) или ${esc(к.second)} (${числоЗапятой(к.second_cosine)})`;
      кнопкиКандидата = `<button class="btn-primary vr-do" type="button" data-r="yes" data-kto="pervyy" ${можноЭтоОн ? "" : "disabled"}
          title="${esc(можноЭтоОн ? "Подтвердить: это " + к.kandidat_v_komande : неВКоманде)}">Это ${esc(к.kandidat_v_komande || к.kandidat)}</button>
        <button class="btn-primary vr-do" type="button" data-r="yes" data-kto="vtoroy" ${можноЭтоБ ? "" : "disabled"}
          title="${esc(можноЭтоБ ? "Подтвердить: это " + к.vtoroy_v_komande : неВКоманде)}">Это ${esc(к.vtoroy_v_komande || к.second)}</button>
        <button class="btn-sm vr-do" type="button" data-r="no">Не они</button>`;
    }
    return `<div class="card vr-cluster" data-n="${номер}" data-vr-key="${esc(ключГолоса(к))}">
      <div><b>${esc(к.vstrecha)}</b> · ${esc(к.label || "без метки")} · речи ${числоЗапятой(к.seconds, 0)} с · отпечатков ${к.vsego}</div>
      <div>${меткаГолоса(к.status)} ${строкаКандидата}${к.prichina ? ` <span class="page-sub">(${esc(к.prichina)})</span>` : ""}</div>
      ${к.akkaunt_obshchiy ? `<div class="page-sub vr-akkaunt">С аккаунта ВКС ${esc(к.akkaunt_obshchiy)} говорили ${к.akkaunt_golosov} голоса — имя аккаунта не предлагается: каждый голос разберите отдельно.</div>`
        : к.akkaunt_vks ? `<div class="vr-akkaunt">Предложение: <b>аккаунт ВКС: ${esc(к.akkaunt_vks)}?</b> — реплики этого голоса шли с этого аккаунта; аккаунт — подсказка, не голос.${к.akkaunt_v_komande ? "" : " В «Команде» его нет — выберите человека сами."}</div>`
        : к.metki_vks.length ? `<div class="page-sub">Метка выгрузки ВКС: ${к.metki_vks.map(esc).join(", ")}</div>` : ""}
      ${к.podskazki.length ? `<div class="page-sub">Подсказка при записи: ${к.podskazki.map(esc).join(", ")}</div>` : ""}
      <div class="table-scroll"><table class="doc-table vr-table"><thead><tr><th></th><th>Время</th><th>Длина</th><th>Реплика</th><th>Звук</th></tr></thead><tbody>${строки}</tbody></table></div>
      <div class="hstack vr-actions">
        ${кнопкиКандидата}
        ${к.akkaunt_v_komande && !к.akkaunt_obshchiy ? `<button class="btn-sm vr-do" type="button" data-r="other" data-imya="${esc(к.akkaunt_v_komande)}"
          title="Подтвердить предложение по аккаунту ВКС">Это ${esc(к.akkaunt_v_komande)} (аккаунт ВКС)</button>` : ""}
        <select class="vr-who" aria-label="Другой человек из «Команды»"><option value="">Другой человек…</option>${команда(к.akkaunt_obshchiy ? "" : к.akkaunt_v_komande)}</select>
        <button class="btn-sm vr-do" type="button" data-r="other">Другой человек</button>
        <button class="btn-sm vr-do" type="button" data-r="noise">Шум / не голос</button>
      </div></div>`;
  };
  const кластеры = [];
  const группаHtml = (г) => `<h3 class="vr-gruppa">${меткаГолоса(г.status)} ${г.imya ? esc(г.imya) : "Кандидата нет"} <span class="page-sub">
      · говорящих ${г.klastery.length}, отпечатков ${г.otpechatkov}${г.imya && !г.v_komande ? " · нет в «Команде»" : ""}</span></h3>`
    + г.klastery.map(к => { кластеры.push([г, к]); return кластерHtml(г, к, кластеры.length - 1); }).join("");
  const раздел = (статус, заголовок, пояснение) => {
    const свои = д.gruppy.filter(г => г.status === статус);
    const говорящих = свои.reduce((n, г) => n + г.klastery.length, 0);
    return свои.length ? `<h2 class="vr-razdel" id="vr-razdel-${статус}">${меткаГолоса(статус)} ${заголовок} · ${говорящих} говорящих</h2>
      <div class="page-sub">${пояснение}</div>${свои.map(группаHtml).join("")}` : "";
  };
  const группы = раздел("hint", "Вероятно", "Голос похож на подтверждённого человека, но правило не прошло: близость или отрыв ниже нужного, или мало речи.")
    + раздел("none", "Не узнан", "Голос не похож ни на кого из эталона, или правило по нему отвергнуто кнопкой «Не он».");
  document.getElementById("vr-body").outerHTML = `<div id="vr-body">${вкладки}${шапка}${безМатериала}${группы}</div>`;
  const $тело = document.getElementById("vr-body");
  виды($тело);
  $тело.querySelectorAll(".vr-play").forEach(кн => кн.addEventListener("click", async () => {
    кн.disabled = true;
    try {
      const плеер = document.createElement("audio");
      плеер.controls = true; плеер.autoplay = true; плеер.preload = "auto";
      const повреждён = () => плеер.replaceWith(Object.assign(document.createElement("span"),
        { className: "page-sub", textContent: "отрывок повреждён — звук не воспроизводится" }));
      плеер.addEventListener("error", повреждён);                     // вместо немого плеера «0:00 / 0:00»
      плеер.addEventListener("loadedmetadata", () => { if (!(плеер.duration > 0)) повреждён(); });
      плеер.src = await отрывокАдрес(кн.dataset.id);
      кн.replaceWith(плеер);
    } catch (e) {
      кн.replaceWith(Object.assign(document.createElement("span"), { className: "page-sub", textContent: e.message }));
    }
  }));
  $тело.querySelectorAll(".vr-cluster").forEach($к => $к.querySelectorAll(".vr-do").forEach(кн => кн.addEventListener("click", async () => {
    const [г, к] = кластеры[Number($к.dataset.n)];
    const снятые = new Set([...$к.querySelectorAll(".vr-take")].filter(ч => !ч.checked).map(ч => Number(ч.dataset.id)));
    const ids = к.ids.filter(i => !снятые.has(i));
    const решение = кн.dataset.r;
    let имя = решение === "yes" || решение === "no" ? к.kandidat : "";
    if (решение === "yes" && кн.dataset.kto) имя = кн.dataset.kto === "vtoroy" ? к.second : к.kandidat;
    if (решение === "no" && к.dva_kandidata) имя = `${к.kandidat}; ${к.second}`;   // «Не они» — оба отклонены
    if (решение === "other") {
      имя = кн.dataset.imya || $к.querySelector(".vr-who").value;
      if (!имя) { toast("Выберите человека из «Команды» в списке «Другой человек…»", true); return; }
    }
    if (!ids.length) { toast("Не выбрано ни одного отпечатка", true); return; }
    $к.querySelectorAll("button, select, input").forEach(эл => { эл.disabled = true; });
    try {
      const итог = await api("/voice/review/decision", { method: "POST", json: { ids, reshenie: решение, imya: имя, vybran: кн.dataset.kto || "", kandidat: к.kandidat || "" } });
      toast(`${д.reshenia[решение]}: разобрано отпечатков ${итог.razobrano}` + (итог.kartochek_zakryto ? `, подсказок в «Конфликтах» закрыто: ${итог.kartochek_zakryto}` : ""));
      if (итог.kartochek_zakryto) updateConflictsBadge();
      renderVoiceReview();
    } catch (e) {
      toast(e.message, true);
      $к.querySelectorAll("button, select, input").forEach(эл => { эл.disabled = false; });
    }
  })));
}

// «База голосов» — отдельный пункт меню супер-админа, как у Планёрки (решение владельца 01.10.26, её снимок экрана).
// Та же раскладка карточек «название | значение | пояснение», что в «Параметрах системы». Пишут в базу ОБЕ
// программы (ERP — с 05.10.26: свои отпечатки), но людей подтверждает только Планёрка, у себя в «Конфликтах»;
// здесь — что накоплено, кто сколько написал и что из этого доходит до ERP.
// «Кто пишет в базу» — разбивка по источникам (решение владельца 05.10.26). Одним словом «planerka»
// этого не рассказать: пишут обе программы, и у каждой своя роль. Строка ERP показывается даже когда
// она ещё ничего не написала — иначе непонятно, работает ли вклад вообще.
// Даты «Базы голосов» — дд.мм.гггг (правило владельца 09.10.26): сервер отдаёт «2026-10-14 09:11», на экране шло так же
function датаРу(s) { return String(s || "").replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, "$3.$2.$1"); }

// Пустой раздел, где делать нечего, — тихой строкой с заголовком, а не карточкой (владелец 15.10.26 в Планёрке f7321f0:
// «сократи размер блока уведомления — очень много места занимает»; «правило: пустое состояние — пометкой в заголовке»)
function пустойРаздел(заголовок, пометка) {
  return `<div class="mon-empty-line"><b>${esc(заголовок)}</b> · <span>${esc(пометка)}</span></div>`;
}

function voiceWriters(v) {
  const rows = (v.by_project || []).map(p => {
    const who = p.project === "erp" ? "ERP" : (p.project === "planerka" ? "Планёрка" : p.project);
    return [who, `${p.samples} отп. · записей ${p.records}`,
            esc([`с заявленным именем ${p.named}`, p.linked ? `привязано к человеку ${p.linked}` : "",
                 p.last_at ? `писал ${датаРу(p.last_at)}` : ""].filter(Boolean).join(" · "))];
  });
  if (!(v.by_project || []).some(p => p.project === "erp")) {
    rows.push(["ERP", `<span class="mon-off">пока ничего</span>`,
      !(v.contrib && v.contrib.erp_writes)
        ? `вклад выключен (${esc((v.contrib || {}).off_switch || "WEBAPP_VOICE_CONTRIB=off")})`
        : (v.contrib.models_ready
           ? "отпечатки появятся, как только ERP обработает запись со своих встреч: они кладутся в базу по ходу разбора"
           : (v.contrib.models_state === "not-used"
              ? `${esc(v.contrib.models_hint)} — текст записей ERP распознаётся и без них`
              : `писать пока нечем: ${esc(v.contrib.models_hint || "разбор по голосам недоступен")} — что именно положить, перечислено в «Мониторинге RealTime»`))]);
  }
  return monSection("Кто пишет в базу", monTable(rows) + `<div class="page-sub" style="margin:8px 0 0">
    Планёрка пишет отпечатки со своих планёрок и подтверждает людей (только её оператор решает «этот
    голос — этот человек»). ERP с 05.10.26 пишет отпечатки со своих записей — по кускам речи длиннее
    ${v.contrib ? v.contrib.min_segment_sec : 5} с, — а имя даёт ЗАЯВЛЕННОЕ: только если голос совпал с уже
    подтверждённым человеком базы. Новых людей ERP не заводит и не подтверждает: это решение человека,
    и принимается оно в Планёрке.</div>`, "оба пишут");
}

async function renderVoiceBase() {
  $main.innerHTML = `<h1>База голосов</h1>
    <div class="page-sub">База общая с Планёркой, и пишут в неё ОБЕ программы (ERP — с 05.10.26).
      ERP кладёт отпечатки со своих записей и берёт из базы подсказки написаний имён при разборе
      участников; людей заводит и подтверждает только Планёрка — её оператор и отличает «этот голос —
      этот человек».</div>
    <div id="voice-base-box" class="card empty-state">Загрузка…</div>`;
  const $box = document.getElementById("voice-base-box");
  let v;
  try { v = await api("/project-status/voice-base", {}); }
  catch (e) { $box.textContent = "Не удалось загрузить: " + e.message; return; }
  $box.className = "";
  if (!v.configured) {
    $box.innerHTML = monSection("База не подключена", monLead(`Причина: ${v.reason}. Это не поломка: без пути подсказок просто нет, Протокол собирается как обычно.`));
    return;
  }
  if (v.read_error) {
    $box.innerHTML = monSection("База не читается", monTable([
      ["Файл базы", esc(v.path), ""],
      ["Ошибка чтения", esc(v.read_error), "подсказок из базы сейчас нет, Протокол собирается без них"]]));
    return;
  }
  const people = v.people || [], pending = v.pending || [], recs = v.recordings || [];
  const inTeam = people.filter(p => p.in_team).length;
  const accumulated = monSection("Что накоплено", monTable([
    ["Отпечатков голоса", String(v.samples), "по кускам речи с обработанных записей"],
    ["Из них с заявленным именем", `${v.claimed} из ${v.samples}`, "так голос назвала выгрузка ВКС или разбор записи. Связи с человеком ещё нет"],
    ["Отпечатков, привязанных к человеку", String(v.linked), ""],
    ["Людей с эталоном голоса", String(people.length), "оператор Планёрки сверил имя с «Командой»"],
    ["Имён ждут сверки", String(pending.length), "подтверждают в Планёрке, во вкладке «Конфликты»"],
    ["Файл базы", esc(v.path), "вне папок обоих проектов"],
  ]), "по голосу");
  const writers = voiceWriters(v);
  const forErp = monSection("Что получает ERP", monTable([
    ["Подтверждённых людей", String(people.length), ""],
    ["Из них есть в «Команде»", `${inTeam} из ${people.length}`, "только они дают подсказки. Остальных ERP не заводит"],
    ["Разбор записи по голосам", "свой", "ERP делит запись по голосам сам (pyannote) и считает отпечатки локально — обращений к базе для этого нет"],
    ["Доступ к базе", v.contrib && v.contrib.erp_writes ? "пишет и читает" : "не пишет, только читает", v.contrib && v.contrib.erp_writes
      ? "свои отпечатки кладём в базу, подтверждённые написания имён берём подсказкой"
      : `вклад ERP выключен (${esc((v.contrib || {}).off_switch || "WEBAPP_VOICE_CONTRIB=off")}) — база наполняется только Планёркой`],
    ["Ожидание общей базы", `${v.lock_wait_seconds} с`, "сколько ждём, если базу сейчас пишет другая программа"],
  ]), "подсказки");
  const peopleBlock = !people.length ? пустойРаздел("Подтверждённые люди", "пока никого не подтвердили") : monSection("Подтверждённые люди", monTable(people.map(p => [p.full_name,
    // Команда названа продуктом (владелец 07.10.26): база голосов общая с Планёркой, и «нет в «Команде»»
    // без имени продукта читается как «нет вообще», хотя речь о справочнике именно ERP.
    p.in_team ? `в «Команде»` : `<span class="mon-off">нет в «Команде»</span>`,
    esc([p.aliases.length ? "написания: " + p.aliases.join(", ") : "", p.confirmed_at ? "подтверждён " + датаРу(p.confirmed_at) : ""].filter(Boolean).join(" · "))])));
  const pendingBlock = pending.length ? monSection("Имена ждут сверки", monTable(pending.map(p => [p.name,
    `${p.samples} отп.`, esc(`${p.minutes} мин речи, записей: ${p.recordings}; источник — ${p.source}`)])), "в Планёрке") : "";
  // Панель не молчит (владелец 06.10.26): рядом со списком отпечатков — записи, с которых их НЕТ,
  // с причиной. Иначе запись 05.10 просто отсутствовала, и отличить «распознавания не было» от
  // «отпечатки не снялись» было нельзя.
  const безОтпечатков = (v.recordings_with_fingerprints || []).filter(h => !h.samples);
  const безBlock = безОтпечатков.length ? monSection(`Записи без отпечатков (${безОтпечатков.length})`,
    monTable(безОтпечатков.map(h => [`${esc(датаРу(h.date))}`, `${h.lines} строк`, `${esc(h.reason)} · распознано ${esc(датаРу(h.when))}`]))) : "";
  const recBlock = !recs.length ? пустойРаздел("С каких записей", "записей пока нет") : monSection("С каких записей", monTable(recs.map(r => [`${r.project} · ${esc(датаРу(r.ref))}`,
    `${r.samples} отп.`, esc(`${r.minutes} мин речи, снято ${датаРу(r.when)}`)])));
  // «Протокол последнего распознавания» (владелец 12.10.26: «добавь в монитор, на вкладку „База голосов“,
  // эти параметры по результатам записи»). Шаги и числа одной строкой на шаг: где распознавание провело
  // время и что оно дало. Числа — с задания очереди; чего задание не сохранило (записи до 12.10.26),
  // берём из общей базы; чего нет нигде — так и говорим, а не показываем нулём.
  const последнее = v.last_recognition;
  const вМинутах = (с) => с == null ? "" : (с >= 3600
    ? `${Math.floor(с / 3600)} ч ${Math.round((с % 3600) / 60)} мин` : `${Math.round(с / 60)} мин`);
  const метка = (с) => `${Math.floor(с / 60)}:${String(Math.round(с % 60)).padStart(2, "0")}`;
  let протоколBlock;
  // «Сейчас» и «последняя попытка» (владелец 12.10.26: «в протоколе последнего распознавания нет никакой
  // инфо, что была попытка распознавания и что она остановлена, и что сейчас идёт распознавание»).
  // Раньше блок строился только по последнему ЗАКОНЧЕННОМУ распознаванию. Зеркально Планёрке.
  const строкаЗадания = (з) => [`${esc(з.meeting || "—")} · ${esc(з.filename || "запись")}`,
    esc(з.state) + (з.minutes != null ? ` — идёт ${з.minutes} мин` : "")
      + (з.attempts ? ` (попыток: ${з.attempts})` : ""),
    [з.why, з.todo].filter(Boolean).map(esc).join(" — ")];
  const текущиеСтроки = [];
  if (последнее && последнее.сейчас) {
    текущиеСтроки.push(["Сейчас распознаётся", ...строкаЗадания(последнее.сейчас)]);
  }
  // Если «последняя попытка» — то же задание, что идёт сейчас, вторую строку не показываем: одна и та
  // же запись дважды в блоке читается как две разные (нашлось живой проверкой 12.10.26).
  if (последнее && последнее.последняя_попытка
      && (!последнее.сейчас || последнее.последняя_попытка.job_id !== последнее.сейчас.job_id)) {
    текущиеСтроки.push(["Последняя попытка", ...строкаЗадания(последнее.последняя_попытка)]);
  }
  if (!последнее) {
    протоколBlock = пустойРаздел("Протокол последнего распознавания", "распознаваний ещё не было, записей в очереди нет");
  } else if (последнее.done === false) {
    // Готового распознавания нет, но очередь и попытки есть — показываем их, а не «записей не было».
    протоколBlock = monSection("Протокол последнего распознавания", monTable([
      ...текущиеСтроки,
      ["Распознавание", "законченных распознаваний ещё не было",
       "строки выше — что происходит с очередью и чем закончилась последняя попытка"],
    ]), "по шагам");
  } else {
    const перерывов = Math.max(0, (последнее.attempts || 1) - 1);
    const какшло = [
      перерывов ? `прерывалось перезапуском сервера: ${перерывов} — работа не потеряна`
                : "без прерываний",
      последнее.resumed_seconds != null ? `продолжено с метки ${метка(последнее.resumed_seconds)}` : "",
    ].filter(Boolean).join("; ");
    const отпечатки = последнее.samples == null ? "не посчитано — задание числа не сохранило"
      : (последнее.samples_named ? `${последнее.samples}, из них с именем человека — ${последнее.samples_named}`
                                 : String(последнее.samples));
    // Когда идёт распознавание И есть готовое — называем это прямо (владелец 12.10.26: «на первой строчке
    // сейчас распознаётся с датой 12.10, а Запись/Принята — 8.10»). Без строки-разделителя две РАЗНЫЕ
    // записи в одной таблице читаются как одна, и получается «некорректно отображает».
    const разделитель = (текущиеСтроки.length && последнее.filename)
      ? `<div class="page-sub" style="margin:0 0 8px">Сейчас идёт распознавание: ${esc((последнее.сейчас || {}).meeting || (последнее.сейчас || {}).filename || "запись")}` +
        ((последнее.сейчас || {}).minutes != null ? ` — ${последнее.сейчас.minutes} мин` : "") +
        `. Ниже — числа последнего ЗАКОНЧЕННОГО распознавания («${esc(последнее.filename)}»` +
        (последнее.meeting ? `, ${esc(последнее.meeting)}` : "") + "): это другая запись.</div>"
      : "";
    протоколBlock = monSection("Протокол последнего распознавания", разделитель + monTable([
      ...текущиеСтроки,
      ["Запись", esc(последнее.filename || "—"),
       последнее.meeting ? `встреча ${esc(последнее.meeting)}` : ""],
      ["Принята", fmtRuDateTime(последнее.accepted_at) || "—", esc(последнее.accepted_note || "")],
      ["Очередь распознавания", `${fmtRuDateTime(последнее.queued_at) || "—"} → начато ${fmtRuDateTime(последнее.started_at) || "—"}`,
       "распознаётся по одной записи за раз, в порядке приёма"],
      ["Распознавание", `закончено ${fmtRuDateTime(последнее.finished_at) || "—"}`
        + (последнее.media_seconds ? ` · запись ${вМинутах(последнее.media_seconds)} (${последнее.media_seconds} с)` : "")
        + (последнее.speech_seconds ? `, речи ${вМинутах(последнее.speech_seconds)} (${последнее.speech_seconds} с)` : ""),
       какшло + (последнее.speech_seconds ? "; паузы отбрасывает фильтр тишины — распознаётся речь" : "")],
      ["Расшифровка", `${последнее.lines} строк`
        + (последнее.transcript ? ` · источником приложена «${esc(последнее.transcript)}»` : ""),
       [последнее.device ? `устройство — ${esc(последнее.device)}` : "",
        "запись после распознавания убрана: голоса не храним"].filter(Boolean).join("; ")],
      ["Разделение по голосам", последнее.speakers == null
        ? (последнее.samples_in_base ? "шло, но числа не сохранились — запись считалась до 12.10.26"
                                    : "не выполнялось — причина в системных сообщениях")
        : `голосов ${последнее.speakers}, подписано строк ${последнее.signed_lines} из ${последнее.lines}`,
       "подписи «Говорящий N» — имён разбор не даёт"],
      ["Отпечатки в общую базу", отпечатки, "ими пополняется общая база двух программ"],
    ]), "по шагам");
  }
  $box.innerHTML = протоколBlock + accumulated + writers + forErp + peopleBlock + pendingBlock + безBlock + recBlock;
  // Ширины колонок по объёму текста — тот же замер, что на «Мониторинге»: без него таблица делится
  // поровну, и путь к файлу базы не помещается в среднюю колонку (замечание владельца 05.10.26).
}

// «Скорость распознавания» — первым блоком «Мониторинга RealTime», акцентом (п. 6 замечаний владелицы 21.10.2026: «явный
// показатель, за сколько прошли расшифровка и распознавание голоса — по каждой записи»). Строка — запись: длина → расшифровка
// → опознание голоса → всего, готово дд.мм.гггг чч:мм (Москва). Данные — `recognition.speed` сервера
// (`skorost_raspoznavaniya`, близнец двух систем); функция одна в обеих системах.
function скоростьРаспознаванияHtml(строки) {
  const нет = '<span class="speed-none">нет замера</span>';
  const тело = (строки || []).length
    ? `<table class="speed-table"><thead><tr><th>Запись</th><th>Длина записи</th><th>Расшифровка</th><th>Опознание голоса</th><th>Всего</th><th>Готово</th></tr></thead><tbody>${строки.map(с => `<tr>
        <td>${esc(с.meeting)}<span class="speed-file">${esc(с.file)}</span></td>
        <td>${с.media ? esc(с.media) : нет}</td>
        <td class="speed-acc">${с.asr ? esc(с.asr) : нет}${с.resumed ? '<span class="speed-file">продолжено после обрыва</span>' : ""}</td>
        <td class="speed-acc">${с.voices ? esc(с.voices) : нет}</td>
        <td><b>${с.total ? esc(с.total) : нет}</b>${с.share ? `<span class="speed-file">${String(с.share).replace(".", ",")} длины записи</span>` : ""}</td>
        <td>${esc(с.finished_msk || "")}</td></tr>`).join("")}</tbody></table>`
    : '<div class="speed-none">Распознанных записей пока нет — показатель появится после первой записи.</div>';
  return `<div class="card speed-card" id="speed-card"><h2 class="speed-h">Скорость распознавания</h2>
    <div class="speed-sub">По каждой записи: длина записи → расшифровка речи → опознание голоса (разделение и сверка с базой голосов) → всего. «нет замера» — запись распознана до 21.10.2026, время этапа тогда не записывалось.</div>${тело}</div>`;
}

function renderMonitoringLive() {
  const $box = document.getElementById("monitoring-panel");
  const m = _monitoringCache;
  if (!$box || !m) return;
  const wf = m.watch_folder || {};
  const services = monTable((m.services_live || []).map(s => [s.name, s.checking ? '<span class="badge badge-neutral">проверка</span>' : monState(s.ok), esc(s.detail)]));
  // «Проверить связь» (18.10.2026): точки модели панель опрашивает фоном раз в 60 с и не ждёт сети на каждом открытии —
  // в строке «проверено N с назад»; кнопка опрашивает сейчас.
  const проверитьСвязь = `<div class="hstack" style="margin-top:8px"><button class="btn-sm" id="probe-now-btn">Проверить связь</button>
    <span class="page-sub" style="margin:0">точки модели опрашиваются фоном раз в 60 секунд; кнопка — опросить сейчас</span></div>`;
  const folderSource = wf.folder_source ? ` Сейчас путь взят: ${esc(wf.folder_source)}.` : "";
  // Частота обхода папки — рядом со строкой ввода пути и ЗАДАЁТСЯ ЗДЕСЬ ЖЕ, как путь (владелец
  // 09.10.26: сначала «выведи в мониторинг переменную…», затем «сделай блок ввода значения для обхода
  // папки активной строкой — чтобы сразу с монитора можно было задавать значение, как путь к файлу
  // приёмника»). Видит только супер-админ: сама панель «Мониторинг RealTime» — его (см. проверку
  // маршрута), здесь роль проверяется явно, чтобы поле не поехало на другие роли при будущих правках.
  const источник = wf.poll_every_source === "переменная окружения"
    ? `сейчас частота взята из переменной окружения ${esc(wf.poll_every_var)}`
    : wf.poll_every_source === "задано на мониторинге"
      ? "сейчас частота задана здесь, на мониторинге"
      : `сейчас частота взята по умолчанию${wf.poll_every_var ? ` (переменная ${esc(wf.poll_every_var)} не задана)` : ""}`;
  const интервал = isSuperAdmin() ? `
    <div class="mon-folder-form" style="margin-top:8px">
      <label class="page-sub" for="watch-interval-input" style="margin:0; white-space:nowrap">Обход папки, секунд:</label>
      <input type="number" id="watch-interval-input" inputmode="numeric" style="max-width:120px"
             min="${wf.poll_every_min || 10}" max="${wf.poll_every_max || 86400}" step="10"
             value="${wf.poll_every_value_setting || wf.poll_every_sec || ""}"
             title="Как часто обходить папку-приёмник. Пустое поле — вернуться к переменной окружения или значению по умолчанию">
      <button class="btn-sm" id="watch-interval-btn">Сохранить интервал</button>
      <span class="page-sub" style="margin:0">${wf.poll_every_sec % 60 === 0 ? `${wf.poll_every_sec / 60} мин · ` : ""}${
        esc(источник)}${wf.poll_every_note ? ` — ${esc(wf.poll_every_note)}` : ""}. Очистите поле и сохраните, чтобы вернуться к значению из настроек сервера.</span>
    </div>` : "";
  const folderForm = `
    <div class="mon-folder-form">
      <input type="text" id="watch-folder-input" value="${esc(wf.folder || "")}" placeholder="Папка-приёмник записей не задана — укажите полный путь" autocomplete="off">
      <button class="btn-sm" id="watch-folder-btn">Сменить папку</button>
    </div>${интервал}
    <div class="page-sub" style="margin:6px 0 0">Меняется в два шага: сначала показываем, что в папке лежит и что заберёт первый проход,
      потом просим повторить путь. Так сделано не из вредности — поллер обходит папку целиком и уносит забранное в подпапку
      «обработано», поэтому опечатка в пути дорого стоит. Пустое поле — выключить папку.${folderSource}</div>`;

  const r = m.recognition || { stages: [] };
  // Последние распознанные записи (05.10.26, замечание владельца: «нет информации о том, что прошла
  // транскрибация записи»): по строке видно, что запись распознана, сколько в ней строк и что она дала
  // общей базе. Ноль отпечатков — не сбой сам по себе: говорят, почему, — в строке «Разбор по голосам».
  const распознанные = (r.last || []).map(h => [
    `Распознано ${h.meeting}`,
    `${h.lines} строк${h.device ? ` · ${h.device}` : ""}${h.finished_at ? ` · ${fmtDate(h.finished_at)}` : ""}`,
    esc(h.voice_text || "отпечатки не собирались: см. строку «Разбор по голосам»")]);
  // Контрольная точка (владелец 12.10.26: «в папке-приёмнике видно, что запись забрали, но мониторинг
  // говорит, что распознавание не идёт»). Раньше здесь были только идущая работа и готовые распознавания:
  // запись, чьё распознавание остановлено, попадала лишь в счётчик «ждут ответа N» в «Очереди».
  const записи = (r.записи || []).map(z => [
    `${esc(z.meeting)} · ${esc(z.file || "запись")}`,
    esc(z.state),
    (z.todo ? `${esc(z.why)} — ${esc(z.todo)}` : esc(z.why))
      // Действие — там, где человек видит состояние (решение владельца 12.10.26): не надо идти в
      // «Конфликты» за тем же решением. Права проверяет сервер (панель и так только супер-админу).
      + (z.resume ? ` <button class="btn-sm" data-resume-job="${esc(String(z.job_id))}">Вернуть в распознавание</button>` : ""),
  ]);
  const recognition = monSection("Распознавание записи", `
    <div class="mon-lead">${r.running
      ? `Сейчас разбирается «${esc(r.filename || "запись")}»${r.media_minutes ? `, запись ${r.media_minutes} мин` : ""}${r.device ? `, на ${r.device === "процессор" ? "процессоре" : "видеокарте"}` : ""}${r.expected_minutes ? `, ориентир до ${r.expected_minutes} мин` : ""}${r.progress_pct != null ? ` (ориентировочно ${r.progress_pct}%)` : ""}`
      : "Сейчас ничего не разбирается"}${r.waiting ? ` · ждут очереди: ${r.waiting}` : ""}</div>
    ${monTable(r.stages.map(st => [st.name, esc(st.state === "идёт" ? `идёт ${st.minutes} мин` : st.state), ""])
      .concat(распознанные)
      .concat(записи)
      .concat((r.history || []).map(h => [`Распознано на ${h.device === "процессор" ? "процессоре" : "видеокарте"}`,
        `${h.count} зап.`, `за ${h.min}–${h.max} длительности записи, обычно ${h.median}`])))}
    ${r.running && r.device === "процессор" ? `<div class="page-sub" style="margin:8px 0 0">Идёт на процессоре — в разы медленнее, эталона для процессора нет. Причина — в технических сообщениях (обычно не видны библиотеки видеокарты).</div>` : ""}
    <div class="page-sub" style="margin:8px 0 0">Эталон — замер 30.09.26 на шести записях ERP: на видеокарте распознавание занимает
      до ${Math.round(100 * ((r.reference_share || {})["видеокарта"] || 0.5))}% длительности записи (обычно около трети). Протокол нужен быстрее — приложите транскрипцию текстом.</div>`);

  const q = m.queues || {};
  const queues = monSection("Очередь", `
    ${нормаКонфликтовHtml(q.conflicts_norm)}${одинСуперадминHtml(q.superadmins)}
    <div class="mon-lead">Разные очереди — разные адресаты: карточки по содержанию разбирает тот, кто ведёт встречи; технические сообщения — только супер-администратор.</div>
    ${monTable([
      ["Карточки «Конфликтов»", `ждут решения ${q.conflicts_open}`, `за сутки решено ${q.conflicts_resolved_day} · <a href="#razbor">разобрать</a>`],
      ["Технические сообщения", `открыто ${q.system_open}`, `за сутки закрыто ${q.system_closed_day} · <a href="#" id="open-system-tab">открыть</a>`],
      ["Записи с нетипичной длительностью", `ждут ответа ${q.recordings_held}`, "карточкой в «Конфликтах»"],
      ["Записи, которые не распознались", `ждут ответа ${q.recordings_failed || 0}`, "карточкой «повторить / удалить»; без ответа 7 дней удаляются сами"],
    ])}`);

  const a = m.autorun || {};
  const autorun = monSection("Автозапуск Протокола", `
    ${monTable([["Сейчас", a.enabled ? "включён" : "выключен",
      "собирает Протокол встречи сразу после первого источника (файл, текст, распознанная запись), если Протокола ещё нет и источник не вызывает сомнений"]])}
    <button class="btn-sm${a.enabled ? "" : " btn-primary"}" id="autorun-toggle-btn" style="margin-top:8px">${a.enabled ? "Выключить" : "Включить"}</button>`);

  const waiting = m.awaiting_total;
  const awaitingLine = waiting
    ? `<div class="mon-lead">Система <b>ждёт ввода от оператора</b>: ${waiting} — <a href="#awaiting">открыть «Ожидает ввода от оператора»</a></div>`
    : `<div class="mon-lead">Система не ждёт ввода от оператора — открытых вопросов нет.</div>`;
  // Первой строкой мониторинга — задачи «под вопросом» (ответ владельца 15.10.26: фокус на работу оператора, как в Планёрке).
  // При нуле — тихая строка без кнопок (решение владельца 15.10.26); выключатель отметки — в «Диск и доступы» → «Настройки».
  const подВопросомСтрока = m.under_question
    ? `<div class="card" id="uq-monitor-line">Задачи под вопросом: <b>${m.under_question}</b> — <a href="#razbor/tasks">открыть «Разбор»</a></div>`
    : `<div class="mon-lead" id="uq-monitor-line">Задачи под вопросом: нет</div>`;
  $box.innerHTML = подВопросомСтрока + скоростьРаспознаванияHtml(r.speed) +
    monLead("Что меняется каждый час: службы (проверка соединением), распознавание записи, очередь одной строкой, автозапуск. Реже меняющееся — на «Диск и доступы», предметное — на «Состояние базы».") +
    monSection("Службы", services + проверитьСвязь + folderForm, `Москва ${m.now_msk || ""}`) +
    recognition + queues + autorun +
    // Стоимость модели (15.10.26): сегодня / 7 / 30 дней; разбивка по встречам и точкам — на вкладке «Расход».
    monSection("Стоимость модели", стоимостьМоделиHtml(m.llm_cost, false, "Встреча")
      + `<div class="page-sub">По встречам, моделям и точкам — <a href="#system">«Параметры системы» → «Расход»</a>.</div>`);

  // «Вернуть в распознавание» со строки контроля (решение владельца 12.10.26) — то же решение, что
  // карточка «Распознать» в «Конфликтах», но там, где человек видит состояние записи.
  document.querySelectorAll("[data-resume-job]").forEach(btn =>
    btn.addEventListener("click", вернутьВРаспознавание));
  document.getElementById("autorun-toggle-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;          // после await currentTarget = null (хаос-тест 02.10.26)
    btn.disabled = true;
    try {
      await api("/project-status/autorun", { method: "POST", json: { enabled: !a.enabled } });
      await loadAndRenderMonitoring(renderMonitoringLive);
    } catch (err) { toast(err.message, true); e.currentTarget.disabled = false; }
  });
  document.getElementById("open-system-tab")?.addEventListener("click", (e) => {
    e.preventDefault();
    // Живая панель — своя страница «Мониторинг RealTime» (02.10.26): сообщения — на «Параметрах системы», вкладка открывается сразу.
    if (document.getElementById("mon-tab-errors")) { document.getElementById("mon-tab-errors").click(); return; }
    try { sessionStorage.setItem("openSystemErrors", "1"); } catch (err) { /* без памяти — откроется первая вкладка */ }
    location.hash = "system";
  });
  document.getElementById("probe-now-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api("/project-status/monitoring/probe-now", { method: "POST" });
      _monitoringCache = await api("/project-status/monitoring", {});
      renderMonitoringLive();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
  document.getElementById("watch-folder-btn")?.addEventListener("click", () => changeWatchFolder());
  // Интервал обхода — прямое действие, без пароля и подтверждения: в отличие от пути, ошибка здесь
  // ничего не разрушает (поллер пройдёт папку раньше или позже) и правится тем же полем (владелец 09.10.26).
  document.getElementById("watch-interval-btn")?.addEventListener("click", async (e) => {
    const поле = document.getElementById("watch-interval-input");
    const сырое = (поле?.value || "").trim();
    const секунд = сырое ? Number(сырое) : null;
    if (сырое && (!Number.isFinite(секунд) || секунд < 10 || секунд > 86400)) {
      toast("Интервал — от 10 секунд до 24 часов", true);
      return;
    }
    const кнопка = e.currentTarget;
    кнопка.disabled = true;
    try {
      await api("/project-status/watch-folder/interval", { method: "POST", json: { seconds: секунд } });
      toast(секунд ? `Обход папки: каждые ${секунд} с` : "Интервал обхода вернули к значению из настроек сервера");
      await loadAndRenderMonitoring(renderMonitoringLive);
    } catch (err) {
      toast(err.message, true);
    } finally {
      // Кнопку возвращаем всегда: перерисовка панели заменяет её на новую, а если панель не обновилась
      // (сеть мигнула) — старая осталась бы навсегда заблокированной и второе нажатие не сработало
      // (поймано живой проверкой 09.10.26: сброс значения не выполнялся).
      кнопка.disabled = false;
    }
  });
}

// Смена папки-приёмника в два шага (по образцу Планёрки): проверка пути на сервере → показ, что в папке
// лежит и что заберёт первый проход → подтверждение повтором пути. Всё решает сервер, здесь только диалог.
async function changeWatchFolder() {
  const path = (document.getElementById("watch-folder-input")?.value || "").trim();
  let step;
  try { step = await api("/project-status/watch-folder", { method: "POST", json: { path, confirm: false } }); }
  catch (e) { toast(e.message, true); return; }
  const p = step.preview;
  const previewHtml = p ? `
    <div class="page-sub" style="margin:8px 0">В папке файлов: ${p.files_total} · первый проход заберёт: ${p.will_take}
      ${p.examples && p.examples.length ? `<br>например: ${p.examples.map(n => `«${esc(n)}»`).join(", ")}` : ""}</div>` : "";
  const ov = openModal(path ? "Сменить папку-приёмник" : "Выключить папку-приёмник", `
    <div>${esc(step.question)}</div>
    ${previewHtml}
    ${path ? `<div class="field"><label>Повторите путь</label><input type="text" id="watch-folder-repeat" autocomplete="off"></div>` : ""}
    <div class="field"><label>Ваш пароль</label><input type="password" id="watch-folder-password" autocomplete="current-password"></div>
    <div class="page-sub" style="margin:6px 0 0">Смена папки-приёмника выполняется по паролю супер-администратора
      (правило 07.10.26): папку поллер обходит целиком, и подтверждать такое действие должен человек,
      а не выбор имени в меню.</div>
  `, async (o) => {
    const repeat = path ? o.querySelector("#watch-folder-repeat").value.trim() : "";
    if (path && !repeat) throw new Error("Повторите путь — так подтверждается смена папки");
    const пароль = o.querySelector("#watch-folder-password").value;
    if (!пароль) throw new Error("Введите пароль — без него папка не меняется");
    await api("/project-status/watch-folder", { method: "POST",
                                                json: { path, confirm: true, repeat_path: repeat, current_password: пароль } });
    toast(path ? "Папка-приёмник изменена" : "Папка-приёмник выключена");
    await loadAndRenderMonitoring(renderMonitoringLive);
  });
  const _save = ov.querySelector("#modal-save");
  if (_save) _save.textContent = path ? "Сделать папкой-приёмником" : "Выключить";
  ov.querySelector("#watch-folder-repeat")?.focus();
}

function renderMonitoringRuns() {
  const $box = document.getElementById("monitoring-panel");
  const m = _monitoringCache;
  if (!$box || !m) return;
  const r = m.runs_14_days;
  const pct = r.verification_total ? ` (${Math.round(100 * r.verification_clean / r.verification_total)} %)` : "";
  $box.innerHTML = monLead("Как идут прогоны: сколько встреч обработано, как проверка встречает черновики, упирались ли в пределы.") +
    monSection(`Прогоны за ${r.days} дней`, monTable([
      ["Встреч с сохранённым Протоколом", String(r.protocols_saved), `последний сохранённый Протокол ${esc(fmtDate(m.last_minutes_saved_at))}`],
      ["Проверок черновиков", r.verification_total ? `${r.verification_total}: чисто ${r.verification_clean}${pct}, с замечаниями ${r.verification_total - r.verification_clean}` : "не было",
        "вердикт проверяющей модели — подсказка, не шлюз: черновик с замечаниями администратор может сохранить"],
      ["Модель проверки в последнем прогоне", r.last_verify_model ? esc(r.last_verify_model) : "—",
        (r.verify_on_draft_model ? "модель черновика · отдельная модель проверки не назначена" : "")
          + (r.last_verify_at ? `${r.verify_on_draft_model ? " · " : ""}${esc(fmtDate(r.last_verify_at))}` : "")],
      ["Сейчас формируется / не удалось", `${r.generating_now} / ${r.failed}`, "не удалось — сбои с технической причиной в системных сообщениях"],
      // Очередь сборок (14.10.26): сборки идут по одной, по датам встреч — что собирается и что ждёт.
      ["Очередь сборок", esc(строкиОчереди(r.build_queue) || "пусто"), "сборки идут по одной, по датам встреч; Карта и Сводка — после протоколов"],
      ["Остановок по пределу за 7 дней", String(r.stopped_by_limit), `пределы на прогон: ${esc(r.limits)}`],
    ]));
}

// «Расход» — токены и деньги (поручение владельца 15.10.26, через «Мониторинг», п. 4): сегодня / 7 / 30 дней; итог, по встречам,
// по моделям. Деньги: от поставщика (OpenRouter возвращает стоимость) и расчётные — токены × тариф точки (общий с Планёркой
// tariffs.py: свой тариф точки в «Моделях», иначе открытый прейскурант поставщика). Расчётная помечена; вызовы без тарифа —
// строкой «тариф не задан: N вызовов».
let расходПериод = "7";
const РАСХОД_ПЕРИОДЫ = [["today", "Сегодня"], ["7", "7 дней"], ["30", "30 дней"]];
const числоРу = (n) => Number(n || 0).toLocaleString("ru-RU");
function деньги(с) {
  const всего = долларыРу(с.cost_usd);
  if (!с.cost_estimated_usd) return всего;
  return с.cost_provider_usd ? `${всего} <span class="mon-off">(расчётная ${долларыРу(с.cost_estimated_usd)})</span>`
    : `${всего} <span class="mon-off">расчётная</span>`;
}
function токены(с) {
  return `вход ${числоРу(с.tokens_in)}${с.tokens_cached ? ` (из кэша ${числоРу(с.tokens_cached)})` : ""} · выход ${числоРу(с.tokens_out)}`;
}

function renderMonitoringCost() {
  const $box = document.getElementById("monitoring-panel");
  const m = _monitoringCache;
  if (!$box || !m) return;
  const u = m.llm_usage_7_days;
  const series = (u.series_by_day || []).map(d => `${esc(fmtRuDate(d.day))}: ${d.cost_usd.toFixed(3)} $ · прогонов ${d.runs}, вызовов ${d.calls}`).join("<br>");
  $box.innerHTML = monLead("Сколько стоит модель. Если поставщик возвращает цену вызова (OpenRouter), берётся его число. Если не возвращает (DeepSeek), стоимость считается как токены × тариф точки по открытому прейскуранту поставщика — такие суммы помечены «расчётная по тарифу»; фактический счёт — в кабинете поставщика. Тариф правится в «Моделях», в форме подключения. У своего сервера в контуре (LM Studio, Ollama) тарифа нет: такие вызовы идут строкой «тариф не задан». Что за модель работает сейчас — в строке «Модель» на вкладке «Мониторинг RealTime».") +
    monSection("Стоимость: токены и деньги", стоимостьМоделиHtml(m.llm_cost, true, "Встреча")) +
    monSection(`Расход на модель за ${u.days} дней`, u.total_calls === 0 ? `<div>вызовов не было</div>` : monTable([
      ["Всего", `${u.total_cost_usd.toFixed(3)} $ · вызовов ${u.total_calls} · прогонов ${u.runs}`, `последний вызов ${esc(fmtDate(u.last_call_at))}`],
      ["Цена прогона (средняя)", u.cost_per_run_usd != null ? `${u.cost_per_run_usd.toFixed(3)} $` : "—", "прогон = все вызовы с одним номером встречи"],
      ["Цена серии по дням", series || "—", "серия = все прогоны за календарный день"],
      ...Object.entries(u.by_purpose).map(([p, s]) => [`Назначение: ${esc(PURPOSE_LABELS[p] || p)}`, `${долларыРу(s.cost_usd)} · ${s.calls} вызовов`, ""]),
    ]));
  $box.querySelectorAll("[data-cost-period]").forEach(a => a.addEventListener("click", (e) => {
    e.preventDefault();
    расходПериод = a.dataset.costPeriod;
    renderMonitoringCost();
  }));
}

const SOURCE_KIND_RU = { protocol: "протокол", transcript: "расшифровка", other: "заметки/без вида", recording: "запись" };
const CLOSED_BY_RU = { meeting: "по протоколу встречи", web_form: "вручную", system: "системой",
  registry_reconciliation_17_09_26: "сверка с файловым реестром 17.09.26" };

function renderMonitoringDataState() {
  const $box = document.getElementById("monitoring-panel");
  const m = _monitoringCache;
  if (!$box || !m) return;
  const d = m.data_state, ks = m.knowledge_state;
  const kinds = Object.entries(d.sources_by_kind).filter(([, n]) => n).map(([k, n]) => `${SOURCE_KIND_RU[k] || k}: ${n}`).join(", ") || "нет";
  const st = d.tasks_by_status;
  const closed = Object.entries(d.closed_by_source).map(([k, n]) => `${CLOSED_BY_RU[k] || k}: ${n}`).join(", ") || "закрытий не было";
  const diverge = ks.active_tasks_as_of_roadmap != null && ks.active_tasks_as_of_roadmap !== ks.active_tasks_now;
  $box.innerHTML = monLead("Чем система отвечает: встречи и записи, реестр задач, люди. Где числа расходятся — показаны оба.") +
    monSection("Встречи и записи", monTable([
      ["Встреч в базе", `${d.meetings}, с источниками ${d.with_sources}, с Протоколом ${d.with_minutes}`, d.last_meeting ? `последняя встреча ${esc(fmtRuDate(d.last_meeting))}` : ""],
      ["Источники", esc(kinds), "вид файла интерфейс не спрашивает (решение 12.09.26) — точно известен только у записей и расшифровок из них"],
    ])) +
    monSection("Реестр задач", monTable([
      ["По статусам", `активных ${st.active}, выполнено ${st.done}`, ""],   // снятые не упоминаются (26.10.2026)
      ["Закрытия по источнику", esc(closed), "по истории статусов"],
      ["Активных сейчас / на момент Карты", !ks.roadmap_generated_at ? `${ks.active_tasks_now} / Карта не собрана` : `${ks.active_tasks_now} / ${ks.active_tasks_as_of_roadmap}`,
        diverge ? "расходятся: реестр менялся после сборки Карты/Сводки — это не сбой" : (ks.roadmap_generated_at ? `Карта собрана ${esc(fmtDate(ks.roadmap_generated_at))}` : "")],
    ])) +
    monSection("Люди", monTable([
      ["Команда ERP", `${d.team_active} активных, не подтверждено ${d.team_unconfirmed}`, "неподтверждённые — карточками в «Конфликтах»"],
      ["База голосов", !(m.voice_directory && m.voice_directory.configured) ? "не подключена"
        : m.voice_directory.read_error ? `подключена, но не читается: ${esc(m.voice_directory.read_error)}` : `подтверждённых людей ${m.voice_directory.confirmed_people}`,
        "общая с Планёркой: ERP берёт подсказки и кладёт свои отпечатки (с 05.10.26)"],
    ]));
}

function renderMonitoringStatic() {
  const $box = document.getElementById("monitoring-panel");
  const m = _monitoringCache;
  if (!$box || !m) return;
  const p = m.paths || {}, ml = m.models_limits || {};
  const rolesText = Object.entries(m.roles).map(([k, v]) => `${ROLE_LABELS_RU[k] || k}: ${v}`).join(", ");
  const address = m.server_address === "127.0.0.1" || m.server_address === "localhost"
    ? "только эта машина (127.0.0.1)" : `все адреса машины (${esc(m.server_address)}) — доступ из локальной сети`;
  $box.innerHTML = monLead("Что меняется редко: размеры и пути, копии, доступы и адрес, модели и пределы.") +
    monSection("Диск", monTable([
      ["База данных", fmtBytes(m.disk.db_bytes), esc(p.db || "")],
      ["Загруженные файлы", fmtBytes(m.disk.uploads_bytes), esc(p.uploads || "")],
      ["Автокопии базы", `${fmtBytes(m.disk.backups_bytes)} · ${m.disk.auto_backups_count} шт.`, esc(p.backups || "")],
      ["Ручные копии", `${m.disk.manual_backups_count} шт.`, "в той же папке, ротация их не трогает"],
      ["Журнал вызовов модели", fmtBytes(p.journal_bytes), esc(p.journal || "")],
      ["Общая база голосов", p.voice_base ? "подключена" : "не найдена",
        esc(p.voice_base ? `${p.voice_base} (из переменной VOICE_BASE_PATH)` : (p.voice_base_reason || "путь — переменная VOICE_BASE_PATH"))],
    ])) +
    monSection("Автобэкап", monTable([
      ["Последняя автокопия", esc(fmtDate(m.auto_backup.last_at)), ""],
      ["Правило", `раз в ${m.auto_backup.interval_hours} ч, хранить ${m.auto_backup.keep_last} последних`, "ручные копии ротация не трогает"],
    ]) + `<button class="btn-sm" id="backup-now-btn" style="margin-top:8px">Снять копию сейчас</button>`) +
    // Выключатель отметки «под вопросом» — в настройках, а не на живом мониторинге (решение владельца 15.10.26)
    monSection("Настройки", monTable([["Отметка задач «под вопросом» в реестре", m.under_question_mark !== false ? "включена" : "выключена",
      "маленькая приглушённая точка перед формулировкой, подпись причины — в подсказке; видят только администраторы. Временная, на пилот"]])
      + `<button class="btn-sm" id="uq-mark-toggle-btn" style="margin-top:8px">${m.under_question_mark !== false ? "Выключить" : "Включить"}</button>`
      // Порог удаления нерешённых карточек «Конфликтов» — как поле «Настроек» Планёрки (решения владелицы 21.10.2026, пункт 3);
      // срок снятия задач «под вопросом» — тот же (решение владелицы 20.10.2026), своего поля у него нет
      + `<div class="field" style="margin-top:12px"><label for="conflict-drop-input">Нерешённая карточка «Конфликтов» удаляется через (дней)</label>
        <input type="text" id="conflict-drop-input" value="${esc(m.conflict_drop_unresolved_days ?? 3)}">
        <div class="page-sub">Решение владельца 01.10.2026: к старой встрече и к её неразобранным карточкам не возвращаются. Карточки
          про людей появятся снова, когда имя встретится в следующий раз. Задачи, отложенные оператору, не вернутся — их текст есть
          только в карточке; перед удалением он целиком записывается в «Системные сообщения». Не удаляются карточки задач «под
          вопросом», договорённостей и записей (у записи своё правило — 7 дней без ответа).</div>
        <div class="page-sub">Тот же срок снимает задачу «под вопросом», по которой не нажали «Подтвердить» или «Снять» (решение
          владелицы 20.10.2026): сейчас ${esc(m.under_question_expire_days ?? 3)} дн. Причина — «срок «под вопросом» истёк», задача
          не удаляется, но и не показывается больше нигде (решение владелицы 26.10.2026). Срок считается от заведения задачи.</div></div>
        <button class="btn-sm" id="conflict-drop-save-btn">Сохранить срок карточек</button>`
      // Хранение служебных журналов — все виды, 7 дней (решение владелицы 18.10.2026; было 15 и только системные сообщения)
      + (isSuperAdmin() ? `<div class="field" style="margin-top:12px"><label for="log-keep-input">Хранить служебные журналы, дней</label>
        <input type="text" id="log-keep-input" value="${esc(m.service_log_keep_days ?? 7)}">
        <div class="page-sub">Старше срока раз в сутки удаляются: технические сообщения (кроме служебных — тех же, что не удаляет «Удалить все»), прогоны проверки (кроме последней у документа и окна статистики «Мониторинга»), завершённые задания распознавания (кроме последнего у встречи), истёкшие сессии входа (живые и «помнить 30 дней» — нет), строки журналов вызовов модели (кроме 30 дней и текущего месяца — по ним расход и предел поставщика). Задачи, история задач, протоколы, карточки, «Команда», договорённости и записи не трогаются. 0 — не чистить.</div></div>
        <button class="btn-sm" id="log-keep-save-btn">Сохранить срок хранения</button>` : "")) +
    // Выключатель общей «Команды» двух систем (решение владелицы 18.10.2026) — та же карточка, что в «Настройках» Планёрки
    (m.team_shared ? командаОбщаяКарточка(m.team_shared) : "") +
    // Сборка протокола: извлечение поручений и договорённости (19.10.2026, Е1 + Е2) — суперадминистратору
    (isSuperAdmin() ? `<div class="card stack" id="sborka-settings-card"><div class="doc-heading">Сборка протокола</div><div class="page-sub">Загрузка…</div></div>` : "") +
    // Проект системы (задание 23.10.2026) — с 23.10.2026 на вкладке «Настройки» (renderSettingsTab), здесь его нет
    monSection("Доступ и роли", monTable([
      ["Вход по паролю", m.auth_required ? "включён" : "выключен — пользователь выбирается в «Вы работаете как»", ""],
      // Общий пароль участников (решение владелицы 18.10.2026, перенос из Планёрки 19.10.2026): состояние — отдельным запросом
      ["Общий пароль", `<span id="shared-password-state">участникам — один на всех; администраторы входят по личному</span>`,
        `<button type="button" class="btn-sm" id="settings-shared-password">Задать</button> ${подсказкаПаролейHtml()}`],
      ["Адрес сервера", address, "меняется переменной HOST при запуске"],
      ["Роли", esc(rolesText), ""],
      ["Заблокированных / неподтверждённых записей", `${m.locked_users} / ${m.unconfirmed_users}`, ""],
    ])) +
    monSection("Проверка загружаемых источников", (() => {
      const sc = m.source_check || {};
      return `<div class="mon-lead">Похож ли файл на материалы другого проекта: доля слов, которые встречаются там и ни разу — в источниках
        этого проекта. Не блокирует загрузку — предупреждает.</div>` + monTable([
        ["Другой проект", sc.available ? esc(sc.project) : "список не собран", sc.available ? `${sc.words} слов из ${sc.files} файлов, собран ${esc(sc.built_at)}` : "команда: python -m app.cli other-project-stems --planerka-db …"],
        ["Порог", `доля ≥ ${Math.round(100 * sc.threshold)} %`, `замер 30.09.26: свои 0 ложных из 26, чужие пойманы 45 из 45; текст короче ${sc.min_stems} смысловых слов не оценивается`],
      ]);
    })()) +
    // Модели — только на вкладке «Модели» (оформление «Линия», решение владельца 13.10.26: «убрать дубль»); модель Карты и
    // Сводки, которой там не было, перенесена туда же (nav.js). Здесь — пределы и служебное.
    monSection("Пределы и служебное", monTable([
      ["Пределы на прогон", `${ml.max_calls} вызовов · ${ml.max_cost_usd} $ · ${ml.max_prompt_chars} знаков`, "проверяются кодом до вызова"],
      // Следы вызовов в Langfuse (06.10.26) — только цифры, текст встреч не уходит. Сбой отправки виден здесь, а не только в журнале
      ["Langfuse", (() => { const lf = ml.langfuse || {};
        if (!lf.enabled) return "выключен — нет ключей в .env.local";
        return `отправлено ${lf.sent || 0}` + (lf.failed ? ` · не ушло ${lf.failed}` : "") + (lf.queued ? ` · в очереди ${lf.queued}` : ""); })(),
        esc((ml.langfuse || {}).last_error || ((ml.langfuse || {}).enabled ? "только цифры: модель, токены, цена, время — без текста" : ""))],
      ["Сервер", `pid ${m.server.pid}, запущен ${esc(fmtDate(m.server.started_at))}`, ""],
    ]));
  карточкаНастроекСборки();
  настроитьОбщийПароль();
  командаОбщаяПривязать(async (включить) => {
    const ст = await api("/project-status/team-shared", { method: "POST", json: { enabled: включить } });
    if (_monitoringCache) _monitoringCache.team_shared = ст;
    return ст;
  });
  document.getElementById("backup-now-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api("/project-status/monitoring/backup-now", { method: "POST" });
      toast("Копия базы сделана");
      _monitoringCache = await api("/project-status/monitoring", {});
      renderMonitoringStatic();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
  document.getElementById("conflict-drop-save-btn")?.addEventListener("click", async () => {
    const сырое = (document.getElementById("conflict-drop-input").value || "").trim();
    // как поле Планёрки: целое больше нуля — ошибка в пороге удаления необратима
    if (!/^\d+$/.test(сырое) || parseInt(сырое, 10) < 1 || parseInt(сырое, 10) > 365) { toast("Срок — целое число дней от 1 до 365, без запятых и букв", true); return; }
    try {
      await api("/project-status/conflict-drop-days", { method: "POST", json: { days: parseInt(сырое, 10) } });
      toast(`Нерешённые карточки удаляются через ${сырое} дн.`);
      _monitoringCache = await api("/project-status/monitoring", {});
      renderMonitoringStatic();
    } catch (err) { toast(err.message, true); }
  });
  document.getElementById("log-keep-save-btn")?.addEventListener("click", async () => {
    const сырое = (document.getElementById("log-keep-input").value || "").trim();
    if (!/^\d+$/.test(сырое) || parseInt(сырое, 10) > 3650) { toast("Срок — целое число дней от 0 до 3650, без запятых и букв", true); return; }
    try {
      await api("/project-status/service-log-keep", { method: "POST", json: { days: parseInt(сырое, 10) } });
      toast(parseInt(сырое, 10) ? `Служебные журналы хранятся ${сырое} дн.` : "Чистка служебных журналов выключена");
      _monitoringCache = await api("/project-status/monitoring", {});
      renderMonitoringStatic();
    } catch (err) { toast(err.message, true); }
  });
  document.getElementById("uq-mark-toggle-btn")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api("/project-status/under-question-mark", { method: "POST", json: { enabled: m.under_question_mark === false } });
      _monitoringCache = await api("/project-status/monitoring", {});
      renderMonitoringStatic();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

// Правило пользователя 19.09.26: ЛЮБЫЕ системные сообщения — только на
// странице «Конфликты», никогда в рабочих вкладках (раньше журнал сбоев
// стоял блоком на «Статусе проекта» и показывал сырой ответ модели).
// В карточке — понятная формулировка, сырой текст и трассировка спрятаны
// под «Технические подробности».
// Назначения вызовов модели в «Расходе» — по-русски (тест двух циклов 01.10.26: было «generate/verify»).
const PURPOSE_LABELS = {
  generate: "сборка Протокола и Плана",
  verify: "проверка черновика",
  resolve_names: "определение участников",
  roadmap: "Дорожная карта и Сводка",
  probe: "пробный запрос перед сборкой",
  tasks: "задачи встречи (по темам протокола)",
  agreements: "договорённости встречи",
  unknown: "без пометки",
};

const SYSTEM_SOURCE_LABELS = {
  meeting_pipeline: "Подготовка документов встречи",
  background_refresh: "Фоновое обновление Карты и Сводки",
  unhandled: "Внутренняя ошибка сервера",
  auth: "Вход в приложение",
  document_edit: "Правка документа по запросу",
  // Источники, появившиеся 30.09.26 (разбор дня, п. 2.2): раньше показывались сырым английским ключом.
  recording_queue: "Распознавание записей",
  watch_folder: "Папка-приёмник записей",
  autorun: "Автозапуск Протокола",
  backup: "Резервные копии",
  main: "Сервер (запуск и остановка)",
  operator_rules: "Правила из решений оператора",
  source_relevance: "Проверка загруженного источника",
  system_messages: "Технические сообщения",
};

function humanizeSystemMessage(e) {
  const m = e.message || "";
  // Уведомление (без трассировки) уже написано человеческим языком: «запись поставлена в очередь», «папка изменена».
  // Раньше оно подписывалось как «Действие не выполнено из-за технической ошибки» (разбор дня 30.09.26, п. 2.2).
  if (e.source === "auth" || !e.traceback) return m;
  if (/не найден JSON|JSON|Invalid control character|Expecting/i.test(m)) return "Модель вернула ответ не в том формате. Действие не выполнено — его можно повторить.";
  if (/Нет соединения|ConnectionError|timed out|таймаут|Name or service|DNS/i.test(m)) return "Нет связи с сервисом модели. Проверьте в «Системе → Модели», что точка модели запущена и отвечает, и повторите.";   // модель в контуре — не «интернет» (Д15)
  // Код ответа — только как код ответа («ошибку 429», «HTTP 503»), а не любое число в тексте: «строк 429» — не перегрузка.
  if (/(?:ошибк\S*|HTTP|код|status)\s*(?:429|5\d\d)\b|Too Many Requests|перегруж/i.test(m)) return "Сервис модели временно перегружен. Повторите позже.";
  return "Действие не выполнено из-за технической ошибки. Подробности — ниже.";
}

async function loadAndRenderSystemMessages() {
  const $box = document.getElementById("system-messages");
  // Список карточек сворачивается общим правилом (5–8 записей) — пометки ставятся здесь, один раз.
  if ($box && !$box.dataset.list) { $box.dataset.list = "messages"; $box.dataset.listItem = "[data-error-id]"; }
  if (!$box) return;
  let items;
  let total = 0;
  try { ({ items, total } = await api("/project-status/errors?with_total=1", {})); }
  catch (e) { $box.className = "card empty-state"; $box.textContent = "Не удалось загрузить системные сообщения."; return; }
  updateConflictsBadge();
  if (!items.length) { $box.className = "card empty-state"; $box.textContent = "Системных сообщений нет."; return; }
  $box.className = "";
  const more = total > items.length
    ? `<div class="page-sub">Показаны последние ${items.length} из ${total} открытых. Закройте разобранные — покажутся следующие.</div>` : "";
  $box.innerHTML = more + items.map(e => `
    <div class="card card-output" data-error-id="${e.id}">
      <div class="page-sub" style="margin-bottom:4px">${esc(fmtDate(e.created_at))} · ${esc(SYSTEM_SOURCE_LABELS[e.source] || e.source)}${e.context ? " · " + esc(e.context) : ""}</div>
      <div>${esc(humanizeSystemMessage(e))}</div>
      <details style="margin-top:8px">
        <summary class="page-sub" style="cursor:pointer; margin:0">Технические подробности</summary>
        <pre class="sys-details">${esc(e.message)}${e.traceback ? "\n\n" + esc(e.traceback) : ""}</pre>
      </details>
      <div class="hstack" style="margin-top:12px"><button class="btn-sm system-resolve">Закрыть</button></div>
    </div>`).join("");
  $box.querySelectorAll(".system-resolve").forEach(btn => btn.addEventListener("click", async () => {
    const id = btn.closest("[data-error-id]").dataset.errorId;
    btn.disabled = true;
    try {
      await api(`/project-status/errors/${id}/resolve`, { method: "POST" });
      await loadAndRenderSystemMessages();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  }));
}

// Кнопки карточки «под вопросом» — подписи и порядок с сервера (общая с Планёркой таблица doubt_labels, решение владельца
// 15.10.26); классы — прежние, на них висят обработчики
const КЛАСС_КНОПКИ_ВОПРОСА = { accept: "btn-primary conflict-accept", custom: "conflict-custom", reject: "conflict-reject",
  duplicate: "conflict-duplicate" };
function кнопкиВопроса(actions) {
  return actions.filter(a => КЛАСС_КНОПКИ_ВОПРОСА[a.action]).map(a =>
    `<button class="btn-sm ${КЛАСС_КНОПКИ_ВОПРОСА[a.action]}"${a.action === "reject" ? ` title="Задача снимается с пометкой «не задача». Ответите так же ещё раз — станет правилом: такая задача не будет заводиться ${NOT_A_TASK_DAYS} дн."` : a.action === "duplicate" ? ' title="Такая задача уже есть в реестре — эта снимается как дубль"' : ""}>${esc(a.label)}</button>`).join("");
}

async function loadAndRenderConflicts() {
  // В «Разборе» — только карточки выбранного вида (решение владелицы 25.10.2026, `отобратьДляРазбора` в razbor.js)
  const conflicts = отобратьДляРазбора(await api("/task-conflicts?status=open", {}));
  // данные карточек — для перестройки в «карточку-вопрос» (conflicts.js, 15.10.26)
  window.конфликтыДанные = new Map(conflicts.map(c => [String(c.id), c]));
  updateConflictsBadge({ conflicts: conflicts.length }, { толькоНезаполненные: true });   // число — из этого же списка (18.10.2026)
  const $list = document.getElementById("conflicts-list");
  if (!$list) return;   // пока шёл запрос, открыли другую страницу — рисовать некуда, и это не ошибка
  if (!conflicts.length) {
    $list.className = "card empty-state";
    $list.textContent = "Открытых конфликтов нет.";
    return;
  }
  $list.className = "";
  // Решение 17.09.26 (жалоба) — 1) «Встреча не импортирована в вебапп»
  // ничего не объясняло человеку, что это и на что влияет — для этого
  // типа теперь отдельный, развёрнутый текст на понятном языке вместо
  // формальной пары «Сейчас/Предлагается», которая для встречи без
  // задачи вообще не имела смысла (там нечего сравнивать). 2) Фон карточки
  // сменён с дефолтного `.card` (плотный лавандовый градиент) на
  // `.card-output` (белый + тень) — тот же стиль, что у карточек в выдаче
  // поиска, плотная заливка на 24 карточках подряд смотрелась тяжело.
  // Задачи «под вопросом» — первыми (ответ владельца 15.10.26: фокус на работу оператора), над ними счётчик.
  const подВопросом = c => c.field === "ungrounded_task" && !!c.task_id;
  const всегоПодВопросом = conflicts.filter(подВопросом).length;
  const упорядоченные = [...conflicts.filter(подВопросом), ...conflicts.filter(c => !подВопросом(c))];
  const счётчикПодВопросом = всегоПодВопросом
    ? `<div class="card" id="uq-counter"><b>Задачи под вопросом: ${всегоПодВопросом}</b>
        <span class="page-sub">— уже в реестре; оставьте или снимите каждую</span></div>` : "";
  $list.innerHTML = счётчикПодВопросом + упорядоченные.map(c => {
    // Отметка участника по задаче (02.10.26): ведущий принимает просьбу или оставляет как есть.
    if (c.field === "member_note") {
      const [yes, no] = c.proposed_value === "done" ? ["Закрыть задачу", "Пока не закрывать"]
        : c.proposed_value ? [`Перенести срок на ${c.proposed_value}`, "Оставить срок"] : ["Прочитано", ""];
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
        <div><b>Отметка по задаче</b></div>
        ${c.task_description ? `<div class="page-sub" style="margin:4px 0">${esc(c.task_description)}</div>` : ""}
        <div style="margin:8px 0">«${esc(c.current_value || "")}»</div>
        ${c.evidence_quote ? `<div class="page-sub">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          <button class="btn-sm btn-primary conflict-accept">${esc(yes)}</button>
          ${no ? `<button class="btn-sm conflict-reject">${esc(no)}</button>` : ""}
        </div>
      </div>`;
    }
    // Очередь сборок, правило 5 (14.10.26): ранняя встреча собрана после поздних. Поздние протоколы не
    // переписываются и сами не пересобираются — администратор сверяет задачи и закрывает карточку.
    if (c.field === "rebuild_order") {
      return `<div class="card card-output conflict-card" data-id="${c.id}">
        <div><b>Ранняя встреча собрана после поздних</b></div>
        <div style="margin:8px 0">${esc(c.evidence_quote || "")}</div>
        <div class="page-sub">Протоколы более поздних встреч не переписываются и сами не пересобираются: проверьте
          в «Реестре задач», не задвоились ли задачи и не закрыты ли они раньше срока.</div>
        <div class="hstack" style="margin-top:12px">
          <button class="btn-sm conflict-reject">Задачи сверены</button>
        </div>
      </div>`;
    }
    // Проект из истории реестра (Е5, 19.10.2026, как Планёрка 17.10.26): проект связанной прошлой задачи — подсказкой, в задачу
    // не поставлен. «Подтвердить» ставит проект, «Не тот» снимает подсказку.
    if (c.field === "project_hint") {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="project_hint" data-src="${esc(c.source || "")}">
        <div><b>${esc(c.task_description || "Задача")}</b></div>
        <div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote || "")}</div>
        <div class="hstack" style="margin-top:12px">
          <button class="btn-sm btn-primary conflict-accept">Подтвердить</button>
          <button class="btn-sm conflict-reject">Не тот</button>
        </div>
      </div>`;
    }
    // Реестр договорённостей — своими кнопками, как в Планёрке (решения владелицы 21.10.2026, пункт 5; до того карточка шла общей
    // веткой «Принять предложенное / Оставить как есть / Указать своё» с подписью-именем поля). Сомнение кода — договорённость
    // уже в реестре с отметкой; замена прежней и закрытие открытой записи — только ответом оператора (`agreements.resolve_card`).
    if (c.field === "agreement_doubt" || c.field === "agreement_replace" || c.field === "agreement_close") {
      const замена = c.field === "agreement_replace" || c.field === "agreement_close";
      const закрытие = c.field === "agreement_close";
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field)}" data-src="${esc(c.source || "")}">
        <div><b>${замена ? (закрытие ? "Открытая: " : "Прежняя: ") : ""}${esc(c.current_value || "")}</b></div>
        ${замена ? `<div style="margin-top:6px">${закрытие ? "Решение" : "Новая"}: ${esc(c.proposed_value || "")}</div>` : ""}
        <div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote || "")}</div>
        <div class="hstack" style="margin-top:12px">
          <button class="btn-sm btn-primary conflict-accept">${закрытие ? "Закрыть прежнюю" : замена ? "Заменить прежнюю" : "Подтвердить"}</button>
          <button class="btn-sm conflict-reject">${закрытие ? "Оставить открытой" : замена ? "Оставить обе" : "Не договорённость"}</button>
        </div>
      </div>`;
    }
    if (c.field === "missing_meeting") {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
        <div><b>Встреча ${esc(c.proposed_value)} не загружена в приложение</b></div>
        <div class="page-sub" style="margin:8px 0">Файлы этой встречи есть среди материалов проекта, но
          обработка через приложение не выполнена — значит задачи и решения с этой встречи не попали
          в реестр задач и не учтены в статистике проекта.</div>
        ${c.evidence_quote ? `<div class="page-sub">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px">
          <button class="btn-sm conflict-reject">Понятно, учту отдельно</button>
        </div>
      </div>`;
    }
    // Похожая задача (30.09.26, «06» Планёрки): предмет тот же, действие может быть другим —
    // обе формулировки рядом, решает человек.
    if (c.field === "duplicate_task") {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-kind="task-proposal" data-proposed="${esc(c.proposed_value || "")}">
        <div><b>Это одна задача или две?</b></div>
        <div style="margin:8px 0">В реестре: «${esc(c.current_value || "")}»</div>
        <div style="margin:8px 0">Новая формулировка: «${esc(c.proposed_value || "")}»</div>
        ${c.evidence_quote ? `<div class="page-sub">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          <button class="btn-sm btn-primary conflict-accept">Это другая задача — завести</button>
          <button class="btn-sm conflict-custom">Завести со своей формулировкой</button>
          <button class="btn-sm conflict-reject">Это та же задача — не заводить</button>
        </div>
      </div>`;
    }
    // Задача без опоры во фразе источника. С 04.10.26 (решение владельца «задача фиксируется») задача Протокола уже в реестре
    // с пометкой — карточка спрашивает, оставить ли её; без заведённой задачи (единицы встречи) — завести ли (30.09.26).
    if (c.field === "ungrounded_task" && c.task_id) {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-kind="task-proposal" data-proposed="${esc(c.proposed_value || "")}">
        <div><b>Задача №${esc(String(c.task_id))} в реестре под вопросом — оставить?</b></div>
        <div style="margin:8px 0">«${esc(c.proposed_value || "")}»</div>
        ${c.current_value ? `<div class="page-sub">Модель сослалась на фразу: «${esc(c.current_value)}»</div>` : ""}
        ${c.evidence_quote ? `<div class="page-sub" style="margin-top:4px">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${(c.actions || []).length ? кнопкиВопроса(c.actions) : `<button class="btn-sm btn-primary conflict-accept">Оставить</button>
          <button class="btn-sm conflict-custom">Оставить со своей формулировкой</button>
          <button class="btn-sm conflict-reject" title="Задача снимается с пометкой «не задача». Ответите так же ещё раз — станет правилом: такая задача не будет заводиться ${NOT_A_TASK_DAYS} дн. Правила видны и отменяются в «Параметрах системы» → «Правила из решений»">Снять: это не задача</button>`}
        </div>
      </div>`;
    }
    if (c.field === "ungrounded_task") {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-kind="task-proposal" data-proposed="${esc(c.proposed_value || "")}">
        <div><b>Завести эту задачу?</b></div>
        <div style="margin:8px 0">«${esc(c.proposed_value || "")}»</div>
        ${c.current_value ? `<div class="page-sub">Модель сослалась на фразу: «${esc(c.current_value)}»</div>` : ""}
        ${c.evidence_quote ? `<div class="page-sub" style="margin-top:4px">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          <button class="btn-sm btn-primary conflict-accept">Завести</button>
          <button class="btn-sm conflict-custom">Завести со своей формулировкой</button>
          <button class="btn-sm conflict-reject" title="Закрывает эту карточку. Ответите так же ещё раз — станет правилом: такая задача не будет предлагаться ${NOT_A_TASK_DAYS} дн. Правила видны и отменяются в «Параметрах системы» → «Правила из решений»">Не заводить</button>
        </div>
      </div>`;
    }
    // Запись встречи вне обычной длительности (Milestone 1, 30.09.26): два ответа, «своего значения» нет —
    // до этой правки карточка показывала общие кнопки, и «Указать своё» получало отказ сервера.
    if (c.field === "units_chunk_not_parsed") {
      // Кусок записи не разобран моделью (14.10.26, по находке Планёрки): поручения из него могли не попасть в реестр.
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
        <div><b>Кусок записи не разобран моделью — поручения из него могли не попасть в реестр</b> <span class="page-sub">(${esc(c.current_value || "")})</span></div>
        ${c.evidence_quote ? `<div class="page-sub" style="margin:8px 0; white-space:pre-line">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          <button class="btn-sm btn-primary conflict-accept">Пересобрать</button>
          ${c.meeting_id ? `<a class="btn-sm" href="#meetings/${c.meeting_id}/protocol">Открыть встречу</a>` : ""}
          <button class="btn-sm conflict-reject">Принято к сведению</button>
        </div>
      </div>`;
    }
    if (c.field === "later_protocols_first") {
      // Очередь сборок, правило 5 (14.10.26): Протокол ранней встречи собран после поздних — поздние не переписаны.
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
        <div><b>Протоколы более поздних встреч собраны до неё — сверить задачи</b> <span class="page-sub">(${esc(c.current_value || "")})</span></div>
        ${c.evidence_quote ? `<div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${c.meeting_id ? `<a class="btn-sm" href="#meetings/${c.meeting_id}/protocol">Открыть встречу</a>` : ""}
          <button class="btn-sm btn-primary conflict-accept">Сверено</button>
        </div>
      </div>`;
    }
    if (c.field === "held_recording") {
      // Не распознанная запись (01.10.26) — та же карточка, свои слова на кнопках: «повторить / удалить».
      const failed = (c.source || "").startsWith("recording_failed:");
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
        <div><b>${esc(c.proposed_value || "Распознать запись?")}</b> <span class="page-sub">(${esc(c.current_value || "")})</span></div>
        ${c.evidence_quote ? `<div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote)}</div>` : ""}
        <div class="hstack" style="margin-top:12px">
          <button class="btn-sm btn-primary conflict-accept">${failed ? "Повторить распознавание" : "Распознать"}</button>
          <button class="btn-sm conflict-reject">${failed ? "Удалить запись" : "Это не наша запись"}</button>
        </div>
      </div>`;
    }
    if (c.field === "external_unheard") {
      // Подтверждённый внешний назван в протоколе, а в записи рядом с местом абзаца не звучит (решение владелицы 24.10.2026,
      // вариант «а»). Одна карточка на протокол, списком; текст протокола код не меняет — правку делает человек.
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="external_unheard" data-src="${esc(c.source || "")}">
        <div><b>Внешний упомянут без звучания в записи — протокол ${esc(c.current_value || "")}</b></div>
        <div class="page-sub cf-why" style="margin:8px 0; white-space:pre-line">${esc(c.evidence_quote || "")}</div>
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${c.meeting_id ? `<a class="btn-sm btn-primary" href="#meetings/${c.meeting_id}/protocol">Открыть Протокол</a>` : ""}
          <button class="btn-sm conflict-reject">Понятно, закрыть</button>
        </div>
      </div>`;
    }
    if (c.source === "review_finding" || c.field === "no_tasks_with_assignment_lines" || c.source === "due_notes_vs_record") {
      // Замечание проверки Протокола (решение владельца 03.10.26): Протокол уже сохранён, карточка — что поправить, если надо.
      // «Поручения в записи — задач нет» (13.10.26) — тот же вид: строки с формой поручения, задачи по ним не заводились.
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-source="${esc(c.source)}">
        <div><b>${c.field === "no_tasks_with_assignment_lines" ? `Модель не вернула поручений — ${esc(c.current_value || "")}`
          : c.source === "due_notes_vs_record" ? `Срок: заметки и расшифровка расходятся (${esc(c.current_value || "")}; ${esc(c.proposed_value || "")})`
          : `Замечание проверки: ${esc(c.current_value || "")}`}</b></div>
        <div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote || "")}</div>
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${c.meeting_id ? (c.document === "plan"     // замечание к Плану (15.10.26) — ссылка на План встречи
            ? `<a class="btn-sm btn-primary" href="#meetings/${c.meeting_id}">Открыть План</a>`
            : `<a class="btn-sm btn-primary" href="#meetings/${c.meeting_id}/protocol">Открыть Протокол</a>`) : ""}
          ${/* Решение владельца 17.10.26 (как у Планёрки): у замечания проверки два ответа. «Неверно» удаляет карточку насовсем,
                а пересборка то же замечание больше не заводит. */ c.source === "review_finding"
            ? `<button class="btn-sm conflict-accept">Замечание верное</button>
          <button class="btn-sm conflict-reject">Замечание неверно</button>`
            : `<button class="btn-sm conflict-reject">Принято к сведению</button>`}
        </div>
      </div>`;
    }
    if (c.source === "unconfirmed_person" && c.identity) {
      // Правило «один человек или два» (03.10.26): «кто из тёзок?» / «тот же или новый?» — выбор человека по id
      const same = c.identity === "same_or_new";
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-source="unconfirmed_person" data-identity="${esc(c.identity)}" data-name="${esc(c.current_value)}">
        <div><b>${same ? `«${esc(c.current_value)}» — тот же человек или новый?` : `«${esc(c.current_value)}» — кто из тёзок?`}</b></div>
        <div class="page-sub" style="margin:8px 0">${esc(c.evidence_quote || "")}</div>
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${(c.candidates || []).map(p => `<button class="btn-sm btn-primary identity-pick" data-person="${p.id}" title="${esc(p.note || "")}">Это ${esc(p.name)}${p.note ? ` · ${esc(p.note)}` : ""}</button>`).join("")}
          <button class="btn-sm conflict-custom">Новый человек — завести с ролью</button>
          <button class="btn-sm conflict-delete">Не человек</button>
          <button class="btn-sm conflict-reject">${c.task_id ? "Оставить без исполнителя" : "Пока не заводить"}</button>
        </div>
      </div>`;
    }
    if (c.source === "unconfirmed_person") {
      return `<div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}" data-source="unconfirmed_person"${c.no_contact ? ' data-nocontact="1"' : ""} data-name="${esc(c.current_value)}">
        ${c.task_id && c.task_description ? `<div class="page-sub">${esc(c.task_description)}</div>` : ""}
        <div><b>Кто такой(ая) «${esc(c.current_value)}»?</b></div>
        <div class="page-sub" style="margin:8px 0">${esc(personConflictNote(c))}</div>
        ${personEvidence(c) ? `<div class="page-sub">${esc(personEvidence(c))}</div>` : ""}
        ${кандидатыЧеловекаHtml(c)}
        <div class="hstack" style="margin-top:12px; flex-wrap:wrap">
          ${c.proposed_value ? `<button class="btn-sm btn-primary conflict-accept">Это ${esc(c.proposed_value)}</button>` : ""}
          <button class="btn-sm btn-primary conflict-custom">Уточнить ФИО или роль и подтвердить</button>
          ${c.no_contact ? "" : `<button class="btn-sm conflict-confirm">Подтвердить — это реальный сотрудник</button>`}
          <button class="btn-sm conflict-delete">${c.no_contact ? "Не человек" : "Удалить из «Команды»"}</button>
          <button class="btn-sm conflict-reject">Пока оставить неподтверждённым</button>
        </div>
      </div>`;
    }
    // Общая карточка — только ответы, которые сервер принимает (`card_policy.ответы`, решения владелицы 21.10.2026, п. 3; как в
    // Планёрке): у подсказки голоса, предложения пересборки и «модель не готова» «Указать своё» нет — сервер его не принимал
    const отв = c.answers && c.answers.length ? c.answers : ["accept", "reject", "custom"];
    return `
    <div class="card card-output conflict-card" data-id="${c.id}" data-field="${esc(c.field || "")}" data-src="${esc(c.source || "")}">
      <div class="page-sub">${c.task_id
        ? (c.task_description ? esc(c.task_description) : "задача из реестра")
        : esc(CONFLICT_FIELD_LABELS[c.field] || c.field)}</div>
      <div><b>${esc(CONFLICT_FIELD_LABELS[c.field] || c.field)}</b>${c.confidence ? ` <span class="page-sub">(уверенность: ${esc(CONFLICT_CONFIDENCE_LABELS[c.confidence] || c.confidence)})</span>` : ""}</div>
      <div class="hstack" style="margin:8px 0; flex-wrap:wrap">
        <div>Сейчас: <b>${esc(conflictValueLabel(c.field, c.current_value) || "—")}</b></div>
        <div class="page-sub">→</div>
        <div>Предлагается: <b>${esc(conflictValueLabel(c.field, c.proposed_value) || "—")}</b></div>
      </div>
      ${c.evidence_quote ? `<div class="page-sub">${esc(c.evidence_quote)}</div>` : ""}
      <div class="hstack" style="margin-top:12px">
        ${/* Владелец 15.10.26: «нажимаю на кнопку „принять предложение“ — нет действий»: неактивная кнопка без предложения
              выглядела как обычная. Предлагать нечего — кнопки нет (как у «Это …» ниже); остаются «Указать своё» и «Оставить». */ ""}
        ${c.proposed_value && отв.includes("accept") ? `<button class="btn-sm btn-primary conflict-accept">Принять предложенное</button>` : ""}
        ${отв.includes("reject") ? `<button class="btn-sm conflict-reject">Оставить как есть</button>` : ""}
        ${отв.includes("custom") ? `<button class="btn-sm conflict-custom">Указать своё</button>` : ""}
      </div>
    </div>`;
  }).join("");

  // Промпт «пять экранов», Экран 1 (24.09.26): «видимый номер с единицы — сквозной по текущему
  // списку, системный — в подсказке при наведении». Тот же приём, что у F10/F23 (реестр задач и
  // таблицы в документах) — номер по порядку в СПИСКЕ, не по id записи в базе.
  $list.querySelectorAll(".conflict-card").forEach((card, i) => {
    card.insertAdjacentHTML("afterbegin", `<span class="conflict-num" title="Внутренний номер: ${card.dataset.id}">№${i + 1}</span>`);
    const id = card.dataset.id;
    card.querySelector(".conflict-accept")?.addEventListener("click", async () => {
      try { await resolveConflict(id, "accept", null, {}, card); } catch (e) { toast(e.message, true); }
    });
    card.querySelector(".conflict-reject")?.addEventListener("click", async () => {
      try { await resolveConflict(id, "reject", null, {}, card); } catch (e) { toast(e.message, true); }
    });
    card.querySelector(".conflict-duplicate")?.addEventListener("click", async () => {
      try { await resolveConflict(id, "duplicate", null, {}, card); } catch (e) { toast(e.message, true); }
    });
    card.querySelector(".conflict-confirm")?.addEventListener("click", async () => {
      try { await resolveConflict(id, "confirm", null, {}, card); } catch (e) { toast(e.message, true); }
    });
    card.querySelectorAll(".identity-pick").forEach(btn => btn.addEventListener("click", async () => {
      try {
        await resolveConflict(id, "accept", null, { person_id: Number(btn.dataset.person) }, card);
      } catch (e) { toast(e.message, true); }
    }));
    card.querySelector(".conflict-delete")?.addEventListener("click", async () => {
      const ask = card.dataset.identity || card.dataset.nocontact
        ? `«${card.dataset.name}» — не человек? Задача не заведётся, написание запомнится.`
        : `Удалить «${card.dataset.name}» из «Команды»? Запись исчезнет, конфликт закроется.`;
      if (!(await confirmDialog(ask, card.dataset.identity || card.dataset.nocontact ? "Не человек" : "Удалить"))) return;
      try { await resolveConflict(id, "delete"); } catch (e) { toast(e.message, true); }
    });
    card.querySelector(".conflict-custom")?.addEventListener("click", () => {
      if (card.dataset.source === "unconfirmed_person") {
        // «новый» на карточке «тот же или новый» — сразу внешний: рядом прозвучала чужая организация
        openIdentityDialog(id, card.dataset.name, card.dataset.identity === "same_or_new" ? { prefill: { external: true } } : {});
        return;
      }
      if (card.dataset.kind === "task-proposal") {
        const ov = openModal("Завести со своей формулировкой", `
          <div class="field"><label>Формулировка задачи</label><textarea id="modal-custom-value" rows="3"></textarea></div>
        `, async (o) => {
          const value = o.querySelector("#modal-custom-value").value.trim();
          if (!value) throw new Error("Впишите формулировку");
          await resolveConflict(id, "custom", value);
        });
        const $t = ov.querySelector("#modal-custom-value");
        $t.value = card.dataset.proposed || "";
        $t.focus();
        return;
      }
      const person = card.dataset.source === "unconfirmed_person";
      const overlay = openModal(person ? "Уточнить ФИО" : "Указать своё значение", person ? `
        <div class="field"><label>Фамилия и Имя <span class="req">*</span></label><input type="text" id="modal-custom-value" autocomplete="off" placeholder="Например: Иванова Мария">
          <div class="field-hint">Обязательны Фамилия и Имя; отчество — по желанию.</div></div>
      ` : `
        <div class="field"><label>Значение</label><input type="text" id="modal-custom-value" autocomplete="off"></div>
      `, async (ov) => {
        const value = ov.querySelector("#modal-custom-value").value.trim();
        if (!value) throw new Error("Введите значение");
        if (person) { const problem = checkFullName(value); if (problem) throw new Error(problem); }
        await resolveConflict(id, "custom", value);
      });
      overlay.querySelector("#modal-custom-value").focus();
    });
  });
}

// Из строки-основания показываем только то, чего нет в пояснении: кандидатов из «Команды» (и цитату — если у контакта нет задачи)
// Кандидаты на карточке «кто это» — кнопками, а не текстом (указание владельца 05.10.26: связывать
// существующего человека одним кликом). На карточке тёзок кандидатов даёт конвейер, здесь их нет, и
// раньше в пояснении стояло «Возможные варианты: …» — по этим словам надо было ещё попасть в нужную
// строку руками. Ищем по названному слову среди подтверждённых и включённых: неподтверждённую запись
// сервер ссылкой не примет.
function кандидатыЧеловека(названо) {
  const норма = (s) => String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я\s-]/gi, " ").trim();
  const слово = норма(String(названо || "").split(/[(\s]/)[0]);
  if (слово.length < 3) return [];
  return (allUsers || []).filter(u => u.is_confirmed !== false && u.is_active !== false
    && норма(u.full_name).includes(слово)).slice(0, 6);
}

function кандидатыЧеловекаHtml(c) {
  const люди = кандидатыЧеловека(c.current_value);
  if (!люди.length) return "";
  return `<div class="page-sub" style="margin:8px 0 0">Есть похожие записи в «Команде» — выберите одним нажатием:</div>
    <div class="hstack" style="margin-top:6px; flex-wrap:wrap">${люди.map(u =>
      `<button class="btn-sm identity-pick" data-person="${u.id}"
         title="Закрепить задачу за этим человеком">Это ${esc(u.full_name)}</button>`).join("")}</div>`;
}

function personEvidence(c) {
  const ev = c.evidence_quote || "";
  const cands = (ev.match(/Возможные варианты:[^\n]*/) || [])[0];
  if (cands) return cands;
  return c.task_id ? "" : ev;
}

// Пояснение на карточке: почему запись оказалась в «Конфликтах» (Доработки 2, п. 1.5).
function personConflictNote(c) {
  const date = ((c.evidence_quote || "").match(/Протокол (\d{2}\.\d{2}\.\d{2})/) || [])[1];
  const oneWord = c.current_value && !/\s/.test(c.current_value);
  const rule = oneWord ? `Правило от 20.09.26: сотрудник регистрируется с фамилией и именем полностью. Указано одно слово — «${c.current_value}». ` : "";
  const origin = c.task_id
    ? `Назван ответственным в задаче «${c.task_description || ""}»${date ? " встречи " + date : ""}. `
    : `Назван(а) в протоколе${date ? " встречи " + date : ""}. `;
  // «Сомнительное сопоставление» (карточка `_conflicts_for_uncertain_matches`) записи в «Команде» не заводит — раньше
  // и на ней стояло «заведена как «не подтверждено»», а записи не было (тест двух циклов 01.10.26).
  const inTeam = /сопоставлен с/.test(c.evidence_quote || "")
    ? "Модель сопоставила это написание с человеком из «Команды», но на его имя оно не похоже — подтвердите, он ли это, или уточните ФИО. Новой записи в «Команде» не заводилось."
    : /Возможные варианты/.test(c.evidence_quote || "")
    ? "В «Команде» есть несколько похожих людей — укажите, кто именно."
    : c.no_contact || oneWord
    ? "В «Команде» такого человека нет и записи не заводилось — заведите его с фамилией и именем («Уточнить»), внешнего — с организацией и ролью."
    : "В «Команде» такой записи не было — она заведена как «не подтверждено».";
  return rule + origin + inTeam;
}

// Окно «Уточнить ФИО или роль и подтвердить»: та же форма, что в «Команде», заполненная данными записи; всё сохраняется одним
// действием вместе с подтверждением.
async function openIdentityDialog(id, name, opts = {}) {
  let contact = null, known = null;
  try {
    const users = await api("/users");
    const нз = (s) => String(s || "").trim().toLowerCase().replace(/ё/g, "е");   // «е» = «ё» (26.10.2026)
    contact = users.find(u => u.is_confirmed === false && нз(u.full_name) === нз(name));
    known = rosterNameTokens(users);
  } catch (e) { /* без предзаполнения и без распознавания падежа */ }
  const parts = splitPersonName(name, known);
  const ov = openModal("Уточнить ФИО или роль", `
    <div class="page-sub" style="margin-bottom:8px">Сотруднику нужны фамилия и имя полностью. Внешнему контакту достаточно фамилии или имени, если заполнена «Роль на проекте».</div>
    ${identityFieldsHtml("idlg", { ...parts, projectRole: contact?.project_role, position: contact?.role, department: contact?.department, external: contact?.is_external,
                                organization: contact?.organization, ...(opts.prefill || {}) })}
  `, async (o) => {
    const v = readIdentityForm("idlg");
    const problem = identityProblem(v);
    if (problem) { showIdentityHint("idlg", problem); throw new Error(problem); }
    await resolveConflict(id, "custom", v.fullName, {
      project_role: v.projectRole || null, role: v.position || null, department: v.department || null, is_external: v.external,
      organization: v.organization || null, name_short_reason: v.nameShortReason || null });
  });
  const _save = ov.querySelector("#modal-save");
  if (_save) _save.textContent = "Подтвердить";
  ov.querySelector(".modal-card").classList.add("modal-wide");   // те же поля, что в «Новом участнике» (14.10.26)
  wireIdentityHints("idlg");
  ov.querySelector(parts.last && !parts.first ? "#idlg-first" : (parts.first ? "#idlg-last" : "#idlg-first")).focus();
}

async function resolveConflict(id, action, customValue, extra = {}, card = null) {
  await api(`/task-conflicts/${id}`, { method: "PATCH", json: { action, custom_value: customValue, ...extra } });
  // Карточка уходит с экрана СРАЗУ и в сообщении сказано, что именно закрыто и сколько осталось
  // (замечание владельца 07.10.26: «при нажатии на кнопки замечания не уходят с экрана»). Кнопки
  // работали — решение сохранялось, — но обратной связи не было видно: после перерисовки на месте
  // закрытой карточки оказывалась почти такая же, и нажатие выглядело как «ничего не произошло».
  const чтоЗакрыли = card ? (card.querySelector("div")?.textContent || "").trim().slice(0, 70) : "";
  card?.remove();
  await loadAndRenderConflicts();
  const осталось = document.querySelectorAll("#conflicts-list .conflict-card").length;
  toast(чтоЗакрыли
    ? `Закрыто: «${чтоЗакрыли}». Осталось неразобранных: ${осталось}`
    : `Решение принято. Осталось неразобранных: ${осталось}`);
}


// Сведение 18.10.26: блок дат стенда стоит до пульта «Моделей» — пульт идёт до конца файла, одинаково с Планёркой.
// Даты на экране — дд.мм.гггг чч:мм (правило владельца 09.10.26), где бы их ни отдал сервер. Обход 19 экранов 15.10.26 нашёл
// ISO-записи на «Мониторинге» и «Моделях» («2026-10-13 15:39:33»); Планёрка у себя — так же (5412b8d). После любой отрисовки
// основной области запись даты в тексте переводится; поля ввода, код и пути к файлам не трогаются (имя файла не искажаем).
function датыПоРусски(корень) {
  const обход = document.createTreeWalker(корень, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => n.parentElement && !n.parentElement.closest("input, textarea, select, code, pre, script, style")
      && /\d{4}-\d{2}-\d{2}/.test(n.textContent) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const узлы = [];
  for (let n = обход.nextNode(); n; n = обход.nextNode()) узлы.push(n);
  узлы.forEach(n => {
    const стало = n.textContent.replace(/(^|[^\w\\/.-])(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?(?![\w\\/-]|\.\w)/g,
      (_, до, г, м, д, ч, мин) => `${до}${д}.${м}.${г}${ч ? ` ${ч}:${мин}` : ""}`);
    if (стало !== n.textContent) n.textContent = стало;
  });
}
(() => {
  let ждёт = false;
  new MutationObserver(() => {
    if (ждёт) return;
    ждёт = true;
    setTimeout(() => { ждёт = false; датыПоРусски($main); }, 0);   // не rAF: в скрытой вкладке он не срабатывает
  }).observe($main, { childList: true, subtree: true });
})();


// Слова, которыми эта система называет свои экраны, — для пояснения о внешней модели (14.10.26). Сам текст пояснения
// одинаков в обеих системах и живёт в renderModelRoutes; отличаются только эти два места.
const МОДЕЛИ_СЛОВА = {
  расход: "вкладке «Расход» в «Параметрах системы»",
  сообщения: "«Системных сообщениях»",
  // В этой версии «Модели» видит только супер-администратор, поэтому строки про администратора проекта нет —
  // как в Планёрке (вариант текста [ERP | Планёрка] из инструкции, редакция 3).
  админ_проекта: "",
};

// Модели (решение владельца 09.10.26) — пульт оператора маршрутов. Роли: основная и запасные, «Сделать основной»,
// «Добавить запасной», «Убрать». Справочник подключений: завести новое (даже без адреса — заготовка), изменить,
// «Проверить связь» до сохранения, удалить. «Откатить» возвращает файл к версии до последнего изменения. Права
// проверяет сервер. Функция одинакова в Планёрке и ERP, разница — адрес и параметры запроса.
// Стоимость вызовов модели (решение владельца 15.10.26): от поставщика, а если он цену не вернул — токены × тариф точки.
// Функция одинакова в ERP и Планёрке до знака (держит scripts/proverka_zerkalnosti_pravok.py): суммы, пометки и даты
// сервер отдаёт готовыми строками («0,04 $», дд.мм.гггг) — экран их только раскладывает. `полная` — с разбивкой по
// встречам, моделям и точкам; `встреча` — как продукт называет встречу («Встреча», «Планёрка»).
function стоимостьМоделиHtml(c, полная, встреча) {
  if (!c || !c.periods) return `<div class="page-sub">Стоимость не измеряется: сервер не отдал сводку.</div>`;
  const токены = к => к.calls
    ? `<div class="page-sub">вызовов ${к.calls} · токены: ${esc(к.tokens)}${к.cache_unknown_calls ? ` · кэш не записан у ${к.cache_unknown_calls}` : ""}</div>` : "";
  const строка = (подпись, к) => `<tr><td class="mon-key">${esc(подпись)}</td><td class="mon-val">${esc(к.label)}${токены(к)}</td></tr>`;
  // Предел расхода в месяц — по каждому поставщику отдельно (решение владельца 15.10.26): 90 % — предупреждение,
  // 100 % — платные вызовы этого поставщика остановлены, другие работают.
  const пределы = (c.providers || []).map(п => `<tr><td class="mon-key">Поставщик: ${esc(п.title)}</td><td class="mon-val">${
    п.state === "stop" ? `<span class="badge badge-danger">${esc(п.label)}</span>` : п.state === "warn"
      ? `<span class="badge badge-warning">${esc(п.label)}</span>` : esc(п.label)}</td></tr>`).join("");
  let html = `<table class="mon-table">${c.periods.map(п => строка(п.title, п)).join("")}
    <tr><td class="mon-key">Тариф не задан</td><td class="mon-val">${esc(c.no_tariff.label)}</td></tr>${пределы}</table>`;
  if (полная) {
    const блок = (заголовок, строки) => `<h3 style="margin:16px 0 4px">${esc(заголовок)}</h3>${строки.length
      ? `<table class="mon-table">${строки.join("")}</table>` : `<div class="page-sub">вызовов не было</div>`}`;
    html += блок(`По ${встреча === "Планёрка" ? "планёркам" : "встречам"} — последние, за 30 дней`, c.by_meeting.map(в =>
      строка(`${встреча} ${в.meeting_id} · последний вызов ${в.last_call}`, в)));
    html += блок("По моделям — за 30 дней", c.by_model.map(м => строка(м.model, м)));
    html += блок("По точкам (подключениям) — за 30 дней", c.by_route.map(т => строка(т.route, т)));
    if (c.tariffs.length) html += `<div class="page-sub" style="margin-top:8px">Расчёт по тарифу: ${c.tariffs.map(esc).join("; ")}.</div>`;
    if (c.backdated_calls) html += `<div class="page-sub">Задним числом посчитано вызовов: ${c.backdated_calls} — записаны до 15.10.2026 без стоимости; кэш в таких строках ERP не записан, сумма — верхняя оценка.</div>`;
    if (c.probes && c.probes.calls) html += `<div class="page-sub">${esc(c.probes.label)}.</div>`;
  }
  return html + `<div class="page-sub" style="margin-top:8px">${esc(c.note)} Данные на ${esc(c.as_of)}, дни — по Москве.</div>`;
}

// Рассуждение точки так, как оно уйдёт в вызов (решение владелицы 27.10.2026; близнец model_routes.reasoning_sent).
// DeepSeek на точке openai/openrouter при «как у модели» — выключено (решение 16.10.2026 «вернуть в статус 0»); Claude
// по адресу api.anthropic.com — «как у модели» = понемногу (low), high — полностью, выключить нельзя.
function адресClaude(url) {
  return /^https?:\/\/api\.anthropic\.com(?=[:/?#]|$)/i.test(String(url || "").trim());
}
function рассуждениеТочки(kind, model, url, reasoning) {
  const режим = reasoning || "auto";
  if (kind !== "openai" && kind !== "openrouter") return "";
  if (kind === "openai" && адресClaude(url)) return режим === "high" ? "полностью (high)" : "понемногу (low)";
  if (режим === "none" || (режим === "auto" && String(model || "").toLowerCase().includes("deepseek"))) return "выключено";
  if (режим === "low") return "понемногу (low)";
  if (режим === "high") return "полностью (high)";
  return "";
}
function рассуждениеСтрокой(kind, model, url, reasoning) {
  const р = рассуждениеТочки(kind, model, url, reasoning);
  return р === "выключено" ? "рассуждение выключено" : р ? `рассуждение: ${р}` : "";
}

async function renderModelRoutes(el, base, apiOpts = {}) {
  if (!el) return;
  const keep = { bookOpen: !!el.querySelector("details.model-book[open]") };
  let d;
  try { d = await api(base, Object.assign({}, apiOpts)); }
  catch (e) { el.innerHTML = `<div class="page-sub">Не удалось получить маршруты моделей: ${esc(e.message)}</div>`; return; }
  const shortModel = m => String(m || "").split(String.fromCharCode(92)).join("/").replace(/^.*models--[^/]*--([^/]+)[/]snapshots[/].*$/, "$1");
  // Модель точки: у распознавания её может и не быть (сервис сети, свой код, модель на этой машине) —
  // писать таким точкам «из переменных окружения» значит врать (владелец 12.10.26: «исправь
  // соответственно переменные окружения — отобразить корректно на текущий момент»).
  const чейМодель = (p) => shortModel(p.model)
    || (p.kind === "asr-service" ? "сервис в сети, модель выбирает он"
      : p.kind === "python" ? "свой код на этой машине"
      : p.kind === "faster-whisper" ? "модель на этой машине"
      : "модель задаётся переменными окружения");

  const ROLE = d.role_titles || { asr: "Распознавание речи", generate: "Генерация черновика", verify: "Проверка черновика", agreements: "Договорённости (отдельный вызов)", guard: "Досмотр реплик к системе" };
  // Подсказка о том, КОГДА применится смена модели (владелец 12.10.26): без неё переключение на живой
  // сборке выглядит как «переключил, а модель не сменилась». Формулировка одна на панель, тултипы и
  // подпись у кнопок — чтобы слова не разошлись.
  const ПОДСКАЗКА_СМЕНЫ = "Смена модели или подключения применяется к следующей попытке вызова — перезапуск не нужен. "
    + "Уже идущий запрос дождётся своего таймаута (при молчании модели — до 10 минут: две попытки по 5). "
    + "Если идёт сборка, её шаги, посчитанные прежней моделью, обесцениваются — сборка продолжится с начала.";
  const post = (path, json) => api(base + path, Object.assign({ method: "POST", json }, apiOpts));
  // Внешние модели с ключом (решение владельца 14.10.26). Тексты — дословно из «Инструкции оператору — внешние
  // модели»; отличаются в двух системах только названия экранов (МОДЕЛИ_СЛОВА рядом с функцией).
  const СЛОВА = (typeof МОДЕЛИ_СЛОВА === "object" && МОДЕЛИ_СЛОВА) || {};
  const ПОДСКАЗКА_КЛЮЧА = "Внешняя модель работает за пределами контура компании. Ей уходит текст встречи, заметки и состав команды. "
    + "Запись голоса не уходит никогда — распознавание всегда идёт на своей машине. Ключ вводится один раз: после сохранения "
    + "он больше не показывается, видно только «ключ задан · …XXXX». Перед сохранением нажмите «Проверить связь». "
    + "Подробно — «Как подключить внешнюю модель» внизу страницы.";
  const внешняяМетка = `<span class="badge badge-neutral" style="margin-left:6px">внешняя</span>`;
  const внутреннийАдрес = (url) => {
    let host = "";
    try { host = new URL(url).hostname.toLowerCase(); } catch (e) { return false; }
    if (!host) return false;
    if (host === "localhost" || !host.includes(".") || /\.(local|lan|internal)$/.test(host)) return true;
    const ip = host.replace(/^\[|\]$/g, "");
    return /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(ip) || ip === "::1" || /^f[cd]/.test(ip);
  };
  const внешняяФорма = (kind, url) => kind === "openrouter" || ((kind === "openai" || kind === "ollama") && !!url && !внутреннийАдрес(url));
  if (!d.switchable) { el.innerHTML = `<div class="page-sub">${esc(d.note)}</div>`; return; }
  const kinds = d.kinds || {};
  const forRole = role => k => (kinds[k] || {}).for === (role === "asr" ? "asr" : "text");
  // «Договорённости (отдельный вызов)» — с 18.10.2026: своя модель назначается здесь же; без неё — «как у черновика».
  // «Досмотр реплик к системе» (guard) — с 20.10.2026: необязательная, генерацию не наследует; не назначена — только правила.
  const order = ["asr", "generate", "verify", "agreements", "guard"].filter(r => d.roles[r]);
  const roles = order.map(role => {
    const pts = d.roles[role];
    // 16.10.26 (решение владельца, Д2): переменные окружения модель роли не задают. Роль без точки — «не настроена»;
    // проверка без своей точки идёт на модель черновика (исключение 13.10.26) — показано явно; из переменных — только
    // распознавание (WEBAPP_WHISPER_MODEL).
    const изПеременных = pts.length === 1 && pts[0].name.startsWith("env");
    const поЧерновику = !!(d.inherited || {})[role];
    const inFile = pts.length > 0 && !изПеременных && !поЧерновику;
    const opts = (d.options || {})[role] || [];
    const spare = opts.filter(o => !pts.some(p => p.name === o.name));
    return `<h3 style="margin:18px 0 4px">${esc(ROLE[role] || role)}</h3>
    ${(inFile ? spare : opts).length ? `<div class="hstack" style="margin:6px 0 8px; gap:8px; flex-wrap:wrap; align-items:center">
        <span class="page-sub" style="margin:0">Резерв из реестра:</span>
        <select data-route-pick="${esc(role)}" style="min-width:300px; flex:0 1 420px">${(inFile ? spare : opts).map(o =>
          `<option value="${esc(o.name)}">${esc(o.name)} — ${esc(shortModel(o.model) || o.kind)}</option>`).join("")}</select>
        ${inFile ? `<button class="btn-sm btn-outline" data-route-pick-add="${esc(role)}">Добавить запасной</button>`
          : `<button class="btn-sm btn-outline" data-route-pick-apply="${esc(role)}">Сделать основной</button>`}</div>`
      : opts.length ? "" : `<div class="page-sub">В реестре нет готовых точек этого типа подключения — заведите подключение в «Списке подключений».</div>`}
    <table class="mon-table">${pts.map((p, i) => `<tr class="${i === 0 ? "route-row-on" : ""}">
      <td style="width:34px; text-align:center">${!inFile ? "" : i === 0
        ? `<span class="route-radio on" style="display:inline-block" aria-label="основная" title="Основная"></span>`
        : `<button class="route-radio" data-route-use="${esc(role)}|${esc(p.name)}" aria-label="Сделать основной: ${esc(p.name)}" title="Сделать основной. ${esc(ПОДСКАЗКА_СМЕНЫ)}"></button>`}</td>
      <td class="mon-key">${esc(p.name)}${p.external ? внешняяМетка : ""}</td>
      <td class="mon-val"><span title="${esc(p.model || "")}">${esc(чейМодель(p))}</span>${p.url ? `<div class="page-sub">${esc(p.url)}</div>` : ""}${рассуждениеСтрокой(p.kind, p.model, p.url, p.reasoning) ? `<div class="page-sub">${esc(рассуждениеСтрокой(p.kind, p.model, p.url, p.reasoning))}</div>` : ""}</td>
      <td>${p.state.startsWith("выведена") ? `<span class="badge badge-danger">${esc(p.state)}</span>`
        : `<span class="${i === 0 ? "route-state-on" : "page-sub"}" style="margin:0">${esc(p.state)}</span>`}${p.last_error ? `<div class="page-sub">${esc(p.last_error)}</div>` : ""}</td>
      <td style="text-align:right; width:90px">${inFile && (pts.length > 1 || role === "agreements" || role === "guard") ? `<button class="btn-link" data-route-remove="${esc(role)}|${esc(p.name)}">Убрать</button>` : ""}</td>
    </tr>`).join("")}</table>
    ${!pts.length && role === "guard" ? `<div class="page-sub"><span class="badge badge-neutral">не настроена</span> работают только правила: реплики, обращённые к системе, разбирает код, модель не вызывается. Назначьте модель («Сделать основной»), чтобы предложения, которые правила сочли подозрительными, досматривала модель — короткий вызов только при подозрении.</div>`
      : pts.length && role === "guard" ? `<div class="page-sub">Модель видит только предложения, которые правила сочли подозрительными, и отвечает «обращение к системе» или «обычная речь». «Убрать» у последней точки — снова только правила.</div>`
      : !pts.length ? `<div class="page-sub"><span class="badge badge-danger">не настроена</span> модель не настроена — назначьте в «Моделях»: выберите подключение из реестра и нажмите «Сделать основной»${(d.not_configured || {})[role] ? ` (${esc(d.not_configured[role])})` : ""}. Без модели роли сборка не начнётся, вызовов модели нет.</div>`
      : поЧерновику && role === "agreements" ? `<div class="page-sub">Своей точки у договорённостей нет — отдельный вызов договорённостей идёт на модель черновика, назначенную выше. «Сделать основной» назначит договорённостям свою модель; «Убрать» у последней точки вернёт «как у черновика».</div>`
      : поЧерновику ? `<div class="page-sub">Своей точки у проверки нет — проверка идёт на модель черновика, назначенную выше (исключение владельца 13.10.26). «Сделать основной» назначит проверке свою точку.</div>`
      : изПеременных ? `<div class="page-sub">Роль не описана в models.json — распознавание по WEBAPP_WHISPER_MODEL на этой машине. «Сделать основной» добавит роль в файл.</div>` : ""}`;
  }).join("");
  const eps = d.endpoints || [];
  const fieldText = e => { const f = e.fields || {}; return [shortModel(f.model), f.callable, f.url, f.path ? "папка " + f.path : "", f.device ? "device " + f.device : "", рассуждениеСтрокой(e.kind, f.model, f.url, f.reasoning), f.max_tokens ? `потолок ответа ${f.max_tokens} токенов` : ""].filter(Boolean).join(" · "); };
  const nDraft = eps.filter(e => e.missing).length;
  const book = `<h3 style="margin:22px 0 4px">Список подключений</h3>
    <div class="page-sub">Реестр точек вызова (endpoints в models.json). Текст: openai — OpenAI-совместимый сервер, ollama,
      openrouter. Распознавание: faster-whisper — модель на этой машине, python — функция «модуль:функция», asr-service —
      HTTP-сервис во внутренней сети. В вызовах участвуют только точки, назначенные в роли. Точка без обязательных полей
      имеет статус «не настроено» и в роль не назначается. Секреты в models.json не хранятся: key_env — имя переменной окружения,
      ключ значением лежит отдельно (model_keys.local.json) и на экран не выводится.</div>
    <details class="model-book" data-no-collapse${keep.bookOpen ? " open" : ""}><summary class="disclosure-summary">Показать список — ${eps.length} подключ${eps.length % 10 === 1 && eps.length % 100 !== 11 ? "ение" : [2, 3, 4].includes(eps.length % 10) && ![12, 13, 14].includes(eps.length % 100) ? "ения" : "ений"}${nDraft ? `, из них не настроено ${nDraft}` : ""}</summary>
    <table class="mon-table">${eps.map(e => `<tr>
      <td class="mon-key">${esc(e.name)}${e.external ? внешняяМетка : ""}<div class="page-sub">${esc(e.kind_title)}</div></td>
      <td class="mon-val">${esc(fieldText(e) || "—")}${e.fields && e.fields.note ? `<div class="page-sub">${esc(e.fields.note)}</div>` : ""}${e.external && e.tariff
        ? `<div class="page-sub">${esc(e.tariff.text)}${e.tariff.origin ? ` · ${esc(e.tariff.form.tariff_prices)} $ за 1 млн токенов${e.tariff.form.tariff_peak ? `, пик ${esc(e.tariff.form.tariff_peak)}` : ""}` : ""}</div>` : ""}${e.key
        ? `<div class="page-sub">${esc(e.key)}</div>` : e.fields && e.fields.key_env ? `<div class="page-sub">ключ — переменная ${esc(e.fields.key_env)}</div>` : ""}</td>
      <td>${e.missing ? `<span class="badge badge-danger">не настроено</span><div class="page-sub">${esc(e.missing)}</div>`
        : e.roles.length ? e.roles.map(r => `<span class="badge" style="white-space:normal; margin:0 4px 4px 0">${esc(ROLE[r] || r)}</span>`).join("") : `<span class="badge badge-neutral">готово, не в ролях</span>`}</td>
      <td style="width:110px"><div style="display:flex; flex-direction:column; gap:6px; align-items:flex-end; white-space:nowrap">
        <button class="btn-sm btn-outline" data-ep-edit="${esc(e.name)}" title="${esc(ПОДСКАЗКА_СМЕНЫ)}">Изменить</button>
        ${e.fields && e.fields.key_source === "value" ? `<button class="btn-link" data-ep-key="${esc(e.name)}">Заменить ключ</button>
        ${e.key && e.key !== "ключа нет" ? `<button class="btn-link btn-link-danger" data-ep-key-delete="${esc(e.name)}">Удалить ключ</button>` : ""}` : ""}
        <button class="btn-link btn-link-danger" data-ep-delete="${esc(e.name)}">Удалить</button></div></td></tr>`).join("")}</table>
    </details>
    <div class="hstack" style="margin-top:10px; gap:8px"><button class="btn-sm btn-outline" data-ep-new="text">+ Новое подключение модели</button>
      <button class="btn-sm btn-outline" data-ep-new="asr">+ Новое подключение распознавания</button></div>
    <div id="ep-form"></div>`;
  const hist = (d.history || []).slice(0, 6);
  const ACT = { use: "основная", add: "запасная", remove: "убрана из роли", new: "новое подключение", edit: "изменено", delete: "удалено", rollback: "откат",
    key_set: "ключ задан", key_replace: "ключ заменён", key_delete: "ключ удалён" };
  const histHtml = `<h3 style="margin:22px 0 4px">Журнал изменений</h3>
    <div class="page-sub">Источник — models.log.jsonl. Перед каждой записью файла прежняя версия сохраняется в models.history/
      (до 30 версий); откат восстанавливает последнюю сохранённую, повторный — предыдущую.</div>
    ${hist.length ? `<table class="mon-table">${hist.map(h => `<tr><td class="mon-key">${esc(h.at || "")}</td>
      <td class="mon-val">${esc(ACT[h.action || "use"] || h.action)}${h.role ? " — " + esc(ROLE[h.role] || h.role) : ""}${h.point ? ": " + esc(h.point) : ""}</td>
      <td>${esc(h.by || "")}</td></tr>`).join("")}</table>` : `<div class="page-sub">Записей нет.</div>`}
    <div class="hstack" style="margin-top:10px; gap:8px; align-items:center"><button class="btn-sm btn-outline" id="route-rollback"${d.versions ? "" : " disabled"}>Откатить последнее изменение</button>
      <span class="page-sub" style="margin:0">Версий в models.history: ${esc(d.versions || 0)}</span></div>`;
  el.innerHTML = `
    <div class="page-sub">Маршрутизация по ролям: вызов обслуживает первая доступная точка цепочки, остальные — резерв по порядку.
      Отказ точки (нет соединения, 5xx/429 после повторов, таймаут, 401–404) выводит её на ${d.cooldown_sec} с (circuit breaker),
      вызов переходит к следующей. Ошибка запроса (400) на резерв не переносится. Изменения пишутся в файл атомарно и
      применяются без перезапуска — файл перечитывается по mtime. ${esc(ПОДСКАЗКА_СМЕНЫ)} Файл: ${esc(d.path)}</div>
    ${d.note ? `<div class="page-sub">${esc(d.note)}</div>` : ""}
    ${roles}
    <div class="hstack" style="margin-top:14px"><button class="btn-sm btn-outline" id="route-check">Проверить все точки в ролях</button></div>
    <div id="route-check-out" class="page-sub" style="margin-top:6px"></div>
    ${book}${histHtml}${внешняяСправка()}`;
  const again = () => renderModelRoutes(el, base, apiOpts);
  const act = async (btn, fn, ok) => {
    btn.disabled = true;
    try { await fn(); if (ok) toast(ok); again(); }
    catch (e) { btn.disabled = false; toast(e.message, true); }
  };
  el.querySelectorAll("[data-route-use]").forEach(b => b.addEventListener("click", () => {
    const [role, point] = b.dataset.routeUse.split("|");
    act(b, () => post("/use", { role, point }), `«${ROLE[role] || role}»: основная — ${point}`);
  }));
  el.querySelectorAll("[data-route-remove]").forEach(b => b.addEventListener("click", () => {
    const [role, point] = b.dataset.routeRemove.split("|");
    act(b, () => post("/role", { role, point, action: "remove" }), `«${point}» убрана из роли «${ROLE[role] || role}»`);
  }));
  el.querySelectorAll("[data-route-pick-apply]").forEach(b => b.addEventListener("click", () => {
    const role = b.dataset.routePickApply, sel = el.querySelector(`[data-route-pick="${role}"]`);
    if (sel) act(b, () => post("/use", { role, point: sel.value }), `«${ROLE[role] || role}»: основная — ${sel.value}`);
  }));
  el.querySelectorAll("[data-route-pick-add]").forEach(b => b.addEventListener("click", () => {
    const role = b.dataset.routePickAdd, sel = el.querySelector(`[data-route-pick="${role}"]`);
    if (sel) act(b, () => post("/role", { role, point: sel.value, action: "add" }), `«${sel.value}» — запасная в роли «${ROLE[role] || role}»`);
  }));
  el.querySelectorAll("[data-ep-delete]").forEach(b => b.addEventListener("click", () => {
    if (!confirm(`Удалить подключение «${b.dataset.epDelete}»? Прежняя версия файла сохранится, её можно вернуть откатом.`)) return;
    act(b, () => post("/endpoint/delete", { name: b.dataset.epDelete }), `Подключение «${b.dataset.epDelete}» удалено`);
  }));
  const rb = el.querySelector("#route-rollback");
  rb?.addEventListener("click", () => act(rb, () => post("/rollback", {}), "Файл маршрутов возвращён к прежней версии"));
  // Форма подключения: поля строятся по описанию типа подключения с сервера (d.kinds)
  const form = el.querySelector("#ep-form");
  // Значок «i» у поля «Ключ» внешнего подключения: подсказка при наведении и по нажатию (на телефоне наведения нет).
  const значокИ = `<button type="button" class="badge badge-neutral" data-key-info title="${esc(ПОДСКАЗКА_КЛЮЧА)}" aria-label="Пояснение о внешней модели"
      style="margin-left:6px; cursor:help; border:0; font-style:italic">i</button>`;
  // Ключ значением — поле ввода пароля; в ответах сервера ключа нет, поэтому в форме он не показывается никогда.
  el.querySelectorAll("[data-ep-key]").forEach(b => b.addEventListener("click", () => {
    const name = b.dataset.epKey;
    form.innerHTML = `<div class="card" style="margin-top:12px; padding:14px 16px">
      <h3 style="margin:0 0 8px">Заменить ключ — «${esc(name)}»</h3>
      <div class="field"><label>Ключ ${значокИ}</label><input type="password" data-key-new autocomplete="off" placeholder="вставьте ключ, полученный у поставщика"></div>
      <div class="page-sub" data-key-info-text hidden>${esc(ПОДСКАЗКА_КЛЮЧА)}</div>
      <div class="page-sub">Прежний ключ после замены не восстанавливается.</div>
      <div class="hstack" style="margin-top:10px; gap:10px; align-items:center"><button class="btn-sm btn-outline" data-key-save>Заменить ключ</button>
        <button class="btn-link" data-ep-cancel>Отмена</button></div></div>`;
    form.querySelector("[data-key-info]").addEventListener("click", () => { const t = form.querySelector("[data-key-info-text]"); t.hidden = !t.hidden; });
    form.querySelector("[data-ep-cancel]").addEventListener("click", () => { form.innerHTML = ""; });
    const kb = form.querySelector("[data-key-save]");
    kb.addEventListener("click", () => act(kb, () => post("/endpoint/key", { name, value: form.querySelector("[data-key-new]").value.trim() }),
      `Ключ подключения «${name}» заменён`));
    form.scrollIntoView({ block: "nearest" });
  }));
  el.querySelectorAll("[data-ep-key-delete]").forEach(b => b.addEventListener("click", () => {
    if (!confirm(`Удалить ключ подключения «${b.dataset.epKeyDelete}»? Прежний ключ после удаления не восстанавливается.`)) return;
    act(b, () => post("/endpoint/key/delete", { name: b.dataset.epKeyDelete }), `Ключ подключения «${b.dataset.epKeyDelete}» удалён`);
  }));
  const openForm = (group, ep) => {
    const list = Object.keys(kinds).filter(k => (kinds[k].for === group));
    let kind = ep ? ep.kind : list[0];
    let cur = null;          // введённое до перерисовки (смена «имя переменной / значение» не стирает форму)
    // Тариф точки (15.10.26): справочник открытых прейскурантов приходит с сервера (d.tariff_book); совпали адрес
    // и модель — поля тарифа предзаполняются, администратор может поправить. Источник и дата видны под полем.
    const тарифКниги = (model, url) => {
      let host = "";
      try { host = new URL(url).hostname.toLowerCase(); } catch (e) { host = ""; }
      const имя = (model || "").trim().toLowerCase();
      return (d.tariff_book || []).find(b => b.hosts.includes(host) && b.models.includes(имя)) || null;
    };
    const ТАРИФ_НЕТ = "тариф не задан — если поставщик не вернёт цену, стоимость не посчитается";
    const draw = () => {
      const fields = (kinds[kind] || {}).fields || [];
      const val = k => cur && k in cur ? cur[k] : ep && ep.kind === kind ? ((ep.fields || {})[k] || "") : "";
      const keySource = val("key_source") || "env";
      const hints = (kinds[kind] || {}).url_hints || [];
      const тарифПоле = k => {
        if (cur && k in cur) return cur[k];
        if (k !== "tariff_prices" && k !== "tariff_peak") return val(k);   // предел расхода — обычное поле точки
        if (ep && ep.kind === kind && ep.tariff) return (ep.tariff.form || {})[k] || "";
        const b = тарифКниги(val("model"), val("url"));
        return b ? b[k] || "" : "";
      };
      const поле = f => {
        if (f.key === "key_env" && keySource === "value") return "";
        if (f.tariff) {
          return `<div class="field" data-tariff-field${внешняяФорма(kind, val("url")) ? "" : " hidden"}><label>${esc(f.label)} — необязательно</label>
            <input type="text" data-f="${esc(f.key)}" value="${esc(тарифПоле(f.key))}" placeholder="${esc(f.hint || "")}">
            ${f.help ? `<div class="page-sub">${esc(f.help)}</div>` : ""}${f.key === "tariff_prices" ? `<div class="page-sub" data-tariff-src></div>` : ""}</div>`;
        }
        if (f.key === "proxy" && f.address_key) {
          // Прокси точки адресом (16.10.26): в файле — сам адрес; в форме — вариант «адрес» и строка ввода
          const сохранён = val("proxy");
          const адресом = /^https?:\/\//.test(сохранён);
          const режим = адресом ? "address" : (сохранён || f.default || f.choices[0]);
          const адрес = cur && f.address_key in cur ? cur[f.address_key] : адресом ? сохранён : "";
          return `<div class="field"><label>${esc(f.label)} — необязательно</label>
            <select data-f="proxy" data-proxy-mode>${f.choices.map(c => `<option value="${esc(c)}"${режим === c ? " selected" : ""}>${esc((f.choice_titles || {})[c] || c)}</option>`).join("")}</select>
            <div data-proxy-address${режим === "address" ? "" : " hidden"}><input type="text" data-f="${esc(f.address_key)}" style="margin-top:6px" value="${esc(адрес)}" placeholder="${esc(f.address_hint || "")}">
              <div class="page-sub">${esc(f.address_help || "")}</div></div></div>`;
        }
        if (f.key === "key_source") {
          const задан = ep && ep.kind === kind && ep.key && ep.key !== "ключа нет" ? ep.key : "";
          return `<div class="field"><label>${esc(f.label)}<span data-key-i${внешняяФорма(kind, val("url")) ? "" : " hidden"}>${значокИ}</span></label>
            <select data-f="key_source">${f.choices.map(c => `<option value="${esc(c)}"${keySource === c ? " selected" : ""}>${esc((f.choice_titles || {})[c] || c)}</option>`).join("")}</select>
            ${keySource === "value" ? `<input type="password" data-key-value autocomplete="off" style="margin-top:6px" value="${esc(cur && cur.__key ? cur.__key : "")}"
              placeholder="${задан ? esc(задан) + " — оставьте пустым, чтобы не менять" : "вставьте ключ, полученный у поставщика"}">` : ""}
            <div class="page-sub" data-key-info-text hidden>${esc(ПОДСКАЗКА_КЛЮЧА)}</div></div>`;
        }
        // У Claude (api.anthropic.com) рассуждение не выключается — в выборе только auto / low / high (27.10.2026)
        const выбор = f.key === "reasoning" && kind === "openai" && адресClaude(val("url")) ? (f.choices || []).filter(c => c !== "none") : f.choices;
        return `<div class="field"><label>${esc(f.label)}${f.required ? "" : " — необязательно"}</label>${выбор
          ? `<select data-f="${esc(f.key)}">${выбор.map(c => `<option value="${esc(c)}"${(val(f.key) || f.default || выбор[0]) === c ? " selected" : ""}>${esc((f.choice_titles || {})[c] || c)}</option>`).join("")}</select>${f.help ? `<div class="page-sub">${esc(f.help)}</div>` : ""}`
          : `<input type="text" data-f="${esc(f.key)}" value="${esc(val(f.key) || (ep || (cur && f.key in cur) ? "" : f.default || ""))}" placeholder="${esc(f.hint || "")}"${f.key === "url" && hints.length ? ` list="ep-url-hints"` : ""}>`}${f.key === "url" && hints.length
          ? `<datalist id="ep-url-hints">${hints.map(h => `<option value="${esc(h.url)}">${esc(h.title)}</option>`).join("")}</datalist>
            <div class="page-sub">Внешний поставщик: ${hints.map(h => `${esc(h.title)} — ${esc(h.url)}`).join("; ")}.</div>` : ""}</div>`;
      };
      form.innerHTML = `<div class="card" style="margin-top:12px; padding:14px 16px">
        <h3 style="margin:0 0 8px">${ep ? `Подключение «${esc(ep.name)}»` : group === "asr" ? "Новое подключение распознавания" : "Новое подключение модели"}</h3>
        <div class="field"><label>Имя подключения</label><input type="text" data-f="name" value="${esc(cur ? cur.name || "" : ep ? ep.name : "")}" placeholder="${group === "asr" ? "whisper-medium" : "deepseek-flash"}"></div>
        <div class="field"><label>Тип подключения</label><select data-f="kind">${list.map(k => `<option value="${esc(k)}"${k === kind ? " selected" : ""}>${esc(kinds[k].title)}</option>`).join("")}</select></div>
        ${fields.map(поле).join("")}
        <div class="field"><label>Пояснение — необязательно</label><input type="text" data-f="note" value="${esc(cur ? cur.note || "" : ep && ep.fields ? ep.fields.note || "" : "")}" placeholder="например: адрес задаёт оператор"></div>
        <div class="page-sub">Обязательное поле можно оставить пустым — подключение сохранится заготовкой «не настроено».</div>
        <div class="hstack" style="margin-top:10px; gap:10px; align-items:center"><button class="btn-sm btn-outline" data-ep-test>Проверить связь</button>
          <button class="btn-sm btn-primary" data-ep-save>Сохранить</button><button class="btn-link" data-ep-cancel>Отмена</button></div>
        <div class="page-sub" data-ep-out style="margin-top:6px"></div></div>`;
      const read = () => { const o = {}; form.querySelectorAll("[data-f]").forEach(i => { o[i.dataset.f] = i.value.trim(); }); return o; };
      const keyValue = () => { const i = form.querySelector("[data-key-value]"); return i ? i.value.trim() : ""; };
      form.querySelector('[data-f="kind"]').addEventListener("change", e => { kind = e.target.value; cur = null; draw(); });
      form.querySelector('[data-f="key_source"]')?.addEventListener("change", () => { cur = Object.assign(read(), { __key: keyValue() }); draw(); });
      form.querySelector("[data-proxy-mode]")?.addEventListener("change", e => {
        const x = form.querySelector("[data-proxy-address]"); if (x) x.hidden = e.target.value !== "address"; });
      form.querySelector('[data-f="url"]')?.addEventListener("input", e => {
        const i = form.querySelector("[data-key-i]"); if (i) i.hidden = !внешняяФорма(kind, e.target.value.trim()); });
      // Тариф: смена адреса или модели предзаполняет его из справочника, если поле пустое или ещё не правлено руками.
      const обновитьТариф = (дополнить) => {
        const url = ((form.querySelector('[data-f="url"]') || {}).value || "").trim();
        const model = ((form.querySelector('[data-f="model"]') || {}).value || "").trim();
        form.querySelectorAll("[data-tariff-field]").forEach(x => { x.hidden = !внешняяФорма(kind, url); });
        const цены = form.querySelector('[data-f="tariff_prices"]'), пик = form.querySelector('[data-f="tariff_peak"]');
        const src = form.querySelector("[data-tariff-src]");
        if (!цены) return;
        const b = тарифКниги(model, url);
        if (дополнить && b && (!цены.value.trim() || цены.value === цены.dataset.auto)) {
          цены.value = цены.dataset.auto = b.tariff_prices;
          if (пик && (!пик.value.trim() || пик.value === пик.dataset.auto)) пик.value = пик.dataset.auto = b.tariff_peak;
        }
        const своё = ep && ep.kind === kind && ep.tariff && ep.tariff.origin === "точка";
        if (src) src.textContent = !цены.value.trim() ? (b ? `пусто — будет взят справочник: ${b.source}, ${b.as_of}` : ТАРИФ_НЕТ)
          : b && цены.value.trim() === b.tariff_prices && (!пик || пик.value.trim() === b.tariff_peak)
            ? `из справочника открытых прейскурантов: ${b.source}, ${b.as_of}`
            : своё && цены.value.trim() === ep.tariff.form.tariff_prices && (!пик || пик.value.trim() === ep.tariff.form.tariff_peak)
              ? ep.tariff.text : "задано администратором — сохранится с сегодняшней датой";
      };
      ["url", "model"].forEach(k => form.querySelector(`[data-f="${k}"]`)?.addEventListener("input", () => обновитьТариф(true)));
      ["tariff_prices", "tariff_peak"].forEach(k => form.querySelector(`[data-f="${k}"]`)?.addEventListener("input", () => обновитьТариф(false)));
      обновитьТариф(true);
      form.querySelector("[data-key-info]")?.addEventListener("click", () => { const t = form.querySelector("[data-key-info-text]"); if (t) t.hidden = !t.hidden; });
      form.querySelector("[data-ep-cancel]").addEventListener("click", () => { form.innerHTML = ""; });
      const out = form.querySelector("[data-ep-out]");
      const tb = form.querySelector("[data-ep-test]");
      tb.addEventListener("click", async () => {
        tb.disabled = true; out.textContent = "Проверяем…";
        try { const f = read(); const r = await post("/endpoint/test", { name: f.name || "проверка", old_name: ep ? ep.name : "", fields: f, key_value: keyValue() });
          out.innerHTML = `<span class="${r.ok ? "badge" : "badge badge-danger"}">${r.ok ? "живо" : "нет"}</span> ${esc(r.detail)}`; }
        catch (e) { out.textContent = e.message; }
        finally { tb.disabled = false; }
      });
      const sb = form.querySelector("[data-ep-save]");
      sb.addEventListener("click", () => { const f = read();
        act(sb, () => post("/endpoint", { name: f.name, old_name: ep ? ep.name : "", fields: f, key_value: keyValue() }), `Подключение «${f.name}» сохранено`); });
      form.scrollIntoView({ block: "nearest" });
    };
    draw();
  };
  el.querySelectorAll("[data-ep-new]").forEach(b => b.addEventListener("click", () => openForm(b.dataset.epNew, null)));
  el.querySelectorAll("[data-ep-edit]").forEach(b => b.addEventListener("click", () => {
    const ep = eps.find(x => x.name === b.dataset.epEdit);
    if (ep) openForm((kinds[ep.kind] || {}).for || "text", ep);
  }));
  const btn = el.querySelector("#route-check");
  btn?.addEventListener("click", async () => {
    btn.disabled = true;
    const out = el.querySelector("#route-check-out");
    out.textContent = "Проверяем — короткий запрос на каждую точку…";
    try {
      const r = await api(base + "/check", Object.assign({ method: "POST" }, apiOpts));
      out.innerHTML = r.results.map(x => `<span class="${x.ok ? "badge" : "badge badge-danger"}">${x.ok ? "живо" : "нет"}</span> ${esc(x.name)} — ${esc(x.detail)}`).join("<br>");
    } catch (e) { out.textContent = e.message; }
    finally { btn.disabled = false; }
  });
  // Свёрнутый блок «Как подключить внешнюю модель» внизу «Моделей» (решение владельца 14.10.26) — текст дословно
  // из «Инструкции оператору — внешние модели»; объявлен в конце функции, чтобы не заслонять разметку пульта.
  function внешняяСправка() {
    return `<details class="model-book" data-no-collapse style="margin-top:22px"><summary class="disclosure-summary">Как подключить внешнюю модель</summary>
    <div class="page-sub" style="margin:6px 0 0">
      <p><b>Когда нужна внешняя модель</b></p>
      <p>Внешняя модель — обходной путь для сборки протокола, когда своя модель недоступна или справляется хуже. Голос она не получает: распознавание речи принимает только модели на своей машине, внешнюю туда поставить нельзя.</p>
      <p><b>Что уходит наружу</b></p>
      <p>Текст встречи после распознавания, заметки секретаря, состав команды и названия проектов. Больше ничего.</p>
      <p><b>Как подключить</b></p>
      <ol>
        <li>Откройте «Список подключений» и нажмите «+ Новое подключение модели».</li>
        <li>Выберите тип подключения: OpenRouter или «Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик».</li>
        <li>Адрес: выберите из подсказки или впишите адрес поставщика, начинается с https.</li>
        <li>Модель: имя модели так, как его пишет поставщик.</li>
        <li>Ключ: выберите «значение» и вставьте ключ, полученный у поставщика. Если ключ уже лежит в переменной окружения на машине, выберите «имя переменной окружения» и впишите её имя.</li>
        <li>Нажмите «Проверить связь». Ответ «живо» и время ответа — можно сохранять. «Ключ не принят поставщиком» — проверьте ключ и срок его действия.</li>
        <li>Нажмите «Сохранить». Подключение появится в списке с пометкой «внешняя».</li>
        <li>Поставьте подключение в роль: «Генерация черновика» или «Проверка черновика». Само в роль оно не встаёт.</li>
      </ol>
      <p><b>Два способа подключения, оба рабочие</b></p>
      <ul>
        <li>Через OpenRouter: тип подключения OpenRouter, адрес https://openrouter.ai/api, ключ OpenRouter, модель — любая из каталога OpenRouter, имя так, как оно записано в каталоге.</li>
        <li>Напрямую через API поставщика, например DeepSeek: тип подключения «Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик», адрес https://api.deepseek.com, модель deepseek-flash, ключ DeepSeek. Рассуждение у DeepSeek «как у модели» — выключено (решение 16.10.2026): весь потолок ответа уходит на ответ; «понемногу» или «полностью» включают его явно.</li>
      </ul>
      <p>Claude (Anthropic) — тем же вторым способом: тип подключения «Свой сервер моделей, OpenAI-совместимый (LM Studio, vLLM, Ollama /v1) или внешний поставщик», адрес https://api.anthropic.com, модель claude-sonnet-5-5, claude-opus-5-5 или claude-haiku-5-5, ключ — значением из консоли Anthropic, потолок ответа 32000, рассуждение — «как у модели» (это понемногу, low; для трудных шагов — «полностью», high). Выключить рассуждение у Claude нельзя: у Sonnet 5.5 и Opus 5.5 поставщик такой вызов не принимает, и значение «выключено» у этого адреса не сохранится. Температуру система этой модели не передаёт — так требует Anthropic. Цена вызова считается по открытому прейскуранту Anthropic.</p>
      <p>Можно завести оба подключения: одно поставить в роль основным, второе — запасным. Если основное не ответит, вызов уйдёт на запасное.</p>
      <p><b>Как заменить или убрать ключ</b></p>
      <p>В строке подключения — «Заменить ключ» или «Удалить ключ». Прежний ключ после замены не восстанавливается. «Откатить последнее изменение» ключ не трогает.</p>
      <p><b>Что важно</b></p>
      <ul>
        <li>Ключ не пишите в комментарии, письма и переписку: в системе он хранится отдельно и наружу не показывается.</li>
        <li>Потолки цены и числа вызовов действуют и на внешнюю модель. Расход видно на ${esc(СЛОВА.расход || "вкладке «Расход»")}.</li>
        <li>Стоимость: если поставщик возвращает цену вызова (OpenRouter), берётся его число. DeepSeek цену не возвращает — тогда стоимость считается как токены × тариф точки, сумма помечена «расчётная по тарифу». Тариф предзаполняется из открытого прейскуранта поставщика и правится в поле «Тариф» подключения. Фактический счёт — в кабинете поставщика.</li>
        <li>Если протокол собран внешней моделью, в ${esc(СЛОВА.сообщения || "«Технических сообщениях»")} появится строка об этом. В самом протоколе пометки нет.</li>
        <li>Если в компании выход в интернет идёт через прокси, в поле «Прокси — для внешней точки» должен стоять вариант «системный» — так по умолчанию.</li>
        <li>Если прокси компании для всей машины не включён, выберите в поле «Прокси — для внешней точки» вариант «адрес» и впишите адрес прокси, например http://172.17.17.97:3128. Через него пойдут только вызовы этого подключения: рабочие, пробный запрос перед сборкой и «Проверить связь». Остальные подключения работают как раньше. Адрес — только хост и порт; прокси с логином и паролем не поддерживается. Подключение к своей машине во внутренней сети прокси не использует, даже если адрес задан.</li>
        <li>Ключи видит и меняет только супер-администратор.${СЛОВА.админ_проекта ? " " + esc(СЛОВА.админ_проекта) : ""}</li>
      </ul>
    </div></details>`;
  }
}

// --- «Возможные поручения» — общий список по всем встречам, пункт блока администратора (решение владелицы 24.10.2026) ---
// Узкий порог задачи: в протокол и реестр идут только поручения с адресатом (человек или отдел); похожее на поручение без
// адресата (безличное, обсуждение без решения, вопрос-просьба) — строкой здесь. Видят администратор и суперадминистратор
// (права «Под вопросом»); в протокол, Word, реестр и «Конфликты» строки не идут. Отборы — дата встречи, причина, состояние
// (по умолчанию «новое» — неразобранные), поиск по словам. «В задачу» — маленькое окно: формулировка, исполнитель из
// «Команды» или текстом, срок; задача заводится обычной задачей встречи. «Не задача» закрывает строку. Неразобранная строка
// истекает сама через N дней (срок меняет суперадминистратор здесь же). Функция одинакова в обеих системах.
const ВОЗМОЖНЫЕ_ПРИЧИНЫ = { "нет адресата": "Нет адресата", "обсуждали без решения": "Обсуждали без решения",
  "вопрос-просьба": "Вопрос-просьба" };
const ВОЗМОЖНЫЕ_СОСТОЯНИЯ = { "новое": "Новое", "в задачу": "В задачу", "не задача": "Не задача", "истекло": "Истекло" };

function датаВозможного(s) {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
}

async function renderVozmozhnye() {
  const мой = location.hash;
  const f = renderVozmozhnye.filters || (renderVozmozhnye.filters = { state: "новое", reason: "", date_from: "", date_to: "", q: "" });
  const адрес = "/possible-assignments?" + new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  let д;
  try { д = await api(адрес, { auth: true }); }
  catch (e) { $main.innerHTML = `<h1>Возможные поручения</h1><div class="card">Не удалось получить список: ${esc(e.message)}</div>`; return; }
  if (location.hash !== мой) return;          // ушли на другой экран, пока список грузился
  _значки.possible = д.unresolved || 0;
  показатьЗначки();
  const опция = (v, sel, label) => `<option value="${esc(v)}"${v === sel ? " selected" : ""}>${esc(label)}</option>`;
  const строкаHtml = (в) => {
    const решено = в.state !== "новое"
      ? `<span class="page-sub">${esc(ВОЗМОЖНЫЕ_СОСТОЯНИЯ[в.state] || в.state)}${в.decided_by ? " · " + esc(в.decided_by) : ""}${в.decided_at ? " · " + esc(датаВозможного(в.decided_at)) : ""}${в.task_id ? ` · задача <a href="#registry">№${в.task_id}</a>` : ""}</span>`
      : `<button class="btn-primary btn-sm vz-task" type="button" data-id="${в.id}">В задачу</button>
         <button class="btn-sm vz-not" type="button" data-id="${в.id}">Не задача</button>`;
    return `<tr data-possible-id="${в.id}">
      <td class="c-due" data-label="Дата"><a href="#meetings/${в.meeting_id}">${esc(датаВозможного(в.meeting_date))}</a></td>
      <td class="task-desc-cell" data-label="Формулировка"><span class="task-desc-text">${esc(в.description)}</span>
        ${в.quote ? `<span class="sub">«${esc(в.quote)}»${в.quote_ref ? " — " + esc(в.quote_ref) : ""}</span>` : ""}</td>
      <td data-label="Прозвучало">${[в.responsible_heard ? "исполнитель: " + esc(в.responsible_heard) : "", в.due_heard ? "срок: " + esc(в.due_heard) : ""].filter(Boolean).join("<br>") || '<span class="page-sub">—</span>'}</td>
      <td data-label="Причина">${esc(ВОЗМОЖНЫЕ_ПРИЧИНЫ[в.reason] || в.reason)}</td>
      <td data-label="Решение">${решено}</td></tr>`;
  };
  $main.innerHTML = `<div class="toolbar"><span class="tb-title">Возможные поручения</span>
      <span class="tip" tabindex="0" role="button" aria-label="Что здесь"><span class="tip-ico" aria-hidden="true">i</span><span class="tip-body" role="tooltip">Похоже на поручение, но адресата нет: безличное («надо бы…»), обсуждение без решения, вопрос-просьба. В протокол и реестр такое не идёт. «В задачу» — заведёт обычную задачу встречи, «Не задача» — закроет строку. Неразобранная строка истекает сама через ${д.days} дн.</span></span>
      <span class="tb-spacer"></span><span class="page-sub" id="vz-unresolved">Неразобранных: <b>${д.unresolved}</b></span></div>
    <div class="card hstack" id="vz-filters">
      <label>с <input type="date" id="vz-from" value="${esc(f.date_from)}"></label>
      <label>по <input type="date" id="vz-to" value="${esc(f.date_to)}"></label>
      <select id="vz-reason" aria-label="Причина"><option value="">Все причины</option>${(д.reasons || []).map(п => опция(п, f.reason, ВОЗМОЖНЫЕ_ПРИЧИНЫ[п] || п)).join("")}</select>
      <select id="vz-state" aria-label="Состояние"><option value="">Все состояния</option>${(д.states || []).map(с => опция(с, f.state, ВОЗМОЖНЫЕ_СОСТОЯНИЯ[с] || с)).join("")}</select>
      <input type="search" id="vz-q" aria-label="Найти" placeholder="Поиск: слова, имя или дата" value="${esc(f.q)}" autocomplete="off">
      <button class="btn-link live-search-reset" id="vz-reset" type="button">Сбросить</button>
    </div>
    ${д.items.length ? `<div class="card card-output"><div class="table-scroll"><table class="agreements-table vz-table">
      <thead><tr><th>Дата</th><th>Формулировка и цитата</th><th>Прозвучало</th><th>Причина</th><th>Решение</th></tr></thead>
      <tbody>${д.items.map(строкаHtml).join("")}</tbody></table></div></div>`
      : `<div class="empty-state" id="vz-empty">Строк по этим условиям нет.</div>`}
    ${isSuperAdmin() ? `<div class="card hstack" id="vz-days"><label>Неразобранная строка истекает через
      <input type="number" id="vz-days-n" min="0" max="365" value="${д.days}" style="width:5em"> дн. (0 — не истекает)</label>
      <button class="btn-sm" id="vz-days-save" type="button">Сохранить</button></div>` : ""}
    <dialog id="vz-dialog"><form method="dialog" class="vz-form">
      <h2>В задачу</h2>
      <label>Формулировка<br><textarea id="vz-desc" rows="3" style="width:100%"></textarea></label>
      <label>Исполнитель<br><input id="vz-resp" list="vz-team" style="width:100%" placeholder="Из «Команды» или отдел текстом"></label>
      <datalist id="vz-team">${(д.team || []).map(и => `<option value="${esc(и)}"></option>`).join("")}</datalist>
      <label>Срок<br><input type="date" id="vz-due"></label>
      <div class="hstack"><button class="btn-primary" id="vz-ok" type="button">Завести задачу</button>
        <button class="btn-sm" value="cancel" type="submit">Отмена</button></div>
    </form></dialog>`;
  const применить = () => {
    Object.assign(f, { date_from: document.getElementById("vz-from").value, date_to: document.getElementById("vz-to").value,
      reason: document.getElementById("vz-reason").value, state: document.getElementById("vz-state").value,
      q: document.getElementById("vz-q").value.trim() });
    renderVozmozhnye();
  };
  ["vz-from", "vz-to", "vz-reason", "vz-state"].forEach(id => document.getElementById(id)?.addEventListener("change", применить));
  let таймер = null;
  document.getElementById("vz-q")?.addEventListener("input", () => { clearTimeout(таймер); таймер = setTimeout(применить, 300); });
  document.getElementById("vz-reset")?.addEventListener("click", () => { renderVozmozhnye.filters = null; renderVozmozhnye(); });
  document.getElementById("vz-days-save")?.addEventListener("click", async () => {
    try {
      const итог = await api("/possible-assignments/settings", { method: "PUT", json: { days: Number(document.getElementById("vz-days-n").value) }, auth: true });
      toast(`Срок неразобранной строки — ${итог.days} дн.`);
      renderVozmozhnye();
    } catch (e) { toast(e.message, true); }
  });
  $main.querySelectorAll(".vz-not").forEach(кн => кн.addEventListener("click", async () => {
    кн.disabled = true;
    try {
      await api(`/possible-assignments/${кн.dataset.id}/not-task`, { method: "POST", auth: true });
      toast("Строка закрыта: не задача");
      renderVozmozhnye();
    } catch (e) { toast(e.message, true); кн.disabled = false; }
  }));
  const окно = document.getElementById("vz-dialog");
  let выбрано = null;
  $main.querySelectorAll(".vz-task").forEach(кн => кн.addEventListener("click", () => {
    выбрано = д.items.find(в => String(в.id) === кн.dataset.id);
    if (!выбрано || !окно) return;
    document.getElementById("vz-desc").value = выбрано.description || "";
    document.getElementById("vz-resp").value = выбрано.responsible_heard || "";
    document.getElementById("vz-due").value = "";
    окно.showModal();
  }));
  document.getElementById("vz-ok")?.addEventListener("click", async (e) => {
    if (!выбрано) return;
    const кн = e.currentTarget;
    кн.disabled = true;
    try {
      const итог = await api(`/possible-assignments/${выбрано.id}/to-task`, { method: "POST", auth: true, json: {
        description: document.getElementById("vz-desc").value.trim() || null,
        responsible: document.getElementById("vz-resp").value.trim() || null,
        due_date: document.getElementById("vz-due").value || null } });
      окно.close();
      toast(`Заведена задача №${итог.task_id}`);
      renderVozmozhnye();
    } catch (err) { toast(err.message, true); кн.disabled = false; }
  });
}

// Выключатель узкого порога задачи — карточка «Настроек» суперадминистратора (решение владелицы 24.10.2026). По умолчанию
// выключен: каждое изменение сначала проходит постоянный набор тестов на стенде, на рабочие системы — по слову владелицы.
// «По переменной окружения» — настройка снята, решает NARROW_TASK_THRESHOLD (стенд). Функция одинакова в обеих системах.
async function карточкаУзкогоПорога($куда) {
  if (!$куда || !isSuperAdmin()) return;
  const $к = document.createElement("div");
  $к.className = "card stack";
  $к.id = "narrow-threshold-card";
  $куда.appendChild($к);
  let с;
  try { с = await api("/possible-assignments/threshold", { auth: true }); }
  catch (e) { $к.innerHTML = `<div class="page-sub">Узкий порог задачи: состояние не получено — ${esc(e.message)}</div>`; return; }
  const выбор = с.setting === true ? "on" : с.setting === false ? "off" : "env";
  const опция = (v, label) => `<option value="${v}"${v === выбор ? " selected" : ""}>${esc(label)}</option>`;
  $к.innerHTML = `<div class="field"><label for="narrow-threshold">Узкий порог задачи и «Возможные поручения» — сейчас
      <b>${с.enabled ? "включён" : "выключен"}</b></label>
    <select id="narrow-threshold">${опция("env", `по переменной окружения NARROW_TASK_THRESHOLD (сейчас ${с.env ? "включён" : "выключен"})`)}
      ${опция("on", "включён")}${опция("off", "выключен")}</select>
    <div class="page-sub">Включён — в протокол и реестр идут только поручения с адресатом (человек или отдел), остальное — в
      «Возможные поручения»; совпавшая с открытой задачей дописывается в её строку. Выключен — как до 24.10.2026. Включать на
      рабочей системе — только по слову владелицы после замера на постоянном наборе тестов.</div></div>`;
  const $в = document.getElementById("narrow-threshold");
  $в.addEventListener("change", async () => {
    $в.disabled = true;
    try {
      const итог = await api("/possible-assignments/threshold", { method: "PUT", auth: true,
        json: { enabled: $в.value === "env" ? null : $в.value === "on" } });
      toast(`Узкий порог задачи ${итог.enabled ? "включён" : "выключен"}`);
      $к.remove();
      карточкаУзкогоПорога($куда);
    } catch (e) { toast(e.message, true); $в.disabled = false; }
  });
}

// Два выключателя распознавания и проекта — карточка «Настроек» суперадминистратора (24.10.2026), оба по умолчанию выключены:
// «Словарь проектов в подсказке распознавания» (названия уходят в подсказку локального Whisper) и «Проект только при
// прозвучавшем названии» (проект факта и задачи снимается, если название не прозвучало рядом в записи). «По переменной
// окружения» — настройка снята, решает переменная (стенд). Функция одинакова в обеих системах.
async function карточкаРаспознавания($куда) {
  if (!$куда || !isSuperAdmin()) return;
  const $к = document.createElement("div");
  $к.className = "card stack";
  $к.id = "recognition-settings-card";
  $куда.appendChild($к);
  let с;
  try { с = await api("/recognition-settings", { auth: true }); }
  catch (e) { $к.innerHTML = `<div class="page-sub">Словарь распознавания и правило проекта: состояние не получено — ${esc(e.message)}</div>`; return; }
  const поле = (ключ, id, заголовок, пояснение) => {
    const x = с[ключ];
    const выбор = x.setting === true ? "on" : x.setting === false ? "off" : "env";
    const опция = (v, label) => `<option value="${v}"${v === выбор ? " selected" : ""}>${esc(label)}</option>`;
    return `<div class="field"><label for="${id}">${esc(заголовок)} — сейчас <b>${x.enabled ? "включено" : "выключено"}</b></label>
      <select id="${id}" data-key="${ключ}">${опция("env", `по переменной окружения ${x.env_name} (сейчас ${x.env ? "включено" : "выключено"})`)}
        ${опция("on", "включено")}${опция("off", "выключено")}</select>
      <div class="page-sub">${пояснение}</div></div>`;
  };
  const сл = с.asr_vocab;
  $к.innerHTML = поле("asr_vocab", "asr-vocab", "Словарь проектов в подсказке распознавания",
      `Названия проектов уходят в подсказку локального распознавания, чтобы оно писало их правильно. Голос никуда не уходит.
       Сейчас в словаре ${esc(String(сл.tokens))} из ${esc(String(сл.limit))} мест подсказки: ${esc(сл.preview || "—")}
       Включать на рабочей системе — после замера на записях со словарём и без, по слову владелицы.`)
    + поле("project_only_heard", "project-only-heard", "Проект только при прозвучавшем названии",
      `Проект факта протокола и задачи остаётся, только если его название, вариант или площадка прозвучали в записи не дальше
       ${esc(String(с.project_only_heard.window))} строк от факта — дословно или искажённо («Рупур» — Руппур). Иначе проект не
       ставится, без карточек и сообщений. Включать — по слову владелицы после прогона набора тестов на стенде.`);
  $к.querySelectorAll("select[data-key]").forEach(($в) => {
    $в.addEventListener("change", async () => {
      $в.disabled = true;
      try {
        const итог = await api("/recognition-settings", { method: "PUT", auth: true,
          json: { key: $в.dataset.key, enabled: $в.value === "env" ? null : $в.value === "on" } });
        toast(`${$в.dataset.key === "asr_vocab" ? "Словарь проектов в подсказке распознавания" : "Проект только при прозвучавшем названии"}: ${итог[$в.dataset.key].enabled ? "включено" : "выключено"}`);
        $к.remove();
        карточкаРаспознавания($куда);
      } catch (e) { toast(e.message, true); $в.disabled = false; }
    });
  });
}
