"""Пакет 01 ветки meeting-registry (письмо 05, 03.10.26): пункты 01/6, 01/15,
01/16. Случаи взяты из самопроверок пакета; правило п. 16 — по решению
владельца 03.10.26 («молча только с тем же именем»), не как в пакете."""
import pytest

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.negation import NegationRule
from meetflow.core.people import Team
from meetflow.core.types import Person


# 01/15 — признак выполнения морфологией, список остаётся запасным путём
@pytest.mark.parametrize("phrase,fact", [
    ("Экономику проекта посчитали.", True),
    ("Смету пересчитали вчера.", True),
    ("Счёт оплачен.", True),
    ("Договор согласован.", True),
    ("Назаров сказал, что подумает.", False),
    ("Игнатов пообещал отправить завтра.", False),
    ("Будем считать экономику.", False),
    ("Считаем экономику.", False),
    ("Экономику проекта не посчитали.", False),
    ("Посчитали ли экономику?", False),
])
def test_done_by_morphology(phrase, fact):
    assert NegationRule().check(phrase).states_fact is fact


# 01/6 — срок только из слов встречи
class Due(MockLLM):
    def __init__(self, due):
        super().__init__()
        self.due = due

    def _extract(self, data):
        return {"tasks": [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                           "due_date": self.due,
                           "quote": "Игнатов Иван: Петрова Анастасия, подготовьте регламент склада до 10.10"}]}


@pytest.mark.parametrize("due,kept", [("31.12.2030", None), ("10.10", "10.10")])
def test_due_only_if_said(store, project, make_pipe, due, kept):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Due(due))
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада до 10.10\n".encode())
    p.run(project, mid)
    assert [t["due_date"] for t in store.q("SELECT due_date FROM tasks")] == [kept]


# 01/16 — искажённая фамилия: молча только с тем же именем (решение владельца 03.10.26)
TEAM = Team([Person("Чистякова Марина", id=1), Person("Гаврилов Павел", id=2), Person("Лапшов Михаил", id=3),
             Person("Сергеев Пётр", id=4), Person("Кузнецов Сергей", id=5)])


def test_distorted_surname_with_same_name_is_fixed():
    m = TEAM.find("Чистяка Марина")
    assert m.person is not None and m.person.id == 1


@pytest.mark.parametrize("mention,cand", [
    ("Чистяка", 1),               # без имени — кандидат, не подстановка
    ("Иван Гаврилов", 2),          # имя противоречит фамилии — кандидат
    ("Лапшав Михаил", 3),         # сходство 0,80 — кандидат
])
def test_distorted_surname_otherwise_candidate(mention, cand):
    m = TEAM.find(mention)
    assert m.person is None and [p.id for p in m.candidates] == [cand]


def test_first_name_not_matched_to_surname():
    # перевёрнут 03.10.26 правилом «один человек или два»: «Сергей» — рабочий ключ единственного
    # Сергея (Кузнецов), назначается; «Сергеев» по имени по-прежнему не находится
    m = TEAM.find("Сергей")
    assert m.person is not None and m.person.id == 5 and 4 not in [p.id for p in m.candidates]


@pytest.mark.parametrize("phrase", ["Регламент склада отменили.", "Задачу сняли.", "Отказались от регламента."])
def test_cancellation_is_not_done(phrase):
    """Найдено при переносе: морфология видит в «отменили» прошедшее совершенное —
    без исключения снятие читалось как выполнение."""
    n = NegationRule()
    assert not n.check(phrase).states_fact and n.states_removal(phrase)


@pytest.mark.parametrize("phrase", ["Заявку поставщика отклонили.", "Договор аннулировали.", "Работы прекратили.",
                                    "Письмо отозвали."])
def test_rejection_verbs_are_not_done(phrase):
    """Список глаголов отмены ветки meeting-registry (письмо 12) шире нашего: без них
    «отклонили», «аннулировали» тоже читались как выполнение."""
    assert not NegationRule().check(phrase).states_fact
