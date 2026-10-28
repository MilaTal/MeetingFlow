"""Вернуть задачи, снятые пересборкой, хотя их цитата в записи есть (решение владелицы 28.10.2026).

До 28.10.2026 пересборка снимала задачу прежней сборки, если новая сборка её не выдала, — «не вошла в пересборку». На
одной и той же расшифровке модель выдаёт разный состав (28.10: вторая сборка сняла 9 задач из 18, с ними двух
исполнителей). Теперь снимается только задача, цитаты которой в записи нет. Этот скрипт приводит уже снятые к новому
правилу: задача встречи, последняя строка истории которой — снятие пересборкой (`rebuild`, без человека), а цитата
(`source_quote`) есть в записи встречи, возвращается в работу с прежним номером (`rebuild.вернуть`).

Снятые человеком и выполненные не трогаются. Записи встречи — текстовые источники встречи (расшифровки).

Запуск (сначала сухой ход, потом применение):
    python scripts/vernut_snyatye_po_citate_2810.py --db <путь к meetflow.db> --meeting 4
    python scripts/vernut_snyatye_po_citate_2810.py --db <путь к meetflow.db> --meeting 4 --apply
Перед применением — копия базы рядом (`meetflow.db.до-возврата-2810`). В консоль — номера задач, без формулировок.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meetflow.core.rebuild import вернуть, снята_пересборкой, цитата_в_записи  # noqa: E402
from meetflow.core.registry import TaskRegistry  # noqa: E402
from meetflow.core.store import Store  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--meeting", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = Path(a.db)
    if a.apply:
        shutil.copy2(db, db.with_name(db.name + ".до-возврата-2810"))
    st = Store(str(db))
    запись = "\n".join(r["text"] or "" for r in st.q(
        "SELECT text FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind='transcript'", (a.meeting,)))
    if not запись.strip():
        print("у встречи нет расшифровки — возвращать не по чему")
        return 1
    reg = TaskRegistry(st)
    вернуть_номера, без_цитаты = [], []
    for t in st.q("SELECT id, source_quote FROM tasks WHERE source_meeting_id=? AND status='dropped'", (a.meeting,)):
        if not снята_пересборкой(st, t["id"]):
            continue
        (вернуть_номера if цитата_в_записи(t["source_quote"], запись) else без_цитаты).append(t["id"])
    print(f"снято пересборкой, цитата в записи есть — вернуть: {len(вернуть_номера)} {вернуть_номера}")
    print(f"снято пересборкой, цитаты в записи нет — оставить снятыми: {len(без_цитаты)} {без_цитаты}")
    if a.apply:
        for tid in вернуть_номера:
            вернуть(st, reg, tid)
        print(f"возвращено: {len(вернуть_номера)}")
    else:
        print("сухой ход: ничего не изменено, для применения — --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
