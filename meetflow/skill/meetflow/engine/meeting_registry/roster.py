"""Сверка людей с «Командой». Непроверенное не идёт в рабочие материалы — кандидат уходит карточкой.

Правила владельца и их поводы:
- 26.09.26: «Лена Яков», «Емин» (есть Ерохин) — имя из распознавания сверяется кодом, подмену делает человек;
- 27.09.26: «Гуцко» принят за «Галкин» и слит — похожесть имени не повод сливать людей;
- 02.10.26: тёзки («Марина» без фамилии при двух Маринах) — карточка, а не выбор наугад;
- 02.10.26: фамилия совпадает от 0,75 и имя то же — подставлять молча («Чистяка» -> «Чистякова»).
Отдел без фамилии заменяется руководителем отдела; руководителя нет — карточка.
"""

from difflib import SequenceMatcher

from .text import norm

SHORT_FORMS = {
    "настя": "анастасия", "света": "светлана", "дима": "дмитрий", "костя": "константин", "юля": "юлия",
    "саша": "александр", "женя": "евгений", "таня": "татьяна", "лена": "елена", "миша": "михаил",
    "сережа": "сергей", "маша": "мария", "наташа": "наталья", "ира": "ирина", "оля": "ольга", "аня": "анна",
    "катя": "екатерина", "слава": "вячеслав", "вова": "владимир", "коля": "николай", "петя": "петр",
    "леша": "алексей", "алеша": "алексей", "паша": "павел", "андрюша": "андрей", "вася": "василий",
    "галя": "галина", "люда": "людмила", "надя": "надежда", "вера": "вера", "марина": "марина",
}

FIRST_NAMES = {
    "иван", "петр", "павел", "олег", "игорь", "антон", "андрей", "юрий", "роман", "максим", "артем", "денис", "илья",
    "кирилл", "никита", "егор", "виктор", "григорий", "борис", "федор", "степан", "тимур", "руслан", "станислав",
    "ольга", "елена", "ирина", "анна", "мария", "дарья", "ксения", "полина", "алина", "виктория", "софья", "лидия",
    "валентина", "людмила", "любовь", "зоя", "инна", "жанна", "оксана", "алла", "нина", "тамара", "лариса", "майя",
}

AUTO_FIX = 0.85     # выше — искажение исправляется молча (порог Планёрки после замера 26.09)
SUSPECT = 0.78       # между — кандидат карточкой; ниже — не тот человек


def _first_name(token: str) -> str:
    t = norm(token)
    for end in ("ой", "ей", "ом", "е", "у", "ы", "и", "а", "ю", "я"):
        if t.endswith(end) and len(t) - len(end) >= 3 and t[: -len(end)] in SHORT_FORMS:
            t = t[: -len(end)]
            break
    return SHORT_FORMS.get(t, t)


# Падежные окончания имён — тот же список, что в ядре MeetFlow (core/text._NAME_TAILS)
_NAME_TAILS = frozenset("""
 а я ы и е у ю ь й о ой ей ою ею ом ем ым им ах ях ам ям ами ями ов ев
 ого его ому ему ая яя ую юю ий ый ие ые их ых
""".split()) | {""}


def _same_case_word(a: str, b: str, max_tail: int = 3) -> bool:
    """Одно слово в разных падежах: общая основа ≥ 4 букв, хвосты с обеих сторон — падежные окончания.
    «Назарову» ~ «Назаров», но «Чистяка» — не «Чистякова»: «-ова» не окончание, это искажение распознавания
    (решение владельца 03.10.26, как MeetFlow core/text.same_word)."""
    if a == b:
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    if n < 4:
        return False
    ta, tb = a[n:], b[n:]
    if len(ta) > max_tail or len(tb) > max_tail:
        return False
    if ta in _NAME_TAILS and tb in _NAME_TAILS:
        return True
    return n > 4 and (a[n - 1] + ta) in _NAME_TAILS and (b[n - 1] + tb) in _NAME_TAILS


def _surname_match(heard: str, surname: str) -> float:
    """Сходство фамилии: 1,0 — то же слово, 0,95 — тот же падежом, иначе сходство написания (искажение)."""
    h, s = norm(heard), norm(surname)
    if not h or not s:
        return 0.0
    if h == s:
        return 1.0
    if _same_case_word(h, s):
        return 0.95
    return SequenceMatcher(None, h, s).ratio()


