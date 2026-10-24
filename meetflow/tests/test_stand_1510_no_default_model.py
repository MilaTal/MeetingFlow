"""Находка стенда 25 — модели по умолчанию нет (правило владельца 13.10.26 для ERP, Планёрки и MeetFlow); ответ
владельца 15.10.26 (через «Мониторинг»): без назначения роль «не настроена», ни одного вызова; заглушка — только явным
MEETFLOW_LLM=mock; настройки подключения ERP и Планёрки — заготовками точек без адресов и ключей; функции точки — как
у них, по общему model_routes.py (ключ значением вне git, рассуждение, потолок ответа, Claude без temperature).
Тесты написаны до правки и падали."""
import hashlib
import json
from pathlib import Path

import pytest

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.base import ConnectorError
from meetflow.connectors.shared import model_routes as mr

SHARED = Path(lr.__file__).parent / "shared"


@pytest.fixture
def routes(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setattr(mr._state, "down_until", {})
    monkeypatch.setattr(mr._state, "last_error", {})
    return path


def test_shared_modules_are_byte_copies():
    """Общие модули ERP и Планёрки — копии байт в байт; правятся там, переносятся целиком."""
    assert hashlib.md5((SHARED / "model_routes.py").read_bytes()).hexdigest().startswith("f839eb2891d8")
    assert hashlib.md5((SHARED / "llm_cost.py").read_bytes()).hexdigest().startswith("7d6d18d214f8")


def test_without_meetflow_llm_it_is_routes_not_mock(routes, monkeypatch):
    from meetflow.core.config import load_theme
    from meetflow.web import app
    monkeypatch.delenv("MEETFLOW_LLM", raising=False)
    llm = app._llm(load_theme("_default"), "generator")
    assert isinstance(llm, lr.RoutedLLM) and not llm.configured
    assert routes.exists(), "справочник заготовок положен"
    data = json.loads(routes.read_text(encoding="utf-8"))
    assert data["roles"] == {}
    for name, ep in data["endpoints"].items():
        assert not ep.get("url") and not ep.get("key_env") and "key" not in ep, name
    with pytest.raises(ConnectorError, match="не настроена"):
        llm.complete("s", "u")


def test_presets_as_in_erp_and_planerka(routes):
    eps = {e["name"]: e for e in lr.panel()["endpoints"]}
    assert eps["deepseek"]["fields"]["model"] == "deepseek-flash" and eps["deepseek"]["fields"]["reasoning"] == "none"
    assert eps["deepseek"]["fields"]["max_tokens"] == 96000 and eps["deepseek"]["missing"]
    assert eps["claude"]["fields"]["model"] == "claude-sonnet-5-5" and "reasoning" not in eps["claude"]["fields"]
    assert eps["qwen-local"]["kind"] == "ollama" and eps["qwen-local"]["fields"]["max_tokens"] == 8000
    assert eps["openrouter"]["kind"] == "openrouter"
    assert {eps[n]["kind"] for n in ("whisper", "asr-code", "asr-service")} == {"faster-whisper", "python", "asr-service"}
    assert all(e["missing"] for e in eps.values()), "заготовка без адреса или модели — «не настроена»"


def test_no_role_falls_back_to_another(routes):
    # перевёрнут 15.10.26 (ответ владельца через «Мониторинг»: «как в ERP и Планёрке», решения 09.10 и 13.10.26):
    # роль проверки без своей точки идёт на модель черновика, назначенную администратором, и это показано явно;
    # «не настроена» — только когда не назначено ни то, ни другое. Остальные роли без точек — «не настроена».
    lr.ensure_file()
    ver = lr.RoutedLLM("verifier")
    assert not ver.configured                                    # нет ни своей точки, ни модели черновика
    with pytest.raises(ConnectorError, match="Проверка черновика"):
        ver.complete("s", "u")
    lr.save_point("local", {"kind": "ollama", "url": "http://localhost:11434", "model": "qwen3.8:latest"})
    lr.add_to_role("generate", "local")
    assert lr.RoutedLLM("generator").configured
    ver = lr.RoutedLLM("verifier")
    assert ver.configured and ver.chain() == ["local"] and ver.borrowed
    assert ver.display == "модель черновика: local · отдельная модель проверки не назначена"
    d = lr.panel()
    assert d["roles"]["verify"] == [] and d["verify_fallback"] == "local" and "verify" not in d["not_configured"]
    assert not lr.configured("guard") and lr.asr_chain() is None   # досмотр и распознавание — без подстановки


def test_run_without_model_makes_no_calls(routes, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    monkeypatch.delenv("MEETFLOW_LLM", raising=False)
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c, H = TestClient(app), {"X-User-Role": "project_admin"}
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H,
           files={"file": ("t 01.10.2026.txt", "[00:01:00] Игнатов Иван: текст встречи\n".encode())})
    rep = c.post(f"/api/meetings/{mid}/run", headers=H).json()
    assert rep["status"] == "not_configured" and rep["calls"] == 0
    assert app.state.store.q("SELECT * FROM cards WHERE title='Сборка не начата: модель не настроена'")


def test_theme_has_no_default_models():
    from meetflow.core.config import load_theme
    th = load_theme("_default")
    for key in ("llm.openrouter.generator.model", "llm.openrouter.verifier.model", "llm.generator.model",
                "llm.verifier.model", "llm.vision.model"):
        assert not th.get(key), key


def test_env_tool_without_theme_model_is_not_configured(monkeypatch):
    from meetflow.core.config import load_theme
    from meetflow.web import app
    monkeypatch.setenv("MEETFLOW_LLM", "openrouter")
    llm = app._llm(load_theme("_default"), "generator")
    assert llm.configured is False
    with pytest.raises(ConnectorError, match="не настроена"):
        llm.complete("s", "u")


def test_key_by_value_never_leaves(routes):
    lr.ensure_file()
    lr.save_point("ds", {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash",
                         "key_source": "value"}, key_value="sk-test-1234567890abcdefWXYZ")
    assert "sk-test" not in routes.read_text(encoding="utf-8")
    keys = routes.with_name("model_keys.local.json")
    assert keys.exists() and "sk-test" in keys.read_text(encoding="utf-8")
    ep = next(e for e in lr.panel()["endpoints"] if e["name"] == "ds")
    assert ep["key"] == "ключ задан · …WXYZ" and "sk-test" not in json.dumps(lr.panel(), ensure_ascii=False)
    assert "sk-test" not in mr.scrub("Authorization: Bearer sk-test-1234567890abcdefWXYZ")


def test_point_body_follows_shared_rules(routes):
    claude = lr.PointLLM("c", {"kind": "openai", "url": "https://api.anthropic.com/v1", "model": "claude-sonnet-5-5",
                               "max_tokens": 32000})
    b = claude.body("s", "u", True, 0.0)
    assert "temperature" not in b and "top_p" not in b and b["max_tokens"] == 32000 and "reasoning_effort" not in b
    ds = lr.PointLLM("d", {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash",
                           "reasoning": "none", "max_tokens": 96000})
    b = ds.body("s", "u", True, 0.0)
    assert b["reasoning_effort"] == "none" and b["max_tokens"] == 96000 and b["temperature"] == 0.0
    assert ds.route.endpoint == "https://api.deepseek.com/v1/chat/completions" and ds.route.uses_proxy
    glm = lr.PointLLM("g", {"kind": "openai", "url": "https://api.z.ai/api/paas/v4", "model": "glm-5"})
    assert glm.route.endpoint == "https://api.z.ai/api/paas/v4/chat/completions"    # адрес с версией (Z.ai)
    orr = lr.PointLLM("o", {"kind": "openrouter", "model": "qwen/qwen-plus", "reasoning": "high"}, max_answer_tokens=4096)
    b = orr.body("s", "u", True, 0.0)
    assert b["provider"] == {"data_collection": "deny"} and b["reasoning"] == {"effort": "high"} and b["max_tokens"] == 4096
    local = lr.PointLLM("l", {"kind": "ollama", "url": "http://localhost:11434", "model": "qwen3.8:latest", "max_tokens": 8000})
    assert local.body("s", "u", True, 0.0)["options"]["num_predict"] == 8000 and not local.route.uses_proxy


def test_asr_role_never_external(routes):
    lr.ensure_file()
    with pytest.raises(ConnectorError, match="внутренней сети"):
        lr.save_point("ext-asr", {"kind": "asr-service", "url": "https://asr.example.com/transcribe"})
    lr.save_point("ds", {"kind": "openai", "url": "https://api.deepseek.com", "model": "deepseek-flash"})
    with pytest.raises(ConnectorError):
        lr.add_to_role("asr", "ds")
    data = json.loads(routes.read_text(encoding="utf-8"))
    data["roles"]["asr"] = ["ds"]
    routes.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConnectorError):
        lr.asr_chain()


def test_run_record_says_verify_borrowed(routes, store, project, make_pipe):
    """Сведения о прогоне: проверку делала модель черновика — записано явно (ответ владельца 15.10.26)."""
    lr.ensure_file()
    lr.save_point("local", {"kind": "ollama", "url": "http://localhost:11434", "model": "qwen3.8:latest"})
    lr.add_to_role("generate", "local")
    from meetflow.connectors.llm_mock import MockLLM
    p = make_pipe(gen=MockLLM(), ver=lr.RoutedLLM("verifier", factory=lambda n, ep: MockLLM()))
    assert p.tool_info["verifier_note"] == "модель черновика: local · отдельная модель проверки не назначена"
