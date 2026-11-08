"""Блок под чертой в левом меню убран (слово владелицы 08.11.2026: «вторым блоком под чертой есть меню — реестр,
список задачи и т. п. — он лишний и не понятный»).

Пункты «Актуализировать задачи из реестра», «Инфо по проекту», «Договорённости по проекту», «Статус проекта» остались
скрытыми в общем меню; всё это живёт в меню проекта под его строкой (вариант А, mf59): Реестр встреч, Подготовка
встречи, Договорённости по проекту, Статус проекта (у «Общих встреч» — без статуса).
"""
from __future__ import annotations

import re
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
СТАТИКА = КОРЕНЬ / "meetflow" / "web" / "static"


def test_все_пункты_блока_скрыты():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    for образец in ('data-route="dashboard" href="#dashboard" hidden',
                    'id="nav-info" hidden',
                    'id="nav-agreements" href="#agreements" hidden',
                    'data-route="status" href="#status" hidden'):
        assert образец in html, образец
    assert 'app.js?v=20261108mf71' in html


def test_меню_проекта_держит_те_же_пункты():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    вложенное = js[js.index("function рисоватьПроекты"):]
    вложенное = вложенное[:вложенное.index("function полеПроекта")]
    for надпись in ("Реестр встреч", "Подготовка встречи", "Договорённости по проекту", "Статус проекта"):
        assert надпись in вложенное, надпись
    assert 'п.general ? "" : `<a class="pl-nested-item" data-route="status"' in js, "у «Общих встреч» статуса нет"
    assert "эл.hidden = true" in js, "сторож не даёт показать скрытые пункты в общем меню"


def test_на_экране_блок_скрыт_а_меню_проекта_на_месте(tmp_path):
    from fastapi.testclient import TestClient
    from meetflow.web.app import create_app

    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    html = c.get("/").text
    for образец in ('id="nav-info" hidden', 'data-route="dashboard" href="#dashboard" hidden'):
        assert образец in html, образец
    assert "pl-nested-item" in (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert re.search(r'<title>Встречи Невалаб</title>', html)
