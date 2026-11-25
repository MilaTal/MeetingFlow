# -*- coding: utf-8 -*-
"""Мусор перед заголовком записи: приёмник сам исправляет рабочую копию (25.11.2026).

Повод: «Новая запись 92.m4a» сутки не принималась. В начале файла стояли два байта `0D 0A` перед боксом `ftyp`:
«Транс» отвечал 400, местный whisper — «Invalid data found when processing input». Файл целый, лечится сдвигом на 2
байта. Здесь держатся три вещи: сдвиг вычисляется по сигнатуре, нормальный файл не трогается, а лечение применяется
только когда сдвинутая копия действительно открывается.
"""
from __future__ import annotations

import wave
from pathlib import Path

from meetflow.core.zvuk_zagolovok import исправить_заголовок, сдвиг_к_заголовку

ГОЛОВА_MP4_С_МУСОРОМ = b"\r\n\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00"


def _wav(путь: Path, секунд: float = 0.5) -> Path:
    with wave.open(str(путь), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * секунд))
    return путь


def test_мусор_перед_mp4_виден_по_сдвигу():
    assert сдвиг_к_заголовку(ГОЛОВА_MP4_С_МУСОРОМ) == (2, "mp4")


def test_нормальный_заголовок_не_трогаем():
    assert сдвиг_к_заголовку(b"\x00\x00\x00\x1cftypM4A ") is None
    assert сдвиг_к_заголовку(b"RIFF\x24\x00\x00\x00WAVEfmt ") is None
    assert сдвиг_к_заголовку(b"ID3\x04\x00") is None


def test_wav_целый_остаётся_как_был(tmp_path):
    путь = _wav(tmp_path / "целый.wav")
    было = путь.read_bytes()
    assert исправить_заголовок(путь) is None
    assert путь.read_bytes() == было


def test_wav_с_мусором_лечится_и_открывается(tmp_path):
    путь = _wav(tmp_path / "мусор.wav")
    путь.write_bytes(b"\r\n" + путь.read_bytes())
    описание = исправить_заголовок(путь)
    assert описание and "2 лишних байт" in описание
    assert путь.read_bytes()[:4] == b"RIFF"
    import av
    c = av.open(str(путь))
    try:
        assert abs(float(c.duration or 0) / 1e6 - 0.5) < 0.05
    finally:
        c.close()


def test_что_не_открывается_после_сдвига_остаётся_целым(tmp_path):
    путь = tmp_path / "не звук.bin"
    было = b"\r\nRIFF" + b"\x00" * 200
    путь.write_bytes(было)
    assert исправить_заголовок(путь) is None
    assert путь.read_bytes() == было


def test_документы_не_трогаем(tmp_path):
    """docx/xlsx — это ZIP: свои правила, лечение заголовка к ним не применяется."""
    путь = tmp_path / "протокол.docx"
    было = b"\r\n\xff\xe0" + b"PK\x03\x04" + b"\x00" * 100
    путь.write_bytes(было)
    assert исправить_заголовок(путь) is None
    assert путь.read_bytes() == было
