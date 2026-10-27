"""Находки стенда 41 и 19 (обе системы 994da43…371f967; ERP итог 13.10 12-11), 3 и 4 (состояние сборки на экране).
41 — очередь сборок: одна за раз, по датам встреч, замок в базе, переживает перезапуск; пересборка после смены модели —
в очередь с «не раньше»; карточка «ранняя пересобрана после поздних». 19 — начатое продолжается по записи о начале,
а не по косвенному признаку; автозапуск запрещает начинать, а не доводить начатое. Тесты написаны до правки и падали."""
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from meetflow.core.build_queue import BuildQueue, later

H = {"X-User-Role": "project_admin"}


def _app(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    return app, TestClient(app)


def _meetings(c, store, dates):
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mids = []
    for d in dates:
        mid = c.post(f"/api/projects/{pid}/meetings", json={"date": d}, headers=H).json()["id"]
        store.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", text="[00:01:00] А: текст", digest=d)
        mids.append(mid)
    return pid, mids


def test_two_meetings_at_once_no_overlap_by_date(tmp_path, monkeypatch):
    app, c = _app(tmp_path)
    store, pipe = app.state.store, app.state.pipe
    pid, mids = _meetings(c, store, ["2026-10-08", "2026-10-01"])
    active, log = [], []
    lock = threading.Lock()

    def slow_run(p, mid):
        with lock:
            active.append(mid)
            assert len(active) == 1, "две сборки шли одновременно"
        log.append(mid)
        time.sleep(0.3)
        with lock:
            active.remove(mid)
        return type("R", (), {"__dict__": {"status": "ok", "meeting_id": mid}})()
    monkeypatch.setattr(pipe, "run", slow_run)
    q = app.state.queue
    nb = later(2)                      # одно «не раньше» на обе (с точностью до секунды; 2 с — без гонки на границе секунды)
    r1 = q.enqueue(pid, mids[0], "тест", not_before=nb)
    r2 = q.enqueue(pid, mids[1], "тест", not_before=nb)
    q.wait(r1, 10), q.wait(r2, 10)
    assert log == [mids[1], mids[0]], "по датам встреч: 01.10 раньше 08.10"


def test_lock_is_in_the_database(tmp_path, monkeypatch):
    """Второй процесс с той же базой: строка «идёт» живого процесса — новая сборка не начинается."""
    app, c = _app(tmp_path)
    store, pipe = app.state.store, app.state.pipe
    pid, mids = _meetings(c, store, ["2026-10-01", "2026-10-02"])
    store.insert("build_queue", project_id=pid, meeting_id=mids[0], meeting_date="2026-10-01", status="running",
                 pid=__import__("os").getpid(), started_at="2026-10-15T10:00:00", reason="другой процесс")
    started = []
    monkeypatch.setattr(pipe, "run", lambda p, mid: started.append(mid))
    q2 = BuildQueue(pipe)
    q2.enqueue(pid, mids[1], "тест")
    time.sleep(0.8)
    assert started == [] and q2.state(mids[1])["status"] == "queued" and q2.state(mids[1])["position"] == 2


def test_started_build_resumes_after_restart_even_with_autorun_off(tmp_path, monkeypatch):
    app, c = _app(tmp_path)
    store = app.state.store
    pid, mids = _meetings(c, store, ["2026-10-05"])
    store.set_setting("autorun", False, pid)
    store.insert("build_queue", project_id=pid, meeting_id=mids[0], meeting_date="2026-10-05", status="running",
                 pid=999999, started_at="2026-10-15T10:00:00", reason="кнопка")
    from meetflow.web import app as webapp
    started = []
    monkeypatch.setattr(webapp.MeetingPipeline, "run", lambda self, p, mid: started.append(mid))
    app2, _ = _app(tmp_path)                                       # перезапуск на той же базе
    for _ in range(40):
        if started:
            break
        time.sleep(0.1)
    assert started == [mids[0]], "начатое доводится по записи о начале, автозапуск этого не запрещает"
    assert store.q("SELECT * FROM cards WHERE title LIKE '%продолжаю сборку после перезапуска%'")


def test_no_indirect_resume(tmp_path, monkeypatch):
    """Источник есть, протокола нет, записи о начале нет — сборка сама не начинается (не косвенный признак)."""
    app, c = _app(tmp_path)
    store = app.state.store
    pid, mids = _meetings(c, store, ["2026-10-05"])
    store.set_setting("autorun", True, pid)
    from meetflow.web import app as webapp
    started = []
    monkeypatch.setattr(webapp.MeetingPipeline, "run", lambda self, p, mid: started.append(mid))
    _app(tmp_path)
    time.sleep(0.6)
    assert started == []


def test_early_rebuilt_after_late_card(tmp_path, monkeypatch):
    app, c = _app(tmp_path)
    store, pipe = app.state.store, app.state.pipe
    pid, mids = _meetings(c, store, ["2026-10-01", "2026-10-08"])
    monkeypatch.setattr(pipe, "run", lambda p, mid: type("R", (), {"__dict__": {"status": "ok"}})())
    q = app.state.queue
    q.wait(q.enqueue(pid, mids[1], "поздняя"), 10)
    q.wait(q.enqueue(pid, mids[0], "ранняя после смены модели"), 10)
    assert store.q("SELECT * FROM cards WHERE title='Встреча 2026-10-01: ранняя пересобрана после поздних'")


def test_button_goes_through_queue_and_screen_sees_state(tmp_path, monkeypatch):
    app, c = _app(tmp_path)
    store, pipe = app.state.store, app.state.pipe
    pid, mids = _meetings(c, store, ["2026-10-01"])
    gate = threading.Event()

    def held_run(p, mid):
        gate.wait(5)
        return type("R", (), {"__dict__": {"status": "ok", "meeting_id": mid}})()
    monkeypatch.setattr(pipe, "run", held_run)
    t = threading.Thread(target=lambda: c.post(f"/api/meetings/{mids[0]}/run", headers=H))
    t.start()
    for _ in range(30):
        st = c.get(f"/api/meetings/{mids[0]}/build", headers=H).json()
        if st["status"] == "running":
            break
        time.sleep(0.1)
    assert st["status"] == "running" and st["started_at"]
    gate.set()
    t.join(5)
    assert c.get(f"/api/meetings/{mids[0]}/build", headers=H).json()["status"] == "idle"
    assert store.q("SELECT status FROM build_queue WHERE meeting_id=?", (mids[0],))[0]["status"] == "done"


def test_model_switch_rebuild_goes_to_queue_with_not_before(tmp_path, monkeypatch):
    app, c = _app(tmp_path)
    store = app.state.store
    pid, mids = _meetings(c, store, ["2026-10-01"])
    app.state.queue_rebuild(mids[0], 900)
    row = store.q("SELECT * FROM build_queue WHERE meeting_id=?", (mids[0],))[0]
    assert row["status"] == "queued" and row["not_before"] > time.strftime("%Y-%m-%dT%H:%M:%S")
    assert "смена модели" in row["reason"]
