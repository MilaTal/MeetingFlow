"""Эвристический клиент: тот же контракт JSON, но без модели.

Зачем он нужен, три причины. Первая — запасной путь внутри периметра: если локальная модель недоступна,
протокол собирается правилами и помечается «собран без модели» (видимая деградация, урок 3 курса).
Вторая — проверка конвейера без недетерминизма модели: тесты и eval гоняют код, а не настроение модели.
Третья — эталон «что ловится правилом»: всё, что ловит эвристика, модели отдавать незачем.
Это не замена модели по полноте: телеграфная речь планёрки правилами покрывается плохо — честно
записано в паспорте (Р4, Р6).
"""

import json
import re

from . import negation
from .llm import LLMClient, estimate_tokens
from .text import coverage, norm, stem

_LINE = re.compile(r"^\[(\d+)\]\s*(?:([^:\]]{2,40}):\s)?(.*)$")
_CAP = r"[А-ЯЁ][а-яё]+"
_NAME = rf"(?:{_CAP}(?:\s+{_CAP})?)"
_DEPT = r"(?:[Оо]тдел\s+[а-яё]+|[А-ЯЁ]{2,5})"
_IMPER = r"(?:[а-яё]+(?:ите|ьте|йте|и|ь|й))"
_FUT3 = (r"(?:подготовит|сделает|отправит|направит|пришлет|пришлёт|согласует|проверит|запросит|закажет|"
         r"оформит|подпишет|передаст|возьмет|возьмёт|организует|проведет|проведёт|напишет|выяснит|уточнит|"
         r"обновит|загрузит|настроит|составит|соберет|соберёт|посчитает|разошлет|разошлёт)")
_FUT1 = (r"(?:подготовлю|сделаю|отправлю|направлю|пришлю|согласую|проверю|запрошу|закажу|оформлю|подпишу|"
         r"передам|возьму|организую|проведу|напишу|выясню|уточню|обновлю|загружу|настрою|составлю|соберу|"
         r"посчитаю|разошлю)")
_DUE = re.compile(
    r"\b(?:до|к)\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|"
    r"субботы|конца\s+(?:недели|месяца|дня)|завтра\w*|следующей\s+планерк\w*|следующей\s+встреч\w*)",
    re.IGNORECASE,
)
_NOT_NAMES = {"Давайте", "Хорошо", "Ладно", "Так", "Итак", "Коллеги", "Значит", "Ну", "Да", "Нет", "Спасибо",
              "Отлично", "Понятно", "Вопрос", "Срок", "Задача", "Все", "Тогда", "Сейчас", "Пожалуйста", "Прошу"}


def _infinitive(phrase: str) -> str:
    """Первый глагол фразы — в начальную форму: «подготовьте отчёт» -> «подготовить отчёт»."""
    parts = phrase.strip().split(maxsplit=1)
    if not parts:
        return phrase
    head = parts[0]
    try:
        from .text import _MORPH
        if _MORPH is not None:
            p = _MORPH.parse(head.lower())[0]
            if {"VERB", "INFN"} & set(str(p.tag).replace(" ", ",").split(",")):
                head = p.normal_form
    except Exception:
        pass
    return (head + (" " + parts[1] if len(parts) > 1 else "")).strip(" .,!")


def _due(text: str):
    m = _DUE.search(text)
    return m.group(0) if m else None


def _parse_lines(user: str) -> list:
    out = []
    for raw in user.splitlines():
        m = _LINE.match(raw.strip())
        if m:
            sp = (m.group(2) or "").strip()
            body = m.group(3)
            # «Итого: …» и «Срок: …» — не говорящие; говорящий — имя из 1–3 слов с заглавной или «Говорящий N»
            if sp and not re.fullmatch(rf"(?:{_CAP}(?:\s+{_CAP}){{0,2}}|Говорящий\s*\d+|Спикер\s*\d+)", sp) or sp in _NOT_NAMES:
                body, sp = f"{sp}: {body}", ""
            out.append({"n": int(m.group(1)), "speaker": sp or None, "text": body})
    return out


