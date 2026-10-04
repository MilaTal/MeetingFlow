"""Письмо 38 оркестратора, решение владельца для всех веток: вердикт проверки «не чисто» — протокол
сохраняется сразу, а каждая существенная находка проверяющей модели уходит оператору отдельной карточкой.
Повод — Планёрка 25.09: протокол сохранили поверх девяти существенных находок, они никуда не дошли.
Тест написан до правки."""
from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM


class Strict(MockLLM):
    def complete(self, system, user, **k):
        if k.get("purpose") == "verify":
            from meetflow.core.types import LLMResult
            import json
            return LLMResult(json.dumps({"clean": False, "findings": [
                {"issue": "Заголовок «Курск» не звучал в записи", "quote": "Курск", "severity": "major"},
                {"issue": "Срок 10.10 не подтверждён", "quote": "до 10.10", "severity": "major"},
                {"issue": "Стиль: длинное предложение", "quote": "…", "severity": "minor"}]}, ensure_ascii=False),
                "mock", 1, 1, 0.0, 0.0)
        return super().complete(system, user, **k)


def test_each_major_finding_is_a_card(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(ver=Strict())
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    assert rep.protocol_saved                                         # протокол сохраняется сразу
    cards = store.q("SELECT * FROM cards WHERE kind='review_finding' AND meeting_id=?", (mid,))
    assert len(cards) == 2                                            # две существенные — две карточки
    assert any("Курск" in c["title"] for c in cards)


def test_rerun_does_not_duplicate_finding_cards(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(ver=Strict())
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    p.run(project, mid)
    assert len(store.q("SELECT * FROM cards WHERE kind='review_finding'")) == 2


class Judging(MockLLM):
    """Протокол с оценочным словом, которого нет в записи (кодовая проверка письма 18)."""
    def _protocol(self, system, data):
        out = super()._protocol(system, data)
        k = next(iter(out["sections"]))
        out["sections"][k] = "Решили фиксировать отправку задач по почте как нарушение."
        return out


def test_code_finding_is_a_card_too(store, project, make_pipe):
    """Письмо 40: существенная находка кодовой проверки — тоже карточка review_finding с меткой «проверка кодом»."""
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Judging())
    p.ingest(project, mid, "t 01.10.2026.txt", "[00:01:00] Игнатов Иван: Задачи по почте мы не принимаем.\n".encode())
    p.run(project, mid)
    p.run(project, mid)                                               # повтор не дублирует
    import json
    cards = store.q("SELECT * FROM cards WHERE kind='review_finding'")
    assert len(cards) == 1 and json.loads(cards[0]["payload"])["by"] == "проверка кодом"
    assert "нарушени" in cards[0]["title"]
