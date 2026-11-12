# -*- coding: utf-8 -*-
"""Паспорт принятого протокола MeetFlow (12.11.2026): снять и сверить после пересборки.

Только чтение для проверки; `--create` пишет паспорт в `protocol_passports`.
Запуск:
  python -I scripts/pasport_protokola.py --meeting 11 --create
  python -I scripts/pasport_protokola.py --meeting 11
  python -I scripts/pasport_protokola.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(КОРЕНЬ / "meetflow"))

from meetflow.core.pasport_protokola import получить, сверить, снять  # noqa: E402
from meetflow.core.store import Store  # noqa: E402

БАЗА = КОРЕНЬ / "data" / "meetflow.db"


def _печать(итог: dict, как_json: bool) -> None:
    if как_json:
        print(json.dumps(итог, ensure_ascii=False, indent=2))
        return
    if not итог.get("есть"):
        print("паспорта нет")
        return
    метка = "ok" if итог.get("сошлось") else "РАСХОЖДЕНИЕ"
    print(f"{метка}: паспорт v{итог.get('версия_паспорта')}, сейчас v{итог.get('версия_сейчас')}, "
          f"знаков {итог.get('было_знаков')} → {итог.get('стало_знаков')}")
    for р in итог.get("расхождения") or []:
        print("  -", р)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(БАЗА))
    ap.add_argument("--meeting", type=int)
    ap.add_argument("--all", action="store_true", help="все встречи, у которых есть паспорт")
    ap.add_argument("--create", action="store_true", help="снять паспорт с текущего состояния")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    store = Store(a.db)
    try:
        if a.create:
            if not a.meeting:
                print("для --create нужен --meeting")
                return 2
            ф = снять(store, a.meeting, by="скрипт")
            if a.json:
                print(json.dumps(ф, ensure_ascii=False, indent=2))
            else:
                print(f"паспорт встречи {a.meeting} снят: v{ф['version']}, задач {ф['active_tasks']}, "
                      f"с ответственным {ф['assignees']}, знаков {ф['protocol_len']}")
            return 0
        if a.meeting:
            и = сверить(store, a.meeting)
            _печать(и, a.json)
            return 0 if (not и.get("есть") or и.get("сошлось")) else 1
        if a.all:
            строки = store.q("SELECT DISTINCT meeting_id FROM protocol_passports ORDER BY meeting_id")
            код = 0
            for р in строки:
                и = сверить(store, р["meeting_id"])
                print(f"встреча {р['meeting_id']}:")
                _печать(и, a.json)
                код |= 0 if и.get("сошлось") else 1
            return код
        print("укажите --meeting или --all")
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
