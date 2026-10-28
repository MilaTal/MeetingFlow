# -*- coding: utf-8 -*-
"""«Параметры системы», «Мониторинг RealTime», «Модели», «База голосов», «Разбор голосов», «Темы планёрок», словарь
распознавания — адреса ERP `/project-status/*`, `/meeting-topics/*`, `/recognition-settings`, `/voice/review/*`
(перенос 27.10.2026, экраны 1 в 1).

Данные — MeetFlow: службы, ожидание оператора и база голосов берутся теми же функциями, что у прежних экранов MeetFlow
(`web/app.py`: `_services`, `_awaiting`, `voice_base_state`), модели — маршрутами `connectors/llm_routes.py` (тот же
`model_routes`, что у ERP), системные сообщения — технические карточки. Папка-приёмник, интервал обхода и автозапуск —
по выбранному проекту (у каждого проекта своя папка — разрешённое отличие от ERP); идущий проход папки показывается
«идёт проход…», а не «завис» (пульс прохода `core/intake.py`, dbc24a5).
"""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ...core.store import now
from .obshchee import Ctx, iso_dt, loads, ru_date

STARTED = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
TECH = "technical"


class InModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Toggle(InModel):
    enabled: bool | None = None


class Days(InModel):
    days: int


class SharedPw(InModel):
    new_password: str = Field(max_length=200)
    repeat_password: str = Field(default="", max_length=200)


class SystemProjectIn(InModel):
    name: str = Field(default="", max_length=200)
    aliases: str = Field(default="", max_length=2000)


class SubprojectsIn(InModel):
    items: list[dict] = Field(default_factory=list, max_length=200)


class WatchFolderIn(InModel):
    path: str = Field(default="", max_length=500)
    repeat_path: str = Field(default="", max_length=500)
    confirm: bool = False
    current_password: str = Field(default="", max_length=200)


class IntervalIn(InModel):
    seconds: int | None = Field(default=None, ge=10, le=86400)


class ResumeIn(InModel):
    job_id: int


class ConfirmIn(InModel):
    confirm: bool = False


class TopicIn(InModel):
    name: str | None = Field(default=None, max_length=200)
    weekdays: list[int] | None = None
    sections: list[str] | None = None
    head_names: list[str] | None = None
    objects: list[str] | None = None
    hint: str | None = Field(default=None, max_length=4000)
    carry_same_topic: bool | None = None
    is_active: bool | None = None


class MeetingTopicIn(InModel):
    topic_id: int | None = None


class RecSettingIn(InModel):
    key: str
    enabled: bool | None = None


class RouteUse(InModel):
    role: str
    point: str


class RoutePoint(InModel):
    name: str = ""
    old_name: str = ""
    fields: dict = Field(default_factory=dict)
    key_value: str = ""
    value: str = ""


class RouteRole(InModel):
    role: str
    point: str
    action: str


class VoiceIds(InModel):
    ids: list[int] = Field(default_factory=list, max_length=5000)


