// «Оперативная» — пометка задачи человеком (решение владелицы 26.10.2026, сервер — services/tablica_zadach.py). Файл-близнец:
// одинаков до байта в Планёрке и ERP — системы выглядят одинаково.
//
// В реестре: отмеченная задача — словом «оперативная» сразу за формулировкой (видно всем ролям); тот, кто правит задачи,
// снимает пометку щелчком по этому слову. Неотмеченная задача в работе — тихой ссылкой в подписи под формулировкой:
// «похоже на оперативную — отметить?», если сервер считает подсказку (разрыв «срок − дата постановки» больше 14 дней или
// больше 5 планёрок), иначе «в оперативные». Одно нажатие — POST /tasks/{id}/operational, версия задачи — общим замком
// `api`. Подсказка пометку не ставит. Открытая оперативная задача стоит в таблице протокола разделом «Оперативные задачи».
// Пользуется общими функциями страницы: api, esc, toast, render.

const ОПЕРАТИВНАЯ_ПОДСКАЗКА = "похоже на оперативную — отметить?";

// Ссылка и слово — шрифтом той строки, где стоят (подпись под формулировкой, слово «под вопросом»): кнопка без своего
// размера и подчёркивания, новых цветов нет. Стиль — здесь, в близнеце, чтобы системы выглядели одинаково (как tema.js).
(function оперативнаяСтили() {
  if (document.getElementById("op-css")) return;
  const s = document.createElement("style");
  s.id = "op-css";
  s.textContent = ".op-link { font: inherit; color: inherit; padding: 0; border: 0; background: none; cursor: pointer; text-decoration: none; }"
    + " button.op-mark { font-family: inherit; padding: 0; border: 0; background: none; cursor: pointer; }"
    + " .op-link:hover, button.op-mark:hover { text-decoration: underline; }";
  document.head.appendChild(s);
})();

// Слово «оперативная» за формулировкой: у того, кто правит, — кнопкой снятия пометки
function оперативнаяМетка(t, можно) {
  if (!t || !t.operational) return "";
  return можно
    ? ` <button type="button" class="uq-label op-mark" data-op-task="${t.id}" data-op-to="0" title="Оперативная задача — щёлкните, чтобы снять пометку">оперативная</button>`
    : ` <span class="uq-label op-mark" title="Оперативная задача — в протоколе в разделе «Оперативные задачи»">оперативная</span>`;
}

// Ссылка в подписи под формулировкой — только у задачи в работе без пометки и только тому, кто правит задачи
function оперативнаяСсылка(t, можно) {
  if (!можно || !t || t.operational || t.status !== "active") return "";
  const текст = t.operational_hint ? ОПЕРАТИВНАЯ_ПОДСКАЗКА : "в оперативные";
  return ` · <button type="button" class="op-link" data-op-task="${t.id}" data-op-to="1" title="Отметить задачу оперативной — в протоколе она встанет в раздел «Оперативные задачи»">${esc(текст)}</button>`;
}

document.addEventListener("click", async (e) => {
  const кнопка = e.target.closest("[data-op-task]");
  if (!кнопка || кнопка.closest(".pp-edit")) return;
  e.preventDefault();
  e.stopPropagation();
  if (кнопка.disabled) return;
  кнопка.disabled = true;
  const отметить = кнопка.dataset.opTo === "1";
  try {
    await api(`/tasks/${кнопка.dataset.opTask}/operational`, { method: "POST", auth: true, json: { value: отметить } });
    toast(отметить ? "Задача отмечена оперативной" : "Пометка «оперативная» снята");
    render();
  } catch (err) {
    toast(err.message, true);
    кнопка.disabled = false;
  }
});
