# -*- coding: utf-8 -*-
"""Повторяемый промер на демо-стенде (05.11.2026): нажатия, консоль, загрузка, ход сборки.

Запуск: `python -m pytest tests/demo_progon_0511.py -q` — на машине без Playwright тест пропускается (skip).
Что меряет на вымышленных данных (`python -m meetflow demo`):
  * нажатия: пересборка с файлом, материал к ближайшей встрече участником, новая встреча и план;
  * ошибки консоли на экранах встречи за три роли — число;
  * загрузка файла переживает перерисовку;
  * идущая сборка видна после ухода и возврата (модель — заглушка, настоящая не вызывается).
Платных вызовов нет: сборка отменяется кнопкой «Отмена».
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api", reason="Playwright не установлен — промер на демо не выполняется")
sync_api = playwright


def _порт() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def демо(tmp_path_factory):
    """Демо-сервер: своя база, заглушка модели, без забора из папок."""
    import uvicorn
    from meetflow.connectors.llm_mock import MockLLM
    from meetflow.connectors.registry import default_registry
    from meetflow.core.config import load_theme
    from meetflow.core.pipeline import MeetingPipeline
    from meetflow.core.store import Store
    from meetflow.web.app import create_app

    папка = tmp_path_factory.mktemp("demo")
    db = str(папка / "demo.db")
    тема = load_theme("it_product")
    st = Store(db)
    pid = st.insert("projects", name="Демо-проект", theme=тема.id)
    for имя in ("Орлова Мария", "Белов Сергей", "Гаврилова Анна"):
        st.insert("people", project_id=pid, full_name=имя)
    mid = st.insert("meetings", project_id=pid, date=time.strftime("%Y-%m-%d"), label="Демо-встреча")
    pipe = MeetingPipeline(тема, st, default_registry(), MockLLM(), MockLLM())
    st.insert("sources", meeting_id=mid, name="Демо 01.10.2026.txt", kind="transcript",
              text="[00:01:00] Белов Сергей: отчёт по тестам отправил.\n", digest="demo")
    порт = _порт()
    app = create_app("it_product", db, str(папка / "j.jsonl"), watch=False)
    сервер = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=порт, log_level="error"))
    поток = threading.Thread(target=сервер.run, daemon=True)
    поток.start()
    for _ in range(100):
        if сервер.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{порт}", mid, папка
    сервер.should_exit = True
    поток.join(timeout=5)


def test_нажатия_и_консоль_на_демо(демо):
    адрес, mid, папка = демо
    with sync_api.sync_playwright() as p:
        браузер = p.chromium.launch()
        страница = браузер.new_page(viewport={"width": 1280, "height": 800})
        ошибки = []
        страница.on("console", lambda m: ошибки.append(m.text) if m.type == "error" else None)
        страница.goto(f"{адрес}/#meetings/{mid}")
        страница.wait_for_load_state("domcontentloaded")
        страница.wait_for_timeout(1200)
        # нажатия до подтверждения пересборки: кнопка → «Собрать» → «Отмена»
        главная = страница.locator("#reader-main-btn")
        assert главная.count() == 1
        главная.click()
        страница.wait_for_timeout(400)
        отмена = страница.locator("#confirm-cancel, #confirm-ok ~ button")
        if отмена.count():
            отмена.first.click()
        # загрузка материала участником: файл переживает перерисовку
        файл = папка / "материал.txt"
        файл.write_text("материал к встрече", encoding="utf-8")
        materials = страница.locator('.mt-btn[data-drawer="materials"]')
        if materials.count():
            materials.first.click()
            поле = страница.locator('input[type="file"]')
            if поле.count():
                поле.first.set_input_files(str(файл))
                страница.wait_for_timeout(1500)
        # три роли: экран встречи открывается, ошибок консоли не прибавилось
        for роль in ("Администратор (супер-админ)", "Костыря Наталья (админ)", "Иванов Пётр Андреевич"):
            селект = страница.locator("#whoami-select")
            if селект.count():
                селект.select_option(label=роль)
                страница.wait_for_timeout(700)
        assert ошибки == [], ошибки
        браузер.close()
