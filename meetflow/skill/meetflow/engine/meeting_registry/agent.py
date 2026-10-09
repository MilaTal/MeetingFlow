"""Разрешающий агент: модель сама выбирает инструмент для спорного пункта, код проверяет каждый шаг.

Почему здесь агент, а не if-ветка (критерий 4.2 курса). Маршрут разбора спорного имени нельзя прочитать
до запуска: «Марина» без фамилии требует посмотреть, кто говорил на встрече; «Кость» — сверить с «Командой»;
«подготовить спецификацию» — проверить, не висит ли та же задача в реестре. Какой инструмент нужен, видно
только по данным прогона. Потолок шагов проверяется до каждого шага кодом (control.RunBudget), поэтому
свобода выбора не делает потолок непроверяемым — это и было доводом Планёрки против агента (паспорт, Р4).

Запись агент делает только через финальные инструменты, и каждый проверяется кодом: assign — только кандидат
из сверки с «Командой» (агент не может отдать поручение человеку, чьё имя не звучало), mark_duplicate — только
при реальном совпадении формулировок. Всё прочее — to_operator: кандидат карточкой, а не догадка.
"""

import json

from .errors import BadModelAnswer, BudgetExceeded, ProviderUnavailable
from .prompts import RESOLVER_SYSTEM
from .text import coverage, norm, numbers, same_subject

FINAL = {"assign", "mark_duplicate", "accept_new", "to_operator"}
PER_ITEM_STEPS = 5


