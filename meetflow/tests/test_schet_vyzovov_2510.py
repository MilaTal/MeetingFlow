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


def test_predel_vyzovov_kak_planerka_2810():
    """28.10.2026, отчёт ЛМ d052f82: сборка 15.10 остановилась на «вызовов 14 из 14» (шаг units, 7 кусков записи) и не
    сохранила единицы. Предел — как у Планёрки: 30 (решения владелицы 16.10 и 18.10.2026)."""
    import json
    from pathlib import Path
    from meetflow.core.budget import BudgetLimits
    assert BudgetLimits().max_calls == 30
    корень = Path(__file__).resolve().parents[1] / "themes"
    for имя in ("_default.json", "daily_ops.json", "erp_rollout.json"):
        assert json.loads((корень / имя).read_text(encoding="utf-8"))["budget"]["max_calls"] == 30, имя
