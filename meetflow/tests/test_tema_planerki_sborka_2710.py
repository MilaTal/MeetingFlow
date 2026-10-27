"""Тема планёрки доходит до сборки протокола 1 в 1 с ERP (27.10.2026, образец — монорепозиторий b0d8ab7,
`webapp/app/services/tema_planerki.py` и его вызовы в `meeting_pipeline`, `meeting_service`, `tablica_zadach`).

Подсказка темы (разделы вместо общего скелета, порядок объектов, «что важно») — последним блоком подсказки черновика; тема —
в шапке протокола кодом; раздел «Задачи» модель не пишет; переходящие задачи и прошлый протокол — с прошлой встречи той же
темы; протокол секретаря уточняет тему, поставленную по дню недели; выбор человека сильнее. Модель — заглушка.
"""
from __future__ import annotations

import json

from conftest import TRANSCRIPT
from meetflow.connectors.llm_mock import MockLLM
from meetflow.core import plan, tablica_zadach, topics


class Seen(MockLLM):
    def __init__(self):
        super().__init__()
        self.systems: dict[str, str] = {}

    def complete(self, system, user, **kw):
        self.systems[kw.get("purpose", "")] = system
        return super().complete(system, user, **kw)


def тема(store, name, weekdays=(), sections=(), hint="", objects=(), carry=False, head=()):
    return store.insert("meeting_topics", name=name, weekdays=json.dumps(list(weekdays)),
                        sections=json.dumps(list(sections), ensure_ascii=False), hint=hint,
                        objects=json.dumps(list(objects), ensure_ascii=False),
                        head_names=json.dumps(list(head), ensure_ascii=False), carry_same_topic=int(carry), is_active=1)


def test_подсказка_темы_как_erp():
    t = {"name": "Стройка", "sections": json.dumps(["Общие вопросы", "Стройка", "Задачи"]), "objects": '["Курск", "Бухта"]',
         "hint": "Абзац на объект."}
    h = topics.подсказка_протокола(t)
    assert "# Тема планёрки «Стройка»" in h and "1. Общие вопросы\n2. Стройка\n3. Задачи" in h
    assert "Раздел «Задачи» собирает программа" in h and "Курск; Бухта." in h and "Что важно для этой темы: Абзац на объект." in h
    assert topics.подсказка_протокола(None) == "" and topics.подсказка_протокола({"name": "Пусто"}) == ""


def test_сборка_подсказка_шапка_и_разделы(store, project, make_pipe):
    тема(store, "Стройка", weekdays=[4], sections=["Общие вопросы", "Стройка", "Задачи"], hint="Абзац на объект.",
         objects=["Курск"])
    mid = store.insert("meetings", project_id=project, date="2026-10-01")          # четверг
    store.insert("sources", meeting_id=mid, name="расшифровка.txt", kind="transcript", text=TRANSCRIPT)
    gen = Seen()
    pipe = make_pipe(gen=gen)
    assert pipe._skeleton(store.get("meetings", mid)) == ["Общие вопросы", "Стройка"]
    pipe.run(project, mid)
    sysm = gen.systems["protocol"]
    # последним блоком задачи (после разделов и схемы ответа), до общего хвоста подсказки MeetFlow
    assert "Что важно для этой темы: Абзац на объект." in sysm and sysm.index("# Тема планёрки") > sysm.index("Схема:")
    assert "Порядок объектов" in sysm and "- Общие вопросы\n- Стройка" in sysm and "- Задачи" not in sysm
    md = store.get("meetings", mid)["protocol_md"]
    assert md.splitlines()[0].startswith("# Протокол") and md.splitlines()[0].endswith(" 01.10.2026. Стройка.")
    assert "Тема: " not in md


def test_без_темы_подсказка_и_шапка_прежние(store, project, make_pipe):
    mid = store.insert("meetings", project_id=project, date="2026-10-01")
    store.insert("sources", meeting_id=mid, name="расшифровка.txt", kind="transcript", text=TRANSCRIPT)
    gen = Seen()
    make_pipe(gen=gen).run(project, mid)
    assert "Тема планёрки" not in gen.systems["protocol"]
    assert store.get("meetings", mid)["protocol_md"].splitlines()[0].endswith(" 01.10.2026")


def test_протокол_секретаря_уточняет_тему_дня(store, project, make_pipe):
    тема(store, "Стройка", weekdays=[4], sections=["Стройка"])
    общие = тема(store, "Общие вопросы", sections=["Ключевые показатели"])
    тема(store, "Склад", head=["Складская логистика"])
    m1 = store.insert("meetings", project_id=project, date="2026-10-01")
    m = store.get("meetings", m1)
    assert topics.применить_эталон(store, m, "Планерка 01.10.2026. Складская логистика.")["действие"] == "поставлена из эталона"
    assert topics.тема_встречи(store, store.get("meetings", m1))["name"] == "Склад"
    # шапка без темы — «Общие вопросы», а не тема дня недели (задание 26.10.2026)
    m2 = store.insert("meetings", project_id=project, date="2026-10-08")
    topics.сверить_со_сборкой(store, store.get("meetings", m2), ["Протокол планёрки 08.10.2026", "текст"])
    assert store.get("meetings", m2)["topic_id"] == общие
    # выбор человека сильнее эталона
    m3 = store.insert("meetings", project_id=project, date="2026-10-15", topic_source="вручную")
    r = topics.применить_эталон(store, store.get("meetings", m3), "Планерка 15.10.2026. Складская логистика.")
    assert r["действие"] == "тему выбрал человек — оставлена" and topics.тема_встречи(store, store.get("meetings", m3)) is None
    # при сборке — по заметкам секретаря
    m4 = store.insert("meetings", project_id=project, date="2026-10-22")
    store.insert("sources", meeting_id=m4, name="протокол секретаря.txt", kind="notes",
                 text="Планерка 22.10.2026. Складская логистика.\n\nПетрова Анастасия, подготовьте регламент склада до 30.10")
    make_pipe().run(project, m4)
    got = store.get("meetings", m4)
    assert got["topic_source"] == "из эталона" and got["protocol_md"].splitlines()[0].endswith(". Склад.")


def test_переходящие_и_прошлый_протокол_той_же_темы(store, project):
    стройка = тема(store, "Стройка", weekdays=[4], carry=True)
    a = store.insert("meetings", project_id=project, date="2026-09-24", protocol_md="# стройка 24.09")    # четверг
    b = store.insert("meetings", project_id=project, date="2026-09-29", protocol_md="# вторник 29.09")   # вторник
    cur = store.insert("meetings", project_id=project, date="2026-10-01")
    m = store.get("meetings", cur)
    assert topics.встречи_той_же_темы(store, m) == {a, cur}
    assert tablica_zadach.предыдущая_встреча(store, m)["id"] == a
    assert plan.collect(store, m)["previous"] == "# стройка 24.09"
    # признак снят — предыдущая по дате, как до 24.10.2026
    store.update("meeting_topics", стройка, carry_same_topic=0)
    assert tablica_zadach.предыдущая_встреча(store, m)["id"] == b
    assert plan.collect(store, m)["previous"] == "# вторник 29.09"


def test_выключенная_тема_не_действует(store, project, make_pipe):
    t = тема(store, "Стройка", weekdays=[4], sections=["Стройка"])
    store.update("meeting_topics", t, is_active=0)
    mid = store.insert("meetings", project_id=project, date="2026-10-01")
    assert topics.тема_встречи(store, store.get("meetings", mid)) is None
    assert make_pipe()._skeleton(store.get("meetings", mid)) == list(make_pipe().theme["protocol_skeleton"])
