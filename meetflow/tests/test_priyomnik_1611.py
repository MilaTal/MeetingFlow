# -*- coding: utf-8 -*-
"""Приёмник: дата по времени файла и ранний перенос в «обработано» (16.11.2026).

Слово владелицы: «проверить, почему осталось в папке приёмника — а не в отработанных… чтобы отработанные файлы
уходили в отработанные сразу». Правила перенесены из Планёрки: файл уезжает в «обработано» сразу после приёма,
а дата берётся из имени, иначе из папки дня, иначе по времени файла.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path

from meetflow.connectors.watch_folder import FolderIntake
from meetflow.core.intake import IntakeService


def _файл(папка: Path, имя: str, содержимое: bytes = b"RIFF....", возраст_дней: int = 0) -> Path:
    путь = папка / имя
    путь.write_bytes(содержимое)
    if возраст_дней:
        старое = time.time() - возраст_дней * 86400
        os.utime(путь, (старое, старое))
    return путь


def test_дата_по_времени_файла_когда_в_имени_её_нет(tmp_path):
    """Файл с названием по теме (без даты) принимается: день — по времени файла, факт назван в отчёте."""
    _файл(tmp_path, "Организация тендерной работы.mp3")
    приёмник = FolderIntake(tmp_path, set())
    приёмник.scan()                       # первый проход: файл «не осел»
    итог = приёмник.scan()                # второй: размер не менялся
    assert [i.path.name for i in итог.ready] == ["Организация тендерной работы.mp3"]
    assert итог.ready[0].meeting_date == date.today()
    assert итог.дата_по_времени == ["Организация тендерной работы.mp3"]


def test_старый_файл_без_даты_не_угадывается(tmp_path):
    """Время файла старше 120 дней — день не угадываем: файл остаётся и попадает в «нет даты»."""
    _файл(tmp_path, "Старая запись.mp3", возраст_дней=200)
    приёмник = FolderIntake(tmp_path, set())
    приёмник.scan()
    итог = приёмник.scan()
    assert итог.ready == []
    assert итог.no_date == ["Старая запись.mp3"]


def test_дата_из_имени_важнее_времени_файла(tmp_path):
    """Дата в имени — главный источник; время файла не перебивает."""
    _файл(tmp_path, "Встреча 05.11.2026.mp3", возраст_дней=3)
    приёмник = FolderIntake(tmp_path, set())
    приёмник.scan()
    итог = приёмник.scan()
    assert итог.ready and итог.ready[0].meeting_date == date(2026, 11, 5)
    assert итог.дата_по_времени == []


class _Карточки:
    def __init__(self):
        self.открытые = []

    def open(self, project_id, kind, title, data=None, meeting_id=None):
        self.открытые.append(title)


class _Пайп:
    def __init__(self, store):
        self.s = store
        self.cards = _Карточки()


def test_рабочая_копия_и_её_уборка(store, tmp_path):
    """Копия для обработки создаётся рядом с базой и убирается после приёма; исходник не трогается."""
    исходник = _файл(tmp_path, "Запись 12.11.2026.mp3", содержимое=b"RIFF" * 100)
    служба = IntakeService(_Пайп(store))
    копия = служба._рабочая_копия(исходник)
    assert копия is not None and копия.is_file() and копия.read_bytes() == исходник.read_bytes()
    assert копия != исходник and "приёмник" in str(копия).lower()
    служба._убрать_копию(копия)
    assert not копия.exists()
    assert исходник.exists()          # исходник остаётся — его переносит приёмник в «обработано»
