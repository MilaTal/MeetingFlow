# -*- coding: utf-8 -*-
"""Старт без папки моделей: строка в журнал и одна карточка сбоя (записка 05.11.2026).

Повод — файл `14.26` встречи 7: его обработал процесс, запущенный в обход `python -m meetflow`, `.env.local`
не прочитался, и разделение по голосам выключилось молча. Теперь такой старт пишет строку в журнал сервера
и заводит одну карточку `technical`; повторный старт с той же причиной вторую не заводит.
"""
from types import SimpleNamespace

from meetflow.core import diarize
from meetflow.core.registry import CardQueue
from meetflow.core.store import Store
from meetflow.web.app import голоса_при_старте

ПРИЧИНА = "не задана папка с моделями — укажите VOICE_MODELS_DIR в .env.local"


def _pipe():
    s = Store(":memory:")
    return SimpleNamespace(cards=CardQueue(s)), s


def test_нет_папки_моделей_карточка_одна_и_строка_в_журнал(monkeypatch, capsys):
    pipe, s = _pipe()
    monkeypatch.setattr(diarize, "enabled", lambda: True)
    monkeypatch.setattr(diarize, "available", lambda: (False, ПРИЧИНА))
    assert голоса_при_старте(pipe) == "fail"
    assert голоса_при_старте(pipe) == "fail"                 # повторный старт — не вторая карточка
    rows = s.q("SELECT * FROM cards WHERE kind='technical'")
    assert len(rows) == 1 and rows[0]["status"] == "open"
    assert ПРИЧИНА in (rows[0]["payload"] or "")
    assert ПРИЧИНА in capsys.readouterr().err


def test_модели_на_месте_карточки_нет(monkeypatch):
    pipe, s = _pipe()
    monkeypatch.setattr(diarize, "enabled", lambda: True)
    monkeypatch.setattr(diarize, "available", lambda: (True, ""))
    assert голоса_при_старте(pipe) == "ok"
    assert s.q("SELECT * FROM cards") == []


def test_выключенное_разделение_не_считается_сбоем(monkeypatch):
    pipe, s = _pipe()
    monkeypatch.setattr(diarize, "enabled", lambda: False)

    def _нельзя():
        raise AssertionError("при MEETFLOW_DIARIZE=off модели не проверяются")

    monkeypatch.setattr(diarize, "available", _нельзя)
    assert голоса_при_старте(pipe) == "off"
    assert s.q("SELECT * FROM cards") == []


def test_ошибка_проверки_тоже_карточка_а_не_падение(monkeypatch):
    pipe, s = _pipe()
    monkeypatch.setattr(diarize, "enabled", lambda: True)

    def _сломалось():
        raise RuntimeError("нет доступа к папке")

    monkeypatch.setattr(diarize, "available", _сломалось)
    assert голоса_при_старте(pipe) == "fail"
    assert len(s.q("SELECT * FROM cards WHERE kind='technical'")) == 1
