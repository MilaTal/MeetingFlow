"""Общая «Команда» (team_shared): список людей для MeetFlow — строго только чтение.

Устройство взято у Планёрки и ERP: одна общая база людей лежит вне папок проектов,
путь — `TEAM_SHARED_PATH`, а если он не задан — `team_shared.db` рядом с общей базой
голосов (`VOICE_BASE_PATH` или путь из «Настроек» MeetFlow). Таблица `people`:
`full_name`, `role`, `department`, `project_role`, `organization`, `is_external`.

Правила:
- в общую базу попадают только подтверждённые записи, поэтому «люди» и
  «подтверждены» здесь — одно число; отдельного поля `confirmed` в ней нет;
- решения по людям принимаются в «Команде» Планёрки и ERP, MeetFlow их только
  читает: ни записи, ни сверки, ни создания файла;
- внешние контакты используются только подтверждённые — это свойство самой общей
  базы, здесь оно лишь показывается отдельным счётчиком;
- сбой или отсутствие файла не роняет экран: причина описывается словами.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

CONTRACT = {"people": {"full_name", "is_external"}}
_OFF = {"0", "off", "false", "no", "нет", "выкл"}


def _enabled() -> bool:
    """Аварийный выключатель `TEAM_SHARED=off` — как в Планёрке и ERP; без него включена."""
    return (os.environ.get("TEAM_SHARED") or "").strip().lower() not in _OFF


def shared_path(voice_base_path: str | None = None) -> Path | None:
    """Явный `TEAM_SHARED_PATH`; иначе `team_shared.db` рядом с общей базой голосов."""
    raw = (os.environ.get("TEAM_SHARED_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    base = (voice_base_path or os.environ.get("VOICE_BASE_PATH") or "").strip()
    return (Path(base).expanduser().parent / "team_shared.db") if base else None


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def team_shared_state(path: str | None = None, voice_base_path: str | None = None) -> dict[str, Any]:
    """Состояние общей «Команды» для мониторинга и настроек: счётчики и список людей."""
    if not _enabled():
        return {"enabled": False, "ok": False, "path": None,
                "detail": "Общая «Команда» выключена (TEAM_SHARED=off)."}
    p = Path(path).expanduser() if path else shared_path(voice_base_path)
    st: dict[str, Any] = {"enabled": True, "path": str(p) if p else None, "ok": False}
    if p is None:
        st["detail"] = "Путь к общей «Команде» не задан: ни TEAM_SHARED_PATH, ни база голосов в «Настройках»."
        return st
    if p.is_dir():
        st["detail"] = "Указана папка, а нужен путь к файлу общей «Команды» (team_shared.db)."
        return st
    if not p.is_file():
        st["detail"] = "Файл общей «Команды» не найден."
        return st
    st["size_kb"] = round(p.stat().st_size / 1024, 1)
    try:
        con = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        st["detail"] = f"Общая «Команда» не открывается: {type(e).__name__}"
        return st
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        problems = []
        for t, need in CONTRACT.items():
            if t not in tables:
                problems.append(f"нет таблицы {t}")
            else:
                missing = need - _cols(con, t)
                if missing:
                    problems.append(f"в {t} нет полей {', '.join(sorted(missing))}")
        if problems:
            st["detail"] = "Схема не по договору: " + "; ".join(problems)
            st["contract_problems"] = problems
            return st
        one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        st["people"] = one("SELECT COUNT(*) FROM people")
        st["people_confirmed"] = st["people"]      # в общую базу попадают только подтверждённые
        st["external"] = one("SELECT COUNT(*) FROM people WHERE COALESCE(is_external, 0) = 1")
        st["internal"] = st["people"] - st["external"]
        cols = _cols(con, "people")
        if "department" in cols:
            st["by_department"] = {d or "не указан": n for d, n in con.execute(
                "SELECT department, COUNT(*) FROM people WHERE COALESCE(is_external, 0) = 0 "
                "GROUP BY department ORDER BY department")}
        fields = [f for f in ("full_name", "role", "department", "organization", "is_external") if f in cols]
        rows = con.execute(f"SELECT {', '.join(fields)} FROM people "
                           "ORDER BY COALESCE(is_external, 0), full_name").fetchall()
        st["people_list"] = [{**{f: r[f] for f in fields if f != "is_external"},
                              "external": bool(r["is_external"])} for r in rows]
        st["ok"] = True
        st["detail"] = "Общая «Команда» доступна, только чтение."
    except sqlite3.Error as e:
        st["detail"] = f"Ошибка чтения общей «Команды»: {type(e).__name__}"
    finally:
        con.close()
    return st
