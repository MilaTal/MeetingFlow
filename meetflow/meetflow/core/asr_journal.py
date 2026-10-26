# -*- coding: utf-8 -*-
"""Журнал распознавания: какая точка, сколько реплик и говорящих, сколько времени.

Отдельно от журнала вызовов модели: распознавание не тратит денег модели и не входит в потолок вызовов,
но оператору нужно видеть, чем и с каким результатом сделана расшифровка (замечание к тестовой встрече
26.10.2026: «точка не записана»).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_lock = threading.Lock()


def write(path: str | Path | None, **record) -> None:
    if not path:
        return
    record.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    p = Path(path)
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_recent(path: str | Path | None, limit: int = 50) -> list[dict]:
    if not path or not Path(path).is_file():
        return []
    out: list[dict] = []
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def last_for_meeting(path: str | Path | None, meeting_id: int) -> dict:
    for rec in reversed(read_recent(path, 500)):
        if rec.get("meeting_id") == meeting_id:
            return rec
    return {}
