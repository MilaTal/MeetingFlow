# -*- coding: utf-8 -*-
"""Правки локальной машины от 12.10.26 (коммит a9c07eb в ERP_Production_meetings), перенесённые в MeetFlow там, где они
к нему относятся: смена модели на ближайшей попытке, подхват после перезапуска, поиск убран со страницы реестра,
выгрузка локально распознанной расшифровки в Word. «Протокол последнего распознавания» и счёт отпечатков не
переносились: своей базы голосов и разбора по голосам у MeetFlow нет, он только читает общую базу."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.base import ConnectorUnavailable, LLMConnector
from meetflow.core.types import LLMResult

JS = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static" / "app.js"


class Fake(LLMConnector):
    def __init__(self, name, on_call):
        self.name, self.model, self.profile, self.on_call = name, f"model-{name}", "generic", on_call
        self.context_chars = 100_000

    def worst_call_usd(self, prompt_chars):
        return None

    def complete(self, system, user, **kw):
        return self.on_call(self.name)


def _routes(path, chain):
    path.write_text(json.dumps({
        "endpoints": {"main": {"kind": "openai", "url": "http://main", "model": "m"},
                      "spare": {"kind": "openrouter", "model": "s"},
                      "fresh": {"kind": "ollama", "url": "http://localhost:11434", "model": "f"}},
        "roles": {"generate": chain, "verify": ["fresh"]}, "cooldown_sec": 300}), encoding="utf-8")
    t = time.time() + 5
    os.utime(path, (t, t))          # mtime заведомо новый — перечитывание не зависит от точности часов файловой системы


def test_смена_модели_подхватывается_на_следующей_попытке_того_же_вызова(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    _routes(path, ["main", "spare"])
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setattr(lr.mr._state, "down_until", {})
    calls = []

    def on_call(name):
        calls.append(name)
        if name == "main":                     # пока главная думала, оператор переключил роль на «fresh»
            _routes(path, ["fresh", "main"])
            raise ConnectorUnavailable("main не отвечает")
        return LLMResult(f"ответ {name}", name, raw={})

    llm = lr.RoutedLLM("generator", factory=lambda n, ep: Fake(n, on_call))
    assert llm.complete("s", "u").text == "ответ fresh"
    assert calls == ["main", "fresh"]          # провалившаяся main не повторяется, spare старой цепочки не вызывается


def test_одна_точка_в_цепочке_прежнее_поведение(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    _routes(path, ["main"])
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setattr(lr.mr._state, "down_until", {})
    calls = []

    def on_call(name):
        calls.append(name)
        raise ConnectorUnavailable("нет")

    with pytest.raises(ConnectorUnavailable):
        lr.RoutedLLM("generator", factory=lambda n, ep: Fake(n, on_call)).complete("s", "u")
    assert calls == ["main"]


def _app(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return app, TestClient(app), {"X-User-Role": "project_admin"}


def test_подхват_после_перезапуска(tmp_path, monkeypatch):
    app, c, H = _app(tmp_path)
    intake, store = app.state.intake, app.state.pipe.s
    started = []
    monkeypatch.setattr(app.state.pipe, "run", lambda pid, mid: started.append(mid))
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mids = []
    for d in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"):
        mid = c.post(f"/api/projects/{pid}/meetings", json={"date": d}, headers=H).json()["id"]
        store.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", text="[00:01:00] А: текст", digest=d)
        mids.append(mid)
    # перевёрнут 15.10.26 (находка стенда 19, итог ERP 13.10 12-11): начатое продолжается по записи о начале
    # (строка очереди «идёт» от умершего процесса), а не по косвенному признаку «источник есть, протокола нет»;
    # автозапуск запрещает начинать новое, а не доводить начатое
    store.update("meetings", mids[0], protocol_md="# готово")
    store.set_setting("autorun", True, pid)
    store.insert("build_queue", project_id=pid, meeting_id=mids[3], meeting_date="2026-10-06", status="running",
                 pid=999999, started_at="2026-10-15T10:00:00", reason="автозапуск из папки-приёмника")
    out = app.state.queue.recover()
    for _ in range(40):
        if started:
            break
        time.sleep(0.1)
    assert started == [mids[3]] and out == [{"meeting_id": mids[3], "status": "requeued"}]   # только начатое
    titles = [r["title"] for r in store.q("SELECT title FROM cards WHERE kind='technical'")]
    assert any("продолжаю сборку" in t for t in titles)


def test_подхват_при_выключенном_автозапуске_только_сообщение(tmp_path, monkeypatch):
    app, c, H = _app(tmp_path)
    store = app.state.pipe.s
    started = []
    monkeypatch.setattr(app.state.pipe, "run", lambda pid, mid: started.append(mid))
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-05"}, headers=H).json()["id"]
    # перевёрнут 15.10.26 (находка стенда 19, итог ERP 13.10 12-11): начатое продолжается по записи о начале
    # (строка очереди «идёт» от умершего процесса), а не по косвенному признаку «источник есть, протокола нет»;
    # автозапуск запрещает начинать новое, а не доводить начатое
    store.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", text="[00:01:00] А: текст", digest="x")
    store.set_setting("autorun", False, pid)
    assert app.state.queue.recover() == [] and not started              # не начато — не начинается само
    store.insert("build_queue", project_id=pid, meeting_id=mid, meeting_date="2026-10-05", status="running",
                 pid=999999, started_at="2026-10-15T10:00:00", reason="кнопка")
    app.state.queue.recover()
    for _ in range(40):
        if started:
            break
        time.sleep(0.1)
    assert started == [mid], "начатое доводится и при выключенном автозапуске"


def test_поиска_нет_на_странице_реестра():
    js = JS.read_text(encoding="utf-8")
    start = js.index("  async tasks() {")
    body = js[start:js.index("\n  async ", start + 10)]
    assert "reg-search" not in body and "data-rhint" not in body and "/search?q=" not in body
    assert "trs.slice(1, 8)" in body                                    # предел 7 строк остаётся (09.10.26)


def test_выгрузка_расшифровки_только_нашего_распознавания(tmp_path):
    app, c, H = _app(tmp_path)
    store = app.state.pipe.s
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-05"}, headers=H).json()["id"]
    ours = store.insert("sources", meeting_id=mid, name="запись.mp4", kind="transcript", digest="a", local_asr=1,
                        text="00:00:05\tИгнатов Иван\tДобрый день\n00:00:09\tПетрова Анна\tНачнём")
    theirs = store.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", digest="b", text="x")
    r = c.get(f"/api/meetings/{mid}/sources/{ours}/export", headers=H)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    from docx import Document
    import io
    text = "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs)
    assert "05.10.2026" in text and "00:00:05 Игнатов Иван: Добрый день" in text and "*" not in text
    assert c.get(f"/api/meetings/{mid}/sources/{theirs}/export", headers=H).status_code == 400
    assert c.get(f"/api/meetings/{mid + 99}/sources/{ours}/export", headers=H).status_code == 404
    srcs = c.get(f"/api/meetings/{mid}/sources", headers=H).json()
    assert {s["id"]: s["local_asr"] for s in srcs} == {ours: 1, theirs: 0}


# ---- смена модели: сообщение, подсказка, пересборка после паузы (локальная машина f94a68c, 7effaa2, 12.10.26)

def _routes_app(tmp_path, monkeypatch):
    from meetflow.web.app import create_app
    path = tmp_path / "models.json"
    path.write_text(json.dumps({
        "endpoints": {"main": {"kind": "openai", "url": "http://main", "model": "m"},
                      "spare": {"kind": "openrouter", "model": "s"}},
        "roles": {"generate": ["main", "spare"], "verify": ["spare"]}, "cooldown_sec": 300}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setenv("MEETFLOW_LLM", "routes")
    monkeypatch.setenv("MEETFLOW_MODEL_SWITCH_PAUSE_SEC", "0")
    app = create_app("it_product", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return app, TestClient(app), {"X-User-Role": "super_admin", "X-User-Name": "boss"}


def _tech(store):
    return [r["title"] for r in store.q("SELECT title FROM cards WHERE kind='technical' ORDER BY id")]


def test_смена_модели_пишет_системное_сообщение_и_молчит_без_смены(tmp_path, monkeypatch):
    app, c, H = _routes_app(tmp_path, monkeypatch)
    store = app.state.pipe.s
    c.post("/api/monitoring/models/use", json={"role": "generate", "point": "main"}, headers=H)      # уже основная
    assert _tech(store) == []
    c.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=H)
    assert _tech(store) == ["Модель роли «Генерация черновика» сменена: main → spare"]


def test_смена_модели_на_живой_сборке_пересобирает_после_паузы(tmp_path, monkeypatch):
    app, c, H = _routes_app(tmp_path, monkeypatch)
    pipe, store = app.state.pipe, app.state.pipe.s
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-05"}, headers=H).json()["id"]
    reruns = []
    monkeypatch.setattr(pipe, "run", lambda p, m: reruns.append(m))
    lock = pipe._meeting_lock(mid)
    lock.acquire()                                    # идёт сборка этой встречи
    try:
        c.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=H)
        assert pipe.running_meetings() == [mid]
        assert "Сейчас идёт сборка" in store.q("SELECT payload FROM cards WHERE kind='technical'")[0]["payload"]
        time.sleep(0.2)
        assert reruns == []                           # пока сборка идёт — не трогаем
    finally:
        lock.release()
    deadline = time.time() + 40
    while not reruns and time.time() < deadline:
        time.sleep(0.5)
    assert reruns == [mid]
    assert any("пересборка на новой модели начата" in t for t in _tech(store))


def test_подсказка_о_смене_в_панели():
    assert "Когда применится смена" in JS.read_text(encoding="utf-8")


def test_системных_сообщений_нет_в_очереди_оператора(tmp_path):
    """Владелец 12.10.26 (локальная машина abb5789): очередь «Ожидает ввода» — только работа людей."""
    app, c, _ = _app(tmp_path)
    app.state.pipe.cards.open(None, "technical", "Сбой прохода папки-приёмника", {}, None)
    keys = [g["key"] for g in c.get("/api/monitoring/awaiting-input", headers={"X-User-Role": "super_admin"}).json()["groups"]]
    assert "tech" not in keys
    tech = c.get("/api/monitoring/system-messages", headers={"X-User-Role": "super_admin"}).json()
    assert any("папки-приёмника" in t["title"] for t in tech)          # на своей странице сообщение есть


def test_мониторинг_называет_точку_и_запасные(tmp_path, monkeypatch):
    """Локальная машина 71b2b27: модель в мониторинге — по маршрутам, с точкой и запасными."""
    app, c, H = _routes_app(tmp_path, monkeypatch)
    rows = {r["name"]: r for r in c.get("/api/monitoring/live", headers=H).json()["services"]}
    assert "точка «main», запасные: spare" in rows["Модель"]["detail"]
    c.post("/api/monitoring/models/use", json={"role": "generate", "point": "spare"}, headers=H)
    rows = {r["name"]: r for r in c.get("/api/monitoring/live", headers=H).json()["services"]}
    assert "точка «spare», запасные: main" in rows["Модель"]["detail"]
