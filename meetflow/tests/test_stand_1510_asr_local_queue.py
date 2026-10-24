"""Распознавание — единообразно с ERP (уточнение владельца к п. 1, 15.10.26, через «Мониторинг»): только локально;
три типа подключения роли asr; без назначения — «не настроено», запись ждёт; очередь распознавания с арендой —
одна запись за раз на машину, общая с ERP и Планёркой (recognition_lease.py байт в байт); «процесс жив» — по коду
выхода (находка стенда 48); сервис распознавания — общим кодом, обе формы запроса. Тесты написаны до правки и падали."""
import hashlib
import io
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from meetflow.connectors import llm_routes as lr
from meetflow.connectors.asr_whisper import WhisperLocalASR, asr_ping
from meetflow.connectors.base import ConnectorError
from meetflow.connectors.shared import recognition_lease

SHARED = Path(lr.__file__).parent / "shared"


def test_lease_module_is_a_byte_copy():
    assert hashlib.md5((SHARED / "recognition_lease.py").read_bytes()).hexdigest().startswith("7f9595227e4f")


class Seg:
    start, text = 1, "Петрова Анастасия, подготовьте регламент склада"


def _asr(monkeypatch):
    asr = WhisperLocalASR()
    model = type("M", (), {"transcribe": lambda *a, **k: ([Seg()], type("I", (), {"duration": 1800})())})()
    monkeypatch.setattr(asr, "_load_point", lambda *a: model)
    return asr


def test_other_product_holds_the_machine_recording_waits(asr_route, tmp_path, monkeypatch):
    lease = Path(os.environ["RECOGNITION_LEASE_PATH"])
    now = datetime.now().isoformat(timespec="seconds")
    lease.write_text(json.dumps({"holder": "planerka", "job": "планёрка 15.10", "since": now, "ts": now,
                                 "pid": os.getpid()}), encoding="utf-8")
    f = tmp_path / "rec 01.10.2026.mp4"
    f.write_bytes(b"x")
    with pytest.raises(ConnectorError, match="waiting_tools: очередь распознавания на машине — сейчас распознаёт Планёркой"):
        _asr(monkeypatch).transcribe(f)
    assert f.exists(), "запись ждёт на месте"


def test_free_machine_takes_lease_and_releases(asr_route, tmp_path, monkeypatch):
    f = tmp_path / "rec 01.10.2026.mp4"
    f.write_bytes(b"x")
    seen = []
    real = recognition_lease.взять
    monkeypatch.setattr(recognition_lease, "взять", lambda *a, **k: (seen.append(a[0]), real(*a, **k))[1])
    doc = _asr(monkeypatch).transcribe(f)
    assert "регламент" in doc.text and seen == ["meetflow"]
    assert not json.loads(Path(os.environ["RECOGNITION_LEASE_PATH"]).read_text(encoding="utf-8")).get("holder")


def test_dead_process_lease_is_released_at_start(tmp_path, monkeypatch):
    lease = tmp_path / "recognition_lease.json"
    monkeypatch.setenv("RECOGNITION_LEASE_PATH", str(lease))
    lease.write_text(json.dumps({"holder": "meetflow", "job": "старая запись", "pid": 999999,
                                 "ts": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    assert not json.loads(lease.read_text(encoding="utf-8")).get("holder")
    assert app.state.store.q("SELECT * FROM cards WHERE title='Очередь распознавания: снята брошенная аренда'")


def test_process_alive_by_exit_code():
    """Строка 48: жив — только код выхода STILL_ACTIVE, а не успешный OpenProcess."""
    assert recognition_lease._процесс_жив(os.getpid())
    assert not recognition_lease._процесс_жив(999999)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_asr_service_multipart_and_lines(asr_route, tmp_path, monkeypatch):
    asr_route.write_text(json.dumps({"endpoints": {"svc": {"kind": "asr-service", "url": "http://192.168.1.10:9000/transcribe",
                                                           "form": "multipart"}}, "roles": {"asr": ["svc"]}}),
                         encoding="utf-8")
    sent = {}

    def fake(req, timeout=None):
        sent["ct"], sent["body"] = req.headers.get("Content-type"), req.data
        return _Resp(json.dumps({"segments": [{"start": 61, "text": "Петрова, подготовьте регламент"}],
                                 "duration": 1800}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    f = tmp_path / "rec 01.10.2026.wav"
    f.write_bytes(b"RIFF....WAVE")
    doc = WhisperLocalASR().transcribe(f)
    assert sent["ct"].startswith("multipart/form-data") and b'name="file"' in sent["body"]
    assert "[00:01:01] Петрова, подготовьте регламент" in doc.text and doc.meta["route"] == "svc"


def test_asr_service_check_posts_silence_not_get(monkeypatch):
    seen = {}

    def fake(req, timeout=None):
        seen["method"], seen["data"] = req.get_method(), req.data
        return _Resp(json.dumps({"text": ""}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ok, detail = asr_ping({"kind": "asr-service", "url": "http://192.168.1.10:9000/transcribe"})
    assert seen["method"] == "POST" and seen["data"][:4] == b"RIFF" and ok
