"""Переключение проекта открывает «Реестр задач» (слово владелицы 09.11.2026, третий раз).

«При переключении по проектам или при выборе общие встречи — должно автоматически открываться со страницы Реестр задач».
Прежнее правило 08.11 (открывать «Реестр встреч») отменено её же словом: задача искалась в реестре задач выбранного
проекта. Если экран уже «Реестр задач» — перерисовываем, иначе hash не меняется и остался бы старый проект.
"""
from pathlib import Path

from starlette.testclient import TestClient

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
    assert "app.js?v=20261109mf79" in html and "styles.css?v=20261109mf79" in html


def test_реестр_задач_назван_и_в_меню_проекта():
    """Экран подписан «Реестр задач», и в меню проекта есть пункт — иначе «не понять, куда попал» (слово 09.11)."""
    reg = (СТАТИКА / "registry.js").read_text(encoding="utf-8")
    assert "<h1>Реестр задач</h1>" in reg
    app_js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert 'data-route="dashboard" href="#dashboard">Реестр задач</a>' in app_js
    assert 'aria-current="page"' in app_js


def test_первая_страница_при_входе_общие_встречи_реестр_задач():
    """Слово 09.11: при входе (портал или просто адрес) первой открывается «Общие встречи» — «Реестр задач».
    Проверка 09.11 вечером: «голый» адрес запоминается при загрузке скрипта (`пришлиБезАдреса`), иначе маршрутизатор
    успевал поставить «#dashboard», проект оставался прежним, а p попадал в строку запроса и старт был пустым."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "function перваяСтраницаПриВходе()" in js
    assert 'const пришлиБезАдреса = !(location.hash || "").replace(/^#/, "").trim();' in js
    assert 'if (!пришлиБезАдреса) return;' in js
    assert 'localStorage.setItem("currentProjectId", String(общие.id));' in js
    assert 'sessionStorage.setItem("currentProjectId", String(общие.id));' in js
    assert '"#dashboard?p=" + общие.id' in js, "адрес первой страницы несёт проект «Общие встречи»"
    # вызывается в обоих путях входа
    assert js.count("перваяСтраницаПриВходе();") >= 2
    # в загрузке проектов решение принимается до отрисовки панели — иначе старт остался бы на прежнем проекте
    assert "if (пришлиБезАдреса) {" in js
    # старый мусор ?p= без «#» убирается из строки запроса
    assert 'поиск.has("p")' in js


def test_страница_входа_не_кэшируется(tmp_path):
    """09.11.2026: из-за кэша браузер держал старый index.html — новая версия статики не подхватывалась до Ctrl+F5,
    и владелица видела прежний старт. HTML отдаётся с `no-cache`, версии в адресах — как раньше."""
    from meetflow.web.app import create_app
    c = TestClient(create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False))
    страница = c.get("/")
    assert страница.status_code == 200
    assert страница.headers.get("cache-control") == "no-cache, must-revalidate"
    файл = c.get("/app.js?v=20261109mf79")
    assert файл.status_code == 200
    assert "no-cache" not in (файл.headers.get("cache-control") or "")
