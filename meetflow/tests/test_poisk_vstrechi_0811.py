"""Поиск встречи в левой панели (слово владелицы 08.11.2026: «поиск проекта или встречи»).

Те же буквы, что сужают список проектов, показывают до восьми встреч выбранного охвата — по названию или дате; ссылка
ведёт на встречу. Встречи берутся тем же адресом `GET /meetings`, что и реестр встреч.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from meetflow.web.app import create_app

КОРЕНЬ = Path(__file__).resolve().parents[1]
СТАТИКА = КОРЕНЬ / "meetflow" / "web" / "static"


def test_поле_искало_проект_или_встречу():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert 'placeholder="Поиск проекта или встречи"' in html
    assert 'id="pl-meetings"' in html
    assert 'app.js?v=20261109mf88' in html and 'styles.css?v=20261109mf88' in html


def test_экран_показывает_найденные_встречи():
    js = (СТАТИКА / "app.js").read_text(encoding="utf-8")
    assert "function показатьВстречиПоЗапросу(запрос)" in js
    assert 'api("/meetings")' in js and "slice(0, 8)" in js
    assert 'href="#meetings/${м.id}"' in js
    assert "показатьВстречиПоЗапросу(запрос)" in js            # вызов в конце рисоватьПроекты
    assert "30000" in js                                        # кэш списка на 30 секунд, а не запрос на каждую букву
    css = (СТАТИКА / "styles.css").read_text(encoding="utf-8")
    assert ".pl-meetings" in css and ".pl-meet-name" in css


def test_адрес_встреч_отдаёт_список(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    st = app.state.store
    pid = st.insert("projects", name="П", theme="erp_rollout")
    st.insert("meetings", project_id=pid, date="2026-11-06", label="работа с тендерами")
    h = {"X-User-Role": "super_admin", "X-User-Name": "admin", "X-Project-Id": str(pid)}
    r = c.get("/meetings", headers=h)
    assert r.status_code == 200, r.text
    строки = r.json()
    строки = строки.get("items", []) if isinstance(строки, dict) else строки
    assert any("тендерами" in (м.get("label") or "") for м in строки)
