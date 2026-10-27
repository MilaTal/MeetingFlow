# -*- coding: utf-8 -*-
"""Выключатели словаря распознавания «Параметров системы» читаются распознаванием и сборкой (как ERP, 27.10.2026).

Экран MeetFlow хранил «Словарь проектов в подсказке распознавания» (`rec:asr_vocab`, переменная `MEETFLOW_ASR_VOCAB`) и
«Проект только при прозвучавшем названии» (`rec:project_only_heard`, `MEETFLOW_PROJECT_ONLY_HEARD`), но никто их не
читал. Теперь, как в ERP (монорепозиторий b0d8ab7: `slovar_whisper`, `iskazheniya_nazvaniy`, `recording_queue`,
`meeting_pipeline._проект_по_записи`): словарь — подсказка Whisper и «Транс» (`initial_prompt`) с проектом встречи в
конце, не длиннее 223 токенов, счёт — в журнал распознавания; правило — проект справочника без опоры в записи снимается
у абзаца тела и у формулировки задачи, проект встречи не снимается. Оба по умолчанию выключены. Моделей тесты не
вызывают, звука нет.
"""
import json
from pathlib import Path

import pytest

from meetflow.connectors import asr_whisper
from meetflow.connectors.base import ASRConnector
from meetflow.core import iskazheniya_nazvaniy as iz
from meetflow.core import slovar_whisper as sw
from meetflow.core.types import SourceDoc, SourceKind

Т = chr(9)
П = chr(10)


@pytest.fixture(autouse=True)
def _без_переменных(monkeypatch):
    monkeypatch.delenv("MEETFLOW_ASR_VOCAB", raising=False)
    monkeypatch.delenv("MEETFLOW_PROJECT_ONLY_HEARD", raising=False)


@pytest.fixture
def справочник(store, project):
    store.update("projects", project, aliases=json.dumps(["Пилот-1"], ensure_ascii=False))
    store.insert("projects", name="Руппур", theme="erp_rollout", aliases=json.dumps(["Бангладеш"], ensure_ascii=False))
    store.insert("projects", name="Титан", theme="erp_rollout")
    store.insert("projects", name="Старый", theme="erp_rollout", archived=1)
    return project


# --- выключатели ----------------------------------------------------------------------------------------------------

def test_по_умолчанию_выключено_настройка_сильнее_переменной(store, monkeypatch):
    assert not sw.включён(store) and not iz.правило_включено(store)
    monkeypatch.setenv("MEETFLOW_ASR_VOCAB", "1")
    monkeypatch.setenv("MEETFLOW_PROJECT_ONLY_HEARD", "on")
    assert sw.включён(store) and iz.правило_включено(store)
    store.set_setting("rec:asr_vocab", False)               # экран: «выключено» — сильнее переменной
    store.set_setting("rec:project_only_heard", False)
    assert not sw.включён(store) and not iz.правило_включено(store)
    store.set_setting("rec:asr_vocab", None)                # «по переменной»
    assert sw.включён(store)


# --- словарь в подсказке --------------------------------------------------------------------------------------------

def test_словарь_проект_встречи_последним_архивных_нет(store, справочник):
    assert sw.подсказка(store, справочник) == ""                  # выключен — подсказки нет, как было
    store.set_setting("rec:asr_vocab", True)
    сборка = sw.подсказка_сборка(store, справочник)
    assert сборка.текст.startswith("Проекты:") and сборка.текст.rstrip(".").endswith("Пилот")
    assert "Руппур" in сборка.текст and "Титан" in сборка.текст and "Старый" not in сборка.текст
    assert сборка.токенов <= sw.ЛИМИТ_ТОКЕНОВ and сборка.словарь_вошло >= 3
    assert "словарь: вошло" in сборка.журнал() and сборка.meta()["asr_vocab_in"] == сборка.словарь_вошло


def test_прибор_длинный_справочник_не_длиннее_223(store, project):
    """Прибор: двести проектов — подсказка всё равно в пределе Whisper, лишнее отброшено, проект встречи на месте."""
    for i in range(200):
        store.insert("projects", name=f"Объект номер {i} Северо-Западного направления", theme="erp_rollout")
    store.set_setting("rec:asr_vocab", True)
    сборка = sw.подсказка_сборка(store, project)
    assert сборка.токенов <= sw.ЛИМИТ_ТОКЕНОВ and сборка.словарь_отброшено > 0
    assert сборка.текст.rstrip(".").endswith("Пилот")


def test_коннектор_отдаёт_подсказку_whisper_и_сервису(monkeypatch, tmp_path):
    asr = asr_whisper.WhisperLocalASR()
    видели = {}

    class Модель:
        def transcribe(self, path, **kw):
            видели["whisper"] = kw.get("initial_prompt")
            return iter([]), type("I", (), {"duration": 0})()
    asr._run(Модель(), tmp_path / "a.wav")
    assert видели["whisper"] is None                              # без подсказки — поля нет, как было
    asr.initial_prompt = "Проекты: Титан, Пилот."
    asr._run(Модель(), tmp_path / "a.wav")
    assert видели["whisper"] == "Проекты: Титан, Пилот."

    from meetflow.connectors import asr_service

    def call(route, path, **kw):
        видели["service"] = kw.get("initial_prompt")
        return "", {"duration": 1}
    monkeypatch.setattr(asr_service, "call", call)
    asr._run_service_shared("Транс", {"kind": "asr-service", "url": "http://127.0.0.1:9/transcribe"}, tmp_path / "a.wav")
    assert видели["service"] == "Проекты: Титан, Пилот."


