"""Тест прибора и cost-атака для MeetFlow. Запуск из папки eval: python -m pytest -q -p no:cacheprovider test_instrument_and_attacks.py

Тест прибора: модель, которая ничего не извлекает, обязана провалить типовые кейсы. Если судья их «пропустит»,
любые «15 из 15» ничего не значат (meeting-registry, 03.10.26: 15 из 15 с первого прогона оказались
поводом проверить прибор — отложенный набор дал 8 из 12).

Cost-атака (урок 5): потолки не выключаются и не завышаются; по каждой атаке две записи — на каком шаге
сработало ограничение и что было дальше.
"""

import json
import sys

sys.dont_write_bytecode = True
import run_eval_meetflow as R  # noqa: E402
from meetflow.connectors.base import LLMConnector  # noqa: E402
from meetflow.core.types import LLMResult  # noqa: E402

EMPTY = {"extract_tasks": {"tasks": []}, "closing_check": {"closed": []}, "protocol": {"sections": {}},
         "units": {"items": []}, "units_close": {"closed": []}, "verify": {"findings": []}}


class Scripted(LLMConnector):
    name, model, profile = "scripted", "scripted", "generic"

    def __init__(self, fn=None, cost=0.0):
        self.fn, self.cost, self.calls = fn or (lambda pu, us: None), cost, []

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose=""):
        self.calls.append(purpose)
        out = self.fn(purpose, user)
        out = EMPTY.get(purpose, {}) if out is None else out
        return LLMResult(json.dumps(out, ensure_ascii=False), "s", 1, 1, self.cost, 0.0)


def _cases(name="cases"):
    return json.load(open(f"{R.HERE}/{name}.json", encoding="utf-8"))["cases"]


def test_instrument_empty_model_fails_typical():
    for case in [c for c in _cases() if c["type"] == "типовой"]:
        b = R.Bench(Scripted())
        for i, s in enumerate(case.get("setup", [])):
            R.seed_task(b, s, i)
        before = {t["id"] for t in b.p.reg.list(b.pid, None)}
        mid, rep = b.meeting("2026-10-02", case["input"], case["id"])
        assert R.judge(case, rep, b, before, mid), f"{case['id']}: пустая модель прошла типовой кейс — судья слеп"


def test_suites_well_formed():
    for name in ("cases", "cases_live", "cases_blind"):
        for c in _cases(name):
            assert c["expect"] and c["type"] in ("типовой", "пограничный", "невалидный вход", "отказ или эскалация")
    assert {c["type"] for c in _cases()} == {"типовой", "пограничный", "невалидный вход", "отказ или эскалация"}


MANY = "".join(f"Гаврилов Павел: Назаров Константин, подготовьте акт сверки по складу номер {i}.\n" for i in range(1, 40))


def test_attack_A_calls_ceiling():
    """Модель-разгон: каждый вызов обходится, но вызовов больше потолка. Ожидание: остановка до вызова сверх потолка."""
    llm = Scripted()
    b = R.Bench(llm)
    b.th.data["budget"]["max_calls"] = 3
    mid, rep = b.meeting("2026-10-02", MANY * 30, "атака А")
    assert len(llm.calls) <= 3
    assert rep.status != "ok" or getattr(rep, "partial", False), "потолок вызовов сработал, а прогон записан как успешный"


def test_attack_B_money_ceiling_uniform_cost():
    """Каждый вызов «стоит» 0,15 $ при потолке 0,40 $. Слабая форма атаки: одинаковая цена."""
    llm = Scripted(cost=0.15)
    b = R.Bench(llm)
    mid, rep = b.meeting("2026-10-02", MANY, "атака Б1")
    assert rep.cost_usd <= b.th.get("budget.max_cost_usd") + 1e-9, f"расход {rep.cost_usd} больше потолка"


class PricedByPurpose(Scripted):
    PRICE = {"extract_tasks": 0.05, "closing_check": 0.05, "protocol": 0.35, "units": 0.01, "verify": 0.01, "units_close": 0.01}

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose=""):
        r = super().complete(system, user, json_mode=json_mode, temperature=temperature, purpose=purpose)
        return LLMResult(r.text, "s", 1, 1, self.PRICE.get(purpose, 0.01), 0.0)


def test_attack_B_money_ceiling_expensive_after_cheap():
    """Сильная форма: дешёвые вызовы, затем дорогой (протокол). Прогноз по прошлым вызовам его не видит:
    0,05 + 0,05 + 0,35 = 0,45 $ при потолке 0,40 $ (проверка MeetFlow 03.10.26, письмо 01, п. 9)."""
    llm = PricedByPurpose()
    b = R.Bench(llm)
    R.seed_task(b, "Гаврилов Павел: Назаров, подготовьте регламент склада.", 0)
    mid, rep = b.meeting("2026-10-02", "Назаров Константин: Регламент склада готов, сделано.\nГаврилов Павел: Спасибо.\n", "атака Б2")
    assert rep.cost_usd <= b.th.get("budget.max_cost_usd") + 1e-9, f"расход {rep.cost_usd} больше потолка"


def test_attack_C_volume_stops_before_first_call():
    """Запись длиннее потолка знаков: остановка до первого вызова, расход ноль."""
    llm = Scripted()
    b = R.Bench(llm)
    b.th.data["budget"]["max_chars_per_call"] = 5000
    b.th.data["budget"]["max_calls"] = 2
    mid, rep = b.meeting("2026-10-02", MANY * 50, "атака В")
    assert len(llm.calls) <= 2 and rep.cost_usd == 0