class VoiceDecision(InModel):
    ids: list[int] = Field(default_factory=list, max_length=5000)
    reshenie: str = Field(max_length=20)
    imya: str = Field(default="", max_length=200)
    vybran: str = Field(default="", max_length=10)
    kandidat: str = Field(default="", max_length=200)


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, pipe, intake, accounts, backups = ctx.store, ctx.pipe, ctx.intake, ctx.accounts, ctx.backups
    probe = {"at": 0.0, "rows": []}

    def st(name: str):
        return getattr(ctx.app.state, name)

    def need_pid(request: Request, what: str = "Папка-приёмник, интервал обхода и автозапуск") -> int:
        pid = ctx.project(request)
        if not pid:
            raise HTTPException(400, f"{what} — у каждого проекта свои: выберите проект вверху левой панели")
        return pid

    def check_password(u: dict, password: str) -> None:
        from .bezopasnost import verify_password
        supers = store.q("SELECT * FROM accounts WHERE role='super_admin' AND COALESCE(active,1)=1 AND "
                         "COALESCE(password_hash,'')!=''")
        if not supers:
            raise HTTPException(400, "Сначала задайте пароль суперадминистратору: «Команда» → «Выдать доступ» или "
                                     "python -m meetflow set-password.")
        mine = store.get("accounts", u["id"]) or {}
        if mine.get("password_hash"):
            if not verify_password(password or "", mine["password_hash"]):
                raise HTTPException(403, "Пароль указан неверно")
            return
        if not any(verify_password(password or "", s["password_hash"]) for s in supers):
            raise HTTPException(403, "Пароль указан неверно — нужен пароль суперадминистратора")

    # ------------------------------------------------------------------ системные сообщения
    def msg_out(c: dict) -> dict:
        p = loads(c.get("payload"), {})
        message = p.get("message") or p.get("detail") or p.get("why") or c.get("title") or ""
        err = p.get("error") or p.get("traceback") or ""
        extra = "; ".join(f"{k}: {v}" for k, v in p.items() if k not in ("message", "detail", "why", "source", "error",
                                                                        "traceback") and v not in (None, "", [], {}))
        return {"id": c["id"], "created_at": iso_dt(c.get("created_at")), "source": p.get("source") or "system_messages",
                "context": c.get("title") or "", "message": message + (f"\n{extra}" if extra else ""),
                "traceback": str(err) if err else "", "resolved": c.get("status") != "open"}

    @r.get("/project-status/errors")
    def errors(request: Request, with_total: bool = False, all_period: bool = False, before: str | None = None,
               before_id: int | None = None):
        ctx.need_super(request)
        try:
            st("mf_tech_cleanup")()
        except Exception:  # noqa: BLE001
            pass
        edge = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        where, args = "kind=? AND status='open'", [TECH]
        if not all_period:
            where += " AND created_at>=?"
            args.append(edge)
        total = store.q(f"SELECT COUNT(*) AS n FROM cards WHERE {where}", tuple(args))[0]["n"]
        if before:
            where += " AND (created_at<? OR (created_at=? AND id<?))"
            args += [before, before, before_id or 0]
        rows = store.q(f"SELECT * FROM cards WHERE {where} ORDER BY created_at DESC, id DESC LIMIT 50", tuple(args))
        items = [msg_out(c) for c in rows]
        return {"items": items, "total": total} if with_total else items

    @r.get("/project-status/errors/count")
    def errors_count(request: Request):
        ctx.need_super(request)
        return {"count": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind=? AND status='open'", (TECH,))[0]["n"]}

    @r.post("/project-status/errors/{cid}/resolve", status_code=204)
    def resolve_error(cid: int, request: Request):
        u = ctx.need_super(request)
        c = store.get("cards", cid)
        if not c or c["kind"] != TECH:
            raise HTTPException(404, "Сообщение не найдено")
        store.update("cards", cid, status="accepted", resolution=f"закрыто: {ctx.name(u)}", resolved_at=now())
        return Response(status_code=204)

    @r.post("/project-status/errors/delete-all")
    def delete_all(payload: ConfirmIn, request: Request):
        u = ctx.need_super(request)
        if not payload.confirm:
            raise HTTPException(400, "Удаление — только с подтверждением")
        rows = store.q("SELECT id FROM cards WHERE kind=?", (TECH,))
        for x in rows:
            store.delete("cards", x["id"])
        ctx.sys_msg("Удалены все технические сообщения", f"Удалил: {ctx.name(u)}. Удалено: {len(rows)}.", "system_messages")
        return {"count": len(rows)}

    # ------------------------------------------------------------------ ожидает ввода
    def awaiting() -> dict:
        try:
            groups = st("mf_awaiting")()
        except Exception:  # noqa: BLE001
            groups = []
        out = []
        for g in groups:
            if not g.get("count"):
                continue
            link = {"#cards": "#razbor", "#team": "#team"}.get(g.get("link") or "", g.get("link") or "#razbor")
            out.append({"title": g.get("title") or "", "count": g.get("count") or 0, "oldest": g.get("oldest") or "",
                        "what": g.get("need") or "", "consequence": g.get("if_not") or "", "where": link,
                        "where_text": {"#razbor": "«Разбор»", "#team": "«Команда»"}.get(link, "открыть"),
                        "details": g.get("details") or [], "examples": g.get("examples") or []})
        uq = store.q("SELECT COUNT(*) AS n FROM tasks WHERE status='active' AND COALESCE(doubt_reason,'')!=''")[0]["n"]
        return {"total": sum(g["count"] for g in out), "groups": out, "under_question": uq,
                "note": "Что система ждёт от человека — читается при открытии, ничего не меняет."}

    @r.get("/project-status/awaiting-input")
    def awaiting_input(request: Request):
        ctx.need_super(request)
        return awaiting()

    # ------------------------------------------------------------------ мониторинг
    def services(request: Request) -> list[dict]:
        rows = []
        try:
            raw = st("mf_services")()
        except Exception as e:  # noqa: BLE001
            raw = [{"name": "Службы", "state": "нет", "detail": type(e).__name__}]
        pid = ctx.project(request)
        pname = (store.get("projects", pid) or {}).get("name") if pid else None
        for x in raw:
            if pname and x["name"].startswith("Папка-приёмник · ") and not x["name"].endswith(pname):
                continue
            ok = {"живо": True, "нет": False}.get(x.get("state"))
            rows.append({"name": x["name"], "ok": ok, "detail": x.get("detail") or "", "checking": False})
        return rows

    def llm_cost() -> dict:
        try:
            from ...connectors.shared import llm_cost as lc
            rows = lc.строки_журнала(pipe.journal.path) if pipe.journal.path else []
            out = lc.сводка(rows, datetime.now(timezone.utc).replace(tzinfo=None), время_utc=False)
            try:
                from ...connectors.llm_routes import provider_limits
                out["providers"] = provider_limits(pipe.journal.path)
            except Exception:  # noqa: BLE001
                out["providers"] = []
            return out
        except Exception:  # noqa: BLE001 — сводка не критична
            return {}

    def journal_rows(days: int) -> list[dict]:
        edge = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        rows = []
        p = pipe.journal.path
        if p and Path(p).exists():
            for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines()[-20000:]:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if str(x.get("ts") or "") >= edge:
                    rows.append(x)
        return rows

    def usage(days: int = 7) -> dict:
        rows = [x for x in journal_rows(days) if x.get("purpose") not in ("retry",)]
        calls = [x for x in rows if x.get("model")]
        runs = len({(x.get("meeting_id"), (x.get("ts") or "")[:10]) for x in calls})
        by_day: dict[str, dict] = {}
        by_purpose: dict[str, dict] = {}
        for x in calls:
            d = (x.get("ts") or "")[:10]
            b = by_day.setdefault(d, {"day": d, "cost_usd": 0.0, "runs": set(), "calls": 0})
            b["cost_usd"] += float(x.get("cost_usd") or 0)
            b["calls"] += 1
            b["runs"].add(x.get("meeting_id"))
            p = by_purpose.setdefault(x.get("purpose") or "unknown", {"cost_usd": 0.0, "calls": 0})
            p["cost_usd"] += float(x.get("cost_usd") or 0)
            p["calls"] += 1
        total = sum(float(x.get("cost_usd") or 0) for x in calls)
        return {"days": days, "total_calls": len(calls), "total_cost_usd": round(total, 4), "runs": runs,
                "last_call_at": (calls[-1].get("ts") if calls else None), "cost_per_run_usd": round(total / runs, 4) if runs else None,
                "series_by_day": [{"day": b["day"], "cost_usd": round(b["cost_usd"], 4), "runs": len(b["runs"]), "calls": b["calls"]}
                                  for b in sorted(by_day.values(), key=lambda z: z["day"])],
                "by_purpose": {k: {"cost_usd": round(v["cost_usd"], 4), "calls": v["calls"]} for k, v in by_purpose.items()}}

    def dir_size(p: Path) -> int:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0

    @r.get("/project-status/monitoring")
    def monitoring(request: Request):
        ctx.need_super(request)
        pid = ctx.project(request)
        today = date.today().isoformat()
        day_ago = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        ws = intake.state(pid) if pid else {}
        wf = {"folder": ws.get("folder") or "", "folder_source": "задана на экране" if ws.get("folder") else "",
              "poll_every_sec": ws.get("interval") or 60, "poll_every_source": {"задана на экране": "задано на мониторинге",
                                                                               "по умолчанию": "по умолчанию"}.get(
                  ws.get("interval_source") or "", "переменная окружения" if "переменн" in (ws.get("interval_source") or "") else "по умолчанию"),
              "poll_every_var": "MEETFLOW_WATCH_INTERVAL_SEC", "poll_every_min": 10, "poll_every_max": 86400,
              "poll_every_value_setting": store.get_setting("watch_interval", pid) if pid else None,
              "poll_every_note": "" if pid else "выберите проект вверху левой панели — у каждого проекта своя папка"}
        cards_open = store.q("SELECT kind, COUNT(*) AS n FROM cards WHERE status='open' AND kind NOT IN ('technical') GROUP BY kind")
        n_open = sum(x["n"] for x in cards_open)
        from ...core import asr_journal
        try:
            recent = asr_journal.read_recent(pipe.asr_journal_path, 5)
        except Exception:  # noqa: BLE001
            recent = []
        last = []
        for x in reversed(recent or []):
            m = store.get("meetings", x.get("meeting_id") or 0) or {}
            last.append({"meeting": ru_date(m.get("date")) or "—", "lines": x.get("lines") or x.get("replicas") or 0,
                         "device": x.get("device") or "", "finished_at": x.get("at") or x.get("ts"),
                         "voice_text": x.get("voice_text") or (f"говорящих {x.get('speakers')}" if x.get("speakers") else "")})
        tasks_by_status = {x["status"]: x["n"] for x in store.q("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")}
        db_path = Path(store.path) if store.path != ":memory:" else None
        bfiles = []
        try:
            bfiles = backups.files() or []
        except Exception:  # noqa: BLE001
            bfiles = []
        roles = {x["role"]: x["n"] for x in store.q("SELECT role, COUNT(*) AS n FROM accounts WHERE COALESCE(active,1)=1 GROUP BY role")}
        vb_path = store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH") or ""
        from ...connectors.voice_base import voice_base_state
        vb = voice_base_state(vb_path or None)
        protocols_14 = store.q("SELECT COUNT(*) AS n FROM meetings WHERE protocol_built_at>=?",
                               ((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S"),))[0]["n"]
        failed = store.q("SELECT COUNT(*) AS n FROM build_queue WHERE status='failed' AND finished_at>=?",
                         ((datetime.now() - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S"),))[0]["n"]
        running = store.q("SELECT meeting_date FROM build_queue WHERE status='running'")
        queued = store.q("SELECT meeting_date FROM build_queue WHERE status='queued' ORDER BY meeting_date")
        lines = [f"собирается: встреча {ru_date(x['meeting_date'])}" for x in running] + \
            ([f"в очереди: {len(queued)} — " + ", ".join(ru_date(x["meeting_date"]) for x in queued[:5])] if queued else [])
        verify = [x for x in journal_rows(14) if x.get("purpose") == "verify" and x.get("model")]
        b = ctx.theme.get("budget", {}) or {}
        ts = {}
        try:
            from ...connectors.team_shared import team_shared_state
            t0 = team_shared_state(voice_base_path=vb_path or None)
            ts = {"enabled": bool(t0.get("enabled")) and bool(store.get_setting("team_shared_param", None, True)),
                  "param": bool(store.get_setting("team_shared_param", None, True)), "env_off": t0.get("enabled") is False,
                  "file_found": bool(t0.get("ok")), "reason": "" if t0.get("ok") else (t0.get("detail") or ""), "last_error": ""}
        except Exception:  # noqa: BLE001
            ts = {}
        uq = store.q("SELECT COUNT(*) AS n FROM tasks WHERE status='active' AND COALESCE(doubt_reason,'')!=''")[0]["n"]
        return {
            "now_msk": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "services_live": services(request), "watch_folder": wf,
            "recognition": {"stages": [], "running": False, "waiting": 0, "last": last, "записи": [], "history": [],
                            "speed": [], "reference_share": {"видеокарта": 0.5}},
            "queues": {"conflicts_norm": {"open": n_open, "norm": 15, "over": n_open > 15,
                                          "by_kind": {x["kind"]: x["n"] for x in cards_open}},
                       "superadmins": roles.get("super_admin", 0),
                       "conflicts_open": n_open,
                       "conflicts_resolved_day": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind!='technical' AND resolved_at>=?",
                                                         (day_ago,))[0]["n"],
                       "system_open": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind='technical' AND status='open'")[0]["n"],
                       "system_closed_day": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind='technical' AND resolved_at>=?",
                                                    (day_ago,))[0]["n"],
                       "recordings_held": store.q("SELECT COUNT(*) AS n FROM cards WHERE status='open' AND kind IN "
                                                  "('held_recording','waiting_tools')")[0]["n"],
                       "recordings_failed": 0},
            "autorun": {"enabled": bool(store.get_setting("autorun", pid, False)) if pid else False},
            "awaiting_total": awaiting()["total"], "under_question": uq, "llm_cost": llm_cost(),
            "runs_14_days": {"days": 14, "protocols_saved": protocols_14, "verification_total": len(verify),
                             "verification_clean": 0, "last_verify_model": verify[-1].get("model") if verify else None,
                             "verify_on_draft_model": False, "last_verify_at": verify[-1].get("ts") if verify else None,
                             "generating_now": len(running), "failed": failed, "build_queue": {"строки": lines},
                             "stopped_by_limit": store.q("SELECT COUNT(*) AS n FROM cards WHERE kind='stopped_by_limit' AND created_at>=?",
                                                         ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S"),))[0]["n"],
                             "limits": f"{b.get('max_calls', '—')} вызовов · {b.get('max_cost_usd', '—')} $"},
            "last_minutes_saved_at": (store.q("SELECT MAX(protocol_built_at) AS t FROM meetings")[0]["t"]),
            "llm_usage_7_days": usage(7),
            "data_state": {"meetings": store.q("SELECT COUNT(*) AS n FROM meetings")[0]["n"],
                           "with_sources": store.q("SELECT COUNT(DISTINCT meeting_id) AS n FROM sources WHERE removed_at IS NULL")[0]["n"],
                           "with_minutes": store.q("SELECT COUNT(*) AS n FROM meetings WHERE protocol_md IS NOT NULL AND protocol_md!=''")[0]["n"],
                           "last_meeting": store.q("SELECT MAX(date) AS d FROM meetings WHERE date<=?", (today,))[0]["d"],
                           "sources_by_kind": {x["kind"]: x["n"] for x in store.q(
                               "SELECT kind, COUNT(*) AS n FROM sources WHERE removed_at IS NULL GROUP BY kind")},
                           "tasks_by_status": {"active": tasks_by_status.get("active", 0), "done": tasks_by_status.get("done", 0)},
                           "closed_by_source": {x["source"]: x["n"] for x in store.q(
                               "SELECT source, COUNT(*) AS n FROM task_history WHERE new_status='done' GROUP BY source")},
                           "team_active": store.q("SELECT COUNT(*) AS n FROM accounts WHERE COALESCE(active,1)=1")[0]["n"],
                           "team_unconfirmed": store.q("SELECT COUNT(*) AS n FROM accounts WHERE COALESCE(confirmed,1)=0")[0]["n"]},
            "knowledge_state": {"active_tasks_now": tasks_by_status.get("active", 0), "active_tasks_as_of_roadmap": None,
                                "roadmap_generated_at": None},
            "voice_directory": {"configured": bool(vb_path), "read_error": "" if vb.get("ok") or not vb_path else vb.get("detail"),
                                "confirmed_people": vb.get("people_confirmed", 0)},
            "paths": {"db": str(db_path) if db_path else ":memory:", "uploads": str((db_path.parent / "uploads") if db_path else ""),
                      "backups": str(getattr(backups, "dir", "") or ""), "journal": str(pipe.journal.path or ""),
                      "journal_bytes": Path(pipe.journal.path).stat().st_size if pipe.journal.path and Path(pipe.journal.path).exists() else 0,
                      "voice_base": vb_path, "voice_base_reason": "" if vb_path else "путь не задан"},
            "models_limits": {"max_calls": b.get("max_calls"), "max_cost_usd": b.get("max_cost_usd"),
                              "max_prompt_chars": b.get("max_prompt_chars"), "langfuse": {"enabled": False}, "roadmap": "собирается кодом"},
            "roles": roles, "server_address": os.environ.get("MEETFLOW_HOST", "127.0.0.1"),
            "disk": {"db_bytes": db_path.stat().st_size if db_path and db_path.exists() else 0,
                     "uploads_bytes": dir_size(db_path.parent / "uploads") if db_path else 0,
                     "backups_bytes": int(sum(float(f.get("size_kb") or 0) for f in bfiles) * 1024),
                     "auto_backups_count": len([f for f in bfiles if not f.get("manual")]),
                     "manual_backups_count": len([f for f in bfiles if f.get("manual")])},
            "auto_backup": {"last_at": bfiles[0].get("at") if bfiles else None, "interval_hours": getattr(backups, "hours", None),
                            "keep_last": getattr(backups, "keep", None)},
            "under_question_mark": bool(store.get_setting("show_doubt_mark", None, True)),
            "conflict_drop_unresolved_days": int(store.get_setting("card_cleanup_days", None, None)
                                                 or ctx.theme.get("operator.card_cleanup_days", 3) or 3),
            "under_question_expire_days": int(store.get_setting("card_cleanup_days", None, None)
                                              or ctx.theme.get("operator.card_cleanup_days", 3) or 3),
            "service_log_keep_days": int(store.get_setting("service_log_keep_days", None, 7) or 0),
            "team_shared": ts, "auth_required": accounts.auth_required(),
            "locked_users": store.q("SELECT COUNT(*) AS n FROM accounts WHERE locked_until>?", (now(),))[0]["n"],
            "unconfirmed_users": store.q("SELECT COUNT(*) AS n FROM accounts WHERE COALESCE(confirmed,1)=0")[0]["n"],
            "source_check": {"available": False, "threshold": 0.3, "min_stems": 30},
            "server": {"pid": os.getpid(), "started_at": STARTED, "host": socket.gethostname()},
        }

    @r.post("/project-status/monitoring/probe-now")
    def probe_now(request: Request):
        ctx.need_super(request)
        try:
            from ...connectors.llm_routes import check_all
            probe.update(at=time.time(), rows=check_all())
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "results": probe["rows"]}

    @r.post("/project-status/monitoring/backup-now")
    def backup_now(request: Request):
        u = ctx.need_super(request)
        try:
            res = backups.snapshot(manual=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Копия не снята: {type(e).__name__}") from e
        ctx.sys_msg("Копия базы снята вручную", f"Снял: {ctx.name(u)}.", "backup")
        return {"ok": True, "result": str(res) if res else ""}

    # ------------------------------------------------------------------ выключатели и сроки
    @r.get("/project-status/autorun")
    def get_autorun(request: Request):
        pid = ctx.project(request)
        return {"enabled": bool(store.get_setting("autorun", pid, False)) if pid else False}

    @r.post("/project-status/autorun")
    def set_autorun(body: Toggle, request: Request):
        u = ctx.need_super(request)
        pid = need_pid(request)
        store.set_setting("autorun", bool(body.enabled), pid, ctx.name(u))
        store.insert("decisions", project_id=pid, what="Автозапуск протокола", decision="включён" if body.enabled else "выключен",
                     why=f"кто: {ctx.name(u)}", at=now())
        return {"enabled": bool(body.enabled)}

    @r.get("/project-status/conflict-drop-days")
    def get_drop(request: Request):
        ctx.need_admin(request)
        return {"days": int(store.get_setting("card_cleanup_days", None, None) or ctx.theme.get("operator.card_cleanup_days", 3) or 3)}

    @r.post("/project-status/conflict-drop-days")
    def set_drop(body: Days, request: Request):
        u = ctx.need_super(request)
        if not (1 <= body.days <= 365):
            raise HTTPException(400, "Срок — целое число дней от 1 до 365")
        store.set_setting("card_cleanup_days", body.days, None, ctx.name(u))
        return {"days": body.days}

    @r.get("/project-status/under-question-expire")
    def uq_expire(request: Request):
        return {"days": int(store.get_setting("card_cleanup_days", None, None) or ctx.theme.get("operator.card_cleanup_days", 3) or 3)}

    @r.get("/project-status/service-log-keep")
    def get_keep(request: Request):
        ctx.need_super(request)
        return {"days": int(store.get_setting("service_log_keep_days", None, 7) or 0)}

    @r.post("/project-status/service-log-keep")
    def set_keep(body: Days, request: Request):
        u = ctx.need_super(request)
        if not (0 <= body.days <= 3650):
            raise HTTPException(400, "Срок — целое число дней от 0 до 3650")
        store.set_setting("service_log_keep_days", body.days, None, ctx.name(u))
        return {"days": body.days}

    @r.get("/project-status/team-shared")
    def get_team_shared(request: Request):
        ctx.need_super(request)
        return monitoring(request)["team_shared"]

    @r.post("/project-status/team-shared")
    def set_team_shared(body: Toggle, request: Request):
        u = ctx.need_super(request)
        store.set_setting("team_shared_param", bool(body.enabled), None, ctx.name(u))
        ctx.sys_msg(f"Общая «Команда»: {'включена' if body.enabled else 'выключена'}", f"Поменял: {ctx.name(u)}.", "settings")
        return monitoring(request)["team_shared"]

    @r.get("/project-status/shared-password")
    def get_shared(request: Request):
        ctx.need_super(request)
        rows = store.q("SELECT updated_at FROM settings WHERE key='shared_password_hash' AND project_id IS NULL")
        h = store.get_setting("shared_password_hash")
        return {"is_set": bool(h), "set_at": ru_date(rows[0]["updated_at"]) if rows and h else ""}

    @r.post("/project-status/shared-password")
    def set_shared(body: SharedPw, request: Request):
        u = ctx.need_super(request)
        from .bezopasnost import hash_password, validate_new_password
        if not body.new_password:
            raise HTTPException(400, "Введите новый общий пароль")
        if body.repeat_password and body.repeat_password != body.new_password:
            raise HTTPException(400, "Пароли не совпадают")
        problem = validate_new_password(body.new_password)
        if problem:
            raise HTTPException(400, problem)
        store.set_setting("shared_password_hash", hash_password(body.new_password), None, ctx.name(u))
        closed = 0
        for s in store.q("SELECT id FROM sessions WHERE COALESCE(via_shared,0)=1"):
            store.delete("sessions", s["id"])
            closed += 1
        ctx.sys_msg("Общий пароль участников сменён", f"Сменил: {ctx.name(u)}. Завершено сессий: {closed}.", "auth")
        return {**get_shared(request), "sessions_closed": closed}

    @r.get("/project-status/system-project")
    def get_system_project(request: Request):
        ctx.need_super(request)
        pid = need_pid(request, "Проект и варианты написания")
        p = store.get("projects", pid) or {}
        return {"name": p.get("name") or "", "aliases": "; ".join(loads(p.get("aliases"), []))}

    @r.post("/project-status/system-project")
    def set_system_project(body: SystemProjectIn, request: Request):
        u = ctx.need_super(request)
        pid = need_pid(request, "Проект и варианты написания")
        name = " ".join(body.name.split())
        if not name:
            raise HTTPException(400, "У проекта MeetFlow название обязательно")
        aliases = [a.strip() for a in body.aliases.replace("\n", ";").split(";") if a.strip()]
        store.update("projects", pid, name=name, aliases=json.dumps(aliases, ensure_ascii=False))
        ctx.sys_msg(f"Проект: {name}", f"Поменял: {ctx.name(u)}. Вариантов написания: {len(aliases)}.", "settings")
        return {"name": name, "aliases": "; ".join(aliases)}

    # Подпроекты карточки «Проект системы» — те же записи справочника проектов (`projects.parent_id`, ЛМ 6c6933f), что на
    # «Проектах»: строка списка — подпроект выбранного проекта (при выбранном подпроекте — его надпроекта верхнего уровня).
    def root_pid(request: Request) -> int:
        return ctx.root_of(need_pid(request, "Подпроекты"))

    @r.get("/project-status/system-subprojects")
    def get_subprojects(request: Request):
        pid = root_pid(request)
        p = store.get("projects", pid) or {}
        items = [{"id": x["id"], "name": x["name"], "aliases": "; ".join(loads(x.get("aliases"), []))}
                 for x in store.q("SELECT * FROM projects WHERE parent_id=? AND COALESCE(archived,0)=0 ORDER BY name", (pid,))]
        return {"items": items, "all": f"Весь проект {p.get('name', '')}".strip()}

    @r.post("/project-status/system-subprojects")
    def set_subprojects(body: SubprojectsIn, request: Request):
        """Список целиком: новое название — новый подпроект, убранное — в архив (записи остаются при нём, протокол и реестр
        задним числом не переписываются), вернувшееся — из архива."""
        u = ctx.need_super(request)
        pid = root_pid(request)
        key = lambda s: " ".join((s or "").lower().replace("ё", "е").split())  # noqa: E731
        want: dict = {}
        for x in body.items:
            n = " ".join(str(x.get("name") or "").split())[:200]
            if n and key(n) not in want and key(n) != key((store.get("projects", pid) or {}).get("name")):
                want[key(n)] = n
        kids = {key(x["name"]): x for x in store.q("SELECT * FROM projects WHERE parent_id=?", (pid,))}
        others = {key(x["name"]) for x in store.q("SELECT name, parent_id FROM projects WHERE COALESCE(parent_id,0)!=?", (pid,))}
        clash = [n for k, n in want.items() if k not in kids and k in others]
        if clash:
            raise HTTPException(409, f"Проект «{clash[0]}» уже есть в справочнике проектов — подпроектом его делает "
                                     "«Параметры системы» → «Проекты», поле «Надпроект».")
        for k, x in kids.items():
            if k not in want and not x.get("archived"):
                store.update("projects", x["id"], archived=1)
        for k, n in want.items():
            if k in kids:
                store.update("projects", kids[k]["id"], name=n, archived=0)
            else:
                store.insert("projects", name=n, theme=ctx.theme.id, aliases="[]", active=1, archived=0, parent_id=pid,
                             created_at=now())
        ctx.sys_msg(f"Подпроекты проекта «{(store.get('projects', pid) or {}).get('name', '')}»: {len(want)}",
                    f"Поменял: {ctx.name(u)}.", "settings")
        return get_subprojects(request)

    # ------------------------------------------------------------------ папка-приёмник проекта
    @r.post("/project-status/watch-folder")
    def watch_folder(body: WatchFolderIn, request: Request):
        u = ctx.need_super(request)
        pid = need_pid(request)
        prj = store.get("projects", pid)
        from ...core.intake import IntakeError, preview_folder, sign_folder, validate_folder
        path_text = body.path.strip().strip('"')
        off = not path_text
        path = None
        if not off:
            try:
                path = validate_folder(path_text, body.repeat_path.strip().strip('"') if body.confirm else path_text,
                                       app_dir=ctx.app_dir, sign=False)
            except IntakeError as e:
                raise HTTPException(400, str(e)) from None
            other = [x for x in store.q("SELECT project_id, value FROM settings WHERE key='watch_folder'")
                     if x["project_id"] != pid and loads(x["value"], None) == str(path)]
            if other:
                raise HTTPException(400, "Эта папка уже назначена приёмником другого проекта: у каждого проекта своя.")
        if not body.confirm:
            if off:
                return {"question": f"Выключить папку-приёмник проекта «{prj['name']}»? Сейчас: {intake.folder(pid) or 'не задана'}. "
                                    "Файлы из неё забираться не будут.", "preview": None}
            pv = preview_folder(path)
            q = f"Сделать «{path}» папкой-приёмником проекта «{prj['name']}»?"
            if pv.get("big"):
                q += f" Файлов больше {pv['big_limit']} — первый проход будет долгим и может стоить денег."
            return {"question": q, "preview": {"files_total": pv.get("files"), "will_take": pv.get("first_pass"),
                                               "examples": pv.get("examples") or []}}
        if not off and body.repeat_path.strip().strip('"') != path_text:
            raise HTTPException(400, "Путь и его повтор не совпадают — проверьте опечатку")
        check_password(u, body.current_password)
        if path is not None:
            sign_folder(path)
        intake.set_folder(pid, path, ctx.name(u))
        ctx.sys_msg(f"Папка-приёмник проекта «{prj['name']}» {'выключена' if off else 'изменена'}",
                    f"{ctx.name(u)}: {path or '—'}.", "watch_folder")
        return {"ok": True, "folder": str(path) if path else ""}

    @r.post("/project-status/watch-folder/interval")
    def watch_interval(body: IntervalIn, request: Request):
        u = ctx.need_super(request)
        pid = need_pid(request)
        store.set_setting("watch_interval", body.seconds, pid, ctx.name(u))
        return {"seconds": body.seconds}

    @r.post("/project-status/recognition/resume")
    def resume(body: ResumeIn, request: Request):
        ctx.need_super(request)
        c = store.get("cards", body.job_id)
        if not c or c["kind"] not in ("held_recording", "waiting_tools"):
            raise HTTPException(404, "Такого задания распознавания нет")
        store.update("cards", c["id"], status="accepted", resolution="возвращено в распознавание с панели «Мониторинг»",
                     resolved_at=now())
        return {"status": "возвращено", "detail": "Запись возвращена: положите её снова в папку-приёмник проекта или "
                                                  "загрузите на странице встречи"}

    # ------------------------------------------------------------------ база голосов
    @r.get("/project-status/voice-base")
    def voice_base(request: Request):
        ctx.need_super(request)
        from ...connectors.voice_base import voice_base_state
        path = store.get_setting("voice_base_path") or os.environ.get("VOICE_BASE_PATH") or ""
        vb = voice_base_state(path or None)
        if not path:
            return {"configured": False, "reason": vb.get("detail") or "путь к базе голосов не задан"}
        if not vb.get("ok"):
            return {"configured": True, "read_error": vb.get("detail") or "база не читается", "path": path}
        team = {" ".join((a["full_name"] or "").lower().replace("ё", "е").split()) for a in store.q("SELECT full_name FROM accounts")}
        people = [{"full_name": p["full_name"], "in_team": " ".join((p["full_name"] or "").lower().replace("ё", "е").split()) in team,
                   "aliases": [x for x in (p.get("aliases") or "").split(";") if x.strip()], "confirmed_at": p.get("confirmed_at")}
                  for p in vb.get("people_list") or []]
        by_project = [{"project": k, "samples": v, "records": len([x for x in vb.get("recordings") or [] if x["project"] == k]),
                       "named": 0, "linked": 0, "last_at": None} for k, v in (vb.get("by_project") or {}).items()]
        from ...core import asr_journal
        try:
            recent = asr_journal.read_recent(pipe.asr_journal_path, 1)
        except Exception:  # noqa: BLE001
            recent = []
        return {"configured": True, "path": path, "samples": vb.get("samples", 0), "claimed": 0,
                "linked": vb.get("samples_linked", 0), "people": people, "pending": [],
                "recordings": [{"project": x["project"], "ref": x["ref"], "samples": x["samples"],
                                "minutes": round((x.get("seconds") or 0) / 60, 1), "when": x.get("last")}
                               for x in vb.get("recordings") or []],
                "by_project": by_project, "contrib": {"erp_writes": True, "models_ready": True, "min_segment_sec": 5,
                                                      "off_switch": "MEETFLOW_VOICE_CONTRIB=off"},
                "lock_wait_seconds": 30, "recordings_with_fingerprints": [],
                "last_recognition": ({"done": True, **recent[-1]} if recent else None)}

    # ------------------------------------------------------------------ модели
    # роль проверяется до разбора тела запроса: чужой роли — 403, а не 422 (сторож test_stand_1510_models_super_only)
    def only_super(request: Request) -> None:
        ctx.need_super(request)
    SUPER = [Depends(only_super)]

    def lr():
        from ...connectors import llm_routes
        return llm_routes

    def routes_call(fn, *a, **kw):
        from ...connectors.base import ConnectorError
        try:
            return fn(*a, **kw)
        except (ConnectorError, FileNotFoundError) as e:
            raise HTTPException(400, str(e)) from e

    @r.get("/project-status/models", dependencies=SUPER)
    def models_panel(request: Request):
        ctx.need_super(request)
        m = lr()
        m.ensure_file()
        d = routes_call(m.panel, full_keys=True)
        try:
            d["provider_spend"] = m.provider_limits(pipe.journal.path)
        except Exception:  # noqa: BLE001
            pass
        return d

    @r.post("/project-status/models/use", dependencies=SUPER)
    def models_use(body: RouteUse, request: Request):
        u = ctx.need_super(request)
        m = lr()
        try:
            old = (json.loads(m.routes_path().read_text(encoding="utf-8")).get("roles", {}).get(body.role) or [None])[0]
        except (OSError, ValueError):
            old = None
        routes_call(m.use, body.role, body.point, by=ctx.name(u))
        if old != body.point:
            ctx.sys_msg(f"Модель роли «{m.ROLE_TITLES.get(body.role, body.role)}» сменена: {old or '—'} → {body.point}",
                        "Смена применится к следующей попытке вызова — перезапуск не нужен." + f" Переключил: {ctx.name(u)}.",
                        "models")
            running = pipe.running_meetings()
            if running and body.role in ("generate", "generator"):
                pause = float(os.environ.get("MEETFLOW_MODEL_SWITCH_PAUSE_SEC", "900"))
                for mid in running:
                    ctx.app.state.queue_rebuild(mid, pause)
        return m.panel(full_keys=True)

    @r.post("/project-status/models/check", dependencies=SUPER)
    def models_check(request: Request):
        ctx.need_super(request)
        return {"results": routes_call(lr().check_all)}

    @r.post("/project-status/models/endpoint", dependencies=SUPER)
    def models_save(body: RoutePoint, request: Request):
        u = ctx.need_super(request)
        routes_call(lr().save_point, body.name, body.fields, by=ctx.name(u), old_name=body.old_name,
                    key_value=body.key_value or None)
        return lr().panel(full_keys=True)

    @r.post("/project-status/models/endpoint/delete", dependencies=SUPER)
    def models_delete(body: RoutePoint, request: Request):
        u = ctx.need_super(request)
        routes_call(lr().delete_point, body.name, by=ctx.name(u))
        return lr().panel(full_keys=True)

    @r.post("/project-status/models/endpoint/test", dependencies=SUPER)
    def models_test(body: RoutePoint, request: Request):
        ctx.need_super(request)
        ok, detail = routes_call(lr().test_point, body.fields, body.key_value, body.old_name or body.name)
        return {"ok": ok, "detail": detail}

    @r.post("/project-status/models/endpoint/key", dependencies=SUPER)
    def models_key(body: RoutePoint, request: Request):
        u = ctx.need_super(request)
        routes_call(lr().set_point_key, body.name, body.value or body.key_value, by=ctx.name(u))
        return lr().panel(full_keys=True)

    @r.post("/project-status/models/endpoint/key/delete", dependencies=SUPER)
    def models_key_delete(body: RoutePoint, request: Request):
        u = ctx.need_super(request)
        routes_call(lr().delete_point_key, body.name, by=ctx.name(u))
        return lr().panel(full_keys=True)

    @r.post("/project-status/models/role", dependencies=SUPER)
    def models_role(body: RouteRole, request: Request):
        u = ctx.need_super(request)
        fn = {"add": lr().add_to_role, "remove": lr().remove_from_role}.get(body.action)
        if fn is None:
            raise HTTPException(400, "action — add или remove")
        routes_call(fn, body.role, body.point, by=ctx.name(u))
        return lr().panel(full_keys=True)

    @r.post("/project-status/models/rollback", dependencies=SUPER)
    def models_rollback(request: Request):
        u = ctx.need_super(request)
        routes_call(lr().rollback, by=ctx.name(u))
        return lr().panel(full_keys=True)

    # ------------------------------------------------------------------ темы планёрок
    from ...core import topics as tp

    def topic_or_404(tid: int) -> dict:
        t = store.get("meeting_topics", tid)
        if not t:
            raise HTTPException(404, "Темы нет")
        return t

    def clean_list(xs) -> list:
        return [" ".join(str(x).split()) for x in (xs or []) if str(x).strip()]

    @r.get("/meeting-topics")
    def topics_list(request: Request):
        ctx.need_user(request)
        return {"topics": [tp.в_словарь(t) for t in store.q("SELECT * FROM meeting_topics ORDER BY id")]}

    @r.post("/meeting-topics", status_code=201)
    def topic_create(body: TopicIn, request: Request):
        u = ctx.need_super(request)
        name = " ".join((body.name or "").split())
        if not name:
            raise HTTPException(400, "Название темы не задано")
        if any(t["name"].lower() == name.lower() for t in store.q("SELECT name FROM meeting_topics")):
            raise HTTPException(409, f"Тема «{name}» уже есть")
        wd = sorted({int(d) for d in (body.weekdays or []) if 1 <= int(d) <= 7})
        tid = store.insert("meeting_topics", name=name, weekdays=json.dumps(wd), sections=json.dumps(clean_list(body.sections), ensure_ascii=False),
                           head_names=json.dumps(clean_list(body.head_names), ensure_ascii=False),
                           objects=json.dumps(clean_list(body.objects), ensure_ascii=False), hint=(body.hint or "").strip(),
                           carry_same_topic=int(bool(body.carry_same_topic)), is_active=1, created_at=now(), updated_by=ctx.name(u))
        return tp.в_словарь(store.get("meeting_topics", tid))

    @r.patch("/meeting-topics/{tid}")
    def topic_patch(tid: int, body: TopicIn, request: Request):
        u = ctx.need_super(request)
        topic_or_404(tid)
        vals: dict = {"updated_by": ctx.name(u)}
        data = body.model_dump(exclude_unset=True)
        if data.get("name") is not None:
            n = " ".join(data["name"].split())
            if not n:
                raise HTTPException(400, "Название темы не задано")
            vals["name"] = n
        if data.get("weekdays") is not None:
            vals["weekdays"] = json.dumps(sorted({int(d) for d in data["weekdays"] if 1 <= int(d) <= 7}))
        for k in ("sections", "head_names", "objects"):
            if data.get(k) is not None:
                vals[k] = json.dumps(clean_list(data[k]), ensure_ascii=False)
        if data.get("hint") is not None:
            vals["hint"] = data["hint"].strip()
        for k in ("carry_same_topic", "is_active"):
            if data.get(k) is not None:
                vals[k] = int(bool(data[k]))
        store.update("meeting_topics", tid, **vals)
        return tp.в_словарь(store.get("meeting_topics", tid))

    @r.get("/meeting-topics/meeting/{mid}")
    def meeting_topic(mid: int, request: Request):
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        t = tp.тема_встречи(store, m)
        source = tp.источник(store, m)
        return {"meeting_id": mid, "topic_id": t["id"] if t else None, "name": t["name"] if t else None,
                "source": source, "set_at": iso_dt(m.get("topic_set_at")), "set_by": m.get("topic_set_by") or ""}

    @r.put("/meeting-topics/meeting/{mid}")
    def set_meeting_topic(mid: int, body: MeetingTopicIn, request: Request):
        u = ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        name = ""
        if body.topic_id is not None:
            t = topic_or_404(body.topic_id)
            if not t.get("is_active", 1):
                raise HTTPException(400, "Тема выключена — выберите действующую")
            name = t["name"]
        store.update("meetings", mid, topic_id=body.topic_id, topic=name, topic_source=tp.ВРУЧНУЮ, topic_set_at=now(),
                     topic_set_by=ctx.name(u))
        return meeting_topic(mid, request)

    # ------------------------------------------------------------------ словарь распознавания
    # Те же выключатели и те же модули, что читают распознавание и сборка (core/slovar_whisper.py,
    # core/iskazheniya_nazvaniy.py): экран показывает словарь, который уходит в распознавание, и действующее окно правила
    REC = {"asr_vocab": ("MEETFLOW_ASR_VOCAB", "Словарь проектов в подсказке распознавания"),
           "project_only_heard": ("MEETFLOW_PROJECT_ONLY_HEARD", "Проект только при прозвучавшем названии")}

    def rec_state(project_id: int | None = None) -> dict:
        from ...core import iskazheniya_nazvaniy as iz
        from ...core import slovar_whisper
        out = {}
        for k, (env, _title) in REC.items():
            out[k] = {"enabled": iz.включено(store, k, env), "setting": iz.настройка(store, k),
                      "env": (os.environ.get(env) or "").strip().lower() in iz._ДА, "env_name": env}
        # бюджет — весь предел Whisper, как ERP: распознавание MeetFlow прежней подсказки не имеет, словарь занимает все 223
        словарь = slovar_whisper.собрать(store, project_id, slovar_whisper.ЛИМИТ_ТОКЕНОВ)
        out["asr_vocab"].update(preview=словарь, tokens=slovar_whisper.токенов(словарь), limit=slovar_whisper.ЛИМИТ_ТОКЕНОВ)
        out["project_only_heard"]["window"] = iz.ОКНО_СТРОК
        return out

    @r.get("/recognition-settings")
    def rec_get(request: Request):
        ctx.need_super(request)
        return rec_state(ctx.project(request))

    @r.put("/recognition-settings")
    def rec_put(body: RecSettingIn, request: Request):
        u = ctx.need_super(request)
        if body.key not in REC:
            raise HTTPException(400, "Неизвестная настройка")
        store.set_setting(f"rec:{body.key}", body.enabled, None, ctx.name(u))
        ctx.sys_msg(f"{REC[body.key][1]}: {'включено' if body.enabled else 'выключено' if body.enabled is False else 'по переменной'}",
                    f"Поменял: {ctx.name(u)}.", "settings")
        return rec_state(ctx.project(request))

    # ------------------------------------------------------------------ разбор голосов
    def base() -> str:
        b = st("mf_voice_base")()
        if not b:
            raise HTTPException(409, "Общая база голосов не подключена: путь к ней не задан.")
        return b

    @r.get("/voice/review")
    def voice_queue(request: Request):
        ctx.need_super(request)
        from ...core import voice_review, voice_rule
        b = st("mf_voice_base")()
        if not b:
            return {"configured": False, "reason": "путь к общей базе голосов не задан", "gruppy": [], "otpechatkov": 0,
                    "klasterov": 0, "s_otryvkom": 0}
        try:
            d = voice_review.ochered(b)
        except (voice_rule.BazaNeTa, voice_review.RazborNeTot, OSError) as e:
            return {"configured": False, "reason": str(e), "gruppy": [], "otpechatkov": 0, "klasterov": 0, "s_otryvkom": 0}
        komanda = st("mf_komanda")()
        vk = st("mf_v_komande")
        meetings = {str(m["id"]): m["date"] for m in store.q("SELECT id, date FROM meetings")}

        def vstrecha(k: dict) -> str:
            if (k.get("project") or "") != "meetflow":
                return f"{ {'planerka': 'Планёрка', 'erp': 'ERP'}.get(k.get('project'), k.get('project'))}, встреча {k.get('data')}".strip()
            d0 = meetings.get(str(k.get("meeting_key") or ""))
            return f"MeetFlow, встреча {ru_date(d0)}" if d0 else f"MeetFlow, запись {k.get('data')}"
        for g in d.get("gruppy") or []:
            g["v_komande"] = bool(g.get("imya")) and vk(g["imya"], komanda) is not None
            for k in g.get("klastery") or []:
                k["vstrecha"] = vstrecha(k)
                k.update(akkaunt_vks="", akkaunt_v_komande="", akkaunt_obshchiy="", akkaunt_golosov=0)
                k.setdefault("metki_vks", [])
                k.setdefault("podskazki", [])
                k["kandidat_v_komande"] = (vk(k["kandidat"], komanda) or "") if k.get("kandidat") else ""
                k["vtoroy_v_komande"] = (vk(k["second"], komanda) or "") if k.get("second") else ""
        for k in (d.get("po_pravilu") or {}).get("klastery", []) + (d.get("reshennye") or {}).get("klastery", []):
            k["vstrecha"] = vstrecha(k)
        return {**d, "configured": True, "komanda": komanda, "reshenia": voice_review.RESHENIYA}

    @r.get("/voice/review/clip/{sid}")
    def voice_clip(sid: int, request: Request):
        ctx.need_super(request)
        from ...core import voice_review
        b = base()
        path = voice_review.put_otryvka(b, sid)
        if not path or not Path(path).is_file():
            raise HTTPException(404, voice_review.pochemu_net_otryvka(b, sid) or "Отрывка нет")
        return Response(Path(path).read_bytes(), media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @r.post("/voice/review/decision")
    def voice_decision(body: VoiceDecision, request: Request):
        u = ctx.need_super(request)
        from ...core import voice_review, voice_rule
        name = " ".join((body.imya or "").split())
        if body.vybran not in ("", "pervyy", "vtoroy"):
            raise HTTPException(400, f"Выбор кандидата «{body.vybran}» неизвестен: есть «pervyy» и «vtoroy».")
        if body.vybran and body.reshenie != voice_review.YES:
            raise HTTPException(400, "Выбор одного из двух кандидатов — только с решением «Это он».")
        if body.reshenie in voice_review.V_ETALON:
            found = st("mf_v_komande")(name)
            if len(name.split()) < 2 or found is None:
                raise HTTPException(400, f"«{name or 'пусто'}» — нет в «Команде» полным ФИО. Выберите человека из «Команды»: "
                                         "одно имя или тёзка не подставляются.")
            if body.reshenie == voice_review.OTHER:
                name = found
        try:
            res = voice_review.primenit(base(), body.ids, body.reshenie, name, kto=ctx.name(u))
        except voice_review.RazborNeTot as e:
            raise HTTPException(400, str(e)) from e
        except voice_rule.BazaNeTa as e:
            raise HTTPException(409, str(e)) from e
        return {"razobrano": res.get("razobrano", 0), "otryvkov_udaleno": res.get("otryvkov_udaleno", 0),
                "kartochek_zakryto": 0, "vybran": body.vybran}

    @r.post("/voice/review/ne-po-pravilu")
    def voice_not_rule(body: VoiceIds, request: Request):
        u = ctx.need_super(request)
        from ...core import voice_review, voice_rule
        try:
            res = voice_review.ne_po_pravilu(base(), body.ids, kto=ctx.name(u))
        except voice_review.RazborNeTot as e:
            raise HTTPException(400, str(e)) from e
        except voice_rule.BazaNeTa as e:
            raise HTTPException(409, str(e)) from e
        return {"vozvrasheno": res.get("vozvrasheno", 0)}
