# -*- coding: utf-8 -*-
"""Название встречи — фраза по содержанию (слово владелицы 09.11.2026).

Владелица: имя встречи — «созданная по контексту тематики фраза (например, „Оформление транспортных документов для
ИП-ков“) + дата дд.мм.гг». Дата стоит отдельной колонкой и в заголовке; в метке — только фраза. Если модель не смогла,
прежний путь (строка «Предмет»/заголовок протокола) остаётся. Ручное название не перезаписывается. Тексты вымышленные.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.config import load_theme
from meetflow.core.pipeline import MeetingPipeline

ЗАПИСЬ = "[00:00:10] Орлова Анна: Петрова Анастасия, подготовьте регламент склада до пятницы."


def _сборка(store, project, meeting, tmp_path, метка=None):
    store.update("meetings", meeting, file_name="запись.m4a", label=метка)
    p = MeetingPipeline(load_theme("it_product"), store, default_registry(), MockLLM(), MockLLM(),
                        journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="запись", kind="transcript", text=ЗАПИСЬ,
                 digest="название" + str(meeting), local_asr=1,
                 meta=json.dumps({"voice_names": {}}, ensure_ascii=False), created_at="2026-11-09T10:00:00")
    p.run(project, meeting)
    return store.get("meetings", meeting)


def test_пустое_название_становится_фразой_по_содержанию(store, project, meeting, tmp_path):
    м = _сборка(store, project, meeting, tmp_path)
    assert м["label"] == "Рабочая встреча по содержанию", м["label"]


def test_ручное_название_не_перезаписывается(store, project, meeting, tmp_path):
    м = _сборка(store, project, meeting, tmp_path, метка="Проверка приёма")
    assert м["label"] == "Проверка приёма"


def test_промпт_просит_короткую_фразу_без_даты():
    from meetflow.core.prompts import PromptBuilder, profile
    pb = PromptBuilder("Ты называешь рабочую встречу по её содержанию.", profile("generic"))
    system, user = pb.название_встречи("Обсуждали оформление транспортных документов для ИП.")
    весь = system + "\n" + user
    assert "3–7 слов" in весь and "Без даты" in весь
    assert "«встреча», «синк», «протокол»" in весь
    assert "{\"name\"" in user
