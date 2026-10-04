"""Дорожная карта проекта — собирает КОД из реестра задач и единиц встречи.

Почему не модель (уроки Проекта ERP):
- Карта, пересобираемая моделью, переписывалась почти целиком: из 65–68
  предложений дословно сохранялось 0–1; появлялась несуществующая
  «Задача №117»; на Qwen проверку не прошла 4 раза из 4 (0,28 $ впустую).
- Сборка из единиц на копии 02–03.10 дала опору каждому пункту и стоила
  в разы дешевле; здесь она доведена до «модели не нужно вовсе».
Правила, перенесённые из пробной сборки ERP:
- блоки предметной области — из темы (roadmap.blocks) с ключевыми словами;
  пункт без блока — в «Прочее» (отнесение «по общим словам» в ERP было
  грубым — открытый вопрос владельца; здесь оно настраивается темой);
- части блока: Сделано · В работе · Действует · Открытые вопросы · Вехи;
- «решено — не значит сделано»: решения никогда не идут в «Сделано»;
- не больше N пунктов на часть (замер 03.10: 5), остальное — «ещё N»;
- у каждого пункта сноска-источник (встреча / дата постановки);
- внизу «Открыто давно, без движения»;
- почти одинаковые формулировки из записи — один раз (задачи реестра не склеиваются).
Карта не хранится: собирается при показе и всегда соответствует реестру,
поэтому баннер «текст мог устареть» ей не нужен.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .text import jaccard, stems
from .units import effective

PARTS = [("done", "Сделано"), ("work", "В работе"), ("active", "Действует"), ("questions", "Открытые вопросы"),
         ("milestones", "Вехи")]


def _ddmm(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d.%m.%y")
    except ValueError:
        return iso


def _block_of(text: str, blocks: list[dict]) -> str | None:
    st = set(stems(text))
    best, score = None, 0
    for b in blocks:
        kw = set()
        for k in b.get("keywords", []):
            kw |= set(stems(k))
        s = len(st & kw)
        if s > score:
            best, score = b["title"], s
    return best


def build(store, theme, project_id: int, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    cfg = theme.get("roadmap", {}) or {}
    blocks = [b for b in cfg.get("blocks", []) if isinstance(b, dict) and b.get("title")]
    other = cfg.get("other_title", "Прочее")
    limit = int(cfg.get("items_per_part", 5))
    stale_days = int(cfg.get("stale_days", 30))
    edge = (today - timedelta(days=stale_days)).isoformat()

    tasks = store.q("SELECT t.*, m.date AS mdate FROM tasks t LEFT JOIN meetings m ON m.id = t.source_meeting_id "
                    "WHERE t.project_id=? ORDER BY t.id", (project_id,))
    status = {t["id"]: t["status"] for t in tasks}
    last_move = {r["task_id"]: r["at"] for r in store.q(
        "SELECT h.task_id, MAX(h.at) AS at FROM task_history h JOIN tasks t ON t.id = h.task_id "
        "WHERE t.project_id=? GROUP BY h.task_id", (project_id,))}
    units = store.q("SELECT u.*, m.date AS mdate FROM units u LEFT JOIN meetings m ON m.id = u.meeting_id "
                    "WHERE u.project_id=? AND u.status != 'removed' ORDER BY m.date, u.id", (project_id,))

    items: list[dict] = []
    for t in tasks:
        if t["status"] == "dropped":
            continue
        part = "done" if t["status"] == "done" else "work"
        who = t["assignee"] or theme.word("unassigned")
        note = (f"закрыто {_ddmm(t['date_closed'])}" if part == "done" else f"{who} · поставлена {_ddmm(t['date_set'])}")
        items.append({"part": part, "text": t["description"], "note": note, "src": "task", "stale":
                      part == "work" and (t["date_set"] or "9999") < edge and (last_move.get(t["id"]) or "") < edge})
    for u in units:
        st, why = effective(u, status, today)
        if u["kind"] == "task":
            continue
        note = f"встреча {_ddmm(u['mdate'])}"
        if u["kind"] == "milestone":
            part = "milestones"
            note += " · достигнуто" if st not in ("open", "active") else ""
        elif st not in ("open", "active"):
            continue                       # закрытые решения и вопросы в карту не идут — они в истории
        elif u["kind"] in ("decision", "agreement"):
            part = "active"                # решено — не значит сделано
            if u["planned_date"]:
                note += f" · срок {_ddmm(u['planned_date'])}"
        elif u["kind"] == "open_question":
            part = "questions"
        else:
            continue                       # уточнения живут в карточке задачи
        items.append({"part": part, "text": u["text"], "note": note, "src": "unit",
                      "stale": part == "questions" and (u["mdate"] or "9999") < edge})

    # почти одинаковые формулировки из записи — один раз; задачи реестра не
    # склеиваются никогда: это разные записи по определению
    seen: list[tuple[str, set]] = []
    uniq = []
    for it in items:
        st = set(stems(it["text"]))
        if it["src"] == "unit":
            if any(p == it["part"] and jaccard(st, o) >= 0.6 for p, o in seen):
                continue
            seen.append((it["part"], st))
        it["block"] = _block_of(it["text"], blocks) or other
        uniq.append(it)

    order = [b["title"] for b in blocks] + [other]
    out_blocks = []
    for title in order:
        mine = [i for i in uniq if i["block"] == title]
        if not mine:
            continue
        parts = []
        for key, label in PARTS:
            rows = [i for i in mine if i["part"] == key]
            if rows:
                parts.append({"key": key, "label": label, "items": rows[:limit], "more": max(0, len(rows) - limit)})
        out_blocks.append({"title": title, "parts": parts})
    stale = [i for i in uniq if i["stale"]]
    counts = {k: sum(1 for i in uniq if i["part"] == k) for k, _ in PARTS}
    return {"as_of": today.isoformat(), "blocks": out_blocks, "stale": stale, "counts": counts,
            "stale_days": stale_days}


def _sentence(text: str) -> str:
    """Точка в конце, но не после «?» и «!» (в ERP было «…профиля?.» — units_docs._line)."""
    t = " ".join((text or "").split()).rstrip(".")
    return t if t.endswith(("?", "!", "…")) else t + "."


def to_markdown(rm: dict, theme) -> str:
    title = theme.get("vocabulary.roadmap", "Дорожная карта проекта")
    c = rm["counts"]
    out = [f"# {title}", "",
           f"*Собрано {_ddmm(rm['as_of'])} из реестра задач и записей встреч. Сделано {c['done']}, в работе {c['work']}, "
           f"действует решений {c['active']}, открытых вопросов {c['questions']}.*", ""]
    if not rm["blocks"]:
        out.append("Пока пусто: нет задач и единиц встречи.")
    for b in rm["blocks"]:
        out += [f"## {b['title']}", ""]
        for p in b["parts"]:
            out.append(f"**{p['label']}:**")
            out += [f"- {_sentence(i['text'])} *({i['note']})*" for i in p["items"]]
            if p["more"]:
                out.append(f"- *…и ещё {p['more']}*")
            out.append("")
    if rm["stale"]:
        out += [f"## Открыто давно, без движения (больше {rm['stale_days']} дней)", ""]
        out += [f"- {_sentence(i['text'])} *({i['note']})*" for i in rm["stale"]]
    return "\n".join(out).rstrip() + "\n"
