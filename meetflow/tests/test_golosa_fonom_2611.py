# -*- coding: utf-8 -*-
"""Голоса фоном ДЛЯ ВСЕХ записей — 5 независимых проверок (26.11.2026, решение владелицы №7).

Каждая проверка — отдельный независимый сценарий in-process через `create_app` на СВОЕЙ копии базы (временный файл,
живой сервер и рабочая база не трогаются). Тяжёлые шаги заменены заглушками: точка распознавания отдаёт готовый текст
с временами реплик, шаг голосов (`voice_step.process`) подписывает строки без настоящей диаризации. Проверяется поток:

  P1 — приёмник принимает файл и ставит голоса в очередь «потом», НЕ блокируясь (проход быстрый, диаризация не зовётся);
  P2 — протокол появляется БЕЗ говорящих сразу (пока голоса ещё ждут);
  P3 — после диаризации протокол пересобирается С именами;
  P4 — деградация: нет модели/сбой → протокол без говорящих сохранён, карточка, без сброса;
  P5 — перезапуск: осиротевшие «ожидают голоса» возвращаются в очередь и досчитываются.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.base import ASRConnector
from meetflow.core import hod
from meetflow.core import pipeline as pl
from meetflow.core.golosa_ochered import СОСТОЯНИЕ_ЖДЁТ
from meetflow.core.types import SourceDoc, SourceKind
from meetflow.web.app import create_app

КОМАНДА = ["Игнатов Иван", "Петрова Анастасия", "Сидоров Пётр"]
# Расшифровка без подписей говорящих (как отдаёт точка распознавания): таймкод + текст реплики.
ТЕКСТ = ("00:00:01\tОбсудили сроки поставки профиля\n"
         "00:00:05\tИгнатов Иван, подготовьте регламент склада до 10.10")
РЕПЛИКИ = ["Обсудили сроки поставки профиля", "Игнатов Иван, подготовьте регламент склада до 10.10"]
ВРЕМЕНА = [[1, 4], [5, 9]]
# Подписанный вариант (как возвращает шаг голосов): «[метка] имя: текст».
ПОДПИСАННЫЙ = ("[00:00:01] [Говорящий 1] Игнатов Иван: Обсудили сроки поставки профиля\n"
               "[00:00:05] [Говорящий 1] Игнатов Иван: подготовьте регламент склада до 10.10")


class _ПробнаяASR(ASRConnector):
    """Точка распознавания-заглушка: готовый текст с временами реплик, без вызова настоящей модели."""

    name = "пробная"

    def transcribe(self, path: Path) -> SourceDoc:
        return SourceDoc("проба (распознано локально).txt", SourceKind.TRANSCRIPT, ТЕКСТ,
                         {"route": "пробная", "model": "пробная", "media_seconds": 120,
                          "segment_lines": РЕПЛИКИ, "segment_times": ВРЕМЕНА,
                          "media_path": str(path), "keep_media": True})


def _подписать(wav_path, text, meta, **kw):
    return {"text": ПОДПИСАННЫЙ, "speakers": 1, "signed_lines": 2,
            "names": {"Говорящий 1": "Игнатов Иван"}, "identified": {}, "base": {},
            "contribution": {}, "clips": 0, "notes": [],
            "diarization": {"seconds": 1, "device": "cpu", "path": "проба"}}


def _ждать(проверка, таймаут: float = 30.0, шаг: float = 0.05) -> bool:
    конец = time.monotonic() + таймаут
    while time.monotonic() < конец:
        if проверка():
            return True
        time.sleep(шаг)
    return False


def _приложение(tmp_path, monkeypatch, имя="t.db"):
    """Своя копия базы + заглушка распознавания для аудио. Живой сервер не поднимается (watch=False)."""
    app = create_app("erp_rollout", str(tmp_path / имя), str(tmp_path / "j.jsonl"), watch=False)
    store = app.state.store
    pid = store.insert("projects", name="Пилот", theme="erp_rollout")
    for n in КОМАНДА:
        store.insert("people", project_id=pid, full_name=n)
    monkeypatch.setattr(app.state.pipe.plugins, "resolve_source",
                        lambda name: _ПробнаяASR() if name.lower().endswith((".m4a", ".wav", ".mp3")) else None)
    return app, store, pid


def _источник_ждёт(store, tmp_path, mid, имя="запись.wav"):
    запись = tmp_path / имя
    запись.write_bytes(b"RIFF" + b"\x00" * 4096)
    sid = store.insert("sources", meeting_id=mid, name="запись (распознано локально).txt", kind="transcript",
                       text=ТЕКСТ, created_at="2026-11-26T15:00:00", local_asr=1, voice_state=СОСТОЯНИЕ_ЖДЁТ,
                       meta=json.dumps({"media_path": str(запись), "segment_lines": РЕПЛИКИ,
                                        "segment_times": ВРЕМЕНА, "media_seconds": 120,
                                        "keep_media": True, "voices_deferred": True}, ensure_ascii=False))
    return sid, запись


def _протокол_без_голосов(store, queue, pid, mid):
    queue.enqueue(pid, mid, "проверка: протокол без голосов")
    assert _ждать(lambda: bool((store.get("meetings", mid) or {}).get("protocol_md"))), "протокол не собрался"


# ---------------------------------------------------------------- P1: приёмник не блокируется
def test_p1_приёмник_ставит_голоса_в_очередь_не_блокируясь(tmp_path, monkeypatch):
    app, store, pid = _приложение(tmp_path, monkeypatch)
    вызовы = {"n": 0}

    def _не_зовём(wav_path, text, meta, **kw):
        вызовы["n"] += 1
        raise AssertionError("диаризация не должна вызываться внутри прохода приёмника")

    monkeypatch.setattr(pl.voice_step, "process", _не_зовём)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "Встреча 26.11.2026 10-00.m4a").write_bytes(b"RIFF" + b"\x00" * 8192)
    store.set_setting("watch_folder", str(inbox), pid, "тест")
    store.set_setting("autorun", True, pid, "тест")
    intake = app.state.intake
    intake.scan_project(pid)                       # первый проход: файл «не осел»
    старт = time.monotonic()
    итог = intake.scan_project(pid)                # второй: принимаем
    elapsed = time.monotonic() - старт
    assert итог.get("status") == "ok", итог
    assert "Встреча 26.11.2026 10-00.m4a" in итог.get("ingested", []), итог
    assert elapsed < 10.0, f"проход заблокировался на {elapsed:.1f} с"
    assert вызовы["n"] == 0, "голоса считались внутри прохода"
    assert (inbox / "обработано" / "Встреча 26.11.2026 10-00.m4a").is_file()   # исходник уехал сразу
    строка = store.q("SELECT * FROM sources WHERE meeting_id IN (SELECT id FROM meetings WHERE project_id=?)",
                     (pid,))
    assert len(строка) == 1 and строка[0]["voice_state"] == СОСТОЯНИЕ_ЖДЁТ, строка
    meta = json.loads(строка[0]["meta"] or "{}")
    assert Path(meta["media_path"]).is_file(), "рабочая копия должна остаться для шага голосов"
    assert app.state.golosa.ожидают() == 1


# ---------------------------------------------------------------- P2: протокол без говорящих сразу
def test_p2_протокол_без_говорящих_сразу(tmp_path, monkeypatch):
    app, store, pid = _приложение(tmp_path, monkeypatch)
    monkeypatch.setattr(pl.voice_step, "process", _подписать)   # голоса ещё НЕ разбираем
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "Встреча 26.11.2026 10-00.m4a").write_bytes(b"RIFF" + b"\x00" * 8192)
    store.set_setting("watch_folder", str(inbox), pid, "тест")
    store.set_setting("autorun", True, pid, "тест")
    app.state.intake.scan_project(pid)
    app.state.intake.scan_project(pid)
    mid = store.q("SELECT id FROM meetings WHERE project_id=?", (pid,))[0]["id"]
    assert _ждать(lambda: bool((store.get("meetings", mid) or {}).get("protocol_md"))), "протокол не появился"
    строка = store.q("SELECT * FROM sources WHERE meeting_id=?", (mid,))[0]
    assert строка["voice_state"] == СОСТОЯНИЕ_ЖДЁТ, "голоса ещё ждут — протокол собран без них"
    assert "[Говорящий" not in (строка["text"] or ""), "в расшифровке не должно быть подписей говорящих"
    протокол = store.get("meetings", mid)["protocol_md"]
    assert протокол and "[Говорящий" not in протокол
    # протокол собран, пока голоса ждут: примечание «уточняются» — прямой признак сборки без говорящих
    assert "уточняются: идёт разбор записи по голосам" in протокол


# ---------------------------------------------------------------- P3: пересборка с именами после диаризации
def test_p3_после_диаризации_протокол_с_именами(tmp_path, monkeypatch):
    app, store, pid = _приложение(tmp_path, monkeypatch)
    mid = store.insert("meetings", project_id=pid, date="2026-11-26", label="Проверка голосов")
    sid, запись = _источник_ждёт(store, tmp_path, mid)
    _протокол_без_голосов(store, app.state.queue, pid, mid)
    было = store.get("meetings", mid)["protocol_md"]
    assert "[Говорящий" not in было
    monkeypatch.setattr(pl.voice_step, "process", _подписать)
    строка = store.q("SELECT * FROM sources WHERE id=?", (sid,))[0]
    app.state.golosa._разобрать(строка)            # второй этап: диаризация (заглушка подписывает)
    после = store.get("sources", sid)
    assert после["voice_state"] == "готово", после["voice_state"]
    assert "Игнатов Иван" in после["text"] and "[Говорящий 1]" in после["text"]
    assert not запись.exists(), "запись убирается после удачного разбора"
    # пересборка с именами — очередью сборок
    assert _ждать(lambda: any(r["status"] == "done" and "голоса разобраны" in (r["reason"] or "")
                              for r in store.q("SELECT * FROM build_queue WHERE meeting_id=?", (mid,)))), \
        "пересборка после голосов не выполнена"
    протокол = store.get("meetings", mid)["protocol_md"]
    assert протокол != было and "Игнатов Иван" in протокол, "протокол должен пересобраться с именами"


# ---------------------------------------------------------------- P4: деградация без сброса
def test_p4_деградация_протокол_без_говорящих_сохранён(tmp_path, monkeypatch):
    app, store, pid = _приложение(tmp_path, monkeypatch)
    mid = store.insert("meetings", project_id=pid, date="2026-11-26", label="Проверка деградации")
    sid, запись = _источник_ждёт(store, tmp_path, mid)
    _протокол_без_голосов(store, app.state.queue, pid, mid)
    было = store.get("meetings", mid)["protocol_md"]

    def _нет_модели(wav_path, text, meta, **kw):
        raise pl.voice_step.VoiceStepError("разделение по голосам недоступно: нет модели")

    monkeypatch.setattr(pl.voice_step, "process", _нет_модели)
    app.state.golosa._разобрать(store.q("SELECT * FROM sources WHERE id=?", (sid,))[0])
    после = store.get("sources", sid)
    assert после["voice_state"].startswith("сбой"), после["voice_state"]
    assert после["text"] == ТЕКСТ, "расшифровка без говорящих должна остаться"
    assert запись.exists(), "запись сохраняется для повтора"
    assert store.get("meetings", mid)["protocol_md"] == было, "протокол не сбрасывается"
    assert not store.q("SELECT id FROM build_queue WHERE meeting_id=? AND reason LIKE 'голоса разобраны%'", (mid,)), \
        "пересборки нет — нечего подписывать"
    assert store.q("SELECT id FROM cards WHERE kind='technical' AND meeting_id=? AND status='open'", (mid,)), \
        "деградация видна человеку карточкой"


# ---------------------------------------------------------------- P5: перезапуск, осиротевшие голоса
def test_p5_перезапуск_осиротевшие_голоса_досчитываются(tmp_path, monkeypatch):
    db = str(tmp_path / "restart.db")
    # Первый запуск: проход убит на шаге голосов — источник остался «ожидают голоса» (не «ждут (потом)»).
    app1 = create_app("erp_rollout", db, str(tmp_path / "j1.jsonl"), watch=False)
    store1 = app1.state.store
    pid = store1.insert("projects", name="Пилот", theme="erp_rollout")
    for n in КОМАНДА:
        store1.insert("people", project_id=pid, full_name=n)
    mid = store1.insert("meetings", project_id=pid, date="2026-11-26", label="Проверка перезапуска")
    запись = tmp_path / "запись.wav"
    запись.write_bytes(b"RIFF" + b"\x00" * 4096)
    sid = store1.insert("sources", meeting_id=mid, name="запись (распознано локально).txt", kind="transcript",
                        text=ТЕКСТ, created_at="2026-11-26T15:00:00", local_asr=1, voice_state="ожидают голоса",
                        meta=json.dumps({"media_path": str(запись), "segment_lines": РЕПЛИКИ,
                                         "segment_times": ВРЕМЕНА, "media_seconds": 120}, ensure_ascii=False))
    app1.state.queue.enqueue(pid, mid, "протокол без голосов")
    assert _ждать(lambda: bool((store1.get("meetings", mid) or {}).get("protocol_md")))
    assert store1.get("sources", sid)["voice_state"] == "ожидают голоса"
    # «сервер остановлен»: первый экземпляр больше не работает
    del app1

    # Второй запуск на той же базе: сторож детей — в свою папку (чужие процессы не трогаем), голоса подписывают.
    monkeypatch.setattr(hod, "ФАЙЛ_ДЕТЕЙ", tmp_path / "child_pids.json")
    monkeypatch.setattr(pl.voice_step, "process", _подписать)
    app2 = create_app("erp_rollout", db, str(tmp_path / "j2.jsonl"), watch=True)
    app2.state.golosa.pause = 0.2        # частый опрос очереди — чтобы увидеть подбор осиротевших сразу, не ждать 60 с
    with TestClient(app2):
        store2 = app2.state.store
        # осиротевшие «ожидают голоса» возвращены в очередь «потом» и досчитаны фоном
        assert _ждать(lambda: store2.get("sources", sid)["voice_state"] == "готово", таймаут=30), \
            f"осиротевшие голоса не досчитаны: {store2.get('sources', sid)['voice_state']}"
        assert "Игнатов Иван" in store2.get("sources", sid)["text"]
        assert _ждать(lambda: any(r["status"] == "done" and "голоса разобраны" in (r["reason"] or "")
                                  for r in store2.q("SELECT * FROM build_queue WHERE meeting_id=?", (mid,)))), \
            "пересборка с именами после перезапуска не выполнена"
        assert "Игнатов Иван" in store2.get("meetings", mid)["protocol_md"]


# ---------------------------------------------------------------- выключатель и порог
def test_выключатель_голоса_фоном(tmp_path, monkeypatch):
    from meetflow.core.intake import голоса_фоном
    from meetflow.core.store import Store
    s = Store(":memory:")
    pid = s.insert("projects", name="П", theme="erp_rollout")
    assert голоса_фоном(s, pid) is True                       # по умолчанию фон включён
    monkeypatch.setenv("MEETFLOW_VOICES_BACKGROUND", "off")
    assert голоса_фоном(s, pid) is False                      # переменная выключает
    monkeypatch.delenv("MEETFLOW_VOICES_BACKGROUND")
    s.set_setting("voices_background", False, pid, "тест")
    assert голоса_фоном(s, pid) is False                      # проектная настройка выключает
    s.set_setting("voices_background", True, pid, "тест")
    assert голоса_фоном(s, pid) is True
    s.close()


def test_порог_голоса_потом_ноль():
    from meetflow.core import peregovorka
    assert peregovorka.ПОРОГ_ГОЛОСА_ПОТОМ_МИН == 0            # фон для всех записей переговорки