"""Решение владельца 15.10.26 (вечер, через «Мониторинг»): фразы с отрицанием, вопросом, условием и намерением
отсеиваются ДО заведения задачи «под вопросом» — правило отрицаний сильнее решения 15.10 о сомнительных задачах.
Такая фраза в реестр не идёт; ждёт в карточке «задача не заведена», как до 15.10. Намерение — говорящего о себе
(«буду», «будем», «планирую», «собираюсь», «попробую», «начну»): «нужно / надо» с адресатом — поручение, не отсеивается.
Тесты написаны до правки и падали (фразы уходили в реестр под вопросом)."""
import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


class Say(MockLLM):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def _extract(self, data):
        return {"tasks": self.items}


@pytest.fixture
def env(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    for n in ("Гаврилов Павел", "Петрова Анастасия"):
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n, "confirm_new": True}, headers=H)
    c.app_ = app
    return c


def run(c, line, desc, who="Петрова Анастасия"):
    c.app_.state.pipe.gen = Say([{"description": desc, "assignee": who, "quote": line}])
    mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H,
           files={"file": ("t 01.10.2026.txt", f"[00:01:00] {line}\n".encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)
    tasks = c.get(f"/api/projects/{c.pid}/tasks", headers=H).json()
    cards = c.get(f"/api/projects/{c.pid}/cards", headers=H).json()
    return tasks, cards


@pytest.mark.parametrize("line, desc", [
    ("Гаврилов Павел: Мы не будем сейчас настраивать интеграцию с банком", "Настроить интеграцию с банком"),
    ("Гаврилов Павел: Отменять поставку не будем", "Отменить поставку"),
    ("Гаврилов Павел: Петрова Анастасия, а вы сможете подготовить регламент склада?", "Подготовить регламент склада"),
    ("Гаврилов Павел: Если успеем, Петрова Анастасия подготовит отчёт по складу", "Подготовить отчёт по складу"),
    ("Петрова Анастасия: Я планирую посмотреть остатки по складу", "Посмотреть остатки по складу"),
])
def test_filtered_before_doubt(env, line, desc):
    tasks, cards = run(env, line, desc)
    assert tasks == [], "отрицание, вопрос, условие, намерение не заводятся даже «под вопросом»"
    assert not [x for x in cards if x["kind"] == "task_doubt"]
    # как у Планёрки (ddfa618): ни задачи, ни карточки — строкой в журнал разбора
    assert not [x for x in cards if x["kind"] == "held_task"], "отсеянное не идёт и в карточку"
    triage = [r for r in env.app_.state.pipe.journal.records if r.get("purpose") == "triage"]
    assert triage and triage[-1]["verdict"] == "отсеяно" and triage[-1]["reasons"]


def test_need_with_addressee_is_still_a_task(env):
    tasks, _ = run(env, "Гаврилов Павел: Петрова Анастасия, нужно подготовить отчёт по складу",
                   "Подготовить отчёт по складу")
    assert len(tasks) == 1


@pytest.mark.parametrize("line, desc, is_task", [
    # ответ владельца 16.10.26: «буду / будем / планирую / собираюсь / начну» — намерение; совершенный вид — задача;
    # с адресатом или повелительным глаголом — не намерение («наверное» поручение не отсеивает — дефект Планёрки)
    ("Гаврилов Павел: Петрова Анастасия, подготовь отчёт, наверное к пятнице", "Подготовить отчёт", True),
    ("Петрова Анастасия: Я сделаю отчёт по складу к пятнице", "Сделать отчёт по складу", True),
    ("Петрова Анастасия: Подготовлю отчёт к пятнице", "Подготовить отчёт", True),
    ("Гаврилов Павел: Петрова Анастасия, будем готовить отчёт по складу", "Подготовить отчёт по складу", True),
    ("Петрова Анастасия: Буду готовить отчёт по складу", "Подготовить отчёт по складу", False),
    ("Петрова Анастасия: Начну сверку остатков на следующей неделе", "Сверить остатки", False),
])
def test_intent_answer_16_10(env, line, desc, is_task):
    tasks, _ = run(env, line, desc)
    assert bool(tasks) == is_task
