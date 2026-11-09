"""Самопроверка стенда: разбор журнала, свежесть кода, итог (план, пункт 26).

Живая часть (порт 8005) проверяется запуском; тесты — на разборе строк журнала и сравнении времён.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "zdorovie.py"
    spec = importlib.util.spec_from_file_location("zdorovie", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


def test_старт_берётся_из_последней_строки():
    м = _скрипт()
    текст = ("2026-11-09 03:01:11,100 INFO: Started server process [53144]\n"
             "2026-11-09 03:01:11,200 INFO: Uvicorn running on http://0.0.0.0:8005\n"
             "2026-11-09 04:28:35,900 INFO: Started server process [46648]\n"
             "2026-11-09 04:28:35,950 INFO: Uvicorn running on http://0.0.0.0:8005\n")
    assert м.запуск_из_журнала(текст) == datetime(2026, 11, 9, 4, 28, 35)
    assert м.запуск_из_журнала("") is None
    assert м.запуск_из_журнала("никакого старта") is None


def test_код_новее_запуска_требует_перезапуска():
    м = _скрипт()
    старт = datetime(2026, 11, 9, 4, 28, 35)
    раньше = datetime(2026, 11, 9, 4, 0, 0)
    позже = datetime(2026, 11, 9, 5, 0, 0)
    assert м.свежесть(старт, раньше)[0] is True
    ok, текст = м.свежесть(старт, позже)
    assert ok is False and "нужен перезапуск" in текст
    assert м.свежесть(None, позже)[0] is False


def test_запас_на_запись_во_время_старта():
    м = _скрипт()
    старт = datetime(2026, 11, 9, 4, 28, 35)
    почти = datetime(2026, 11, 9, 4, 28, 37)      # файл записан через 2 с после старта — это не новый код
    assert м.свежесть(старт, почти)[0] is True


def test_последняя_правка_по_каталогу(tmp_path):
    м = _скрипт()
    (tmp_path / "a").mkdir()
    первый = tmp_path / "a" / "старый.py"
    второй = tmp_path / "a" / "новый.py"
    первый.write_text("", encoding="utf-8")
    второй.write_text("", encoding="utf-8")
    import os
    os.utime(первый, (1_700_000_000, 1_700_000_000))
    os.utime(второй, (1_700_000_100, 1_700_000_100))
    правка = м.последняя_правка([tmp_path / "a"])
    assert правка == datetime.fromtimestamp(1_700_000_100)
    assert м.последняя_правка([tmp_path / "нет"]) is None


def test_health_отдаёт_время_старта(tmp_path):
    """/health возвращает `started_at`: по нему видно, на каком коде работает служба."""
    from datetime import datetime as дт
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app

    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    данные = r.json()
    assert данные["ok"] is True and "started_at" in данные
    assert дт.fromisoformat(данные["started_at"]) <= дт.now()


def test_расхождение_команды_видно():
    """После правки общей «Команды» самопроверка говорит, сколько дописать и чем синхронизировать."""
    м = _скрипт()
    assert м.строка_команды({})[1].startswith("Команда: общей")
    assert м.строка_команды({1: {"дописать": [], "добавить": []}})[1] == "Команда: расхождений нет"
    всего, текст = м.строка_команды({1: {"дописать": ["Иванов Пётр Сергеевич"], "добавить": []},
                                      6: {"дописать": [], "добавить": ["Сидоров Пётр Иванович"]}})
    assert всего == 2 and "расхождений 2" in текст and "sync_komandy.py --apply" in текст
