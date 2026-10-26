# -*- coding: utf-8 -*-
"""Голоса в MeetFlow: времена реплик, разделение, правило 0,65/0,10, шаг после распознавания."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from meetflow.core import asr_journal, diarize, voice_rule, voice_step
from meetflow.core.store import Store


def _unit(*values):
    import math
    n = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / n for v in values]


def test_voice_rule_confirmed_and_hint():
    centry = {"Иванов Иван": _unit(1, 0), "Петров Пётр": _unit(0, 1)}
    confirmed = voice_rule.reshit(_unit(0.95, 0.05), centry, 0.65, 0.10, 0.55)
    assert confirmed["status"] == voice_rule.CONFIRMED and confirmed["name"] == "Иванов Иван"
    assert confirmed["gap"] >= 0.10
    hint = voice_rule.reshit(_unit(0.6, 0.8), centry, 0.65, 0.10, 0.55)
    assert hint["status"] in (voice_rule.HINT, voice_rule.CONFIRMED)
    assert hint["name"] == "Петров Пётр"


def test_diarize_label_lines_puts_name_or_number():
    times = [(0.0, 3.0), (4.0, 6.0), (10.0, 12.0)]
    segments = [{"start": 0, "end": 3.5, "speaker": "Говорящий 1"},
                {"start": 3.8, "end": 6.2, "speaker": "Говорящий 2"}]
    lines = ["00:00:00\tраз", "00:00:04\tдва", "00:00:20\tтри"]
    out, signed = diarize.label_lines(lines, times, segments, names={"Говорящий 1": "Иванов Иван"})
    assert signed == 2
    assert out[0] == "00:00:00\tИванов Иван\tраз"
    assert out[1] == "00:00:04\tГоворящий 2: два"
    assert out[2] == "00:00:20\tтри"          # без пересечения и ближе 1,5 с никого — метки нет


def test_asr_service_keeps_segment_times(monkeypatch):
    from meetflow.connectors import asr_service

    class Route:
        name = "Транс"
        url = "http://192.168.100.224:8021/transcribe"
        def opt(self, key, default=None):
            return {"form": "multipart", "timeout_sec": 5}.get(key, default)

    payload = {"text": "сплошной", "segments": [
        {"start": 1.5, "end": 4.25, "text": "первая"},
        {"start": 5.0, "end": 7.5, "text": "вторая"},
    ], "duration": 8}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(asr_service.urllib.request, "urlopen", lambda *a, **k: Resp())
    text, meta = asr_service.call(Route(), Path(__file__))   # файл-заглушка: тело запроса не важно
    assert text.splitlines()[0].endswith("первая")
    assert meta["segment_lines"] == ["первая", "вторая"]
    assert meta["segment_times"] == [[1.5, 4.25], [5.0, 7.5]]
    assert meta["segments"] == 2


def test_voice_step_labels_by_base(monkeypatch, tmp_path):
    import soundfile as sf
    wav = tmp_path / "rec.wav"
    sf.write(str(wav), [0.0] * 16000, 16000)     # секунда тишины: шагу нужен читаемый звук
    meta = {"segment_lines": ["раз", "два"], "segment_times": [[0.0, 12.0], [13.0, 15.0]]}
    segments = [{"start": 0, "end": 12.0, "speaker": "Говорящий 1"},
                {"start": 12.5, "end": 15.0, "speaker": "Говорящий 2"}]

    monkeypatch.setattr(diarize, "enabled", lambda: True)
    monkeypatch.setattr(diarize, "available", lambda: (True, ""))
    monkeypatch.setattr(diarize, "diarize", lambda p: (segments, {"speakers": 2, "elapsed_seconds": 1, "device": "процессор"}))
    monkeypatch.setattr(voice_step.voice_contrib, "embed_segments",
                        lambda p, segs: [{**s, "embedding": _unit(1, 0) if s["speaker"] == "Говорящий 1" else _unit(0, 1)}
                                         for s in segs])
    monkeypatch.setattr(voice_rule, "etalony", lambda base: ({"Иванов Иван": _unit(1, 0)}, {"lyudey": 1, "otpechatkov": 3}))
    monkeypatch.setattr(voice_rule, "zapisat", lambda *a, **k: Path(tmp_path / "voice.json"))
    monkeypatch.setattr(voice_step.voice_contrib, "contribute", lambda *a, **k: {"samples": 2, "hinted": 0})
    monkeypatch.setattr(voice_step.voice_review, "vyrezat_otryvki", lambda *a, **k: 0)
    monkeypatch.setattr(voice_step.voice_review, "zapisat_repliki", lambda *a, **k: 0)

    result = voice_step.process(str(wav), "старый текст", meta, meeting_id=1, meeting_date="2026-10-15",
                                base_path=tmp_path / "voices.db", team=["Иванов Иван"])
    assert result["speakers"] == 2 and result["signed_lines"] == 2
    assert "Иванов Иван: раз" in result["text"]
    assert "Говорящий 2: два" in result["text"]
    assert result["text"].startswith("[00:00:00]")
    assert result["contribution"]["samples"] == 2


def test_voice_step_without_times_says_why(monkeypatch, tmp_path):
    import soundfile as sf
    wav = tmp_path / "rec.wav"
    sf.write(str(wav), [0.0] * 16000, 16000)
    monkeypatch.setattr(diarize, "enabled", lambda: True)
    monkeypatch.setattr(diarize, "available", lambda: (True, ""))
    with pytest.raises(voice_step.VoiceStepError, match="нет времён"):
        voice_step.process(str(wav), "текст", {"segment_lines": ["раз"]}, meeting_id=1, meeting_date="2026-10-15")


def test_asr_journal_roundtrip(tmp_path):
    path = tmp_path / "asr_journal.jsonl"
    asr_journal.write(path, meeting_id=7, route="Транс", segments=3, speakers=2)
    asr_journal.write(path, meeting_id=8, route="whisper")
    assert asr_journal.last_for_meeting(path, 7)["route"] == "Транс"
    assert asr_journal.last_for_meeting(path, 8)["route"] == "whisper"
    assert asr_journal.last_for_meeting(path, 9) == {}


def test_sources_have_meta_column(tmp_path):
    store = Store(tmp_path / "app.db")
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(sources)")}
    assert "meta" in cols
