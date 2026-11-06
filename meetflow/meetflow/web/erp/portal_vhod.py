# -*- coding: utf-8 -*-
"""Приём входа от портала единого входа — этап 2 (задание владелицы 06.11.2026; план «19 Единый вход», раздел 6.5).

Те же адреса и то же поведение, что у Проекта ERP и Планёрки (`app/routers/portal_sso.py` там), поверх учётных записей
MeetFlow (`accounts`). Отличие одно: в MeetFlow нет связки «запись ↔ общий человек», поэтому человек от портала ищется
по логину, а для списка портала (`/auth/portal/accounts`) номер общей «Команды» берётся по точному совпадению ФИО —
только если такой человек в общей «Команде» один и он внутренний. Похожие имена не сопоставляются (правило 03.10.2026:
спорное имя не подставляется), е и ё равны (правило 26.10.2026).

Как идёт переход. Портал ведёт браузер на `GET /auth/portal?code=…`; MeetFlow по внутреннему адресу портала меняет код на
человека (`/api/sso/exchange`, со своим секретом) и открывает свою обычную сессию `mf_session` на 12 часов, без «помнить»
(вопрос 7: «помнить 30 дней» только на портале). Вход выключен — человек подставляется в «Вы работаете как»
(`/?portal_user=`). Вход включён, а на портале человек выбран из списка без пароля — входа нет.

Обратный канал портала — только с секретом: `POST /auth/portal/logout` закрывает все сессии человека (вопрос 8),
`GET /auth/portal/accounts` — у кого логин и какая роль (вопрос 3: суперадмин любой системы — суперадмин портала).

Настройки — в `.env.local` MeetFlow, в git не попадают: `PORTAL_SECRET` (у портала — `PORTAL_SECRET_MEETFLOW`),
`PORTAL_INTERNAL_URL` (по умолчанию http://127.0.0.1:8010). Нет секрета — приёма нет, прямой вход работает как раньше.
"""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from ...connectors.team_shared import shared_path
from ...core import norm_yo
from .bezopasnost import normalize_login
from .obshchee import SHARED_PASSWORD_ROLES, Ctx

SYSTEM = "meetflow"
TIMEOUT = 2.0
OPEN = ("/auth/portal", "/auth/portal/logout", "/auth/portal/accounts", "/auth/portal/passwords")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


class PortalPasswordsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared_hash: str | None = Field(default=None, max_length=300)
    super_admins: list[dict] = Field(default_factory=list, max_length=500)


def _is_scrypt(value: str | None) -> bool:
    parts = (value or "").split("$")
    return len(parts) == 6 and parts[0] == "scrypt"


class PortalLogoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str = Field(default="", max_length=100)
    login: str | None = Field(default="", max_length=200)


def _secret() -> str:
    return (os.environ.get("PORTAL_SECRET") or "").strip()


def _portal_url() -> str:
    return (os.environ.get("PORTAL_INTERNAL_URL") or "http://127.0.0.1:8010").strip().rstrip("/")


def enabled() -> bool:
    return bool(_secret())


def _check_secret(request: Request) -> None:
    secret = _secret()
    if not secret:
        raise HTTPException(404, "Not Found")
    header = (request.headers.get("authorization") or "").strip()
    presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(secret.encode("utf-8"), presented.encode("utf-8")):
        raise HTTPException(401, "Портал не опознан")


