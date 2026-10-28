# -*- coding: utf-8 -*-
"""Встречи — адреса ERP `/meetings/*` (перенос 27.10.2026, экраны 1 в 1): список «Встречи по проекту», «Подготовка
встречи» (одна встреча на дату, вторая — по подтверждению, ключ повтора), удаление пустой, отмена с планом, «Свести в
одну» и «Вернуть на новую дату», источники и материалы, сборка плана и протокола через очередь MeetFlow, путь встречи.

Источник протокола и материал плана в MeetFlow — одна таблица `sources`; материал помечен в `meta.material`. Протокол и
план хранятся у встречи (`protocol_md`, `plan_md`), версии протокола — `protocol_versions`.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.store import now
from .obshchee import Ctx, iso_dt, loads, ru_date, to_date, today_iso

AUTO_LABEL = "дата ориентировочная"
ARCHIVE_CUTOFF_DAYS = 28
MAX_MATERIALS = 20
ЕСЛИ_НЕТ_МАТЕРИАЛОВ = ("Собирать протокол не из чего: к встрече не приложены ни расшифровка, ни запись, ни заметки. "
                       "Добавьте файл в «Источниках» подготовки встречи — протокол соберётся сам.")
ПЕРЕСБОРКА_ЗАПРЕЩЕНА = ("Протокол правил человек — моделью он не пересобирается: правки человека сохраняются. Текст "
                        "поправьте на полотне («Правка»).")
MEDIA_EXT = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".ogg", ".flac")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class MeetingLabelIn(BaseModel):
    """Название встречи (Доработка 2, 28.10.2026): пусто — без названия, встреча видна по дате."""
    label: str | None = Field(default=None, max_length=200)


class MoveProjectIn(BaseModel):
    """«Перенести встречу в другой проект» (27.10.2026): номер проекта и пересобрать ли протокол после переноса."""
    project_id: int
    rebuild: bool = True


class InModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _date_in(v):
    if v is None or v == "":
        raise ValueError("Укажите дату встречи: ДД.ММ.ГГГГ")
    d = to_date(v)
    if d is None:
        raise ValueError("Укажите дату встречи: ДД.ММ.ГГГГ")
    if not (date(2020, 1, 1) <= d <= date(2099, 12, 31)):
        raise ValueError("Дата встречи — с 2020 по 2099 год")
    return d


class MeetingCreate(InModel):
    date: date
    label: str | None = Field(default=None, max_length=200)
    second_same_day: bool = False
    request_key: str | None = Field(default=None, max_length=80)

    @field_validator("date", mode="before")
    @classmethod
    def _d(cls, v):
        return _date_in(v)


class MeetingDateIn(InModel):
    date: date

    @field_validator("date", mode="before")
    @classmethod
    def _d(cls, v):
        return _date_in(v)


class MeetingSubprojectIn(InModel):
    subproject: str | None = Field(default=None, max_length=200)


class MeetingLeaderIn(InModel):
    user_id: int | None


class MeetingMoveIn(InModel):
    to: int = Field(ge=1)


class MeetingUnmergeIn(InModel):
    from_id: int = Field(ge=1)
    date: date

    @field_validator("date", mode="before")
    @classmethod
    def _d(cls, v):
        return _date_in(v)


class TextSourceIn(InModel):
    text: str = Field(min_length=20, max_length=2_000_000)
    kind: str = "other"

    @field_validator("text")
    @classmethod
    def _t(cls, v: str) -> str:
        if len(re.sub(r"[\u0000-\u001f​-‏﻿]", "", v).strip()) < 20:
            raise ValueError("Текст заметок слишком короткий — вставьте не меньше 20 значащих символов")
        return v


class PointEditIn(InModel):
    find: str = Field(min_length=1, max_length=20000)
    replace: str = Field(max_length=20000)
    is_processing_error_fix: bool = True


class CorrectionIn(InModel):
    request: str = Field(min_length=3, max_length=4000)


def is_material(src: dict) -> bool:
    return bool(loads(src.get("meta"), {}).get("material"))


def mount(r: APIRouter, ctx: Ctx) -> None:
    store, pipe, queue = ctx.store, ctx.pipe, ctx.queue
    create_lock = threading.Lock()
    plan_jobs: dict[int, dict] = {}          # сборка плана идёт в фоне: {mid: {"since", "error"}}
    rec_jobs: dict[int, dict] = {}           # распознавание записи, загруженной с экрана: {source_name: …}
    ctx.plan_jobs = plan_jobs

    # ------------------------------------------------------------------ сведения о встрече
    def live(rows: list[dict]) -> list[dict]:
        return [m for m in rows if (m.get("status") or "scheduled") != "cancelled" and not m.get("deleted_at")]

    def sources_of(mid: int, material: bool | None = None) -> list[dict]:
        rows = store.q("SELECT * FROM sources WHERE meeting_id=? AND removed_at IS NULL ORDER BY id", (mid,))
        if material is None:
            return rows
        return [s for s in rows if is_material(s) == material]

    def text_sources(mid: int) -> list[dict]:
        return [s for s in sources_of(mid, False) if (s.get("text") or "").strip()]

    def building(mid: int) -> dict:
        st = queue.state(mid)
        pj = plan_jobs.get(mid)
        if pj and pj.get("running"):
            return {"running": True, "since": pj.get("since"), "queued": False, "place": None, "kind": "plan"}
        if st.get("status") == "running":
            return {"running": True, "since": st.get("started_at"), "queued": False, "place": None, "kind": "minutes"}
        if st.get("status") == "queued":
            return {"running": False, "since": None, "queued": True, "place": st.get("position"), "kind": "minutes",
                    "not_before": st.get("not_before")}
        return {"running": False, "since": None, "queued": False, "place": None, "kind": None}

    def last_build(mid: int) -> dict | None:
        rows = store.q("SELECT * FROM build_queue WHERE meeting_id=? ORDER BY id DESC LIMIT 1", (mid,))
        return rows[0] if rows else None

    def state_line(m: dict) -> str | None:
        """Одной строкой для списка: из чего протокол можно собрать и что мешает (как `состояние_протокола` ERP)."""
        if (m.get("status") or "") == "cancelled":
            return "встреча отменена"
        if m.get("protocol_md"):
            return None
        b = building(m["id"])
        if b["running"] and b["kind"] == "minutes":
            return "идёт сборка протокола"
        if b["queued"]:
            return f"в очереди сборок, место {b['place']}"
        srcs = text_sources(m["id"])
        if srcs:
            lb = last_build(m["id"])
            if lb and lb.get("status") == "failed":
                return "сборка протокола не удалась — соберите заново кнопкой «Создать протокол»"
            if any(s.get("local_asr") for s in srcs):
                return "расшифровка записи, сделанная системой — можно собирать"
            if any(s.get("kind") == "transcript" for s in srcs):
                return "приложенная расшифровка (файл) — можно собирать"
            return "заметки секретаря — можно собирать"
        held = store.q("SELECT id FROM cards WHERE meeting_id=? AND status='open' AND kind IN ('held_recording','waiting_tools')",
                       (m["id"],))
        if held:
            return "распознавание записи остановлено — см. «Конфликты»"
        if any(j.get("meeting_id") == m["id"] for j in rec_jobs.values()):
            return "запись распознаётся"
        return "ждём расшифровку: приложите запись или текст"

    def tasks_count(mid: int) -> int:
        return len(store.q("SELECT id FROM tasks WHERE source_meeting_id=? AND status!='dropped'", (mid,)))

    def meeting_out(m: dict, full: bool = True) -> dict:
        has_min = bool(m.get("protocol_md"))
        b = building(m["id"]) if full else {"running": False}
        out = {"id": m["id"], "date": (m.get("date") or "")[:10], "label": m.get("label") or None,
               "status": m.get("status") or "scheduled", "has_minutes": has_min,
               "second_same_day": bool(m.get("second_same_day")), "created_at": iso_dt(m.get("created_at")) or "",
               "processed_at": iso_dt(m.get("protocol_built_at")), "model_used": None,
               "verification_verdict_clean": None, "leader_user_id": m.get("leader_user_id"),
               "leader_speaker": m.get("leader_speaker") or (m.get("leader") if not m.get("leader_user_id") else None),
               "leader_confidence": 100 if m.get("leader_source") == "вручную" else None,
               "leader_source": m.get("leader_source") or ("запись" if m.get("leader") else None),
               "leader_note": m.get("leader_note"), "project_id": m.get("project_id")}
        if full:
            out.update({"состояние_протокола": state_line(m), "tasks_count": tasks_count(m["id"]), "draft_pending": False,
                        "building": bool(b["running"]), "предложена_пересборка": False,
                        "has_plan": bool(m.get("plan_md")), "plan_generated_at": iso_dt(m.get("plan_built_at")),
                        "materials_count": len(sources_of(m["id"], True))})
        # проект и подпроект встречи (справочник проектов, `projects.parent_id`): подпись «Проект – Подпроект»
        root_name, sub_name = ctx.project_names(m.get("project_id"))
        out.update(project_name=root_name, subproject=sub_name or None, project_label=ctx.project_label(m.get("project_id")),
                   project_root_id=ctx.root_of(m.get("project_id")),
                   # как встреча попала в проект из папки-приёмника и лежит ли в «Общих встречах» (Доработка 2, 28.10.2026)
                   project_how=m.get("project_how") or None,
                   general=bool((store.get("projects", m.get("project_id") or 0) or {}).get("general")))
        return out

    def describe(m: dict) -> dict:
        return {"id": m["id"], "date": (m.get("date") or "")[:10], "label": m.get("label"),
                "auto": m.get("label") == AUTO_LABEL, "has_plan": bool(m.get("plan_md")),
                "plan_generated_at": iso_dt(m.get("plan_built_at")), "has_minutes": bool(m.get("protocol_md")),
                "materials": len(sources_of(m["id"], True))}

    def refuse(code: int, detail: str, other: dict | None = None) -> JSONResponse:
        body = {"detail": detail}
        if other is not None:
            body["existing_id"] = other["id"]
            body["existing"] = describe(other)
        return JSONResponse(status_code=code, content=body)

    def on_date(pid: int, day: str, exclude: int | None = None) -> list[dict]:
        return [m for m in live(store.q("SELECT * FROM meetings WHERE project_id=? AND date=? ORDER BY id", (pid, day)))
                if m["id"] != exclude]

    def check_not_cancelled(m: dict) -> None:
        if (m.get("status") or "") == "cancelled":
            raise HTTPException(400, "Встреча отменена — материалы и сборки ведут у действующей встречи на эту дату")

    def archived(m: dict) -> bool:
        d = to_date(m.get("date"))
        return bool(d and d < date.today() - timedelta(days=ARCHIVE_CUTOFF_DAYS))

    def check_not_archived_settled(m: dict) -> None:
        if m.get("protocol_md") and archived(m):
            raise HTTPException(400, "Встреча в архиве — менять её уже нельзя")

    # ------------------------------------------------------------------ список, создание
    @r.get("/meetings")
    def list_meetings(request: Request):
        extra, args = ctx.scope_sql(request)
        rows = live(store.q("SELECT * FROM meetings WHERE 1=1" + extra + " ORDER BY date DESC, id DESC", args))
        return [meeting_out(m) for m in rows]

    @r.post("/meetings", status_code=201)
    def create_meeting(payload: MeetingCreate, request: Request):
        ctx.need_user(request)
        pid = ctx.project_for_create(request)
        day = payload.date.isoformat()
        with create_lock:
            if payload.request_key:
                same = store.q("SELECT * FROM meetings WHERE request_key=? AND project_id=?", (payload.request_key, pid))
                if same:
                    return meeting_out(same[0])
            busy = on_date(pid, day)
            if busy and not payload.second_same_day:
                m0 = busy[0]
                plan = "план собран" if m0.get("plan_md") else "плана пока нет"
                name = f" «{m0['label']}»" if m0.get("label") else ""
                return refuse(409, f"На {ru_date(day)} уже есть встреча №{m0['id']}{name} — {plan}. Откройте её. Вторая "
                                   "встреча в тот же день — только с отметкой «Вторая встреча в этот день».", m0)
            mid = store.insert("meetings", project_id=pid, date=day, label=(payload.label or "").strip() or None,
                               status="scheduled", second_same_day=int(bool(busy) and payload.second_same_day),
                               request_key=payload.request_key, created_at=now())
        return JSONResponse(status_code=201, content=meeting_out(store.get("meetings", mid)))

    @r.get("/meetings/date-check")
    def date_check(request: Request, date: str | None = None):  # noqa: A002 — имя параметра как у ERP
        try:
            day = _date_in(date).isoformat()
        except ValueError:
            raise HTTPException(400, "Укажите дату встречи: ДД.ММ.ГГГГ") from None
        pid = ctx.project(request)
        those = on_date(pid, day) if pid else live(store.q("SELECT * FROM meetings WHERE date=?", (day,)))
        return {"date": day, "busy": bool(those), "meetings": [describe(m) for m in those]}

    @r.post("/meetings/{mid}/confirm-date")
    def confirm_date(mid: int, request: Request):
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        if m.get("label") == AUTO_LABEL:
            store.update("meetings", mid, label=None)
        return meeting_out(store.get("meetings", mid))

    # ------------------------------------------------------------------ удаление, отмена, сводка
    def blockers(m: dict, skip: tuple[str, ...] = ()) -> list[tuple[str, int]]:
        mid = m["id"]
        out = []
        if m.get("protocol_md"):
            out.append(("протокол", 1))
        n = tasks_count(mid)
        if n:
            out.append(("задачи", n))
        src = len(sources_of(mid, False))
        if src:
            out.append(("запись или источники протокола", src))
        mats = len(sources_of(mid, True))
        if mats and "материалы" not in skip:
            out.append(("материалы", mats))
        if m.get("plan_md"):
            out.append(("план встречи", 1))
        units = len(store.q("SELECT id FROM units WHERE meeting_id=?", (mid,)))
        if units:
            out.append(("пункты встречи", units))
        return out

    def refuse_text(m: dict, bl: list[tuple[str, int]], start: str | None = None) -> str:
        has = ", ".join(f"{w} ({n})" for w, n in bl)
        head = start or f"Встречу {ru_date(m['date'])} (№{m['id']}) удалить нельзя"
        t = f"{head}: есть {has}."
        what = {w for w, _ in bl}
        if "задачи" in what:
            t += " Задачи не удаляются, поэтому встреча с задачами остаётся."
        if "материалы" in what:
            t += " Сначала перенесите материалы — «Свести в одну»."
        return t

    def can_cancel(bl) -> bool:
        return bool(bl) and all(w == "план встречи" for w, _ in bl)

    def cancel_text(m: dict) -> str:
        return (f"Встречу {ru_date(m['date'])} удалить нельзя — у неё собран план. Отменить встречу? План сохранится, "
                "встреча уйдёт из списков")

    @r.get("/meetings/{mid}/delete-check")
    def delete_check(mid: int):
        m = ctx.meeting_or_404(mid)
        bl = blockers(m)
        cc = can_cancel(bl)
        n = len(open_tasks(mid))
        return {"can_delete": not bl, "detail": refuse_text(m, bl) if bl else None,
                "blockers": [{"what": w, "count": k} for w, k in bl], "can_cancel": cc,
                "cancel_text": cancel_text(m) if cc else None,
                # Доработка 2 (28.10.2026): встречу с протоколом и задачами можно удалить — задачи снимаются, отмена сразу
                "can_delete_with_tasks": bool(bl),
                "with_tasks_text": (f"Удалить встречу {ru_date(m['date'])}? "
                                    + (f"Её задачи ({n}) будут сняты с причиной «встреча удалена». " if n else "")
                                    + "Отменить удаление можно сразу после него.") if bl else None}

    def open_tasks(mid: int) -> list[dict]:
        return store.q("SELECT id, status FROM tasks WHERE source_meeting_id=? AND status NOT IN ('dropped','done')",
                       (mid,))

    def soft_delete(m: dict, who: str) -> dict:
        """Удаление встречи с содержимым (Доработка 2, 28.10.2026): встреча скрывается отовсюду, её действующие задачи —
        «снято» с причиной «встреча удалена», открытые карточки закрываются. Что было, хранится у встречи: отмена
        возвращает задачам прежний статус и открывает карточки. Протокол, источники и история не стираются."""
        mid = m["id"]
        задачи = open_tasks(mid)
        карточки = store.q("SELECT id FROM cards WHERE meeting_id=? AND status='open'", (mid,))
        with store.tx():
            for t in задачи:
                store.update("tasks", t["id"], status="dropped", date_closed=today_iso())
                store.insert("task_history", task_id=t["id"], old_status=t["status"], new_status="dropped",
                             source="meeting_delete", evidence_quote="встреча удалена", changed_by=who, at=now())
            for c in карточки:
                store.update("cards", c["id"], status="rejected", resolution="встреча удалена", resolved_at=now())
            for q in store.q("SELECT id FROM build_queue WHERE meeting_id=? AND status='queued'", (mid,)):
                store.delete("build_queue", q["id"])
            store.update("meetings", mid, deleted_at=now(), deleted_info=json.dumps(
                {"tasks": [[t["id"], t["status"]] for t in задачи], "cards": [c["id"] for c in карточки]}))
        ctx.sys_msg(f"Удалена встреча {ru_date(m['date'])} (№{mid})",
                    f"Удалил: {who}. Задач снято: {len(задачи)}.", "meetings")
        return {"deleted": True, "id": mid, "date": m["date"], "tasks_dropped": len(задачи), "can_undo": True}

    def _drop_meeting(m: dict, who: str) -> None:
        for s in store.q("SELECT id FROM sources WHERE meeting_id=?", (m["id"],)):
            store.delete("sources", s["id"])
        for q in store.q("SELECT id FROM build_queue WHERE meeting_id=? AND status='queued'", (m["id"],)):
            store.delete("build_queue", q["id"])
        store.delete("meetings", m["id"])
        ctx.sys_msg(f"Удалена встреча {ru_date(m['date'])} (№{m['id']})", f"Удалил: {who}.", "meetings")

    @r.delete("/meetings/{mid}")
    def delete_meeting(mid: int, request: Request, with_tasks: bool = False):
        admin = ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        bl = blockers(m)
        if bl and with_tasks:
            return soft_delete(m, ctx.name(admin))
        if bl:
            return refuse(400, refuse_text(m, bl))
        _drop_meeting(m, ctx.name(admin))
        return {"deleted": True, "id": mid, "date": m["date"]}

    @r.post("/meetings/{mid}/restore")
    def restore_meeting(mid: int, request: Request):
        """Отмена удаления (Доработка 2, 28.10.2026): задачам — прежний статус, карточкам — снова открыты."""
        admin = ctx.need_admin(request)
        m = store.get("meetings", mid)
        if not m or not m.get("deleted_at"):
            raise HTTPException(404, "Удалённой встречи с таким номером нет")
        info = loads(m.get("deleted_info"), {})
        with store.tx():
            for tid, было in info.get("tasks", []):
                t = store.get("tasks", tid)
                if t and t["status"] == "dropped":
                    store.update("tasks", tid, status=было, date_closed=None)
                    store.insert("task_history", task_id=tid, old_status="dropped", new_status=было,
                                 source="meeting_restore", evidence_quote="удаление встречи отменено",
                                 changed_by=ctx.name(admin), at=now())
            for cid in info.get("cards", []):
                store.update("cards", cid, status="open", resolution=None, resolved_at=None)
            store.update("meetings", mid, deleted_at=None, deleted_info="{}")
        ctx.sys_msg(f"Удаление встречи {ru_date(m['date'])} (№{mid}) отменено", f"{ctx.name(admin)}.", "meetings")
        return {"restored": True, "meeting": meeting_out(store.get("meetings", mid))}

    @r.patch("/meetings/{mid}/label")
    def set_label(mid: int, payload: MeetingLabelIn, request: Request):
        """Переименовать встречу (Доработка 2, 28.10.2026). Пустое название — встреча показывается по дате."""
        admin = ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        label = " ".join((payload.label or "").split()) or None
        store.update("meetings", mid, label=label)
        ctx.sys_msg("Встреча переименована", f"{ctx.name(admin)}: «{label or 'без названия'}».", "meetings")
        return meeting_out(store.get("meetings", mid))

    @r.post("/meetings/{mid}/cancel-with-plan")
    def cancel_with_plan(mid: int, request: Request):
        admin = ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        bl = blockers(m)
        if not bl:
            _drop_meeting(m, ctx.name(admin))
            return {"deleted": True, "cancelled": False, "id": mid}
        if not can_cancel(bl):
            return refuse(400, refuse_text(m, bl))
        store.update("meetings", mid, status="cancelled")
        ctx.sys_msg(f"Отменена встреча {ru_date(m['date'])} (№{mid})", f"Отменил: {ctx.name(admin)}. План сохранён.",
                    "meetings")
        return {"cancelled": True, "deleted": False, "id": mid}

    def move_materials(src_m: dict, dst_m: dict, mark_from: bool = True) -> tuple[int, int]:
        have = {s.get("digest") for s in sources_of(dst_m["id"], True) if s.get("digest")}
        moved = same = 0
        if len(sources_of(dst_m["id"], True)) + len(sources_of(src_m["id"], True)) > MAX_MATERIALS:
            raise HTTPException(400, f"У встречи получится больше {MAX_MATERIALS} материалов — удалите лишние")
        for s in sources_of(src_m["id"], True):
            if s.get("digest") and s["digest"] in have:
                store.update("sources", s["id"], removed_at=now(), removed_reason="одинаковый материал уже есть")
                same += 1
                continue
            meta = loads(s.get("meta"), {})
            if mark_from:
                meta.update(moved_from_meeting_id=src_m["id"], moved_from_date=(src_m.get("date") or "")[:10],
                            moved_at=now())
            store.update("sources", s["id"], meeting_id=dst_m["id"], meta=json.dumps(meta, ensure_ascii=False))
            moved += 1
        return moved, same

    @r.post("/meetings/{mid}/merge")
    def merge(mid: int, payload: MeetingMoveIn, request: Request):
        admin = ctx.need_admin(request)
        src_m, dst_m = ctx.meeting_or_404(mid), ctx.meeting_or_404(payload.to)
        if src_m["id"] == dst_m["id"]:
            raise HTTPException(400, "Встречу нельзя свести саму в себя")
        bl = blockers(src_m, skip=("материалы",))
        if bl and not can_cancel(bl):
            return refuse(400, refuse_text(src_m, bl, f"Свести встречу {ru_date(src_m['date'])} (№{mid}) нельзя"))
        moved, same = move_materials(src_m, dst_m)
        merged = loads(dst_m.get("merged"), [])
        merged.append({"from_id": mid, "from_date": (src_m.get("date") or "")[:10], "count": moved, "moved_at": now()})
        store.update("meetings", dst_m["id"], merged=json.dumps(merged, ensure_ascii=False))
        if bl:
            store.update("meetings", mid, status="cancelled")
            ctx.sys_msg(f"Встреча №{mid} сведена в №{dst_m['id']} и отменена", f"{ctx.name(admin)}: материалов {moved}.",
                        "meetings")
            return {"moved": moved, "skipped_same": same, "cancelled": True, "deleted": False}
        _drop_meeting(store.get("meetings", mid), ctx.name(admin))
        return {"moved": moved, "skipped_same": same, "deleted": True, "cancelled": False}

    @r.get("/meetings/{mid}/merged")
    def merged(mid: int):
        m = ctx.meeting_or_404(mid)
        out = []
        for x in loads(m.get("merged"), []):
            left = [s for s in sources_of(mid, True) if loads(s.get("meta"), {}).get("moved_from_meeting_id") == x["from_id"]]
            if left:
                out.append({**x, "count": len(left), "moved_at": iso_dt(x.get("moved_at"))})
        return out

    @r.post("/meetings/{mid}/unmerge")
    def unmerge(mid: int, payload: MeetingUnmergeIn, request: Request):
        admin = ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        day = payload.date.isoformat()
        busy = on_date(m["project_id"], day)
        if busy:
            return refuse(409, f"На {ru_date(day)} уже есть встреча №{busy[0]['id']} — встреча не заведена", busy[0])
        nid = store.insert("meetings", project_id=m["project_id"], date=day, status="scheduled", created_at=now())
        moved = 0
        for s in sources_of(mid, True):
            meta = loads(s.get("meta"), {})
            if meta.get("moved_from_meeting_id") == payload.from_id:
                for k in ("moved_from_meeting_id", "moved_from_date", "moved_at"):
                    meta.pop(k, None)
                store.update("sources", s["id"], meeting_id=nid, meta=json.dumps(meta, ensure_ascii=False))
                moved += 1
        merged_ = [x for x in loads(m.get("merged"), []) if x.get("from_id") != payload.from_id]
        store.update("meetings", mid, merged=json.dumps(merged_, ensure_ascii=False))
        ctx.sys_msg(f"Сводка возвращена на новую дату {ru_date(day)}", f"{ctx.name(admin)}: материалов {moved}.",
                    "meetings")
        return {"meeting": meeting_out(store.get("meetings", nid)), "moved": moved}

    @r.post("/meetings/{mid}/move-project")
    def move_project(mid: int, payload: MoveProjectIn, request: Request):
        """«Перенести встречу в другой проект» вместе с её задачами (27.10.2026): встреча из общей папки попала не в свой
        проект. Протокол не переписывается — после переноса сборка встаёт в очередь заново (`rebuild`)."""
        from ...core import proekt_zapisi as pz
        admin = ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        try:
            out = pz.перенести_встречу(store, mid, payload.project_id, ctx.name(admin))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        rid = pz.собрать_после_выбора(store, getattr(ctx.pipe, "queue", None), mid, ctx.name(admin)) \
            if payload.rebuild else None
        ctx.sys_msg("Встреча перенесена в другой проект",
                    f"{ctx.name(admin)}: задач {out['tasks']}" + ("; сборка поставлена в очередь" if rid else ""),
                    "meetings")
        return {**out, "queued": bool(rid), "meeting": meeting_out(store.get("meetings", mid))}

    @r.post("/meetings/{mid}/move-materials")
    def move_mats(mid: int, payload: MeetingMoveIn, request: Request):
        ctx.need_admin(request)
        moved, same = move_materials(ctx.meeting_or_404(mid), ctx.meeting_or_404(payload.to))
        return {"moved": moved, "skipped_same": same}

    @r.get("/meetings/{mid}")
    def get_meeting(mid: int):
        return meeting_out(ctx.meeting_or_404(mid))

    # ------------------------------------------------------------------ источники и материалы
    def source_status(s: dict) -> str | None:
        meta = loads(s.get("meta"), {})
        if s.get("removed_reason"):
            return s["removed_reason"]
        if s.get("local_asr"):
            m = store.get("meetings", s["meeting_id"]) or {}
            if m.get("protocol_built_at") and (s.get("created_at") or "") > m["protocol_built_at"]:
                return ("расшифровка, сделана системой из записи; Протокол собран до неё — его можно пересобрать "
                        "кнопкой «Пересобрать протокол»")
            return "расшифровка, сделана системой из записи"
        return meta.get("status")

    def src_out(s: dict) -> dict:
        return {"id": s["id"], "kind": s.get("kind") or "other", "original_filename": s.get("name") or "",
                "uploaded_at": iso_dt(s.get("created_at")), "removed_at": iso_dt(s.get("removed_at")),
                "removed_reason": s.get("removed_reason"), "status": source_status(s),
                "local_transcript": bool(s.get("local_asr"))}

    @r.get("/meetings/{mid}/sources")
    def list_sources(mid: int):
        ctx.meeting_or_404(mid)
        out = [src_out(s) for s in sources_of(mid, False)]
        for name, j in rec_jobs.items():
            if j.get("meeting_id") == mid:
                out.append({"id": 0, "kind": "recording", "original_filename": name, "uploaded_at": iso_dt(j.get("at")),
                            "removed_at": None, "removed_reason": None, "status": j.get("status"),
                            "local_transcript": False})
        return out

    def autorun_maybe(m: dict) -> tuple[bool, str]:
        from ...core.intake import автозапуск_включён
        if not автозапуск_включён(store, m["project_id"]):
            return False, "автозапуск выключен — протокол собирается кнопкой «Создать протокол»"
        if (m.get("date") or "") > today_iso():
            return False, "встреча ещё не прошла"
        if m.get("protocol_md"):
            return False, "протокол уже есть"
        queue.enqueue(m["project_id"], m["id"], "автозапуск после загрузки", by="система")
        return True, "протокол собирается автоматически"

    def recognize_in_background(m: dict, path: Path, name: str) -> None:
        rec_jobs[name] = {"meeting_id": m["id"], "status": "распознаётся сейчас", "at": now()}

        def work():
            try:
                res = pipe.ingest(m["project_id"], m["id"], name, None, path=path)
                st = res.get("status")
                if st == "ok":
                    autorun_maybe(store.get("meetings", m["id"]) or m)
                elif st == "held":
                    pass
                else:
                    pipe.cards.open(m["project_id"], "technical", f"Запись «{name}» не распознана",
                                    {"reason": res.get("reason", "")}, m["id"])
            except Exception as e:  # noqa: BLE001 — сбой распознавания не роняет сервер
                pipe.cards.open(m["project_id"], "technical", f"Запись «{name}» не распознана",
                                {"error": type(e).__name__}, m["id"])
            finally:
                rec_jobs.pop(name, None)
        threading.Thread(target=work, daemon=True).start()

    def upload_dir(mid: int) -> Path:
        base = Path(store.path).parent if store.path != ":memory:" else Path(os.environ.get("TEMP", "."))
        d = base / "uploads" / str(mid)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_material(m: dict, name: str, data: bytes, description: str | None, u: dict, text: str = "",
                      digest: str = "") -> dict:
        import hashlib
        if len(sources_of(m["id"], True)) >= MAX_MATERIALS:
            raise HTTPException(400, f"У встречи уже {MAX_MATERIALS} материалов — удалите лишние, прежде чем добавлять новые")
        dg = digest or hashlib.sha256(data).hexdigest()
        meta = {"material": True, "description": description or "", "uploaded_by_user_id": u.get("id")}
        sid = store.insert("sources", meeting_id=m["id"], name=name, kind="other", text=text, digest=dg,
                           created_at=now(), local_asr=0, meta=json.dumps(meta, ensure_ascii=False))
        return mat_out(store.get("sources", sid))

    def mat_out(s: dict) -> dict:
        meta = loads(s.get("meta"), {})
        return {"id": s["id"], "meeting_id": s["meeting_id"], "kind": "other", "original_filename": s.get("name"),
                "description": meta.get("description") or None, "added_at": iso_dt(s.get("created_at")),
                "uploaded_by_user_id": meta.get("uploaded_by_user_id"),
                "moved_from_meeting_id": meta.get("moved_from_meeting_id"), "moved_from_date": meta.get("moved_from_date")}

    def тема_из_эталона(mid: int, sid) -> None:
        """Пришёл протокол секретаря (источник «заметки») — тема планёрки по его шапке, молча; выбор человека не трогается
        (как ERP meeting_service.тема_из_эталона, Р3 24.10.2026). Сбой разбора загрузке не мешает."""
        s = store.get("sources", sid or 0) or {}
        if s.get("kind") != "notes":
            return
        try:
            from ...core import topics
            topics.применить_эталон(store, store.get("meetings", mid), s.get("text"))
        except Exception:  # noqa: BLE001
            pass

    @r.post("/meetings/{mid}/sources", status_code=201)
    async def upload_source(mid: int, request: Request, kind: str = Form("other"), file: UploadFile = File(...)):
        u = ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        check_not_archived_settled(m)
        check_not_cancelled(m)
        name = file.filename or "файл"
        limit = int(ctx.theme.get("intake.max_media_mb", 2048)) * 2 ** 20
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, "Файл слишком большой")
        if kind == "recording" or name.lower().endswith(MEDIA_EXT):
            import hashlib
            dg = hashlib.sha256(data).hexdigest()
            if store.q("SELECT id FROM sources WHERE meeting_id=? AND digest=?", (mid, dg)) or name in rec_jobs:
                raise HTTPException(409, "Эта запись уже загружена к встрече (распознана или стоит в очереди) — второй раз "
                                         "она не нужна")
            path = upload_dir(mid) / re.sub(r'[\\/:*?"<>|]', "_", name)
            path.write_bytes(data)
            from ...connectors.registry import default_registry  # noqa: F401 — тот же реестр, что у конвейера
            c = pipe.plugins.resolve_source(name)
            ready = c is not None and getattr(c, "kind", "") == "asr"
            if ready:
                recognize_in_background(m, path, name)
            else:
                pipe.cards.open(m["project_id"], "waiting_tools", f"Запись «{name}»: распознавать нечем",
                                {"file": str(path)}, mid)
            return {"id": 0, "kind": "recording", "original_filename": name, "relevance_warnings": [], "queued": True,
                    "recognition_available": ready}
        res = pipe.ingest(m["project_id"], mid, name, data)
        st = res.get("status")
        if st == "duplicate":
            other = store.get("sources", res.get("source_id") or 0) or {}
            raise HTTPException(409, f"Этот файл уже загружен к встрече («{other.get('name') or name}») — второй раз он не "
                                     "нужен: его текст в сборку дважды не идёт")
        if st == "rejected":
            reason = res.get("reason", "")
            if "не поддерживается" in reason:
                mat = save_material(m, name, data, "приложено с полосы источников: в текст Протокола не идёт", u)
                return {"id": mat["id"], "kind": "material", "material": True, "original_filename": name,
                        "relevance_warnings": [],
                        "note": f"Файл «{name}» приложен к встрече как материал: такие файлы (таблицы, презентации, pdf, "
                                "картинки) в текст Протокола не идут, но остаются при встрече — он виден в списке "
                                "материалов."}
            raise HTTPException(400, f"Файл «{name}» не принят. {reason}")
        if st == "held":
            raise HTTPException(409, res.get("reason") or "Файл ждёт решения в «Разборе»")
        тема_из_эталона(mid, res.get("source_id"))
        run_now, why = autorun_maybe(store.get("meetings", mid))
        return {"id": res.get("source_id"), "kind": res.get("kind"), "original_filename": name, "relevance_warnings": [],
                "autorun": run_now, "autorun_note": why}

    @r.post("/meetings/{mid}/sources/text", status_code=201)
    def upload_text(mid: int, payload: TextSourceIn, request: Request):
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        check_not_archived_settled(m)
        check_not_cancelled(m)
        same = " ".join(payload.text.split())
        for s in sources_of(mid, False):
            if (s.get("name") or "").startswith("Вставленный текст") and " ".join((s.get("text") or "").split()) == same:
                raise HTTPException(409, f"Этот текст уже добавлен к встрече ({s['name']})")
        name = f"Вставленный текст {datetime.now().strftime('%d.%m.%y %H-%M-%S')}.txt"
        taken = {s.get("name") for s in sources_of(mid)}
        k = 2
        while name in taken:
            name = f"Вставленный текст {datetime.now().strftime('%d.%m.%y %H-%M-%S')} ({k}).txt"
            k += 1
        res = pipe.ingest(m["project_id"], mid, name, payload.text.encode("utf-8"))
        if res.get("status") == "duplicate":
            raise HTTPException(409, "Этот текст уже добавлен к встрече")
        if res.get("status") != "ok":
            raise HTTPException(400, f"Текст не принят. {res.get('reason', '')}")
        run_now, why = autorun_maybe(store.get("meetings", mid))
        return {"id": res.get("source_id"), "kind": res.get("kind"), "original_filename": name, "relevance_warnings": [],
                "autorun": run_now, "autorun_note": why}

    def docx_response(md: str, stem: str) -> Response:
        from ...connectors.export import DocxOutput
        from ...core.draft_checks import clean_document
        out = DocxOutput(ctx.theme.get("design.document_font", "Times New Roman"),
                         int(ctx.theme.get("design.document_size_pt", 12)))
        body = out.render(clean_document(md)[0], "protocol")
        return Response(body, media_type=DOCX, headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                                        + quote(re.sub(r'[\\/:*?"<>|]', " ", stem)[:120] + ".docx")})

    @r.get("/meetings/{mid}/sources/{sid}/export")
    def export_source(mid: int, sid: int):
        ctx.meeting_or_404(mid)
        s = store.get("sources", sid)
        if not s or s["meeting_id"] != mid:
            raise HTTPException(404, "Источник не найден у этой встречи")
        if not (s.get("text") or "").strip():
            raise HTTPException(400, "В Word выгружается текстовый источник — заметки или расшифровка; этот файл приложен "
                                     "материалом и хранится как есть")

        def line(ln: str) -> str:
            parts = [x.strip() for x in ln.split("\t")]
            return f"{parts[0]} {parts[1]}: {parts[2]}" if len(parts) == 3 else " ".join(parts)
        m = store.get("meetings", mid)
        md = "\n\n".join([f"# Расшифровка встречи {ru_date(m['date'])}", f"Источник: {s['name']}"]
                         + [line(x) for x in s["text"].splitlines() if x.strip()])
        return docx_response(md, (s.get("name") or "расшифровка").rsplit(".", 1)[0])

    @r.delete("/meetings/{mid}/sources/{sid}", status_code=204)
    def delete_source(mid: int, sid: int, request: Request):
        admin = ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        check_not_archived_settled(m)
        s = store.get("sources", sid)
        if not s or s["meeting_id"] != mid:
            raise HTTPException(404, "Источник не найден")
        if building(mid)["running"]:
            raise HTTPException(409, "Сейчас идёт подготовка документа по этой встрече — дождитесь её завершения, затем "
                                     "удаляйте заметки")
        store.update("sources", sid, removed_at=now(), removed_reason=f"удалён вручную: {ctx.name(admin)}")
        return Response(status_code=204)

    @r.post("/meetings/{mid}/materials", status_code=201)
    async def upload_material(mid: int, request: Request, kind: str = Form("other"),
                              description: str | None = Form(None), file: UploadFile = File(...)):
        u = ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        check_not_archived_settled(m)
        check_not_cancelled(m)
        name = file.filename or "файл"
        data = await file.read(int(ctx.theme.get("intake.max_text_mb", 20)) * 2 ** 20 + 1)
        desc = re.sub(r"[\u0000-\u0008\u000b-\u001f\u007f​-‏‪-‮⁦-⁩﻿]", "",
                      description or "").strip()[:500] or None
        text = ""
        try:
            c = pipe.plugins.resolve_source(name)
            if c is not None and getattr(c, "kind", "") not in ("asr",) and hasattr(c, "read"):
                text = c.read(data, name).text
        except Exception:  # noqa: BLE001 — материал хранится и без текста
            text = ""
        return save_material(m, name, data, desc, u, text)

    @r.get("/meetings/{mid}/materials")
    def list_materials(mid: int):
        ctx.meeting_or_404(mid)
        return [mat_out(s) for s in sources_of(mid, True)]

    @r.delete("/meetings/{mid}/materials/{sid}", status_code=204)
    def delete_material(mid: int, sid: int, request: Request):
        u = ctx.need_user(request)
        s = store.get("sources", sid)
        if not s or s["meeting_id"] != mid or not is_material(s):
            raise HTTPException(404, "Материал не найден")
        check_not_archived_settled(ctx.meeting_or_404(mid))
        if not ctx.is_admin(u) and loads(s.get("meta"), {}).get("uploaded_by_user_id") != u["id"]:
            raise HTTPException(403, "Удалить материал может тот, кто его добавил, или администратор проекта")
        if building(mid)["running"]:
            raise HTTPException(409, "Сейчас собирается документ по этой встрече — дождитесь окончания, затем удаляйте")
        store.delete("sources", sid)
        return Response(status_code=204)

    # ------------------------------------------------------------------ сборка
    def queue_lines(mid: int) -> list[str]:
        b = building(mid)
        out = []
        running = store.q("SELECT meeting_id, meeting_date, started_at FROM build_queue WHERE status='running'")
        for x in running:
            out.append(f"собирается: встреча {ru_date(x['meeting_date'])}" + (" (эта)" if x["meeting_id"] == mid else ""))
        if b["queued"]:
            out.append(f"в очереди: место {b['place']}")
        pj = plan_jobs.get(mid)
        if pj and pj.get("running"):
            out.append("собирается: план этой встречи")
        return out

    @r.post("/meetings/{mid}/prepare-plan")
    def prepare_plan(mid: int, request: Request, confirm: bool = False):
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        check_not_cancelled(m)
        pj = plan_jobs.get(mid)
        if pj and pj.get("running"):
            return {"status": "already_running", "since": pj.get("since"), "reason": "Сборка плана уже идёт — показываю её ход",
                    "queue": {"строки": queue_lines(mid)}}
        since = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        plan_jobs[mid] = {"running": True, "since": since}

        def work():
            try:
                pipe.build_plan(m["project_id"], mid)
                plan_jobs[mid] = {"running": False, "since": since, "done": now()}
            except Exception as e:  # noqa: BLE001 — сбой — карточкой, сервер работает дальше
                plan_jobs[mid] = {"running": False, "since": since, "error": str(e)[:300]}
                pipe.cards.open(m["project_id"], "technical", f"План встречи {ru_date(m['date'])} не собран",
                                {"detail": f"{type(e).__name__}: {str(e)[:300]}"}, mid)
        threading.Thread(target=work, daemon=True).start()
        return {"status": "queued", "since": since, "reason": "Сборка плана начата — результат появится на экране сам",
                "queue": {"строки": queue_lines(mid)}}

    @r.post("/meetings/{mid}/prepare-minutes")
    def prepare_minutes(mid: int, request: Request, rebuild: bool = False, confirm: bool = False):
        u = ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        check_not_cancelled(m)
        if (m.get("date") or "") > today_iso():
            raise HTTPException(400, f"Встреча {ru_date(m['date'])} ещё не прошла — протокол собирается после неё")
        if not text_sources(mid):
            raise HTTPException(400, ЕСЛИ_НЕТ_МАТЕРИАЛОВ)
        if m.get("protocol_md") and m.get("protocol_hand_edited"):
            raise HTTPException(409, ПЕРЕСБОРКА_ЗАПРЕЩЕНА)
        b = building(mid)
        if b["running"]:
            return {"status": "already_running", "since": b["since"], "queue": {"строки": queue_lines(mid)}}
        if b["queued"]:
            return {"status": "already_queued", "queue": {"строки": queue_lines(mid)},
                    "reason": f"Сборка в очереди, место {b['place']} — начнётся сама"}
        queue.enqueue(m["project_id"], mid, "кнопка" + (" · пересборка" if rebuild else ""), by=ctx.name(u))
        b = building(mid)
        return {"status": "already_running" if b["running"] else "queued", "since": b.get("since"),
                "queue": {"строки": queue_lines(mid)},
                "reason": "Сборка протокола начата — результат появится на экране сам"}

    @r.get("/meetings/{mid}/generation")
    def generation(mid: int, request: Request):
        ctx.need_user(request)
        ctx.meeting_or_404(mid)
        b = building(mid)
        lines = queue_lines(mid)
        return {"running": b["running"], "since": b["since"], "queued": b["queued"], "place": b["place"],
                "queue_lines": lines, "queue": {"строки": lines}, "pending": {}, "waiting_model": None}

    @r.get("/meetings/{mid}/path")
    def path(mid: int, request: Request):
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        srcs = sources_of(mid, False)

        def step(k, title, at=None, detail="", state="ждёт", failure=None):
            return {"k": k, "title": title, "at": iso_dt(at), "detail": detail, "state": state, "failure": failure}
        steps = []
        rec = [s for s in srcs if s.get("local_asr")]
        if rec:
            steps.append(step("intake", "Запись принята", rec[0].get("created_at"), rec[0].get("name") or "", "готово"))
        elif srcs:
            steps.append(step("intake", "Источник принят", srcs[0].get("created_at"), srcs[0].get("name") or "", "готово"))
        elif any(j.get("meeting_id") == mid for j in rec_jobs.values()):
            steps.append(step("intake", "Запись принята", None, "распознаётся", "готово"))
        else:
            steps.append(step("intake", "Запись встречи", detail="ни записи, ни текста ещё нет"))
        tr = [s for s in srcs if s.get("kind") == "transcript"]
        if tr:
            n = len([x for x in (tr[0].get("text") or "").splitlines() if x.strip()])
            steps.append(step("transcript", "Расшифровка готова", tr[0].get("created_at"), f"строк {n}", "готово"))
        elif any(j.get("meeting_id") == mid for j in rec_jobs.values()):
            steps.append(step("transcript", "Расшифровка готова", None, "распознаётся", "идёт"))
        elif srcs:
            steps.append(step("transcript", "Расшифровка готова", srcs[0].get("created_at"), "заметки приложены текстом", "готово"))
        else:
            steps.append(step("transcript", "Расшифровка готова"))
        b = building(mid)
        lb = last_build(mid)
        fail = None
        if lb and lb.get("status") == "failed" and not m.get("protocol_md"):
            res = loads(lb.get("result"), {})
            fail = {"что": res.get("detail") or "сборка не удалась", "сама": "повторит сама, если сбой проходящий",
                    "человек": "посмотреть причину в «Разборе» и собрать заново"}
        if b["running"] and b["kind"] == "minutes":
            mins = 0
            st = to_date(b.get("since"))
            try:
                mins = int((datetime.now() - datetime.fromisoformat(str(b["since"]))).total_seconds() // 60)
            except (TypeError, ValueError):
                mins = 0 if st else 0
            steps.append(step("draft", "Черновик собран", b.get("since"), f"идёт с этого времени, {mins} мин", "идёт"))
        elif m.get("protocol_md"):
            steps.append(step("draft", "Черновик собран", m.get("protocol_built_at"), "", "готово"))
        else:
            steps.append(step("draft", "Черновик собран", lb.get("finished_at") if lb else None, "",
                              "сбой" if fail else "ждёт", fail))
        steps.append(step("decision", "Ждёт решения", detail="решение не требовалось" if m.get("protocol_md") else "",
                          state="готово" if m.get("protocol_md") else "ждёт"))
        steps.append(step("saved", "Протокол сохранён", m.get("protocol_built_at"), "",
                          "готово" if m.get("protocol_md") else "ждёт"))
        nxt = [x for x in live(store.q("SELECT * FROM meetings WHERE project_id=? AND date>? ORDER BY date, id",
                                        (m["project_id"], m["date"])))]
        nx = nxt[0] if nxt else None
        if nx and nx.get("plan_md"):
            steps.append(step("next_plan", "План следующей встречи", nx.get("plan_built_at"), f"встреча {ru_date(nx['date'])}",
                              "готово"))
        elif nx and (plan_jobs.get(nx["id"]) or {}).get("running"):
            steps.append(step("next_plan", "План следующей встречи", detail=f"собирается — встреча {ru_date(nx['date'])}",
                              state="идёт"))
        else:
            steps.append(step("next_plan", "План следующей встречи"))
        cur = next((s["k"] for s in steps if s["state"] != "готово"), None)
        return {"meeting_id": mid, "date": (m.get("date") or "")[:10], "steps": steps, "current": cur,
                "next_meeting_id": nx["id"] if nx else None}

    @r.patch("/meetings/{mid}/date")
    def set_date(mid: int, payload: MeetingDateIn, request: Request):
        ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        if m.get("protocol_md") or text_sources(mid):
            raise HTTPException(400, "У встречи уже есть Протокол или источники — дату больше не меняют")
        check_not_cancelled(m)
        if building(mid)["running"]:
            raise HTTPException(409, "Сейчас собирается документ по этой встрече — дату поменяете после сборки")
        day = payload.date.isoformat()
        clash = on_date(m["project_id"], day, exclude=mid)
        if clash:
            raise HTTPException(409, f"На {ru_date(day)} уже есть встреча №{clash[0]['id']}")
        vals = {"date": day}
        if m.get("label") == AUTO_LABEL:
            vals["label"] = None
        if m.get("plan_md"):
            head, sep, rest = m["plan_md"].partition("\n")
            old = to_date(m["date"])
            new = payload.date
            for fmt in ("%d.%m.%y", "%d.%m.%Y"):
                head = head.replace(old.strftime(fmt), new.strftime(fmt))
            vals["plan_md"] = head + sep + rest
        store.update("meetings", mid, **vals)
        return meeting_out(store.get("meetings", mid))

    @r.patch("/meetings/{mid}/leader")
    def set_leader(mid: int, payload: MeetingLeaderIn, request: Request):
        admin = ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        if payload.user_id is None:
            store.update("meetings", mid, leader_user_id=None, leader_source=None, leader_note=None)
        else:
            u = store.get("accounts", payload.user_id) if payload.user_id >= 1 else None
            if not u or not u.get("active", 1):
                raise HTTPException(400, "Такого человека нет в «Команде» среди активных")
            store.update("meetings", mid, leader_user_id=u["id"], leader=u["full_name"], leader_speaker=None,
                         leader_source="вручную", leader_note=f"указан вручную: {ctx.name(admin)}")
        return meeting_out(store.get("meetings", mid))

    @r.get("/meetings/{mid}/subprojects")
    def meeting_subprojects(mid: int, request: Request):
        """Подпроекты, в которые можно отнести встречу: подпроекты её проекта верхнего уровня (не архивные)."""
        ctx.need_user(request)
        m = ctx.meeting_or_404(mid)
        root = ctx.root_of(m.get("project_id"))
        fam = ctx.family(root)
        items = [{"id": p["id"], "name": ctx.project_names(p["id"])[1]} for p in store.q(
            "SELECT id FROM projects WHERE COALESCE(archived,0)=0 ORDER BY name") if p["id"] in fam and p["id"] != root]
        return {"project": ctx.project_names(root)[0], "current": ctx.project_names(m.get("project_id"))[1] or "",
                "items": items}

    @r.patch("/meetings/{mid}/subproject")
    def set_meeting_subproject(mid: int, payload: MeetingSubprojectIn, request: Request):
        """Подпроект встречи внутри того же проекта верхнего уровня; пусто — весь проект. Задачи, уже поставленные на встрече,
        остаются в своём подпроекте (протокол и реестр задним числом не переписываются); следующая сборка ставит новые задачи
        в подпроект встречи. Перенос встречи в другой проект — отдельное действие (агент протокола, 27.10.2026)."""
        admin = ctx.need_admin(request)
        m = ctx.meeting_or_404(mid)
        root = ctx.root_of(m.get("project_id"))
        target = root
        sp = " ".join((payload.subproject or "").split())
        if sp:
            key = lambda s: " ".join((s or "").lower().replace("ё", "е").split())  # noqa: E731
            fam = ctx.family(root)
            hit = [p for p in store.q("SELECT id, name FROM projects WHERE COALESCE(archived,0)=0")
                   if p["id"] in fam and p["id"] != root and key(p["name"]) == key(sp)]
            if not hit:
                raise HTTPException(400, f"Подпроекта «{sp}» нет в справочнике подпроектов проекта "
                                         f"«{ctx.project_names(root)[0]}».")
            target = hit[0]["id"]
        store.update("meetings", mid, project_id=target)
        ctx.sys_msg(f"Встреча {ru_date(m.get('date'))}: {ctx.project_label(target)}",
                    f"Отнёс: {ctx.name(admin)}. Было: {ctx.project_label(m.get('project_id'))}.", "settings")
        return meeting_out(store.get("meetings", mid))

    @r.post("/meetings/{mid}/accept-draft")
    def accept_draft(mid: int, request: Request):
        ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        raise HTTPException(400, "Черновика, ждущего решения, нет: протокол MeetFlow сохраняется сразу, замечания проверки — "
                                 "карточками в «Разборе»")

    @r.post("/meetings/{mid}/accept-plan-draft")
    def accept_plan_draft(mid: int, request: Request):
        ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        raise HTTPException(400, "Черновика плана, ждущего решения, нет: план сохраняется сразу")

    @r.get("/meetings/{mid}/plan-basis")
    def plan_basis(mid: int):
        m = ctx.meeting_or_404(mid)
        prev_rows = live(store.q("SELECT * FROM meetings WHERE project_id=? AND date<? ORDER BY date DESC, id DESC",
                                 (m["project_id"], m["date"])))
        if not prev_rows:
            prev = {"state": "empty"}
        else:
            p = prev_rows[0]
            if p.get("protocol_md"):
                prev = {"state": "minutes", "date": p["date"], "meeting_id": p["id"]}
            elif text_sources(p["id"]):
                prev = {"state": "source", "date": p["date"], "meeting_id": p["id"]}
            else:
                earlier = next((x for x in prev_rows[1:] if x.get("protocol_md")), None)
                prev = {"state": "none", "date": p["date"], "meeting_id": p["id"],
                        "used_date": earlier["date"] if earlier else None}
        day = m["date"]
        cands = []
        for t in store.q("SELECT * FROM tasks WHERE project_id=? AND status='active' ORDER BY id", (m["project_id"],)):
            why = []
            if t.get("due_date") and t["due_date"] <= day:
                why.append("срок подошёл")
            if (t.get("due_kind") or "") == "к следующей встрече":
                why.append("договорились обсудить")
            if t.get("last_comment"):
                why.append("свежий комментарий")
            if why:
                cands.append({"description": t["description"], "reasons": why})
        qs = store.q("SELECT u.text, m.date FROM units u LEFT JOIN meetings m ON m.id=u.meeting_id WHERE u.project_id=? "
                     "AND u.kind='open_question' AND u.status IN ('open','active') ORDER BY m.date DESC",
                     (m["project_id"],))
        fallback = None
        if prev.get("state") in ("empty", "none") and not cands and not sources_of(mid, True) and not qs:
            fallback = "empty"
        return {"previous": prev, "candidates_count": len(cands), "candidates_preview": cands[:5],
                "open_questions_count": len(qs), "open_questions_preview": [{"text": q["text"], "date": q["date"]} for q in qs[:5]],
                "materials_count": len(sources_of(mid, True)), "fallback": fallback}

    @r.get("/meetings/{mid}/post-save-check")
    def post_save_check(mid: int, request: Request):
        ctx.need_admin(request)
        ctx.meeting_or_404(mid)
        tasks, findings = [], []
        for c in store.q("SELECT * FROM cards WHERE meeting_id=? AND status='open' ORDER BY id", (mid,)):
            p = loads(c.get("payload"), {})
            if c["kind"] in ("held_task", "task_doubt"):
                t = store.get("tasks", p.get("task_id") or 0) or {}
                tasks.append({"id": c["id"], "description": p.get("description") or t.get("description") or c["title"],
                              "registry_text": p.get("similar") or "", "why": p.get("reason") or p.get("why") or "",
                              "labels": {"accept": "Завести задачу" if c["kind"] == "held_task" else "Подтвердить",
                                         "reject": "Не задача"}})
            elif c["kind"] == "review_finding":
                findings.append({"title": "Проверка", "text": p.get("issue") or c["title"]})
        return {"show": bool(tasks or findings), "tasks": tasks, "tasks_count": len(tasks), "findings": findings,
                "findings_count": len(findings)}

    def shown(md: str | None, project_id: int | None, meeting: dict | None = None) -> str:
        """Дверь показа: снятые задачи не показываются; с `meeting` (протокол на экране и в Word, не полотно правки) —
        открытые задачи из реестра одной строкой (ERP 3550fc6, `tablica_zadach.укрупнить_показ`, 27.10.2026)."""
        from ...core.tablica_zadach import без_снятых, задачи_для_скрытия, укрупнить_показ
        if not md or project_id is None:
            return md or ""
        md = без_снятых(md, *задачи_для_скрытия(store, project_id))     # проект с подпроектами (27.10.2026)
        return укрупнить_показ(store, meeting, md) if meeting else md
    ctx.shown = shown

    def notes_of(m: dict) -> list[dict]:
        out = []
        for i, n in enumerate(loads(m.get("review_notes"), [])):
            if not isinstance(n, dict):
                continue
            issue = str(n.get("issue") or "")
            words = issue.split()
            out.append({"run_id": m["id"], "idx": i, "title": " ".join(words[:6]) + ("…" if len(words) > 6 else ""),
                        "issue": issue, "quote": n.get("quote") or "", "why": "", "kind": n.get("kind_ui") or "text",
                        "task_no": None, "dismissed": bool(n.get("dismissed")), "outcome": n.get("outcome"),
                        "outcome_label": n.get("outcome_label")})
        return out
    ctx.notes_of = notes_of

    @r.get("/meetings/{mid}/minutes")
    def minutes(mid: int):
        m = ctx.meeting_or_404(mid)
        if not m.get("protocol_md"):
            return {"available": False, "message": "Протокола этой встречи пока нет"}
        srcs = [{"kind": s.get("kind") or "other", "original_filename": s.get("name") or ""} for s in text_sources(mid)]
        return {"available": True, "content_md": shown(m["protocol_md"], m["project_id"], m),
                "generated_at": iso_dt(m.get("protocol_built_at")), "sources": srcs, "build_note": m.get("build_note") or "",
                "hand_edited": bool(m.get("protocol_hand_edited")), "minor_findings": notes_of(m)}

    @r.get("/meetings/{mid}/plan")
    def plan(mid: int):
        m = ctx.meeting_or_404(mid)
        if not m.get("plan_md"):
            return {"available": False, "message": "Плана этой встречи пока нет"}
        built = m.get("plan_built_at") or ""
        newer = len([s for s in sources_of(mid, True) if (s.get("created_at") or "") > built])
        srcs = [{"kind": "other", "original_filename": s.get("name") or ""} for s in sources_of(mid, True)]
        return {"available": True, "content_md": shown(m["plan_md"], m["project_id"]), "generated_at": iso_dt(built),
                "sources": srcs, "newer_materials": newer, "hand_edited": bool(m.get("plan_hand_edited")),
                "minor_findings": []}

    @r.get("/meetings/{mid}/minutes/export")
    def export_minutes(mid: int):
        m = ctx.meeting_or_404(mid)
        if not m.get("protocol_md"):
            raise HTTPException(404, "Протокола этой встречи пока нет")
        return docx_response(shown(m["protocol_md"], m["project_id"], m), f"Протокол встречи {ru_date(m['date'])}")

    @r.get("/meetings/{mid}/plan/export")
    def export_plan(mid: int):
        m = ctx.meeting_or_404(mid)
        if not m.get("plan_md"):
            raise HTTPException(404, "Плана этой встречи пока нет")
        return docx_response(shown(m["plan_md"], m["project_id"]), f"План встречи {ru_date(m['date'])}")

    def point_edit(mid: int, vid: str, payload: PointEditIn, u: dict) -> dict:
        m = ctx.meeting_or_404(mid)
        if archived(m):
            raise HTTPException(400, "Встреча в архиве — менять её уже нельзя")
        col = "protocol_md" if vid == "minutes" else "plan_md"
        md = m.get(col) or ""
        if not md:
            raise HTTPException(404, "Протокола этой встречи пока нет" if vid == "minutes" else "Плана этой встречи пока нет")
        n = md.count(payload.find)
        if n == 0:
            return {"status": "error", "reason": "Такого фрагмента в документе нет — скопируйте его из текста дословно"}
        if n > 1:
            return {"status": "error", "reason": f"Фрагмент встречается {n} раз — возьмите кусок длиннее, чтобы он был один"}
        new = md.replace(payload.find, payload.replace, 1)
        ctx.save_doc(mid, vid, new, ctx.name(u), place="точечная правка", old=payload.find, new_text=payload.replace,
                     fix=payload.is_processing_error_fix)
        return {"status": "ok"}

    def save_doc(mid: int, vid: str, md: str, who: str, place: str = "", old: str = "", new_text: str = "",
                 fix: bool = True) -> None:
        """Новая версия документа человеком: прежняя — в базе (версии протокола), правка — в реестр корректировок."""
        if vid == "minutes":
            last = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (mid,))
            ver = int((last[0]["v"] if last and last[0]["v"] is not None else 0) or 0) + 1
            store.insert("protocol_versions", meeting_id=mid, version=ver, protocol_md=md, model="правка", built_at=now())
            store.update("meetings", mid, protocol_md=md, protocol_hand_edited=1)
        else:
            store.update("meetings", mid, plan_md=md, plan_hand_edited=1)
        store.insert("doc_corrections", meeting_id=mid, doc=vid, who=who, at=now(), place=place or "абзац",
                     old_text=old, new_text=new_text, fix=int(bool(fix)))
    ctx.save_doc = save_doc

    @r.post("/meetings/{mid}/minutes/point-edit")
    def point_edit_minutes(mid: int, payload: PointEditIn, request: Request):
        res = point_edit(mid, "minutes", payload, ctx.need_admin(request))
        if res["status"] == "error":
            raise HTTPException(400, res["reason"])
        return res

    @r.post("/meetings/{mid}/plan/point-edit")
    def point_edit_plan(mid: int, payload: PointEditIn, request: Request):
        res = point_edit(mid, "plan", payload, ctx.need_admin(request))
        if res["status"] == "error":
            raise HTTPException(400, res["reason"])
        return res

    def correction(mid: int, vid: str, payload: CorrectionIn, u: dict) -> dict:
        """«Попросить ИИ поправить словами» — один вызов модели генерации MeetFlow: абзац, который надо заменить, и его
        новый текст; замена проходит, только если старый абзац найден в документе дословно (сверка кодом)."""
        m = ctx.meeting_or_404(mid)
        col = "protocol_md" if vid == "minutes" else "plan_md"
        md = m.get(col) or ""
        if not md:
            raise HTTPException(404, "Документа пока нет")
        from ...core.budget import BudgetLimits, RunBudget
        system = ("Ты правишь документ встречи по просьбе человека. Верни JSON {\"old\": \"абзац дословно из документа\", "
                  "\"new\": \"исправленный абзац\", \"note\": \"что исправлено, одной фразой\"}. Факты не придумывай.")
        user = f"Просьба: {payload.request}\n\nДокумент:\n{md[:60000]}"
        try:
            out = pipe._call(pipe.gen, RunBudget(BudgetLimits(**ctx.theme.get("budget", {}))), "correction", system, user, mid)
        except Exception as e:  # noqa: BLE001 — модель не ответила: отказ словами
            raise HTTPException(400, f"Модель не ответила: {type(e).__name__}") from None
        old, new = str((out or {}).get("old") or ""), str((out or {}).get("new") or "")
        if not old or md.count(old) != 1 or not new.strip():
            return {"status": "verification_failed"}
        save_doc(mid, vid, md.replace(old, new, 1), ctx.name(u), place="правка словами (ИИ)", old=old, new_text=new)
        return {"status": "ok", "note": str((out or {}).get("note") or "")[:300]}

    @r.post("/meetings/{mid}/minutes/correction-request")
    def correction_minutes(mid: int, payload: CorrectionIn, request: Request):
        return correction(mid, "minutes", payload, ctx.need_admin(request))

    @r.post("/meetings/{mid}/plan/correction-request")
    def correction_plan(mid: int, payload: CorrectionIn, request: Request):
        return correction(mid, "plan", payload, ctx.need_admin(request))
