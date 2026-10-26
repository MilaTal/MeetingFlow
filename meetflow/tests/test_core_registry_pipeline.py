"""Ядро: проверки задачи, реестр, карточки, память оператора, конвейер."""
import threading

from conftest import TRANSCRIPT

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.gates import TaskGate
from meetflow.core.people import Team
from meetflow.core.registry import CardQueue, OperatorMemory, TaskRegistry
from meetflow.core.types import CardStatus, Person, SourceDoc, SourceKind, TaskDraft, TaskStatus

SRC = SourceDoc("t.txt", SourceKind.TRANSCRIPT, TRANSCRIPT)
GATE = TaskGate(Team([Person("Игнатов Иван"), Person("Петрова Анастасия"), Person("Сидоров Пётр")]))


def test_gate_accepts_named_assignee_with_quote():
    g = GATE.check(TaskDraft("подготовить регламент склада", "Петрова Анастасия", line_no=2), SRC)
    assert g.accepted and "регламент" in g.quote


def test_gate_quote_is_taken_from_source_not_model():
    g = GATE.check(TaskDraft("подготовить регламент склада", "Петрова Анастасия",
                             quote="Петрова, подготовьте регламент склада"), SRC)
    assert g.accepted and g.quote.startswith("[00:02:00]")


def test_gate_holds_without_quote():
    g = GATE.check(TaskDraft("купить слона", "Петрова Анастасия", quote="купить слона"), SRC)
    assert not g.accepted and "no_verbatim_quote" in g.reasons


def test_gate_unknown_full_name_is_new_person():
    # перевёрнут 03.10.26 по документу 14 (решение владельца, письмо 34): человек не из «Команды», названный
    # фамилией и именем, заводится «не подтверждён», задача на него, оператору — карточка на подтверждение
    g = GATE.check(TaskDraft("проверить отчёт по браку", "Кузнецов Олег", line_no=4), SRC)
    assert g.accepted and g.pending["reason"] == "new_person" and g.pending["name"] == "Кузнецов Олег"


def test_gate_holds_question():
    g = GATE.check(TaskDraft("обновить спецификации", "Игнатов Иван", line_no=5), SRC)
    assert "question_not_assignment" in g.reasons


def test_gate_duplicate_same_person_only():
    d = TaskDraft("подготовить регламент склада", "Петрова Анастасия", line_no=2)
    assert "duplicate" in GATE.check(d, SRC, [("подготовить регламент склада", "Петрова Анастасия")]).reasons
    assert GATE.check(d, SRC, [("подготовить регламент склада", "Игнатов Иван")]).accepted  # разные люди — две задачи


def test_gate_caps_description():
    g = GATE.check(TaskDraft("подготовить регламент склада " + "х" * 5000, "Петрова Анастасия", line_no=2), SRC)
    assert g.accepted


def test_registry_numbering_from_one(store, project):
    reg = TaskRegistry(store)
    ids = [reg.add(project, f"задача {i}", None) for i in range(3)]
    reg.set_status(ids[0], TaskStatus.DONE, "web_form")
    rows = reg.list(project)
    assert [r["no"] for r in rows] == [1, 2] and rows[0]["id"] == ids[1]


def test_registry_meeting_close_needs_fact_quote(store, project):
    reg = TaskRegistry(store)
    t = reg.add(project, "отправить выгрузку", "Сидоров Пётр")
    assert not reg.set_status(t, TaskStatus.DONE, "meeting", "Выгрузку отправил?")
    assert not reg.set_status(t, TaskStatus.DONE, "meeting", "")
    assert reg.set_status(t, TaskStatus.DONE, "meeting", "Выгрузку отправил, сделано.")
    hist = reg.history(t)
    assert hist[-1]["source"] == "meeting" and "сделано" in hist[-1]["evidence_quote"]


def test_dropped_differs_from_done_and_can_return(store, project):
    reg = TaskRegistry(store)
    t = reg.add(project, "x", None)
    reg.set_status(t, TaskStatus.DROPPED, "web_form")
    assert reg.list(project, TaskStatus.DROPPED)[0]["id"] == t and not reg.list(project, TaskStatus.DONE)
    reg.set_status(t, TaskStatus.ACTIVE, "web_form")
    assert reg.list(project)[0]["id"] == t


def test_memory_needs_two_same_answers(store, project):
    mem = OperatorMemory(store)
    r1 = mem.answer(project, "not_a_person", "Даш", "reject")
    assert r1["status_text"] == "на паузе: 1 из 2" and mem.lookup(project, "not_a_person", "Даш") is None
    r2 = mem.answer(project, "not_a_person", "даш", "reject")
    assert r2["status_text"] == "действует" and mem.lookup(project, "not_a_person", "Даш") == "reject"


def test_memory_different_answers_reset(store, project):
    mem = OperatorMemory(store)
    mem.answer(project, "same_person", "Света", "Петрова Светлана")
    r = mem.answer(project, "same_person", "Света", "Игнатова Светлана")
    assert r["active"] == 0


def test_memory_revoke_restore_and_decay(store, project):
    mem = OperatorMemory(store)
    mem.answer(project, "not_a_task", "k", "reject")
    r = mem.answer(project, "not_a_task", "k", "reject")
    assert r["expires_at"]  # «не задача» затухает через 21 день
    mem.revoke(r["id"])
    assert mem.lookup(project, "not_a_task", "k") is None
    mem.restore(r["id"])
    assert mem.lookup(project, "not_a_task", "k") == "reject"


