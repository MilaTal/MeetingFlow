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
                 "created_at": "TEXT", "aliases": "TEXT DEFAULT '[]'", "active": "INTEGER DEFAULT 1",
                 "archived": "INTEGER DEFAULT 0", "parent_id": "INTEGER",
                 # «Общие встречи» — служебный проект встреч без проекта; удалённый проект скрыт везде (Доработка 2,
                 # 28.10.2026): его встречи уходят в «Общие встречи», запись остаётся для истории
                 "general": "INTEGER DEFAULT 0", "deleted": "INTEGER DEFAULT 0"},
    "meetings": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "date": "TEXT", "label": "TEXT",
                 "protocol_md": "TEXT", "protocol_built_at": "TEXT", "built_from": "TEXT DEFAULT '[]'",
                 "leader": "TEXT", "review_notes": "TEXT DEFAULT '[]'",
                 # план встречи — как в ERP: готовится до встречи из прошлого протокола, задач и материалов
                 "plan_md": "TEXT", "plan_built_at": "TEXT", "topic": "TEXT DEFAULT ''",
                 # экраны ERP 1 в 1 (27.10.2026): состояние встречи, вторая на дату по подтверждению, ключ повтора
                 # создания, ведущий вручную, сводки «Свести в одну», ручная правка протокола и плана, итог сборки
                 "status": "TEXT DEFAULT 'scheduled'", "second_same_day": "INTEGER DEFAULT 0", "request_key": "TEXT",
                 "created_at": "TEXT", "leader_user_id": "INTEGER", "leader_source": "TEXT", "leader_note": "TEXT",
                 "leader_speaker": "TEXT", "merged": "TEXT DEFAULT '[]'", "protocol_hand_edited": "INTEGER DEFAULT 0",
                 "plan_hand_edited": "INTEGER DEFAULT 0", "build_note": "TEXT DEFAULT ''",
                 "plan_sources": "TEXT DEFAULT '[]'",
                 # тема планёрки встречи (как ERP 24.10.2026): номер темы, откуда (день недели / вручную), когда и кто
                 "topic_id": "INTEGER", "topic_source": "TEXT DEFAULT ''", "topic_set_at": "TEXT",
                 "topic_set_by": "TEXT DEFAULT ''",
                 # проект записи из общей папки не определён (27.10.2026): сборка ждёт выбора проекта человеком
                 "project_pending": "INTEGER DEFAULT 0",
                 # как узнан проект записи из папки-приёмника (Доработка 2, 28.10.2026): «по имени файла», «по содержанию:
                 # названо 7 раз», «не узнан — в общих встречах»; удалённая встреча: когда и что вернуть при отмене
                 "project_how": "TEXT DEFAULT ''", "deleted_at": "TEXT", "deleted_info": "TEXT DEFAULT '{}'"},
    # «Темы планёрок» (основа из ERP, перенос 27.10.2026): самостоятельная сущность — дни недели (по умолчанию всем
    # встречам этих дней), свои разделы протокола, названия в шапке секретаря, объекты, подсказка сборки, переходящие
    # задачи с прошлой встречи той же темы; удаления нет — выключается
    "meeting_topics": {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "weekdays": "TEXT DEFAULT '[]'",
                       "sections": "TEXT DEFAULT '[]'", "head_names": "TEXT DEFAULT '[]'", "objects": "TEXT DEFAULT '[]'",
                       "hint": "TEXT DEFAULT ''", "carry_same_topic": "INTEGER DEFAULT 0", "is_active": "INTEGER DEFAULT 1",
                       "created_at": "TEXT", "updated_by": "TEXT DEFAULT ''"},
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
              "doubt_reason": "TEXT DEFAULT ''",
              # пометка «оперативная» — ставит человек одним нажатием или протокол секретаря (как ERP, 26.10.2026)
              "operational": "INTEGER DEFAULT 0",
              # экраны ERP 1 в 1 (27.10.2026): версия строки — замок на данных (две правки разом: вторая получает отказ),
              # время правки, кто оставил последний комментарий и когда, первоначальный срок переходящей задачи, подпроект
              "version": "INTEGER DEFAULT 1", "updated_at": "TEXT", "last_comment_by": "TEXT DEFAULT ''",
              "last_comment_date": "TEXT", "due_original": "TEXT", "subproject": "TEXT DEFAULT ''",
              "status_detail": "TEXT DEFAULT ''"},
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
                 "locked_until": "TEXT", "last_login_at": "TEXT", "created_at": "TEXT",
                 # «Команда» как в ERP (27.10.2026, экраны 1 в 1): учётная запись — это и запись «Команды»; логин и
                 # пароль необязательны, у участника — общий пароль (хэш в настройке shared_password_hash)
                 "position": "TEXT DEFAULT ''", "department": "TEXT DEFAULT ''", "project_role": "TEXT DEFAULT ''",
                 "external": "INTEGER DEFAULT 0", "organization": "TEXT DEFAULT ''", "confirmed": "INTEGER DEFAULT 1",
                 "name_short_reason": "TEXT DEFAULT ''", "confirmed_source": "TEXT DEFAULT ''",
                 "leads_meetings": "INTEGER DEFAULT 0", "must_change_password": "INTEGER DEFAULT 0",
                 "temp_expires_at": "TEXT"},
    # реестр корректировок документов (как ERP и Планёрка, 27.10.2026): каждая правка протокола и плана человеком —
    # кто, когда, где, было и стало; признак «исправление ошибки обработки, не переписывание факта»
    "doc_corrections": {"id": "INTEGER PRIMARY KEY", "meeting_id": "INTEGER", "doc": "TEXT", "who": "TEXT",
                        "at": "TEXT", "place": "TEXT", "old_text": "TEXT DEFAULT ''", "new_text": "TEXT DEFAULT ''",
                        "fix": "INTEGER DEFAULT 1"},
    # «Возможные поручения» (узкий порог, как ERP и Планёрка 24.10.2026): похоже на поручение, но без адресата — не
    # задача реестра, а строка здесь; «В задачу» заводит обычную задачу встречи, «Не задача» закрывает, срок — истекает
    "possible_assignments": {"id": "INTEGER PRIMARY KEY", "project_id": "INTEGER", "meeting_id": "INTEGER",
                             "meeting_date": "TEXT", "text": "TEXT", "quote": "TEXT DEFAULT ''", "quote_ref": "TEXT DEFAULT ''",
                             "responsible": "TEXT DEFAULT ''", "due": "TEXT DEFAULT ''", "reason": "TEXT",
                             "state": "TEXT DEFAULT 'новое'", "task_id": "INTEGER", "decided_by": "TEXT DEFAULT ''",
                             "decided_at": "TEXT", "created_at": "TEXT"},
    "sessions": {"id": "INTEGER PRIMARY KEY", "token_hash": "TEXT", "account_id": "INTEGER", "created_at": "TEXT",
                 "expires_at": "TEXT", "remember": "INTEGER DEFAULT 0", "via_shared": "INTEGER DEFAULT 0"},
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
        self._closed = False
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
            if self._closed:
                raise RuntimeError("база уже закрыта")
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
            # Фоновый поток очереди может проснуться после закрытия базы (тесты, остановка): отвечаем пусто,
            # а не лезем в закрытое соединение — это давало падение процесса на уровне C.
            if self._closed:
                return []
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
        with self._lock:
            self._closed = True
            self._conn.close()
