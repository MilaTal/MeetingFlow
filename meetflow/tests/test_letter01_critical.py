"""Письмо 01 ветки meeting-registry (03.10.26), пять критичных пунктов.
Каждый тест написан до правки и до неё падал (план сведения 09: тест до
правки, одна правка за раз)."""
import json

import httpx
import pytest

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.llm_ollama import OllamaLLM
from meetflow.connectors.vision_ollama import OllamaVision

PROXY_ENV = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


# 01/1 — системный прокси не должен видеть текст встречи
@pytest.mark.security
@pytest.mark.parametrize("make", [lambda: OllamaLLM(model="m")._client(),
                                  lambda: OllamaVision(model="m")._client()])
def test_local_model_ignores_system_proxy(monkeypatch, make):
    for k in PROXY_ENV:
        monkeypatch.setenv(k, "http://proxy.invalid:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    with make() as c:
        pool = c._transport_for_url(httpx.URL("http://localhost:11434/api/chat"))
        assert pool is c._transport                       # не прокси-маршрут из окружения
        assert not c._mounts or all(v is None for v in c._mounts.values())


# 01/2 — массовое закрытие без человека
TASKS = ["Подготовить регламент склада", "Отправить выгрузку остатков", "Согласовать график поставок",
         "Проверить отчёт браку продукции"]
LINES = ["Регламент склада готов, сделано.", "Выгрузку остатков отправил, сделано.",
         "График поставок согласовал, сделано.", "Отчёт по браку продукции проверен, сделано."]


def _closing_meeting(store, project, make_pipe, n_lines, mdate="2026-10-01", set_date="2026-09-01"):
    p = make_pipe()
    for t in TASKS:
        p.reg.add(project, t, "Игнатов Иван", date_set=set_date)
    mid = store.insert("meetings", project_id=project, date=mdate, label="встреча")
    text = "\n".join(f"[00:0{i}:00] Игнатов Иван: {ln}" for i, ln in enumerate(LINES[:n_lines], 1))
    p.ingest(project, mid, f"t {mdate[8:]}.{mdate[5:7]}.{mdate[:4]}.txt", text.encode())
    return p, mid, p.run(project, mid)


def test_mass_closing_goes_to_one_card(store, project, make_pipe):
    p, mid, rep = _closing_meeting(store, project, make_pipe, 4)
    assert [t["status"] for t in store.q("SELECT status FROM tasks")].count("done") == 0
    cards = store.q("SELECT * FROM cards WHERE kind='mass_closing'")
    assert len(cards) == 1 and len(json.loads(cards[0]["payload"])["closings"]) == 4


def test_few_closings_still_apply(store, project, make_pipe):
    p, mid, rep = _closing_meeting(store, project, make_pipe, 3)        # 3 из 4 — не больше трёх
    assert rep.tasks_closed == 3 and not store.q("SELECT * FROM cards WHERE kind='mass_closing'")


# 01/3 — ранняя встреча не закрывает задачу, поставленную позже
def test_earlier_meeting_does_not_close_later_task(store, project, make_pipe):
    p, mid, rep = _closing_meeting(store, project, make_pipe, 1, mdate="2026-09-01", set_date="2026-10-05")
    t = store.q("SELECT * FROM tasks WHERE description LIKE 'Подготовить регламент%'")[0]
    assert t["status"] == "active" and rep.tasks_closed == 0


# 01/4 — второе поручение из той же строки не теряется
class TwoFromOneLine(MockLLM):
    def __init__(self, second_who="Петрова Анастасия"):
        super().__init__()
        self.second_who = second_who

    def _extract(self, data):
        q = "Игнатов Иван: Петрова Анастасия, подготовьте регламент склада и отправьте выгрузку остатков"
        return {"tasks": [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия", "quote": q},
                          {"description": "Отправить выгрузку остатков", "assignee": self.second_who, "quote": q}]}


@pytest.mark.parametrize("second", ["Петрова Анастасия", "Сидоров Пётр"])
def test_second_task_from_same_line_kept(store, project, make_pipe, second):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=TwoFromOneLine(second))
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада и отправьте выгрузку остатков\n".encode())
    rep = p.run(project, mid)
    assert rep.tasks_added + rep.tasks_held == 2
    p.run(project, mid)                                    # повторный прогон не плодит копии
    assert len(store.q("SELECT * FROM tasks")) == rep.tasks_added


# 01/5 — отчёт о сделанном не становится задачей говорящему
class ReportAsTask(MockLLM):
    def _extract(self, data):
        return {"tasks": [{"description": "Подписать договор и отправить в бухгалтерию", "assignee": "Петрова Анастасия",
                           "quote": "Петрова Анастасия: Договор подписан, отправили в бухгалтерию."}]}


def test_report_of_done_is_not_assignment(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=ReportAsTask())
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Петрова Анастасия: Договор подписан, отправили в бухгалтерию.\n".encode())
    rep = p.run(project, mid)
    assert rep.tasks_added == 0 and rep.tasks_held == 1
    card = store.q("SELECT * FROM cards WHERE kind='held_task'")[0]
    assert "report_not_assignment" in json.loads(card["payload"])["reasons"]


def test_assignment_with_done_word_still_task(store, project, make_pipe):
    """Обратная сторона п. 5: поручение со словом «готов» рядом — задача."""
    class Assign(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                               "quote": "Игнатов Иван: Петрова Анастасия, подготовьте регламент склада, шаблон готов."}]}
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Assign())
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада, шаблон готов.\n".encode())
    assert p.run(project, mid).tasks_added == 1
