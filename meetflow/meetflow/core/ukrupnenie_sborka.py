# -*- coding: utf-8 -*-
"""Укрупнение задач в сборке MeetFlow (перенос ERP 27.10.2026).

Сам механизм — модуль-близнец `ukrupnenie_zadach.py`, скопирован из ERP (`webapp/app/services/`, main 80df5f3) до байта,
вместе с его чистыми соседями `ispolnitel_strazh.py`, `vneshnie_kontakty.py` и `sushchestvennost.py`. Одно отличие копий:
фамилии в примерах комментариев заменены вымышленными (правило «без реальных ФИО в git»); код не менялся. Здесь — только то, что у MeetFlow своё:
задачи сборки — пары (черновик, итог ворот), а не словари ERP; запись истории — таблица `task_history`; выключатели —
«Параметры системы» (настройки базы) поверх переменных окружения модуля.

Место в сборке — как в ERP: после ворот задачи и стража исполнителя, до заведения в реестр и до таблицы документа.
Сначала сведение с открытыми задачами прошлых встреч того же исполнителя и проекта (не новая задача, а та же), затем
соседние задачи встречи одного предмета или одного контрагента — одной строкой «Объект: действие 1; действие 2».
Задача с карточкой (исполнитель на выбор, срок под вопросом) не объединяется ни с какой; сомнение — не объединять.

Выключатели (каждое основание своим, решение 25–26.10.2026):
  * `ukrupnenie_zadach` — укрупнение целиком (основание «один предмет»); переменная модуля `WEBAPP_UKRUPNENIE_ZADACH`;
  * `ukrupnenie_kontragent` — основание «один контрагент»; переменная `WEBAPP_UKRUPNENIE_KONTRAGENT`;
  * `ukrupnenie_reestr` — сведение с открытыми задачами реестра.
Настройка не задана — включено, как в ERP.
"""
from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace

from . import ukrupnenie_zadach as uz

НАСТРОЙКИ = ("ukrupnenie_zadach", "ukrupnenie_kontragent", "ukrupnenie_reestr")
# Предел пар сравнения на сборку. Сравнение попарное, со словарём pymorphy3: у планёрки 10–40 поручений и до сотни открытых
# задач — доли секунды; на нагрузочном прогоне (1 500 строк, 200 открытых) — минуты. Больше предела — шаг пропускается
# строкой итога, а не держит сборку (своё у MeetFlow: в ERP предела нет, такой нагрузки там не бывает).
ПРЕДЕЛ_ПАР = 20000


def включено(store, ключ: str) -> bool:
    v = store.get_setting(ключ, None, None)
    return True if v is None else bool(v)


def _справочник(store, project_id: int):
    """Справочник контрагентов: «Команда» проекта (внешний подтверждённый — фамилия и организация, свой — фамилия, которая
    контрагентом не бывает) и проекты справочника. Цепочки договора у проектов MeetFlow нет — поле пустое."""
    люди = [SimpleNamespace(full_name=p["full_name"], is_external=bool(p["external"]), is_confirmed=bool(p["confirmed"]),
                            organization=p.get("organization") or "")
            for p in store.q("SELECT * FROM people WHERE project_id=?", (project_id,))]
    проекты = [{"name": r["name"], "is_active": bool(r.get("active", 1)), "contract_chain": ""}
               for r in store.q("SELECT name, active FROM projects WHERE COALESCE(archived, 0) = 0")]
    return uz.справочник_контрагентов(люди, проекты)


_СТРОКА_MEETFLOW = re.compile(r"^\s*\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:\n]{2,80}?):\s*(.*)$")


def запись_как_erp(запись: str) -> str:
    """Строки MeetFlow «[чч:мм:сс] ФИО: текст» → вид ERP «чч:мм:сс<TAB>ФИО<TAB>текст»: по нему близнец узнаёт говорящего
    (`ispolnitel_strazh._ГОЛОС_RE`) для правила «соседние строки одного говорящего». Прочие строки — как есть."""
    out = []
    for ln in (запись or "").split("\n"):
        m = _СТРОКА_MEETFLOW.match(ln)
        out.append(f"{m.group(1)}\t{m.group(2).strip()}\t{m.group(3)}" if m else ln)
    return "\n".join(out)


