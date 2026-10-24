"""Командная строка MeetFlow.

  python -m meetflow themes                      — список тем
  python -m meetflow todo --theme erp_rollout    — заглушки, ждущие оператора
  python -m meetflow new-project "Имя" --theme daily_ops --db data/x.db
  python -m meetflow demo --theme it_product --db data/demo.db
  python -m meetflow serve --theme erp_rollout --port 8002
  python -m meetflow routes show | use generate <точка> | check   — маршруты моделей (models.json)
"""
from __future__ import annotations

import argparse
import os
import sys

from .core.config import list_themes, load_theme
from .core.store import Store

DEMO_TEXT = """[00:00:05] Орлова Мария: Доброе утро, начинаем.
[00:01:10] Белов Сергей: Отчёт по тестам отправил вчера, сделано.
[00:02:20] Орлова Мария: Белов Сергей, подготовьте план релиза до 15.10
[00:03:05] Орлова Мария: Гаврилова Анна, проверьте доступы к стенду
[00:04:00] Гаврилова Анна: А нужно ли переносить демо?
[00:05:30] Орлова Мария: Калинин Олег, согласуйте бюджет с финансами
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="meetflow")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("themes")
    t = sub.add_parser("todo"); t.add_argument("--theme", default="_default")
    n = sub.add_parser("new-project"); n.add_argument("name"); n.add_argument("--theme", default="_default")
    n.add_argument("--db", default="data/meetflow.db")
    d = sub.add_parser("demo"); d.add_argument("--theme", default="_default"); d.add_argument("--db", default="data/demo.db")
    s = sub.add_parser("serve"); s.add_argument("--theme", default="_default"); s.add_argument("--db", default="data/meetflow.db")
    s.add_argument("--port", type=int, default=8002); s.add_argument("--host", default="127.0.0.1")
    r = sub.add_parser("routes"); r.add_argument("action", choices=("show", "use", "check"))
    r.add_argument("role", nargs="?"); r.add_argument("point", nargs="?")
    sp = sub.add_parser("set-password", help="учётная запись для входа по паролю; пароль спрашивается скрыто")
    sp.add_argument("--login", required=True); sp.add_argument("--name", default="")
    sp.add_argument("--role", default="super_admin"); sp.add_argument("--db", default="data/meetflow.db")
    a = ap.parse_args(argv)

    if a.cmd == "set-password":
        import getpass
        from .core.accounts import Accounts, AuthError
        pw = getpass.getpass("Пароль (не отображается): ")
        if pw != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпадают.", file=sys.stderr)
            return 2
        try:
            acc = Accounts(Store(a.db)).save(a.login, a.name, a.role, pw)
        except AuthError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"Учётная запись {acc['login']} ({acc['role']}) сохранена.")
    elif a.cmd == "themes":
        print("\n".join(list_themes()))
    elif a.cmd == "todo":
        th = load_theme(a.theme)
        print("\n".join(th.todo()) or "Заглушек нет.")
    elif a.cmd == "new-project":
        th = load_theme(a.theme)
        pid = Store(a.db).insert("projects", name=a.name, theme=th.id)
        print(f"Проект создан: {a.name} (тема {th.id}, id {pid})")
    elif a.cmd == "demo":
        from .connectors.llm_mock import MockLLM
        from .connectors.registry import default_registry
        from .core.pipeline import MeetingPipeline
        th = load_theme(a.theme)
        st = Store(a.db)
        pid = st.insert("projects", name="Демо-проект", theme=th.id)
        for name in ("Орлова Мария", "Белов Сергей", "Гаврилова Анна"):
            st.insert("people", project_id=pid, full_name=name)
        mid = st.insert("meetings", project_id=pid, date="2026-10-01", label="Демо-встреча")
        p = MeetingPipeline(th, st, default_registry(), MockLLM(), MockLLM())
        p.reg.add(pid, "Отправить отчёт по тестам", "Белов Сергей")
        p.ingest(pid, mid, "Расшифровка 01.10.2026.txt", DEMO_TEXT.encode("utf-8"))
        print(p.run(pid, mid))
    elif a.cmd == "routes":
        import json
        from .connectors.llm_routes import check_all, ensure_file, read, use
        if a.action == "use":
            print(json.dumps(use(a.role, a.point), ensure_ascii=False, indent=2))
        elif a.action == "show":                   # файла нет — справочник заготовок, роли «не настроены» (15.10.26)
            print(json.dumps(read(ensure_file()), ensure_ascii=False, indent=2))
        else:                                      # тем же телом, что рабочий вызов (общий ping)
            for r in check_all():
                print(f"{'ок ' if r['ok'] else 'НЕТ'}  {r['name']:<20} {r['model'] or ''} — {r['detail']}")
    elif a.cmd == "serve":
        import uvicorn
        os.environ["MEETFLOW_THEME"], os.environ["MEETFLOW_DB"] = a.theme, a.db
        from .web.app import create_app
        if a.port in (8000, 8001):
            print("Порты 8000/8001 заняты Проектом ERP и Планёркой — выберите другой.", file=sys.stderr)
            return 2
        if a.host not in ("127.0.0.1", "localhost", "::1"):
            # роль пока берётся из заголовка: на внешнем адресе любой стал бы супер-админом (письмо 01/20).
            # Внешний адрес — только после входа по паролю (FRAMEWORK_REPORT, вопрос «вход»)
            print(f"Адрес {a.host} доступен из сети, а входа по паролю пока нет — сервер не запущен. "
                  "Запускайте на 127.0.0.1.", file=sys.stderr)
            return 2
        os.environ["MEETFLOW_PORT"] = str(a.port)      # метка запуска знает свой порт (стенд 34)
        uvicorn.run(create_app(), host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
