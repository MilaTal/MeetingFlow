"""Аудит выключателей: значения читаются теми же функциями, что и код (план, пункт 27)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "nastrojki.py"
    spec = importlib.util.spec_from_file_location("nastrojki", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


def _настройка(строки, имя):
    return next(с for с in строки if с["переменная"] == имя)


def test_по_умолчанию_всё_как_решили(monkeypatch):
    from meetflow.core import protokol_poteri as пп
    from meetflow.core import svedenie_ten as ст
    from meetflow.core import ukrupnenie_zadach as уз

    for имя in (ст.ПЕРЕМЕННАЯ, ст.ПЕРЕМЕННАЯ_СРАВНЕНИЯ, ст.ПЕРЕМЕННАЯ_ПРЕДЕЛА, уз.ПЕРЕМЕННАЯ_В_БОЙ,
                пп.ПЕРЕМЕННАЯ_ПОРОГ, пп.ПЕРЕМЕННАЯ_ВОЗВРАТ, уз.ПЕРЕМЕННАЯ):
        monkeypatch.delenv(имя, raising=False)
    строки = _скрипт().строки_настроек()
    assert _настройка(строки, ст.ПЕРЕМЕННАЯ)["действует"] == "включена"
    assert _настройка(строки, ст.ПЕРЕМЕННАЯ_СРАВНЕНИЯ)["действует"] == "включено"
    assert _настройка(строки, ст.ПЕРЕМЕННАЯ_ПРЕДЕЛА)["действует"] == str(ст.ПРЕДЕЛ_СРАВНЕНИЯ)
    assert _настройка(строки, уз.ПЕРЕМЕННАЯ_В_БОЙ)["действует"] == "выключен"
    assert _настройка(строки, пп.ПЕРЕМЕННАЯ_ПОРОГ)["действует"] == str(пп.ПОРОГ_ОПОРЫ)
    assert _настройка(строки, пп.ПЕРЕМЕННАЯ_ВОЗВРАТ)["действует"] == "включён"


def test_заданные_переменные_видны(monkeypatch):
    from meetflow.core import protokol_poteri as пп
    from meetflow.core import svedenie_ten as ст
    from meetflow.core import ukrupnenie_zadach as уз

    monkeypatch.setenv(уз.ПЕРЕМЕННАЯ_В_БОЙ, "1")
    monkeypatch.setenv(пп.ПЕРЕМЕННАЯ_ПОРОГ, "0.8")
    monkeypatch.setenv(ст.ПЕРЕМЕННАЯ_СРАВНЕНИЯ, "0")
    monkeypatch.setenv(ст.ПЕРЕМЕННАЯ, "0")
    строки = _скрипт().строки_настроек()
    assert _настройка(строки, уз.ПЕРЕМЕННАЯ_В_БОЙ) == {
        "переменная": уз.ПЕРЕМЕННАЯ_В_БОЙ, "что": "способ 1 в бою (сборка без условия «рядом»)",
        "задана": True, "действует": "ВКЛЮЧЁН", "по умолчанию": "выключен"}
    assert _настройка(строки, пп.ПЕРЕМЕННАЯ_ПОРОГ)["действует"] == "0.8"
    assert _настройка(строки, ст.ПЕРЕМЕННАЯ_СРАВНЕНИЯ)["действует"] == "ВЫКЛЮЧЕНО"
    assert _настройка(строки, ст.ПЕРЕМЕННАЯ)["действует"] == "ВЫКЛЮЧЕНА"


def test_таблица_печатается(capsys):
    м = _скрипт()
    assert м.main() == 0
    вывод = capsys.readouterr().out
    assert "переменная" in вывод and "действует" in вывод
    assert "WEBAPP_SVEDENIE_V_BOY" in вывод
