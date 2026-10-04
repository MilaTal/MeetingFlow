"""Единицы встречи (перенос из Проекта ERP с исправлениями), Дорожная карта
(собирается кодом) и поиск по базе проекта."""
import json
from datetime import date

import pytest
from conftest import TEAM
from fastapi.testclient import TestClient

from meetflow.connectors.llm_mock import MockLLM
from meetflow.core import roadmap as rm
from meetflow.core import search as sr
from meetflow.core import units as un
from meetflow.core.budget import BudgetLimits
from meetflow.core.config import load_theme
from meetflow.core.types import LLMResult
from meetflow.web.app import create_app

MEET1 = """[00:00:05] Игнатов Иван: Начинаем, коллеги.
[00:01:00] Игнатов Иван: Решили принимать панели на складе вместе с производством.
[00:02:00] Петрова Анастасия: Кто создаёт потребность на позиции с долгим сроком?
[00:03:00] Сидоров Пётр: Профиль придёт 10.10.2026 от поставщика по графику.
[00:04:00] Игнатов Иван: Договорились передавать документы только через документооборот.
[00:05:00] Игнатов Иван: Да.
"""
MEET2 = """[00:00:05] Игнатов Иван: Продолжаем.
[00:01:00] Петрова Анастасия: По потребности на позиции с долгим сроком решили: создаёт диспетчер.
[00:02:00] Сидоров Пётр: Остальное без изменений.
"""


def _meeting(store, project, d):
    return store.insert("meetings", project_id=project, date=d, label="встреча")


def _units(store, mid):
    return store.q("SELECT * FROM units WHERE meeting_id=? ORDER BY id", (mid,))


# ------------------------------------------------------------------ единицы
def test_units_extracted_with_code_quote_and_kinds(store, project, make_pipe):
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe()
    p.ingest(project, mid, "Расшифровка 01.10.2026.txt", MEET1.encode())
    rep = p.run(project, mid)
    kinds = {u["kind"] for u in _units(store, mid)}
    assert {"decision", "open_question", "milestone", "agreement"} <= kinds and rep.units_added >= 4
    q = next(u for u in _units(store, mid) if u["kind"] == "decision")
    assert "Решили принимать панели" in q["quote"] and q["ts"] == "00:01:00"   # цитата — из источника


def test_short_phrase_is_not_a_unit():
    by_n = {1: un.Line(1, 0, 0, "[00:00:01] А: Да, решили.")}
    from meetflow.core.people import Team
    assert un.parse_items([{"kind": "Решение", "statement": "решили", "lines": [1]}], by_n, Team([]), {}, None, "x") == []


def test_roles_need_grounding_near_quote():
    from meetflow.core.people import Team
    from meetflow.core.types import Person
    by_n = {n: un.Line(n, n, None, t) for n, t in enumerate(
        ["пусто", "Игнатов Иван: решили принимать панели вместе со складом", "дальше", "ещё", "и ещё", "и ещё раз"], 0)}
    items = [{"kind": "Решение", "statement": "панели вместе", "lines": [1],
              "participants": ["Игнатов Иван", "Петрова Анастасия"]}]
    out = un.parse_items(items, by_n, Team([Person("Игнатов Иван"), Person("Петрова Анастасия")]), {}, None, "x")
    assert [r["person"] for r in out[0].roles] == ["Игнатов Иван"]   # Петрова рядом не названа


def test_near_duplicates_merged():
    a = un.Extracted("open_question", "Кто создаёт потребность на позиции с долгим сроком", [3], "q", 2, 2, None, None, None)
    b = un.Extracted("open_question", "Не решено, кто создаёт потребность на позиции с долгим сроком поставки", [9], "q", 8, 8,
                     None, None, None)
    assert len(un.merge([a, b])) == 1


class UnitTask(MockLLM):
    def _units(self, data):
        return {"items": [{"kind": "Задача", "statement": "Кузнецов Олег подготовит отчёт по браку", "lines": [2],
                           "responsible": ["Кузнецов Олег"]},
                          {"kind": "Задача", "statement": "Петрова Анастасия обновит регламент склада", "lines": [3],
                           "responsible": ["Петрова Анастасия"]}]}


