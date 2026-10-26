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
    assert 'class="sub task-meeting" href="#meeting/' in JS and "— протокол</a>" in JS and "Задачи встречи · " in JS


def test_pending_change_applied_on_leave_and_close():
    assert 'window.addEventListener("pagehide", () => flushChanges(true));' in JS
    assert "keepalive: true" in JS and "if (pendingChange.size) await flushChanges();" in JS
    body = JS[JS.index("function undoable("):JS.index('window.addEventListener("pagehide"')]
    assert body.index("flushChanges();") < body.index("pendingChange.set(id")      # повторный вызов — сначала прежняя


def test_font_calibri_without_external_loads():
    assert "--font: Calibri, Carlito, system-ui" in CSS
    assert "fonts.googleapis" not in CSS and "Onest" not in CSS
    assert "@import" not in CSS and "@font-face" not in CSS


def test_long_lists_limit_7_and_ribbon():
    assert "const listLimit = () => (window.innerHeight < 720 ? 5 : 7);" in JS
    assert ".ribbon { max-height: 480px; overflow: auto;" in CSS
    for marker in ('moreRows("<tr><th>Дата</th><th>Название</th></tr>"', 'moreRows("<tr><th>№</th><th>ФИО</th>',
                   "moreItems(visible, (c) =>", 'moreRows("<tr><th>Проект</th><th>Что</th>', "moreItems(rows, (t) =>",
                   'moreRows("", d.history', "moreItems(mtasks,", "moreItems(proto.units,"):
        assert marker in JS, marker
    assert "dec.slice(0, 3)" not in JS and "history.slice(0, 6)" not in JS
    assert "trs.slice(1, 6)" in JS                                    # реестр на низком окне — от 5 строк


def test_actions_next_to_object():
    assert '<th>Протокол</th>' not in JS and '` <a class="sub" href="#meeting/${m.id}">протокол →</a>`' in JS
    assert 'justify-content:space-between;align-items:baseline"><h1>' not in JS          # выгрузка за заголовком
    assert '<div class="row" style="justify-content:flex-end"><button class="btn" id="msg-all">' not in JS
    assert 'style="white-space:nowrap; text-align:right"><button class="btn btn-outline" data-ep-edit' not in JS
    assert '<td style="text-align:right"><button class="btn-link" data-route-remove' not in JS
