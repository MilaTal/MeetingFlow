"""Маршруты моделей, MEETFLOW_LLM=routes (решение владельца 09.10.26): цепочка точек по роли, переход на запасную
при недоступности, переключение без перезапуска. Точки подменены: проверяется, какая ответила."""
import json

import pytest

from meetflow.connectors.base import ConnectorError, ConnectorUnavailable, LLMConnector
from meetflow.connectors import llm_routes as lr
from meetflow.core.types import LLMResult


class Fake(LLMConnector):
    def __init__(self, name, mode, calls):
        self.name, self.model, self.profile, self.mode, self.calls = name, f"model-{name}", "generic", mode, calls
        self.context_chars = 100_000

    def worst_call_usd(self, prompt_chars):
        return {"main": 0.01, "spare": 0.05}.get(self.name)

    def complete(self, system, user, **kw):
        self.calls.append(self.name)
        m = self.mode.get(self.name, "ok")
        if m == "down":
            raise ConnectorUnavailable(f"{self.name} не отвечает")
        if m == "bad":
            raise ConnectorError(f"{self.name}: HTTP 400")
        return LLMResult(f"ответ {self.name}", self.model, raw={})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "endpoints": {"main": {"kind": "openai", "url": "http://main", "model": "m"},
                      "spare": {"kind": "openrouter", "model": "s"},
                      "check": {"kind": "ollama", "url": "http://localhost:11434", "model": "c"}},
        "roles": {"generate": ["main", "spare"], "verify": ["check", "spare"]}, "cooldown_sec": 300,
    }), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    # охлаждение точек хранит общий модуль ERP и Планёрки (с 15.10.26)
    monkeypatch.setattr(lr.mr._state, "down_until", {})
    monkeypatch.setattr(lr.mr._state, "last_error", {})
    calls, mode = [], {}
    make = lambda side: lr.RoutedLLM(side, factory=lambda n, ep: Fake(n, mode, calls))  # noqa: E731
    return path, calls, mode, make


def test_primary_answers_and_route_is_recorded(setup):
    _, calls, _, make = setup
    res = make("generator").complete("s", "u")
    assert res.text == "ответ main" and res.raw["route"] == "main" and calls == ["main"]


def test_unavailable_point_hands_over_and_rests(setup):
    _, calls, mode, make = setup
    llm = make("generator")
    mode["main"] = "down"
    assert llm.complete("s", "u").text == "ответ spare"
    calls.clear()
    assert llm.complete("s", "u").text == "ответ spare"
    assert calls == ["spare"]                      # главная на охлаждении — сразу запасная
    assert "main" in llm.health()["down"]


def test_request_error_is_not_carried_over(setup):
    _, calls, mode, make = setup
    mode["main"] = "bad"
    with pytest.raises(ConnectorError) as e:
        make("generator").complete("s", "u")
    assert not isinstance(e.value, ConnectorUnavailable) and calls == ["main"]


def test_verifier_has_its_own_chain(setup):
    _, calls, _, make = setup
    assert make("verifier").complete("s", "u").text == "ответ check"


def test_switch_without_restart(setup):
    path, _, _, make = setup
    llm = make("generator")
    lr.use("generate", "spare", path)
    assert llm.complete("s", "u").text == "ответ spare"   # тот же объект подхватил файл
    lr.use("generate", "main", path)
    assert llm.complete("s", "u").text == "ответ main"


def test_all_down_names_the_points(setup):
    _, _, mode, make = setup
    mode["main"] = mode["spare"] = "down"
    with pytest.raises(ConnectorUnavailable, match="main.*spare"):
        make("generator").complete("s", "u")


def test_worst_case_is_the_dearest_point(setup):
    _, _, _, make = setup
    assert make("generator").worst_call_usd(1000) == 0.05


def test_bad_file_is_explained(setup):
    path, _, _, make = setup
    path.write_text(json.dumps({"endpoints": {"a": {"kind": "openai", "model": "m"}}, "roles": {"generate": ["a"]}}),
                    encoding="utf-8")
    with pytest.raises(ConnectorError, match="адрес"):
        make("generator")