def test_task_from_units_goes_through_gate(store, project, make_pipe):
    text = ("[00:00:05] Игнатов Иван: Начинаем.\n[00:01:00] Игнатов Иван: Кузнецов Олег подготовит отчёт по браку.\n"
            "[00:02:00] Игнатов Иван: Петрова Анастасия обновит регламент склада к пятнице.\n")
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe(gen=UnitTask())
    p.ingest(project, mid, "t 01.10.2026.txt", text.encode())
    rep = p.run(project, mid)
    tasks = [t["description"] for t in p.reg.list(project)]
    # перевёрнут 03.10.26 по документу 14 (решение владельца, письмо 34): человек не из «Команды», названный
    # фамилией и именем, заводится «не подтверждён», задача на него, оператору — карточка на подтверждение
    assert any("регламент" in t for t in tasks) and any("браку" in t for t in tasks) and rep.units_tasks == 2
    assert [c for c in p.cards.list(project) if c["kind"] == "confirm_person"]
    # через шлюз, а не напрямую (в ERP заводилось в реестр без проверки): новый человек — «не подтверждён»
    assert store.q("SELECT confirmed FROM people WHERE full_name='Кузнецов Олег'")[0]["confirmed"] == 0


class BrokenSecondRun(MockLLM):
    runs = 0

    def complete(self, system, user, **kw):
        if kw.get("purpose") == "units" and BrokenSecondRun.runs >= 1:
            return LLMResult("не JSON", "m")
        if kw.get("purpose") == "verify":          # конец прогона
            BrokenSecondRun.runs += 1
        return super().complete(system, user, **kw)


def test_failed_chunk_keeps_previous_units(store, project, make_pipe):
    BrokenSecondRun.runs = 0
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe(gen=BrokenSecondRun())
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    p.run(project, mid)
    before = len(_units(store, mid))
    p.run(project, mid)                           # все куски единиц «сломаны»
    assert before >= 4 and len(_units(store, mid)) == before


def test_close_by_voice_next_meeting(store, project, make_pipe):
    m1, m2 = _meeting(store, project, "2026-10-01"), _meeting(store, project, "2026-10-02")
    p = make_pipe()
    p.ingest(project, m1, "a 01.10.2026.txt", MEET1.encode())
    p.run(project, m1)
    p.ingest(project, m2, "b 02.10.2026.txt", MEET2.encode())
    rep = p.run(project, m2)
    q = next(u for u in _units(store, m1) if u["kind"] == "open_question")
    assert rep.units_closed >= 1 and q["status"] == "closed" and "диспетчер" in q["closed_quote"]


@pytest.mark.parametrize("enabled,expect", [(False, "open"), (True, "closed")])
def test_same_meeting_closing_only_when_theme_enables(enabled, expect):
    """Перевёрнут 03.10.26: раньше закрытие внутри своей встречи было всегда.
    ERP отложил его до замера (закрытие по голосу почти на уровне случайного)
    — во framework оно по ключу темы, по умолчанию выключено."""
    text = ("[00:00:01] А: Кто согласует бюджет на закупку профиля?\n[00:01:00] Б: Обсудили и решили: бюджет на закупку "
            "профиля согласует финансовый отдел.\n")
    from meetflow.core.store import Store
    from meetflow.connectors.registry import default_registry
    from meetflow.core.pipeline import MeetingPipeline
    s = Store()
    pid = s.insert("projects", name="P", theme="erp_rollout")
    mid = s.insert("meetings", project_id=pid, date="2026-10-01")
    th = load_theme("erp_rollout")
    th.data["units"]["close_same_meeting"] = enabled
    p = MeetingPipeline(th, s, default_registry(), MockLLM(), MockLLM())
    p.ingest(pid, mid, "t 01.10.2026.txt", text.encode())
    p.run(pid, mid)
    q = [u for u in s.q("SELECT * FROM units WHERE kind='open_question'")]
    assert q and q[0]["status"] == expect


class ClosePanels(MockLLM):
    """Модель «закрывает» решение про панели фразой на строке 2."""
    def _units_close(self, system, data):
        import re
        refs = re.findall(r"^(U\d+): \[Решение\][^\n]*панел", system, re.M | re.I)
        return {"closed": [{"unit": r, "lines": [2], "how": "закрыт", "answer": "x"} for r in refs]}


@pytest.mark.parametrize("phrase,closed", [
    ("Подтвердили: панели принимаем на складе вместе с производством, всё в силе.", False),
    ("Решили иначе: панели теперь принимает только склад, без производства.", True)])
