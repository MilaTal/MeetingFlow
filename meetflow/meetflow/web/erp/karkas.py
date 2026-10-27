# -*- coding: utf-8 -*-
"""Каркас фронта ERP: значки меню одним запросом, выключатели, которые фронт читает при каждом показе (27.10.2026).

`/badges` — как `app/routers/badges.py` ERP: «Разбор» — одно число (карточки «Конфликтов», задачи «под вопросом»,
неразобранные «Возможные поручения»), системные сообщения и «Разбор голосов» — суперадминистратору. Чего человеку не
видно — пусто (None). Числа — по выбранному проекту; «Все проекты» — по всем.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .obshchee import Ctx

# Виды карточек MeetFlow, которые в ERP живут не в «Конфликтах»: технические — системные сообщения, «под вопросом» —
# отдельный вид «Задачи» в «Разборе»
NOT_CONFLICTS = ("technical", "task_doubt", "possible_assignment")


class Toggle(BaseModel):
    enabled: bool


class ProjectIn(BaseModel):
    name: str | None = None
    aliases: str | None = ""
    archived: bool | None = None


def open_conflicts(ctx: Ctx, request: Request) -> int:
    extra, args = ctx.scope_sql(request)
    return len(ctx.store.q("SELECT id FROM cards WHERE status='open' AND kind NOT IN (?,?,?)" + extra,
                           NOT_CONFLICTS + args))


def under_question(ctx: Ctx, request: Request) -> int:
    extra, args = ctx.scope_sql(request)
    return len(ctx.store.q("SELECT id FROM tasks WHERE status='active' AND COALESCE(doubt_reason,'')!=''" + extra, args))


def possible_open(ctx: Ctx, request: Request) -> int:
    extra, args = ctx.scope_sql(request)
    try:
        return len(ctx.store.q("SELECT id FROM possible_assignments WHERE state='новое'" + extra, args))
    except Exception:  # noqa: BLE001 — таблицы может ещё не быть на старой базе
        return 0


def system_open(ctx: Ctx) -> int:
    return len(ctx.store.q("SELECT id FROM cards WHERE status='open' AND kind='technical'"))


def voice_base(ctx: Ctx) -> str | None:
    return ctx.store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH") or None


def voice_review_count(ctx: Ctx) -> int | None:
    from ...core import voice_review
    base = voice_base(ctx)
    if not base:
        return None
    try:
        return voice_review.chislo_klasterov(base)
    except Exception:  # noqa: BLE001 — значок не критичен
        return None


def mount(r: APIRouter, ctx: Ctx) -> None:
    store = ctx.store

    @r.get("/badges")
    def badges(request: Request):
        u = ctx.need_user(request)
        admin = ctx.is_admin(u)
        sup = u.get("role") == "super_admin"
        c = open_conflicts(ctx, request) if admin else None
        q = under_question(ctx, request) if admin else None
        p = possible_open(ctx, request) if admin else None
        return {"conflicts": c, "system": system_open(ctx) if sup else None, "under_question": q,
                "razbor": (c + q + p) if admin else None, "possible": p,
                "voice_review": voice_review_count(ctx) if sup else None}

    @r.get("/units/enabled")
    def units_enabled():
        """Единицы встреч — за выключателем темы (`units.enabled`), как выключатель сервера ERP."""
        return {"enabled": bool(ctx.theme.get("units.enabled", True))}

    @r.get("/project-status/under-question-mark")
    def uq_mark_get(request: Request):
        return {"enabled": bool(store.get_setting("show_doubt_mark", None, True))}

    @r.post("/project-status/under-question-mark")
    def uq_mark_set(body: Toggle, request: Request):
        u = ctx.need_super(request)
        store.set_setting("show_doubt_mark", bool(body.enabled), None, ctx.name(u))
        return {"enabled": bool(body.enabled)}

    @r.get("/projects-list")
    def projects_list(request: Request):
        """Выбор проекта внизу левой панели (многопроектность — разрешённое отличие от ERP)."""
        rows = store.q("SELECT id, name, archived FROM projects ORDER BY name")
        return [{"id": p["id"], "name": p["name"]} for p in rows if not p.get("archived")]

    # «Параметры системы» → «Проекты»: завести, переименовать, убрать в архив и вернуть (многопроектность MeetFlow —
    # разрешённое отличие от ERP, где проект один). Папка-приёмник проекта — на «Мониторинге RealTime» при выбранном проекте.
    def project_out(p: dict) -> dict:
        from .obshchee import loads
        n = store.q("SELECT (SELECT COUNT(*) FROM meetings WHERE project_id=?) AS m, "
                    "(SELECT COUNT(*) FROM tasks WHERE project_id=? AND status='active') AS t", (p["id"], p["id"]))[0]
        return {"id": p["id"], "name": p["name"], "aliases": loads(p.get("aliases"), []), "archived": bool(p.get("archived")),
                "meetings": n["m"], "active_tasks": n["t"], "watch_folder": ctx.intake.folder(p["id"]) or ""}

    @r.get("/projects-list/all")
    def projects_all(request: Request):
        ctx.need_super(request)
        return [project_out(p) for p in store.q("SELECT * FROM projects ORDER BY COALESCE(archived,0), name")]

    def clean(body: "ProjectIn") -> tuple[str, str]:
        import json
        name = " ".join((body.name or "").split())
        if not name:
            raise HTTPException(400, "Название проекта не задано")
        aliases = [a.strip() for a in (body.aliases or "").replace(chr(10), ";").split(";") if a.strip()]
        return name, json.dumps(aliases, ensure_ascii=False)

    @r.post("/projects-list", status_code=201)
    def project_create(body: ProjectIn, request: Request):
        from ...core.store import now
        u = ctx.need_super(request)
        name, aliases = clean(body)
        if any(" ".join(p["name"].lower().replace("ё", "е").split()) == name.lower().replace("ё", "е")
               for p in store.q("SELECT name FROM projects")):
            raise HTTPException(409, f"Проект «{name}» уже есть")
        pid = store.insert("projects", name=name, theme=ctx.theme.id, aliases=aliases, active=1, archived=0, created_at=now())
        ctx.sys_msg(f"Заведён проект «{name}»", f"Завёл: {ctx.name(u)}.", "settings")
        return project_out(store.get("projects", pid))

    @r.patch("/projects-list/{pid}")
    def project_edit(pid: int, body: ProjectIn, request: Request):
        u = ctx.need_super(request)
        p = store.get("projects", pid)
        if not p:
            raise HTTPException(404, "Проекта нет")
        vals = {}
        if body.name is not None:
            vals["name"], vals["aliases"] = clean(body)
        if body.archived is not None:
            if body.archived and not p.get("archived") and                     len(store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0")) <= 1:
                raise HTTPException(400, "Последний действующий проект в архив не убирается")
            vals["archived"] = int(body.archived)
        store.update("projects", pid, **vals)
        if body.archived:
            ctx.intake.set_folder(pid, None, ctx.name(u))     # у архивного проекта приёмник выключен
        return project_out(store.get("projects", pid))
