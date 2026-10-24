"""Находка стенда, строка 42 (обе системы, 371f967 — корень случая 08.10): реестр «на дату встречи».
Сборка встречи D видит только задачи, поставленные до D включительно; иначе поручение ранней встречи
молча уходит «уже в реестре» к задаче поздней. Тест написан до правки и падал."""
from conftest import TRANSCRIPT


def test_later_task_does_not_swallow_earlier_meeting_task(store, project, make_pipe):
    p = make_pipe()
    late = p.reg.add(project, "подготовьте регламент склада до 10.10", "Петрова Анастасия", date_set="2026-10-08")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча 01.10")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    mine = [t for t in p.reg.list(project) if t["source_meeting_id"] == mid and "регламент" in t["description"]]
    assert mine, "поручение 01.10 ушло «уже в реестре» к задаче 08.10"
    assert not any("duplicate" in (c["payload"].get("reasons") or []) for c in p.cards.list(project))
    assert store.get("tasks", late)["status"] == "active"


def test_earlier_task_still_counts_as_duplicate(store, project, make_pipe):
    p = make_pipe()
    p.reg.add(project, "подготовьте регламент склада до 10.10", "Петрова Анастасия", date_set="2026-09-20")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча 01.10")
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    mine = [t for t in p.reg.list(project) if t["source_meeting_id"] == mid and "регламент" in t["description"]]
    assert not mine, "задача, поставленная до встречи, — дубль, второй раз не заводится"
