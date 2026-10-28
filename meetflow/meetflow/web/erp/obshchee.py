# -*- coding: utf-8 -*-
"""Общее для слоя «ERP 1 в 1»: кто делает запрос, какой проект выбран, права, даты.

Фронт MeetFlow с 27.10.2026 — фронт Проекта ERP целиком (задание владелицы «все окна и каждое действие 1 в 1»). Он ходит
по адресам ERP (`/meetings`, `/tasks`, `/users` …) и ждёт ответы того же вида. Этот слой отвечает на них поверх ядра и
базы MeetFlow (`core/store.py`). Отличий от ERP два, оба разрешены владелицей: многопроектность (заголовок
`X-Project-Id`: номер проекта или 0 — «Все проекты») и папки-приёмники по проектам.

Личность — как в ERP (`app/deps.py`): вход выключен — заголовок `X-User-Id` (номер записи «Команды»), включён — сессия
в cookie. «Команда» ERP — таблица `accounts` MeetFlow, расширенная полями ERP (должность, отдел, внешний, организация,
подтверждение); люди «Команды» переносятся в людей проектов (`people`), по которым работает конвейер.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request

from ...core.store import Store, now

ADMIN_ROLES = {"project_admin", "super_admin"}
SHARED_PASSWORD_ROLES = {"member", "director"}
РОЛЬ_СЛОВАМИ = {"super_admin": "суперадмин", "project_admin": "администратор", "director": "директор",
                "member": "участник"}
COOKIE = "mf_session"
_USER_ID_RE = re.compile(r"[0-9]{1,18}")


def ru_date(value: Any) -> str:
    """Дата для человека — дд.мм.гггг (правило владелицы 09.10.2026)."""
    d = to_date(value)
    return f"{d.day:02d}.{d.month:02d}.{d.year}" if d else ""


def to_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d.%m.%Y", 10)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


def iso_dt(value: Any) -> str | None:
    """Время в ответе — ISO без зоны, как у ERP (фронт сам приводит к дд.мм.гггг чч:мм)."""
    if not value:
        return None
    return str(value).replace(" ", "T")[:19]


def loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class Ctx:
    """Всё, чем живут ручки слоя: база, конвейер, тема, вход, очередь сборок, забор из папок."""

    def __init__(self, *, store: Store, pipe, theme, accounts, queue, intake, backups, journal: str, app_dir):
        self.store, self.pipe, self.theme, self.accounts = store, pipe, theme, accounts
        self.queue, self.intake, self.backups, self.journal, self.app_dir = queue, intake, backups, journal, app_dir
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ личность
    def _row_user(self, row: dict | None) -> dict | None:
        if not row:
            return None
        return dict(row)

    def user(self, request: Request) -> dict | None:
        """Кто делает запрос; None — никто (вход выключен и заголовка нет)."""
        if self.accounts.auth_required():
            return self._row_user(self.accounts.by_session(request.cookies.get(COOKIE)))
        raw = (request.headers.get("x-user-id") or "").strip()
        if raw and _USER_ID_RE.fullmatch(raw):
            row = self.store.get("accounts", int(raw))
            if row and row.get("active", 1):
                return self._row_user(row)
        return None

    def need_user(self, request: Request) -> dict:
        u = self.user(request)
        if u is None:
            if self.accounts.auth_required():
                raise HTTPException(401, "Требуется вход")
            raise HTTPException(401, "Нужен заголовок X-User-Id — кто выполняет действие")
        if u.get("must_change_password") and self.accounts.auth_required() \
                and request.url.path not in ("/auth/change-password", "/auth/me", "/auth/logout"):
            raise HTTPException(403, "Сначала смените временный пароль", headers={"X-Auth-Reason": "password_change_required"})
        return u

    def need_admin(self, request: Request) -> dict:
        u = self.need_user(request)
        if u.get("role") not in ADMIN_ROLES:
            raise HTTPException(403, "Действие доступно администратору проекта")
        return u

    def need_super(self, request: Request) -> dict:
        u = self.need_user(request)
        if u.get("role") != "super_admin":
            raise HTTPException(403, "Раздел доступен суперадминистратору")
        return u

    @staticmethod
    def is_admin(u: dict | None) -> bool:
        return bool(u) and u.get("role") in ADMIN_ROLES

    @staticmethod
    def name(u: dict | None) -> str:
        return (u or {}).get("full_name") or (u or {}).get("login") or "система"

    # ------------------------------------------------------------------ проект
    def project(self, request: Request) -> int | None:
        """Выбранный проект: номер или None («Все проекты»). Нет заголовка — тоже «Все проекты»."""
        raw = (request.headers.get("x-project-id") or request.query_params.get("project_id") or "").strip()
        if not raw or not raw.isdigit() or raw == "0":
            return None
        pid = int(raw)
        return pid if self.store.get("projects", pid) else None

    def project_for_create(self, request: Request) -> int:
        """Создать встречу, задачу или источник можно только в конкретном проекте."""
        pid = self.project(request)
        if pid is None:
            rows = self.store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0 ORDER BY id")
            if len(rows) == 1:
                return rows[0]["id"]
            raise HTTPException(400, "Выберите проект вверху левой панели: «Все проекты» показывают, но не заводят.")
        return pid

    # Проект и подпроекты (справочник ЛМ 6c6933f, `projects.parent_id`; возвращено 27.10.2026): подпроект — запись проекта
    # с надпроектом. Выбранный проект показывается вместе со всеми своими подпроектами, выбранный подпроект — сам по себе.
    def family(self, pid: int | None) -> list[int]:
        """Проект и все его подпроекты (любой глубины), включая архивные: записи архивного подпроекта не пропадают."""
        if not pid:
            return []
        rows = self.store.q("SELECT id, parent_id FROM projects")
        kids: dict = {}
        for r in rows:
            kids.setdefault(r["parent_id"], []).append(r["id"])
        out, todo = [], [pid]
        while todo:
            x = todo.pop()
            if x in out:
                continue
            out.append(x)
            todo += kids.get(x, [])
        return out

    def root_of(self, pid: int | None) -> int | None:
        seen = set()
        while pid and pid not in seen:
            seen.add(pid)
            p = self.store.get("projects", pid) or {}
            if not p.get("parent_id"):
                return pid
            pid = p["parent_id"]
        return pid

    def project_names(self, pid: int | None) -> tuple[str, str]:
        """(проект, подпроект): у записи подпроекта — название надпроекта верхнего уровня и своё; у проекта — («имя», «»)."""
        p = self.store.get("projects", pid or 0) or {}
        if not p:
            return "", ""
        root = self.root_of(pid)
        if root == pid:
            return p.get("name") or "", ""
        return (self.store.get("projects", root) or {}).get("name") or "", p.get("name") or ""

    def project_label(self, pid: int | None) -> str:
        """«Проект – Подпроект» или «Проект» — приставка формулировки и подпись в отборах «Все проекты»."""
        a, b = self.project_names(pid)
        return f"{a} – {b}" if b else a

    def scope_sql(self, request: Request, col: str = "project_id") -> tuple[str, tuple]:
        ids = self.family(self.project(request))
        if not ids:
            return "", ()
        return f" AND {col} IN ({','.join('?' * len(ids))})", tuple(ids)

    def meeting_or_404(self, mid: int) -> dict:
        m = self.store.get("meetings", mid)
        if not m or m.get("deleted_at"):
            raise HTTPException(404, "Встреча не найдена")
        return m

    def task_or_404(self, tid: int) -> dict:
        t = self.store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена")
        return t

    # ------------------------------------------------------------------ служебное
    def sys_msg(self, context: str, message: str, source: str = "auth") -> None:
        """Системное сообщение («Параметры системы → Системные сообщения») — техническая карточка MeetFlow."""
        try:
            self.pipe.cards.open(None, "technical", context[:200], {"message": message, "source": source})
        except Exception:  # noqa: BLE001 — журнал не должен ронять действие
            pass

    def setting(self, key: str, default: Any = None, project_id: int | None = None) -> Any:
        return self.store.get_setting(key, project_id, default)

    def set_setting(self, key: str, value: Any, by: str = "", project_id: int | None = None) -> None:
        self.store.set_setting(key, value, project_id, by)


def today_iso() -> str:
    return date.today().isoformat()


def plus_days(iso: str, days: int) -> str:
    d = to_date(iso) or date.today()
    return (d + timedelta(days=days)).isoformat()


__all__ = ["Ctx", "ADMIN_ROLES", "SHARED_PASSWORD_ROLES", "РОЛЬ_СЛОВАМИ", "COOKIE", "ru_date", "to_date", "iso_dt",
           "loads", "now", "today_iso", "plus_days"]
