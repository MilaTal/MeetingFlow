# -*- coding: utf-8 -*-
"""Синхронизация проектной «Команды» с общей после правки отчеств (9–10.11.2026).

Правка отчеств идёт в общей «Команде» (`team_shared.db` рядом с базой голосов). Проектная «Команда» MeetFlow обновляется
`sync_people` — но только когда открывают экран «Команда» или идёт сборка. Перед проверкой «что дописалось» нужна команда
«синхронизировать сейчас» с понятным отчётом:

    python scripts/sync_komandy.py                 # сухой ход: что изменится
    python scripts/sync_komandy.py --apply         # применить (сначала копия базы рядом)

Сухой ход ничего не пишет. При `--apply` база копируется в `meetflow.db.до-sinhrona-<ддмм>`, затем `sync_all`.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"


def _норма(фио: str | None) -> list[str]:
    return " ".join((фио or "").replace("ё", "е").split()).split()


def _ключ(фио: str | None) -> str:
    ч = _норма(фио)
    return " ".join(sorted(с.lower() for с in ч[:2])) if len(ч) >= 2 else " ".join(с.lower() for с in ч)


def план(store, люди: list[dict]) -> dict:
    """Что сделает sync_people по каждому живому проекту: дописать отчество, добавить, тёзки не угаданы.

    Ничего не пишет — считает по тем же правилам, что `team_sync.sync_people`.
    """
    итог: dict = {}
    проекты = store.q("SELECT id, name FROM projects WHERE COALESCE(archived,0)=0 AND COALESCE(deleted,0)=0 ORDER BY id")
    for п in проекты:
        записи = store.q("SELECT full_name FROM people WHERE project_id=?", (п["id"],))
        if not записи:
            continue
        существующие = {_норма(r["full_name"]) and " ".join(_норма(r["full_name"])) for r in записи}
        по_ключу: dict[str, list[str]] = {}
        for r in записи:
            if len(_норма(r["full_name"])) >= 2:
                по_ключу.setdefault(_ключ(r["full_name"]), []).append(r["full_name"])
        дописать, добавить, тёзки = [], [], []
        for ч in люди:
            оригинал = " ".join((ч.get("full_name") or "").split())
            имя = " ".join(_норма(оригинал))
            if not имя or имя in существующие:
                continue
            части = _норма(оригинал)
            варианты = по_ключу.get(_ключ(имя), []) if len(части) >= 2 else []
            if len(части) >= 3:
                if any(len(_норма(в)) >= 3 and _норма(в)[2].lower() == части[2].lower() for в in варианты):
                    continue
                if any(len(_норма(в)) == 2 for в in варианты):
                    дописать.append(оригинал)
                else:
                    добавить.append(оригинал)
            else:
                отчества = {_норма(в)[2].lower() for в in варианты if len(_норма(в)) >= 3}
                if len(отчества) <= 1:
                    continue
                тёзки.append(оригинал)
        итог[п["id"]] = {"проект": п["name"], "дописать": дописать, "добавить": добавить, "тёзки": тёзки}
    return итог


def отчёт(разбор: dict, кратко: bool = False) -> str:
    строки = []
    всего_доп = всего_доб = всего_тёзк = 0
    for pid in sorted(разбор):
        п = разбор[pid]
        всего_доп += len(п["дописать"]); всего_доб += len(п["добавить"]); всего_тёзк += len(п["тёзки"])
        строки.append(f"Проект {pid} «{п['проект']}»: дописать отчество {len(п['дописать'])}, "
                      f"добавить {len(п['добавить'])}, тёзок не угадано {len(п['тёзки'])}")
        if not кратко:
            строки += [f"  дописать: {и}" for и in п["дописать"]]
            строки += [f"  добавить: {и}" for и in п["добавить"]]
            строки += [f"  тёзки (не угаданы): {и}" for и in п["тёзки"]]
    if not строки:
        return "живых проектов с людьми нет"
    строки.append("")
    строки.append(f"Итого: дописать {всего_доп}, добавить {всего_доб}, тёзок не угадано {всего_тёзк}")
    return "\n".join(строки)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Синхронизация проектной «Команды» с общей (сухой ход по умолчанию)")
    ap.add_argument("--db", default=str(БАЗА))
    ap.add_argument("--apply", action="store_true", help="применить (сначала копия базы рядом)")
    ap.add_argument("--кратко", action="store_true")
    a = ap.parse_args(argv)

    from meetflow.core.store import Store
    from meetflow.core.team_sync import shared_people, sync_all

    база = Path(a.db).expanduser().resolve()
    if not база.is_file():
        raise SystemExit(f"базы нет: {база}")
    store = Store(str(база))
    try:
        люди = shared_people(store.get_setting("voice_base_path"))
        if not люди:
            print("общая «Команда» не читается или пуста — проверьте путь в настройках", file=sys.stderr)
            return 3
        разбор = план(store, люди)
        print(отчёт(разбор, a.кратко))
        if not a.apply:
            print("\nСухой ход: ничего не изменено. Применить — с ключом --apply.")
            return 0
        копия = база.with_name(f"{база.name}.до-sinhrona-{datetime.now():%d%m}")
        shutil.copy2(база, копия)
        print(f"\nКопия базы: {копия.name}")
        добавлено = sync_all(store, store.get_setting("voice_base_path"))
        print("Применено: " + (", ".join(f"проект {k}: +{v}" for k, v in добавлено.items()) or "новых записей нет"))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