def применить(store, project_id: int, meeting_id: int, planned: list, запись: str, с_карточкой: set[int],
              дата_встречи: str | None = None) -> dict:
    """planned — [(TaskDraft, GateResult)]; `с_карточкой` — id(черновика) задач, у которых будет карточка (срок под
    вопросом). Возвращает {"planned", "сведённые", "счёт", "строка", "истории": {id(черновика): строка истории}}."""
    запись = запись_как_erp(запись)
    итог = {"planned": list(planned), "сведённые": [], "счёт": {}, "строка": "", "истории": {}, "замены": {}}
    if not planned or not включено(store, "ukrupnenie_zadach") or not uz.включено():
        if not включено(store, "ukrupnenie_zadach"):
            итог["строка"] = "укрупнение задач выключено"
        return итог
    задачи = []
    for n, (d, g) in enumerate(planned):
        кто = g.assignee.label if g.assignee else ((g.pending or {}).get("name") if (g.pending or {}).get("reason") == "department" else "")
        t = {"description": g.description or d.description, "quote": g.quote or d.quote or "", "responsible": кто or "",
             "due_date": d.due_date or "", "_n": n}
        if (g.pending and (g.pending or {}).get("reason") != "department") or id(d) in с_карточкой:
            t["нужна_карточка"] = True
        задачи.append(t)
    счёт: dict = {}
    if включено(store, "ukrupnenie_reestr"):
        # открытые на дату встречи: задача, поставленная позже, поручение этой встречи не поглощает (стенд 42)
        открытые = [{"id": r["id"], "description": r["description"] or "", "responsible": r["assignee"] or "",
                     "project": ""}
                    for r in store.q("SELECT id, description, assignee, date_set FROM tasks WHERE project_id=? AND "
                                     "status='active' AND (source_meeting_id IS NULL OR source_meeting_id<>?)",
                                     (project_id, meeting_id))
                    if not (дата_встречи and r["date_set"] and str(r["date_set"])[:10] > str(дата_встречи)[:10])]
        if len(задачи) * len(открытые) <= ПРЕДЕЛ_ПАР:
            задачи, сведённые, счёт_р = uz.с_реестром(задачи, открытые, запись)
            счёт.update(счёт_р)
            итог["сведённые"] = сведённые
        else:
            счёт["пропущено_с_реестром"] = len(задачи) * len(открытые)
    контрагенты = _справочник(store, project_id) if включено(store, "ukrupnenie_kontragent") else None
    if len(задачи) * (len(задачи) - 1) // 2 > ПРЕДЕЛ_ПАР:
        итог["строка"] = f"укрупнение задач пропущено: задач {len(задачи)}, пар сравнения больше {ПРЕДЕЛ_ПАР}"
        return итог
    задачи, счёт_у = uz.укрупнить(задачи, запись, контрагенты=контрагенты)
    счёт.update(счёт_у)
    новые = []
    for t in задачи:
        d, g = planned[t["_n"]]
        if t.get("объединено_из"):
            прежний = id(d)
            d = replace(d, description=t["description"], due_date=t.get("due_date") or d.due_date)
            g = replace(g, description=t["description"])
            итог["истории"][id(d)] = uz.строка_истории(t)
            итог["замены"][id(d)] = прежний
        новые.append((d, g))
    итог["planned"] = новые
    итог["счёт"] = {k: v for k, v in счёт.items() if k != "пары"}
    итог["строка"] = uz.строка_итога(счёт)
    if счёт.get("пропущено_с_реестром"):
        итог["строка"] = ((итог["строка"] + "; ") if итог["строка"] else "укрупнение задач: ") + \
            f"сведение с реестром пропущено, пар больше {ПРЕДЕЛ_ПАР}"
    return итог


def записать_историю(store, task_id: int, строка: str) -> None:
    """Строка истории задачи «Объединено из: …» (источник `ukrupnenie_2510`, как ERP)."""
    if not task_id or not строка:
        return
    from .store import now
    store.insert("task_history", task_id=task_id, old_status="active", new_status="active", source=uz.ИСТОЧНИК_ИСТОРИИ,
                 evidence_quote=строка, changed_by="сборка", at=now())
