# -*- coding: utf-8 -*-
"""Общая «Команда» → проектная «Команда» MeetFlow.

Задание владелицы 26.10.2026: список участников, подсказка модели и выбор исполнителя должны опираться на
подтверждённую общую «Команду», а не на пустую таблицу проекта. Общая база `team_shared.db` — только чтение;
здесь её подтверждённые люди (внутренние и подтверждённые внешние) переносятся в `people` проекта, чтобы
работали существующие правила `Team`/`TaskGate` (тёзки, падежи, «е = ё», «исполнитель не прозвучал»).

Перенос идемпотентный: человек с тем же ФИО (без учёта ё/е, регистра и лишних пробелов) второй раз не
заводится; уже заведённые записи не перезаписываются — правки владельца сохраняются.
"""
from __future__ import annotations

import json
import os
from typing import Any

from ..connectors.team_shared import team_shared_state
from .store import Store


def _norm(name: str) -> str:
    return " ".join((name or "").replace("ё", "е").replace("Ё", "Е").lower().split())


def shared_people(voice_base_path: str | None = None) -> list[dict[str, Any]]:
    """Подтверждённые люди общей «Команды»; нет базы — пустой список, без исключения."""
    try:
        st = team_shared_state(voice_base_path=voice_base_path)
    except Exception:  # noqa: BLE001 — общая база не должна ломать экран и сборку
        return []
    return [p for p in (st.get("people_list") or []) if (p.get("full_name") or "").strip()]


def sync_people(store: Store, project_id: int, voice_base_path: str | None = None) -> int:
    """Добавить недостающих подтверждённых людей общей «Команды» в проект. Возвращает, сколько добавлено."""
    people = shared_people(voice_base_path)
    if not people:
        return 0
    have = {_norm(r["full_name"]): r for r in
            store.q("SELECT id, full_name FROM people WHERE project_id=?", (project_id,))}
    added = 0
    for p in people:
        name = " ".join(str(p.get("full_name") or "").split())
        if not name or _norm(name) in have:
            continue
        store.insert("people", project_id=project_id, full_name=name,
                     role=str(p.get("role") or ""), department=str(p.get("department") or ""),
                     aliases=json.dumps([], ensure_ascii=False),
                     external=int(bool(p.get("external"))), confirmed=1,
                     organization=str(p.get("organization") or ""),
                     known_marks=json.dumps([], ensure_ascii=False))
        have[_norm(name)] = {"full_name": name}
        added += 1
    return added


def sync_all(store: Store, voice_base_path: str | None = None) -> dict[int, int]:
    """Обновить «Команду» всех проектов; {project_id: сколько добавлено}."""
    out = {}
    for row in store.q("SELECT id FROM projects ORDER BY id"):
        n = sync_people(store, row["id"], voice_base_path)
        if n:
            out[row["id"]] = n
    return out
