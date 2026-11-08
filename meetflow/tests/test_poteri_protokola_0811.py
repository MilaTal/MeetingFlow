"""Пересборка потеряла абзацы протокола — вариант А (08.11.2026).

Тело протокола пишет модель заново: факт, выпавший из её ответа при пересборке, исчезает из видимого протокола (то же
нашлось у Планёрки: 0 дословных абзацев, 2 пропали, 11 фраз). Вариант А протокол не восстанавливает — считает потери
кодом и показывает карточку с прежним текстом, чтобы потеря не была молчаливой.
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core import protokol_poteri as пп
from meetflow.core.pipeline import MeetingPipeline

ТЕКСТ = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
         "[00:02:00] Игнатов Иван: Петрова Анастасия, подготовьте регламент склада к пятнице.\n"
         "[00:03:00] Игнатов Иван: Робот собран, экономия около 4 млн рублей за квартал, заявку оформлять на 17-16.\n")
СТАРЫЙ = ("# Протокол\n\n## Обсуждение\nРобот собран, экономия около 4 млн рублей за квартал, заявку оформлять на 17-16, "
          "сроки согласованы со всеми участниками встречи.\n\n## Решения\nПродолжаем работу как есть.")
НОВЫЙ = "# Протокол\n\n## Обсуждение\nРобот собран и работает."


def test_абзацы_без_заголовков_таблиц_и_коротких():
    абзацы = пп.абзацы(СТАРЫЙ)
    # заголовок «## Обсуждение» стоит вплотную к абзацу — текст под ним остаётся; короткое «Продолжаем работу как есть.»
    # (26 знаков) в расчёт не идёт
    assert абзацы == ["Робот собран, экономия около 4 млн рублей за квартал, заявку оформлять на 17-16, сроки "
                      "согласованы со всеми участниками встречи."]
    assert all(not б.lstrip().startswith("#") and "|" not in б for б in абзацы)


def test_потерянные_находятся_дословно():
    потеряно = пп.потерянные(СТАРЫЙ, НОВЫЙ)
    assert потеряно and "4 млн" in потеряно[0]
    карточка = пп.данные(потеряно, 2)
    assert карточка["count"] == len(потеряно) and карточка["version"] == 2
    assert "4 млн" in карточка["paragraphs"][0]


def test_перестановка_пробелов_не_потеря():
    assert пп.потерянные(СТАРЫЙ, СТАРЫЙ.replace("  ", " ")) == []


def _сборка(store, project, meeting, theme, tmp_path, раздел):
    class Модель(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Подготовить регламент склада", "assignee": "Петрова Анастасия",
                               "line": 2, "due_date": "к пятнице"}]}

        def _units(self, data):
            return {"items": []}

        def _protocol(self, system, data):
            out = super()._protocol(system, data)
            out.setdefault("sections", {})["Обсуждение"] = раздел
            return out
    p = MeetingPipeline(theme, store, default_registry(), Модель(), MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=ТЕКСТ,
                 digest="п" + str(meeting) + раздел, local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    return p


def test_пересборка_даёт_карточку_и_возвращает_абзац(store, project, meeting, theme, tmp_path):
    первая = _сборка(store, project, meeting, theme, tmp_path, "Робот собран, экономия около 4 млн рублей за квартал, "
                                                              "заявку оформлять на 17-16, сроки согласованы.")
    первая.run(project, meeting)
    assert "4 млн" in store.get("meetings", meeting)["protocol_md"]
    вторая = _сборка(store, project, meeting, theme, tmp_path, "Робот собран и работает.")
    вторая.run(project, meeting)
    второй = store.get("meetings", meeting)["protocol_md"]
    # вариант Б: абзац, опирающийся на запись, возвращён разделом «Из прежней версии» и помечен
    assert "## Из прежней версии" in второй and "(из прежней версии)" in второй
    assert "4 млн" in второй
    карточки = store.q("SELECT title, payload FROM cards WHERE meeting_id=? AND title LIKE 'Пересборка потеряла%'",
                       (meeting,))
    assert карточки, "потеря не должна быть молчаливой"
    данные = json.loads(карточки[0]["payload"])
    assert данные["count"] >= 1 and данные["returned"] == 1
    assert "4 млн" in данные["paragraphs"][0] and данные["version"] == 2


def test_обоснованность_считается_по_записи():
    assert пп.обоснован("Робот собран, экономия около 4 млн рублей за квартал",
                        ТЕКСТ) is True
    assert пп.обоснован("Совершенно посторонний вывод про марсианские каналы и климат красной планеты",
                        ТЕКСТ) is False
    assert пп.обоснован("Робот собран", "") is False


def test_первая_сборка_карточки_не_даёт(store, project, meeting, theme, tmp_path):
    p = _сборка(store, project, meeting, theme, tmp_path, "Робот собран и работает.")
    p.run(project, meeting)
    assert not store.q("SELECT id FROM cards WHERE meeting_id=? AND title LIKE 'Пересборка потеряла%'", (meeting,))


def test_повторная_пересборка_не_двоит_пометку():
    """Абзац возвращается и во второй пересборке, но пометка одна: «(из прежней версии) (из прежней версии)» — нет."""
    прежний = ("## Обсуждение\n\nРобот собран и отгружен, бюджет 4 млн рублей согласован с заказчиком на этой неделе.\n\n"
               "## Задачи\n\n| задача |\n")
    новый = "## Обсуждение\n\nСобрали робота.\n\n## Задачи\n\n| задача |\n"
    первый = пп.дополнить(новый, пп.потерянные(прежний, новый))
    второй = пп.дополнить(новый, пп.потерянные(первый, новый))
    assert "(из прежней версии) (из прежней версии)" not in второй
    assert второй.count("(из прежней версии)") == 1
    assert "4 млн" in второй


def test_порог_возврата_из_настройки(monkeypatch):
    """Порог опоры — числом из `WEBAPP_POTERI_POROG`, а не правкой кода: 0.6 возвращает, 0.8 — уже нет."""
    запись = "Робот собран, экономия около 4 млн рублей, заявку оформлять, сроки согласованы"
    абзац = "Робот собран, экономия около 4 млн рублей, заявку оформлять, но про марсианские каналы и климат ничего"
    monkeypatch.delenv(пп.ПЕРЕМЕННАЯ_ПОРОГ, raising=False)
    assert пп.порог() == 0.6 and пп.обоснован(абзац, запись) is True
    monkeypatch.setenv(пп.ПЕРЕМЕННАЯ_ПОРОГ, "0.8")
    assert пп.порог() == 0.8 and пп.обоснован(абзац, запись) is False
    monkeypatch.setenv(пп.ПЕРЕМЕННАЯ_ПОРОГ, "0,7")
    assert пп.порог() == 0.7
    monkeypatch.setenv(пп.ПЕРЕМЕННАЯ_ПОРОГ, "не число")
    assert пп.порог() == 0.6


def test_возврат_можно_выключить(store, project, meeting, theme, tmp_path, monkeypatch):
    """«WEBAPP_POTERI_VOZVRAT=0» — вариант «только карточка»: в протокол ничего не возвращается, потеря видна."""
    monkeypatch.setenv(пп.ПЕРЕМЕННАЯ_ВОЗВРАТ, "0")
    первая = _сборка(store, project, meeting, theme, tmp_path, "Робот собран, экономия около 4 млн рублей за квартал, "
                                                              "заявку оформлять на 17-16, сроки согласованы.")
    первая.run(project, meeting)
    вторая = _сборка(store, project, meeting, theme, tmp_path, "Робот собран и работает.")
    вторая.run(project, meeting)
    второй = store.get("meetings", meeting)["protocol_md"]
    assert "## Из прежней версии" not in второй and "4 млн" not in второй
    карточки = store.q("SELECT payload FROM cards WHERE meeting_id=? AND title LIKE 'Пересборка потеряла%'", (meeting,))
    assert карточки and json.loads(карточки[0]["payload"])["returned"] == 0
