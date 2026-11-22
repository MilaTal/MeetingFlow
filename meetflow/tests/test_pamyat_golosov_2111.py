# -*- coding: utf-8 -*-
"""Проверка памяти перед разделением по голосам (21.11.2026).

Повод — `BrokenProcessPool`: при нехватке физической памяти система убивает дочерний процесс pyannote, и сборка
повторяет разбор пять раз, не называя причину. Теперь перед запуском pyannote шаг сразу говорит «мало памяти»
и сохраняет запись. Проверка стоит в `diarize`, чтобы подменённый в тестах разбор не зависел от памяти машины.
"""
from __future__ import annotations

import pytest

from meetflow.core import diarize


def test_мало_памяти_даёт_понятную_ошибку(monkeypatch):
    monkeypatch.setattr(diarize, "free_memory_bytes", lambda: 100 * 1024 * 1024)
    monkeypatch.setenv("VOICE_MIN_FREE_MB", "2500")
    with pytest.raises(diarize.NotEnoughMemory, match="памяти"):
        diarize.проверить_память()


def test_достаточно_памяти_проверка_проходит(monkeypatch):
    monkeypatch.setattr(diarize, "free_memory_bytes", lambda: 8 * 1024 ** 3)
    monkeypatch.setenv("VOICE_MIN_FREE_MB", "2500")
    assert diarize.проверить_память() is None


def test_порог_можно_выключить_нулём(monkeypatch):
    monkeypatch.setattr(diarize, "free_memory_bytes", lambda: 1)
    monkeypatch.setenv("VOICE_MIN_FREE_MB", "0")
    assert diarize.проверить_память() is None
