# -*- coding: utf-8 -*-
"""Обучающее видео «Как пользоваться» (10.11.2026).

Владелица: «видео не проигрывается и открывается в урезанном по высоте виде». Причина: в `static/media` не было файла —
`<video src="media/kak_polzovatsya.mp4">` получал 404, блок схлопывался. Теперь файл лежит рядом с фронтом, отдаётся
статикой с поддержкой диапазонов (перемотка), пропорции 16:9 держатся и до загрузки метаданных.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"
ВИДЕО = СТАТИКА / "media" / "kak_polzovatsya.mp4"


def test_файл_есть_и_это_mp4():
    assert ВИДЕО.is_file(), "файла обучающего видео нет в static/media"
    размер = ВИДЕО.stat().st_size
    assert 1_000_000 < размер <= 15 * 1024 * 1024, размер
    assert ВИДЕО.read_bytes()[4:8] == b"ftyp", "контейнер MP4"


def test_версия_ролика_как_у_статики():
    app_js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    версия = re.search(r'app\.js\?v=([0-9a-z]+)"', (СТАТИКА / "index.html").read_text(encoding="utf-8")).group(1)
    assert f'"media/kak_polzovatsya.mp4?v={версия}"' in app_js, "ролик и статика — одна ступень версии"


def test_пропорции_и_высота():
    css = (СТАТИКА / "styles.css").read_text(encoding="utf-8")
    assert ".help-video { height: auto; aspect-ratio: 16 / 9; object-fit: contain; }" in css


def test_отдаётся_с_диапазонами(tmp_path):
    from meetflow.web.app import create_app
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False))
    полный = c.get("/media/kak_polzovatsya.mp4")
    assert полный.status_code in (200, 206)
    assert полный.headers["content-type"].startswith("video/mp4")
    кусок = c.get("/media/kak_polzovatsya.mp4", headers={"Range": "bytes=0-100000"})
    assert кусок.status_code == 206, "без диапазонов не работает перемотка"
    assert кусок.headers["content-range"] == f"bytes 0-100000/{ВИДЕО.stat().st_size}"
    assert len(кусок.content) == 100001
