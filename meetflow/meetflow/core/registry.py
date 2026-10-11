"""Реестр задач, карточки оператору и память решений.

Правила, ставшие кодом:
- Статус из встречи меняется только по цитате, которую правило отрицаний
  признало фактом (иначе — карточка «кандидат на закрытие»).
- «Снято» (dropped) — не «выполнено» (done); вернуть в работу можно оба.
- Каждое изменение пишется в историю с источником и цитатой.
- Нумерация для человека всегда с 1, внутренний id скрыт (02.10).
- Ответ оператора становится правилом только после N одинаковых ответов
  (по умолчанию 2: «на паузе: 1 из 2», ERP 02.10) — защита от ошибочного
  нажатия. Правила вида «не задача» затухают через 21 день. Снятие мягкое.
- Каждое решение по карточке — строка в журнале решений «что / решение / почему».
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .negation import NegationRule
from .store import Store, now
from .types import CardStatus, TaskStatus


class TaskRegistry:
    def __init__(self, store: Store, negation: NegationRule | None = None):
        self.s = store
        self.neg = negation or NegationRule()

    def add(self, project_id: int, description: str, assignee: str | None, meeting_id: int | None = None,
            quote: str = "", due_date: str | None = None, date_set: str | None = None) -> int:
        if meeting_id:   # формулировка от модели — через фильтр выхода; набранное человеком не трогаем
            from .guard import filter_text
            description = filter_text(description)[0]
        tid = self.s.insert("tasks", project_id=project_id, description=description, assignee=assignee,
                            status=TaskStatus.ACTIVE.value, due_date=due_date, date_set=date_set or now()[:10],
                            source_meeting_id=meeting_id, source_quote=quote)
        self._history(tid, None, TaskStatus.ACTIVE.value, "meeting" if meeting_id else "web_form", quote)
        return tid

    def set_assignee(self, task_id: int, assignee: str, by: str = "", note: str = "") -> None:
        """Исполнитель в уже заведённую задачу — по выбору в карточке «кто из них» / «тот же или
        новый» (письмо 30: выбор ставит исполнителя в ту же задачу, новую не заводит)."""
        with self.s.tx():
            t = self.s.get("tasks", task_id)
            if not t:
                raise KeyError(task_id)
            self.s.update("tasks", task_id, assignee=assignee)
            self._history(task_id, t["status"], t["status"], "operator",
                          f"исполнитель: {assignee}" + (f" ({note})" if note else ""), by)

    def set_status(self, task_id: int, status: TaskStatus, source: str, quote: str = "",
                   by: str = "", meeting_date: str | None = None) -> bool:
        """source='meeting' требует цитату-факт. Возвращает, применено ли.
        Чтение и запись — одной транзакцией: иначе история рвалась при
        одновременных изменениях (итерация 4, 5 прогонов из 5)."""
        if source == "meeting" and status != TaskStatus.ACTIVE:
            ok = self.neg.states_removal(quote) if status == TaskStatus.DROPPED else self.neg.check(quote).states_fact
            if not quote or not ok:
                return False
        with self.s.tx():
            t = self.s.get("tasks", task_id)
            if not t:
                raise KeyError(task_id)
            closed = (meeting_date or now()[:10]) if status != TaskStatus.ACTIVE else None
            self.s.update("tasks", task_id, status=status.value, date_closed=closed)
            self._history(task_id, t["status"], status.value, source, quote, by)
        return True

    def comment(self, task_id: int, text: str, by: str) -> None:
        self.s.update("tasks", task_id, last_comment=text[:2000])
        self._history(task_id, None, None, "member_note", text[:2000], by)

    def _history(self, task_id, old, new, source, quote="", by="") -> None:
        self.s.insert("task_history", task_id=task_id, old_status=old, new_status=new, source=source,
                      evidence_quote=quote, changed_by=by, at=now())

    def list(self, project_id: int, status: TaskStatus | None = TaskStatus.ACTIVE) -> list[dict]:
        if status is None:
            rows = self.s.q("SELECT * FROM tasks WHERE project_id=? ORDER BY id", (project_id,))
        else:
            rows = self.s.q("SELECT * FROM tasks WHERE project_id=? AND status=? ORDER BY id",
                            (project_id, status.value))
        for i, r in enumerate(rows, 1):
            r["no"] = i  # номер для человека; id — только внутренний
        return rows

    def search(self, project_id: int, query: str) -> list[dict]:
        """Поиск без учёта регистра кириллицы — в Python (SQLite lower() её не знает)."""
        q = query.casefold().replace("ё", "е")
        return [r for r in self.list(project_id, None)
                if q in (r["description"] or "").casefold().replace("ё", "е")
                or q in (r["assignee"] or "").casefold().replace("ё", "е")]

    def history(self, task_id: int) -> list[dict]:
        return self.s.q("SELECT * FROM task_history WHERE task_id=? ORDER BY id", (task_id,))


class CardQueue:
    def __init__(self, store: Store):
        self.s = store

    def open(self, project_id: int, kind: str, title: str, payload: dict | None = None,
             meeting_id: int | None = None) -> int:
        """Та же открытая карточка не заводится второй раз (повторный прогон,
        повторяющийся сбой) — «двойной работы быть не должно» (16.09)."""
        body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with self.s.tx():
            same = self.s.q("SELECT id, payload FROM cards WHERE project_id IS ? AND meeting_id IS ? AND kind=? "
                            "AND title=? AND status='open'", (project_id, meeting_id, kind, title))
            for c in same:
                if json.dumps(json.loads(c["payload"] or "{}"), ensure_ascii=False, sort_keys=True) == body:
                    return c["id"]
            return self.s.insert("cards", project_id=project_id, meeting_id=meeting_id, kind=kind, title=title,
                                 payload=payload or {}, status=CardStatus.OPEN.value, created_at=now())

    def cleanup(self, project_id: int, days: int) -> int:
        """Нерешённые карточки старше N дней снимаются (решение 01.10, порог
        в теме operator.card_cleanup_days; 0 — не снимать). Снятие — статус,
        а не удаление: след остаётся."""
        if days <= 0:
            return 0
        edge = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        # карточки выбора и подтверждения исполнителя не снимаются сами (документ 14)
        rows = self.s.q("SELECT id FROM cards WHERE project_id=? AND status='open' AND created_at < ? "
                        "AND kind NOT IN ('technical', 'assign_person', 'confirm_person')", (project_id, edge))
        for r in rows:
            self.s.update("cards", r["id"], status=CardStatus.REJECTED.value, resolution="снято по сроку",
                          resolved_at=now())
        return len(rows)

    def list(self, project_id: int, status: CardStatus | None = CardStatus.OPEN) -> list[dict]:
        if status is None:
            rows = self.s.q("SELECT * FROM cards WHERE project_id=? ORDER BY id", (project_id,))
        else:
            rows = self.s.q("SELECT * FROM cards WHERE project_id=? AND status=? ORDER BY id",
                            (project_id, status.value))
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    def resolve(self, card_id: int, status: CardStatus, resolution: str = "", why: str = "") -> dict:
        with self.s.tx():
            card = self.s.get("cards", card_id)
            if not card:
                raise KeyError(card_id)
            if card["status"] != CardStatus.OPEN.value:
                # check-then-write под одним замком: второе решение не затирает первое
                return card
            self.s.update("cards", card_id, status=status.value, resolution=resolution, resolved_at=now())
            self.s.insert("decisions", project_id=card["project_id"], what=card["title"],
                          decision=f"{status.value}: {resolution}".strip(": "), why=why, at=now())
        return self.s.get("cards", card_id) or card


class OperatorMemory:
    DECAYING = {"not_a_task": 21}

    def __init__(self, store: Store, confirmations: int = 2):
        self.s = store
        self.n = max(1, confirmations)

    def answer(self, project_id: int, kind: str, key: str, value: str) -> dict:
        key_n = key.strip().lower()
        rows = self.s.q("SELECT * FROM operator_rules WHERE project_id=? AND kind=? AND key=? AND revoked_at IS NULL",
                        (project_id, kind, key_n))
        if rows:
            rule = rows[0]
            pending = json.loads(rule["pending_answers"] or "[]")
        else:
            rid = self.s.insert("operator_rules", project_id=project_id, kind=kind, key=key_n, value=value,
                                pending_answers=[], active=0, created_at=now())
            rule, pending = self.s.get("operator_rules", rid), []
        pending.append(value)
        same = pending[-self.n:]
        active = len(same) >= self.n and len(set(same)) == 1
        expires = None
        if active and kind in self.DECAYING:
            expires = (datetime.now() + timedelta(days=self.DECAYING[kind])).strftime("%Y-%m-%dT%H:%M:%S")
        self.s.update("operator_rules", rule["id"], pending_answers=pending[-5:], value=value,
                      active=int(active), expires_at=expires)
        out = self.s.get("operator_rules", rule["id"])
        out["status_text"] = "действует" if active else f"на паузе: {min(len(same), self.n)} из {self.n}"
        return out

    def lookup(self, project_id: int, kind: str, key: str) -> str | None:
        rows = self.s.q("SELECT * FROM operator_rules WHERE project_id=? AND kind=? AND key=? AND active=1 "
                        "AND revoked_at IS NULL", (project_id, kind, key.strip().lower()))
        if not rows:
            return None
        r = rows[0]
        if r["expires_at"] and r["expires_at"] < now():
            return None
        self.s.update("operator_rules", r["id"], applied_count=r["applied_count"] + 1)
        return r["value"]

    def revoke(self, rule_id: int) -> None:
        self.s.update("operator_rules", rule_id, revoked_at=now())

    def restore(self, rule_id: int) -> None:
        self.s.update("operator_rules", rule_id, revoked_at=None)
