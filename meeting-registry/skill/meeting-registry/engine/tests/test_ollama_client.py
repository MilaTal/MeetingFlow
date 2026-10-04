"""Итерация 1, коннектор: клиент Ollama против поддельного локального сервера с тем же API (/api/chat).
Настоящей модели на машине нет (Ollama 0.35 без загруженных моделей) — поэтому проверяется контракт:
повторы на 5xx, разбор JSON, обрезка по длине, отсутствие модели, учёт токенов, периметр."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from meeting_registry.errors import BadModelAnswer, ProviderUnavailable, SetupError
from meeting_registry.llm import OllamaClient


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                outer.requests.append(body)
                code, payload = outer.replies.pop(0) if len(outer.replies) > 1 else outer.replies[0]
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def ok(content, pin=100, pout=20, reason="stop"):
    return 200, {"message": {"role": "assistant", "content": content}, "prompt_eval_count": pin, "eval_count": pout,
                 "done": True, "done_reason": reason}


@pytest.fixture
def fake():
    servers = []

    def make(replies):
        s = FakeOllama(replies)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def test_json_and_tokens(fake):
    f = fake([ok('{"assignments": []}', 1234, 56)])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1)
    obj, usage = c.complete_json("sys", "user", "extract")
    assert obj == {"assignments": []}
    assert usage["tokens_in"] == 1234 and usage["tokens_out"] == 56 and usage["cost_usd"] == 0
    req = f.requests[0]
    assert req["format"] == "json" and req["options"]["temperature"] == 0 and req["stream"] is False


def test_retry_on_5xx_then_success(fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    f = fake([(503, {"error": "busy"}), ok('{"x": 1}')])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=3)
    assert c.complete_json("s", "u", "p")[0] == {"x": 1}
    assert len(f.requests) == 2


def test_gives_up_after_attempts(fake, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    f = fake([(500, {"error": "boom"})])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=3)
    with pytest.raises(ProviderUnavailable):
        c.complete_json("s", "u", "p")
    assert len(f.requests) == 3


def test_bad_json_one_retry_with_reminder(fake):
    f = fake([ok("это не json"), ok('{"ok": true}')])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1)
    assert c.complete_json("s", "u", "p")[0] == {"ok": True}
    assert "ТОЛЬКО одним JSON" in f.requests[1]["messages"][1]["content"]


def test_bad_json_twice_raises(fake):
    f = fake([ok("мусор")])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1)
    with pytest.raises(BadModelAnswer):
        c.complete_json("s", "u", "p")
    assert len(f.requests) == 2   # один повтор, не четыре


def test_truncated_answer_is_reported(fake):
    f = fake([ok('{"assignments": [', reason="length")])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1)
    with pytest.raises(BadModelAnswer, match="обрезан"):
        c.complete_json("s", "u", "p")


def test_model_not_pulled_is_setup_error(fake):
    f = fake([(404, {"error": "model 'glm-4.7-flash' not found"})])
    c = OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1)
    with pytest.raises(SetupError, match="ollama pull"):
        c.complete_json("s", "u", "p")


def test_perimeter_and_training_models():
    with pytest.raises(SetupError, match="вне периметра"):
        OllamaClient(base_url="https://api.example.com", model="glm-4.7-flash")
    with pytest.raises(SetupError, match="обучается"):
        OllamaClient(base_url="http://127.0.0.1:11434", model="vendor/model:contributor")
    with pytest.raises(SetupError, match="MR_MODEL"):
        OllamaClient(base_url="http://127.0.0.1:11434", model="")


def test_pipeline_through_fake_ollama(fake, run, reg, m1):
    """Конвейер целиком через HTTP-клиент: модель отвечает номерами строк, задачу пишет код."""
    f = fake([ok(json.dumps({"assignments": [{"line": 5, "to": "Назаров", "action": "подготовить спецификацию на фильтры",
                                               "due": "до пятницы"}]}, ensure_ascii=False))] +
             [ok('{"tool": "to_operator", "args": {"reason": "нет данных"}}')])
    res = run(m1, client=OllamaClient(base_url=f.url, model="glm-4.7-flash", attempts=1))
    assert res["outcome"] == "done"
    assert [t["responsible_id"] for t in reg.all_tasks()] == ["u05"]
    assert res["tokens_in"] >= 100
