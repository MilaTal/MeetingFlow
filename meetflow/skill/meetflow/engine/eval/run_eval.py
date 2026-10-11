"""Прогон eval suite. Судья — код: значения сверяются с реестром и карточками.

  python eval/run_eval.py --label до --client heuristic
  python eval/run_eval.py --label после --client ollama --model glm-4.7-flash
Результат: eval/results/<набор>__<label>.json и строка-итог; сравнение двух прогонов — eval/compare.py.
"""

import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from meeting_registry import pipeline  # noqa: E402
from meeting_registry.cli import load_team  # noqa: E402
from meeting_registry.heuristic import HeuristicClient  # noqa: E402
from meeting_registry.llm import OllamaClient  # noqa: E402
from meeting_registry.registry import Registry  # noqa: E402


def judge(case, res, reg, setup_ids):
    exp = case["expect"]
    fails = []
    if res["outcome"] != exp["outcome"]:
        fails.append(f"исход {res['outcome']} вместо {exp['outcome']}")
    if "code" in exp and res.get("code") != exp["code"]:
        fails.append(f"код отказа {res.get('code')} вместо {exp['code']}")
    new = [t for t in reg.all_tasks() if t["id"] not in setup_ids]
    if "tasks" in exp:
        if len(new) != len(exp["tasks"]):
            fails.append(f"новых задач {len(new)} вместо {len(exp['tasks'])}")
        for e in exp["tasks"]:
            hit = [t for t in new if e["has"] in t["description"].lower()]
            if not hit:
                fails.append(f"нет задачи «{e['has']}»")
                continue
            if "who" in e and hit[0]["responsible_id"] != e["who"]:
                fails.append(f"ответственный {hit[0]['responsible_id']} вместо {e['who']}")
            if "due" in e and hit[0]["due"] != e["due"]:
                fails.append(f"срок {hit[0]['due']} вместо {e['due']}")
    if "new_tasks_count" in exp and len(new) != exp["new_tasks_count"]:
        fails.append(f"новых задач {len(new)} вместо {exp['new_tasks_count']}")
    if "closed" in exp:
        closed = [t for t in reg.all_tasks() if t["status"] != "active"]
        if len(closed) != len(exp["closed"]):
            fails.append(f"закрыто {len(closed)} вместо {len(exp['closed'])}")
        for e in exp["closed"]:
            hit = [t for t in closed if e["has"] in t["description"].lower()]
            if not hit or hit[0]["status"] != e["status"]:
                fails.append(f"не закрыта «{e['has']}»")
            elif e.get("quote_has"):
                q = reg._conn().execute("SELECT quote FROM task_history WHERE task_id=? AND new=?", (hit[0]["id"], e["status"])).fetchone()
                if not q or e["quote_has"] not in (q["quote"] or ""):
                    fails.append("нет цитаты-основания закрытия")
    for a in exp.get("active_has", []):
        if not any(a in t["description"].lower() and t["status"] == "active" for t in reg.all_tasks()):
            fails.append(f"задача «{a}» не активна")
    kinds = [c["kind"] for c in reg.open_cards() if c["meeting_id"] == res.get("meeting_id")]
    for k in exp.get("cards", []):
        if k not in kinds:
            fails.append(f"нет карточки {k}")
    if exp.get("no_cards") and kinds:
        fails.append(f"лишние карточки {kinds}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--client", default="heuristic", choices=["heuristic", "ollama"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--set", default="cases", help="cases (основной), cases_live (живая речь) или cases_blind (слепой)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = json.load(open(os.path.join(ROOT, "eval", f"{args.set}.json"), encoding="utf-8"))["cases"]
    team = load_team(os.path.join(ROOT, "tests", "data", "team.json"))
    make = (lambda: HeuristicClient()) if args.client == "heuristic" else (lambda: OllamaClient(model=args.model))
    rows = []
    for case in cases:
        with tempfile.TemporaryDirectory() as d:
            reg = Registry(os.path.join(d, "r.db"))
            for i, s in enumerate(case.get("setup", [])):
                pipeline.process(s, f"setup{i}.txt", "2026-10-01", reg, team, make())
            setup_ids = {t["id"] for t in reg.all_tasks()}
            t0 = time.monotonic()
            res = pipeline.process(case["input"], f"{case['id']}.txt", "2026-10-02", reg, team, make())
            sec = time.monotonic() - t0
            fails = judge(case, res, reg, setup_ids)
            rows.append({"id": case["id"], "type": case["type"], "title": case["title"], "ok": not fails, "fails": fails,
                         "outcome": res["outcome"], "calls": res.get("calls", 0), "steps": res.get("steps", 0),
                         "tokens_in": res.get("tokens_in", 0), "tokens_out": res.get("tokens_out", 0),
                         "cost_usd": res.get("cost_usd", 0.0), "seconds": round(sec, 3)})
            reg.close()
    out_dir = os.path.join(ROOT, "eval", "results")
    os.makedirs(out_dir, exist_ok=True)
    summary = {"set": args.set, "label": args.label, "client": args.client, "model": args.model, "at": time.strftime("%Y-%m-%d %H:%M"),
               "passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}
    with open(os.path.join(out_dir, f"{args.set}__{args.label}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(f"{r['id']:<4} {'ок ' if r['ok'] else 'НЕТ'} {r['type']:<20} {r['title']:<45} {'; '.join(r['fails'])}")
    print(f"ИТОГ {args.label}: {summary['passed']} из {summary['total']}")


if __name__ == "__main__":
    main()