def test_app_picks_routes_mode(setup, monkeypatch):
    from meetflow.core.config import load_theme
    from meetflow.web import app
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    llm = app._llm(load_theme("it_product"), "generator")
    assert isinstance(llm, lr.RoutedLLM) and llm.chain() == ["main", "spare"]


def test_openai_point_sends_no_openrouter_extensions(monkeypatch):
    import httpx
    from meetflow.connectors.llm_openrouter import OpenRouterLLM
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "да"}, "finish_reason": "stop"}]})

    llm = OpenRouterLLM(model="qwen3.8-27b", api_base="http://lmstudio:1234/v1", key_env="", label="lmstudio",
                        transport=httpx.MockTransport(handler))
    assert llm.complete("s", "u", json_mode=False).text == "да"
    assert seen["url"] == "http://lmstudio:1234/v1/chat/completions"
    assert not {"usage", "provider", "reasoning"} & set(seen["body"])


# --- Вкладка «Модели» в «Мониторинге» (09.10.26): только супер-администратору, переключение без перезапуска ---


def test_monitoring_models_api(setup, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    path, _, _, _ = setup
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    client = TestClient(create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False))
    sup, member = {"X-User-Role": "super_admin"}, {"X-User-Role": "member"}
    assert client.get("/api/monitoring/models", headers=member).status_code == 403
    d = client.get("/api/monitoring/models", headers=sup).json()
    assert d["switchable"] and [p["name"] for p in d["roles"]["generate"]] == ["main", "spare"]
    assert client.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=member).status_code == 403
    after = client.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"},
                        headers={**sup, "X-User-Name": "boss"}).json()
    assert after["roles"]["generate"][0]["name"] == "spare"
    rec = json.loads(path.with_name("models.log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["point"] == "spare" and rec["by"] == "boss"
    assert client.post("/api/monitoring/models/use", json={"role": "generate", "point": "нет"}, headers=sup).status_code == 400


def test_monitoring_models_without_file_explains(tmp_path, monkeypatch):
    # перевёрнут 15.10.26 (находка стенда 25, правило владельца 13.10.26, ответ 15.10.26 — модели по умолчанию нет): 
    # файла нет — кладётся справочник заготовок без адресов и ключей, ни одна роль не назначена
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(tmp_path / "нет.json"))
    d = lr.panel()
    assert d["switchable"] and (tmp_path / "нет.json").exists()
    assert d["not_configured"] == ["generate", "verify", "asr"] and all(not d["roles"][r] for r in lr.ROLES)
    assert {e["name"] for e in d["endpoints"]} >= {"deepseek", "claude", "openrouter", "qwen-local", "whisper"}


# --- Распознавание через маршруты и ручной выбор модели (09.10.26) --------------------------------------------


def _with_asr(path, chain, extra=None):
    data = json.loads(path.read_text(encoding="utf-8"))
    data["endpoints"].update({"whisper-gpu": {"kind": "faster-whisper", "model": "large-v3", "device": "cuda"},
                              "whisper-cpu": {"kind": "faster-whisper", "model": "tiny", "device": "cpu"},
                              "сломанный-код": {"kind": "python", "callable": "asr_plugin_mf:broken"},
                              "свой-код": {"kind": "python", "callable": "asr_plugin_mf:transcribe"}, **(extra or {})})
    if chain is not None:
        data["roles"]["asr"] = chain
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def asr_plugin(tmp_path, monkeypatch):
    (tmp_path / "asr_plugin_mf.py").write_text(
        "def transcribe(wav, **kw):\n    return '[00:00:01] Говорящий: текст своего движка', {'duration': 1800}\n"
        "def broken(wav, **kw):\n    raise RuntimeError('движок не поднялся')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    rec = tmp_path / "rec.mp4"
    rec.write_bytes(b"x")
    return rec


def test_asr_role_accepts_only_local_engines(setup):
    path, *_ = setup
    _with_asr(path, ["main"])
    with pytest.raises(ConnectorError, match="только через faster-whisper, свой код или сервис"):   # текст общего модуля
        lr.asr_chain()
    _with_asr(path, ["whisper-cpu"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["roles"]["generate"] = ["whisper-cpu"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConnectorError, match="не может писать текст"):
        lr.asr_chain()


def test_asr_through_routes_falls_back_and_marks_point(setup, asr_plugin):
    from meetflow.connectors.asr_whisper import WhisperLocalASR
    path, *_ = setup
    _with_asr(path, ["сломанный-код", "свой-код"])
    asr = WhisperLocalASR(duration_min=20, duration_max=90)
    doc = asr.transcribe(asr_plugin)
    assert "своего движка" in doc.text and doc.meta["route"] == "свой-код"
    assert "сломанный-код" in lr.mr._state.down_until


def test_asr_gpu_point_hands_over_to_cpu_point(setup, asr_plugin, monkeypatch):
    from meetflow.connectors.asr_whisper import WhisperLocalASR
    path, *_ = setup
    _with_asr(path, ["whisper-gpu", "whisper-cpu"])
    asr = WhisperLocalASR()
    seen = []

    class Seg:
        start, text = 1, "процессор"

    def load_point(model, device="auto"):
        seen.append(device)
        if device == "cuda":
            raise RuntimeError("CUDA out of memory")
        return type("M", (), {"transcribe": lambda *a, **k: ([Seg()], type("I", (), {"duration": 60})())})()

    monkeypatch.setattr(asr, "_load_point", load_point)
    doc = asr.transcribe(asr_plugin)
    assert seen == ["cuda", "cpu"] and doc.meta["route"] == "whisper-cpu" and "процессор" in doc.text


def test_asr_without_role_works_as_before(setup, asr_plugin):
    # перевёрнут 15.10.26 (находка стенда 25, правило владельца 13.10.26, уточнение 15.10.26): без роли asr запись
    # не распознаётся моделью темы — ждёт с понятной причиной, пока супер-администратор не назначит точку
    from meetflow.connectors.asr_whisper import WhisperLocalASR
    path, *_ = setup
    _with_asr(path, None)
    assert lr.asr_chain() is None

    class Seg:
        start, text = 1, "модель темы"

    asr = WhisperLocalASR()
    asr._model = type("M", (), {"transcribe": lambda *a, **k: ([Seg()], type("I", (), {"duration": 60})())})()
    with pytest.raises(ConnectorError, match="waiting_tools: распознавание не настроено"):
        asr.transcribe(asr_plugin)


def test_manual_pick_options_and_new_role(setup, asr_plugin):
    path, *_ = setup
    _with_asr(path, None)
    d = lr.panel()
    assert [o["name"] for o in d["options"]["generate"]] == ["main", "spare", "check"]
    assert {o["name"] for o in d["options"]["asr"]} == {"whisper-gpu", "whisper-cpu", "сломанный-код", "свой-код"}
    assert d["asr_switchable"]
    with pytest.raises(ConnectorError):
        lr.use("generate", "whisper-cpu")
    lr.use("asr", "свой-код", by="boss")                       # роли не было — выбор её заводит
    assert [n for n, _ in lr.asr_chain()[0]] == ["свой-код"]
    lr.use("verify", "main")                                    # точка не из цепочки роли — встаёт первой
    assert json.loads(path.read_text(encoding="utf-8"))["roles"]["verify"] == ["main", "check", "spare"]


def test_check_all_pings_asr_without_audio(setup, asr_plugin, monkeypatch):
    path, *_ = setup
    _with_asr(path, ["свой-код", "сломанный-код"], {"нет-кода": {"kind": "python", "callable": "нет_такого:f"}})
    data = json.loads(path.read_text(encoding="utf-8"))
    data["roles"]["asr"].append("нет-кода")
    path.write_text(json.dumps(data), encoding="utf-8")
    # «Проверить связь» — тем же телом, что рабочий вызов (общий ping); у текстовых точек сеть подменена
    real_ping = lr.mr.ping
    monkeypatch.setattr(lr.mr, "ping", lambda r, **kw: (True, "ответ: да") if r.kind in lr.KINDS else real_ping(r, **kw))
    res = {r["name"]: r for r in lr.check_all()}
    assert res["свой-код"]["ok"] and not res["нет-кода"]["ok"] and res["main"]["ok"]


def test_models_tab_has_manual_pick_with_active_buttons():
    from pathlib import Path
    js = (Path(lr.__file__).resolve().parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    # перевёрнут 09.10.26: строка «Выбрать вручную» уступила пульту — выбор, запасная, справочник, форма, откат
    assert "data-route-pick-apply" in js and "data-route-pick-add" in js and "Выбрать вручную" not in js
    # перевёрнут ещё раз 09.10.26 (вариант Б): основную выбирают отметкой в строке, залита одна «Сохранить»
    assert '<button class="route-radio" data-route-use=' in js and 'class="btn btn-primary" data-route-use=' not in js
    assert "Список подключений" in js and 'details class="model-book"' in js
    for marker in ("data-ep-new", "data-ep-edit", "data-ep-delete", "data-ep-test", "route-rollback", "/endpoint/test"):
        assert marker in js, marker


# --- Справочник подключений, форма оператора, откат (просьба владельца 09.10.26) --------------------------------


def test_draft_point_lives_in_book_but_not_in_role(setup):
    path, *_ = setup
    lr.save_point("deepseek-flash", {"kind": "openai", "model": "deepseek-flash", "url": ""}, by="boss")
    d = lr.panel()
    row = next(e for e in d["endpoints"] if e["name"] == "deepseek-flash")
    assert row["missing"].startswith("не задан адрес") and row["roles"] == []
    assert "deepseek-flash" not in [o["name"] for o in d["options"]["generate"]]
    with pytest.raises(ConnectorError, match="не настроена"):
        lr.add_to_role("generate", "deepseek-flash")
    lr.save_point("deepseek-flash", {"kind": "openai", "model": "deepseek-flash", "url": "http://ds:1234"}, old_name="deepseek-flash")
    lr.add_to_role("generate", "deepseek-flash")
    assert json.loads(path.read_text(encoding="utf-8"))["roles"]["generate"] == ["main", "spare", "deepseek-flash"]


def test_key_is_never_stored(setup):
    with pytest.raises(ConnectorError, match="имя переменной"):
        lr.save_point("x", {"kind": "openrouter", "model": "m", "key_env": "sk-or-v1-0123456789abcdef"})
    with pytest.raises(ConnectorError, match="не хранятся"):
        lr.check_point("x", {"kind": "openai", "url": "http://a", "model": "m", "api_key": "секрет"})


def test_rename_remove_delete_and_rollback(setup):
    path, *_ = setup
    lr.save_point("spare-2", {"kind": "openrouter", "model": "s"}, old_name="spare")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["roles"]["generate"] == ["main", "spare-2"] and data["roles"]["verify"] == ["check", "spare-2"]
    lr.remove_from_role("generate", "spare-2")
    # перевёрнут 15.10.26 (находка стенда 25, правило владельца 13.10.26, ответ 15.10.26 — модели по умолчанию нет): 
    # последняя точка уходит — роль «не настроена», вызовов нет; удалить её подключение тоже можно
    lr.remove_from_role("generate", "main")
    assert not lr.configured("generate")
    with pytest.raises(ConnectorError, match="не настроена"):
        lr.RoutedLLM("generator").complete("s", "u")
    lr.delete_point("spare-2", by="boss")
    for _ in range(4):
        lr.rollback(by="boss")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["roles"]["generate"] == ["main", "spare"] and "spare" in data["endpoints"]
    assert [h["action"] for h in lr.history()][:6] == ["rollback"] * 4 + ["delete", "remove"]
    with pytest.raises(ConnectorError, match="откатывать нечего"):
        lr.rollback()


def test_asr_service_inside_network_and_used_for_transcription(setup, asr_plugin, monkeypatch):
    from meetflow.connectors.asr_whisper import WhisperLocalASR
    import io
    path, *_ = setup
    with pytest.raises(ConnectorError, match="внутренней сети"):
        lr.save_point("облако", {"kind": "asr-service", "url": "https://api.example.com/asr"})
    lr.save_point("сервис", {"kind": "asr-service", "url": "http://192.168.100.60:9000/transcribe"})
    sent = {}

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        sent.update(url=req.full_url, ctype=req.headers.get("Content-type"))
        return _R(json.dumps({"text": "[00:00:02] Говорящий: от сервиса", "meta": {"duration": 60}}).encode("utf-8"))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    lr.use("asr", "сервис")
    doc = WhisperLocalASR().transcribe(asr_plugin)
    assert "от сервиса" in doc.text and doc.meta["route"] == "сервис" and sent["ctype"] == "audio/wav"
    assert "language=ru" in sent["url"]


def test_code_in_folder(setup, tmp_path):
    from meetflow.connectors.asr_whisper import WhisperLocalASR
    code = tmp_path / "движок"
    code.mkdir()
    (code / "mf_engine_folder.py").write_text("def run(wav, **kw):\n    return '[00:00:01] Говорящий: из папки'\n", encoding="utf-8")
    lr.save_point("из-папки", {"kind": "python", "callable": "mf_engine_folder:run", "path": str(code)})
    ok, info = lr.test_point({"kind": "python", "callable": "mf_engine_folder:run", "path": str(code)})
    assert ok and "код найден" in info
    lr.use("asr", "из-папки")
    rec = tmp_path / "r.mp4"
    rec.write_bytes(b"x")
    assert "из папки" in WhisperLocalASR().transcribe(rec).text


def test_points_api_is_super_admin_only(setup, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    client = TestClient(create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False))
    sup, member = {"X-User-Role": "super_admin", "X-User-Name": "boss"}, {"X-User-Role": "member"}
    base = "/api/monitoring/models"
    body = {"name": "deepseek-flash", "fields": {"kind": "openai", "model": "deepseek-flash", "url": ""}}
    assert client.post(base + "/endpoint", json=body, headers=member).status_code == 403
    d = client.post(base + "/endpoint", json=body, headers=sup).json()
    assert any(e["name"] == "deepseek-flash" and e["missing"] for e in d["endpoints"])
    r = client.post(base + "/endpoint/test", json=body, headers=sup).json()
    assert r["ok"] is False and "не настроена" in r["detail"]
    assert client.post(base + "/role", json={"role": "generate", "point": "deepseek-flash", "action": "add"}, headers=sup).status_code == 400
    d = client.post(base + "/role", json={"role": "verify", "point": "main", "action": "add"}, headers=sup).json()
    assert [p["name"] for p in d["roles"]["verify"]] == ["check", "spare", "main"]
    d = client.post(base + "/rollback", headers=sup).json()
    assert [p["name"] for p in d["roles"]["verify"]] == ["check", "spare"]
    d = client.post(base + "/endpoint/delete", json={"name": "deepseek-flash", "fields": {}}, headers=sup).json()
    assert not any(e["name"] == "deepseek-flash" for e in d["endpoints"])


def test_models_is_a_left_menu_item():
    """Владелец 09.10.26: «Модели» — отдельный пункт левой панели; старая вкладка мониторинга ведёт туда."""
    from pathlib import Path
    static = Path(lr.__file__).resolve().parents[1] / "web" / "static"
    js, html = (static / "app.js").read_text(encoding="utf-8"), (static / "index.html").read_text(encoding="utf-8")
    assert '<a href="#models" data-route="models">Модели</a>' in html
    # 11.10.26: общий рендер принимает заголовок; прежний «Мониторинг» ведёт на «Модели» или «Мониторинг RealTime»
    assert 'async models() { return routes.monitoring("models", true, "Модели"); }' in js
    assert 'location.replace(tab === "models" ? "#models" : "#live")' in js


def test_switch_seen_even_with_same_mtime_and_size(setup):
    """Найдено 15.10.26 нестабильным test_switch_without_restart: файл перечитывался только по времени изменения;
    две записи в один тик времени не видны. Теперь — по содержимому."""
    import os
    path, _, _, make = setup
    llm = make("generator")
    assert llm.complete("s", "u").text == "ответ main"
    st = os.stat(path)
    lr.use("generate", "spare", path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))       # тот же тик времени
    assert llm.complete("s", "u").text == "ответ spare"
