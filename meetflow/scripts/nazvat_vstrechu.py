# -*- coding: utf-8 -*-
"""Название встречи по содержанию — один вызов модели и (по слову) запись в метку.

Слово владелицы 09.11.2026: имя встречи — фраза по контексту тематики (например, «Оформление транспортных документов
для ИП») плюс дата дд.мм.гг. Дата стоит отдельной колонкой и в заголовке, поэтому в метку пишется только фраза.
Ручное название не трогаем; по умолчанию работаем только с пустым/техническим названием (как `для_показа`).

    python scripts/nazvat_vstrechu.py 9                 # сухой ход: одна дешёвая модельная фраза, в базу не пишем
    python scripts/nazvat_vstrechu.py 9 --применить     # записать полученную фразу в label
    python scripts/nazvat_vstrechu.py 9 --фраза "Оформление транспортных документов для ИП" --применить
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from meetflow.connectors.registry import default_registry  # noqa: E402
from meetflow.core.config import load_theme  # noqa: E402
from meetflow.core.nazvanie_vstrechi import для_показа  # noqa: E402
from meetflow.core.pipeline import MeetingPipeline, RunBudget  # noqa: E402
from meetflow.core.store import Store  # noqa: E402
from meetflow.core.budget import BudgetLimits  # noqa: E402


def _чисто(сырое: str) -> str:
    тема = re.sub(r"\s+", " ", str(сырое or "")).strip(" .,:;—-\"«»")
    if len(тема) > 90 or not re.search(r"[^\W\d_]{3}", тема):
        return ""
    return тема


def main() -> int:
    ap = argparse.ArgumentParser(description="Название встречи по содержанию (один вызов модели)")
    ap.add_argument("встреча", type=int, help="номер встречи")
    ap.add_argument("--база", default="data/meetflow.db", help="путь к базе (по умолчанию рабочая)")
    ap.add_argument("--применить", action="store_true", help="записать фразу в метку встречи")
    ap.add_argument("--фраза", default="", help="готовая фраза: модель не зовём")
    ap.add_argument("--всегда", action="store_true", help="переписать и непустое (ручное) название")
    args = ap.parse_args()

    store = Store(args.база)
    meeting = store.get("meetings", args.встреча)
    if not meeting:
        print("нет такой встречи", file=sys.stderr)
        return 2
    текущая = для_показа(meeting.get("label"))
    if текущая and not args.всегда:
        print(f"у встречи уже есть название «{текущая}» — не трогаю (нужно переписать: --всегда)")
        return 0
    текст = meeting.get("protocol_md") or ""
    if not текст.strip():
        print("у встречи нет протокола — называть не по чему", file=sys.stderr)
        return 3

    фраза = _чисто(args.фраза)
    цена = 0.0
    if not фраза:
        theme = load_theme("it_product")
        from meetflow.web.app import _llm
        gen = _llm(theme, "generator", str(ROOT / "data" / "logs" / "llm_calls.jsonl"))
        pipe = MeetingPipeline(theme, store, default_registry(), gen, gen,
                               journal_path=ROOT / "data" / "logs" / "llm_calls.jsonl")
        budget = RunBudget(BudgetLimits(**theme.get("budget", {})))
        sysm, user = pipe.pb.название_встречи(текст)
        ответ = pipe._call(gen, budget, "nazvanie", sysm, user, args.встреча)  # noqa: SLF001 — разовый скрипт
        фраза = _чисто((ответ or {}).get("name") if isinstance(ответ, dict) else "")
        цена = budget.cost_usd
        if not фраза:
            print("модель не дала годной фразы", file=sys.stderr)
            return 4

    print(f"встреча {args.встреча} ({meeting.get('date')}): «{фраза}» · цена {цена:.5f} $")
    if args.применить:
        store.update("meetings", args.встреча, label=фраза)
        print("записано в label")
    else:
        print("сухой ход: в базу не писали (--применить)")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
