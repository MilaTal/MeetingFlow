# -*- coding: utf-8 -*-
"""Whisper не обязателен (слово владелицы 19.11.2026).

Было: проверялся только пакет faster-whisper. Пакет стоит, а папки модели нет — точка «есть» по проверке, но
распознавание падает, а контрольная расшифровка оставляет карточку-вопрос. Стало: готовность — пакет и модель
на диске; нет модели — шаг молча пропускается, сборка идёт по основной расшифровке.
"""
from pathlib import Path

from meetflow.connectors import asr_whisper as aw


def test_model_ready_по_папке_модели(monkeypatch, tmp_path):
    from meetflow.core import local_models

    monkeypatch.setattr(local_models, "whisper_dir", lambda name=None: tmp_path / "whisper-large-v3")
    w = aw.WhisperLocalASR()
    assert w.model_ready() is False          # папки нет — модели нет
    (tmp_path / "whisper-large-v3").mkdir()
    assert w.model_ready() is True


def test_здоровье_говорит_про_модель(monkeypatch, tmp_path):
    from meetflow.core import local_models

    monkeypatch.setattr(local_models, "whisper_dir", lambda name=None: tmp_path / "нет")
    monkeypatch.setattr(aw.WhisperLocalASR, "available", lambda self: True)
    h = aw.WhisperLocalASR().health()
    assert h["ok"] is False and "модели" in h["detail"]


def test_проверка_точки_не_обещает_модель_из_кэша(monkeypatch):
    monkeypatch.setattr(aw.WhisperLocalASR, "available", lambda self: True)
    monkeypatch.setattr(aw.WhisperLocalASR, "model_ready", lambda self, model=None: False)
    ok, почему = aw.asr_ping({"kind": "faster-whisper", "model": "large-v3"})
    assert ok is False and "нет в наборе моделей" in почему


def test_явный_путь_модели_проверяется_как_путь(tmp_path):
    ep = {"kind": "faster-whisper", "model": str(Path(tmp_path) / "нет-такой")}
    ok, почему = aw.asr_ping(ep)
    if aw.WhisperLocalASR().available():          # на машине без пакета проверка отвечает про пакет
        assert ok is False and "папки модели нет" in почему
