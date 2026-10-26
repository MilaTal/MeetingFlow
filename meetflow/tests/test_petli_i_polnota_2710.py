# -*- coding: utf-8 -*-
"""Петли распознавания и полнота расшифровки (перенос из ERP 27.10.2026; DECISIONS ERP 26.10.2026 «Транс: … петли
распознавания» и «неполная расшифровка, тема по факту …»).

Модули-близнецы `petlya_raspoznavaniya` и `polnota_rasshifrovki` — чистая часть как в ERP main 2ea59c1. Петли чистятся
сразу после распознавания, до голосов и до сохранения: два повтора остаются, строки и времена сегментов на месте,
число петель — в журнал распознавания, доля убранного больше 1 % — одна карточка «Система». Полнота: последняя метка
против длительности записи, меньше 80 % — карточка, снова полная — карточка закрывается сама; строка — в итог сборки.
"""
import json
from pathlib import Path

import pytest

from meetflow.connectors.base import ASRConnector
from meetflow.core import petlya_raspoznavaniya as petlya
from meetflow.core import polnota_rasshifrovki as polnota
from meetflow.core.types import SourceDoc, SourceKind

ПЕТЛЯ = "Не, " + "не, " * 300 + "давайте дальше."


# --- модуль петель --------------------------------------------------------------------------------------------------

def test_петля_15_повторов_убирается_два_остаются():
    текст, итог = petlya.очистить("00:00:05\t" + ПЕТЛЯ)
    assert итог["петель"] == 1 and итог["убрано_слов"] == 299
    assert текст == "00:00:05\tНе, не, давайте дальше."


def test_14_повторов_и_живые_повторы_не_трогаются():
    живое = "00:00:01\t" + "да, " * 14 + "хорошо\n00:00:09\tпо, по, по, по, по договору"
    текст, итог = petlya.очистить(живое)
    assert текст == живое and итог["петель"] == 0


def test_ё_равно_е_и_метка_не_слово():
    текст, итог = petlya.очистить("[00:10] " + "всё, " * 8 + "все, " * 8 + "конец")
    assert итог["петель"] == 1 and текст == "[00:10] всё, всё, конец"


def test_строки_сегментов_чистятся_так_же():
    _, итог = petlya.очистить(ПЕТЛЯ)
    meta = petlya.очистить_сводку({"segment_lines": [ПЕТЛЯ, "вторая"], "segment_times": [[0, 1], [2, 3]]}, итог)
    assert meta["segment_lines"] == ["Не, не, давайте дальше.", "вторая"]
    assert meta["segment_times"] == [[0, 1], [2, 3]] and meta["asr_loops"]["петель"] == 1


# --- модуль полноты -------------------------------------------------------------------------------------------------

def test_полнота_по_записи():
    мера = polnota.по_записи("00:00:01\tа\n00:15:27\tб", 3600)
    assert мера["неполная"] and мера["распознано_сек"] == 927
    assert "распознано только 15 мин из 60" in polnota.строка_итога(мера)
    assert not polnota.по_записи("00:00:01\tа\n00:59:50\tб", 3600)["неполная"]
    assert polnota.по_записи("без меток", 3600) is None and polnota.по_записи("00:01\tа", None) is None


# --- конвейер ----------------------------------------------------------------------------------------------------------

class _ASR(ASRConnector):
    name = "fake-asr"

    def __init__(self, text: str, seconds: int):
        self.text, self.seconds = text, seconds

    def transcribe(self, path: Path) -> SourceDoc:
        lines = self.text.splitlines()
        return SourceDoc(path.name, SourceKind.TRANSCRIPT, self.text,
                         {"media_seconds": self.seconds, "segment_lines": [ln.split("\t", 1)[-1] for ln in lines],
                          "segment_times": [[i * 10.0, i * 10.0 + 5] for i in range(len(lines))], "keep_media": True})


@pytest.fixture
def pipe(make_pipe, tmp_path, monkeypatch):
    p = make_pipe()
    p.asr_journal_path = tmp_path / "asr_journal.jsonl"
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)    # голоса не разбираются: звук поддельный, шаг пишет причину
    return p


def _ingest(pipe, project, meeting, text, seconds, tmp_path, monkeypatch):
    f = tmp_path / "rec 01.10.2026.wav"
    f.write_bytes(b"RIFF")
    monkeypatch.setattr(pipe.plugins, "resolve_source", lambda name: _ASR(text, seconds))
    return pipe.ingest(project, meeting, f.name, path=f)


def test_петля_чистится_до_сохранения_карточка_и_журнал(pipe, project, meeting, store, tmp_path, monkeypatch):
    текст = "00:00:01\tНачинаем.\n00:00:20\t" + ПЕТЛЯ + "\n00:58:00\tВсем спасибо."
    r = _ingest(pipe, project, meeting, текст, 3600, tmp_path, monkeypatch)
    src = store.get("sources", r["source_id"])
    assert "не, " * 3 not in src["text"].lower() and src["text"].count("\n") == 2
    meta = json.loads(src["meta"])
    assert meta["asr_loops"]["петель"] == 1 and len(meta["segment_lines"]) == 3
    cards = store.q("SELECT * FROM cards WHERE kind='transcript_loop' AND status='open'")
    assert len(cards) == 1 and "переслушать" in json.loads(cards[0]["payload"])["text"]
    row = json.loads(pipe.asr_journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["loops"] == 1 and "петли распознавания: 1" in row["loops_line"]


def test_без_петель_карточки_нет(pipe, project, meeting, store, tmp_path, monkeypatch):
    _ingest(pipe, project, meeting, "00:00:01\tНачинаем.\n00:58:00\tВсем спасибо.", 3600, tmp_path, monkeypatch)
    assert not store.q("SELECT id FROM cards WHERE kind='transcript_loop'")


def test_неполная_расшифровка_карточка_при_сборке_и_закрытие(pipe, project, meeting, store, tmp_path, monkeypatch):
    r = _ingest(pipe, project, meeting, "00:00:01\tНачинаем.\n00:15:27\tДальше обрыв.", 3600, tmp_path, monkeypatch)
    rep = pipe.run(project, meeting)
    assert "распознано только 15 мин из 60" in rep.completeness
    open_ = store.q("SELECT * FROM cards WHERE kind='transcript_incomplete' AND status='open'")
    assert len(open_) == 1 and "распознано только 15 мин из 60" in json.loads(open_[0]["payload"])["text"]
    assert "распознано только" not in (store.get("meetings", meeting)["protocol_md"] or "")
    # перераспознали — полная: карточка закрывается сама
    store.update("sources", r["source_id"], removed_at="2026-10-27T10:00:00")
    _ingest(pipe, project, meeting, "00:00:01\tНачинаем.\n00:59:30\tВсем спасибо.", 3600, tmp_path, monkeypatch)
    pipe.run(project, meeting)
    assert not store.q("SELECT id FROM cards WHERE kind='transcript_incomplete' AND status='open'")
