"""Находка стенда, строка 31 (Планёрка, задача №219, протокол секретаря 30.09): служебная заметка секретаря
в ячейке таблицы задач («задача с 29.09.2026 не обсуждали на текущей планерке») переносилась моделью в
формулировку и тянулась в каждый протокол. Код вырезает хвосты при любом заведении; формы — общий файл ERP и
Планёрки document_marks.md. Тесты написаны до правки и падали."""
import hashlib
from pathlib import Path

import pytest

from meetflow.core.document_marks import FILE, strip_tails
from meetflow.core.registry import TaskRegistry

STAND = Path(r"C:\Users\Мила\Documents\ITMO_case\Тестовый стенд 13.10.26\code\webapp\project-data\document_marks.md")


@pytest.mark.parametrize("raw, clean", [
    ("Бухта-Север: составить график, задача с 29.09.2026 не обсуждали на текущей планерке",
     "Бухта-Север: составить график"),
    ("Подготовить акт сверки (задача с 26.08.2026)", "Подготовить акт сверки"),
    ("Сверить остатки, задача с планёрки 28.09.2026", "Сверить остатки"),
    ("Сдать отчёт поставлена 30.09.2026", "Сдать отчёт"),
])
def test_tail_is_cut(raw, clean):
    assert strip_tails(raw)[0] == clean


@pytest.mark.parametrize("text", [
    "Задача поставлена 06.08.26, ответственный — склад, срок пятница",   # в прозе — не хвост (ERP, Сводки №15–16)
    "Обсудить на текущей планерке график отпусков",
    "задача с 29.09.2026",                                                # стала бы пустой — остаётся как была
])
def test_business_text_untouched(text):
    assert strip_tails(text)[0] == text


def test_registry_add_cuts_tail_on_every_path(store, project):
    reg = TaskRegistry(store)
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="в")
    t1 = reg.add(project, "Составить график, задача с 29.09.2026 не обсуждали на текущей планерке", None, mid)
    t2 = reg.add(project, "Составить график (задача с 26.08.2026)", None)          # ручное заведение
    assert store.get("tasks", t1)["description"] == "Составить график"
    assert store.get("tasks", t2)["description"] == "Составить график"


def test_forms_file_is_the_shared_one():
    """Файл общий с ERP и Планёркой — копия байт в байт; правится там и переносится целиком."""
    if not STAND.exists():
        pytest.skip("стенда ERP на этой машине нет")
    assert hashlib.md5(FILE.read_bytes()).hexdigest() == hashlib.md5(STAND.read_bytes()).hexdigest()
