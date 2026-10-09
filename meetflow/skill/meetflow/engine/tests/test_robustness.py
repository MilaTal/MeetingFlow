"""Итерация 3, устойчивость и нагрузка: битые и пустые данные, превышение контекста, одновременная запись, поток встреч."""

import os
import threading
import time

import pytest

from meeting_registry import intake, negation, pipeline
from meeting_registry.control import Limits
from meeting_registry.errors import SourceRejected
from meeting_registry.llm import ScriptedClient
from meeting_registry.registry import Registry


@pytest.mark.parametrize("phrase,fact", [
    ("Экономику проекта посчитали.", "done"),            # находка 03.10.26: глагола не было в списке
    ("Назаров сказал, что подумает.", None),             # глагол речи — не работа
    ("Игнатов пообещал отправить завтра.", None),
])
def test_done_by_morphology(phrase, fact):
    assert negation.classify(phrase)["fact"] == fact


def test_empty_and_garbage_rejected_before_meeting_created(run, reg):
    for bad in ["", "   ", "\x00\x00\x00", "ааа ааа ааа ааа ааа ааа ааа ааа"]:
        res = run(bad)
        assert res["outcome"] == "rejected"
    assert reg.all_tasks() == []
    assert reg._conn().execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 0   # пустых встреч не осталось


def test_broken_files(tmp_path):
    p = tmp_path / "битый.docx"
    p.write_bytes(b"PK\x03\x04 not really a docx")
    with pytest.raises(SourceRejected):
        intake.read_file(str(p))
    b = tmp_path / "двоичный.txt"
    b.write_bytes(os.urandom(2000).replace(b"\x00", b"\x01") + b"\x00" * 500)
    with pytest.raises(SourceRejected):
        intake.read_file(str(b))


def test_context_overflow_stops_before_any_call(run, reg):
    """Встреча на ~15 кусков при потолке 10: остановка до первого вызова модели, карточка человеку."""
    long = "\n".join(f"Гаврилов Павел: По пункту {i} обсудили поставку материалов и сроки работ по объекту." for i in range(1, 2200))
    client = ScriptedClient({})
    res = run(long, client=client, limits=Limits())
    assert res["outcome"] == "stopped_by_limit" and "кусков" in res["limit"]
    assert client.calls == []
    assert any(c["kind"] == "limit" for c in reg.open_cards())


def test_single_call_size_ceiling(run, reg):
    text = "Гаврилов Павел: Назаров, подготовьте отчёт по проекту до пятницы.\n" * 50
    res = run(text, client=ScriptedClient({}), limits=Limits(max_chars_per_call=500))
    assert res["outcome"] == "stopped_by_limit" and "знаков" in res["limit"]


def test_concurrent_writes_lose_nothing(tmp_path, team):
    """Восемь потоков пишут восемь разных встреч в один реестр. Замок на данных: ни одна задача не теряется."""
    reg = Registry(str(tmp_path / "r.db"))
    errors = []

    def worker(i):
        try:
            text = f"Гаврилов Павел: Назаров, подготовьте отчёт номер {i} по объекту {i}.\n"
            r = pipeline.process(text, f"m{i}.txt", f"2026-10-{i + 1:02d}", reg, team)
            assert r["outcome"] == "done", r
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(reg.all_tasks()) == 8


def test_same_meeting_twice_concurrently_no_duplicates(tmp_path, team):
    reg = Registry(str(tmp_path / "r.db"))
    text = "Гаврилов Павел: Назаров, подготовьте отчёт по фильтрам.\n"
    threads = [threading.Thread(target=pipeline.process, args=(text, "m.txt", "2026-10-02", reg, team)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(reg.all_tasks()) == 1
    assert reg._conn().execute("SELECT COUNT(*) FROM meetings").fetchone()[0] == 1


def test_highload_stream_of_meetings(tmp_path, team):
    """Поток 100 встреч подряд: время на встречу и рост реестра. Число записывается в отчёт как замер."""
    reg = Registry(str(tmp_path / "r.db"))
    t0 = time.monotonic()
    for i in range(100):
        text = (f"Гаврилов Павел: Назаров, подготовьте отчёт по объекту {i} до пятницы.\n"
                f"Гаврилов Павел: Ершова, запросите счёт по объекту {i}.\n"
                f"Илюшин Антон: Я обновлю график по объекту {i} к понедельнику.\n")
        r = pipeline.process(text, f"m{i}.txt", "2026-10-02", reg, team)
        assert r["outcome"] == "done"
    per = (time.monotonic() - t0) / 100
    assert len(reg.all_tasks()) == 300
    assert per < 2.0, f"{per:.3f} с на встречу"


def test_encoding_mojibake_and_bidi_survive(run, reg):
    text = "Гаврилов Павел: Назаров,‮ подготовьте​ спецификацию﻿ на фильтры.\n"
    res = run(text)
    assert res["outcome"] == "done"
    assert reg.all_tasks()[0]["description"] == "Подготовить спецификацию на фильтры"


def test_parse_json_tolerates_raw_tab_in_quote():
    """Находка полного прогона ERP 03.10.26: модель копирует в цитату строку записи «00:00:00<TAB>Имя» с сырой
    табуляцией, строгий разбор падает «Invalid control character» на двух встречах из двадцати."""
    from meeting_registry.llm import parse_json
    raw = '{"tasks": [{"quote": "00:00:10' + chr(9) + 'Гаврилов Павел: подготовьте график"}]}'
    assert parse_json(raw)["tasks"][0]["quote"].endswith("подготовьте график")
