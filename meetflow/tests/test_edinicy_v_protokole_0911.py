"""Единицы реестра могут не попасть в протокол молча — теперь карточка (рекомендация Планёрки 09.11.2026, п. 3)."""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Решили: поставки идут по средам.\n")


class Модель(MockLLM):
    def _extract(self, data):
        return {"tasks": []}

    def _units(self, data):
        return {"items": [{"kind": "Договорённость", "statement": "Поставки идут по средам", "lines": ["2"]}]}

    def _units_close(self, system, data):
        return {"closed": []}


def _сборка(store, project, meeting, tmp_path, md_раздел=""):
    class СРазделом(Модель):
        def _protocol(self, system, data):
            out = super()._protocol(system, data)
            out.setdefault("sections", {})["Решения"] = md_раздел
            return out
    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), СРазделом(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="ед" + str(meeting) + md_раздел, local_asr=1,
                 meta=json.dumps({"voice_names": {}}, ensure_ascii=False), created_at="2026-11-09T10:00:00")
    return p


def test_договорённость_не_в_протоколе_даёт_карточку(store, project, meeting, tmp_path):
    p = _сборка(store, project, meeting, tmp_path)
    p.run(project, meeting)
    карточки = store.q("SELECT title, payload FROM cards WHERE meeting_id=? AND status='open'", (meeting,))
    карточка = next((c for c in карточки if c["title"].startswith("Договорённости не попали")), None)
    assert карточка, карточки
    данные = json.loads(карточка["payload"])
    assert данные["units"] >= 1 and данные["in_text"] == 0


def test_договорённость_в_протоколе_карточки_нет(store, project, meeting, tmp_path):
    p = _сборка(store, project, meeting, tmp_path, md_раздел="Поставки идут по средам.")
    p.run(project, meeting)
    assert not store.q("SELECT id FROM cards WHERE meeting_id=? AND title LIKE 'Договорённости не попали%'", (meeting,))
