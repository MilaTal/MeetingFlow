"""Регрессия «до/после»: один набор дважды, построчно. Расхождения уходят в improvement-log.

  python eval/compare.py cases до_v1.0 после_v1.1
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(s, label):
    with open(os.path.join(ROOT, "results", f"{s}__{label}.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    s, a, b = sys.argv[1:4]
    ra, rb = load(s, a), load(s, b)
    rows_b = {r["id"]: r for r in rb["rows"]}
    print(f"| кейс | тип | {a} | {b} | что изменилось |")
    print("|---|---|---|---|---|")
    for r in ra["rows"]:
        x = rows_b.get(r["id"], {})
        changed = "без изменений" if r["ok"] == x.get("ok") else ("починилось" if x.get("ok") else "СЛОМАЛОСЬ")
        print(f"| {r['id']} {r['title']} | {r['type']} | {'да' if r['ok'] else 'нет: ' + '; '.join(r['fails'])} | "
              f"{'да' if x.get('ok') else 'нет: ' + '; '.join(x.get('fails', []))} | {changed} |")
    print(f"\nИтог: {a} — {ra['passed']} из {ra['total']}; {b} — {rb['passed']} из {rb['total']}.")


if __name__ == "__main__":
    main()
