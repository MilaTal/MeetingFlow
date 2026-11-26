# -*- coding: utf-8 -*-
"""Паритет правила времени разбора по голосам в MeetFlow (26.11.2026, слово владелицы).
MF выровнен под Планёрку/ERP: 4,5 длины + 20 мин, не меньше 30 мин (вместо фиксированных 4500 с).
Зеркально transcribe_queue.предел_голосов (ПЛ) и recording_queue.предел_голосов (ERP).
"""
from __future__ import annotations

import pytest

from meetflow.core import diarize


@pytest.mark.parametrize("сек,ожид", [
    (0, 1800),
    (None, 1800),
    (100, 1800),
    (600, 3900),
    (3600, 17400),
    (3900, 18750),
])
def test_формула_предела_голосов(сек, ожид):
    assert diarize.предел_голосов(сек) == ожид


def test_не_фиксированные_4500():
    assert diarize.предел_голосов(3600) > 4500
    assert diarize.предел_голосов(60) >= 1800


def test_монотонность():
    значения = [diarize.предел_голосов(s) for s in (0, 600, 1800, 3600, 7200)]
    assert значения == sorted(значения)