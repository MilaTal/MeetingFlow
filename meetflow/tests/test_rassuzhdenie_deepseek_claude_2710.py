# -*- coding: utf-8 -*-
"""Рассуждение модели: DeepSeek без рассуждения, Claude — усилие в настройке точки (перенос из ERP 27.10.2026).

Тесты близнеца ERP main 595036d6 `webapp/tests/test_rassuzhdenie_deepseek_claude_2710.py` на устройстве MeetFlow:
рабочий вызов — `llm_routes.PointLLM`, пробный запрос и «Проверить связь» — общий `model_routes` (копия ERP до байта),
строка журнала вызовов — `MeetingPipeline._call` из `res.raw`. Экран «Модели» здесь не проверяется: он приходит с фронтом
ERP v73.

Решение владелицы 16.10.2026 «вернуть в статус 0» — у DeepSeek рассуждение выключено: у модели DeepSeek `auto` =
«выключено» (openai — `reasoning_effort: "none"`, openrouter — `reasoning: {"enabled": false}`); low и high — как раньше.
У Claude по адресу api.anthropic.com поле точки управляющее: auto — low, low/high — `output_config.effort`, none — отказ
при загрузке и записи. `LLM_CLAUDE_EFFORT` — только переопределение. Сети нет: ответы подставлены, тела записываются.
"""
import io
import json
import urllib.request

import pytest

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.base import ConnectorError
from meetflow.connectors.shared import model_routes as mr
from meetflow.core.budget import CallJournal, RunBudget

АДРЕС_ANTHROPIC = "https://api.anthropic.com"
ОТВЕТ = '{"ok": 1}'


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sse(события: list, anthropic: bool) -> bytes:
    if anthropic:
        return "".join(f"event: {с['type']}\ndata: {json.dumps(с, ensure_ascii=False)}\n\n" for с in события).encode()
    return ("".join("data: " + json.dumps(с, ensure_ascii=False) + "\n\n" for с in события) + "data: [DONE]\n\n").encode()


