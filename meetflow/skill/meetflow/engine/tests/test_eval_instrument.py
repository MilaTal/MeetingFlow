"""Прибор врёт чаще продукта: судья eval проверяется на заведомом ответе.
Пустой клиент (ничего не извлекает) обязан провалить типовые кейсы; если судья их «пропустит», 15 из 15 ничего не значит."""

import json
import os
import sys

from meeting_registry import pipeline
from meeting_registry.llm import ScriptedClient
from meeting_registry.registry import Registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "eval"))
import run_eval  # noqa: E402


def _cases(name="cases"):
    with open(os.path.join(ROOT, "eval", f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)["cases"]


def _judge_with(client_factory, case, team, tmp_path):
    reg = Registry(str(tmp_path / f"{case['id']}.db"))
    for i, s in enumerate(case.get("setup", [])):
        pipeline.process(s, f"s{i}.txt", "2026-10-01", reg, team)       # подготовка — всегда эталонным путём
    ids = {t["id"] for t in reg.all_tasks()}
    res = pipeline.process(case["input"], f"{case['id']}.txt", "2026-10-02", reg, team, client_factory())
    out = run_eval.judge(case, res, reg, ids)
    reg.close()
    return out


def test_judge_fails_empty_client_on_typical_cases(team, tmp_path):
    empty = lambda: ScriptedClient({"extract:1/1": {"assignments": []}, "closing": {"closures": []}})  # noqa: E731
    typical = [c for c in _cases() if c["type"] == "типовой"]
    failed = [c["id"] for c in typical if _judge_with(empty, c, team, tmp_path)]
    assert failed == [c["id"] for c in typical]


def test_judge_catches_wrong_responsible(team, tmp_path):
    case = next(c for c in _cases() if c["id"] == "T1")
    case = {**case, "expect": {**case["expect"], "tasks": [{"has": "спецификац", "who": "u06"}]}}   # заведомо чужой
    assert any("ответственный" in f for f in _judge_with(lambda: None, case, team, tmp_path))


def test_every_case_has_expectation_and_type():
    for name in ("cases", "cases_live", "cases_blind"):
        for c in _cases(name):
            assert c["expect"] and c["type"] in ("типовой", "пограничный", "невалидный вход", "отказ или эскалация")
    types = {c["type"] for c in _cases()}
    assert types == {"типовой", "пограничный", "невалидный вход", "отказ или эскалация"}
    assert 10 <= len(_cases()) <= 15
