"""Прогон наборов eval meeting-registry через конвейер MeetFlow. Судья — код: сверка с реестром и карточками.

  python run_eval_meetflow.py --set cases --llm mock --label до
  python run_eval_meetflow.py --set cases_blind --llm ollama --label после   (модель — из темы it_product)

Наборы: cases (15, основной), cases_live (12, «живая речь»), cases_blind (10, слепой — прогонять один раз
после правок и ничего под него не править). На заглушке модели набор меряет заглушку; осмысленная полнота —
только на настоящей модели. Точность (ложные записи) осмысленна на любой.

Отличие от нашего судьи: исполнитель сверяется по ФИО (у MeetFlow поле assignee — текст).
Отдел без руководителя (R15) задаётся отсутствием «ото» в department_heads.
"""

import argparse
import json
import os
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATES = [os.path.join(HERE, "..", "..", "..", "..", "meetflow"),  # общий репозиторий MeetingFlow
               os.path.join(HERE, "..", "..", "..", "..", "..", "ITMO_project lead", "meetflow-framework")]
sys.path.insert(0, os.environ.get("MEETFLOW_PATH") or next(
    (p for p in _CANDIDATES if os.path.isdir(os.path.join(p, "meetflow"))), _CANDIDATES[0]))

from meetflow.connectors.llm_mock import MockLLM  # noqa: E402
from meetflow.connectors.registry import default_registry  # noqa: E402
from meetflow.core.config import load_theme  # noqa: E402
from meetflow.core.pipeline import MeetingPipeline  # noqa: E402
from meetflow.core.store import Store  # noqa: E402

TEAM = json.load(open(os.path.join(HERE, "team.json"), encoding="utf-8"))
NAME = {p["id"]: p["full_name"] for p in TEAM["people"]}
DIMINUTIVES = {"костя": ["константин"], "настя": ["анастасия"], "юля": ["юлия"], "света": ["светлана"],
               "антон": ["антон"], "марина": ["марина"]}
HEADS = {"осн": "Ершова Светлана", "отдел закупок": "Ершова Светлана", "олг": "Осипов Игорь"}


def make_llm(kind):
    if kind == "mock":
        return MockLLM()
    from meetflow.connectors.llm_ollama import OllamaLLM
    cfg = load_theme("it_product").get("llm.generator", {})
    return OllamaLLM(model=cfg.get("model", ""), profile=cfg.get("profile", "generic"))


def to_lines(text):
    out = []
    for i, l in enumerate([x for x in text.splitlines() if x.strip()]):
        out.append(f"[00:{i // 60:02d}:{i % 60:02d}] {l.strip()}")
    return "\n".join(out) + "\n"


class Bench:
    def __init__(self, llm):
        self.th = load_theme("it_product")
        self.th.data.setdefault("people", {})
        self.th.data["people"]["diminutives"] = DIMINUTIVES
        self.th.data["people"]["department_heads"] = HEADS
        self.s = Store(":memory:")
        self.pid = self.s.insert("projects", name="eval", theme=self.th.id)
        for p in TEAM["people"]:
            self.s.insert("people", project_id=self.pid, full_name=p["full_name"])
        self.p = MeetingPipeline(self.th, self.s, default_registry(), llm, llm, None)

    def meeting(self, date, text, label):
        mid = self.s.insert("meetings", project_id=self.pid, date=date, label=label)
        self.p.ingest(self.pid, mid, f"{label}.txt", to_lines(text).encode("utf-8"))
        return mid, self.p.run(self.pid, mid)


def seed_task(b, setup_text, i):
    """Задача прошлой встречи заводится прямо в реестр, а не прогоном MeetFlow.

    Причина: MeetFlow заводит задачу только при полном «Фамилия Имя», а подготовка набора говорит «Ершова, …».
    Прогоном подготовка оставляла реестр пустым, и кейсы закрытия проваливались впустую (прибор, 03.10.26).
    Формат подготовки: «Гаврилов Павел: <Фамилия>, <глагол> <что>.»
    """
    body = setup_text.split(":", 1)[1].strip()
    who, what = [x.strip(" .") for x in body.split(",", 1)]
    full = next(p["full_name"] for p in TEAM["people"] if p["full_name"].split()[0].startswith(who[:5]))
    mid = b.s.insert("meetings", project_id=b.pid, date="2026-10-01", label=f"setup{i}")
    b.p.reg.add(b.pid, what, full, mid, setup_text, "", "2026-10-01")


