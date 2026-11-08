"""Тёзки при записи из двух слов: не угадывать и не заводить третьего (09.11.2026).

Остаток отчёта 07.11 (`29d4e86`): если общая «Команда» присылает «Фамилия Имя» без отчества, а в проекте таких двое с
разными отчествами, прежний код заводил третью запись — то есть угадывал. Правильно: оставить как есть (ничего не
заводить) и показать карточку; уточнение — за человеком. Данные вымышленные.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import team_sync
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n")


def _люди(store, project_id):
    return [r["full_name"] for r in store.q("SELECT full_name FROM people WHERE project_id=? ORDER BY id", (project_id,))]


def test_два_тёзки_и_два_слова_не_угадываются(store, project, monkeypatch):
    store.insert("people", project_id=project, full_name="Иванов Пётр Сергеевич", confirmed=1)
    store.insert("people", project_id=project, full_name="Иванов Пётр Иванович", confirmed=1)
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: [{"full_name": "Иванов Пётр"}])
    неоднозначные: list[dict] = []
    added = team_sync.sync_people(store, project, неоднозначные=неоднозначные)
    assert added == 0, "третью запись не заводим — угадывать не должны"
    assert "Иванов Пётр" not in _люди(store, project)
    assert len(неоднозначные) == 1
    assert неоднозначные[0]["name"] == "Иванов Пётр"
    assert sorted(неоднозначные[0]["candidates"]) == ["Иванов Пётр Иванович", "Иванов Пётр Сергеевич"]


def test_один_тёзка_и_два_слова_это_он(store, project, monkeypatch):
    store.insert("people", project_id=project, full_name="Иванов Пётр Сергеевич", confirmed=1)
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: [{"full_name": "Иванов Пётр"}])
    неоднозначные: list[dict] = []
    assert team_sync.sync_people(store, project, неоднозначные=неоднозначные) == 0
    assert неоднозначные == [] and "Иванов Пётр" not in _люди(store, project)


def test_без_тёзок_два_слова_заводится(store, project, monkeypatch):
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: [{"full_name": "Иванов Пётр"}])
    неоднозначные: list[dict] = []
    assert team_sync.sync_people(store, project, неоднозначные=неоднозначные) == 1
    assert "Иванов Пётр" in _люди(store, project) and неоднозначные == []


def test_три_слова_с_новым_отчеством_второй_тёзка_заводится(store, project, monkeypatch):
    """Прежнее правило в силе: отчество есть и оно другое — это отдельный человек."""
    store.insert("people", project_id=project, full_name="Иванов Пётр Сергеевич", confirmed=1)
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: [{"full_name": "Иванов Пётр Иванович"}])
    assert team_sync.sync_people(store, project) == 1
    люди = _люди(store, project)
    assert "Иванов Пётр Иванович" in люди and "Иванов Пётр Сергеевич" in люди
    assert люди.count("Иванов Пётр Иванович") == 1


def test_сборка_открывает_карточку_о_тёзках(store, project, meeting, monkeypatch, tmp_path):
    store.insert("people", project_id=project, full_name="Иванов Пётр Сергеевич", confirmed=1)
    store.insert("people", project_id=project, full_name="Иванов Пётр Иванович", confirmed=1)
    monkeypatch.setattr(team_sync, "shared_people", lambda *a, **k: [{"full_name": "Иванов Пётр"}])

    class Модель(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                               "line": 2, "due_date": "к пятнице"}]}

        def _units(self, data):
            return {"items": []}

    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), Модель(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="т" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-09T10:00:00")
    p.run(project, meeting)
    карточки = store.q("SELECT title, payload FROM cards WHERE project_id=? AND status='open'", (project,))
    карточка = next((c for c in карточки if c["title"].startswith("В «Команде» тёзки")), None)
    assert карточка, карточки
    данные = json.loads(карточка["payload"])
    assert данные["items"][0]["name"] == "Иванов Пётр" and len(данные["items"][0]["candidates"]) == 2