def _json_after(marker: str, user: str):
    i = user.find(marker)
    if i < 0:
        return None
    s = user[i + len(marker):].strip()
    depth, end = 0, None
    for j, ch in enumerate(s):
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    return json.loads(s[:end]) if end else None


_CLAUSE_SPLIT = re.compile(r"\s*(?:;|,\s+а\s+|,\s+и\s+пусть\s+|\s+а\s+также\s+)\s*")
_FILLERS = {"пожалуйста", "давай", "давайте", "ты", "вы", "надо", "нужно", "срочно", "ну", "тоже", "еще", "ещё"}


def _compose(words_left: list, verb: str) -> str:
    """Действие из частей фразы: глагол вперёд в начальной форме, имя и слова-связки выброшены.
    «По фильтрам, Назаров, спецификацию подготовьте» -> «подготовить спецификацию по фильтрам»."""
    rest = [w for w in words_left if w.strip(",.").lower() not in _FILLERS and w.strip(",.")]
    return _infinitive(verb + " " + " ".join(w.strip(",") for w in rest)).strip(" ,.")


def _clause_assignment(t: str, speaker):
    """Одна часть фразы -> (кому, действие) или None. Общие обороты живой речи, а не шаблоны конкретных строк."""
    m = re.match(rf"^(?:Прошу|Поручаю|Поручить)\s+({_NAME})\s*,?\s+(.+)$", t)
    if m:
        return m.group(1), m.group(2)
    # обращение в начале: «Назаров, подготовьте…»
    m = re.match(rf"^({_NAME}|{_DEPT})\s*,\s*(?:пожалуйста\s*,?\s*)?({_IMPER}\b.+)$", t)
    if m and m.group(1).split()[0] not in _NOT_NAMES:
        return m.group(1), m.group(2)
    # «Ершова, с вас коммерческие предложения»
    m = re.match(rf"^({_NAME}|{_DEPT})\s*,\s*с\s+(?:вас|тебя)\s+(.+)$", t)
    if m and m.group(1).split()[0] not in _NOT_NAMES:
        return m.group(1), "предоставить " + m.group(2)
    # «Ершова пусть запросит цены», «Назаров подготовит…»
    m = re.match(rf"^({_NAME}|{_DEPT})\s+(?:пусть\s+)?({_FUT3}\b.+)$", t)
    if m and m.group(1).split()[0] not in _NOT_NAMES:
        return m.group(1), m.group(2)
    # обращение в середине: «По фильтрам, Назаров, спецификацию подготовьте до пятницы»
    m = re.match(rf"^(.*?),\s*({_NAME})\s*,\s*(.+)$", t)
    if m and m.group(2).split()[0] not in _NOT_NAMES:
        tail = m.group(3).split()
        verbs = [i for i, w in enumerate(tail) if re.fullmatch(_IMPER, w.strip(",.").lower())]
        if verbs:
            v = tail.pop(verbs[0])
            prefix = m.group(1).split()
            if prefix and not prefix[0].isupper():   # заглавная начала фразы, а не имя собственное
                prefix[0] = prefix[0].lower()
            return m.group(2), _compose(tail + prefix, v.strip(",."))
    # глагол впереди, имя в конце: «Подготовит отчёт по экономике Седова, срок среда»
    m = re.match(rf"^({_FUT3})\s+(.+?)\s+({_NAME})(?:\s*,\s*(.*))?$", t[:1].lower() + t[1:])
    if m and m.group(3).split()[0] not in _NOT_NAMES:
        return m.group(3), m.group(1) + " " + m.group(2) + (", " + m.group(4) if m.group(4) else "")
    if speaker:
        m = re.search(rf"\b(?:я|Я)\s+(?:сам[аи]?\s+)?({_FUT1}\b.+)$", t)
        if m:
            return speaker, m.group(1)
    return None


