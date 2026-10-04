"""Кодовые проверки черновика протокола — то, что проверяющая модель почти не
ловит (письмо 18 ветки meeting-registry, запись 71 вехи 4): оценочное слово,
которого нет в источнике, — 0 из 8 прогонов; факт, перенесённый в чужой
эпизод, — 1 из 8. Вопрос механический — есть ли слово в источнике и где лежит
опорная строка, — поэтому решает код.

Перенесено из Планёрки (services/draft_checks.py, check_added_judgement и
check_facts_from_other_project; код Планёрки только прочитан). Находки — справка
рядом с замечаниями проверки, не шлюз: протокол сохраняется сразу.
"""
from __future__ import annotations

import re

from .text import stems

# Слова оценки и обвинения: протокол фиксирует сказанное, а не выносит суждение. Список намеренно
# короткий — обвинительные слова, а не любая эмоция (как в Планёрке).
JUDGEMENT = ("нарушени", "нарушил", "срыв", "сорван", "вина", "виноват", "претензи", "халатн",
             "недопустим", "безответствен", "провал", "саботаж", "обман")
RARE = 3                       # «редкое» слово факта: звучало не больше чем в 3 строках записи
_HEADER_SPLIT = re.compile(r"\s+[–—-]\s+")
_TOKEN = re.compile(r"[a-zа-я0-9]+")


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def added_judgement(draft_md: str, source_text: str) -> list[dict]:
    """Оценочное слово есть в черновике и отсутствует в источнике (сверка по основе слова)."""
    src = _norm(source_text)
    out = []
    for line in (draft_md or "").splitlines():
        s = line.strip()
        if not s or s.startswith("|"):
            continue
        low = _norm(s)
        for base in JUDGEMENT:
            if base in low and base not in src:
                out.append({"kind": "оценка", "quote": s[:200], "source_line": "",
                            "note": f"оценка «{base}…» есть в протоколе и отсутствует в записи — протокол "
                                    "фиксирует сказанное, а не выносит суждение"})
                break
    return out


def _episodes(text: str, bold_only: bool) -> list[tuple[str, str]]:
    """(заголовок, содержание) для строк «Заголовок – содержание»; в черновике — «**Заголовок** – …»."""
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("|"):
            continue
        if bold_only:
            m = re.match(r"^\*\*(.+?)\*\*\s*[–—-]\s*(.+)$", ln)
            if m:
                out.append((m.group(1).strip(), m.group(2).strip()))
            continue
        parts = _HEADER_SPLIT.split(ln.replace("*", ""), maxsplit=1)
        if len(parts) == 2 and 2 <= len(parts[0]) <= 60:
            out.append((re.sub(r"^\[[^\]]*\]\s*", "", parts[0]).strip(), parts[1].strip()))
    return out


def _header_similarity(a: str, b: str) -> float:
    """Доля слов заголовка черновика, чьё трёхбуквенное начало есть в заголовке источника."""
    toks = [t for t in _TOKEN.findall(_norm(a)) if len(t) >= 3 or t.isdigit()]
    if not toks:
        return 0.0
    src = _norm(b)
    return sum(1 for t in toks if t[:3] in src) / len(toks)


_DRAFT_EPISODE = [re.compile(r"^\*\*(.+?)\*\*\s*[–—-]\s*(.+)$"),
                  re.compile(r"^[—–-]?\s*(?:по\s+проекту|проект)\s*[«\"]?([^»\":–—]+?)[»\"]?\s*[:–—-]\s*(.+)$", re.I)]
LOOKBACK = 3                   # реплик назад: где в расшифровке последний раз назван проект


def _draft_episodes(draft_md: str) -> list[tuple[str, str]]:
    """Абзацы черновика под проектом: «**Курск** – …» (Планёрка) и «По проекту «Курск»: …» (ERP)."""
    out = []
    for ln in (draft_md or "").splitlines():
        s = ln.strip()
        for rx in _DRAFT_EPISODE:
            m = rx.match(s)
            if m:
                out.append((m.group(1).strip(), m.group(2).strip()))
                break
    return out


def _names_project(line: str, project: str) -> bool:
    """Назван ли проект в строке — с допуском на искажение распознавания («Альдаба» ~ «Эльдаба»)."""
    from difflib import SequenceMatcher

    from .text import same_lexeme
    lw = _TOKEN.findall(_norm(line))
    for pw in _TOKEN.findall(_norm(project)):
        if len(pw) < 4:
            continue
        if any(same_lexeme(w, pw) or (len(w) >= 5 and SequenceMatcher(None, w, pw).ratio() >= 0.7) for w in lw):
            return True
    return False


def facts_from_other_episode(draft_md: str, source_text: str) -> list[dict]:
    """Предложение под заголовком одного проекта, а опорная строка — в эпизоде другого.

    Обобщено против Планёрки для расшифровки: опорная строка ищется с весом по редкости основ
    («холост» решает, «производство» — нет), её эпизод — последний проект, названный в самой строке
    или до LOOKBACK реплик назад. Если опора есть и в своём эпизоде (не хуже на 0,2), молчим —
    ничего не утверждаем. Проектов в черновике меньше двух — проверять нечего."""
    drafts = _draft_episodes(draft_md)
    lines = [ln for ln in (source_text or "").splitlines() if ln.strip()]
    projects = list(dict.fromkeys(h for h, _ in drafts))
    if len(projects) < 2:          # черновик назвал один проект — остальные берём из эпизодов источника
        projects += [h for h, _ in _episodes(source_text, bold_only=False)
                     if h not in projects and len(h.split()) <= 3 and not re.search(r"[\d:]", h)]
    if len(projects) < 2 or not lines:
        return []
    line_stems = [set(stems(ln)) for ln in lines]
    project_stems = {w for p in projects for w in stems(p)}
    where: dict[str, list[int]] = {}
    for i, st in enumerate(line_stems):
        for w in st:
            where.setdefault(w, []).append(i)
    cache: dict[int, str | None] = {}

    def episode(i: int) -> str | None:
        if i not in cache:
            cache[i] = None
            for k in range(i, max(-1, i - LOOKBACK - 1), -1):
                named = [p for p in projects if _names_project(lines[k], p)]
                if named:
                    cache[i] = named[0] if len(named) == 1 else None   # названы два — неоднозначно
                    break
        return cache[i]

    out = []
    for header, body in drafts:
        for sent in re.split(r"(?<=[.;])\s+", body or ""):
            # редкое слово факта (не больше RARE строк записи, не название проекта): где оно звучало?
            for w in sorted(set(stems(sent))):
                hits = where.get(w, [])
                if not hits or len(hits) > RARE or len(w) < 5 or w in project_stems:
                    continue
                eps = {episode(i) for i in hits}
                if None in eps or header in eps:
                    continue                  # звучало и в своём эпизоде или эпизод не ясен — молчим
                ep = sorted(eps)[0]
                out.append({"kind": "факт не из того эпизода", "quote": sent.strip()[:200],
                            "source_line": lines[hits[0]].strip()[:300],
                            "note": f"факт под заголовком «{header}» («{w}…») звучал в эпизоде «{ep}» записи, "
                                    f"а не в своём"})
                break
    return out


def run_code_checks(draft_md: str, source_text: str) -> list[dict]:
    return added_judgement(draft_md, source_text) + facts_from_other_episode(draft_md, source_text)
