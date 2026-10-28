"""Левое меню MeetFlow — решение владелицы 28.10.2026 (как в ERP плюс многопроектность).

Блок пользователей: «Реестр встреч» (#meetings, было «Встречи по проекту»), «Подготовка встречи» (#prep, поднята из блока
под чертой), «Актуализировать задачи из реестра» (#dashboard), «Инфо по проекту» — подпись группы с подпунктами
«Договорённости по проекту» (#agreements) и «Статус проекта» (#status). Выбор «Проект» (#project-select) — вверху левой
панели, над меню. «Подготовка встречи» при «Все проекты» — выбор проекта и «Создать проект»; при выбранном проекте — прежняя
страница и «Создать проект» в конце. Создание — прежним адресом POST /projects-list с правами суперадминистратора.
Данные вымышленные.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
NAV = (STATIC / "nav.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
W = {"X-Requested-With": "erp-webapp"}


def _блок_пользователей() -> str:
    меню = HTML[HTML.index('<div class="nav" id="nav">'):HTML.index('id="nav-admin-hr"')]
    return re.sub(r"<!--.*?-->", "", меню, flags=re.S)


def test_порядок_и_подписи_блока_пользователей():
    пункты = []
    for м in re.finditer(r'<a class="nav-item [^"]*" data-route="([a-z]+)"[^>]*>(.*?)</a>|<div class="nav-group"[^>]*>(.*?)</div>',
                         _блок_пользователей(), re.S):
        пункты.append((м.group(1), re.sub(r"<[^>]+>", "", м.group(2)).strip()) if м.group(1)
                      else ("группа", re.sub(r"<[^>]+>", "", м.group(3)).strip()))
    assert пункты == [("meetings", "Реестр встреч"), ("prep", "Подготовка встречи"),
                      ("dashboard", "Актуализировать задачи из реестра"), ("группа", "Инфо по проекту"),
                      ("agreements", "Договорённости по проекту"), ("status", "Статус проекта")]
    под_чертой = HTML[HTML.index('id="nav-admin-hr"'):HTML.index('id="nav-sa-hr"')]
    assert 'data-route="prep"' not in под_чертой
    assert "if ($adminHr) $adminHr.hidden = !isAdmin();" in APP


def test_выбор_проекта_над_меню():
    # Перевёрнуто 29.10.2026 (Доработка 2, решение владелицы 28.10.2026): было — видимый выпадающий список над меню;
    # стало — блок «Проекты» на том же месте, список остаётся скрытым (его читают другие экраны)
    проект = HTML.index('id="project-list"')
    assert HTML.count('id="project-select"') == 1 and '<select id="project-select" hidden' in HTML
    assert проект < HTML.index('<div class="nav" id="nav">') < HTML.index('id="user-box"')
    assert 'class="whoami-project nav-project"' in HTML
    # поведение прежнее: смена — через одну точку `выбратьПроект`, и у списка, и у строки блока
    assert 'getElementById("project-select")?.addEventListener("change", (e) => выбратьПроект(e.target.value));' in APP
    assert 'р.querySelector(".pl-name").addEventListener("click", () => выбратьПроект(р.dataset.id));' in APP


def test_подготовка_при_всех_проектах_выбор_и_создать_проект():
    prep = NAV[NAV.index("async function renderPrep()"):NAV.index("routes.prep = renderPrep;")]
    assert "if (!выбранныйПроект()) { renderPrepВыборПроекта(); return; }" in prep
    assert 'if (нуженПроект("Подготовка встречи")) return;' not in prep        # голой подсказки больше нет
    выбор = NAV[NAV.index("function renderPrepВыборПроекта()"):NAV.index("async function renderPrep()")]
    assert 'id="prep-project-select"' in выбор and "выбратьПроект(e.target.value)" in выбор
    assert "${создатьПроектHtml()}" in выбор and "подключитьСозданиеПроекта();" in выбор
    # при выбранном проекте — прежняя страница и «Создать проект» в конце
    assert "Ближайшая встреча: ${esc(fmtRuDate(б.date))}" in prep and "Другая дата…" in prep
    assert "${создатьПроектHtml()}`;\n  подключитьСозданиеПроекта();" in prep


def test_создать_проект_прежним_адресом_и_правами():
    код = NAV[NAV.index("function создатьПроектHtml()"):NAV.index("function renderPrepВыборПроекта()")]
    assert 'if (!isSuperAdmin()) return "";' in код                         # права — как у POST /projects-list (need_super)
    assert 'api("/projects-list", { method: "POST", json: { name: имя,' in код
    assert 'id="prep-project-parent"' in код and "Надпроект" in код
    assert "await загрузитьПроекты();\n      выбратьПроект(п.id);" in код
    assert код.count('api("/') == 1                                           # нового адреса нет


@pytest.fixture
def env(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="Склад", theme="erp_rollout", archived=0)
    ids = {role: st.insert("accounts", login=None, full_name=fio, role=role, password_hash="", active=1, confirmed=1)
           for fio, role in (("Орлова Анна", "super_admin"), ("Петров Илья", "project_admin"))}

    def h(role="super_admin", project=0):
        return {**W, "X-User-Id": str(ids[role]), "X-Project-Id": str(project)}
    c.h, c.pid = h, pid
    return c


def test_создание_проекта_с_подготовки_через_прежний_адрес(env):
    c, h = env, env.h
    # «Все проекты» (0): суперадминистратор заводит проект и подпроект с надпроектом; новый — в выборе проектов
    n = c.post("/projects-list", json={"name": "Цех окраски"}, headers=h())
    assert n.status_code == 201, n.text
    sub = c.post("/projects-list", json={"name": "Участок сушки", "parent_id": c.pid}, headers=h())
    assert sub.status_code == 201 and sub.json()["parent_id"] == c.pid
    ids = [p["id"] for p in c.get("/projects-list", headers=h()).json()]
    assert n.json()["id"] in ids and sub.json()["id"] in ids
    # администратор проекта — нет: блок «Создать проект» ему не показывается, сервер отказывает так же
    assert c.post("/projects-list", json={"name": "Цех сварки"}, headers=h("project_admin")).status_code == 403
