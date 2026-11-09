"""Прибор «завис», /health busy, осиротевшие процессы, расшифровка до голосов, тень сведения (06.11.2026).

Повод — запись с тендерами: шаг разделения по голосам шёл 68 минут, прибор показывал «завис» (отметка ставилась
один раз в начале шага), по этому слову дважды перезапустили сервер и потеряли 2,5 часа распознавания. Ещё три
осиротевших дочерних процесса продолжали считать. Проверки — по запискам `85642d3` и `917f51e`, раздел 4.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors.base import ASRConnector
from meetflow.core import hod, svedenie_ten
from meetflow.core.types import SourceDoc, SourceKind

W = {"X-Requested-With": "erp-webapp"}


# ---------------------------------------------------------------- 4.1 прибор «завис»
def test_растущий_процессор_дочернего_процесса_не_завис(monkeypatch):
    процессор = {"сек": 100.0}
    monkeypatch.setattr(hod, "процессор_секунды", lambda pid: процессор["сек"])
    monkeypatch.setattr(hod, "жив", lambda pid: True)
    monkeypatch.setattr(hod, "ЗАМЕР_КАЖДЫЕ_СЕК", 0)
    проба = hod.Ход()
    проба.подшаг("разделение по голосам", прогноз_сек=3000)
    проба.дочерний(4242)
    проба.снимок()
    процессор["сек"] += 60                       # минута процессорного времени за замер — работа идёт
    снимок = проба.снимок()
    assert not проба.завис(снимок)
    assert снимок["подшаг"] == "разделение по голосам" and снимок["pid"] == 4242
    assert снимок["pid"] == 4242 and снимок["прогноз_сек"] == 3000


def test_стоящий_процессор_дочернего_процесса_завис(monkeypatch):
    monkeypatch.setattr(hod, "процессор_секунды", lambda pid: 500.0)   # время не растёт
    monkeypatch.setattr(hod, "жив", lambda pid: True)
    monkeypatch.setattr(hod, "ЗАМЕР_КАЖДЫЕ_СЕК", 0)
    проба = hod.Ход()
    проба.подшаг("разделение по голосам", прогноз_сек=3000)
    проба.дочерний(4242)
    проба.снимок()
    проба._рос = time.monotonic() - (hod.СТОП_ПРОЦЕССОРА_СЕК + 60)     # последний рост был давно
    снимок = проба.снимок()
    assert снимок["без_роста_сек"] and снимок["без_роста_сек"] > hod.СТОП_ПРОЦЕССОРА_СЕК
    assert проба.завис(снимок)


def test_мёртвый_дочерний_процесс_завис(monkeypatch):
    monkeypatch.setattr(hod, "жив", lambda pid: False)
    monkeypatch.setattr(hod, "процессор_секунды", lambda pid: None)
    проба = hod.Ход()
    проба.подшаг("отпечатки голосов", прогноз_сек=600)
    проба.дочерний(4242)
    assert проба.завис(проба.снимок())


def test_молчащий_сервис_распознавания_завис_только_после_получаса(monkeypatch):
    проба = hod.Ход()
    проба.подшаг("распознавание записи")
    проба._начат = time.monotonic() - 100          # 100 с — норма: «Транс» отвечает за минуту-две
    assert not проба.завис(проба.снимок())
    проба._начат = time.monotonic() - (hod.СТОП_РАСПОЗНАВАНИЯ_СЕК + 60)
    assert проба.завис(проба.снимок())


# ---------------------------------------------------------------- 4.2 /health busy
@pytest.fixture
def клиент(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETFLOW_HEAVY_IN_PROCESS", "off")
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    su = st.insert("accounts", login=None, full_name="Орлова Анна", role="super_admin", password_hash="", active=1,
                   confirmed=1)
    c.заголовки = {**W, "X-User-Id": str(su), "X-Project-Id": str(pid)}
    c.st, c.pid, c.app = st, pid, app
    return c


def test_health_спокоен_без_работы(клиент):
    d = клиент.get("/health").json()
    assert d["ok"] is True and d["busy"] is False and d["busy_что"] == {}


def test_health_показывает_идущий_шаг(клиент):
    c = клиент
    папка = Path(c.st.get_setting("watch_folder", c.pid) or "")
    c.st.set_setting("watch_folder", str(папка or Path(os.environ.get("TEMP", "."))), c.pid, "тест")
    c.app.state.intake._scanning[c.pid] = {"started": "2026-11-06T15:35:00", "step": "распознавание записи",
                                           "file": "работа с тендерами.m4a", "pulse": time.monotonic(),
                                           "step_started": time.monotonic() - 900}
    d = c.get("/health").json()
    assert d["busy"] is True
    assert d["busy_что"]["что"] == "проход папки-приёмника"
    assert d["busy_что"]["шаг"] == "распознавание записи"
    assert d["busy_что"]["секунд"] >= 900
    c.app.state.intake._scanning.pop(c.pid, None)


# ---------------------------------------------------------------- 4.3 осиротевшие процессы
def test_осиротевший_ребёнок_находится_и_останавливается(клиент, monkeypatch, tmp_path):
    monkeypatch.setattr(hod, "ФАЙЛ_ДЕТЕЙ", tmp_path / "child_pids.json")
    monkeypatch.setattr(hod, "дети", lambda parent: [])
    живые = {4242: True}
    monkeypatch.setattr(hod, "жив", lambda pid: живые.get(pid, False))
    созданные = {4242: 1_700_000_000.0}
    monkeypatch.setattr(hod, "время_создания", lambda pid: созданные.get(pid))
    останавливали: list[int] = []
    monkeypatch.setattr(hod.os, "kill", lambda pid, sig: (останавливали.append(pid), живые.pop(pid, None)), raising=False)
    hod.запомнить_ребёнка(4242)
    assert [x["pid"] for x in hod.осиротевшие()] == [4242]
    if hod.sys.platform != "win32":
        остановленные = hod.остановить_сирот()
        assert [x["pid"] for x in остановленные] == [4242] and останавливали == [4242]
    # свой живой ребёнок сиротой не считается
    monkeypatch.setattr(hod, "дети", lambda parent: [4242])
    живые[4242] = True
    hod.запомнить_ребёнка(4242)
    assert hod.осиротевшие() == []


def test_номер_процесса_занят_другим_не_трогаем(monkeypatch, tmp_path):
    """Windows переиспользует PID (записка 06.11.2026): если время создания не совпало — это чужой процесс
    (ERP 8000, Планёрка 8001, «Транс»), его не останавливаем, а запись снимаем."""
    monkeypatch.setattr(hod, "ФАЙЛ_ДЕТЕЙ", tmp_path / "child_pids.json")
    monkeypatch.setattr(hod, "дети", lambda parent: [])
    monkeypatch.setattr(hod, "жив", lambda pid: pid == 777)
    monkeypatch.setattr(hod, "время_создания", lambda pid: 1_700_000_000.0)
    hod._записать_детей([{"pid": 777, "сервер": 1, "создан": 1_600_000_000.0, "начат": "2026-11-06T13:31:00"}])
    assert hod.осиротевшие() == [], "чужой процесс по занятому номеру не наш"
    assert hod._прочитать_детей() == [], "запись о таком номере должна сниматься"


def test_старая_запись_без_времени_создания_не_трогается(monkeypatch, tmp_path):
    monkeypatch.setattr(hod, "ФАЙЛ_ДЕТЕЙ", tmp_path / "child_pids.json")
    monkeypatch.setattr(hod, "дети", lambda parent: [])
    monkeypatch.setattr(hod, "жив", lambda pid: True)
    monkeypatch.setattr(hod, "время_создания", lambda pid: 1_700_000_000.0)
    hod._записать_детей([{"pid": 888, "сервер": 1, "начат": "2026-11-02T10:23:00"}])
    assert hod.осиротевшие() == []


# ---------------------------------------------------------------- 4.4 расшифровка до голосов
class СчитающаяЗапись(ASRConnector):
    """Точка распознавания, которая считает свои вызовы и умеет «падать» на голосах."""

    name = "считающая"
    вызовов = 0

    def transcribe(self, path: Path) -> SourceDoc:
        type(self).вызовов += 1
        return SourceDoc("проба (распознано локально).txt", SourceKind.TRANSCRIPT,
                         "00:00:01\tОбсудили сроки поставки\n00:00:05\tПроверить склад",
                         {"route": "считающая", "media_seconds": 120,
                          "segment_lines": ["Обсудили сроки поставки", "Проверить склад"],
                          "segment_times": [[1, 4], [5, 9]], "media_path": str(path), "keep_media": True})

    def health(self) -> dict:
        return {"name": self.name, "ok": True}


def test_повтор_после_остановки_на_голосах_не_зовёт_распознавание(make_pipe, store, project, tmp_path, monkeypatch):
    monkeypatch.setenv("MEETFLOW_HEAVY_IN_PROCESS", "off")
    p = make_pipe()
    p.plugins.resolve_source = lambda name: СчитающаяЗапись()  # noqa: ARG005
    запись = tmp_path / "проба.m4a"
    запись.write_bytes(b"RIFF" + b"\x00" * 4096)
    mid = store.insert("meetings", project_id=project, date="2026-11-06", label="в")
    первый = p.ingest(project, mid, запись.name, path=запись)
    assert первый["status"] == "ok" and СчитающаяЗапись.вызовов == 1
    строка = store.q("SELECT id, text, file_digest, voice_state FROM sources WHERE meeting_id=?", (mid,))
    assert len(строка) == 1 and строка[0]["file_digest"], "отпечаток файла должен сохраниться"
    assert строка[0]["voice_state"] != "готово", "голоса в тесте не разбираются — источник ждёт продолжения"
    # «сервер упал»: строка уже в базе, файл на месте. Повторный проход берёт расшифровку и не зовёт точку
    запись.write_bytes(запись.read_bytes())
    второй = p.ingest(project, mid, запись.name, path=запись)
    assert СчитающаяЗапись.вызовов == 1, "распознавание вызвано второй раз"
    assert второй["status"] == "ok" and второй["source_id"] == строка[0]["id"]
    assert len(store.q("SELECT id FROM sources WHERE meeting_id=?", (mid,))) == 1


# ---------------------------------------------------------------- вариант C: тень сведения
def test_тень_сведения_считает_и_ничего_не_снимает(tmp_path):
    задачи = [{"description": "Проверить склад на Бору", "quote": "", "responsible": "Петров Илья", "project": "Склад"},
              {"description": "Проверить склад на Бору", "quote": "", "responsible": "Петров Илья", "project": "Склад"},
              {"description": "Обновить спецификации склада", "quote": "", "responsible": "Орлова Анна", "project": "Склад"}]
    копия = [dict(x) for x in задачи]
    счёт = svedenie_ten.посчитать(задачи, запись="")
    assert задачи == копия, "тень не должна менять задачи"
    assert счёт["было"] == 3 and счёт["групп"] >= 1 and счёт["ошибочно_снятых"] == 0
    журнал = tmp_path / "svedenie_ten.jsonl"
    svedenie_ten.записать(журнал, 8, счёт, чем="сборка")
    строки = [json.loads(x) for x in журнал.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert строки and строки[0]["meeting_id"] == 8 and строки[0]["групп"] == счёт["групп"]
    assert "тень: групп" in svedenie_ten.строка_итога(счёт)
