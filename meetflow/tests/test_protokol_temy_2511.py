# -*- coding: utf-8 -*-
"""E5 (25.11.2026), план «темы, объём, покрытие»: MeetFlow — транспорт и факты.

1. Потолок ответа: шаг протокола/генерации — общий `model_routes.step_ceiling` (48 000), транспортное умолчание
   4096 объём не режет; точка главнее. Блок ветки B (think/num_ctx для ollama) не тронут.
2. Конструктор блока темы в подсказке: слоты, ориентир 3–6 предложений / 300–600 знаков, переполнение → подтемы;
   признаки прежней формы для тестов сохранены.
3. `fakty_protokola` — близнец Планёрки байт-в-байт; потерянные факты → карточка fact_loss и строка в build_note;
   сбой сверки сохранение не роняет. Сети нет: ответы поставщика подставлены, заглушка модели — MockLLM.
"""
from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path

import pytest

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.shared import model_routes as mr
from meetflow.core import fakty_protokola as фп
from meetflow.core.prompts import PromptBuilder, profile

ЗАПИСЬ_С_ФАКТАМИ = (
    "[00:00:10] Игнатов Иван: Добрый день, начинаем.\n"
    "[00:01:00] Петрова Анастасия: На посуду выделяем 32 млн рублей, предоплата 70%.\n"
    "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада до 10.10\n"
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _точка(род: str = "openai", модель: str = "deepseek-flash", **поля) -> lr.PointLLM:
    ep = {"kind": род, "model": модель, **поля}
    if род == "openai":
        ep.setdefault("url", "https://api.deepseek.com")
    elif род == "ollama":
        ep.setdefault("url", "http://127.0.0.1:11434")
    return lr.PointLLM("p", ep)


# --- 1. потолок ответа ------------------------------------------------------------------------------------------------

def test_потолок_протокола_48000():
    assert mr.GENERATE_MAX_TOKENS_CEILING == 48000
    p = _точка()                                   # у точки нет max_tokens — прежде транспорт резал до 4096
    assert p.ceiling_for("protocol") == 48000 and p.ceiling_for("generate") == 48000
    assert p._тело_шага("s", "u", True, 0.0, "protocol")["max_tokens"] == 48000


def test_прочие_шаги_прежний_потолок():
    p = _точка()
    for шаг in ("extract_tasks", "verify", "units", ""):
        assert p.ceiling_for(шаг) == 4096
        assert p._тело_шага("s", "u", True, 0.0, шаг)["max_tokens"] == 4096


def test_точка_главнее_и_может_опустить():
    assert _точка(max_tokens=8000).ceiling_for("protocol") == 8000      # точка ниже потолка — она главнее
    assert _точка(max_tokens=96000).ceiling_for("protocol") == 48000    # точка выше — потолок шага режет до 48000
    assert _точка(max_tokens=96000)._тело_шага("s", "u", True, 0.0, "protocol")["max_tokens"] == 48000


def test_переменная_шага_меняет_потолок(monkeypatch):
    monkeypatch.setenv("LLM_GENERATE_MAX_TOKENS_CEILING", "20000")
    assert _точка().ceiling_for("protocol") == 20000
    monkeypatch.setenv("LLM_GENERATE_MAX_TOKENS_CEILING", "0")          # 0 — без потолка поверх базы шага
    assert _точка().ceiling_for("protocol") == 48000


def test_ollama_потолок_и_блок_B_цел():
    """Потолок шага доходит до num_predict, а think/num_ctx ветки B не меняются."""
    qwen = _точка("ollama", "qwen3.8:latest")
    b = qwen._тело_шага("s", "u", True, 0.0, "protocol")
    assert b["options"]["num_predict"] == 48000 and b["think"] is False and b["options"]["num_ctx"] == 131072
    assert qwen._тело_шага("s", "u", True, 0.0, "extract_tasks")["options"]["num_predict"] == 4096
    прочая = _точка("ollama", "llama3")                                # у прочих локальных окно прежние 32 768
    assert прочая._тело_шага("s", "u", True, 0.0, "protocol")["options"]["num_ctx"] == 32768


def test_вызов_несёт_потолок_протокола(monkeypatch):
    запросы: list[dict] = []

    def urlopen(req, *a, **k):
        запросы.append(json.loads(req.data.decode("utf-8")))
        return _Resp(json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 3}}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    _точка().complete("s", "u", purpose="protocol")
    assert запросы[-1]["max_tokens"] == 48000


