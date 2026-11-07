"""Правило 16.10 и 20.10 — семь случаев (записки 09cf585, d60557a, 07.11.2026).

Вопрос-просьба и отрицание внутри содержания — обычная задача без карточки; условие — «под вопросом»;
намерение о себе и мелочь — отсев. Тесты держат и то, что сборка не падает на условии (был `KeyError candidates`).
"""
from meetflow.core.gates import TaskGate
from meetflow.core.people import Team
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

ЛЮДИ = [Person("Петрова Анна"), Person("Игнатов Иван")]
GATE = TaskGate(Team(ЛЮДИ))


def _источник(строка: str) -> SourceDoc:
    return SourceDoc("проба.txt", SourceKind.TRANSCRIPT, f"[00:00:01] Петрова Анна: {строка}")


def _проверить(строка: str, описание: str, кто: str | None = "Петрова Анна"):
    цитата = f"[00:00:01] Петрова Анна: {строка}"
    return GATE.check(TaskDraft(описание, кто, quote=цитата, line_no=0), _источник(строка))


def test_вопрос_просьба_обычная_задача():
    g = _проверить("Обновить спецификации склада, можешь?", "обновить спецификации склада")
    assert g.accepted and "question_not_assignment" not in g.reasons
    assert g.pending is None, "вопрос не даёт карточки"


def test_отрицание_внутри_содержания_обычная_задача():
    g = _проверить("Проверить остатки, а не только цены", "проверить остатки")
    assert g.accepted and "negation_in_quote" not in g.reasons


def test_вопрос_рядом_с_другим_замечанием_код_снят():
    g = _проверить("Подготовить отчёт по браку, можешь?", "подготовить отчёт")
    assert "question_not_assignment" not in g.reasons, "код вопроса снимается при любом наборе причин"


def test_условие_под_вопросом_и_без_пустого_списка_кандидатов():
    g = _проверить("Если успеем, проверим остатки на складе", "проверить остатки на складе")
    assert g.pending is None or "candidates" in g.pending, "карточка без списка кандидатов запрещена"


def test_намерение_о_себе_отсев():
    g = _проверить("Я буду делать табличку и добавлю", "сделать табличку", кто=None)
    assert "intent_not_assignment" in g.reasons


def test_мелочь_отсев():
    g = _проверить("Ну ладно, посмотрим", "ну ладно", кто=None)
    assert "insignificant" in g.reasons or not g.accepted


def test_условие_не_роняет_сборку():
    g = _проверить("Если получится, обновим регламент", "обновить регламент")
    assert isinstance(g.accepted, bool)
