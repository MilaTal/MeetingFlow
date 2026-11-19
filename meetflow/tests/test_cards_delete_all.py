# -*- coding: utf-8 -*-
"""Массовое удаление карточек (слово владелицы 19.11.2026: «карточки — все убрать сейчас»).

Тестовый режим: карточки уходят насовсем (и открытые, и решённые), журнал решений остаётся — по нему видно,
что и когда решали. Проверяем и число, и то, что решения не задеты.
"""
from meetflow.core.registry import CardQueue
from meetflow.core.types import CardStatus


def test_delete_all_cards_keeps_decisions(store, project):
    q = CardQueue(store)
    закрытая = q.open(project, "technical", "старая карточка")
    q.resolve(закрытая, CardStatus.ACCEPTED, "да")
    q.open(project, "technical", "открытая карточка")
    ещё = q.open(project, "technical", "ещё открытая")

    assert q.delete_all() == (3, 2)
    assert store.q("SELECT * FROM cards") == []
    assert len(store.q("SELECT * FROM decisions")) == 1
    assert ещё  # карточки были заведены — проверка не на пустой базе
