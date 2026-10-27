# -*- coding: utf-8 -*-
"""Общий клиент моделей как в ERP (перенос 27.10.2026, записи DECISIONS ERP 26.10.2026).

1. Claude — родной Messages API (`/v1/messages`, `x-api-key`, `anthropic-version`, `output_config.effort` = low,
   системная подсказка полем `system`); поля OpenAI-совместимого входа не уходят. Пустой ответ при остановке по потолку —
   стоп с причиной без повтора, в журнале `completion_tokens` и `empty_at_ceiling`.
2. Негодный ответ (пустой, зацикливание) — не больше `BAD_ANSWERS_PER_CALL` = 2 обращений на вызов, на запасную точку
   не уходит; каждая отброшенная попытка — строка `stop` (`model_routes.stop_line`) в журнале.
3. Прочие точки (DeepSeek) — прежним входом.

Сети нет: ответы поставщика подставлены, адрес, заголовки и тело каждого запроса записываются. Ключ выдуманный.
"""
import io
import json
import urllib.request

import pytest

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.base import AnswerTruncated, BadAnswer
from meetflow.connectors.shared import model_routes as mr

КЛЮЧ = "sk-ant-vydumannyj-2710"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _claude(text: str, stop: str = "end_turn", out: int = 50) -> dict:
    content = [{"type": "thinking", "thinking": "", "signature": "EqQB"}]
    if text:
        content.append({"type": "text", "text": text})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": content,
            "stop_reason": stop, "usage": {"input_tokens": 1000, "output_tokens": out, "cache_read_input_tokens": 200}}


