"""Проверка резервной копии базы (план, пункт 25).

Копия перед правкой отчеств должна открываться, проходить `integrity_check` и содержать нужные таблицы; разница чисел с
рабочей базой — нормально (копия сделана раньше). Тесты на временных копиях.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from meetflow.core.store import Store

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "proverka_kopii.py"
    spec = importlib.util.spec_from_file_location("proverka_kopii", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


def _база(путь: Path, людей: int):
    s = Store(str(путь))
    pid = s.insert("projects", name="Склад", theme="it_product")
    for i in range(людей):
        s.insert("people", project_id=pid, full_name=f"Человек Номер{i} Отчествович", confirmed=1)
    s.insert("meetings", project_id=pid, date="2026-11-06", status="built")
    s.close()
    return путь


@pytest.fixture
def копия(tmp_path):
    рабочая = _база(tmp_path / "рабочая.db", 3)
    копи = _база(tmp_path / "копия.db", 2)      # копия сделана раньше — людей меньше
    return копи, рабочая


def test_целая_копия_годится_и_разница_видна(копия, capsys):
    м = _скрипт()
    копи, рабочая = копия
    разбор = м.проверить(копи)
    assert разбор["целостность"] == "ok" and разбор["пропали"] == []
    assert разбор["числа"]["people"] == 2
    текст = м.отчёт(разбор, м.проверить(рабочая))
    assert "people: 2 (в рабочей 3, разница -1)" in текст and "Копия годится: да" in текст
    assert м.main(["--копия", str(копи), "--база", str(рабочая)]) == 0


def test_битая_копия_не_годится(tmp_path, capsys):
    м = _скрипт()
    битая = tmp_path / "битая.db"
    битая.write_bytes("это не sqlite".encode("utf-8"))
    assert м.main(["--копия", str(битая), "--база", str(tmp_path / "нет.db")]) == 2
    assert "не годится" in capsys.readouterr().err


def test_нет_копии_понятная_ошибка(tmp_path):
    м = _скрипт()
    with pytest.raises(SystemExit):
        м.проверить(tmp_path / "нет-такой.db")
