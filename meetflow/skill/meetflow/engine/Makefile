# Локальный прогон проверок. GitHub Actions запрещён манифестом проекта — только локальные раннеры.
PY ?= python
export PYTHONIOENCODING=utf-8

.PHONY: test eval regress attack five all

test:
	$(PY) -m pytest tests -q

eval:
	$(PY) eval/run_eval.py --label текущий --set cases
	$(PY) eval/run_eval.py --label текущий --set cases_live
	$(PY) eval/run_eval.py --label текущий --set cases_blind

regress:
	$(PY) eval/compare.py cases_live до_v1.0 после_v1.2

attack:
	$(PY) eval/cost_attack.py

five:
	$(PY) eval/five_runs.py --client heuristic

all: test eval attack five