def _ответ(url: str, тело: dict) -> bytes:
    anthropic = "api.anthropic.com" in url
    if not тело.get("stream"):
        if anthropic:
            return json.dumps({"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": ОТВЕТ}],
                               "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 3}}).encode()
        return json.dumps({"choices": [{"message": {"content": ОТВЕТ}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 3}}).encode()
    if anthropic:
        return _sse([
            {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "content": [],
                                                  "usage": {"input_tokens": 10, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ок"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
            {"type": "message_stop"}], True)
    return _sse([{"choices": [{"delta": {"content": "ок"}}]},
                 {"choices": [{"delta": {}, "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 5, "completion_tokens": 2}}], False)


@pytest.fixture
def стенд(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_KEY_2710", "sk-vydumannyj-2710")
    monkeypatch.setenv("MODEL_PROBE", "off")
    monkeypatch.delenv("LLM_CLAUDE_EFFORT", raising=False)
    monkeypatch.setattr(lr.time, "sleep", lambda s: None)
    запросы: list[dict] = []

    def urlopen(req, *a, **k):
        тело = json.loads(req.data.decode("utf-8"))
        запросы.append({"url": req.full_url, "body": тело})
        return _Resp(_ответ(req.full_url, тело))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    журнал = tmp_path / "llm_calls.jsonl"

    def точка(род: str = "openai", модель: str = "deepseek-flash", режим: str = "auto",
              url: str = "https://api.deepseek.com") -> lr.PointLLM:
        ep = {"kind": род, "model": модель, "key_env": "TEST_KEY_2710"}
        if режим != "auto":
            ep["reasoning"] = режим
        if род == "openai":
            ep["url"] = url
        return lr.PointLLM("p", ep, journal_path=журнал)
    return точка, запросы, журнал


def _три_пути(p: lr.PointLLM):
    """Рабочий вызов, пробный запрос и «Проверить связь» — одной точкой; ответ рабочего и текст «Проверить связь»."""
    res = p.complete("s", "u", purpose="protocol")
    mr.probe(p.route, chars=100)
    ok, подробно = mr.ping(p.route)
    assert ok, подробно
    return res, подробно


# --- DeepSeek: auto = выключено -------------------------------------------------------------------------------------

def test_deepseek_auto_выключено_во_всех_трёх_путях(стенд):
    точка, запросы, _ = стенд
    res, подробно = _три_пути(точка())
    assert [з["body"].get("reasoning_effort") for з in запросы] == ["none", "none", "none"]
    assert "рассуждение none" in подробно and "reasoning_chars 0" in подробно
    assert res.raw["reasoning_effort"] == "none"


def test_deepseek_openrouter_auto_выключено(стенд):
    точка, запросы, _ = стенд
    точка("openrouter", "deepseek/deepseek-chat").complete("s", "u")
    assert запросы[-1]["body"]["reasoning"] == {"enabled": False}


@pytest.mark.parametrize("режим", ["low", "high"])
def test_deepseek_явные_low_high_как_раньше(стенд, режим):
    точка, запросы, _ = стенд
    res, _ = _три_пути(точка(режим=режим))
    assert [з["body"].get("reasoning_effort") for з in запросы] == [режим] * 3
    assert res.raw["reasoning_effort"] == режим


def test_прибор_прочие_модели_auto_поля_не_шлют(стенд):
    """Прибор: правило держится на имени DeepSeek — у другой модели на том же входе поле при auto не уходит."""
    точка, запросы, _ = стенд
    res = точка(модель="qwen-plus", url="http://127.0.0.1:9").complete("s", "u")
    assert "reasoning_effort" not in запросы[-1]["body"] and res.raw["reasoning_effort"] == "auto"
    # у DeepSeek на родном протоколе Ollama поля нет вовсе — рассуждение там не настраивается
    assert mr.reasoning_effort(mr._route("o", {"kind": "ollama", "url": "http://127.0.0.1:9",
                                               "model": "deepseek-r1"})) is None


# --- Claude: поле точки управляющее ---------------------------------------------------------------------------------

@pytest.mark.parametrize("режим,усилие", [("auto", "low"), ("low", "low"), ("high", "high")])
def test_claude_усилие_из_поля_точки_во_всех_трёх_путях(стенд, режим, усилие):
    точка, запросы, _ = стенд
    res, подробно = _три_пути(точка(модель="claude-sonnet-5-5", режим=режим, url=АДРЕС_ANTHROPIC))
    assert [з["url"] for з in запросы] == [АДРЕС_ANTHROPIC + "/v1/messages"] * 3
    assert [з["body"].get("output_config") for з in запросы] == [{"effort": усилие}] * 3
    assert all(not {"reasoning_effort", "reasoning", "thinking"} & set(з["body"]) for з in запросы)
    assert f"рассуждение {усилие}" in подробно and res.raw["reasoning_effort"] == усилие


def test_claude_переменная_только_переопределение(стенд, monkeypatch):
    точка, запросы, _ = стенд
    p = точка(модель="claude-sonnet-5-5", режим="high", url=АДРЕС_ANTHROPIC)
    monkeypatch.setenv("LLM_CLAUDE_EFFORT", "medium")
    p.complete("s", "u")
    assert запросы[-1]["body"]["output_config"] == {"effort": "medium"}
    monkeypatch.setenv("LLM_CLAUDE_EFFORT", "чепуха")     # неверное слово — решает поле точки
    p.complete("s", "u")
    assert запросы[-1]["body"]["output_config"] == {"effort": "high"}


def test_claude_none_отказ_при_загрузке_и_записи(tmp_path):
    path = tmp_path / "models.json"
    плохой = {"kind": "openai", "url": АДРЕС_ANTHROPIC, "model": "claude-opus-5-5", "reasoning": "none",
              "key_env": "TEST_KEY_2710"}
    with pytest.raises(ConnectorError, match="у Claude рассуждение не выключается"):
        lr.validate({"endpoints": {"p": плохой}, "roles": {"generate": ["p"]}})
    path.write_text(json.dumps({"endpoints": {}, "roles": {}}), encoding="utf-8")
    with pytest.raises(ConnectorError, match="не выключается"):
        lr.save_point("claude", {**плохой, "url": АДРЕС_ANTHROPIC + "/"}, path=path)
    lr.save_point("claude", {**плохой, "reasoning": "high"}, path=path)
    файл = json.loads(path.read_text(encoding="utf-8"))
    assert файл["endpoints"]["claude"]["reasoning"] == "high"


# --- журнал вызовов: с каким рассуждением ушёл вызов ----------------------------------------------------------------

def test_журнал_вызовов_несёт_рассуждение(стенд, make_pipe, tmp_path):
    точка, _, _ = стенд
    pipe = make_pipe()
    pipe.journal = CallJournal(tmp_path / "calls.jsonl")
    for p in (точка(), точка(модель="claude-sonnet-5-5", режим="high", url=АДРЕС_ANTHROPIC),
              точка(модель="qwen-plus", url="http://127.0.0.1:9")):
        assert pipe._call(p, RunBudget(), "protocol", "s", "u", 1) == {"ok": 1}
    строки = [json.loads(с) for с in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [с.get("reasoning_effort") for с in строки] == ["none", "high", "auto"]


def test_строка_отброшенной_попытки_несёт_рассуждение(стенд, monkeypatch):
    точка, _, журнал = стенд
    p = точка()

    def пусто(req, *a, **k):
        return _Resp(json.dumps({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
                                 "usage": {"completion_tokens": 0}}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", пусто)
    with pytest.raises(Exception):
        p.complete("s", "u", purpose="protocol")
    строки = [json.loads(с) for с in журнал.read_text(encoding="utf-8").splitlines()]
    assert строки and all(с.get("reasoning_effort") == "none" and с.get("stop") for с in строки)


def test_reasoning_sent_без_точки_и_у_ollama_пусто():
    assert mr.reasoning_sent(None) is None and mr.journal_reasoning(None) == {}
    assert mr.reasoning_sent(mr._route("o", {"kind": "ollama", "url": "http://127.0.0.1:9", "model": "m"})) is None
