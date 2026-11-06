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
from .core.store import Store, now

DEMO_TEXT = """[00:00:05] Орлова Мария: Доброе утро, начинаем.
[00:01:10] Белов Сергей: Отчёт по тестам отправил вчера, сделано.
[00:02:20] Орлова Мария: Белов Сергей, подготовьте план релиза до 15.10
[00:03:05] Орлова Мария: Гаврилова Анна, проверьте доступы к стенду
[00:04:00] Гаврилова Анна: А нужно ли переносить демо?
[00:05:30] Орлова Мария: Калинин Олег, согласуйте бюджет с финансами
"""


def _load_env_local() -> None:
    """Свой `.env.local` MeetFlow: строки `ИМЯ=значение` рядом с папкой пакета.

    Как у Планёрки и ERP: файл вне git, уже заданная переменная окружения главнее файла.
    Нужен для путей раздела 0 задания 24.10.2026 (`VOICE_BASE_PATH`, `TEAM_SHARED_PATH`) —
    без него ручной запуск требовал бы передавать их в каждом окне.
    """
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / ".env.local"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def main(argv: list[str] | None = None) -> int:
    _load_env_local()
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
    sp = sub.add_parser("set-password", help="временный пароль на 24 часа со сменой при входе (как скрипт сброса ERP)")
    sp.add_argument("--login", required=True); sp.add_argument("--name", default="")
    # Роль по умолчанию убрана (решение владелицы 06.11.2026, файл 20, вопрос 5): прежде команда без --role делала
    # существующего участника суперадмином. Новой записи роль обязательна, существующей — меняется, только если указана.
    sp.add_argument("--role", default=None); sp.add_argument("--db", default="data/meetflow.db")
    a = ap.parse_args(argv)

    if a.cmd == "set-password":
        # Переведено на правила слоя «Команды», как скрипт сброса ERP (решение владелицы 06.11.2026, вопрос 5): пароль не
        # вводится, а выдаётся временный — на 24 часа, показан один раз, при входе обязательна смена; сессии человека
        # закрываются; в «Системные сообщения» — строка без пароля. Прежде команда ставила постоянный пароль по правилам
        # ядра (8 знаков), не закрывала сессии и ничего не писала в журнал.
        import getpass
        import platform
        from datetime import datetime, timedelta
        from .core.registry import CardQueue
        from .web.erp.bezopasnost import generate_temp_password, hash_password, normalize_login
        store = Store(a.db)
        login = normalize_login(a.login)
        if not login:
            print("Укажите логин — часть адреса до «@».", file=sys.stderr)
            return 2
        rows = store.q("SELECT * FROM accounts WHERE lower(login)=?", (login,))
        if not rows and not a.role:
            print("Новой учётной записи нужна роль: --role super_admin | project_admin | member.", file=sys.stderr)
            return 2
        temp = generate_temp_password()
        fields = {"password_hash": hash_password(temp), "must_change_password": 1, "failed_attempts": 0,
                  "locked_until": None, "temp_expires_at": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")}
        if a.role:
            fields["role"] = a.role
        if rows:
            uid = rows[0]["id"]
            store.update("accounts", uid, **fields)
        else:
            uid = store.insert("accounts", login=login, full_name=a.name or login, active=1, confirmed=1, created_at=now(),
                               **fields)
        closed = 0
        for s_row in store.q("SELECT id FROM sessions WHERE account_id=?", (uid,)):
            store.delete("sessions", s_row["id"])
            closed += 1
        who = platform.node() + "\\" + (getpass.getuser() or os.environ.get("USERNAME", "?"))
        CardQueue(store).open(None, "event", f"Временный пароль выдан командной строкой: {login}",
                              {"message": f"Запустил {who}. Действует 24 часа, при входе обязательна смена. "
                                          f"Завершено сессий: {closed}. Самого пароля здесь нет.", "source": "auth"})
        print(f"Готово: {login}. Завершено сессий: {closed}.")
        print(f"Временный пароль (показан один раз, нигде не записан): {temp}")
        print("Пароль действует 24 часа. Передайте лично, не пересылайте. При входе система попросит задать свой.")
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
        # Роли демо (записка 05.11.2026): супер-админ, админ проекта и участник — чтобы выбор «Вы работаете как»
        # показывал все три и промер шёл по ним, а не по людям без роли.
        for имя, роль in (("Орлова Мария", "super_admin"), ("Белов Сергей", "project_admin"),
                          ("Гаврилова Анна", "member")):
            st.insert("accounts", login=None, full_name=имя, role=роль, password_hash="", active=1, failed_attempts=0,
                      created_at=now(), confirmed=1, confirmed_source="демо")
        mid = st.insert("meetings", project_id=pid, date="2026-10-01", label="Демо-встреча")
        # Демо не должно читать настоящую общую базу (находка администратора 05.11.2026): иначе sync_people
        # заводит в демо-базу настоящих людей из VOICE_BASE_PATH. Боевой serve это не затрагивает.
        сохранённые = {k: os.environ.pop(k, None) for k in ("VOICE_BASE_PATH", "TEAM_SHARED_PATH")}
        try:
            p = MeetingPipeline(th, st, default_registry(), MockLLM(), MockLLM())
            p.reg.add(pid, "Отправить отчёт по тестам", "Белов Сергей")
            p.ingest(pid, mid, "Расшифровка 01.10.2026.txt", DEMO_TEXT.encode("utf-8"))
            print(p.run(pid, mid))
        finally:
            for k, v in сохранённые.items():
                if v is not None:
                    os.environ[k] = v
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
        if a.host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            # роль пока берётся из заголовка: на внешнем адресе любой стал бы супер-админом (письмо 01/20).
            # Внешний адрес — только после входа по паролю (FRAMEWORK_REPORT, вопрос «вход»)
            print(f"Адрес {a.host} доступен из сети, а входа по паролю пока нет — сервер не запущен. "
                  "Запускайте на 127.0.0.1 или 0.0.0.0 (слово владелицы 26.10.2026: фронт на "
                  "http://m46-ai-vm1.nevalab.ru:8005/).", file=sys.stderr)
            return 2
        if a.host == "0.0.0.0":
            print("Внимание: сервер открыт в локальную сеть, вход по паролю выключен — роль берётся из заголовка. "
                  "Открыто по слову владелицы 26.10.2026 (http://m46-ai-vm1.nevalab.ru:8005/).", file=sys.stderr)
        os.environ["MEETFLOW_PORT"] = str(a.port)      # метка запуска знает свой порт (стенд 34)
        _crash_log(a.db)
        uvicorn.run(create_app(), host=a.host, port=a.port)
    return 0


def _crash_log(db: str) -> None:
    """Падение процесса на уровне C (не исключение Python) — в файл `logs/server_crash.log` рядом с базой
    (27.10.2026). Отчёт локальной машины: «сделать основной» оборвала соединение и сервер перезапустился, а журнала
    сервера нет — `run_dev` пишет в скрытое окно. `faulthandler` пишет трассу всех потоков в момент падения."""
    import faulthandler
    from pathlib import Path
    try:
        folder = Path(db).resolve().parent / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        f = open(folder / "server_crash.log", "a", encoding="utf-8")   # noqa: SIM115 — открыт до конца процесса
        faulthandler.enable(file=f, all_threads=True)
        globals()["_CRASH_FILE"] = f
    except OSError:
        faulthandler.enable()


if __name__ == "__main__":
    sys.exit(main())
