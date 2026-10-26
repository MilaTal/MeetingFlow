# -*- coding: utf-8 -*-
"""«Транс»: подсказка не в строке запроса, формат звука точки (перенос из ERP 27.10.2026; DECISIONS ERP 26.10.2026,
«Транс: подсказка не в строке запроса, формат звука; петли распознавания»).

Свой вызов MeetFlow (`connectors/asr_service.py`, ЛМ) сохраняет сегменты и времена строк; поверх — правила общего
клиента ERP: у формы raw с подсказкой запрос уходит multipart (подсказка полем формы под прежним именем), без подсказки
raw — как раньше; `prompt_in=query` — прежний путь; `audio` — формат звука, что ушло — в сводке. Сети нет.
"""
import json
import urllib.parse
from pathlib import Path

from meetflow.connectors import asr_service
from meetflow.connectors.shared import model_routes as mr

ОТВЕТ = {"segments": [{"start": 1.5, "end": 4.25, "text": "первая"}, {"start": 5.0, "end": 7.5, "text": "вторая"}],
         "duration": 8}


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(ОТВЕТ).encode("utf-8")


def _route(**opts):
    class Route:
        name = "Транс"
        url = "http://192.168.100.224:8021/transcribe"

        def opt(self, key, default=None):
            return {"timeout_sec": 5, **opts}.get(key, default)
    return Route()


def _ловушка(monkeypatch):
    sent = []

    def fake(req, timeout=None):
        sent.append({"url": req.full_url, "ct": req.headers.get("Content-type"), "body": req.data})
        return _Resp()
    monkeypatch.setattr(asr_service.urllib.request, "urlopen", fake)
    return sent


def _wav(tmp_path) -> Path:
    f = tmp_path / "rec.wav"
    f.write_bytes(b"RIFF....WAVEdata")
    return f


def test_raw_с_подсказкой_уходит_формой(monkeypatch, tmp_path):
    sent = _ловушка(monkeypatch)
    text, meta = asr_service.call(_route(), _wav(tmp_path), initial_prompt="Курск, Титан, бетон " * 20)
    q = sent[-1]
    assert urllib.parse.urlparse(q["url"]).query == "", "в строке запроса ничего"
    assert q["ct"].startswith("multipart/form-data")
    assert b'name="initial_prompt"' in q["body"] and "Титан".encode("utf-8") in q["body"]
    assert b'name="file"' in q["body"] and b"RIFF" in q["body"]
    assert meta["prompt_sent"] == "поле формы" and meta["audio_sent"] == "wav"
    assert meta["segment_times"] == [[1.5, 4.25], [5.0, 7.5]] and meta["segment_lines"] == ["первая", "вторая"]


def test_raw_без_подсказки_как_раньше(monkeypatch, tmp_path):
    sent = _ловушка(monkeypatch)
    asr_service.call(_route(), _wav(tmp_path))
    q = sent[-1]
    assert q["ct"] == "audio/wav" and q["body"] == b"RIFF....WAVEdata"
    assert urllib.parse.parse_qs(urllib.parse.urlparse(q["url"]).query) == {"language": ["ru"]}


def test_prompt_in_query_прежний_путь(monkeypatch, tmp_path):
    sent = _ловушка(monkeypatch)
    _, meta = asr_service.call(_route(prompt_in="query"), _wav(tmp_path), initial_prompt="Титан")
    assert "initial_prompt" in urllib.parse.parse_qs(urllib.parse.urlparse(sent[-1]["url"]).query)
    assert meta["prompt_sent"] == "строка запроса"


def test_формат_звука_m4a(monkeypatch, tmp_path):
    sent = _ловушка(monkeypatch)
    monkeypatch.setattr(mr, "_звук_для_сервиса", lambda p, f: (b"M4A-DATA", "rec.m4a", "audio/mp4", "m4a"))
    _, meta = asr_service.call(_route(form="multipart"), _wav(tmp_path), initial_prompt="Титан")
    q = sent[-1]
    assert b"Content-Type: audio/mp4" in q["body"] and b'filename="rec.m4a"' in q["body"] and b"M4A-DATA" in q["body"]
    assert meta["audio_sent"] == "m4a" and meta["audio_bytes"] == 8 and meta["prompt_sent"] == "поле формы"
