"""Имя и инициал — дополнение к правилу «один человек или два». Решение
владельца 03.10.26 («да», для всех веток), документ meeting-registry
«13_Решение — имя и инициал». Кейсы — из документа, записаны до кода."""
import pytest
from fastapi.testclient import TestClient

from meetflow.core.people import Team
from meetflow.core.types import Person
from meetflow.web.app import create_app

CH = Person("Чистякова Марина", id=1)
VORON = Person("Воронова Марина", id=2)
VARL = Person("Варламова Марина", id=3)
KOST = Person("Костина Мария", id=4)
NAZ_K = Person("Назаров Константин", id=5)
NAZ_A = Person("Назаров Андрей", id=6)
DIM = {"маша": ["мария"]}


@pytest.mark.parametrize("team,mention,who", [
    ([CH, VORON], "Марина Ч.", 1),                  # один подходит — молча
    ([KOST, CH], "Маша К.", 4),                    # краткая форма имени
    ([NAZ_K, NAZ_A], "Назаров К.", 5),             # фамилия общая, инициал имени решает
    ([CH, VORON], "Ч. Марина", 1),                  # порядок не важен
])
def test_initial_assigns_when_one_fits(team, mention, who):
    assert Team(team, diminutives=DIM).find(mention).person.id == who


def test_initial_several_fit_is_card():
    m = Team([VORON, VARL, CH]).find("Марина В.")
    assert m.person is None and m.ambiguous and {p.id for p in m.candidates} == {2, 3}


def test_initial_none_fits_is_not_in_team():
    m = Team([NAZ_K, NAZ_A]).find("Назаров С.")
    assert m.person is None and m.candidates == [] and m.via == "unknown"


def test_initial_mismatch_check_applies():
    m = Team([CH, VORON]).find("Марина Ч.", context="Подрядчик Марина Ч. из ТМК, пришлите акт.")
    assert m.person is None and m.via == "same_or_new"


def test_initial_does_not_match_the_same_word():
    """«Марина М.» при Петровой Марине: инициал сверяется с фамилией, а не с самим именем."""
    m = Team([Person("Петрова Марина", id=7)]).find("Марина М.")
    assert m.person is None


def test_initial_never_registers_a_person(tmp_path):
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                   raise_server_exceptions=False)
    H = {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    assert c.post(f"/api/projects/{pid}/people", json={"full_name": "Пересыпкин С."}, headers=H).status_code == 422
