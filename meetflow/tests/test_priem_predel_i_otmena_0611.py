"""Предел времени и остановка распознавания (06.11.2026) — по записи с тендерами из приёмника.

Что было: у вызова сервиса распознавания предел был только у сокета (4 ч), а проход папки-приёмника ждал ответ
сколько угодно — запись 54,6 МБ стояла 4102 с, признак «завис», и убрать её можно было только перезапуском
сервера, который начинал распознавание с нуля. Проверки: предел по часам, остановка человеком, поведение прохода
после остановки и маршрут «Остановить проход».
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetflow.connectors import asr_service
from meetflow.connectors.base import ASRConnector, ConnectorError
from meetflow.core.types import SourceDoc, SourceKind

W = {"X-Requested-With": "erp-webapp"}


class МолчащийСервер:
    """Сервер, который принимает соединение и не отвечает: так ведёт себя зависшая точка распознавания."""

    def __init__(self) -> None:
        self.сокет = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.сокет.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.сокет.bind(("127.0.0.1", 0))
        self.сокет.listen(5)
        self.порт = self.сокет.getsockname()[1]
        self.принятые: list[socket.socket] = []
        self.остановлен = threading.Event()
        self.поток = threading.Thread(target=self._крутить, daemon=True)
        self.поток.start()

    def _крутить(self) -> None:
        while not self.остановлен.is_set():
            try:
                клиент, _ = self.сокет.accept()
            except OSError:
                return
            self.принятые.append(клиент)

    def закрыть(self) -> None:
        self.остановлен.set()
        try:
            self.сокет.close()
        except OSError:
            pass
        for к in self.принятые:
            try:
                к.close()
            except OSError:
                pass


class Точка:
    """Точка распознавания для вызова: адрес, имя и настройки."""

    def __init__(self, url: str, **настройки):
        self.url, self.name = url, "точка-теста"
        self.настройки = настройки

    def opt(self, name: str, default=None):
        return self.настройки.get(name, default)


@pytest.fixture
def молчащий():
    сервер = МолчащийСервер()
    yield сервер
    сервер.закрыть()


def _запись(tmp_path: Path) -> Path:
    путь = tmp_path / "проба.wav"
    путь.write_bytes(b"RIFF" + b"\x00" * 2048)
    return путь


def test_предел_по_часам_останавливает_зависший_вызов(молчащий, tmp_path):
    точка = Точка(f"http://127.0.0.1:{молчащий.порт}/asr", form="multipart", deadline_sec=1)
    начало = time.monotonic()
    with pytest.raises(asr_service.Отменено) as ошибка:
        asr_service.call(точка, _запись(tmp_path))
    прошло = time.monotonic() - начало
    assert прошло < 20, f"вызов держался {прошло:.0f} с — предел не сработал"
    assert "не ответил за 1 с" in str(ошибка.value)
    assert asr_service.текущие() == [], "вызов остался в списке идущих"


def test_человек_останавливает_идущий_вызов(молчащий, tmp_path):
    точка = Точка(f"http://127.0.0.1:{молчащий.порт}/asr", form="multipart")   # предела нет
    итог: dict = {}

    def позвать() -> None:
        try:
            asr_service.call(точка, _запись(tmp_path))
        except BaseException as e:  # noqa: BLE001 — ошибку проверяем ниже
            итог["ошибка"] = e

    поток = threading.Thread(target=позвать, daemon=True)
    поток.start()
    срок = time.monotonic() + 10
    while not asr_service.текущие() and time.monotonic() < срок:
        time.sleep(0.05)
    assert asr_service.текущие(), "вызов не зарегистрировался — останавливать нечего"
    assert asr_service.отменить_все("тест") == 1
    поток.join(20)
    assert not поток.is_alive(), "остановленный вызов не закончился"
    assert isinstance(итог.get("ошибка"), asr_service.Отменено)
    assert "остановлено: тест" in str(итог["ошибка"])


def test_предел_считается_по_размеру_записи(monkeypatch):
    monkeypatch.delenv("MEETFLOW_ASR_DEADLINE_SEC", raising=False)
    точка = Точка("http://127.0.0.1:1/asr")
    # 54,6 МБ — та самая запись: минута на мегабайт, но не меньше получаса
    assert asr_service.предел_вызова(точка, int(54.6 * 2 ** 20)) == pytest.approx(54.6 * 60, rel=0.01)
    assert asr_service.предел_вызова(точка, 1024) == asr_service.ПРЕДЕЛ_МИН_СЕК
    assert asr_service.предел_вызова(Точка("http://127.0.0.1:1/asr", deadline_sec=120), 10 ** 9) == 120
    monkeypatch.setenv("MEETFLOW_ASR_DEADLINE_SEC", "90")
    assert asr_service.предел_вызова(точка, 10 ** 9) == 90


class ОтменяемаяЗапись(ASRConnector):
    """Точка, которая сообщает об остановке так же, как настоящая: «cancelled: …»."""

    name = "отменяемая"

    def transcribe(self, path: Path) -> SourceDoc:  # noqa: ARG002 — путь не нужен
        raise ConnectorError("cancelled: «проба.m4a» остановлено на 12 с: остановлено: человек")

    def health(self) -> dict:
        return {"name": self.name, "ok": True}


def test_остановленное_распознавание_не_считается_принятым(make_pipe, store, project):
    """Файл не «не принят» и не «принят»: он остаётся в папке, сборка не запускается, карточка — событие."""
    p = make_pipe()
    p.plugins.resolve_source = lambda name: ОтменяемаяЗапись()  # noqa: ARG005 — подменяем разбор имени
    mid = store.insert("meetings", project_id=project, date="2026-11-06", label="в")
    res = p.ingest(project, mid, "проба.m4a", path=Path("проба.m4a"))
    assert res["status"] == "cancelled", res
    assert "остановлено" in res["reason"]
    событие = store.q("SELECT kind, title FROM cards WHERE meeting_id=?", (mid,))
    assert событие and событие[0]["kind"] == "event" and "остановлено" in событие[0]["title"]
    assert store.q("SELECT id FROM sources WHERE meeting_id=?", (mid,)) == [], "расшифровка не должна сохраниться"


@pytest.fixture
def клиент(tmp_path):
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


def test_маршрут_остановки_прохода(клиент):
    c = клиент
    intake = c.app.state.intake
    пусто = c.post("/project-status/watch-folder/cancel", headers=c.заголовки)
    assert пусто.status_code == 200 and пусто.json()["cancelled"] is False
    assert "не идёт" in пусто.json()["detail"]

    intake._scanning[c.pid] = {"started": "2026-11-06T15:00:00", "step": "распознавание записи",
                               "file": "работа с тендерами.m4a", "pulse": time.monotonic()}
    остановка = c.post("/project-status/watch-folder/cancel", headers=c.заголовки)
    assert остановка.status_code == 200, остановка.text
    assert остановка.json()["cancelled"] is True
    assert c.pid in intake._отмена
    # следующая проходка снимает просьбу: она относится к одному проходу
    intake._отмена.discard(c.pid)


def test_проход_после_остановки_не_берёт_файлы(клиент, tmp_path):
    c = клиент
    intake = c.app.state.intake
    папка = tmp_path / "приёмник"
    папка.mkdir()
    c.st.set_setting("watch_folder", str(папка), c.pid, "тест")
    (папка / "Встреча 06.11.2026.m4a").write_bytes(b"RIFF" + b"\x00" * 64)
    intake.scan_project(c.pid)                        # первый проход запоминает размер — файл ещё «пишется»
    intake._отмена.add(c.pid)                         # человек нажал «Остановить проход» посреди прохода
    intake.pipe.ingest = lambda *a, **k: pytest.fail("после остановки файл брать нельзя")
    итог = intake._scan(c.pid, str(папка))
    assert итог["status"] == "cancelled"
    assert итог["cancelled"] and итог["cancelled"][0]["file"].startswith("Встреча 06.11.2026")


def test_просьба_остановить_не_переносится_на_следующий_проход(клиент, tmp_path):
    c = клиент
    intake = c.app.state.intake
    папка = tmp_path / "пусто"
    папка.mkdir()
    c.st.set_setting("watch_folder", str(папка), c.pid, "тест")
    intake._отмена.add(c.pid)                         # просьба, оставшаяся с прошлого прохода
    итог = intake.scan_project(c.pid)
    assert итог["status"] == "ok" and c.pid not in intake._отмена
