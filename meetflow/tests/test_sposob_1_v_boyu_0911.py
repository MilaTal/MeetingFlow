"""Способ 1 в бою — выключатель на 13.11 (09.11.2026).

Решение владелицы по замеру В ещё не принято, но если она скажет «включаем», это должно быть переключение, а не правка
кода. `WEBAPP_SVEDENIE_V_BOY=1` снимает у обычной сборки условие «рядом» — ровно то, что считает тень. По умолчанию
**выключено**: бой идёт как сейчас.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from meetflow.core import ukrupnenie_sborka as сборка
from meetflow.core import ukrupnenie_zadach as уз


def test_по_умолчанию_способ_1_не_в_бою(monkeypatch):
    monkeypatch.delenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, raising=False)
    assert уз.способ_1_в_бою() is False
    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "0")
    assert уз.способ_1_в_бою() is False
    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "1")
    assert уз.способ_1_в_бою() is True
    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "да")
    assert уз.способ_1_в_бою() is True


def _план():
    d = SimpleNamespace(description="Подготовить график поставки труб", quote="", due_date="")
    g = SimpleNamespace(description="Подготовить график поставки труб", quote="", assignee=None, pending=None)
    return [(d, g)]


@pytest.fixture
def захват(monkeypatch):
    """Подменяет само укрупнение: проверяем только, что сборка передаёт выключатель."""
    пойманное: dict = {}

    def фейк(задачи, запись, **кв):
        пойманное.update(кв)
        return задачи, {"было": len(задачи), "стало": len(задачи), "групп": 0, "объединено": 0, "сомнений": 0,
                        "по_предмету": 0, "по_контрагенту": 0, "по_подпроектам": 0, "через_отдел": 0, "пары": []}
    monkeypatch.setattr(уз, "укрупнить", фейк)
    return пойманное


def test_выключатель_передаётся_в_сборку(store, project, monkeypatch, захват):
    monkeypatch.delenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, raising=False)
    сборка.применить(store, project, 1, _план(), "", set())
    assert захват.get("без_рядом") is False

    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "1")
    итог = сборка.применить(store, project, 1, _план(), "", set())
    assert захват.get("без_рядом") is True
    assert "способ 1 в бою" in итог["строка"], "в отчёте сборки видно, что бой без условия «рядом»"
