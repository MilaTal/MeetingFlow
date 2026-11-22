# -*- coding: utf-8 -*-
"""MeetFlow: полное ФИО в участниках и таблице задач (решения владелицы 20.11.2026).

Проверяем два фактических разрыва: раздел «Участники» оставался пустым, когда голоса не дали имён, хотя роли единиц
встречи уже знают людей; таблица задач сокращала «Фамилия Имя Отчество» до «Фамилия И.О.».
"""
from __future__ import annotations

import json

from meetflow.core import tablica_zadach


def test_участники_из_единиц_берут_полное_фио(make_pipe, store, project):
    p = make_pipe()
    mid = store.insert("meetings", project_id=project, date="2026-11-19", label="Встреча")
    store.insert("units", meeting_id=mid, kind="agreement", text="x",
                 roles=json.dumps([{"role": "участник", "person": "Ирина Геннадьевна", "in_team": True},
                                   {"role": "ответственный", "person": "Петрова Вероника Евгеньевна",
                                    "in_team": True}], ensure_ascii=False))

    class Человек:
        full_name = "Иванова Ирина Геннадьевна"

    class Match:
        person = Человек()

    class Team:
        def find(self, _name):
            return Match()

    assert p._участники_из_единиц(mid, Team()) == ["Иванова Ирина Геннадьевна"]


def test_неоднозначная_роль_остаётся_как_услышано(make_pipe, store, project):
    """Слово владелицы 20.11.2026: «Мария» при двух Мариях в «Команде» не выбрасывается, а идёт как услышано."""
    p = make_pipe()
    mid = store.insert("meetings", project_id=project, date="2026-11-19", label="Встреча")
    store.insert("units", meeting_id=mid, kind="agreement", text="x",
                 roles=json.dumps([{"role": "участник", "person": "Мария", "in_team": False}], ensure_ascii=False))
    assert p._имена_ролей(mid) == ["Мария"]
    assert p._услышанные(["Мария"], ["Белова Мария", "Орлова Мария"]) == ["Мария"]


def test_выполненная_задача_не_идёт_в_таблицу(store, project):
    """Решение владелицы 21.11.2026: после завершения задачу в протоколе не показываем, в реестре она остаётся."""
    mid = store.insert("meetings", project_id=project, date="2026-11-19", label="Встреча")
    store.insert("tasks", project_id=project, description="Активная", status="active", source_meeting_id=mid,
                 date_set="2026-11-19")
    store.insert("tasks", project_id=project, description="Выполненная", status="done", source_meeting_id=mid,
                 date_set="2026-11-19", date_closed="2026-11-20")
    store.insert("tasks", project_id=project, description="Снятая", status="dropped", source_meeting_id=mid,
                 date_set="2026-11-19")
    строки = tablica_zadach.строки_встречи(store, store.get("meetings", mid), lambda _t: "")
    assert [с.задача for с in строки] == ["Активная"]


def test_раздел_закрытых_задач_не_пишется(make_pipe, store, project):
    """Решение 21.11.2026: выполненные задачи после завершения в протоколе не показываем, отдельного раздела нет."""
    mid = store.insert("meetings", project_id=project, date="2026-11-19", label="Встреча")
    md = make_pipe()._render_protocol(store.get("meetings", mid), {}, [], [(1, "Сделали")], [], people=[])
    assert "Закрытые задачи" not in md and "Сделали" not in md


def test_таблица_задач_не_сокращает_фио(store, project):
    mid = store.insert("meetings", project_id=project, date="2026-11-19", label="Встреча")
    store.insert("tasks", project_id=project, description="Проверить отчёт", assignee="Петрова Вероника Евгеньевна",
                 status="active", source_meeting_id=mid, date_set="2026-11-19")
    meeting = store.get("meetings", mid)
    строки = tablica_zadach.строки_встречи(store, meeting, lambda _t: "")
    assert строки and строки[0].ответственный == "Петрова Вероника Евгеньевна"
