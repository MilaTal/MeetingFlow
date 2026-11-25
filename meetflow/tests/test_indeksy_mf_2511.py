# -*- coding: utf-8 -*-
"""Индексы скорости MeetFlow (25.11, аналог Планёрки/ERP): создаются при старте, идемпотентны."""
from meetflow.core.store import Store


def test_индексы_создаются_при_старте():
    s = Store(":memory:")
    имена = {r[0] for r in s._conn.execute("select name from sqlite_master where type='index' and name like 'ix_mf%'")}
    assert "ix_mf_protocol_versions_meeting" in имена
    assert "ix_mf_tasks_status" in имена
    assert "ix_mf_cards_meeting_kind_status" in имена
    s._ensure_indexes()  # повторный вызов не падает
    s.close() if hasattr(s, "close") else None