def _portal_call(path: str, body: dict) -> dict | None:
    req = urllib.request.Request(_portal_url() + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + _secret(), "Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read(100_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _name_key(name: str | None) -> str:
    return " ".join(norm_yo.ключ(name or "").split())


def _team_uids_by_name() -> dict[str, str]:
    """ФИО → номер общей «Команды», только однозначные внутренние. Файл открывается только на чтение."""
    path = shared_path()
    if path is None or not path.is_file():
        return {}
    try:
        con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT uid, full_name, COALESCE(is_external, 0) FROM people").fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    seen: dict[str, list[tuple[str, int]]] = {}
    for uid, name, ext in rows:
        seen.setdefault(_name_key(name), []).append((uid, int(ext)))
    return {k: v[0][0] for k, v in seen.items() if k and len(v) == 1 and v[0][1] == 0}


def notify_logout(account: dict) -> None:
    """Выход в MeetFlow — сообщить порталу фоном: выход не ждёт портал, недоступный портал выйти не мешает."""
    if not enabled():
        return
    body = {"system": SYSTEM, "uid": "", "login": account.get("login") or ""}
    threading.Thread(target=_portal_call, args=("/api/sso/logout", body), daemon=True,
                     name="portal-logout-notify").start()


def mount(r: APIRouter, ctx: Ctx) -> None:
    store = ctx.store

    def find_account(login: str | None) -> dict | None:
        key = normalize_login(login)
        if not key:
            return None
        rows = store.q("SELECT * FROM accounts WHERE lower(login)=?", (key,))
        u = rows[0] if len(rows) == 1 else None
        if u is None or not u.get("active", 1) or u.get("external"):
            return None
        return u

    @r.get("/auth/portal")
    def accept_code(request: Request, code: str = ""):
        if not enabled() or not code or len(code) > 200:
            return RedirectResponse("/", status_code=303)
        person = _portal_call("/api/sso/exchange", {"system": SYSTEM, "code": code})
        if not person or not isinstance(person.get("uid"), str):
            return RedirectResponse("/", status_code=303)
        u = find_account(person.get("login"))
        if u is None:
            return RedirectResponse("/", status_code=303)
        if not ctx.accounts.auth_required():
            return RedirectResponse(f"/?portal_user={u['id']}", status_code=303)
        if not person.get("verified"):
            return RedirectResponse("/", status_code=303)
        response = RedirectResponse("/", status_code=303)
        ctx.start_session(u, request, response, via_shared=(u.get("role") or "member") in SHARED_PASSWORD_ROLES,
                          remember=False)
        return response

    @r.post("/auth/portal/logout")
    def portal_logout(payload: PortalLogoutIn, request: Request):
        _check_secret(request)
        u = find_account(payload.login)
        return {"closed": ctx.revoke_sessions(u["id"]) if u else 0}

    @r.post("/auth/portal/passwords")
    def portal_passwords(payload: PortalPasswordsIn, request: Request):
        """Пароли живут на портале, портал раздаёт тот же хэш (решение владелицы 06.11.2026, вопрос 1): общий пароль и
        личные суперадминов. Сменился общий — выходят вошедшие по общему; личный — все сессии суперадмина."""
        _check_secret(request)
        result = {"shared": False, "super_admins": 0}
        if payload.shared_hash is not None:
            if not _is_scrypt(payload.shared_hash):
                raise HTTPException(400, "Не хэш пароля")
            if payload.shared_hash != store.get_setting("shared_password_hash"):
                store.set_setting("shared_password_hash", payload.shared_hash, None, "портал единого входа")
                for s in store.q("SELECT id FROM sessions WHERE COALESCE(via_shared,0)=1"):
                    store.delete("sessions", s["id"])
                result["shared"] = True
        for item in payload.super_admins:
            u = find_account((item or {}).get("login"))
            value = (item or {}).get("hash")
            if u is None or u.get("role") != "super_admin" or not _is_scrypt(value) or u.get("password_hash") == value:
                continue
            store.update("accounts", u["id"], password_hash=value, must_change_password=0, temp_expires_at=None)
            ctx.revoke_sessions(u["id"])
            result["super_admins"] += 1
        return result

    @r.get("/auth/portal/accounts")
    def portal_accounts(request: Request):
        _check_secret(request)
        by_name = _team_uids_by_name()
        rows = []
        for u in store.q("SELECT * FROM accounts WHERE COALESCE(login, '') <> ''"):
            if not u.get("active", 1) or u.get("external"):
                continue
            uid = by_name.get(_name_key(u.get("full_name")))
            if uid:
                rows.append({"uid": uid, "login": normalize_login(u["login"]), "access_role": u.get("role") or "member"})
        return rows

