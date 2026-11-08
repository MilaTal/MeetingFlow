# -*- coding: utf-8 -*-
"""Срез тени сведения по текущим задачам — без пересборки, без модели, без денег (план, пункт 7).

Зачем: недельная таблица 13.11 собирается из журнала `svedenie_ten.jsonl`, а строки туда пишут только сборки. Если за
неделю рабочих сборок не было, итог пуст. Этот срез показывает, что способ 1 сделал бы **на сегодняшних задачах** уже
собранных встреч: сколько групп и какие пары он объединил бы.

Срез — не замена недельному наблюдению: в журнал он **не пишется** (иначе недельный итог смешается с разовым срезом), в
отчёте называется «срез по текущим задачам, без пересборки». База открывается только на чтение, встречи не пересобираются,
модель не вызывается.

    python scripts/srez_ten_tekushchie.py
    python scripts/srez_ten_tekushchie.py --db data/kopiya.db --вывод срез.md
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"


def _соединение(путь: str | Path) -> sqlite3.Connection:
    """Соединение только на чтение. `PRAGMA query_only` надёжнее URI `mode=ro`: путь может быть сетевым (диск P:),
    и `file://` с UNC-именем SQLite отвергает («invalid uri authority»)."""
    p = Path(путь).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"базы нет: {p}")
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def задачи_встречи(con: sqlite3.Connection, meeting_id: int) -> list[dict]:
    """Активные задачи встречи в том виде, в каком их читает укрупнение: формулировка, исполнитель, срок, цитата."""
    строки = con.execute("SELECT description, assignee, due_date, due_kind, source_quote FROM tasks "
                         "WHERE source_meeting_id=? AND status='active' ORDER BY id", (meeting_id,)).fetchall()
    return [{"description": s["description"] or "", "responsible": s["assignee"] or "",
             "due_date": s["due_date"] or "", "due_kind": s["due_kind"] or "",
             "quote": s["source_quote"] or ""} for s in строки]


def запись_встречи(con: sqlite3.Connection, meeting_id: int) -> str:
    """Все живые источники встречи одной строкой (по ним ищется место цитаты)."""
    строки = con.execute("SELECT text FROM sources WHERE meeting_id=? AND removed_at IS NULL ORDER BY id",
                         (meeting_id,)).fetchall()
    return "\n".join(s["text"] or "" for s in строки)


def срез(путь: str | Path, встречи: list[int] | None = None) -> dict:
    """Посчитать способ 1 по текущим задачам каждой встречи и сравнить с обычным сведением. Ничего не пишет: только чтение."""
    from meetflow.core import svedenie_ten
    from meetflow.core import ukrupnenie_zadach as уз

    con = _соединение(путь)
    try:
        ids = [int(x) for x in (встречи or [])]
        if not ids:
            ids = [s["source_meeting_id"] for s in con.execute(
                "SELECT DISTINCT source_meeting_id FROM tasks WHERE status='active' "
                "AND source_meeting_id IS NOT NULL ORDER BY source_meeting_id")]
        итоги = []
        for mid in ids:
            задачи = задачи_встречи(con, mid)
            if not задачи:
                continue
            встреча = con.execute("SELECT date, label FROM meetings WHERE id=?", (mid,)).fetchone()
            запись = запись_встречи(con, mid)
            счёт = svedenie_ten.посчитать(задачи, запись)
            _, как_сейчас = уз.укрупнить(задачи, запись)        # обычное сведение, с условием «рядом»
            счёт["сейчас_стало"] = как_сейчас["стало"]
            счёт["сейчас_объединено"] = как_сейчас["объединено"]
            счёт["meeting_id"] = mid
            счёт["date"] = (встреча["date"] if встреча else "") or ""
            счёт["label"] = (встреча["label"] if встреча else "") or ""
            итоги.append(счёт)
        return {"встречи": итоги}
    finally:
        con.close()


def _итоги(встречи: list[dict]) -> dict:
    итог = {"встреч": len(встречи), "было": 0, "сейчас_стало": 0, "сейчас_объединено": 0, "стало_бы": 0,
            "объединено_бы": 0, "сомнений": 0, "по_предмету": 0, "по_контрагенту": 0, "по_подпроектам": 0,
            "через_отдел": 0, "ошибочно_снятых": 0}
    for в in встречи:
        for поле in итог:
            if поле == "встреч":
                continue
            итог[поле] += int(в.get(поле) or 0)
    return итог


def markdown(разбор: dict) -> str:
    встречи = разбор["встречи"]
    строки = ["# Срез тени сведения по текущим задачам (без пересборки)", "",
              "Способ 1 посчитан по задачам, которые лежат в базе сейчас. Встречи не пересобирались, модель не вызывалась,",
              "в журнал недельного наблюдения срез **не пишется**.", ""]
    if not встречи:
        строки += ["активных задач ни у одной встречи нет — срез пуст.", ""]
        return "\n".join(строки)
    строки += ["| встреча | дата | задач | сейчас стало | способ 1 стало бы | сейчас объединено | объединено бы | "
               "сомнений | по предмету | по контрагенту | по подпроектам | через отдел | ошибочно снятых |",
               "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for в in встречи:
        строки.append(f"| {в['meeting_id']} | {в['date']} | {в['было']} | {в['сейчас_стало']} | {в['стало_бы']} | "
                      f"{в['сейчас_объединено']} | {в['объединено_бы']} | {в['сомнений']} | {в['по_предмету']} | "
                      f"{в['по_контрагенту']} | {в['по_подпроектам']} | {в['через_отдел']} | {в['ошибочно_снятых']} |")
    ит = _итоги(встречи)
    строки.append(f"| **итого** | | {ит['было']} | {ит['сейчас_стало']} | {ит['стало_бы']} | {ит['сейчас_объединено']} | "
                  f"{ит['объединено_бы']} | {ит['сомнений']} | {ит['по_предмету']} | {ит['по_контрагенту']} | "
                  f"{ит['по_подпроектам']} | {ит['через_отдел']} | {ит['ошибочно_снятых']} |")
    строки.append("")
    сверх = ит["сейчас_стало"] - ит["стало_бы"]
    строки += ["Способ 1 сверх обычного сведения объединил бы ещё "
               f"**{сверх}** задач(и) ({ит['сейчас_стало']} → {ит['стало_бы']}).", ""]
    пары = [(в["meeting_id"], п) for в in встречи for п in в.get("пары", [])]
    if пары:
        строки += ["## Пары, которые объединил бы способ 1", ""]
        for mid, пара in пары[:40]:
            части = " | ".join(str(ч) for ч in (пара.get("части") or []))
            if len(части) > 200:
                части = части[:200] + "…"
            строки.append(f"- встреча {mid}, основание «{пара.get('основание') or '—'}»: {части}")
        if len(пары) > 40:
            строки.append(f"- … ещё {len(пары) - 40} пар")
        строки.append("")
    строки += ["## Условие варианта C", "",
               f"Ошибочно снятых настоящих задач — **0, жёстко**: "
               f"{'да' if ит['ошибочно_снятых'] == 0 else 'НЕТ — ' + str(ит['ошибочно_снятых'])}. "
               "Срез ничего не снимает и не меняет.", ""]
    return "\n".join(строки)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Срез тени сведения по текущим задачам (только чтение)")
    ap.add_argument("--db", default=str(БАЗА), help="база MeetFlow; открывается только на чтение")
    ap.add_argument("--встречи", default=None, help="номера встреч через запятую (по умолчанию все с активными задачами)")
    ap.add_argument("--вывод", default=None, help="файл, куда записать таблицу")
    a = ap.parse_args(argv)
    встречи = [int(x) for x in a.встречи.split(",") if x.strip()] if a.встречи else None
    разбор = срез(a.db, встречи)
    текст = markdown(разбор)
    print(текст)
    if a.вывод:
        Path(a.вывод).write_text(текст, encoding="utf-8", newline="\n")
    if not разбор["встречи"]:
        return 1
    ит = _итоги(разбор["встречи"])
    if ит["ошибочно_снятых"]:
        print(f"ВНИМАНИЕ: ошибочно снятых {ит['ошибочно_снятых']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
