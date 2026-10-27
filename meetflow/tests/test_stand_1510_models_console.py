"""Пульт «Модели» — функции точки как у ERP и Планёрки (ответ владельца 15.10.26): значок «i» и общая инструкция в
раскрывающемся блоке (текст оператору 14.10.26, одинаковый до слова), ключ значением — наружу только «ключ задан ·
…XXXX», «Заменить ключ» / «Удалить ключ», подписи вариантов рассуждения, тариф и предел расхода, все роли видны,
роль без точек — «не настроена». Протокол, собранный внешней моделью, — строкой в системных сообщениях, в документе
пометки нет. Тесты написаны до правки и падали."""
import io
import json
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.shared import model_routes as mr

JS = (Path(__file__).parents[1] / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")
SUPER = {"X-User-Role": "super_admin"}


def test_console_texts_and_controls():
    """Консоль «Модели» — с 27.10.2026 разметка ERP 1 в 1 (`renderModelRoutes`): роли, точки, ключи, проверка, откат."""
    assert "async function renderModelRoutes(el, base, apiOpts = {})" in JS
    for marker in ("/endpoint/key", "/endpoint/test", "/rollback", "/use", "/role"):
        assert marker in JS, marker


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def app_with_deepseek(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": {
        "ds": {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash", "key_source": "value"}},
        "roles": {"generate": ["ds"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    monkeypatch.setenv("MODEL_PROBE", "off")
    monkeypatch.setattr(mr._state, "down_until", {})

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        text = MockLLM().complete(body["messages"][0]["content"], body["messages"][1]["content"]).text
        return _Resp(json.dumps({"model": "deepseek-flash", "choices": [{"message": {"content": text},
                                 "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    c.post("/api/monitoring/models/endpoint/key", json={"name": "ds", "key_value": "sk-test-1234567890abcdefQRST"},
           headers=SUPER)
    return app, c


def test_key_mask_only_and_spend_in_panel(app_with_deepseek):
    app, c = app_with_deepseek
    d = c.get("/api/monitoring/models", headers=SUPER).json()
    assert "sk-test" not in json.dumps(d, ensure_ascii=False)
    ep = next(e for e in d["endpoints"] if e["name"] == "ds")
    assert ep["key"] == "ключ задан · …QRST" and ep["external"] and "provider_spend" in d
    assert c.get("/api/monitoring/models", headers={"X-User-Role": "project_admin"}).status_code == 403


def test_external_model_build_is_a_system_message_not_a_mark(app_with_deepseek):
    app, c = app_with_deepseek
    H = {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", TRANSCRIPT.encode())})
    rep = c.post(f"/api/meetings/{mid}/run", headers=H).json()
    assert rep["protocol_saved"]
    msgs = app.state.store.q("SELECT title, payload FROM cards WHERE kind='technical' AND meeting_id=?", (mid,))
    assert any("собран внешней моделью" in m["title"] and "api.deepseek.com" in m["payload"] for m in msgs)
    md = app.state.store.get("meetings", mid)["protocol_md"]
    assert "внешн" not in md.lower() and "deepseek" not in md.lower()
