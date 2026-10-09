"""Решения владельца 03.10.26, к которым движок приведён при сведении в скилл meetflow (09.10.26).
Прежде движок назначал тёзку, если говорил только он, исправлял «Чистяка» молча и считал «отказались» выполнением."""
from meeting_registry.agent import _final
from meeting_registry.negation import classify


def _ctx(team, speakers):
    lines = [{"n": i + 1, "speaker": s, "text": "Хорошо, займусь."} for i, s in enumerate(speakers)]
    return {"team": team, "tasks": [], "lines": lines}


def test_namesake_always_goes_to_operator_even_if_only_one_spoke(team):
    ctx = _ctx(team, ["Чистякова Марина", "Гаврилов Павел"])
    obs = [{"tool": "participants"}]
    d = _final("assign", {"person_id": "u03"}, {"to": "Марина"}, ctx, obs)
    assert d["decision"] == "to_operator"
    # участники встречи сортируют кандидатов: говоривший — первым, с пометкой
    assert d["reason"].index("Чистякова Марина — говорил на встрече") < d["reason"].index("Воронова Марина")


def test_distorted_surname_without_name_is_a_candidate(team):
    assert team.resolve("Чистяка")["status"] == "suspect"
    assert team.resolve("Чистяка Марина")["status"] == "fixed"
    assert team.resolve("Чистяка Светлана")["status"] not in ("exact", "fixed")   # имя противоречит
    assert team.resolve("Назаровой")["status"] == "exact"                         # падеж — не искажение


def test_refusal_is_removal_not_done():
    assert classify("От поставщика отказались")["fact"] == "dropped"
    assert classify("Вычеркнули из плана")["fact"] == "dropped"
    assert classify("Не отказались, работаем")["fact"] is None
    assert classify("Отказываться от поставщика не будем")["fact"] is None
    assert classify("Отчёт отправили")["fact"] == "done"
