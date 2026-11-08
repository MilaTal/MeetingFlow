"""Переименование системы для людей: MeetFlow → «Встречи Невалаб» (записка `ffaa73e`, слово владелицы 07.11.2026).

Меняются только названия для людей: заголовок вкладки, шапка, подписи и сообщения, которые видит человек. Имя пакета,
маршруты, переменные `MEETFLOW_*`, ключи базы и имена журналов не трогаются — это не названия для людей.
"""
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
СТАТИКА = КОРЕНЬ / "meetflow" / "web" / "static"


def test_заголовок_вкладки_и_шапка():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert "<title>Встречи Невалаб</title>" in html
    assert '<div class="brand">Встречи Невалаб</div>' in html
    assert '<div class="brand">MeetFlow</div>' not in html
    assert '<div class="brand-sub">Прогресс проекта</div>' in html       # подпись под шапкой не трогается


def test_подписи_экранов_для_людей():
    app = (КОРЕНЬ / "meetflow" / "web" / "app.py").read_text(encoding="utf-8")
    assert 'FastAPI(title="Встречи Невалаб"' in app
    assert "Второй экземпляр «Встреч Невалаб» на той же базе" in app
    assert "«Команде» «Встреч Невалаб» полным ФИО" in app
    reestr = (КОРЕНЬ / "meetflow" / "web" / "erp" / "reestr.py").read_text(encoding="utf-8")
    assert "В «Встречах Невалаб» задача всегда в проекте" in reestr
    protokol = (КОРЕНЬ / "meetflow" / "web" / "erp" / "protokol.py").read_text(encoding="utf-8")
    assert "Пункты встречи во «Встречах Невалаб» собираются" in protokol
    intake = (КОРЕНЬ / "meetflow" / "core" / "intake.py").read_text(encoding="utf-8")
    assert "приёмником встреч «Встречи Невалаб»" in intake


def test_proizvodstvo_вместо_проекта_erp_в_мониторинге():
    app_js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "Проект ERP" not in app_js, "на экранах система называется «Производство»"
    assert "Производство обработает запись" in app_js
    assert "Что получает Производство" in app_js


def test_имя_пакета_и_маршруты_не_тронуты():
    # названия для людей поменялись, служебные имена — нет: перенос в ERP и Планёрку идёт по ним
    assert (КОРЕНЬ / "meetflow" / "core" / "pipeline.py").is_file()
    app = (КОРЕНЬ / "meetflow" / "web" / "app.py").read_text(encoding="utf-8")
    assert 'request.headers.get("x-requested-with") != "MeetFlow"' in app
