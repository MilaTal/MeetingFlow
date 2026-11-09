# -*- coding: utf-8 -*-
"""Договорённости из реестра — в показ протокола с пометкой (решение Планёрки 09.11.2026, где применимо).

У Планёрки договорённости встречи вставляются в показ и выгрузку протокола все действующие, «под вопросом» — с пометкой,
а хранимый документ не меняется. У нас та же тихая потеря: единицы «договорённость/решение» есть в реестре, а в тексте их
может не быть (замер 09.11: встречи 2/4/7/8 — 18/1, 9/0, 8/0, 7/1).

Здесь — тот же принцип: при показе и выгрузке недостающие единицы дописываются строками «(из реестра)»; протокол в базе
не меняется. По умолчанию выключено: `WEBAPP_DOGOVORENNOSTI_V_POKAZE=1`.
"""
from __future__ import annotations

import os

ПЕРЕМЕННАЯ = "WEBAPP_DOGOVORENNOSTI_V_POKAZE"
ЗАГОЛОВОК = "## Договорённости (из реестра)"
ПОМЕТКА = "(из реестра)"


def включено() -> bool:
    return (os.environ.get(ПЕРЕМЕННАЯ) or "").strip().lower() in ("1", "on", "true", "да")


def _норм(текст: str | None) -> str:
    return " ".join((текст or "").replace("ё", "е").lower().split())


def недостающие(store, meeting_id: int, md: str | None) -> list[str]:
    """Тексты единиц, которых нет в протоколе (первые 30 знаков, без «ё» и регистра)."""
    текст = _норм(md)
    out: list[str] = []
    for r in store.q("SELECT text FROM units WHERE meeting_id=? AND kind IN ('agreement','decision') "
                     "AND COALESCE(status,'') != 'dropped' ORDER BY id", (meeting_id,)):
        т = " ".join((r["text"] or "").split())
        начало = _норм(т)[:30]
        if т and начало and начало not in текст:
            out.append(т)
    return out


def дополнить(store, meeting_id: int, md: str | None) -> str:
    """Показать недостающие договорённости в разделе «Решения» (или своим разделом), не меняя хранимый документ."""
    if not включено() or not md:
        return md or ""
    строки = недостающие(store, meeting_id, md)
    if not строки:
        return md
    блок = [f"- {ПОМЕТКА} {т}" for т in строки]
    линии = md.splitlines()
    for i, строка in enumerate(линии):
        if строка.strip().lower().startswith("## решения"):
            # конец раздела «Решения»: до следующего заголовка второго уровня
            конец = next((j for j in range(i + 1, len(линии)) if линии[j].startswith("## ")), len(линии))
            return "\n".join(линии[:конец] + [""] + блок + линии[конец:])
    return "\n".join(линии + [""] + [ЗАГОЛОВОК, ""] + блок + [""])
