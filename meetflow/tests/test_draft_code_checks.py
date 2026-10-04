"""Две кодовые проверки черновика — письмо 18 ветки meeting-registry (запись 71
вехи 4). Решение владельца «делать» в Планёрке и ERP; MeetFlow — основа
единого инструмента. Модель эти классы почти не ловит: оценочное слово —
0 из 8 прогонов, факт не из того эпизода — 1 из 8. Тесты написаны до кода.

К17/К18 — настоящая встреча ERP из набора v2 вехи 4: в git MeetFlow не
копируется: путь к suite_v2.json задаёт переменная MEETFLOW_SUITE_V2,
без неё тесты К17/К18 пропускаются."""
import json
import os
from pathlib import Path

import pytest

from meetflow.core.draft_checks import added_judgement, facts_from_other_episode, run_code_checks

SRC = """Курск – провода для четырёх колонн не пришли, осталось около десяти колонн собрать.
Эльдаба – текущее производство: колонны холостые, ждём комплектацию шкафов.
Регламент – задачи по почте мы не принимаем, только через документооборот."""


def test_judgement_word_absent_in_source():
    f = added_judgement("Решили фиксировать случаи отправки задач по почте как нарушение.", SRC)
    assert len(f) == 1 and "нарушени" in f[0]["note"]


def test_judgement_word_present_in_source_is_silent():
    assert added_judgement("Отмечен срыв поставки.", SRC + "\nКурск – срыв поставки проводов.") == []


def test_fact_from_other_episode():
    draft = "**Курск** – текущее производство: колонны холостые, ждём комплектацию шкафов по графику."
    f = facts_from_other_episode(draft, SRC)
    assert len(f) == 1 and "Эльдаба" in f[0]["note"]


def test_fact_in_own_episode_is_silent():
    draft = "**Эльдаба** – текущее производство: колонны холостые, ждём комплектацию шкафов по графику."
    assert facts_from_other_episode(draft, SRC) == []


def test_findings_go_to_review_notes_not_gate(store, project, make_pipe):
    from meetflow.connectors.llm_mock import MockLLM

    class Judging(MockLLM):
        def _protocol(self, system, data):
            out = super()._protocol(system, data)
            k = next(iter(out["sections"]))
            out["sections"][k] = "Решили фиксировать отправку задач по почте как нарушение."
            return out
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=Judging())
    p.ingest(project, mid, "t 01.10.2026.txt", "[00:01:00] Игнатов Иван: Задачи по почте мы не принимаем.\n".encode())
    rep = p.run(project, mid)
    assert rep.protocol_saved                                         # справка, не шлюз
    notes = json.loads(store.get("meetings", mid)["review_notes"])
    assert any(n.get("by") == "код" and "нарушени" in n["issue"] for n in notes)


# набор v2 вехи 4 живёт вне репозитория: путь к suite_v2.json — в переменной окружения
SUITE = Path(os.environ.get("MEETFLOW_SUITE_V2", ""))


def _case(cid):
    if not SUITE.is_file():
        pytest.skip("набор v2 вехи 4 недоступен (MEETFLOW_SUITE_V2)")
    return next(c for c in json.loads(SUITE.read_text(encoding="utf-8"))["cases"] if c["id"] == cid)


def test_k17_code_catches_r4_and_r2():
    c = _case("К17")
    text = " ".join(f["note"] + " " + f["quote"] for f in run_code_checks(c["draft"], c["source"])).lower()
    assert "нарушен" in text, "Р4 — оценочное слово не поймано"
    assert "холост" in text, "Р2 — факт Эльдабы у Курска не пойман"


def test_k18_owner_protocol_is_silent():
    c = _case("К18")
    assert run_code_checks(c["draft"], c["source"]) == []
