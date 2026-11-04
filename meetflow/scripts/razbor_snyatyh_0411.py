# -*- coding: utf-8 -*-
"""Разбор задач, снятых пересборкой, по нынешнему правилу замены. Только чтение: работает на временной копии базы.

Отчёт 0948fb1 считал снятую заменённой, если есть действующая задача с той же цитатой. Этого мало: широкая цитата несёт
разные поручения (решение владелицы 04.11.2026). Скрипт раскладывает снятые заново и даёт основание по каждой, чтобы
владелица решила о возврате. Сам ничего не возвращает: возврат — `vernut_snyatye_po_citate_2810.py` по её слову.

    python scripts/razbor_snyatyh_0411.py --db <путь к meetflow.db> [--meeting 1 --meeting 4] [--out <файл в Tests>]

В консоль — номера без формулировок. Формулировки, цитаты и исполнители — только в файл `--out`.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meetflow.core import povtory_reestra  # noqa: E402
from meetflow.core.rebuild import (ВОЗВРАТ, _для_сравнения, _слова, заменяющие, снята_пересборкой, та_же_цитата,  # noqa: E402
                                   цитата_в_записи)
from meetflow.core.store import Store  # noqa: E402

ЛОЖНО, ЗАМЕНА, ПУСТАЯ, ЧУЖАЯ = ("ложно снята, цитата есть, замены нет", "заменена той же работой", "цитата пустая",
                               "цитаты нет в записи")


def _класс(st, mid: int, t: dict, запись: str) -> str:
    if not (t["source_quote"] or "").strip():
        return ПУСТАЯ
    if not цитата_в_записи(t["source_quote"], запись):
        return ЧУЖАЯ
    return ЗАМЕНА if заменяющие(st, mid, t["id"], t["source_quote"]) else ЛОЖНО


def _строки(st, mid: int, t: dict, класс: str) -> list[str]:
    возврат = ВОЗВРАТ.split("(")[0]
    возвращалась = any(возврат in (h["evidence_quote"] or "") for h in st.q(
        "SELECT evidence_quote FROM task_history WHERE task_id=?", (t["id"],)))
    цитата = t["source_quote"] or ""
    out = [f"Задача {t['id']}, встреча {mid}: {класс}.",
           f"Формулировка: {t['description']}",
           f"Исполнитель: {t['assignee'] or 'нет'}. Слов в цитате: {len(_слова(цитата))}. "
           f"Возвращалась раньше: {'да' if возвращалась else 'нет'}.",
           f"Цитата: {цитата}"]
    прежняя = _для_сравнения(t)
    for r in st.q("SELECT * FROM tasks WHERE source_meeting_id=? AND status='active' AND id<>?", (mid, t["id"])):
        if та_же_цитата(цитата, r["source_quote"]):
            вердикт, основание = povtory_reestra.пара(прежняя, _для_сравнения(r))
            out.append(f"Та же цитата у задачи {r['id']}: {вердикт} ({основание}). {r['description']}. "
                       f"Исполнитель: {r['assignee'] or 'нет'}.")
    return out + [""]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--meeting", type=int, action="append")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    итог: dict[str, list[int]] = {ЛОЖНО: [], ЗАМЕНА: [], ПУСТАЯ: [], ЧУЖАЯ: []}
    строки: list[str] = []
    with tempfile.TemporaryDirectory() as папка:
        копия = Path(папка) / "копия.db"
        shutil.copy2(a.db, копия)
        st = Store(str(копия))
        встречи = a.meeting or [r["id"] for r in st.q("SELECT id FROM meetings ORDER BY id")]
        for mid in встречи:
            запись = "\n".join(r["text"] or "" for r in st.q(
                "SELECT text FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind='transcript'", (mid,)))
            if not запись.strip():
                continue
            for t in st.q("SELECT * FROM tasks WHERE source_meeting_id=? AND status='dropped' ORDER BY id", (mid,)):
                if снята_пересборкой(st, t["id"]):
                    класс = _класс(st, mid, dict(t), запись)
                    итог[класс].append(t["id"])
                    строки += _строки(st, mid, dict(t), класс)
        закрыть = getattr(st, "close", None)
        if закрыть:
            закрыть()
    for класс, номера in итог.items():
        print(f"{класс}: {len(номера)} {номера}")
    if a.out:
        Path(a.out).write_text("\n".join(строки), encoding="utf-8")
        print(f"основания записаны: {a.out}")
    print("только чтение: база не менялась, возврат — по слову владелицы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
