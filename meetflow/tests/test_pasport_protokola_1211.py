# -*- coding: utf-8 -*-
"""Паспорт принятого протокола (12.11.2026): числа и фразы, которые обязаны сохраниться после пересборки."""
from __future__ import annotations

from meetflow.core import pasport_protokola as pp
from meetflow.core.store import Store


def _мир():
    s = Store(":memory:")
    mid = s.insert("meetings", project_id=1, date="2026-11-11", label="Встреча",
                   protocol_md="## Решения\n**Титан** – акт подписан.\n## Поставленные на встрече\n")
    s.insert("protocol_versions", meeting_id=mid, version=1, protocol_md="## Решения\n", built_at="2026-11-11T10:00")
    s.insert("tasks", project_id=1, description="Подписать акт", assignee="Иванов Иван", status="active",
             source_meeting_id=mid)
    s.insert("tasks", project_id=1, description="Снять старую", assignee="", status="dropped",
             source_meeting_id=mid)
    return s, mid


def test_паспорт_снимается_и_сходится():
    s, mid = _мир()
    ф = pp.снять(s, mid, by="тест")
    assert ф["active_tasks"] == 1 and ф["assignees"] == 1
    и = pp.сверить(s, mid)
    assert и["есть"] and и["сошлось"], и
    s.close()


def test_паспорт_видит_новую_и_пропавшую_задачу():
    s, mid = _мир()
    pp.снять(s, mid)
    s.insert("tasks", project_id=1, description="Вернулась 375 тысяч", assignee="", status="active",
             source_meeting_id=mid)
    и = pp.сверить(s, mid)
    assert not и["сошлось"]
    assert any("активных задач" in р for р in и["расхождения"])
    assert any("появились формулировки" in р for р in и["расхождения"])
    s.close()


def test_паспорт_видит_смену_ответственного_и_потерю_заголовка():
    s, mid = _мир()
    pp.снять(s, mid)
    t = s.q("SELECT id FROM tasks WHERE status='active'")[0]["id"]
    s.update("tasks", t, assignee="")
    m = s.get("meetings", mid)
    s.update("meetings", mid, protocol_md=(m["protocol_md"] or "").replace("**Титан**", "**Проект не определён**"))
    и = pp.сверить(s, mid)
    assert not и["сошлось"]
    assert any("с ответственным" in р for р in и["расхождения"])
    assert any("заголовки" in р for р in и["расхождения"])
    s.close()


def test_без_паспорта_расхождений_нет():
    s, mid = _мир()
    и = pp.сверить(s, mid)
    assert и == {"есть": False, "расхождения": []}
    s.close()


def test_расхождение_даёт_одну_карточку_разбора():
    class Карточки:
        def __init__(self):
            self.открытые = []

        def open(self, project_id, kind, title, payload, meeting_id):
            self.открытые.append((kind, title, payload))

    class Пайп:
        def __init__(self, store):
            self.s = store
            self.cards = Карточки()

    s, mid = _мир()
    pp.снять(s, mid)
    s.insert("tasks", project_id=1, description="Вернулась лишняя", assignee="", status="active",
             source_meeting_id=mid)
    p = Пайп(s)
    и = pp.карточка_при_расхождении(p, 1, mid)
    assert not и["сошлось"] and len(p.cards.открытые) == 1
    assert p.cards.открытые[0][0] == "technical" and "Паспорт" in p.cards.открытые[0][1]
    s.close()
