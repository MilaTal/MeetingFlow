# -*- coding: utf-8 -*-
"""Слой «ERP 1 в 1»: те же адреса и ответы, что у сервера Проекта ERP, поверх ядра и базы MeetFlow (27.10.2026).

Подключается в `web/app.py` до раздачи фронта. Модули — по роутерам ERP:
`komanda` — `/auth`, `/users`; `karkas` — значки, выключатели, справочники каркаса; остальные — по группам экранов.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from .obshchee import COOKIE, Ctx

# Адреса ERP: всё, что начинается так, — данные; до входа (когда вход включён) отдаются только открытые ручки входа
ERP_PREFIXES = ("/auth", "/users", "/meetings", "/tasks", "/badges", "/units", "/project-status", "/search",
                "/agreements", "/razbor", "/task-conflicts", "/operator-rules", "/possible-assignments",
                "/recognition-settings", "/review-notes", "/voice", "/meeting-topics", "/projects-list")
OPEN_PATHS = {"/auth/mode", "/auth/login", "/auth/logout", "/auth/first-login", "/auth/first-login/people",
              # портал единого входа (этап 2, 06.11.2026): приём кода — до входа; обратный канал проверяет секрет сам
              "/auth/portal", "/auth/portal/logout", "/auth/portal/accounts"}


def mount(app: FastAPI, **parts) -> Ctx:
    ctx = Ctx(**parts)
    ctx.app = app
    app.state.erp = ctx
    r = APIRouter()
    from . import karkas, komanda, portal_vhod
    komanda.mount(r, ctx)
    portal_vhod.mount(r, ctx)   # приём входа от портала единого входа (06.11.2026)
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
        # Д2.4 (решение владелицы 05.11.2026): изменяющий запрос по встрече с чужим X-Project-Id — 409.
        # Замок на данных и один раз на все пути встречи: материалы, план, протокол, перенос, задачи, отметки.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            м = re.match(r"^/meetings/(\d+)(?:/|$)", path)
            чужой = (request.headers.get("x-project-id") or "").strip()
            if м and чужой not in ("", "0"):
                встреча = ctx.store.get("meetings", int(м.group(1)))
                if встреча:
                    проект_встречи = встреча.get("project_id")
                    # Общая встреча — та, что лежит в служебном «Общие встречи» (признак general): пропускаем
                    # из любой вкладки, иначе запираем самый частый рабочий путь (записка 06.11.2026).
                    общая = проект_встречи is None or bool(ctx.store.q(
                        "SELECT id FROM projects WHERE id=? AND COALESCE(general,0)=1", (str(проект_встречи),)))
                    if not общая and str(проект_встречи) != чужой:
                        return JSONResponse({"detail": "Встреча принадлежит другому проекту — откройте её из своего проекта"}, 409)
        return await call_next(request)
    return ctx
