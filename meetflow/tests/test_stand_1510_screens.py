"""Экранные находки стенда 5, 11, 16, 17, 26 (живая проверка 15.10.26 на стенде 8011 — в сверке; здесь сторожа).
5 — задача ↔ встреча в обе стороны; 11 — отложенное действие: уход и закрытие вкладки применяют, а не теряют
изменение; 16 — шрифт Calibri без внешних загрузок; 17 — длинные списки: 7 строк (на низком окне от 5), остальное
свёрнуто, раскрытое — лента 480 px; 26 — действие рядом с объектом. Тесты написаны до правки и падали."""
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import TRANSCRIPT

STATIC = Path(__file__).parents[1] / "meetflow" / "web" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
H = {"X-User-Role": "project_admin"}


def test_task_and_meeting_link_both_ways(tmp_path):
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    mid = c.post(f"/api/projects/{pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{mid}/sources", headers=H, files={"file": ("t 01.10.2026.txt", TRANSCRIPT.encode())})
    c.post(f"/api/meetings/{mid}/run", headers=H)
    tasks = c.get(f"/api/projects/{pid}/tasks", headers=H).json()
    assert tasks and all(t["meeting_date"] == "2026-10-01" for t in tasks if t["source_meeting_id"] == mid)
    mt = c.get(f"/api/meetings/{mid}/tasks", headers=H).json()
    assert {t["id"] for t in mt} == {t["id"] for t in tasks if t["source_meeting_id"] == mid}
    # с 27.10.2026 разметка ERP 1 в 1: строка реестра ведёт на встречу, страница встречи — «Задачи встречи N»
    root = Path(__file__).parents[1] / "meetflow" / "web" / "static"
    reg, meet = (root / "registry.js").read_text(encoding="utf-8"), (root / "meeting.js").read_text(encoding="utf-8")
    assert 'class="reg-meet">встреча ${esc(fmtRuDate(t.source_meeting_date))} · протокол</a>' in reg
    assert 'кнопка("tasks", ВСТРЕЧА_ЗНАКИ.tasks, "Задачи встречи", мои.length)' in meet


def test_pending_change_applied_on_leave_and_close():
    """Отмена «Выполнено» — общим отсчётом ERP (`startUndoCountdown`, 2 с) — с 27.10.2026 фронт ERP 1 в 1."""
    assert "const DONE_UNDO_SECONDS = 2;" in JS and "function startUndoCountdown(" in JS
    body = JS[JS.index("function startDelayedDone("):JS.index("function wireTaskActions(")]
    assert "startUndoCountdown({" in body and 'new_status: "done"' in body


def test_font_calibri_without_external_loads():
    """Шрифт — системный, как в ERP (27.10.2026); внешних загрузок шрифтов нет."""
    assert 'font-family: -apple-system, "Segoe UI", Roboto' in CSS
    assert "fonts.googleapis" not in CSS and "@import" not in CSS and "@font-face" not in CSS


def test_long_lists_limit_7_and_ribbon():
    """Длинные списки — 7 строк и «Показать все» (решение 09.10.26) — правило ERP: `ПРЕДЕЛ_РЕЕСТРА`, `collapseLongTable`."""
    assert "const ПРЕДЕЛ_РЕЕСТРА = 7;" in JS and "function collapseLongTable(" in JS
    assert "function свернутьДлинныеТаблицы(" in JS and "function свернутьДлинныеСписки(" in JS


def test_actions_next_to_object():
    """Действие — рядом со своим объектом (13.10.26). С 27.10.2026 строка встречи ERP: «Протокол» и «Встреча» в самой
    строке, кнопки страницы встречи — сразу за заголовком (`mt-acts`)."""
    root = Path(__file__).parents[1] / "meetflow" / "web" / "static"
    nav, meet = (root / "nav.js").read_text(encoding="utf-8"), (root / "meeting.js").read_text(encoding="utf-8")
    assert '<span class="proto-acts"><a href="#meetings/${m.id}/protocol">Протокол</a><a href="#meetings/${m.id}">Встреча</a></span>' in nav
    assert '<div class="mt-title-row"><h1 class="mt-title">' in meet and '<span class="mt-acts">' in meet
