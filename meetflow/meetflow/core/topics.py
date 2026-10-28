# -*- coding: utf-8 -*-
"""Тема планёрки — перенос из Проекта ERP (`webapp/app/services/tema_planerki.py`, монорепозиторий b0d8ab7), 27.10.2026.

Решения владелицы 24.10.2026 (Р1–Р6, как ERP): тема — самостоятельная сущность (`meeting_topics`) со своими днями недели,
структурой протокола (набор и порядок разделов), блоком подсказки, источником переходящих задач и сводки (прошлая встреча
той же темы), списком объектов и их порядком. Выбор человека («вручную», в том числе «без темы») сильнее эталона секретаря
и дня недели; эталон уточняет тему молча; день недели — только подсказка, протокол секретаря её перекрывает (26.10.2026).
Нет темы — сборка идёт как до 24.10.2026: общий скелет, общая подсказка, предыдущая встреча по дате.

Чистые функции (шапка секретаря, сопоставление по шапке, подсказка, шапка протокола) — как у ERP до смысла. Отличие от ERP
одно, и оно в базе: ERP пишет тему дня недели во встречу при её заведении (`поставить_по_дню`), MeetFlow считает её при
чтении (`тема_встречи`). Ответ тот же: тема, назначенная на день недели, у всех встреч дня, пока её не перекрыли вручную или
эталоном.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

ИСТОЧНИК_ДЕНЬ = "по дню недели"
ИСТОЧНИК_ЭТАЛОН = "из эталона"
ИСТОЧНИК_РУЧНОЙ = "вручную"
ИСТОЧНИКИ = (ИСТОЧНИК_ДЕНЬ, ИСТОЧНИК_ЭТАЛОН, ИСТОЧНИК_РУЧНОЙ)
ВРУЧНУЮ, ПО_ДНЮ = ИСТОЧНИК_РУЧНОЙ, ИСТОЧНИК_ДЕНЬ       # прежние имена (sistema.py)
# Тема по умолчанию (задание 26.10.2026): шапка протокола секретаря без темы — эта тема, а не тема дня недели
ТЕМА_ПО_УМОЛЧАНИЮ = "Общие вопросы"
РАЗДЕЛ_ЗАДАЧ = "Задачи"          # таблицу задач собирает программа, модель её не пишет


# --- Чистые функции (как ERP) ---------------------------------------------------------------------------------------
def _норм(текст: str | None) -> str:
    s = (текст or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'*_.,:;!?()\[\]]+", " ", s)
    s = s.replace("+", " ").replace("–", " ").replace("—", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def _список(значение) -> list:
    if isinstance(значение, (list, tuple)):
        return list(значение)
    try:
        v = json.loads(значение or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def _поле(тема, имя: str):
    v = тема.get(имя) if isinstance(тема, dict) else getattr(тема, имя, None)
    if имя in ("sections", "head_names", "objects", "weekdays"):
        return _список(v)
    if имя in ("is_active", "carry_same_topic") and v is not None:
        return bool(v)
    return v


_ШАПКА_СЕКРЕТАРЯ_RE = re.compile(
    r"^\s*(?:#+\s*)?\**\s*План[её]рка\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s*[.,]?(?:\s+(.*?))?\s*\**\s*$", re.IGNORECASE)
_ШАПКА_ПРОТОКОЛА_RE = re.compile(
    r"^\s*(?:#+\s*)?\**\s*Протокол\s+(?:план[её]рки|встречи|совещания)\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s*г?\.?\s*[.,]?"
    r"(?:\s+(.*?))?\s*\**\s*$", re.IGNORECASE)


def _хвост(текст: str | None, шаблон) -> str | None:
    видимых = 0
    for строка in (текст or "").splitlines():
        s = строка.strip()
        if not s:
            continue
        видимых += 1
        m = шаблон.match(s)
        if m:
            return (m.group(2) or "").strip().strip("*").strip().rstrip(".").strip()
        if видимых >= 5:
            break
    return None


def шапка_секретаря(текст: str | None) -> str | None:
    """Тема из шапки «Планерка ДД.ММ.ГГГГ. Тема.»: хвост после даты; шапка без темы — «»; шапки среди первых пяти строк нет —
    None. Наша выгрузка («Протокол планёрки …») шапкой секретаря здесь не считается."""
    return _хвост(текст, _ШАПКА_СЕКРЕТАРЯ_RE)


def шапка_эталона(текст: str | None) -> str | None:
    """Тема из шапки протокола секретаря (источник «заметки / протокол секретаря»): «Планерка ДД.ММ.ГГГГ. Тема.» или
    «Протокол планёрки ДД.ММ.ГГГГ[. Тема.]» (задание 26.10.2026)."""
    хвост = шапка_секретаря(текст)
    return хвост if хвост is not None else _хвост(текст, _ШАПКА_ПРОТОКОЛА_RE)


def тема_по_умолчанию(темы) -> dict | None:
    for тема in темы or []:
        if _поле(тема, "is_active") is not False and _норм(_поле(тема, "name")) == _норм(ТЕМА_ПО_УМОЛЧАНИЮ):
            return тема
    return None


def _имена_темы(тема) -> list[str]:
    return [x for x in [_поле(тема, "name")] + list(_поле(тема, "head_names") or []) if (x or "").strip()]


def тема_по_шапке(хвост: str | None, темы) -> dict | None:
    """Точное совпадение с названием темы или её «названием в шапке секретаря», потом вхождение; при нескольких — по самому
    длинному совпавшему имени. Выключенные темы не участвуют."""
    n = _норм(хвост)
    if not n:
        return None
    лучшая, вес = None, 0
    for тема in темы or []:
        if _поле(тема, "is_active") is False:
            continue
        for имя in _имена_темы(тема):
            ни = _норм(имя)
            if not ни:
                continue
            if ни == n:
                в = 1000 + len(ни)
            elif re.search(r"(?:^| )" + re.escape(ни) + r"(?: |$)", n):
                в = len(ни)
            else:
                continue
            if в > вес:
                лучшая, вес = тема, в
    return лучшая


def дни(тема) -> list[int]:
    out = []
    for ч in _поле(тема, "weekdays"):
        try:
            d = int(ч)
        except (TypeError, ValueError):
            continue
        if 1 <= d <= 7 and d not in out:
            out.append(d)
    return sorted(out)


def разделы(тема) -> list[str]:
    return [s for s in (_поле(тема, "sections") or []) if (s or "").strip()] if тема is not None else []


def подсказка_протокола(тема) -> str:
    """Блок системной подсказки черновика протокола для темы (как ERP): разделы темы вместо общего скелета, порядок
    объектов, «что важно для этой темы». Темы нет или у неё нет ни разделов, ни подсказки — пусто."""
    if тема is None:
        return ""
    название = _поле(тема, "name") or ""
    р = разделы(тема)
    объекты = [o for o in (_поле(тема, "objects") or []) if (o or "").strip()]
    важно = (_поле(тема, "hint") or "").strip()
    if not р and not важно:
        return ""
    части = [f"\n\n---\n\n# Тема планёрки «{название}» (решение владелицы 24.10.2026)\n",
             f"Тема этой встречи — «{название}». Шапку протокола с темой ставит программа: «Протокол планёрки [ДД.ММ.ГГГГ]. "
             f"{название}.» — тему в шапке не угадывай и не меняй."]
    if р:
        список = "\n".join(f"{i}. {s}" for i, s in enumerate(р, 1))
        части.append("Структура протокола для этой темы ЗАМЕНЯЕТ блоки общего скелета выше: разделы — только эти и строго "
                     "в этом порядке, название раздела — заголовком 2 уровня. Блоки общего скелета, которых здесь нет, не "
                     "выводи; раздел, по которому на встрече ничего не прозвучало, не выводи (заглушек вида «новой "
                     "информации нет» не пиши)." + (f" Раздел «{РАЗДЕЛ_ЗАДАЧ}» собирает программа — сам его не пиши."
                                                     if РАЗДЕЛ_ЗАДАЧ in р else "") + "\n" + список)
    if объекты:
        части.append("Порядок объектов (абзац на объект, объект, который не прозвучал, не упоминается; прозвучавший объект "
                     "не из списка — после списка): " + "; ".join(объекты) + ".")
    if важно:
        части.append("Что важно для этой темы: " + важно)
    return "\n\n".join(части) + "\n"


_ДАТА_В_ШАПКЕ_RE = re.compile(r"^(#\s+.*?\d{1,2}\.\d{1,2}\.\d{2,4})\.?(.*)$")


def поставить_в_шапку(md: str, название: str | None) -> str:
    """Тема в шапку протокола кодом: «# Протокол 01.10.2026. Стройка.». Шапки с датой нет или темы нет — текст как есть."""
    if not (название or "").strip() or not md:
        return md
    строки = md.split("\n")
    for i, строка in enumerate(строки):
        if not строка.strip():
            continue
        m = _ДАТА_В_ШАПКЕ_RE.match(строка.strip())
        if m and строка.lstrip().startswith("# "):
            строки[i] = f"{m.group(1)}. {название.strip().rstrip('.')}."
        break
    return "\n".join(строки)


