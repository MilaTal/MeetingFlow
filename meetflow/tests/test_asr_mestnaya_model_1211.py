# -*- coding: utf-8 -*-
"""Локальная модель распознавания берётся из набора VOICE_MODELS_DIR (12.11.2026).

Повод: встреча 11.11 не распозналась — «Транс» недоступен, а whisper искал кэш Hugging Face и падал
«Cannot find an appropriate cached snapshot folder», хотя папка `whisper-large-v3` лежит в наборе моделей.
"""
from __future__ import annotations

from pathlib import Path

from meetflow.connectors.asr_whisper import WhisperLocalASR


def test_имя_модели_превращается_в_папку_набора(tmp_path, monkeypatch):
    папка = tmp_path / "whisper-large-v3"
    папка.mkdir()
    monkeypatch.setenv("VOICE_MODELS_DIR", str(tmp_path))
    assert WhisperLocalASR()._местная_модель("large-v3") == str(папка)


def test_нет_папки_остаётся_имя(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_MODELS_DIR", str(tmp_path))
    assert WhisperLocalASR()._местная_модель("large-v3") == "large-v3"


def test_потоки_mkl_ограничены():
    """12.11.2026: без ограничения MKL падал «mkl_malloc: failed to allocate memory» при загрузке large-v3."""
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "connectors" / "asr_whisper.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("OMP_NUM_THREADS", "4")' in код
    assert 'os.environ.setdefault("MKL_NUM_THREADS", "4")' in код


def test_оба_загрузчика_используют_местную_модель():
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "connectors" / "asr_whisper.py").read_text(encoding="utf-8")
    assert код.count("self._местная_модель(") >= 2, "и _load, и _load_point"
    assert "длительность {сколько} вне окна темы" in код, "короткая запись называется в секундах"
