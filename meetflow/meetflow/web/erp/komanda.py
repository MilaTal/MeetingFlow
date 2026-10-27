# -*- coding: utf-8 -*-
"""«Команда» и вход — адреса ERP `/auth/*` и `/users/*` (перенос 27.10.2026, экраны 1 в 1).

Правила — те же, что в ERP (`app/routers/auth.py`, `app/routers/users.py`): общий пароль у участников, личный у
администраторов и суперадмина; «Первый вход — завести аккаунт» привязывает логин; временный пароль 24 часа со сменой при
первом входе; назначать администратора — только суперадмин; последнего носителя админской роли не понизить, не отключить
и не удалить; внешним доступ не выдаётся; логин видит и меняет только суперадмин; дубль ФИО (и с перестановкой фамилии и
имени) не заводится. Запись «Команды» — строка `accounts`; подтверждённые люди переносятся в людей проектов (`people`).
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...core import norm_yo
from ...core.store import now
from . import names, vneshnie_kontakty
from .bezopasnost import (generate_temp_password, hash_password, normalize_login, validate_login, validate_new_password,
                          verify_password)
from .obshchee import ADMIN_ROLES, COOKIE, SHARED_PASSWORD_ROLES, РОЛЬ_СЛОВАМИ, Ctx

MAX_FAILED = 5
LOCK = timedelta(minutes=2)
IP_WINDOW, IP_MAX = 600, 20
BAD_CREDENTIALS = "Неверный логин или пароль"
LOCKED_MESSAGE = "Слишком много неудачных попыток. Учётная запись временно заблокирована — повторите через 2 минуты."
TEMP_TTL = timedelta(hours=24)
TEMP_EXPIRED = "Временный пароль истёк (он действует 24 часа) — попросите суперадмина сбросить пароль ещё раз"
EXTERNAL_NO_ACCESS = "Внешним участникам доступ не выдаётся"
SHARED_KEY = "shared_password_hash"
ROLE_NAMES = {"super_admin": "супер-администратор", "project_admin": "администратор проекта", "member": "участник"}
GRANT_REPEAT_SECONDS = 10
REMEMBER = timedelta(days=30)
SESSION = timedelta(hours=12)


class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(InModel):
    login: str = Field(max_length=200)
    password: str = Field(max_length=200)
    remember: bool = False


class FirstLoginIn(InModel):
    user_id: int
    login: str = Field(max_length=200)
    password: str = Field(max_length=200)
    remember: bool = False


class ChangePasswordIn(InModel):
    old_password: str = Field(default="", max_length=200)
    new_password: str = Field(max_length=200)


class ResetPasswordIn(InModel):
    user_id: int


class ModeIn(InModel):
    auth_required: bool
    current_password: str | None = Field(default=None, max_length=200)


ROLES = ("member", "project_admin", "super_admin", "director")


class UserCreate(InModel):
    full_name: str = Field(max_length=200)
    email: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=1000)
    department: str | None = Field(default=None, max_length=200)
    access_role: str = "member"
    project_role: str | None = Field(default=None, max_length=1000)
    is_external: bool = False
    organization: str | None = Field(default=None, max_length=200)
    is_confirmed: bool = True
    name_short_reason: str | None = Field(default=None, max_length=300)
    leads_meetings: bool = False


class UserPatch(InModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=1000)
    department: str | None = Field(default=None, max_length=200)
    access_role: str | None = None
    project_role: str | None = Field(default=None, max_length=1000)
    is_external: bool | None = None
    organization: str | None = Field(default=None, max_length=200)
    is_confirmed: bool | None = None
    name_short_reason: str | None = Field(default=None, max_length=300)
    leads_meetings: bool | None = None
    login: str | None = Field(default=None, max_length=200)


class AccessGrantIn(InModel):
    email: str | None = Field(default=None, max_length=200)


class SetPasswordIn(InModel):
    password: str = Field(max_length=200)


class ActiveIn(InModel):
    is_active: bool


def _role_ok(role: str | None) -> str:
    r = (role or "member").strip()
    if r not in ROLES:
        raise HTTPException(422, "Неизвестная роль доступа")
    return r


def has_access(u: dict) -> bool:
    if u.get("external"):
        return False
    if (u.get("role") or "member") in SHARED_PASSWORD_ROLES:
        return bool(u.get("login"))
    return bool(u.get("login") and u.get("password_hash"))


def user_out(u: dict, viewer: dict | None) -> dict:
    """Запись «Команды» наружу — поля `schemas.UserOut` ERP. Логин и почту видит только суперадмин."""
    out = {"id": u["id"], "full_name": u.get("full_name") or "", "email": u.get("login") or None,
           "role": u.get("position") or None, "department": u.get("department") or None,
           "is_active": bool(u.get("active", 1)), "access_role": u.get("role") or "member",
           "has_access": has_access(u), "is_confirmed": bool(u.get("confirmed", 1)),
           "project_role": u.get("project_role") or None, "is_external": bool(u.get("external")),
           "organization": u.get("organization") or None, "name_short_reason": u.get("name_short_reason") or None,
           "confirmed_source": u.get("confirmed_source") or None, "leads_meetings": bool(u.get("leads_meetings")),
           "login": u.get("login") or None}
    if not viewer or viewer.get("role") != "super_admin":
        out.pop("login", None)
        out["email"] = None
    return out


def me_dict(u: dict) -> dict:
    role = u.get("role") or "member"
    return {"id": u["id"], "full_name": u.get("full_name") or "", "role": u.get("position") or None,
            "department": u.get("department") or None, "access_role": role, "login": u.get("login") or None,
            "role_words": РОЛЬ_СЛОВАМИ.get(role, "участник"), "must_change_password": bool(u.get("must_change_password"))}


def _norm_name(s: str | None) -> str:
    return " ".join((s or "").replace("ё", "е").replace("Ё", "Е").lower().split())


def komanda_v_lyudi(store) -> int:
    """Подтверждённые люди «Команды» — в людей каждого проекта (конвейер ищет исполнителей там). Идемпотентно: человек с
    тем же ФИО («е» = «ё», регистр, пробелы) второй раз не заводится; должность, отдел и организация обновляются."""
    team = [u for u in store.q("SELECT * FROM accounts WHERE COALESCE(active,1)=1") if u.get("confirmed", 1)]
    good = []
    for u in team:
        fio = (u.get("full_name") or "").strip()
        if not fio:
            continue
        if u.get("external"):
            if (u.get("organization") or "").strip():
                good.append(u)
        elif names.check_full_name(fio).ok:
            good.append(u)
    added = 0
    for p in store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0"):
        have = {_norm_name(r["full_name"]): r for r in
                store.q("SELECT id, full_name, role, department, organization FROM people WHERE project_id=?", (p["id"],))}
        for u in good:
            key = _norm_name(u["full_name"])
            row = have.get(key)
            if row is None:
                store.insert("people", project_id=p["id"], full_name=" ".join(u["full_name"].split()),
                             role=u.get("project_role") or u.get("position") or "", department=u.get("department") or "",
                             external=int(bool(u.get("external"))), confirmed=1, organization=u.get("organization") or "",
                             aliases="[]", known_marks="[]")
                have[key] = {"full_name": u["full_name"]}
                added += 1
            else:
                vals = {"department": u.get("department") or row.get("department") or "",
                        "organization": u.get("organization") or row.get("organization") or ""}
                if u.get("project_role") or u.get("position"):
                    vals["role"] = u.get("project_role") or u.get("position")
                if any(vals[k] != (row.get(k) or "") for k in vals):
                    store.update("people", row["id"], **vals)
    return added


def lyudi_v_komandu(store) -> int:
    """Люди проектов, которых нет в «Команде» (завела прежняя «Команда» MeetFlow или общая «Команда»), — записями «Команды»
    без логина. Подтверждение переносится как есть: неподтверждённый остаётся неподтверждённым."""
    have = {_norm_name(r["full_name"]) for r in store.q("SELECT full_name FROM accounts")}
    added = 0
    for r in store.q("SELECT * FROM people ORDER BY id"):
        key = _norm_name(r.get("full_name"))
        if not key or key in have:
            continue
        store.insert("accounts", login=None, full_name=" ".join((r["full_name"] or "").split()), role="member",
                     password_hash="", active=1, failed_attempts=0, created_at=now(), position="",
                     project_role=r.get("role") or "", department=r.get("department") or "",
                     external=int(bool(r.get("external"))), organization=r.get("organization") or "",
                     confirmed=int(bool(r.get("confirmed", 1))), confirmed_source="импорт")
        have.add(key)
        added += 1
    return added


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, accounts = ctx.store, ctx.accounts
    ip_fail: dict[str, deque] = defaultdict(deque)
    unknown: dict[str, list] = {}
    stripes = [threading.Lock() for _ in range(64)]
    create_lock, role_lock, bind_lock = threading.Lock(), threading.Lock(), threading.Lock()
    last_grant: dict[int, float] = {}
    synced = {"at": 0.0}

    def key_lock(k: str) -> threading.Lock:
        return stripes[hash(k) % len(stripes)]

    def sync(force: bool = False) -> None:
        if force or time.monotonic() - synced["at"] > 30:
            with ctx.lock:
                lyudi_v_komandu(store)
                komanda_v_lyudi(store)
            synced["at"] = time.monotonic()

    ctx.sync_team = sync
    # Пустая база в тестовом режиме: выбрать в «Вы работаете как» некого, и завести «Команду» некому. В ERP первую запись
    # кладёт засев справочников; здесь — одна служебная запись суперадминистратора без логина (в людей проектов не
    # переносится: не ФИО). Вход по паролю она не даёт — его задаёт `python -m meetflow set-password`.
    def seed_super() -> None:
        if not store.q("SELECT id FROM accounts WHERE role='super_admin'") and not accounts.auth_required():
            store.insert("accounts", login=None, full_name="Суперадминистратор", role="super_admin", password_hash="",
                         active=1, failed_attempts=0, created_at=now(), confirmed=1, confirmed_source="засев")

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def ip_blocked(ip: str) -> bool:
        q = ip_fail[ip]
        while q and q[0] < time.time() - IP_WINDOW:
            q.popleft()
        return len(q) >= IP_MAX

    def shared_hash() -> str | None:
        return store.get_setting(SHARED_KEY) or None

    def find_by_login(login: str) -> dict | None:
        key = normalize_login(login)
        if not key:
            return None
        for u in store.q("SELECT * FROM accounts WHERE login IS NOT NULL AND login != ''"):
            if normalize_login(u["login"]) == key:
                return u
        return None

    def login_owner(login: str, exclude_id: int | None = None) -> dict | None:
        u = find_by_login(login)
        return u if u and u["id"] != exclude_id else None

    def locked(u: dict) -> bool:
        return bool(u.get("locked_until") and u["locked_until"] > now())

    def temp_expired(u: dict) -> bool:
        return bool(u.get("must_change_password") and u.get("temp_expires_at") and u["temp_expires_at"] <= now())

    def password_ok(u: dict | None, password: str) -> tuple[bool, bool]:
        if u is None:
            verify_password(password, None)
            return False, False
        if (u.get("role") or "member") in SHARED_PASSWORD_ROLES:
            return verify_password(password, shared_hash()), True
        return verify_password(password, u.get("password_hash") or None), False

    def register_failure(u: dict, ip: str, context: str) -> None:
        n = int(store.get("accounts", u["id"]).get("failed_attempts") or 0) + 1
        if n >= MAX_FAILED:
            until = (datetime.now() + LOCK).strftime("%Y-%m-%dT%H:%M:%S")
            store.update("accounts", u["id"], failed_attempts=0, locked_until=until)
            ctx.sys_msg(f"{context}, логин {u.get('login')}",
                        f"Учётная запись «{u.get('login')}» ({u.get('full_name')}) заблокирована на 2 мин после "
                        f"{MAX_FAILED} неверных паролей подряд (IP {ip}). Если это были не вы или сотрудник — проверьте, "
                        "не подбирают ли пароль.")
        else:
            store.update("accounts", u["id"], failed_attempts=n)

    def unknown_locked(key: str) -> bool:
        e = unknown.get(key)
        if not e:
            return False
        if e[1] and e[1] <= time.time():
            del unknown[key]
            return False
        return bool(e[1])

    def unknown_failure(key: str) -> None:
        e = unknown.setdefault(key, [0, 0.0])
        e[0] += 1
        if e[0] >= MAX_FAILED:
            e[0], e[1] = 0, time.time() + LOCK.total_seconds()

    def start_session(u: dict, request: Request, response: Response, *, via_shared: bool, remember: bool) -> None:
        import hashlib
        import secrets
        old = request.cookies.get(COOKIE)
        if old:
            for s in store.q("SELECT id FROM sessions WHERE token_hash=?", (hashlib.sha256(old.encode()).hexdigest(),)):
                store.delete("sessions", s["id"])
        token = secrets.token_urlsafe(32)
        exp = (datetime.now() + (REMEMBER if remember else SESSION)).strftime("%Y-%m-%dT%H:%M:%S")
        store.insert("sessions", token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=u["id"],
                     created_at=now(), expires_at=exp, remember=int(remember), via_shared=int(via_shared))
        store.update("accounts", u["id"], failed_attempts=0, locked_until=None, last_login_at=now())
        response.set_cookie(COOKIE, token, max_age=int((REMEMBER if remember else SESSION).total_seconds()),
                            httponly=True, samesite="lax", path="/")

    def revoke_sessions(uid: int) -> int:
        rows = store.q("SELECT id FROM sessions WHERE account_id=?", (uid,))
        for s in rows:
            store.delete("sessions", s["id"])
        return len(rows)

    def csrf(request: Request) -> None:
        if (request.headers.get("x-requested-with") or "").lower() not in ("erp-webapp", "meetflow"):
            raise HTTPException(403, "Запрос без защитного заголовка отклонён")

    # ------------------------------------------------------------------ вход
    @r.get("/auth/mode")
    def get_mode():
        return {"auth_required": accounts.auth_required()}

    @r.post("/auth/login")
    def login(payload: LoginIn, request: Request, response: Response):
        csrf(request)
        ip = client_ip(request)
        if ip_blocked(ip):
            wait = max(1, int(ip_fail[ip][0] + IP_WINDOW - time.time()))
            raise HTTPException(429, f"Слишком много неудачных попыток входа с этого адреса. Повторите через "
                                     f"{max(1, round(wait / 60))} мин.", headers={"Retry-After": str(wait)})
        key = normalize_login(payload.login)
        with key_lock(key):
            u = find_by_login(key)
            if (u is not None and locked(u)) or (u is None and unknown_locked(key)):
                verify_password(payload.password, None)
                ip_fail[ip].append(time.time())
                raise HTTPException(429, LOCKED_MESSAGE)
            valid, shared = password_ok(u, payload.password)
            if u is None or not valid or not u.get("active", 1) or u.get("external"):
                ip_fail[ip].append(time.time())
                if u is not None:
                    register_failure(u, ip, "вход")
                else:
                    unknown_failure(key)
                raise HTTPException(401, BAD_CREDENTIALS)
            if temp_expired(u):
                raise HTTPException(401, TEMP_EXPIRED)
            start_session(u, request, response, via_shared=shared, remember=payload.remember)
        return {"user": me_dict(store.get("accounts", u["id"]))}

    def first_people() -> list[dict]:
        return [u for u in store.q("SELECT id, full_name, login, external, confirmed, active FROM accounts ORDER BY full_name")
                if u.get("active", 1) and not u.get("external") and u.get("confirmed", 1) and not (u.get("login") or "").strip()]

    @r.get("/auth/first-login/people")
    def first_login_people():
        return {"people": [{"id": u["id"], "full_name": u["full_name"]} for u in first_people()],
                "shared_password_set": bool(shared_hash())}

    @r.post("/auth/first-login")
    def first_login(payload: FirstLoginIn, request: Request, response: Response):
        csrf(request)
        ip = client_ip(request)
        if ip_blocked(ip):
            raise HTTPException(429, "Слишком много неудачных попыток входа. Повторите через 2 минуты.")
        key = normalize_login(payload.login)
        problem = validate_login(key)
        if problem:
            raise HTTPException(400, problem)

        def refuse(u: dict | None = None, count: bool = False):
            ip_fail[ip].append(time.time())
            if count and u is not None:
                register_failure(u, ip, "первый вход")
            raise HTTPException(401, BAD_CREDENTIALS)
        with bind_lock:
            u = store.get("accounts", payload.user_id)
            ok = bool(u) and u.get("active", 1) and not u.get("external") and u.get("confirmed", 1) \
                and not (u.get("login") or "").strip()
            if not ok:
                verify_password(payload.password, None)
                refuse()
            if locked(u):
                verify_password(payload.password, None)
                ip_fail[ip].append(time.time())
                raise HTTPException(429, LOCKED_MESSAGE)
            if login_owner(key, u["id"]) is not None:
                verify_password(payload.password, None)
                refuse()
            valid, shared = password_ok(u, payload.password)
            if not valid:
                refuse(u, count=True)
            if temp_expired(u):
                raise HTTPException(401, TEMP_EXPIRED)
            store.update("accounts", u["id"], login=key)
            start_session(store.get("accounts", u["id"]), request, response, via_shared=shared, remember=payload.remember)
        ctx.sys_msg(f"Привязан логин: {u['full_name']}",
                    f"Логин «{key}» привязан при первом входе ({РОЛЬ_СЛОВАМИ.get(u.get('role') or 'member')}, "
                    f"{'общий' if shared else 'личный'} пароль). Перепривязать или очистить логин может только суперадмин в "
                    "«Команде».")
        return {"user": me_dict(store.get("accounts", u["id"]))}

    @r.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        csrf(request)
        accounts.close_session(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")

    @r.get("/auth/me")
    def me(request: Request):
        return me_dict(ctx.need_user(request))

    def check_current(u: dict, password: str | None, ip: str, context: str) -> None:
        u = store.get("accounts", u["id"])
        if locked(u):
            raise HTTPException(429, LOCKED_MESSAGE)
        if not password or not verify_password(password, u.get("password_hash") or None):
            register_failure(u, ip, context)
            raise HTTPException(400, "Текущий пароль указан неверно" if password else "Введите текущий пароль")
        if u.get("failed_attempts"):
            store.update("accounts", u["id"], failed_attempts=0)

    @r.post("/auth/change-password", status_code=204)
    def change_password(payload: ChangePasswordIn, request: Request):
        u = ctx.need_user(request)
        if (u.get("role") or "member") in SHARED_PASSWORD_ROLES:
            raise HTTPException(400, "Вы входите по общему паролю — его меняет только суперадмин")
        with key_lock(u.get("login") or f"id:{u['id']}"):
            u = store.get("accounts", u["id"])
            if not u.get("must_change_password") and verify_password(payload.new_password, u.get("password_hash") or None):
                return
            check_current(u, payload.old_password, client_ip(request), "смена пароля")
            if temp_expired(u):
                raise HTTPException(400, TEMP_EXPIRED)
            problem = validate_new_password(payload.new_password, u.get("login"))
            if problem:
                raise HTTPException(400, problem)
            if verify_password(payload.new_password, u.get("password_hash") or None):
                raise HTTPException(400, "Новый пароль должен отличаться от текущего")
            store.update("accounts", u["id"], password_hash=hash_password(payload.new_password), must_change_password=0,
                         temp_expires_at=None)
            import hashlib
            mine = request.cookies.get(COOKIE)
            mine_h = hashlib.sha256(mine.encode()).hexdigest() if mine else ""
            for s in store.q("SELECT id, token_hash FROM sessions WHERE account_id=?", (u["id"],)):
                if s["token_hash"] != mine_h:
                    store.delete("sessions", s["id"])

    def issue_temp(u: dict) -> str:
        temp = generate_temp_password()
        store.update("accounts", u["id"], password_hash=hash_password(temp), must_change_password=1,
                     temp_expires_at=(datetime.now() + TEMP_TTL).strftime("%Y-%m-%dT%H:%M:%S"),
                     failed_attempts=0, locked_until=None)
        return temp

    @r.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordIn, request: Request):
        admin = ctx.need_super(request)
        u = store.get("accounts", payload.user_id)
        if u is None or not u.get("active", 1):
            raise HTTPException(404, "Такого сотрудника нет в «Команде» или он отключён")
        if u.get("external"):
            raise HTTPException(400, EXTERNAL_NO_ACCESS)
        if (u.get("role") or "member") in SHARED_PASSWORD_ROLES:
            raise HTTPException(400, "Участники и директора входят по общему паролю — личного пароля у них нет, "
                                     "сбрасывать нечего. Общий пароль меняется в «Настройках».")
        if u["id"] == admin["id"]:
            raise HTTPException(400, "Свой пароль меняйте кнопкой «Сменить пароль»")
        if not (u.get("login") or "").strip():
            raise HTTPException(400, "Доступ ещё не выдан — используйте «Выдать доступ»")
        temp = issue_temp(u)
        closed = revoke_sessions(u["id"])
        ctx.sys_msg(f"Сброшен личный пароль: {u['full_name']}",
                    f"Сбросил суперадмин {admin['full_name']}. Логин «{u['login']}» не изменён. Временный пароль показан "
                    f"суперадмину один раз и действует 24 часа. Завершено сессий: {closed}.")
        return {"login": u["login"], "temporary_password": temp, "sessions_closed": closed, "valid_hours": 24,
                "note": "Передайте временный пароль человеку лично. Он виден один раз и действует 24 часа; свой пароль "
                        "человек задаст при входе."}

    @r.post("/auth/mode")
    def set_mode(payload: ModeIn, request: Request):
        admin = ctx.need_super(request)
        if payload.auth_required and not has_access(admin):
            raise HTTPException(400, "Сначала задайте себе доступ (логин и пароль) — иначе вы не сможете войти после "
                                     "включения. Первый пароль суперадминистратора задаётся командой: python -m meetflow "
                                     "set-password")
        was = accounts.auth_required()
        if was and not payload.auth_required and admin.get("password_hash"):
            check_current(admin, payload.current_password, client_ip(request), "выключение входа")
        accounts.set_auth_required(payload.auth_required, admin.get("full_name") or "")
        if was != payload.auth_required:
            ctx.sys_msg("режим входа", f"Вход по логину и паролю {'ВКЛЮЧЁН' if payload.auth_required else 'ВЫКЛЮЧЕН (режим тестирования)'} "
                                       f"суперадминистратором {admin.get('full_name')}.")
        return {"auth_required": payload.auth_required}

    # ------------------------------------------------------------------ «Команда»
    def refuse_duplicate(full_name: str, exclude_id: int | None = None, organization: str | None = None) -> None:
        key = names.person_key(full_name)
        w = (full_name or "").split()
        swapped = names.person_key(" ".join([w[1], w[0]] + w[2:])) if len(w) >= 2 else None
        keys = {k for k in (key, swapped) if k}
        for o in store.q("SELECT id, full_name, organization FROM accounts"):
            if o["id"] == exclude_id:
                continue
            same = (names.person_key(o["full_name"]) in keys) if keys else (
                norm_yo.равны(o["full_name"], full_name) and norm_yo.равны(o.get("organization") or "", organization or ""))
            if same:
                raise HTTPException(409, f"Такой участник уже есть в команде: {o['full_name']}. Проверьте, не тот ли это человек.")

    def forbid_super(u: dict, admin: dict) -> None:
        if u.get("role") == "super_admin" and admin.get("role") != "super_admin":
            raise HTTPException(403, "Запись супер-администратора может изменить только супер-администратор")

    def others_with_role(role: str, exclude: int) -> int:
        return len(store.q("SELECT id FROM accounts WHERE role=? AND COALESCE(active,1)=1 AND id!=?", (role, exclude)))

    def has_super() -> bool:
        return bool(store.q("SELECT id FROM accounts WHERE role='super_admin'"))

    def only_super_assigns_admin(requester: dict, new_role: str, old_role: str) -> None:
        if new_role != "project_admin" or new_role == old_role or not has_super():
            return
        if requester.get("role") != "super_admin":
            raise HTTPException(403, "Назначать администратора может только суперадмин")

    def external_member_only(is_external: bool, role: str | None) -> None:
        if is_external and role not in (None, "member"):
            raise HTTPException(400, EXTERNAL_NO_ACCESS)

    def personal_password_by_super(u: dict, admin: dict) -> None:
        if u.get("external"):
            raise HTTPException(400, EXTERNAL_NO_ACCESS)
        if (u.get("role") or "member") in SHARED_PASSWORD_ROLES:
            raise HTTPException(400, "Участники входят по общему паролю — личный пароль им не выдаётся. Логин человек "
                                     "привяжет сам при первом входе; поправить его может суперадмин в правке записи.")
        if u["id"] != admin["id"] and admin.get("role") != "super_admin":
            raise HTTPException(403, "Личный пароль администратору выдаёт только суперадмин")

    @r.get("/users")
    def list_users(request: Request):
        seed_super()        # при первом показе «Вы работаете как», а не при старте: база могла наполниться после
        sync()
        viewer = ctx.user(request)
        rows = store.q("SELECT * FROM accounts ORDER BY full_name")
        return [user_out(u, viewer) for u in rows]

    @r.post("/users", status_code=201)
    def create_user(payload: UserCreate, request: Request):
        req = ctx.need_user(request)
        role = _role_ok(payload.access_role)
        if role == "super_admin" and req.get("role") != "super_admin":
            raise HTTPException(403, "Роль супер-администратора может назначить только супер-администратор")
        if role == "project_admin" and req.get("role") not in ADMIN_ROLES:
            raise HTTPException(403, "Назначать администраторов может только существующий администратор")
        only_super_assigns_admin(req, role, "member")
        external_member_only(payload.is_external, role)
        if payload.email and req.get("role") != "super_admin":
            raise HTTPException(403, "Логин может указать только суперадмин")
        bad = names.problem(payload.full_name, payload.project_role, payload.is_external, payload.organization,
                            payload.name_short_reason)
        if bad:
            raise HTTPException(400, bad)
        with create_lock:
            refuse_duplicate(payload.full_name, organization=payload.organization)
            login = normalize_login(payload.email) if payload.email else None
            if login and login_owner(login):
                raise HTTPException(400, "Пользователь с таким логином уже существует")
            uid = store.insert("accounts", login=login, full_name=" ".join(payload.full_name.split()), role=role,
                               password_hash="", active=1, failed_attempts=0, created_at=now(),
                               position=payload.role or "", department=payload.department or "",
                               project_role=payload.project_role or "", external=int(payload.is_external),
                               organization=payload.organization or "", confirmed=int(payload.is_confirmed),
                               name_short_reason=payload.name_short_reason or "",
                               confirmed_source=vneshnie_kontakty.ИСТ_ЭКРАН if payload.is_confirmed else "",
                               leads_meetings=int(payload.leads_meetings))
        sync(force=True)
        u = store.get("accounts", uid)
        if role != "member":
            ctx.sys_msg(f"Назначена роль: {u['full_name']} — {РОЛЬ_СЛОВАМИ.get(role)}",
                        f"Назначил: {req.get('full_name')}. Новая запись.")
        return user_out(u, req)

    @r.get("/users/{user_id}")
    def get_user(user_id: int, request: Request):
        u = store.get("accounts", user_id)
        if not u:
            raise HTTPException(404, "Пользователь не найден")
        return user_out(u, ctx.user(request))

    @r.delete("/users/{user_id}", status_code=204)
    def delete_user(user_id: int, request: Request):
        admin = ctx.need_admin(request)
        u = store.get("accounts", user_id)
        if not u:
            raise HTTPException(404, "Пользователь не найден")
        if u["id"] == admin["id"]:
            raise HTTPException(400, "Свою запись удалить нельзя — попросите другого администратора")
        forbid_super(u, admin)
        if u.get("role") in ADMIN_ROLES and others_with_role(u["role"], u["id"]) == 0:
            raise HTTPException(400, f"Это последний активный пользователь с ролью «{ROLE_NAMES.get(u['role'])}» — "
                                     "удалять его нельзя")
        revoke_sessions(u["id"])
        store.delete("accounts", u["id"])
        ctx.sys_msg("auth", f"Удалена запись «Команды»: {u['full_name']} ({ROLE_NAMES.get(u.get('role') or 'member')}); "
                            f"удалил: {admin.get('full_name')}")

    @r.post("/users/{user_id}/access")
    def grant_access(user_id: int, payload: AccessGrantIn, request: Request):
        admin = ctx.need_admin(request)
        u = store.get("accounts", user_id)
        if not u:
            raise HTTPException(404, "Пользователь не найден")
        forbid_super(u, admin)
        if not u.get("active", 1):
            raise HTTPException(400, "Учётная запись отключена — сначала включите её, затем выдайте доступ")
        personal_password_by_super(u, admin)
        if u["id"] == admin["id"]:
            raise HTTPException(400, "Свой пароль меняйте кнопкой «Сменить пароль»")
        login = normalize_login(payload.email) or normalize_login(u.get("login"))
        if not login:
            raise HTTPException(400, "Укажите логин — часть адреса до «@», например ipetrukevich")
        problem = validate_login(login)
        if problem:
            raise HTTPException(400, problem)
        if login_owner(login, u["id"]):
            raise HTTPException(400, "Этот логин уже используется другим человеком")
        last = last_grant.get(u["id"])
        if last is not None and time.monotonic() - last < GRANT_REPEAT_SECONDS:
            raise HTTPException(409, "Временный пароль только что выдан — повторное нажатие новый не выдаёт. "
                                     f"Если нужен новый, нажмите ещё раз через {GRANT_REPEAT_SECONDS} секунд")
        had = bool(u.get("password_hash"))
        store.update("accounts", u["id"], login=login)
        temp = issue_temp(u)
        revoke_sessions(u["id"])
        ctx.sys_msg(f"{'Сброшен личный пароль' if had else 'Выдан доступ'}: {u['full_name']}",
                    f"{admin.get('full_name')}: логин {login}. Временный пароль показан суперадмину один раз, действует "
                    "24 часа; при первом входе человек обязан задать свой. Самого пароля здесь нет.")
        last_grant[u["id"]] = time.monotonic()
        return {"login": login, "temp_password": temp, "temporary_password": temp, "valid_hours": 24,
                "note": "Передайте пароль человеку лично. Он виден один раз и действует 24 часа — в базе хранится только хэш."}

    @r.patch("/users/{user_id}")
    def patch_user(user_id: int, payload: UserPatch, request: Request):
        admin = ctx.need_admin(request)
        with role_lock:
            u = store.get("accounts", user_id)
            if not u:
                raise HTTPException(404, "Пользователь не найден")
            forbid_super(u, admin)
            data = payload.model_dump(exclude_unset=True)
            vals: dict = {}
            old_role = u.get("role") or "member"
            if data.get("access_role") is not None and data["access_role"] != old_role:
                new_role = _role_ok(data["access_role"])
                if "super_admin" in (new_role, old_role) and admin.get("role") != "super_admin":
                    raise HTTPException(403, "Роль супер-администратора назначает и снимает только супер-администратор")
                only_super_assigns_admin(admin, new_role, old_role)
                external_member_only(data["is_external"] if data.get("is_external") is not None else bool(u.get("external")),
                                     new_role)
                leaves = (old_role == "super_admin" and new_role != "super_admin") or \
                    (old_role in ADMIN_ROLES and new_role not in ADMIN_ROLES)
                if leaves and others_with_role(old_role, u["id"]) == 0:
                    raise HTTPException(400, f"Нельзя понизить последнего активного пользователя с ролью "
                                             f"«{ROLE_NAMES.get(old_role)}» — сначала назначьте другого")
                ctx.sys_msg(f"Назначена роль: {u['full_name']} — {РОЛЬ_СЛОВАМИ.get(new_role)}",
                            f"Назначил: {admin.get('full_name')}. Было: {РОЛЬ_СЛОВАМИ.get(old_role)} "
                            f"({ROLE_NAMES.get(old_role)} → {ROLE_NAMES.get(new_role)}).")
                vals["role"] = new_role
            if data.get("is_external") is True:
                external_member_only(True, vals.get("role", old_role))
            login_change = "login" in data and normalize_login(data.get("login")) != normalize_login(u.get("login"))
            if login_change:
                if admin.get("role") != "super_admin":
                    raise HTTPException(403, "Логин видит и меняет только суперадмин")
                new_login = normalize_login(data.get("login"))
                if new_login:
                    ext = data["is_external"] if data.get("is_external") is not None else bool(u.get("external"))
                    if ext:
                        raise HTTPException(400, EXTERNAL_NO_ACCESS)
                    p = validate_login(new_login)
                    if p:
                        raise HTTPException(400, p)
                    busy = login_owner(new_login, u["id"])
                    if busy:
                        raise HTTPException(400, f"Этот логин уже привязан: «{busy['full_name']}»")
                vals["login"] = new_login or None
                revoke_sessions(u["id"])
            new = {"full_name": u["full_name"], "project_role": u.get("project_role"), "is_external": bool(u.get("external")),
                   "is_confirmed": bool(u.get("confirmed", 1)), "organization": u.get("organization"),
                   "name_short_reason": u.get("name_short_reason")}
            new.update({k: v for k, v in data.items() if k in new and v is not None})
            touched = any(k in data for k in new)
            if touched and new["is_confirmed"]:
                bad = names.problem(new["full_name"], new["project_role"], new["is_external"], new["organization"],
                                    new["name_short_reason"])
                if bad:
                    raise HTTPException(400, bad)
            if data.get("full_name") is not None:
                nm = " ".join(data["full_name"].split())
                if not nm or not re.search(r"[A-Za-zА-Яа-яЁё]{2}", nm) or re.search(r"[\d_@#%*=+<>/\\|\[\]{}()!?;:\"«»]", nm):
                    raise HTTPException(400, "Имя должно состоять из букв: укажите фамилию и имя")
                with create_lock:
                    refuse_duplicate(nm, exclude_id=u["id"], organization=data.get("organization")
                                     if data.get("organization") is not None else u.get("organization"))
            fmap = {"full_name": "full_name", "role": "position", "project_role": "project_role", "department": "department",
                    "is_external": "external", "organization": "organization", "is_confirmed": "confirmed",
                    "leads_meetings": "leads_meetings", "name_short_reason": "name_short_reason"}
            for k, col in fmap.items():
                if k in data and data[k] is not None:
                    v = data[k]
                    vals[col] = " ".join(v.split()) if isinstance(v, str) else int(v) if isinstance(v, bool) else v
            was_unconfirmed = not u.get("confirmed", 1)
            if was_unconfirmed and vals.get("confirmed") == 1:
                vals["confirmed_source"] = vneshnie_kontakty.ИСТ_ЭКРАН
            elif not was_unconfirmed and vals.get("confirmed") == 0:
                vals["confirmed_source"] = ""
            to_external = data.get("is_external") is True and not u.get("external")
            if to_external:
                vals.update(login=None, password_hash="", must_change_password=0)
                revoke_sessions(u["id"])
                ctx.sys_msg(f"Переведён во внешнюю команду: {u['full_name']}",
                            f"{admin.get('full_name')}: доступ закрыт — сессии завершены, логин и личный пароль очищены.")
            if login_change:
                ctx.sys_msg(f"Логин {'изменён' if vals.get('login') else 'очищен'}: {u['full_name']}",
                            f"{admin.get('full_name')}: «{u.get('login') or '—'}» → «{vals.get('login') or '—'}». Прежние "
                            "сессии человека завершены.")
            if vals:
                store.update("accounts", u["id"], **vals)
            if vals.get("full_name") and vals["full_name"] != u["full_name"]:
                for t in store.q("SELECT id FROM tasks WHERE assignee=?", (u["full_name"],)):
                    store.update("tasks", t["id"], assignee=vals["full_name"])
                for p in store.q("SELECT id FROM people WHERE full_name=?", (u["full_name"],)):
                    store.update("people", p["id"], full_name=vals["full_name"])
            if was_unconfirmed and vals.get("confirmed") == 1:
                for c in store.q("SELECT id, payload FROM cards WHERE status='open' AND kind IN ('confirm_person','unconfirmed_person')"):
                    if u["full_name"] in (c["payload"] or "") or (vals.get("full_name") or "\0") in (c["payload"] or ""):
                        store.update("cards", c["id"], status="accepted", resolution=f"Запись «{vals.get('full_name') or u['full_name']}» "
                                     "подтверждена в «Команде».", resolved_at=now())
        sync(force=True)
        return user_out(store.get("accounts", u["id"]), admin)

    @r.post("/users/{user_id}/password")
    def set_password(user_id: int, payload: SetPasswordIn, request: Request):
        admin = ctx.need_admin(request)
        u = store.get("accounts", user_id)
        if not u:
            raise HTTPException(404, "Пользователь не найден")
        forbid_super(u, admin)
        if not u.get("active", 1):
            raise HTTPException(400, "Учётная запись отключена — сначала включите её")
        personal_password_by_super(u, admin)
        if u["id"] != admin["id"]:
            raise HTTPException(403, "Личный пароль администратор задаёт сам. Суперадмин может только сбросить его кнопкой "
                                     "«Сбросить пароль» — человек получит временный пароль и при входе задаст свой")
        if not u.get("login"):
            raise HTTPException(400, "Сначала выдайте доступ — укажите логин человека (часть адреса до «@»).")
        problem = validate_new_password(payload.password, u["login"])
        if problem:
            raise HTTPException(400, problem)
        if verify_password(payload.password, u.get("password_hash") or None):
            raise HTTPException(400, "Новый пароль совпадает с прежним — придумайте другой")
        store.update("accounts", u["id"], password_hash=hash_password(payload.password), must_change_password=0,
                     temp_expires_at=None, failed_attempts=0, locked_until=None)
        ctx.sys_msg("задан пароль", f"{admin.get('full_name')} задал(а) пароль для «{u['full_name']}».")
        return {"ok": True, "login": u["login"], "must_change_password": False}

    @r.post("/users/{user_id}/active")
    def set_active(user_id: int, payload: ActiveIn, request: Request):
        admin = ctx.need_admin(request)
        with role_lock:
            u = store.get("accounts", user_id)
            if not u:
                raise HTTPException(404, "Пользователь не найден")
            forbid_super(u, admin)
            if not payload.is_active:
                if u["id"] == admin["id"]:
                    raise HTTPException(400, "Нельзя отключить собственную учётную запись")
                if u.get("role") in ADMIN_ROLES and others_with_role(u["role"], u["id"]) == 0:
                    raise HTTPException(400, f"Нельзя отключить последнего активного пользователя с ролью "
                                             f"«{ROLE_NAMES.get(u['role'])}»")
                revoke_sessions(u["id"])
            if bool(u.get("active", 1)) != payload.is_active:
                ctx.sys_msg("учётная запись " + ("включена" if payload.is_active else "отключена"),
                            f"{admin.get('full_name')}: «{u['full_name']}» — " + (
                                "включена" if payload.is_active else "отключена, текущие сессии завершены; логин сохранён"))
            store.update("accounts", u["id"], active=int(payload.is_active))
        return user_out(store.get("accounts", u["id"]), admin)
