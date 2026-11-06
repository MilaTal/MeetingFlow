"""Д2.2 — смена проекта со страницы встречи (06.11.2026).

Записка `07b1234`, п. Д2.2: «смена проекта, стоя на встрече, уводит в «Реестр встреч» нового проекта; при
несохранённом вводе сначала спросить». Проверяется по коду экрана: поведение браузерное, а сервер в этом пункте
не участвует. Рядом — что прежние правила выбора проекта не сломаны.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def _app() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def test_смена_проекта_со_встречи_уводит_в_реестр():
    js = _app()
    начало = js.index("async function выбратьПроект(")
    тело = js[начало:js.index("document.getElementById(\"project-select\")?.addEventListener", начало)]
    assert "наЭкранеВстречи()" in тело, "смена проекта должна знать, что человек стоит на встрече"
    assert 'location.hash = "#meetings"' in тело, "после смены проекта открывается «Реестр встреч»"
    # при отказе от перехода проект не меняется, а список возвращается к прежнему значению
    assert 'if (!уйти)' in тело and '$s.value = String(выбранныйПроект())' in тело


def test_несохранённый_ввод_спрашивают_до_ухода():
    js = _app()
    assert "function естьНесохранённыйВвод()" in js
    функция = js[js.index("function естьНесохранённыйВвод()"):]
    функция = функция[:функция.index("\n}\n")]
    assert 'el.defaultValue' in функция, "сравнение с исходным значением поля — так видно правку человека"
    assert 'confirmDialog(' in js[js.index("async function выбратьПроект("):], "перед уходом — вопрос, а не молчание"


def test_встреча_узнаётся_по_номеру_целиком():
    js = _app()
    assert r"/^meetings\/\d+(\/|\?|$)/" in js, "номер встречи сравнивается целиком (Д2.5)"


def test_смена_проекта_по_прежнему_пишет_адрес_и_историю():
    js = _app()
    начало = js.index("async function выбратьПроект(")
    тело = js[начало:js.index("document.getElementById(\"project-select\")?.addEventListener", начало)]
    assert "записатьПроектВАдрес(v, true)" in тело
    assert 'sessionStorage.setItem("currentProjectId", String(v))' in тело


# ---------------------------------------------------------------- Д2.3: ссылка несёт проект задачи
def test_ссылка_открыть_в_реестре_переключает_на_проект_задачи():
    js = (STATIC / "meeting.js").read_text(encoding="utf-8")
    начало = js.index("function пунктЗадачи(")
    тело = js[начало:js.index("\n}\n", начало)]
    assert "t.project_id" in тело and "&p=${t.project_id}" in тело, "ссылка должна нести проект задачи"
    # адрес главнее памяти вкладки: пришёл p — вкладка переключается на него
    app = _app()
    assert "пИзАдреса" in app and 'sessionStorage.setItem("currentProjectId", String(Number(пИзАдреса)))' in app


# ---------------------------------------------------------------- Д2.6: «✓» уходит с проектом задачи
def test_галочка_уходит_с_проектом_задачи_даже_после_смены_проекта():
    js = _app()
    начало = js.index("function wireTaskDoneCell(")
    тело = js[начало:js.index("function wireTaskDoneButtons", начало)] if "function wireTaskDoneButtons" in js else js[начало:начало + 1800]
    assert "const проект = выбранныйПроект();" in тело, "проект запоминается в момент щелчка"
    assert "startDelayedDone(taskId, btn, проект)" in тело
    assert "проект: проект ?? выбранныйПроект()" in тело and "keepalive: true" in тело
    # заголовок можно переопределить на один запрос — иначе поздний вызов взял бы новый проект
    assert 'headers["X-Project-Id"] = String(opts.проект ?? выбранныйПроект());' in js

