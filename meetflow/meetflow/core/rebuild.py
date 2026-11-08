"""Задачи прежней сборки встречи, не вошедшие в пересборку (решение владелицы 21.10.2026).

Правило перенесено из Планёрки (`peresborka.py`, коммит 21e280c): «при пересборке задачи не снимаются молча, по ним
заводятся карточки — снимай сразу при пересборке». Задача прежней сборки этой встречи, которой нет в новой, — «снято»
с причиной «не вошла в пересборку (дд.мм.гггг чч:мм)» и строкой в истории задачи; карточки нет.

Не снимаются:
  * задача, которую после сборки правил человек (статус, исполнитель, срок, формулировка, комментарий) — остаётся,
    по ней одна карточка «не вошла в пересборку, но правилась человеком»;
  * ничего, если извлечение было неполным (остановка по пределу, сбой шага): «не найдена в новом прогоне» не доказано.

Номера задач в протоколе MeetFlow — порядковые внутри встречи, поэтому правила Планёрки «перешла в протокол более
поздней встречи» и «строка протокола секретаря» здесь не применимы: переносится смысл — снимать только то, что новая
сборка действительно не вернула.
"""
from __future__ import annotations

import re

from datetime import datetime

from . import povtory_reestra
from .types import TaskStatus

FIELD = "rebuild_missing"
ВОЗВРАТ_ВЛАДЕЛИЦЫ = "возвращена по слову владелицы"
ШИРОКАЯ_ЦИТАТА = 40                  # слов: длиннее — цитата может нести несколько разных поручений (04.11.2026)
ДЛИНА_УЧАСТКА = 2                    # участок записи — не больше двух длин цитаты (05.11.2026)
# Источники строк истории, которые пишет человек: правка в реестре, своя формулировка, срок, исполнитель, ответ карточкой
РУЧНЫЕ_ИСТОЧНИКИ = ("operator", "web_form", "member_note", "conflict_resolution", "task_conflict", "conflict")
ПРИЧИНА = "не вошла в пересборку ({when})"
# Служебные начала строки — это НЕ цитата (правки ERP/Планёрки 03–06.11, п. 8: «нет в списке», «ответственный →»,
# «сведено»). Служебная строка не доказывает, что работа ещё есть в записи, и не держит задачу от снятия.
СЛУЖЕБНЫЕ_НАЧАЛА = ("ответственный", "исполнитель перенесен", "срок", "сведено", "объединено из",
                   "заменена прежней задачей", "возвращена по слову", "работа снята человеком", "нет в списке",
                   "подтверждена", "своя формулировка", "правка", "задача заведена", "не вошла в пересборку")


def когда_сейчас() -> str:
    """Метка причины: местное время пересборки, «дд.мм.гггг чч:мм»."""
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def причина(when: str | None = None) -> str:
    return ПРИЧИНА.format(when=when or когда_сейчас())


def правилась_человеком(store, task_id: int) -> str:
    """Что в задаче после сборки менял человек — словами через запятую; пусто — не менял."""
    what: list[str] = []
    for h in store.q("SELECT source, evidence_quote FROM task_history WHERE task_id=? ORDER BY id", (task_id,)):
        if h["source"] not in РУЧНЫЕ_ИСТОЧНИКИ:
            continue
        text = (h["evidence_quote"] or "").strip().lower()
        if text.startswith("исполнитель"):
            what.append("исполнитель")
        elif text.startswith("срок"):
            what.append("срок")
        elif h["source"] == "member_note":
            what.append("комментарий")
        elif h["source"] in ("conflict_resolution", "task_conflict", "conflict"):
            what.append("ответ на карточку")
        elif text.startswith("своя формулировка"):
            what.append("формулировка")
        else:
            what.append("статус")
    return ", ".join(dict.fromkeys(what))


_НЕ_СЛОВО = re.compile(r"[^0-9a-zа-я]+")
_ВРЕМЯ = re.compile(r"\[?\d{1,2}:\d{2}(?::\d{2})?\]?")


def _слова(текст: str | None) -> list[str]:
    return [w for w in _НЕ_СЛОВО.sub(" ", _ВРЕМЯ.sub(" ", (текст or "").lower().replace("ё", "е"))).split() if w]


def служебная_строка(цитата: str | None) -> bool:
    """Строка служебная (история задачи, а не речь встречи): «ответственный → …», «сведено с задачей …»,
    «нет в списке», «объединено из: …» и подобное. Такая строка цитатой не считается — иначе задача держалась бы
    от снятия служебной записью (правки ERP/Планёрки 03–06.11, п. 8)."""
    т = " ".join(str(цитата or "").replace("ё", "е").lower().split())
    return bool(т) and any(т.startswith(н) for н in СЛУЖЕБНЫЕ_НАЧАЛА)


