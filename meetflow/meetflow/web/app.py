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
from ..core.draft_checks import clean_document
from ..core.budget import BudgetExceeded
from ..connectors.llm_mock import MockLLM
from ..connectors.llm_ollama import OllamaLLM
from ..connectors.llm_openrouter import OpenRouterLLM
from ..connectors.registry import default_registry
from ..connectors.team_shared import team_shared_state
from ..connectors.voice_base import voice_base_state
from ..core.config import Theme, list_themes, load_theme
from ..core.team_sync import sync_people
from ..core.accounts import Accounts, AuthError
from ..core.backup import Backups
from ..core.dates import due_text, lenient_date
from ..core.intake import MIN_INTERVAL, IntakeError, IntakeService, preview_folder, sign_folder, validate_folder
from ..core.runs_report import runs_report
from ..core import roadmap as roadmap_mod
from ..core import search as search_mod
from ..core import units as units_mod
from ..core.pipeline import MeetingPipeline
from ..core import norm_yo
from ..core.store import Store, now
from ..core.text import same_word, stems, words
from ..core.types import CardStatus, TaskStatus

STATIC = Path(__file__).parent / "static"
ADMIN_ROLES = {"project_admin", "super_admin"}


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    parent_id: int = 0                  # 0 — без надпроекта


class ProjectEditIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    parent_id: int = 0                  # 0 — убрать надпроект
    archived: bool = False


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


class OperationalIn(BaseModel):
    """Пометка «оперативная» одним нажатием (как ERP, 26.10.2026): True — отметить, False — снять."""
    on: bool


class FolderIn(BaseModel):
    path: str = Field("", max_length=500)
    path_repeat: str = Field("", max_length=500)
    # смена папки — в два шага, второй по паролю супер-администратора (как в Планёрке и ERP с 07.10.26)
    confirm: bool = False
    login: str = Field("", max_length=100)            # в тестовом режиме — чья учётная запись подтверждает
    current_password: str = Field("", max_length=200)


class TopicIn(BaseModel):
    topic: str = Field("", max_length=300)


class ProtocolEditIn(BaseModel):
    markdown: str = Field(min_length=1, max_length=2_000_000)


class ProtocolVersionIn(BaseModel):
    version: int


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
    show_doubt_mark: bool | None = None       # отметка «под вопросом» в реестре — выключатель на пилот (15.10.26)


class IntervalIn(BaseModel):
    seconds: int = Field(ge=MIN_INTERVAL, le=86400)


class RouteUseIn(BaseModel):
    role: str = Field(max_length=40)
    point: str = Field(max_length=100)


class RoutePointIn(BaseModel):
    name: str = Field(max_length=100)
    old_name: str = Field("", max_length=100)
    fields: dict = Field(default_factory=dict)
    key_value: str = Field("", max_length=400)    # ключ значением — только в хранилище вне git, наружу не отдаётся


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
    # действие карточки «под вопросом»: accept / custom / reject / duplicate (общая таблица кнопок, 15.10.26)
    action: str = Field("", max_length=20)
    # «новый человек» в карточке «тот же или новый» — только подтверждением, внешний с организацией и ролью
    new_full_name: str = Field("", max_length=200)
    new_organization: str = Field("", max_length=200)
    new_role: str = Field("", max_length=200)


class VoiceDecisionIn(BaseModel):
    ids: list[int] = Field(default_factory=list)
    decision: Literal["yes", "no", "other", "noise"] = "yes"
    name: str = Field("", max_length=200)
    # два почти равных кандидата (как ERP 26.10.2026): какой выбран — «pervyy» / «vtoroy»; только с «Это он»
    vybran: Literal["", "pervyy", "vtoroy"] = ""
    kandidat: str = Field("", max_length=200)


LLM_TOOLS = ("mock", "ollama", "openrouter", "routes")


def llm_mode() -> str:
    """Модели по умолчанию нет (правило владельца 13.10.26, ответ 15.10.26): без MEETFLOW_LLM — маршруты из «Моделей»,
    где роль без точек «не настроена»; заглушка — только явным MEETFLOW_LLM=mock."""
    return os.environ.get("MEETFLOW_LLM", "").strip().lower() or "routes"


def _llm(theme: Theme, side: str, journal: str | None = None):
    """Инструмент подключения: routes (умолчание) — цепочки точек по ролям из models.json, назначает
    супер-администратор в «Моделях» (connectors/llm_routes.py); mock — стенд без модели с плашкой, только явно;
    ollama / openrouter — модели из темы (llm.generator / llm.openrouter.*), в теме их по умолчанию нет.
    Потолок ответа — llm.max_answer_tokens, у точки — свой, если задан."""
    mode = llm_mode()
    if mode not in LLM_TOOLS:
        raise ValueError(f"MEETFLOW_LLM={mode}: допустимы {', '.join(LLM_TOOLS)}")
    if mode == "mock":
        return MockLLM()
    cap = int(theme.get("llm.max_answer_tokens", 4096))
    if mode == "routes":
        from ..connectors.llm_routes import RoutedLLM, ensure_file
        ensure_file()
        return RoutedLLM(side, max_answer_tokens=cap, journal_path=Path(journal) if journal else None)
    cfg = theme.get(f"llm.openrouter.{side}" if mode == "openrouter" else f"llm.{side}", {}) or {}
    if not str(cfg.get("model") or "").strip():
        from ..connectors.llm_routes import NotConfiguredLLM
        return NotConfiguredLLM(side)
    if mode == "openrouter":
        return OpenRouterLLM(model=cfg.get("model", ""), profile=cfg.get("profile", "generic"), max_answer_tokens=cap)
    return OllamaLLM(model=cfg.get("model", ""), profile=cfg.get("profile", "generic"),
                     num_ctx=int(cfg.get("num_ctx", 32768)), max_answer_tokens=cap)


