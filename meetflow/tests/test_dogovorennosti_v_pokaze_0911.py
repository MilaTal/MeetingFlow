"""Договорённости из реестра — в показ протокола с пометкой (решение Планёрки 09.11.2026)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meetflow.core import dogovorennosti_v_pokaze as дп
from meetflow.core.store import Store


def test_недостающие_считаются_по_первым_30_знакам():
    s = Store(":memory:")
    try:
        pid = s.insert("projects", name="Пилот", theme="it_product")
        mid = s.insert("meetings", project_id=pid, date="2026-11-09", status="built")
        s.insert("units", meeting_id=mid, kind="agreement", text="Поставки идут по средам")
        s.insert("units", meeting_id=mid, kind="decision", text="Срок сдачи — пятница")
        md = "## Решения\n\nПоставки идут по средам.\n"
        assert дп.недостающие(s, mid, md) == ["Срок сдачи — пятница"]
    finally:
        s.close()


def test_дополнение_вставляет_в_решения(monkeypatch):
    s = Store(":memory:")
    try:
        pid = s.insert("projects", name="Пилот", theme="it_product")
        mid = s.insert("meetings", project_id=pid, date="2026-11-09", status="built")
        s.insert("units", meeting_id=mid, kind="agreement", text="Поставки идут по средам")
        monkeypatch.setenv(дп.ПЕРЕМЕННАЯ, "1")
        md = "## Решения\n\nДругое решение.\n\n## Открытые вопросы\n\n—"
        итог = дп.дополнить(s, mid, md)
        assert "- (из реестра) Поставки идут по средам" in итог
        assert "## Открытые вопросы" in итог
        # без заголовка «Решения» — свой раздел в конце
        итог2 = дп.дополнить(s, mid, "## Участники\n\nЛюди")
        assert дп.ЗАГОЛОВОК in итог2 and "- (из реестра)" in итог2
    finally:
        s.close()


def test_по_умолчанию_выключено(monkeypatch):
    s = Store(":memory:")
    try:
        pid = s.insert("projects", name="Пилот", theme="it_product")
        mid = s.insert("meetings", project_id=pid, date="2026-11-09", status="built")
        s.insert("units", meeting_id=mid, kind="agreement", text="Поставки идут по средам")
        monkeypatch.delenv(дп.ПЕРЕМЕННАЯ, raising=False)
        md = "## Решения\n\nДругое."
        assert дп.дополнить(s, mid, md) == md
    finally:
        s.close()


def test_показ_протокола_с_флагом(monkeypatch, tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    uid = st.insert("accounts", full_name="Орлова Анна", role="super_admin", active=1, confirmed=1)
    mid = st.insert("meetings", project_id=pid, date="2026-11-09", status="built",
                    protocol_md="## Решения\n\nДругое решение.")
    st.insert("units", meeting_id=mid, kind="agreement", text="Поставки идут по средам")
    headers = {"X-User-Id": str(uid), "X-Requested-With": "erp-webapp"}
    monkeypatch.delenv(дп.ПЕРЕМЕННАЯ, raising=False)
    assert "(из реестра)" not in c.get(f"/api/meetings/{mid}/protocol", headers=headers).json()["markdown"]
    monkeypatch.setenv(дп.ПЕРЕМЕННАЯ, "1")
    assert "(из реестра) Поставки идут по средам" in c.get(f"/api/meetings/{mid}/protocol", headers=headers).json()["markdown"]
