# -*- coding: utf-8 -*-
"""Текст протокола и таблица задач как в ERP (перенос 27.10.2026; DECISIONS ERP 25.10.2026 «протокол и план блоками,
только суть», «материалы к встрече в конце плана»; 26.10.2026 «текст протокола без «Решили» и только с опорой в
записи», «таблица задач протокола как у секретаря», «пометка «оперативная» из раздела секретаря ставится сама»).
"""
import pytest
from conftest import TRANSCRIPT
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core import tablica_zadach
from meetflow.core.prompts import PromptBuilder, profile
from meetflow.web.app import create_app


class Протокол(MockLLM):
    """Разделы: одно предложение с опорой в записи, одно без опоры, заглушка; «Решения» пустые."""

    def _protocol(self, system, data):
        return {"sections": {
            "Участники": "Игнатов Иван, Петрова Анастасия, Сидоров Пётр.",
            "Обсуждение": ("**Склад:** По складу всё идёт по плану. Выгрузку остатков склада отправили. "
                           "Поставщик бетона сменился на прошлой неделе."),
            "Решения": "",
            "Открытые вопросы": "Вопросов не возникло."}}


def _сборка(make_pipe, store, project, date="2026-10-01", gen=None, text=TRANSCRIPT):
    p = make_pipe(gen=gen or Протокол())
    mid = store.insert("meetings", project_id=project, date=date, label="в")
    p.ingest(project, mid, f"t {date[8:10]}.{date[5:7]}.{date[:4]}.txt", text.encode())
    rep = p.run(project, mid)
    return p, mid, rep


# --- текст протокола --------------------------------------------------------------------------------------------------

def test_предложение_без_опоры_и_заглушка_не_пишутся(make_pipe, store, project):
    p, mid, rep = _сборка(make_pipe, store, project)
    md = store.get("meetings", mid)["protocol_md"]
    assert "По складу всё идёт по плану." in md
    assert "Поставщик бетона" not in md, "предложение без опоры в записи не пишется"
    assert "Вопросов не возникло" not in md and "Не обсуждалось" not in md
    assert "## Решения" not in md and "## Открытые вопросы" not in md, "раздел без строк не пишется"
    assert "Решили" not in md and "Открытый вопрос:" not in md
    assert "убрано" in rep.text_check and any("Поставщик бетона" in x for x in rep.text_removed)


def test_подсказка_блоками_и_без_решили():
    pb = PromptBuilder("секретарь", profile("generic"))
    system, _ = pb.protocol(["Обсуждение"], "запись")
    assert "«**Предмет:** суть»" in system and "не длиннее 400 знаков" in system
    assert "Слово «Решили»" in system and "не пиши" in system.lower()


# --- таблица задач --------------------------------------------------------------------------------------------------

def test_таблица_семь_колонок_и_раздел_поставленных(make_pipe, store, project):
    _, mid, _ = _сборка(make_pipe, store, project)
    md = store.get("meetings", mid)["protocol_md"]
    assert "## Поставленные на встрече" in md
    assert "| № | Задача | Статус | Ответственный | Срок | Дата постановки | Откуда |" in md
    строки = [ln for ln in md.splitlines() if ln.startswith("| 1 |")]
    assert строки and "в работе" in строки[0] and "01.10.2026" in строки[0] and "запись" in строки[0]


def test_горизонт_две_встречи_оперативные_снятые(make_pipe, store, project):
    старая = store.insert("meetings", project_id=project, date="2026-09-17", label="с")
    прошлая = store.insert("meetings", project_id=project, date="2026-09-24", label="п")
    t_old = store.insert("tasks", project_id=project, description="Задача позапрошлой встречи", status="active",
                         source_meeting_id=старая, date_set="2026-09-17")
    t_prev = store.insert("tasks", project_id=project, description="Задача прошлой встречи", status="active",
                          source_meeting_id=прошлая, date_set="2026-09-24", due_date="2026-09-30")
    t_op = store.insert("tasks", project_id=project, description="Долгая оперативная задача", status="active",
                        source_meeting_id=старая, date_set="2026-09-17", operational=1)
    t_drop = store.insert("tasks", project_id=project, description="Снятая задача прошлой встречи", status="dropped",
                          source_meeting_id=прошлая, date_set="2026-09-24", date_closed="2026-09-25")
    _, mid, _ = _сборка(make_pipe, store, project)
    md = store.get("meetings", mid)["protocol_md"]
    assert "Задача прошлой встречи" in md and "Задача позапрошлой встречи" not in md
    assert "Снятая задача" not in md and "## Снято по встрече" not in md
    строка = next(ln for ln in md.splitlines() if "Задача прошлой встречи" in ln)
    assert "в работе — просрочена" in строка and "| реестр |" in строка and "24.09.2026" in строка
    оп = md.split("## Оперативные задачи", 1)
    assert len(оп) == 2 and "Долгая оперативная задача" in оп[1] and "| 1 |" in оп[1]
    assert {t_old, t_prev, t_op, t_drop}


