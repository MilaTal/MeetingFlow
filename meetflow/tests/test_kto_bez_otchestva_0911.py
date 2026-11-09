"""Кто в «Команде» без отчества — список к правке 9–10.11 (план, пункт 21).

Скрипт только читает базу и печатает имена в консоль; в репозиторий имена не пишутся. Тесты — на вымышленных людях.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from meetflow.core.store import Store

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "kto_bez_otchestva.py"
    spec = importlib.util.spec_from_file_location("kto_bez_otchestva", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


@pytest.fixture
def база(tmp_path):
    путь = tmp_path / "люди.db"
    s = Store(str(путь))
    p1 = s.insert("projects", name="Склад", theme="it_product", archived=0)
    p2 = s.insert("projects", name="Цех", theme="it_product", archived=0)
    архив = s.insert("projects", name="Старый", theme="it_product", archived=1)
    for фио in ("Иванов Пётр Сергеевич", "Петрова Анна", "Сидоров Пётр Иванович", "Кузнецов"):
        s.insert("people", project_id=p1, full_name=фио, confirmed=1)
    s.insert("people", project_id=p2, full_name="Орлова Мария", confirmed=1)
    s.insert("people", project_id=архив, full_name="Старый Человек", confirmed=1)
    s.close()
    return путь


def test_два_слова_без_отчества_три_слова_нет(база):
    м = _скрипт()
    разбор = м.собрать(база)
    склад = next(п for pid, п in разбор.items() if п["проект"] == "Склад")
    assert склад["всего"] == 4 and склад["без_отчества"] == 1
    assert склад["люди"] == ["Петрова Анна"]          # у «Кузнецов» одно слово — это не запись из двух слов
    assert all(п["проект"] != "Старый" for п in разбор.values()), "архивные проекты не в списке"


def test_кратко_без_имён(база):
    м = _скрипт()
    текст = м.отчёт(м.собрать(база), кратко=True)
    assert "без отчества 1 из 4" in текст and "Петрова Анна" not in текст
    assert "Всего: без отчества 2 из 5" in текст


def test_имена_печатаются_в_консоль(база, capsys):
    м = _скрипт()
    assert м.main(["--db", str(база)]) == 0
    вывод = capsys.readouterr().out
    assert "Петрова Анна" in вывод and "Орлова Мария" in вывод


def test_пустая_база_даёт_код_1(tmp_path, capsys):
    м = _скрипт()
    путь = tmp_path / "пусто.db"
    s = Store(str(путь))
    s.insert("projects", name="Пусто", theme="it_product", archived=0)
    s.close()
    assert м.main(["--db", str(путь)]) == 1
    assert "живых проектов с людьми нет" in capsys.readouterr().out
