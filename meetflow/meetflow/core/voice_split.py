# -*- coding: utf-8 -*-
"""Слипшиеся метки говорящих: разделить до опознания (10.11.2026).

Общий модуль ERP и MeetFlow, файл-близнец. Повод — планёрка 10.11.2026: диаризация собрала 38 окон
разных людей в одну метку «Говорящий 2» (внутренняя близость окон по медиане 0,395 при 0,71 у одного
голоса). Центр такой метки лёг между Майдуровым, Попковым и Ранцаном — правило 0,65 / 0,10 имени не
дало. После деления на четыре группы правило уверенно назвало трёх человек.

Правило: если в метке много окон, а окна между собой не похожи — это не один голос, а несколько.
Делим такую метку на подгруппы и только потом опознаём; однородные метки не трогаем.

Вариант деления, если передана проверка `подходит`, выбирается по числу РАЗНЫХ уверенно названных
людей: у похожих голосов центры подгрупп близки, и «геометрический» порог тут врёт.
"""
from __future__ import annotations

import math

MIXED_COHERENCE = 0.5        # медиана близости окон ниже — метка считается слипшейся
MIXED_MIN_WINDOWS = 8        # меньше окон — статистики не хватает, не трогаем
MIXED_MAX_K = 4              # больше четырёх голосов в одной метке не делим
MIXED_MIN_CLUSTER = 3        # содержательная подгруппа — не меньше трёх окон
MIXED_MAX_CENTER_COS = 0.65  # без проверки имён: центры ближе — это всё ещё один голос


def _норма(v) -> list[float]:
    длина = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / длина for x in v]


def _косинус(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1.0)
                                               * (math.sqrt(sum(y * y for y in b)) or 1.0))


def _медиана_близости(векторы: list[list[float]]) -> float:
    """Медиана попарной близости окон метки: у одного голоса высокая, у смеси — низкая."""
    оценки = []
    for i in range(len(векторы)):
        for j in range(i + 1, len(векторы)):
            оценки.append(_косинус(векторы[i], векторы[j]))
    if not оценки:
        return 0.0
    оценки.sort()
    return оценки[len(оценки) // 2]


def _кmeans(векторы: list[list[float]], k: int, итераций: int = 30) -> tuple[list[int], list[list[float]]]:
    """Сферический k-means: центры — средние направления, мера — косинус. Детерминированно (без random)."""
    порядок = sorted(range(len(векторы)), key=lambda i: tuple(векторы[i]))
    центры = [_норма(векторы[порядок[int((j + 0.5) * len(векторы) / k)]]) for j in range(k)]
    метки = [0] * len(векторы)
    for _ in range(итераций):
        новые = [max(range(k), key=lambda c: _косинус(v, центры[c])) for v in векторы]
        if новые == метки:
            break
        метки = новые
        for c in range(k):
            свои = [векторы[i] for i in range(len(векторы)) if метки[i] == c]
            if свои:
                центры[c] = _норма([sum(v[i] for v in свои) for i in range(len(свои[0]))])
    return метки, центры


def _подгруппы(куски: list[dict], метки: list[int], метка: str) -> tuple[list[dict], list[dict]]:
    """Куски с новыми метками и такие же отрезки — одна нумерация для отпечатков и строк."""
    под = [dict(s, speaker=f"{метка}-{m + 1}") for s, m in zip(куски, метки)]
    сегменты = [{"speaker": x["speaker"], "start": x["start"], "end": x["end"]} for x in под]
    return под, сегменты


def split_mixed(samples: list[dict], segments: list[dict],
                подходит=None) -> tuple[list[dict], list[dict], list[dict]]:
    """Разделить слипшиеся метки. Возвращает (samples, segments, отчёт).

    `подходит(под_samples, под_segments) -> int` — сколько РАЗНЫХ людей правило имени называет уверенно;
    если передана, выбирается деление с наибольшим числом имён. Без неё — первое, где центры различимы.
    """
    группы: dict[str, list[dict]] = {}
    for s in samples:
        if s.get("embedding"):
            группы.setdefault(s.get("speaker") or "", []).append(s)
    новые: dict[tuple, str] = {}
    отчёт = []
    for метка, куски in группы.items():
        if len(куски) < MIXED_MIN_WINDOWS:
            continue
        векторы = [_норма(s["embedding"]) for s in куски]
        было = _медиана_близости(векторы)
        if было >= MIXED_COHERENCE:
            continue
        варианты = []
        for k in range(2, MIXED_MAX_K + 1):
            метки, центры = _кmeans(векторы, k)
            размеры = [метки.count(c) for c in range(k)]
            if sum(1 for n in размеры if n >= MIXED_MIN_CLUSTER) < 2:
                continue
            макс = max(_косинус(центры[a], центры[b]) for a in range(k) for b in range(a + 1, k))
            if подходит is None and макс > MIXED_MAX_CENTER_COS:
                continue
            варианты.append((k, метки, макс))
        if not варианты:
            continue
        выбрано = None
        if подходит is not None:
            лучший = 0
            for k, метки, макс in варианты:
                под, сег = _подгруппы(куски, метки, метка)
                try:
                    счёт = int(подходит(под, сег))
                except Exception:  # noqa: BLE001 — проверка не должна ронять разбор
                    счёт = 0
                if счёт > лучший:
                    лучший, выбрано = счёт, (k, метки, макс)
        if выбрано is None:
            k, метки, макс = варианты[0]
            выбрано = (k, метки, макс)
        k, метки, макс = выбрано
        for s, c in zip(куски, метки):
            новые[(s.get("start"), s.get("end"))] = f"{метка}-{c + 1}"
        после = max((_медиана_близости([векторы[i] for i in range(len(векторы)) if метки[i] == c])
                     for c in range(k)), default=0.0)
        отчёт.append({"label": метка, "windows": len(куски), "groups": k,
                      "coherence_before": round(было, 3), "coherence_after": round(после, 3),
                      "max_center_cos": round(макс, 3)})
    if not новые:
        return samples, segments, []
    for s in samples:
        новая = новые.get((s.get("start"), s.get("end")))
        if новая:
            s["speaker"] = новая
    for seg in segments:
        новая = новые.get((seg.get("start"), seg.get("end")))
        if новая:
            seg["speaker"] = новая
    return samples, segments, отчёт
