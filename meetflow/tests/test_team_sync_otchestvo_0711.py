"""Общая «Команда» → проект: отчество, тёзки, порядок слов (записки ecbfc73, 22ad64f, 58febf3).

Правила, которые держим: отчество дописывается в существующую запись, а не заводит двойника; тёзка с другим
отчеством — отдельный человек; порядок слов «Иванов Пётр» / «Пётр Иванов» не даёт дубля.
"""
from __future__ import annotations

import pytest

from meetflow.core import team_sync
from meetflow.core.store import Store


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _общая(monkeypatch, люди: list[dict]):
    monkeypatch.setattr(team_sync, "shared_people", lambda _p=None: люди)


def test_отчество_дописывается_в_существующую_запись(store, monkeypatch):
    pid = store.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    store.insert("people", project_id=pid, full_name="Шаравин Андрей", confirmed=1)
    _общая(monkeypatch, [{"full_name": "Шаравин Андрей Алексеевич", "role": "", "department": "",
                          "external": False, "organization": ""}])
    добавлено = team_sync.sync_people(store, pid)
    строки = store.q("SELECT full_name FROM people WHERE project_id=?", (pid,))
    assert добавлено == 0, "двойник не заводится"
    assert [r["full_name"] for r in строки] == ["Шаравин Андрей Алексеевич"], "отчество дописано в ту же запись"


def test_тёзка_с_другим_отчеством_отдельный_человек(store, monkeypatch):
    pid = store.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    store.insert("people", project_id=pid, full_name="Иванов Пётр Сергеевич", confirmed=1)
    _общая(monkeypatch, [{"full_name": "Иванов Пётр Андреевич", "role": "", "department": "",
                          "external": False, "organization": ""}])
    добавлено = team_sync.sync_people(store, pid)
    имена = sorted(r["full_name"] for r in store.q("SELECT full_name FROM people WHERE project_id=?", (pid,)))
    assert добавлено == 1, "второй тёзка заводится"
    assert имена == ["Иванов Пётр Андреевич", "Иванов Пётр Сергеевич"], "тёзки не сливаются"


def test_порядок_слов_не_даёт_дубля(store, monkeypatch):
    pid = store.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    store.insert("people", project_id=pid, full_name="Пётр Иванов", confirmed=1)
    _общая(monkeypatch, [{"full_name": "Иванов Пётр", "role": "", "department": "",
                          "external": False, "organization": ""}])
    добавлено = team_sync.sync_people(store, pid)
    assert добавлено == 0
    assert len(store.q("SELECT id FROM people WHERE project_id=?", (pid,))) == 1
