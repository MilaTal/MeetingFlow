"""Находка стенда, строка 40 (ERP 9e8af1a): ответ модели «не JSON» — карточка из общей точки всех перехватов
сборки. Внутренние перехваты шагов глотали ошибку: проверка протокола писала строку в замечания, единицы встречи —
в detail, закрытие единиц — молча пустой список; оператор не узнавал ничего. Тест сквозной — через API сборки,
а не вызов функции карточки. Написан до правки и падал."""
import pytest
from fastapi.testclient import TestClient

from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.types import LLMResult
from meetflow.web.app import create_app

H = {"X-User-Role": "project_admin"}


class NotJsonOn(MockLLM):
    def __init__(self, purposes):
        super().__init__()
        self.purposes = purposes

    def complete(self, system, user, **kw):
        if kw.get("purpose") in self.purposes:
            return LLMResult("Извините, не могу ответить в JSON.", self.model, 10, 10)
        return super().complete(system, user, **kw)


def _run(tmp_path, gen=None, ver=None, transcript=TRANSCRIPT):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    if gen:
        app.state.pipe.gen = gen
    if ver:
        app.state.pipe.ver = ver
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", transcript.encode())})
    rep = c.post(f"/api/meetings/{mid}/run", headers=H).json()
    tech = app.state.store.q("SELECT title FROM cards WHERE kind='technical' AND meeting_id=?", (mid,))
    return rep, [t["title"] for t in tech]


def test_verify_not_json_gives_card(tmp_path):
    rep, tech = _run(tmp_path, ver=NotJsonOn({"verify"}))
    assert rep["protocol_saved"]
    assert any(t == "Шаг сборки не выполнен: Проверка протокола" for t in tech), tech


def test_units_not_json_gives_card(tmp_path):
    rep, tech = _run(tmp_path, gen=NotJsonOn({"units"}))
    assert rep["protocol_saved"]
    assert any("Единицы встречи" in t for t in tech), tech


def test_units_close_not_json_gives_card(tmp_path):
    text = TRANSCRIPT + "[00:06:00] Игнатов Иван: Решили закупать песок у Северного карьера.\n"
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    m1 = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-09-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{m1}/sources", headers=H, files={"file": ("t 01.09.2026.txt", text.encode())})
    c.post(f"/api/meetings/{m1}/run", headers=H)
    assert app.state.store.q("SELECT id FROM units WHERE status='open'"), "нужен открытый пункт для закрытия"
    app.state.pipe.gen = NotJsonOn({"units_close"})
    m2 = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{m2}/sources", headers=H, files={"file": ("t 01.10.2026.txt", text.encode())})
    rep = c.post(f"/api/meetings/{m2}/run", headers=H).json()
    tech = [t["title"] for t in app.state.store.q("SELECT title FROM cards WHERE kind='technical' AND meeting_id=?", (m2,))]
    assert rep["protocol_saved"]
    assert any("Закрытие пунктов" in t for t in tech), tech
