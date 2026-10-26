"""Сборка промптов и профили целевых моделей продакшена (Ollama, локально).

Framework к моделям не подключается — он проектирует формат под них.
Значения контекста — консервативные умолчания, точные цифры ставит
оператор (PLACEHOLDER в теме llm.*.num_ctx).

Принципы из проектов:
- Узкие вызовы вместо одного холистического: закрытия в общем запросе
  давали 3 верных из 235 предложений, узкий — 21 предложение, 0 ложных.
- Модель отвечает НОМЕРОМ строки/фразы, цитату берёт код.
- Данные не в инструкции: источник огорожен метками (security.fence).
- Примеры в промпте — только иллюстрация формата (модель копировала пример
  «Нестерова Светлана» вместо реального имени).
- Большие таблицы модель не воспроизводит (0 из 14) — таблицы вставляет код.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .security import DATA_NOT_INSTRUCTIONS, fence


@dataclass(frozen=True)
class ModelProfile:
    name: str
    context_chars: int          # бюджет на весь запрос, знаков
    chunk_chars: int            # кусок источника для узких вызовов
    json_hint: str              # как просить JSON именно у этой модели
    strip_think: bool = False   # убирать <think>…</think> из ответа
    no_think_suffix: str = ""   # отключение рассуждений, если модель умеет
    supports_tools: bool = False


PROFILES: dict[str, ModelProfile] = {
    # GLM-5.3 / GLM-5.3-Flash / GLM-4.7-Flash: function calling, длинный контекст
    "glm": ModelProfile("glm", context_chars=96_000, chunk_chars=12_000,
                        json_hint="Ответ — один JSON-объект без пояснений и без markdown.",
                        supports_tools=True),
    # DeepSeek (R-серия рассуждает в <think>): рассуждения вырезаем
    "deepseek": ModelProfile("deepseek", context_chars=64_000, chunk_chars=10_000,
                             json_hint="Верни только JSON. Без текста до и после.", strip_think=True),
    # Qwen3 через Ollama: /no_think отключает рассуждение
    "qwen": ModelProfile("qwen", context_chars=64_000, chunk_chars=12_000,
                         json_hint="Ответ — строго JSON.", strip_think=True, no_think_suffix=" /no_think"),
    "generic": ModelProfile("generic", context_chars=32_000, chunk_chars=8_000,
                            json_hint="Ответ — строго JSON."),
}


def profile(name: str) -> ModelProfile:
    return PROFILES.get(name, PROFILES["generic"])


_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_json(text: str, strip_think: bool = True) -> dict:
    """Снимает обёртку ```json и рассуждения; берёт от первой { до последней }."""
    t = _THINK.sub("", text) if strip_think else text
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```\w*\n?|```$", "", t).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("ответ модели не JSON")
    return json.loads(t[i:j + 1], strict=False)   # сырая табуляция в цитате — не сбой (письмо 48)


def numbered(lines: list[str], start: int = 0) -> str:
    return "\n".join(f"{start + i} | {ln}" for i, ln in enumerate(lines))


def chunks(lines: list[str], chunk_chars: int) -> list[tuple[int, list[str]]]:
    """Нарезка по строкам: (номер первой строки, строки куска)."""
    out, cur, size, start = [], [], 0, 0
    for i, ln in enumerate(lines):
        if cur and size + len(ln) > chunk_chars:
            out.append((start, cur))
            cur, size, start = [], 0, i
        cur.append(ln)
        size += len(ln) + 1
    if cur:
        out.append((start, cur))
    return out


class PromptBuilder:
    def __init__(self, theme_role: str, prof: ModelProfile):
        self.role = theme_role
        self.p = prof

    def _system(self, task: str) -> str:
        return f"{self.role}\n\n{task}\n\n{DATA_NOT_INSTRUCTIONS}\n{self.p.json_hint}"

    def extract_tasks(self, first_line: int, lines: list[str], team: list[str]) -> tuple[str, str]:
        # Прежняя формулировка «поручение есть, только если исполнителя назвали» заставляла модель
        # молча отбрасывать решённые действия без исполнителя — у протоколов секретаря ERP это
        # большинство (прогон 03.10.26: 06.03 — 1 задача против 13). Правило владельца: без
        # исполнителя — карточка, решает человек. Поэтому такие действия возвращаются с assignee null.
        # Правила подсказки поручений (находка стенда 45, старая версия c74e5f7, 92a3e40; стенд Планёрки)
        task = ("ЗАДАЧА: найди поручения в куске записи встречи — действия, которые на встрече решили "
                "сделать. Если исполнителя назвали или человек твёрдо взял работу на себя («я сделаю», «беру на "
                "себя») — укажи его: это поручение. Если действие решено, а исполнитель не назван — всё равно "
                "верни его с assignee null: его разберёт человек. Ведущий планёрки и директор — такие же "
                "исполнители, как все: поручение дано им или взято ими на себя — укажи их (решение владелицы "
                "19.10.2026: ведущий может быть исполнителем). Если человек принял предложение («да, давайте так», "
                "«хорошо, займусь») — это поручение, не отбрасывай его. Повелительное «попробуйте сделать» — "
                "поручение. "
                "Вопрос, отрицание и неуверенное намерение («попробую, может успею», «посмотрим») — не "
                "поручение. Для каждого верни номер строки-основания.\n"
                'Схема: {"tasks":[{"description":str,"assignee":str|null,"line":int,"due_date":str|null}]}')
        team_txt = "Команда (для написания имён, НЕ источник фактов): " + "; ".join(team[:120])
        body, _ = fence(numbered(lines, first_line), "кусок записи встречи, строки пронумерованы")
        return self._system(task), f"{team_txt}\n\n{body}{self.p.no_think_suffix}"

    def closing_check(self, candidates: list[dict]) -> tuple[str, str]:
        task = ("ЗАДАЧА: для каждой задачи реестра выбери номер фразы, в которой на встрече "
                "СООБЩИЛИ о выполнении или о снятии задачи (отменили, больше не нужна). Если такой "
                "фразы нет — не включай задачу. Вопрос, план, отрицание, частичный результат, «отменять "
                "не будем» — ни выполнение, ни снятие.\n"
                'Схема: {"closed":[{"task_ref":int,"phrase":int}]}')
        safe = json.dumps({"candidates": candidates}, ensure_ascii=False)
        body, _ = fence(safe, "фразы встречи-кандидаты")
        return self._system(task), body + self.p.no_think_suffix

    def protocol(self, sections: list[str], source_text: str, notes_text: str = "",
                 participants: list[str] | None = None, leader: str = "") -> tuple[str, str]:
        task = ("ЗАДАЧА: кратко изложи обсуждение по разделам протокола. Только то, что есть в "
                "тексте встречи; задачи и таблицы не пиши — их вставит система. Без оценок и "
                "домыслов, деловым языком.\nРАЗДЕЛЫ:\n" + "\n".join(f"- {s}" for s in sections) +
                '\n\nСхема: {"sections":{"<раздел>":str}}')
        # Участники — по голосам и «Команде», а не по догадке модели (задание владелицы 26.10.2026):
        # имена уже опознаны правилом 0,65/0,10 и сверены с подтверждённой «Командой».
        if participants:
            task += ("\n\nУчастники по голосам (ФИО из «Команды»; в разделе «Участники» используй только эти "
                     "имена, других не придумывай): " + "; ".join(participants[:60]))
        if leader:
            task += f"\nВедущий встречи: {leader}."
        body, _ = fence(source_text, "текст встречи")
        if notes_text:
            nb, _ = fence(notes_text, "заметки — акцент: что точно обязательно, но не предел")
            body = f"{body}\n\n{nb}"
        return self._system(task), body + self.p.no_think_suffix

    def verify(self, protocol_md: str, source_text: str) -> tuple[str, str]:
        task = ("ЗАДАЧА: независимо проверь протокол по тексту встречи. Ищи утверждения без опоры, "
                "перепутанных людей, «решено» поданное как «сделано». Цитируй дословно.\n"
                'Схема: {"clean":bool,"findings":[{"issue":str,"quote":str,"severity":"minor|major"}]}')
        src, _ = fence(source_text, "текст встречи — источник фактов")
        doc, _ = fence(protocol_md, "проверяемый протокол")
        return self._system(task), f"{src}\n\n{doc}{self.p.no_think_suffix}"
