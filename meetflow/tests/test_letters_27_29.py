"""Письма 27–29 ветки meeting-registry (находки Планёрки 0613e95 и ERP cd51043, 90d7bf1).
Тесты написаны до правки."""
import json

import pytest

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.people import Team
from meetflow.core.types import Person


# 27.3 — хвост сверяется списком окончаний: «Антон» не становится Антоновым
def test_first_name_is_not_surname_with_ov():
    m = Team([Person("Антонов Пётр", id=1), Person("Гаврилов Павел", id=2)]).find("Антон")
    assert m.person is None or m.person.id != 1


# 29.1 — страж: «Петрович» не совпадает с «Петров Иван» строго
def test_patronymic_word_not_surname():
    m = Team([Person("Петров Иван", id=1)]).find("Петрович")
    assert m.person is None


# 27.4 — нет свободных частей имени: инициал не противоречие
def test_initial_without_free_parts_is_not_conflict():
    t = Team([Person("Иван", external=True, organization="ТМК", role="инженер", id=10), Person("Гаврилов Павел", id=2)])
    assert t.find("Иван П.").person.id == 10


# 29.2 — отчество — свободная часть имени («Мария Ч.» при «Игнатова Мария Чеславовна»)
def test_initial_matches_patronymic():
    t = Team([Person("Игнатова Мария Чеславовна", id=3), Person("Гаврилов Павел", id=2)])
    assert t.find("Мария Ч.").person.id == 3
    assert Team([Person("Петрова Марина", id=7)]).find("Марина М.").person is None    # страж прежний


# 27.2 / 28.3 — одна задача, исполнитель в разных падежах: одна карточка, не две
class Twice(MockLLM):
    def _extract(self, data):
        q = "Игнатов Иван: Соболевой подготовить отчёт по складу"
        return {"tasks": [{"description": "Подготовить отчёт по складу", "assignee": "Соболева", "quote": q},
                          {"description": "Подготовить отчёт по складу", "assignee": "Соболевой", "quote": q}]}


def test_same_task_case_variants_one_card(store, project, make_pipe):
    store.insert("people", project_id=project, full_name="Соболева Анна")
    store.insert("people", project_id=project, full_name="Соболева Ольга")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Twice())
    p.ingest(project, mid, "t 01.10.2026.txt", "[00:01:00] Игнатов Иван: Соболевой подготовить отчёт по складу\n".encode())
    # перевёрнут 03.10.26 по письму 30 оркестратора (решение владельца): задача сразу без исполнителя,
    # рядом карточка assign_person; выбор ставит исполнителя в ту же задачу
    p.run(project, mid)
    assert len(store.q("SELECT * FROM tasks")) == 1
    assert len(store.q("SELECT * FROM cards WHERE kind='assign_person'")) == 1
