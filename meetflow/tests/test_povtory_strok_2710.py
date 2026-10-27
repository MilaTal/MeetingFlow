# -*- coding: utf-8 -*-
"""Подряд одинаковые строки распознавания — сворачивать (решение владелицы 27.10.2026).

MeetFlow (перенос 27.10.2026): тесты близнеца ERP main 595036d6 `webapp/tests/test_povtory_strok_2710.py` на модуле
MeetFlow `meetflow.core.petlya_raspoznavaniya` и проход очереди — `Pipeline.ingest`. Моделей тесты не вызывают. Модуль петель
ловил повтор только внутри строки, а вторая разновидность галлюцинации Whisper — серия одинаковых сегментов подряд:
21 строка «Сколько?». До правки такие серии оставались в расшифровке целиком. Правило: 3 и больше подряд строк с одним
нормализованным текстом и одним говорящим → первая, время — от первой до конца последней; две подряд не трогаются.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from meetflow.connectors.base import ASRConnector
from meetflow.core import petlya_raspoznavaniya as пр
from meetflow.core.types import SourceDoc, SourceKind

П = chr(10)
Т = chr(9)
СКОЛЬКО_21 = [f"00:00:{i + 2:02d}{Т}Сколько?" for i in range(21)]


def test_21_раз_сколько_одна_строка():
    текст = П.join([f"00:00:01{Т}Добрый день."] + СКОЛЬКО_21 + [f"00:01:00{Т}Идём дальше."])
    чистый, итог = пр.очистить(текст)
    assert чистый.split(П) == [f"00:00:01{Т}Добрый день.", f"00:00:02{Т}Сколько?", f"00:01:00{Т}Идём дальше."]
    assert итог["свёрнуто_строк"] == 20 and итог["серий_строк"] == 1 and итог["петель"] == 0
    assert итог["серии"][0]["строка"] == 2 and итог["серии"][0]["строк"] == 21 and итог["метки"] == ["00:00:02"]


def test_две_одинаковые_подряд_не_трогаются():
    текст = П.join([f"00:00:01{Т}Да.", f"00:00:02{Т}Да.", f"00:00:03{Т}Поехали."])
    чистый, итог = пр.очистить(текст)
    assert чистый == текст and итог["свёрнуто_строк"] == 0 and not пр.есть_находки(итог)
    assert пр.строка_итога(итог) == ""


def test_разные_говорящие_не_сворачиваются():
    строки = [f"00:00:01{Т}Говорящий 1: Сколько?", f"00:00:02{Т}Говорящий 2: Сколько?",
              f"00:00:03{Т}Говорящий 1: Сколько?"]
    чистый, итог = пр.очистить(П.join(строки))
    assert чистый.split(П) == строки and итог["свёрнуто_строк"] == 0
    # один говорящий — сворачивается; метка у одних и без метки у других — не один говорящий
    один = [с.replace("Говорящий 2", "Говорящий 1") for с in строки]
    assert пр.очистить(П.join(один))[0].split(П) == [один[0]]
    смесь = [f"00:00:01{Т}Сколько?", f"00:00:02{Т}Говорящий 1: Сколько?", f"00:00:03{Т}Сколько?"]
    assert пр.очистить(П.join(смесь))[1]["свёрнуто_строк"] == 0


def test_нормализация_регистр_знаки_ё_и_пустая_строка_прерывает():
    строки = [f"00:00:01{Т}Ещё раз.", f"00:00:02{Т}еще раз", f"00:00:03{Т}ЕЩЁ, РАЗ!"]
    assert пр.очистить(П.join(строки))[0].split(П) == [строки[0]]
    с_пустой = [f"00:00:01{Т}Вот.", f"00:00:02{Т}Вот.", "", f"00:00:03{Т}Вот."]
    assert пр.очистить(П.join(с_пустой))[1]["свёрнуто_строк"] == 0


def test_сводка_строки_сегментов_и_время_от_первой_до_конца_последней():
    строки = [f"00:00:01{Т}Добрый день."] + СКОЛЬКО_21
    времена = [[1.0, 1.8]] + [[2.0 + i, 2.6 + i] for i in range(21)]
    чистый, итог = пр.очистить(П.join(строки))
    meta = пр.очистить_сводку({"segment_lines": строки, "segment_times": времена, "lines": 22}, итог)
    assert П.join(meta["segment_lines"]) == чистый
    assert meta["segment_times"] == [[1.0, 1.8], [2.0, 22.6]] and meta["lines"] == 2
    assert meta["asr_loops"]["свёрнуто_строк"] == 20 and meta["asr_loops"]["петель"] == 0
    # времена не той длины — не трогаются, строки сворачиваются
    meta = пр.очистить_сводку({"segment_lines": строки, "segment_times": [[0, 1]]}, итог)
    assert meta["segment_times"] == [[0, 1]] and len(meta["segment_lines"]) == 2


def test_доля_карточки_и_строка_итога_вместе_с_петлями():
    длинная = [f"00:{м // 4:02d}:{м % 4 * 15:02d}{Т}обычная реплика номер {м} про сроки и задачи" for м in range(200)]
    _, итог = пр.очистить(П.join(длинная + [f"01:00:00{Т}Вот."] * 3))
    assert итог["свёрнуто_строк"] == 2 and итог["доля"] < пр.ДОЛЯ_КАРТОЧКИ and not пр.нужна_карточка(итог)
    петля = f"00:12:30{Т}Ну и вот. " + "Не, " * 300 + "не."
    _, итог = пр.очистить(П.join([петля] + СКОЛЬКО_21))
    assert итог["петель"] == 1 and итог["свёрнуто_строк"] == 20 and пр.нужна_карточка(итог)
    assert итог["доля"] == round((итог["убрано_слов"] + итог["убрано_слов_строк"]) / итог["слов_всего"], 4)
    строка = пр.строка_итога(итог)
    assert "петли распознавания: 1" in строка and "подряд одинаковых строк свёрнуто 20 (серий 1)" in строка
    карточка = пр.текст_карточки("Встреча 07.07.2026", итог)
    assert "одна и та же строка шла подряд 3 и больше раз" in карточка and "переслушать запись" in карточка


def test_прибор_без_повторов_текст_тот_же():
    """Прибор: обычная расшифровка не меняется ни на знак — значит, свёрнутое выше видит именно серии."""
    текст = П.join(f"00:00:{i:02d}{Т}реплика {i}" for i in range(30))
    чистый, итог = пр.очистить(текст)
    assert чистый == текст and итог["свёрнуто_строк"] == 0 and итог["серии"] == []


# --- проход очереди MeetFlow: распознавание → свёртка → журнал распознавания и карточка -------------------------------

class _ASR(ASRConnector):
    name = "fake-asr"

    def __init__(self, text: str, seconds: int):
        self.text, self.seconds = text, seconds

    def transcribe(self, path: Path) -> SourceDoc:
        lines = self.text.splitlines()
        return SourceDoc(path.name, SourceKind.TRANSCRIPT, self.text,
                         {"media_seconds": self.seconds, "segment_lines": [ln.split(Т, 1)[-1] for ln in lines],
                          "segment_times": [[i * 10.0, i * 10.0 + 5] for i in range(len(lines))], "keep_media": True})


@pytest.fixture
def pipe(make_pipe, tmp_path, monkeypatch):
    p = make_pipe()
    p.asr_journal_path = tmp_path / "asr_journal.jsonl"
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)
    return p


def test_очередь_сворачивает_серию_число_в_журнал_и_карточку(pipe, project, meeting, store, tmp_path, monkeypatch):
    f = tmp_path / "rec 01.10.2026.wav"
    f.write_bytes(b"RIFF")
    текст = П.join([f"00:00:01{Т}Добрый день."] + СКОЛЬКО_21 + [f"00:01:00{Т}Идём дальше."])
    monkeypatch.setattr(pipe.plugins, "resolve_source", lambda name: _ASR(текст, 70))
    r = pipe.ingest(project, meeting, f.name, path=f)
    src = store.get("sources", r["source_id"])
    assert src["text"].split(П) == [f"00:00:01{Т}Добрый день.", f"00:00:02{Т}Сколько?", f"00:01:00{Т}Идём дальше."]
    meta = json.loads(src["meta"])
    assert len(meta["segment_lines"]) == 3 and meta["segment_times"][1] == [10.0, 215.0]
    assert meta["asr_loops"]["свёрнуто_строк"] == 20 and meta["asr_loops"]["петель"] == 0
    row = json.loads(pipe.asr_journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["collapsed_lines"] == 20 and row["line_series"] == 1 and row["loops"] == 0
    assert "подряд одинаковых строк свёрнуто 20 (серий 1)" in row["loops_line"]
    # 20 слов из 24 убрано — доля выше 1 %: карточка «Петля распознавания» по свёрнутым строкам
    cards = store.q("SELECT * FROM cards WHERE kind='transcript_loop' AND status='open'")
    assert len(cards) == 1
    данные = json.loads(cards[0]["payload"])
    assert "одна и та же строка шла подряд 3 и больше раз" in данные["text"] and "серии" not in данные


def test_очередь_две_одинаковые_журнал_без_свёртки(pipe, project, meeting, store, tmp_path, monkeypatch):
    f = tmp_path / "rec 01.10.2026.wav"
    f.write_bytes(b"RIFF")
    текст = П.join([f"00:00:01{Т}Да.", f"00:00:02{Т}Да.", f"00:00:03{Т}Поехали."])
    monkeypatch.setattr(pipe.plugins, "resolve_source", lambda name: _ASR(текст, 5))
    r = pipe.ingest(project, meeting, f.name, path=f)
    assert store.get("sources", r["source_id"])["text"] == текст
    row = json.loads(pipe.asr_journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert "collapsed_lines" not in row and "loops" not in row
    assert not store.q("SELECT id FROM cards WHERE kind='transcript_loop'")
