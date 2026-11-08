# -*- coding: utf-8 -*-
"""Замер «выгрузка ВКС вторым текстом» на копии базы (записка 05.11.2026, п. «Как закрыть числом»).

Скрипт ничего не решает и не снимает: собирает встречу на КОПИИ базы и печатает числа, которые просит записка:
задачи (всего и с исполнителем), есть ли в задачах объект «Эль-Дабаа», число 5128 и срок «к 17-му», сколько окон
выгрузки дали карточку «возможна потерянная задача», цена прогона. Рабочую базу трогать нельзя — путь `data/meetflow.db`
и файл, на который он указывает, скрипт отвергает.

Порядок (потолок на весь пункт 0,10 $ — сверх не тратить):

    python scripts/zamer_vks_vtoroy_tekst.py --db data/kopiya-05-11.db --date 2026-11-05 \
        --local "…\\Транскрипция 05.11.2026 (распознано локально).txt" \
        --vks "…\\Транскрипция Планёрка 05.11.2026.txt"

Второй прогон для сравнения «до» делается тем же скриптом без `--vks`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
ЖИВАЯ = (КОРЕНЬ / "data" / "meetflow.db").resolve()
МАРКЕРЫ = ("эль-дабаа", "эльдаба", "прокал", "5128", "17-м", "17 му", "к 17")


def проверить_базу(путь: Path) -> Path:
    """Копия, а не рабочая база: иначе замер изменит то, с чем работает владелица."""
    p = Path(путь).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"базы нет: {p}")
    if p == ЖИВАЯ:
        raise SystemExit("это рабочая база MeetFlow — замер идёт только на копии")
    return p


def _строки(путь: Path) -> str:
    p = Path(путь).expanduser()
    if not p.is_file():
        raise SystemExit(f"файла расшифровки нет: {p}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def собрать(база: Path, тема: str, дата: str, местный: Path, вкс: Path | None, проект: int | None) -> dict:
    from meetflow.web.app import create_app

    app = create_app(тема, str(база), str(база.with_suffix(".jsonl")), watch=False)
    st = app.state.store
    pid = проект or st.q("SELECT id FROM projects ORDER BY id LIMIT 1")[0]["id"]
    mid = st.insert("meetings", project_id=pid, date=дата, label="замер выгрузки ВКС")
    st.insert("sources", meeting_id=mid, name=местный.name, kind="transcript", text=_строки(местный),
              digest="z1" + дата, local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
              created_at=f"{дата}T09:00:00")
    if вкс is not None:
        st.insert("sources", meeting_id=mid, name=вкс.name, kind="transcript", text=_строки(вкс),
                  digest="z2" + дата, local_asr=0, meta=json.dumps({}, ensure_ascii=False),
                  created_at=f"{дата}T09:05:00")
    начало = time.monotonic()
    rep = app.state.pipe.run(pid, mid)
    секунд = round(time.monotonic() - начало, 1)
    задачи = st.q("SELECT description, assignee, due_date, source_quote FROM tasks WHERE source_meeting_id=? "
                  "ORDER BY id", (mid,))
    def тексты(row):
        return " ".join(str(row[k] or "") for k in ("description", "assignee", "due_date", "source_quote")).lower()
    итог = {
        "встреча": mid,
        "источников": 2 if вкс is not None else 1,
        "задач": len(задачи),
        "с_исполнителем": sum(1 for t in задачи if (t["assignee"] or "").strip()),
        "задач_с_маркерами_выгрузки": {
            маркер: sum(1 for t in задачи if маркер in тексты(t)) for маркер in МАРКЕРЫ},
        "окон_возможных_потерь": len(st.q(
            "SELECT id FROM cards WHERE meeting_id=? AND title LIKE 'Возможна потерянная задача%'", (mid,))),
        "цена_долларов": getattr(rep, "cost_usd", None),
        "вызовов": getattr(rep, "calls", None),
        "секунд": секунд,
        "итог_сборки": getattr(rep, "status", ""),
        "почему_источник": getattr(rep, "source_reason", ""),
    }
    return итог


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Замер выгрузки ВКС вторым текстом на копии базы")
    ap.add_argument("--db", required=True, help="копия базы MeetFlow (рабочая отвергается)")
    ap.add_argument("--theme", default="it_product")
    ap.add_argument("--date", required=True)
    ap.add_argument("--local", required=True, help="своя расшифровка, .txt")
    ap.add_argument("--vks", default=None, help="выгрузка ВКС, .txt (без неё — замер «до»)")
    ap.add_argument("--project", type=int, default=None)
    a = ap.parse_args(argv)
    база = проверить_базу(Path(a.db))
    итог = собрать(база, a.theme, a.date, Path(a.local), Path(a.vks) if a.vks else None, a.project)
    print(json.dumps(итог, ensure_ascii=False, indent=1))
    цена = итог.get("цена_долларов") or 0
    if цена > 0.10:
        print(f"ВНИМАНИЕ: цена {цена} $ выше потолка пункта 0,10 $", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
