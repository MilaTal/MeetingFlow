"""Правило отрицаний (общий промпт 21.09.26, обязателен для всех проектов).

Слово в фразе не делает факта. Отрицание, вопрос, условие, намерение,
поручение и частичный результат статус задачи не меняют. При сомнении — отказ.
Механизм в ядре, словарь — в теме (lexicon.negation), здесь умолчание для ru.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .morph import has_done_form

DEFAULT_LEXICON: dict[str, list[str]] = {
    "negation": [r"\bне\s+\w+", r"\bнет\b", r"\bни\s+разу\b", r"\bникак\b", r"\bне\s*-?\s*актуальн"],
    "question": [r"\?", r"\bли\b", r"\bразве\b", r"\bкогда\s+будет\b"],
    "condition": [r"\bесли\b", r"\bв\s+случае\b", r"\bпри\s+условии\b"],
    "intent": [r"\bпланиру\w*", r"\bбуд(у|ем|ет|ут|ешь|ете)\b", r"\bсобира\w+ся\b", r"\bнадо\b", r"\bнужно\b",
               r"\bхоти?м\b", r"\bпопробу(ю|ем|ет|ют|ешь|ете)\b", r"\bрешили\s+опробовать\b", r"\bк\s+следующей\b",
               r"\bначн(у|ём|ем|ут|ет)\b", r"\bзавтра\b", r"\bпослезавтра\b"],
    "assignment": [r"\bпоручи\w*", r"\bпрошу\b(?!\s+прощения)", r"\bсделай\w*\b", r"\bподготов(ь|ьте)\b",
                   r"\b\w{3,}(ите|йте)\b"],
    "partial": [r"\bчастично\b", r"\bпочти\b", r"\bначали\b", r"\bв\s+процессе\b", r"\bпока\s+не\b",
                r"\bтолько\b", r"\bполовин\w*"],
}

# Только прошедшее время и краткие причастия: настоящее («готовим»,
# «выполняем») и будущее факта не делают (находка ревью 03.10).
DONE_WORDS_DEFAULT = [r"\bсделан[аоы]?\b", r"\bсделал[аи]?\b", r"\bвыполнен[аоы]?\b", r"\bвыполнил[аи]?\b",
                      r"\bготов[аоы]?\b", r"\bзакрыт[аоы]?\b", r"\bзакрыл[аи]?\b", r"\bзаверш[её]н[аоы]?\b",
                      r"\bзавершил[аи]?\b", r"\bполучен[аоы]?\b", r"\bполучил[аи]?\b", r"\bотправлен[аоы]?\b",
                      r"\bотправил[аи]?\b", r"\bсогласован[аоы]?\b", r"\bсогласовал[аи]?\b"]


# Снятие задачи по голосу (решение владельца 03.10.26, «как для единиц»): только
# явные слова снятия. «Больше не нужна» — снятие, хотя в ней есть «не»: эти
# слова вырезаются до проверки блокеров. «Не отменили», «отменять не будем» — нет.
REMOVAL_WORDS = [r"\bотменил[аи]?\b", r"\bотмен[её]н[аоы]?\b", r"\bсним(аем|ают)\b", r"\bснял[аи]?\b", r"\bснят[аоы]?\b",
                 r"\bотказал(ись|ся|ась)\b", r"\bвычеркнул[аи]?\b", r"\bбольше\s+не\s+(нужн\w*|актуал\w*|делаем)\b",
                 r"\bне\s*актуал\w*\b"]
REMOVAL_DENIED = [r"\bне\s+(отмен\w*|сним\w*|снял\w*|снят\w*|отказ\w*|вычерк\w*)",
                  r"\b(отмен|снима|снять|сним|отказ|вычерк)\w*\s+(\w+\s+){0,3}не\s+(будем|станем|надо|нужно|стоит)\b"]


@dataclass
class NegationVerdict:
    states_fact: bool
    blockers: list[str] = field(default_factory=list)


class NegationRule:
    def __init__(self, lexicon: dict[str, list[str]] | None = None,
                 done_words: list[str] | None = None):
        lex = {k: list(v) for k, v in DEFAULT_LEXICON.items()}
        for k, v in (lexicon or {}).items():
            lex[k] = list(v)
        self._lex = {k: [re.compile(p, re.I) for p in v] for k, v in lex.items()}
        self._done = [re.compile(p, re.I) for p in (done_words or DONE_WORDS_DEFAULT)]

    def check(self, phrase: str) -> NegationVerdict:
        """Утверждает ли фраза свершившийся факт. Без «слова выполнения» —
        не утверждает; с любым блокирующим признаком — не утверждает."""
        p = phrase.strip()
        blockers = [kind for kind, pats in self._lex.items() if any(r.search(p) for r in pats)]
        # список — быстрый путь; морфология ловит глаголы вне списка («посчитали», «оплачен»,
        # письмо meeting-registry 01/15). Блокеры по-прежнему проверяются раньше и отдельно
        has_done = any(r.search(p) for r in self._done) or has_done_form(p) is True
        # «не сделано» — блокер negation; «сделано» без блокеров — факт
        if not has_done:
            return NegationVerdict(False, blockers + ["no_done_word"])
        return NegationVerdict(not blockers, blockers)

    def states_removal(self, phrase: str) -> bool:
        """Сообщает ли фраза, что задачу сняли. Вопрос, условие, намерение,
        частичность и отрицание самого снятия — не снятие."""
        p = phrase.strip()
        rem = [re.compile(x, re.I) for x in REMOVAL_WORDS]
        if not any(r.search(p) for r in rem) or any(re.search(x, p, re.I) for x in REMOVAL_DENIED):
            return False
        rest = p
        for r in rem:
            rest = r.sub(" ", rest)
        blockers = {kind for kind, pats in self._lex.items() if any(r.search(rest) for r in pats)}
        return not blockers & {"question", "condition", "intent", "partial"}
