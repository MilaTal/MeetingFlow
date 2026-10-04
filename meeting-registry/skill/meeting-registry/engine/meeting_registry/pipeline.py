"""Конвейер: источник -> проверка входа -> встреча -> извлечение поручений -> проверки кодом ->
разрешающий агент -> закрытия -> запись в реестр -> протокол -> журнал прогона.

Паттерн — SEQUENTIAL с валидаторами кодом (как в Планёрке) плюс ограниченный агентский шаг для спорных пунктов.
Правило проекта с 18.09.26: всё, что «всегда», — в коде, не в промпте.
"""

import time

from . import agent, intake, negation, protocol
from .control import Limits, RunBudget
from .errors import BadModelAnswer, BudgetExceeded, ProviderUnavailable, SetupError, SourceRejected
from .heuristic import HeuristicClient
from .prompts import CLOSING_SYSTEM, DATA_CLOSE, DATA_OPEN, EXTRACT_SYSTEM
from .registry import key
from .text import chunk_lines, content_stems, coverage, norm, numbered_lines, render_lines, same_subject

QUOTE_SUPPORT = 0.5      # доля основ действия, найденных в цитате (окно строки и двух соседних)
SELF_DUP = 0.8           # повтор внутри одной встречи
REGISTRY_DUP = 0.6       # кандидат в повтор открытой задачи (порог Планёрки для дублей)
CLOSE_PAIR = 0.25        # основы задачи в окне фразы о свершившемся (порог закрытия Планёрки)
MASS_CLOSE_SHARE = 0.5   # закрытий больше половины открытых — подозрение на внедрение или сбой, всё к человеку

import re as _re

FIRST_PERSON = _re.compile(r"(^|\s)(я|сам|сама|беру|возьму)\s|\b[а-я]+(ю|у)\b\s.*\b(к|до)\s")
IMPERATIVE = _re.compile(r"\b[а-я]+(ите|йте|ьте)\b|\bпоручаю\b|\bпрошу\b")


class Run:
    def __init__(self, registry, client, limits, source_name):
        self.registry = registry
        self.client = client
        self.budget = RunBudget(limits or Limits())
        self.n = 0
        self.degraded = False
        self.limit_hit = None   # потолок сработал внутри прогона: встреча сохранена, часть пунктов у человека
        self.run_id = registry.start_run(source_name, getattr(client, "name", "?"))

    def log(self, name, ok, usage=None, detail="", seconds=0.0):
        self.n += 1
        usage = usage or {}
        self.registry.log_step(self.run_id, self.n, name, ok, usage.get("seconds", seconds),
                               usage.get("tokens_in", 0), usage.get("tokens_out", 0), detail)

    def call(self, system, user, purpose):
        """Вызов модели под потолком. Недоступна локальная модель — один запасной уровень: правила (видимая деградация)."""
        self.budget.before_call(len(system) + len(user))
        # один вызов не может съесть больше оставшегося времени прогона (ревью 03.10.26, п. 14)
        if hasattr(self.client, "base_timeout"):
            self.client.timeout = max(5.0, min(self.client.base_timeout, self.budget.limits.max_seconds - self.budget.elapsed()))
        try:
            obj, usage = self.client.complete_json(system, user, purpose)
        except ProviderUnavailable as e:
            if isinstance(self.client, HeuristicClient):
                raise
            self.log(purpose, False, detail=f"модель недоступна, переход на правила: {e}")
            self.client = HeuristicClient()
            self.degraded = True
            obj, usage = self.client.complete_json(system, user, purpose)
        self.budget.after_call(usage["tokens_in"], usage["tokens_out"], usage["cost_usd"])
        self.log(purpose, True, usage)
        return obj


def _window(lines_by_n, n, before=1, after=1):
    return " ".join(lines_by_n[i]["text"] for i in range(n - before, n + after + 1) if i in lines_by_n)


def _card(kind, title, quote=None, payload=None, task_id=None):
    # ключ карточки — по содержанию, а не по заголовку: одинаковые заголовки разных пунктов не должны схлопываться
    # (cost-attack 03.10.26: 18 неразобранных пунктов слились в одну карточку)
    import json as _json
    idem = key("card", kind, title, quote, _json.dumps(payload or {}, ensure_ascii=False, sort_keys=True))
    return {"kind": kind, "title": title, "quote": quote, "payload": payload or {}, "task_id": task_id, "idem_key": idem}


