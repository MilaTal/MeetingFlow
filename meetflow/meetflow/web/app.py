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
from contextlib import asynccontextmanager
from datetime import date as date_cls
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
from ..core.intake import MIN_INTERVAL, IntakeError, IntakeService, validate_folder
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


class IntervalIn(BaseModel):
    seconds: int = Field(ge=MIN_INTERVAL, le=86400)


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


LLM_TOOLS = ("mock", "ollama", "openrouter")


def _llm(theme: Theme, side: str):
    """Инструмент подключения модели выбирается при развёртывании (решение владельца 03.10.26):
    MEETFLOW_LLM=mock — стенд без модели с плашкой; ollama — локальная модель (модели в теме
    llm.generator / llm.verifier, пока заглушки); openrouter — модели из llm.openrouter.*, ключ —
    переменная OPENROUTER_API_KEY. Потолок ответа — llm.max_answer_tokens (4096)."""
    mode = os.environ.get("MEETFLOW_LLM", "mock").strip().lower()
    if mode not in LLM_TOOLS:
        raise ValueError(f"MEETFLOW_LLM={mode}: допустимы {', '.join(LLM_TOOLS)}")
    if mode == "mock":
        return MockLLM()
    cap = int(theme.get("llm.max_answer_tokens", 4096))
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
    intake = IntakeService(pipe)
    watch_on = os.environ.get("MEETFLOW_WATCH", "on") != "off" if watch is None else watch

    @asynccontextmanager
    async def lifespan(_app):
        if watch_on:
            intake.start()        # фоновый забор из папок-приёмников
        yield
        intake.stop()

    app = FastAPI(title="MeetFlow", lifespan=lifespan)
    app.state.theme, app.state.store, app.state.pipe, app.state.intake = theme, store, pipe, intake
    app_dir = Path(__file__).resolve().parents[2]

    def user(x_user_role: str = Header("member"), x_user_name: str = Header("")) -> dict:
        role = x_user_role if x_user_role in theme["roles"] else "member"
        return {"role": role, "name": unquote(x_user_name)[:200]}  # кириллица в заголовке — URL-кодом

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
        return store.q("SELECT id, name, kind, created_at FROM sources WHERE meeting_id=? AND removed_at IS NULL",
                       (mid,))

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
        return [{k: v for k, v in r.items() if k != "project_id"} for r in rows]

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

    LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}

    def local_only(request: Request) -> None:
        """Пока вход по паролю не встроен, адреса папок и баз меняются только
        с машины сервера (правило Планёрки 28.09)."""
        if (request.client.host if request.client else "") not in LOCAL:
            raise HTTPException(403, "Адрес меняется только с компьютера, где работает сервер.")

    @app.get("/api/projects/{pid}/settings")
    def get_settings(pid: int, u: dict = Depends(super_admin)):
        project_or_404(pid)
        return {"intake": intake.state(pid),
                "voice_base_path": store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH"),
                "min_interval": MIN_INTERVAL}

    @app.post("/api/projects/{pid}/settings/watch-folder")
    def set_watch_folder(pid: int, body: FolderIn, request: Request, u: dict = Depends(super_admin)):
        project_or_404(pid)
        local_only(request)
        if not body.path.strip() and not body.path_repeat.strip():
            intake.set_folder(pid, None, u["name"] or u["role"])
            return intake.state(pid)
        try:
            path = validate_folder(body.path, body.path_repeat, app_dir=app_dir)
        except IntakeError as e:
            raise HTTPException(422, str(e)) from None
        other = [r for r in store.q("SELECT project_id, value FROM settings WHERE key='watch_folder'")
                 if r["project_id"] != pid and json.loads(r["value"] or "null") == str(path)]
        if other:
            raise HTTPException(422, "Эта папка уже назначена приёмником другого проекта: у каждого проекта своя.")
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
        local_only(request)
        a, b = body.path.strip().strip('"'), body.path_repeat.strip().strip('"')
        if a != b:
            raise HTTPException(422, "Адрес и его повтор не совпадают — проверьте опечатку.")
        if a and not Path(a).is_absolute():
            raise HTTPException(422, r"Нужен полный путь к файлу базы, например D:\Голоса\voices.db.")
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

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def main() -> None:  # python -m meetflow.web.app
    import uvicorn
    port = int(os.environ.get("MEETFLOW_PORT", "8002"))
    uvicorn.run(create_app(), host=os.environ.get("MEETFLOW_HOST", "127.0.0.1"), port=port)


if __name__ == "__main__":
    main()
