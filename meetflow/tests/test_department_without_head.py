"""R15 набора meeting-registry, письмо 14 (03.10.26): отдел без руководителя —
отдельная причина department_without_head и понятная карточка «Отдел без
руководителя: назначьте ответственного» с отделом, цитатой и сотрудниками
отдела кандидатами. Правило владельца 26.09: в рабочий материал не давать.
Шлюз проверяется напрямую — на заглушке модели R15 проходит впустую."""
import json

import pytest

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core.gates import TaskGate
from meetflow.core.people import Team
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

TEAM = Team([Person("Гаврилов Павел"), Person("Осипов Игорь", department="ОТН"),
             Person("Лаптева Ольга", department="отдел технического надзора"),
             Person("Ершова Светлана", department="закупки")],
            department_heads={"осн": "Ершова Светлана"})
LINE = "Гаврилов Павел: ОТН, проверьте пломбы на цистернах."


@pytest.mark.parametrize("mention", ["ОТН", "отдел технического надзора"])
def test_department_without_head_reason(mention):
    src = SourceDoc("t", SourceKind.TRANSCRIPT, f"[00:00:00] {LINE}")
    # перевёрнут 03.10.26 (письмо 36): по умолчанию задача принимается с пометкой «отдел»; при выключенном
    # task_first — прежняя задержка карточкой
    g = TaskGate(TEAM).check(TaskDraft("Проверить пломбы на цистернах", mention, quote=LINE), src)
    assert g.accepted and g.pending["reason"] == "department" and g.pending["name"] == mention
    from meetflow.core.gates import GateConfig
    g2 = TaskGate(TEAM, cfg=GateConfig(task_first=False)).check(TaskDraft("Проверить пломбы на цистернах", mention,
                                                                          quote=LINE), src)
    assert not g2.accepted and "department_without_head" in g2.reasons
    m = TEAM.find(mention)
    assert m.via == "department_without_head" and {p.full_name for p in m.candidates} == {"Осипов Игорь", "Лаптева Ольга"}


def test_department_with_head_still_assigns():
    assert TEAM.find("ОСН").person.full_name == "Ершова Светлана"


def test_unknown_person_is_not_department():
    assert TEAM.find("Кутузов").via != "department_without_head"


class Ask(MockLLM):
    def _extract(self, data):
        return {"tasks": [{"description": "Проверить пломбы на цистернах", "assignee": "ОТН", "quote": LINE}]}


def test_card_title_and_payload(store, project, make_pipe):
    store.insert("people", project_id=project, full_name="Осипов Игорь", department="ОТН")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Ask())
    p.ingest(project, mid, "t 01.10.2026.txt", f"[00:01:00] {LINE}\n".encode())
    # перевёрнут 03.10.26 решением владельца (письмо 36): задача отделу без руководителя заводится сразу,
    # рядом карточка «назначить ответственного в отделе». Перевёрнут ещё раз владельцем 10.10.26: исполнитель
    # пустой, отдел — только в карточке (было: в графе исполнителя — отдел)
    assert p.run(project, mid).tasks_added == 1
    t = store.q("SELECT * FROM tasks")[0]
    assert t["assignee"] is None
    card = store.q("SELECT * FROM cards WHERE kind='assign_person'")[0]
    pl = json.loads(card["payload"])
    assert card["title"].startswith("Отдел без руководителя: назначьте ответственного")
    assert pl["reason"] == "department" and pl["department"] == "ОТН" and pl["task_id"] == t["id"]
    assert [c["name"] for c in pl["candidates"]] == ["Осипов Игорь"]
