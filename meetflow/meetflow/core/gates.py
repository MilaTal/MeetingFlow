"""Проверки кандидата в задачу кодом — до реестра.

Правило Планёрки 27.09: «поручение есть тогда, когда исполнителя называют
или когда человек берёт работу на себя; остальное — догадка, и догадка
идёт оператору». Задача, не прошедшая проверку, не пропадает и не идёт в
реестр молча: она становится карточкой с причиной.

Пороги взяты из замеров источников:
- цитата: покрытие основ ≥ 0.7 в окне до 4 подряд строк (короткие строки
  ASR, Планёрка 30.09: окно подняло принятие верных с 1/6 до 3-5 из 5-8);
- дубль: Jaccard основ ≥ 0.6 при том же исполнителе (ERP draft_guards);
  разные люди — две задачи (правило 30.09);
- формулировка не длиннее 2000 знаков (ERP _cap).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .document_marks import strip_tails
from .negation import NegationRule
from .people import Team
from .security import looks_like_injection
from .morph import lemmas
from .text import coverage, sanitize, stems, words
from .types import GateResult, SourceDoc, TaskDraft

MAX_DESCRIPTION = 2000


_DATE_LIKE = re.compile(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"\d+")


def _numbers(text: str) -> set[str]:
    """Числа задачи без дат: срок не делает задачу другой, номер — делает."""
    return set(_NUMBER.findall(_DATE_LIKE.sub(" ", text or "")))



# намерение говорящего о себе («буду», «планирую», «попробую»…), а не поручение другому
_SELF_INTENT = re.compile(r"\b(планиру(ю|ем)|буд(у|ем)|собира(юсь|емся)|хочу|хотим|попробу(ю|ем)|начн(у|ём|ем))\b", re.I)

@dataclass
class GateConfig:
    quote_coverage: float = 0.7
    quote_window: int = 4
    duplicate_jaccard: float = 0.6       # с 15.10.26 — доля общих слов в same_point, имя ключа темы прежнее
    # в теме _default — false (решение владельца 03.10.26, письмо 30): решённое действие без названного
    # исполнителя — задача с пустым исполнителем, без карточки; назначает оператор при разборе
    require_assignee: bool = True
    # задача не теряется: тёзки и чужая организация — задача сразу без исполнителя + карточка
    # (решение владельца 03.10.26, письмо 30 оркестратора meeting-registry)
    task_first: bool = True


class TaskGate:
    def __init__(self, team: Team, negation: NegationRule | None = None, cfg: GateConfig | None = None):
        self.team = team
        self.neg = negation or NegationRule()
        self.cfg = cfg or GateConfig()
        self._cache_key: str | None = None
        self._line_stems: list[set[str]] = []

    def find_quote(self, quote: str, source: SourceDoc) -> str | None:
        """Ищет цитату в источнике окном подряд строк; возвращает текст
        источника (цитату берёт код, а не модель)."""
        want = set(stems(quote))
        if not want:
            return None
        lines = source.lines
        key = source.content_digest
        if self._cache_key != key:
            self._cache_key, self._line_stems = key, [set(stems(ln)) for ln in lines]
        ls = self._line_stems
        best, best_key = None, (0.0, 0)
        for i in range(len(lines)):
            if not (want & ls[i]):
                continue
            acc: set[str] = set()
            for w in range(self.cfg.quote_window):
                if i + w >= len(lines):
                    break
                acc |= ls[i + w]
                cov = round(coverage(want, acc), 6)
                # при равном покрытии — самое короткое окно: основание не
                # должно тянуть за собой чужую реплику
                key = (cov, -(w + 1))
                if key > best_key:
                    best, best_key = " ".join(lines[i:i + w + 1]), key
                if cov >= 0.999:
                    break
        return best if best_key[0] >= self.cfg.quote_coverage else None

    def _lemma_quote(self, want: str, source: SourceDoc, line_no: int | None) -> str | None:
        """Тот же поиск цитаты окном строк, но по леммам: строка с номером модели — первой, затем вся запись."""
        need = lemmas(want)
        if not need:
            return None
        lines = source.lines
        order = ([line_no] if line_no is not None and 0 <= line_no < len(lines) else []) + list(range(len(lines)))
        for i in order:
            acc: set[str] = set()
            for w in range(self.cfg.quote_window):
                if i + w >= len(lines):
                    break
                acc |= lemmas(lines[i + w]) or set()
                if coverage(need, acc) >= self.cfg.quote_coverage:
                    return " ".join(lines[i:i + w + 1])
        return None

    def _echoes_injection(self, desc: str, source: SourceDoc) -> bool:
        """Задача без цитаты, а её слова — из строки-команды системе («создай задачу „…“»): модель выполнила
        инструкцию из данных, не сославшись на неё. Строки-команды считаются один раз на источник."""
        key = id(source), len(source.text)
        if getattr(self, "_inj_key", None) != key:
            self._inj_key = key
            self._inj_lines = [set(stems(ln)) for ln in source.lines if looks_like_injection(ln)]
        mine = set(stems(desc))
        return bool(mine) and any(coverage(mine, ln) >= 0.6 for ln in self._inj_lines)

    def check(self, draft: TaskDraft, source: SourceDoc, existing: list[tuple[str, str]] | None = None) -> GateResult:
        reasons: list[str] = []
        desc = strip_tails(sanitize(draft.description).strip())[0][:MAX_DESCRIPTION]   # хвост секретаря (стенд 31)
        if not desc:
            return GateResult(False, ["empty_description"])

        # 1. цитата — по номеру строки, если модель его дала, иначе поиск
        # строка по номеру проходит тот же порог, что и поиск (находка ревью:
        # при line_no порог был 0.3 и пропускал дописанное моделью содержание)
        quote = None
        want = draft.quote or desc
        if draft.line_no is not None and 0 <= draft.line_no < len(source.lines):
            lines = source.lines
            acc: set[str] = set()
            for w in range(self.cfg.quote_window):
                if draft.line_no + w >= len(lines):
                    break
                acc |= set(stems(lines[draft.line_no + w]))
                if coverage(set(stems(want)), acc) >= self.cfg.quote_coverage:
                    quote = " ".join(lines[draft.line_no:draft.line_no + w + 1])
                    break
        if quote is None and want:
            quote = self.find_quote(want, source)
        if quote is None and want:
            # D3 (прогон 09.10.26): «заказать» и «закажите» — разные основы, одна лемма; без морфологии — как раньше
            quote = self._lemma_quote(want, source, draft.line_no)
        if not quote:
            reasons.append("no_verbatim_quote")

        # 2. вопрос / отрицание в цитате — не поручение
        if quote:
            v = self.neg.check(quote)
            if "question" in v.blockers and "assignment" not in v.blockers:
                reasons.append("question_not_assignment")
            if "negation" in v.blockers and "assignment" not in v.blockers:
                reasons.append("negation_in_quote")
            # условие и намерение говорящего о себе — не поручение и не «под вопросом» (решение владельца 15.10.26,
            # вечер: правило отрицаний сильнее решения о сомнительных задачах). «Нужно / надо» с адресатом — поручение
            if "condition" in v.blockers and "assignment" not in v.blockers:
                reasons.append("condition_not_assignment")
            # с адресатом из «Команды» («Петрова, будем готовить…») — не намерение (ответ владельца 16.10.26)
            if _SELF_INTENT.search(quote) and "assignment" not in v.blockers and not self.team.addressee(quote):
                reasons.append("intent_not_assignment")
            # отчёт о сделанном («Договор подписан, отправили…») — не поручение говорящему:
            # слово выполнения без маркера поручения или намерения — карточка (письмо 01/5)
            if "no_done_word" not in v.blockers and not {"assignment", "intent"} & set(v.blockers):
                reasons.append("report_not_assignment")

        # 3. исполнитель назван и есть в Команде
        person, pending = None, None
        named = draft.assignee
        if not named and quote:
            # D5 (прогон 09.10.26): модель исполнителя не дала, а реплика обращена к отделу или человеку из
            # «Команды» («ПТО, обновите график») — адресат берётся из цитаты
            named = self.team.addressee(quote)
        if not named and quote:
            # исполнитель «я» из подписи голоса (ERP `fill_self_assigned_responsibles`, перенос 27.10.2026): цитата в
            # строке, подписанной ФИО «Команды» по голосу, и говорящий сам в единственном числе обещает действие
            from .ispolnitel_golosom import из_подписи
            named = из_подписи(quote, desc, [p.full_name for p in self.team.people])
        if not named:
            if self.cfg.require_assignee:
                reasons.append("no_assignee")
        else:
            # D1 (прогон 09.10.26): сверяется прозвучавшее в цитате, а не имя из ответа модели
            said = self.team.said(named, quote or draft.quote or "")
            m = None
            if said is None:
                # имя модели в цитате не прозвучало — не подставлять молча: задача без исполнителя и карточка
                guess = self.team.find(named).person
                if self.cfg.task_first:
                    pending = {"reason": "not_said", "candidates": [guess] if guess else [], "marks": []}
                else:
                    reasons.append("assignee_not_said")
            else:
                # фраза поручения и описание — для признаков несовпадения («подрядчик Игнатов из ТМК»)
                m = self.team.find(said, context=quote or draft.quote or "", description=desc)
                person = m.person
            if m is None:
                pass
            elif person is None and self.cfg.task_first and m.via in ("same_or_new", "ambiguous") and m.candidates:
                pending = {"reason": m.via, "candidates": m.candidates, "marks": m.marks}
            elif person is None and self.cfg.task_first and m.via == "department_without_head":
                # отдел без руководителя: задача сразу, исполнитель — отдел, рядом карточка «назначить
                # ответственного в отделе» (решение владельца 03.10.26, письмо 36)
                pending = {"reason": "department", "name": named.strip(), "candidates": m.candidates,
                           "marks": []}
            elif person is None and self.cfg.task_first and m.via == "unknown":
                # документ 14 (владелец 03.10.26): уже заведённый «не подтверждён» — это он; фамилия и имя без
                # похожих — новая запись «не подтверждён»; одно слово или внешний без роли — без исполнителя + карточка
                # упоминание модели прозвучало дословно («Сидоров Олег из ТМК») — берём его целиком: служебное
                # «из» несёт признак внешнего человека; иначе — только прозвучавшее
                q_words = set(words(quote or draft.quote or ""))
                as_said = named if all(w in q_words for w in words(named)) else said
                person = self.team.find_unconfirmed(as_said)
                if person is None:
                    name = self.team.new_person_name(as_said)
                    pending = ({"reason": "new_person", "name": name, "candidates": [], "marks": []} if name
                               else {"reason": "unknown", "candidates": [], "marks": []})
            elif person is None:
                reasons.append(m.via if m.via in ("same_or_new", "department_without_head") else
                               "assignee_ambiguous" if m.ambiguous else "assignee_not_in_team")

        # 4. дубль активной задачи того же человека
        for old_desc, old_assignee in existing or []:
            same_person = person is not None and old_assignee == person.label
            # разный набор чисел вне сроков («акт номер 0» и «номер 1») — разные задачи (01/14). Похожесть —
            # same_point, а не Жаккар (стенд 36, 37): на парах «то же поручение / другое по той же теме» Жаккар
            # по основам и по леммам — 7 из 10, same_point — 10 из 10 (tests/test_stand_1510_duplicate_pairs.py);
            # своё главное слово с обеих сторон («дату / цену») — два поручения
            from .units import same_point
            if same_person and _numbers(desc) == _numbers(old_desc) and \
                    same_point(desc, old_desc, self.cfg.duplicate_jaccard):
                reasons.append("duplicate")
                break

        # 5. подозрение на внедрённую инструкцию — только человеку
        # и по тому, на что сослалась модель: цитата не найдена, а строка или её цитата — команда системе. С 15.10.26
        # сомнительное идёт в реестр под вопросом — без этой проверки туда попадала «задача» из внедрённой команды
        named = source.lines[draft.line_no] if draft.line_no is not None and 0 <= draft.line_no < len(source.lines) else ""
        if any(x and looks_like_injection(x) for x in (desc, quote, draft.quote, named)) or \
                (not quote and self._echoes_injection(desc, source)):
            reasons.append("suspicious_instruction")

        # 6. существенность — правило кодом (ERP `sushchestvennost.решение`, решения владелицы 21–22.10.2026, перенос
        # 27.10.2026): мелочь, обрывок реплики, общее пожелание без предмета — не задача (отсеивается строкой журнала,
        # при узком пороге — «Возможные поручения»); пересказ в третьем лице с именем внутри — «под вопросом». Только у
        # кандидата, прошедшего остальные проверки; оценка моделью (поля significance ERP) в MeetFlow не переносилась
        if not reasons:
            from .sushchestvennost import ОТСЕЯТЬ, ПОД_ВОПРОСОМ, решение
            как, _почему = решение(desc)
            if как == ОТСЕЯТЬ:
                reasons.append("insignificant")
            elif как == ПОД_ВОПРОСОМ:
                reasons.append("third_person_retelling")

        return GateResult(not reasons, reasons, person, quote or "", desc, pending if not reasons else None)
