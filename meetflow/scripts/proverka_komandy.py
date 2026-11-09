# -*- coding: utf-8 -*-
"""Проверка «Команды» проекта после правки отчеств (10–11.11.2026).

Владелица дописывает отчества вручную (46 записей). Руками легко получить двойника («Иванов Пётр» и «Иванов Пётр
Сергеевич» рядом) или, наоборот, склеить тёзок. Скрипт читает базу **только на чтение** и печатает по живым проектам:

- **дубли** — одна и та же запись дважды (после «ё» = «е», регистра и лишних пробелов) — это ошибка, код возврата 2;
- **тёзки** — одна фамилия и имя, разные отчества: это нормально (разные люди), но полезно видеть списком;
- **без отчества** — записи из двух слов (что ещё не дописано);
- **одно слово** — не человек «Команды»: фамилия без имени, подсказка модели по такой записи не сработает.

Имена печатаются в консоль и в репозиторий не попадают.

    python scripts/proverka_komandy.py
    python scripts/proverka_komandy.py --кратко
    python scripts/proverka_komandy.py --проект 6
"""
from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"


def _слова_из_соседа():
    """`слова` из `kto_bez_otchestva.py` — рядом, в `scripts/` (пакетом скрипты не являются)."""
    путь = Path(__file__).with_name("kto_bez_otchestva.py")
    spec = importlib.util.spec_from_file_location("kto_bez_otchestva", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м.слова


слова = _слова_из_соседа()


def _ключ(фио: str | None) -> str:
    """Полное ФИО без регистра, лишних пробелов и «ё»: так ловятся двойники, записанные по-разному."""
    return " ".join(слова(фио)).lower()


def проверить(люди: list[dict]) -> dict:
    """Дубли, тёзки, без отчества, одно слово. Всё по нормализованному ФИО, порядок строк сохраняется."""
    группы: dict[str, list[str]] = {}
    for ч in люди:
        полное = _ключ(ч.get("full_name"))
        if полное:
            группы.setdefault(полное, []).append(ч.get("full_name") or "")
    дубли = {ф: имена for ф, имена in группы.items() if len(имена) > 1}

    тёзки_карта: dict[str, dict[str, str]] = {}
    без_отчества: list[str] = []
    одно_слово: list[str] = []
    for ч in люди:
        части = слова(ч.get("full_name"))
        if len(части) == 1:
            одно_слово.append(ч.get("full_name") or "")
            continue
        if len(части) == 2:
            без_отчества.append(ч.get("full_name") or "")
            continue
        ключ = " ".join(sorted(ч.lower() for ч in части[:2]))
        тёзки_карта.setdefault(ключ, {}).setdefault(части[2].lower(), ч.get("full_name") or "")
    тёзки = {к: list(в.values()) for к, в in тёзки_карта.items() if len(в) > 1}
    return {"всего": len(люди), "дубли": дубли, "тёзки": тёзки,
            "без_отчества": без_отчества, "одно_слово": одно_слово}


def собрать(путь: str | Path, проект: int | None = None) -> dict:
    p = Path(путь).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"базы нет: {p}")
    con = sqlite3.connect(str(p))
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    try:
        запрос = "SELECT id, name FROM projects WHERE COALESCE(archived,0)=0 AND COALESCE(deleted,0)=0"
        параметры: tuple = ()
        if проект is not None:
            запрос += " AND id=?"
            параметры = (проект,)
        итог: dict = {}
        for п in con.execute(запрос + " ORDER BY id", параметры).fetchall():
            люди = [dict(r) for r in con.execute(
                "SELECT id, full_name FROM people WHERE project_id=? ORDER BY full_name", (п["id"],))]
            if люди:
                итог[п["id"]] = {"проект": п["name"], **проверить(люди)}
        return итог
    finally:
        con.close()


def отчёт(разбор: dict, кратко: bool = False) -> str:
    if not разбор:
        return "живых проектов с людьми нет"
    строки: list[str] = []
    for pid in sorted(разбор):
        п = разбор[pid]
        строки.append(f"Проект {pid} «{п['проект']}»: людей {п['всего']}, дублей {len(п['дубли'])}, тёзок "
                      f"{len(п['тёзки'])}, без отчества {len(п['без_отчества'])}, одно слово {len(п['одно_слово'])}")
        if кратко:
            continue
        for имена in п["дубли"].values():
            строки.append("  дубль: " + " / ".join(имена))
        for имена in п["тёзки"].values():
            строки.append("  тёзки: " + " / ".join(имена))
        for фио in п["без_отчества"]:
            строки.append(f"  без отчества: {фио}")
        for фио in п["одно_слово"]:
            строки.append(f"  одно слово: {фио}")
    дублей = sum(len(п["дубли"]) for п in разбор.values())
    строки.append("")
    строки.append(f"Итог: дублей {дублей} — " + ("есть, разобрать" if дублей else "нет"))
    return "\n".join(строки)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проверка «Команды» после правки отчеств (только чтение)")
    ap.add_argument("--db", default=str(БАЗА))
    ap.add_argument("--проект", type=int, default=None)
    ap.add_argument("--кратко", action="store_true", help="только числа и итог")
    a = ap.parse_args(argv)
    разбор = собрать(a.db, a.проект)
    print(отчёт(разбор, a.кратко))
    if not разбор:
        return 1
    if any(п["дубли"] for п in разбор.values()):
        print("ВНИМАНИЕ: есть дубли — их быть не должно", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
