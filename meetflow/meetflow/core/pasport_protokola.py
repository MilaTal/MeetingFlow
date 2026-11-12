# -*- coding: utf-8 -*-
"""Паспорт принятого протокола: что в нём обязано сохраниться после пересборки (12.11.2026).

Зачем. Пересборка моделью может незаметно вернуть снятую строку, сменить ответственного или потерять задачу — тесты
кода этого не видят, потому что текст и реестр при этом «валидны». Паспорт фиксирует числа и фразы принятого
протокола, а после пересборки сравнивает с ними и говорит, что разошлось.

Паспорт хранится в базе рядом с версиями протокола (`protocol_passports`, один на встречу) и снимается явно:
скриптом `scripts/pasport_protokola.py --meeting N --create` или при ручном принятии протокола. Сам он ничего не
блокирует: расхождение — карточка «Разбора», а не отказ сборке.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

ТАБЛИЦА = "protocol_passports"


def _сейчас() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _фраза(текст: str | None) -> str:
    return " ".join((текст or "").replace("ё", "е").lower().split())


def _заголовки(protocol_md: str | None) -> list[str]:
    """Ключевые фразы документа: заголовки разделов и жирные начала абзацев, без текста целиком."""
    out = []
    for строка in (protocol_md or "").splitlines():
        с = строка.strip()
        if с.startswith("## "):
            out.append(_фраза(с[3:]))
        elif с.startswith("**") and "**" in с[2:]:
            кусок = с[2:с.find("**", 2)].strip(" :–—-")
            if кусок:
                out.append(_фраза(кусок))
    return list(dict.fromkeys(х for х in out if х))


def _версия(store, meeting_id: int) -> int:
    row = store.q("SELECT MAX(version) AS v FROM protocol_versions WHERE meeting_id=?", (meeting_id,))
    return int((row[0]["v"] if row and row[0]["v"] is not None else 0) or 0)


def факты(store, meeting_id: int, *, protocol_md: str | None = None, задачи: list[dict] | None = None) -> dict:
    """Числа и фразы, которые характеризуют принятый протокол. Не зависит от форматирования таблицы."""
    m = store.get("meetings", meeting_id) or {}
    md = protocol_md if protocol_md is not None else (m.get("protocol_md") or "")
    задачи = задачи if задачи is not None else store.q(
        "SELECT description, assignee, status FROM tasks WHERE source_meeting_id=?", (meeting_id,))
    живые = [t for t in задачи if (t.get("status") or "active") == "active"]
    описания = sorted({_фраза(t.get("description")) for t in живые if (t.get("description") or "").strip()})
    return {
        "version": _версия(store, meeting_id),
        "protocol_len": len(md or ""),
        "protocol_digest": hashlib.sha256((md or "").encode("utf-8")).hexdigest()[:16],
        "active_tasks": len(живые),
        "assignees": sum(1 for t in живые if (t.get("assignee") or "").strip()),
        "tasks": описания,
        "headings": _заголовки(md),
    }


def снять(store, meeting_id: int, by: str = "") -> dict:
    """Запомнить текущее состояние как паспорт (прежний паспорт встречи заменяется)."""
    ф = факты(store, meeting_id)
    старые = store.q(f"SELECT id FROM {ТАБЛИЦА} WHERE meeting_id=?", (meeting_id,))
    for р in старые:
        store.delete(ТАБЛИЦА, р["id"])
    store.insert(ТАБЛИЦА, meeting_id=meeting_id, version=ф["version"], facts=json.dumps(ф, ensure_ascii=False),
                 created_at=_сейчас(), created_by=by)
    return ф


def получить(store, meeting_id: int) -> dict | None:
    строки = store.q(f"SELECT * FROM {ТАБЛИЦА} WHERE meeting_id=? ORDER BY id DESC LIMIT 1", (meeting_id,))
    if not строки:
        return None
    р = строки[0]
    try:
        ф = json.loads(р["facts"] or "{}")
    except ValueError:
        ф = {}
    return {**р, "facts": ф}


def сверить(store, meeting_id: int) -> dict:
    """Сравнить текущее состояние с паспортом. Нет паспорта — `есть: False`, расхождений нет."""
    п = получить(store, meeting_id)
    if not п:
        return {"есть": False, "расхождения": []}
    было, стало = п["facts"], факты(store, meeting_id)
    разные = []
    if было.get("active_tasks") != стало["active_tasks"]:
        разные.append(f"активных задач: было {было.get('active_tasks')}, стало {стало['active_tasks']}")
    if было.get("assignees") != стало["assignees"]:
        разные.append(f"задач с ответственным: было {было.get('assignees')}, стало {стало['assignees']}")
    пропали = sorted(set(было.get("tasks") or []) - set(стало["tasks"]))
    появились = sorted(set(стало["tasks"]) - set(было.get("tasks") or []))
    if пропали:
        разные.append("пропали формулировки: " + "; ".join(пропали[:5]))
    if появились:
        разные.append("появились формулировки: " + "; ".join(появились[:5]))
    потерянные_заголовки = sorted(set(было.get("headings") or []) - set(стало["headings"]))
    if потерянные_заголовки:
        разные.append("пропали заголовки: " + "; ".join(потерянные_заголовки[:5]))
    return {"есть": True, "версия_паспорта": п.get("version"), "версия_сейчас": стало["version"],
            "было_знаков": было.get("protocol_len"), "стало_знаков": стало["protocol_len"],
            "расхождения": разные, "сошлось": not разные}


def карточка_при_расхождении(pipeline, project_id: int, meeting_id: int) -> dict:
    """После сборки: если паспорт есть и факты разошлись — одна карточка «Разбора». Сборку не отменяет."""
    итог = сверить(pipeline.s, meeting_id)
    if not итог.get("есть") or итог.get("сошлось"):
        return итог
    pipeline.cards.open(project_id, "technical",
                        "Паспорт протокола: после пересборки изменились факты",
                        {"meeting_id": meeting_id, "расхождения": итог["расхождения"],
                         "версия_паспорта": итог.get("версия_паспорта"), "версия_сейчас": итог.get("версия_сейчас")},
                        meeting_id)
    return итог
