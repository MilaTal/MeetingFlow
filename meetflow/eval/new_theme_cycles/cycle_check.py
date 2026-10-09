"""Сверка итога цикла с ожиданиями, записанными до прогона. Печатает команду, задачи, карточки и вердикт по строкам."""
import json
import sys

r = json.load(open(sys.argv[1], encoding="utf-8"))
print("==", r["scenario"])
print("-- «Команда»:")
for t in r["team"]:
    print(f"   {t['status']} {t['who']}: {t['answer'] if t['answer'] != 'заведён' else 'заведён'}")
ok_all = bad_all = 0
for m in r["meetings"]:
    rep = m["report"] if isinstance(m["report"], dict) else {"raw": m["report"]}
    print(f"\n-- {m['label']}: загрузка {m['upload']}, run {m['run_status']}, {m['seconds']} с, "
          f"статус {rep.get('status')}, вызовов {rep.get('calls')}, ${rep.get('cost_usd')}, задач +{rep.get('tasks_added')}, "
          f"без исполнителя {rep.get('tasks_held')}, закрыто {rep.get('tasks_closed')}, снято {rep.get('tasks_dropped')}")
    tasks = m["tasks"] if isinstance(m["tasks"], list) else m["tasks"].get("tasks", [])
    for t in tasks:
        print(f"   задача: {t.get('description')!r:70} | {t.get('responsible') or t.get('responsible_name') or t.get('assignee') or '—'} | "
              f"{t.get('status')} | срок {t.get("due_date") or "—"}")
    cards = m["cards"] if isinstance(m["cards"], list) else m["cards"].get("cards", [])
    for c in cards:
        print(f"   карточка: [{c.get('kind')}] {str(c.get('title'))[:110]}")
    e = m["expect"]
    low = lambda s: (s or "").lower().replace("ё", "е")  # noqa: E731
    def find(key):
        return [t for t in tasks if low(key) in low(t.get("description"))]
    def who(t):
        return t.get("responsible") or t.get("responsible_name") or t.get("assignee") or ""
    checks = []
    for k, person in e.get("tasks_assigned", {}).items():
        f = find(k)
        checks.append((f"задача «{k}» на {person}", any(person.split()[0] in who(t) for t in f)))
    for k in e.get("tasks_without_assignee", []):
        f = find(k)
        checks.append((f"задача «{k}» заведена без исполнителя", bool(f) and all(not who(t) for t in f)))
    for k in e.get("no_task_for", []):
        checks.append((f"нет задачи «{k}»", not find(k)))
    for k in e.get("cards_about", []):
        checks.append((f"карточка про «{k}»", any(low(k) in low(json.dumps(c, ensure_ascii=False)) for c in cards) or (k == "систем" and any(c.get("kind") == "suspicious_source" for c in cards))))
    for k, d in e.get("dues", {}).items():
        checks.append((f"срок «{k}» = {d}", any(t.get("due_date") == d for t in find(k))))
    for k in e.get("closed_done", []):
        checks.append((f"«{k}» выполнена", any(t.get("status") in ("done", "выполнена") for t in find(k))))
    for k in e.get("closed_dropped", []):
        checks.append((f"«{k}» снята", any(t.get("status") in ("dropped", "снята", "cancelled") for t in find(k))))
    for k in e.get("stay_active", []):
        checks.append((f"«{k}» осталась активной", bool(find(k)) and all(t.get("status") in ("active", "в работе", "open") for t in find(k))))
    for name, ok in checks:
        ok_all += ok
        bad_all += not ok
        print(f"   {'ДА ' if ok else 'НЕТ'} {name}")
    if e.get("observe"):
        print("   наблюдать:", e["observe"])
print(f"\nИТОГ: {ok_all} из {ok_all + bad_all} ожиданий")
