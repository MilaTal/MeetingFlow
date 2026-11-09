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
    assert 'app.js?v=20261109mf88' in html


def test_в_меню_проекта_только_встречи_и_подготовка():
    """Перевёрнуто 09.11.2026 (слово владелицы): задачи и договорённости относятся только к конкретной встрече,
    «Статус проекта» для отдельных встреч не нужен. В меню проекта остаются «Реестр встреч» и «Подготовка встречи»."""
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    начало = js.index("const менюПроектаСтрокой")
    вложенное = js[начало:js.index("const строка =", начало)]
    for надпись in ("Реестр встреч", "Реестр задач", "Подготовка встречи"):
        assert надпись in вложенное, надпись
    # 10.11.2026: «Договорённости по проекту» есть у всех (и у «Общих встреч»); «Статус проекта» — только у
    # заведённых проектов, он внутри условия `п.general ? "" : …`
    assert "п.general ? \"\" :" in вложенное
    for надпись in ("Договорённости по проекту", "Статус проекта"):
        assert надпись in вложенное, надпись
    assert вложенное.index("data-route=\"agreements\"") < вложенное.index("п.general ?"),         "договорённости — вне условия, видны и у «Общих встреч»"
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
