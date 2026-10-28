"""Общая база компании в MeetFlow — настройка и проверка на живых данных без платных вызовов (задание владелицы 28.10.2026).

База Планёрки открывается только на чтение (`mode=ro`), в неё ничего не пишется. В базу MeetFlow пишутся только настройки
(путь, флаг проекта) — и только с `--apply`. В консоль — числа и названия проектов; ФИО не печатаются.

    # что есть сейчас (ничего не меняет)
    python scripts/obshchaya_baza_2810.py --meetflow-db <meetflow.db>
    # задать путь к базе Планёрки и отметить проект «встречи общей тематики компании»
    python scripts/obshchaya_baza_2810.py --meetflow-db <meetflow.db> --planerka-db <app.db Планёрки> --project <номер> --apply
    # проверить узнавание проекта записи по имени файла (подпапки — через «/»)
    python scripts/obshchaya_baza_2810.py --meetflow-db <meetflow.db> --project <номер> --file "Башнефть/встреча 28.10.2026.m4a"
    # выключить у проекта
    python scripts/obshchaya_baza_2810.py --meetflow-db <meetflow.db> --project <номер> --off --apply
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meetflow.core import obshchaya_baza as ob, proekt_zapisi as pz  # noqa: E402
from meetflow.core.store import Store  # noqa: E402


_НЕТ = object()


def _снимок(st, ключ: str, pid):
    return _НЕТ if not st.q("SELECT id FROM settings WHERE key=? AND project_id IS ?", (ключ, pid)) else         st.get_setting(ключ, pid, None)


def _вернуть(st, ключ: str, pid, было) -> None:
    """Сухой ход: настройка — как была до прогона; не было строки — строка удаляется."""
    if было is _НЕТ:
        with st.tx():
            st._conn.execute("DELETE FROM settings WHERE key=? AND project_id IS ?", (ключ, pid))
    else:
        st.set_setting(ключ, было, pid, "")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")      # консоль Windows в cp1251
    ap = argparse.ArgumentParser()
    ap.add_argument("--meetflow-db", required=True, type=Path)
    ap.add_argument("--planerka-db", type=Path, help="рабочая app.db Планёрки (только чтение)")
    ap.add_argument("--project", type=int, help="номер проекта MeetFlow")
    ap.add_argument("--off", action="store_true", help="снять у проекта «встречи общей тематики компании»")
    ap.add_argument("--file", help="имя файла записи относительно общей папки — показать, какой проект узнаётся")
    ap.add_argument("--apply", action="store_true", help="записать настройки в базу MeetFlow")
    a = ap.parse_args()
    if not a.meetflow_db.exists():
        print("База MeetFlow не найдена:", a.meetflow_db)
        return 2
    st = Store(a.meetflow_db)
    try:
        # сухой ход: настройки ставятся на время прогона и возвращаются как были
        путь_был = _снимок(st, ob.НАСТРОЙКА_ПУТЬ, None)
        флаг_был = _снимок(st, ob.НАСТРОЙКА_ТЕМАТИКА, a.project) if a.project else _НЕТ
        кто = "скрипт общей базы" if a.apply else ""
        if a.planerka_db:
            st.set_setting(ob.НАСТРОЙКА_ПУТЬ, str(a.planerka_db.resolve()), None, кто)
        if a.project and (a.apply or a.planerka_db or a.off):
            st.set_setting(ob.НАСТРОЙКА_ТЕМАТИКА, not a.off, a.project, кто)
        с = ob.сводка(st, a.project)
        print("Путь к базе Планёрки:", с["path"] or "не задан")
        print("Открылась:", "да" if с["ok"] else f"нет — {с['error']}")
        print(f"В базе Планёрки: проектов {с['projects_in_base']}, записей «Команды» {с['people_in_base']}")
        print("Всем проектам:", "да" if с["all_projects"] else "нет")
        if a.project:
            print(f"Проект {a.project}: общая тематика — {'да' if с['company_topic'] else 'нет'}, общая база "
                  f"{'включена' if с['enabled'] else 'не включена'}")
            print(f"  взято проектов {с['projects_taken']} (из них площадок {с['subprojects_taken']}), "
                  f"внешних контактов {с['external_taken']} (с организацией {с['external_with_org']}), "
                  f"своих сотрудников компании {с['internal_taken']}")
            имена = ob.названия_проектов(st, a.project)
            if имена:
                print("  первые названия:", "; ".join(имена[:15]))
            if a.file:
                with tempfile.TemporaryDirectory() as d:
                    общая = Path(d) / "Встречи по всем проектам"
                    файл = общая / a.file
                    файл.parent.mkdir(parents=True, exist_ok=True)
                    файл.write_bytes(b"")
                    итог = pz.проект_файла(st, a.project, общая, файл)
                print(f"  файл «{a.file}» — проект {итог['project_id']} ({итог['how']}); спорные {итог['disputed']}")
        if not a.apply:
            print("Сухой ход: настройки не записаны (для записи — --apply).")
    finally:
        if not a.apply:
            if a.planerka_db:
                _вернуть(st, ob.НАСТРОЙКА_ПУТЬ, None, путь_был)
            if a.project and (a.planerka_db or a.off):
                _вернуть(st, ob.НАСТРОЙКА_ТЕМАТИКА, a.project, флаг_был)
        st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
