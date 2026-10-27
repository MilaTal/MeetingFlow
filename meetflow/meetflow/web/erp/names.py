"""Проверка ФИО для регистрации члена команды (решение 20.09.26, файл «Проверка на совпадение по ФИО.docx»).

Обязательный минимум — Фамилия и Имя (отчество по желанию). Только имя, имя с отчеством без фамилии и «Фамилия И.»
(инициалы вместо имени) для регистрации НЕ подходят: такие записи не отличить друг от друга (совпадают имена,
отчества, фамилии).

Исключение (решение владельца 05.10.26): одна фамилия допустима, если заполнена РОЛЬ НА ПРОЕКТЕ. Так приходит из
записей встреч — «Петрукевич» без имени, — и человек в карточке либо дозаводит имя, либо указывает роль: роль на
проекте и отличает его от однофамильца. Без роли односложная запись не принимается. Проверка роли живёт в
`problem()`: сам `check_full_name` роли не знает и остаётся проверкой одного текста.

Модуль чистый — без БД, чтобы одну и ту же проверку использовали форма, API и разбор Протокола.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATRONYMIC = re.compile(r"(?:ович|евич|ьич|ич|овна|евна|ична|инична)$", re.I)
_PATRONYMIC_TURKIC = re.compile(r"(?:оглы|кызы)$", re.I)    # редкие суффиксы, с фамилиями почти не пересекаются
# Применено 22.09.26 из Planerka (реестр «Ошибка правила по ФИО от 20.09.2026»): окончание одно проверять
# недостаточно — фамилия на «-евич» («Петрукевич», «Абрамович») раньше ошибочно принималась за отчество без
# фамилии. Отчество признаётся отчеством, только если окончание стоит СРАЗУ ПОСЛЕ корня известного имени
# («Сергеевич» = «серге»+«евич» — да; «Петрукевич» — корня «седюк» в списке нет — нет).
_PATRONYMIC_ROOTS = (
    "александр", "алексе", "анатол", "андре", "антон", "аркад", "артем", "артур", "борис", "вадим", "валент",
    "валер", "васил", "виктор", "витал", "владимир", "владислав", "вячеслав", "геннад", "георг", "григор",
    "денис", "дмитри", "евген", "егор", "иван", "игор", "иль", "кирилл", "константин", "леонид", "льв", "макс",
    "михайл", "михал", "никит", "никола", "олег", "павл", "петр", "роман", "руслан", "семен", "серге",
    "станислав", "степан", "тимур", "тимофе", "федор", "эдуард", "юр", "яковл", "ярослав", "кузьм", "лук", "фом",
)
_WORD = re.compile(r"^[А-ЯЁA-Z][а-яёА-ЯЁa-zA-Z'’-]*[а-яёa-z]$")      # «О'Брайен», «Салтыков-Щедрин»; не «ИВАНОВ» и не «иванов»
_INITIALS = re.compile(r"^(?:[А-ЯЁA-Z]\.){1,2}$|^[А-ЯЁA-Z]\.[А-ЯЁA-Z]?\.?$")
_DEPARTMENT_WORDS = re.compile(r"\b(?:отдел|служба|группа|управление|департамент|команда|дирекция|бухгалтерия|производство|закупки|склад|оТО|ОТО|ИТ|IT)\b", re.I)

_ABBREVIATION = re.compile(r"^[А-ЯЁA-Z]{2,7}$")     # «ОТЛ», «ОЗ», «ОПС» — названия отделов, не люди

HINT_FORMAT = "Укажите Фамилию и Имя, например: «Иванова Мария» (отчество можно добавить третьим словом)."


@dataclass
class NameCheck:
    ok: bool
    kind: str          # full | empty | surname_or_name_only | name_patronymic | initials | invalid | department
    hint: str | None   # понятная подсказка человеку, если ok=False
    surname: str | None = None
    first_name: str | None = None
    patronymic: str | None = None


def _norm(s: str) -> str:
    # ъ = ь: «Талъянова» при «Иванова» — опечатка, не другой человек (хаос-тест 02.10.26: дубль не ловился)
    return (s or "").lower().replace("ё", "е").replace("ъ", "ь")


def is_patronymic(word: str) -> bool:
    w = word or ""
    if _PATRONYMIC_TURKIC.search(w):
        return True
    low = _norm(w)
    m = _PATRONYMIC.search(low)
    if not m or len(low) <= 5:
        return False
    stem = low[:m.start()]
    return any(stem == root or (len(stem) >= 3 and (root.startswith(stem) or stem.startswith(root)))
               for root in _PATRONYMIC_ROOTS)


def check_full_name(text: str | None) -> NameCheck:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return NameCheck(False, "empty", "Введите ФИО. " + HINT_FORMAT)
    if re.search(r"[\d_@#%*=+<>/\\|\[\]{}()!?;:\"«»]", text):
        return NameCheck(False, "invalid", "В имени не должно быть цифр и служебных знаков — только буквы. " + HINT_FORMAT)
    if _DEPARTMENT_WORDS.search(text):
        return NameCheck(False, "department", "Похоже, это название отдела или группы, а не человека. Команда проекта — это люди. "
                                              + HINT_FORMAT)
    if _MIXED_SCRIPT.search(text):
        return NameCheck(False, "invalid", "В слове смешаны латинские и русские буквы — проверьте написание. " + HINT_FORMAT)
    tokens = text.split(" ")
    if len(tokens) == 1:
        return NameCheck(False, "surname_or_name_only",
                         "Одного слова недостаточно: по одной фамилии или одному имени человека не отличить от однофамильцев и тёзок. "
                         + HINT_FORMAT)
    if any(_INITIALS.match(t) for t in tokens[1:2]) or (len(tokens) >= 2 and _INITIALS.match(tokens[1])):
        return NameCheck(False, "initials", "Вместо имени указаны инициалы — напишите имя полностью. " + HINT_FORMAT)
    if not all(_WORD.match(t) for t in tokens):
        return NameCheck(False, "invalid", "Каждое слово должно начинаться с заглавной буквы и состоять только из букв. " + HINT_FORMAT)
    if len(tokens) > 3:
        return NameCheck(False, "invalid", "Слишком много слов. " + HINT_FORMAT)
    if is_patronymic(tokens[1]) and not is_patronymic(tokens[0]):
        return NameCheck(False, "name_patronymic",
                         "Похоже, указаны имя и отчество без фамилии (или другой порядок слов). Порядок: Фамилия Имя [Отчество]. "
                         + HINT_FORMAT)
    if is_patronymic(tokens[0]):
        return NameCheck(False, "name_patronymic", "Первым словом должна быть фамилия, а не отчество. " + HINT_FORMAT)
    return NameCheck(True, "full", None, tokens[0], tokens[1], tokens[2] if len(tokens) == 3 else None)


_CASE_END = re.compile(r"(?:ой|ей|ою|ею|[аяуюыиеоь])$")
_MIXED_SCRIPT = re.compile(r"(?=\w*[A-Za-z])(?=\w*[А-Яа-яЁё])\w+")


def _first_key(name: str) -> str:
    """Имя без падежного окончания: «Мария/Марию/Марии» — одно и то же, «Марина» — другое."""
    n = _norm(name)
    stem = _CASE_END.sub("", n)
    return stem if len(stem) >= 2 else n


def person_key(full_name: str | None) -> tuple[str, str] | None:
    """Ключ для поиска совпадений: (первые пять букв фамилии, имя) без регистра и без ё — окончания фамилий меняются
    («Петрукевичу» и «Петрукевич»)."""
    c = check_full_name(full_name)
    if not c.ok:
        return None
    return _norm(c.surname)[:5], _first_key(c.first_name)


def looks_like_bare_person_name(text: str | None) -> bool:
    """Одно слово с заглавной буквы («Юля», «Иванов») — так человек выглядит в Протоколе, когда назван не полностью.
    Названия отделов и служебные пометки («не назначен», «Отдел ОТО») сюда не относятся."""
    t = (text or "").strip()
    if not t or " " in t or _DEPARTMENT_WORDS.search(t) or _ABBREVIATION.match(t):
        return False
    return bool(_WORD.match(t)) and _norm(t) not in {"нет", "неизвестно", "все", "всех", "команда"}


_BAD_CHARS = re.compile(r"[\d_@#%*=+<>/\\|\[\]{}()!?;:\"«»]")
EXTERNAL_ROLE_HINT = ("У внешнего контакта неполное имя — так бывает, но тогда заполните «Роль на проекте», "
                      "чтобы его можно было отличить от других.")


EXTERNAL_ORG_HINT = ("У внешнего контакта укажите организацию и роль на проекте: по ним его отличают от тёзок из других "
                     "организаций («Иван» из ТМК и «Иван» из Газпрома — разные люди).")


def problem(full_name: str | None, project_role: str | None = None, is_external: bool = False,
            organization: str | None = None, name_short_reason: str | None = None) -> str | None:
    """ЕДИНОЕ правило записи в «Команде» (Доработки 2, 20.09.26). None — запись можно подтверждать; иначе готовая фраза для
    человека. Сотрудник — Фамилия и Имя полностью. Внешний контакт — любое непустое имя, но обязательны организация и роль на
    проекте (правило «один человек или два», владелец 03.10.26; раньше роль требовалась только при неполном имени).
    Фронтенд повторяет правило только ради подсказки до отправки."""
    text = re.sub(r"\s+", " ", (full_name or "").strip())
    role = (project_role or "").strip()
    if is_external:
        if not text:
            return "Укажите хотя бы фамилию или имя контакта."
        if _BAD_CHARS.search(text):
            return "В имени не должно быть цифр и служебных знаков — только буквы."
        if not re.search(r"[A-Za-zА-Яа-яЁё]{2}", text):
            return "Укажите фамилию или имя контакта буквами."
        if _MIXED_SCRIPT.search(text):
            return "В слове смешаны латинские и русские буквы — проверьте написание."
        if not role or not (organization or "").strip():
            return EXTERNAL_ORG_HINT
        # Одно слово без инициала — только с явным «да, известно только одно слово» и причиной (решение владелицы
        # 24.10.2026, п. 7: «поставить проверку, чтобы больше не заводились такие»); правило — общий модуль-близнец.
        from . import vneshnie_kontakty
        return vneshnie_kontakty.причина_экрана(text, name_short_reason)
    if not text:
        return "Укажите фамилию и имя сотрудника (либо фамилию и роль на проекте)."
    c = check_full_name(text)
    if c.ok:
        return None
    if c.kind == "surname_or_name_only":
        # Решение владельца 05.10.26: одна фамилия допустима, если заполнена роль на проекте. Так
        # приходит из записей встреч («Петрукевич» без имени), и человек в карточке либо дозаводит имя,
        # либо указывает роль — второе и отличает его от однофамильца. Без роли запись не принимаем:
        # односложное имя не отличить от другого такого же.
        if role:
            return None
        # Фраза не выбирает между «нет фамилии» и «нет имени»: сервер видит одно слово и не знает, фамилия
        # это или имя (догадка по корню ошибалась бы на «Швец», «Громыш», «Лукин»), а ошибочная подсказка
        # «добавьте фамилию» поверх заполненной фамилии — ровно та жалоба, из которой выросло правило.
        # Форма поля различает и говорит точнее; здесь называем оба условия.
        return (f"Указано одно слово — «{text}». Нужны два условия: фамилия и имя либо фамилия и роль на проекте. "
                "По одной фамилии человека не отличить от однофамильца, а роль на проекте отличает.")
    if c.kind == "initials":
        initial = text.split(" ")[1] if len(text.split(" ")) > 1 else "А."
        return f"Вместо инициала «{initial}» укажите имя полностью: по инициалу человека не отличить от однофамильца."
    if c.kind == "name_patronymic":
        return "Добавьте фамилию: одно имя (и имя с отчеством) может совпасть у нескольких сотрудников."
    return c.hint
