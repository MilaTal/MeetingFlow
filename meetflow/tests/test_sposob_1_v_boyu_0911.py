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


ЗАПИСЬ = "\n".join([
    "00:01:00\tИгнатов Иван\tПетрова Анастасия, подготовьте график поставки труб к пятнице",
    *(f"00:0{i}:00\tИгнатов Иван\tОбсудили текущие вопросы по складу, пункт {i}" for i in range(2, 9)),
    "00:09:00\tИгнатов Иван\tИ график поставки труб согласуйте с подрядчиком до среды",
])


class _Модель:
    """Две задачи про один предмет у одного исполнителя; цитаты стоят далеко друг от друга — «рядом» не сработает."""

    def __init__(self):
        from meetflow.connectors.llm_mock import MockLLM
        self._м = MockLLM()

    def extract_tasks(self, *а, **к):
        return {"tasks": [
            {"description": "Подготовить график поставки труб", "assignee": "Петрова Анастасия", "line": 0,
             "due_date": "к пятнице"},
            {"description": "Согласовать график поставки труб с подрядчиком", "assignee": "Петрова Анастасия", "line": 8,
             "due_date": "до среды"}]}

    def units(self, *а, **к):
        return {"items": []}

    def protocol(self, *а, **к):
        return {"sections": {}}

    def __getattr__(self, имя):
        return getattr(self._м, имя)


def _план_боя():
    """Две задачи про один предмет и исполнителя; цитаты далеко друг от друга — «рядом» не сработает."""
    from meetflow.core.types import GateResult, Person, TaskDraft

    пары = []
    for оп, цитата, строка in (
            ("Подготовить график поставки труб", "Петрова Анастасия, подготовьте график поставки труб к пятнице", 0),
            ("Согласовать график поставки труб с подрядчиком", "И график поставки труб согласуйте с подрядчиком", 8)):
        d = TaskDraft(оп, "Петрова Анастасия", quote=цитата, line_no=строка, due_date="к пятнице")
        g = GateResult(True, [], assignee=Person("Петрова Анастасия"), quote=цитата)
        пары.append((d, g))
    return пары


def test_по_умолчанию_рядом_держит_далёкие_цитаты(store, project, monkeypatch):
    monkeypatch.delenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, raising=False)
    итог = сборка.применить(store, project, 1, _план_боя(), ЗАПИСЬ, set())
    assert len(итог["planned"]) == 2, "по умолчанию бой с условием «рядом»"
    assert "способ 1 в бою" not in (итог["строка"] or "")


def test_включённый_выключатель_снимает_рядом(store, project, monkeypatch):
    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "1")
    итог = сборка.применить(store, project, 1, _план_боя(), ЗАПИСЬ, set())
    assert len(итог["planned"]) == 1, "способ 1 в бою объединяет задачи с далёкими цитатами"
    assert "способ 1 в бою" in (итог["строка"] or "")
