"""Находка стенда 45 (старая версия c74e5f7, 92a3e40; стенд Планёрки): подсказка поручений — твёрдое самовзятие —
поручение; неуверенное намерение — нет; задачу ведущего или директора выписывать с пустым исполнителем; принятие
предложения не отсекать; повелительное «попробуйте» — поручение (в словаре намерений «попробу…» стояло целиком).
Тесты написаны до правки и падали."""
import pytest

from meetflow.core.negation import NegationRule
from meetflow.core.prompts import PROFILES, PromptBuilder


def test_prompt_has_the_four_rules():
    sysm, _ = PromptBuilder("роль", PROFILES["generic"]).extract_tasks(0, ["a"], [])
    for rule in ("твёрдо взял работу на себя", "неуверенное намерение", "ведущий или директор",
                 "принял предложение", "«попробуйте сделать»"):
        assert rule in sysm, rule


@pytest.mark.parametrize("phrase", [
    "Петрова Анастасия, попробуйте согласовать график с подрядчиком до пятницы",
    "Попробуйте выгрузить остатки по складу в среду",
])
def test_imperative_try_is_assignment_not_intent(phrase):
    v = NegationRule().check(phrase)
    assert "assignment" in v.blockers and "intent" not in v.blockers


@pytest.mark.parametrize("phrase", [
    "Попробую посмотреть, может быть успею к пятнице",
    "Мы попробуем, но не обещаем",
])
def test_unsure_intent_stays_intent(phrase):
    assert "intent" in NegationRule().check(phrase).blockers
