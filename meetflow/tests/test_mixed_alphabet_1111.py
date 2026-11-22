# -*- coding: utf-8 -*-
"""Смешанные алфавиты в названиях протокола (11.11.2026).

Живой случай — протокол 10.11: «Quadrosоft» — латиница с кириллической «о». Глазом не видно, поиск и
сверка со справочником ломаются. Ловим кодом: слово, где есть и кириллица, и латиница.
"""
from meetflow.core import draft_checks


def test_mixed_word_is_found():
    md = "|1|Подать протоколы на устранение замечаний по Quadrosоft|не назначен|\n"
    found = draft_checks.mixed_alphabet(md)
    assert len(found) == 1
    assert found[0]["kind"] == "смешанный алфавит"
    assert "Quadrosоft" in found[0]["note"]


def test_clean_alphabet_is_silent():
    md = "|1|Подать протоколы по Quadrosoft|Иванов И.И.|\n|2|Согласовать мебель|Петров П.П.|\n"
    assert draft_checks.mixed_alphabet(md) == []


def test_run_code_checks_includes_mixed_alphabet():
    md = "|1|Проверить SRG-50 и SRG-60 в Quadrosоft|\n"
    kinds = [f["kind"] for f in draft_checks.run_code_checks(md, "текст записи")]
    assert "смешанный алфавит" in kinds
