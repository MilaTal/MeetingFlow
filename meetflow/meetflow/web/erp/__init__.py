# -*- coding: utf-8 -*-
"""Слой «ERP 1 в 1»: те же адреса и ответы, что у сервера Проекта ERP, поверх ядра и базы MeetFlow (27.10.2026).

Подключается в `web/app.py` до раздачи фронта. Модули — по роутерам ERP:
`komanda` — `/auth`, `/users`; `karkas` — значки, выключатели, справочники каркаса; остальные — по группам экранов.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from .obshchee import COOKIE, Ctx

# Адреса ERP: всё, что начинается так, — данные; до входа (когда вход включён) отдаются только открытые ручки входа
ERP_PREFIXES = ("/auth", "/users", "/meetings", "/tasks", "/badges", "/units", "/project-status", "/search",
                "/agreements", "/razbor", "/task-conflicts", "/operator-rules", "/possible-assignments",
                "/recognition-settings", "/review-notes", "/voice", "/meeting-topics", "/projects-list")
OPEN_PATHS = {"/auth/mode", "/auth/login", "/auth/logout", "/auth/first-login", "/auth/first-login/people"}


def mount(app: FastAPI, **parts) -> Ctx:
    ctx = Ctx(**parts)
    app.state.erp = ctx
    r = APIRouter()
    from . import karkas, komanda
    komanda.mount(r, ctx)
    karkas.mount(r, ctx)
    import importlib
    import importlib.util
    for name in ("vstrechi", "reestr", "protokol", "dogovorennosti", "razbor", "sistema"):
        if importlib.util.find_spec(f"{__name__}.{name}") is None:
            continue
        importlib.import_module(f"{__name__}.{name}").mount(r, ctx)
    app.include_router(r)

    @app.middleware("http")
    async def _erp_gate(request: Request, call_next):
        """Вход включён — данные ERP-адресов только с живой сессией (как `main._auth_gate` ERP)."""
        path = request.url.path
        if path.startswith(ERP_PREFIXES) and path not in OPEN_PATHS and ctx.accounts.auth_required() \
                and not ctx.accounts.by_session(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Требуется вход"}, 401)
        return await call_next(request)
    return ctx
