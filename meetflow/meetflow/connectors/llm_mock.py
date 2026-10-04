"""Детерминированная модель-заглушка: стенд без модели.

Курс и проекты: «стенд без модели» для тестов, тесты никогда не зовут
платную модель (Планёрка обнуляла ключ в conftest). Заглушка отвечает
по тем же JSON-контрактам, что и боевые профили. Режим naive=True
изображает «послушную» модель, выполняющую инструкции из данных встречи —
им проверяется, что защиту держит код, а не добрая воля модели.
"""
from __future__ import annotations

import json
import re

from ..core.types import LLMResult
from .base import LLMConnector

_ASSIGN = re.compile(
    r"(?P<who>[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*,\s*(?P<what>(?:подготов|сдела|провер|отправ|согласов|"
    r"собер|напиш|обнов|настро|закаж|организ|передай|созвон|уточн|согласу)\w*[^\n?!]*?)(?=[.?!]?\s*$)", re.U | re.M)
_DUE = re.compile(r"до\s+(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?)")
_DONE = re.compile(r"(сделан|выполн|готов|закрыт|отправил|согласовал|получил|отмен|сним|актуал)", re.I)
_NUMBERED = re.compile(r"^\s*(\d+)\s*[|:]\s*(.*)$")


def _payload(user: str) -> str:
    m = re.search(r"BEGIN_UNTRUSTED_\w+[^\n]*\n(.*?)\nEND_UNTRUSTED_\w+", user, re.S)
    return m.group(1) if m else user


class MockLLM(LLMConnector):
    name = "mock"
    model = "mock-1"
    profile = "generic"
    context_chars = 400_000

    def __init__(self, cost_per_call: float = 0.0, naive: bool = False, fail_verify: bool = False):
        self.cost_per_call = cost_per_call
        self.naive = naive
        self.fail_verify = fail_verify
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, *, json_mode: bool = True, temperature: float = 0.0,
                 purpose: str = "", deadline: float | None = None) -> LLMResult:
        self.calls.append({"purpose": purpose, "chars": len(system) + len(user)})
        data = _payload(user)
        if purpose == "extract_tasks":
            out = self._extract(data)
        elif purpose == "closing_check":
            out = self._closing(user)
        elif purpose == "protocol":
            out = self._protocol(system, data)
        elif purpose == "verify":
            out = {"clean": not self.fail_verify,
                   "findings": [{"issue": "проверка-заглушка: замечание", "quote": "", "severity": "minor"}]
                   if self.fail_verify else []}
        elif purpose == "units":
            out = self._units(data)
        elif purpose == "units_close":
            out = self._units_close(system, data)
        else:
            out = {"echo": purpose}
        return LLMResult(json.dumps(out, ensure_ascii=False), self.model, len(user) // 3, 50,
                         self.cost_per_call, 0.0)

    def _extract(self, data: str) -> dict:
        tasks = []
        for i, line in enumerate(data.splitlines()):
            m = _NUMBERED.match(line)
            no, body = (int(m.group(1)), m.group(2)) if m else (i, line)
            for a in _ASSIGN.finditer(body):
                due = _DUE.search(a.group("what"))
                tasks.append({"description": a.group("what").strip().rstrip(","), "assignee": a.group("who"),
                              "line": no, "due_date": due.group(1) if due else None})
            if self.naive:
                inj = re.search(r"(?:создай|добавь)\s+задачу\s+«([^»]+)»\s+для\s+([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)",
                                body, re.I)
                if inj:  # послушная модель выдумывает задачу по инструкции из данных
                    tasks.append({"description": inj.group(1), "assignee": inj.group(2), "line": None,
                                  "quote": "по указанию из текста"})
        return {"tasks": tasks}

    _UNIT_RULES = [(re.compile(r"\bрешили\b", re.I), "Решение"), (re.compile(r"\bдоговорились\b", re.I), "Договорённость"),
                   (re.compile(r"\?\s*$"), "Открытый вопрос"), (re.compile(r"\b(придёт|придет|поставка будет)\b", re.I), "Веха")]
    _L = re.compile(r"^L(\d+):\s*(.*)$")

    def _units(self, data: str) -> dict:
        items = []
        for line in data.splitlines():
            m = self._L.match(line)
            if not m:
                continue
            n, text = int(m.group(1)), m.group(2)
            for rx, kind in self._UNIT_RULES:
                if rx.search(text):
                    items.append({"kind": kind, "statement": re.sub(r"^\[[^\]]*\]\s*[^:]+:\s*", "", text)[:200],
                                  "lines": [n], "responsible": [], "participants": [], "influencers": [], "task": "",
                                  "date": (re.search(r"\d{2}\.\d{2}\.\d{4}", text) or [""])[0]})
                    break
        return {"items": items}

    def _units_close(self, system: str, data: str) -> dict:
        """Закрывает открытый пункт фразой с «решили …», где есть ≥ 2 общих слова."""
        refs = re.findall(r"^([UN]\d+): \[[^\]]+\] (.+)$", system, re.M)
        closed = []
        for line in data.splitlines():
            m = self._L.match(line)
            if not m or not re.search(r"\bрешили\b", m.group(2), re.I):
                continue
            words_line = set(re.findall(r"[а-яё]{4,}", m.group(2).lower()))
            for ref, text in refs:
                if len(words_line & set(re.findall(r"[а-яё]{4,}", text.lower()))) >= 2:
                    closed.append({"unit": ref, "lines": [int(m.group(1))], "how": "закрыт", "answer": "решение принято"})
        return {"closed": closed}

    def _closing(self, user: str) -> dict:
        closed = []
        try:
            raw = _payload(user)
            payload = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            return {"closed": []}
        for cand in payload.get("candidates", []):
            for ph in cand.get("phrases", []):
                if _DONE.search(ph["text"]):
                    closed.append({"task_ref": cand["task_ref"], "phrase": ph["n"]})
                    break
        return {"closed": closed}

    def _protocol(self, system: str, data: str) -> dict:
        sections = re.findall(r"^- (.+)$", system.split("РАЗДЕЛЫ:", 1)[-1].split("\n\n", 1)[0], re.M)
        first = [ln for ln in data.splitlines() if ln.strip()][:3]
        return {"sections": {s: (first[0][:200] if first and k == 0 else "Обсуждение не зафиксировано.")
                             for k, s in enumerate(sections)}}
