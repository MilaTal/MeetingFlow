"""Переключение проекта открывает «Реестр встреч» (слово владелицы 09.11.2026, вечернее уточнение).

«Не могу добиться, чтобы первая страница при переходе была Реестр встреч из Общие встречи». Прежнее слово того же дня
(«Реестр задач») отменено ею же: при переключении проекта и «Общих встреч» справа открывается «Реестр встреч».
Если экран уже «Реестр встреч» — перерисовываем, иначе hash не меняется и остался бы старый проект.
"""
from pathlib import Path

from starlette.testclient import TestClient

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_нажатие_на_проект_открывает_реестр_встреч():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("function рисоватьПроекты")
    конец = js.index("// Поиск встречи", начало)
    кусок = js[начало:конец]
    assert 'location.hash = "#meetings";' in кусок
    assert "реестр встреч" in кусок.lower() or "Реестр встреч" in кусок
    assert 'location.hash = "#dashboard";' not in кусок, "открытие «Реестра задач» отменено словом 09.11"
    assert "else render();" in кусок, "если уже на реестре встреч — перерисовка, иначе останется старый проект"


def test_шапка_панели_двумя_строками():
    css = (СТАТИКА / "styles.css").read_text(encoding="utf-8")
    assert ".pl-head { display: flex; flex-wrap: wrap;" in css
    assert ".pl-head > span { flex: 1 1 100%;" in css
    assert ".pl-search { flex: 1 1 100%;" in css


def test_версии_подняты():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert "app.js?v=20261110mf93" in html and "styles.css?v=20261109mf93" in html


def test_реестр_задач_назван_и_открывается_из_встречи():
    """09.11.2026: экран «Реестр задач» виден снова (слово владелицы «не видно вообще»). Он открывается из меню проекта,
    а со страницы встречи — с фильтром по этой встрече."""
    reg = (СТАТИКА / "registry.js").read_text(encoding="utf-8")
    assert "<h1>Реестр задач</h1>" in reg
    app_js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert 'data-route="dashboard" href="#dashboard">Реестр задач</a>' in app_js
    assert 'class="pl-nested-item pl-start"' in app_js
    assert "pl-start-num" not in app_js, "цифры шага нет — только «начни здесь»"
    assert 'pl-start-mark">начни здесь<' in app_js


def test_первая_страница_при_входе_общие_встречи_реестр_встреч():
    """Слово 09.11 (вечернее уточнение): при входе (портал или просто адрес) первой открывается
    «Общие встречи» — «Реестр встреч».
    Проверка 09.11 вечером: «голый» адрес запоминается при загрузке скрипта (`пришлиБезАдреса`), иначе маршрутизатор
    успевал поставить адрес, проект оставался прежним, а p попадал в строку запроса и старт был пустым."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "function перваяСтраницаПриВходе()" in js
    assert 'const пришлиБезАдреса = !(location.hash || "").replace(/^#/, "").trim();' in js
    assert 'if (!пришлиБезАдреса && !только_общий_реестр) return;' in js
    assert 'localStorage.setItem("currentProjectId", String(общие.id));' in js
    assert 'sessionStorage.setItem("currentProjectId", String(общие.id));' in js
    assert '"#meetings?p=" + общие.id' in js, "адрес первой страницы несёт проект «Общие встречи»"
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


def test_в_меню_проекта_реестр_встреч_первым():
    """Слово владелицы 09.11.2026: первой строкой меню проекта — «Реестр встреч». Вечером того же дня задачи и
    договорённости убраны из меню проекта (только у конкретной встречи), поэтому строк осталось две."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("const менюПроектаСтрокой")
    конец = js.index("const строка =", начало)
    кусок = js[начало:конец]
    assert кусок.index('href="#meetings"') < кусок.index('href="#prep"'), "«Реестр встреч» — первым пунктом"
    assert кусок.count("pl-nested-item") == 5, "у проекта: встречи, задачи, подготовка, договорённости, статус"
    assert "п.general ? \"\" :" in кусок, "у «Общих встреч» договорённостей и статуса нет"


def test_задачи_и_договорённости_открываются_у_встречи():
    """Слово владелицы 09.11.2026: реестр задач и договорённости — только у конкретной встречи. На её странице есть
    кнопка «Все задачи встречи в реестре» (фильтр по встрече) и вкладка «Договорённости» с запросом по meeting_id."""
    mj = (СТАТИКА / "meeting.js").read_text(encoding="utf-8")
    assert "реестрПоВстрече(id, встреча.date)" in mj
    assert "agreements?meeting_id=${id}" in mj


def test_вход_с_общего_реестра_ведёт_на_реестр_встреч():
    """Жалоба владелицы 10.11.2026: вход снова попадал на «Реестр задач». Если адрес — `#dashboard` без выбранной
    встречи (прежняя вкладка/закладка), первая страница — «Реестр встреч»; ссылка с проектом не перебивается."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "только_общий_реестр" in js
    assert 'pИзАдреса === null || pИзАдреса === "" || Number(pИзАдреса) === общие.id' in js
