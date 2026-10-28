"""Скрипт возврата задач, снятых пересборкой при цитате в записи (решение владелицы 28.10.2026)."""
import importlib.util
from pathlib import Path

from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import TaskStatus


def _скрипт():
    p = Path(__file__).resolve().parents[1] / "scripts" / "vernut_snyatye_po_citate_2810.py"
    spec = importlib.util.spec_from_file_location("vernut", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_возвращает_только_с_цитатой_в_записи(tmp_path):
    db = tmp_path / "m.db"
    st = Store(str(db))
    pid = st.insert("projects", name="П", theme="_default")
    mid = st.insert("meetings", project_id=pid, date="2026-10-28", label="в")
    st.insert("sources", meeting_id=mid, name="t.txt", kind="transcript",
              text="[00:01:00] Иванов Иван: Петров, подготовь спецификацию на краны по Бухте-Север до пятницы.")
    reg = TaskRegistry(st)
    a = reg.add(pid, "Подготовить спецификацию на краны", None, mid,
                "Петров, подготовь спецификацию на краны по Бухте-Север до пятницы")
    b = reg.add(pid, "Согласовать акт сверки", None, mid, "согласовать акт сверки с бухгалтерией до конца месяца")
    for tid in (a, b):
        reg.set_status(tid, TaskStatus.DROPPED, "rebuild", "не вошла в пересборку (28.10.2026 14:52)")
    m = _скрипт()
    assert m.main(["--db", str(db), "--meeting", str(mid)]) == 0
    assert st.get("tasks", a)["status"] == "dropped"                 # сухой ход ничего не меняет
    assert m.main(["--db", str(db), "--meeting", str(mid), "--apply"]) == 0
    st2 = Store(str(db))
    assert st2.get("tasks", a)["status"] == "active" and st2.get("tasks", b)["status"] == "dropped"
    assert (tmp_path / "m.db.до-возврата-2810").exists()
