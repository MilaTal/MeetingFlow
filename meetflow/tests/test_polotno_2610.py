# -*- coding: utf-8 -*-
"""Правка текста протокола: новая версия, история, возврат версии (задание 26.10.2026)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


def test_protocol_edit_creates_versions_and_restore(tmp_path):
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False),
                   raise_server_exceptions=False)
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]

    first = c.post(f"/api/meetings/{mid}/protocol/edit", json={"markdown": "# Протокол\n\nПервый текст"}, headers=H)
    assert first.status_code == 200 and first.json()["version"] == 1
    assert "Первый текст" in c.get(f"/api/meetings/{mid}/protocol", headers=H).json()["markdown"]

    second = c.post(f"/api/meetings/{mid}/protocol/edit", json={"markdown": "# Протокол\n\nВторой текст"}, headers=H)
    assert second.json()["version"] == 2
    versions = c.get(f"/api/meetings/{mid}/protocol/versions", headers=H).json()
    assert [v["version"] for v in versions] == [2, 1]

    restored = c.post(f"/api/meetings/{mid}/protocol/restore", json={"version": 1}, headers=H)
    assert restored.status_code == 200 and restored.json()["version"] == 3
    assert "Первый текст" in c.get(f"/api/meetings/{mid}/protocol", headers=H).json()["markdown"]
    assert [v["version"] for v in c.get(f"/api/meetings/{mid}/protocol/versions", headers=H).json()] == [3, 2, 1]
