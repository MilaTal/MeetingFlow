"""Хранилище ядра на SQLite (stdlib, без ORM).

Решения, перенесённые из проектов:
- Замок на ДАННЫЕ, а не на кнопку: все записи идут через один RLock
  (ERP write_serial: из 10 одновременных правок протокола 7 терялись).
- Миграция «добавить недостающие колонки» при старте (_ensure_columns),
  без DROP; новые колонки только с умолчанием (NOT NULL без умолчания
  ронял вставку на старой базе — урок Планёрки 01.10).
- Регистр кириллицы сравнивается в Python, а не через SQLite lower()/LIKE.
- Внутренний id никогда не показывается: номер для человека — с 1.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA: dict[str, dict[str, str]] = {
    "projects": {"id": "INTEGER PRIMARY KEY", "name": "TEXT NOT NULL", "theme": "TEXT NOT NULL",
                 "created_at": "TEXT"},
    "meetings": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "date": "TEXT", "label": "TEXT",
                 "protocol_md": "TEXT", "protocol_built_at": "TEXT", "built_from": "TEXT DEFAULT '[]'",
                 "leader": "TEXT", "review_notes": "TEXT DEFAULT '[]'"},
    "sources": {"id": "INTEGER PRIMARY KEY", "meeting_id": "INTEGER", "name": "TEXT", "kind": "TEXT",
                "text": "TEXT", "digest": "TEXT", "removed_at": "TEXT", "removed_reason": "TEXT",
                "created_at": "TEXT", "local_asr": "INTEGER DEFAULT 0",
                # сведения распознавания: точка, модель, устройство, времена реплик, говорящие (26.10.2026)
                "meta": "TEXT DEFAULT '{}'"},   # расшифровка нашим распознаванием
    "people": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "full_name": "TEXT",
               "role": "TEXT DEFAULT ''", "department": "TEXT DEFAULT ''", "aliases": "TEXT DEFAULT '[]'",
               "external": "INTEGER DEFAULT 0", "confirmed": "INTEGER DEFAULT 1",
               "organization": "TEXT DEFAULT ''", "known_marks": "TEXT DEFAULT '[]'"},
    "tasks": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "description": "TEXT",
              "assignee": "TEXT", "status": "TEXT DEFAULT 'active'", "due_date": "TEXT", "due_kind": "TEXT",
              "date_set": "TEXT", "date_closed": "TEXT", "source_meeting_id": "INTEGER",
              "source_quote": "TEXT DEFAULT ''", "last_comment": "TEXT DEFAULT ''",
              # «под вопросом» — причина сомнения, служебная: в документы не идёт, видна только администраторам (15.10.26)
              "doubt_reason": "TEXT DEFAULT ''"},
    # версии протокола (находки стенда 43, 47; решение владельца 15.10.26): прежняя не затирается; model — модель,
    # которая написала текст (ответившая точка маршрута), а не настроенная основная
    "protocol_versions": {"id": "INTEGER PRIMARY KEY", "meeting_id": "INTEGER", "version": "INTEGER",
                          "protocol_md": "TEXT", "model": "TEXT DEFAULT ''", "built_at": "TEXT"},
    # очередь сборок (находки стенда 41, 19): одна за раз, по датам встреч; строка «идёт» — запись о начале
    "build_queue": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "meeting_id": "INTEGER",
                    "meeting_date": "TEXT DEFAULT ''", "status": "TEXT", "reason": "TEXT DEFAULT ''",
                    "not_before": "TEXT", "created_at": "TEXT", "started_at": "TEXT", "finished_at": "TEXT",
                    "pid": "INTEGER", "result": "TEXT", "by": "TEXT DEFAULT ''", "attempts": "INTEGER DEFAULT 0"},
    "task_history": {"id": "INTEGER PRIMARY KEY", "task_id": "INTEGER", "old_status": "TEXT",
                     "new_status": "TEXT", "source": "TEXT", "evidence_quote": "TEXT DEFAULT ''",
                     "changed_by": "TEXT DEFAULT ''", "at": "TEXT"},
    "cards": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "meeting_id": "INTEGER",
              "kind": "TEXT", "title": "TEXT", "payload": "TEXT DEFAULT '{}'",
              "status": "TEXT DEFAULT 'open'", "resolution": "TEXT DEFAULT ''",
              "created_at": "TEXT", "resolved_at": "TEXT"},
    "operator_rules": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "kind": "TEXT", "key": "TEXT",
                       "value": "TEXT DEFAULT ''", "pending_answers": "TEXT DEFAULT '[]'",
                       "active": "INTEGER DEFAULT 0", "applied_count": "INTEGER DEFAULT 0",
                       "created_at": "TEXT", "expires_at": "TEXT", "revoked_at": "TEXT"},
    # единицы встречи (перенесены из Проекта ERP 03.10.26): решение, договорённость, уточнение,
    # открытый вопрос, веха, задача — с цитатой (берёт код), ролями и закрытием
    "units": {"id": "INTEGER PRIMARY KEY", "meeting_id": "INTEGER", "kind": "TEXT", "text": "TEXT",
              "quote": "TEXT", "status": "TEXT DEFAULT 'open'", "closed_quote": "TEXT DEFAULT ''",
              "task_id": "INTEGER", "project_id": "INTEGER", "line_from": "INTEGER", "line_to": "INTEGER",
              "ts": "TEXT", "planned_date": "TEXT", "roles": "TEXT DEFAULT '[]'", "closed_meeting_id": "INTEGER",
              "closed_note": "TEXT DEFAULT ''", "closed_how": "TEXT DEFAULT ''", "prev_status": "TEXT DEFAULT ''",
              "extracted_by": "TEXT DEFAULT ''", "decided_by": "TEXT DEFAULT ''", "created_at": "TEXT",
              "updated_at": "TEXT"},
    "decisions": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "what": "TEXT", "decision": "TEXT",
                  "why": "TEXT", "at": "TEXT"},
    # настройки: project_id = NULL — общие для машины (база голосов)
    "settings": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "key": "TEXT", "value": "TEXT",
                 "updated_at": "TEXT", "updated_by": "TEXT DEFAULT ''"},
    # вход по паролю (как в ERP и Планёрке): пароль — только scrypt-хэш, сессия — только sha256 токена
    "accounts": {"id": "INTEGER PRIMARY KEY", "login": "TEXT", "full_name": "TEXT", "role": "TEXT",
                 "password_hash": "TEXT DEFAULT ''", "active": "INTEGER DEFAULT 1", "failed_attempts": "INTEGER DEFAULT 0",
                 "locked_until": "TEXT", "last_login_at": "TEXT", "created_at": "TEXT"},
    "sessions": {"id": "INTEGER PRIMARY KEY", "token_hash": "TEXT", "account_id": "INTEGER", "created_at": "TEXT",
                 "expires_at": "TEXT"},
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._depth = 0
        self._ensure_schema()

    # --- служебное -------------------------------------------------------
    def _ensure_schema(self) -> None:
        with self._lock:
            for table, cols in SCHEMA.items():
                body = ", ".join(f"{c} {t}" for c, t in cols.items())
                self._conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({body})")
                have = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                for c, t in cols.items():
                    if c not in have:
                        if "NOT NULL" in t and "DEFAULT" not in t:
                            t = t.replace("NOT NULL", "")  # старая база не должна падать
                        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")
            self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Вложенные tx не коммитят: commit/rollback делает только внешний
        уровень (находка ревью: вложенный insert коммитил раньше времени)."""
        with self._lock:
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.rollback()
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self._conn.commit()

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def insert(self, table: str, **vals: Any) -> int:
        if table not in SCHEMA:
            raise ValueError(f"unknown table {table}")
        cols = [c for c in vals if c in SCHEMA[table]]
        args = tuple(json.dumps(vals[c], ensure_ascii=False) if isinstance(vals[c], (dict, list)) else vals[c]
                     for c in cols)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        with self.tx() as c:
            return int(c.execute(sql, args).lastrowid)

    def update(self, table: str, row_id: int, **vals: Any) -> None:
        cols = [c for c in vals if c in SCHEMA[table] and c != "id"]
        if not cols:
            return
        args = tuple(json.dumps(vals[c], ensure_ascii=False) if isinstance(vals[c], (dict, list)) else vals[c]
                     for c in cols)
        with self.tx() as c:
            c.execute(f"UPDATE {table} SET {', '.join(f'{x}=?' for x in cols)} WHERE id=?", args + (row_id,))

    def delete(self, table: str, row_id: int) -> None:
        if table not in SCHEMA:
            raise ValueError(f"unknown table {table}")
        with self.tx() as c:
            c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))

    def get(self, table: str, row_id: int) -> dict[str, Any] | None:
        rows = self.q(f"SELECT * FROM {table} WHERE id=?", (row_id,))
        return rows[0] if rows else None

    # --- настройки ---------------------------------------------------------
    def get_setting(self, key: str, project_id: int | None = None, default: Any = None) -> Any:
        rows = self.q("SELECT value FROM settings WHERE key=? AND project_id IS ?", (key, project_id))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except (TypeError, json.JSONDecodeError):
            return rows[0]["value"]

    def set_setting(self, key: str, value: Any, project_id: int | None = None, by: str = "") -> None:
        val = json.dumps(value, ensure_ascii=False)
        with self.tx():
            rows = self.q("SELECT id FROM settings WHERE key=? AND project_id IS ?", (key, project_id))
            if rows:
                self.update("settings", rows[0]["id"], value=val, updated_at=now(), updated_by=by)
            else:
                self.insert("settings", project_id=project_id, key=key, value=val, updated_at=now(), updated_by=by)

    def close(self) -> None:
        self._conn.close()
