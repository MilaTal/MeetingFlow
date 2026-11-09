# -*- coding: utf-8 -*-
"""Запись не удаляется, если не разобрались голоса (09.11.2026).

Повод: у встречи 9 шаг голосов упал `BrokenProcessPool`, расшифровка сохранилась, а запись удалили — повтор и разбор
причины стали невозможны без новой отправки файла. Правило: удаляем только после чистого прохода голосов.
"""
from pathlib import Path

from meetflow.core.pipeline import можно_удалить_запись

СТАТИКА = Path(__file__).resolve().parents[1]


def test_при_сбое_голосов_запись_остаётся():
    assert not можно_удалить_запись({"media_path": r"P:\запись.m4a", "voice_retry": True,
                                     "voice_error": "BrokenProcessPool: процесс прерван"})


def test_когда_повтор_не_поможет_запись_удаляется():
    """«Нет времён реплик» или «нет модели» — повтор бессмысленен, запись не храним (как раньше)."""
    assert можно_удалить_запись({"media_path": r"P:\запись.m4a", "voice_retry": False,
                                 "voice_error": "точка распознавания не вернула времена реплик"})


def test_по_пометке_keep_media_остаётся():
    assert not можно_удалить_запись({"media_path": r"P:\запись.m4a", "keep_media": True})


def test_после_чистого_прохода_удаляется():
    assert можно_удалить_запись({"media_path": r"P:\запись.m4a"})
    assert not можно_удалить_запись({})


def test_есть_проверка_голосов_отдельным_скриптом():
    """Диагностика без сервера: скрипт готовит звук как сборка и гоняет pyannote с faulthandler."""
    скрипт = (СТАТИКА / "scripts" / "proverka_golosov.py").read_text(encoding="utf-8")
    assert "faulthandler.enable()" in скрипт
    assert "_diarize_here" in скрипт and "--в-отдельном" in скрипт
