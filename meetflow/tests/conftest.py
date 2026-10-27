"""Общие фикстуры. Тесты никогда не зовут настоящую модель (стенд без модели)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["MEETFLOW_LLM"] = "mock"
# Рабочий data/models.json тестам не виден: маршруты задают сами тесты (09.10.26). Папка временная: «Модели» без
# файла кладут справочник заготовок (15.10.26) — в репозиторий он не попадает.
import tempfile  # noqa: E402
os.environ["MODEL_ROUTES_PATH"] = str(Path(tempfile.mkdtemp(prefix="meetflow-routes-")) / "models.json")

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
def asr_route(tmp_path, monkeypatch):
    """Назначенная точка распознавания (с 15.10.26 модели по умолчанию нет: без роли asr запись ждёт)."""
    import json as _json
    path = tmp_path / "models.json"
    path.write_text(_json.dumps({"endpoints": {"whisper": {"kind": "faster-whisper", "model": "large-v3"}},
                                 "roles": {"asr": ["whisper"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setenv("RECOGNITION_LEASE_PATH", str(tmp_path / "recognition_lease.json"))
    return path


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


@pytest.fixture(autouse=True)
def _no_real_shared_bases(monkeypatch):
    """Тесты не видят настоящую общую «Команду» и базу голосов машины (27.10.2026): при заданных VOICE_BASE_PATH или
    TEAM_SHARED_PATH люди общей «Команды» попадали в «Команду» проекта, и проверки ввода человека видели чужие записи.
    Тест, которому база нужна, задаёт её сам (`monkeypatch.setenv`)."""
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)
    monkeypatch.delenv("TEAM_SHARED_PATH", raising=False)
