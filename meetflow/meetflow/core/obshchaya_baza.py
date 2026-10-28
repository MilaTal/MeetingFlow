# -*- coding: utf-8 -*-
"""Общая база компании: справочник проектов и внешние контакты «Команды» Планёрки (задание владелицы 28.10.2026).

Зачем. В MeetFlow будут встречи с общей для компании тематикой: в них звучат проекты и внешние люди компании, которых нет
в справочнике самого MeetFlow. Планёрка и Проект ERP этот справочник уже ведут (Планёрка — `projects` с вариантами
написания, площадками `parent_id` и цепочкой договора; «Команда» — `users` с признаком внешнего и организацией; ERP —
снимок `company_projects`). MeetFlow берёт его из рабочей базы Планёрки, открывая её только на чтение (`mode=ro`, как
перенос ролей `scripts/roli_iz_planerki_2710.py`); в базу MeetFlow ничего не копируется.

Где используется (только когда общая база включена для проекта встречи):
  * узнавание проекта записи (`proekt_zapisi.проект_файла`): своё не узналось, а в имени подпапки или файла назван проект
    общей базы — встреча остаётся проекту папки (он ведёт встречи общей тематики), а не уходит в «проект не определён»;
  * семейства проектов укрупнения (`tablica_zadach.справочники_укрупнения`): площадки общей базы — подпроекты своего
    родителя, в том числе родителя из справочника MeetFlow с тем же названием;
  * справочник контрагентов укрупнения (`ukrupnenie_sborka._справочник`): подтверждённые человеком внешние контакты —
    фамилия и организация, свои сотрудники компании — фамилии, которые контрагентом не бывают, цепочки договора проектов;
  * подсказки: словарь распознавания (`slovar_whisper.имена_базы`) и узкий вызов поручений (`extract_tasks`) — названия
    проектов строкой «для написания, НЕ источник фактов», внешние — по правилу `vneshnie_kontakty.в_подсказку`.

Свой справочник главнее. Проект общей базы, чьё название или вариант совпали с названием или вариантом проекта MeetFlow
(е = ё, без регистра и кавычек, код при названии — вариант написания), не берётся: действует свой. Человек общей базы,
чьё ФИО совпало с записью «Команды» проекта, не берётся: действует своя запись. Неподтверждённые, безличные метки и
снятые (`is_active = 0`) не берутся никогда — правило «внешние только подтверждённые» (24.10.2026).

Как включается (выключатели «Параметров системы», настройки базы):
  * `company_base_path` (общая) — путь к рабочей `app.db` Планёрки; не задан — переменная окружения
    `MEETFLOW_COMPANY_BASE`; нет ни того, ни другого или файл не открывается — общей базы нет, всё как прежде;
  * `company_topic` (у проекта) — «встречи общей тематики компании»: да — проект и его подпроекты пользуются общей базой;
  * `company_base_all` (общая) — общая база всем проектам сразу, без флага у каждого (по умолчанию нет).
По умолчанию выключено: проект узкой тематики не получает в подсказку чужие названия, пока его не отметят.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

НАСТРОЙКА_ПУТЬ = "company_base_path"
ПЕРЕМЕННАЯ_ПУТЬ = "MEETFLOW_COMPANY_BASE"
НАСТРОЙКА_ТЕМАТИКА = "company_topic"
НАСТРОЙКА_ВСЕМ = "company_base_all"
ИСТОЧНИК = "общая база компании"

_кэш: dict = {}


def путь(store) -> Path | None:
    """Путь к базе Планёрки: настройка, иначе переменная окружения; None — не задан."""
    v = store.get_setting(НАСТРОЙКА_ПУТЬ, None, None) or os.environ.get(ПЕРЕМЕННАЯ_ПУТЬ) or ""
    v = str(v).strip().strip('"')
    return Path(v) if v else None


def _надпроект(store, project_id: int | None) -> int | None:
    p = store.get("projects", project_id) if project_id else None
    return (p or {}).get("parent_id")


def отмечен(store, project_id: int | None) -> bool:
    """Проект (или его надпроект) отмечен «встречи общей тематики компании», либо общая база включена всем."""
    if bool(store.get_setting(НАСТРОЙКА_ВСЕМ, None, False)):
        return True
    if not project_id:
        return False
    if bool(store.get_setting(НАСТРОЙКА_ТЕМАТИКА, project_id, False)):
        return True
    род = _надпроект(store, project_id)
    return bool(род) and bool(store.get_setting(НАСТРОЙКА_ТЕМАТИКА, род, False))


def включена(store, project_id: int | None) -> bool:
    """Пользоваться ли общей базой во встречах проекта: проект отмечен и база Планёрки открывается."""
    if not отмечен(store, project_id):
        return False
    return bool(прочитать(store)["ok"])


def _столбцы(con, таблица: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({таблица})")}


def _из_файла(п: Path) -> dict:
    """Проекты и люди Планёрки; база открывается только на чтение."""
    con = sqlite3.connect(f"file:{п.as_posix()}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        пс = _столбцы(con, "projects")
        поля = ["id", "name"] + [к for к in ("aliases", "parent_id", "is_active", "contract_chain") if к in пс]
        проекты = [dict(r) for r in con.execute(f"SELECT {', '.join(поля)} FROM projects ORDER BY id")]
        ус = _столбцы(con, "users")
        поля = ["full_name"] + [к for к in ("is_external", "organization", "confidence", "is_active", "department")
                                if к in ус]
        люди = [dict(r) for r in con.execute(f"SELECT {', '.join(поля)} FROM users ORDER BY id")]
    finally:
        con.close()
    return {"ok": True, "projects": проекты, "people": люди, "error": ""}


def прочитать(store) -> dict:
    """{"ok", "projects", "people", "error", "path"} — содержимое базы Планёрки; перечитывается при смене файла."""
    п = путь(store)
    if п is None:
        return {"ok": False, "projects": [], "people": [], "error": "путь к базе Планёрки не задан", "path": ""}
    try:
        ст = п.stat()
        ключ = (str(п), ст.st_mtime_ns, ст.st_size)
    except OSError:
        return {"ok": False, "projects": [], "people": [], "error": "файл базы Планёрки не найден", "path": str(п)}
    if _кэш.get("ключ") != ключ:
        try:
            данные = _из_файла(п)
        except sqlite3.Error as e:
            данные = {"ok": False, "projects": [], "people": [], "error": f"база Планёрки не открылась: {e}"}
        _кэш.clear()
        _кэш.update(ключ=ключ, данные=данные)
    return {**_кэш["данные"], "path": str(п)}


def _ключи(имя: str | None) -> set[str]:
    """Название для сравнения со своим справочником: как `ukrupnenie_zadach._ключ_проекта`, и без кода при названии."""
    from . import ukrupnenie_zadach as u
    к = u._ключ_проекта(имя)
    if not к:
        return set()
    без_кода = u._БЕЗ_КОДА_RE.split(к, maxsplit=1)[0].strip(" -–—*.")
    return {к} | ({без_кода} if len(без_кода) >= 3 else set())


def _варианты(aliases) -> list[str]:
    from .proekt_zapisi import _варианты as в
    return в(aliases)


def _свои_проекты(store) -> list[dict]:
    return store.q("SELECT id, name, aliases FROM projects WHERE COALESCE(archived, 0) = 0")


def проекты(store, project_id: int | None) -> list[dict]:
    """Проекты общей базы, которых нет в своём справочнике: {"id", "name", "aliases" (строкой), "parent_id",
    "is_active", "contract_chain", "source"}. Номера — отрицательные (номер Планёрки со знаком минус), чтобы не
    пересекаться со своими; площадка, чей родитель есть в своём справочнике, — подпроект своего. Выключено — пусто."""
    if not включена(store, project_id):
        return []
    свои: dict[str, int] = {}
    for р in _свои_проекты(store):
        for написание in [р["name"]] + _варианты(р.get("aliases")):
            for к in _ключи(написание):
                свои.setdefault(к, р["id"])
    данные = прочитать(store)["projects"]
    по_номеру = {р["id"]: р for р in данные}

    def свой(р: dict) -> int | None:
        for написание in [р.get("name")] + _варианты(р.get("aliases")):
            for к in _ключи(написание):
                if к in свои:
                    return свои[к]
        return None
    out = []
    for р in данные:
        if not (р.get("name") or "").strip() or р.get("is_active", 1) in (0, False) or свой(р) is not None:
            continue
        род = по_номеру.get(р.get("parent_id")) if р.get("parent_id") is not None else None
        parent_id = None
        if род is not None and род.get("is_active", 1) not in (0, False):
            parent_id = свой(род) or -род["id"]
        out.append({"id": -р["id"], "name": р["name"].strip(), "aliases": р.get("aliases") or "", "parent_id": parent_id,
                    "is_active": True, "contract_chain": р.get("contract_chain") or "", "source": ИСТОЧНИК})
    return out


def _н(текст: str | None) -> str:
    return " ".join((текст or "").replace("ё", "е").replace("Ё", "Е").lower().split())


def люди(store, project_id: int | None) -> list[SimpleNamespace]:
    """Действующие подтверждённые записи «Команды» Планёрки, которых нет в «Команде» проекта: full_name, is_external,
    organization, department, confidence, is_confirmed. Неподтверждённые и безличные метки не берутся
    (`vneshnie_kontakty.используется`). Выключено — пусто."""
    if not включена(store, project_id):
        return []
    from . import vneshnie_kontakty as vk
    свои = {_н(p["full_name"]) for p in store.q("SELECT full_name FROM people WHERE project_id=?", (project_id,))}
    out, видели = [], set()
    for р in прочитать(store)["people"]:
        фио = (р.get("full_name") or "").strip()
        ключ = _н(фио)
        if not фио or ключ in свои or ключ in видели or р.get("is_active", 1) in (0, False):
            continue
        з = SimpleNamespace(full_name=фио, is_external=bool(р.get("is_external")),
                            organization=(р.get("organization") or "").strip(), department=р.get("department") or "",
                            confidence=р.get("confidence") or "confirmed")
        з.is_confirmed = vk.подтверждён(з)
        if not vk.используется(з):
            continue
        видели.add(ключ)
        out.append(з)
    return out


def внешние(store, project_id: int | None) -> list[SimpleNamespace]:
    return [з for з in люди(store, project_id) if з.is_external]


def внешние_в_подсказку(store, project_id: int | None, тексты=None) -> list[str]:
    """Строки внешних контактов общей базы для подсказки модели — по правилу `vneshnie_kontakty.в_подсказку`:
    полным именем — с пометкой «упоминать только там, где звучит»; одним словом — только прозвучавший в этой встрече."""
    from . import vneshnie_kontakty as vk
    out = []
    for з in внешние(store, project_id):
        да, пометка = vk.в_подсказку(з.full_name, внешний=True, подтверждён=True, тексты=тексты)
        if да:
            орг = f" ({з.organization})" if з.organization else ""
            out.append(f"{з.full_name}{орг} [{пометка}]" if пометка else f"{з.full_name}{орг}")
    return out


def названия_проектов(store, project_id: int | None) -> list[str]:
    """Названия проектов общей базы (без своих) — для подсказок; площадка — «Проект – Площадка»."""
    пр = проекты(store, project_id)
    имена = {р["id"]: р["name"] for р in пр}
    свои = {р["id"]: р["name"] for р in _свои_проекты(store)}
    out = []
    for р in пр:
        род = имена.get(р["parent_id"]) or свои.get(р["parent_id"]) if р["parent_id"] is not None else None
        out.append(f"{род} – {р['name']}" if род else р["name"])
    return list(dict.fromkeys(out))


def строка_проектов(store, project_id: int | None, предел: int = 150) -> str:
    """«Проекты компании (для написания названий, НЕ источник фактов): …» — своих проектов и общей базы; пусто, если
    общая база для проекта выключена (подсказка тогда прежняя)."""
    if not включена(store, project_id):
        return ""
    свои = [р["name"] for р in store.q("SELECT name FROM projects WHERE COALESCE(archived, 0) = 0 "
                                       "AND COALESCE(active, 1) = 1 ORDER BY id") if (р["name"] or "").strip()]
    имена = list(dict.fromkeys(свои + названия_проектов(store, project_id)))
    if not имена:
        return ""
    return "Проекты компании (для написания названий, НЕ источник фактов): " + "; ".join(имена[:предел])


def сводка(store, project_id: int | None = None) -> dict:
    """Состояние для экрана и записки машине: путь, открылась ли база, сколько взято и сколько перекрыто своим."""
    д = прочитать(store)
    итог = {"path": д.get("path") or "", "ok": bool(д["ok"]), "error": д.get("error") or "",
            "all_projects": bool(store.get_setting(НАСТРОЙКА_ВСЕМ, None, False)),
            "projects_in_base": len(д["projects"]), "people_in_base": len(д["people"])}
    if project_id:
        пр, лю = проекты(store, project_id), люди(store, project_id)
        итог.update(project_id=project_id, company_topic=отмечен(store, project_id), enabled=включена(store, project_id),
                    projects_taken=len(пр), subprojects_taken=sum(1 for р in пр if р["parent_id"] is not None),
                    external_taken=sum(1 for з in лю if з.is_external),
                    external_with_org=sum(1 for з in лю if з.is_external and з.organization),
                    internal_taken=sum(1 for з in лю if not з.is_external))
    return итог

