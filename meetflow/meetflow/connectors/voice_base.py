"""База голосов: состояние для мониторинга, строго только чтение.

Устройство взято из проектов-примеров: общая база `voices.db` лежит вне
папок проектов, путь — к ФАЙЛУ (VOICE_BASE_PATH или настройка супер-админа),
умолчания нет. Таблицы `voice_person` (люди: full_name, aliases, confirmed)
и `voice_sample` (отпечатки: person_id, embedding_model, origin_project).
Уроки:
- экран мониторинга падал целиком при отсутствии базы — здесь любое
  состояние описывается словами, исключение наружу не выходит;
- «подтверждено» значило два факта — здесь раздельно: подтверждённые люди
  и отпечатки, привязанные к человеку;
- запасная модель отпечатка другой размерности молча давала «никого не
  узнали» — поэтому показывается состав embedding_model;
- база открывается только на чтение (mode=ro), WAL не трогается.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

CONTRACT = {
    "voice_person": {"id", "full_name", "confirmed"},
    "voice_sample": {"id", "person_id"},
}


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def voice_base_state(path: str | None) -> dict[str, Any]:
    path = path or os.environ.get("VOICE_BASE_PATH") or None
    st: dict[str, Any] = {"path": path, "ok": False}
    if not path:
        st["detail"] = "Путь к базе голосов не задан (настройка супер-админа или VOICE_BASE_PATH)."
        return st
    p = Path(path)
    if p.is_dir():
        st["detail"] = "Указана папка, а нужен путь к файлу базы (например voices.db)."
        return st
    if not p.exists():
        st["detail"] = "Файл базы голосов не найден."
        return st
    st["size_kb"] = round(p.stat().st_size / 1024, 1)
    try:
        con = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        st["detail"] = f"База не открывается: {type(e).__name__}"
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
        st["journal_mode"] = con.execute("PRAGMA journal_mode").fetchone()[0]
        if problems:
            st["detail"] = "Схема не по договору: " + "; ".join(problems)
            st["contract_problems"] = problems
            return st
        one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
        st["samples"] = one("SELECT COUNT(*) FROM voice_sample")
        st["samples_linked"] = one("SELECT COUNT(*) FROM voice_sample WHERE person_id IS NOT NULL")
        st["people"] = one("SELECT COUNT(*) FROM voice_person")
        st["people_confirmed"] = one("SELECT COUNT(*) FROM voice_person WHERE confirmed = 1")
        st["people_waiting"] = st["people"] - st["people_confirmed"]
        # Списки — для экрана «База голосов» как в ERP: люди, записи, откуда отпечатки.
        pc = _cols(con, "voice_person")
        aliases_sql = "aliases" if "aliases" in pc else "''"
        confirmed_sql = "confirmed_at" if "confirmed_at" in pc else "NULL"
        try:
            st["people_list"] = [{"id": r["id"], "full_name": r["full_name"], "aliases": r["aliases"] or "",
                                  "confirmed_at": r["confirmed_at"]}
                                 for r in con.execute(
                                     f"SELECT id, full_name, {aliases_sql} AS aliases, {confirmed_sql} AS confirmed_at "
                                     "FROM voice_person WHERE confirmed = 1 ORDER BY full_name LIMIT 500")]
        except sqlite3.Error:
            st["people_list"] = []
        sc = _cols(con, "voice_sample")
        if "embedding_model" in sc:
            st["embedding_models"] = {m or "не указана": n for m, n in con.execute(
                "SELECT embedding_model, COUNT(*) FROM voice_sample GROUP BY embedding_model")}
        if "origin_project" in sc:
            st["by_project"] = {m or "не указан": n for m, n in con.execute(
                "SELECT origin_project, COUNT(*) FROM voice_sample GROUP BY origin_project")}
        if "created_at" in sc:
            st["last_sample_at"] = one("SELECT MAX(created_at) FROM voice_sample")
        if {"origin_project", "origin_ref", "seconds", "created_at"} <= sc:
            st["recordings"] = [
                {"project": r["origin_project"] or "", "ref": r["origin_ref"] or "", "samples": r["n"],
                 "seconds": round(float(r["sec"] or 0), 1), "last": r["last"]}
                for r in con.execute("SELECT origin_project, origin_ref, COUNT(*) AS n, SUM(seconds) AS sec, "
                                     "MAX(created_at) AS last FROM voice_sample "
                                     "GROUP BY origin_project, origin_ref ORDER BY MAX(created_at) DESC LIMIT 50")]
        else:
            st["recordings"] = []
        st["ok"] = True
        st["detail"] = "База доступна, только чтение."
    except sqlite3.Error as e:
        st["detail"] = f"Ошибка чтения базы: {type(e).__name__}"
    finally:
        con.close()
    return st
