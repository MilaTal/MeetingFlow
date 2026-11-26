# -*- coding: utf-8 -*-
"""Повтор разбора по голосам не должен сам падать (26.11.2026).

Живой случай: запись hJ3EQiBK получила «сбой: NameError: name 'logger' is not defined» — в обработчике повтора
стоял logger.warning без объявления, поэтому первая же неудача шага голосов убивала весь повтор и настоящая
причина терялась. Здесь: первая попытка падает, вторая успешна — разбор должен дойти до конца без voice_error.
"""
from __future__ import annotations

from pathlib import Path

from meetflow.core import pipeline as pl
from meetflow.core.types import SourceDoc, SourceKind


def test_повтор_голосов_не_падает_на_логировании(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    pipe = make_pipe()
    wav = tmp_path / "запись.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 64)
    doc = SourceDoc("запись.wav", SourceKind.TRANSCRIPT, "[00:00:01] текст", {
        "segment_lines": ["текст"], "segment_times": [[1.0, 2.0]], "media_seconds": 2,
    })
    вызовы = {"n": 0}

    def процесс(wav_path, text, meta, **kw):
        вызовы["n"] += 1
        if вызовы["n"] == 1:
            raise RuntimeError("BrokenProcessPool")
        return {"text": text, "speakers": 1, "signed_lines": 0, "names": {}, "base": {},
                "contribution": {}, "clips": [], "diarization": {"seconds": 1, "device": "cpu"}, "notes": []}

    monkeypatch.setattr(pl.voice_step, "process", процесс)
    pipe._voice_step(project, meeting, wav, doc, "запись.wav")
    assert вызовы["n"] == 2, вызовы                      # повтор состоялся, а не умер на логировании
    assert not doc.meta.get("voice_error"), doc.meta.get("voice_error")
