# -*- coding: utf-8 -*-
"""Прод-контроль Whisper на сервисной точке (26.11.2026, слово владелицы).

Контроль — вторая расшифровка той же записи на сервисной точке whisper-large-v3 из цепочки asr (как Планёрка
и ERP), а не на местном faster-whisper. Проверяется: контроль идёт на 100 % записей, если точка доступна;
недоступна/в охлаждении/основная уже whisper — пропуск БЕЗ сброса и без карточки-вопроса; сбой сервиса не
роняет основную сборку; текст контроля пригоден для сверки; расхождение Транс/Whisper — флаг с обоими
значениями, не перезапись суммы основной.
"""
import json
import types
from pathlib import Path

import pytest

from meetflow.connectors.shared import model_routes as mr


def _routes(tmp_path, monkeypatch, whisper=True, cooldown=False):
    endpoints = {"Транс": {"kind": "asr-service", "url": "http://192.168.100.224:8021/transcribe",
                            "form": "multipart"}}
    asr = ["Транс"]
    if whisper:
        endpoints["whisper-large-v3"] = {
            "kind": "asr-service", "url": "http://192.168.100.30:8001/v1/audio/transcriptions",
            "form": "multipart", "extra_fields": {"model": "whisper-large-v3", "response_format": "verbose_json"},
            "timeout_sec": 900, "chunk_seconds": "600", "max_mb": "25"}
        asr.append("whisper-large-v3")
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": endpoints, "roles": {"asr": asr}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setattr(mr._state, "down_until", {})
    monkeypatch.setattr(mr._state, "last_error", {})
    if cooldown:
        import time
        mr._state.down_until["whisper-large-v3"] = time.time() + 300
    return path


def _запись(tmp_path):
    p = tmp_path / "встреча.wav"
    p.write_bytes(b"\x00\x01\x02")
    return p


def _основной(route="Транс"):
    return types.SimpleNamespace(last_route=route)


def test_control_runs_via_service_point(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch)
    calls = []

    def fake_callable(route):
        def run(wav_path, **params):
            calls.append(route.name)
            return "00:35:26\tСумма контракта по проекту составляет 30,65 млн рублей", {"model": route.name}
        return run
    monkeypatch.setattr(mr, "asr_callable", fake_callable)
    pipe = make_pipe()
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav", _основной())
    assert sid > 0 and calls == ["whisper-large-v3"]
    src = store.q("SELECT name, text FROM sources WHERE id=?", (sid,))[0]
    assert "контрольная Whisper" in src["name"]
    # формат пригоден для сверки: скобки + обезличенный говорящий, текст речи сохранён
    assert "[00:35:26] Говорящий 1:" in src["text"] and "30,65 млн" in src["text"]


def test_control_skipped_without_whisper_point(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch, whisper=False)
    pipe = make_pipe()
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav", _основной())
    assert sid == 0
    assert not store.q("SELECT id FROM sources WHERE name LIKE '%контрольная Whisper%'")


def test_control_skipped_when_point_in_cooldown(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch, cooldown=True)
    pipe = make_pipe()
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav", _основной())
    assert sid == 0


def test_control_skipped_when_main_already_whisper(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch)
    pipe = make_pipe()
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav",
                                        _основной("whisper-large-v3"))
    assert sid == 0


def test_control_failure_does_not_break_main(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch)

    def fake_callable(route):
        def run(wav_path, **params):
            raise RuntimeError("сервис не отвечает")
        return run
    monkeypatch.setattr(mr, "asr_callable", fake_callable)
    pipe = make_pipe()
    # сбой контроля не пробрасывается: основная сборка идёт дальше
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav", _основной())
    assert sid == 0
    assert not store.q("SELECT id FROM sources WHERE name LIKE '%контрольная Whisper%'")


def test_control_disabled_by_env(make_pipe, store, project, meeting, tmp_path, monkeypatch):
    _routes(tmp_path, monkeypatch)
    monkeypatch.setenv("WEBAPP_CONTROL_TRANSCRIPT", "0")
    pipe = make_pipe()
    sid = pipe._контрольная_расшифровка(project, meeting, _запись(tmp_path), "встреча.wav", _основной())
    assert sid == 0


def test_discrepancy_flag_not_overwrite():
    """КП I9x_ZsFL: истина Транса 365 млн, Whisper ослышался (30,65). Сверка помечает оба значения,
    сумму основной не перезаписывает."""
    from meetflow.core.pipeline import контроль_расшифровки
    base = {"name": "своя (распознано локально).txt", "local_asr": 1,
            "text": "[00:35:26] Виктор Сидоров: Сумма контракта по проекту составляет 365 млн рублей"}
    control = {"name": "встреча — контрольная Whisper.txt", "local_asr": 0,
               "text": "[00:35:26] Говорящий 1: Сумма контракта по проекту составляет 30,65 млн рублей"}
    было = base["text"]
    итог = контроль_расшифровки([base, control], base)
    assert итог["есть"] is True
    assert "365 млн" in base["text"] and base["text"] == было, "сумма основной не перезаписана"
    assert "30,65" in итог["блок"] and "365" in итог["блок"]
    assert "молча не выбирать" in итог["блок"]