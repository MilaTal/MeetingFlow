"""Переключение проекта открывает «Реестр встреч» (уточнение владелицы 08.11.2026 по скриншоту).

Слово: «куда-то потерялась задача — при переключении проектов и встреч сразу открывать вкладку Реестр встреч, а не как
сейчас». Прежде нажатие на проект принудительно открывало реестр задач; теперь — «Реестр встреч». Там же поправлена
шапка панели: «Встречи по» и «Поиск про» обрезались — заголовок и поле встали двумя строками.
"""
from pathlib import Path

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_нажатие_на_проект_открывает_реестр_встреч():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("function рисоватьПроекты")
    конец = js.index("// Поиск встречи", начало)
    кусок = js[начало:конец]
    assert 'location.hash = "#meetings";' in кусок
    assert 'location.hash = "#dashboard";' not in кусок, "прежнее «реестр задач» по слову владелицы убрано"
    assert "Реестр встреч" in кусок


def test_шапка_панели_двумя_строками():
    css = (СТАТИКА / "styles.css").read_text(encoding="utf-8")
    assert ".pl-head { display: flex; flex-wrap: wrap;" in css
    assert ".pl-head > span { flex: 1 1 100%;" in css
    assert ".pl-search { flex: 1 1 100%;" in css


def test_версии_подняты():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert "app.js?v=20261108mf71" in html and "styles.css?v=20261108mf71" in html
