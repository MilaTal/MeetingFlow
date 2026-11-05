# -*- coding: utf-8 -*-
"""Промер демо-стенда: нажатия по путям, ошибки консоли, загрузка материала (05.11.2026).

Переписан по замечаниям разработчика (записка «замеры на демо сделаны, поправить скрипт»):
  * без `if count()` — шаг без элемента роняет тест, а не проходит молча;
  * роли из демо, в демо заведены супер-админ, админ проекта и участник; только вымышленные имена;
  * пути и число нажатий — из таблицы разработчика;
  * браузер — системный Chrome, иначе Edge; пропуск только когда нет ни Playwright, ни браузера, причина в выводе.
Платных вызовов нет: `MEETFLOW_LLM=mock`, сборка — заглушка.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api",
                               reason="Playwright не установлен — промер на демо не выполняется (ставить не обязательно)")

РОЛИ = {"супер": "Орлова Мария (супер-админ)", "админ": "Белов Сергей (админ)", "участник": "Гаврилова Анна"}
ИМЕНА = ("Орлова Мария", "Белов Сергей", "Гаврилова Анна")


def _порт() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def демо(tmp_path_factory):
    """Демо-сервер: своя база, три роли, заглушка модели, без забора из папок."""
    import uvicorn
    from meetflow.core.config import load_theme
    from meetflow.core.store import Store, now
    from meetflow.web.app import create_app

    папка = tmp_path_factory.mktemp("демо")
    db = str(папка / "demo.db")
    тема = load_theme("it_product")
    st = Store(db)
    pid = st.insert("projects", name="Демо-проект", theme=тема.id)
    for имя in ИМЕНА:
        st.insert("people", project_id=pid, full_name=имя)
    for имя, роль in zip(ИМЕНА, ("super_admin", "project_admin", "member")):
        st.insert("accounts", login=None, full_name=имя, role=роль, password_hash="", active=1, failed_attempts=0,
                  created_at=now(), confirmed=1, confirmed_source="демо")
    mid = st.insert("meetings", project_id=pid, date=time.strftime("%Y-%m-%d"), label="Демо без протокола")
    st.insert("sources", meeting_id=mid, name="Демо 05.11.2026.txt", kind="transcript",
              text="[00:01:00] Белов Сергей: отчёт по тестам отправил.\n[00:02:00] Орлова Мария: принято.\n",
              digest="демо-05.11")
    # Встреча с протоколом — путь «пересобрать с файлом»: у неё вкладка «Протокол» открывается сразу.
    from meetflow.connectors.llm_mock import MockLLM
    from meetflow.connectors.registry import default_registry
    from meetflow.core.pipeline import MeetingPipeline
    from meetflow.__main__ import DEMO_TEXT
    собранная = st.insert("meetings", project_id=pid, date=time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)),
                            label="Демо-встреча")
    was = {k: os.environ.pop(k, None) for k in ("VOICE_BASE_PATH", "TEAM_SHARED_PATH")}
    try:
        p = MeetingPipeline(тема, st, default_registry(), MockLLM(), MockLLM(), str(папка / "j.jsonl"))
        p.reg.add(pid, "Отправить отчёт по тестам", "Белов Сергей")
        p.ingest(pid, собранная, "Расшифровка 01.10.2026.txt", DEMO_TEXT.encode("utf-8"))
        assert p.run(pid, собранная).status == "ok"
    finally:
        for k, v in was.items():
            if v is not None:
                os.environ[k] = v
    было = os.environ.get("MEETFLOW_LLM")
    os.environ["MEETFLOW_LLM"] = "mock"          # ни одного платного вызова
    порт = _порт()
    app = create_app("it_product", db, str(папка / "j.jsonl"), watch=False)
    сервер = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=порт, log_level="error"))
    поток = threading.Thread(target=сервер.run, daemon=True)
    поток.start()
    for _ in range(100):
        if сервер.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{порт}", mid, папка, собранная
    сервер.should_exit = True
    поток.join(timeout=5)
    if было is None:
        os.environ.pop("MEETFLOW_LLM", None)
    else:
        os.environ["MEETFLOW_LLM"] = было


def _браузер(p):
    """Системный Chrome, иначе Edge: ставить ничего не нужно. Нет обоих — пропуск с причиной."""
    причины = []
    for канал in ("chrome", "msedge"):
        try:
            return p.chromium.launch(channel=канал)
        except Exception as exc:  # noqa: BLE001 — нет канала: пробуем следующий
            причины.append(f"{канал}: {str(exc).splitlines()[0][:80]}")
    pytest.skip("нет ни Chrome, ни Edge для промера — " + "; ".join(причины))


class Клики:
    """Счёт нажатий пути: каждое нажатие — один шаг, без «если кнопка есть»."""

    def __init__(self, стр):
        self.стр, self.n = стр, 0

    def по(self, локатор):
        локатор.first.click()
        self.n += 1
        self.стр.wait_for_timeout(350)


def _роль(стр, метка):
    стр.locator("#whoami-select").select_option(label=метка)
    стр.wait_for_timeout(900)


def _материал(папка, имя: str, данные: bytes) -> Path:
    файл = папка / имя
    файл.write_bytes(данные)
    return файл


def test_путь_пересборки_с_файлом(демо):
    """Меню → строка → «Материалы» → «Добавить материал» → главная → подтверждение = 6 (выбор файла отдельно)."""
    адрес, mid, папка, собранная = демо
    with sync_api.sync_playwright() as p:
        браузер = _браузер(p)
        стр = браузер.new_page(viewport={"width": 1400, "height": 900})
        ошибки = []
        стр.on("console", lambda m: ошибки.append(m.text) if m.type == "error" else None)
        стр.goto(адрес + "/#status")
        стр.wait_for_timeout(900)
        _роль(стр, РОЛИ["супер"])
        клики = Клики(стр)
        клики.по(стр.locator('#nav a[href="#meetings"]'))
        клики.по(стр.locator(f'a.proto-date[href="#meetings/{собранная}"]'))
        стр.wait_for_selector(".mt-bar")
        # две кнопки об одном: путь подписан «Путь: …», действие — своим глаголом
        assert стр.locator(".mt-path .mp-label").inner_text().startswith("Путь:")
        assert стр.locator("#reader-main-btn").inner_text() == "Пересобрать протокол"
        клики.по(стр.locator('.mt-btn[data-drawer="materials"]'))
        файл = _материал(папка, "дополнение.txt", "[00:03:00] Гаврилова Анна: добавка к записи.\n".encode("utf-8"))
        with стр.expect_file_chooser() as выбор:
            клики.по(стр.locator('label:has-text("Добавить материал")'))
        выбор.value.set_files(str(файл))                 # выбор файла — отдельно, не в счёте пути
        стр.wait_for_timeout(2500)                       # загрузка и возможная автозаглушечная сборка
        if стр.locator("#reader-main-btn[disabled]").count():
            стр.wait_for_selector("#reader-main-btn:not([disabled])", timeout=60000)
        клики.по(стр.locator("#reader-main-btn"))
        клики.по(стр.locator("#confirm-ok"))
        стр.wait_for_timeout(2500)
        assert клики.n == 6, клики.n
        assert ошибки == [], ошибки
        браузер.close()


def test_участник_добавляет_материал(демо):
    """Участник: «Реестр встреч» → строка → «Материалы» → «Добавить материал» = 3 и выбор файла отдельно."""
    адрес, mid, папка, собранная = демо
    with sync_api.sync_playwright() as p:
        браузер = _браузер(p)
        стр = браузер.new_page(viewport={"width": 1400, "height": 900})
        ошибки = []
        стр.on("console", lambda m: ошибки.append(m.text) if m.type == "error" else None)
        стр.goto(адрес + "/#meetings")
        стр.wait_for_timeout(900)
        _роль(стр, РОЛИ["участник"])
        стр.wait_for_timeout(600)
        клики = Клики(стр)
        клики.по(стр.locator(f'a.proto-date[href="#meetings/{mid}"]'))
        стр.wait_for_selector(".mt-bar")
        было = стр.locator('.mt-btn[data-drawer="materials"]').inner_text()
        клики.по(стр.locator('.mt-btn[data-drawer="materials"]'))
        файл = _материал(папка, "материал.png",
                         bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                                       "890000000a49444154789c6360000002000154a24f6b0000000049454e44ae426082"))
        with стр.expect_file_chooser() as выбор:
            клики.по(стр.locator('label:has-text("Добавить материал")'))
        выбор.value.set_files(str(файл))
        стр.wait_for_timeout(1800)
        assert клики.n == 3, клики.n
        стало = стр.locator('.mt-btn[data-drawer="materials"]').inner_text()
        assert стало != было or "материал.png" in стр.locator(".mt-drawer").inner_text(), (было, стало)
        assert ошибки == [], ошибки
        браузер.close()


def test_новая_встреча_и_план(демо):
    """Меню → «Другая дата…» → «Создать встречу» → «Сформировать план встречи» = 4."""
    адрес, _mid, _папка, _собранная = демо
    with sync_api.sync_playwright() as p:
        браузер = _браузер(p)
        стр = браузер.new_page(viewport={"width": 1400, "height": 900})
        ошибки = []
        стр.on("console", lambda m: ошибки.append(m.text) if m.type == "error" else None)
        стр.goto(адрес + "/#status")
        стр.wait_for_timeout(900)
        _роль(стр, РОЛИ["супер"])
        клики = Клики(стр)
        клики.по(стр.locator("#nav a#nav-prep"))
        клики.по(стр.locator("#prep-other-date"))
        стр.locator("#prep-new-date").fill(time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400)))
        клики.по(стр.locator("#prep-new-btn"))
        стр.wait_for_selector("#reader-main-btn", timeout=15000)
        assert стр.locator("#reader-main-btn").inner_text() == "Сформировать план встречи"
        клики.по(стр.locator("#reader-main-btn"))
        assert стр.locator("#confirm-ok").count() == 1       # нажатие ведёт к окну подтверждения
        assert клики.n == 4, клики.n
        стр.locator("#confirm-cancel").click()
        assert ошибки == [], ошибки
        браузер.close()