class Team:
    def __init__(self, people: list, departments: dict | None = None):
        # people: [{id, full_name: "Фамилия Имя", department, role, aliases: []}]
        self.people = people
        self.by_id = {p["id"]: p for p in people}
        self.departments = departments or {}  # {"осн": {"name": "Отдел закупок", "head_id": 7}}
        self.first_names = set(FIRST_NAMES) | set(SHORT_FORMS.values()) | {
            norm(p["full_name"].split()[1]) for p in people if len(p["full_name"].split()) > 1}

    def get(self, pid):
        return self.by_id.get(pid)

    def resolve(self, heard: str) -> dict:
        """Исход: exact | fixed | department | ambiguous | suspect | unknown. Кандидаты — всегда списком id."""
        heard = (heard or "").strip(" .,:;")
        if not heard:
            return {"status": "unknown", "candidates": [], "reason": "исполнитель не назван"}
        key = norm(heard)
        dep = self.departments.get(key) or self.departments.get(key.replace("отдел ", ""))
        if dep:
            if dep.get("head_id") in self.by_id:
                return {"status": "department", "candidates": [dep["head_id"]], "reason": f"отдел {dep['name']}: ответственный — руководитель"}
            return {"status": "ambiguous", "candidates": [], "reason": f"отдел {dep['name']} без руководителя в «Команде»"}
        for p in self.people:
            if key in [norm(a) for a in p.get("aliases", [])]:
                return {"status": "exact", "candidates": [p["id"]], "reason": "совпало с известным написанием"}

        tokens = heard.split()
        scored = []
        for p in self.people:
            parts = p["full_name"].split()
            surname, first = parts[0], (parts[1] if len(parts) > 1 else "")
            best = 0.0
            first_ok = None
            first_conflict = False
            for t in tokens:
                fn = _first_name(t)
                if fn in self.first_names:
                    # имя не сравнивается с фамилией по общему началу: «Сергей» — не «Сергеев» (ревью 03.10.26)
                    if first and fn == norm(first):
                        first_ok = True
                    elif first:
                        first_conflict = True
                    if norm(t) == norm(surname):
                        best = max(best, 1.0)
                    continue
                best = max(best, _surname_match(t, surname))
            if best >= SUSPECT or (first_ok and len(tokens) == 1):
                scored.append((p, best if not first_conflict else min(best, AUTO_FIX - 0.01), first_ok))

        if not scored:
            return {"status": "unknown", "candidates": [], "reason": f"«{heard}» нет в «Команде»"}

        surname_hits = [s for s in scored if s[1] >= SUSPECT]
        if surname_hits:
            top = max(s[1] for s in surname_hits)
            tops = [s for s in surname_hits if s[1] == top]
            if len(tops) > 1:
                with_first = [s for s in tops if s[2]]
                if len(with_first) == 1:
                    tops = with_first
                else:
                    return {"status": "ambiguous", "candidates": [s[0]["id"] for s in tops], "reason": f"«{heard}»: несколько людей с такой фамилией"}
            p, score, first_ok = tops[0]
            if score >= 1.0 or score == 0.95:
                return {"status": "exact", "candidates": [p["id"]], "reason": "фамилия совпала"}
            # молча — только при сходстве ≥ 0,85 И том же имени; фамилия без имени — кандидат карточкой
            # (решение владельца 03.10.26: «Чистяка» без имени — не Чистякова молча; так же в MeetFlow people._distorted)
            if score >= AUTO_FIX and first_ok:
                return {"status": "fixed", "candidates": [p["id"]], "reason": f"искажение «{heard}» исправлено по «Команде»"}
            return {"status": "suspect", "candidates": [p["id"]], "reason": f"«{heard}» похоже на {p['full_name']}, но не уверенно"}

        # Совпало только имя (краткая форма): один — он, несколько — тёзки, карточка
        firsts = [s[0] for s in scored if s[2]]
        if len(firsts) == 1:
            return {"status": "exact", "candidates": [firsts[0]["id"]], "reason": "имя совпало, тёзок нет"}
        return {"status": "ambiguous", "candidates": [p["id"] for p in firsts], "reason": f"«{heard}»: тёзки в «Команде»"}

    def names_compatible(self, heard: str, pid) -> bool:
        """Можно ли отдать поручение человеку pid, если на встрече прозвучало heard. Защита от подмены агентом."""
        r = self.resolve(heard)
        return pid in r["candidates"]
