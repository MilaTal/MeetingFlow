# -*- coding: utf-8 -*-
"""Протокол и план встречи на полотне, замечания проверки, единицы встречи — адреса ERP (перенос 27.10.2026).

Правка на полотне (`/meetings/{id}/{minutes|plan}/edit-context|edits|edits/finish|edits/discard`) — как
`services/pravka_polotno.py` ERP: правки абзацев копятся в черновике сеанса, «Готово» делает из него новую действующую
версию (прежняя остаётся в `protocol_versions`), «Отменить правки» убирает черновик; поля задач уходят в реестр сразу,
под версией задачи; каждая правка — строкой реестра корректировок (`doc_corrections`). Протокол, который правил человек,
моделью не пересобирается (`meetings.protocol_hand_edited`).

Замечания проверки (`/review-notes/{run}/{idx}`) — замечания сборки MeetFlow (`meetings.review_notes`): «Оставить как
есть», «Учтено», «Поправлено», «Вернуть». Единицы встречи (`/meetings/{id}/units`, `/units/*`) — пункты ядра MeetFlow.
"""
from __future__ import annotations

import json
import re
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core import units as units_mod
from ...core.store import now
from ...core.types import TaskStatus
from .obshchee import ADMIN_ROLES, Ctx, iso_dt, loads, ru_date, to_date

STATUS_LABEL = {"active": "в работе", "done": "выполнена", "dropped": "снята"}
UNIT_STATUS_RU = {"open": "открыт", "active": "действует", "closed": "закрыт", "replaced": "заменено", "removed": "убрано",
                  "done": "выполнено"}
OUTCOME_LABEL = {"keep": "оставлено как есть", "seen": "учтено", "fixed": "поправлено вручную",
                 "drop_task": "задача снята", "no_status": "статус не прозвучал"}


class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditsIn(InModel):
    version_id: str | int | None = None
    ops: list[dict] = Field(default_factory=list, max_length=50)
    is_processing_error_fix: bool = True


class FinishIn(InModel):
    version_id: str | int | None = None


class NoteActIn(InModel):
    action: str


