"""Два инструмента подключения модели — решение владельца 03.10.26: «пока
запускаем через OpenRouter; делай сразу два инструмента — через роутер и
локальный (заглушки, как в базовом); при развёртывании — выбор». Потолок
ответа — 4096 токенов на вызов (решение владельца 03.10.26). Сеть не
вызывается: httpx.MockTransport."""
import json

import httpx
import pytest

from meetflow.connectors.base import ConnectorError
from meetflow.connectors.llm_ollama import OllamaLLM
from meetflow.connectors.llm_openrouter import OpenRouterLLM
from meetflow.core.budget import BudgetExceeded, BudgetLimits, RunBudget
from meetflow.core.config import load_theme, validate

MODELS = {"data": [{"id": "qwen/qwen-plus", "pricing": {"prompt": "0.0000004", "completion": "0.0000012"}},
                   {"id": "meta/muse-spark-1.3", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]}


def router(seen, answer=None, status=200, finish="stop"):
    def h(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        seen.append({"body": json.loads(req.content), "auth": req.headers.get("authorization")})
        if status != 200:
            return httpx.Response(status, text="bad request: context too long")
        return httpx.Response(200, json={"choices": [{"message": {"content": answer or '{"tasks": []}'},
                                                       "finish_reason": finish}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0012}})
    return httpx.MockTransport(h)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-real")


def test_openrouter_request_shape(key):
    seen = []
    llm = OpenRouterLLM(model="qwen/qwen-plus", transport=router(seen))
    res = llm.complete("s", "u", purpose="extract_tasks")
    b = seen[0]["body"]
    assert b["max_tokens"] == 4096                                   # потолок ответа — решение владельца
    assert b["usage"] == {"include": True} and b["provider"]["data_collection"] == "deny"
    assert b["reasoning"] == {"enabled": False}                      # рассуждение не съедает потолок
    assert seen[0]["auth"] == "Bearer sk-or-test-not-real"
    assert res.cost_usd == pytest.approx(0.0012) and res.text == '{"tasks": []}'


def test_openrouter_reasoning_required_model(key):
    seen = []
    OpenRouterLLM(model="meta/muse-spark-1.3", transport=router(seen)).complete("s", "u")
    assert seen[0]["body"]["reasoning"] == {"effort": "low", "exclude": True}   # Muse отвечает 400 без рассуждения


def test_openrouter_truncated_answer_not_retried(key):
    seen = []
    with pytest.raises(ConnectorError, match="4096"):
        OpenRouterLLM(model="qwen/qwen-plus", transport=router(seen, finish="length"), backoff=0).complete("s", "u")
    assert len(seen) == 1


def test_openrouter_4xx_not_retried_and_key_not_leaked(key):
    seen = []
    with pytest.raises(ConnectorError) as e:
        OpenRouterLLM(model="qwen/qwen-plus", transport=router(seen, status=400), backoff=0).complete("s", "u")
    assert len(seen) == 1 and "context too long" in str(e.value) and "sk-or-test" not in str(e.value)


def test_openrouter_without_key_refuses(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ConnectorError, match="OPENROUTER_API_KEY"):
        OpenRouterLLM(model="qwen/qwen-plus", transport=router([])).complete("s", "u")
    assert OpenRouterLLM(model="qwen/qwen-plus", transport=router([])).health()["ok"] is False


@pytest.mark.parametrize("model", ["qwen/qwen-plus:contributor", "x/y-contributor"])
def test_openrouter_training_model_refused(key, model):
    with pytest.raises(ConnectorError, match="обучается"):
        OpenRouterLLM(model=model, transport=router([]))


def test_openrouter_worst_call_from_pricing(key):
    llm = OpenRouterLLM(model="meta/muse-spark-1.3", transport=router([]))
    worst = llm.worst_call_usd(3000)                                  # ~1000 токенов запроса + 4096 ответа
    assert worst == pytest.approx(1000 * 0.000003 + 4096 * 0.000015, rel=0.01)


def test_budget_refuses_call_whose_worst_case_does_not_fit():
    b = RunBudget(BudgetLimits(max_cost_usd=0.40, max_calls=10))
    b.check(1000); b.add_cost(0.30, 1000)
    with pytest.raises(BudgetExceeded):
        b.check(1000, worst_usd=0.15)                                 # 0,30 + 0,15 > 0,40 — вызова нет
    b2 = RunBudget(BudgetLimits(max_cost_usd=0.40, max_calls=10))
    b2.check(1000, worst_usd=0.05)                                    # помещается — вызов идёт


def test_ollama_answer_cap_and_truncation():
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"message": {"content": "{}"}, "done_reason": "length"})
    with pytest.raises(ConnectorError, match="4096"):
        OllamaLLM(model="m", transport=httpx.MockTransport(h), backoff=0).complete("s", "u")
    assert seen[0]["options"]["num_predict"] == 4096 and len(seen) == 1


