"""Сопоставление людей с «Командой».

Правила владельца, ставшие кодом:
- непроверенное ФИО не идёт в рабочие материалы — кандидат карточкой (26.09);
- человек не из Команды — задача не ставится до подтверждения (02.10);
- своим считается только то же имя И фамилия (одно слово в разных падежах,
  хвост ≤ 2 букв); неполное упоминание и тёзки — карточкой с кандидатами;
- уменьшительные имена берутся из темы (people.diminutives), не угадываются;
- отдел без фамилии → руководитель отдела из темы, иначе карточка.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from .text import _WORD, content_words, same_lexeme, same_word, stems, words
from .types import Person

SURNAME_AUTOFIX, SURNAME_SUSPECT = 0.85, 0.78
# частые имена — чтобы имя не сравнивалось с фамилией по сходству (пакет 01 meeting-registry)
COMMON_FIRST = set("""иван петр павел олег игорь антон андрей юрий роман максим артем денис илья кирилл никита
егор виктор григорий борис федор степан тимур руслан станислав сергей дмитрий александр алексей михаил николай
владимир константин евгений вячеслав василий ольга елена ирина анна мария дарья ксения полина алина виктория
софья лидия валентина людмила любовь инна жанна оксана алла нина тамара лариса майя марина светлана наталья
татьяна юлия анастасия екатерина надежда галина вера""".split())


_FOREIGN = re.compile(r"\b(подрядчик\w*|субподрядчик\w*|заказчик\w*|поставщик\w*|их)\b", re.I)
_ORG_AFTER = re.compile(r"\b(?:из|от)\s+[«\"]?([А-ЯЁA-Z][\w\-]+)")


def _abbrev(name: str) -> str:
    """«отдел технического надзора» и «ОТН» — один отдел: сокращение по первым буквам."""
    ws = words(name)
    return ws[0] if len(ws) == 1 else "".join(w[0] for w in ws)


@dataclass
class Match:
    person: Person | None
    candidates: list[Person] = field(default_factory=list)
    via: str = ""
    marks: list[str] = field(default_factory=list)     # признаки несовпадения («подрядчик», «ТМК»)
    dept_marks: list[str] = field(default_factory=list)  # другой отдел в фразе: задача заводится, рядом карточка

    @property
    def ambiguous(self) -> bool:
        """Есть кандидаты, но не однозначно: неполное упоминание или тёзки."""
        return self.person is None and len(self.candidates) >= 1


class Team:
    def __init__(self, people: list[Person], diminutives: dict[str, list[str]] | None = None,
                 department_heads: dict[str, str] | None = None, tasks: list[dict] | None = None,
                 today: str | None = None):
        self._tasks = tasks or []                 # реестр — для профиля человека (темы за 60 дней)
        self._since = ""
        if today:
            try:
                self._since = (date.fromisoformat(today[:10]) - timedelta(days=60)).isoformat()
            except ValueError:
                self._since = ""
        self.people = [p for p in people if p.confirmed]
        self.unconfirmed = [p for p in people if not p.confirmed]
        # «Настя» -> ["Анастасия"]
        self._dim = {k.lower(): [v.lower() for v in vs] for k, vs in (diminutives or {}).items()}
        self._heads = {k.lower(): v for k, v in (department_heads or {}).items()}

    def _first_names(self, token: str) -> list[str]:
        t = token.lower()
        return [t] + self._dim.get(t, [])

    def find(self, mention: str, context: str = "", description: str = "") -> Match:
        """context — фраза поручения (для признаков несовпадения), description —
        описание задачи (для профиля внешнего)."""
        mention = (mention or "").strip()
        if not mention:
            return Match(None)
        low = mention.lower()
        # отдел без фамилии
        for dept, head in self._heads.items():
            if low == dept or low in (f"отдел {dept}", f"{dept} отдел"):
                m = self.find(head)
                if m.person:
                    return Match(m.person, via="department_head")
        # отдел без руководителя — карточка с сотрудниками отдела, в рабочий материал не идёт
        # (правило владельца 26.09; отдельная причина — письмо meeting-registry 14, R15)
        if mention.isupper() and 2 <= len(mention) <= 6 or low.startswith("отдел"):
            members = [p for p in self.people if p.department and _abbrev(p.department) == _abbrev(mention)]
            return Match(None, candidates=members, via="department_without_head")
        org_toks = self._org_tokens(mention)                  # «Иван из ТМК» — организация в самом упоминании
        toks = [t for t in words(mention) if t not in ("из", "от") and t not in org_toks]
        if not toks:
            return Match(None)
        inits = [t for t in toks if len(t) == 1 and t.isalpha()]
        if inits and len(inits) < len(toks):
            return self._by_initial(toks, inits, context, description)
        name_low = " ".join(toks)
        exact = [p for p in self.people if p.full_name.lower().replace("ё", "е") == name_low
                 or name_low in [a.lower() for a in p.aliases]]
        exact = self._by_org(exact, org_toks or self._org_tokens(context)) if len(exact) > 1 else exact
        if len(exact) == 1 and len(toks) >= 2:
            return Match(exact[0], via="exact")
        full = [p for p in self.people if self._full_hit(p, toks)]
        if len(full) == 1:
            return Match(full[0], via="surname+name")
        fixed, suspects = (None, []) if full else self._distorted(toks)
        if fixed:
            return Match(fixed, via="distorted+name")
        # рабочий ключ (решение владельца 03.10.26, «один человек или два»): слово, которое
        # есть только у одного человека «Команды», — это он, если нет признака несовпадения
        owners = self._key_owners(toks) if not full else full
        if org_toks:
            owners = self._by_org(owners, org_toks)
        elif len(owners) > 1:
            narrowed = self._by_org(owners, self._org_tokens(context))
            owners = narrowed if len(narrowed) == 1 else owners
        if len(owners) == 1:
            x = owners[0]
            marks, dept = ([], []) if org_toks else self._mismatch(x, context, description)
            if marks:
                return Match(None, candidates=[x], via="same_or_new", marks=marks)
            return Match(x, via="key", dept_marks=dept)
        # ключ общий без имени — карточка с кандидатами (тёзки — всегда карточкой, 03.10.26)
        partial = owners or [p for p in self.people if self._partial_hit(p, toks)]
        if len(toks) >= 2 and not owners:
            # фамилия и имя: «похож» — это та же фамилия, а не одно совпавшее имя (документ 14)
            partial = [p for p in partial if words(p.full_name) and
                       any(same_word(t, words(p.full_name)[0]) for t in toks if not self._is_first_name(t))]
        # запись короче упоминания («Пересыпкин» при «Пересыпкин Сергей») — кандидат, а не «никого»
        # (находка Планёрки, письмо meeting-registry 23)
        partial += [p for p in self.people if p not in partial and len(words(p.full_name)) == 1
                    and any(same_word(t, words(p.full_name)[0]) for t in toks)]
        partial += [p for p in suspects if p not in partial]
        return Match(None, candidates=partial, via="ambiguous" if partial else "unknown")

    def said(self, mention: str, quote: str) -> str | None:
        """Как исполнитель назван в самой цитате — с «Командой» сверяется прозвучавшее, а не имя из ответа модели.

        Находка прогона 09.10.26 (тематика «Стройплощадка», D1): прозвучало «Ирина» при двух Иринах — модель
        вписала «Ковалёва Ирина», и тёзка ушла одной; «Лебеде» без имени — «Лебедева Ольга»; «ПТО» — что-то своё,
        и отдел остался без руководителя. Возвращает слова упоминания модели, найденные в цитате (то же слово,
        падеж, уменьшительное, искажение со сходством ≥ 0,78), в форме и порядке цитаты. Ничего из упоминания
        не прозвучало — отдел, названный в цитате, если он есть; иначе None (исполнитель не прозвучал)."""
        orig = _WORD.findall(quote or "")
        qw = [w.lower().replace("ё", "е") for w in orig]
        mw = [w for w in words(mention or "") if len(w) >= 2]
        if not qw or not mw:
            return None
        hit = []
        for i, w in enumerate(qw):
            if not orig[i][:1].isupper():
                continue        # имена и отделы в записи — с заглавной: «производства» не «производственный отдел»
            for t in mw:
                if w == t or same_word(w, t) or t in self._first_names(w) or w in self._first_names(t):
                    hit.append(i)
                    break
                if (len(w) >= 4 and len(t) >= 4 and not self._is_first_name(w) and not self._is_first_name(t)
                        and SequenceMatcher(None, w, t).ratio() >= SURNAME_SUSPECT):
                    hit.append(i)
                    break
        if hit:
            return " ".join(orig[i] for i in hit)
        depts = set(self._heads) | {p.department.lower().replace("ё", "е") for p in self.people if p.department}
        for w, o in zip(qw, orig):
            if w in depts:
                return o
        return None

    def addressee(self, quote: str) -> str | None:
        """Кому обращена реплика: слова до первой запятой после подписи говорящего («ПТО, обновите…»,
        «Лебедева Ольга, подготовьте…»). Нужен, когда модель исполнителя не дала (прогон 09.10.26, D5): адресат,
        которого знает «Команда» — человек, тёзки или отдел, — берётся из цитаты. «Хорошо, …» — не адресат."""
        first = (quote or "").splitlines()[0] if quote else ""
        first = re.sub(r"^\s*\[[^\]]*\]\s*", "", first)
        if ":" in first[:60]:
            first = first.split(":", 1)[1]
        head = first.split(",", 1)[0].strip()
        if not head or "," not in first or len(head.split()) > 4:
            return None
        m = self.find(head)
        known = m.person is not None or bool(m.candidates) or m.via in ("department_head", "department_without_head")
        return head if known else None

    def find_unconfirmed(self, mention: str) -> Person | None:
        """Уже заведённый «не подтверждён» с тем же ФИО (в любом падеже) — тот же человек, второй
        записи не заводится (документ 14)."""
        toks = [t for t in words(mention) if t.isalpha()]
        for p in self.unconfirmed:
            pw = words(p.full_name)
            if len(toks) >= 2 and len(pw) == len(toks) and all(same_word(a, b) for a, b in zip(toks, pw)):
                return p
        return None

    def new_person_name(self, mention: str) -> str | None:
        """Можно ли завести по упоминанию: фамилия и имя (два слова из букв, без инициалов) и без
        названной организации — внешнему нужны организация и роль, роль из речи не берём (документ 14)."""
        if self._org_tokens(mention) or re.search(r"(?<![А-Яа-яЁё])(из|от)\s", mention or "", re.I):
            return None
        # несколько людей («Чистякова М., Мелехова А.», «… и …») или инициалы — не один новый человек:
        # прогон ERP 03.10.26 склеил две фамилии в «Чистякова Мелехова»
        if re.search(r"[,;]|(?<![А-Яа-яЁё])и(?![А-Яа-яЁё])", mention or "") or \
                any(len(t) == 1 for t in re.findall(r"[А-Яа-яЁё]+", mention or "")):
            return None
        toks = [t for t in re.findall(r"[А-Яа-яЁё]+", mention or "") if len(t) >= 2]
        if len(toks) < 2 or len(toks) > 3:
            return None
        # слово — фамилия того, кто уже есть в «Команде», — значит «похож»: карточка, а не запись
        known = [words(p.full_name)[0] for p in self.people + self.unconfirmed if words(p.full_name)]
        if any(same_word(t.lower(), k) for t in toks for k in known):
            return None
        return " ".join(t[:1].upper() + t[1:].lower() for t in toks)

    def _by_initial(self, toks: list[str], inits: list[str], context: str, description: str) -> Match:
        """«Марина Ч.», «Назаров К.» — полное слово и инициал (решение владельца 03.10.26,
        документ meeting-registry «13_Решение — имя и инициал»). Инициал сверяется со ВТОРОЙ
        частью имени, а не с той, что названа словом («Марина М.» не Петрова Марина).
        Один подходит — назначить (с проверкой несовпадения), несколько — карточка, никого —
        «нет в Команде»."""
        full = [t for t in toks if t not in inits]
        fit = []
        for p in self.people:
            pw = words(p.full_name)
            if not pw or not all(self._matches_key(p, t) for t in full):
                continue
            # свободные части — все слова имени, кроме названной словом; отчество тоже часть
            # (соглашение Планёрки и ERP, письмо 29); нет свободных частей — инициал не противоречие (письмо 27)
            t = full[0]
            if len(pw) == 1:
                named = 0
            else:
                named = 1 if (self._is_first_name(t) and pw[1] in self._first_names(t)) or same_word(t, pw[1]) else 0
            free = [w for k, w in enumerate(pw) if k != named]
            if not free or all(any(w.startswith(i) for w in free) for i in inits):
                fit.append(p)
        if len(fit) == 1:
            marks, dept = self._mismatch(fit[0], context, description)
            if marks:
                return Match(None, candidates=fit, via="same_or_new", marks=marks)
            return Match(fit[0], via="name+initial", dept_marks=dept)
        return Match(None, candidates=fit, via="ambiguous" if fit else "unknown")

    # ---------------------------------------------------------------- ключи и профиль
    def _matches_key(self, p: Person, t: str) -> bool:
        pw = words(p.full_name)
        if not pw:
            return False
        if t in [w for a in p.aliases for w in words(a)]:
            return True
        if len(pw) == 1:                                       # внешний, известный одним словом
            return t == pw[0] or same_word(t, pw[0])
        if self._is_first_name(t):                             # имя — с именем; фамилия с ним только точно
            return pw[1] in self._first_names(t) or same_word(t, pw[1]) or t == pw[0]
        return t == pw[0] or same_word(t, pw[0]) or same_word(t, pw[1])

    def _key_owners(self, toks: list[str]) -> list[Person]:
        """Люди, которых называют все слова упоминания. Ключ рабочий, пока он у
        одного человека; считается заново при каждом построении Team, то есть
        при каждом изменении «Команды»."""
        owners = None
        for t in toks:
            hit = {id(p): p for p in self.people if self._matches_key(p, t)}
            if not hit:
                # слово, которое никого не называет, — противоречащее имя («Алексей Алексейко» при
                # Веронике) или искажённая фамилия («Лапшав Михаил»): ключ не работает, решает человек
                return []
            owners = hit if owners is None else {k: v for k, v in owners.items() if k in hit}
        return list((owners or {}).values())

    def _orgs(self) -> set[str]:
        return {w for p in self.people for w in words(p.organization or "")}

    def _org_tokens(self, text: str) -> list[str]:
        """Организации, названные в тексте: известные по «Команде» и «из/от Название»."""
        out = [w for w in words(text) if any(w == o or same_lexeme(w, o) for o in self._orgs())]
        out += [m.lower().replace("ё", "е") for m in _ORG_AFTER.findall(text or "")]
        return list(dict.fromkeys(out))

    def _by_org(self, people: list[Person], org_toks: list[str]) -> list[Person]:
        if not org_toks:
            return people
        return [p for p in people if any(same_lexeme(o, w) for o in org_toks for w in words(p.organization or ""))]

    def _profile(self, p: Person) -> set[str]:
        """Темы человека: основы описаний его задач за последние 60 дней."""
        out: set[str] = set()
        for t in self._tasks:
            if t.get("assignee") == p.label and (not self._since or (t.get("date_set") or "") >= self._since):
                out |= set(stems(t.get("description") or ""))
        return out

    def _mismatch(self, p: Person, context: str, description: str) -> tuple[list[str], list[str]]:
        """Явные признаки «это не он» при рабочем ключе — не «не похоже»."""
        ctx = context or ""
        marks: list[str] = []
        for m in _FOREIGN.findall(ctx):
            marks.append(m.lower())
        own_org = {w for w in words(p.organization or "")}
        for o in self._org_tokens(ctx):
            if not any(same_lexeme(o, w) for w in own_org):
                marks.append(o)
        # другой отдел в фразе — не задержка, а пометка (решение владельца 03.10.26, письмо 22:
        # «главное — чтобы задача не потерялась»); задача заводится, рядом карточка
        dept: list[str] = []
        other_depts = {p2.department.lower() for p2 in self.people if p2.department and p2 is not p}
        mine = (p.department or "").lower()
        for d in other_depts:
            dw = content_words(d)
            if dw and all(any(same_lexeme(a, b) for b in content_words(ctx)) for a in dw) and \
                    not (mine and all(any(same_lexeme(a, b) for b in content_words(ctx)) for a in content_words(mine))):
                dept.append(d)
        if p.external and description:
            prof = self._profile(p)
            if prof and not (set(stems(description)) & prof):
                marks.append("тема новая для этого человека")
        known = {k.lower() for k in p.known_marks}
        return [m for m in dict.fromkeys(marks) if m not in known], [d for d in dict.fromkeys(dept) if d not in known]

    def candidate_hints(self, mention: str, description: str, source_lines: list[str], notes_text: str,
                        tasks: list[dict]) -> list[dict]:
        """Кандидаты для карточки спорного имени — с подсказками, которые
        СОРТИРУЮТ, а не выбирают (решение владельца 03.10.26: подстановки тёзки
        нет никогда; ведущий и дикторы есть не всегда — на них не опираемся).
        Подсказки только из текста и реестра."""
        from .text import content_words, jaccard, same_lexeme, stems
        cands = self.find(mention).candidates
        ds = set(stems(description))
        notes_w = words(notes_text)
        out = []
        for p in cands:
            pw = words(p.full_name)
            hints = []
            if len(pw) >= 2 and any(any(same_word(w, pw[0]) for w in lw) and any(same_word(w, pw[1]) for w in lw)
                                    for lw in (words(ln) for ln in source_lines)):
                hints.append("назван полностью в этой же записи")
            similar = [t for t in tasks if t.get("assignee") == p.label
                       and jaccard(ds, set(stems(t.get("description") or ""))) >= 0.3]
            if similar:
                hints.append(f"ведёт похожие задачи в реестре: {len(similar)}")
            if pw and any(same_word(w, pw[0]) for w in notes_w):
                hints.append("есть в заметках встречи")
            if p.department and any(same_lexeme(a, b) for a in content_words(p.department)
                                    for b in content_words(description)):
                hints.append(f"отдел «{p.department}» — по теме задачи")
            out.append({"id": p.id, "name": p.label, "hints": hints})
        return sorted(out, key=lambda x: (-len(x["hints"]), x["name"]))

    def _is_first_name(self, token: str) -> bool:
        t = token.lower().replace("ё", "е")
        team_first = {words(p.full_name)[1] for p in self.people if len(words(p.full_name)) >= 2}
        dims = set(self._dim) | {v for vs in self._dim.values() for v in vs}
        return t in COMMON_FIRST or t in team_first or t in dims

    def _distorted(self, toks: list[str]) -> tuple[Person | None, list[Person]]:
        """Искажённая фамилия (распознавание: «Чистяка» вместо «Чистякова»).
        Перенесено из пакета 01 meeting-registry (письмо 05, п. 01/16) с правилом
        владельца 03.10.26: молча — только при сходстве ≥ 0,85 И том же имени;
        без имени, при противоречащем имени или сходстве 0,78–0,85 — кандидат.
        Имя с фамилией по сходству не сравнивается: «Сергей» — не «Сергеев»."""
        scored = []
        for p in self.people:
            pw = words(p.full_name)
            if len(pw) < 2:
                continue
            best, name_ok, conflict = 0.0, False, False
            for t in toks:
                if self._is_first_name(t):
                    if pw[1] in self._first_names(t):
                        name_ok = True
                    else:
                        conflict = True
                    continue
                best = max(best, SequenceMatcher(None, t, pw[0]).ratio())
            if best >= SURNAME_SUSPECT:
                scored.append((best, name_ok and not conflict, p))
        scored.sort(key=lambda x: -x[0])
        top = [x for x in scored if x[0] == scored[0][0]] if scored else []
        if len(top) == 1 and top[0][0] >= SURNAME_AUTOFIX and top[0][1]:
            return top[0][2], []
        return None, [p for _, _, p in scored]

    def _partial_hit(self, p: Person, toks: list[str]) -> bool:
        pw = words(p.full_name)
        if len(pw) < 2:
            return False
        # имя с фамилией — только точно: «Сергей» не «Сергеев» (пакет 01 meeting-registry)
        return any((t == pw[0]) if self._is_first_name(t) else same_word(t, pw[0]) for t in toks) or any(
            n == pw[1] or same_word(n, pw[1]) for t in toks for n in self._first_names(t))

    def _full_hit(self, p: Person, toks: list[str]) -> bool:
        """Фамилия и имя — РАЗНЫМИ словами упоминания («Иван» не засчитывается
        и за фамилию «Игнатов», и за имя — находка ревью)."""
        pw = words(p.full_name)
        if len(pw) < 2:
            return False
        for i, t in enumerate(toks):
            if not same_word(t, pw[0]):
                continue
            for j, u in enumerate(toks):
                if j != i and any(n == pw[1] or same_word(n, pw[1]) for n in self._first_names(u)):
                    return True
        return False
