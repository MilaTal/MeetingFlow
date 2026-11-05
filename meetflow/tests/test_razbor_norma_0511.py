# -*- coding: utf-8 -*-
"""«Разбор» к норме: замечания проверки — справка, карточка исполнителя истекает через 7 дней (05.11.2026).

Замечания проверки в «Разбор» и в норму не идут (`review_finding` — как `card_policy` ERP). Карточка выбора
исполнителя старше 7 дней закрывается сама, задача остаётся в реестре без исполнителя (решение владелицы 25.10.2026).
"""
from datetime import datetime, timedelta

from meetflow.core.registry import CardQueue
from meetflow.core.store import Store, now
from meetflow.web.erp.razbor import EXCLUDED


def test_замечания_проверки_не_в_разборе():
    assert "review_finding" in EXCLUDED


def test_чтение_разбора_данные_не_меняет():
    """GET «Разбора» — чтение: срок карточек применяет фоновый обход раз в час и сборка, как в ERP (`conflict_cleanup`)."""
    from pathlib import Path
    razbor = (Path(__file__).resolve().parents[1] / "meetflow" / "web" / "erp" / "razbor.py").read_text(encoding="utf-8")
    assert "expire_assign" not in razbor
    app = (Path(__file__).resolve().parents[1] / "meetflow" / "web" / "app.py").read_text(encoding="utf-8")
    assert "карточки_сторож_старт" in app and "pipe.cards.expire_assign()" in app


def _card(s, kind, days_old, title="Карточка"):
    at = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%S")
    return s.insert("cards", project_id=None, kind=kind, title=title, payload="{}", status="open", created_at=at)


def test_карточка_исполнителя_истекает_через_7_дней_задача_остаётся():
    s = Store(":memory:")
    pid = s.insert("projects", name="П", theme="_default")
    tid = s.insert("tasks", project_id=pid, description="Согласовать график", status="active", date_set="2026-10-20")
    старая = _card(s, "assign_person", 8, "Кто исполнитель: Согласовать график")
    s.update("cards", старая, payload=f'{{"task_id": {tid}}}')
    свежая = _card(s, "assign_person", 2, "Кто исполнитель: другая задача")
    assert CardQueue(s).expire_assign() == 1
    assert s.get("cards", старая)["status"] == "rejected"
    assert "срок карточки 7 дней" in (s.get("cards", старая)["resolution"] or "")
    assert s.get("cards", свежая)["status"] == "open"
    assert s.get("tasks", tid)["status"] == "active"          # задача не потеряна, осталась без исполнителя
    assert s.get("tasks", tid)["assignee"] is None


def test_истечение_не_трогает_другие_виды():
    s = Store(":memory:")
    t = _card(s, "technical", 30, "Голоса не разобраны")
    assert CardQueue(s).expire_assign() == 0
    assert s.get("cards", t)["status"] == "open"
