"""Перенос из Планёрки `21e280c` (решение владелицы 21.10.2026): пересборка сразу снимает задачи прежней сборки.

Задача прежней сборки, которой нет в новой, — «снято» с причиной «не вошла в пересборку (дата)», без карточки.
Задача, которую после сборки правил человек, остаётся — по ней одна карточка. Неполное извлечение ничего не снимает.
Тесты написаны до правки и падали.
"""
from conftest import TRANSCRIPT

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core import rebuild as rebuild_mod
from meetflow.core.rebuild import drop_missing
from meetflow.core.registry import TaskRegistry
from meetflow.core.types import TaskStatus

FIRST = {"description": "подготовьте регламент склада до 10.10", "assignee": "Петрова Анастасия",
         "quote": "Петрова Анастасия, подготовьте регламент склада до 10.10", "line": 3}


class OnlyFirst(MockLLM):
    """Пересборка вернула только первое поручение — второе из новой сборки выпало."""

    def _extract(self, data):
        return {"tasks": [FIRST]}


def _build(make_pipe, store, project, gen=None):
    p = make_pipe(gen=gen)
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    return p, mid


def test_rebuild_drops_task_missing_from_new_build(store, project, make_pipe, monkeypatch):
    # 28.10.2026: снимается только задача без цитаты в записи — здесь цитаты «нет», как при сменившейся записи
    monkeypatch.setattr(rebuild_mod, "цитата_в_записи", lambda *a, **k: False)
    p, mid = _build(make_pipe, store, project)
    before = {t["description"]: t["id"] for t in
              store.q("SELECT id, description FROM tasks WHERE source_meeting_id=?", (mid,))}
    assert len(before) == 2
    p.gen = OnlyFirst()
    p.run(project, mid)
    alive = {t["description"]: t["id"] for t in
             store.q("SELECT id, description FROM tasks WHERE source_meeting_id=? AND status='active'", (mid,))}
    assert list(alive) == [FIRST["description"]]
    assert alive[FIRST["description"]] == before[FIRST["description"]], "номер задачи, оставшейся в сборке, изменился"
    gone = store.q("SELECT * FROM tasks WHERE source_meeting_id=? AND status='dropped'", (mid,))
    assert len(gone) == 1 and gone[0]["date_closed"] == "2026-10-01"
    hist = store.q("SELECT * FROM task_history WHERE task_id=? ORDER BY id DESC", (gone[0]["id"],))[0]
    assert hist["source"] == "rebuild" and "не вошла в пересборку" in hist["evidence_quote"]
    assert not store.q("SELECT id FROM cards WHERE kind='rebuild_kept'")


def test_rebuild_keeps_task_edited_by_human_with_one_card(store, project, make_pipe, monkeypatch):
    # 28.10.2026: снимается только задача без цитаты в записи — здесь цитаты «нет», как при сменившейся записи
    monkeypatch.setattr(rebuild_mod, "цитата_в_записи", lambda *a, **k: False)
    p, mid = _build(make_pipe, store, project)
    missing = [t for t in store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (mid,))
               if t["description"] != FIRST["description"]][0]
    p.reg.comment(missing["id"], "взял в работу, проверил", "оператор")
    p.gen = OnlyFirst()
    p.run(project, mid)
    p.run(project, mid)                       # повторная пересборка не плодит карточки
    t = store.get("tasks", missing["id"])
    assert t["status"] == TaskStatus.ACTIVE.value
    cards = store.q("SELECT * FROM cards WHERE kind='rebuild_kept'")
    assert len(cards) == 1 and str(missing["id"]) in cards[0]["payload"]


def test_incomplete_extraction_drops_nothing(store, project):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    tid = store.insert("tasks", project_id=project, description="Старая задача", status="active",
                       source_meeting_id=mid, date_set="2026-10-01")
    res = drop_missing(store, TaskRegistry(store), mid, "2026-10-01", kept_ids=set(), incomplete=True)
    assert res["dropped"] == [] and store.get("tasks", tid)["status"] == "active"


def test_rebuild_fills_empty_assignee_of_kept_task(store, project, make_pipe):
    """28.10.2026, отчёт ЛМ 2469aec: при пересборке ворота нашли исполнителя, а прежняя строка этой встречи без
    исполнителя оставалась пустой (повтор узнавался только при том же исполнителе). Теперь пустая строка получает его,
    с историей; номер задачи прежний, заданного исполнителя не меняем."""
    p, mid = _build(make_pipe, store, project, gen=OnlyFirst())
    t = store.q("SELECT * FROM tasks WHERE source_meeting_id=? AND description=?", (mid, FIRST["description"]))[0]
    store.update("tasks", t["id"], assignee=None)               # прежняя сборка исполнителя не дала
    p.run(project, mid)
    after = store.get("tasks", t["id"])
    assert after["assignee"] == "Петрова Анастасия" and after["status"] == TaskStatus.ACTIVE.value
    assert len(store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active'", (mid,))) == 1
    hist = store.q("SELECT * FROM task_history WHERE task_id=? ORDER BY id DESC", (t["id"],))[0]
    assert "исполнитель найден при пересборке" in hist["evidence_quote"]


def test_rebuild_keeps_task_whose_quote_is_in_transcript_2810(store, project, make_pipe):
    """Решение владелицы 28.10.2026: задача прежней сборки, которую новая сборка той же записи не выдала, остаётся, если её
    цитата в записи есть (28.10: вторая сборка сняла 9 задач из 18). Снимается — только без цитаты в записи."""
    p, mid = _build(make_pipe, store, project)
    p.gen = OnlyFirst()
    p.run(project, mid)
    alive = store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active'", (mid,))
    assert len(alive) == 2
    assert not store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='dropped'", (mid,))


def test_rebuild_drops_task_replaced_with_same_quote_2810(store, project, make_pipe):
    """Отчёт ЛМ 8680ea4: прежняя задача, чью цитату несёт новая задача этой сборки, — замена, снимается (иначе дубль)."""
    from meetflow.core.rebuild import drop_missing
    p, mid = _build(make_pipe, store, project)
    old = store.q("SELECT * FROM tasks WHERE source_meeting_id=? ORDER BY id", (mid,))[0]
    new = p.reg.add(project, old["description"] + " (другими словами)", None, mid, old["source_quote"])
    res = drop_missing(store, p.reg, mid, "2026-10-01", {new}, текст_записи=TRANSCRIPT)
    assert old["id"] in [t["id"] for t in res["dropped"]]


def test_rebuild_prefers_active_over_dropped_with_same_quote_2810(store, project, make_pipe):
    """Отчёт ЛМ d096df6: снятая 87 и действующая 101 с той же цитатой — пересборка узнавала первой снятую (меньший номер)
    и возвращала её: две пары дублей. Теперь узнаётся действующая, снятая остаётся снятой."""
    p, mid = _build(make_pipe, store, project, gen=OnlyFirst())
    old = store.q("SELECT * FROM tasks WHERE source_meeting_id=? AND description=?", (mid, FIRST["description"]))[0]
    p.reg.set_status(old["id"], TaskStatus.DROPPED, "rebuild", "не вошла в пересборку (28.10.2026 14:52)")
    new = p.reg.add(project, old["description"], old["assignee"], mid, old["source_quote"])
    p.run(project, mid)
    assert store.get("tasks", old["id"])["status"] == TaskStatus.DROPPED.value
    assert store.get("tasks", new)["status"] == TaskStatus.ACTIVE.value
    assert len(store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status='active' AND source_quote=?",
                       (mid, old["source_quote"]))) == 1