def сначала_та_же_тема(тема_id: int | None, по_теме: bool, кандидаты: list, ключ) -> list:
    """Источник переходящих задач и сводки (Р4): у темы «с прошлой встречи той же темы» встречи этой темы — первыми."""
    if not тема_id or not по_теме:
        return list(кандидаты)
    свои = [m for m in кандидаты if ключ(m) == тема_id]
    return свои + [m for m in кандидаты if ключ(m) != тема_id]


# --- База MeetFlow ---------------------------------------------------------------------------------------------------
def _d(value) -> date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def активные(store) -> list[dict]:
    return store.q("SELECT * FROM meeting_topics WHERE COALESCE(is_active,1)=1 ORDER BY id")


def по_дню(store, day: date | None) -> dict | None:
    if day is None:
        return None
    for t in активные(store):
        if day.isoweekday() in дни(t):
            return t
    return None


def тема_встречи(store, meeting: dict) -> dict | None:
    """Действующая тема встречи: выбранная человеком или поставленная эталоном, иначе — по дню недели; «без темы»
    (вручную или эталоном) — нет темы. Выключенная тема не действует."""
    if not meeting:
        return None
    tid = meeting.get("topic_id")
    if tid:
        rows = store.q("SELECT * FROM meeting_topics WHERE id=?", (tid,))
        return rows[0] if rows and (rows[0].get("is_active") is None or rows[0].get("is_active")) else None
    if (meeting.get("topic_source") or "") in (ИСТОЧНИК_РУЧНОЙ, ИСТОЧНИК_ЭТАЛОН):
        return None
    return по_дню(store, _d(meeting.get("date")))