class _ASR(ASRConnector):
    name = "fake-asr"

    def __init__(self):
        self.initial_prompt = ""
        self.получено: list[str] = []

    def transcribe(self, path: Path) -> SourceDoc:
        self.получено.append(self.initial_prompt)
        текст = f"00:00:01{Т}Начинаем.{П}00:00:20{Т}По Титану всё по плану."
        meta = {"media_seconds": 30, "segment_lines": ["Начинаем.", "По Титану всё по плану."],
                "segment_times": [[1.0, 3.0], [20.0, 25.0]], "keep_media": True}
        if self.initial_prompt:
            meta["asr_prompt_sent"] = True
        return SourceDoc(path.name, SourceKind.TRANSCRIPT, текст, meta)


@pytest.mark.parametrize("включено", [False, True])
def test_приём_записи_подсказка_и_журнал(make_pipe, store, справочник, meeting, tmp_path, monkeypatch, включено):
    pipe = make_pipe()
    pipe.asr_journal_path = tmp_path / "asr_journal.jsonl"
    if включено:
        store.set_setting("rec:asr_vocab", True)
    asr = _ASR()
    monkeypatch.setattr(pipe.plugins, "resolve_source", lambda name: asr)
    f = tmp_path / "rec 01.10.2026.wav"
    f.write_bytes(b"RIFF")
    r = pipe.ingest(справочник, meeting, f.name, path=f)
    meta = json.loads(store.get("sources", r["source_id"])["meta"])
    row = json.loads(pipe.asr_journal_path.read_text(encoding="utf-8").splitlines()[-1])
    assert asr.initial_prompt == ""                               # снята после записи: коннектор общий
    if not включено:
        assert asr.получено == [""] and "asr_prompt_tokens" not in meta and "prompt_line" not in row
        return
    assert asr.получено[0].startswith("Проекты:") and asr.получено[0].rstrip(".").endswith("Пилот")
    assert 0 < meta["asr_prompt_tokens"] <= 223 and meta["asr_project_vocab"] is True
    assert "из 223 токенов" in row["prompt_line"] and "словарь: вошло" in row["prompt_line"]


# --- проект только при прозвучавшем названии ------------------------------------------------------------------------

ЗАПИСЬ = П.join([f"00:00:01{Т}Начинаем.", f"00:00:20{Т}По Титану поставка идёт по плану, акт подписан.",
                 f"00:00:40{Т}Регламент склада готовим к пятнице."])
ТЕЛО = П.join(["## Ход встречи", "**Титан** – поставка идёт по плану, акт подписан.",
               "**Руппур** – регламент склада готовим к пятнице.", "**Пилот** – регламент склада готовим к пятнице."])


def test_правило_выключено_ничего_не_меняет(store, справочник):
    md, описания, сводка = iz.применить_к_встрече(store, справочник, ТЕЛО, ["Руппур: подготовить регламент"], ЗАПИСЬ)
    assert md == ТЕЛО and описания == ["Руппур: подготовить регламент"] and сводка == {"тело": 0, "задачи": 0}


def test_правило_снимает_непрозвучавший_проект_встречи_не_трогает(store, справочник):
    store.set_setting("rec:project_only_heard", True)
    md, описания, сводка = iz.применить_к_встрече(
        store, справочник, ТЕЛО, ["Руппур: подготовить регламент склада", "Титан: подписать акт поставки",
                                  "Пилот: обновить регламент склада"], ЗАПИСЬ)
    строки = md.split(П)
    assert строки[1].startswith("**Титан**")                      # прозвучал («Титану») — остаётся
    assert строки[2] == f"**{iz.НЕ_ОПРЕДЕЛЁН}** – регламент склада готовим к пятнице."
    assert строки[3].startswith("**Пилот**")                      # проект встречи не снимается
    assert описания == ["подготовить регламент склада", "Титан: подписать акт поставки",
                        "Пилот: обновить регламент склада"]
    assert сводка == {"тело": 1, "задачи": 1}


def test_правило_вариант_проекта_и_искажение_считаются_опорой(store, справочник):
    store.set_setting("rec:project_only_heard", True)
    запись = ЗАПИСЬ + П + f"00:01:00{Т}По Бангладешу регламент склада к пятнице."
    md, _о, сводка = iz.применить_к_встрече(store, справочник, ТЕЛО, [], запись)
    assert "**Руппур**" in md and сводка["тело"] == 0
    md, _о, сводка = iz.применить_к_встрече(store, справочник, ТЕЛО, [],
                                            ЗАПИСЬ + П + f"00:01:00{Т}По Рупуру регламент склада к пятнице.")
    assert "**Руппур**" in md and сводка["тело"] == 0             # искажение распознавания — тоже опора


def test_сборка_зовёт_правило_для_задач_и_тела(make_pipe, store, project, meeting, monkeypatch):
    """Прибор подключения: сборка отдаёт правилу формулировки задач и готовый текст протокола; без выключателя — как было."""
    from conftest import TRANSCRIPT
    вызовы = []
    настоящее = iz.применить_к_встрече

    def шпион(store_, pid, md, описания, текст):
        вызовы.append((pid, bool(md), len(описания), bool(текст)))
        return настоящее(store_, pid, md, описания, текст)
    monkeypatch.setattr(iz, "применить_к_встрече", шпион)
    pipe = make_pipe()
    assert pipe.ingest(project, meeting, "Транскрибация.txt", data=TRANSCRIPT.encode("utf-8"))["status"] == "ok"
    pipe.run(project, meeting)
    assert any(md is False and n > 0 for _p, md, n, _t in вызовы)          # задачи
    assert any(md is True and n == 0 and т for _p, md, n, т in вызовы)    # тело протокола
    assert all(p == project for p, *_ in вызовы)
