# -*- coding: utf-8 -*-
"""Проверка резервной копии базы MeetFlow перед правкой «Команды» (9–10.11.2026).

Копию делают, чтобы вернуться, если ручная правка 46 отчеств что-то испортит. Но копия — ещё не страховка: она должна
открываться, проходить `integrity_check` и содержать те таблицы, что нужны. Скрипт читает обе базы **только на чтение** и
печатает: цела ли копия, какие в ней числа и чем они отличаются от рабочей базы (разница — нормально: копия сделана
раньше правок; важно, чтобы она была целой).

    python scripts/proverka_kopii.py --копия data/meetflow.db.do-otchestv-0911
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"
ТАБЛИЦЫ = ("people", "meetings", "tasks", "sources", "protocol_versions")


def _открыть(путь: str | Path) -> sqlite3.Connection:
    p = Path(путь).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"базы нет: {p}")
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA query_only=ON")     # только чтение: проверка не должна трогать ни копию, ни рабочую базу
    return con


def проверить(путь: str | Path) -> dict:
    """Целостность и числа по таблицам. `ok` — integrity_check вернул `ok` и нет пропавших таблиц."""
    con = _открыть(путь)
    try:
        try:
            целостность = con.execute("PRAGMA integrity_check").fetchone()[0]
            есть = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as exc:      # файл есть, но это не база SQLite
            return {"целостность": f"не база: {exc}", "пропали": list(ТАБЛИЦЫ), "числа": {}}
        пропали = [т for т in ТАБЛИЦЫ if т not in есть]
        числа = {}
        for т in ТАБЛИЦЫ:
            if т in есть:
                числа[т] = con.execute(f"SELECT COUNT(*) FROM {т}").fetchone()[0]
        return {"целостность": целостность, "пропали": пропали, "числа": числа}
    finally:
        con.close()


def отчёт(копия: dict, рабочая: dict | None = None) -> str:
    строки = [f"Копия: целостность {копия['целостность']}"
              + ("" if not копия["пропали"] else f", нет таблиц: {', '.join(копия['пропали'])}")]
    for т, n in копия["числа"].items():
        строка = f"  {т}: {n}"
        if рабочая and т in рабочая["числа"]:
            разница = n - рабочая["числа"][т]
            if разница:
                строка += f" (в рабочей {рабочая['числа'][т]}, разница {разница:+d})"
        строки.append(строка)
    if рабочая is not None:
        строки.append("Разница с рабочей базой — нормально: копия сделана раньше правок; важна целостность.")
    годится = копия["целостность"] == "ok" and not копия["пропали"]
    строки.append("Копия годится: " + ("да" if годится else "НЕТ"))
    return "\n".join(строки)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка резервной копии базы (только чтение)")
    ap.add_argument("--копия", required=True, help="путь к копии базы")
    ap.add_argument("--база", default=str(БАЗА), help="рабочая база для сравнения (только чтение)")
    a = ap.parse_args(argv)
    копия = проверить(a.копия)
    рабочая = проверить(a.база) if Path(a.база).is_file() else None
    print(отчёт(копия, рабочая))
    if копия["целостность"] != "ok" or копия["пропали"]:
        print("ВНИМАНИЕ: копия не годится", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
