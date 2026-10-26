"""Письмо 39 (находка Планёрки 692d05d): таблица поручений в протоколе собиралась раньше последнего
решения — протокол утверждал не то, что в реестре. Проверка при task_first: поручения и исполнители в
сохранённом протоколе совпадают с реестром после ворот. Тест написан до правки."""
import re

import pytest

from meetflow.connectors.llm_mock import MockLLM


class Say(MockLLM):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def _extract(self, data):
        return {"tasks": self.items}


def _rows(md):
    out = {}
    for ln in md.splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
        # перевёрнут 27.10.2026: семь колонок (№ · Задача · Статус · Ответственный · …), ERP 26.10.2026
        if len(cells) == 7 and cells[0].isdigit():
            out[cells[1]] = cells[3]
    return out


@pytest.mark.parametrize("who,line", [
    ("Сидоров Олег", "Гаврилов Павел: Сидоров Олег, подготовьте график монтажа"),     # новый «не подтверждён»
    ("ОТН", "Гаврилов Павел: ОТН, подготовьте график монтажа"),                       # отдел без руководителя
    (None, "Гаврилов Павел: Решили подготовить график монтажа"),                      # без исполнителя
])
def test_protocol_assignee_equals_registry(store, project, make_pipe, who, line):
    store.insert("people", project_id=project, full_name="Гаврилов Павел")
    store.insert("people", project_id=project, full_name="Осипов Игорь", department="ОТН")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Say([{"description": "Подготовить график монтажа", "assignee": who, "quote": line}]))
    p.ingest(project, mid, "t 01.10.2026.txt", f"[00:01:00] {line}\n".encode())
    assert p.run(project, mid).tasks_added == 1
    reg = {t["description"]: t["assignee"] for t in store.q("SELECT * FROM tasks WHERE source_meeting_id=?", (mid,))}
    proto = _rows(store.get("meetings", mid)["protocol_md"])
    from meetflow.core.tablica_zadach import НЕ_НАЗНАЧЕН
    unassigned = НЕ_НАЗНАЧЕН                 # перевёрнут 27.10.2026: «не назначен», как таблица ERP
    assert set(proto) == set(reg)
    assert all(proto[d] == (reg[d] or unassigned) for d in reg)
