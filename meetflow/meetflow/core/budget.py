"""Control layer: потолки на прогон и журнал вызовов.

Курс (занятие 5, позиция 5.3): max steps, max cost, fallback — лимиты стоят
в самом сценарии, «сделано» и «остановлено по пределу» различаются, при
атаке потолки не выключаются. Из проектов:
- ERP: 20 вызовов / 2 $ на прогон; Планёрка: 14 вызовов (+1 бронь на
  проверку), 0.40 $, 400 000 знаков на вызов.
- Проверка ДО вызова модели; превышение — BudgetExceeded без повтора.
- У Планёрки денежный потолок был объявлен, но по умолчанию не исполнялся
  (LLM_COST_LIMIT_ENFORCED=off) — здесь исполняется всегда.
- Для локальной модели денег нет, но есть время и GPU: max_seconds.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """Остановлено по пределу. Сообщение начинается с этой фразы — так
    оператор отличает остановку от сбоя."""


@dataclass
class BudgetLimits:
    max_calls: int = 14
    verify_reserve: int = 1
    max_cost_usd: float = 0.40
    max_chars_per_call: int = 400_000
    max_seconds: float = 3600.0


@dataclass
class RunBudget:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    calls: int = 0
    cost_usd: float = 0.0
    max_call_cost: float = 0.0
    max_price_per_char: float = 0.0     # самая высокая цена знака запроса из сделанных вызовов
    started: float = field(default_factory=time.monotonic)
    stopped_by: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def check(self, prompt_chars: int, purpose: str = "", worst_usd: float | None = None) -> None:
        """Вызывается до каждого обращения к модели."""
        with self._lock:
            limit = self.limits.max_calls + (self.limits.verify_reserve if purpose == "verify" else 0)
            if self.calls >= limit:
                self._stop("calls", f"вызовов {self.calls} из {limit}")
            # прогноз: следующий вызов не дешевле самого дорогого из сделанных (атака Б) и
            # не дешевле своего размера по самой высокой цене знака — крупный запрос после
            # мелких перепрыгивал потолок: 0,05 + 0,05 + 0,35 при пределе 0,40 (письмо 01/9)
            expected = max(self.max_call_cost, self.max_price_per_char * prompt_chars)
            # худший случай от подключения (цена токена × запрос + потолок ответа 4096): вызов,
            # который в остаток не помещается, не делается — потолок не перепрыгивается (01/9)
            if worst_usd is not None:
                expected = max(expected, worst_usd)
            projected = self.cost_usd + expected
            if self.cost_usd >= self.limits.max_cost_usd or ((self.calls or worst_usd is not None)
                                                              and projected > self.limits.max_cost_usd):
                self._stop("cost", f"расход {self.cost_usd:.3f} $ (+{expected:.3f} $ ожидается) "
                                   f"из {self.limits.max_cost_usd} $")
            if prompt_chars > self.limits.max_chars_per_call:
                self._stop("chars", f"запрос {prompt_chars} знаков, предел {self.limits.max_chars_per_call}")
            if time.monotonic() - self.started > self.limits.max_seconds:
                self._stop("time", f"время прогона больше {self.limits.max_seconds:.0f} с")
            self.calls += 1

    @property
    def deadline(self) -> float:
        """Момент конца прогона по max_seconds (time.monotonic)."""
        return self.started + self.limits.max_seconds

    def add_cost(self, usd: float, prompt_chars: int = 0) -> None:
        with self._lock:
            usd = max(0.0, usd or 0.0)
            self.cost_usd += usd
            self.max_call_cost = max(self.max_call_cost, usd)
            if prompt_chars > 0:
                self.max_price_per_char = max(self.max_price_per_char, usd / prompt_chars)

    def _stop(self, by: str, detail: str) -> None:
        self.stopped_by = by
        raise BudgetExceeded(f"Остановлено по пределу: {detail}")


class CallJournal:
    """Журнал вызовов модели (jsonl): строка на вызов и итог прогона."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def write(self, **rec) -> None:
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self._lock:
            self.records.append(rec)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