def _participants(lines):
    counts = {}
    for l in lines:
        if l.get("speaker"):
            counts[l["speaker"]] = counts.get(l["speaker"], 0) + 1
    return {"speakers": [{"name": k, "lines": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]}


def _tool(name, args, item, ctx):
    team, lines, tasks = ctx["team"], ctx["lines"], ctx["tasks"]
    if name == "find_person":
        r = team.resolve(args.get("name") or item.get("to", ""))
        return {"status": r["status"], "reason": r["reason"],
                "candidates": [{"id": pid, "full_name": team.get(pid)["full_name"], "department": team.get(pid).get("department")}
                               for pid in r["candidates"] if team.get(pid)]}
    if name == "participants":
        return _participants(lines)
    if name == "read_lines":
        a = max(1, _int(args.get("from"), item.get("line", 1)))
        b = min(a + 7, _int(args.get("to"), a + 3))
        return {"lines": [f"[{l['n']}] " + (f"{l['speaker']}: " if l["speaker"] else "") + l["text"]
                          for l in lines if a <= l["n"] <= b]}
    if name == "search_registry":
        q = args.get("text") or item.get("action", "")
        hits = sorted(({"id": t["id"], "description": t["description"], "coverage": round(coverage(q, t["description"]), 2),
                        "same_numbers": numbers(q) == numbers(t["description"])}
                       for t in tasks), key=lambda x: -x["coverage"])[:3]
        return {"tasks": [h for h in hits if h["coverage"] > 0]}
    return {"error": f"нет инструмента {name}"}


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(default)
        except (TypeError, ValueError):
            return 1


def _spoke(pid, ctx):
    """Говорил ли человек pid на этой встрече (по подписям реплик). Свидетельство для выбора между тёзками."""
    p = ctx["team"].get(pid)
    if not p:
        return False
    surname = norm(p["full_name"].split()[0])
    return any(l.get("speaker") and surname[:-1] in norm(l["speaker"]) for l in ctx["lines"])


def _final(name, args, item, ctx, obs=()):
    """Проверка финального решения агента кодом. Возвращает решение или перевод к оператору."""
    team, tasks = ctx["team"], {t["id"]: t for t in ctx["tasks"]}
    if name == "assign":
        pid = args.get("person_id")
        if not isinstance(pid, str) or not team.get(pid) or not team.names_compatible(item.get("to", ""), pid):
            return {"decision": "to_operator", "reason": f"агент предложил исполнителя, не совпадающего с прозвучавшим «{item.get('to')}»"}
        status = team.resolve(item.get("to", ""))["status"]
        if status == "ambiguous":
            # тёзки — всегда карточкой: участники встречи кандидатов только СОРТИРУЮТ, а не выбирают
            # (решение владельца 03.10.26; прежде движок назначал тёзку, если говорил только он)
            cands = team.resolve(item.get("to", ""))["candidates"]
            ranked = sorted(cands, key=lambda c: (not _spoke(c, ctx), c != pid))
            hint = ", ".join(team.get(c)["full_name"] + (" — говорил на встрече" if _spoke(c, ctx) else "")
                             for c in ranked if team.get(c))
            return {"decision": "to_operator", "reason": f"«{item.get('to')}»: тёзки, выбирает человек. Кандидаты: {hint}"}
        elif status not in ("exact", "fixed", "department"):
            # «похоже, но не уверенно» — кандидат карточкой, не молчаливая подстановка (правило владельца 26.09.26)
            return {"decision": "to_operator", "reason": f"«{item.get('to')}» похоже на {team.get(pid)['full_name']} — нужно подтверждение"}
        return {"decision": "assign", "person_id": pid}
    if name == "mark_duplicate":
        tid = _int(args.get("task_id"), -1)
        t = tasks.get(tid)
        # дубль — только та же задача того же человека: иначе поручение исчезнет без следа (ревью 03.10.26)
        if (t and item.get("kind") == "duplicate" and t.get("responsible_id") == item.get("responsible_id")
                and same_subject(item.get("action", ""), t["description"], 0.6)):
            return {"decision": "duplicate", "task_id": tid}
        return {"decision": "to_operator", "reason": "предложенный дубль не подтверждается: другая задача или другой исполнитель"}
    if name == "accept_new":
        if item.get("kind") == "duplicate":
            return {"decision": "accept_new"}
        return {"decision": "to_operator", "reason": "исполнитель не установлен"}
    return {"decision": "to_operator", "reason": str(args.get("reason") or "агент не нашёл оснований")}


def resolve_items(items, ctx, client, budget, log_step):
    """Разбирает спорные пункты. Потолок шагов — исход к человеку для всех оставшихся, без повтора."""
    results = []
    stopped = None
    for item in items:
        if stopped:
            results.append({**item, "decision": "to_operator", "reason": f"остановлено по пределу: {stopped}"})
            continue
        obs = []
        decision = None
        for _ in range(PER_ITEM_STEPS):
            try:
                budget.before_step()
                state = {"item": {k: item.get(k) for k in ("kind", "line", "to", "action", "quote", "status", "reason")},
                         "observations": obs}
                user = "СОСТОЯНИЕ: " + json.dumps(state, ensure_ascii=False)
                budget.before_call(len(RESOLVER_SYSTEM) + len(user))
                ans, usage = client.complete_json(RESOLVER_SYSTEM, user, "resolve")
                budget.after_call(usage["tokens_in"], usage["tokens_out"], usage["cost_usd"])
            except BudgetExceeded as e:
                stopped = str(e)
                decision = {"decision": "to_operator", "reason": f"остановлено по пределу: {e}"}
                break
            except (BadModelAnswer, ProviderUnavailable) as e:
                decision = {"decision": "to_operator", "reason": f"агент не ответил по контракту: {e}"}
                break
            tool = str(ans.get("tool", ""))[:40]
            args = ans.get("args") if isinstance(ans.get("args"), dict) else {}   # ответ модели — данные неизвестной формы
            log_step("resolve:" + tool, True, usage, f"пункт строки {item.get('line')}: {json.dumps(args, ensure_ascii=False)[:200]}")
            if tool in FINAL:
                decision = _final(tool, args, item, ctx, obs)
                break
            obs.append({"tool": tool, "args": args, "result": _tool(tool, args, item, ctx)})
        if decision is None:
            decision = {"decision": "to_operator", "reason": f"не решено за {PER_ITEM_STEPS} шагов"}
        results.append({**item, **decision, "trace": [o["tool"] for o in obs]})
    return results
