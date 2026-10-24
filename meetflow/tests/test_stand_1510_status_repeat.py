"""Находка стенда, строка 35 (Планёрка, хаос-проверка 14.10.26): двойное «Выполнено»
из двух вкладок или повтор запроса писало второе закрытие и сдвигало дату.
Повтор той же смены статуса — без изменений. Тест написан до правки и падал."""
from meetflow.core.registry import TaskRegistry
from meetflow.core.types import TaskStatus


def test_repeat_same_status_writes_nothing(store, project):
    reg = TaskRegistry(store)
    tid = reg.add(project, "подготовить акт сверки", None)
    assert reg.set_status(tid, TaskStatus.DONE, "web_form", meeting_date="2026-10-14")
    reg.set_status(tid, TaskStatus.DONE, "web_form", meeting_date="2026-10-15")   # вторая вкладка
    t = store.get("tasks", tid)
    assert t["date_closed"] == "2026-10-14", "повтор сдвинул дату закрытия"
    closes = store.q("SELECT * FROM task_history WHERE task_id=? AND new_status='done'", (tid,))
    assert len(closes) == 1, "повтор записал второе закрытие"


def test_real_change_still_applies(store, project):
    reg = TaskRegistry(store)
    tid = reg.add(project, "подготовить акт сверки", None)
    reg.set_status(tid, TaskStatus.DONE, "web_form")
    assert reg.set_status(tid, TaskStatus.ACTIVE, "web_form")
    assert store.get("tasks", tid)["status"] == "active"
    assert store.get("tasks", tid)["date_closed"] is None