def create_app(theme_name: str | None = None, db_path: str | None = None, journal: str | None = None,
               watch: bool | None = None) -> FastAPI:
    theme = load_theme(theme_name or os.environ.get("MEETFLOW_THEME", "_default"))
    store = Store(db_path or os.environ.get("MEETFLOW_DB", "data/meetflow.db"))
    plugins = default_registry()
    journal = journal or os.environ.get("MEETFLOW_JOURNAL", "data/logs/llm_calls.jsonl")
    pipe = MeetingPipeline(theme, store, plugins, _llm(theme, "generator", journal), _llm(theme, "verifier", journal),
                           journal)
    if llm_mode() == "routes":
        from ..connectors.llm_routes import RoutedLLM, configured
        if configured("guard"):   # досмотр — только если у роли guard есть точки; без них решает правило guard.py
            pipe.guard_llm = RoutedLLM("guard", max_answer_tokens=5, journal_path=Path(journal))
    # Копия базы на другом месте не дотягивается до файлов прежнего (стенд 22): база помнит, где лежит; открыта в
    # другом месте — ссылки на внешние папки (приёмник, база голосов) откладываются до подтверждения супер-админом.
    if store.path != ":memory:":
        home, here = store.get_setting("db_home"), str(Path(store.path).resolve())
        if home and home != here:
            moved = []
            for p in store.q("SELECT id, name FROM projects ORDER BY id"):
                wf = store.get_setting("watch_folder", p["id"])
                if wf:
                    store.set_setting("watch_folder_previous", wf, p["id"], "система")
                    store.set_setting("watch_folder", None, p["id"], "система")
                    moved.append(f"папка-приёмник «{p['name']}»: {wf}")
            vb = store.get_setting("voice_base_path")
            if vb:
                store.set_setting("voice_base_path_previous", vb, None, "система")
                store.set_setting("voice_base_path", None, None, "система")
                moved.append(f"база голосов: {vb}")
            pipe.cards.open(None, "technical", "База открыта на новом месте — внешние папки прежнего места отложены",
                            {"was": home, "now": here, "отложено": moved,
                             "why": "копия не должна забирать файлы прежней установки; задайте папки заново в «Настройках»"})
        if home != here:
            store.set_setting("db_home", here, None, "система")
    intake = IntakeService(pipe)
    from ..core.build_queue import BuildQueue, later
    queue = BuildQueue(pipe)
    pipe.queue = queue                     # автозапуск из папки-приёмника идёт через ту же очередь

    # Очередь распознавания на одну машину — общая аренда ERP, Планёрки и MeetFlow (recognition_lease.py): файл
    # лежит рядом с общей базой голосов. У MeetFlow путь к базе — в «Настройках», а не в переменной окружения.
    lease_from_env = bool(os.environ.get("RECOGNITION_LEASE_PATH", "").strip())

    def _lease_path() -> None:
        vb = store.get_setting("voice_base_path")
        if not lease_from_env and vb and Path(vb).parent.is_dir():
            os.environ["RECOGNITION_LEASE_PATH"] = str(Path(vb).parent / "recognition_lease.json")

    _lease_path()
    from ..connectors.shared import recognition_lease
    left = recognition_lease.снять_брошенную("meetflow")     # своя аренда от умершего процесса — снимаем при старте
    if left:
        pipe.cards.open(None, "technical", "Очередь распознавания: снята брошенная аренда", {"detail": left})
    accounts = Accounts(store)
    backups = Backups(store.path)
    watch_on = os.environ.get("MEETFLOW_WATCH", "on") != "off" if watch is None else watch

    def _primary() -> bool:
        """Метка запуска рядом с базой (стенд 34, Планёрка 0e79042): «первый уже работает» — только если его процесс
        жив И его порт слушает. Завис при остановке и порт молчит — метка перехватывается, иначе следующие запуски
        работали бы «вторыми» без забора из папки, и сбой не был бы виден."""
        if store.path == ":memory:":
            return True
        marker = Path(store.path).with_suffix(".launch.json")
        try:
            m = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        from ..core.build_queue import _alive
        pid, port = int(m.get("pid") or 0), int(m.get("port") or 0)
        if pid and pid != os.getpid() and _alive(pid) and port:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return False
            except OSError:
                pass                       # процесс жив, а порт не слушает — завис; метку берём себе
        try:
            marker.write_text(json.dumps({"pid": os.getpid(), "port": int(os.environ.get("MEETFLOW_PORT", "0") or 0),
                                          "started": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
        except OSError:
            pass
        return True

    @asynccontextmanager
    async def lifespan(_app):
        if watch_on and _primary():
            intake.start()        # фоновый забор из папок-приёмников
            backups.start()       # автокопия базы по расписанию
        elif watch_on:
            pipe.cards.open(None, "technical", "Второй экземпляр MeetFlow на той же базе — забор из папки и автокопия "
                            "в нём выключены", {"why": "первый экземпляр работает: его процесс жив и порт слушает; "
                                                       "остановите лишний запуск"})
        yield
        intake.stop()
        backups.stop()

    app = FastAPI(title="MeetFlow", lifespan=lifespan)
    app.state.theme, app.state.store, app.state.pipe, app.state.intake = theme, store, pipe, intake
    app.state.queue = queue
    if os.environ.get("MEETFLOW_RESUME_ON_START", "on") != "off":
        queue.recover()       # начатое продолжается по записи о начале, независимо от автозапуска (стенд 19)

    def queue_rebuild(mid: int, pause: float) -> int:
        """Пересборка после смены модели — в очередь с «не раньше»: идущая сборка дожидается своего ответа, новая
        начнётся после паузы и после неё (стенд 41; прежде — поток со sleep в памяти, перезапуск его терял)."""
        m = store.get("meetings", mid)
        return queue.enqueue(m["project_id"], mid, "смена модели генерации", not_before=later(pause))
    app.state.queue_rebuild = queue_rebuild
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

    def doubt_visible(u: dict) -> bool:
        """Отметка «под вопросом» (решение владельца 15.10.26): только администраторам; выключена — никому.
        Проверяет сервер: причина сомнения не уходит тому, кому её не показывают (находка Планёрки 3411d1f)."""
        return u["role"] in admin_roles and bool(store.get_setting("show_doubt_mark", None, True))

    def task_out(t: dict, u: dict) -> dict:
        if not doubt_visible(u):
            return {**t, "doubt_reason": "", "doubt_label": ""}
        from ..connectors.shared.doubt_labels import подпись
        return {**t, "doubt_label": подпись(t.get("doubt_reason"))}    # короткая подпись — общая с ERP и Планёркой

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
        rows = store.q("SELECT id, name, theme, aliases, active, archived, parent_id FROM projects ORDER BY name")
        for r in rows:
            try:
                r["aliases"] = json.loads(r.get("aliases") or "[]")
            except (TypeError, ValueError):
                r["aliases"] = []
        return rows

    @app.post("/api/projects")
    def create_project(p: ProjectIn, u: dict = Depends(admin)):
        if p.parent_id:
            project_or_404(p.parent_id)
        return {"id": store.insert("projects", name=p.name.strip(), theme=theme.id,
                                   aliases=json.dumps([a.strip() for a in p.aliases if a.strip()], ensure_ascii=False),
                                   active=1, archived=0, parent_id=p.parent_id or None, created_at=now())}

    @app.patch("/api/projects/{pid}")
    def edit_project(pid: int, p: ProjectEditIn, u: dict = Depends(admin)):
        project_or_404(pid)
        parent = p.parent_id or None
        if parent:
            project_or_404(parent)
            if parent == pid:
                raise HTTPException(422, "Проект не может быть надпроектом сам себе.")
            seen, cur = {pid}, parent
            while cur:
                if cur in seen:
                    raise HTTPException(422, "Так получится кольцо проектов — выберите другой надпроект.")
                seen.add(cur)
                row = store.get("projects", cur) or {}
                cur = row.get("parent_id")
        store.update("projects", pid, name=p.name.strip(),
                     aliases=json.dumps([a.strip() for a in p.aliases if a.strip()], ensure_ascii=False),
                     parent_id=parent, archived=int(bool(p.archived)))
        return {"ok": True}

    @app.get("/api/projects/{pid}/people")
    def people(pid: int):
        project_or_404(pid)
        # подтверждённые люди общей «Команды» — в проектную, иначе экран «Команда» пуст (26.10.2026)
        sync_people(store, pid, store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH"))
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
            org_same = norm_yo.равны(r["organization"], p.organization)     # «е» = «ё» (ERP 26.10.2026)
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
        if pid:
            project_or_404(pid)
            rows = store.q("SELECT id, date, label, protocol_built_at, project_id FROM meetings "
                           "WHERE project_id=? ORDER BY date DESC", (pid,))
        else:
            rows = store.q("SELECT m.id, m.date, m.label, m.protocol_built_at, m.project_id, p.name AS project_name "
                           "FROM meetings m LEFT JOIN projects p ON p.id=m.project_id ORDER BY m.date DESC, p.name")
        for r in rows:
            r["has_protocol"] = bool(r.pop("protocol_built_at"))
        return rows

    @app.post("/api/projects/{pid}/meetings")
    def create_meeting(pid: int, m: MeetingIn, u: dict = Depends(admin)):
        project_or_404(pid)
        return {"id": store.insert("meetings", project_id=pid, date=m.date, label=m.label)}

    @app.get("/api/projects/{pid}/prep")
    def prep(pid: int):
        """«Подготовка встречи»: ближайшая встреча, план, материалы, протокол."""
        project_or_404(pid)
        rows = store.q("SELECT m.id, m.date, m.label, m.topic, m.plan_built_at, m.protocol_built_at, "
                       "(SELECT COUNT(*) FROM sources s WHERE s.meeting_id=m.id AND s.removed_at IS NULL) AS sources "
                       "FROM meetings m WHERE m.project_id=? ORDER BY m.date DESC", (pid,))
        for r in rows:
            r["has_plan"] = bool(r.pop("plan_built_at"))
            r["has_protocol"] = bool(r.pop("protocol_built_at"))
        return rows

    @app.get("/api/meetings/{mid}/plan")
    def get_plan(mid: int):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        return {"meeting_id": mid, "date": m.get("date"), "topic": m.get("topic") or "",
                "markdown": m.get("plan_md") or "", "built_at": m.get("plan_built_at")}

    @app.post("/api/meetings/{mid}/plan/build")
    def build_plan(mid: int, u: dict = Depends(admin)):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        try:
            return pipe.build_plan(m["project_id"], mid)
        except BudgetExceeded as exc:
            raise HTTPException(422, str(exc)) from exc
        except ConnectorError as exc:
            raise HTTPException(422, f"Модель не ответила: {exc}") from exc

    @app.post("/api/meetings/{mid}/topic")
    def set_topic(mid: int, body: TopicIn, u: dict = Depends(admin)):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        topic = body.topic.strip()[:300]
        store.update("meetings", mid, topic=topic)
        return {"ok": True, "topic": topic}

    @app.get("/api/projects/{pid}/summary")
    def project_summary(pid: int):
        """«Сводка» статуса проекта — как вкладка ERP: цифры по задачам, решениям, вопросам и вехам."""
        project_or_404(pid)
        today = date_cls.today().isoformat()
        tasks = store.q("SELECT status, due_date FROM tasks WHERE project_id=?", (pid,))
        units = store.q("SELECT kind, status FROM units WHERE project_id=?", (pid,))
        meetings = store.q("SELECT date, protocol_built_at FROM meetings WHERE project_id=?", (pid,))
        active = [t for t in tasks if t["status"] == "active"]
        overdue = [t for t in active if t["due_date"] and t["due_date"] < today]
        return {
            "tasks_active": len(active), "tasks_done": sum(1 for t in tasks if t["status"] == "done"),
            "tasks_overdue": len(overdue), "tasks_no_due": sum(1 for t in active if not t["due_date"]),
            "decisions": sum(1 for u in units if u["kind"] == "decision" and u["status"] in ("open", "active")),
            "agreements": sum(1 for u in units if u["kind"] == "agreement" and u["status"] in ("open", "active")),
            "questions": sum(1 for u in units if u["kind"] == "open_question" and u["status"] in ("open", "active")),
            "milestones": sum(1 for u in units if u["kind"] == "milestone" and u["status"] in ("open", "active")),
            "meetings": len(meetings), "with_protocol": sum(1 for m in meetings if m["protocol_built_at"]),
            "last_meeting": max((m["date"] or "" for m in meetings), default=""),
        }

    @app.get("/api/projects/{pid}/agreements")
    def agreements(pid: int, kind: str = "", status: str = "open", since: str = "", till: str = ""):
        """«Договорённости»: решения, договорённости, открытые вопросы, вехи — как отдельный экран ERP."""
        if pid:
            project_or_404(pid)
        where, args = (["u.project_id=?"], [pid]) if pid else (["1=1"], [])
        if kind:
            where.append("u.kind=?")
            args.append(kind)
        if status == "open":
            where.append("u.status IN ('open','active')")
        elif status and status != "all":
            where.append("u.status=?")
            args.append(status)
        if since:
            where.append("COALESCE(m.date,'') >= ?")
            args.append(since)
        if till:
            where.append("COALESCE(m.date,'') <= ?")
            args.append(till)
        rows = store.q("SELECT u.id, u.kind, u.text, u.quote, u.status, u.planned_date, u.ts, u.meeting_id, "
                       "u.project_id, p.name AS project_name, m.date AS meeting_date "
                       "FROM units u LEFT JOIN meetings m ON m.id=u.meeting_id "
                       "LEFT JOIN projects p ON p.id=u.project_id "
                       "WHERE " + " AND ".join(where) + " ORDER BY COALESCE(m.date,'') DESC, u.line_from, u.id",
                       tuple(args))
        for r in rows:
            r["kind_ru"] = units_mod.KIND_RU.get(r["kind"], r["kind"])
        return rows

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
        rows = store.q("SELECT id, name, kind, created_at, local_asr, meta FROM sources "
                       "WHERE meeting_id=? AND removed_at IS NULL", (mid,))
        for r in rows:
            try:
                r["meta"] = json.loads(r.get("meta") or "{}")
            except (TypeError, ValueError):
                r["meta"] = {}
        return rows

    @app.get("/api/meetings/{mid}/recognition")
    def recognition(mid: int):
        """Последняя запись журнала распознавания по встрече: точка, модель, реплики, говорящие."""
        from ..core import asr_journal
        return asr_journal.last_for_meeting(pipe.asr_journal_path, mid)

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
        # через очередь (стенд 41): одна сборка за раз по датам; ответ — когда сборка этой встречи закончится
        rid = queue.enqueue(m["project_id"], mid, "кнопка", by=u.get("name") or u["role"])
        res = queue.wait(rid)
        if res.get("internal_error"):          # карточка уже заведена исполнителем очереди — одна на одинаковый сбой
            raise HTTPException(500, res["detail"])
        return res

    @app.get("/api/meetings/{mid}/build")
    def build_state(mid: int, u: dict = Depends(user)):
        """Состояние сборки встречи — для экрана (стенд 3, 4): в очереди (какая по счёту) или идёт с какого часа."""
        if not store.get("meetings", mid):
            raise HTTPException(404, "Встреча не найдена.")
        return queue.state(mid)

    @app.post("/api/meetings/{mid}/enqueue")
    def enqueue(mid: int, u: dict = Depends(admin)):
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        queue.enqueue(m["project_id"], mid, "кнопка", by=u.get("name") or u["role"])
        return queue.state(mid)

    @app.get("/api/meetings/{mid}/tasks")
    def meeting_tasks(mid: int, u: dict = Depends(user)):
        """Задачи встречи (стенд 5): у каждой встречи — её задачи; «под вопросом» — только администраторам."""
        if not store.get("meetings", mid):
            raise HTTPException(404, "Встреча не найдена.")
        rows = store.q("SELECT * FROM tasks WHERE source_meeting_id=? AND status<>'dropped' ORDER BY id", (mid,))
        return [task_out({k: v for k, v in r.items() if k != "project_id"}, u) for r in rows]

    def shown(md: str | None, project_id: int | None) -> str:
        """Дверь показа документа: строки снятых задач не показываются (хранимый текст не меняется, 26.10.2026)."""
        from ..core.tablica_zadach import без_снятых
        if not md or project_id is None:
            return md or ""
        rows = store.q("SELECT description, status FROM tasks WHERE project_id=?", (project_id,))
        return без_снятых(md, {r["description"] for r in rows if r["status"] == "dropped"},
                          {r["description"] for r in rows if r["status"] != "dropped"})

    @app.get("/api/meetings/{mid}/protocol")
    def protocol(mid: int, u: dict = Depends(user)):
        m = store.get("meetings", mid)
        if not m or not m["protocol_md"]:
            raise HTTPException(404, "Протокола пока нет.")
        # служебные поля (замечания проверки, когда собран) — только администраторам; участнику — документ
        # (находка циклов ролей ERP и Планёрки 15.10.26: Планёрка GET /meetings/{id}/minutes отдавала их всем)
        staff = u["role"] in admin_roles
        return {"markdown": shown(m["protocol_md"], m["project_id"]),
                "built_at": m["protocol_built_at"] if staff else None,
                "topic": m.get("topic") or "", "leader": m.get("leader") or "",
                "review_notes": json.loads(m["review_notes"] or "[]") if staff else [], "units": meeting_units(mid)}

    @app.get("/api/meetings/{mid}/protocol/versions")
    def protocol_versions(mid: int, u: dict = Depends(admin)):
        return store.q("SELECT id, version, model, built_at FROM protocol_versions WHERE meeting_id=? "
                       "ORDER BY version DESC", (mid,))

    @app.post("/api/meetings/{mid}/protocol/edit")
    def edit_protocol(mid: int, body: ProtocolEditIn, u: dict = Depends(admin)):
        """Правка текста протокола с новой версией: прежняя не затирается."""
        m = store.get("meetings", mid)
        if not m:
            raise HTTPException(404, "Встреча не найдена.")
        last = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (mid,))
        version = int((last[0]["v"] if last and last[0]["v"] is not None else 0) or 0) + 1
        store.insert("protocol_versions", meeting_id=mid, version=version, protocol_md=body.markdown,
                     model="правка", built_at=now())
        store.update("meetings", mid, protocol_md=body.markdown)
        return {"ok": True, "version": version}

    @app.post("/api/meetings/{mid}/protocol/restore")
    def restore_protocol(mid: int, body: ProtocolVersionIn, u: dict = Depends(admin)):
        row = store.q("SELECT protocol_md FROM protocol_versions WHERE meeting_id=? AND version=?",
                      (mid, body.version))
        if not row:
            raise HTTPException(404, "Версия не найдена.")
        last = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (mid,))
        version = int((last[0]["v"] if last and last[0]["v"] is not None else 0) or 0) + 1
        store.insert("protocol_versions", meeting_id=mid, version=version, protocol_md=row[0]["protocol_md"],
                     model=f"восстановлена версия {body.version}", built_at=now())
        store.update("meetings", mid, protocol_md=row[0]["protocol_md"])
        return {"ok": True, "version": version}

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

    @app.get("/api/meetings/{mid}/versions")
    def protocol_versions(mid: int, u: dict = Depends(admin)):
        """История версий протокола (стенд 43): прежняя не затирается; модель — та, что написала текст (47)."""
        if not store.get("meetings", mid):
            raise HTTPException(404, "Встреча не найдена.")
        return store.q("SELECT version, model, built_at, protocol_md FROM protocol_versions WHERE meeting_id=? "
                       "ORDER BY version DESC", (mid,))

    @app.get("/api/meetings/{mid}/protocol.docx")
    def protocol_docx(mid: int):
        m = store.get("meetings", mid)
        if not m or not m["protocol_md"]:
            raise HTTPException(404, "Протокола пока нет.")
        out = DocxOutput(theme.get("design.document_font", "Times New Roman"),
                         int(theme.get("design.document_size_pt", 12)))
        # проверка кодом до передачи: старые протоколы хранят шапку с пометками; сам документ не переписывается
        return Response(out.render(clean_document(shown(m["protocol_md"], m["project_id"]))[0], "protocol"),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                 + quote(f"protocol_{m['date']}.docx")})

    @app.get("/api/projects/{pid}/tasks")
    def tasks(pid: int, status: Literal["active", "done", "dropped", "all"] = "active", u: dict = Depends(user)):
        if pid:
            project_or_404(pid)
        # снятые не показываются нигде (решение владелицы 26.10.2026, как ERP): ни по «all», ни по просьбе «dropped»
        st = None if status == "all" else TaskStatus(status)
        if st == TaskStatus.DROPPED:
            rows = []
        elif pid:
            rows = [r for r in pipe.reg.list(pid, st) if r["status"] != "dropped"]
        else:
            sql = ("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id=t.project_id "
                   "WHERE t.status!='dropped'" + (" AND t.status=?" if st else "") + " ORDER BY p.name, t.id")
            rows = store.q(sql, ((st.value,) if st else ()))
        counters: dict[int, int] = {}
        for r in rows:                         # номер — свой в каждом проекте
            key = int(r.get("project_id") or 0)
            counters[key] = counters.get(key, 0) + 1
            r["no"] = counters[key]
        # задача связана со встречей (стенд 5): дата встречи — для ссылки «встреча дд.мм.гггг — протокол»
        mdates = ({m["id"]: m["date"] for m in store.q("SELECT id, date FROM meetings WHERE project_id=?", (pid,))}
                  if pid else {m["id"]: m["date"] for m in store.q("SELECT id, date FROM meetings")})
        n = int(store.get_setting("overdue_highlight_working_days", None, 7) or 7)
        today = date_cls.today()
        from ..core import tablica_zadach
        dates_by_project: dict[int, list] = {}

        def dates_for(project_id: int):
            if project_id not in dates_by_project:
                dates_by_project[project_id] = tablica_zadach.даты_прошедших_встреч(store, project_id)
            return dates_by_project[project_id]

        def hint(r: dict) -> bool:   # «похоже на оперативную — отметить?»: только подсказка, пометку не ставит
            return tablica_zadach.похоже_на_оперативную(
                r, tablica_zadach.встреч_после(dates_for(int(r.get("project_id") or 0)),
                                               lenient_date(r.get("date_set"))))

        def overdue(r: dict) -> bool:   # как в Планёрке: N рабочих дней после срока, только у задач в работе
            d = lenient_date(r.get("due_date")) if r.get("status") == "active" else None
            if not d or d >= today:
                return False
            days, cur = 0, d
            while cur < today:
                cur += timedelta(days=1)
                days += cur.weekday() < 5
            return days >= n
        return [task_out({**{k: v for k, v in r.items() if k != "project_id"}, "overdue": overdue(r),
                          "project_name": r.get("project_name") or "",
                          "meeting_date": mdates.get(r.get("source_meeting_id")),
                          "operational": int(r.get("operational") or 0), "operational_hint": hint(r),
                          "due_text": due_text(r.get("due_date"), r.get("date_set"), r.get("due_kind"))}, u) for r in rows]

    @app.patch("/api/tasks/{tid}")
    def set_status(tid: int, body: StatusIn, u: dict = Depends(user)):
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена.")
        responsible = u["name"] and u["name"] == t["assignee"]
        if not can(u, "task_status") and not responsible:
            raise HTTPException(403, "Статус меняет ответственный или администратор.")
        pipe.reg.set_status(tid, body.status, "web_form", by=u["name"] or u["role"])
        return task_out(store.get("tasks", tid), u)

    @app.post("/api/tasks/{tid}/operational")
    def set_operational(tid: int, body: OperationalIn, u: dict = Depends(admin)):
        """Пометка «оперативная» — администратор одним нажатием; строка истории «оперативная: отмечена / пометка
        снята» — ручное решение, оно главнее протокола секретаря (как ERP, 26.10.2026)."""
        from ..core.tablica_zadach import РУЧНАЯ_ПОМЕТКА
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена.")
        with store.tx():
            store.update("tasks", tid, operational=int(body.on))
            store.insert("task_history", task_id=tid, old_status=None, new_status=None, source="web_form",
                         evidence_quote=f"{РУЧНАЯ_ПОМЕТКА} {'отмечена' if body.on else 'пометка снята'}",
                         changed_by=u["name"] or u["role"], at=now())
        return task_out(store.get("tasks", tid), u)

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

    def doubt_buttons_now(c: dict) -> list[dict]:
        """Кнопки «под вопросом» — по реестру СЕЙЧАС: «Это дубль» — только пока похожая задача действует (встреча
        могла закрыть её уже после заведения карточки)."""
        from ..core.pipeline import doubt_buttons
        p = c["payload"] if isinstance(c["payload"], dict) else json.loads(c["payload"] or "{}")
        t = store.get("tasks", p.get("task_id") or 0) or {}
        return doubt_buttons(pipe.reg, c["project_id"], t.get("id") or 0, t.get("description") or p.get("description", ""))

    @app.get("/api/projects/{pid}/cards")
    def cards(pid: int, u: dict = Depends(admin)):
        out = [c for c in pipe.cards.list(pid) if c["kind"] != "technical"]
        for c in out:
            if c["kind"] == "task_doubt" and c["status"] == "open":
                c["payload"] = {**c["payload"], "buttons": doubt_buttons_now(c)}
        return out

    def _apply_card(c: dict, payload: dict, chosen: dict | None, by: str, custom_text: str = "") -> None:
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
        elif c["kind"] == "task_doubt" and payload.get("task_id"):
            # «Подтвердить» — задача остаётся, пометка снимается; выбор исполнителя — в ту же задачу (15.10.26);
            # «Своя формулировка» — текст оператора в ту же задачу, пометка снимается
            if custom_text:
                pipe.reg.set_description(payload["task_id"], custom_text, by)
            if chosen:
                pipe.reg.set_assignee(payload["task_id"], chosen["name"], by, "из карточки «под вопросом»")
            pipe.reg.clear_doubt(payload["task_id"], by)
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
        elif (c["kind"] in ("held_task", "assign_person") or c["kind"] == "task_doubt" and body.choice.strip())                 and body.status == CardStatus.ACCEPTED and cands:
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
        custom_text = ""
        if c["kind"] == "task_doubt":
            act = body.action.strip() or ("accept" if body.status == CardStatus.ACCEPTED else
                                          "duplicate" if body.resolution.strip().lower() in ("duplicate", "дубль", "это дубль")
                                          else "reject")
            now_buttons = doubt_buttons_now({**c, "payload": payload})
            if act not in {b["action"] for b in now_buttons}:
                raise HTTPException(400, "Для этой задачи такого действия нет: " + ", ".join(b["label"] for b in now_buttons) + ".")
            if act == "custom":
                custom_text = body.resolution.strip()
                if not custom_text:
                    raise HTTPException(422, "Впишите свою формулировку задачи.")
                body.status = CardStatus.ACCEPTED
            elif act == "duplicate":
                body.status, body.resolution = CardStatus.REJECTED, "duplicate"
            elif act == "reject":
                body.status = CardStatus.REJECTED
            else:
                body.status = CardStatus.ACCEPTED
        with store.tx():                      # действие и решение — вместе; второе нажатие ничего не делает
            if store.get("cards", cid)["status"] != CardStatus.OPEN.value:
                return store.get("cards", cid)
            if body.status == CardStatus.ACCEPTED:
                _apply_card(c, payload, chosen, by, custom_text)
            elif c["kind"] == "task_doubt" and payload.get("task_id"):
                # «Не задача» и «Это дубль» — задача снимается (статус «снято», не удаляется), пометка уходит
                dup = body.resolution.strip().lower() in ("duplicate", "дубль", "это дубль")
                pipe.reg.set_status(payload["task_id"], TaskStatus.DROPPED, "operator",
                                    "это дубль" if dup else "не задача", by=by)
                pipe.reg.clear_doubt(payload["task_id"], by, "дубль" if dup else "не задача")
            elif c["kind"] == "confirm_person" and payload.get("person_id"):
                # «не тот человек»: неподтверждённая запись убирается, задачи остаются без исполнителя
                p = store.get("people", int(payload["person_id"]))
                if p and p["project_id"] == c["project_id"] and not p["confirmed"]:
                    for t in store.q("SELECT id FROM tasks WHERE project_id=? AND assignee=?",
                                     (c["project_id"], p["full_name"])):
                        store.update("tasks", t["id"], assignee=None)
                    store.delete("people", p["id"])
            out = pipe.cards.resolve(cid, body.status, body.resolution or (chosen or {}).get("name", ""), body.why)
        if (c["kind"] == "held_task" or c["kind"] == "task_doubt" and body.resolution.strip().lower()
                not in ("duplicate", "дубль", "это дубль")) and body.status == CardStatus.REJECTED and c["project_id"]:
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
                "team_shared": team_shared_state(
                    voice_base_path=store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH")),
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
        _lease_path()                       # аренда распознавания — рядом с новой базой голосов
        return voice_base_state(a or None)

    @app.get("/api/monitoring/intake")
    def mon_intake(u: dict = Depends(super_admin)):
        return [{"project_id": p["id"], "project": p["name"], **intake.state(p["id"])}
                for p in store.q("SELECT id, name FROM projects ORDER BY id")]

    @app.get("/api/monitoring/voice-base")
    def mon_voice(u: dict = Depends(super_admin)):
        st = voice_base_state(store.get_setting("voice_base_path"))
        from ..core import asr_journal
        recent = asr_journal.read_recent(pipe.asr_journal_path, 1)
        st["last_recognition"] = recent[-1] if recent else {}
        try:
            st["team_count"] = team_shared_state(
                voice_base_path=store.get_setting("voice_base_path")).get("people_confirmed", 0)
        except Exception:  # noqa: BLE001
            st["team_count"] = 0
        return st

    def _voice_base() -> str:
        return store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH") or ""

    def _komanda() -> list[str]:
        """«Команда» MeetFlow для «Разбора голосов»: подтверждённые внутренние люди всех проектов и общей «Команды»,
        полным ФИО (фамилия и имя)."""
        names = {" ".join((r["full_name"] or "").split()) for r in store.q(
            "SELECT full_name FROM people WHERE confirmed=1 AND COALESCE(external, 0)=0")}
        try:
            st = team_shared_state(voice_base_path=store.get_setting("voice_base_path"))
            names |= {" ".join((p.get("full_name") or "").split()) for p in (st.get("people_list") or [])
                      if not p.get("external")}
        except Exception:  # noqa: BLE001 — без общей «Команды» — только проектные люди
            pass
        return sorted(n for n in names if len(n.split()) >= 2)

    def v_komande(name: str, komanda: list[str] | None = None) -> str | None:
        """ФИО человека «Команды»: точное совпадение («е» = «ё») или один человек с тем же ключом фамилии и имени;
        тёзки — нет (как ERP `routers/voice_review.в_команде`, 26.10.2026)."""
        name = " ".join((name or "").split())
        if not name:
            return None
        komanda = _komanda() if komanda is None else komanda
        same = [k for k in komanda if norm_yo.равны(k, name)]
        if len(same) == 1:
            return same[0]
        key = " ".join(norm_yo.ключ(name).split()[:2])
        hits = [k for k in komanda if len(key.split()) == 2 and " ".join(norm_yo.ключ(k).split()[:2]) == key]
        return hits[0] if len(hits) == 1 else None

    @app.get("/api/monitoring/voice-review")
    def voice_review_state(tab: str = "queue", u: dict = Depends(super_admin)):
        """«Разбор голосов»: очередь новых отпечатков и решённые — как в ERP (задание 26.10.2026). «Это он» — по
        кандидату, однозначно найденному в «Команде» (`kandidat_v_komande`); второй из двух почти равных — тоже
        (`vtoroy_v_komande`)."""
        from ..core import voice_review
        base = _voice_base()
        if not base:
            return {"error": "Путь к общей базе голосов не задан.", "gruppy": [], "klastery": []}
        try:
            if tab == "done":
                return voice_review.reshennye(base)
            data = voice_review.ochered(base)
        except (voice_review.RazborNeTot, OSError) as exc:
            return {"error": str(exc), "gruppy": [], "klastery": []}
        komanda = _komanda()
        for g in data.get("gruppy") or []:
            g["v_komande"] = bool(g.get("imya")) and v_komande(g["imya"], komanda) is not None
            for kl in g.get("klastery") or []:
                kl["kandidat_v_komande"] = (v_komande(kl["kandidat"], komanda) or "") if kl.get("kandidat") else ""
                kl["vtoroy_v_komande"] = (v_komande(kl["second"], komanda) or "") if kl.get("second") else ""
        data["komanda"] = komanda
        return data

    @app.get("/api/monitoring/voice-review/clip/{sid}")
    def voice_review_clip(sid: int, u: dict = Depends(super_admin)):
        from ..core import voice_review
        base = _voice_base()
        path = voice_review.put_otryvka(base, sid) if base else None
        if not path or not path.is_file():
            why = voice_review.pochemu_net_otryvka(base, sid) if base else "путь к базе не задан"
            raise HTTPException(404, why or "Отрывка нет.")
        return Response(path.read_bytes(), media_type="audio/wav")

    @app.post("/api/monitoring/voice-review/apply")
    def voice_review_apply(body: VoiceDecisionIn, u: dict = Depends(super_admin)):
        from ..core import voice_review
        base = _voice_base()
        if not base:
            raise HTTPException(422, "Путь к общей базе голосов не задан.")
        if not body.ids:
            raise HTTPException(422, "Не выбран ни один говорящий.")
        if body.decision == "yes" and not body.name.strip():
            raise HTTPException(422, "Для решения «Это он» нужно имя.")
        if body.vybran and body.decision != "yes":
            raise HTTPException(422, "Выбор одного из двух кандидатов — только с решением «Это он».")
        name = body.name.strip()
        if body.decision in ("yes", "other"):
            # имя должно однозначно найтись в «Команде» полным ФИО (как ERP 26.10.2026); «Другой человек» — ФИО
            # «Команды», «Это он» — имя кандидата из базы голосов, чтобы отпечатки легли к тому же человеку базы
            found = v_komande(name)
            if len(name.split()) < 2 or found is None:
                raise HTTPException(422, f"«{name or 'пусто'}» — нет в «Команде» MeetFlow полным ФИО. Выберите человека "
                                         "в «Другой человек»: одно имя или тёзка не подставляются.")
            if body.decision == "other":
                name = found
        try:
            out = voice_review.primenit(base, body.ids, body.decision, name,
                                        kto=u.get("name") or u.get("role") or "")
            return {**out, "vybran": body.vybran}
        except (voice_review.RazborNeTot, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/monitoring/voice-review/dismiss")
    def voice_review_dismiss(body: VoiceDecisionIn, u: dict = Depends(super_admin)):
        """«Не он» для принятого правилом (auto_rule): вернуть говорящего в очередь «не узнан»."""
        from ..core import voice_review
        base = _voice_base()
        if not base:
            raise HTTPException(422, "Путь к общей базе голосов не задан.")
        return voice_review.ne_po_pravilu(base, body.ids, kto=u.get("name") or u.get("role") or "")

    @app.get("/api/monitoring/team-shared")
    def mon_team(u: dict = Depends(super_admin)):
        """Общая «Команда» Планёрки и ERP — только чтение (задание 24.10.2026, раздел 0)."""
        return team_shared_state(voice_base_path=store.get_setting("voice_base_path"))

    @app.get("/api/monitoring/runs")
    def mon_runs(days: int = 7, u: dict = Depends(super_admin)):
        return runs_report(pipe.journal.path, max(1, min(days, 90)), theme.get("budget", {}))

    # Переключение моделей (решение владельца 09.10.26): роли, точки по порядку, «Сделать основной»,
    # «Проверить связь». Только супер-администратору; при MEETFLOW_LLM=routes действует сразу, без перезапуска.
    @app.get("/api/monitoring/models")
    def mon_models(u: dict = Depends(super_admin)):
        from ..connectors.llm_routes import panel, provider_limits
        try:
            d = panel(full_keys=True)
            d["provider_spend"] = provider_limits(pipe.journal.path)     # расход за месяц и предел (стенд 46)
            return d
        except ConnectorError as e:
            raise HTTPException(400, str(e))

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
                    queue_rebuild(mid, pause)
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
        _routes(lr.save_point, body.name, body.fields, by=u.get("name") or u["role"], old_name=body.old_name,
                key_value=body.key_value or None)
        return lr.panel()

    @app.post("/api/monitoring/models/endpoint/key")
    def mon_models_key(body: RoutePointIn, u: dict = Depends(super_admin)):
        """«Заменить ключ» / «Удалить ключ» (пустое значение) — наружу только «ключ задан · …XXXX»."""
        from ..connectors import llm_routes as lr
        by = u.get("name") or u["role"]
        if body.key_value.strip():
            _routes(lr.set_point_key, body.name, body.key_value, by=by)
        else:
            _routes(lr.delete_point_key, body.name, by=by)
        return lr.panel()

    @app.post("/api/monitoring/models/endpoint/delete")
    def mon_models_delete(body: RoutePointIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        _routes(lr.delete_point, body.name, by=u.get("name") or u["role"])
        return lr.panel()

    @app.post("/api/monitoring/models/endpoint/test")
    def mon_models_test(body: RoutePointIn, u: dict = Depends(super_admin)):
        from ..connectors import llm_routes as lr
        ok, detail = _routes(lr.test_point, body.fields, body.key_value, body.old_name or body.name)
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

    # Опрос моделей фоном (стенд 12, ERP 8020): итог в памяти 20 с, все точки разом, экран ждёт не больше 0,5 с —
    # иначе прошлый итог с возрастом. Молчащий сервер не держит экран мониторинга.
    poll = {"results": [], "at": None, "running": False, "error": "", "done": threading.Event()}
    poll_lock = threading.Lock()

    def _poll_run() -> None:
        from ..connectors.llm_routes import check_all
        try:
            res, err = check_all(), ""
        except Exception as e:  # noqa: BLE001 — итог опроса — справка, не ошибка экрана
            res, err = poll["results"], str(e)[:300]
        with poll_lock:
            poll.update(results=res, at=time.time(), running=False, error=err)
            poll["done"].set()

    def _poll_state(force: bool) -> dict:
        with poll_lock:
            stale = poll["at"] is None or time.time() - poll["at"] > 20
            if (force or stale) and not poll["running"]:
                poll["running"], poll["done"] = True, threading.Event()
                threading.Thread(target=_poll_run, daemon=True).start()
            done = poll["done"]
        done.wait(0.5)
        with poll_lock:
            age = None if poll["at"] is None else round(time.time() - poll["at"], 1)
            return {"results": poll["results"], "age_sec": age, "running": poll["running"], "error": poll["error"]}

    @app.get("/api/monitoring/models/status")
    def mon_models_status(u: dict = Depends(super_admin)):
        return _poll_state(False)

    @app.post("/api/monitoring/models/check")
    def mon_models_check(u: dict = Depends(super_admin)):
        return _poll_state(True)

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
        tool = {"tool": llm_mode(), "generator": getattr(pipe.gen, "model", ""),
                "verifier": getattr(pipe.ver, "display", None) or getattr(pipe.ver, "model", ""),
                "max_answer_tokens": theme.get("llm.max_answer_tokens", 4096),
                "openrouter_key_set": bool(os.environ.get("OPENROUTER_API_KEY", "").strip())}
        spend = []
        if llm_mode() == "routes":      # расход по поставщикам за месяц и предел (стенд 46), общим llm_cost
            from ..connectors.llm_routes import provider_limits
            try:
                spend = provider_limits(pipe.journal.path)
            except ConnectorError:
                spend = []
        return {"connectors": conns, "technical_messages": tech, "journal": pipe.journal.records[-50:],
                "todo": theme.todo(), "llm_tool": tool, "provider_spend": spend}

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
        tool = llm_mode()
        key = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        gen, ver = getattr(pipe.gen, "model", "") or "", getattr(pipe.ver, "model", "") or ""
        rows = []
        if tool == "mock":
            rows.append(_row("Модель", "выкл.", "стенд без модели: протоколы собирает заглушка"))
        elif tool == "openrouter" and not key:
            rows.append(_row("Модель", "нет", "OpenRouter: ключ OPENROUTER_API_KEY не задан"))
        else:
            def route(llm) -> str:   # точка и запасные — как в ERP и Планёрке (локальная машина 71b2b27, 12.10.26)
                try:
                    names = llm.chain() if hasattr(llm, "chain") else []
                except Exception:   # noqa: BLE001 — сбой файла маршрутов не должен ронять мониторинг
                    return ""
                return (f" · точка «{names[0]}»" + (f", запасные: {', '.join(names[1:])}" if names[1:] else "")) if names else ""
            rows.append(_row("Модель", "живо", f"{tool}: генерирует {gen or 'по маршрутам'}{route(pipe.gen)}"))
            rows.append(_row("Модель проверки", "живо", (ver or "по маршрутам") + route(pipe.ver) +
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
            elif st.get("stalled") and st.get("scan_in_progress"):
                rows.append(_row(f"Папка-приёмник · {p['name']}", "нет",
                                 f"{st['folder']} — проход стоит: {st['scan_step']}"
                                 + (f" «{st['current_file']}»" if st.get("current_file") else "")
                                 + f", без движения {st['step_seconds'] // 60} мин"))
            elif st.get("stalled"):
                rows.append(_row(f"Папка-приёмник · {p['name']}", "нет",
                                 f"{st['folder']} — поток завис: проходов нет дольше трёх интервалов"))
            elif st.get("scan_in_progress"):
                rows.append(_row(f"Папка-приёмник · {p['name']}", "живо",
                                 f"{st['folder']} · идёт проход с {datetime.fromisoformat(st['scan_started_at']).strftime('%d.%m.%Y %H:%M')}: {st['scan_step']}"
                                 + (f" «{st['current_file']}»" if st.get("current_file") else "")
                                 + f" · шаг идёт {st['step_seconds'] // 60} мин"))
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
        ts = team_shared_state(voice_base_path=store.get_setting("voice_base_path"))
        rows.append(_row("Общая «Команда»", "живо" if ts.get("ok") else "выкл." if not ts.get("enabled") else "нет",
                         (f"людей {ts.get('people')} · внутренних {ts.get('internal')} · внешних {ts.get('external')}"
                          if ts.get("ok") else ts.get("detail") or "не задана")))
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
        # задачи под вопросом — отдельной строкой и первой: фокус на операторе (решение владельца 15.10.26)
        n = store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind='task_doubt'")[0]["n"]
        out.append({"key": "doubt", "title": "Задачи под вопросом", "count": n, "link": "#cards",
                    "need": "Подтвердить, снять как «не задача» или отметить дублем.",
                    "if_not": "Задача уже в реестре и в протоколе; без ответа она так и останется под вопросом."})
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
        # Системных сообщений в очереди оператора нет (владелец 12.10.26, локальная машина abb5789: «убери блок —
        # здесь это дублирование, они уже есть на отдельной странице мониторинга»). Очередь — только работа людей.
        return out

    @app.get("/api/monitoring/live")
    def mon_live(pid: int | None = None, u: dict = Depends(super_admin)):
        aw = _awaiting()
        rec = store.q("SELECT s.name, s.created_at, m.date FROM sources s JOIN meetings m ON m.id = s.meeting_id "
                      "WHERE s.removed_reason LIKE 'запись распознана%' ORDER BY s.id DESC LIMIT 5")
        day = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        q = {"tasks_doubt_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind='task_doubt'")[0]["n"],
             "cards_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind != 'technical'")[0]["n"],
             "cards_resolved_day": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind != 'technical' AND resolved_at >= ?",
                                           (day,))[0]["n"],
             "tech_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind='technical'")[0]["n"]}
        return {"services": _services(), "awaiting_total": sum(g["count"] for g in aw), "recognition": rec, "queue": q,
                "intake": intake.state(pid) if pid and store.get("projects", pid) else None,
                "recognition_queue": recognition_lease.состояние(),   # кто распознаёт сейчас, кто ждёт
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
                            "SELECT status, COUNT(*) AS n FROM tasks WHERE project_id=? AND status<>'dropped' "
                            "GROUP BY status", (pid,))},
                        "closed_by": {r["source"]: r["n"] for r in store.q(
                            "SELECT h.source, COUNT(*) AS n FROM task_history h JOIN tasks t ON t.id=h.task_id WHERE "
                            "t.project_id=? AND h.new_status='done' GROUP BY h.source", (pid,))},
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
                "models": {"tool": llm_mode(), "generator": getattr(pipe.gen, "model", ""),
                           "verifier": getattr(pipe.ver, "display", None) or getattr(pipe.ver, "model", ""),
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
                "card_cleanup_source": "задан на экране" if cc is not None else "из темы",
                "show_doubt_mark": bool(store.get_setting("show_doubt_mark", None, True))}

    @app.post("/api/settings/thresholds")
    def set_thresholds(body: ThresholdsIn, u: dict = Depends(super_admin)):
        by = u["name"] or u["role"]
        for k in ("overdue_highlight_working_days", "card_cleanup_days", "show_doubt_mark"):
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
