"""Приёмник: выгрузка ВКС рядом с записью прикрепляется к её встрече (записка 05.11.2026, п. 6; шаг 4 пункта 6 плана).

Дата и время в именах файлов решают, та же это встреча или другая: две встречи одного дня не сливаются, а выгрузка,
пришедшая позже записи, ложится к своей встрече и запускает пересборку — как новая запись.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from meetflow.core.intake import время_из_имени
from meetflow.web.app import create_app

ЗАПИСЬ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная, вопросов нет.\n"
          "[00:02:00] Петрова Анастасия: Готовлю регламент склада к пятнице.\n"
          "[00:03:00] Игнатов Иван: Хорошо, дальше по складу и адресному хранению.\n")
ВЫГРУЗКА = ("[00:01:05] Игнатов Иван: Начинаем по складу, повестка обычная, вопросов нет.\n"
            "[00:02:10] Петрова Анастасия: Готовлю регламент склада к 17-му.\n"
            "[00:03:10] Игнатов Иван: Хорошо, дальше по складу и адресному хранению.\n")


class _Пайп:
    """Запись вызовов сборки: настоящая не нужна, проверяется приём и запуск."""

    def __init__(self, pipe):
        self._pipe = pipe
        self.calls: list[tuple[int, int]] = []

    def __call__(self, project_id, meeting_id, limits=None):
        self.calls.append((project_id, meeting_id))

        class Отчёт:
            status = "ok"
            detail = ""
            protocol_saved = True

        return Отчёт()


def test_время_из_имени():
    assert время_из_имени("работа с тендерами 2026-11-06 11-59-7.m4a") == 11 * 60 + 59
    assert время_из_имени("Выгрузка ВКС 06.11.2026 10.15.txt") == 10 * 60 + 15
    assert время_из_имени("Отчёт 15.10.2026 09:05.txt") == 9 * 60 + 5
    assert время_из_имени("Встреча 06.11.2026.txt") is None
    assert время_из_имени("06.11") is None                  # дата, а не время


def _приложение(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout")
    st.set_setting("watch_folder", str(tmp_path / "приёмник"), pid, "тест")
    (tmp_path / "приёмник").mkdir()
    return c, st, pid


def _два_прохода(c, pid):
    svc = c.app.state.intake
    svc._intakes.pop(pid, None)
    svc.scan_project(pid)
    return svc.scan_project(pid)


def test_выгрузка_рядом_с_записью_та_же_встреча(tmp_path):
    c, st, pid = _приложение(tmp_path)
    папка = tmp_path / "приёмник"
    (папка / "Запись 06.11.2026 10-15.txt").write_text(ЗАПИСЬ, encoding="utf-8")
    (папка / "Выгрузка ВКС 06.11.2026 10-20.txt").write_text(ВЫГРУЗКА, encoding="utf-8")
    _два_прохода(c, pid)
    встречи = st.q("SELECT id FROM meetings WHERE date='2026-11-06'")
    assert len(встречи) == 1, [dict(r) for r in встречи]
    источники = st.q("SELECT name, local_asr FROM sources WHERE meeting_id=? ORDER BY name", (встречи[0]["id"],))
    assert [s["name"] for s in источники] == ["Выгрузка ВКС 06.11.2026 10-20.txt", "Запись 06.11.2026 10-15.txt"]
    assert [s["local_asr"] for s in источники] == [0, 0]      # текстовые источники: своего распознавания нет


def test_другая_встреча_того_же_дня_не_сливается(tmp_path):
    c, st, pid = _приложение(tmp_path)
    папка = tmp_path / "приёмник"
    (папка / "Запись 06.11.2026 09-00.txt").write_text(ЗАПИСЬ, encoding="utf-8")
    (папка / "Запись 06.11.2026 15-30.txt").write_text(ЗАПИСЬ.replace("к пятнице", "к среде"), encoding="utf-8")
    _два_прохода(c, pid)
    встречи = st.q("SELECT id FROM meetings WHERE date='2026-11-06'")
    assert len(встречи) == 2, [dict(r) for r in встречи]


def test_поздняя_выгрузка_запускает_пересборку(tmp_path, monkeypatch):
    c, st, pid = _приложение(tmp_path)
    папка = tmp_path / "приёмник"
    (папка / "Запись 06.11.2026 10-15.txt").write_text(ЗАПИСЬ, encoding="utf-8")
    st.set_setting("autorun", True, pid, "тест")
    _два_прохода(c, pid)
    встречи = st.q("SELECT id FROM meetings WHERE date='2026-11-06'")
    assert len(встречи) == 1
    (папка / "Выгрузка ВКС 06.11.2026 10-20.txt").write_text(ВЫГРУЗКА, encoding="utf-8")
    зов = _Пайп(c.app.state.pipe)
    monkeypatch.setattr(c.app.state.pipe, "run", зов)
    r = _два_прохода(c, pid)
    assert st.q("SELECT name FROM sources WHERE meeting_id=? AND name LIKE 'Выгрузка%'", (встречи[0]["id"],))
    assert зов.calls and зов.calls[-1] == (pid, встречи[0]["id"]), (зов.calls, r.get("autorun"))
