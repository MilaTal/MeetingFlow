"""Общие фикстуры. Тесты никогда не зовут настоящую модель (стенд без модели)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["MEETFLOW_LLM"] = "mock"
# Рабочий data/models.json тестам не виден: маршруты задают сами тесты (09.10.26)
os.environ["MODEL_ROUTES_PATH"] = str(ROOT / "tests" / "_нет_маршрутов.json")

from meetflow.connectors.llm_mock import MockLLM  # noqa: E402
from meetflow.connectors.registry import default_registry  # noqa: E402
from meetflow.core.config import load_theme  # noqa: E402
from meetflow.core.pipeline import MeetingPipeline  # noqa: E402
from meetflow.core.store import Store  # noqa: E402

TRANSCRIPT = """[00:00:10] Игнатов Иван: Добрый день, начинаем.
[00:01:00] Петрова Анастасия: По складу всё идёт по плану.
[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада до 10.10
[00:03:00] Сидоров Пётр: Выгрузку остатков склада отправил, сделано.
[00:04:00] Игнатов Иван: Кузнецов Олег, проверьте отчёт по браку
[00:05:00] Игнатов Иван: Нужно ли обновить спецификации?
"""
TEAM = ["Игнатов Иван", "Петрова Анастасия", "Сидоров Пётр"]


@pytest.fixture
def theme():
    return load_theme("erp_rollout")


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def project(store):
    pid = store.insert("projects", name="Пилот", theme="erp_rollout")
    for n in TEAM:
        store.insert("people", project_id=pid, full_name=n)
    return pid


@pytest.fixture
def meeting(store, project):
    return store.insert("meetings", project_id=project, date="2026-10-01", label="Встреча")


@pytest.fixture
def make_pipe(theme, store):
    def _make(gen=None, ver=None, th=None):
        return MeetingPipeline(th or theme, store, default_registry(), gen or MockLLM(), ver or MockLLM())
    return _make
