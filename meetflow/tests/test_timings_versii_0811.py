"""Итог сборки у каждой версии протокола (правки ERP/Планёрки 03–06.11, п. 12).

«Почему так вышло» не воспроизводится, если у версии нет итога: сколько вызовов, какая цена, сколько задач, какой
источник. Теперь `timings` пишется у каждой версии — у сборки свой, у ручной правки и восстановления свой.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.pipeline import MeetingPipeline
from meetflow.web.app import create_app

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная, вопросов нет.\n"
          "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n"
          "[00:03:00] Петрова Анастасия: Хорошо, сделаю к пятнице.\n")


def _сборка(store, project, meeting, theme, tmp_path):
    p = MeetingPipeline(theme, store, default_registry(), MockLLM(), MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ЗАПИСЬ,
                 digest="t" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-05T10:00:00")
    return p.run(project, meeting)


def test_у_версии_сборки_есть_итог(store, project, meeting, theme, tmp_path):
    rep = _сборка(store, project, meeting, theme, tmp_path)
    версия = store.q("SELECT version, timings FROM protocol_versions WHERE meeting_id=? ORDER BY version DESC",
                     (meeting,))[0]
    итог = json.loads(версия["timings"] or "{}")
    assert итог["status"] == rep.status == "ok"
    assert итог["calls"] == rep.calls and итог["cost_usd"] is not None
    assert isinstance(итог["tasks_added"], int)
    assert итог["source_choice"] == "своя запись"


def test_ручная_правка_и_восстановление_пишут_свой_итог(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    st.insert("accounts", login="admin", full_name="Админ", role="super_admin", password_hash="х", active=1,
              confirmed=1)
    pid = st.insert("projects", name="П", theme="erp_rollout")
    mid = st.insert("meetings", project_id=pid, date="2026-10-01")
    st.insert("protocol_versions", meeting_id=mid, version=1, protocol_md="# Протокол\n", model="mock",
              built_at="2026-10-01T10:00:00")
    h = {"X-User-Role": "super_admin", "X-User-Name": "admin", "X-Project-Id": str(pid)}
    r = c.post(f"/api/meetings/{mid}/protocol/edit", json={"markdown": "# Протокол\n\nправка\n"}, headers=h)
    assert r.status_code == 200, r.text
    r2 = c.post(f"/api/meetings/{mid}/protocol/restore", json={"version": 1}, headers=h)
    assert r2.status_code == 200, r2.text
    строки = c.get(f"/api/meetings/{mid}/protocol/versions", headers=h).json()
    по_версии = {x["version"]: json.loads(x["timings"] or "{}") for x in строки}
    assert по_версии[2]["source"] == "правка вручную"
    assert по_версии[3]["source"] == "восстановлена версия 1"
    assert по_версии[1] == {}          # старая версия без итога читается пусто, без падения