def test_theme_has_both_tools_and_cap():
    th = load_theme("_default")
    assert th.get("llm.max_answer_tokens") == 4096
    # перевёрнут 15.10.26 (находка стенда 25, правило владельца 13.10.26, ответ 15.10.26 — модели по умолчанию нет): 
    assert not th.get("llm.openrouter.generator.model") and not th.get("llm.openrouter.verifier.model")
    assert not th.get("llm.generator.model") and not th.get("llm.verifier.model")
    d = json.loads(json.dumps(th.data))
    d["llm"]["openrouter"]["generator"]["model"] = "qwen/qwen-plus"
    d["llm"]["openrouter"]["verifier"]["model"] = "qwen/qwen-max"
    d["llm"]["openrouter"]["verifier"].pop("family", None)
    assert any("семейств" in e for e in validate(d))                       # разные семейства и у роутера


@pytest.mark.parametrize("mode,cls", [("mock", "MockLLM"), ("ollama", "OllamaLLM"), ("openrouter", "OpenRouterLLM")])
def test_tool_chosen_at_deployment(monkeypatch, key, mode, cls):
    from meetflow.web import app
    monkeypatch.setenv("MEETFLOW_LLM", mode)
    th = load_theme("_default")
    # перевёрнут 15.10.26 (находка стенда 25, правило владельца 13.10.26, ответ 15.10.26 — модели по умолчанию нет): 
    # без модели в теме — «не настроена»; модель задана явно — тот же инструмент, что раньше
    if mode != "mock":
        assert type(app._llm(th, "generator")).__name__ == "NotConfiguredLLM"
        th.data["llm"]["openrouter" if mode == "openrouter" else "generator"] = {
            **(th.data["llm"]["openrouter"]["generator"] if mode == "openrouter" else th.data["llm"]["generator"]),
            "model": "qwen3.8:latest"}
        if mode == "openrouter":
            th.data["llm"]["openrouter"] = {"generator": {"model": "qwen/qwen-plus"}, "verifier": {}}
    assert type(app._llm(th, "generator")).__name__ == cls


def test_unknown_tool_refused(monkeypatch):
    from meetflow.web import app
    monkeypatch.setenv("MEETFLOW_LLM", "cloudy")
    with pytest.raises(ValueError, match="mock, ollama, openrouter"):
        app._llm(load_theme("_default"), "generator")


def test_attack_b2_stopped_when_worst_case_known(store, project, make_pipe):
    """Атака Б2 ветки meeting-registry: 0,05 / 0,05 / 0,35 при потолке 0,40. Модель, которая знает
    свою цену и потолок ответа (как OpenRouter по каталогу), сообщает худший случай — дорогой
    вызов не делается, расход остаётся в пределе, прогон не помечен успешным."""
    from meetflow.connectors.llm_mock import MockLLM
    costs = {"extract_tasks": 0.05, "closing_check": 0.05, "protocol": 0.35}

    class Priced(MockLLM):
        def __init__(self):
            super().__init__()
            self.next = None

        def worst_call_usd(self, prompt_chars):
            return max(costs.values())               # худший случай известен заранее

        def complete(self, system, user, **k):
            r = super().complete(system, user, **k)
            r.cost_usd = costs.get(k.get("purpose"), 0.0)
            return r
    p0 = make_pipe()
    p0.reg.add(project, "Подготовить регламент склада", "Игнатов Иван", date_set="2026-09-01")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Priced(), ver=Priced())
    p.ingest(project, mid, "t 01.10.2026.txt", "[00:00:10] Игнатов Иван: Регламент склада готов, сделано.\n".encode())
    rep = p.run(project, mid, BudgetLimits(max_cost_usd=0.40, max_calls=14))
    assert rep.cost_usd <= 0.40 + 1e-9 and rep.status != "ok"


def test_tool_visible_in_run_journal_and_protocol(store, project, make_pipe, tmp_path):
    """Письмо 17, п. 4: видно, где обработана встреча — подключение и модели в журнале прогона и в протоколе."""
    from conftest import TRANSCRIPT
    from meetflow.connectors.llm_mock import MockLLM
    from meetflow.core.budget import CallJournal

    class Routed(MockLLM):
        name, model = "openrouter", "qwen/qwen-plus"

    class Checker(MockLLM):
        name, model = "openrouter", "meta/muse-spark-1.3"
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Routed(), ver=Checker())
    p.journal = CallJournal(tmp_path / "j.jsonl")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    run = [r for r in p.journal.records if r.get("run") == mid][-1]
    assert run["llm_tool"] == "openrouter" and run["generator"] == "qwen/qwen-plus" and run["verifier"] == "meta/muse-spark-1.3"
    proto = store.get("meetings", mid)["protocol_md"]
    # перевёрнут 15.10.26 (находка стенда 30, правило владельца 13.10.26): документ чистый — пометка модели — в журнале (выше), не в документе
    assert "OpenRouter" not in proto and "qwen/qwen-plus" not in proto and "meta/muse-spark-1.3" not in proto
