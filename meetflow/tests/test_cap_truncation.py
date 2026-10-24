"""Потолок ответа 4096 (решение владельца 03.10.26) не должен терять встречу. Прогон этапа 6 на встречах
ERP: 08.09 — извлечение поручений упёрлось в потолок, вся встреча ушла в сбой, задач 0. Тест до правки."""
import pytest

from conftest import TRANSCRIPT
from meetflow.connectors.base import AnswerTruncated, ConnectorError
from meetflow.connectors.llm_mock import MockLLM


class CapAt(MockLLM):
    """Ответ «обрывается», если в куске больше N строк — как длинный протокол секретаря."""
    def __init__(self, max_lines, purposes=("extract_tasks",)):
        super().__init__()
        self.max_lines, self.purposes, self.sizes = max_lines, purposes, []

    def complete(self, system, user, **k):
        if k.get("purpose") in self.purposes:
            n = sum(1 for ln in user.splitlines() if ln[:1].isdigit() or ln.startswith("L"))
            self.sizes.append(n)
            if n > self.max_lines:
                raise AnswerTruncated("Ответ модели оборван потолком 4096 токенов")
        return super().complete(system, user, **k)


def test_truncation_is_connector_error():
    assert issubclass(AnswerTruncated, ConnectorError)


def test_extract_splits_chunk_instead_of_failing(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    gen = CapAt(max_lines=3)
    p = make_pipe(gen=gen)
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    assert rep.status in ("ok", "ok_limited") and rep.protocol_saved
    assert rep.tasks_added >= 1                          # «Петрова… регламент склада» не потерялась
    assert len(gen.sizes) >= 3 and min(gen.sizes) <= 3   # кусок делился


def test_protocol_truncation_keeps_tasks(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=CapAt(max_lines=-1, purposes=("protocol",)))
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    assert rep.protocol_saved and rep.tasks_added >= 1
    # перевёрнут 15.10.26 (находка стенда 30, правило владельца 13.10.26): документ чистый — пометка в карточке
    md = store.get("meetings", mid)["protocol_md"]
    assert "потолк" not in md and "Не собрано" not in md
    assert any("потолк" in c["payload"].get("detail", "") for c in store.q("SELECT * FROM cards WHERE kind='technical'")
               for c in [{**c, "payload": __import__("json").loads(c["payload"] or "{}")}])
