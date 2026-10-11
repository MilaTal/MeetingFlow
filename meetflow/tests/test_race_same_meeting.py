"""Гонка: две сборки одной встречи одновременно (письмо ветки «AI агентные скилы» 09.10, строка 12 — замок на данных,
а не на кнопке; вызов модели — вне замка). Две вкладки, двойной щелчок, папка-приёмник и кнопка вместе — задачи
не задваиваются, вторая сборка не ломает первую.

Эталон собирается в отдельном проекте: та же запись в том же проекте законно не заводит задачи второй раз
(первая версия теста так и «поймала» 0 вместо 2 — врал прибор)."""
import threading
import time

from conftest import TEAM, TRANSCRIPT

from meetflow.connectors.llm_mock import MockLLM


class Slow(MockLLM):
    """Задержка в вызове модели — чтобы прогоны точно перекрылись по времени."""
    def complete(self, system, user, **kw):
        time.sleep(0.15)
        return super().complete(system, user, **kw)


def _project(store, name):
    pid = store.insert("projects", name=name, theme="erp_rollout")
    for n in TEAM:
        store.insert("people", project_id=pid, full_name=n)
    mid = store.insert("meetings", project_id=pid, date="2026-10-01", label="встреча")
    return pid, mid


def _count(store, pid):
    return store.q("SELECT COUNT(*) AS n FROM tasks WHERE project_id=?", (pid,))[0]["n"]


def test_two_parallel_runs_do_not_duplicate_tasks(store, make_pipe):
    p1, m1 = _project(store, "эталон")
    ref = make_pipe()
    ref.ingest(p1, m1, "t.txt", TRANSCRIPT.encode())
    ref.run(p1, m1)
    single = _count(store, p1)
    assert single > 0

    p2, m2 = _project(store, "гонка")
    p = make_pipe(gen=Slow(), ver=Slow())
    p.ingest(p2, m2, "t.txt", TRANSCRIPT.encode())
    reps, errs = [], []

    def go():
        try:
            reps.append(p.run(p2, m2))
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs
    assert _count(store, p2) == single, f"одна сборка заводит {single}, две одновременные — {_count(store, p2)}"
    assert any(r.status == "ok" for r in reps), [r.status for r in reps]


def test_two_pipeline_instances_share_the_meeting_lock(store, make_pipe):
    """Веб и папка-приёмник — разные экземпляры конвейера над одной базой: замок общий, по базе и встрече."""
    p1, m1 = _project(store, "эталон")
    ref = make_pipe()
    ref.ingest(p1, m1, "t.txt", TRANSCRIPT.encode())
    ref.run(p1, m1)
    single = _count(store, p1)

    p2, m2 = _project(store, "два экземпляра")
    a, b = make_pipe(gen=Slow(), ver=Slow()), make_pipe(gen=Slow(), ver=Slow())
    a.ingest(p2, m2, "t.txt", TRANSCRIPT.encode())
    reps = []
    ts = [threading.Thread(target=lambda x=x: reps.append(x.run(p2, m2))) for x in (a, b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert _count(store, p2) == single
    assert sorted(r.status for r in reps) == ["busy", "ok"]


def test_model_call_is_outside_the_lock_two_meetings_overlap(store, make_pipe):
    """Разные встречи собираются одновременно: замок — на встрече и на записи, не на всём конвейере."""
    pa, ma = _project(store, "А")
    pb, mb = _project(store, "Б")
    p = make_pipe(gen=Slow(), ver=Slow())
    for pid, mid in ((pa, ma), (pb, mb)):
        p.ingest(pid, mid, "t.txt", TRANSCRIPT.encode())
    t0 = time.perf_counter()
    p.run(pa, ma)
    one = time.perf_counter() - t0
    pc, mc = _project(store, "В")
    p.ingest(pc, mc, "t.txt", TRANSCRIPT.encode())
    t0 = time.perf_counter()
    ts = [threading.Thread(target=p.run, args=a) for a in ((pb, mb), (pc, mc))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    both = time.perf_counter() - t0
    assert both < one * 1.6, f"одна встреча {one:.2f} с, две одновременно {both:.2f} с — сборки шли по очереди"