def process(text: str, source_name: str, meeting_date: str, registry, team, client=None, limits=None,
            title: str = "") -> dict:
    client = client or HeuristicClient()
    run = Run(registry, client, limits, source_name)
    meeting_id = None
    t0 = time.monotonic()
    try:
        # 1. Вход: отказ до создания встречи и до денег
        try:
            _check_date(meeting_date)
            src = intake.check(text, source_name)
        except SourceRejected as e:
            run.log("intake", False, detail=f"{e.code}: {e}", seconds=time.monotonic() - t0)
            registry.finish_run(run.run_id, None, "rejected", run.budget, str(e))
            return {"outcome": "rejected", "reason": str(e), "code": e.code, "run_id": run.run_id}
        run.log("intake", True, detail=f"вид: {src['kind']}; подозрительных строк: {src['suspicious']}", seconds=time.monotonic() - t0)

        digest = intake.digest(src["text"])
        prev = registry.meeting_by_digest(digest)
        if prev and prev["status"] == "processed":
            registry.finish_run(run.run_id, prev["id"], "duplicate", run.budget, "источник уже обработан")
            return {"outcome": "duplicate", "meeting_id": prev["id"], "run_id": run.run_id}
        meeting_id = registry.create_meeting(meeting_date, title, digest, source_name)

        lines = numbered_lines(src["text"])
        cards = []
        injected = [l for l in lines if intake.is_injection(l["text"])]
        if injected:
            cards.append(_card("suspicious_text", "В записи есть реплики, обращённые к системе; в разбор они не взяты",
                               quote=" / ".join(l["text"][:160] for l in injected[:3]),
                               payload={"lines": [l["n"] for l in injected]}))
        clean_lines = [l for l in lines if l not in injected]
        # окна контекста — только из чистых строк: внедрение не должно попасть и в запрос закрытий (ревью 03.10.26)
        by_n = {l["n"]: l for l in clean_lines}
        failed_chunks = 0

        # 2. Извлечение поручений по кускам. Превышение числа кусков — остановка по пределу до вызовов
        chunks = chunk_lines(clean_lines, run.budget.limits.chunk_chars)
        if len(chunks) > run.budget.limits.max_chunks:
            raise BudgetExceeded("кусков записи на встречу", len(chunks), run.budget.limits.max_chunks)
        roster_hint = "Команда: " + "; ".join(p["full_name"] for p in team.people)
        raw = []
        for i, ch in enumerate(chunks):
            user = f"{roster_hint}\n\n{DATA_OPEN}\n{render_lines(ch)}\n{DATA_CLOSE}"
            try:
                obj = run.call(EXTRACT_SYSTEM, user, f"extract:{i + 1}/{len(chunks)}")
            except BadModelAnswer as e:  # плохой ответ после повтора: кусок к человеку, остальные идут дальше
                failed_chunks += 1
                cards.append(_card("chunk_failed", f"Кусок записи {i + 1} не разобран моделью", payload={"error": str(e)}))
                continue
            got = obj.get("assignments")
            if not isinstance(got, list):   # ответ модели — данные неизвестной формы: не тот тип — кусок не разобран
                failed_chunks += 1
                cards.append(_card("chunk_failed", f"Кусок записи {i + 1}: ответ модели не по контракту", payload={"answer": str(got)[:200]}))
                continue
            raw.extend(_norm_assignment(a) for a in got if isinstance(a, dict))

        # 3. Проверки кодом: опора на строку, форма поручения, исполнитель в строке, сверка с «Командой»
        accepted, items, held = [], [], []
        seen = set()
        active = registry.active_tasks()
        for a in raw:
            try:
                n = int(a.get("line"))
            except (TypeError, ValueError):
                held.append(_card("held_task", "Поручение без номера строки", payload=a))
                continue
            line = by_n.get(n)
            if not line or line in injected:
                held.append(_card("held_task", "Поручение ссылается на строку, которой нет в записи", payload=a))
                continue
            # ключ включает действие: два разных поручения одному человеку в одной строке — две задачи (ревью 03.10.26)
            sig = (n, norm(a["to"]), norm(a["action"]))
            if sig in seen:
                continue
            seen.add(sig)
            quote = (f"{line['speaker']}: " if line["speaker"] else "") + line["text"]
            action = str(a.get("action") or "").strip()
            to = str(a.get("to") or "").strip()
            shape = negation.is_assignment_shape(line["text"])
            if not shape["ok"]:
                held.append(_card("held_task", f"Не поручение: {shape['reason']}", quote=quote, payload=a))
                continue
            if not action or coverage(action, _window(by_n, n)) < QUOTE_SUPPORT:
                held.append(_card("held_task", "Формулировка задачи не опирается на слова встречи", quote=quote, payload=a))
                continue
            if negation.classify(line["text"])["fact"] and not FIRST_PERSON.search(norm(line["text"])) \
                    and not IMPERATIVE.search(norm(line["text"])):
                held.append(_card("held_task", "Не поручение: отчёт о сделанном", quote=quote, payload=a))
                continue
            to_words = [w for w in norm(to).split() if len(w) >= 2]
            in_text = any(w[:4] in norm(_window(by_n, n, 1, 0)) for w in to_words)
            is_speaker = bool(line["speaker"]) and any(w[:4] in norm(line["speaker"]) for w in to_words)
            # говорящий становится исполнителем, только если сам берёт работу («я подготовлю»)
            if not to or not (in_text or (is_speaker and FIRST_PERSON.search(norm(line["text"])))):
                held.append(_card("held_task", "Исполнитель не прозвучал рядом с поручением", quote=quote, payload=a))
                continue
            r = team.resolve(to)
            item = {"line": n, "to": to, "action": action, "due": _supported_due(a.get("due"), _window(by_n, n, 0, 1)), "quote": quote,
                    "status": r["status"], "reason": r["reason"]}
            if r["status"] in ("exact", "fixed", "department") and len(r["candidates"]) == 1:
                item["responsible_id"] = r["candidates"][0]
                dup = [t for t in active if t.get("responsible_id") == item["responsible_id"]
                       and same_subject(action, t["description"], REGISTRY_DUP)]
                if dup:
                    items.append({**item, "kind": "duplicate"})
                else:
                    accepted.append(item)
            else:
                items.append({**item, "kind": "person"})
        run.log("gates", True, detail=f"извлечено {len(raw)}, принято {len(accepted)}, спорных {len(items)}, отложено {len(held)}")

        # 4. Разрешающий агент для спорных пунктов
        duplicates = 0
        if items:
            ctx = {"team": team, "lines": clean_lines, "tasks": active}
            resolved = agent.resolve_items(items, ctx, run.client, run.budget,
                                           lambda name, ok, usage, detail: run.log(name, ok, usage, detail))
            stopped = [it for it in resolved if str(it.get("reason", "")).startswith("остановлено по пределу")]
            if stopped:
                run.limit_hit = stopped[0]["reason"]
                cards.append(_card("limit", f"Остановлено по пределу: {len(stopped)} спорных пунктов не разобраны, нужно решение",
                                   payload={"reason": stopped[0]["reason"],
                                            "items": [{"line": it["line"], "to": it["to"], "action": it["action"], "quote": it["quote"]}
                                                      for it in stopped]}))
            for it in resolved:
                d = it.get("decision")
                if it in stopped:
                    continue
                if d == "assign":
                    accepted.append({**it, "responsible_id": it["person_id"]})
                elif d == "accept_new":
                    accepted.append(it)
                elif d == "duplicate":
                    duplicates += 1   # след остаётся и в протоколе, и в журнале (ревью 03.10.26)
                    run.log("duplicate", True, detail=f"строка {it['line']} повторяет задачу №{it['task_id']}")
                else:
                    held.append(_card("held_task", f"Нужно решение: {it.get('reason', '')}", quote=it["quote"],
                                      payload={"to": it["to"], "action": it["action"], "line": it["line"],
                                               "candidates": team.resolve(it["to"])["candidates"]}))

        # повтор внутри встречи: одна задача одному человеку дважды не заводится
        new_tasks = []
        for it in accepted:
            if any(t.get("responsible_id") == it.get("responsible_id") and same_subject(it["action"], t["description"], SELF_DUP)
                   for t in new_tasks):
                continue
            new_tasks.append({"description": it["action"][:1].upper() + it["action"][1:], "responsible_id": it.get("responsible_id"),
                              "responsible_text": None if it.get("responsible_id") else it["to"], "due": it.get("due"),
                              "line": it["line"], "quote": it["quote"]})

        # 5. Закрытия: кандидаты отбирает код, модель отвечает номером фразы, цитату берёт код
        closures = []
        closing_failed = False
        try:
            closures = _closures(run, clean_lines, by_n, active, meeting_id, meeting_date, cards)
        except (BadModelAnswer, ProviderUnavailable) as e:  # частичный отказ: протокол без закрытий, но не без протокола
            closing_failed = True
            cards.append(_card("closing_failed", "Сверка закрытий не выполнена; задачи остались открытыми", payload={"error": str(e)}))

        # 6. Потолок записей до записи
        run.budget.before_artifact(len(new_tasks) + len(closures) + len(cards) + len(held))

        people = {p["id"]: p["full_name"] for p in team.people}
        closed_ids = {c["task_id"] for c in closures}
        open_after = [t for t in active if t["id"] not in closed_ids] + [{**t} for t in new_tasks]
        # протокол не пишет «не прозвучало», если часть записи не разобрана (ревью 03.10.26)
        notes = {"failed_chunks": failed_chunks, "closing_unfinished": closing_failed or any(c["kind"] == "mass_closure" for c in cards),
                 "duplicates": duplicates}
        md = protocol.render(meeting_date, title, new_tasks, closures, len(held), open_after, people, run.degraded, notes)
        if run.degraded:
            cards.append(_card("degraded", "Протокол собран без модели: локальная модель была недоступна"))
        result = registry.apply_meeting_result(meeting_id, meeting_date, new_tasks, closures, cards + held, md)
        run.log("write", True, detail=f"задач {len(result['created'])}, закрыто {len(result['closed'])}, карточек {len(result['cards'])}")
        # «сделано» и «остановлено по пределу» — разные события (урок 5): различаем исходом прогона
        outcome = "partial_limit" if run.limit_hit else ("degraded" if run.degraded else "done")
        registry.finish_run(run.run_id, meeting_id, outcome, run.budget, run.limit_hit or "")
        return {"outcome": outcome, "limit": run.limit_hit, "meeting_id": meeting_id, "run_id": run.run_id,
                "created": result["created"], "closed": result["closed"], "cards": result["cards"],
                "held": len(held), "protocol_md": md, "calls": run.budget.calls, "steps": run.budget.steps,
                "tokens_in": run.budget.tokens_in, "tokens_out": run.budget.tokens_out, "cost_usd": run.budget.cost_usd}

    except BudgetExceeded as e:
        # исход к человеку, не повтор: одна карточка, встреча помечена, ничего частично не записано
        run.log("limit", False, detail=str(e))
        if meeting_id is not None:
            registry.set_meeting_status(meeting_id, "stopped_by_limit")
        registry.add_card("limit", f"Обработка остановлена по пределу: {e.limit}", meeting_id,
                          payload={"value": e.value, "ceiling": e.ceiling, "source": source_name})
        registry.finish_run(run.run_id, meeting_id, "stopped_by_limit", run.budget, str(e))
        return {"outcome": "stopped_by_limit", "limit": e.limit, "meeting_id": meeting_id, "run_id": run.run_id,
                "calls": run.budget.calls, "steps": run.budget.steps}
    except (SetupError, ProviderUnavailable) as e:
        run.log("error", False, detail=str(e))
        if meeting_id is not None:
            registry.set_meeting_status(meeting_id, "failed")
        registry.add_card("setup" if isinstance(e, SetupError) else "provider", str(e), meeting_id)
        registry.finish_run(run.run_id, meeting_id, "failed", run.budget, str(e))
        return {"outcome": "failed", "reason": str(e), "meeting_id": meeting_id, "run_id": run.run_id}
    except Exception as e:  # noqa: BLE001 — непредвиденное: прогон закрывается, встреча помечена, человеку карточка
        detail = f"{type(e).__name__}: {e}"
        try:
            run.log("error", False, detail=detail)
            if meeting_id is not None:
                registry.set_meeting_status(meeting_id, "failed")
            registry.add_card("internal_error", "Внутренняя ошибка обработки встречи — нужен разбор", meeting_id,
                              payload={"error": detail, "source": source_name})
            registry.finish_run(run.run_id, meeting_id, "failed", run.budget, detail)
        except Exception:
            pass
        return {"outcome": "failed", "reason": detail, "meeting_id": meeting_id, "run_id": run.run_id}


