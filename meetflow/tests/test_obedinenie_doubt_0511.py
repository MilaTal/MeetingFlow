# -*- coding: utf-8 -*-
"""Сквозная проверка «под вопросом» без карточки после сбоя дополнения (05.11.2026).

Длинный пункт без предмета остаётся в реестре с `doubt_reason`; карточка не заводится; цитата и её место
не подменяются причиной. Модель падает, молчит или возвращает слово не из записи — три случая.
"""
from meetflow.core import obedinenie as о
from meetflow.core import ukrupnenie_sborka as us
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import GateResult, TaskDraft

ЗАПИСЬ = ("[00:10:00] Иванов Пётр: Обсудили динамику по просроченным обязательствам за прошлый квартал "
          "по договору 45 и решили посмотреть ещё раз.")
ЦИТАТА = "Обсудили динамику по просроченным обязательствам за прошлый квартал по договору 45"
ДЛИННАЯ = "Посмотреть динамику по просроченным обязательствам за прошлый квартал"


def _собрать(модель):
    s = Store(":memory:")
    pid = s.insert("projects", name="", theme="_default")   # проекта встречи нет — длинный пункт без предмета
    mid = s.insert("meetings", project_id=pid, date="2026-10-26", label="в")
    s.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", text=ЗАПИСЬ)
    d = TaskDraft(description=ДЛИННАЯ, assignee=None, quote=ЦИТАТА)
    g = GateResult(True, [], quote=ЦИТАТА, description=ДЛИННАЯ)
    res = us.объединение(s, pid, [(d, g)], ЗАПИСЬ, модель, mid, "2026-10-26")
    d2, g2 = res["planned"][0]
    tid = TaskRegistry(s).add(pid, g2.description, None, mid, g2.quote, d2.due_date, "2026-10-26",
                              doubt_reason=d2.doubt_reason)
    return s, tid


def _проверить(s, tid, цитата=ЦИТАТА):
    t = s.get("tasks", tid)
    assert t["doubt_reason"] == о.ПОД_ВОПРОСОМ_БЕЗ_ПРЕДМЕТА
    assert t["source_quote"] == цитата
    assert not s.q("SELECT id FROM cards")


def test_падающая_модель_оставляет_задачу_под_вопросом():
    def сбой(system, user):
        raise RuntimeError("сеть")

    s, tid = _собрать(сбой)
    _проверить(s, tid)


def test_молчащая_модель_оставляет_задачу_под_вопросом():
    s, tid = _собрать(lambda system, user: {})
    _проверить(s, tid)


def test_слово_не_из_записи_оставляет_задачу_под_вопросом():
    s, tid = _собрать(lambda system, user: {"пункты": [{"номер": 1, "формулировка": "Посмотреть динамику по бетону"}]})
    _проверить(s, tid)