def test_confirmation_does_not_close_decision(store, project, make_pipe, phrase, closed):
    m1, m2 = _meeting(store, project, "2026-10-01"), _meeting(store, project, "2026-10-02")
    make_pipe().ingest(project, m1, "a 01.10.2026.txt", MEET1.encode())
    make_pipe().run(project, m1)
    p = make_pipe(gen=ClosePanels())
    p.ingest(project, m2, "b 02.10.2026.txt", f"[00:00:05] Игнатов Иван: Продолжаем.\n[00:01:00] Игнатов Иван: {phrase}\n".encode())
    p.run(project, m2)
    d = next(u for u in _units(store, m1) if u["kind"] == "decision")
    assert (d["status"] == "closed") is closed


class TwoForOne(MockLLM):
    def _units_close(self, system, data):
        import re
        refs = re.findall(r"^([UN]\d+):", system, re.M)
        return {"closed": [{"unit": r, "lines": [2], "how": "закрыт", "answer": "x"} for r in refs]}


def test_one_phrase_closes_one_unit(store, project, make_pipe):
    m1, m2 = _meeting(store, project, "2026-10-01"), _meeting(store, project, "2026-10-02")
    make_pipe().ingest(project, m1, "a 01.10.2026.txt", MEET1.encode())
    make_pipe().run(project, m1)
    p = make_pipe(gen=TwoForOne())
    p.ingest(project, m2, "b 02.10.2026.txt", MEET2.encode())
    assert p.run(project, m2).units_closed == 1


@pytest.mark.parametrize("phrase,unresolved", [("Решили: создаёт диспетчер.", False), ("Давайте подумаем, кто создаёт?", True),
                                               ("Если согласуют, решим позже.", True), ("Надо бы обсудить это.", True)])
def test_not_resolved(phrase, unresolved):
    from meetflow.core.negation import NegationRule
    assert un.not_resolved(phrase, NegationRule()) is unresolved


def test_effective_task_and_date():
    q = {"status": "open", "kind": "open_question", "task_id": 7, "planned_date": None}
    assert un.effective(q, {7: "done"})[0] == "closed"
    d = {"status": "active", "kind": "decision", "task_id": None, "planned_date": "2026-09-01"}
    assert un.effective(d, {}, date(2026, 10, 3)) == ("closed", "дата прошла 2026-09-01")


def test_event_date_plausibility():
    assert un._event_date("10.10.2026", "decision", date(2026, 10, 1)) == "2026-10-10"
    assert un._event_date("10.10.2020", "decision", date(2026, 10, 1)) is None     # раньше встречи — ошибка модели
    assert un._event_date("10.10.2026", "open_question", date(2026, 10, 1)) is None


def test_units_off_by_default_theme(store, project, theme):
    from meetflow.connectors.registry import default_registry
    from meetflow.core.pipeline import MeetingPipeline
    p = MeetingPipeline(load_theme("_default"), store, default_registry(), MockLLM(), MockLLM())
    mid = _meeting(store, project, "2026-10-01")
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    assert p.run(project, mid).units_added == 0 and _units(store, mid) == []


def test_units_budget_out_keeps_protocol(store, project, make_pipe):
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe()
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    rep = p.run(project, mid, BudgetLimits(max_calls=2, verify_reserve=0))
    assert rep.protocol_saved and "Единицы встречи не собраны" in rep.detail


def test_rerun_keeps_human_removed(store, project, make_pipe):
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe()
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    p.run(project, mid)
    u = _units(store, mid)[0]
    un.remove(store, u["id"], "оператор")
    p.run(project, mid)
    assert store.get("units", u["id"])["status"] == "removed"
    assert sum(1 for x in _units(store, mid) if x["line_from"] == u["line_from"]) == 1