def _check_date(d):
    from datetime import date
    try:
        date.fromisoformat(str(d))
    except ValueError:
        raise SourceRejected(f"Дата встречи «{d}» не в формате ГГГГ-ММ-ДД.", "bad_date")


def _norm_assignment(a: dict) -> dict:
    """Ответ модели — данные неизвестной формы: приводим поля к строкам, срок — строка или None."""
    due = a.get("due")
    return {"line": a.get("line"), "to": str(a.get("to") or "")[:120], "action": str(a.get("action") or "")[:400],
            "due": due.strip()[:60] if isinstance(due, str) and due.strip() and due.strip().lower() != "null" else None}


_DUE_STOP = {"до", "к", "ко", "срок", "в", "на", "не", "позднее", "позже"}


def _supported_due(due, window_text):
    """Срок принимается, только если его слова прозвучали рядом с поручением (ревью 03.10.26: «31.12.2030» из воздуха)."""
    if not due:
        return None
    said = norm(window_text)
    toks = [w for w in norm(due).replace(".", " ").replace("/", " ").split() if w not in _DUE_STOP]
    if toks and all((w if w.isdigit() else w[:5]) in said for w in toks):
        return due
    return None


def _closures(run, lines, by_n, active, meeting_id, meeting_date, cards):
    candidates = []
    for l in lines:
        c = negation.classify(l["text"])
        if c["fact"]:
            candidates.append({**l, "fact": c["fact"]})
    # своя встреча не закрывает свои задачи; ранняя встреча не закрывает задачу, поставленную позже (ревью 03.10.26)
    eligible = [t for t in active if t.get("source_meeting_id") != meeting_id and (t.get("date_set") or "") <= meeting_date]
    if not candidates or not eligible:
        run.log("closing", True, detail="кандидатов нет — модель не вызывалась")
        return []
    payload, phrase_by_k = [], {}
    k = 0
    for t in eligible:
        stems_t = content_stems(t["description"])
        scored = []
        for c in candidates:
            ctx_text = _window(by_n, c["n"], 2, 0)
            cov = len(stems_t & content_stems(ctx_text)) / max(1, len(stems_t))
            if cov >= CLOSE_PAIR:
                scored.append((cov, c, ctx_text))
        scored.sort(key=lambda x: -x[0])
        phrases = []
        for cov, c, ctx_text in scored[:4]:
            k += 1
            phrase_by_k[k] = (c, t["id"])
            phrases.append({"k": k, "text": ctx_text})
        if phrases:
            payload.append({"id": t["id"], "description": t["description"], "phrases": phrases})
    if not payload:
        run.log("closing", True, detail="ни одна фраза не касается открытых задач — модель не вызывалась")
        return []
    import json
    user = f"{DATA_OPEN}\nЗАДАЧИ: {json.dumps(payload, ensure_ascii=False)}\n{DATA_CLOSE}"
    obj = run.call(CLOSING_SYSTEM, user, "closing")
    out, used = [], set()
    tasks = {t["id"]: t for t in eligible}
    for c in obj.get("closures", []):
        try:
            kk, tid = int(c.get("phrase")), int(c.get("task_id"))
        except (TypeError, ValueError):
            continue
        pair = phrase_by_k.get(kk)
        if not pair or pair[1] != tid or tid in used:
            continue  # модель указала фразу, которую код этой задаче не предлагал
        phrase = pair[0]
        verdict = negation.classify(phrase["text"])
        if not verdict["fact"]:
            continue
        used.add(tid)
        quote = (f"{phrase['speaker']}: " if phrase["speaker"] else "") + phrase["text"]
        out.append({"task_id": tid, "status": verdict["fact"], "quote": quote, "description": tasks[tid]["description"]})
    if len(out) > max(3, MASS_CLOSE_SHARE * len(eligible)):
        cards.append(_card("mass_closure", f"Предложено закрыть {len(out)} задач из {len(eligible)} разом — нужна проверка человека",
                           payload={"task_ids": [c["task_id"] for c in out]}))
        run.log("closing", True, detail=f"массовое закрытие {len(out)} — отдано человеку")
        return []
    run.log("closing", True, detail=f"закрытий {len(out)}")
    return out


def idem(*parts):
    return key(*parts)
