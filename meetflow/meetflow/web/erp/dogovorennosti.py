# -*- coding: utf-8 -*-
"""«Договорённости», «Статус проекта» (Сводка, Дорожная карта) и поиск — адреса ERP (перенос 27.10.2026).

Договорённости — пункты встречи ядра MeetFlow (`units`): решение, договорённость (правило работы), открытый вопрос; у
MeetFlow ещё два вида — уточнение и веха, они показываются своими словами. Режим «в тени» — настройка `agreements_mode`.

Сводка и Дорожная карта в MeetFlow собираются кодом из реестра, пунктов и встреч (`core/roadmap.py`), без платного вызова
модели: «Пересчитать» — пересборка сразу. Правленный человеком документ хранится как правленный (полотно).

Поиск — двухэтапный, как в ERP: этап 1 — протоколы, заметки, задачи, пункты встреч (`core/search.py`); пусто —
«Идёт глубокий поиск…» и этап 2 по расшифровкам (`/search/deep`); пусто и там — «По запросу информации нет».
"""
from __future__ import annotations

import re
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ...core import roadmap as roadmap_mod
from ...core import search as search_mod
from ...core import units as units_mod
from ...core.store import now
from .obshchee import Ctx, iso_dt, loads, ru_date, to_date

KIND_AGR = {"decision": "решение", "agreement": "правило работы", "open_question": "открытый вопрос",
            "clarification": "уточнение", "milestone": "веха"}
AGR_KIND = {v: k for k, v in KIND_AGR.items()}
KINDS = ["решение", "правило работы", "открытый вопрос", "обсуждено без решения", "уточнение", "веха"]
STATUS_AGR = {"active": "действует", "open": "действует", "closed": "закрыта", "replaced": "заменена",
              "removed": "убрана", "done": "выполнена"}
OPEN_FILTER = "открытые"
ПЕРВАЯ_ПОРЦИЯ = 7
SUGGESTED = ["задачи с ответственным (ФИО)", "в этой задаче есть о ...", "было ли упомянуто", "протокол встречи от",
             "саммари по встрече от", "информация о"]
ПРИМЕРЫ = ("в сентябре", "примерно месяц назад", "на прошлой неделе")
ПУСТО = "По запросу информации нет"
ГЛУБОКИЙ = "Идёт глубокий поиск, подождите, пожалуйста"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REFRESH_PAUSE_MIN = 60


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extract_mode: str | None = None
    agreements_mode: str | None = Field(default=None)


class EditsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str | int | None = None
    ops: list[dict] = Field(default_factory=list, max_length=50)
    is_processing_error_fix: bool = True


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str | int | None = None


