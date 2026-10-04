"""Независимая проверка MeetFlow ветвью meeting-registry (этап 5 плана сведения, 03.10.26).

Код MeetFlow только импортируется и вызывается: в его папку ничего не пишется — ни база
(всё в памяти), ни кеш Python (dont_write_bytecode, запуск с -p no:cacheprovider).
Каждый тест проверяет ИСПРАВЛЕННОЕ поведение по письмам 01 и 02. До правок ветки MeetFlow
тест падает — это и есть подтверждение дефекта; после правки проходит.

Запуск:  python -m pytest -q -p no:cacheprovider   (из этой папки)
Путь к MeetFlow — переменная MEETFLOW_PATH, по умолчанию соседняя папка meetflow
в общем репозитории MeetingFlow, иначе папка ITMO_project lead рядом.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [os.path.join(_HERE, "..", "..", "meetflow"),  # общий репозиторий MeetingFlow
               os.path.join(_HERE, "..", "..", "..", "ITMO_project lead", "meetflow-framework")]
MEETFLOW = os.environ.get("MEETFLOW_PATH") or next(
    (p for p in _CANDIDATES if os.path.isdir(os.path.join(p, "meetflow"))), _CANDIDATES[0])
sys.path.insert(0, MEETFLOW)
os.environ.setdefault("MEETFLOW_LLM", "mock")

import pytest  # noqa: E402

from meetflow.connectors.base import LLMConnector  # noqa: E402
from meetflow.connectors.llm_mock import MockLLM  # noqa: E402
from meetflow.connectors.registry import default_registry  # noqa: E402
from meetflow.core.config import load_theme  # noqa: E402
from meetflow.core.pipeline import MeetingPipeline  # noqa: E402
from meetflow.core.store import Store  # noqa: E402
from meetflow.core.types import LLMResult  # noqa: E402

TEAM = ["Игнатов Иван", "Петрова Анастасия", "Сидоров Пётр", "Лаптева Ольга", "Чистякова Марина", "Воронова Марина"]
EMPTY = {"extract_tasks": {"tasks": []}, "closing_check": {"closed": []}, "protocol": {"sections": {}},
         "units": {"items": []}, "units_close": {"closed": []}, "verify": {"findings": []}}


class Scripted(LLMConnector):
    """Модель по сценарию: ответ по назначению вызова. Позволяет проверить код, а не настроение модели."""
    name = "scripted"
    model = "scripted"
    profile = "generic"

    def __init__(self, fn=None, costs=None):
        self.fn = fn or (lambda pu, sy, us: None)
        self.costs = costs or {}
        self.calls = []

    def worst_call_usd(self, prompt_chars):
        """Худший случай одного вызова — как у настоящих подключений с известной ценой и потолком ответа
        (MeetFlow 7440f82: цена из каталога × 4096 токенов). Без этого тест требовал знать цену, которой нет
        ни в запросе, ни в каталоге (письмо MeetFlow после 7440f82, 03.10.26). Нет цен — None: худший случай
        неизвестен, как у заглушки."""
        return max(self.costs.values()) if self.costs else None

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose=""):
        self.calls.append((purpose, system, user))
        out = self.fn(purpose, system, user)
        if out is None:
            out = EMPTY.get(purpose, {})
        if isinstance(out, Exception):
            raise out
        txt = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return LLMResult(txt, "scripted", 1, 1, self.costs.get(purpose, 0.0), 0.0)


class Env:
    def __init__(self, theme="it_product", date="2026-10-01", gen=None, team=TEAM):
        self.th = load_theme(theme)
        self.s = Store(":memory:")
        self.pid = self.s.insert("projects", name="P", theme=self.th.id)
        for n in team:
            self.s.insert("people", project_id=self.pid, full_name=n)
        self.mid = self.s.insert("meetings", project_id=self.pid, date=date, label="m")
        self.gen = gen or MockLLM()
        self.p = MeetingPipeline(self.th, self.s, default_registry(), self.gen, self.gen, None)

    def meeting(self, date, label="m2"):
        return self.s.insert("meetings", project_id=self.pid, date=date, label=label)

    def src(self, text, mid=None, name="Транскрибация.txt"):
        return self.p.ingest(self.pid, mid or self.mid, name, text.encode("utf-8"))

    def run(self, mid=None):
        return self.p.run(self.pid, mid or self.mid)

    def tasks(self, status="all"):
        return self.p.reg.list(self.pid, None) if status == "all" else self.p.reg.list(self.pid)

    def cards(self):
        return self.p.cards.list(self.pid)

    def prior(self, items, date="2026-09-01"):
        m0 = self.meeting(date, "prior")
        for desc, who in items:
            self.p.reg.add(self.pid, desc, who, m0, "q", "", date)
        return m0


def assert_task_first(e, min_candidates=0):
    """Правило владельца 03.10.26 (документ 14): спорное имя — задача сразу без исполнителя, рядом карточка,
    привязанная к этой задаче. Молчаливой подстановки нет."""
    tasks = e.tasks()
    assert len(tasks) == 1, f"задача должна завестись сразу: {tasks}"
    assert not tasks[0]["assignee"], f"исполнитель подставлен молча: {tasks[0]['assignee']}"
    cards = [c for c in e.cards() if c["payload"].get("task_id") == tasks[0]["id"]]
    assert cards, "нет карточки, привязанной к задаче"
    assert len(cards[0]["payload"].get("candidates") or []) >= min_candidates, cards[0]["payload"]


@pytest.fixture
def env():
    return Env
