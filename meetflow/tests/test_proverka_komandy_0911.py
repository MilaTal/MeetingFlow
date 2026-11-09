"""Проверка «Команды» после правки отчеств (план, пункт 22).

Дубли — ошибка (код 2), тёзки с разными отчествами — норма (показываются списком), без отчества и одно слово — что ещё не
доделано. Имена только в консоль; тесты на вымышленных людях.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from meetflow.core.store import Store

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "proverka_komandy.py"
    spec = importlib.util.spec_from_file_location("proverka_komandy", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


@pytest.fixture
def база(tmp_path):
    путь = tmp_path / "люди.db"
    s = Store(str(путь))
    pid = s.insert("projects", name="Склад", theme="it_product", archived=0)
    архив = s.insert("projects", name="Старый", theme="it_product", archived=1)
    for фио in ("Иванов Пётр Сергеевич", "Петрова Анна", "Сидоров Пётр Иванович", "Кузнецов",
                "Иванов Пётр  сергеевич"):     # дубль: регистр и лишние пробелы
        s.insert("people", project_id=pid, full_name=фио, confirmed=1)
    s.insert("people", project_id=pid, full_name="Иванов Пётр Иванович", confirmed=1)   # тёзка — норма
    s.insert("people", project_id=архив, full_name="Старый Человек", confirmed=1)
    s.close()
    return путь


def test_дубли_и_тёзки_различаются(база):
    м = _скрипт()
    разбор = м.собрать(база)
    склад = next(п for пid, п in разбор.items() if п["проект"] == "Склад")
    assert list(склад["дубли"]) == ["иванов петр сергеевич"]
    assert len(склад["дубли"]["иванов петр сергеевич"]) == 2
    assert len(склад["тёзки"]) == 1 and len(list(склад["тёзки"].values())[0]) == 2
    assert склад["без_отчества"] == ["Петрова Анна"]
    assert склад["одно_слово"] == ["Кузнецов"]
    assert all(п["проект"] != "Старый" for п in разбор.values()), "архив не проверяем"


def test_дубль_даёт_код_2(база, capsys):
    м = _скрипт()
    assert м.main(["--db", str(база)]) == 2
    вывод = capsys.readouterr()
    assert "дубль: Иванов Пётр  сергеевич" in вывод.out     # как записано в базе, с двойным пробелом
    assert "Иванов Пётр Сергеевич" in вывод.out
    assert "есть, разобрать" in вывод.out and "ВНИМАНИЕ" in вывод.err


def test_без_дублей_код_0(tmp_path, capsys):
    м = _скрипт()
    путь = tmp_path / "чисто.db"
    s = Store(str(путь))
    pid = s.insert("projects", name="Склад", theme="it_product", archived=0)
    for фио in ("Иванов Пётр Сергеевич", "Петрова Анна Сергеевна", "Сидоров Пётр Иванович"):
        s.insert("people", project_id=pid, full_name=фио, confirmed=1)
    s.close()
    assert м.main(["--db", str(путь), "--кратко"]) == 0
    вывод = capsys.readouterr().out
    assert "дублей 0" in вывод and "дублей 0 — нет" in вывод and "Иванов" not in вывод
