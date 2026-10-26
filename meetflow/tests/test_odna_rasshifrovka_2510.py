"""Правило 25.10.2026, пункт 4: текстом одна своя расшифровка, выгрузка — только при явно неполной своей.

Страховка: своя пустая или знаков меньше 0,5 от выгрузки — текстом идёт выгрузка; выбор и причина — в итоге сборки.
Покрытие по времени (70 %) в MeetFlow пока не считается: длительность записи не хранится. Тест написан до правки.
"""
from meetflow.core.pipeline import choose_transcript


def _s(name, text, local=False, sid=1):
    return {"id": sid, "name": name, "text": text, "local_asr": 1 if local else 0}


def test_local_transcript_wins_when_complete():
    local = _s("своя", "а" * 1000, local=True)
    other = _s("выгрузка", "б" * 1200, sid=2)
    row, reason = choose_transcript([other, local])
    assert row is local and reason == ""


def test_local_empty_falls_back_to_upload():
    local = _s("своя", "  ", local=True)
    other = _s("выгрузка", "б" * 1200, sid=2)
    row, reason = choose_transcript([local, other])
    assert row is other and "пустая" in reason


def test_local_less_than_half_falls_back():
    local = _s("своя", "а" * 400, local=True)
    other = _s("выгрузка", "б" * 1200, sid=2)
    row, reason = choose_transcript([local, other])
    assert row is other and "неполная" in reason


def test_no_local_uses_single_transcript():
    only = _s("выгрузка", "б" * 1200)
    row, reason = choose_transcript([only])
    assert row is only and "своей" in reason


def test_local_short_by_time_falls_back():
    """Охват по меткам: своя 0:00–0:10 против выгрузки 0:00–1:00 — меньше 70 %, текстом выгрузка."""
    local = _s("своя", "[00:00] раз [00:10] два " + "а" * 1000, local=True)
    other = _s("выгрузка", "[00:00] раз [01:00] два " + "б" * 1200, sid=2)
    row, reason = choose_transcript([local, other])
    assert row is other and "времени" in reason


def test_local_full_by_time_wins():
    local = _s("своя", "[00:00] раз [00:55] два " + "а" * 1000, local=True)
    other = _s("выгрузка", "[00:00] раз [01:00] два " + "б" * 1200, sid=2)
    row, reason = choose_transcript([local, other])
    assert row is local and reason == ""


def test_no_timestamps_uses_half_length_only():
    local = _s("своя", "а" * 1000, local=True)
    other = _s("выгрузка", "б" * 1200, sid=2)
    row, reason = choose_transcript([local, other])
    assert row is local and reason == ""
