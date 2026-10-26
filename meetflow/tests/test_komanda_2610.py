# -*- coding: utf-8 -*-
"""«Команда» из общей базы в проектной: подсказка модели и страж исполнителя (задание 26.10.2026)."""
from __future__ import annotations

import sqlite3

from meetflow.core import team_sync
from meetflow.core.prompts import PromptBuilder, profile
from meetflow.core.store import Store


def _shared(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE people (full_name TEXT, role TEXT, department TEXT, organization TEXT, "
                "is_external INTEGER, confirmed_human INTEGER)")
    con.executemany("INSERT INTO people VALUES (?,?,?,?,?,?)", [
        ("Иванов Иван", "Инженер", "Производство", "", 0, 0),
        ("Петров Пётр", "Логист", "Склад", "", 0, 0),
        ("Сидоров Сидор", "Поставщик", "", "ООО Ромашка", 1, 1),
        ("Скрытый Внешний", "Менеджер", "", "ООО Другое", 1, 0),
    ])
    con.commit()
    con.close()


def test_shared_team_fills_project_without_duplicates(tmp_path, monkeypatch):
    shared = tmp_path / "team_shared.db"
    _shared(shared)
    monkeypatch.setenv("TEAM_SHARED_PATH", str(shared))
    store = Store(tmp_path / "app.db")
    pid = store.insert("projects", name="Проект", theme="it_product")
    assert team_sync.sync_people(store, pid) == 3          # внутренние + подтверждённый внешний
    rows = store.q("SELECT full_name, external, confirmed FROM people WHERE project_id=? ORDER BY full_name", (pid,))
    assert [r["full_name"] for r in rows] == ["Иванов Иван", "Петров Пётр", "Сидоров Сидор"]
    assert next(r for r in rows if r["full_name"] == "Сидоров Сидор")["external"] == 1
    assert team_sync.sync_people(store, pid) == 0          # повтор не плодит


def test_protocol_prompt_names_participants_and_leader():
    pb = PromptBuilder("роль", profile("generic"))
    system, _user = pb.protocol(["Участники", "Решения"], "текст встречи",
                                participants=["Иванов Иван", "Петров Пётр"], leader="Петров Пётр")
    assert "Иванов Иван" in system and "Петров Пётр" in system
    assert "Ведущий встречи: Петров Пётр" in system
    assert "других не придумывай" in system
