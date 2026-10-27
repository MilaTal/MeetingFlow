"""Уровни доступа «Команды» MeetFlow — 1 в 1 как в рабочей Планёрке (задание владелицы 27.10.2026).

После переноса фронта ERP «Команда» MeetFlow завела людей проектов записями с ролью «участник»: у прежнего MeetFlow
уровней доступа у сотрудников не было (роль выбиралась в тестовом режиме). Источник ролей — рабочая Планёрка
(`users.access_role`: member / director / project_admin / super_admin), база открывается только на чтение.

Сопоставление — по ФИО без регистра и лишних пробелов, «е» = «ё». Что делает:
- у найденного в «Команде» MeetFlow — роль как в Планёрке, если отличается;
- человек Планёрки с ролью выше «участника», которого нет в «Команде» MeetFlow, — заводится записью «Команды» без
  логина с этой ролью (иначе его уровень доступа некуда перенести); участники не заводятся — «Команда» проекта своя;
- внешние (организация) — только «участник», как правило «Команды» ERP;
- роли MeetFlow, которых нет в Планёрке, не трогаются, о них — строка в выводе;
- логины и пароли не переносятся: доступ (логин и временный пароль) выдаёт суперадмин в «Команде».

Запуск (сначала сухой ход, потом применение):
    python scripts/roli_iz_planerki_2710.py --planerka-db <путь к app.db Планёрки> --meetflow-db <путь к meetflow.db>
    python scripts/roli_iz_planerki_2710.py ... --apply
Перед применением делается копия базы MeetFlow рядом (`meetflow.db.до-ролей-2710`). Вывод с ФИО — в `--out` (по
умолчанию рядом с базой MeetFlow, вне git); в консоль — только числа.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROLES = ("member", "director", "project_admin", "super_admin")
WORDS = {"super_admin": "суперадмин", "project_admin": "администратор", "director": "директор", "member": "участник"}


def norm(s: str | None) -> str:
    return " ".join((s or "").replace("ё", "е").replace("Ё", "Е").lower().split())


def role_of(v) -> str:
    r = str(v or "member").strip()
    r = r.split(".")[-1]          # Enum мог сохраниться как «AccessRole.project_admin»
    return r if r in ROLES else "member"


def planerka_people(path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
    ext = "is_external" if "is_external" in cols else "0"
    act = "is_active" if "is_active" in cols else "1"
    rows = [dict(r) for r in con.execute(
        f"SELECT full_name, access_role, {ext} AS external, {act} AS active FROM users")]
    con.close()
    return rows


def plan(pl: list[dict], mf: sqlite3.Connection) -> dict:
    mf.row_factory = sqlite3.Row
    accounts = [dict(r) for r in mf.execute("SELECT id, full_name, role, COALESCE(external,0) AS external FROM accounts")]
    by_name: dict[str, list[dict]] = {}
    for a in accounts:
        by_name.setdefault(norm(a["full_name"]), []).append(a)
    seen: set[str] = set()
    out = {"change": [], "same": [], "create": [], "skip_member_absent": 0, "double": [], "external_kept": [],
           "inactive": []}
    for p in pl:
        key = norm(p["full_name"])
        if not key or key in seen:
            continue
        seen.add(key)
        want = role_of(p["access_role"])
        if not p.get("active", 1):
            out["inactive"].append(p["full_name"])
            continue
        if p.get("external") and want != "member":
            want = "member"
        found = by_name.get(key, [])
        if len(found) > 1:
            out["double"].append((p["full_name"], want, [a["id"] for a in found]))
            continue
        if found:
            a = found[0]
            have = a["role"] or "member"
            if a["external"] and want != "member":
                out["external_kept"].append((a["full_name"], want))
            elif have != want:
                out["change"].append((a["id"], a["full_name"], have, want))
            else:
                out["same"].append((a["full_name"], have))
        elif want != "member":
            out["create"].append((p["full_name"], want))
        else:
            out["skip_member_absent"] += 1
    pl_keys = seen
    out["mf_only"] = [(a["full_name"], a["role"] or "member") for a in accounts
                      if norm(a["full_name"]) not in pl_keys and (a["role"] or "member") != "member"]
    return out


def apply(res: dict, mf: sqlite3.Connection) -> None:
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    cols = {r[1] for r in mf.execute("PRAGMA table_info(accounts)")}
    with mf:
        for aid, _fio, _have, want in res["change"]:
            mf.execute("UPDATE accounts SET role=? WHERE id=?", (want, aid))
        for fio, want in res["create"]:
            vals = {"login": None, "full_name": " ".join(fio.split()), "role": want, "password_hash": "", "active": 1,
                    "failed_attempts": 0, "created_at": now, "position": "", "project_role": "", "department": "",
                    "external": 0, "organization": "", "confirmed": 1, "confirmed_source": "Планёрка, роли 27.10"}
            vals = {k: v for k, v in vals.items() if k in cols}
            mf.execute(f"INSERT INTO accounts ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                       tuple(vals.values()))


def report(res: dict, applied: bool) -> str:
    L = [f"# Роли «Команды» MeetFlow из Планёрки — {'применено' if applied else 'сухой ход'} "
         f"({datetime.now().strftime('%d.%m.%Y %H:%M')})", ""]
    L.append(f"Сменить роль: {len(res['change'])}; уже так же: {len(res['same'])}; завести с ролью: {len(res['create'])}; "
             f"участники Планёрки, которых нет в MeetFlow (не заводятся): {res['skip_member_absent']}; "
             f"двойники по ФИО (не тронуты): {len(res['double'])}; внешние с ролью выше участника в Планёрке: "
             f"{len(res['external_kept'])}; отключённые в Планёрке (не тронуты): {len(res['inactive'])}; "
             f"роль выше участника только в MeetFlow (не тронута): {len(res['mf_only'])}.")
    L += ["", "| ФИО | В MeetFlow было | Как в Планёрке | Что сделано |", "|---|---|---|---|"]
    for _aid, fio, have, want in res["change"]:
        L.append(f"| {fio} | {WORDS[have] if have in WORDS else have} | {WORDS[want]} | роль сменена |")
    for fio, want in res["create"]:
        L.append(f"| {fio} | нет в «Команде» | {WORDS[want]} | заведён без логина |")
    for fio, have in res["same"]:
        if have != "member":
            L.append(f"| {fio} | {WORDS.get(have, have)} | {WORDS.get(have, have)} | так же |")
    for fio, want, ids in res["double"]:
        L.append(f"| {fio} | двойник: записи {ids} | {WORDS[want]} | не тронуто — решить вручную |")
    for fio, want in res["external_kept"]:
        L.append(f"| {fio} | внешний | {WORDS[want]} | оставлен участником (внешним доступ не выдаётся) |")
    for fio, have in res["mf_only"]:
        L.append(f"| {fio} | {WORDS.get(have, have)} | нет в Планёрке | не тронуто |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--planerka-db", required=True, type=Path)
    ap.add_argument("--meetflow-db", required=True, type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    for p in (a.planerka_db, a.meetflow_db):
        if not p.is_file():
            print(f"нет файла: {p}", file=sys.stderr)
            return 2
    pl = planerka_people(a.planerka_db)
    if a.apply:
        shutil.copy2(a.meetflow_db, a.meetflow_db.with_name(a.meetflow_db.name + ".до-ролей-2710"))
    mf = sqlite3.connect(a.meetflow_db)
    res = plan(pl, mf)
    if a.apply:
        apply(res, mf)
    mf.close()
    out = a.out or a.meetflow_db.with_name("Роли из Планёрки (27.10.2026).md")
    out.write_text(report(res, a.apply), encoding="utf-8")
    print(f"{'применено' if a.apply else 'сухой ход'}: сменить {len(res['change'])}, завести {len(res['create'])}, "
          f"так же {len(res['same'])}, двойников {len(res['double'])}, только в MeetFlow {len(res['mf_only'])}; "
          f"подробно (с ФИО, вне git): {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