def test_статус_на_дату_встречи():
    t = {"status": "done", "date_closed": "2026-10-03", "due_date": "2026-10-10", "date_set": "2026-10-01"}
    from datetime import date
    assert tablica_zadach.статус_задачи(t, date(2026, 10, 1)) == "в работе; выполнена 03.10.2026"
    assert tablica_zadach.статус_задачи(t, date(2026, 10, 5)) == "выполнена 03.10.2026"


def test_подсказка_оперативной_только_подсказка():
    t = {"status": "active", "date_set": "2026-10-01", "due_date": "2026-10-20", "description": "Сверка"}
    assert tablica_zadach.похоже_на_оперативную(t, 0)
    assert not tablica_zadach.похоже_на_оперативную({**t, "due_date": "2026-10-10"}, 2)
    assert tablica_zadach.похоже_на_оперативную({**t, "due_date": None}, 6)


def test_раздел_секретаря_ставит_пометку_ручное_главнее(make_pipe, store, project):
    a = store.insert("tasks", project_id=project, description="Подготовить сверку расчётов с поставщиком бетона",
                     status="active", date_set="2026-09-24")
    b = store.insert("tasks", project_id=project, description="Обновить график поставки арматуры на объект",
                     status="active", date_set="2026-09-24")
    store.insert("task_history", task_id=b, source="web_form", evidence_quote="оперативная: пометка снята",
                 changed_by="админ", at="2026-09-25T10:00:00")
    заметки = ("Протокол встречи 01.10.2026\n\n| № | Задача | Ответственный |\n|---|---|---|\n"
               "| | Оперативные задачи | |\n| 1 | Подготовить сверку расчётов с поставщиком бетона | Петрова |\n"
               "| 2 | Обновить график поставки арматуры на объект | Сидоров |\n")
    p = make_pipe(gen=Протокол())
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.ingest(project, mid, "Заметки секретаря 01.10.2026.txt", заметки.encode())
    store.q("UPDATE sources SET kind='notes' WHERE name LIKE 'Заметки%'")
    p.run(project, mid)
    assert store.get("tasks", a)["operational"] == 1 and store.get("tasks", b)["operational"] == 0
    hist = store.q("SELECT * FROM task_history WHERE task_id=? AND source='secretary_table'", (a,))
    assert hist and "протокол секретаря" in hist[0]["evidence_quote"]
    assert not store.q("SELECT id FROM tasks WHERE description LIKE 'Оперативные задачи%'")


# --- пометка в реестре -------------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"))
    c = TestClient(app, raise_server_exceptions=False)
    c.pid = c.post("/api/projects", json={"name": "Пилот"}, headers={"X-User-Role": "project_admin"}).json()["id"]
    return c


def test_пометка_оперативная_одним_нажатием(client):
    h = {"X-User-Role": "project_admin"}
    mid = client.post(f"/api/projects/{client.pid}/meetings", json={"date": "2026-10-01"}, headers=h).json()["id"]
    client.post(f"/api/meetings/{mid}/sources", files={"file": ("Расшифровка 01.10.2026.txt", TRANSCRIPT.encode())},
                headers=h)
    client.post(f"/api/meetings/{mid}/run", headers=h)
    tid = client.get(f"/api/projects/{client.pid}/tasks", headers=h).json()[0]["id"]
    r = client.post(f"/api/tasks/{tid}/operational", json={"on": True}, headers=h)
    assert r.status_code == 200 and r.json()["operational"] == 1
    row = next(t for t in client.get(f"/api/projects/{client.pid}/tasks", headers=h).json() if t["id"] == tid)
    assert row["operational"] == 1 and row["operational_hint"] is False
    hist = client.get(f"/api/tasks/{tid}/history", headers=h)
    if hist.status_code == 200:
        assert any("оперативная: отмечена" in (x.get("evidence_quote") or "") for x in hist.json())
    assert client.post(f"/api/tasks/{tid}/operational", json={"on": False},
                       headers={"X-User-Role": "member"}).status_code == 403
    assert client.post(f"/api/tasks/{tid}/operational", json={"on": False}, headers=h).json()["operational"] == 0


# --- план: «Из материалов» в конце -------------------------------------------------------------------------------------

def test_план_из_материалов_в_конце(make_pipe, store, project):
    p = make_pipe()
    mid = store.insert("meetings", project_id=project, date="2026-10-08", label="в")
    store.insert("sources", meeting_id=mid, name="График отпусков", kind="other",
                 text="Отпуска сотрудников отдела закупок на ноябрь 2026 года.\nИванов — 3–14 ноября.")
    md = p.build_plan(project, mid)["markdown"]
    хвост = md.rsplit("## Из материалов", 1)
    assert len(хвост) == 2 and "Материал «График отпусков»: Отпуска сотрудников отдела закупок" in хвост[1]
    assert md.rstrip().endswith(хвост[1].rstrip())