def judge(case, rep, b, before_ids, mid):
    exp, fails = case["expect"], []
    tasks = b.p.reg.list(b.pid, None)
    new = [t for t in tasks if t["id"] not in before_ids]
    if exp["outcome"] == "rejected":
        if getattr(rep, "status", "") not in ("rejected", "error") and new:
            fails.append(f"ожидался отказ, исход {getattr(rep, 'status', '?')}, задач {len(new)}")
        return fails
    if "tasks" in exp:
        if len([t for t in new if t["status"] == "active"]) != len(exp["tasks"]):
            fails.append(f"новых задач {len(new)} вместо {len(exp['tasks'])}")
        for e in exp["tasks"]:
            hit = [t for t in new if e["has"] in t["description"].lower()]
            if not hit:
                fails.append(f"нет задачи «{e['has']}»")
            elif "who" in e and NAME[e["who"]] not in (hit[0].get("assignee") or ""):
                fails.append(f"исполнитель {hit[0].get('assignee')} вместо {NAME[e['who']]}")
    if "new_tasks_count" in exp and len(new) != exp["new_tasks_count"]:
        fails.append(f"новых задач {len(new)} вместо {exp['new_tasks_count']}")
    if "closed" in exp:
        closed = [t for t in tasks if t["status"] != "active"]
        if len(closed) != len(exp["closed"]):
            fails.append(f"закрыто {len(closed)} вместо {len(exp['closed'])}")
        for e in exp["closed"]:
            hit = [t for t in closed if e["has"] in t["description"].lower()]
            if not hit or hit[0]["status"] != e["status"]:
                fails.append(f"не закрыта «{e['has']}» статусом {e['status']}")
    for a in exp.get("active_has", []):
        if not any(a in t["description"].lower() and t["status"] == "active" for t in tasks):
            fails.append(f"задача «{a}» не активна")
    if exp.get("cards"):
        if not [c for c in b.p.cards.list(b.pid) if c.get("meeting_id") in (mid, None)]:
            fails.append("нет карточки оператору")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="cases")
    ap.add_argument("--llm", default="mock", choices=["mock", "ollama"])
    ap.add_argument("--label", default="прогон")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = json.load(open(os.path.join(HERE, f"{a.set}.json"), encoding="utf-8"))["cases"]
    rows = []
    for case in cases:
        b = Bench(make_llm(a.llm))
        for i, s in enumerate(case.get("setup", [])):
            seed_task(b, s, i)
        before = {t["id"] for t in b.p.reg.list(b.pid, None)}
        t0 = time.monotonic()
        try:
            mid, rep = b.meeting("2026-10-02", case["input"], case["id"])
            fails = judge(case, rep, b, before, mid)
        except Exception as e:  # отказ входа у MeetFlow может быть исключением ingest
            rep, fails = None, ([] if case["expect"]["outcome"] == "rejected" else [f"исключение {type(e).__name__}: {e}"])
        rows.append({"id": case["id"], "type": case["type"], "title": case["title"], "ok": not fails, "fails": fails,
                     "seconds": round(time.monotonic() - t0, 3)})
    out = {"set": a.set, "llm": a.llm, "label": a.label, "at": time.strftime("%Y-%m-%d %H:%M"),
           "passed": sum(r["ok"] for r in rows), "total": len(rows), "rows": rows}
    res_dir = os.path.join(tempfile.gettempdir() if os.environ.get("EVAL_TMP") else HERE, "results")
    os.makedirs(res_dir, exist_ok=True)
    json.dump(out, open(os.path.join(res_dir, f"{a.set}__{a.llm}__{a.label}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in rows:
        print(f"{r['id']:<4} {'ок ' if r['ok'] else 'НЕТ'} {r['type']:<20} {r['title']:<45} {'; '.join(r['fails'])}")
    print(f"ИТОГ {a.set} / {a.llm} / {a.label}: {out['passed']} из {out['total']}")


if __name__ == "__main__":
    main()