def _openai(text: str, finish: str = "stop") -> dict:
    return {"model": "deepseek-flash", "choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3}}


@pytest.fixture
def сеть(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_TEST_KEY", КЛЮЧ)
    monkeypatch.setenv("DS_TEST_KEY", "sk-ds-vydumannyj")
    monkeypatch.delenv("LLM_CLAUDE_EFFORT", raising=False)
    monkeypatch.setattr(lr.time, "sleep", lambda s: None)
    запросы: list[dict] = []
    ответы: list = []

    def urlopen(req, *a, **k):
        запросы.append({"url": req.full_url, "headers": {к.lower(): з for к, з in req.header_items()},
                        "body": json.loads(req.data.decode("utf-8"))})
        return _Resp(json.dumps(ответы.pop(0)).encode("utf-8"))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    журнал = tmp_path / "llm_calls.jsonl"

    def строки() -> list[dict]:
        return [json.loads(x) for x in журнал.read_text(encoding="utf-8").splitlines()] if журнал.exists() else []
    return запросы, ответы, журнал, строки


def _claude_point(журнал, потолок: int = 32000) -> lr.PointLLM:
    ep = {"kind": "openai", "url": "https://api.anthropic.com", "model": "claude-sonnet-5-5",
          "key_env": "CLAUDE_TEST_KEY", "max_tokens": потолок}
    return lr.PointLLM("claude", ep, journal_path=журнал)


def _ds_point(журнал) -> lr.PointLLM:
    ep = {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash", "key_env": "DS_TEST_KEY"}
    return lr.PointLLM("deepseek", ep, journal_path=журнал)


def test_общий_модуль_копия_erp():
    """Копия общего клиента совпадает с ERP 595036d6 (scripts/model_routes.py) до байта."""
    assert hasattr(mr, "wire_request") and hasattr(mr, "stop_line") and mr.BAD_ANSWERS_PER_CALL == 2
    assert mr.CLAUDE_EFFORT_DEFAULT == "low"


def test_claude_идёт_в_messages_api_с_усилием(сеть):
    запросы, ответы, журнал, _ = сеть
    ответы.append(_claude('{"ok": 1}'))
    res = _claude_point(журнал).complete("Ты секретарь.", "Запись встречи", purpose="protocol")
    assert res.text == '{"ok": 1}'
    q = запросы[-1]
    assert q["url"] == "https://api.anthropic.com/v1/messages"
    assert q["headers"].get("x-api-key") == КЛЮЧ and "authorization" not in q["headers"]
    assert q["headers"].get("anthropic-version") == mr.ANTHROPIC_VERSION
    тело = q["body"]
    assert тело["output_config"] == {"effort": "low"} and тело["system"] == "Ты секретарь."
    assert [r["role"] for r in тело["messages"]] == ["user"]
    assert not {"temperature", "top_p", "response_format", "reasoning", "reasoning_effort", "thinking"} & set(тело)
    # расход Messages API — словами OpenAI: вход вместе с кэшем
    assert res.prompt_tokens == 1200 and res.completion_tokens == 50


def test_усилие_переменной(сеть, monkeypatch):
    запросы, ответы, журнал, _ = сеть
    monkeypatch.setenv("LLM_CLAUDE_EFFORT", "medium")
    ответы.append(_claude("{}"))
    _claude_point(журнал).complete("с", "у")
    assert запросы[-1]["body"]["output_config"] == {"effort": "medium"}


def test_пустой_ответ_по_потолку_стоп_без_повтора(сеть):
    запросы, ответы, журнал, строки = сеть
    ответы += [_claude("", stop="max_tokens", out=32000), _claude("{}")]
    with pytest.raises(BadAnswer, match="обрыв по потолку — ответ пуст.*completion_tokens 32000"):
        _claude_point(журнал).complete("с", "у", purpose="protocol")
    assert len(запросы) == 1, "повтор тем же запросом не делается"
    стоп = [r for r in строки() if r.get("stop")]
    assert len(стоп) == 1 and стоп[0]["empty_at_ceiling"] is True and стоп[0]["completion_tokens"] == 32000
    assert "Запись" not in json.dumps(стоп, ensure_ascii=False)


def test_обрыв_с_текстом_по_прежнему_обрыв(сеть):
    запросы, ответы, журнал, _ = сеть
    ответы.append(_openai('{"tasks": [', finish="length"))
    with pytest.raises(AnswerTruncated):
        _ds_point(журнал).complete("с", "у")


def test_пустой_ответ_не_больше_двух_обращений_и_не_на_запасную(сеть, tmp_path, monkeypatch):
    запросы, ответы, журнал, строки = сеть
    path = tmp_path / "models.json"
    eps = {"deepseek": {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash",
                        "key_env": "DS_TEST_KEY"},
           "claude": {"kind": "openai", "url": "https://api.anthropic.com", "model": "claude-sonnet-5-5",
                      "key_env": "CLAUDE_TEST_KEY"}}
    path.write_text(json.dumps({"endpoints": eps, "roles": {"generate": ["deepseek", "claude"]}}), encoding="utf-8")
    monkeypatch.setattr(mr._state, "down_until", {})
    llm = lr.RoutedLLM("generator", path=path, journal_path=журнал)
    ответы += [_openai(""), _openai(""), _claude("{}")]
    with pytest.raises(BadAnswer, match="негодный ответ"):
        llm.complete("с", "у", purpose="extract_tasks")
    assert len(запросы) == 2 and all("deepseek" in q["url"] for q in запросы)
    стоп = [r["stop"] for r in строки() if r.get("stop")]
    assert len(стоп) == 2 and "остановлено: пустой ответ" in стоп[0] and "шаг «extract_tasks»" in стоп[0]


def test_зацикливание_один_повтор_с_напоминанием(сеть):
    запросы, ответы, журнал, строки = сеть
    петля = "Обсудили график поставки бетона на объект. " * 300
    ответы += [_openai(петля), _openai('{"ok": 1}')]
    res = _ds_point(журнал).complete("с", "у", purpose="protocol")
    assert res.text == '{"ok": 1}' and len(запросы) == 2
    assert mr.LOOP_REMINDER.strip()[:20] in запросы[1]["body"]["messages"][-1]["content"]
    assert any("зацикливание" in (r.get("stop") or "") for r in строки())


def test_deepseek_прежним_входом(сеть):
    запросы, ответы, журнал, _ = сеть
    ответы.append(_openai("{}"))
    _ds_point(журнал).complete("с", "у")
    q = запросы[-1]
    assert q["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert q["headers"].get("authorization") == "Bearer sk-ds-vydumannyj" and "x-api-key" not in q["headers"]
    assert q["body"]["messages"][0]["role"] == "system" and "output_config" not in q["body"]
