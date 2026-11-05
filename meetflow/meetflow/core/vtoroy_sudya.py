# -*- coding: utf-8 -*-
"""Второй судья в тень: один вызов на сборку, только журнал (решение разработчика 05.11.2026).

Повод — замер 05.11.2026: по парам «одна работа или разные» модель ошибается и одна (3 ложных из 46), и пачками
(10 из 46), ответ к тому же меняется между ходами. Сразу снимать задачи по такому ответу нельзя, поэтому судья
работает в тень: пары своей встречи от 0,4, ничего не снимает и не меняет, на экране не показывается — только
строка в журнале `vtoroy_sudya.jsonl` рядом с журналом вызовов.

Выключатель `WEBAPP_VTOROY_SUDYA` по умолчанию выключен: боевая сборка его не делает. Включают для замеров
(`on`/`1`/`true`/`да`). Потолок — один вызов на сборку. Решение включить правило примет разработчик по таблицам
с трёх встреч, где ни одна настоящая задача не снята.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import ukrupnenie_zadach as уз

ПЕРЕМЕННАЯ = "WEBAPP_VTOROY_SUDYA"
ПОРОГ = 0.4                  # ниже — не пара для судьи
ПРЕДЕЛ_ПАР = 12              # один вызов не должен расти без края
ИМЯ_ЖУРНАЛА = "vtoroy_sudya.jsonl"

СИСТЕМА = (
    "Ты сверяешь задачи одной организации. Для каждой пары реши: это одна и та же работа или разные работы. "
    "Смотри на предмет: что именно нужно сделать и с чем. Разные объекты, разные исполнители или разные этапы — "
    "разные работы. Короткая и подробная запись одной работы — одна. Ответ — только JSON по схеме: "
    '{"pairs": [{"n": 1, "answer": "одна" или "разные", "why": "до 15 слов"}]}'
)


def включён() -> bool:
    """Выключатель: по умолчанию выключен — боевая сборка второго судью не зовёт."""
    return os.environ.get(ПЕРЕМЕННАЯ, "").strip().lower() in ("on", "1", "true", "yes", "да")


def _доля(а: dict, б: dict) -> tuple[str, float]:
    """(вердикт правила, доля предмета) — тем же счётом, что у повторов реестра."""
    ка, кб = уз.исполнитель(а), уз.исполнитель(б)
    текст_а = уз.без_исполнителя(уз.описание(а), ка)
    текст_б = уз.без_исполнителя(уз.описание(б), кб)
    return уз.сходство_предмета(текст_а, текст_б, ка, кб)


def пары(store, project_id: int, meeting_id: int, предел: int = ПРЕДЕЛ_ПАР) -> list[dict]:
    """Пары «задача этой встречи — другая действующая задача проекта» от 0,4, лучшие первыми.

    В пары идут и задачи самой встречи (сборка укрупняет их до этого шага, но не всегда), и задачи других
    встреч: дубль бывает и внутри одной записи, и между записями.
    """
    свои = store.q("SELECT * FROM tasks WHERE project_id=? AND source_meeting_id=? AND status='active'",
                   (project_id, meeting_id))
    чужие = store.q("SELECT * FROM tasks WHERE project_id=? AND status='active' "
                    "AND (source_meeting_id IS NULL OR source_meeting_id<>?)", (project_id, meeting_id))
    найдено = []
    for i, а in enumerate(свои):
        for б in свои[i + 1:] + чужие:
            вердикт, доля = _доля(а, б)
            if вердикт == "нет" and доля < ПОРОГ:
                continue
            найдено.append({"a": а["id"], "b": б["id"], "score": доля, "rule": вердикт,
                            "a_text": (а["description"] or "")[:300], "b_text": (б["description"] or "")[:300]})
    найдено.sort(key=lambda п: (-п["score"], п["a"], п["b"]))
    return найдено[:предел]


def _журнал(pipe) -> Path | None:
    путь = getattr(getattr(pipe, "journal", None), "path", None)
    return Path(путь).with_name(ИМЯ_ЖУРНАЛА) if путь else None


def _ответы(data) -> dict[int, dict]:
    """Номер пары → {answer, why}; принимаем и «pairs», и просто список."""
    пункты = data.get("pairs") if isinstance(data, dict) else data
    out: dict[int, dict] = {}
    for п in пункты if isinstance(пункты, list) else []:
        if not isinstance(п, dict):
            continue
        try:
            n = int(п.get("n"))
        except (TypeError, ValueError):
            continue
        ответ = " ".join(str(п.get("answer") or "").split()).lower()
        if ответ.startswith("одна") or ответ.startswith("одно") or ответ.startswith("та же"):
            ответ = "одна"
        elif ответ.startswith("разн"):
            ответ = "разные"
        else:
            ответ = "непонятно"
        out[n] = {"answer": ответ, "why": " ".join(str(п.get("why") or "").split())[:200]}
    return out


def прогнать(pipe, project_id: int, meeting_id: int, budget) -> dict:
    """Один вызов на сборку; ничего не меняет. Ошибки не выходят наружу — судья в тени."""
    if not включён():
        return {"пропуск": f"{ПЕРЕМЕННАЯ} выключен"}
    try:
        пары_ = пары(pipe.s, project_id, meeting_id)
        if not пары_:
            return {"пар": 0}
        запрос = "\n".join(f'{n}. A: {п["a_text"]}\n   B: {п["b_text"]}'
                           for n, п in enumerate(пары_, 1))
        data = pipe._call(pipe.gen, budget, "второй судья", СИСТЕМА, запрос, meeting_id)
        ответы = _ответы(data)
        for n, п in enumerate(пары_, 1):
            о = ответы.get(n) or {"answer": "непонятно", "why": ""}
            п["answer"], п["why"] = о["answer"], о["why"]
        строка = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "meeting_id": meeting_id,
                  "project_id": project_id, "model": getattr(pipe.gen, "model", ""),
                  "pairs": [{k: п[k] for k in ("a", "b", "score", "rule", "answer", "why", "a_text", "b_text")}
                            for п in пары_]}
        путь = _журнал(pipe)
        if путь:
            путь.parent.mkdir(parents=True, exist_ok=True)
            with путь.open("a", encoding="utf-8") as f:
                f.write(json.dumps(строка, ensure_ascii=False) + "\n")
        return строка
    except Exception as exc:  # noqa: BLE001 — тень не должна ронять сборку
        return {"сбой": f"{type(exc).__name__}: {exc}"[:300]}
