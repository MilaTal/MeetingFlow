"""Контрольный слой: четыре потолка курса (шаги, деньги, время, артефакты) плюс вызовы и длина запроса.

Все потолки проверяются КОДОМ ДО обращения к модели. После потолка — исход к человеку
(карточка оператору), повтор запрещён: он кормит разгон (урок 5 курса; Планёрка, Т3).
Числа и их источники — в LIMIT_SOURCES, они же уходят в паспорт (лист потолков).
"""

import os
import time
from dataclasses import dataclass, field

from .errors import BudgetExceeded

LIMIT_SOURCES = {
    "max_calls": "наблюдаемый максимум Планёрки 10–11 вызовов на прогон при потолке 14 (журнал llm_calls.jsonl, 30.09.26)",
    "max_steps": "шагов разрешающего агента: опыт плюс один — в эталонном наборе нужно до 8 шагов, потолок 12",
    "max_chars_per_call": "кусок 12 000 знаков из Планёрки (41 из 43 источников режутся) с запасом x4 на справочники",
    "max_chunks": "самая длинная запись Планёрки ~52 тыс. знаков = 5 кусков; потолок 10 кусков = встреча около 2 часов",
    "max_cost_usd": "наблюдаемый максимум прогона Планёрки 0,228 $ x ~1,75 = 0,40 $ (только для облачного режима; локально 0)",
    "max_seconds": "час секретаря на протокол (оценка владельца 23.09.26) — машина не должна думать дольше 20 минут",
    "max_artifacts": "максимум записей за планёрку в Планёрке: ~12 задач + ~10 карточек; потолок 40",
}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Limits:
    max_calls: int = field(default_factory=lambda: _env_int("MR_MAX_CALLS", 14))
    max_steps: int = field(default_factory=lambda: _env_int("MR_MAX_STEPS", 12))
    max_chars_per_call: int = field(default_factory=lambda: _env_int("MR_MAX_CHARS", 48000))
    chunk_chars: int = field(default_factory=lambda: _env_int("MR_CHUNK_CHARS", 12000))
    max_chunks: int = field(default_factory=lambda: _env_int("MR_MAX_CHUNKS", 10))
    max_cost_usd: float = field(default_factory=lambda: _env_float("MR_MAX_COST_USD", 0.40))
    max_seconds: float = field(default_factory=lambda: _env_float("MR_MAX_SECONDS", 1200))
    max_artifacts: int = field(default_factory=lambda: _env_int("MR_MAX_ARTIFACTS", 40))


@dataclass
class RunBudget:
    limits: Limits
    calls: int = 0
    steps: int = 0
    artifacts: int = 0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    started: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def before_call(self, prompt_chars: int):
        """Проверка до вызова модели. Ничего не тратится, если потолок уже достигнут."""
        if self.calls + 1 > self.limits.max_calls:
            raise BudgetExceeded("вызовов модели за прогон", self.calls + 1, self.limits.max_calls)
        if prompt_chars > self.limits.max_chars_per_call:
            raise BudgetExceeded("знаков в одном запросе", prompt_chars, self.limits.max_chars_per_call)
        # прогноз, а не факт: следующий вызов не должен перепрыгнуть потолок (cost-attack 03.10.26: 0,48 $ при 0,40 $).
        # Цену будущего вызова до ответа не знает никто — берём среднюю цену уже сделанных вызовов этого прогона.
        projected = self.cost_usd + (self.cost_usd / self.calls if self.calls else 0.0)
        if projected > self.limits.max_cost_usd:
            raise BudgetExceeded("стоимость прогона, $ (с учётом следующего вызова)", round(projected, 4), self.limits.max_cost_usd)
        self.check_time()
        self.calls += 1

    def after_call(self, tokens_in: int, tokens_out: int, cost_usd: float):
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += cost_usd

    def before_step(self):
        if self.steps + 1 > self.limits.max_steps:
            raise BudgetExceeded("шагов разрешающего агента", self.steps + 1, self.limits.max_steps)
        self.check_time()
        self.steps += 1

    def before_artifact(self, n: int = 1):
        if self.artifacts + n > self.limits.max_artifacts:
            raise BudgetExceeded("записей в реестр и карточек за прогон", self.artifacts + n, self.limits.max_artifacts)
        self.artifacts += n

    def check_time(self):
        if self.elapsed() > self.limits.max_seconds:
            raise BudgetExceeded("время прогона, с", round(self.elapsed()), self.limits.max_seconds)