def test_card_resolve_twice_keeps_first(store, project):
    q = CardQueue(store)
    cid = q.open(project, "held_task", "t")
    q.resolve(cid, CardStatus.ACCEPTED, "да")
    out = q.resolve(cid, CardStatus.REJECTED, "нет")
    assert out["status"] == "accepted"
    assert len(store.q("SELECT * FROM decisions")) == 1


def test_card_resolve_race(store, project):
    q = CardQueue(store)
    cid = q.open(project, "held_task", "t")
    ths = [threading.Thread(target=q.resolve, args=(cid, CardStatus.ACCEPTED if i % 2 else CardStatus.REJECTED))
           for i in range(20)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert len(store.q("SELECT * FROM decisions")) == 1


def test_pipeline_end_to_end(store, project, meeting, make_pipe):
    p = make_pipe()
    old = p.reg.add(project, "Отправить выгрузку остатков склада", "Сидоров Пётр", date_set="2026-09-01")
    assert p.ingest(project, meeting, "Расшифровка 01.10.2026.txt", TRANSCRIPT.encode())["status"] == "ok"
    rep = p.run(project, meeting)
    assert rep.status == "ok" and rep.protocol_saved
    # перевёрнут 03.10.26 по документу 14 (решение владельца, письмо 34): человек не из «Команды», названный
    # фамилией и именем, заводится «не подтверждён», задача на него, оператору — карточка на подтверждение
    assert rep.tasks_added == 2 and rep.tasks_held == 0 and rep.tasks_closed == 1
    assert store.get("tasks", old)["status"] == "done"
    proto = store.get("meetings", meeting)["protocol_md"]
    # перевёрнут 15.10.26 (находка стенда 30, правило владельца 13.10.26): документ чистый — пометка «откуда собран» убрана
    assert proto.startswith("# Протокол встречи 01.10.2026") and "Откуда: собран" not in proto
    # перевёрнут 09.10.26: срок без года — с годом встречи, «день.месяц.год» (формат владельца)
    # перевёрнут 27.10.2026 (таблица задач как у секретаря, ERP 26.10.2026): семь колонок, статус и дата постановки
    assert ("| 1 | подготовьте регламент склада до 10.10 | в работе | Петрова Анастасия | 10.10.2026 | 01.10.2026 | "
            "запись |") in proto
    cards = p.cards.list(project)
    assert cards[0]["kind"] == "confirm_person" and cards[0]["payload"]["full_name"] == "Кузнецов Олег"


def test_pipeline_rerun_does_not_duplicate(store, project, meeting, make_pipe):
    p = make_pipe()
    p.ingest(project, meeting, "Расшифровка 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, meeting)
    rep2 = p.run(project, meeting)
    assert rep2.tasks_added == 0 and len(p.reg.list(project)) == 2       # Петрова и Кузнецов (документ 14)
    assert len(store.q("SELECT * FROM people WHERE full_name='Кузнецов Олег'")) == 1   # второй записи нет


def test_pipeline_duplicate_source_upload(store, project, meeting, make_pipe):
    p = make_pipe()
    p.ingest(project, meeting, "a.txt", TRANSCRIPT.encode())
    assert p.ingest(project, meeting, "b.txt", TRANSCRIPT.encode())["status"] == "duplicate"


def test_pipeline_no_sources(store, project, meeting, make_pipe):
    rep = make_pipe().run(project, meeting)
    assert rep.status == "no_sources" and not rep.protocol_saved


def test_pipeline_notes_only(store, project, meeting, make_pipe):
    notes = ("Протокол встречи 01.10\nПовестка: склад\nРешили: регламент\n"
             "Петрова Анастасия, подготовьте регламент склада до 10.10\nОтветственный указан, срок задан")
    p = make_pipe()
    r = p.ingest(project, meeting, "Заметки 01.10.2026.txt", notes.encode())
    assert r["kind"] == "notes"
    rep = p.run(project, meeting)
    assert rep.status == "ok" and rep.tasks_added == 1


def test_pipeline_rejects_own_output(store, project, meeting, make_pipe):
    p = make_pipe()
    p.ingest(project, meeting, "a.txt", TRANSCRIPT.encode())
    p.run(project, meeting)
    own = store.get("meetings", meeting)["protocol_md"].encode()
    assert p.ingest(project, meeting, "протокол.md", own)["status"] == "rejected"


def test_one_phrase_cannot_close_many(store, project, meeting, make_pipe):
    p = make_pipe()
    a = p.reg.add(project, "Отправить выгрузку остатков склада", "Сидоров Пётр", date_set="2026-09-01")
    b = p.reg.add(project, "Выгрузку остатков склада сверить", "Сидоров Пётр", date_set="2026-09-01")
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())

    class Greedy(MockLLM):  # «Получилось.» для всех задач сразу
        def _closing(self, user):
            return {"closed": [{"task_ref": a, "phrase": 3}, {"task_ref": b, "phrase": 3}]}

    rep = make_pipe(gen=Greedy()).run(project, meeting)
    assert rep.tasks_closed == 0 and rep.closing_cards == 2


def test_verify_findings_are_notes_not_gate(store, project, meeting, make_pipe):
    p = make_pipe(ver=MockLLM(fail_verify=True))
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    rep = p.run(project, meeting)
    assert rep.protocol_saved and rep.findings  # сохранено сразу, замечания — справка
