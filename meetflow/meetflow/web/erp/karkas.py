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
    parent_id: int | None = None


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

    def migrate_subprojects() -> None:
        """Подпроекты, заведённые 27.10.2026 до возврата справочника (настройка `subprojects` проекта и текст
        `tasks.subproject`), — в записи справочника проектов: подпроект — проект с надпроектом, задача — в нём. Повторный
        запуск ничего не меняет."""
        import json
        from ...core.store import now
        key = lambda s: " ".join((s or "").lower().replace("ё", "е").split())  # noqa: E731
        for s in store.q("SELECT project_id, value FROM settings WHERE key='subprojects' AND project_id IS NOT NULL"):
            try:
                names = json.loads(s["value"] or "[]")
            except ValueError:
                names = []
            have = {key(x["name"]) for x in store.q("SELECT name FROM projects WHERE parent_id=?", (s["project_id"],))}
            for n in names:
                n = " ".join(str(n).split())
                if n and key(n) not in have:
                    store.insert("projects", name=n, theme=ctx.theme.id, aliases="[]", active=1, archived=0,
                                 parent_id=s["project_id"], created_at=now())
                    have.add(key(n))
        for t in store.q("SELECT id, project_id, subproject FROM tasks WHERE COALESCE(subproject,'')!=''"):
            hit = [x for x in store.q("SELECT id, name FROM projects WHERE parent_id=?", (t["project_id"],))
                   if key(x["name"]) == key(t["subproject"])]
            store.update("tasks", t["id"], project_id=hit[0]["id"] if hit else t["project_id"], subproject="")

    try:
        migrate_subprojects()
    except Exception:  # noqa: BLE001 — перенос старых подпроектов не должен мешать запуску
        pass

    def tree(rows: list[dict]) -> list[dict]:
        """Проекты деревом: проект, под ним его подпроекты по алфавиту (как справочник ЛМ 6c6933f)."""
        ids = {r["id"] for r in rows}
        kids: dict = {}
        for r in rows:
            par = r.get("parent_id") if r.get("parent_id") in ids else None
            kids.setdefault(par, []).append(r)
        out: list[dict] = []

        def walk(par, level, seen):
            for r in sorted(kids.get(par, []), key=lambda x: (x["name"] or "").lower()):
                if r["id"] in seen:
                    continue
                out.append({**r, "level": level})
                walk(r["id"], level + 1, seen | {r["id"]})
        walk(None, 0, set())
        return out

    @r.get("/projects-list")
    def projects_list(request: Request):
        """Выбор проекта вверху левой панели: проект, под ним подпроекты, «Все проекты» (многопроектность — разрешённое
        отличие от ERP). Архивные не показываются; подпроект архивного проекта — тоже."""
        rows = store.q("SELECT id, name, parent_id, archived FROM projects")
        live = [r for r in rows if not r.get("archived")]
        return [{"id": r["id"], "name": r["name"], "parent_id": r.get("parent_id"), "level": r["level"],
                 "label": ctx.project_label(r["id"])} for r in tree(live)]

    # «Параметры системы» → «Проекты»: справочник проектов и подпроектов — завести, переименовать, варианты написания,
    # надпроект, архив и возврат (справочник ЛМ 6c6933f, возвращён 27.10.2026). Папка-приёмник — у каждого проекта и
    # подпроекта своя, на «Мониторинге RealTime» при выбранном проекте.
    def project_out(p: dict) -> dict:
        from .obshchee import loads
        n = store.q("SELECT (SELECT COUNT(*) FROM meetings WHERE project_id=?) AS m, "
                    "(SELECT COUNT(*) FROM tasks WHERE project_id=? AND status='active') AS t", (p["id"], p["id"]))[0]
        parent = store.get("projects", p.get("parent_id") or 0) or {}
        return {"id": p["id"], "name": p["name"], "aliases": loads(p.get("aliases"), []), "archived": bool(p.get("archived")),
                "parent_id": p.get("parent_id"), "parent_name": parent.get("name") or "", "level": p.get("level", 0),
                "label": ctx.project_label(p["id"]),
                "meetings": n["m"], "active_tasks": n["t"], "watch_folder": ctx.intake.folder(p["id"]) or ""}

    @r.get("/projects-list/all")
    def projects_all(request: Request):
        ctx.need_super(request)
        return [project_out(p) for p in tree(store.q("SELECT * FROM projects"))]

    def clean(body: "ProjectIn") -> tuple[str, str]:
        import json
        name = " ".join((body.name or "").split())
        if not name:
            raise HTTPException(400, "Название проекта не задано")
        aliases = [a.strip() for a in (body.aliases or "").replace(chr(10), ";").replace(",", ";").split(";") if a.strip()]
        return name, json.dumps(aliases, ensure_ascii=False)

    def same_name(name: str, but: int | None = None) -> bool:
        key = " ".join(name.lower().replace("ё", "е").split())
        return any(" ".join((p["name"] or "").lower().replace("ё", "е").split()) == key and p["id"] != but
                   for p in store.q("SELECT id, name FROM projects"))

    def check_parent(pid: int | None, parent: int | None) -> int | None:
        """Надпроект есть, не сам проект и не его подпроект: кольца проектов нет (как ЛМ 6c6933f)."""
        if not parent:
            return None
        if not store.get("projects", parent):
            raise HTTPException(400, "Такого надпроекта нет")
        if pid and parent in ctx.family(pid):
            raise HTTPException(422, "Так получится кольцо проектов — выберите другой надпроект.")
        return parent

    @r.post("/projects-list", status_code=201)
    def project_create(body: ProjectIn, request: Request):
        from ...core.store import now
        u = ctx.need_super(request)
        name, aliases = clean(body)
        if same_name(name):
            raise HTTPException(409, f"Проект «{name}» уже есть")
        parent = check_parent(None, body.parent_id)
        pid = store.insert("projects", name=name, theme=ctx.theme.id, aliases=aliases, active=1, archived=0,
                           parent_id=parent, created_at=now())
        ctx.sys_msg(f"Заведён {'подпроект' if parent else 'проект'} «{ctx.project_label(pid)}»", f"Завёл: {ctx.name(u)}.",
                    "settings")
        return project_out(store.get("projects", pid))

    @r.patch("/projects-list/{pid}")
    def project_edit(pid: int, body: ProjectIn, request: Request):
        u = ctx.need_super(request)
        p = store.get("projects", pid)
        if not p:
            raise HTTPException(404, "Проекта нет")
        vals: dict = {}
        data = body.model_dump(exclude_unset=True)
        if body.name is not None:
            vals["name"], vals["aliases"] = clean(body)
            if same_name(vals["name"], pid):
                raise HTTPException(409, f"Проект «{vals['name']}» уже есть")
        if "parent_id" in data:
            vals["parent_id"] = check_parent(pid, body.parent_id)
        if body.archived is not None:
            if body.archived and not p.get("archived") and not p.get("parent_id") and \
                    len(store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0 AND parent_id IS NULL")) <= 1:
                raise HTTPException(400, "Последний действующий проект в архив не убирается")
            vals["archived"] = int(body.archived)
        store.update("projects", pid, **vals)
        if body.archived:
            ctx.intake.set_folder(pid, None, ctx.name(u))     # у архивного проекта приёмник выключен
        return project_out(store.get("projects", pid))