def цитата_в_записи(цитата: str | None, текст_записи: str | None) -> bool:
    """Цитата задачи по-прежнему есть в записи встречи.

    Сначала как раньше: восемь слов подряд из цитаты (или вся, если короче) стоят в тексте записи подряд. Если так не
    нашлось, а в цитате не меньше восьми значимых слов — цитата считается найденной, когда не меньше 80 % её значимых
    слов стоят в одном участке записи длиной не больше двух длин цитаты (решение владельца 04.11.2026: одного окна в
    восемь слов мало, у ERP 4 из 5 задач потеряны из-за порядка слов — «смог оформить это» против «смог это оформить»).
    Короткая цитата — только первое правило. Нет цитаты или записи — False."""
    ц, т = _слова(цитата), " ".join(_слова(текст_записи))
    if len(ц) < 4 or not т:
        return False
    окно = min(8, len(ц))
    if any(" ".join(ц[i:i + окно]) in т for i in range(0, len(ц) - окно + 1)):
        return True
    значимые = [w for w in ц if len(w) >= 4]
    if len(значимые) < 8:
        return False
    слова_записи = _слова(текст_записи)
    размер = min(len(слова_записи), ДЛИНА_УЧАСТКА * len(ц))
    нужно = -(-len(set(значимые)) * 8 // 10)          # ceil(0.8 × число различных значимых слов)
    набор = set(значимые)
    for i in range(0, max(1, len(слова_записи) - размер + 1)):
        if len(набор & set(слова_записи[i:i + размер])) >= нужно:
            return True
    return False


def та_же_цитата(a: str | None, b: str | None) -> bool:
    """Две цитаты — одна строка записи: слова совпадают или одна целиком внутри другой (28.10.2026, отчёт ЛМ 8680ea4:
    задачи 87 и 88 заменены новыми 101 и 102 с той же цитатой — возвращать их значит завести дубли)."""
    x, y = " ".join(_слова(a)), " ".join(_слова(b))
    return bool(x) and bool(y) and (x == y or (len(x) >= 20 and x in y) or (len(y) >= 20 and y in x))


def заменена(прежняя: dict, другая: dict, цитата_прежней: str | None, цитата_другой: str | None) -> bool:
    """Задача этой встречи о той же работе заменяет прежнюю — **при любой цитате** (решение разработчика 05.11.2026).

    Замер 05.11.2026 на результатах сухого хода: «под вопросом» при порогах 0,65/0,7/0,8/0,9 даёт ошибочную замену
    настоящей задачи (`Промаркировать полки` и `Разработать структуру склада` — 1,0), поэтому заменяют только пары «да».
    «Под вопросом» при той же узкой цитате остаётся заменой: это одно поручение другими словами (28.10.2026)."""
    if not (прежняя.get("responsible") and другая.get("responsible")):   # новая сборка могла не назвать исполнителя
        прежняя, другая = {**прежняя, "responsible": ""}, {**другая, "responsible": ""}
    вердикт = povtory_reestra.пара(прежняя, другая)[0]
    if вердикт == povtory_reestra.ДА:
        return True
    if not та_же_цитата(цитата_прежней, цитата_другой):
        return False
    return (вердикт == povtory_reestra.ПОД_ВОПРОСОМ
            and max(len(_слова(цитата_прежней)), len(_слова(цитата_другой))) <= ШИРОКАЯ_ЦИТАТА)


def _для_сравнения(r) -> dict:
    return {"id": r.get("id"), "description": r.get("description") or "", "responsible": r.get("assignee") or "",
            "subproject": r.get("subproject")}


def цитата_занята(store, meeting_id: int, task_id: int, цитата: str | None) -> bool:
    """Другая действующая задача этой встречи несёт ту же цитату и ту же работу — задача заменена, а не потеряна.
    Одной цитаты мало: широкая цитата несёт разные поручения (встреча 15.10, отчёт 9c79eca: задачи 3, 5, 6 сняты из-за
    задач 7–10 с той же цитатой; решение владелицы 04.11.2026)."""
    return bool(заменяющие(store, meeting_id, task_id, цитата))


def заменяющие(store, meeting_id: int, task_id: int, цитата: str | None) -> list:
    """Действующие задачи этой встречи, которые заменяют задачу `task_id` (см. `цитата_занята`). Перебираются все
    задачи встречи: замена по работе не требует той же цитаты (05.11.2026)."""
    прежняя = _для_сравнения(store.get("tasks", task_id) or {})
    return [r for r in store.q("SELECT * FROM tasks WHERE source_meeting_id=? AND status=? AND id<>?",
                               (meeting_id, TaskStatus.ACTIVE.value, task_id))
            if заменена(прежняя, _для_сравнения(r), цитата, r["source_quote"])]


def перенести_исполнителя(store, reg, task_id: int, замены: list) -> None:
    """Новая сборка не назвала исполнителя, а прежняя задача его знала: исполнитель не пропадает вместе со снятой задачей,
    он ставится в замену, с историей (отчёт 0948fb1: на встрече 28.10 сняты все четыре задачи с исполнителем)."""
    кто = (store.get("tasks", task_id).get("assignee") or "").strip()
    if not кто or not замены or any((r["assignee"] or "").strip() for r in замены):
        return
    замена = замены[0]
    store.update("tasks", замена["id"], assignee=кто)
    reg._history(замена["id"], замена["status"], замена["status"], "meeting",
                 f"исполнитель перенесён при пересборке со снятой задачи №{task_id}: {кто}")


def drop_missing(store, reg, meeting_id: int | None, meeting_date: str | None, kept_ids: set[int], *,
                 incomplete: bool = False, when: str | None = None, текст_записи: str | None = None,
                 new_ids: set[int] | None = None) -> dict:
    """Снять задачи прежней сборки, которых нет в новой. `kept_ids` — задачи этой встречи, которые новая сборка
    подтвердила (в том числе заведённые заново в этом прогоне). `incomplete` — извлечение неполное: ничего не снимаем.
    `текст_записи` — запись встречи: задача, цитата которой в ней есть, не снимается — модель просто не выдала её в этот
    раз (решение владелицы 28.10.2026: 28.10 вторая сборка той же расшифровки сняла 9 задач из 18)."""
    when = when or когда_сейчас()
    out: dict = {"dropped": [], "kept": [], "when": when}
    if incomplete or meeting_id is None:
        return out
    from .pipeline import same_task_text        # локально: pipeline сам импортирует rebuild
    kept = set(kept_ids)
    новые = [store.get("tasks", i) for i in sorted(new_ids or ())]
    новые = [t for t in новые if t and t.get("status") == TaskStatus.ACTIVE.value]
    # Работа, снятая человеком или по его решению, не возвращается ни своим номером, ни новым (решение владелицы
    # 04.11.2026: задачи 3, 5 и 6 встречи 15.10). Проверяем до снятия «не вошедших»: пересборка заводит ту же
    # работу новым номером — её и снимаем, причина уходит в журнал потерь.
    снятые_людьми = [t for t in store.q("SELECT id, description FROM tasks WHERE source_meeting_id=? AND status=?",
                                        (meeting_id, TaskStatus.DROPPED.value))
                     if not снята_пересборкой(store, t["id"])]
    for новая in list(новые):
        hit = next((s for s in снятые_людьми if same_task_text(новая["description"], [s["description"]])), None)
        if hit:
            reg.set_status(новая["id"], TaskStatus.DROPPED, "rebuild",
                           f"работа снята человеком (№{hit['id']}) — новая не заводится")
            out.setdefault("dropped_human", []).append(dict(новая))
            новые.remove(новая)
    for t in store.q("SELECT id, description FROM tasks WHERE source_meeting_id=? AND status=?", 
                     (meeting_id, TaskStatus.ACTIVE.value)):
        if t["id"] in kept:
            continue
        # Та же работа заведена заново новым номером — номер прежней задачи сохраняется (правка 05.11.2026):
        # новая формулировка и цитата пишутся в прежнюю, ручная правка человека не затирается, пустые поля
        # (исполнитель, срок) берутся у новой. Новая задача снимается, история остаётся у прежней.
        замена = next((n for n in новые if same_task_text(t["description"], [n["description"]])), None)
        if замена is None:
            # пары «почти та же работа» (доля 0,6–0,7) ничего не меняют, но идут строкой в журнал потерь:
            # порог 0,7 оставлен (ответ 05.11.2026), решим по таблице с трёх встреч
            from .text import stems as _stems, coverage as _coverage
            for n in новые:
                x, y = set(_stems(t["description"])), set(_stems(n["description"]))
                доля = round(max(_coverage(x, y), _coverage(y, x)), 2)
                if 0.6 <= доля < 0.7:
                    out.setdefault("near_pairs", []).append(
                        {"старая": t["description"], "новая": n["description"], "доля": доля})
        if замена is not None:
            полная = store.get("tasks", t["id"]) or {}
            edits = правилась_человеком(store, t["id"])
            поля = {"source_quote": замена.get("source_quote") or ""}
            if not edits:
                поля["description"] = замена["description"]
            if not (полная.get("assignee") or "").strip() and замена.get("assignee"):
                поля["assignee"] = замена["assignee"]
            if not полная.get("due_date") and замена.get("due_date"):
                поля["due_date"], поля["due_kind"] = замена["due_date"], замена.get("due_kind")
            store.update("tasks", t["id"], **поля)
            reg.set_status(замена["id"], TaskStatus.DROPPED, "rebuild",
                           f"заменена прежней задачей №{t['id']}: номер сохранён")
            новые.remove(замена)
            out.setdefault("kept_number", []).append({"id": t["id"], "новая": замена["id"], "правка": bool(edits)})
            continue
        if возвращена_владелицей(store, t["id"]):
            out.setdefault("kept_owner", []).append(dict(t))
            continue
        if из_секретаря(store, t["id"]):
            out.setdefault("kept_secretary", []).append(dict(t))
            continue                      # строка протокола секретаря пересборкой не заменяется (05.11.2026)
        цит = store.get("tasks", t["id"]).get("source_quote")
        # Служебная строка цитатой не считается (п. 8 записок ERP/Планёрки): она не доказывает, что работа ещё
        # есть в записи, — задача не держится ею от снятия и снимается как «не вошедшая»
        живая_цитата = bool(текст_записи) and not служебная_строка(цит) and цитата_в_записи(цит, текст_записи)
        замены = заменяющие(store, meeting_id, t["id"], цит) if живая_цитата else None
        if замены == []:
            out.setdefault("kept_quote", []).append(dict(t))
            continue
        edits = правилась_человеком(store, t["id"])
        if edits:
            out["kept"].append((dict(t), edits))
            continue
        перенести_исполнителя(store, reg, t["id"], замены or [])
        reg.set_status(t["id"], TaskStatus.DROPPED, "rebuild", причина(when), meeting_date=meeting_date)
        out["dropped"].append(dict(t))
    return out


# --- возврат снятой пересборкой задачи (перенос из ERP 27.10.2026, DECISIONS ERP 26.10.2026 «пересборка без задач») ---
#
# Задача своей встречи, снятая правилом пересборки (последняя строка истории — «не вошла в пересборку» источника
# `rebuild`, без человека), которую новая сборка нашла снова, возвращается в работу с прежним номером — история, срок и
# ссылки людей остаются у задачи (как `peresborka.вернуть` ERP и Планёрки). Снятая человеком (реестр, карточка, голос
# встречи) и выполненная не возвращаются: решение человека и сделанная работа пересборкой не отменяются.
ВОЗВРАТ = "снова найдена в пересборке ({when}) — возвращена в работу с прежним номером"


def снята_пересборкой(store, task_id: int) -> bool:
    t = store.get("tasks", task_id)
    if not t or t.get("status") != TaskStatus.DROPPED.value:
        return False
    last = store.q("SELECT source, new_status FROM task_history WHERE task_id=? AND new_status IS NOT NULL "
                   "ORDER BY id DESC LIMIT 1", (task_id,))
    return bool(last) and last[0]["source"] == "rebuild" and last[0]["new_status"] == TaskStatus.DROPPED.value


СЕКРЕТАРСКИЙ_ИСТОЧНИК = "secretary_table"     # строка истории: задачу отметил протокол секретаря


def из_секретаря(store, task_id: int) -> bool:
    """Задача пришла строкой протокола секретаря: её пересборка не заменяет (решение разработчика 05.11.2026)."""
    return bool(store.q("SELECT 1 FROM task_history WHERE task_id=? AND source=? LIMIT 1",
                        (task_id, СЕКРЕТАРСКИЙ_ИСТОЧНИК)))


def возвращена_владелицей(store, task_id: int) -> bool:
    """Задачу вернула владелица: пересборка её больше не снимает (решение владелицы 04.11.2026)."""
    return bool(store.q("SELECT 1 FROM task_history WHERE task_id=? AND evidence_quote LIKE ? LIMIT 1",
                        (task_id, f"%{ВОЗВРАТ_ВЛАДЕЛИЦЫ}%")))


def вернуть(store, reg, task_id: int, when: str | None = None, владелица: bool = False) -> bool:
    """Вернуть в работу задачу, снятую прежней пересборкой; номер тот же. Возвращает, вернули ли."""
    if not снята_пересборкой(store, task_id):
        return False
    текст = ВОЗВРАТ.format(when=when or когда_сейчас())
    reg.set_status(task_id, TaskStatus.ACTIVE, "rebuild", f"{текст}; {ВОЗВРАТ_ВЛАДЕЛИЦЫ}" if владелица else текст)
    return True
