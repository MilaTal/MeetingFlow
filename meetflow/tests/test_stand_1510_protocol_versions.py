"""Находки стенда 43 и 47 (решение владельца 15.10.26; ERP 708e590).
43 — протокол сохраняется сразу, прежняя версия остаётся в истории, а не затирается.
47 — поле «модель» у версии — модель, которой написан черновик (ответившая точка), а не настроенная основная:
при переходе маршрута на запасную точку писалось имя основной. Тесты написаны до правки и падали."""
from dataclasses import replace

from conftest import TRANSCRIPT

from meetflow.connectors.llm_mock import MockLLM


class Fallback(MockLLM):
    """Основная точка маршрута — «основная-модель», ответила запасная."""
    model = "основная-модель"

    def complete(self, system, user, **kw):
        return replace(super().complete(system, user, **kw), model="запасная-модель")


def test_version_model_is_the_one_that_answered(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Fallback())
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    v = store.q("SELECT * FROM protocol_versions WHERE meeting_id=? ORDER BY version", (mid,))
    assert len(v) == 1 and v[0]["model"] == "запасная-модель"
    assert v[0]["protocol_md"] == store.get("meetings", mid)["protocol_md"]


def test_rebuild_keeps_previous_version(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe()
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    first = store.get("meetings", mid)["protocol_md"]
    p.run(project, mid)
    v = store.q("SELECT version, protocol_md FROM protocol_versions WHERE meeting_id=? ORDER BY version", (mid,))
    assert [x["version"] for x in v] == [1, 2] and v[0]["protocol_md"] == first


def test_versions_api_admin_only_and_journal_names_who_wrote(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c, H = TestClient(app), {"X-User-Role": "project_admin"}
    app.state.pipe.gen = Fallback()
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", TRANSCRIPT.encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)
    v = c.get(f"/api/meetings/{mid}/versions", headers=H).json()
    assert v[0]["version"] == 1 and v[0]["model"] == "запасная-модель"
    assert c.get(f"/api/meetings/{mid}/versions", headers={"X-User-Role": "member"}).status_code == 403
    run = [r for r in app.state.pipe.journal.records if r.get("run") == mid][-1]
    assert run["answered_by"]["protocol"] == ["запасная-модель"] and run["generator"] == "основная-модель"
