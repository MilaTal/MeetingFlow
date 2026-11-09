# -*- coding: utf-8 -*-
"""Кто в «Команде» без отчества — список к правке 9–10.11.2026.

Владелица будет дописывать отчества в «Команду». Чтобы правка шла по списку, а не по памяти: скрипт читает базу **только
на чтение** и печатает по проектам, у кого в записи два слова (фамилия и имя). Имена — **в консоль**, в репозиторий не
пишутся.

    python scripts/kto_bez_otchestva.py                 # по всем живым проектам, с именами
    python scripts/kto_bez_otchestva.py --кратко        # только числа
    python scripts/kto_bez_otchestva.py --проект 6      # один проект
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"


def _соединение(путь: str | Path) -> sqlite3.Connection:
    p = Path(путь).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"базы нет: {p}")
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA query_only=ON")     # только чтение: правку делает человек в «Команде», не скрипт
    con.row_factory = sqlite3.Row
    return con


def слова(фио: str | None) -> list[str]:
    return " ".join((фио or "").replace("ё", "е").split()).split()


def без_отчества(люди: list[dict]) -> list[dict]:
    """Записи из двух слов (фамилия и имя). Три слова и больше — отчество есть; одно слово — не человек «Команды»."""
    return [ч for ч in люди if len(слова(ч.get("full_name"))) == 2]


def собрать(путь: str | Path, проект: int | None = None) -> dict:
    """{проект: {"всего": n, "без_отчества": m, "люди": [...]}} — по живым проектам."""
    con = _соединение(путь)
    try:
        запрос = ("SELECT id, name FROM projects WHERE COALESCE(archived,0)=0 AND COALESCE(deleted,0)=0")
        параметры: tuple = ()
        if проект is not None:
            запрос += " AND id=?"
            параметры = (проект,)
        проекты = con.execute(запрос + " ORDER BY id", параметры).fetchall()
        итог: dict = {}
        for п in проекты:
            люди = [dict(r) for r in con.execute(
                "SELECT id, full_name FROM people WHERE project_id=? ORDER BY full_name", (п["id"],))]
            нет = без_отчества(люди)
            if not люди:
                continue
            итог[п["id"]] = {"проект": п["name"], "всего": len(люди), "без_отчества": len(нет),
                             "люди": [ч["full_name"] for ч in нет]}
        return итог
    finally:
        con.close()


def отчёт(разбор: dict, кратко: bool = False) -> str:
    строки: list[str] = []
    всего = без = 0
    for pid in sorted(разбор):
        п = разбор[pid]
        всего += п["всего"]
        без += п["без_отчества"]
        строки.append(f"Проект {pid} «{п['проект']}»: без отчества {п['без_отчества']} из {п['всего']}")
        if not кратко and п["люди"]:
            строки += [f"  — {фио}" for фио in п["люди"]]
    if not строки:
        return "живых проектов с людьми нет"
    строки.append("")
    строки.append(f"Всего: без отчества {без} из {всего}")
    return "\n".join(строки)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Кто в «Команде» без отчества (только чтение, имена в консоль)")
    ap.add_argument("--db", default=str(БАЗА), help="база MeetFlow; открывается только на чтение")
    ap.add_argument("--проект", type=int, default=None, help="один проект (по умолчанию все живые)")
    ap.add_argument("--кратко", action="store_true", help="только числа, без имён")
    a = ap.parse_args(argv)
    разбор = собрать(a.db, a.проект)
    print(отчёт(разбор, a.кратко))
    return 0 if разбор else 1


if __name__ == "__main__":
    raise SystemExit(main())