class UnitActIn(InModel):
    action: str


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _norm(s: str | None) -> str:
    return " ".join((s or "").replace("[new] ", "").replace("ё", "е").replace("Ё", "Е").lower().split())


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, pipe = ctx.store, ctx.pipe

    def need_polotno(request: Request) -> dict:
        u = ctx.need_user(request)
        if u.get("role") not in ADMIN_ROLES:
            raise HTTPException(403, "Правка документа доступна администраторам проекта и директору")
        return u

    def doc_of(mid: int, vid: str) -> tuple[dict, str]:
        if vid not in ("minutes", "plan"):
            raise HTTPException(404, "Нет такого документа встречи")
        m = ctx.meeting_or_404(mid)
        md = m.get("protocol_md" if vid == "minutes" else "plan_md") or ""
        if not md:
            raise HTTPException(404, "Протокола этой встречи пока нет" if vid == "minutes" else "Плана этой встречи пока нет")
        return m, md

    def version_id(m: dict, vid: str) -> str:
        if vid == "minutes":
            v = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (m["id"],))
            return f"m{(v[0]['v'] if v and v[0]['v'] is not None else 0)}:{m.get('protocol_built_at') or ''}"
        return f"p:{m.get('plan_built_at') or ''}:{len(m.get('plan_md') or '')}"

    def draft_key(mid: int, vid: str) -> str:
        return f"polotno_draft:{mid}:{vid}"

    def get_draft(m: dict, vid: str) -> dict | None:
        d = store.get_setting(draft_key(m["id"], vid))
        return d if isinstance(d, dict) and d.get("md") else None

    def task_row(t: dict) -> dict:
        d = to_date(t.get("due_date"))
        return {"id": t["id"], "source_meeting_id": t.get("source_meeting_id"), "status": t.get("status") or "active",
                "status_label": STATUS_LABEL.get(t.get("status") or "active", t.get("status")),
                "status_detail": t.get("status_detail") or "", "operational": bool(t.get("operational")),
                "description": t.get("description") or "", "responsible": t.get("assignee") or "",
                "due": f"{d.day:02d}.{d.month:02d}.{d.year}" if d else "", "version": int(t.get("version") or 1)}

    def rows_of(m: dict, md: str) -> list[dict]:
        tasks = store.q("SELECT * FROM tasks WHERE project_id=? AND status!='dropped'", (m["project_id"],))
        by_desc: dict[str, dict] = {}
        for t in tasks:
            by_desc.setdefault(_norm(t["description"]), t)
        out, head = [], None
        for line in md.splitlines():
            s = line.strip()
            if not (s.startswith("|") and s.endswith("|") and len(s) > 1):
                head = None
                continue
            cells = _cells(s)
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            if head is None:
                head = [c.lower() for c in cells]
                continue
            di = next((i for i, h in enumerate(head) if any(w in h for w in ("задач", "описан", "формулир", "поручен"))), -1)
            if di < 0 or di >= len(cells):
                continue
            core = cells[di].split("¦")[0].replace("[new] ", "").strip()
            oi = next((i for i, h in enumerate(head) if h == "откуда"), -1)
            t = by_desc.get(_norm(core))
            if t:
                out.append({"line": s, "kind": "task", "task": task_row(t), "core": core,
                            "doubt": (t.get("doubt_reason") or "") if t.get("status") == "active" else "", "in_doc": True})
            elif oi >= 0 and oi < len(cells) and "материал" in cells[oi].lower():
                out.append({"line": s, "kind": "material", "why": "строка из материала — в реестр не заводилась"})
            else:
                out.append({"line": s, "kind": "unlinked", "why": "такой задачи в реестре нет — строка правится как текст"})
        return out

    def log_of(mid: int, vid: str) -> list[dict]:
        rows = store.q("SELECT * FROM doc_corrections WHERE meeting_id=? AND doc IN (?, 'task') ORDER BY id DESC LIMIT 100",
                       (mid, vid))
        return [{"who": x.get("who") or "", "when": iso_dt(x.get("at")), "place": x.get("place") or "",
                 "old": x.get("old_text") or "", "new": x.get("new_text") or ""} for x in rows]

    @r.get("/meetings/{mid}/{vid}/edit-context")
    def edit_context(mid: int, vid: str, request: Request):
        need_polotno(request)
        m, md = doc_of(mid, vid)
        dr = get_draft(m, vid)
        cur = version_id(m, vid)
        work = dr["md"] if dr else md
        shown = ctx.shown(work, m["project_id"])
        draft = None
        if dr:
            draft = {"edits": int(dr.get("edits") or 0), "since": iso_dt(dr.get("since")), "who": dr.get("who") or "",
                     "stale": dr.get("base_version") != cur}
        possible = []
        for p in store.q("SELECT * FROM possible_assignments WHERE meeting_id=? AND state='новое' ORDER BY id", (mid,)) \
                if _has_table("possible_assignments") else []:
            possible.append({"source": "pa", "id": p["id"], "description": p.get("text") or "", "responsible": p.get("responsible") or "",
                             "due": p.get("due") or "", "mark": "возможное поручение", "why": p.get("reason") or "",
                             "after_task_id": None, "version": 1})
        return {"version_id": cur, "display_md": shown, "source_md": work,
                "draft_note": "Документ пересобран после начала правки — черновик можно только отменить." if draft and draft["stale"] else "",
                "rows": rows_of(m, shown), "own_tasks": vid == "minutes", "possible": possible, "draft": draft,
                "log": log_of(mid, vid)}

    def _has_table(name: str) -> bool:
        return bool(store.q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))

    def correction(mid: int, vid: str, who: str, place: str, old: str, new: str, fix: bool) -> None:
        store.insert("doc_corrections", meeting_id=mid, doc=vid, who=who, at=now(), place=place, old_text=old or "",
                     new_text=new or "", fix=int(bool(fix)))

    def replace_line_cells(m: dict, vid: str, old_desc: str, t: dict) -> None:
        """Строка задачи в документе — вслед за реестром (формулировка, исполнитель, срок)."""
        col = "protocol_md" if vid == "minutes" else "plan_md"
        md = (store.get("meetings", m["id"]) or {}).get(col) or ""
        out, head, changed = [], None, False
        for line in md.splitlines():
            s = line.strip()
            if s.startswith("|") and s.endswith("|") and len(s) > 1:
                cells = _cells(s)
                if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                    out.append(line)
                    continue
                if head is None:
                    head = [c.lower() for c in cells]
                    out.append(line)
                    continue
                di = next((i for i, h in enumerate(head) if any(w in h for w in ("задач", "описан", "формулир", "поручен"))), -1)
                if 0 <= di < len(cells) and _norm(cells[di].split("¦")[0]) == _norm(old_desc):
                    sub = cells[di].split("¦", 1)
                    new_desc = ("[new] " if cells[di].startswith("[new] ") else "") + t["description"]
                    cells[di] = new_desc + (("¦" + sub[1]) if len(sub) > 1 else "")
                    for i, h in enumerate(head):
                        if i < len(cells) and ("ответствен" in h or "исполнит" in h):
                            cells[i] = t.get("assignee") or "не назначен"
                        if i < len(cells) and h.startswith("срок"):
                            d = to_date(t.get("due_date"))
                            cells[i] = f"{d.day:02d}.{d.month:02d}.{d.year}" if d else "не указан"
                    line = "| " + " | ".join(cells) + " |"
                    changed = True
            else:
                head = None
            out.append(line)
        if changed:
            store.update("meetings", m["id"], **{col: "\n".join(out)})

    @r.post("/meetings/{mid}/{vid}/edits")
    def edits(mid: int, vid: str, payload: EditsIn, request: Request):
        u = need_polotno(request)
        m, md = doc_of(mid, vid)
        from datetime import timedelta
        if to_date(m.get("date")) and to_date(m["date"]) < date.today() - timedelta(days=28):
            raise HTTPException(400, "Встреча в архиве — менять её уже нельзя")
        who = ctx.name(u)
        dr = get_draft(m, vid)
        cur = version_id(m, vid)
        if dr and dr.get("base_version") != cur:
            raise HTTPException(409, "Документ пересобран после начала правки — черновик относится к прежней версии; отмените его.")
        work = dr["md"] if dr else md
        draft_changed = False
        applied = []
        for op in payload.ops:
            kind = op.get("kind")
            if kind == "block":
                old, new = str(op.get("old") or ""), str(op.get("new") or "")
                if not new.strip():
                    raise HTTPException(400, "Пустой абзац не сохраняется")
                if work.count(old) != 1:
                    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
                    hits = [ln for ln in work.split("\n\n") if norm(ln) == norm(old)]
                    if len(hits) != 1:
                        raise HTTPException(409, "Этот абзац уже изменился — обновите страницу и поправьте снова.")
                    old = hits[0]
                work = work.replace(old, new, 1)
                correction(mid, vid, who, "абзац", old, new, payload.is_processing_error_fix)
                draft_changed = True
                applied.append("block")
            elif kind == "task":
                tid = int(op.get("task_id") or 0)
                t = store.get("tasks", tid)
                if not t:
                    raise HTTPException(404, "Задачи больше нет — её удалили. Обновите страницу.")
                if op.get("version") is not None and int(op["version"]) != int(t.get("version") or 1):
                    raise HTTPException(409, "Задачу уже изменили, пока окно было открыто — обновите страницу.")
                old_desc = t["description"]
                if "description" in op and op["description"] is not None:
                    pipe.reg.set_description(tid, str(op["description"]), who, "правка на полотне")
                    correction(mid, vid, who, f"формулировка задачи №{tid}", old_desc, str(op["description"]), payload.is_processing_error_fix)
                if "responsible" in op and op["responsible"] is not None:
                    v = str(op["responsible"]).strip()
                    if v:
                        pipe.reg.set_assignee(tid, v, who, "правка на полотне")
                    else:
                        store.update("tasks", tid, assignee=None)
                    correction(mid, vid, who, f"исполнитель задачи №{tid}", t.get("assignee") or "", v, payload.is_processing_error_fix)
                if "due" in op and op["due"] is not None:
                    d = to_date(op["due"]) if str(op["due"]).strip() else None
                    if str(op["due"]).strip() and d is None:
                        raise HTTPException(400, "Срок — в виде дд.мм.гггг, например 30.10.2026")
                    if t.get("due_date") and d and not t.get("due_original"):
                        store.update("tasks", tid, due_original=t["due_date"])
                    pipe.reg.set_due(tid, d.isoformat() if d else None, who, "правка на полотне")
                    correction(mid, vid, who, f"срок задачи №{tid}", ru_date(t.get("due_date")), ru_date(d), payload.is_processing_error_fix)
                if op.get("status"):
                    st = str(op["status"])
                    if st == "dropped" and not str(op.get("reason") or "").strip():
                        raise HTTPException(400, "Укажите причину снятия — задача снимается с причиной, не удаляется")
                    pipe.reg.set_status(tid, TaskStatus(st), "web_form", str(op.get("reason") or ""), by=who)
                    if st == "dropped":
                        store.update("tasks", tid, status_detail=f"снята: {op.get('reason')}")
                    correction(mid, vid, who, f"статус задачи №{tid}", STATUS_LABEL.get(t["status"], t["status"]),
                               STATUS_LABEL.get(st, st), payload.is_processing_error_fix)
                if "operational" in op and op["operational"] is not None:
                    from ...core.tablica_zadach import РУЧНАЯ_ПОМЕТКА
                    store.update("tasks", tid, operational=int(bool(op["operational"])))
                    pipe.reg._history(tid, t["status"], t["status"], "web_form",
                                      f"{РУЧНАЯ_ПОМЕТКА} {'отмечена' if op['operational'] else 'пометка снята'}", who)
                replace_line_cells(m, vid, old_desc, store.get("tasks", tid))
                applied.append("task")
            elif kind == "new_task":
                desc = str(op.get("description") or "").strip()
                if not desc:
                    raise HTTPException(400, "Формулировка не может быть пустой")
                d = to_date(op.get("due")) if str(op.get("due") or "").strip() else None
                tid = pipe.reg.add(m["project_id"], desc, (str(op.get("responsible") or "").strip() or None), mid, "",
                                   d.isoformat() if d else None, m.get("date"))
                row = f"| {tid} | {desc} | {str(op.get('responsible') or '').strip() or 'не назначен'} | {ru_date(d) or 'не указан'} | вручную |"
                lines = work.splitlines()
                last = max((i for i, ln in enumerate(lines) if ln.strip().startswith("|")), default=-1)
                if last >= 0:
                    lines.insert(last + 1, row)
                    work = "\n".join(lines)
                    draft_changed = True
                correction(mid, vid, who, "новая задача", "", desc, payload.is_processing_error_fix)
                applied.append("new_task")
            elif kind in ("confirm_possible", "drop_possible"):
                src = op.get("source")
                if src == "uq":
                    tid = int(op.get("task_id") or op.get("id") or 0)
                    t = store.get("tasks", tid)
                    if not t:
                        raise HTTPException(404, "Задачи больше нет — её удалили. Обновите страницу.")
                    if kind == "confirm_possible":
                        for f, setter in (("description", lambda v: pipe.reg.set_description(tid, v, who, "правка на полотне")),
                                          ("responsible", lambda v: pipe.reg.set_assignee(tid, v, who, "правка на полотне"))):
                            if str(op.get(f) or "").strip():
                                setter(str(op[f]).strip())
                        pipe.reg.clear_doubt(tid, who, "подтверждена на полотне")
                    else:
                        pipe.reg.set_status(tid, TaskStatus.DROPPED, "operator", "не поручение — решение секретаря", by=who)
                        pipe.reg.clear_doubt(tid, who, "не задача")
                    correction(mid, vid, who, "задача под вопросом", t["description"],
                               "в задачу" if kind == "confirm_possible" else "убрана", payload.is_processing_error_fix)
                elif src == "pa" and _has_table("possible_assignments"):
                    pa = store.get("possible_assignments", int(op.get("id") or 0))
                    if not pa:
                        raise HTTPException(404, "Строки больше нет — обновите страницу.")
                    if kind == "confirm_possible":
                        d = to_date(op.get("due") or pa.get("due"))
                        tid = pipe.reg.add(m["project_id"], str(op.get("description") or pa["text"]),
                                           str(op.get("responsible") or pa.get("responsible") or "") or None, mid,
                                           pa.get("quote") or "", d.isoformat() if d else None, m.get("date"))
                        store.update("possible_assignments", pa["id"], state="в задачу", task_id=tid, decided_by=who,
                                     decided_at=now())
                    else:
                        store.update("possible_assignments", pa["id"], state="не задача", decided_by=who, decided_at=now())
                    correction(mid, vid, who, "возможное поручение", pa.get("text") or "",
                               "в задачу" if kind == "confirm_possible" else "не задача", payload.is_processing_error_fix)
                applied.append(kind)
            else:
                raise HTTPException(400, "Неизвестный вид правки")
        if draft_changed:
            prev = dr or {"since": now(), "who": who, "edits": 0, "base_version": cur}
            prev.update(md=work, edits=int(prev.get("edits") or 0) + 1)
            store.set_setting(draft_key(mid, vid), prev, None, who)
        return {"ok": True, "applied": applied}

    @r.post("/meetings/{mid}/{vid}/edits/finish")
    def finish(mid: int, vid: str, payload: FinishIn, request: Request):
        u = need_polotno(request)
        m, _md = doc_of(mid, vid)
        dr = get_draft(m, vid)
        if not dr:
            return {"ok": True, "saved": False}
        if dr.get("base_version") != version_id(m, vid):
            raise HTTPException(409, "Документ пересобран после начала правки — черновик можно только отменить.")
        md = dr["md"]
        if vid == "minutes":
            v = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (mid,))
            ver = int((v[0]["v"] if v and v[0]["v"] is not None else 0) or 0) + 1
            store.insert("protocol_versions", meeting_id=mid, version=ver, protocol_md=md, model="правка на полотне", built_at=now())
            store.update("meetings", mid, protocol_md=md, protocol_hand_edited=1)
        else:
            store.update("meetings", mid, plan_md=md, plan_hand_edited=1)
        store.set_setting(draft_key(mid, vid), None, None, ctx.name(u))
        return {"ok": True, "saved": True}

    @r.post("/meetings/{mid}/{vid}/edits/discard")
    def discard(mid: int, vid: str, request: Request):
        u = need_polotno(request)
        doc_of(mid, vid)
        store.set_setting(draft_key(mid, vid), None, None, ctx.name(u))
        return {"ok": True}

    # ------------------------------------------------------------------ замечания проверки
    @r.post("/review-notes/{run_id}/{idx}")
    def note_act(run_id: str, idx: int, payload: NoteActIn, request: Request):
        u = ctx.need_admin(request)
        if payload.action not in ("keep", "seen", "fixed", "undo", "drop_task", "no_status"):
            raise HTTPException(400, "Неизвестное действие")
        try:
            mid = int(str(run_id).lstrip("m"))
        except ValueError:
            raise HTTPException(404, "Замечание не найдено") from None
        m = ctx.meeting_or_404(mid)
        notes = loads(m.get("review_notes"), [])
        if not (0 <= idx < len(notes)) or not isinstance(notes[idx], dict):
            raise HTTPException(404, "Замечание не найдено")
        n = notes[idx]
        if payload.action == "undo":
            for k in ("dismissed", "outcome", "outcome_label", "by", "at"):
                n.pop(k, None)
            msg = "Замечание снова открыто"
        else:
            n.update(dismissed=True, outcome=payload.action, outcome_label=OUTCOME_LABEL.get(payload.action, ""),
                     by=ctx.name(u), at=now())
            msg = f"Решение записано: {OUTCOME_LABEL.get(payload.action, '')}"
        store.update("meetings", mid, review_notes=json.dumps(notes, ensure_ascii=False))
        return {"ok": True, "message": msg}

    @r.get("/review-notes/decisions")
    def note_decisions(request: Request):
        ctx.need_admin(request)
        out = []
        extra, args = ctx.scope_sql(request)
        for m in store.q("SELECT id, date, review_notes FROM meetings WHERE 1=1" + extra + " ORDER BY date DESC", args):
            for i, n in enumerate(loads(m.get("review_notes"), [])):
                if isinstance(n, dict) and n.get("dismissed"):
                    out.append({"run_id": m["id"], "idx": i, "meeting_id": m["id"], "meeting_date": m["date"],
                                "issue": n.get("issue") or "", "quote": n.get("quote") or "", "outcome": n.get("outcome"),
                                "outcome_label": n.get("outcome_label") or "", "by": n.get("by") or "",
                                "at": iso_dt(n.get("at"))})
        return out

    # ------------------------------------------------------------------ единицы встречи
    def unit_out(u: dict, status: dict[int, str], mid: int) -> dict:
        st, why = units_mod.effective(u, status)
        roles = []
        for x in loads(u.get("roles"), []):
            if isinstance(x, dict):
                roles.append({"role": x.get("role") or "участник", "person": x.get("person") or x.get("name") or ""})
        t = store.get("tasks", u["task_id"]) if u.get("task_id") else None
        closed_m = store.get("meetings", u["closed_meeting_id"]) if u.get("closed_meeting_id") else None
        return {"id": u["id"], "kind": units_mod.KIND_RU.get(u["kind"], u["kind"]), "statement": u.get("text") or "",
                "status": "задача заведена" if u["kind"] == "task" and u.get("task_id") else UNIT_STATUS_RU.get(st, st),
                "quote": u.get("quote") or "", "ts": u.get("ts") or "", "roles": roles,
                "task_description": (t or {}).get("description"), "closed_how": u.get("closed_how") or "",
                "closed_note": u.get("closed_note") or why or "", "closed_quote": u.get("closed_quote") or "",
                "closed_meeting_date": (closed_m or {}).get("date"), "closed_here": bool(u.get("closed_meeting_id") == mid
                                                                                       and u.get("meeting_id") != mid),
                "auto": u["kind"] == "task", "planned_date": u.get("planned_date")}

    @r.get("/units/meetings")
    def units_meetings(request: Request):
        ctx.need_super(request)
        extra, args = ctx.scope_sql(request, "m.project_id")
        rows = store.q("SELECT m.id, m.date, m.label, COUNT(u.id) AS n FROM meetings m JOIN units u ON u.meeting_id=m.id "
                       "WHERE 1=1" + extra + " GROUP BY m.id ORDER BY m.date DESC", args)
        return [{"id": x["id"], "date": x["date"], "label": x.get("label"), "units": x["n"]} for x in rows]

    @r.get("/meetings/{mid}/units")
    def meeting_units(mid: int):
        ctx.meeting_or_404(mid)
        status = {t["id"]: t["status"] for t in store.q("SELECT id, status FROM tasks")}
        rows = store.q("SELECT * FROM units WHERE meeting_id=? OR closed_meeting_id=? ORDER BY line_from, id", (mid, mid))
        return [unit_out(u, status, mid) for u in rows]

    @r.post("/meetings/{mid}/units/extract")
    def units_extract(mid: int, request: Request):
        ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        raise HTTPException(400, "Пункты встречи в MeetFlow собираются при сборке протокола — пересоберите протокол "
                                 "(«Подготовка встречи»), отдельного вызова нет")

    @r.post("/meetings/{mid}/units/accept-all")
    def units_accept_all(mid: int, request: Request):
        ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        return {"accepted": 0}

    @r.patch("/units/{uid}")
    def unit_act(uid: int, payload: UnitActIn, request: Request):
        u = ctx.need_admin(request)
        row = store.get("units", uid)
        if not row:
            raise HTTPException(404, "Пункт не найден")
        who = ctx.name(u)
        if payload.action == "reject":
            units_mod.remove(store, uid, who)
            if row["kind"] == "task" and row.get("task_id"):
                pipe.reg.set_status(row["task_id"], TaskStatus.DROPPED, "operator", "задача заведена ошибочно", by=who)
        elif payload.action == "reopen":
            units_mod.reopen(store, uid, who)
        elif payload.action == "unlink":
            store.update("units", uid, task_id=None, updated_at=now())
        elif payload.action == "accept":
            store.update("units", uid, status="active" if row["kind"] in ("decision", "agreement") else "open",
                         decided_by=who, updated_at=now())
        else:
            raise HTTPException(400, "Неизвестное действие")
        status = {t["id"]: t["status"] for t in store.q("SELECT id, status FROM tasks")}
        return unit_out(store.get("units", uid), status, row["meeting_id"])