# ------------------------------------------------------------------ Дорожная карта
def test_roadmap_from_registry_and_units(store, project, make_pipe):
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe()
    done = p.reg.add(project, "Утвердить структуру складов с ордерной схемой", "Игнатов Иван", date_set="2026-08-01")
    from meetflow.core.types import TaskStatus
    p.reg.set_status(done, TaskStatus.DONE, "web_form")
    p.reg.add(project, "Подготовить ресурсную спецификацию на шкаф", "Петрова Анастасия", date_set="2026-08-01")
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    p.run(project, mid)
    store._conn.execute("UPDATE task_history SET at='2026-08-01T10:00:00' WHERE task_id != ?", (done,))  # движения не было
    data = rm.build(store, load_theme("erp_rollout"), project, date(2026, 10, 3))
    md = rm.to_markdown(data, load_theme("erp_rollout"))
    blocks = {b["title"]: {pp["key"]: [i["text"] for i in pp["items"]] for pp in b["parts"]} for b in data["blocks"]}
    assert "Утвердить структуру складов с ордерной схемой" in blocks["Склады и схемы обеспечения"]["done"]
    assert any("панели" in t for t in blocks["Склады и схемы обеспечения"]["active"])   # решение — «Действует», не «Сделано»
    assert all("Решили" not in t for b in blocks.values() for t in b.get("done", []))
    assert "## Открыто давно, без движения" in md and "ресурсную спецификацию" in md.split("без движения")[1]
    assert md.startswith("# Дорожная карта")


def test_roadmap_limit_and_dedup(store, project):
    from meetflow.core.registry import TaskRegistry
    reg = TaskRegistry(store)
    for i in range(8):
        reg.add(project, f"Настроить отчёт номер {i} для бухгалтерии", None)
    data = rm.build(store, load_theme("erp_rollout"), project, date(2026, 10, 3))
    part = data["blocks"][0]["parts"][0]
    assert len(part["items"]) == 5 and part["more"] == 3          # 8 разных задач не склеены


def test_distinct_unit_phrasings_not_merged():
    a = un.Extracted("decision", "Спецификация на шкаф согласована", [1], "q", 0, 0, None, None, None)
    b = un.Extracted("decision", "Спецификация на стол согласована", [5], "q", 4, 4, None, None, None)
    assert len(un.merge([a, b])) == 2


# Пары с известным ответом — мера похожести проверяется на них до правки
# (вывод ERP 03.10.26). Замер 03.10.26: Жаккар ≥ 0,6 ошибался на обоих
# «двух отчётах одного» (0,60 и 0,67), «отчёт 1 / 2» (0,67) и дубле в других
# падежах (0,33) — и по основам, и по словам от трёх букв.
@pytest.mark.parametrize("a,b,same", [
    ("Кто создаёт потребность на позиции с долгим сроком",
     "Не решено, кто создаёт потребность на позиции с долгим сроком поставки", True),
    ("Согласовать график поставки профиля", "Согласовали график поставок профиля", True),
    ("Спецификация на шкаф согласована", "Спецификация на стол согласована", False),
    ("Подготовить отчёт номер 1 по складу", "Подготовить отчёт номер 2 по складу", False),
    ("Игнатов подготовит отчёт по браку", "Игнатов подготовит отчёт по отгрузкам", False),
    ("Петрова обновит регламент приёмки на складе", "Петрова обновит регламент отгрузки на складе", False),
    ("Документы передаём только через документооборот", "Бумаги отправляем исключительно в СЭД", False),  # цена
    ("Решили", "Решили принимать панели на складе", False),
])
def test_merge_known_pairs(a, b, same):
    assert un.same_point(a, b) is same


def test_roadmap_empty():
    from meetflow.core.store import Store
    s = Store()
    pid = s.insert("projects", name="P", theme="x")
    assert "Пока пусто" in rm.to_markdown(rm.build(s, load_theme("_default"), pid), load_theme("_default"))


# ------------------------------------------------------------------ поиск
@pytest.fixture
def filled(store, project, make_pipe):
    mid = _meeting(store, project, "2026-10-01")
    p = make_pipe()
    p.reg.add(project, "Проверить упаковки готовой продукции", "Назарова Ольга")
    p.reg.add(project, "Обсудить, который склад брать", "Игнатов Иван")
    p.ingest(project, mid, "t 01.10.2026.txt", MEET1.encode())
    p.run(project, mid)
    return project


@pytest.mark.parametrize("q,expect", [("упаковка", 1), ("назаров", 1), ("кот", 0), ("ДОКУМЕНТООБОРОТ", 1),
                                      ("принимают", 1), ("склада", 1), ("складовщик", 0)])
def test_search_word_forms_not_substrings(store, filled, q, expect):
    r = sr.search(store, filled, q)
    hits = [x for x in r["results"] if x["type"] in ("task", "unit", "source", "protocol")]
    assert (len(hits) > 0) == bool(expect)