def источник(store, meeting: dict) -> str:
    src = meeting.get("topic_source") or ""
    if src in (ИСТОЧНИК_РУЧНОЙ, ИСТОЧНИК_ЭТАЛОН):
        return src
    return ИСТОЧНИК_ДЕНЬ if тема_встречи(store, meeting) else ""


def _поставить(store, meeting: dict, тема: dict | None, src: str, кто: str) -> None:
    from .store import now
    store.update("meetings", meeting["id"], topic_id=тема["id"] if тема else None, topic=тема["name"] if тема else "",
                 topic_source=src, topic_set_at=now(), topic_set_by=(кто or "")[:200])
    meeting.update(topic_id=тема["id"] if тема else None, topic=тема["name"] if тема else "", topic_source=src)


def применить_эталон(store, meeting: dict, текст: str | None) -> dict:
    """Пришёл протокол секретаря — тема по его шапке молча, если тему не выбрал человек (Р3). Без вызова модели. Шапка без
    темы — тема по умолчанию «Общие вопросы»; её нет среди активных — встреча без темы (как ERP)."""
    хвост = шапка_эталона(текст)
    if хвост is None:
        return {"действие": "шапки секретаря нет"}
    src = meeting.get("topic_source") or ""
    все = активные(store)
    if not хвост:
        if src == ИСТОЧНИК_РУЧНОЙ:
            return {"действие": "тему выбрал человек — оставлена", "шапка": ""}
        тема = тема_по_умолчанию(все)
        тема_id = тема["id"] if тема else None
        if src == ИСТОЧНИК_ЭТАЛОН and meeting.get("topic_id") == тема_id:
            return {"действие": "тема уже из эталона", "шапка": "", "тема": тема["name"] if тема else None}
        if тема_id is None and not тема_встречи(store, meeting):
            return {"действие": "шапка без темы — встреча без темы", "шапка": ""}
        _поставить(store, meeting, тема, ИСТОЧНИК_ЭТАЛОН, "эталон секретаря")
        return {"действие": "шапка без темы — тема по умолчанию" if тема else "шапка без темы — тема снята", "шапка": "",
                "тема": тема["name"] if тема else None}
    тема = тема_по_шапке(хвост, все)
    if тема is None:
        return {"действие": "тема по шапке не распознана", "шапка": хвост}
    if src == ИСТОЧНИК_РУЧНОЙ:
        return {"действие": "тему выбрал человек — оставлена", "шапка": хвост, "тема": тема["name"]}
    if meeting.get("topic_id") == тема["id"] and src == ИСТОЧНИК_ЭТАЛОН:
        return {"действие": "тема уже из эталона", "шапка": хвост, "тема": тема["name"]}
    _поставить(store, meeting, тема, ИСТОЧНИК_ЭТАЛОН, "эталон секретаря")
    return {"действие": "поставлена из эталона", "шапка": хвост, "тема": тема["name"]}


