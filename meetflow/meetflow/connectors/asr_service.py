# -*- coding: utf-8 -*-
"""Вызов сервиса распознавания во внутренней сети — с временами реплик.

Зачем свой вызов, а не общий `model_routes._asr_service`: общий модуль — байтовая копия ERP и Планёрки, и менять
его в MeetFlow нельзя (тест `test_shared_modules_are_byte_copies`). Общий вызов оставляет только готовые строки
«ЧЧ:ММ:СС<TAB>текст»; для разделения по голосам нужны ещё начало и конец каждой реплики, поэтому ответ сервиса
разбирается здесь и в сводку кладутся `segment_lines` / `segment_times`.

Протокол тот же, что у общего вызова: `form=multipart` — multipart с полем `file`, иначе — wav телом и параметры
в строке запроса. Разделение по голосам у сервиса не просим (`diarization=false`): его делает наш код.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .shared import model_routes as _mr


def call(route, wav_path, *, language: str = "ru", initial_prompt: str = "",
         hotwords: str | None = None) -> tuple[str, dict]:
    """Текст «ЧЧ:ММ:СС<TAB>реплика» и сводка с временами реплик."""
    if not _mr._internal_url(route.url):
        raise _mr.RoutesError("сервис распознавания — только во внутренней сети")
    data = Path(wav_path).read_bytes()
    prompt = " ".join(x for x in (initial_prompt or "", hotwords or "") if x)
    started = time.monotonic()

    def collect(raw: dict) -> tuple[str, dict]:
        segments = raw.get("segments") if isinstance(raw.get("segments"), list) else []
        rows, texts, times = [], [], []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            phrase = str(segment.get("text") or "").strip()
            if not phrase:
                continue
            try:
                start = float(segment.get("start") or 0)
                end = float(segment.get("end") or start)
            except (TypeError, ValueError):
                continue
            stamp = int(start)
            rows.append(f"{stamp // 3600:02d}:{stamp % 3600 // 60:02d}:{stamp % 60:02d}\t{phrase}")
            texts.append(phrase)
            times.append([round(start, 2), round(end, 2)])
        text = "\n".join(rows) if rows else str(raw.get("text") or "")
        duration = raw.get("duration") or raw.get("media_seconds") \
            or (raw.get("meta") or {}).get("media_seconds")
        meta = dict(raw.get("meta") or {})
        meta.setdefault("model", route.name)
        meta.setdefault("device", "сервис в сети")
        meta.update({
            "engine": route.url,
            "language": raw.get("language") or meta.get("language"),
            "duration": duration,
            "media_seconds": round(float(duration)) if duration else None,
            "lines": len(rows) or len([x for x in text.splitlines() if x.strip()]),
            "elapsed_seconds": round(time.monotonic() - started),
            "speakers": raw.get("speaker_count") or meta.get("speakers"),
            "segments": len(segments),
            "segment_lines": texts,
            "segment_times": times,
        })
        return text, {k: v for k, v in meta.items() if v not in (None, [], "")}

    form = str(route.opt("form") or "").strip().lower()
    if form != "multipart":
        query = {k: v for k, v in {"language": language, "initial_prompt": initial_prompt,
                                   "hotwords": hotwords or ""}.items()
                 if isinstance(v, (str, int, float)) and v != ""}
        url = route.url + (("&" if "?" in route.url else "?") + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "audio/wav"}, method="POST")
        with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return collect(raw)

    boundary = "----meetflow-asr-" + uuid.uuid4().hex
    file_field = str(route.opt("file_field") or "file")
    fields = [("language", language), ("prompt", prompt), ("wait", "true"),
              ("diarization", "false"), ("identify_speakers", "false"), ("word_timestamps", "false")]
    fields += [(str(k), str(v)) for k, v in (route.opt("extra_fields") or {}).items()]
    parts: list[bytes] = []
    for name, value in fields:
        if value == "":
            continue
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
                     .encode("utf-8"))
    filename = Path(wav_path).name or "audio.wav"
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                 f"filename=\"{filename}\"\r\nContent-Type: audio/wav\r\n\r\n".encode("utf-8"))
    parts.append(data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    req = urllib.request.Request(route.url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "Content-Length": str(len(body))})
    with urllib.request.urlopen(req, timeout=float(route.opt("timeout_sec", 4 * 3600))) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    return collect(raw)
