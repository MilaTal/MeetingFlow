"""Командная строка.

  python -m meeting_registry process <файл> --date 2026-10-02 --db реестр.db --team команда.json [--model glm-4.7-flash]
  python -m meeting_registry watch <папка> --db реестр.db --team команда.json [--interval 60] [--once]
  python -m meeting_registry runs --db реестр.db            # мониторинг: шаги, токены, стоимость, ошибки
  python -m meeting_registry cards --db реестр.db           # очередь оператору
"""

import argparse
import json
import sys

from . import intake, pipeline, watch
from .errors import SourceRejected
from .heuristic import HeuristicClient
from .llm import OllamaClient
from .registry import Registry
from .roster import Team


def load_team(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Team(data["people"], data.get("departments", {}))


def client_factory(args):
    def make():
        if args.model == "heuristic":
            return HeuristicClient()
        return OllamaClient(model=args.model or None)
    return make


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="meeting_registry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("process", "watch"):
        p = sub.add_parser(name)
        p.add_argument("path")
        p.add_argument("--db", required=True)
        p.add_argument("--team", required=True)
        p.add_argument("--model", default=None, help="имя модели в Ollama или heuristic")
        if name == "process":
            p.add_argument("--date", default=None)
            p.add_argument("--out", default=None, help="куда сохранить протокол .md")
        else:
            p.add_argument("--interval", type=int, default=60)
            p.add_argument("--once", action="store_true")
    for name in ("runs", "cards"):
        p = sub.add_parser(name)
        p.add_argument("--db", required=True)
    args = ap.parse_args(argv)

    if args.cmd in ("runs", "cards"):
        reg = Registry(args.db)
        if args.cmd == "cards":
            for c in reg.open_cards():
                print(f"[{c['id']}] {c['kind']}: {c['title']}" + (f" — «{c['quote'][:120]}»" if c["quote"] else ""))
            return 0
        for r in reg.runs():
            print(f"прогон {r['id']} | {r['source_name']} | {r['outcome']} | модель {r['model']} | вызовов {r['calls']} | "
                  f"шагов агента {r['steps']} | токенов {r['tokens_in']}/{r['tokens_out']} | {r['seconds']} с | "
                  f"{r['cost_usd']} $" + (f" | ошибка: {r['error']}" if r["error"] else ""))
            for s in reg.run_steps(r["id"]):
                print(f"    {s['n']:>2}. {s['name']:<16} {'ок ' if s['ok'] else 'СБОЙ'} {s['seconds']:>7} с "
                      f"{s['tokens_in']:>6}/{s['tokens_out']:<5} {s['detail']}")
        return 0

    reg = Registry(args.db)
    team = load_team(args.team)
    make = client_factory(args)
    if args.cmd == "watch":
        watch.watch(args.path, reg, team, make, args.interval, once=args.once)
        return 0
    try:
        text = intake.read_file(args.path)
    except SourceRejected as e:
        print(json.dumps({"outcome": "rejected", "reason": str(e)}, ensure_ascii=False))
        return 2
    date = args.date or intake.date_from_name(args.path)
    if not date:
        print(json.dumps({"outcome": "no_date", "reason": "дата встречи не задана и не читается из имени файла"}, ensure_ascii=False))
        return 2
    res = pipeline.process(text, args.path, date, reg, team, make())
    if args.out and res.get("protocol_md"):
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(res["protocol_md"])
    print(json.dumps({k: v for k, v in res.items() if k != "protocol_md"}, ensure_ascii=False))
    return 0 if res["outcome"] in ("done", "degraded", "duplicate", "partial_limit") else 1


if __name__ == "__main__":
    sys.exit(main())
