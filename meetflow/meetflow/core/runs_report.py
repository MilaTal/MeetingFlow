"""Прогоны и расход на модель — сводка из журнала вызовов (jsonl).

Как в проектах-примерах («Расход» в ERP, «Прогоны и Расход на модель» в
Планёрке): строка на вызов и итог прогона; разбивка по назначению,
модели и дням; потолки рядом с фактом. Расход — отнесение по журналу,
а не счёт поставщика (оговорка ERP). Битые строки журнала пропускаются и
считаются отдельно — прибор врёт чаще продукта, это видно.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _ts(rec: dict) -> datetime | None:
    try:
        return datetime.strptime(str(rec.get("ts", ""))[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def runs_report(journal_path: str | Path | None, days: int = 7, limits: dict | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"days": days, "limits": limits or {}, "broken_lines": 0,
                           "note": "Расход по журналу вызовов, не счёт поставщика."}
    p = Path(journal_path) if journal_path else None
    if not p or not p.exists():
        out.update(calls=0, cost_usd=0.0, runs=[], by_purpose={}, by_model={}, by_day={},
                   detail="Журнал вызовов пока пуст.")
        return out
    since = (now or datetime.now()) - timedelta(days=days)
    calls, runs = [], []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out["broken_lines"] += 1
            continue
        t = _ts(rec)
        if t is None or t < since:
            continue
        (runs if "run" in rec else calls).append(rec)
    agg = lambda: {"calls": 0, "cost_usd": 0.0, "seconds": 0.0, "chars": 0}  # noqa: E731
    by_purpose, by_model, by_day = defaultdict(agg), defaultdict(agg), defaultdict(agg)
    errors = 0
    for c in calls:
        if c.get("error"):
            errors += 1
        for key, bucket in ((c.get("purpose") or "—", by_purpose), (c.get("model") or "—", by_model),
                            (str(c.get("ts", ""))[:10], by_day)):
            b = bucket[key]
            b["calls"] += 1
            b["cost_usd"] += float(c.get("cost_usd") or 0)
            b["seconds"] += float(c.get("seconds") or 0)
            b["chars"] += int(c.get("chars") or 0)
    rnd = lambda d: {k: {**v, "cost_usd": round(v["cost_usd"], 4), "seconds": round(v["seconds"], 1)}  # noqa: E731
                     for k, v in sorted(d.items())}
    run_rows = [{"ts": r.get("ts"), "meeting_id": r.get("run"), "status": r.get("status") or
                 ("stopped_by_limit" if r.get("stopped_by") else "—"), "stopped_by": r.get("stopped_by"),
                 "calls": r.get("calls"), "cost_usd": r.get("cost_usd"), "added": r.get("added"),
                 "held": r.get("held"), "closed": r.get("closed"), "stand": bool(r.get("stand"))} for r in runs]
    stopped = sum(1 for r in run_rows if r["status"] == "stopped_by_limit")
    out.update(calls=len(calls), errors=errors, cost_usd=round(sum(float(c.get("cost_usd") or 0) for c in calls), 4),
               runs_total=len(run_rows), runs_stopped=stopped, runs=list(reversed(run_rows))[:30],
               by_purpose=rnd(by_purpose), by_model=rnd(by_model), by_day=rnd(by_day))
    # стенд без модели и «ok_limited» в стоимость успешного не идут (письмо 01/8, 01/19)
    out["stand_runs"] = sum(1 for r in run_rows if r["stand"])
    ok_runs = [r for r in run_rows if r["status"] == "ok" and not r["stand"]]
    if ok_runs:  # стоимость успешного результата (курс, занятие 6)
        out["cost_per_success_usd"] = round(out["cost_usd"] / len(ok_runs), 4)
    return out
