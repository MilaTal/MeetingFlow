"""Итерация 3: битые и пустые данные, нагрузка, масштабируемость коннекторов."""
import json
import threading
import time

import pytest
from conftest import TRANSCRIPT

from meetflow.connectors.base import ConnectorError, SourceConnector
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.classify import classify_text
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import LLMResult, SourceDoc, SourceKind


# ---------------------------------------------------------------- битые данные
class Garbage(MockLLM):
    def complete(self, system, user, **kw):
        self.calls.append(kw.get("purpose"))
        return LLMResult("я не JSON и не буду", "garbage", 1, 1)


class HalfJSON(MockLLM):
    """Мусор в полях: строки вместо чисел, лишние ключи, None, огромные строки."""
    def _extract(self, data):
        return {"tasks": [None, "строка", {"description": None}, {"description": "x" * 50000, "assignee": 5,
                 "line": "два"}, {"description": "подготовьте регламент склада", "assignee": "Петрова Анастасия",
                 "line": 2, "evil": "<script>"}]}


@pytest.mark.load
def test_non_json_model_is_error_not_crash(store, project, meeting, make_pipe):
    gen = Garbage()
    p = make_pipe(gen=gen)
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    rep = p.run(project, meeting)
    assert rep.status == "error" and "модели" in rep.detail and len(gen.calls) == 2  # один повтор с напоминанием
    assert not rep.protocol_saved


@pytest.mark.load
def test_malformed_fields_are_skipped(store, project, meeting, make_pipe):
    p = make_pipe(gen=HalfJSON())
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    rep = p.run(project, meeting)
    # перевёрнут 15.10.26 (находка стенда 44, решение владельца 15.10.26 заменяет пункт документа 14): 
    # мусорное поле не роняет прогон; уверенная задача одна, мусор — разве что под вопросом с карточкой
    sure = [t for t in p.reg.list(project) if not t["doubt_reason"]]
    assert rep.status == "ok" and len(sure) == 1 and rep.tasks_added - rep.tasks_doubt == 1


@pytest.mark.load
@pytest.mark.parametrize("text", ["", "\n\n\n", "ё" * 5, "\x00\x01", "| | |\n|---|"])
def test_classify_never_crashes(text):
    assert classify_text(text).kind in set(SourceKind)


@pytest.mark.load
def test_huge_single_line_source(store, project, meeting, make_pipe):
    p = make_pipe()
    blob = ("Петрова Анастасия, подготовьте регламент склада " * 4000).encode()
    assert p.ingest(project, meeting, "blob 01.10.2026.txt", blob)["status"] == "ok"
    assert p.run(project, meeting).status in {"ok", "ok_limited", "stopped_by_limit"}


@pytest.mark.load
def test_store_survives_old_schema(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, description TEXT)")
    con.execute("INSERT INTO tasks (description) VALUES ('старая')")
    con.commit(); con.close()
    s = Store(db)                                   # недостающие колонки добавятся, данные целы
    assert s.q("SELECT description, status FROM tasks")[0] == {"description": "старая", "status": "active"}


@pytest.mark.load
def test_cyrillic_case_search_in_python(store, project):
    reg = TaskRegistry(store)
    reg.add(project, "Регламент СКЛАДА", None)
    rows = [r for r in reg.list(project) if "склада" in r["description"].lower()]
    assert len(rows) == 1                           # SQLite lower() кириллицу не понимает — фильтр в Python


# ---------------------------------------------------------------- нагрузка
@pytest.mark.load
def test_long_meeting_and_big_registry_time(store, project, meeting, make_pipe):
    p = make_pipe()
    for i in range(200):
        p.reg.add(project, f"Задача номер {i} по складу и браку партии {i}", "Сидоров Пётр")
    lines = [f"[{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}] Игнатов Иван: Петрова Анастасия, подготовьте "
             f"раздел {i} регламента склада" for i in range(1500)]
    p.ingest(project, meeting, "long 01.10.2026.txt", "\n".join(lines).encode())
    t0 = time.perf_counter()
    rep = p.run(project, meeting, None)
    dt = time.perf_counter() - t0
    assert rep.status in {"ok", "ok_limited", "stopped_by_limit"} and dt < 30, dt


