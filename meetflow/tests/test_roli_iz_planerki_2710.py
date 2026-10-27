"""27.10.2026: уровни доступа «Команды» MeetFlow — 1 в 1 как в Планёрке (scripts/roli_iz_planerki_2710.py).
ФИО вымышленные."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import roli_iz_planerki_2710 as rp  # noqa: E402

from meetflow.web.app import create_app  # noqa: E402


def _planerka(tmp_path):
    p = tmp_path / "planerka.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, access_role TEXT, is_external INT, "
                "is_active INT)")
    con.executemany("INSERT INTO users (full_name, access_role, is_external, is_active) VALUES (?,?,?,?)", [
        ("Иванов Пётр Сергеевич", "project_admin", 0, 1),
        ("Сидорова Анна Олеговна", "super_admin", 0, 1),
        ("Козлов Илья Андреевич", "director", 0, 1),
        ("Новиков Олег Петрович", "project_admin", 0, 1),     # нет в MeetFlow — завести
        ("Орлова Мария Ивановна", "member", 0, 1),             # нет в MeetFlow, участник — не заводить
        ("Внешний Глеб Юрьевич", "project_admin", 1, 1),       # внешний — только участник
        ("Отключён Ян Янович", "project_admin", 0, 0),
    ])
    con.commit()
    con.close()
    return p


def _meetflow(tmp_path):
    db = tmp_path / "mf.db"
    app = create_app("erp_rollout", str(db), str(tmp_path / "j.jsonl"), watch=False)
    s = app.state.store
    for fio, role, ext in (("Иванов Петр Сергеевич", "member", 0), ("Сидорова Анна Олеговна", "member", 0),
                           ("Козлов Илья Андреевич", "director", 0), ("Внешний Глеб Юрьевич", "member", 1),
                           ("Только Мф Админ", "project_admin", 0)):
        s.insert("accounts", login=None, full_name=fio, role=role, password_hash="", active=1, failed_attempts=0,
                 created_at="2026-10-27T10:00:00", external=ext)
    return db


def _roles(db):
    con = sqlite3.connect(db)
    r = {n: role for n, role in con.execute("SELECT full_name, role FROM accounts")}
    con.close()
    return r


def test_dry_run_changes_nothing_and_apply_copies_roles(tmp_path):
    pl, mf = _planerka(tmp_path), _meetflow(tmp_path)
    before = _roles(mf)
    assert rp.main(["--planerka-db", str(pl), "--meetflow-db", str(mf)]) == 0
    assert _roles(mf) == before, "сухой ход ничего не меняет"
    assert rp.main(["--planerka-db", str(pl), "--meetflow-db", str(mf), "--apply"]) == 0
    r = _roles(mf)
    assert r["Иванов Петр Сергеевич"] == "project_admin"          # «е» = «ё»
    assert r["Сидорова Анна Олеговна"] == "super_admin"
    assert r["Козлов Илья Андреевич"] == "director"
    assert r["Новиков Олег Петрович"] == "project_admin"           # заведён с ролью
    assert "Орлова Мария Ивановна" not in r                       # участник не заводится
    assert r["Внешний Глеб Юрьевич"] == "member"                  # внешнему доступ не выдаётся
    assert "Отключён Ян Янович" not in r
    assert r["Только Мф Админ"] == "project_admin"                 # роль только в MeetFlow не тронута
    assert (mf.parent / "mf.db.до-ролей-2710").is_file()
    rep = (mf.parent / "Роли из Планёрки (27.10.2026).md").read_text(encoding="utf-8")
    assert "Сменить роль: 2" in rep and "завести с ролью: 1" in rep
    assert rp.main(["--planerka-db", str(pl), "--meetflow-db", str(mf), "--apply"]) == 0
    assert "Сменить роль: 0" in (mf.parent / "Роли из Планёрки (27.10.2026).md").read_text(encoding="utf-8")


def test_planerka_db_opened_read_only(tmp_path):
    pl, mf = _planerka(tmp_path), _meetflow(tmp_path)
    m = pl.stat().st_mtime_ns
    rp.main(["--planerka-db", str(pl), "--meetflow-db", str(mf), "--apply"])
    assert pl.stat().st_mtime_ns == m
