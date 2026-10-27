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

    _ = HTTPException
