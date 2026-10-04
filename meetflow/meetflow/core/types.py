"""Сущности ядра.

Взяты из общей части Проекта ERP и Планёрки: встреча, источник, человек,
задача, карточка оператору, единица встречи. Предметных полей (отдел ОСН,
стадия 1С) здесь нет — они живут в конфигурации темы.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    TRANSCRIPT = "transcript"   # расшифровка: строки-реплики с таймкодами
    NOTES = "notes"             # заметки / протокол секретаря
    RECORDING = "recording"     # аудио или видео, идёт в ASR
    IMAGE = "image"             # снимок доски, скан — идёт в Vision
    OTHER = "other"             # материал к встрече, не источник фактов


class TaskStatus(str, Enum):
    ACTIVE = "active"
    DONE = "done"
    DROPPED = "dropped"         # снято / неактуально — не то же, что выполнено


class CardStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CUSTOM = "custom"


class UnitKind(str, Enum):
    """Единицы встречи (Проект ERP, 02.10.26). Риск отложен владельцем."""
    TASK = "task"
    DECISION = "decision"
    AGREEMENT = "agreement"
    CLARIFICATION = "clarification"
    OPEN_QUESTION = "open_question"
    MILESTONE = "milestone"


def digest(data: bytes | str) -> str:
    """Отпечаток содержимого: дубль узнаётся и после переименования файла."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass
class SourceDoc:
    """Прочитанный источник. lines — нумерованные строки: модель отвечает
    номером строки, а цитату берёт код (защита от выдуманных цитат)."""
    name: str
    kind: SourceKind
    text: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.text.splitlines()]

    @property
    def content_digest(self) -> str:
        """Отпечаток не зависит от концов строк и хвостовых пробелов: тот же
        текст, сохранённый в Windows (CRLF), иначе заводился вторым источником."""
        norm = "\n".join(ln.rstrip() for ln in self.text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
        return digest(norm.strip())


@dataclass
class Person:
    full_name: str
    role: str = ""
    department: str = ""
    aliases: list[str] = field(default_factory=list)
    external: bool = False
    confirmed: bool = True
    id: int | None = None
    organization: str = ""          # у внешних обязательна: «Иван — инженер ТМК» (03.10.26)
    known_marks: list[str] = field(default_factory=list)   # признаки, принятые ответом «это он»

    @property
    def label(self) -> str:
        """Как человек пишется ответственным: у внешнего — с организацией,
        иначе «Иван» из ТМК и «Иван» из Газпрома в реестре неразличимы."""
        return f"{self.full_name} ({self.organization})" if self.external and self.organization else self.full_name


@dataclass
class TaskDraft:
    """Кандидат в задачу до проверок кодом."""
    description: str
    assignee: str | None
    quote: str = ""
    line_no: int | None = None
    due_date: str | None = None
    source_name: str = ""


@dataclass
class GateResult:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    assignee: Person | None = None
    quote: str = ""
    description: str | None = None   # очищенная и обрезанная формулировка
    pending: dict | None = None      # задача заводится, исполнителя выбирает человек: reason, candidates, marks


@dataclass
class Card:
    """Карточка оператору: всё, что код не решил сам. Не блокирует документ."""
    kind: str
    title: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: CardStatus = CardStatus.OPEN
    id: int | None = None


@dataclass
class Finding:
    """Замечание проверки. source='code' нельзя принять, 'model' — справка."""
    issue: str
    source: str = "code"
    severity: str = "minor"
    quote: str = ""


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)
