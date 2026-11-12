# -*- coding: utf-8 -*-
"""Замер опоры проекта на трёх записях (12.11.2026), без включения правила.

Для каждой встречи: абзацы тела с проектом и задачи с проектом в начале; проверяется, звучит ли проект в записи
(60 с назад / 30 с вперёд, чужой проект между перебивает тему). Только чтение, модели не зовутся.

Запуск: python -X utf8 scripts/zamer_opory_proekta_1211.py --meetings 2,4,7 [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ / "meetflow"))

from meetflow.core import iskazheniya_nazvaniy as iz  # noqa: E402
from meetflow.core import obshchaya_baza as ob  # noqa: E402
from meetflow.core.store import Store  # noqa: E402

БАЗА = КОРЕНЬ / "data" / "meetflow.db"
_АБЗАЦ = re.compile(r"^\s*(?:[-*]\s+)?\*\*([^*\n]{2,80})\*\*\s*[–—-]\s*(.*)$")
_ПРЕФИКС = re.compile(r"^([^:\n]{2,70}):\s+(.+)$", re.S)


def _проект_заголовка(заголовок: str, формы: dict) -> str:
    найдено = {н.проект for н in iz.найти(заголовок, формы, искажения=False, строго=True)}
    return next(iter(найдено)) if len(найдено) == 1 else ""


def _мера(store, mid: int, формы: dict, проекты: list[dict]) -> dict:
    m = store.get("meetings", mid) or {}
    src = store.q("SELECT text FROM sources WHERE meeting_id=? AND removed_at IS NULL ORDER BY id LIMIT 1", (mid,))
    текст = (src[0]["text"] if src else "") or ""
    сегм = iz.сегменты(текст)
    упоминания, сегм = iz.упоминания_по_сегментам(текст, формы)
    площ = iz.площадки(проекты)
    строки = []
    # Проекты в тексте протокола: каждое предложение, где проект назван. Смотрим, звучит ли он в записи.
    for ln in (m.get("protocol_md") or "").splitlines():
        if ln.strip().startswith("#") or ln.strip().startswith("|"):
            continue
        for предложение in re.split(r"(?<=[.!?…])\s+", ln):
            найдено = {н.проект for н in iz.найти(предложение, формы, искажения=False, строго=True)}
            for проект in sorted(найдено):
                опора = iz.есть_опора_текста(проект, предложение, упоминания, сегм, площ)
                строки.append({"вид": "тело", "проект": проект, "опора": bool(опора),
                               "фрагмент": " ".join(предложение.split())[:160]})
    for t in store.q("SELECT description, source_quote FROM tasks WHERE source_meeting_id=? AND status='active'", (mid,)):
        описание = t["description"] or ""
        найдено = {н.проект for н in iz.найти(описание, формы, искажения=False, строго=True)}
        for проект in sorted(найдено):
            опора = iz.есть_опора_текста(проект, описание + " " + (t["source_quote"] or ""), упоминания, сегм, площ)
            строки.append({"вид": "задача", "проект": проект, "опора": bool(опора),
                           "фрагмент": " ".join(описание.split())[:160]})
    return {"встреча": mid, "дата": m.get("date"), "секунд": (сегм[-1].секунда if сегм else 0),
            "строк": строки}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(БАЗА))
    ap.add_argument("--meetings", default="2,4,7")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ids = [int(x) for x in a.meetings.split(",") if x.strip()]
    store = Store(a.db)
    try:
        проекты = iz.проекты_справочника(store)
        итоги = []
        for mid in ids:
            m = store.get("meetings", mid) or {}
            проекты_встречи = проекты + (ob.проекты(store, m.get("project_id")) if m.get("project_id") else [])
            формы = iz.формы(проекты_встречи)
            р = _мера(store, mid, формы, проекты_встречи)
            итоги.append(р)
            if not a.json:
                всего = len(р["строк"])
                с_опорой = sum(1 for с in р["строк"] if с["опора"])
                print(f"\nВстреча {mid} ({р['дата']}), строк с проектом {всего}, с опорой {с_опорой}:")
                for с in р["строк"]:
                    print(f"  {'да' if с['опора'] else 'НЕТ'}  {с['вид']:6}  {с['проект']}: {с['фрагмент']}")
        if a.json:
            print(json.dumps(итоги, ensure_ascii=False, indent=2))
        else:
            print("\nИтого:")
            for р in итоги:
                всего = len(р["строк"])
                с = sum(1 for х in р["строк"] if х["опора"])
                print(f"  встреча {р['встреча']}: {с} из {всего} с опорой")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
