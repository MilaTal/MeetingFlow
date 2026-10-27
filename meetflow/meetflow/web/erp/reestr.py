# -*- coding: utf-8 -*-
"""Реестр задач — адреса ERP `/tasks/*` (перенос 27.10.2026, экраны 1 в 1): «Актуализировать задачи из реестра», архив
«Завершённые» порциями, поиск только по задачам, правка формулировки, ответственного, срока, статуса и проекта, «оперативная»,
«под вопросом», «Вернуть», удаление насовсем, отметка исполнителя («Актуализировать»).

Замок на данных — версия строки (`tasks.version`): экран присылает версию, которую видел; не совпала — 409, правка не
затирает чужую. Снятые задачи не показываются нигде (решение владелицы 26.10.2026). Задачи ведёт `TaskRegistry` ядра.
«Проект задачи» в MeetFlow — проект ведения: перенос задачи в другой проект меняет её `project_id`.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core import norm_yo
from ...core.store import now
from ...core.types import TaskStatus
from .obshchee import Ctx, iso_dt, loads, ru_date, to_date

СТАТУС_СЛОВАМИ = {"active": "в работе", "done": "выполнена", "dropped": "снята с рассмотрения"}
NOTE_PHRASES = {"done": "Сделано — проверьте", "on_track": "Идёт по плану", "question": "Есть вопрос"}
NOTE_KINDS = ("done", "on_track", "reschedule", "question", "text")
ПОРЦИЯ = 50
ЗАДАЧИ_НЕТ = "Задачи больше нет — её удалили. Обновите страницу."


class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _d(v):
    if v in (None, ""):
        return None
    d = to_date(v)
    if d is None:
        raise ValueError("Срок — в виде дд.мм.гггг")
    return d


class Versioned(InModel):
    version: int | None = None


class StatusIn(Versioned):
    new_status: str | None = None
    status_detail: str | None = Field(default=None, max_length=2000)
    comment: str | None = Field(default=None, max_length=2000)


class ResponsibleIn(Versioned):
    responsible_user_id: int | None = None
    responsible_text: str | None = Field(default=None, max_length=300)


class DueIn(Versioned):
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _v(cls, v):
        return _d(v)


class ProjectIn(Versioned):
    project_id: int | None = None


class SubprojectIn(Versioned):
    subproject: str | None = Field(default=None, max_length=200)


class DescriptionIn(Versioned):
    description: str = Field(min_length=1, max_length=2000)


class OperationalIn(Versioned):
    value: bool


class UnderQuestionIn(Versioned):
    action: str


class NoteIn(InModel):
    kind: str = "text"
    text: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        if v not in NOTE_KINDS:
            raise ValueError("Неизвестный вид отметки")
        return v

    @field_validator("due_date", mode="before")
    @classmethod
    def _v(cls, v):
        return _d(v)


class TaskCreate(InModel):
    description: str = Field(min_length=1, max_length=2000)
    responsible_user_id: int | None = None
    responsible_text: str | None = Field(default=None, max_length=300)
    status_detail: str | None = Field(default=None, max_length=2000)
    date_set: date | None = None
    due_date: date | None = None
    source_meeting_id: int | None = None

    @field_validator("due_date", "date_set", mode="before")
    @classmethod
    def _v(cls, v):
        return _d(v)


def _norm(s: str | None) -> str:
    return norm_yo.ключ(s or "") if hasattr(norm_yo, "ключ") else " ".join((s or "").lower().replace("ё", "е").split())


def is_responsible(t: dict, u: dict) -> bool:
    """Человек — ответственный задачи: по фамилии и, если имя указано, по имени (как `task_service.is_responsible` ERP)."""
    mine = [w.lower().replace("ё", "е") for w in (u.get("full_name") or "").split()]
    if not mine:
        return False
    surname, name = mine[0], (mine[1] if len(mine) > 1 else "")
    for part in re.split(r"[,;/()]|\s+и\s+", t.get("assignee") or ""):
        words = [w.lower().replace("ё", "е") for w in re.findall(r"[А-Яа-яЁёA-Za-z]+", part)]
        if not words:
            continue
        stem = surname[:max(4, len(surname) - 2)]
        if not any(w.startswith(stem) for w in words):
            continue
        others = [w for w in words if not w.startswith(stem)]
        if not others or not name or any(o[:3] == name[:3] for o in others):
            return True
    return False


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, pipe = ctx.store, ctx.pipe
    lock = threading.Lock()

    def team_ids() -> dict[str, int]:
        return {_norm(a["full_name"]): a["id"] for a in store.q("SELECT id, full_name FROM accounts") if a.get("full_name")}

    def doubt_label(reason: str) -> str | None:
        if not (reason or "").strip():
            return None
        try:
            from ...connectors.shared.doubt_labels import подпись
            return подпись(reason) or reason
        except Exception:  # noqa: BLE001
            return reason

    def task_out(t: dict, u: dict | None, *, ids: dict | None = None, mdates: dict | None = None,
                 dates_by_project: dict | None = None, all_projects: bool = False) -> dict:
        from ...core import tablica_zadach
        admin = ctx.is_admin(u)
        ids = ids if ids is not None else team_ids()
        rid = ids.get(_norm(t.get("assignee"))) if t.get("assignee") else None
        mdate = (mdates or {}).get(t.get("source_meeting_id")) if mdates is not None else (
            (store.get("meetings", t["source_meeting_id"]) or {}).get("date") if t.get("source_meeting_id") else None)
        pid = int(t.get("project_id") or 0)
        if dates_by_project is not None:
            if pid not in dates_by_project:
                dates_by_project[pid] = tablica_zadach.даты_прошедших_встреч(store, pid)
            dates = dates_by_project[pid]
        else:
            dates = tablica_zadach.даты_прошедших_встреч(store, pid)
        try:
            hint = tablica_zadach.похоже_на_оперативную(t, tablica_zadach.встреч_после(dates, to_date(t.get("date_set"))))
        except Exception:  # noqa: BLE001 — подсказка не критична
            hint = False
        reason = (t.get("doubt_reason") or "") if t.get("status") == "active" else ""
        label = doubt_label(reason) if reason and bool(store.get_setting("show_doubt_mark", None, True)) else None
        if label and not admin and "см." in label:
            label = "требует подтверждения"
        project_name = None
        if all_projects:
            p = store.get("projects", pid)
            project_name = p["name"] if p else None
        out = {"id": t["id"], "description": t.get("description") or "", "responsible_user_id": rid,
               "responsible_text": t.get("assignee") or None, "status": t.get("status") or "active",
               "status_detail": t.get("status_detail") or None, "date_set": (t.get("date_set") or "")[:10] or None,
               "date_closed": (t.get("date_closed") or "")[:10] or None, "due_date": (t.get("due_date") or "")[:10] or None,
               "last_comment": t.get("last_comment") or None, "last_comment_date": (t.get("last_comment_date") or "")[:10] or None,
               "last_comment_by": t.get("last_comment_by") or None,
               "can_actualize": bool(u) and t.get("status") == "active" and (admin or is_responsible(t, u)),
               "status_at": СТАТУС_СЛОВАМИ.get(t.get("status") or "active"), "status_at_date": date.today().isoformat(),
               "source_quote": None, "source_ref": None,
               "source_anchor": (reason or None) if admin else None, "under_question_label": label,
               "due_phrase": None, "due_kind": t.get("due_kind") or None,
               "due_original": (t.get("due_original") or "")[:10] or None,
               "source_meeting_id": t.get("source_meeting_id"), "source_meeting_date": (mdate or "")[:10] or None,
               "project_id": pid or None, "project_name": project_name, "subproject": t.get("subproject") or None,
               "operational": bool(t.get("operational")), "operational_hint": bool(hint),
               "updated_at": iso_dt(t.get("updated_at") or t.get("date_set")) or now(),
               "version": int(t.get("version") or 1)}
        return out

    def rows_out(rows: list[dict], u: dict | None, request: Request) -> list[dict]:
        ids = team_ids()
        mdates = {m["id"]: m["date"] for m in store.q("SELECT id, date FROM meetings")}
        dbp: dict = {}
        all_p = ctx.project(request) is None
        return [task_out(t, u, ids=ids, mdates=mdates, dates_by_project=dbp, all_projects=all_p) for t in rows]

    def take(t: dict, version: int | None, who: str) -> None:
        """Замок на данных: правка проходит, только если экран видел текущую версию задачи."""
        if version is not None and int(t.get("version") or 1) != int(version):
            raise HTTPException(409, f"Задачу уже изменили, пока окно было открыто ({who or 'другой пользователь'} видел "
                                     "прежнюю версию) — обновите страницу и повторите правку.")

    def get_or_404(tid: int) -> dict:
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, ЗАДАЧИ_НЕТ)
        return t

    def history(tid: int, old, new, source: str, quote: str, by: str) -> None:
        pipe.reg._history(tid, old, new, source, quote, by)

    def fresh(tid: int, u: dict | None, request: Request) -> dict:
        return rows_out([store.get("tasks", tid)], u, request)[0]

    def scoped(request: Request, where: str, args: tuple = ()) -> list[dict]:
        extra, a2 = ctx.scope_sql(request)
        return store.q(f"SELECT * FROM tasks WHERE {where}{extra} ORDER BY COALESCE(date_set,'') DESC, id DESC", args + a2)

    # ------------------------------------------------------------------ чтение
    @r.get("/tasks")
    def list_tasks(request: Request, status: str | None = None, meeting_id: int | None = None, as_of: str | None = None):
        u = ctx.user(request)
        where, args = "status!='dropped'", ()
        if status:
            if status not in ("active", "done", "dropped"):
                raise HTTPException(422, "Неизвестный статус задачи")
            where += " AND status=?"
            args += (status,)
        if meeting_id is not None:
            where += " AND source_meeting_id=?"
            args += (meeting_id,)
        if meeting_id is not None:
            rows = store.q(f"SELECT * FROM tasks WHERE {where} ORDER BY COALESCE(date_set,'') DESC, id DESC", args)
        else:
            rows = scoped(request, where, args)
        return rows_out(rows, u, request)

    @r.get("/tasks/search")
    def search_tasks(request: Request, q: str = ""):
        u = ctx.user(request)
        text = " ".join((q or "").split())[:300]
        closed = bool(re.search(r"закрыт[а-яё]*\s+задач", text, re.I))
        words = [w for w in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", re.sub(r"закрыт[а-яё]*\s+задач[а-яё]*", " ", text, flags=re.I))
                 if len(w) >= 2]
        if not words:
            return {"results": [], "tasks": [], "needs_detail": bool(text), "problem": "", "markers": None,
                    "closed_included": closed}
        rows = scoped(request, "status!='dropped'" + ("" if closed else " AND status='active'"))
        projects = {p["id"]: p["name"] for p in store.q("SELECT id, name FROM projects")}

        def n(s):
            return (s or "").lower().replace("ё", "е")
        stems = [n(w)[:max(4, len(w) - 2)] if len(w) > 4 else n(w) for w in words]
        found = []
        for t in rows:
            fields = {"description": n(t.get("description")), "responsible": n(t.get("assignee")),
                      "comment": n(t.get("last_comment")), "project": n(projects.get(t.get("project_id")))}
            hit = [k for k, v in fields.items() if all(s in " ".join(fields.values()) for s in stems) and any(s in v for s in stems)]
            if all(any(s in v for v in fields.values()) for s in stems):
                found.append({"task_id": t["id"], "matched_in": hit or ["description"]})
        by_id = {x["id"]: x for x in rows_out([t for t in rows if t["id"] in {f["task_id"] for f in found}], u, request)}
        return {"results": found, "tasks": [by_id[f["task_id"]] | {"matched_in": f["matched_in"]} for f in found if f["task_id"] in by_id],
                "needs_detail": False, "problem": "", "markers": None, "closed_included": closed}

    @r.get("/tasks/closed")
    def closed_tasks(request: Request, cursor: str | None = None, limit: int = ПОРЦИЯ):
        u = ctx.user(request)
        rows = scoped(request, "status='done'")
        rows.sort(key=lambda t: ((t.get("date_closed") or ""), t["id"]), reverse=True)
        start = 0
        if cursor:
            try:
                start = int(cursor)
            except ValueError:
                raise HTTPException(400, "Курсор архива не распознан") from None
        limit = max(1, min(int(limit or ПОРЦИЯ), 500))
        part = rows[start:start + limit]
        nxt = str(start + limit) if start + limit < len(rows) else None
        return {"items": rows_out(part, u, request), "next_cursor": nxt}

    @r.get("/tasks/closed/count")
    def closed_count(request: Request):
        return {"count": len(scoped(request, "status='done'"))}

    @r.get("/tasks/projects")
    def task_projects():
        """Справочник проектов для окна правки задачи — проекты MeetFlow (проект ведения)."""
        return [{"id": p["id"], "name": p["name"], "category": None}
                for p in store.q("SELECT id, name, archived FROM projects ORDER BY name") if not p.get("archived")]

    @r.post("/tasks", status_code=201)
    def create_task(payload: TaskCreate, request: Request):
        admin = ctx.need_admin(request)
        if payload.source_meeting_id:
            m = ctx.meeting_or_404(payload.source_meeting_id)
            pid = m["project_id"]
        else:
            pid = ctx.project_for_create(request)
        who = payload.responsible_text
        if payload.responsible_user_id:
            a = store.get("accounts", payload.responsible_user_id)
            if not a:
                raise HTTPException(404, "Пользователь не найден")
            who = a["full_name"]
        recent = store.q("SELECT * FROM tasks WHERE project_id=? AND updated_at>=?",
                         (pid, (datetime.now() - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S")))
        same = next((t for t in recent if norm_yo.равны(t["description"], payload.description)
                     and (t.get("assignee") or "") == (who or "")), None)
        if same:
            raise HTTPException(409, f"Такая задача только что заведена: «{same['description'][:80]}». Повторное нажатие не "
                                     "создаёт вторую")
        tid = pipe.reg.add(pid, payload.description, who, payload.source_meeting_id, "",
                           payload.due_date.isoformat() if payload.due_date else None,
                           payload.date_set.isoformat() if payload.date_set else date.today().isoformat())
        store.update("tasks", tid, status_detail=payload.status_detail or "")
        history(tid, "active", "active", "web_form", "заведена вручную", ctx.name(admin))
        return fresh(tid, admin, request)

    @r.get("/tasks/{tid}")
    def get_task(tid: int, request: Request):
        t = store.get("tasks", tid)
        if not t:
            raise HTTPException(404, "Задача не найдена")
        return rows_out([t], ctx.user(request), request)[0]

    @r.get("/tasks/{tid}/history")
    def get_history(tid: int):
        if not store.get("tasks", tid):
            raise HTTPException(404, "Задача не найдена")
        ids = team_ids()
        return [{"id": h["id"], "changed_at": iso_dt(h["at"]), "changed_by_user_id": ids.get(_norm(h.get("changed_by"))),
                 "old_status": h.get("old_status"), "new_status": h.get("new_status"), "source": h.get("source") or "",
                 "evidence_quote": h.get("evidence_quote")} for h in pipe.reg.history(tid)]

    # ------------------------------------------------------------------ правка
    @r.patch("/tasks/{tid}/status")
    def patch_status(tid: int, payload: StatusIn, request: Request):
        admin = ctx.need_admin(request)
        comment = (payload.comment or "").strip() or None
        if payload.new_status is None and not comment and not (payload.status_detail or "").strip():
            raise HTTPException(422, "Нечего менять: укажите новый статус (поле «new_status») или комментарий (поле «comment»)")
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            if payload.new_status:
                try:
                    st = TaskStatus(payload.new_status)
                except ValueError:
                    raise HTTPException(422, "Неизвестный статус задачи") from None
                pipe.reg.set_status(tid, st, "web_form", by=ctx.name(admin))
                if st == TaskStatus.DROPPED:
                    store.update("tasks", tid, status_detail=payload.status_detail or "снята вручную")
                for c in store.q("SELECT id FROM cards WHERE status='open' AND kind='member_note' AND payload LIKE ?",
                                 (f'%"task_id": {tid}%',)):
                    store.update("cards", c["id"], status="rejected", resolution="Задача закрыта — отметка больше не "
                                 "требует ответа", resolved_at=now())
            if payload.status_detail and not payload.new_status:
                store.update("tasks", tid, status_detail=payload.status_detail)
            if comment:
                if re.search(r"\b(снято|неактуально)\b", comment, re.I):
                    pipe.reg.set_status(tid, TaskStatus.DROPPED, "web_form", comment, by=ctx.name(admin))
                pipe.reg.comment(tid, comment, ctx.name(admin))
                store.update("tasks", tid, last_comment_by=ctx.name(admin), last_comment_date=date.today().isoformat())
        return fresh(tid, admin, request)

    @r.patch("/tasks/{tid}/responsible")
    def patch_responsible(tid: int, payload: ResponsibleIn, request: Request):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            who = (payload.responsible_text or "").strip() or None
            if payload.responsible_user_id:
                a = store.get("accounts", payload.responsible_user_id)
                if not a:
                    raise HTTPException(404, "Пользователь не найден")
                who = a["full_name"]
            if who:
                pipe.reg.set_assignee(tid, who, ctx.name(admin), "вручную")
            else:
                store.update("tasks", tid, assignee=None)
                history(tid, t["status"], t["status"], "operator", "исполнитель снят (вручную)", ctx.name(admin))
        return fresh(tid, admin, request)

    @r.patch("/tasks/{tid}/due")
    def patch_due(tid: int, payload: DueIn, request: Request):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            new = payload.due_date.isoformat() if payload.due_date else None
            if t.get("due_date") and new and t["due_date"] != new and not t.get("due_original"):
                store.update("tasks", tid, due_original=t["due_date"])
            pipe.reg.set_due(tid, new, ctx.name(admin), "вручную")
        return fresh(tid, admin, request)

    @r.patch("/tasks/{tid}/project")
    def patch_project(tid: int, payload: ProjectIn, request: Request):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            if payload.project_id is None:
                raise HTTPException(400, "В MeetFlow задача всегда в проекте — выберите проект из списка")
            p = store.get("projects", payload.project_id)
            if not p or p.get("archived"):
                raise HTTPException(400, "Такого проекта нет в справочнике — выберите из списка")
            store.update("tasks", tid, project_id=p["id"])
            history(tid, t["status"], t["status"], "operator", f"проект: {p['name']}", ctx.name(admin))
        return fresh(tid, admin, request)

    @r.patch("/tasks/{tid}/subproject")
    def patch_subproject(tid: int, payload: SubprojectIn, request: Request):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            sp = (payload.subproject or "").strip()
            allowed = [str(x) for x in (store.get_setting("subprojects", t["project_id"], []) or [])]
            if sp and sp not in allowed:
                raise HTTPException(400, "Такого подпроекта нет в справочнике подпроектов проекта")
            store.update("tasks", tid, subproject=sp)
            history(tid, t["status"], t["status"], "operator", f"подпроект: {sp or 'весь проект'}", ctx.name(admin))
        return fresh(tid, admin, request)

    @r.patch("/tasks/{tid}/description")
    def patch_description(tid: int, payload: DescriptionIn, request: Request):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, payload.version, ctx.name(admin))
            pipe.reg.set_description(tid, payload.description, ctx.name(admin), "правка формулировки")
            store.insert("doc_corrections", meeting_id=t.get("source_meeting_id"), doc="task", who=ctx.name(admin), at=now(),
                         place=f"формулировка задачи №{tid}", old_text=t.get("description") or "",
                         new_text=payload.description, fix=1)
        return fresh(tid, admin, request)

    @r.delete("/tasks/{tid}", status_code=204)
    def delete_task(tid: int, request: Request, version: int | None = None):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            take(t, version, ctx.name(admin))
            for c in store.q("SELECT id, payload FROM cards WHERE payload LIKE ?", (f'%"task_id": {tid}%',)):
                if loads(c["payload"], {}).get("task_id") == tid:
                    store.delete("cards", c["id"])
            for u in store.q("SELECT id FROM units WHERE task_id=?", (tid,)):
                store.update("units", u["id"], task_id=None)
            for h in store.q("SELECT id FROM task_history WHERE task_id=?", (tid,)):
                store.delete("task_history", h["id"])
            store.delete("tasks", tid)
            ctx.sys_msg(f"Задача №{tid} удалена из реестра насовсем",
                        f"Удалил: {ctx.name(admin)}. Формулировка: «{(t.get('description') or '')[:300]}». Встреча-источник: "
                        f"{t.get('source_meeting_id') or 'нет'}. Удаление необратимо.", "tasks")
        return Response(status_code=204)

    @r.post("/tasks/{tid}/operational")
    def set_operational(tid: int, payload: OperationalIn, request: Request):
        admin = ctx.need_admin(request)
        from ...core.tablica_zadach import РУЧНАЯ_ПОМЕТКА
        with lock:
            t = get_or_404(tid)
            if bool(t.get("operational")) == payload.value:
                return fresh(tid, admin, request)
            take(t, payload.version, ctx.name(admin))
            store.update("tasks", tid, operational=int(payload.value))
            history(tid, t["status"], t["status"], "web_form",
                    f"{РУЧНАЯ_ПОМЕТКА} {'отмечена' if payload.value else 'пометка снята'}", ctx.name(admin))
        return fresh(tid, admin, request)

    @r.post("/tasks/{tid}/revert")
    def revert(tid: int, request: Request, version: int | None = None):
        admin = ctx.need_admin(request)
        with lock:
            t = get_or_404(tid)
            if t["status"] not in ("done", "dropped"):
                raise HTTPException(400, "Вернуть в работу можно только задачу со статусом «выполнено» или «снято»")
            take(t, version, ctx.name(admin))
            pipe.reg.set_status(tid, TaskStatus.ACTIVE, "web_form", "возвращена в работу", by=ctx.name(admin))
            store.update("tasks", tid, status_detail="")
        return fresh(tid, admin, request)

    @r.post("/tasks/{tid}/under-question")
    def under_question(tid: int, payload: UnderQuestionIn, request: Request):
        admin = ctx.need_admin(request)
        if payload.action not in ("confirm", "drop"):
            raise HTTPException(400, "Здесь ответы: «Подтвердить» или «Снять».")
        with lock:
            t = get_or_404(tid)
            if t["status"] != "active" or not (t.get("doubt_reason") or "").strip():
                raise HTTPException(400, "Задача уже не «под вопросом» — обновите страницу.")
            take(t, payload.version, ctx.name(admin))
            was = t["doubt_reason"]
            if payload.action == "confirm":
                pipe.reg.clear_doubt(tid, ctx.name(admin), f"подтверждена (была под вопросом: {was})")
            else:
                pipe.reg.set_status(tid, TaskStatus.DROPPED, "operator", "не задача", by=ctx.name(admin))
                pipe.reg.clear_doubt(tid, ctx.name(admin), "не задача")
                store.update("tasks", tid, status_detail="снято: админом из «Разбора»")
                pipe.memory.answer(t["project_id"], "not_a_task", t.get("description") or "", "reject")
            for c in store.q("SELECT id, payload FROM cards WHERE status='open' AND kind='task_doubt' AND payload LIKE ?",
                             (f'%"task_id": {tid}%',)):
                if loads(c["payload"], {}).get("task_id") == tid:
                    store.update("cards", c["id"], status="accepted" if payload.action == "confirm" else "rejected",
                                 resolution=f"Задача {'оставлена' if payload.action == 'confirm' else 'снята'} — из «Разбора»",
                                 resolved_at=now())
        return fresh(tid, admin, request)

    @r.post("/tasks/{tid}/note")
    def note(tid: int, payload: NoteIn, request: Request):
        u = ctx.need_user(request)
        with lock:
            t = get_or_404(tid)
            admin = ctx.is_admin(u)
            if not admin and not is_responsible(t, u):
                raise HTTPException(403, "Актуализировать задачу может её ответственный или администратор")
            if t["status"] != "active":
                raise HTTPException(400, "Задача уже закрыта — актуализировать можно задачу в работе")
            head = (f"Нужен перенос срока до {ru_date(payload.due_date)}" if payload.kind == "reschedule" and payload.due_date
                    else "Нужен перенос срока" if payload.kind == "reschedule" else NOTE_PHRASES.get(payload.kind, ""))
            extra = " ".join((payload.text or "").split())
            text = f"{head}: {extra}" if head and extra else (head or extra)
            if not text:
                raise HTTPException(422, "Выберите готовый ответ или напишите, как идёт дело")
            who = ctx.name(u)
            if admin and payload.kind == "text" and re.search(r"\b(снято|неактуально)\b", text, re.I):
                pipe.reg.set_status(tid, TaskStatus.DROPPED, "web_form", text, by=who)
            if admin and payload.kind == "reschedule" and payload.due_date:
                if t.get("due_date") and not t.get("due_original"):
                    store.update("tasks", tid, due_original=t["due_date"])
                pipe.reg.set_due(tid, payload.due_date.isoformat(), who, "отметка ведущего")
            pipe.reg.comment(tid, text, who)
            store.update("tasks", tid, last_comment_by=who, last_comment_date=date.today().isoformat())
            if not admin:
                proposed = ru_date(payload.due_date) if payload.kind == "reschedule" and payload.due_date else (
                    "done" if payload.kind == "done" else None)
                for c in store.q("SELECT id, payload FROM cards WHERE status='open' AND kind='member_note'"):
                    p = loads(c["payload"], {})
                    if p.get("task_id") == tid and p.get("by_user_id") == u["id"]:
                        store.update("cards", c["id"], status="rejected", resolution="Заменена более новой отметкой того "
                                     "же человека", resolved_at=now())
                pipe.cards.open(t["project_id"], "member_note", f"Отметка по задаче: {text[:120]}",
                                {"task_id": tid, "description": t.get("description"), "note": text, "kind": payload.kind,
                                 "proposed": proposed, "by": who, "by_user_id": u["id"]}, t.get("source_meeting_id"))
        return fresh(tid, u, request)

    ctx.task_out = lambda t, u, request: rows_out([t], u, request)[0]
    _ = json
