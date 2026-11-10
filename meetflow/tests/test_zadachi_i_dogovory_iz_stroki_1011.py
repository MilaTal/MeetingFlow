# -*- coding: utf-8 -*-
"""Задачи и договорённости — из строки конкретной встречи (10.11.2026, жалоба владелицы).

В меню проекта общих списков у «Общих встреч» нет; чтобы было видно, откуда открыть, в «…» строки реестра встреч
появились пункты «Реестр задач встречи» и «Договорённости встречи». Первый открывает реестр с фильтром по встрече,
второй — страницу встречи сразу с панелью договорённостей.
"""
from pathlib import Path

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_в_строке_встречи_свои_задачи_и_договорённости():
    js = (СТАТИКА / "nav.js").read_text(encoding="utf-8")
    assert 'data-act="tasks">Реестр задач встречи</button>' in js
    assert 'data-act="agreements">Договорённости встречи</button>' in js
    assert "реестрПоВстрече(m.id, m.date)" in js
    assert "#meetings/${m.id}/agreements" in js


def test_адрес_встречи_открывает_панель_договорённостей():
    js = (СТАТИКА / "meeting.js").read_text(encoding="utf-8")
    assert "сразу открывает панель договорённостей" in js
    assert 'await открыть("agreements", панель)' in js
