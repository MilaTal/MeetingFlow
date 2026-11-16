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


class _Источник:
    kind = "text"


class _Плагины:
    def resolve_source(self, имя):
        return _Источник() if имя.lower().endswith(".txt") else None


class _ПайпСПриёмом(_Пайп):
    """Конвейер-заглушка: приём текста сразу «успешен», без распознавания и моделей."""

    def __init__(self, store):
        super().__init__(store)
        self.plugins = _Плагины()
        self.queue = None
        self.принято = []

    def ingest(self, project_id, meeting_id, filename, data=None, path=None, **kwargs):
        self.принято.append(filename)
        return {"status": "ok", "kind": "transcript"}


def test_проход_переносит_файл_и_не_падает(store, project, tmp_path):
    """Сквозная проверка прохода: файл уезжает в «обработано», проход завершается, рабочая копия убрана.

    Тест ловит класс ошибок «переехало и упало»: 16.11.2026 проход падал с NameError после переноса файла, и
    владелица видела «файл исчез, а в базе ничего».
    """
    meeting_date = date.today().isoformat()
    _файл(tmp_path, "Заметки 16.11.2026.txt", содержимое="[00:01:00] Игнатов Иван: подготовьте отчёт".encode())
    приёмник = FolderIntake(tmp_path, set())
    приёмник.scan()
    store.set_setting("watch_folder", str(tmp_path), project, "тест")   # папка-приёмник проекта
    служба = IntakeService(_ПайпСПриёмом(store))
    служба.scan_project(project)                     # первый проход: файл «не осел», только запоминаем размер
    итог = служба.scan_project(project)               # второй: размер не менялся — берём
    assert итог.get("status") == "ok", итог
    assert "Заметки 16.11.2026.txt" in итог.get("ingested", []), итог
    assert (tmp_path / "обработано" / "Заметки 16.11.2026.txt").is_file()
    assert not (tmp_path / "Заметки 16.11.2026.txt").exists()


def test_повторный_файл_не_распознаётся(make_pipe, store, project, meeting, tmp_path):
    """Тот же файл, положенный в другую встречу, узнаётся до распознавания: «уже обработан — встреча N».

    Слово владелицы 16.11.2026: повторная загрузка не должна запускать распознавание заново и плодить встречу-дубль.
    """
    import hashlib

    файл = tmp_path / "запись.wav"
    файл.write_bytes(b"RIFF" + b"\x00" * 4096)
    отпечаток = hashlib.sha256(файл.read_bytes()).hexdigest()
    другая = store.insert("meetings", project_id=project, date="2026-11-10", label="Другая встреча")
    store.insert("file_digests", digest=отпечаток, meeting_id=другая, name="запись.wav", at="2026-11-10T00:00:00")

    конвейер = make_pipe()
    итог = конвейер.ingest(project, meeting, "запись.wav", path=файл)

    assert итог["status"] == "duplicate", итог
    assert итог["existing_meeting"] == другая
    assert not store.q("SELECT id FROM sources WHERE meeting_id=?", (meeting,))   # распознавания не было


def test_предпросмотр_папки_совпадает_с_проходом(tmp_path):
    """Экран настройки обещает то же, что заберёт проход: файл с названием по теме считается пригодным."""
    from meetflow.core.intake import preview_folder
    _файл(tmp_path, "Тема без даты.mp3")
    _файл(tmp_path, "Очень старая запись.mp3", возраст_дней=200)
    п = preview_folder(tmp_path)
    assert п["first_pass"] == 1, п
    assert п["no_date"] == ["Очень старая запись.mp3"], п
