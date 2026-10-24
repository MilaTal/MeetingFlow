"""Находка стенда 46 (решение владельца 15.10.26): стоимость вызова — «поставщик / расчёт по тарифу / тариф не задан»;
предел расхода в месяц по поставщику — необязательный, 90 % — предупреждение, 100 % — стоп только этого поставщика,
другие подключения работают. Расчёт и предел — общим llm_cost.py ERP и Планёрки. Тесты написаны до правки и падали
(журнал не писал поставщика и вид цены — предел считать было не из чего)."""
import io
import json
import urllib.request
from datetime import datetime

import pytest

from conftest import TRANSCRIPT
from meetflow.connectors import llm_routes as lr
from meetflow.connectors.base import ConnectorUnavailable
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.shared import model_routes as mr


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def deepseek(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": {
        "ds": {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash", "month_limit_usd": 1.0},
        "local": {"kind": "ollama", "url": "http://localhost:11434", "model": "qwen3.8:latest"}},
        "roles": {"generate": ["ds", "local"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setenv("MODEL_PROBE", "off")
    monkeypatch.setattr(mr._state, "down_until", {})
    sent = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data)
        sent.append(req.full_url)
        if "11434" in req.full_url:
            text = MockLLM().complete(body["messages"][0]["content"], body["messages"][1]["content"]).text
            return _Resp(json.dumps({"message": {"content": text}, "done_reason": "stop",
                                     "prompt_eval_count": 100, "eval_count": 20}).encode())
        text = MockLLM().complete(body["messages"][0]["content"], body["messages"][1]["content"]).text
        return _Resp(json.dumps({"model": "deepseek-flash", "choices": [{"message": {"content": text},
                                 "finish_reason": "stop"}], "usage": {"prompt_tokens": 1_000_000,
                                                                     "completion_tokens": 0}}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return path, sent


def test_cost_by_tariff_and_provider_in_journal(deepseek, store, project, make_pipe, tmp_path):
    path, sent = deepseek
    gen = lr.RoutedLLM("generator", path=path, journal_path=tmp_path / "j.jsonl")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=gen)
    p.journal.path = tmp_path / "j.jsonl"
    gen.connector("ds").journal_path = p.journal.path
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    calls = [r for r in p.journal.records if r.get("purpose") and r.get("model") == "deepseek-flash"]
    assert calls, "вызовы ушли на DeepSeek"
    r = calls[0]
    assert r["provider"] == "api.deepseek.com" and r["cost_source"].startswith("расчёт по тарифу")
    assert r["cost_usd"] in (0.15, 0.3)                    # 1 млн входа × 0,15 $ (в часы пик ×2)


def test_provider_limit_stops_only_this_provider(deepseek, store, project, make_pipe, tmp_path):
    path, sent = deepseek
    j = tmp_path / "j.jsonl"
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    j.write_text(json.dumps({"ts": now, "purpose": "extract_tasks", "model": "deepseek-flash",
                             "provider": "api.deepseek.com", "cost_usd": 1.2, "cost_source": "расчёт по тарифу"}) + "\n",
                 encoding="utf-8")
    point = lr.PointLLM("ds", json.loads(path.read_text(encoding="utf-8"))["endpoints"]["ds"], journal_path=j)
    with pytest.raises(ConnectorUnavailable, match="Предел расхода DeepSeek"):
        point.complete("s", "u")
    gen = lr.RoutedLLM("generator", path=path, journal_path=j)
    res = gen.complete("Отвечай JSON.", "текст")
    assert gen.last_route == "local" and res.text, "другие подключения работают"


def test_monitoring_shows_provider_spend(deepseek, tmp_path, monkeypatch):
    path, _ = deepseek
    j = tmp_path / "j.jsonl"
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    j.write_text(json.dumps({"ts": now, "purpose": "x", "model": "deepseek-flash", "provider": "api.deepseek.com",
                             "cost_usd": 0.95, "cost_source": "расчёт по тарифу"}) + "\n", encoding="utf-8")
    rows = {r["provider"]: r for r in lr.provider_limits(j)}
    assert rows["api.deepseek.com"]["state"] == "warn" and "90 %" in rows["api.deepseek.com"]["label"]
