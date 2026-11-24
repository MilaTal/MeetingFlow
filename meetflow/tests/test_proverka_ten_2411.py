# -*- coding: utf-8 -*-
"""Проверка в тень qwen3.8 в MeetFlow — 24.11.2026 (зеркально Планёрке и ERP).

Тень работает в шаге 4.4 сборки протокола (`MeetingPipeline`, проверка моделью): qwen3.8 получает тот же
источник и тот же черновик, что проверяющая модель, и пишет только строку журнала. Вердикт, правка по
замечаниям и карточки не меняются. Модуль — байтовая копия модуля Планёрки/ERP.
"""

import json

from meetflow.core import pipeline as конвейер
from meetflow.core import proverka_ten as тень


def _настройки():
    return {"имя": "qwen3.8-27b", "url": "http://127.0.0.1:9", "model": "qwen3.8:latest",
            "ключ": "", "max_tokens": 8000}


def _включить(monkeypatch, tmp_path):
    monkeypatch.setenv("SHADOW_VERIFY", "1")
    monkeypatch.setenv("SHADOW_VERIFY_UNTIL", "2099-01-01T00:00:00")
    monkeypatch.setenv("WEBAPP_SHADOW_VERIFY_PATH", str(tmp_path / "shadow_verify.jsonl"))
    monkeypatch.setattr(тень, "настройки", _настройки)


def test_тень_выключается_переменной(monkeypatch):
    monkeypatch.setenv("SHADOW_VERIFY", "0")
    assert тень.включена() is False


def test_шаг_тени_пишет_журнал_и_считает_совпадения(monkeypatch, tmp_path):
    _включить(monkeypatch, tmp_path)
    monkeypatch.setattr(тень, "_вызов", lambda *_а, **_к: {"verdict": {"clean": False, "findings": [
        {"category": "атрибуция", "quote": "15 позиций", "issue": "в источнике 12 позиций"},
        {"category": "атрибуция", "quote": "срок — понедельник", "issue": "в источнике пятница"}]}})
    основной = {"clean": False, "findings": [{"quote": "15 позиций", "issue": "в источнике 12 позиций"}]}
    строка = тень.прогнать(system="s", пользователь="u", label="Протокол встречи 19.11.2026",
                           основной=основной, источник="тест")

    assert строка["находок"] == 2 and строка["совпало"] == 1
    assert json.loads((tmp_path / "shadow_verify.jsonl").read_text(encoding="utf-8"))["источник"] == "тест"


def test_сбой_тени_не_роняет_сборку(monkeypatch, tmp_path):
    _включить(monkeypatch, tmp_path)

    def падение(*_а, **_к):
        raise OSError("spark-1 не отвечает")

    monkeypatch.setattr(тень, "_вызов", падение)
    строка = тень.прогнать(system="s", пользователь="u", label="Проверка", основной={"clean": True})
    assert строка["сбои"] and "spark-1" in строка["сбои"][0]


def test_шаг_проверки_протокола_зовёт_тень(monkeypatch):
    """Главное: сборка MeetFlow зовёт тень тем же запросом, что и проверяющую модель, и не падает."""
    зов: list[dict] = []
    monkeypatch.setattr(тень, "включена", lambda: True)
    monkeypatch.setattr(тень, "прогнать", lambda **к: зов.append(к))
    конвейер._тень_проверки("система", "черновик и источник", "Протокол встречи 19.11.2026",
                            {"clean": True, "findings": []}, 21)
    assert зов and зов[0]["источник"] == "meetflow" and зов[0]["meeting_id"] == 21

def test_тень_не_дублирует_основную_точку(monkeypatch, tmp_path):
    """Основная модель недоступна и цепочка ушла на точку тени — второй такой же вызов не нужен."""
    _включить(monkeypatch, tmp_path)
    звали = []
    monkeypatch.setattr(тень, "_вызов", lambda *а, **к: звали.append(1) or {"verdict": {"clean": True, "findings": []}})
    строка = тень.прогнать(system="s", пользователь="u", label="Проверка", основной={"clean": True},
                           точка="qwen3.8-27b")
    assert not звали
    assert строка["пропуск"] == "тень совпадает с основной точкой"
