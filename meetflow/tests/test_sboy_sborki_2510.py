"""Правило 25.10.2026, пункт 2: сбой сборки не оставляет встречу молча.

Проходящий сбой (модель недоступна, сеть, таймаут) — повтор через 10 минут, затем через час, не больше двух;
каждый повтор — строкой журнала с `run_id`. Непроходящий (формат, предел) — без слепого повтора, карточка с
действием «Пересобрать». Тест написан до правки и падал.
"""
import json
from types import SimpleNamespace

from meetflow.core.build_queue import BuildQueue
from meetflow.core.store import now


class Cards:
    def __init__(self):
        self.opened = []

    def open(self, project_id, kind, title, payload=None, meeting_id=None):
        self.opened.append({"kind": kind, "title": title, "payload": payload or {}})


class Journal:
    def __init__(self):
        self.rows = []
        self.run_id = None

    def write(self, **rec):
        if self.run_id:
            rec.setdefault("run_id", self.run_id)
        self.rows.append(rec)


class Pipe:
    def __init__(self, store, results):
        self.s, self.cards, self.journal = store, Cards(), Journal()
        self.results = list(results)

    def run(self, project_id, meeting_id):
        return self.results.pop(0)


def _setup(store):
    pid = store.insert("projects", name="П", theme="erp_rollout")
    mid = store.insert("meetings", project_id=pid, date="2026-10-01", label="в")
    return pid, mid


def test_passing_failure_requeued_10_minutes_then_hour(store):
    pid, mid = _setup(store)
    bad = lambda: SimpleNamespace(status="error", retryable=True, detail="нет связи", run_id="r1")
    pipe = Pipe(store, [bad(), bad(), bad()])
    q = BuildQueue(pipe, tick=0.01)
    rid = q.enqueue(pid, mid, "тест")
    q.run_one()
    row = store.get("build_queue", rid)
    assert row["status"] == "queued" and row["attempts"] == 1 and row["not_before"] > now()
    store.update("build_queue", rid, not_before=None)
    q.run_one()
    row = store.get("build_queue", rid)
    assert row["status"] == "queued" and row["attempts"] == 2
    store.update("build_queue", rid, not_before=None)
    q.run_one()
    row = store.get("build_queue", rid)
    assert row["status"] == "failed" and row["attempts"] == 2
    retries = [x for x in pipe.journal.rows if x.get("purpose") == "retry"]
    assert len(retries) == 2 and retries[0]["delay_min"] == 10 and retries[1]["delay_min"] == 60


def test_not_passing_failure_no_retry_and_card_with_rebuild(store):
    pid, mid = _setup(store)
    pipe = Pipe(store, [SimpleNamespace(status="error", retryable=False, detail="вход больше предела", run_id="r2")])
    q = BuildQueue(pipe, tick=0.01)
    rid = q.enqueue(pid, mid, "тест")
    q.run_one()
    row = store.get("build_queue", rid)
    assert row["status"] == "failed" and row["attempts"] == 0
    assert any("Пересобрать" in c["payload"].get("action", "") or
               "Пересобрать" in c["title"] for c in pipe.cards.opened)
