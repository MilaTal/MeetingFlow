"""Переключение проекта открывает «Реестр задач» (слово владелицы 09.11.2026, третий раз).

«При переключении по проектам или при выборе общие встречи — должно автоматически открываться со страницы Реестр задач».
Прежнее правило 08.11 (открывать «Реестр встреч») отменено её же словом: задача искалась в реестре задач выбранного
проекта. Если экран уже «Реестр задач» — перерисовываем, иначе hash не меняется и остался бы старый проект.
"""
from pathlib import Path

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_нажатие_на_проект_открывает_реестр_задач():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("function рисоватьПроекты")
    конец = js.index("// Поиск встречи", начало)
    кусок = js[начало:конец]
    assert 'location.hash = "#dashboard";' in кусок
    assert "реестр задач" in кусок.lower() or "Реестр задач" in кусок
    assert 'location.hash = "#meetings";' not in кусок, "открытие «Реестра встреч» отменено словом 09.11"
    assert "else render();" in кусок, "если уже на реестре задач — перерисовка, иначе останется старый проект"


def test_шапка_панели_двумя_строками():
    css = (СТАТИКА / "styles.css").read_text(encoding="utf-8")
    assert ".pl-head { display: flex; flex-wrap: wrap;" in css
    assert ".pl-head > span { flex: 1 1 100%;" in css
    assert ".pl-search { flex: 1 1 100%;" in css


def test_версии_подняты():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert "app.js?v=20261109mf76" in html and "styles.css?v=20261109mf76" in html


def test_реестр_задач_назван_и_в_меню_проекта():
    """Экран подписан «Реестр задач», и в меню проекта есть пункт — иначе «не понять, куда попал» (слово 09.11)."""
    reg = (СТАТИКА / "registry.js").read_text(encoding="utf-8")
    assert "<h1>Реестр задач</h1>" in reg
    app_js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert 'data-route="dashboard" href="#dashboard">Реестр задач</a>' in app_js
    assert 'aria-current="page"' in app_js


def test_первая_страница_при_входе_общие_встречи_реестр_задач():
    """Слово 09.11: при входе (портал или просто адрес) первой открывается «Общие встречи» — «Реестр задач»."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "function перваяСтраницаПриВходе()" in js
    assert 'localStorage.setItem("currentProjectId", String(общие.id));' in js
    assert 'location.hash = "#dashboard";' in js
    # вызывается в обоих путях входа
    assert js.count("перваяСтраницаПриВходе();") >= 2
    # пришли по ссылке с адресом — не перебиваем
    assert 'if ((location.hash || "").replace(/^#/, "").trim()) return;' in js