# --- 2. конструктор блока темы ----------------------------------------------------------------------------------------

def test_конструктор_темы_в_подсказке():
    pb = PromptBuilder("секретарь", profile("generic"))
    system, _ = pb.protocol(["Обсуждение"], "запись")
    for признак in ("конструктор", "тема одной фразой", "факт с цифрами", "финальной редакции",
                    "исполнитель", "срок", "таймкод", "3–6", "300–600", "подтемы"):
        assert признак in system, f"слот/ориентир конструктора отсутствует: {признак}"
    assert "кратко изложи обсуждение" not in system                    # прежняя квота убрана
    # признаки прежней формы — для существующих тестов (test_tekst_i_tablica_2710)
    assert "«**Предмет:** суть»" in system and "не длиннее 400 знаков" in system


# --- 3. факты: близнец, сверка, карточка ------------------------------------------------------------------------------

def test_факты_считаются_и_теряются():
    источник = "На посуду выделяем 32 млн рублей, предоплата 70%."
    ключи = {ф["ключ"] for ф in фп.факты(источник)}
    assert "32000000 RUB" in ключи and "70%" in ключи
    assert len(фп.потерянные(источник, "Обсуждение не зафиксировано.")) == 2
    assert фп.потерянные(источник, "Выделяем 32 млн рублей, предоплата 70%.") == []


def test_близнец_байт_в_байт():
    here = Path(__file__).resolve()
    источник = here.parents[3] / "Planerka" / "planerka" / "webapp" / "app" / "services" / "fakty_protokola.py"
    близнец = here.parents[1] / "meetflow" / "core" / "fakty_protokola.py"
    if not источник.is_file():
        pytest.skip("нет первоисточника Планёрки на этом диске")
    assert близнец.read_bytes() == источник.read_bytes()


def _сборка_с_фактами(make_pipe, store, project, monkeypatch=None):
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe()
    p.ingest(project, mid, "t 01.10.2026.txt", ЗАПИСЬ_С_ФАКТАМИ.encode())
    rep = p.run(project, mid)
    return p, mid, rep


def test_потерянные_факты_карточка_и_строка(make_pipe, store, project):
    p, mid, rep = _сборка_с_фактами(make_pipe, store, project)
    assert rep.protocol_saved is True
    assert "32 млн рублей" in rep.fact_loss and "70%" in rep.fact_loss   # в timings версии
    карточки = store.q("SELECT kind, title, payload FROM cards WHERE meeting_id=? AND kind='fact_loss'", (mid,))
    assert len(карточки) == 1 and "не вошли факты" in карточки[0]["title"]
    данные = json.loads(карточки[0]["payload"])
    assert данные["потеряно"] == 2
    примечание = store.get("meetings", mid)["build_note"] or ""
    assert "не вошли факты" in примечание and "32 млн рублей" in примечание


def test_сбой_сверки_не_роняет_сохранение(make_pipe, store, project, monkeypatch):
    def _сбой(*a, **k):
        raise RuntimeError("сверка сломалась")
    monkeypatch.setattr(фп, "потерянные", _сбой)
    p, mid, rep = _сборка_с_фактами(make_pipe, store, project)
    assert rep.protocol_saved is True                                  # протокол сохранён несмотря на сбой сверки
    assert store.q("SELECT COUNT(*) AS n FROM cards WHERE meeting_id=? AND kind='fact_loss'", (mid,))[0]["n"] == 0
    тех = store.q("SELECT title FROM cards WHERE meeting_id=? AND kind='technical'", (mid,))
    assert any("Сверка фактов" in r["title"] for r in тех)