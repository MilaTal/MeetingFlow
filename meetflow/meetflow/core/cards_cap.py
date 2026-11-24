"""Пороги карточек MeetFlow — 30 (решение владелицы 24.11.2026).

1. Технические сообщения (`technical`/`event`) — 30 самых новых открытых; остальные закрываются системно
   (`rejected`), записи остаются в базе.
2. «Разбор» — блоки «Срок» (`due_unconfirmed`, `closing_candidate`, `mass_closing`) и «Задачи и замечания»
   (`held_task`, `member_note`, `review_finding`, `task_doubt`): по 30 самых новых открытых в каждом блоке, остальные
   закрываются нейтрально — протокол, задачи и правила памяти не меняются.

Запуск: при открытии экранов «Разбор» и «Система → Сообщения». Часового потока в MeetFlow нет, поэтому порог
применяется на первом же открытии экрана.
"""
from __future__ import annotations

from .store import now

ПРЕДЕЛ = 30

ГРУППЫ_РАЗБОРА = {
    "Срок": ("due_unconfirmed", "closing_candidate", "mass_closing"),
    "Задачи и замечания": ("held_task", "member_note", "review_finding", "task_doubt"),
}


def _закрыть(store, ids: list[int], resolution: str) -> int:
    for cid in ids:
        store.update("cards", int(cid), status="rejected", resolution=resolution, resolved_at=now())
    return len(ids)


def технические(store, предел: int = ПРЕДЕЛ) -> int:
    """Технические сообщения: 30 самых новых открытых, остальные закрываются. Возвращает число закрытых."""
    if предел < 0:
        предел = 0
    открытые = store.q(
        "SELECT id FROM cards WHERE status='open' AND kind IN ('technical','event') "
        "ORDER BY created_at DESC, id DESC")
    return _закрыть(store, [r["id"] for r in открытые[предел:]],
                    "Закрыто системно: сверх 30 самых новых")


def разбор(store, предел: int = ПРЕДЕЛ) -> int:
    """Блоки «Срок» и «Задачи и замечания»: по 30 самых новых открытых, остальные закрываются. Возвращает число."""
    if предел < 0:
        предел = 0
    закрыто = 0
    for виды in ГРУППЫ_РАЗБОРА.values():
        метки = ",".join("?" * len(виды))
        открытые = store.q(
            f"SELECT id FROM cards WHERE status='open' AND kind IN ({метки}) "
            "ORDER BY created_at DESC, id DESC", tuple(виды))
        закрыто += _закрыть(store, [r["id"] for r in открытые[предел:]],
                           "Закрыто системно: сверх 30 в блоке «Разбор»")
    return закрыто
