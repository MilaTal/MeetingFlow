"""Настройки супер-админа (папка-приёмник, опрос, автозапуск, база голосов)
и мониторинг (приём записей, база голосов, прогоны и расход)."""
import hashlib
import json
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

import pytest
from conftest import TEAM, TRANSCRIPT
from fastapi.testclient import TestClient

from meetflow.connectors.voice_base import voice_base_state
from meetflow.connectors.watch_folder import MARKER
from meetflow.core.intake import HINT_FILE, IntakeError, IntakeService, validate_folder
from meetflow.core.runs_report import runs_report
from meetflow.web.app import create_app

SUPER = {"X-User-Role": "super_admin", "X-User-Name": "admin"}
PASSWORD = "пароль-для-теста"   # тестовое значение учётной записи стенда, не настоящий пароль
ADMIN = {"X-User-Role": "project_admin"}


@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    app.state.accounts.save("admin", "Админ", "super_admin", PASSWORD)   # смена папки — по паролю (11.10.26)
    c.pid = c.post("/api/projects", json={"name": "Пилот"}, headers=SUPER).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=SUPER)
    return c


def _wf(c, a, b=None, h=SUPER, pid=None, password=PASSWORD):
    """Перевёрнут 11.10.26 (владелец: «как в ERP»): смена папки — два шага, второй по паролю супер-администратора.
    Было: один запрос сразу менял папку, и только с машины сервера."""
    url = f"/api/projects/{pid or c.pid}/settings/watch-folder"
    body = {"path": str(a), "path_repeat": str(a if b is None else b)}
    r = c.post(url, json=body, headers=h)
    if r.status_code != 200 or not r.json().get("confirm_needed"):
        return r
    return c.post(url, json={**body, "confirm": True, "login": "admin", "current_password": password}, headers=h)


# ---------------------------------------------------------------- адрес папки
def test_settings_super_admin_only(client):
    assert client.get(f"/api/projects/{client.pid}/settings", headers=ADMIN).status_code == 403
    assert _wf(client, "C:/x", h=ADMIN).status_code == 403
    assert client.get("/api/monitoring/intake", headers=ADMIN).status_code == 403
    assert client.get("/api/monitoring/voice-base", headers=ADMIN).status_code == 403
    assert client.get("/api/monitoring/runs", headers=ADMIN).status_code == 403


def test_repeat_must_match(client, tmp_path):
    r = _wf(client, tmp_path / "in", tmp_path / "inn")
    assert r.status_code == 422 and "не совпадают" in r.json()["detail"]


@pytest.mark.parametrize("bad", ["relative/path", ""])
def test_relative_or_empty_path(client, bad):
    assert _wf(client, bad, bad + "x").status_code == 422 or bad == ""


def test_forbidden_folders(tmp_path):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    for p in (home, home / "Documents", Path(tmp_path.anchor)):
        with pytest.raises(IntakeError):
            validate_folder(str(p), str(p), home=home)


def test_app_folder_forbidden(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "inbox").mkdir(parents=True)
    with pytest.raises(IntakeError, match="приложения"):
        validate_folder(str(app_dir / "inbox"), str(app_dir / "inbox"), app_dir=app_dir, home=tmp_path / "h")


