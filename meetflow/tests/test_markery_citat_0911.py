"""Служебная пометка вместо цитаты не хранится (рекомендация Планёрки 09.11.2026, п. 1)."""
from __future__ import annotations

from meetflow.core import markery_citat as м
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store


def test_пометки_узнаются():
    assert м.служебная("эталон B+C 06.11.2026")
    assert м.служебная("Протокол 06.11.2026")
    assert м.служебная("импорт из ERP")
    assert м.служебная("Протокол_планёрки_06_11_2026.docx")
    assert not м.служебная("[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте график")
    assert not м.служебная("")
    assert not м.служебная("Протокол совещания решил: поставки по средам, ответственный Петров, срок пятница — "
                           "подробная запись разговора, которая длиннее пометки и похожа на настоящую цитату")


def test_реестр_не_хранит_пометку_в_цитате():
    s = Store(":memory:")
    try:
        pid = s.insert("projects", name="Пилот", theme="it_product")
        tid = TaskRegistry(s).add(pid, "Ответить на замечания ПВК", "Петров Иван", None,
                                  quote="эталон B+C 06.11.2026")
        assert s.get("tasks", tid)["source_quote"] in ("", None)
        tid2 = TaskRegistry(s).add(pid, "Подготовить график", "Петров Иван", None,
                                   quote="[00:02:00] Петрова Анастасия, подготовьте график к пятнице")
        assert s.get("tasks", tid2)["source_quote"].startswith("[00:02:00]")
    finally:
        s.close()
