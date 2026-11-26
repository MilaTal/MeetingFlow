# -*- coding: utf-8 -*-
"""Папка-приёмник: фон не умирает и поднимается сам (26.11.2026).

Живой случай: 25.11.2026 поток обхода умер на записи итога прохода — `sqlite3.OperationalError: database is locked`
(база на сетевом диске). Карточка о сбое тоже не записалась (та же занятая база), исключение вышло из `_loop` и
убило поток. С тех пор записи из папки не забирались, а мониторинг показывал «Папка-приёмник — нет: фоновый забор
не запущен» до перезапуска сервера. Здесь три правила, которые это закрывают: запись повторяется, пока база занята;
цикл обхода переживает сбой; упавший поток поднимается сторожами без перезапуска сервера.
"""
from __future__ import annotations

import sqlite3

from meetflow.core.intake import IntakeService


class _Карточки:
    def __init__(self):
        self.открытые = []

    def open(self, project_id, kind, title, data=None, meeting_id=None):
        self.открытые.append(title)


class _Пайп:
    def __init__(self, store):
        self.s = store
        self.cards = _Карточки()


def test_запись_повторяется_когда_база_занята(store):
    """«database is locked» — не приговор: запись повторяется с паузой и доходит."""
    store.ЗАНЯТА_ПАУЗА_СЕК = 0.01
    вызовы = {"n": 0}

    def действие():
        вызовы["n"] += 1
        if вызовы["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return 42

    assert store._с_повтором(действие) == 42
    assert вызовы["n"] == 3


def test_чужая_ошибка_не_повторяется(store):
    """Повторяем только занятую базу; «нет такой таблицы» — сразу наружу, иначе ошибка прячется."""
    вызовы = {"n": 0}

    def действие():
        вызовы["n"] += 1
        raise sqlite3.OperationalError("no such table: cards")

    try:
        store._с_повтором(действие)
    except sqlite3.OperationalError as e:
        assert "no such table" in str(e)
    else:
        raise AssertionError("ошибка должна была выйти наружу")
    assert вызовы["n"] == 1


def test_поток_обхода_переживает_сбой_прохода(store, project, monkeypatch):
    """Сбой прохода (та же занятая база) остаётся в состоянии и карточкой, а цикл идёт дальше."""
    служба = IntakeService(_Пайп(store))
    store.set_setting("watch_folder", r"P:\__нет_такой_папки__", project, "тест")
    monkeypatch.setattr(служба, "interval", lambda pid: 0)
    вызовы = {"n": 0}

    def проход(pid, today=None):
        вызовы["n"] += 1
        if вызовы["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        служба._stop.set()            # второй проход состоялся — останавливаем цикл изнутри
        return {"status": "ok"}

    monkeypatch.setattr(служба, "scan_project", проход)
    служба.start(tick=0.01)
    служба._thread.join(timeout=5)
    assert вызовы["n"] >= 2, вызовы                  # цикл не умер на первом сбое
    assert "locked" in (служба._last_error or "")
    assert any("Сбой прохода папки-приёмника" in t for t in служба.pipe.cards.открытые)
    служба.stop()


def test_упавший_поток_поднимается_сам(store, monkeypatch):
    """Поток завершился (как 25.11) — ensure_running поднимает его и говорит об этом карточкой."""
    служба = IntakeService(_Пайп(store))
    служба.start(tick=0.01)
    служба._stop.set()                                 # имитируем падение: поток вышел, фон разрешён
    служба._thread.join(timeout=5)
    assert not служба.running
    служба._stop.clear()
    assert служба.ensure_running() is True
    assert служба.running
    assert any("Фоновый забор папки-приёмника перезапущен" in t for t in служба.pipe.cards.открытые)
    служба.stop()


def test_второй_экземпляр_фон_не_поднимает(store):
    """Фон не запускался (`start` не звали) — ensure_running молчит: второй экземпляр на базе забор не ведёт."""
    служба = IntakeService(_Пайп(store))
    assert служба.ensure_running() is False
    assert not служба.running
