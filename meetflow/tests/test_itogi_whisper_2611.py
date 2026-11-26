# -*- coding: utf-8 -*-
"""«Итоги распознавания» MeetFlow: блок Whisper подписан моделью (26.11.2026).

Слово владелицы: «Проверить, что транскрибация от вайспер также попадает в файл — Результат транскрибации». В MeetFlow
подпись берётся из сводки источника (`meta.route`/`meta.model`) — проверяем, что блок называет точку Whisper.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from meetflow.web.app import create_app


def test_блок_итогов_подписан_моделью_whisper(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    store = app.state.store
    pid = store.insert("projects", name="Пилот", theme="erp_rollout")
    mid = store.insert("meetings", project_id=pid, date="2026-11-26", label="Проверка Whisper")
    store.insert("sources", meeting_id=mid, name="Запись — контрольная Whisper.txt", kind="transcript",
                 text="00:00:00\tНе верит никому нельзя, и очные ставки только.\n00:00:04\tА вы записывали?",
                 created_at="2026-11-26T13:05:00", voice_state="",
                 meta=json.dumps({"route": "whisper-large-v3", "model": "whisper-large-v3",
                                  "device": "сервис в сети"}, ensure_ascii=False))

    ответ = c.get(f"/meetings/{mid}/recognition/export")
    assert ответ.status_code == 200, ответ.text
    вывод = ответ.text
    assert "Система: MeetFlow" in вывод
    assert "Модель распознавания: whisper-large-v3" in вывод, вывод[:1200]
    assert "Не верит никому нельзя" in вывод
