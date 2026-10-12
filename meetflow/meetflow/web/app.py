"""HTTP API и раздача интерфейса.

Режим входа: как в исходных проектах, вход по паролю по умолчанию выключен
(решение владельца «до прода»), роль и имя передаются заголовками
X-User-Role / X-User-Name — только для тестового контура. Права проверяет
СЕРВЕР; кнопки на экране лишь отражают их.
Технические сообщения не показываются в рабочих вкладках — только в
«Мониторинге» супер-админа; пользователю — понятная фраза.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from ..connectors.base import ConnectorError
from ..connectors.export import DocxOutput
from ..connectors.llm_mock import MockLLM
from ..connectors.llm_ollama import OllamaLLM
from ..connectors.llm_openrouter import OpenRouterLLM
from ..connectors.registry import default_registry
from ..connectors.voice_base import voice_base_state
from ..core.config import Theme, list_themes, load_theme
from ..core.accounts import Accounts, AuthError
from ..core.backup import Backups
from ..core.dates import due_text, lenient_date
from ..core.intake import MIN_INTERVAL, IntakeError, IntakeService, preview_folder, sign_folder, validate_folder
from ..core.runs_report import runs_report
from ..core import roadmap as roadmap_mod
from ..core import search as search_mod
from ..core import units as units_mod
from ..core.pipeline import MeetingPipeline
from ..core.store import Store, now
from ..core.text import same_word, stems, words
from ..core.types import CardStatus, TaskStatus

STATIC = Path(__file__).parent / "static"
ADMIN_ROLES = {"project_admin", "super_admin"}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PersonIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=200)
    role: str = Field("", max_length=200)
    department: str = Field("", max_length=200)
    external: bool = False
    organization: str = Field("", max_length=200)
    confirm_new: bool = False      # «это новый человек», хотя фамилия совпала с кем-то из «Команды»


class MeetingIn(BaseModel):
    date: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")   # \d пропускал «２０２６» (ревью)
    label: str = Field("", max_length=200)

    @field_validator("date")
    @classmethod
    def _real_date(cls, v: str) -> str:
        date_cls.fromisoformat(v)
        return v


class StatusIn(BaseModel):
    status: TaskStatus


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class FolderIn(BaseModel):
    path: str = Field("", max_length=500)
    path_repeat: str = Field("", max_length=500)
    # смена папки — в два шага, второй по паролю супер-администратора (как в Планёрке и ERP с 07.10.26)
    confirm: bool = False
    login: str = Field("", max_length=100)            # в тестовом режиме — чья учётная запись подтверждает
    current_password: str = Field("", max_length=200)


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ModeIn(BaseModel):
    auth_required: bool
    login: str = Field("", max_length=100)
    password: str = Field("", max_length=200)


class AccountIn(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    full_name: str = Field("", max_length=200)
    role: str = Field(max_length=40)
    password: str = Field(min_length=1, max_length=200)


class ThresholdsIn(BaseModel):
    overdue_highlight_working_days: int | None = Field(None, ge=1, le=60)
    card_cleanup_days: int | None = Field(None, ge=0, le=365)


class IntervalIn(BaseModel):
    seconds: int = Field(ge=MIN_INTERVAL, le=86400)


class RouteUseIn(BaseModel):
    role: str = Field(max_length=40)
    point: str = Field(max_length=100)


class RoutePointIn(BaseModel):
    name: str = Field(max_length=100)
    old_name: str = Field("", max_length=100)
    fields: dict


class RouteRoleIn(BaseModel):
    role: str = Field(max_length=40)
    point: str = Field(max_length=100)
    action: str = Field(max_length=10)   # add — запасной в конец цепочки, remove — убрать из роли


class ToggleIn(BaseModel):
    enabled: bool


class ResolveIn(BaseModel):
    status: CardStatus
    resolution: str = Field("", max_length=2000)
    why: str = Field("", max_length=1000)
    choice: str = Field("", max_length=200)   # выбранный кандидат по спорному имени
    # «новый человек» в карточке «тот же или новый» — только подтверждением, внешний с организацией и ролью
    new_full_name: str = Field("", max_length=200)
    new_organization: str = Field("", max_length=200)
    new_role: str = Field("", max_length=200)


LLM_TOOLS = ("mock", "ollama", "openrouter", "routes")


def _llm(theme: Theme, side: str):
    """Инструмент подключения модели выбирается при развёртывании (решение владельца 03.10.26):
    MEETFLOW_LLM=mock — стенд без модели с плашкой; ollama — локальная модель (модели в теме
    llm.generator / llm.verifier, пока заглушки); openrouter — модели из llm.openrouter.*, ключ —
    переменная OPENROUTER_API_KEY; routes — цепочки точек по ролям из models.json с переходом на запасную
    при недоступности (решение владельца 09.10.26, connectors/llm_routes.py). Потолок ответа — llm.max_answer_tokens."""
    mode = os.environ.get("MEETFLOW_LLM", "mock").strip().lower()
    if mode not in LLM_TOOLS:
        raise ValueError(f"MEETFLOW_LLM={mode}: допустимы {', '.join(LLM_TOOLS)}")
    if mode == "mock":
        return MockLLM()
    cap = int(theme.get("llm.max_answer_tokens", 4096))
    if mode == "routes":
        from ..connectors.llm_routes import RoutedLLM
        return RoutedLLM(side, max_answer_tokens=cap)
    if mode == "openrouter":
        cfg = theme.get(f"llm.openrouter.{side}", {})
        return OpenRouterLLM(model=cfg.get("model", ""), profile=cfg.get("profile", "generic"), max_answer_tokens=cap)
    cfg = theme.get(f"llm.{side}", {})
    return OllamaLLM(model=cfg.get("model", ""), profile=cfg.get("profile", "generic"),
                     num_ctx=int(cfg.get("num_ctx", 32768)), max_answer_tokens=cap)


def create_app(theme_name: str | None = None, db_path: str | None = None, journal: str | None = None,
               watch: bool | None = None) -> FastAPI:
    theme = load_theme(theme_name or os.environ.get("MEETFLOW_THEME", "_default"))
    store = Store(db_path or os.environ.get("MEETFLOW_DB", "data/meetflow.db"))
    plugins = default_registry()
    pipe = MeetingPipeline(theme, store, plugins, _llm(theme, "generator"), _llm(theme, "verifier"),
                           journal or os.environ.get("MEETFLOW_JOURNAL", "data/logs/llm_calls.jsonl"))
    if os.environ.get("MEETFLOW_LLM", "mock").strip().lower() == "routes":
        from ..connectors.llm_routes import RoutedLLM, routes_path
        try:   # досмотр — только если у роли guard есть точки; без них решает правило guard.py
            has_guard = bool(json.loads(routes_path().read_text(encoding="utf-8")).get("roles", {}).get("guard"))
        except (OSError, ValueError):
            has_guard = False
        if has_guard:
            pipe.guard_llm = RoutedLLM("guard", max_answer_tokens=5)
    intake = IntakeService(pipe)
    accounts = Accounts(store)
    backups = Backups(store.path)
    watch_on = os.environ.get("MEETFLOW_WATCH", "on") != "off" if watch is None else watch

    @asynccontextmanager
    async def lifespan(_app):
        if watch_on:
            intake.start()        # фоновый забор из папок-приёмников
            backups.start()       # автокопия базы по расписанию
            if os.environ.get("MEETFLOW_RESUME_ON_START", "on") != "off":
                intake.resume_after_restart()     # оборванная перезапуском работа (локальная машина 12.10.26)
        yield
        intake.stop()
        backups.stop()

    app = FastAPI(title="MeetFlow", lifespan=lifespan)
    app.state.theme, app.state.store, app.state.pipe, app.state.intake = theme, store, pipe, intake
    app.state.accounts, app.state.backups = accounts, backups
    app_dir = Path(__file__).resolve().parents[2]
    COOKIE = "mf_session"
    PUBLIC = {"/api/theme", "/api/auth/mode", "/api/auth/login", "/api/auth/logout"}

    @app.middleware("http")
    async def _login_gate(request: Request, call_next):
        """Вход включён — любой /api, кроме публичных, только с действующей сессией."""
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC and accounts.auth_required() \
                and not accounts.by_session(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Нужно войти: включён вход по логину и паролю."}, 401)
        return await call_next(request)

    def user(request: Request, x_user_role: str = Header("member"), x_user_name: str = Header("")) -> dict:
        if accounts.auth_required():        # рабочий режим: роль и имя — из учётной записи, заголовки не в счёт
            a = accounts.by_session(request.cookies.get(COOKIE))
            if not a:
                raise HTTPException(401, "Нужно войти.")
            return {"role": a["role"] if a["role"] in theme["roles"] else "member", "name": a["full_name"],
                    "login": a["login"]}
        role = x_user_role if x_user_role in theme["roles"] else "member"
        return {"role": role, "name": unquote(x_user_name)[:200], "login": ""}  # кириллица в заголовке — URL-кодом

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def confirm_super(u: dict, login: str, password: str, request: Request) -> dict:
        """Пароль супер-администратора для опасных смен (папка, база голосов, выключение входа)."""
        if not accounts.has_super_admin():
            raise HTTPException(400, "Сначала заведите учётную запись супер-администратора с паролем: «Параметры "
                                     "системы → Диск и доступы» или python -m meetflow set-password.")
        who = u.get("login") or (login or "").strip()
        if not who:
            raise HTTPException(400, "Укажите логин супер-администратора и его пароль.")
        try:
            a = accounts.check(who, password, client_ip(request))
        except AuthError as e:
            raise HTTPException(403, str(e)) from None
        if a["role"] != "super_admin":
            raise HTTPException(403, "Подтвердить может только супер-администратор.")
        return a

    perms = theme.get("permissions", {})
    admin_roles = set(perms.get("admin", ADMIN_ROLES))

    def can(u: dict, action: str) -> bool:
        return u["role"] in set(perms.get(action, admin_roles))

    def project_or_404(pid: int) -> dict:
        p = store.get("projects", pid)
        if not p:
            raise HTTPException(404, "Проект не найден.")
        return p

    def admin(u: dict = Depends(user)) -> dict:
        if u["role"] not in admin_roles:
            raise HTTPException(403, "Действие доступно администратору проекта.")
        return u

    def super_admin(u: dict = Depends(user)) -> dict:
        if u["role"] != "super_admin":
            raise HTTPException(403, "Раздел доступен супер-администратору.")
        return u

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # пользователю — человеческая фраза
        # одинаковые сбои не множат карточки (ревью: флуд технических карточек)
        pipe.cards.open(None, "technical", "Сбой сервера",
                        {"path": str(request.url.path), "error": type(exc).__name__})
        return JSONResponse({"detail": "К сожалению, что-то пошло не так. Попробуйте ещё раз позже."}, 500)

    @app.get("/health")
    def health():
        return {"ok": True, "theme": theme.id}

    @app.get("/api/theme")
    def get_theme():
        d = theme.data
        return {"id": d["id"], "title": d["title"], "vocabulary": d["vocabulary"], "roles": d["roles"],
                "design": d["design"], "protocol_skeleton": d["protocol_skeleton"],
                "permissions": d.get("permissions", {}),
                "stand": pipe.stand}       # стенд без модели — плашка на каждом экране (01/19)

    @app.get("/api/themes")
    def themes():
        return list_themes()

    @app.get("/api/todo")
    def todo(u: dict = Depends(super_admin)):
        return theme.todo()

    @app.get("/api/projects")
    def projects():
        return store.q("SELECT id, name, theme FROM projects ORDER BY id")

    @app.post("/api/projects")
    def create_project(p: ProjectIn, u: dict = Depends(admin)):
        return {"id": store.insert("projects", name=p.name, theme=theme.id)}

    @app.get("/api/projects/{pid}/people")
    def people(pid: int):
        return store.q("SELECT id, full_name, role, department, organization, external, confirmed FROM people "
                       "WHERE project_id=? "
                       "ORDER BY full_name", (pid,))

    @app.post("/api/projects/{pid}/people")
    def add_person(pid: int, p: PersonIn, u: dict = Depends(admin)):
        project_or_404(pid)
        # своя команда — фамилия и имя (20.09.26); внешняя — организация и роль, ФИО не обязательно (03.10.26)
        if p.external and not (p.organization.strip() and p.role.strip()):
            raise HTTPException(422, "Для человека внешней команды нужны организация и роль на проекте.")
        name_words = [w for w in words(p.full_name) if w.isalpha() and len(w) >= 2]
        if len(name_words) < 2 and not p.external:
            # «Пересыпкин -», «Пересыпкин 1», «П. С.» — не фамилия и имя (письмо meeting-registry 13)
            raise HTTPException(422, "Нужны фамилия и имя полностью.")
        # сверка с «Командой» ДО записи: тот же человек — отказ, совпала фамилия — «тот же или новый?»
        # (в Планёрке без этой сверки появились «Пересыпкин» и «Пересыпкин Сергей», письмо 13)
        norm = " ".join(words(p.full_name))
        new_w = words(p.full_name)
        same, similar = [], []
        for r in store.q("SELECT full_name, external, organization FROM people WHERE project_id=?", (pid,)):
            rw = words(r["full_name"])
            org_same = (r["organization"] or "").strip().lower() == p.organization.strip().lower()
            if " ".join(rw) == norm and bool(r["external"]) == p.external and (not p.external or org_same):
                same.append(r["full_name"])
            elif not p.external and not r["external"] and rw and name_words and same_word(rw[0], name_words[0]):
                similar.append(r["full_name"])
            elif p.external and r["external"] and org_same and rw and new_w and (
                    all(any(same_word(a, b) for b in new_w) for a in rw) or
                    all(any(same_word(a, b) for b in rw) for a in new_w)):
                # внешний той же организации, одна запись короче другой («Иван» и «Иван Петров» из ТМК) —
                # «тот же или новый?» (письмо 23); другая организация — не дубль (письмо 24)
                similar.append(r["full_name"])
        if same:
            raise HTTPException(409, f"Такой человек уже есть: {same[0]}. Вторая запись не заводится.")
        if similar and not p.confirm_new:
            raise HTTPException(409, f"Похоже, человек уже есть: {', '.join(similar)}. Если это новый человек, "
                                     "подтвердите — запись будет заведена.")
        return {"id": store.insert("people", project_id=pid, **p.model_dump(exclude={"confirm_new"}))}

    @app.get("/api/projects/{pid}/meetings")
    def meetings(pid: int):
        rows = store.q("SELECT id, date, label, protocol_built_at FROM meetings WHERE project_id=? ORDER BY date DESC",
                       (pid,))
        for r in rows:
            r["has_protocol"] = bool(r.pop("protocol_built_at"))
        return rows

    @app.post("/api/projects/{pid}/meetings")
    def create_meeting(pid: int, m: MeetingIn, u: dict = Depends(admin)):
        project_or_404(pid)
        return {"id": store.insert("meetings", project_id=pid, date=m.date, label=m.label)}

    @app.post("/api/meetings/{mid}/sources")
    async def upload(mid: int, file: UploadFile = File(...), u: dict = Depends(user)):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        if not can(u, "upload_source"):
            raise HTTPException(403, "Источники встречи загружает администратор.")
        limit = int(theme.get("intake.max_text_mb", 20)) * 2 ** 20
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, "Файл слишком большой.")
        res = pipe.ingest(m["project_id"], mid, file.filename or "файл", data)
        if res["status"] == "rejected":
            raise HTTPException(422, res["reason"])
        return res

    @app.get("/api/meetings/{mid}/sources")
    def sources(mid: int):
        return store.q("SELECT id, name, kind, created_at, local_asr FROM sources WHERE meeting_id=? AND removed_at IS NULL",
                       (mid,))

    @app.get("/api/meetings/{mid}/sources/{sid}/export")
    def source_docx(mid: int, sid: int):
        """Расшифровка, сделанная НАШИМ распознаванием, — в Word тем же выводом, что протокол (локальная машина
        12.10.26, зеркально с ERP и Планёркой). Чужой файл выгружать незачем — он и так у владельца."""
        s = store.get("sources", sid)
        if not s or s["meeting_id"] != mid or s["removed_at"]:
            raise HTTPException(404, "Источник не найден.")
        if not s.get("local_asr"):
            raise HTTPException(400, "Выгружается только расшифровка, распознанная здесь; загруженный файл уже у вас.")
        m = store.get("meetings", mid) or {}
        fmt = lambda d: f"{d.day:02d}.{d.month:02d}.{d.year}" if d else ""   # noqa: E731 — дата владельца
        out = DocxOutput(theme.get("design.document_font", "Times New Roman"),
                         int(theme.get("design.document_size_pt", 12)))
        def line(ln: str) -> str:            # «ЧЧ:ММ:СС<таб>Говорящий<таб>текст» → «ЧЧ:ММ:СС Говорящий: текст»
            parts = [x.strip() for x in ln.split("\t")]
            return f"{parts[0]} {parts[1]}: {parts[2]}" if len(parts) == 3 else " ".join(parts)
        lines = [f"# Расшифровка встречи {fmt(lenient_date(m.get('date')))}", "", f"Источник: {s['name']}"]
        lines += [line(ln) for ln in (s["text"] or "").splitlines() if ln.strip()]
        return Response(out.render("\n\n".join(lines), "transcript"),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                 + quote(f"transcript_{m.get('date', mid)}.docx")})

    @app.post("/api/meetings/{mid}/run")
    def run(mid: int, u: dict = Depends(admin)):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        rep = pipe.run(m["project_id"], mid)
        return rep.__dict__

    @app.get("/api/meetings/{mid}/protocol")
    def protocol(mid: int):
        m = store.get("meetings", mid)
        if not m or not m["protocol_md"]:
            raise HTTPException(404, "Протокола пока нет.")
        return {"markdown": m["protocol_md"], "built_at": m["protocol_built_at"],
                "review_notes": json.loads(m["review_notes"] or "[]"), "units": meeting_units(mid)}

    def meeting_units(mid: int) -> list[dict]:
        """Единицы встречи показываются отдельно от протокола: протокол задним
        числом не переписывается, а раздел единиц всегда текущий (как в ERP)."""
        status = {t["id"]: t["status"] for t in store.q("SELECT id, status FROM tasks")}
        out = []
        for u in store.q("SELECT * FROM units WHERE meeting_id=? ORDER BY line_from, id", (mid,)):
            st, why = units_mod.effective(u, status)
            out.append({"id": u["id"], "kind": u["kind"], "kind_ru": units_mod.KIND_RU.get(u["kind"], u["kind"]),
                        "text": u["text"], "quote": u["quote"], "ts": u["ts"], "status": st, "why": why or u["closed_note"],
                        "roles": json.loads(u["roles"] or "[]"), "planned_date": u["planned_date"]})
        return out

    @app.get("/api/meetings/{mid}/units")
    def get_units(mid: int):
        return meeting_units(mid)

    @app.post("/api/units/{uid}/remove")
    def remove_unit(uid: int, u: dict = Depends(admin)):
        r = units_mod.remove(store, uid, u["name"] or u["role"])
        if not r:
            raise HTTPException(404, "Пункт не найден.")
        return {"ok": True, "status": r["status"]}

    @app.post("/api/units/{uid}/return")
    def return_unit(uid: int, u: dict = Depends(admin)):
        r = units_mod.reopen(store, uid, u["name"] or u["role"])
        if not r:
            raise HTTPException(404, "Пункт не найден.")
        return {"ok": True, "status": r["status"]}

    @app.get("/api/projects/{pid}/search")
    def search(pid: int, q: str = ""):
        project_or_404(pid)
        return search_mod.search(store, pid, q[:300], raw_speech=bool(theme.get("search.raw_speech", False)))

    @app.get("/api/projects/{pid}/roadmap")
    def roadmap(pid: int):
        project_or_404(pid)
        rm = roadmap_mod.build(store, theme, pid)
        return {"markdown": roadmap_mod.to_markdown(rm, theme), "data": rm}

    @app.get("/api/projects/{pid}/roadmap.docx")
    def roadmap_docx(pid: int):
        project_or_404(pid)
        md = roadmap_mod.to_markdown(roadmap_mod.build(store, theme, pid), theme)
        out = DocxOutput(theme.get("design.document_font", "Times New Roman"), int(theme.get("design.document_size_pt", 12)))
        return Response(out.render(md, "roadmap"),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote("roadmap.docx")})

    @app.get("/api/meetings/{mid}/protocol.docx")
    def protocol_docx(mid: int):
        m = store.get("meetings", mid)
        if not m or not m["protocol_md"]:
            raise HTTPException(404, "Протокола пока нет.")
        out = DocxOutput(theme.get("design.document_font", "Times New Roman"),
                         int(theme.get("design.document_size_pt", 12)))
        return Response(out.render(m["protocol_md"], "protocol"),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                 + quote(f"protocol_{m['date']}.docx")})

    @app.get("/api/projects/{pid}/tasks")
    def tasks(pid: int, status: Literal["active", "done", "dropped", "all"] = "active"):
        project_or_404(pid)
        st = None if status == "all" else TaskStatus(status)
        rows = pipe.reg.list(pid, st)
        n = int(store.get_setting("overdue_highlight_working_days", None, 7) or 7)
        today = date_cls.today()

        def overdue(r: dict) -> bool:   # как в Планёрке: N рабочих дней после срока, только у задач в работе
            d = lenient_date(r.get("due_date")) if r.get("status") == "active" else None
            if not d or d >= today:
                return False
            days, cur = 0, d
            while cur < today:
                cur += timedelta(days=1)
                days += cur.weekday() < 5
            return days >= n
        return [{**{k: v for k, v in r.items() if k != "project_id"}, "overdue": overdue(r),
                 "due_text": due_text(r.get("due_date"), r.get("date_set"))} for r in rows]

    @app.patch("/api/tasks/{tid}")
    def set_status(tid: int, body: StatusIn, u: dict = Depends(user)):
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена.")
        responsible = u["name"] and u["name"] == t["assignee"]
        if not can(u, "task_status") and not responsible:
            raise HTTPException(403, "Статус меняет ответственный или администратор.")
        pipe.reg.set_status(tid, body.status, "web_form", by=u["name"] or u["role"])
        return store.get("tasks", tid)

    @app.post("/api/tasks/{tid}/comment")
    def comment(tid: int, body: CommentIn, u: dict = Depends(user)):
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена.")
        responsible = u["name"] and u["name"] == t["assignee"]
        if not can(u, "task_status") and not responsible:
            raise HTTPException(403, "Комментарий оставляет ответственный или администратор.")
        pipe.reg.comment(tid, body.text, u["name"] or u["role"])
        return {"ok": True}

    @app.get("/api/projects/{pid}/cards")
    def cards(pid: int, u: dict = Depends(admin)):
        return [c for c in pipe.cards.list(pid) if c["kind"] != "technical"]

    def _apply_card(c: dict, payload: dict, chosen: dict | None, by: str) -> None:
        """«Подтвердить» делает то, что карточка предлагала. Раньше решение
        только записывалось: задача не заводилась, закрытие не применялось."""
        pid, mid = c["project_id"], c["meeting_id"]
        if c["kind"] == "held_task" and payload.get("description"):
            m = store.get("meetings", mid) if mid else None
            if chosen and chosen.get("id") is not None and payload.get("marks"):
                # «это он»: признаки несовпадения — в профиль ровно этого человека (по id)
                p = store.get("people", int(chosen["id"]))
                if p and p["project_id"] == pid:
                    known = json.loads(p["known_marks"] or "[]")
                    store.update("people", p["id"], known_marks=sorted(set(known) | set(payload["marks"])))
            who = chosen["name"] if chosen else payload.get("assignee")
            pipe.reg.add(pid, payload["description"], who, mid, payload.get("quote", ""),
                         payload.get("due_date"), (m or {}).get("date"))
        elif c["kind"] == "assign_person" and chosen and payload.get("task_id"):
            # выбор ставит исполнителя в ту же задачу, новую не заводит (письмо 30)
            pipe.reg.set_assignee(payload["task_id"], chosen["name"], by,
                                  "новый человек" if chosen.get("new") else payload.get("reason", ""))
            if payload.get("marks") and not chosen.get("new"):
                p = store.get("people", int(chosen["id"]))
                if p and p["project_id"] == pid:
                    known = json.loads(p["known_marks"] or "[]")
                    store.update("people", p["id"], known_marks=sorted(set(known) | set(payload["marks"])))
        elif c["kind"] == "due_unconfirmed" and payload.get("task_id"):
            # «Подтвердить» ставит предложенный срок; «Не нужно» — задача остаётся без срока (как в Планёрке)
            d = lenient_date(payload.get("proposed_value"))
            pipe.reg.set_due(payload["task_id"], f"{d.day:02d}.{d.month:02d}.{d.year}" if d else
                             payload.get("proposed_text"), by, "срок из карточки")
        elif c["kind"] == "confirm_person" and payload.get("person_id"):
            p = store.get("people", int(payload["person_id"]))
            if p and p["project_id"] == pid:
                store.update("people", p["id"], confirmed=1)       # документ 14: оператор подтвердил
        elif c["kind"] == "closing_candidate" and payload.get("task_id"):
            pipe.reg.set_status(payload["task_id"], TaskStatus.DONE, "operator", payload.get("quote", ""), by=by)
        elif c["kind"] == "mass_closing":
            for x in payload.get("closings") or []:
                pipe.reg.set_status(x["task_id"], TaskStatus(x.get("status", "done")), "operator", x.get("quote", ""),
                                    by=by)

    @app.post("/api/cards/{cid}/resolve")
    def resolve(cid: int, body: ResolveIn, u: dict = Depends(admin)):
        c = store.get("cards", cid)
        if not c:
            raise HTTPException(404, "Карточка не найдена.")
        payload = json.loads(c["payload"] or "{}")
        cands = payload.get("candidates") or []
        chosen = None
        if c["kind"] == "assign_person" and body.status == CardStatus.ACCEPTED and body.new_full_name.strip():
            # новый человек — внешний; без организации или роли не заводится, задача остаётся без исполнителя
            if not (body.new_organization.strip() and body.new_role.strip()):
                raise HTTPException(422, "Для нового человека нужны организация и роль на проекте.")
            nm, org = body.new_full_name.strip(), body.new_organization.strip()
            twin = store.q("SELECT id FROM people WHERE project_id=? AND external=1 AND lower(organization)=lower(?) "
                           "AND lower(full_name)=lower(?)", (c["project_id"], org, nm))
            pid_new = twin[0]["id"] if twin else store.insert("people", project_id=c["project_id"], full_name=nm,
                                                             role=body.new_role.strip(), organization=org, external=1)
            chosen = {"id": pid_new, "name": f"{nm} ({org})", "new": True}
        elif c["kind"] in ("held_task", "assign_person") and body.status == CardStatus.ACCEPTED and cands:
            # выбор по id, а не по строке ФИО: у двух людей ФИО может совпасть (письмо 19, по ответу ERP);
            # имя принимается, только если оно однозначно среди кандидатов
            by_id = [x for x in cands if x.get("id") is not None and str(x["id"]) == body.choice.strip()]
            by_name = [x for x in cands if x.get("name") == body.choice]
            chosen = by_id[0] if by_id else (by_name[0] if len(by_name) == 1 else None)
            if chosen is None:
                raise HTTPException(400, "Выберите, о ком речь: " + ", ".join(x["name"] for x in cands) + ".")
        if c["kind"] == "confirm_person" and body.status == CardStatus.REJECTED and payload.get("person_id"):
            # «не человек»: только если запись назначена на одну задачу; иначе отказ (письмо 45, находка ERP)
            p0 = store.get("people", int(payload["person_id"]))
            if p0 and len(store.q("SELECT id FROM tasks WHERE project_id=? AND assignee=?",
                                  (c["project_id"], p0["full_name"]))) > 1:
                raise HTTPException(409, f"На «{p0['full_name']}» назначено несколько задач — «не человек» здесь нельзя; "
                                         "переназначьте задачи в реестре.")
        by = u["name"] or u["role"]
        with store.tx():                      # действие и решение — вместе; второе нажатие ничего не делает
            if store.get("cards", cid)["status"] != CardStatus.OPEN.value:
                return store.get("cards", cid)
            if body.status == CardStatus.ACCEPTED:
                _apply_card(c, payload, chosen, by)
            elif c["kind"] == "confirm_person" and payload.get("person_id"):
                # «не тот человек»: неподтверждённая запись убирается, задачи остаются без исполнителя
                p = store.get("people", int(payload["person_id"]))
                if p and p["project_id"] == c["project_id"] and not p["confirmed"]:
                    for t in store.q("SELECT id FROM tasks WHERE project_id=? AND assignee=?",
                                     (c["project_id"], p["full_name"])):
                        store.update("tasks", t["id"], assignee=None)
                    store.delete("people", p["id"])
            out = pipe.cards.resolve(cid, body.status, body.resolution or (chosen or {}).get("name", ""), body.why)
        if c["kind"] == "held_task" and body.status == CardStatus.REJECTED and c["project_id"]:
            desc = json.loads(c["payload"] or "{}").get("description", "")
            rule = pipe.memory.answer(c["project_id"], "not_a_task", " ".join(sorted(set(stems(desc)))), "reject")
            out = dict(out, rule=rule["status_text"])
        return out

    @app.get("/api/projects/{pid}/decisions")
    def decisions(pid: int, u: dict = Depends(admin)):
        return store.q("SELECT what, decision, why, at FROM decisions WHERE project_id=? ORDER BY id DESC", (pid,))

    @app.get("/api/projects/{pid}/settings")
    def get_settings(pid: int, u: dict = Depends(super_admin)):
        project_or_404(pid)
        return {"intake": intake.state(pid),
                "voice_base_path": store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH"),
                "min_interval": MIN_INTERVAL}

    @app.post("/api/projects/{pid}/settings/watch-folder")
    def set_watch_folder(pid: int, body: FolderIn, request: Request, u: dict = Depends(super_admin)):
        """Два шага, как в Планёрке и ERP: первый — проверка и предпросмотр «что заберёт первый проход», второй —
        подтверждение паролем супер-администратора. Пустой адрес — выключить папку (тоже по паролю)."""
        prj = project_or_404(pid)
        off = not body.path.strip() and not body.path_repeat.strip()
        path = None
        if not off:
            try:
                path = validate_folder(body.path, body.path_repeat, app_dir=app_dir, sign=False)
            except IntakeError as e:
                raise HTTPException(422, str(e)) from None
            other = [r for r in store.q("SELECT project_id, value FROM settings WHERE key='watch_folder'")
                     if r["project_id"] != pid and json.loads(r["value"] or "null") == str(path)]
            if other:
                raise HTTPException(422, "Эта папка уже назначена приёмником другого проекта: у каждого проекта своя.")
        if not body.confirm:
            if off:
                return {"confirm_needed": True, "question": f"Выключить папку-приёмник проекта «{prj['name']}»? "
                        f"Сейчас: {intake.folder(pid) or 'не задана'}. Файлы из неё забираться не будут."}
            pv = preview_folder(path)
            q = (f"Сделать «{path}» папкой-приёмником проекта «{prj['name']}»? В папке файлов: {pv['files']}, первый "
                 f"проход заберёт {pv['first_pass']}.")
            if pv["big"]:
                q += f" Это больше {pv['big_limit']} — первый проход будет долгим и может стоить денег."
            return {"confirm_needed": True, "question": q, "preview": pv}
        confirm_super(u, body.login, body.current_password, request)
        if path is not None:
            sign_folder(path)
        intake.set_folder(pid, path, u["name"] or u["role"])
        return intake.state(pid)

    @app.post("/api/projects/{pid}/settings/watch-interval")
    def set_interval(pid: int, body: IntervalIn, u: dict = Depends(super_admin)):
        project_or_404(pid)
        store.set_setting("watch_interval", body.seconds, pid, u["name"] or u["role"])
        return intake.state(pid)

    @app.post("/api/projects/{pid}/settings/autorun")
    def set_autorun(pid: int, body: ToggleIn, u: dict = Depends(super_admin)):
        project_or_404(pid)
        store.set_setting("autorun", body.enabled, pid, u["name"] or u["role"])
        store.insert("decisions", project_id=pid, what="Автозапуск протокола по расшифровке из папки",
                     decision="включён" if body.enabled else "выключен", why=f"кто: {u['name'] or u['role']}", at=now())
        return intake.state(pid)

    @app.post("/api/settings/voice-base")
    def set_voice_base(body: FolderIn, request: Request, u: dict = Depends(super_admin)):
        a, b = body.path.strip().strip('"'), body.path_repeat.strip().strip('"')
        if a != b:
            raise HTTPException(422, "Адрес и его повтор не совпадают — проверьте опечатку.")
        if a and not Path(a).is_absolute():
            raise HTTPException(422, r"Нужен полный путь к файлу базы, например D:\Голоса\voices.db.")
        confirm_super(u, body.login, body.current_password, request)     # как смена папки — по паролю
        store.set_setting("voice_base_path", a or None, None, u["name"] or u["role"])
        return voice_base_state(a or None)

    @app.get("/api/monitoring/intake")
    def mon_intake(u: dict = Depends(super_admin)):
        return [{"project_id": p["id"], "project": p["name"], **intake.state(p["id"])}
                for p in store.q("SELECT id, name FROM projects ORDER BY id")]

    @app.get("/api/monitoring/voice-base")
    def mon_voice(u: dict = Depends(super_admin)):
        return voice_base_state(store.get_setting("voice_base_path"))

    @app.get("/api/monitoring/runs")
    def mon_runs(days: int = 7, u: dict = Depends(super_admin)):
        return runs_report(pipe.journal.path, max(1, min(days, 90)), theme.get("budget", {}))

    # Переключение моделей (решение владельца 09.10.26): роли, точки по порядку, «Сделать основной»,
    # «Проверить связь». Только супер-администратору; при MEETFLOW_LLM=routes действует сразу, без перезапуска.
    @app.get("/api/monitoring/models")
    def mon_models(u: dict = Depends(super_admin)):
        from ..connectors.llm_routes import panel
        return panel()

    def _rebuild_after_switch(mid: int, pause: float, wait_limit: float = 7200) -> None:
        """Смена модели генерации на живой сборке (локальная машина 7effaa2, решение владельца 12.10.26): текущий
        вызов не обрываем; через паузу дожидаемся конца идущей сборки (до двух часов) и собираем заново — на
        новой модели, иначе документ остаётся смесью шагов двух моделей (правило 08.10.26). Из прежнего прохода
        не берётся ничего: все шаги выводятся из черновика прежней модели. И план, и итог — системным сообщением."""
        time.sleep(pause)
        lock, waited = pipe._meeting_lock(mid), 0.0
        step = 30.0 if pause >= 60 else 0.2           # короткая пауза — только в тестах и на стенде
        while lock.locked() and waited < wait_limit:
            time.sleep(step)
            waited += step
        m = store.get("meetings", mid)
        if not m:
            return
        if lock.locked():
            pipe.cards.open(m["project_id"], "technical", f"Встреча {m['date']}: пересборка после смены модели не начата",
                            {"why": "идущая сборка не закончилась за два часа — запустите сборку кнопкой"}, mid)
            return
        pipe.cards.open(m["project_id"], "technical", f"Встреча {m['date']}: пересборка на новой модели начата",
                        {"why": "модель генерации сменили во время сборки; из прежнего прохода ничего не берётся"}, mid)
        pipe.run(m["project_id"], mid)

    @app.post("/api/monitoring/models/use")
    def mon_models_use(body: RouteUseIn, u: dict = Depends(super_admin)):
        from ..connectors.llm_routes import ROLE_TITLES, panel, routes_path, use
        try:
            old = (json.loads(routes_path().read_text(encoding="utf-8")).get("roles", {}).get(body.role) or [None])[0]
        except (OSError, ValueError):
            old = None
        try:
            use(body.role, body.point, by=u.get("name") or u["role"])
        except (ConnectorError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))
        if old != body.point:      # переключение на точку, которая и так основная, — не событие (локальная машина)
            running = pipe.running_meetings()
            pause = float(os.environ.get("MEETFLOW_MODEL_SWITCH_PAUSE_SEC", "900"))
            note = ""
            if running and body.role == "generate":
                note = (f" Сейчас идёт сборка: текущий вызов дождётся ответа, через {int(pause // 60)} мин и после конца "
                        "сборки протокол соберётся заново на новой модели.")
            m = store.get("meetings", running[0]) if running else None
            pipe.cards.open(m["project_id"] if m else None, "technical",
                            f"Модель роли «{ROLE_TITLES.get(body.role, body.role)}» сменена: {old or '—'} → {body.point}",
                            {"why": ("Следующий вызов пойдёт на новую модель." + note).strip(), "by": u.get("name") or u["role"]},
                            running[0] if running else None)
            if running and body.role == "generate":
                for mid in running:
                    threading.Thread(target=_rebuild_after_switch, args=(mid, pause), daemon=True).start()
        return panel()

    # Справочник подключений (09.10.26): завести, изменить, удалить, проверить до сохранения; запасная, убрать из
    # роли; откат к прежней версии файла. Только супер-администратору, каждое изменение — в журнал с именем.
    def _routes(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ConnectorError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/monitoring/models/endpoint")
    def mon_models_save(body: RoutePointIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        _routes(lr.save_point, body.name, body.fields, by=u.get("name") or u["role"], old_name=body.old_name)
        return lr.panel()

    @app.post("/api/monitoring/models/endpoint/delete")
    def mon_models_delete(body: RoutePointIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        _routes(lr.delete_point, body.name, by=u.get("name") or u["role"])
        return lr.panel()

    @app.post("/api/monitoring/models/endpoint/test")
    def mon_models_test(body: RoutePointIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        ok, detail = _routes(lr.test_point, body.fields)
        return {"ok": ok, "detail": detail}

    @app.post("/api/monitoring/models/role")
    def mon_models_role(body: RouteRoleIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        fn = {"add": lr.add_to_role, "remove": lr.remove_from_role}.get(body.action)
        if fn is None:
            raise HTTPException(400, "action — add или remove")
        _routes(fn, body.role, body.point, by=u.get("name") or u["role"])
        return lr.panel()

    @app.post("/api/monitoring/models/rollback")
    def mon_models_rollback(u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        _routes(lr.rollback, by=u.get("name") or u["role"])
        return lr.panel()

    @app.post("/api/monitoring/models/check")
    def mon_models_check(u: dict = Depends(super_admin)):
        from ..connectors.llm_routes import check_all
        try:
            return {"results": check_all()}
        except ConnectorError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/monitoring")
    def monitoring(u: dict = Depends(super_admin)):
        conns = []
        for kind in ("source", "asr", "vision", "llm", "output"):
            for c in plugins.all(kind):
                try:
                    h = c.health() if kind != "llm" or c.name == "mock" else {"name": c.name, "ok": None,
                                                                             "detail": "проверка по запросу"}
                except Exception as e:  # монитор не должен падать целиком
                    h = {"name": c.name, "ok": False, "detail": type(e).__name__}
                conns.append({"kind": kind, **h})
        tech = store.q("SELECT id, title, payload, created_at FROM cards WHERE kind='technical' AND status='open' "
                       "ORDER BY id DESC LIMIT 50")
        # выбранный при развёртывании инструмент модели; ключ — только «задан / не задан», без значения
        tool = {"tool": os.environ.get("MEETFLOW_LLM", "mock"), "generator": getattr(pipe.gen, "model", ""),
                "verifier": getattr(pipe.ver, "model", ""), "max_answer_tokens": theme.get("llm.max_answer_tokens", 4096),
                "openrouter_key_set": bool(os.environ.get("OPENROUTER_API_KEY", "").strip())}
        return {"connectors": conns, "technical_messages": tech, "journal": pipe.journal.records[-50:],
                "todo": theme.todo(), "llm_tool": tool}

    # ---------------------------------------------------------------- вход по паролю (как в ERP и Планёрке)
    def _csrf(request: Request) -> None:
        if request.headers.get("x-requested-with") != "MeetFlow":
            raise HTTPException(403, "Запрос без защитного заголовка.")

    @app.get("/api/auth/mode")
    def auth_mode():
        return {"auth_required": accounts.auth_required()}

    @app.post("/api/auth/login")
    def auth_login(body: LoginIn, request: Request):
        _csrf(request)
        try:
            a = accounts.check(body.login, body.password, client_ip(request))
        except AuthError as e:
            raise HTTPException(401, str(e)) from None
        resp = JSONResponse({"login": a["login"], "full_name": a["full_name"], "role": a["role"]})
        resp.set_cookie(COOKIE, accounts.open_session(a), httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", max_age=12 * 3600)
        return resp

    @app.post("/api/auth/logout")
    def auth_logout(request: Request):
        _csrf(request)
        accounts.close_session(request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/api/auth/me")
    def auth_me(u: dict = Depends(user)):
        return {**u, "auth_required": accounts.auth_required()}

    @app.post("/api/auth/mode")
    def auth_set_mode(body: ModeIn, request: Request, u: dict = Depends(super_admin)):
        """Включить вход — только подтвердив логин и пароль супер-администратора (иначе войти будет нечем);
        выключить при включённом входе — своим паролем (украденная сессия не снимет защиту одним запросом)."""
        was = accounts.auth_required()
        if body.auth_required != was:
            confirm_super(u, body.login, body.password, request)
            accounts.set_auth_required(body.auth_required, u["name"] or u["role"])
            pipe.cards.open(None, "technical", "Вход по логину и паролю " + ("ВКЛЮЧЁН" if body.auth_required
                            else "ВЫКЛЮЧЕН (тестовый режим)"), {"кто": u["name"] or u["role"]})
        return {"auth_required": accounts.auth_required()}

    @app.get("/api/monitoring/accounts")
    def mon_accounts(u: dict = Depends(super_admin)):
        return accounts.list()

    @app.post("/api/monitoring/accounts")
    def mon_accounts_save(body: AccountIn, u: dict = Depends(super_admin)):
        if body.role not in theme["roles"]:
            raise HTTPException(422, "Такой роли нет в теме.")
        try:
            a = accounts.save(body.login, body.full_name, body.role, body.password)
        except AuthError as e:
            raise HTTPException(422, str(e)) from None
        pipe.cards.open(None, "technical", f"Доступ выдан или пароль сменён: {a['login']}",
                        {"роль": a["role"], "кто": u["name"] or u["role"]})
        return accounts.list()

    # ---------------------------------------------------------------- Мониторинг RealTime (как в ERP)
    def _row(name: str, state: str, detail: str) -> dict:
        return {"name": name, "state": state, "detail": detail}

    def _services() -> list[dict]:
        tool = os.environ.get("MEETFLOW_LLM", "mock")
        key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        gen, ver = getattr(pipe.gen, "model", "") or "", getattr(pipe.ver, "model", "") or ""
        rows = []
        if tool == "mock":
            rows.append(_row("Модель", "выкл.", "стенд без модели: протоколы собирает заглушка"))
        elif tool == "openrouter" and not key:
            rows.append(_row("Модель", "нет", "OpenRouter: ключ OPENROUTER_API_KEY не задан"))
        else:
            rows.append(_row("Модель", "живо", f"{tool}: генерирует {gen or 'по маршрутам'}"))
            rows.append(_row("Модель проверки", "живо", (ver or "по маршрутам") +
                             (" — та же, что генерация" if ver and ver == gen else "")))
        try:
            store.q("SELECT 1 AS x")
            size = Path(store.path).stat().st_size / 1024 if store.path != ":memory:" else 0
            rows.append(_row("База данных", "живо", f"{store.path} · {size:.0f} КБ"))
        except Exception as e:  # noqa: BLE001
            rows.append(_row("База данных", "нет", type(e).__name__))
        last = (backups.files() or [{}])[0].get("at", "")
        rows.append(_row("Автобэкап", "выкл." if not backups.enabled else "живо" if backups.running else "нет",
                         ("выключен переменной MEETFLOW_BACKUP=off" if not backups.enabled else
                          f"раз в {backups.hours:g} ч, хранить {backups.keep}" + (f"; последняя копия {last}" if last else "")
                          + (f"; сбой: {backups.last_error}" if backups.last_error else ""))))
        rows.append(_row("Сервер", "живо", f"pid {os.getpid()} · {socket.gethostname()}"))
        for p in store.q("SELECT id, name FROM projects ORDER BY id"):
            st = intake.state(p["id"])
            last_at = (st.get("last_scan") or {}).get("at", "—")
            useful = (st.get("last_useful_scan") or {}).get("at", "—")
            if not st["folder"]:
                rows.append(_row(f"Папка-приёмник · {p['name']}", "выкл.", "не задана"))
            elif not st.get("exists"):
                rows.append(_row(f"Папка-приёмник · {p['name']}", "нет", f"{st['folder']} — не найдена"))
            elif not st["worker"]:
                rows.append(_row(f"Папка-приёмник · {p['name']}", "нет", f"{st['folder']} — фоновый забор не запущен"))
            elif st.get("stalled"):
                rows.append(_row(f"Папка-приёмник · {p['name']}", "нет",
                                 f"{st['folder']} — поток завис: проходов нет дольше трёх интервалов"))
            else:
                rows.append(_row(f"Папка-приёмник · {p['name']}", "живо",
                                 f"{st['folder']} · раз в {st['interval']} с · последний проход {last_at} · "
                                 f"последний результативный {useful}"))
        asr = [c for c in plugins.all("asr")]
        try:
            asr_ok = [c for c in asr if c.health().get("ok")]
        except Exception:  # noqa: BLE001
            asr_ok = []
        rows.append(_row("Распознавание записей", "живо" if asr_ok else "нет" if asr else "выкл.",
                         ", ".join(c.name for c in asr_ok) if asr_ok else "инструменты распознавания не найдены"
                         if asr else "коннектор не подключён"))
        vb = voice_base_state(store.get_setting("voice_base_path"))
        rows.append(_row("База голосов", "живо" if vb.get("ok") else "выкл." if not vb.get("path") else "нет",
                         (f"{vb.get('path')} · отпечатков {vb.get('samples')}" if vb.get("ok") else
                          vb.get("detail") or "не задана")))
        rows.append(_row("Досмотр реплик к системе", "живо" if pipe.guard_llm else "выкл.",
                         "модель роли guard" if pipe.guard_llm else "роль guard в маршрутах не задана — решает правило"))
        return rows

    def _tech_cleanup() -> None:
        """Технические сообщения старше N дней закрываются сами (ERP: 2 дня)."""
        days = int(os.environ.get("MEETFLOW_SYSTEM_MESSAGES_KEEP_DAYS", "2") or 2)
        edge = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        for r in store.q("SELECT id FROM cards WHERE kind='technical' AND status='open' AND created_at < ?", (edge,)):
            store.update("cards", r["id"], status=CardStatus.ACCEPTED.value, resolution="закрыто по сроку",
                         resolved_at=now())

    def _awaiting() -> list[dict]:
        _tech_cleanup()
        out = []
        n = store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind != 'technical'")[0]["n"]
        out.append({"key": "cards", "title": "Карточки «Конфликтов»", "count": n, "link": "#cards",
                    "need": "Решить: кто исполнитель, задача ли это, закрыта ли задача.",
                    "if_not": "Задачи остаются без исполнителя или не заводятся; нерешённые снимаются по сроку."})
        n = store.q("SELECT COUNT(*) AS n FROM people WHERE confirmed=0")[0]["n"]
        out.append({"key": "people", "title": "Неподтверждённые люди в «Команде»", "count": n, "link": "#team",
                    "need": "Подтвердить нового человека или объединить с существующим.",
                    "if_not": "Задачи на него заведены, но сверка следующих встреч может ошибаться."})
        no_date, stopped = [], []
        for p in store.q("SELECT id, name FROM projects ORDER BY id"):
            f = intake.folder(p["id"])
            if f and Path(f).is_dir():
                no_date += [f"{p['name']}: {x}" for x in preview_folder(Path(f))["no_date"]]
                sd = Path(f) / "остановлено"
                stopped += [f"{p['name']}: {x.name}" for x in sd.glob("*") if x.is_file()] if sd.is_dir() else []
        out.append({"key": "no_date", "title": "Файлы без одной даты в папке-приёмнике", "count": len(no_date),
                    "items": no_date[:10], "link": "#live", "need": "Переименовать файл: в имени — одна дата встречи.",
                    "if_not": "Файл так и лежит в папке, встреча не разбирается."})
        out.append({"key": "stopped", "title": "Остановлено по пределу", "count": len(stopped), "items": stopped[:10],
                    "link": "#system/runs", "need": "Решить: повторить прогон вручную или убрать файл.",
                    "if_not": "Протокол встречи неполный."})
        n = store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind='technical'")[0]["n"]
        out.append({"key": "tech", "title": "Системные сообщения", "count": n, "link": "#system/messages",
                    "need": "Прочитать и закрыть.", "if_not": "Закроются сами через срок хранения."})
        return out

    @app.get("/api/monitoring/live")
    def mon_live(pid: int | None = None, u: dict = Depends(super_admin)):
        aw = _awaiting()
        rec = store.q("SELECT s.name, s.created_at, m.date FROM sources s JOIN meetings m ON m.id = s.meeting_id "
                      "WHERE s.removed_reason LIKE 'запись распознана%' ORDER BY s.id DESC LIMIT 5")
        day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        q = {"cards_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind != 'technical'")[0]["n"],
             "cards_resolved_day": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind != 'technical' AND resolved_at >= ?",
                                           (day,))[0]["n"],
             "tech_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind='technical'")[0]["n"]}
        return {"services": _services(), "awaiting_total": sum(g["count"] for g in aw), "recognition": rec, "queue": q,
                "intake": intake.state(pid) if pid and store.get("projects", pid) else None,
                "min_interval": MIN_INTERVAL, "auth_required": accounts.auth_required()}

    @app.get("/api/monitoring/awaiting-input")
    def mon_awaiting(u: dict = Depends(super_admin)):
        groups = _awaiting()
        return {"total": sum(g["count"] for g in groups), "groups": groups}

    # ---------------------------------------------------------------- Параметры системы (как в ERP)
    @app.get("/api/monitoring/system-messages")
    def mon_messages(u: dict = Depends(super_admin)):
        _tech_cleanup()
        rows = store.q("SELECT id, title, payload, created_at FROM cards WHERE kind='technical' AND status='open' "
                       "ORDER BY id DESC LIMIT 100")
        return [{**r, "payload": json.loads(r["payload"] or "{}")} for r in rows]

    @app.post("/api/monitoring/system-messages/{cid}/close")
    def mon_message_close(cid: int, u: dict = Depends(super_admin)):
        c = store.get("cards", cid)
        if not c or c["kind"] != "technical":
            raise HTTPException(404, "Сообщение не найдено.")
        store.update("cards", cid, status=CardStatus.ACCEPTED.value, resolution=f"закрыто: {u['name'] or u['role']}",
                     resolved_at=now())
        return {"ok": True}

    @app.post("/api/monitoring/system-messages/close-all")
    def mon_message_close_all(u: dict = Depends(super_admin)):
        rows = store.q("SELECT id FROM cards WHERE kind='technical' AND status='open'")
        for r in rows:
            store.update("cards", r["id"], status=CardStatus.ACCEPTED.value,
                         resolution=f"закрыто: {u['name'] or u['role']}", resolved_at=now())
        return {"closed": len(rows)}

    @app.get("/api/monitoring/data-state")
    def mon_data_state(u: dict = Depends(super_admin)):
        out = []
        for p in store.q("SELECT id, name FROM projects ORDER BY id"):
            pid = p["id"]
            one = lambda sql, a=(pid,): store.q(sql, a)[0]["n"]  # noqa: E731
            out.append({"project": p["name"],
                        "meetings": one("SELECT COUNT(*) AS n FROM meetings WHERE project_id=?"),
                        "with_protocol": one("SELECT COUNT(*) AS n FROM meetings WHERE project_id=? AND protocol_md IS NOT NULL"),
                        "sources": {r["kind"]: r["n"] for r in store.q(
                            "SELECT s.kind, COUNT(*) AS n FROM sources s JOIN meetings m ON m.id=s.meeting_id "
                            "WHERE m.project_id=? AND s.removed_at IS NULL GROUP BY s.kind", (pid,))},
                        "tasks": {r["status"]: r["n"] for r in store.q(
                            "SELECT status, COUNT(*) AS n FROM tasks WHERE project_id=? GROUP BY status", (pid,))},
                        "closed_by": {r["source"]: r["n"] for r in store.q(
                            "SELECT h.source, COUNT(*) AS n FROM task_history h JOIN tasks t ON t.id=h.task_id WHERE "
                            "t.project_id=? AND h.new_status IN ('done','dropped') GROUP BY h.source", (pid,))},
                        "people": one("SELECT COUNT(*) AS n FROM people WHERE project_id=?"),
                        "people_unconfirmed": one("SELECT COUNT(*) AS n FROM people WHERE project_id=? AND confirmed=0"),
                        "people_external": one("SELECT COUNT(*) AS n FROM people WHERE project_id=? AND external=1"),
                        "units": one("SELECT COUNT(*) AS n FROM units WHERE project_id=?")})
        return out

    @app.get("/api/monitoring/static")
    def mon_static(u: dict = Depends(super_admin)):
        def size(pth: Path) -> float:
            if pth.is_file():
                return round(pth.stat().st_size / 1024, 1)
            return round(sum(f.stat().st_size for f in pth.rglob("*") if f.is_file()) / 1024, 1) if pth.is_dir() else 0
        db = Path(store.path)
        journal = Path(pipe.journal.path) if pipe.journal.path else None
        return {"disk": {"db": str(db), "db_kb": size(db) if store.path != ":memory:" else 0,
                         "journal": str(journal) if journal else "", "journal_kb": size(journal) if journal else 0,
                         "backups_dir": str(backups.dir), "backups_kb": size(backups.dir)},
                "backup": {"enabled": backups.enabled, "running": backups.running, "hours": backups.hours,
                           "keep": backups.keep, "files": backups.files()[:10], "error": backups.last_error},
                "access": {"auth_required": accounts.auth_required(), "accounts": accounts.list(),
                           "roles": theme["roles"], "host": os.environ.get("MEETFLOW_HOST", "127.0.0.1")},
                "models": {"tool": os.environ.get("MEETFLOW_LLM", "mock"), "generator": getattr(pipe.gen, "model", ""),
                           "verifier": getattr(pipe.ver, "model", ""),
                           "max_answer_tokens": theme.get("llm.max_answer_tokens", 4096),
                           "budget": theme.get("budget", {})}}

    @app.post("/api/monitoring/backup-now")
    def mon_backup_now(u: dict = Depends(super_admin)):
        if store.path == ":memory:":
            raise HTTPException(400, "База в памяти — копировать нечего.")
        f = backups.snapshot(manual=True)
        return {"file": f.name, "files": backups.files()[:10]}

    @app.get("/api/monitoring/decisions")
    def mon_decisions(u: dict = Depends(super_admin)):
        return store.q("SELECT d.what, d.decision, d.why, d.at, p.name AS project FROM decisions d LEFT JOIN projects p "
                       "ON p.id = d.project_id ORDER BY d.id DESC LIMIT 200")

    @app.get("/api/monitoring/rules")
    def mon_rules(u: dict = Depends(super_admin)):
        return store.q("SELECT r.id, r.kind, r.key, r.value, r.active, r.applied_count, r.created_at, r.revoked_at, "
                       "p.name AS project FROM operator_rules r LEFT JOIN projects p ON p.id = r.project_id "
                       "ORDER BY r.id DESC LIMIT 200")

    @app.post("/api/monitoring/rules/{rid}/{action}")
    def mon_rule_act(rid: int, action: Literal["revoke", "restore"], u: dict = Depends(super_admin)):
        if not store.get("operator_rules", rid):
            raise HTTPException(404, "Правило не найдено.")
        (pipe.memory.revoke if action == "revoke" else pipe.memory.restore)(rid)
        return {"ok": True}

    @app.get("/api/settings/thresholds")
    def get_thresholds(u: dict = Depends(super_admin)):
        cc = store.get_setting("card_cleanup_days")
        return {"overdue_highlight_working_days": int(store.get_setting("overdue_highlight_working_days", None, 7) or 7),
                "card_cleanup_days": int(cc if cc is not None else theme.get("operator.card_cleanup_days", 0) or 0),
                "card_cleanup_source": "задан на экране" if cc is not None else "из темы"}

    @app.post("/api/settings/thresholds")
    def set_thresholds(body: ThresholdsIn, u: dict = Depends(super_admin)):
        by = u["name"] or u["role"]
        for k in ("overdue_highlight_working_days", "card_cleanup_days"):
            v = getattr(body, k)
            if v is not None:
                old = store.get_setting(k)
                store.set_setting(k, v, None, by)
                if old != v:
                    pipe.cards.open(None, "technical", f"Порог изменён: {k}", {"было": old, "стало": v, "кто": by})
        return get_thresholds(u)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def main() -> None:  # python -m meetflow.web.app
    import uvicorn
    port = int(os.environ.get("MEETFLOW_PORT", "8002"))
    uvicorn.run(create_app(), host=os.environ.get("MEETFLOW_HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
