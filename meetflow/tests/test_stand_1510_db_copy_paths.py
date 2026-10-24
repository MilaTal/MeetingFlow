"""Находки стенда 22 и 21. 22 (ERP и Планёрка, стенд): копия базы на другом месте не должна дотягиваться до файлов
прежнего места. В MeetFlow свои файлы в базе не хранятся по путям (тексты — в базе), но в ней записаны внешние папки —
папка-приёмник и база голосов: копия, открытая на другом месте, забирала бы файлы из папки прежней установки. Теперь
база помнит, где лежит; открыта в другом месте — ссылки на внешние папки откладываются до подтверждения, системное
сообщение. 21: то, что ждёт человека (карточки), переживает перезапуск. Тесты написаны до правки; 22 падал."""
import shutil

from fastapi.testclient import TestClient

H = {"X-User-Role": "project_admin"}


def test_db_copy_does_not_reach_previous_folders(tmp_path):
    from meetflow.web.app import create_app
    a = tmp_path / "a" / "t.db"
    app = create_app("erp_rollout", str(a), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    inbox = tmp_path / "приёмник"
    inbox.mkdir()
    app.state.store.set_setting("watch_folder", str(inbox), pid)
    app.state.store.set_setting("voice_base_path", str(tmp_path / "voices.db"))
    b = tmp_path / "b" / "t.db"
    b.parent.mkdir()
    shutil.copy(a, b)
    copy = create_app("erp_rollout", str(b), str(tmp_path / "j2.jsonl"), watch=False)
    s = copy.state.store
    assert s.get_setting("watch_folder", pid) is None and s.get_setting("voice_base_path") is None
    assert s.get_setting("watch_folder_previous", pid) == str(inbox)
    assert s.q("SELECT * FROM cards WHERE title LIKE 'База открыта на новом месте%'")
    assert app.state.store.get_setting("watch_folder", pid) == str(inbox), "прежняя установка не тронута"
    again = create_app("erp_rollout", str(a), str(tmp_path / "j3.jsonl"), watch=False)
    assert again.state.store.get_setting("watch_folder", pid) == str(inbox), "на своём месте — ничего не трогаем"


def test_pending_decisions_survive_restart(tmp_path):
    from meetflow.web.app import create_app
    db = tmp_path / "t.db"
    app = create_app("erp_rollout", str(db), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    tid = app.state.pipe.reg.add(pid, "Подготовить регламент", None, doubt_reason="это вопрос, а не поручение")
    app.state.pipe.cards.open(pid, "task_doubt", "Задача под вопросом: Подготовить регламент", {"task_id": tid}, None)
    app2 = create_app("erp_rollout", str(db), str(tmp_path / "j.jsonl"), watch=False)    # перезапуск
    c2 = TestClient(app2)
    cards = [x for x in c2.get(f"/api/projects/{pid}/cards", headers=H).json() if x["kind"] == "task_doubt"]
    assert len(cards) == 1
    r = c2.post(f"/api/cards/{cards[0]['id']}/resolve", json={"status": "accepted"}, headers=H)
    assert r.status_code == 200 and app2.state.store.get("tasks", tid)["doubt_reason"] == ""
