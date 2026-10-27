# -*- coding: utf-8 -*-
"""Путь базы — от папки программы, а не от папки запуска (27.10.2026: на 8005 пропали проекты и встречи)."""
import os
from pathlib import Path

from meetflow.web.app import ПАПКА_ПРОГРАММЫ, путь_данных


def test_относительный_путь_от_папки_программы(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # запуск из чужой папки
    assert Path(путь_данных("data/meetflow.db")) == ПАПКА_ПРОГРАММЫ / "data" / "meetflow.db"
    assert (ПАПКА_ПРОГРАММЫ / "pyproject.toml").exists()


def test_абсолютный_путь_как_есть(tmp_path):
    p = str(tmp_path / "x.db")
    assert путь_данных(p) == p
