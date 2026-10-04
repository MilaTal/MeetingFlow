"""Приём источника: проверка ДО вызова модели и ДО создания встречи (правило Планёрки 01.10.26 —
отклонённый файл не должен оставлять пустую встречу).

Сбой входа — отказ шага, повтором не лечится (урок 3): у каждого отказа машинный признак и текст для человека.
"""

import hashlib
import re
from datetime import date

from .errors import SourceRejected
from .text import clean, content_stems, words

MAX_SOURCE_CHARS = 400_000   # потолок Планёрки на длину запроса; длиннее — это не одна встреча
MIN_MEANINGFUL = 20          # меньше 20 значащих знаков — пустой источник (ERP, 19.09.26)

_INJECTION = [
    r"игнорир\w*\s+(?:все\s+|всё\s+)?(?:предыдущ|прежн|выше|инструкц|правил)",
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
    r"забудь\s+(?:все|всё|инструкц|правил)",
    r"ты\s+теперь\s+(?:\w+\s+)?(?:ассистент\w*|бот\w*|модел\w*|систем\w*|администратор\w*|админ\w*|ии\b)",
    r"\bsystem\s*:|\bсистемн\w+\s+(?:промпт|инструкц)",
    r"(?:закрой|закрыть|удали|удалить|сними|снять)\s+(?:все|всё)\s+задач",
    r"(?:выведи|покажи|раскрой)\s+(?:свой\s+)?(?:промпт|инструкц)",
    r"<\s*/?\s*(?:system|assistant|tool)\s*>",
    r"режим\s+разработчика|developer\s+mode|jailbreak",
]
_INJ = re.compile("|".join(_INJECTION), re.IGNORECASE)
_INJ_CASE = re.compile(r"\bDAN\b")   # регистр важен: «Dan» — имя, «DAN» — известный приём обхода

_MEETING_MARKERS = re.compile(
    r"\b(задач\w*|срок\w*|поруч\w*|подготов\w*|отправ\w*|согласов\w*|сделал\w*|сделает|проект\w*|встреч\w*|"
    r"планерк\w*|планёрк\w*|договор\w*|отчет\w*|отчёт\w*|коллеги|давайте|по\s+проекту)\b",
    re.IGNORECASE,
)
_TIMECODE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_DATE_IN_NAME = [
    (re.compile(r"(20\d{2})[._-](\d{2})[._-](\d{2})"), ("y", "m", "d")),
    (re.compile(r"(\d{2})[._-](\d{2})[._-](20\d{2})"), ("d", "m", "y")),
    (re.compile(r"(\d{2})[._-](\d{2})[._-](\d{2})(?!\d)"), ("d", "m", "yy")),
]


def decode(data: bytes) -> str:
    """UTF-8, UTF-16 только с BOM, иначе cp1251. Бинарный мусор — отказ, а не «что-то пошло не так» позже."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    if data.count(b"\x00") > len(data) // 50:
        raise SourceRejected("Файл не текстовый: в нём двоичные данные.", "binary")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="strict")


def read_file(path: str) -> str:
    p = str(path).lower()
    if p.endswith(".docx"):
        try:
            import docx  # python-docx
        except ImportError:
            raise SourceRejected("Для .docx нужен пакет python-docx; приложите текстовую версию.", "no_docx_reader")
        try:
            d = docx.Document(path)
        except Exception:
            raise SourceRejected("Файл .docx повреждён или не открывается.", "bad_docx")
        parts = [para.text for para in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                # ячейки разделяем явно: склейка «пылемерПроработать» (Планёрка 02.10.26) рождалась здесь
                parts.append(" | ".join(" ".join(x.text for x in cell.paragraphs) for cell in row.cells))
        return "\n".join(parts)
    with open(path, "rb") as f:
        data = f.read()
    try:
        return decode(data)
    except UnicodeDecodeError:
        raise SourceRejected("Кодировка файла не распознана.", "encoding")


def date_from_name(name: str):
    """Дата встречи из имени файла. Найденный кусок вымарывается, чтобы второй шаблон не прочёл «09_05» как 9 мая."""
    s = name
    found = []
    for rx, order in _DATE_IN_NAME:
        for m in rx.finditer(s):
            vals = dict(zip(order, m.groups()))
            y = int(vals["y"]) if "y" in vals else 2000 + int(vals["yy"])
            try:
                found.append(date(y, int(vals["m"]), int(vals["d"])))
            except ValueError:
                continue
        s = rx.sub("#", s)
    found = sorted(set(found))
    return found[0].isoformat() if len(found) == 1 else None


def digest(text: str) -> str:
    return hashlib.sha256(" ".join(words(text)).encode("utf-8")).hexdigest()


def check(text: str, source_name: str = "") -> dict:
    """Возвращает {text, kind, injection_lines}. Отказ — SourceRejected с кодом."""
    text = clean(text)
    if len(text) > MAX_SOURCE_CHARS:
        raise SourceRejected(
            f"Источник длиннее {MAX_SOURCE_CHARS:,} знаков — это не одна встреча; разделите файл.".replace(",", " "),
            "too_large")
    meaningful = re.sub(r"[\W_]+", "", text)
    if len(meaningful) < MIN_MEANINGFUL:
        raise SourceRejected("Источник пустой: в нём нет текста встречи.", "empty")
    if len(content_stems(text)) < 5:
        raise SourceRejected("В источнике нет связного текста — похоже на мусор или служебный файл.", "garbage")
    lines = [l for l in text.split("\n") if l.strip()]
    markers = (len(_MEETING_MARKERS.findall(text))
               + len(re.findall(r"\b[а-яё]+(?:ите|йте|ьте)\b", text, re.IGNORECASE))      # «запросите», «проверьте»
               + sum(1 for l in lines if re.match(r"^\s*[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?\s*:", l)))  # реплики «Имя: …»
    if markers == 0 and len(text) < 3000:
        raise SourceRejected("Текст не похож на запись совещания: нет ни задач, ни сроков, ни обращений к участникам.",
                             "not_meeting")
    timecodes = len(_TIMECODE.findall(text))
    kind = "transcript" if timecodes >= 3 or sum(1 for l in lines if re.match(r"^\s*[А-ЯЁ][\w ]{1,30}:", l)) >= 0.4 * len(lines) else "notes"
    return {"text": text, "kind": kind, "suspicious": sum(1 for l in lines if is_injection(l)), "markers": markers}


def is_injection(line: str) -> bool:
    """Реплика, обращённая к системе, а не к людям. Такие строки не идут в модель и уходят оператору карточкой."""
    return bool(_INJ.search(line or "") or _INJ_CASE.search(line or ""))
