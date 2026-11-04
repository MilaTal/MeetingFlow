# -*- coding: utf-8 -*-
"""События журнала и сбои в «Разборе» (решение разработчика 05.11.2026).

События (роль назначена, встреча удалена, протокол собран внешней моделью, второй экземпляр) в «Разбор» не идут:
у них вид `event`. Сбои (`technical`) идут и считаются в норму. Неизвестный заголовок технической карточки —
сбой: лучше лишняя карточка, чем скрытый сбой.
"""
import json

from meetflow.core.store import Store, now
from meetflow.web.erp.razbor import СОБЫТИЯ, это_событие


def test_известные_события_узнаются():
    for з in ("Протокол встречи 2026-11-03 собран внешней моделью", "Удалена встреча 03.11.2026 (№8)",
              "Встреча переименована", "Второй экземпляр MeetFlow на той же базе",
              "Назначена роль: Иванов — администратор", "Из протокола убрана системная пометка"):
        assert это_событие(з), з


def test_неизвестный_заголовок_не_событие():
    assert not это_событие("Голоса не разобраны: запись 14.26")
    assert not это_событие("Шаг сборки не выполнен: Единицы встречи")
    assert not это_событие("")
    assert not это_событие(None)


def test_разбор_событие_не_показывает_сбой_показывает():
    from meetflow.web.erp.razbor import EXCLUDED
    s = Store(":memory:")
    s.insert("cards", project_id=None, kind="event", title="Удалена встреча", status="open", created_at=now(),
             payload=json.dumps({}, ensure_ascii=False))
    s.insert("cards", project_id=None, kind="technical", title="Удалена встреча 03.11.2026 (№8)", status="open",
             created_at=now(), payload=json.dumps({}, ensure_ascii=False))
    s.insert("cards", project_id=None, kind="technical", title="Голоса не разобраны: запись 14.26", status="open",
             created_at=now(), payload=json.dumps({}, ensure_ascii=False))
    s.insert("cards", project_id=None, kind="technical", title="Что-то новое и непонятное", status="open",
             created_at=now(), payload=json.dumps({}, ensure_ascii=False))
    rows = [c for c in s.q("SELECT * FROM cards WHERE status='open' ORDER BY id")
            if c["kind"] not in EXCLUDED and not (c["kind"] == "technical" and это_событие(c["title"]))]
    assert [c["title"] for c in rows] == ["Голоса не разобраны: запись 14.26", "Что-то новое и непонятное"]


def test_список_событий_явный():
    assert СОБЫТИЯ == ("Протокол встречи", "Удалена встреча", "Встреча переименована", "Второй экземпляр",
                       "Назначена роль", "Из протокола убрана системная пометка")
