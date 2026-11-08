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


def sync_people(store: Store, project_id: int, voice_base_path: str | None = None,
                неоднозначные: list[dict] | None = None) -> int:
    """Добавить недостающих подтверждённых людей общей «Команды» в проект. Возвращает, сколько добавлено.

    Если пришло «фамилия + имя» без отчества, а в проекте таких двое с разными отчествами — **не угадываем** и третью
    запись не заводим: человек остаётся как есть, сведения кладутся в `неоднозначные` (карточку открывает сборка).
    Правка 09.11.2026 по остатку отчёта 07.11 (`29d4e86`).
    """
    people = shared_people(voice_base_path)
    if not people:
        return 0
    have = {_norm(r["full_name"]): r for r in
            store.q("SELECT id, full_name FROM people WHERE project_id=?", (project_id,))}
    # 07.11.2026 (записки ecbfc73, 22ad64f): ключ — первые два слова «фамилия + имя». Если в проекте человек
    # записан без отчества, а в общей «Команде» с отчеством — ДОПИСЫВАЕМ отчество в существующую запись, а не
    # заводим двойника. Тёзки с разными отчествами не сливаются: у обоих по три слова и отчества разные — разные люди.
    def _части(фио: str) -> list[str]:
        return _norm(фио).split()

    def _ключ(фио: str) -> str:
        # порядок слов не важен: «Иванов Пётр» и «Пётр Иванов» — один человек
        ч = _части(фио)
        return " ".join(sorted(ч[:2])) if len(ч) >= 2 else _norm(фио)

    в_проекте: dict[str, list[dict]] = {}
    for r in store.q("SELECT id, full_name FROM people WHERE project_id=?", (project_id,)):
        ч = _части(r["full_name"])
        if len(ч) >= 2:
            в_проекте.setdefault(_ключ(r["full_name"]), []).append(r)
    added = updated = 0
    не_угадано = 0
    for p in people:
        name = " ".join(str(p.get("full_name") or "").split())
        if not name:
            continue
        if _norm(name) in have:
            continue
        ч = _части(name)
        варианты = в_проекте.get(_ключ(name), []) if len(ч) >= 2 else []
        if варианты:
            if len(ч) >= 3:
                тот_же = [r for r in варианты if len(_части(r["full_name"])) >= 3
                          and _norm(_части(r["full_name"])[2]) == _norm(ч[2])]
                if тот_же:
                    continue          # тот же человек, уже есть
                без_отчества = [r for r in варианты if len(_части(r["full_name"])) == 2]
                if без_отчества:
                    # дописать отчество в существующую запись
                    store.update("people", без_отчества[0]["id"], full_name=name)
                    have[_norm(name)] = {"full_name": name}
                    обновлённая = без_отчества[0]
                    for гр in в_проекте.values():
                        for i, r in enumerate(гр):
                            if r["id"] == обновлённая["id"]:
                                гр[i] = {"id": r["id"], "full_name": name}
                    updated += 1
                    continue
                # разные отчества — тёзки: это разные люди, заводим второго отдельной записью
            else:
                # пришло «фамилия + имя»: один человек с отчеством — это он; двое с разными отчествами — не угадываем
                отчества = {_norm(_части(r["full_name"])[2]) for r in варианты
                            if len(_части(r["full_name"])) >= 3}
                if len(отчества) <= 1:
                    continue          # один человек (или записи без отчества) — это он
                не_угадано += 1
                if неоднозначные is not None:
                    неоднозначные.append({"name": name, "project_id": project_id,
                                          "candidates": [r["full_name"] for r in варианты]})
                continue              # третью запись не заводим: угадывать не должны (09.11.2026)
        store.insert("people", project_id=project_id, full_name=name,
                     role=str(p.get("role") or ""), department=str(p.get("department") or ""),
                     aliases=json.dumps([], ensure_ascii=False),
                     external=int(bool(p.get("external"))), confirmed=1,
                     organization=str(p.get("organization") or ""),
                     known_marks=json.dumps([], ensure_ascii=False))
        have[_norm(name)] = {"full_name": name}
        if len(ч) >= 2:
            в_проекте.setdefault(_ключ(name), []).append({"id": 0, "full_name": name})
        added += 1
    print(f"MeetFlow: Команда проекта {project_id} — добавлено {added}, дописано отчеств {updated}"
          + (f", тёзок не угадано {не_угадано}" if не_угадано else ""), file=__import__("sys").stderr, flush=True)
    return added


def sync_all(store: Store, voice_base_path: str | None = None) -> dict[int, int]:
    """Обновить «Команду» всех проектов; {project_id: сколько добавлено}."""
    out = {}
    # 07.11.2026: только живые проекты — в архивные и удалённые люди не переносятся (иначе 241 строка
    # в проекты-проверки, найденная на копии базы)
    for row in store.q("SELECT id FROM projects WHERE COALESCE(archived,0)=0 AND COALESCE(deleted,0)=0 ORDER BY id"):
        n = sync_people(store, row["id"], voice_base_path)
        if n:
            out[row["id"]] = n
    return out
