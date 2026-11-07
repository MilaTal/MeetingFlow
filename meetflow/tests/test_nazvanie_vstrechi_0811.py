# -*- coding: utf-8 -*-
"""Название встречи без «из папки-приёмника:» и без технических знаков имени файла (слово владелицы 08.11.2026).

Сервер (`core/nazvanie_vstrechi.для_показа`) и фронт (`cleanLabel` в app.js) чистят одинаково: тест гоняет одни и те же
примеры через обе функции (фронт — через node, если он есть). Ручное название не трогается. Имена файлов вымышленные.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from meetflow.core.nazvanie_vstrechi import для_показа

ПРИМЕРЫ = [
    ("из папки-приёмника: Склад адресное хранение 2026-11-05 10_30.m4a", "Склад адресное хранение"),
    ("из папки-приёмника: rec_20261105_103015.mp3", None),
    ("из папки-приёмника: Планёрка_по_закупкам (1).wav", "Планёрка по закупкам"),
    ("из папки-приёмника: Zoom Meeting 05.11.2026 GMT+3.mp4", None),
    ("из папки-приёмника: [Важно] Встреча с поставщиком — стеллажи.docx", "Важно Встреча с поставщиком — стеллажи"),
    ("создана из папки приёмника: закупки_стеллажей.ogg", "Закупки стеллажей"),
    ("из папки-приёмника", None),
    ("Встреча с поставщиком", "Встреча с поставщиком"),                 # ручное — как есть
    ("Разбор 10_30 final", "Разбор 10_30 final"),                       # ручное — не чистится
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("label, ждём", ПРИМЕРЫ)
def test_сервер(label, ждём):
    assert для_показа(label) == ждём


def test_фронт_чистит_так_же():
    node = shutil.which("node")
    if not node:
        pytest.skip("node не установлен — проверка фронта пропущена")
    js = (Path(__file__).resolve().parent.parent / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    начало = js.index("const МЕТКА_ПРИЁМНИКА")
    конец = js.index("\n}\n", js.index("function cleanLabel(label)")) + 3
    код = js[начало:конец]
    вход = json.dumps([p[0] for p in ПРИМЕРЫ], ensure_ascii=False)
    скрипт = код + f"\nconsole.log(JSON.stringify({вход}.map(x => cleanLabel(x) || null)));"
    out = subprocess.run([node, "-e", скрипт], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [p[1] for p in ПРИМЕРЫ]


def test_все_показы_через_чистку():
    """Сырых показов названия во фронте не осталось: везде cleanLabel."""
    static = Path(__file__).resolve().parent.parent / "meetflow" / "web" / "static"
    сырые = []
    for f in ("app.js", "nav.js", "meeting.js"):
        for n, line in enumerate((static / f).read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"esc\((?:m|meeting|занятая|б|другаяНаДату)\.label\)", line):
                сырые.append(f"{f}:{n}")
    assert сырые == []
