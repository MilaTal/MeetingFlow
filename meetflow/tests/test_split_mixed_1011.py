# -*- coding: utf-8 -*-
"""Слипшиеся голоса: метка, в которой диаризация смешала разных людей, делится до опознания (10.11.2026).

Живой случай — планёрка 10.11.2026 (встреча 51): в метке «Говорящий 2» оказались 38 окон двух голосов,
внутренняя близость окон 0,395. Центр метки лёг между Майдуровым (0,782) и Попковым (0,764) — отрыв
0,018, правило 0,65 / 0,10 имени не дало. После разделения на две группы: Попков 0,87 (отрыв 0,33) и
Майдуров 0,83 (отрыв 0,30).
"""
import math

from meetflow.core import voice_split as voice_base


def _norm(vector):
    length = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / length for x in vector]


def _base(size=32):
    one = [0.0] * size
    one[0] = 1.0
    two = [0.0] * size
    two[1] = 1.0
    return one, two


def _near(base, salt, size=32):
    """Вектор «того же голоса»: основа плюс небольшой разброс, свой у каждого окна."""
    vector = list(base)
    for i in range(1, size):
        vector[i] = 0.02 * (((i * 7 + salt * 13) % 5) - 2)
    return _norm(vector)


def _sample(speaker, start, vector):
    return {"speaker": speaker, "start": start, "end": start + 5.0, "embedding": vector, "seconds": 5.0}


def test_two_voices_in_one_label_are_split():
    one, two = _base()
    samples = ([_sample("Говорящий 2", i * 10.0, _near(one, i)) for i in range(10)]
               + [_sample("Говорящий 2", 100.0 + i * 10.0, _near(two, i)) for i in range(10)])
    segments = [{"speaker": s["speaker"], "start": s["start"], "end": s["end"]} for s in samples]

    samples, segments, report = voice_base.split_mixed(samples, segments)

    assert len(report) == 1 and report[0]["label"] == "Говорящий 2" and report[0]["groups"] == 2
    labels = {s["speaker"] for s in samples}
    assert labels == {"Говорящий 2-1", "Говорящий 2-2"}
    # Метки сегментов совпадают с метками отпечатков: иначе строки расшифровки потеряют голос.
    assert {(g["start"], g["speaker"]) for g in segments} == {(s["start"], s["speaker"]) for s in samples}
    # Группы действительно разные голоса: центры далеко друг от друга.
    первый = [s["embedding"] for s in samples if s["speaker"] == "Говорящий 2-1"]
    второй = [s["embedding"] for s in samples if s["speaker"] == "Говорящий 2-2"]
    assert len(первый) >= voice_base.MIXED_MIN_CLUSTER and len(второй) >= voice_base.MIXED_MIN_CLUSTER
    центр1 = _norm([sum(v[i] for v in первый) for i in range(len(первый[0]))])
    центр2 = _norm([sum(v[i] for v in второй) for i in range(len(второй[0]))])
    assert voice_base._косинус(центр1, центр2) <= voice_base.MIXED_MAX_CENTER_COS


def test_one_voice_is_not_touched():
    one, _ = _base()
    samples = [_sample("Говорящий 1", i * 10.0, _near(one, i)) for i in range(12)]
    segments = [{"speaker": s["speaker"], "start": s["start"], "end": s["end"]} for s in samples]

    samples, segments, report = voice_base.split_mixed(samples, segments)

    assert report == []
    assert {s["speaker"] for s in samples} == {"Говорящий 1"}
    assert {g["speaker"] for g in segments} == {"Говорящий 1"}


def test_short_label_is_not_split_even_if_mixed():
    """Меньше восьми окон — статистики мало, метка остаётся как есть (правило 10.11.2026)."""
    one, two = _base()
    samples = [_sample("Говорящий 3", 0.0, _near(one, 0)), _sample("Говорящий 3", 10.0, _near(two, 1))]
    segments = [{"speaker": s["speaker"], "start": s["start"], "end": s["end"]} for s in samples]

    samples, segments, report = voice_base.split_mixed(samples, segments)

    assert report == []
    assert {s["speaker"] for s in samples} == {"Говорящий 3"}


def test_variant_with_more_confirmed_names_is_chosen():
    """Вариант деления выбирается по числу разных людей, которых правило имени называет уверенно
    (живой случай 10.11: k=2 — один Попков, k=4 — Ранцан, Майдуров, Попков)."""
    one, two = _base()
    три = [0.0] * 32
    три[2] = 1.0
    samples = ([_sample("Говорящий 2", i * 10.0, _near(one, i)) for i in range(8)]
               + [_sample("Говорящий 2", 100.0 + i * 10.0, _near(two, i)) for i in range(8)]
               + [_sample("Говорящий 2", 200.0 + i * 10.0, _near(три, i)) for i in range(8)])
    segments = [{"speaker": s["speaker"], "start": s["start"], "end": s["end"]} for s in samples]

    def имена(под_samples, _под_segments):
        групп = len({s["speaker"] for s in под_samples})
        return {2: 1, 3: 3, 4: 2}.get(групп, 0)   # «правило имени» называет только при трёх группах

    samples, segments, report = voice_base.split_mixed(samples, segments, подходит=имена)

    assert report and report[0]["groups"] == 3
    assert len({s["speaker"] for s in samples}) == 3
