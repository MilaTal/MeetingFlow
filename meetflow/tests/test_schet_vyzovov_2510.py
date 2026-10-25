"""Правила 25.10.2026, пункт 1: счёт вызовов на шаг по `run_id`, потолок шага считает переспросы.

До правки: потолок был только общий на прогон, вызовы шага не считались, `run_id` в журнале не было.
"""
import json

import pytest

from meetflow.core.budget import BudgetExceeded, BudgetLimits, CallJournal, RunBudget


def test_step_cap_counts_retries_same_purpose():
    b = RunBudget(BudgetLimits(max_calls=100, max_calls_per_step=3))
    for _ in range(3):
        b.check(10, "extract_tasks")          # первый вызов и два переспроса
    assert b.steps["extract_tasks"] == 3
    with pytest.raises(BudgetExceeded, match="шаг"):
        b.check(10, "extract_tasks")


def test_step_cap_does_not_block_other_step():
    b = RunBudget(BudgetLimits(max_calls=100, max_calls_per_step=2))
    b.check(10, "extract_tasks"); b.check(10, "extract_tasks")
    b.check(10, "protocol")                   # другой шаг идёт
    assert b.steps == {"extract_tasks": 2, "protocol": 1}


def test_journal_records_run_id(tmp_path):
    j = CallJournal(tmp_path / "j.jsonl")
    j.run_id = "run-42"
    j.write(purpose="extract_tasks", meeting_id=1)
    rec = json.loads((tmp_path / "j.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["run_id"] == "run-42" and rec["purpose"] == "extract_tasks"
