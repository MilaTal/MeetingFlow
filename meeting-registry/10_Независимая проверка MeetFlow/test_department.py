"""R15 (письмо 14, 03.10.26): отдел без руководителя — своя причина и карточка с сотрудниками отдела.
Правило владельца 26.09.26: в рабочий материал не давать. Шлюз проверяется напрямую — на заглушке R15 пустой."""

from meetflow.core.gates import TaskGate
from meetflow.core.people import Team
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

LINE = "Гаврилов Павел: ОТН, проверьте пломбы на цистернах."


def team():
    return Team([Person("Гаврилов Павел"), Person("Осипов Игорь", department="ОТН"), Person("Ершова Светлана", department="ОСН")],
                department_heads={"осн": "Ершова Светлана"})


def check(mention):
    src = SourceDoc("t", SourceKind.TRANSCRIPT, f"[00:00:00] {LINE}")
    return TaskGate(team()).check(TaskDraft("Проверить пломбы на цистернах", mention, quote=LINE), src)


def test_r15_department_without_head_task_first():
    """Перевёрнут 03.10.26 по документу 14, п. 4а (решение владельца): задача заводится сразу, исполнитель — отдел,
    рядом карточка «назначить ответственного» с сотрудниками отдела. Было: шлюз не пропускал, задача только в карточке."""
    from conftest import Env, Scripted

    def g(pu, sy, us):
        if pu == "extract_tasks":
            return {"tasks": [{"description": "проверьте пломбы на цистернах", "assignee": "ОТН", "line": 0}]}
    e = Env(gen=Scripted(g), team=["Гаврилов Павел"])
    e.s.insert("people", project_id=e.pid, full_name="Осипов Игорь", department="ОТН")
    e.src(f"[00:00:00] {LINE}\n")
    e.run()
    t = e.tasks()
    assert len(t) == 1 and "ОТН" in (t[0]["assignee"] or ""), t
    cards = [c for c in e.cards() if c["payload"].get("task_id") == t[0]["id"]]
    assert cards and any("Осипов" in c_["name"] for c_ in cards[0]["payload"].get("candidates") or []), cards


def test_r15_department_with_head_still_assigns():
    assert team().find("ОСН").person.full_name == "Ершова Светлана"


def test_r15_surname_is_not_department():
    assert team().find("Осипов").via != "department_without_head"
