"""Служебные строки истории не считаются цитатой (правки ERP/Планёрки 03–06.11, п. 8).

В ERP из-за этого задача снималась по служебной записи («нет в списке», «ответственный →», «сведено»). В MeetFlow
цитата хранится отдельным полем, но если туда попала служебная строка, она не должна держать задачу от снятия:
работа в записи не доказана. Настоящая цитата записи — держит; строка секретаря — держит своим правилом.
"""
from __future__ import annotations

from meetflow.core import rebuild
from meetflow.core.registry import TaskRegistry
from meetflow.core.types import TaskStatus

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте график поставки труб к пятнице.\n")


def test_служебные_начала():
    for строка in ("ответственный → Петров И.", "ответственный: Сидоров", "сведено с задачей №4: график поставки",
                   "нет в списке", "Объединено из: 1) подготовить график", "исполнитель перенесён при пересборке",
                   "не вошла в пересборку (08.11.2026 12:00)"):
        assert rebuild.служебная_строка(строка), строка
    assert not rebuild.служебная_строка("[00:02:00] Петрова Анастасия: подготовьте график поставки труб")
    assert not rebuild.служебная_строка("")


def _задача(store, project, meeting, текст, цитата):
    return TaskRegistry(store).add(project, текст, "Петрова Анастасия", meeting, цитата, None, "2026-11-06")


def test_служебная_цитата_не_держит_задачу(store, project, meeting):
    tid = _задача(store, project, meeting, "Подготовить график поставки труб",
                  "ответственный → Петрова Анастасия: подготовить график поставки труб")
    итог = rebuild.drop_missing(store, TaskRegistry(store), meeting, "2026-11-06", kept_ids=set(),
                                текст_записи=ЗАПИСЬ)
    assert [t["id"] for t in итог["dropped"]] == [tid], итог
    assert store.get("tasks", tid)["status"] == TaskStatus.DROPPED.value


def test_настоящая_цитата_держит_задачу(store, project, meeting):
    tid = _задача(store, project, meeting, "Подготовить график поставки труб",
                  "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте график поставки труб к пятнице.")
    итог = rebuild.drop_missing(store, TaskRegistry(store), meeting, "2026-11-06", kept_ids=set(),
                                текст_записи=ЗАПИСЬ)
    assert [t["id"] for t in итог["kept_quote"]] == [tid], итог
    assert store.get("tasks", tid)["status"] == TaskStatus.ACTIVE.value


def test_строка_секретаря_держит_задачу(store, project, meeting):
    reg = TaskRegistry(store)
    tid = _задача(store, project, meeting, "Согласовать график с подрядчиком", "")
    store.insert("task_history", task_id=tid, old_status="active", new_status="active",
                 source=rebuild.СЕКРЕТАРСКИЙ_ИСТОЧНИК, evidence_quote="строка протокола секретаря")
    итог = rebuild.drop_missing(store, reg, meeting, "2026-11-06", kept_ids=set(), текст_записи=ЗАПИСЬ)
    assert [t["id"] for t in итог["kept_secretary"]] == [tid], итог
    assert store.get("tasks", tid)["status"] == TaskStatus.ACTIVE.value