def test_missing_folder_and_file_instead_of_folder(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(IntakeError, match="не найдена"):
        validate_folder(str(tmp_path / "нет"), str(tmp_path / "нет"), home=tmp_path / "h")
    with pytest.raises(IntakeError):
        validate_folder(str(f), str(f), home=tmp_path / "h")


def test_nonempty_without_marker_refused(client, tmp_path):
    d = tmp_path / "busy"
    d.mkdir()
    (d / "чужое.txt").write_text("x")
    r = _wf(client, d)
    assert r.status_code == 422 and "метки" in r.json()["detail"]


def test_empty_folder_gets_marker_and_hint(client, tmp_path):
    d = tmp_path / "Приёмник"
    d.mkdir()
    r = _wf(client, d)
    assert r.status_code == 200 and r.json()["folder"] == str(d) and r.json()["marker"]
    assert (d / MARKER).exists() and (d / HINT_FILE).exists()


def test_change_is_logged_and_can_be_disabled(client, tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    _wf(client, d)
    dec = client.get(f"/api/projects/{client.pid}/decisions", headers=SUPER).json()
    assert any("Папка-приёмник" in x["what"] and "admin" in x["why"] for x in dec)
    assert _wf(client, "", "").json()["folder"] is None
    tech = client.get("/api/monitoring", headers=SUPER).json()["technical_messages"]
    assert any("адрес папки-приёмника" in t["title"] for t in tech)


def test_one_folder_per_project(client, tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    _wf(client, d)
    p2 = client.post("/api/projects", json={"name": "Второй"}, headers=SUPER).json()["id"]
    r = _wf(client, d, pid=p2)
    assert r.status_code == 422 and "другого проекта" in r.json()["detail"]


def test_remote_client_changes_path_only_with_password(tmp_path):
    """Перевёрнут 11.10.26: было «адрес меняется только с компьютера сервера», стало — с любого адреса, но по паролю
    супер-администратора, как в Планёрке и ERP с 07.10.26."""
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    app.state.accounts.save("admin", "Админ", "super_admin", PASSWORD)

    async def remote(scope, receive, send):  # запрос как будто с другого компьютера сети
        if scope["type"] == "http":
            scope = dict(scope, client=("10.0.0.5", 50000))
        await app(scope, receive, send)

    c = TestClient(remote)
    pid = c.post("/api/projects", json={"name": "П"}, headers=SUPER).json()["id"]
    d = tmp_path / "in"
    d.mkdir()
    url, body = f"/api/projects/{pid}/settings/watch-folder", {"path": str(d), "path_repeat": str(d)}
    assert c.post(url, json=body, headers=SUPER).json()["confirm_needed"]
    bad = c.post(url, json={**body, "confirm": True, "login": "admin", "current_password": "не тот"}, headers=SUPER)
    assert bad.status_code == 403 and "Неверный" in bad.json()["detail"]
    ok = c.post(url, json={**body, "confirm": True, "login": "admin", "current_password": PASSWORD}, headers=SUPER)
    assert ok.status_code == 200 and ok.json()["folder"] == str(d)


def test_first_step_changes_nothing_and_previews(client, tmp_path):
    """Шаг 1 — только вопрос и предпросмотр: папка не меняется и не подписывается до пароля."""
    d = tmp_path / "in"
    d.mkdir()
    (d / MARKER).write_text("метка", encoding="utf-8")
    (d / "Встреча 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    (d / "без даты.txt").write_text("x", encoding="utf-8")
    url = f"/api/projects/{client.pid}/settings/watch-folder"
    r = client.post(url, json={"path": str(d), "path_repeat": str(d)}, headers=SUPER).json()
    assert r["confirm_needed"] and r["preview"]["files"] == 2 and r["preview"]["first_pass"] == 1
    assert r["preview"]["no_date"] == ["без даты.txt"] and "первый проход заберёт 1" in r["question"]
    assert client.get(f"/api/projects/{client.pid}/settings", headers=SUPER).json()["intake"]["folder"] is None
    e = tmp_path / "empty"
    e.mkdir()
    client.post(url, json={"path": str(e), "path_repeat": str(e)}, headers=SUPER)
    assert not (e / MARKER).exists()                       # подпись — только после пароля


def test_no_super_admin_account_means_clear_refusal(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "П"}, headers=SUPER).json()["id"]
    d = tmp_path / "in"
    d.mkdir()
    r = c.post(f"/api/projects/{pid}/settings/watch-folder", json={"path": str(d), "path_repeat": str(d), "confirm": True,
               "login": "admin", "current_password": "x"}, headers=SUPER)
    assert r.status_code == 400 and "учётную запись супер-администратора" in r.json()["detail"]


def test_interval_bounds(client):
    url = f"/api/projects/{client.pid}/settings/watch-interval"
    assert client.post(url, json={"seconds": 5}, headers=SUPER).status_code == 422
    assert client.post(url, json={"seconds": 60}, headers=SUPER).json()["interval"] == 60


# ---------------------------------------------------------------- забор файлов
@pytest.fixture
def svc(client, tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    assert _wf(client, d).status_code == 200
    s = client.app.state.intake
    s.d = d
    return s


def _scan_twice(svc, pid):
    today = date(2026, 10, 3)
    svc._intakes.pop(pid, None)
    svc.scan_project(pid, today)          # первый проход — файл «оседает»
    return svc.scan_project(pid, today)


def test_transcript_ingested_into_meeting_by_date_and_moved(client, svc):
    (svc.d / "Расшифровка 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    r = _scan_twice(svc, client.pid)
    assert r["ingested"] == ["Расшифровка 01.10.2026.txt"]
    assert (svc.d / "обработано" / "Расшифровка 01.10.2026.txt").exists()
    m = client.app.state.store.q("SELECT * FROM meetings WHERE project_id=?", (client.pid,))
    assert m[0]["date"] == "2026-10-01" and m[0]["label"] == "из папки-приёмника"


def test_no_date_reported_once_and_stays(client, svc):
    (svc.d / "без даты.txt").write_text(TRANSCRIPT, encoding="utf-8")
    r = _scan_twice(svc, client.pid)
    assert r["no_date"] == ["без даты.txt"] and (svc.d / "без даты.txt").exists()
    r2 = svc.scan_project(client.pid, date(2026, 10, 3))
    assert r2["no_date"] == []
    tech = [c for c in client.app.state.store.q("SELECT title FROM cards WHERE kind='technical'") if "без даты" in c["title"]]
    assert len(tech) == 1


def test_duplicate_of_manual_upload(client, svc):
    mid = client.post(f"/api/projects/{client.pid}/meetings", json={"date": "2026-10-01"}, headers=SUPER).json()["id"]
    client.post(f"/api/meetings/{mid}/sources", files={"file": ("ручная.txt", TRANSCRIPT.encode())}, headers=SUPER)
    (svc.d / "копия 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    r = _scan_twice(svc, client.pid)
    assert "копия 01.10.2026.txt" in r["duplicates"] and (svc.d / "обработано" / "копия 01.10.2026.txt").exists()


def test_rejected_file_stays_with_one_card(client, svc):
    (svc.d / "мусор 01.10.2026.txt").write_bytes(b"\x00\x01\x02" * 50)
    r = _scan_twice(svc, client.pid)
    assert r["rejected"] == ["мусор 01.10.2026.txt"] and (svc.d / "мусор 01.10.2026.txt").exists()


def test_recording_without_asr_waits(client, svc, monkeypatch):
    asr = client.app.state.pipe.plugins.get("asr", "whisper_local")
    monkeypatch.setattr(asr, "available", lambda: False)
    (svc.d / "запись 01.10.2026.mp4").write_bytes(b"\x00media")
    r = _scan_twice(svc, client.pid)
    assert r["held"] == ["запись 01.10.2026.mp4"] and (svc.d / "запись 01.10.2026.mp4").exists()


def test_autorun_builds_protocol(client, svc):
    client.post(f"/api/projects/{client.pid}/settings/autorun", json={"enabled": True}, headers=SUPER)
    (svc.d / "Расшифровка 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    r = _scan_twice(svc, client.pid)
    assert r["autorun"][0]["status"] == "ok"
    m = client.app.state.store.q("SELECT protocol_md FROM meetings WHERE project_id=?", (client.pid,))[0]
    assert m["protocol_md"].startswith("# Протокол встречи 01.10.2026")


def test_unavailable_folder_is_not_empty_success(client, svc):
    import shutil
    shutil.rmtree(svc.d)
    r = svc.scan_project(client.pid)
    assert r["status"] == "unavailable"
    # список приёмников открывается «Общими встречами» (Доработка 2, 28.10.2026) — проект ищется по номеру
    st = next(x for x in client.get("/api/monitoring/intake", headers=SUPER).json() if x["project_id"] == client.pid)
    assert st["last_scan"]["status"] == "unavailable"


def test_last_useful_scan_kept(client, svc):
    (svc.d / "Расшифровка 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    _scan_twice(svc, client.pid)
    svc.scan_project(client.pid, date(2026, 10, 3))   # пустой проход
    st = next(x for x in client.get("/api/monitoring/intake", headers=SUPER).json() if x["project_id"] == client.pid)
    assert st["last_scan"]["ingested"] == [] and st["last_useful_scan"]["ingested"]


def test_background_worker_scans_and_stops(client, svc):
    client.app.state.store.set_setting("watch_interval", 0, client.pid)
    (svc.d / "Расшифровка 01.10.2026.txt").write_text(TRANSCRIPT, encoding="utf-8")
    svc.start(tick=0.05)
    deadline = time.time() + 5
    while time.time() < deadline and not (svc.d / "обработано").exists():
        time.sleep(0.05)
    svc.stop()
    assert (svc.d / "обработано" / "Расшифровка 01.10.2026.txt").exists() and not svc.running


# ---------------------------------------------------------------- база голосов
def _voice_db(path: Path, contract=True):
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    if contract:
        con.execute("CREATE TABLE voice_person (id INTEGER PRIMARY KEY, full_name TEXT UNIQUE, aliases TEXT, confirmed INTEGER)")
        con.execute("CREATE TABLE voice_sample (id INTEGER PRIMARY KEY, person_id INTEGER, embedding BLOB, "
                    "embedding_model TEXT, origin_project TEXT, created_at TEXT)")
        con.executemany("INSERT INTO voice_person (full_name, confirmed) VALUES (?, ?)",
                        [("Игнатов Иван", 1), ("Петрова Анастасия", 0)])
        con.executemany("INSERT INTO voice_sample (person_id, embedding_model, origin_project, created_at) VALUES (?,?,?,?)",
                        [(1, "wespeaker-34", "planerka", "2026-10-01"), (None, "wespeaker-34", "erp", "2026-10-02"),
                         (2, "wespeaker-34", "planerka", "2026-10-02")])
    else:
        con.execute("CREATE TABLE voice_person (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()


def test_voice_base_not_set_and_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("VOICE_BASE_PATH", raising=False)
    assert "не задан" in voice_base_state(None)["detail"]
    assert "не найден" in voice_base_state(str(tmp_path / "нет.db"))["detail"]
    assert "папка" in voice_base_state(str(tmp_path))["detail"]


def test_voice_base_counts_read_only(tmp_path):
    db = tmp_path / "voices.db"
    _voice_db(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    st = voice_base_state(str(db))
    assert st["ok"] and st["samples"] == 3 and st["samples_linked"] == 2
    assert st["people_confirmed"] == 1 and st["people_waiting"] == 1
    assert st["by_project"] == {"planerka": 2, "erp": 1} and st["embedding_models"] == {"wespeaker-34": 3}
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before          # только чтение


def test_voice_base_contract_violation(tmp_path):
    db = tmp_path / "v.db"
    _voice_db(db, contract=False)
    st = voice_base_state(str(db))
    assert not st["ok"] and "не по договору" in st["detail"]


def test_voice_base_via_settings_and_monitoring(client, tmp_path):
    db = tmp_path / "voices.db"
    _voice_db(db)
    pw = {"login": "admin", "current_password": PASSWORD}     # как смена папки — по паролю (11.10.26)
    r = client.post("/api/settings/voice-base", json={"path": str(db), "path_repeat": str(db), **pw}, headers=SUPER)
    assert r.status_code == 200 and r.json()["samples"] == 3
    assert client.get("/api/monitoring/voice-base", headers=SUPER).json()["people"] == 2
    assert client.post("/api/settings/voice-base", json={"path": "a.db", "path_repeat": "a.db"}, headers=SUPER).status_code == 422


# ---------------------------------------------------------------- прогоны и расход
def test_runs_report_aggregates(tmp_path):
    j = tmp_path / "j.jsonl"
    rows = [{"ts": "2026-10-03T10:00:00", "purpose": "extract_tasks", "model": "glm", "cost_usd": 0.01, "seconds": 2, "chars": 1000},
            {"ts": "2026-10-03T10:00:05", "purpose": "verify", "model": "ds", "cost_usd": 0.02, "seconds": 3, "chars": 500},
            {"ts": "2026-10-03T10:00:06", "run": 1, "status": "ok", "calls": 2, "cost_usd": 0.03, "added": 1},
            {"ts": "2026-10-03T11:00:00", "run": 2, "stopped_by": "cost", "calls": 5, "cost_usd": 0.4},
            {"ts": "2026-09-01T10:00:00", "purpose": "verify", "model": "ds", "cost_usd": 9.0}]
    j.write_text("\n".join(json.dumps(r) for r in rows) + "\n{битая строка\n", encoding="utf-8")
    r = runs_report(j, 7, {"max_calls": 14}, now=datetime(2026, 10, 3, 12))
    assert r["calls"] == 2 and r["cost_usd"] == 0.03 and r["broken_lines"] == 1
    assert r["runs_total"] == 2 and r["runs_stopped"] == 1 and r["runs"][0]["status"] == "stopped_by_limit"
    assert r["by_purpose"]["verify"]["calls"] == 1 and r["by_day"] == {"2026-10-03": {"calls": 2, "cost_usd": 0.03, "seconds": 5.0, "chars": 1500}}
    assert r["cost_per_success_usd"] == 0.03 and r["limits"]["max_calls"] == 14


def test_runs_report_empty(tmp_path):
    assert runs_report(tmp_path / "нет.jsonl")["calls"] == 0


def test_runs_monitoring_after_real_run(client):
    mid = client.post(f"/api/projects/{client.pid}/meetings", json={"date": "2026-10-01"}, headers=SUPER).json()["id"]
    client.post(f"/api/meetings/{mid}/sources", files={"file": ("t 01.10.2026.txt", TRANSCRIPT.encode())}, headers=SUPER)
    client.post(f"/api/meetings/{mid}/run", headers=SUPER)
    r = client.get("/api/monitoring/runs", headers=SUPER).json()
    assert r["calls"] >= 3 and r["runs_total"] == 1 and r["runs"][0]["status"] == "ok"
    assert set(r["by_purpose"]) >= {"extract_tasks", "protocol", "verify"}


def test_ui_is_laid_out_like_erp():
    """Владелец 11.10.26: левое меню суперадминистратора и вкладки «Параметров системы» — как в ERP. С 27.10.2026 фронт
    MeetFlow — фронт ERP целиком: те же пункты и те же вкладки."""
    root = Path(__file__).resolve().parents[1] / "meetflow/web/static"
    js, nav, html = ((root / f).read_text(encoding="utf-8") for f in ("app.js", "nav.js", "index.html"))
    for route, label in (("system", "Параметры системы"), ("live", "Мониторинг RealTime"), ("models", "Модели"),
                         ("voices", "База голосов"), ("voice-review", "Разбор голосов")):
        assert f'data-route="{route}" href="#{route}" hidden>{label}' in html
    assert 'data-route="settings"' not in html and 'data-route="monitoring"' not in html
    for tab in ("Системные сообщения", "Ожидает ввода от оператора", "Прогоны", "Расход", "Состояние базы",
                "Диск и доступы", "Настройки", "Реестр решений"):
        assert f'label: "{tab}"' in nav
    assert "function changeWatchFolder" in js and "renderMonitoringLive" in js


def test_same_text_with_crlf_is_duplicate(tmp_path):
    """Тот же текст с концами строк Windows — не новый источник (найдено при тесте папки)."""
    from meetflow.core.types import SourceDoc, SourceKind
    a = SourceDoc("a", SourceKind.TRANSCRIPT, "строка 1\nстрока 2\n")
    b = SourceDoc("b", SourceKind.TRANSCRIPT, "строка 1  \r\nстрока 2\r\n")
    assert a.content_digest == b.content_digest
