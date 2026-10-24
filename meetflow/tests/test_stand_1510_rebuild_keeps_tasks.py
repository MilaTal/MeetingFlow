"""Находка циклов ролей ERP и Планёрки (ВЫСОКИЙ, через «Мониторинг» 15.10.26): пересборка протокола снимала задачи своей
встречи как «задача прошлого прогона» и не заводила заново — сверка «уже в реестре» видела задачи этой же встречи как
чужие. Проверка для MeetFlow: встреча с задачами → пересобрать → задачи живы, номера прежние, без дублей; то же для
задачи «под вопросом» без дословной цитаты (её повтор узнавался только по цитате)."""
from conftest import TRANSCRIPT

from meetflow.connectors.llm_mock import MockLLM


def _snapshot(store, project, mid):
    return sorted((t["id"], t["description"], t["status"]) for t in
                  store.q("SELECT * FROM tasks WHERE project_id=? AND source_meeting_id=?", (project, mid)))


def test_rebuild_keeps_own_tasks_alive_same_numbers(store, project, make_pipe):
    p = make_pipe()
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    before = _snapshot(store, project, mid)
    assert before
    p.run(project, mid)
    p.run(project, mid)
    assert _snapshot(store, project, mid) == before, "пересборка сняла, завела заново или удвоила задачи встречи"
    assert all(s == "active" for _, _, s in before)


class NoQuote(MockLLM):
    """Модель отдаёт поручение без опоры в записи — задача «под вопросом» без цитаты."""
    def _extract(self, data):
        return {"tasks": [{"description": "Составить план закупок на ноябрь", "assignee": "Петрова Анастасия",
                           "quote": "по указанию руководителя"}]}


def test_rebuild_does_not_double_doubt_task_without_quote(store, project, make_pipe):
    p = make_pipe(gen=NoQuote())
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    first = _snapshot(store, project, mid)
    assert any("план закупок" in d for _, d, _ in first)
    p.run(project, mid)
    assert _snapshot(store, project, mid) == first, "задача «под вопросом» без цитаты удвоилась при пересборке"
    assert len(store.q("SELECT * FROM cards WHERE kind='task_doubt' AND status='open'")) == 1
