"""Массовые действия в реестре задач (пункт 5 плана 08.11.2026, задание владелицы 06.11.2026: «пометить все или снять
выделение… и удалить выделенное»).

Проверяется: право — на сервере (участнику 403), удаляются только присланные номера, частичный отказ — числом,
уборка как у одиночного удаления (карточки, связи единиц, история), и «Пометить все» на экране берёт только строки
текущего списка — с учётом отбора и вида, а не все задачи проекта.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from meetflow.core.registry import CardQueue, TaskRegistry
from meetflow.core.types import TaskStatus
from meetflow.web.app import create_app

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _клиент(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    роли = {}
    for роль in ("super_admin", "project_admin", "member"):
        роли[роль] = st.insert("accounts", login=None, full_name=роль, role=роль, password_hash="", active=1,
                               confirmed=1)
    return c, st, pid, роли


def _заголовки(pid, uid):
    return {"X-Requested-With": "erp-webapp", "X-User-Id": str(uid), "X-Project-Id": str(pid)}


def test_участнику_массовое_удаление_запрещено(tmp_path):
    c, st, pid, роли = _клиент(tmp_path)
    tid = TaskRegistry(st).add(pid, "Убрать мусор из списка", "Петрова Анастасия")
    r = c.post("/tasks/bulk-delete", json={"ids": [tid]}, headers=_заголовки(pid, роли["member"]))
    assert r.status_code == 403, r.text
    assert st.get("tasks", tid), "участник не должен ничего удалить"


def test_удаляются_только_присланные_номера(tmp_path):
    c, st, pid, роли = _клиент(tmp_path)
    reg = TaskRegistry(st)
    a = reg.add(pid, "Задача первая", "Петрова Анастасия")
    b = reg.add(pid, "Задача вторая", "Игнатов Иван")
    остаётся = reg.add(pid, "Задача третья", "Сидоров Пётр")
    r = c.post("/tasks/bulk-delete", json={"ids": [a, b]}, headers=_заголовки(pid, роли["project_admin"]))
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2, "refused": 0, "ids": [a, b]}
    assert not st.get("tasks", a) and not st.get("tasks", b)
    assert st.get("tasks", остаётся), "неотмеченная задача остаётся"


def test_частичный_отказ_числом(tmp_path):
    c, st, pid, роли = _клиент(tmp_path)
    tid = TaskRegistry(st).add(pid, "Задача на удаление", "Петрова Анастасия")
    r = c.post("/tasks/bulk-delete", json={"ids": [tid, 999999]}, headers=_заголовки(pid, роли["super_admin"]))
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1 and r.json()["refused"] == 1
    assert not st.get("tasks", tid)


def test_уборка_как_у_одиночного_удаления(tmp_path):
    c, st, pid, роли = _клиент(tmp_path)
    reg = TaskRegistry(st)
    tid = reg.add(pid, "Задача с карточкой и историей", "Петрова Анастасия")
    reg.set_status(tid, TaskStatus.DONE, "web_form", "сделано")
    card = CardQueue(st).open(pid, "held_task", "Карточка о задаче", {"task_id": tid})
    unit = st.insert("units", project_id=pid, meeting_id=None, kind="clarification", text="Уточнение к задаче",
                     quote="", status="open", task_id=tid, line_from=0, line_to=0, ts=None, planned_date=None,
                     roles=[], extracted_by="", created_at="2026-11-08T10:00:00", updated_at="2026-11-08T10:00:00")
    r = c.post("/tasks/bulk-delete", json={"ids": [tid]}, headers=_заголовки(pid, роли["project_admin"]))
    assert r.status_code == 200, r.text
    # номер карточки может достаться служебной карточке события (`cards.id` без AUTOINCREMENT), поэтому сверяем
    # не строку по номеру, а сами связи: карточек и истории с этим номером задачи нет, у единицы связь снята
    assert not st.q("SELECT id FROM cards WHERE payload LIKE ?", (f'%"task_id": {tid}%',))
    assert not st.get("cards", card) or (st.get("cards", card)["payload"] or "{}").find(f'"task_id": {tid}') < 0
    assert st.get("units", unit)["task_id"] is None
    assert not st.q("SELECT id FROM task_history WHERE task_id=?", (tid,))


def test_пометить_все_берёт_только_видимый_список():
    """«Только видимые» — правило экрана: отметки ставятся строкам текущего списка (`$list`), а не всем задачам проекта."""
    код = (КОРЕНЬ / "meetflow" / "web" / "static" / "registry.js").read_text(encoding="utf-8")
    assert "function привязатьОтметки($list)" in код
    assert '$list.querySelectorAll(".task-check")' in код
    for подпись in ("Пометить все", "Снять выделение", "Удалить выделенное"):
        assert подпись in код, подпись
    assert '/tasks/bulk-delete' in код and "confirmDialog(" in код