@pytest.mark.load
def test_concurrent_writes_not_lost(store, project):
    reg = TaskRegistry(store)
    errors = []

    def worker(k):
        try:
            for i in range(25):
                reg.add(project, f"поток {k} задача {i}", None)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ths = [threading.Thread(target=worker, args=(k,)) for k in range(16)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert not errors and len(reg.list(project)) == 16 * 25


@pytest.mark.load
def test_concurrent_status_changes_consistent(store, project):
    reg = TaskRegistry(store)
    from meetflow.core.types import TaskStatus
    tid = reg.add(project, "x", None)
    ths = [threading.Thread(target=reg.set_status, args=(tid, TaskStatus.DONE if i % 2 else TaskStatus.ACTIVE,
                                                          "web_form")) for i in range(40)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    hist = reg.history(tid)
    # находка стенда 35 (15.10.26): повтор той же смены не пишется — строк не больше 41, каждая — настоящая смена
    assert len(hist) <= 41 and store.get("tasks", tid)["status"] == hist[-1]["new_status"]
    assert all(h["old_status"] != h["new_status"] for h in hist[1:])
    # усилено по ревью: история — непрерывная цепочка «старый -> новый»
    assert all(hist[i]["old_status"] == hist[i - 1]["new_status"] for i in range(1, len(hist)))


# ---------------------------------------------------------------- масштабируемость
class CsvSource(SourceConnector):
    """Новый тип входа — без единой правки ядра."""
    name, extensions = "csv", (".csv",)

    def read(self, data, filename):
        rows = [r.split(";") for r in data.decode("utf-8").splitlines() if r.strip()]
        text = "\n".join(f"[00:{i:02d}:00] {r[0]}: {r[1]}" for i, r in enumerate(rows))
        return SourceDoc(filename, SourceKind.TRANSCRIPT, text, {"connector": self.name})


@pytest.mark.scale
def test_new_connector_without_core_changes(store, project, meeting, theme):
    reg = default_registry()
    reg.register(CsvSource())
    p = MeetingPipeline(theme, store, reg, MockLLM(), MockLLM())
    csv = "Игнатов Иван;Петрова Анастасия, подготовьте регламент склада\nСидоров Пётр;Привет\nИгнатов Иван;Начали\n"
    assert p.ingest(project, meeting, "встреча 01.10.2026.csv", csv.encode())["kind"] == "transcript"
    assert p.run(project, meeting).tasks_added == 1


@pytest.mark.scale
def test_connector_from_theme_spec():
    reg = default_registry()
    loaded = reg.load_extra(["test_robustness_load:CsvSource"])
    assert loaded[0].name == "csv" and reg.resolve_source("x.csv").name == "csv"


@pytest.mark.scale
def test_many_projects_isolated(store, theme):
    pids = [store.insert("projects", name=f"P{i}", theme=theme.id) for i in range(30)]
    reg = TaskRegistry(store)
    for pid in pids:
        reg.add(pid, "общая задача", None)
    assert all(len(reg.list(pid)) == 1 for pid in pids)


@pytest.mark.scale
def test_same_core_three_themes(store, project, meeting):
    from meetflow.core.config import load_theme
    for name in ("erp_rollout", "daily_ops", "it_product"):
        th = load_theme(name)
        mid = store.insert("meetings", project_id=project, date="2026-10-01")
        p = MeetingPipeline(th, store, default_registry(), MockLLM(), MockLLM())
        p.ingest(project, mid, f"{name}.txt", (TRANSCRIPT + f"\n[00:09:00] {name}\n").encode())
        rep = p.run(project, mid)
        proto = store.get("meetings", mid)["protocol_md"]
        assert rep.status == "ok" and proto.startswith(f"# {th.word('protocol')}")
        assert all(f"## {s}" in proto for s in th["protocol_skeleton"])
