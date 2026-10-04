"""Имя и инициал (решение владельца 03.10.26, документ «13_Решение — имя и инициал»). Кейсы записаны до проверки кода."""

import pytest

from meetflow.core.people import Team
from meetflow.core.types import Person

TEAM = Team([Person("Чистякова Марина", id=1), Person("Воронова Марина", id=2), Person("Варламова Марина", id=3),
             Person("Костина Мария", id=4), Person("Назаров Константин", id=5), Person("Назаров Андрей", id=6)],
            diminutives={"маша": ["мария"]})


@pytest.mark.parametrize("mention,pid", [("Марина Ч.", 1), ("Маша К.", 4), ("Назаров К.", 5)])
def test_initial_one_fits_assigns(mention, pid):
    m = TEAM.find(mention)
    assert m.person is not None and m.person.id == pid, (mention, m)


@pytest.mark.parametrize("mention", ["Марина В.", "Назаров С."])
def test_initial_several_or_none_is_not_assigned(mention):
    assert TEAM.find(mention).person is None


def test_initial_with_foreign_org_is_not_assigned():
    m = TEAM.find("Марина Ч.", context="подрядчик Марина Ч. из ТМК, пришлите акт")
    assert m.person is None


def test_erp_patronymic_is_not_namesake():
    """Находка ERP (90d7bf1): при сверке хвоста по длине «Петрович» строго совпадал с «Петров Иван»."""
    t = Team([Person("Петров Иван", id=1), Person("Гаврилов Павел", id=2)])
    m = t.find("Петрович")
    assert m.person is None or m.person.id != 1


def test_erp_initial_matches_patronymic():
    """Находка ERP (90d7bf1): инициал сверяется со свободными частями имени, отчество — тоже часть.
    Так же сделано в Планёрке (0613e95). Это соглашение двух веток, а не решение владельца: отдельного решения
    про отчество нет."""
    t2 = Team([Person("Игнатова Мария Чеславовна", id=1), Person("Гаврилов Павел", id=2)])
    m = t2.find("Мария Ч.")
    assert m.person is not None and m.person.id == 1, m