def test_search_dates_and_problems(store, filled):
    assert any(x["type"] == "protocol" for x in sr.search(store, filled, "01.10.2026")["results"])
    assert "не бывает" in sr.search(store, filled, "31.02.26")["problem"]
    assert "свой в каждой таблице" in sr.search(store, filled, "№5")["problem"]
    assert "Допишите" in sr.search(store, filled, "было ли упомянуто")["problem"]
    assert sr.search(store, filled, "ё")["problem"]


def test_search_raw_speech_only_when_theme_allows(store, filled):
    """Перевёрнут 03.10.26: раньше расшифровки искались всегда. Поиск по
    сырой речи — решение о доступе (ERP: владелец отклонил), по умолчанию нет."""
    off = sr.search(store, filled, "панели производством")["results"]
    assert "source" not in {x["type"] for x in off} and "unit" in {x["type"] for x in off}
    on = sr.search(store, filled, "панели производством", raw_speech=True)["results"]
    assert {"source", "unit"} <= {x["type"] for x in on}
    assert on[0]["meeting_date"] == "2026-10-01"


def test_search_unit_quote_is_raw_speech(store, filled):
    store._conn.execute("UPDATE units SET text='Порядок приёмки', quote='сказал дословно: зелёный слон'")
    assert not sr.search(store, filled, "слон")["results"]
    assert sr.search(store, filled, "слон", raw_speech=True)["results"]


def test_same_lexeme_rules():
    from meetflow.core.text import same_lexeme, same_word
    assert same_lexeme("согласовать", "согласовали") and same_lexeme("назаров", "назаровой")
    assert same_lexeme("кот", "кота") and not same_lexeme("кот", "который") and not same_lexeme("том", "томат")
    assert not same_lexeme("1", "10") and not same_lexeme("делать", "сделать")
    assert same_lexeme("алексей", "алексейко") and not same_word("алексей", "алексейко")   # имена — только same_word


def test_raw_speech_question_in_todo():
    assert any("search.raw_speech_decision" in t for t in load_theme("_default").todo())
    assert not any("raw_speech" in t for t in load_theme("erp_rollout").todo())   # решено владельцем ERP


def test_search_snippet_hides_internal_ids(store, filled):
    store.update("meetings", 1, protocol_md="| № | Задача |\n|---|---|\n| 117 | Секретный склад |\n")
    r = sr.search(store, filled, "секретный склад")["results"]
    assert r and "117" not in r[0]["snippet"]


# ------------------------------------------------------------------ API и экран
@pytest.fixture
def client(tmp_path):
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=False)
    c = TestClient(app, raise_server_exceptions=False)
    H = {"X-User-Role": "project_admin"}
    c.pid = c.post("/api/projects", json={"name": "П"}, headers=H).json()["id"]
    for n in TEAM:
        c.post(f"/api/projects/{c.pid}/people", json={"full_name": n}, headers=H)
    c.mid = c.post(f"/api/projects/{c.pid}/meetings", json={"date": "2026-10-01"}, headers=H).json()["id"]
    c.post(f"/api/meetings/{c.mid}/sources", files={"file": ("t 01.10.2026.txt", MEET1.encode())}, headers=H)
    c.post(f"/api/meetings/{c.mid}/run", headers=H)
    c.H = H
    return c


def test_api_units_remove_return(client):
    units = client.get(f"/api/meetings/{client.mid}/units").json()
    assert units and units[0]["kind_ru"]
    uid = units[0]["id"]
    assert client.post(f"/api/units/{uid}/remove").status_code == 403
    assert client.post(f"/api/units/{uid}/remove", headers=client.H).json()["status"] == "removed"
    assert client.post(f"/api/units/{uid}/return", headers=client.H).json()["status"] in ("open", "active")
    assert "units" in client.get(f"/api/meetings/{client.mid}/protocol").json()


def test_api_roadmap_and_docx(client):
    r = client.get(f"/api/projects/{client.pid}/roadmap").json()
    assert r["markdown"].startswith("# Дорожная карта") and r["data"]["blocks"]
    d = client.get(f"/api/projects/{client.pid}/roadmap.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"


def test_api_search(client):
    r = client.get(f"/api/projects/{client.pid}/search", params={"q": "документооборот"}).json()
    assert r["problem"] is None and r["results"]
    assert client.get(f"/api/projects/{client.pid}/search", params={"q": "№3"}).json()["problem"]
