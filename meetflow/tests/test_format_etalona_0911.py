# -*- coding: utf-8 -*-
"""Формат протокола по эталону заказчика (слово владелицы 09.11.2026).

Эталон 06.11.2026: шапка «Протокол встречи  06.11.2026» (названия встречи в шапке нет), разделы «Участники»,
«Что сделано», «Блокирующие факторы», «Решения», «Открытые вопросы»; таблица «Поставленные на встрече» —
№, Задача, Ответственный, Срок, Дата постановки; пустые ячейки вместо «не назначен»/«не указан»; Word Calibri 11.
Новая тема `mf_protocol`; старая `it_product` (семь колонок, тема в шапке) остаётся для уже сохранённых протоколов.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline
from meetflow.core.store import Store

ЗАПИСЬ = "[00:00:10] Орлова Анна: Петрова Анастасия, подготовьте регламент склада до пятницы."


def test_тема_по_эталону():
    theme = load_theme("mf_protocol")
    assert theme.word("protocol") == "Протокол встречи"
    assert theme.get("protocol_skeleton") == ["Участники", "Что сделано", "Блокирующие факторы", "Решения",
                                              "Открытые вопросы"]
    assert theme.get("protocol_table", {}).get("columns") == ["№", "Задача", "Ответственный", "Срок",
                                                              "Дата постановки"]
    assert theme.get("protocol", {}).get("title_with_topic") is False
    assert theme.get("design", {}).get("document_font") == "Calibri"
    assert int(theme.get("design", {}).get("document_size_pt")) == 11


def _сборка(theme_name: str):
    theme = load_theme(theme_name)
    store = Store(":memory:")
    pid = store.insert("projects", name="Общие встречи", theme=theme_name, general=1)
    mid = store.insert("meetings", project_id=pid, date="2026-11-09")
    store.insert("sources", meeting_id=mid, name="запись", kind="transcript", text=ЗАПИСЬ, digest="формат" + theme_name,
                 local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False), created_at="2026-11-09T10:00:00")
    p = MeetingPipeline(theme, store, default_registry(), MockLLM(), MockLLM(),
                        journal_path=Path(tempfile.gettempdir()) / "j_format.jsonl")
    p.run(pid, mid)
    md = store.get("meetings", mid)["protocol_md"]
    store.close()
    return md


def test_шапка_и_таблица_как_в_эталоне():
    md = _сборка("mf_protocol")
    assert md.startswith("# Протокол встречи 09.11.2026\n"), md[:80]
    assert "Итоги синка" not in md[:200], "названия встречи и слова «синк» в шапке нет"
    assert "| № | Задача | Ответственный | Срок | Дата постановки |" in md
    assert "| Статус |" not in md and "| Откуда |" not in md
    assert "| не назначен |" not in md and "| не указан |" not in md
    assert "## Что сделано" in md


def test_старая_тема_осталась_семь_колонок():
    md = _сборка("it_product")
    assert md.startswith("# Итоги синка 09.11.2026"), md[:80]
    assert "| № | Задача | Статус | Ответственный | Срок | Дата постановки | Откуда |" in md