def extract(lines: list) -> list:
    found = []
    for l in lines:
        line_text = l["text"].strip()
        # одно поручение — одна задача: «Назаров, подготовьте…, а Ершова пусть запросит…» — две части
        # (правило Проекта ERP 01.10.26, повод — задача №130, склейка трёх поручений)
        for t in _CLAUSE_SPLIT.split(line_text):
            t = t.strip(" ,.")
            if not t or not negation.is_assignment_shape(t)["ok"]:
                continue
            hit = _clause_assignment(t, l.get("speaker"))
            if not hit:
                continue
            to, action = hit
            due = _due(action) or _due_word(action)
            if due:
                action = action.replace(due, "").strip(" ,.")
            action = re.sub(r"\s+", " ", action)
            found.append({"line": l["n"], "to": to.strip(), "action": _infinitive(action), "due": due})
    return found


def _due_word(text: str):
    m = re.search(r"срок\w*\s*[—:-]?\s*(понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|\d{1,2}[./]\d{1,2})", text, re.I)
    return m.group(0) if m else None


class HeuristicClient(LLMClient):
    name = "heuristic"

    def complete_json(self, system, user, purpose):
        if purpose.startswith("extract"):
            obj = {"assignments": extract(_parse_lines(user))}
        elif purpose == "closing":
            obj = {"closures": self._closures(user)}
        elif purpose.startswith("resolve"):
            obj = self._resolve(_json_after("СОСТОЯНИЕ:", user) or {})
        else:
            obj = {}
        return obj, {"tokens_in": estimate_tokens(system + user), "tokens_out": estimate_tokens(json.dumps(obj, ensure_ascii=False)),
                     "cost_usd": 0.0, "seconds": 0.0}

    @staticmethod
    def _closures(user: str) -> list:
        tasks = _json_after("ЗАДАЧИ:", user) or []
        out = []
        for t in tasks:
            best, score = None, 0.0
            for ph in t.get("phrases", []):
                c = coverage(t["description"], ph["text"])
                if c > score:
                    best, score = ph["k"], c
            if best is not None and score >= 0.34:
                out.append({"task_id": t["id"], "phrase": best})
        return out

    @staticmethod
    def _resolve(state: dict) -> dict:
        item = state.get("item", {})
        obs = state.get("observations", [])
        tools_used = [o["tool"] for o in obs]
        if item.get("kind") == "duplicate":
            if "search_registry" not in tools_used:
                return {"tool": "search_registry", "args": {"text": item.get("action", "")}}
            hits = obs[tools_used.index("search_registry")]["result"].get("tasks", [])
            if hits and hits[0]["coverage"] >= 0.6 and hits[0].get("same_numbers", True):
                return {"tool": "mark_duplicate", "args": {"task_id": hits[0]["id"]}}
            return {"tool": "accept_new", "args": {}}
        if "find_person" not in tools_used:
            return {"tool": "find_person", "args": {"name": item.get("to", "")}}
        fp = obs[tools_used.index("find_person")]["result"]
        cands = fp.get("candidates", [])
        if fp.get("status") in ("exact", "fixed", "department") and len(cands) == 1:
            return {"tool": "assign", "args": {"person_id": cands[0]["id"]}}
        if fp.get("status") == "ambiguous" and cands:
            if "participants" not in tools_used:
                return {"tool": "participants", "args": {}}
            speakers = [norm(s["name"]) for s in obs[tools_used.index("participants")]["result"].get("speakers", [])]
            present = [c for c in cands if any(stem(w) in [stem(x) for x in sp.split()] for sp in speakers for w in norm(c["full_name"]).split()[:1])]
            if len(present) == 1:
                return {"tool": "assign", "args": {"person_id": present[0]["id"]}}
        return {"tool": "to_operator", "args": {"reason": fp.get("reason", "исполнитель не установлен")}}
