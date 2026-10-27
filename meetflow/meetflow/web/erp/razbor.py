# -*- coding: utf-8 -*-
"""«Разбор» — адреса ERP `/razbor`, `/task-conflicts`, `/possible-assignments`, `/operator-rules` (перенос 27.10.2026).

Одна очередь, как в ERP: строки задач «под вопросом» и «Возможных поручений», ниже карточки «Конфликтов». Карточки — это
карточки MeetFlow (`cards`), отданные в виде `TaskConflictOut` ERP: поле, текущее и предложенное значение, цитата,
кандидаты. Решение карточки идёт тем же разбором, что и прежний экран MeetFlow (`/api/cards/{id}/resolve`), поэтому
правила одни: «это он» — по номеру человека, «не задача» дважды — правило оператора, второе нажатие ничего не делает.
Технические карточки — системные сообщения («Параметры системы»), в «Разбор» не идут.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core import vozmozhnye as vp
from ...core.store import now
from ...core.types import CardStatus, TaskStatus
from .obshchee import Ctx, iso_dt, loads, ru_date, to_date

NORM = 15
DAYS = 7
FIELD_OF = {"held_task": "ungrounded_task", "task_doubt": "ungrounded_task", "assign_person": "responsible",
            "confirm_person": "person", "due_unconfirmed": "due_date", "closing_candidate": "status",
            "mass_closing": "status", "review_finding": "review_finding", "member_note": "member_note",
            "held_recording": "held_recording", "waiting_tools": "held_recording", "department_mismatch": "responsible",
            "suspicious_source": "suspicious_source", "source_kind": "source_kind", "stopped_by_limit": "build_failed",
            "limit_cut": "build_failed", "rebuild_kept": "rebuild_order", "project_undetermined": "project_hint"}
VIEW_OF = {"ungrounded_task": "tasks", "duplicate_task": "tasks", "due_date": "tasks", "status": "tasks",
           "member_note": "tasks", "build_failed": "tasks", "rebuild_order": "tasks", "responsible": "people",
           "person": "people", "held_recording": "people", "voice_hint": "people", "project_hint": "projects",
           "agreement_doubt": "agree", "agreement_replace": "agree", "agreement_close": "agree",
           "review_finding": "system", "suspicious_source": "system", "source_kind": "system"}
EXCLUDED = ("technical", "task_doubt")


class InModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConflictIn(InModel):
    action: str
    custom_value: str | None = Field(default=None, max_length=2000)
    person_id: int | None = None
    project_role: str | None = None
    role: str | None = None
    department: str | None = None
    is_external: bool | None = None
    organization: str | None = None
    name_short_reason: str | None = None


class BatchIn(InModel):
    source: str
    ids: list[int] = Field(default_factory=list, max_length=200)
    action: str


class ToTaskIn(InModel):
    description: str | None = Field(default=None, max_length=2000)
    responsible: str | None = Field(default=None, max_length=300)
    due_date: str | None = None


class DaysIn(InModel):
    days: int


class ThresholdIn(InModel):
    enabled: bool | None = None


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, pipe = ctx.store, ctx.pipe

    def resolve(cid: int, u: dict, status: CardStatus, **kw) -> dict:
        app = ctx.app
        body = app.state.ResolveIn(status=status, **kw)
        return app.state.resolve_card(cid, body, {"role": u.get("role"), "name": ctx.name(u), "login": u.get("login") or ""})

    def conflict_out(c: dict) -> dict:
        p = loads(c.get("payload"), {})
        kind = c["kind"]
        field = FIELD_OF.get(kind, kind)
        t = store.get("tasks", p.get("task_id") or 0) if p.get("task_id") else None
        out = {"id": c["id"], "task_id": p.get("task_id"), "field": field, "source": kind, "current_value": None,
               "proposed_value": None, "evidence_quote": p.get("quote") or p.get("why") or "", "confidence": None,
               "status": c.get("status"), "meeting_id": c.get("meeting_id"), "task_description": (t or {}).get("description"),
               "identity": None, "candidates": [], "no_contact": False, "actions": [], "answers": [], "document": None,
               "voice_wait": False, "title": c.get("title"), "created_at": iso_dt(c.get("created_at"))}
        if kind == "held_task":
            out.update(proposed_value=p.get("description") or c["title"], current_value=p.get("quote") or "",
                       evidence_quote="; ".join(p.get("reasons") or []) if isinstance(p.get("reasons"), list) else "")
            if p.get("candidates"):
                out.update(source="unconfirmed_person", identity="same_or_new" if "same_or_new" in (p.get("reasons") or [])
                           else "namesakes", current_value=p.get("assignee") or "",
                           candidates=[{"id": x.get("id"), "name": x.get("name"), "note": x.get("note") or ""}
                                       for x in p["candidates"]], task_description=p.get("description"))
        elif kind in ("assign_person", "department_mismatch"):
            out.update(source="unconfirmed_person", current_value=p.get("named") or p.get("assignee") or p.get("name") or "",
                       identity="namesakes" if p.get("candidates") else None,
                       candidates=[{"id": x.get("id"), "name": x.get("name"), "note": x.get("note") or ""}
                                   for x in (p.get("candidates") or [])], no_contact=not p.get("candidates"))
        elif kind == "confirm_person":
            person = store.get("people", p.get("person_id") or 0) or {}
            out.update(source="unconfirmed_person", current_value=person.get("full_name") or p.get("name") or "")
        elif kind == "due_unconfirmed":
            out.update(current_value=ru_date((t or {}).get("due_date")) or "без срока",
                       proposed_value=p.get("proposed_text") or ru_date(p.get("proposed_value")))
        elif kind == "closing_candidate":
            out.update(current_value="active", proposed_value="done", confidence=p.get("confidence"))
        elif kind == "mass_closing":
            out.update(current_value="active", proposed_value="done",
                       evidence_quote=f"Закрытий сразу: {len(p.get('closings') or [])}. " + (p.get("why") or ""))
        elif kind == "review_finding":
            out.update(current_value=p.get("issue") or c["title"], evidence_quote=p.get("quote") or "")
        elif kind == "member_note":
            out.update(current_value=p.get("note") or "", proposed_value=p.get("proposed"),
                       evidence_quote=f"Отметка: {p.get('by') or ''}", task_description=p.get("description"))
        elif kind == "project_undetermined":
            # «Проект записи не определён» (27.10.2026): кандидаты — проекты справочника, выбор переносит встречу
            out.update(current_value=p.get("file") or "", evidence_quote=p.get("why") or "",
                       candidates=[{"id": x.get("id"), "name": x.get("name"), "note": ", ".join(x.get("hints") or [])}
                                   for x in (p.get("candidates") or [])], answers=["accept", "custom"])
        elif kind in ("held_recording", "waiting_tools"):
            out.update(current_value=p.get("file") or "", proposed_value=c["title"], answers=["accept", "reject"])
        else:
            out.update(current_value=c["title"], answers=["reject"])
        return out

    def open_cards(request: Request) -> list[dict]:
        extra, args = ctx.scope_sql(request)
        rows = store.q("SELECT * FROM cards WHERE status='open'" + extra + " ORDER BY id", args)
        return [c for c in rows if c["kind"] not in EXCLUDED]

    @r.get("/task-conflicts")
    def list_conflicts(request: Request, status: str = "open"):
        ctx.need_admin(request)
        if status != "open":
            extra, args = ctx.scope_sql(request)
            rows = store.q("SELECT * FROM cards WHERE status!='open'" + extra + " ORDER BY id DESC LIMIT 300", args)
            return [conflict_out(c) for c in rows if c["kind"] not in EXCLUDED]
        return [conflict_out(c) for c in open_cards(request)]

    @r.get("/task-conflicts/count")
    def count(request: Request):
        ctx.need_admin(request)
        return {"count": len(open_cards(request))}

    def decide_card(c: dict, payload: ConflictIn, u: dict) -> dict:
        kind, p, act = c["kind"], loads(c.get("payload"), {}), payload.action
        who = ctx.name(u)
        if kind == "member_note":
            tid = p.get("task_id")
            if act == "accept" and tid and store.get("tasks", tid):
                if p.get("proposed") == "done":
                    pipe.reg.set_status(tid, TaskStatus.DONE, "operator", p.get("note") or "", by=who)
                elif p.get("proposed"):
                    d = to_date(p["proposed"])
                    if d:
                        pipe.reg.set_due(tid, d.isoformat(), who, "по отметке исполнителя")
            store.update("cards", c["id"], status="accepted" if act == "accept" else "rejected",
                         resolution="принято" if act == "accept" else "оставлено как есть", resolved_at=now())
            return store.get("cards", c["id"])
        if kind == "project_undetermined" and act in ("accept", "confirm", "custom"):
            from ...core import proekt_zapisi as pz
            pid = payload.person_id
            if act == "custom":
                val = " ".join((payload.custom_value or "").split()).lower().replace("ё", "е")
                hit = [x for x in pz.проекты(store) if x["name"].lower().replace("ё", "е") == val]
                pid = hit[0]["id"] if len(hit) == 1 else None
            if not pid or not any(x["id"] == pid for x in pz.проекты(store)):
                raise HTTPException(422, "Выберите проект из справочника")
            pz.перенести_встречу(store, int(p.get("meeting_id") or c.get("meeting_id")), int(pid), who)
            pz.собрать_после_выбора(store, getattr(pipe, "queue", None), int(p.get("meeting_id") or c.get("meeting_id")), who)
            return store.get("cards", c["id"])
        if kind == "review_finding" and act == "reject":
            store.delete("cards", c["id"])            # «Замечание неверно» удаляет карточку насовсем (17.10.26)
            return {**c, "status": "rejected"}
        if act == "reject":
            return resolve(c["id"], u, CardStatus.REJECTED, resolution="оставлено как есть")
        if act == "duplicate":
            return resolve(c["id"], u, CardStatus.REJECTED, resolution="duplicate", action="duplicate")
        if act == "delete":
            return resolve(c["id"], u, CardStatus.REJECTED, resolution="не человек")
        if act in ("accept", "confirm"):
            choice = ""
            if payload.person_id:
                cands = p.get("candidates") or []
                if any(str(x.get("id")) == str(payload.person_id) for x in cands):
                    choice = str(payload.person_id)
                else:                                  # номер записи «Команды» — человек проекта с тем же ФИО
                    a = store.get("accounts", payload.person_id) or {}
                    hit = [x for x in cands if (x.get("name") or "").split(" (")[0] == a.get("full_name")]
                    choice = str(hit[0]["id"]) if hit else (a.get("full_name") or "")
                    if not hit and a.get("full_name") and p.get("task_id"):
                        pipe.reg.set_assignee(p["task_id"], a["full_name"], who, "выбор в «Разборе»")
                        store.update("cards", c["id"], status="accepted", resolution=a["full_name"], resolved_at=now())
                        return store.get("cards", c["id"])
            return resolve(c["id"], u, CardStatus.ACCEPTED, choice=choice, action="accept" if kind == "task_doubt" else "")
        if act == "custom":
            val = (payload.custom_value or "").strip()
            if not val:
                raise HTTPException(422, "Введите значение")
            if kind == "held_task":
                p["description"] = val
                store.update("cards", c["id"], payload=p)
                return resolve(c["id"], u, CardStatus.ACCEPTED)
            if kind in ("assign_person", "department_mismatch", "confirm_person"):
                ext = bool(payload.is_external)
                if ext:
                    return resolve(c["id"], u, CardStatus.ACCEPTED, new_full_name=val, new_organization=payload.organization or "",
                                   new_role=payload.project_role or "")
                from . import names
                bad = names.problem(val, payload.project_role, False, None, None)
                if bad:
                    raise HTTPException(400, bad)
                if kind == "confirm_person" and p.get("person_id"):
                    store.update("people", int(p["person_id"]), full_name=val, confirmed=1,
                                 role=payload.project_role or payload.role or "")
                elif p.get("task_id"):
                    pipe.reg.set_assignee(p["task_id"], val, who, "уточнено в «Разборе»")
                if not store.q("SELECT id FROM accounts WHERE full_name=?", (val,)):
                    store.insert("accounts", login=None, full_name=val, role="member", password_hash="", active=1,
                                 created_at=now(), confirmed=1, confirmed_source="карточка", position=payload.role or "",
                                 project_role=payload.project_role or "", department=payload.department or "")
                if getattr(ctx, "sync_team", None):
                    ctx.sync_team(force=True)
                store.update("cards", c["id"], status="accepted", resolution=val, resolved_at=now())
                return store.get("cards", c["id"])
            return resolve(c["id"], u, CardStatus.ACCEPTED, resolution=val)
        raise HTTPException(400, "Неизвестное действие")

    @r.patch("/task-conflicts/{cid}")
    def patch_conflict(cid: int, payload: ConflictIn, request: Request):
        u = ctx.need_admin(request)
        c = store.get("cards", cid)
        if not c:
            raise HTTPException(404, "Карточка не найдена")
        if c["status"] != "open":
            raise HTTPException(409, "Карточка уже закрыта — обновите список")
        out = decide_card(c, payload, u)
        fresh = store.get("cards", cid)
        return conflict_out(fresh) if fresh else {**conflict_out(c), "status": out.get("status", "rejected")}

    # ------------------------------------------------------------------ одна очередь «Разбора»
    def expires(created: str | None) -> tuple[str | None, bool]:
        d = to_date(created)
        if not d:
            return None, False
        end = d + timedelta(days=DAYS)
        return f"{end.isoformat()}T00:00:00", end == date.today() + timedelta(days=1)

    @r.get("/razbor")
    def razbor(request: Request):
        ctx.need_admin(request)
        vp.истечь(store)
        extra, args = ctx.scope_sql(request)
        items = []
        meetings = {m["id"]: m["date"] for m in store.q("SELECT id, date FROM meetings")}
        for t in store.q("SELECT * FROM tasks WHERE status='active' AND COALESCE(doubt_reason,'')!=''" + extra, args):
            ex, tom = expires(t.get("updated_at") or t.get("date_set"))
            items.append({"source": "task", "id": t["id"], "meeting_id": t.get("source_meeting_id"),
                          "meeting_date": meetings.get(t.get("source_meeting_id")), "title": t["description"],
                          "why": t.get("doubt_reason") or "", "expires_at": ex, "expires_tomorrow": tom, "impact": 0})
        for pa in store.q("SELECT * FROM possible_assignments WHERE state='новое'" + extra, args):
            ex, tom = expires(pa.get("created_at"))
            items.append({"source": "possible", "id": pa["id"], "meeting_id": pa.get("meeting_id"),
                          "meeting_date": pa.get("meeting_date"), "title": pa.get("text") or "", "why": pa.get("reason") or "",
                          "expires_at": ex if vp.срок_дней(store) else None, "expires_tomorrow": tom, "impact": 1})
        for c in open_cards(request):
            o = conflict_out(c)
            ex, tom = expires(c.get("created_at"))
            items.append({"source": "card", "id": c["id"], "kind": c["kind"], "field": o["field"],
                          "meeting_id": c.get("meeting_id"), "meeting_date": meetings.get(c.get("meeting_id")),
                          "title": c["title"], "why": "", "expires_at": ex, "expires_tomorrow": tom,
                          "impact": 0 if VIEW_OF.get(o["field"]) in ("tasks", "people") else 2, "golos": None})
        items.sort(key=lambda x: (x["impact"], x["expires_at"] or "9999"))
        by_view: dict[str, int] = {}
        for x in items:
            v = "tasks" if x["source"] in ("task", "possible") else VIEW_OF.get(x.get("field"), "tasks")
            by_view[v] = by_view.get(v, 0) + 1
        return {"items": items, "total": len(items), "by_view": by_view, "fields": VIEW_OF, "days": DAYS, "norm": NORM,
                "over": len(items) > NORM, "expires_tomorrow": sum(1 for x in items if x["expires_tomorrow"])}

    @r.get("/razbor/count")
    def razbor_count(request: Request):
        return {"total": razbor(request)["total"]}

    @r.post("/razbor/batch")
    def batch(payload: BatchIn, request: Request):
        u = ctx.need_admin(request)
        if payload.action not in ("to_task", "drop"):
            raise HTTPException(400, "Решения: «В задачу» или «Убрать»")
        done, errors = 0, []
        keys = set()
        for i in payload.ids:
            try:
                if payload.source == "task":
                    t = store.get("tasks", i)
                    if not t:
                        raise ValueError("задачи нет")
                    keys.add(t.get("source_meeting_id"))
                    if payload.action == "to_task":
                        pipe.reg.clear_doubt(i, ctx.name(u), "подтверждена в «Разборе»")
                    else:
                        pipe.reg.set_status(i, TaskStatus.DROPPED, "operator", "не задача", by=ctx.name(u))
                        pipe.reg.clear_doubt(i, ctx.name(u), "не задача")
                    for c in store.q("SELECT id, payload FROM cards WHERE status='open' AND kind='task_doubt'"):
                        if loads(c["payload"], {}).get("task_id") == i:
                            store.update("cards", c["id"], status="accepted" if payload.action == "to_task" else "rejected",
                                         resolution="решено в «Разборе»", resolved_at=now())
                elif payload.source == "possible":
                    pa = store.get("possible_assignments", i)
                    if not pa:
                        raise ValueError("строки нет")
                    keys.add(pa.get("meeting_id"))
                    if payload.action == "to_task":
                        vp.в_задачу(store, pipe.reg, pa, ctx.name(u))
                    else:
                        vp.не_задача(store, pa, ctx.name(u))
                elif payload.source == "card":
                    c = store.get("cards", i)
                    if not c or c["status"] != "open":
                        raise ValueError("карточка уже закрыта")
                    keys.add((c["kind"], c.get("meeting_id")))
                    decide_card(c, ConflictIn(action="accept" if payload.action == "to_task" else "reject"), u)
                else:
                    raise HTTPException(400, "Неизвестный вид строки")
                done += 1
            except (ValueError, vp.УжеРешено, HTTPException) as e:
                errors.append(f"№{i}: {getattr(e, 'detail', None) or e}")
        return {"done": done, "total": len(payload.ids), "errors": errors}

    # ------------------------------------------------------------------ «Возможные поручения»
    @r.get("/possible-assignments")
    def possible(request: Request, state: str = "", reason: str = "", date_from: str = "", date_to: str = "", q: str = ""):
        ctx.need_admin(request)
        vp.истечь(store)
        extra, args = ctx.scope_sql(request)
        rows = store.q("SELECT * FROM possible_assignments WHERE 1=1" + extra + " ORDER BY COALESCE(meeting_date,'') DESC, id",
                       args)
        out = []
        for x in rows:
            if state and x.get("state") != state:
                continue
            if reason and x.get("reason") != reason:
                continue
            d = (x.get("meeting_date") or "")[:10]
            if to_date(date_from) and d < to_date(date_from).isoformat():
                continue
            if to_date(date_to) and d > to_date(date_to).isoformat():
                continue
            if q.strip() and q.strip().lower().replace("ё", "е") not in (x.get("text") or "").lower().replace("ё", "е"):
                continue
            out.append(vp.в_словарь(x))
        team = sorted({a["full_name"] for a in store.q("SELECT full_name, active FROM accounts") if a.get("active", 1)
                       and (a.get("full_name") or "").strip()})
        return {"items": out, "total": len(out),
                "unresolved": len(store.q("SELECT id FROM possible_assignments WHERE state='новое'" + extra, args)),
                "days": vp.срок_дней(store), "reasons": list(vp.ПРИЧИНЫ), "states": list(vp.СОСТОЯНИЯ), "team": team}

    @r.post("/possible-assignments/{pid_}/to-task")
    def to_task(pid_: int, payload: ToTaskIn, request: Request):
        u = ctx.need_admin(request)
        pa = store.get("possible_assignments", pid_)
        if not pa:
            raise HTTPException(404, "Строки нет — обновите список")
        d = to_date(payload.due_date) if payload.due_date else None
        try:
            tid = vp.в_задачу(store, pipe.reg, pa, ctx.name(u), description=payload.description,
                              responsible=payload.responsible, due=d.isoformat() if d else None)
        except vp.УжеРешено as e:
            raise HTTPException(409, str(e)) from e
        return {"task_id": tid, "state": vp.В_ЗАДАЧУ}

    @r.post("/possible-assignments/{pid_}/not-task")
    def not_task(pid_: int, request: Request):
        u = ctx.need_admin(request)
        pa = store.get("possible_assignments", pid_)
        if not pa:
            raise HTTPException(404, "Строки нет — обновите список")
        try:
            vp.не_задача(store, pa, ctx.name(u))
        except vp.УжеРешено as e:
            raise HTTPException(409, str(e)) from e
        return {"id": pid_, "state": vp.НЕ_ЗАДАЧА}

    def threshold_state() -> dict:
        v = store.get_setting("narrow_threshold", None, None)
        return {"enabled": bool(v), "setting": v, "env": False, "source": "задан на экране" if v is not None else "по умолчанию"}

    @r.get("/possible-assignments/threshold")
    def threshold(request: Request):
        ctx.need_super(request)
        return threshold_state()

    @r.put("/possible-assignments/threshold")
    def set_threshold(payload: ThresholdIn, request: Request):
        u = ctx.need_super(request)
        vp.задать(store, payload.enabled, ctx.name(u))
        ctx.sys_msg(f"Узкий порог задачи: {'включён' if payload.enabled else 'выключен'}", f"Поменял: {ctx.name(u)}.",
                    "settings")
        return threshold_state()

    @r.put("/possible-assignments/settings")
    def set_days(payload: DaysIn, request: Request):
        u = ctx.need_super(request)
        if payload.days < 0 or payload.days > vp.ПРЕДЕЛ_ДНЕЙ:
            raise HTTPException(400, f"Срок — от 0 до {vp.ПРЕДЕЛ_ДНЕЙ} дней (0 — строки не истекают)")
        store.set_setting("possible_days", payload.days, None, ctx.name(u))
        return {"days": payload.days}

    # ------------------------------------------------------------------ правила оператора
    @r.get("/operator-rules")
    def rules(request: Request):
        ctx.need_admin(request)
        extra, args = ctx.scope_sql(request, "r.project_id")
        rows = store.q("SELECT r.*, p.name AS project_name FROM operator_rules r LEFT JOIN projects p ON p.id=r.project_id "
                       "WHERE 1=1" + extra + " ORDER BY r.id DESC LIMIT 300", args)
        out = []
        for x in rows:
            state = "отменено" if x.get("revoked_at") else ("действует" if x.get("active") else "копит ответы")
            out.append({"id": x["id"], "kind": x.get("kind"), "key": x.get("key"), "value": x.get("value"),
                        "text": x.get("key"), "state": state, "active": bool(x.get("active")) and not x.get("revoked_at"),
                        "applied_count": x.get("applied_count") or 0, "created_at": iso_dt(x.get("created_at")),
                        "expires_at": iso_dt(x.get("expires_at")), "revoked_at": iso_dt(x.get("revoked_at")),
                        "answers": len(loads(x.get("pending_answers"), [])), "project": x.get("project_name") or ""})
        return out

    @r.post("/operator-rules/{rid}/revoke")
    def revoke(rid: int, request: Request):
        ctx.need_admin(request)
        if not store.get("operator_rules", rid):
            raise HTTPException(404, "Правило не найдено")
        pipe.memory.revoke(rid)
        return {"ok": True}

    @r.post("/operator-rules/{rid}/restore")
    def restore(rid: int, request: Request):
        ctx.need_admin(request)
        if not store.get("operator_rules", rid):
            raise HTTPException(404, "Правило не найдено")
        pipe.memory.restore(rid)
        return {"ok": True}

    _ = datetime
