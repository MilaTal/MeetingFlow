# Локальные раннеры (GitHub Actions запрещён манифестом).
PY ?= python
export PYTHONIOENCODING=utf-8

.PHONY: test test-func test-security test-load test-scale demo serve todo

test:            ## все итерации
	$(PY) -m pytest tests -q -p no:cacheprovider -W ignore::DeprecationWarning

test-func:       ## итерация 1
	$(PY) -m pytest tests -q -m "not security and not load and not scale" -p no:cacheprovider

test-security:   ## итерация 2
	$(PY) -m pytest tests -q -m security -p no:cacheprovider

test-load:       ## итерация 3
	$(PY) -m pytest tests -q -m "load or scale" -p no:cacheprovider

demo:
	$(PY) -m meetflow demo --theme it_product --db data/demo.db

serve:
	$(PY) -m meetflow serve --theme it_product --db data/demo.db --port 8002

todo:
	$(PY) -m meetflow todo --theme _default