def _n(s: str | None) -> str:
    return (s or "").lower().replace("ё", "е")


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, theme = ctx.store, ctx.theme

    # ------------------------------------------------------------------ договорённости
    def mode() -> str:
        return str(store.get_setting("agreements_mode", None, "on") or "on")

    @r.get("/agreements")
    def agreements(request: Request, project: str = "", kind: str = "", date_from: str = "", date_to: str = "", q: str = "",
                   status: str = "", meeting_id: int | None = None, offset: int = 0, limit: int | None = None):
        u = ctx.user(request)
        admin = ctx.is_admin(u)
        pid = ctx.project(request)
        projects = {p["id"]: p["name"] for p in store.q("SELECT id, name FROM projects")}
        # Фильтр проекта (вид ERP `podproekty.фильтр`): при выбранном проекте — «Весь проект X», его подпроекты и «без
        # подпроекта»; при «Все проекты» — проекты и подпроекты подписью «Проект – Подпроект» (многопроектность MeetFlow)
        live = [p for p in store.q("SELECT id, parent_id FROM projects WHERE COALESCE(archived,0)=0")]
        fam = ctx.family(pid) if pid else []
        if pid:
            label_ids = {ctx.project_names(i)[1]: i for i in fam if i != pid and ctx.project_names(i)[1]}
            subs = sorted(label_ids)
            pf = {"all": f"Весь проект {ctx.project_label(pid)}".strip(), "options": subs,
                  "none": "без подпроекта" if subs else "", "none_value": "__none__"}
        else:
            label_ids = {ctx.project_label(p["id"]): p["id"] for p in live}
            pf = {"all": "Все проекты", "options": sorted(label_ids), "none": "", "none_value": "__none__"}
        if project == "__none__":
            want_ids = {pid} if pid else None
        elif project:
            hit = label_ids.get(project)
            want_ids = set(ctx.family(hit)) if hit else set()
        else:
            want_ids = None
        base = {"kinds": KINDS, "statuses": sorted(set(STATUS_AGR.values())), "projects": pf["options"], "project_filter": pf,
                "mode": mode()}
        if u is None or (not admin and mode() == "shadow"):
            return {"items": [], "total": 0, **base}
        where, args = ["u.status != 'removed'", "u.kind IN ('decision','agreement','open_question','clarification','milestone')"], []
        if meeting_id is not None:
            where.append("u.meeting_id=?")
            args.append(meeting_id)
        elif pid:
            where.append(f"u.project_id IN ({','.join('?' * len(fam))})")
            args += fam
        rows = store.q("SELECT u.*, m.date AS mdate FROM units u LEFT JOIN meetings m ON m.id=u.meeting_id WHERE "
                       + " AND ".join(where) + " ORDER BY COALESCE(m.date,'') DESC, u.id", tuple(args))
        status_map = {t["id"]: t["status"] for t in store.q("SELECT id, status FROM tasks")}
        items = []
        for x in rows:
            st, _why = units_mod.effective(x, status_map)
            k = KIND_AGR.get(x["kind"], x["kind"])
            if (kind or "").strip().lower() == OPEN_FILTER:
                if k not in ("открытый вопрос", "обсуждено без решения") or st not in ("open", "active"):
                    continue
            elif kind and k != kind.strip().lower():
                continue
            stt = STATUS_AGR.get(st, st)
            if status and stt != status:
                continue
            d = (x.get("mdate") or "")[:10]
            if to_date(date_from) and d < to_date(date_from).isoformat():
                continue
            if to_date(date_to) and d > to_date(date_to).isoformat():
                continue
            if want_ids is not None and x.get("project_id") not in want_ids:
                continue
            roles = loads(x.get("roles"), [])
            people = lambda role: ", ".join(r.get("person") or r.get("name") or "" for r in roles  # noqa: E731
                                            if isinstance(r, dict) and r.get("role") == role)
            item = {"id": x["id"], "meeting_id": x["meeting_id"], "date": d,
                    "project": ctx.project_names(x.get("project_id"))[0],
                    "subproject": ctx.project_names(x.get("project_id"))[1] if pid else ctx.project_label(x.get("project_id")),
                    "topic": "", "kind": k, "text": x.get("text") or "",
                    "decided_by": x.get("decided_by") or people("ответственный"), "agreed_by": people("участник"),
                    "proposed_by": people("влияющий"), "quote": (x.get("quote") or "") if admin else "",
                    "line_no": x.get("line_from") if admin else None, "status": stt, "replaced_by_id": None,
                    "under_question": None}
            if q.strip():
                words = [w for w in re.findall(r"[0-9A-Za-zА-Яа-яЁё.]+", q) if len(w) >= 2]
                hay = _n(" ".join([item["text"], item["project"], item["decided_by"], item["agreed_by"], ru_date(d), d]))
                if not all(_n(w)[:max(4, len(w) - 2)] in hay for w in words):
                    continue
            items.append(item)
        total = len(items)
        lim = (ПЕРВАЯ_ПОРЦИЯ if meeting_id is None else 0) if limit is None else max(0, limit)
        part = items[max(0, offset):(max(0, offset) + lim) if lim else None]
        return {"items": part, "total": total, "markers": None, "period_relaxed": False, **base}

    @r.get("/agreements/settings")
    def agr_settings(request: Request):
        ctx.need_admin(request)
        return {"extract_mode": str(store.get_setting("extract_mode", None, "topics") or "topics"),
                "extract_modes": ["topics", "chunks", "draft"], "agreements_mode": mode()}

    @r.post("/agreements/settings")
    def agr_settings_set(payload: SettingsIn, request: Request):
        u = ctx.need_super(request)
        if payload.agreements_mode is not None:
            if payload.agreements_mode not in ("on", "shadow"):
                raise HTTPException(400, "Режим договорённостей — «on» или «shadow»")
            if payload.agreements_mode != mode():
                ctx.sys_msg(f"Договорённости: {mode()} → {payload.agreements_mode}",
                            f"Поменял: {ctx.name(u)}. Действует сразу для показа.", "settings")
            store.set_setting("agreements_mode", payload.agreements_mode, None, ctx.name(u))
        if payload.extract_mode is not None:
            if payload.extract_mode not in ("topics", "chunks", "draft"):
                raise HTTPException(400, "Неизвестный режим извлечения")
            store.set_setting("extract_mode", payload.extract_mode, None, ctx.name(u))
        return agr_settings(request)

    # ------------------------------------------------------------------ Статус проекта
    def need_pid(request: Request) -> int:
        pid = ctx.project(request)
        if not pid:
            raise HTTPException(400, "Сводка и Дорожная карта собираются по одному проекту — выберите проект внизу левой панели")
        return pid

    def summary_md(pid: int) -> str:
        p = store.get("projects", pid) or {}
        today = date.today().isoformat()
        # проект — вместе с подпроектами (выбор проекта показывает его с подпроектами)
        fam = ctx.family(pid) or [pid]
        inn = f"IN ({','.join('?' * len(fam))})"
        tasks = store.q(f"SELECT status, due_date, description, assignee FROM tasks WHERE project_id {inn}", tuple(fam))
        active = [t for t in tasks if t["status"] == "active"]
        over = [t for t in active if t.get("due_date") and t["due_date"] < today]
        units = store.q(f"SELECT kind, status, text FROM units WHERE project_id {inn}", tuple(fam))
        meetings = store.q(f"SELECT date, protocol_built_at FROM meetings WHERE project_id {inn} AND COALESCE(status,'')!='cancelled'",
                           tuple(fam))
        past = sorted(m["date"] for m in meetings if (m["date"] or "") <= today)
        lines = [f"Сводка по проекту «{p.get('name', '')}» на {ru_date(today)}", "",
                 "1 Задачи", "",
                 f"В работе — {len(active)}, просрочено — {len(over)}, без срока — "
                 f"{sum(1 for t in active if not t.get('due_date'))}, выполнено — {sum(1 for t in tasks if t['status'] == 'done')}.", ""]
        if over:
            lines += ["Просроченные задачи:", ""] + [f"— {t['description']} ({t.get('assignee') or 'не назначен'}, срок "
                                                      f"{ru_date(t['due_date'])})" for t in over[:15]] + [""]
        opened = [x for x in units if x["status"] in ("open", "active")]
        lines += ["2 Решения и открытые вопросы", "",
                  f"Действующих решений — {sum(1 for x in opened if x['kind'] == 'decision')}, договорённостей — "
                  f"{sum(1 for x in opened if x['kind'] == 'agreement')}, открытых вопросов — "
                  f"{sum(1 for x in opened if x['kind'] == 'open_question')}.", ""]
        qs = [x for x in opened if x["kind"] == "open_question"]
        if qs:
            lines += [f"— {x['text']}" for x in qs[:15]] + [""]
        lines += ["3 Встречи", "",
                  f"Встреч — {len(meetings)}, с протоколом — {sum(1 for m in meetings if m['protocol_built_at'])}"
                  + (f", последняя — {ru_date(past[-1])}." if past else ".")]
        return "\n".join(lines)

    def roadmap_md(pid: int) -> str:
        return roadmap_mod.to_markdown(roadmap_mod.build(store, theme, pid), theme)

    def doc(pid: int, kind: str) -> dict:
        saved = store.get_setting(f"status_doc:{kind}", pid)
        if isinstance(saved, dict) and saved.get("md"):
            return saved
        return {}

    def rebuild(pid: int, who: str) -> dict:
        at = now()
        for kind, fn in (("summary", summary_md), ("roadmap", roadmap_md)):
            old = doc(pid, kind)
            if old.get("hand_edited"):
                continue                       # правленный человеком документ кодом не перезаписывается
            store.set_setting(f"status_doc:{kind}", {"md": fn(pid), "generated_at": at, "hand_edited": False}, pid, who)
        store.set_setting("status_refresh", {"status": "done", "finished_at": at, "started_at": at,
                                             "duration_seconds": 0, "result": {"status": "saved"}, "by": who}, pid, who)
        return store.get_setting("status_refresh", pid)

    def doc_out(pid: int, kind: str) -> dict:
        d = doc(pid, kind)
        if not d:
            return {"available": False, "message": ("Сводки" if kind == "summary" else "Дорожной карты")
                    + " пока нет — нажмите «Пересчитать»"}
        return {"available": True, "content_md": ctx.shown(d["md"], pid), "generated_at": iso_dt(d.get("generated_at")),
                "sources": [], "minor_findings": [], "hand_edited": bool(d.get("hand_edited"))}

    @r.get("/project-status/summary")
    def get_summary(request: Request):
        return doc_out(need_pid(request), "summary")

    @r.get("/project-status/roadmap")
    def get_roadmap(request: Request):
        return doc_out(need_pid(request), "roadmap")

    @r.get("/project-status/refresh-status")
    def refresh_status(request: Request):
        pid = ctx.project(request)
        st = (store.get_setting("status_refresh", pid) if pid else None) or {"status": "idle"}
        out = {"status": st.get("status", "idle"), "finished_at": iso_dt(st.get("finished_at")),
               "duration_seconds": st.get("duration_seconds"), "elapsed_seconds": 0, "likely_stuck": False,
               "result": st.get("result") or {}}
        u = ctx.user(request)
        if st.get("finished_at") and not (u and u.get("role") == "super_admin"):
            try:
                nxt = datetime.fromisoformat(st["finished_at"]) .timestamp() + REFRESH_PAUSE_MIN * 60
                if nxt > datetime.now().timestamp():
                    out["next_manual_at"] = datetime.fromtimestamp(nxt).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        return out

    @r.post("/project-status/refresh")
    def refresh(request: Request):
        u = ctx.need_user(request)
        pid = need_pid(request)
        st = rebuild(pid, ctx.name(u))
        return {"status": "done", "already": False, "pause": False, "finished_at": iso_dt(st.get("finished_at")),
                "duration_seconds": 0, "elapsed_seconds": 0, "result": {"status": "saved"}}

    @r.get("/project-status/staleness")
    def staleness(request: Request):
        pid = ctx.project(request)
        if not pid:
            return {"stale": False, "changed_tasks_count": 0}
        d = doc(pid, "summary")
        if not d:
            return {"stale": True, "reason": "not_generated_yet", "changed_tasks_count": 0}
        n = store.q("SELECT COUNT(*) AS n FROM task_history h JOIN tasks t ON t.id=h.task_id WHERE t.project_id=? AND h.at>?",
                    (pid, d.get("generated_at") or ""))[0]["n"]
        return {"stale": n >= 5, "changed_tasks_count": n}

    def export(pid: int, kind: str) -> Response:
        from ...connectors.export import DocxOutput
        d = doc(pid, kind)
        if not d:
            raise HTTPException(404, "Документа пока нет")
        out = DocxOutput(theme.get("design.document_font", "Times New Roman"), int(theme.get("design.document_size_pt", 12)))
        from urllib.parse import quote
        name = ("Сводка" if kind == "summary" else "Дорожная карта") + f" {ru_date(date.today())}.docx"
        return Response(out.render(ctx.shown(d["md"], pid), kind), media_type=DOCX,
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})

    @r.get("/project-status/summary/export")
    def summary_export(request: Request):
        return export(need_pid(request), "summary")

    @r.get("/project-status/roadmap/export")
    def roadmap_export(request: Request):
        return export(need_pid(request), "roadmap")

    def status_draft_key(kind: str) -> str:
        return f"status_draft:{kind}"

    @r.get("/project-status/{kind}/edit-context")
    def status_ctx(kind: str, request: Request):
        ctx.need_admin(request)
        if kind not in ("summary", "roadmap"):
            raise HTTPException(404, "Нет такого документа")
        pid = need_pid(request)
        d = doc(pid, kind)
        if not d:
            raise HTTPException(404, "Документа пока нет")
        dr = store.get_setting(status_draft_key(kind), pid)
        work = dr["md"] if isinstance(dr, dict) and dr.get("md") else d["md"]
        log = [{"who": x["who"], "when": iso_dt(x["at"]), "place": x["place"], "old": x["old_text"], "new": x["new_text"]}
               for x in store.q("SELECT * FROM doc_corrections WHERE doc=? AND meeting_id IS ? ORDER BY id DESC LIMIT 100",
                                (f"{kind}:{pid}", None))]
        draft = ({"edits": dr.get("edits", 0), "since": iso_dt(dr.get("since")), "who": dr.get("who", ""), "stale": False}
                 if isinstance(dr, dict) and dr.get("md") else None)
        return {"version_id": d.get("generated_at"), "display_md": work, "source_md": work, "draft_note": "", "rows": [],
                "own_tasks": False, "possible": [], "draft": draft, "log": log}

    @r.post("/project-status/{kind}/edits")
    def status_edits(kind: str, payload: EditsIn, request: Request):
        u = ctx.need_admin(request)
        pid = need_pid(request)
        d = doc(pid, kind)
        if kind not in ("summary", "roadmap") or not d:
            raise HTTPException(404, "Документа пока нет")
        dr = store.get_setting(status_draft_key(kind), pid)
        dr = dr if isinstance(dr, dict) and dr.get("md") else {"md": d["md"], "since": now(), "who": ctx.name(u), "edits": 0}
        for op in payload.ops:
            if op.get("kind") != "block":
                raise HTTPException(400, "В Сводке и Дорожной карте правятся только абзацы")
            old, new = str(op.get("old") or ""), str(op.get("new") or "")
            if dr["md"].count(old) != 1 or not new.strip():
                raise HTTPException(409, "Этот абзац уже изменился — обновите страницу и поправьте снова.")
            dr["md"] = dr["md"].replace(old, new, 1)
            store.insert("doc_corrections", meeting_id=None, doc=f"{kind}:{pid}", who=ctx.name(u), at=now(), place="абзац",
                         old_text=old, new_text=new, fix=int(payload.is_processing_error_fix))
        dr["edits"] = int(dr.get("edits") or 0) + 1
        store.set_setting(status_draft_key(kind), dr, pid, ctx.name(u))
        return {"ok": True}

    @r.post("/project-status/{kind}/edits/finish")
    def status_finish(kind: str, payload: FinishIn, request: Request):
        u = ctx.need_admin(request)
        pid = need_pid(request)
        dr = store.get_setting(status_draft_key(kind), pid)
        if isinstance(dr, dict) and dr.get("md"):
            d = doc(pid, kind)
            store.set_setting(f"status_doc:{kind}", {"md": dr["md"], "generated_at": d.get("generated_at") or now(),
                                                    "hand_edited": True}, pid, ctx.name(u))
            store.set_setting(status_draft_key(kind), None, pid, ctx.name(u))
            return {"ok": True, "saved": True}
        return {"ok": True, "saved": False}

    @r.post("/project-status/{kind}/edits/discard")
    def status_discard(kind: str, request: Request):
        u = ctx.need_admin(request)
        store.set_setting(status_draft_key(kind), None, need_pid(request), ctx.name(u))
        return {"ok": True}

    # ------------------------------------------------------------------ поиск
    def project_ids(request: Request) -> list[int]:
        pid = ctx.project(request)
        return [pid] if pid else [p["id"] for p in store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0")]

    def kind_label(t: str) -> str:
        return {"protocol": "Протокол встречи", "source": "Источник", "task": "Задача", "unit": "Из записи встречи"}.get(t, t)

    def stage(request: Request, q: str, raw: bool) -> list[dict]:
        out = []
        for pid in project_ids(request):
            res = search_mod.search(store, pid, q, raw_speech=raw)
            if res.get("problem"):
                return [{"problem": res["problem"]}]
            out += res.get("results") or []
        return out

    def snippet_parts(text: str, q: str) -> list[dict]:
        words = [w for w in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", q) if len(w) >= 3]
        if not words:
            return [{"text": text, "mark": False}]
        rx = re.compile("(" + "|".join(re.escape(w[:max(4, len(w) - 2)]) for w in words) + r"[0-9A-Za-zА-Яа-яЁё]*)", re.I)
        parts, pos = [], 0
        for m in rx.finditer(text):
            if m.start() > pos:
                parts.append({"text": text[pos:m.start()], "mark": False})
            parts.append({"text": m.group(0), "mark": True})
            pos = m.end()
        if pos < len(text):
            parts.append({"text": text[pos:], "mark": False})
        return parts

    @r.get("/search")
    def search(request: Request, q: str = Query("", max_length=300)):
        if not q.strip():
            return {"results": [], "suggested_queries": SUGGESTED}
        if search_mod.is_hint_only(q):
            return {"results": [], "suggested_queries": SUGGESTED, "needs_detail": True, "markers": None}
        found = stage(request, q, False)
        if found and found[0].get("problem"):
            return {"results": [], "suggested_queries": SUGGESTED, "needs_detail": True, "problem": found[0]["problem"],
                    "markers": None}
        found = [x for x in found if x.get("type") != "source" or True]
        if not found:
            return {"results": [], "stage": 2, "deep": True, "message": ГЛУБОКИЙ, "suggested_queries": SUGGESTED,
                    "markers": None}
        results = []
        for x in found:
            st = {"protocol": "meeting_minutes", "source": "meeting_source", "task": "task", "unit": "meeting_source"}.get(x["type"], x["type"])
            mid = x["id"] if x["type"] in ("protocol", "source", "unit") else (store.get("tasks", x["id"]) or {}).get("source_meeting_id")
            results.append({"source_type": st, "kind_label": x.get("title") or kind_label(x["type"]),
                            "meeting_date": (x.get("meeting_date") or "")[:10] or None, "meeting_id": mid,
                            "is_current": True, "places": 1, "snippet": x.get("snippet") or "",
                            "snippet_parts": snippet_parts(x.get("snippet") or "", q)})
        return {"results": results, "stage": 1, "suggested_queries": SUGGESTED, "markers": None}

    @r.get("/search/markers")
    def markers(request: Request):
        pid = ctx.project(request)
        p = store.get("projects", pid) if pid else None
        ex = list(ПРИМЕРЫ) + ([f"по проекту {p['name']}"] if p else [])
        return {"hint": "Кроме слов, в одной строке можно указать время: «в сентябре», «на прошлой неделе», «12.09.2026».",
                "examples": ex}

    @r.get("/search/deep")
    def deep(request: Request, q: str = Query("", max_length=300)):
        out = []
        words = [w for w in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", q) if len(w) >= 3]
        if not words:
            return {"results": [], "stage": 3, "message": ПУСТО, "suggested_queries": SUGGESTED, "markers": None}
        stems = [_n(w)[:max(4, len(w) - 2)] for w in words]
        projects = {p["id"]: p["name"] for p in store.q("SELECT id, name FROM projects")}
        for pid in project_ids(request):
            rows = store.q("SELECT s.text, s.meeting_id, m.date, m.protocol_md FROM sources s JOIN meetings m ON m.id=s.meeting_id "
                           "WHERE m.project_id=? AND s.removed_at IS NULL AND s.kind IN ('transcript','recording') "
                           "ORDER BY m.date DESC", (pid,))
            for s in rows:
                lines = [ln for ln in (s["text"] or "").splitlines() if ln.strip()]
                for i, ln in enumerate(lines):
                    if not all(st in _n(ln) for st in stems):
                        continue

                    def rep(x: str, hit: bool) -> dict:
                        parts = [p.strip() for p in x.split("\t")]
                        if len(parts) == 3:
                            tm, who, text = parts
                        else:
                            mm = re.match(r"\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*([^:]{2,60}):\s*(.*)", x)
                            tm, who, text = (mm.group(1), mm.group(2), mm.group(3)) if mm else ("", "участник не определён", x)
                        return {"time": tm, "speaker": who, "parts": snippet_parts(text, q) if hit else [{"text": text, "mark": False}],
                                "hit": hit}
                    cur = rep(ln, True)
                    reps = [rep(x, False) for x in lines[max(0, i - 1):i]] + [cur] + [rep(x, False) for x in lines[i + 1:i + 2]]
                    out.append({"source_type": "transcript_hit", "brief": len(out) >= 3,
                                "header": {"title": "Встреча", "date": ru_date(s["date"]), "project": projects.get(pid, "")},
                                "links": {"meeting": f"#meetings/{s['meeting_id']}", "meeting_label": f"встреча {ru_date(s['date'])}",
                                          "protocol": f"#meetings/{s['meeting_id']}/protocol" if s.get("protocol_md") else ""},
                                "speaker": cur["speaker"], "time": cur["time"], "replicas": reps, "retell": "",
                                "quote_title": "Как звучало в записи", "quote_collapsed": False})
                    if len(out) >= 20:
                        break
        if not out:
            return {"results": [], "stage": 3, "message": ПУСТО, "suggested_queries": SUGGESTED, "markers": None}
        return {"results": out, "stage": 2, "suggested_queries": SUGGESTED, "markers": None}
