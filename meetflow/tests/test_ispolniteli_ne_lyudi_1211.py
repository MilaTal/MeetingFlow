# -*- coding: utf-8 -*-
"""Исполнитель — человек или известный отдел; неизвестные сокращения не ставим (12.11.2026).

Повод: в протоколе 11.11 ответственным оказались «ТМЦ» (товарно-материальные ценности) и «ОДС». Причина —
`Team.find` считал отделом любое слово капсом из 2–6 букв, даже если такого отдела нет в «Команде»; ворота
ставили его исполнителем, а проверка этого не ловила.
"""
from __future__ import annotations

from meetflow.core.gates import GateConfig, TaskGate
from meetflow.core.people import Person, Team
from meetflow.core.types import SourceDoc, SourceKind, TaskDraft

ЛЮДИ = [Person("Петрова Анастасия", department="ПТО"), Person("Сидоров Пётр", department="ПТО")]


def test_неизвестное_сокращение_не_отдел():
    t = Team(ЛЮДИ, department_heads={"ПТО": "Сидоров Пётр"})
    assert t.find("ТМЦ").via == "not_a_person"
    assert t.find("ОДС").via == "not_a_person"


def test_известный_отдел_остаётся_отделом():
    t = Team(ЛЮДИ)                      # руководитель отдела не задан — отдел остаётся отделом
    m = t.find("ПТО")
    assert m.via == "department_without_head" and len(m.candidates) == 2


def test_ворота_не_ставят_сокращение_исполнителем():
    src = SourceDoc("t", SourceKind.TRANSCRIPT,
                    "[00:10:00] Петрова Анастасия: ТМЦ, разберитесь, почему факт по трудозатратам не попадает в отчёт.\n")
    g = TaskGate(Team(ЛЮДИ), cfg=GateConfig(require_assignee=False)).check(
        TaskDraft("Разобраться, почему факт по трудозатратам не попадает в отчёт", "ТМЦ", line_no=0), src)
    assert g.accepted, g.reasons
    assert g.assignee is None, "ТМЦ — не человек"
    assert (g.pending or {}).get("reason") == "not_a_person", g.pending


def test_далёкий_отдел_в_длинной_строке_не_адресат():
    """Строка распознавания на 5–7 тыс. знаков: отдел, названный в её начале, — не адресат поручения в конце."""
    хвост = "Разобраться, почему факт по трудозатратам не попадает в отчёт."
    строка = "ПТО, проверьте пломбы на цистернах. " + "Обсуждение отчётов по производству. " * 160 + хвост
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:10:00] Петрова Анастасия: " + строка + "\n")
    g = TaskGate(Team(ЛЮДИ), cfg=GateConfig(require_assignee=False)).check(
        TaskDraft("Разобраться, почему факт по трудозатратам не попадает в отчёт", None, quote=хвост, line_no=0), src)
    assert g.accepted, g.reasons
    assert g.assignee is None
    assert (g.pending or {}).get("reason") != "department", "ПТО из начала строки — не адресат"


def test_отдел_в_той_же_фразе_остаётся_адресатом():
    цитата = "ПТО, разберитесь, почему факт по трудозатратам не попадает в отчёт."
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:10:00] Петрова Анастасия: " + цитата + "\n")
    g = TaskGate(Team(ЛЮДИ), cfg=GateConfig(require_assignee=False)).check(
        TaskDraft("Разобраться, почему факт по трудозатратам не попадает в отчёт", None, quote=цитата, line_no=0), src)
    assert g.accepted, g.reasons
    assert (g.pending or {}).get("reason") == "department", g.pending
    assert (g.pending or {}).get("name") == "ПТО"


def test_упоминание_в_третьем_лице_не_адресат():
    """«Анастасия сказала, что отчёт формируется» — не поручение Анастасии (встреча 11.11)."""
    t = Team(ЛЮДИ)
    assert t.addressee("Анастасия сказала, что отчёт формируется корректно.") is None
    assert t.addressee("Петрова Анастасия, подготовьте отчёт.") == "Петрова Анастасия"


def test_сборка_не_пишет_сокращение_в_протокол(tmp_path):
    """Сквозная проверка: модель назвала «ТМЦ» исполнителем — в реестре и протоколе его нет, есть карточка."""
    from fastapi.testclient import TestClient

    from meetflow.connectors.llm_mock import MockLLM
    from meetflow.web.app import create_app

    H = {"X-User-Role": "project_admin"}
    строка = "[00:10:00] Петрова Анастасия: ТМЦ, разберитесь, почему факт по трудозатратам не попадает в отчёт."

    class Say(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Разобраться, почему факт по трудозатратам не попадает в отчёт",
                               "assignee": "ТМЦ", "quote": строка, "line": 0}]}

    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    c.store, c.pipe = app.state.store, app.state.pipe
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    c.post(f"/api/projects/{pid}/people", json={"full_name": "Петрова Анастасия", "department": "ПТО"}, headers=H)
    c.pipe.gen = Say()
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-11-11"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H,
           files={"file": ("t.txt", (строка + "\n").encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)

    задачи = c.get(f"/api/meetings/{mid}/tasks", headers=H).json()
    assert задачи and задачи[0]["assignee"] is None, задачи
    протокол = c.get(f"/api/meetings/{mid}/protocol", headers=H).json()["markdown"]
    assert "ТМЦ" not in протокол
    карточки = c.store.q("SELECT title FROM cards WHERE project_id=?", (pid,))
    assert any("сокращения вне «Команды»" in (x["title"] or "") for x in карточки), карточки
