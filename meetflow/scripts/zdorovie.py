# -*- coding: utf-8 -*-
"""Самопроверка стенда MeetFlow одной командой (09.11.2026).

Отвечает на вопрос «работает ли система и на текущем ли коде» без ручных wmic/лога:

- служба 8005 отвечает и говорит `ok`;
- **код не новее запуска**: сравнивается время старта из журнала (`Uvicorn running`) с самой свежей правкой `.py`
  ядра и веб-слоя; новее — значит служба работает на старом коде, нужен перезапуск;
- база открывается и проходит `quick_check`, людей и встреч — числом;
- журнал тени существует (иначе 13.11 нечего считать).

    python scripts/zdorovie.py
    python scripts/zdorovie.py --без-базы     # только служба и код

Код возврата: 0 — всё в порядке; 1 — служба не отвечает; 2 — код новее запуска (нужен перезапуск); 3 — база или журнал.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
БАЗА = КОРЕНЬ / "data" / "meetflow.db"
ЖУРНАЛ_ТЕНИ = КОРЕНЬ / "data" / "logs" / "svedenie_ten.jsonl"
АДРЕС = "http://127.0.0.1:8005/health"
_СТАРТ_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),?\d*.*Uvicorn running", re.MULTILINE)


def запуск_из_журнала(текст: str) -> datetime | None:
    """Время последнего старта uvicorn из журнала обёртки. В журнале строки «2026-11-09 04:28:35,123 … Uvicorn running»."""
    найдено = _СТАРТ_RE.findall(текст or "")
    if not найдено:
        return None
    день, время = найдено[-1]
    return datetime.strptime(f"{день} {время}", "%Y-%m-%d %H:%M:%S")


def последняя_правка(каталоги: list[Path]) -> datetime | None:
    """Самое свежее время изменения `.py` в переданных каталогах (рекурсивно)."""
    свежее: float | None = None
    for каталог in каталоги:
        if not Path(каталог).is_dir():
            continue
        for файл in Path(каталог).rglob("*.py"):
            m = файл.stat().st_mtime
            свежее = m if свежее is None else max(свежее, m)
    return datetime.fromtimestamp(свежее) if свежее else None


def свежесть(старт: datetime | None, правка: datetime | None, запас_сек: int = 5) -> tuple[bool, str]:
    """(ok, текст): код новее запуска — служба на старом коде. Запас — запись файла во время старта."""
    if старт is None:
        return False, "время старта не найдено в журнале"
    if правка is None:
        return True, "правок кода не найдено"
    if правка.timestamp() > старт.timestamp() + запас_сек:
        return False, f"код новее запуска на {int(правка.timestamp() - старт.timestamp())} с — нужен перезапуск"
    return True, "служба на текущем коде"


def строка_команды(разбор: dict) -> tuple[int, str]:
    """(сколько расхождений, строка): проектная «Команда» против общей — сколько отчеств дописать и людей добавить.

    Расхождение — не ошибка: после правки общей «Команды» копия проектов отстаёт до синхронизации. Но видеть его надо:
    иначе сборка пойдёт по старым именам, а проверка покажет «46 без отчества».
    """
    дописать = sum(len(п.get("дописать") or []) for п in (разбор or {}).values())
    добавить = sum(len(п.get("добавить") or []) for п in (разбор or {}).values())
    всего = дописать + добавить
    if not разбор:
        return 0, "Команда: общей «Команды» нет или она пуста"
    if not всего:
        return 0, "Команда: расхождений нет"
    return всего, (f"Команда: расхождений {всего} (дописать отчество {дописать}, добавить {добавить}) — "
                   "синхронизировать: python scripts/sync_komandy.py --apply")


def _health(адрес: str = АДРЕС) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # localhost мимо прокси
    try:
        with opener.open(адрес, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — служба может быть выключена
        return None


def _база(путь: Path) -> tuple[bool, str]:
    if not Path(путь).is_file():
        return False, f"базы нет: {путь}"
    con = sqlite3.connect(str(путь))
    con.execute("PRAGMA query_only=ON")
    try:
        проверка = con.execute("PRAGMA quick_check").fetchone()[0]
        people = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        meetings = con.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
        return проверка == "ok", f"quick_check {проверка}, людей {people}, встреч {meetings}"
    except sqlite3.DatabaseError as exc:
        return False, f"база не читается: {exc}"
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Самопроверка стенда MeetFlow")
    ap.add_argument("--журнал", default=str(Path.home() / "AppData/Local/MeetFlow/logs/meetflow.log"))
    ap.add_argument("--без-базы", action="store_true", help="не проверять базу и журнал тени")
    a = ap.parse_args(argv)

    беды: list[str] = []
    здоровье = _health()
    if not здоровье or not здоровье.get("ok"):
        беды.append("служба 8005 не отвечает")
    else:
        print(f"Служба: ok, тема {здоровье.get('theme')}, busy {здоровье.get('busy')}")

    старт = None
    if здоровье and здоровье.get("started_at"):
        try:
            старт = datetime.fromisoformat(str(здоровье["started_at"]))
        except ValueError:
            старт = None
    if старт is None:      # старый код без started_at — пробуем журнал обёртки
        текст_журнала = (Path(a.журнал).read_text(encoding="utf-8", errors="replace")
                         if Path(a.журнал).is_file() else "")
        старт = запуск_из_журнала(текст_журнала)
    правка = последняя_правка([КОРЕНЬ / "meetflow", КОРЕНЬ / "meetflow" / "web"])
    ok, сообщение = свежесть(старт, правка)
    print(f"Код: {сообщение}" + (f" (старт {старт:%d.%m %H:%M:%S})" if старт else ""))
    if not ok:
        беды.append(сообщение)

    if not a.без_базы:
        ok_б, сообщение_б = _база(БАЗА)
        print(f"База: {сообщение_б}")
        if not ok_б:
            беды.append(сообщение_б)
        if not ЖУРНАЛ_ТЕНИ.is_file():
            беды.append(f"журнала тени нет: {ЖУРНАЛ_ТЕНИ}")
        else:
            строк = sum(1 for _ in ЖУРНАЛ_ТЕНИ.open(encoding="utf-8"))
            print(f"Журнал тени: строк {строк}")
        try:  # расхождение проектной «Команды» с общей — предупреждение, не отказ
            import importlib.util as _ilu
            from meetflow.core.store import Store
            from meetflow.core.team_sync import shared_people
            spec = _ilu.spec_from_file_location("sync_komandy", Path(__file__).with_name("sync_komandy.py"))
            ск = _ilu.module_from_spec(spec)
            spec.loader.exec_module(ск)
            s_ = Store(str(БАЗА))
            try:
                люди = shared_people(s_.get_setting("voice_base_path"))
                _, текст = строка_команды(ск.план(s_, люди) if люди else {})
            finally:
                s_.close()
            print(текст)
        except Exception as exc:  # noqa: BLE001 — сверка не должна ломать самопроверку
            print(f"Команда: сверить не удалось ({type(exc).__name__})")

    if not здоровье or not здоровье.get("ok"):
        return 1
    if any("код новее запуска" in б for б in беды):
        return 2
    if беды:
        return 3
    print("Итог: стенд в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
