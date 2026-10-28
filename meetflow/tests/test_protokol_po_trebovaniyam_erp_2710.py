"""Протокол MeetFlow по требованиям ERP (27.10.2026): исполнитель «я» из подписи голоса, отдел текстом, участники кодом,
укрупнение задач, `finish_reason` в журнале, проект записи из общей папки и перенос встречи, «сделать основной».

Повод — протокол MeetFlow 26.10.2026 (две записи в одном протоколе, все строки «не назначен», в «Участниках» человек,
которого во встрече нет). Данные вымышленные, модель — заглушка.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEAM, TRANSCRIPT
from meetflow.connectors.base import LLMResult
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import proekt_zapisi as pz
from meetflow.core import ukrupnenie_sborka, ukrupnenie_zadach as uz
from meetflow.core.gates import TaskGate
from meetflow.core.ispolnitel_golosom import берёт_на_себя, из_подписи
from meetflow.core.people import Team
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

ЛЮДИ = ["Игнатов Иван", "Петрова Анастасия", "Сидоров Пётр"]


# --- исполнитель «я» из подписи голоса (ERP fill_self_assigned_responsibles) ------------------------------------------

@pytest.mark.parametrize("строка, кто", [
    ("[00:02:00] Петрова Анастасия: Хорошо. Регламент склада я подготовлю к пятнице.", "Петрова Анастасия"),
    ("[00:02:00] Петрова Анастасия: Регламент склада подготовлю сама.", "Петрова Анастасия"),
    ("[00:02:00] Говорящий 2: Регламент склада я подготовлю к пятнице.", None),          # безличная метка
    ("[00:02:00] Кравцов Олег: Регламент склада я подготовлю к пятнице.", None),         # не из «Команды»
    ("[00:02:00] Петрова Анастасия: Регламент склада я буду смотреть.", None),           # намерение
    ("[00:02:00] Петрова Анастасия: Попрошу подготовить регламент склада.", None),       # передача поручения
    ("[00:02:00] Петрова Анастасия: Регламент склада мы подготовим.", None),             # «мы» — группа
    ("[00:02:00] Петрова Анастасия: Я подготовлю отчёт. А регламент склада — потом.", None),   # чужое предложение
])
def test_исполнитель_из_подписи(строка, кто):
    assert из_подписи(строка, "Подготовить регламент склада", ЛЮДИ) == кто


def test_ворота_ставят_исполнителя_по_голосу():
    src = SourceDoc("t", SourceKind.TRANSCRIPT,
                    "[00:01:00] Игнатов Иван: Что по регламенту?\n"
                    "[00:02:00] Петрова Анастасия: Регламент склада я подготовлю к пятнице.")
    team = Team([Person(n) for n in ЛЮДИ])
    g = TaskGate(team).check(TaskDraft("Подготовить регламент склада", None, line_no=1), src)
    assert g.accepted and g.assignee is not None and g.assignee.full_name == "Петрова Анастасия"


@pytest.mark.parametrize("формулировка, причина", [
    ("Разобраться с вопросом", "insignificant"),                       # мелочь без предмета — правилом
    ("Посмотреть", "insignificant"),                                    # обрывок
    ("Анастасия займётся регламентом склада", "third_person_retelling"),  # пересказ — под вопросом
])
def test_существенность_правилом(формулировка, причина):
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:02:00] Игнатов Иван: Петрова Анастасия, " + формулировка.lower())
    team = Team([Person(n) for n in ЛЮДИ])
    g = TaskGate(team).check(TaskDraft(формулировка, "Петрова Анастасия", line_no=0), src)
    assert причина in g.reasons


def test_берёт_на_себя_глагол_сильнее_буду():
    assert берёт_на_себя("буду делать табличку и добавлю строки")
    assert not берёт_на_себя("я думаю, что надо сделать")


# --- участники кодом, finish_reason, укрупнение — на сборке ---------------------------------------------------------

class Модель(MockLLM):
    """Заглушка: протокол пишет в «Участники» постороннего, ответ несёт finish_reason; поручения — заданные."""

    def __init__(self, tasks=None):
        super().__init__()
        self.tasks = tasks
        self.protocol_system = ""

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose="", deadline=None):
        if purpose == "protocol":
            self.protocol_system = system
        res = super().complete(system, user, json_mode=json_mode, temperature=temperature, purpose=purpose)
        return LLMResult(res.text, res.model, res.prompt_tokens, res.completion_tokens, res.cost_usd, res.seconds,
                         {"finish_reason": "stop"})

    def _extract(self, data):
        return {"tasks": self.tasks} if self.tasks is not None else super()._extract(data)

    def _protocol(self, system, data):
        out = super()._protocol(system, data)
        out["sections"]["Участники"] = "Игнатов Иван, Посторонний Человек"
        return out


def _сборка(store, project, meeting, theme, tmp_path, tasks=None, voice=True, text=TRANSCRIPT):
    gen = Модель(tasks)
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    meta = {"voice_names": {"Говорящий 1": "Игнатов Иван", "Говорящий 2": "Петрова Анастасия"}} if voice else {}
    store.insert("sources", meeting_id=meeting, name="запись 01.10.2026", kind="transcript", text=text,
                 digest="d" + str(meeting), meta=json.dumps(meta, ensure_ascii=False), created_at="2026-10-01T10:00:00")
    rep = p.run(project, meeting)
    return p, gen, rep


def test_участники_кодом_по_голосам(store, project, meeting, theme, tmp_path):
    p, gen, rep = _сборка(store, project, meeting, theme, tmp_path)
    proto = store.get("meetings", meeting)["protocol_md"]
    assert "## Участники\nИгнатов Иван, Петрова Анастасия." in proto
    assert "Посторонний" not in proto
    assert "- Участники" not in gen.protocol_system           # модель раздел не пишет
    assert rep.participants.startswith("участники кодом: 2")


def test_участники_без_голосов_как_раньше(store, project, meeting, theme, tmp_path):
    _p, gen, rep = _сборка(store, project, meeting, theme, tmp_path, voice=False)
    assert "- Участники" in gen.protocol_system and not rep.participants


def test_finish_reason_в_журнале(store, project, meeting, theme, tmp_path):
    _сборка(store, project, meeting, theme, tmp_path)
    строки = [json.loads(x) for x in (tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()]
    вызовы = [x for x in строки if x.get("purpose") in ("extract_tasks", "protocol")]
    assert вызовы and all(x.get("finish_reason") == "stop" and "chars_out" in x for x in вызовы)


ДВА = ("[00:01:00] Игнатов Иван: Начинаем.\n"
       "[00:02:00] Петрова Анастасия: График поставки труб я подготовлю к пятнице.\n"
       "[00:03:00] Петрова Анастасия: И график поставки труб я согласую с подрядчиком.\n"
       "[00:04:00] Сидоров Пётр: Отчёт по браку я отправлю завтра.\n")
ЗАДАЧИ = [{"description": "Подготовить график поставки труб", "assignee": None, "line": 1},
          {"description": "Согласовать график поставки труб с подрядчиком", "assignee": None, "line": 2},
          {"description": "Отправить отчёт по браку", "assignee": None, "line": 3}]


def test_укрупнение_по_предмету(store, project, meeting, theme, tmp_path):
    _p, _g, rep = _сборка(store, project, meeting, theme, tmp_path, tasks=ЗАДАЧИ, voice=False, text=ДВА)
    задачи = store.q("SELECT * FROM tasks WHERE source_meeting_id=? ORDER BY id", (meeting,))
    assert len(задачи) == 2, [t["description"] for t in задачи]
    assert задачи[0]["assignee"] == "Петрова Анастасия" and "график поставки труб" in задачи[0]["description"].lower()
    assert задачи[1]["assignee"] == "Сидоров Пётр"
    история = store.q("SELECT * FROM task_history WHERE task_id=? AND source=?", (задачи[0]["id"], uz.ИСТОЧНИК_ИСТОРИИ))
    assert история and история[0]["evidence_quote"].startswith("Объединено из: 1)")
    assert rep.ukrupnenie.startswith("укрупнение задач: объединено 1 в 1")


def test_укрупнение_выключателем(store, project, meeting, theme, tmp_path):
    store.set_setting("ukrupnenie_zadach", False)
    _p, _g, rep = _сборка(store, project, meeting, theme, tmp_path, tasks=ЗАДАЧИ, voice=False, text=ДВА)
    assert len(store.q("SELECT id FROM tasks WHERE source_meeting_id=?", (meeting,))) == 3
    assert rep.ukrupnenie == "укрупнение задач выключено"


def test_сведение_с_реестром(store, project, meeting, theme, tmp_path):
    from meetflow.core.registry import TaskRegistry
    old = TaskRegistry(store).add(project, "Обновить и разослать график поставки труб подрядчикам", "Петрова Анастасия",
                                  date_set="2026-09-20")
    _p, _g, rep = _сборка(store, project, meeting, theme, tmp_path, tasks=ЗАДАЧИ[:1], voice=False, text=ДВА)
    assert not store.q("SELECT id FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert store.get("tasks", old)["status"] == "active" and "сведено с открытыми задачами реестра 1" in rep.ukrupnenie


def test_укрупнение_не_трогает_задачу_с_карточкой():
    a = {"description": "Подготовить график поставки труб", "responsible": "Петрова Анастасия", "нужна_карточка": True}
    b = {"description": "Согласовать график поставки труб", "responsible": "Петрова Анастасия"}
    итог, счёт = uz.укрупнить([a, b])
    assert len(итог) == 2 and счёт["объединено"] == 0


# --- проект записи из общей папки, перенос встречи --------------------------------------------------------------------

@pytest.fixture
def справочник(store):
    erp = store.insert("projects", name="Проект ERP", theme="erp_rollout")
    склад = store.insert("projects", name="Адресный учёт на складе", theme="erp_rollout")
    марк = store.insert("projects", name="Маркировка ячеек", theme="erp_rollout", parent_id=склад)
    return {"erp": erp, "склад": склад, "марк": марк}


@pytest.mark.parametrize("путь, ключ", [
    ("Встреча ERP 15.10.2026 15.06.m4a", "erp"),                                   # корень — по имени файла
    ("Адресный учет на складе/маркировка_2026_10_26_16_32_51.m4a", "склад"),        # подпапка проекта, е = ё
    ("Адресный учет на складе/Маркировка ячеек/запись 26.10.2026.m4a", "марк"),     # подпапка подпроекта
    ("запись 20.10.2026.m4a", None),                                               # не назван — не определён
])
def test_проект_файла(store, справочник, tmp_path, путь, ключ):
    общая = tmp_path / "Встречи по всем проектам"
    файл = общая / путь
    файл.parent.mkdir(parents=True, exist_ok=True)
    файл.write_bytes(b"x")
    итог = pz.проект_файла(store, справочник["erp"], общая, файл)
    assert итог["project_id"] == (справочник[ключ] if ключ else None), итог


def test_своя_папка_проекта_корень_его(store, справочник, tmp_path):
    своя = tmp_path / "Склад"
    (своя).mkdir()
    (своя / "запись 20.10.2026.m4a").write_bytes(b"x")
    assert pz.проект_файла(store, справочник["склад"], своя, своя / "запись 20.10.2026.m4a")["project_id"] == \
        справочник["склад"]


def test_два_проекта_в_имени_спор(store, справочник, tmp_path):
    общая = tmp_path / "Встречи по всем проектам"
    общая.mkdir()
    f = общая / "Проект ERP и Адресный учёт на складе 20.10.2026.txt"
    f.write_bytes(b"x")
    итог = pz.проект_файла(store, справочник["erp"], общая, f)
    assert итог["project_id"] is None and set(итог["disputed"]) == {справочник["erp"], справочник["склад"]}


SUPER = {"X-User-Role": "super_admin", "X-User-Name": "admin"}
PASSWORD = "пароль-для-теста"   # тестовое значение учётной записи стенда, не настоящий пароль


@pytest.fixture
def client(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    app.state.accounts.save("admin", "Админ", "super_admin", PASSWORD)
    c.pid = c.post("/api/projects", json={"name": "Склад"}, headers=SUPER).json()["id"]
    c.erp = c.post("/api/projects", json={"name": "Проект ERP"}, headers=SUPER).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=SUPER)
    return c


def _папка(c, d):
    url = f"/api/projects/{c.pid}/settings/watch-folder"
    body = {"path": str(d), "path_repeat": str(d)}
    r = c.post(url, json=body, headers=SUPER)
    if r.status_code == 200 and r.json().get("confirm_needed"):
        r = c.post(url, json={**body, "confirm": True, "login": "admin", "current_password": PASSWORD}, headers=SUPER)
    assert r.status_code == 200, r.text


def _два_прохода(c):
    svc = c.app.state.intake
    svc._intakes.pop(c.pid, None)
    svc.scan_project(c.pid, date(2026, 10, 27))
    return svc.scan_project(c.pid, date(2026, 10, 27))


def test_общая_папка_корень_не_определён_карточка_и_перенос(client, tmp_path):
    общая = tmp_path / "Встречи по всем проектам"
    общая.mkdir()
    _папка(client, общая)
    (общая / "Расшифровка 20.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    (общая / "Встреча ERP 15.10.2026.txt").write_text(TRANSCRIPT.replace("Добрый день", "Здравствуйте"),
                                                         encoding="utf-8")
    r = _два_прохода(client)
    st = client.app.state.store
    assert sorted(r["ingested"]) == ["Встреча ERP 15.10.2026.txt", "Расшифровка 20.10.2026.txt"]
    # Перевёрнуто 28.10.2026 (Доработка 2, решение владелицы): было — встреча «проект не определён» в проекте папки и
    # карточка выбора проекта. Стало — проект решает содержание записи: склад назван в трёх строках, второго проекта нет,
    # встреча уходит в «Склад»; карточки выбора нет, встреч «проект не определён» нет.
    assert not st.q("SELECT * FROM meetings WHERE project_pending=1")
    assert not st.q("SELECT * FROM cards WHERE kind=? AND status='open'", (pz.КАРТОЧКА,))
    склад = st.q("SELECT * FROM meetings WHERE date='2026-10-20'")
    assert len(склад) == 1 and склад[0]["project_id"] == client.pid
    assert склад[0]["project_how"].startswith("по содержанию записи: «Склад», упоминаний 3")
    # имя файла назвало ERP — встреча в ERP по имени; содержание говорит о складе — карточка о расхождении, без переноса
    erp = st.q("SELECT * FROM meetings WHERE project_id=?", (client.erp,))
    assert len(erp) == 1 and erp[0]["date"] == "2026-10-15" and erp[0]["project_how"].startswith("название в имени файла")
    расход = st.q("SELECT * FROM cards WHERE kind='project_mismatch' AND status='open'")
    assert len(расход) == 1 and расход[0]["meeting_id"] == erp[0]["id"]
    # перенос встречи в «Общие встречи» — с экрана, вместе с задачами (`move-project`)
    общие = pz.общие_встречи(st)
    h = {"X-Requested-With": "erp-webapp", "X-User-Id": str(st.insert("accounts", login=None, full_name="Орлова Анна",
                                                                       role="super_admin", password_hash="", active=1,
                                                                       confirmed=1))}
    out = client.post(f"/meetings/{склад[0]['id']}/move-project", json={"project_id": общие, "rebuild": False},
                      headers=h)
    assert out.status_code == 200, out.text
    assert st.get("meetings", склад[0]["id"])["project_id"] == общие


def test_перенести_встречу_вместе_с_задачами(store, справочник):
    from meetflow.core.registry import TaskRegistry
    mid = store.insert("meetings", project_id=справочник["склад"], date="2026-10-15")
    tid = TaskRegistry(store).add(справочник["склад"], "Проверить пломбы", "Сидоров Пётр", mid, "", None, "2026-10-15")
    out = pz.перенести_встречу(store, mid, справочник["erp"], "Орлова Анна")
    assert out == {"from": справочник["склад"], "to": справочник["erp"], "tasks": 1}
    assert store.get("tasks", tid)["project_id"] == справочник["erp"]
    assert store.q("SELECT * FROM task_history WHERE task_id=? AND source='meeting_move'", (tid,))
    assert store.q("SELECT * FROM decisions WHERE project_id=?", (справочник["erp"],))


def test_горизонт_таблицы_только_свой_проект(store, справочник):
    """Две встречи разных проектов: таблица 26.10 не берёт задачи встречи 15.10 другого проекта (замечание 27.10.2026)."""
    from meetflow.core import tablica_zadach
    from meetflow.core.registry import TaskRegistry
    reg = TaskRegistry(store)
    m15 = store.insert("meetings", project_id=справочник["erp"], date="2026-10-15")
    m26 = store.insert("meetings", project_id=справочник["склад"], date="2026-10-26")
    reg.add(справочник["erp"], "Задача встречи ERP", "Сидоров Пётр", m15, "", None, "2026-10-15")
    reg.add(справочник["склад"], "Разметить ячейки", "Петрова Анастасия", m26, "", None, "2026-10-26")
    строки = tablica_zadach.строки_встречи(store, store.get("meetings", m26), lambda t: "")
    assert [с.задача for с in строки] == ["Разметить ячейки"]


# --- «Сделать основной» ---------------------------------------------------------------------------------------------

def _маршруты(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": {"main": {"kind": "openai", "url": "http://main", "model": "m"},
                                              "spare": {"kind": "openai", "url": "http://spare", "model": "s"}},
                                "roles": {"generate": ["main", "spare"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    return path


def test_сделать_основной_во_время_сборки(tmp_path, monkeypatch):
    from meetflow.web.app import create_app
    _маршруты(tmp_path, monkeypatch)
    app = create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="it_product")
    mid = st.insert("meetings", project_id=pid, date="2026-10-26")
    замок = app.state.pipe._meeting_lock(mid)
    замок.acquire()
    try:
        r = c.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=SUPER)
    finally:
        замок.release()
    assert r.status_code == 200 and r.json()["roles"]["generate"][0]["name"] == "spare"
    assert st.q("SELECT id FROM build_queue WHERE meeting_id=?", (mid,))        # пересборка поставлена
    assert st.q("SELECT id FROM cards WHERE title LIKE 'Модель роли%'")


def test_сделать_основной_файл_занят_ответ_словами(tmp_path, monkeypatch):
    from meetflow.connectors import llm_routes
    from meetflow.web.app import create_app
    _маршруты(tmp_path, monkeypatch)
    app = create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)

    def занят(*_a, **_k):
        raise PermissionError(13, "файл открыт другим процессом")
    monkeypatch.setattr(llm_routes.os, "replace", занят)
    monkeypatch.setattr(llm_routes.time, "sleep", lambda *_a: None)
    r = c.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=SUPER)
    assert r.status_code == 409 and "Файл моделей сейчас не записать" in r.json()["detail"]


def test_замена_файла_повторяет_при_занятом(tmp_path, monkeypatch):
    from meetflow.connectors import llm_routes
    a, b = tmp_path / "a.tmp", tmp_path / "b.json"
    a.write_text("{}", encoding="utf-8")
    попытки = []
    настоящий = llm_routes.os.replace

    def иногда(x, y):
        попытки.append(1)
        if len(попытки) < 3:
            raise PermissionError(13, "занят")
        return настоящий(x, y)
    monkeypatch.setattr(llm_routes.os, "replace", иногда)
    monkeypatch.setattr(llm_routes.time, "sleep", lambda *_a: None)
    llm_routes._replace(a, b)
    assert b.exists() and len(попытки) == 3


def test_odna_vstrecha_bez_proekta_na_datu_2810(client, tmp_path, monkeypatch):
    """28.10.2026, отчёт ЛМ 7ede6e3: запись 28.10 из корня общей папки дала две пустые встречи «проект не определён» —
    пока запись распознавалась, файл оставался в папке, и каждый проход заводил новую встречу. Теперь одна на дату."""
    общая = tmp_path / "Встречи по всем проектам"
    общая.mkdir()
    _папка(client, общая)
    (общая / "Расшифровка 21.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    pipe = client.app.state.pipe
    monkeypatch.setattr(pipe, "ingest", lambda *a, **k: {"status": "held"})   # файл остаётся в папке, как при распознавании
    _два_прохода(client)
    _два_прохода(client)
    st = client.app.state.store
    # перевёрнуто 28.10.2026 (Доработка 2): встреча неузнанной записи — в «Общих встречах», одна на файл, а не на дату
    assert len(st.q("SELECT id FROM meetings WHERE project_id=? AND date='2026-10-21' AND label=?",
                    (pz.общие_встречи(st), "из папки-приёмника: Расшифровка 21.10.2026.txt"))) == 1