def сверить_со_сборкой(store, meeting: dict, тексты_секретаря) -> dict:
    """При сборке: тема стоит по дню недели (или её нет), а у встречи есть протокол секретаря — тема по его шапке."""
    if (meeting.get("topic_source") or "") in (ИСТОЧНИК_РУЧНОЙ, ИСТОЧНИК_ЭТАЛОН):
        return {"действие": "тема уже не по дню"}
    for текст in тексты_секретаря or []:
        if шапка_эталона(текст) is not None:
            return применить_эталон(store, meeting, текст)
    return {"действие": "протокола секретаря нет"}


def _id_темы(store, кэш: dict):
    def ключ(m: dict):
        if m["id"] not in кэш:
            t = тема_встречи(store, m)
            кэш[m["id"]] = t["id"] if t else None
        return кэш[m["id"]]
    return ключ


def по_теме_сначала(store, meeting: dict, кандидаты: list[dict]) -> list[dict]:
    """Кандидаты в «предыдущую встречу» (прошлый протокол для плана, сводка): у темы «с прошлой встречи той же темы» —
    сначала встречи этой темы (Р4). Темы нет или признак снят — порядок как был."""
    тема = тема_встречи(store, meeting)
    return сначала_та_же_тема(тема["id"] if тема else None, bool(тема and тема.get("carry_same_topic")), кандидаты,
                              _id_темы(store, {}))


def встречи_той_же_темы(store, meeting: dict) -> set[int] | None:
    """Номера встреч той же темы — для переходящих задач темы «с прошлой встречи той же темы»; иначе None (как до 24.10)."""
    тема = тема_встречи(store, meeting)
    if тема is None or not тема.get("carry_same_topic"):
        return None
    ключ = _id_темы(store, {})
    return {m["id"] for m in store.q("SELECT * FROM meetings WHERE deleted_at IS NULL AND project_id=?", (meeting.get("project_id"),))
            if ключ(m) == тема["id"]}


def в_словарь(t: dict) -> dict:
    return {"id": t["id"], "name": t.get("name") or "", "weekdays": дни(t), "sections": _поле(t, "sections"),
            "head_names": _поле(t, "head_names"), "objects": _поле(t, "objects"), "hint": t.get("hint") or "",
            "carry_same_topic": bool(t.get("carry_same_topic")), "is_active": bool(t.get("is_active", 1))}
