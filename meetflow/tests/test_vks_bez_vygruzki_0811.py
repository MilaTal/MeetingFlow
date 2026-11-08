"""Без выгрузки ВКС сборка не меняется (записка 05.11.2026, п. 4: «на встрече без выгрузки тот же итог»).

Проверяется: второй текст не появляется, правило выгрузки в промпты не попадает, проверка полноты по окнам молчит, итог
сборки не говорит о втором тексте. Модель — заглушка, денег нет.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.pipeline import MeetingPipeline, teksty_sborki

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n"
          "[00:03:00] Петрова Анастасия: Хорошо, сделаю.\n")


class Модель(MockLLM):
    def __init__(self):
        super().__init__()
        self.seen: dict[str, tuple[str, str]] = {}

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose="", deadline=None):
        self.seen[purpose] = (system, user)
        return super().complete(system, user, json_mode=json_mode, temperature=temperature, purpose=purpose)


def _s(name, text, local, sid=1):
    return {"id": sid, "name": name, "text": text, "local_asr": 1 if local else 0}


def test_одна_расшифровка_без_второй():
    своя = _s("своя", ЗАПИСЬ, True)
    base, second, reason = teksty_sborki([своя])
    assert base is своя and second is None and reason == ""


def test_промпты_и_итог_без_выгрузки(store, project, meeting, theme, tmp_path):
    gen = Модель()
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="x1" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-05T10:00:00")
    rep = p.run(project, meeting)
    for purpose in ("extract_tasks", "protocol", "units"):
        if purpose not in gen.seen:
            continue
        система, тело = gen.seen[purpose]
        assert "выгрузка ВКС" not in система
        assert "выгрузка ВКС" not in тело
    assert "вторым текстом" not in rep.source_reason
    assert store.q("SELECT id FROM cards WHERE meeting_id=? AND title LIKE 'Возможна потерянная задача%'", (meeting,)) == []
