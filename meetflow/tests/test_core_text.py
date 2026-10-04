"""Ядро: текст, правило отрицаний, даты, вид источника, люди."""
from datetime import date

import pytest

from meetflow.core.classify import classify_text, kind_by_extension
from meetflow.core.dates import dates_in_name, single_date
from meetflow.core.negation import NegationRule
from meetflow.core.people import Team
from meetflow.core.text import same_word, sanitize, stems
from meetflow.core.types import Person, SourceKind

TODAY = date(2026, 10, 3)


def test_sanitize_removes_invisible_and_control():
    assert sanitize("a​b\x07c‮d") == "abcd"


@pytest.mark.parametrize("a,b,ok", [
    ("Баженовой", "Баженова", True), ("Мария", "Марина", False), ("Алексей", "Алексейко", False),
    ("Петровой", "Петрова", True), ("Игнатову", "Игнатов", True), ("отв", "ответ", False)])
def test_same_word(a, b, ok):
    assert same_word(a, b) is ok


def test_stems_drop_stop_words():
    assert "и" not in stems("склад и регламент")


NEG = NegationRule()


@pytest.mark.parametrize("phrase,fact", [
    ("Выгрузку отправил, сделано.", True),
    ("Отчёт готов.", True),
    ("Отчёт не готов.", False),
    ("Отчёт готов?", False),
    ("Если согласуют, будет сделано.", False),
    ("Планируем закрыть к пятнице, будет готово.", False),
    ("Частично выполнено.", False),
    ("Почти сделали.", False),
    ("Прошу сделать до пятницы.", False),
    ("Задачу обсудили.", False),               # нет слова выполнения
    ("Прошу прощения, отчёт отправил, сделано.", True),  # «прошу прощения» — не поручение
    ("Это уже не актуально, выполнено.", False),
])
def test_negation_rule(phrase, fact):
    assert NEG.check(phrase).states_fact is fact


@pytest.mark.parametrize("name,expect", [
    ("Транскрибация 30.09.2026.txt", date(2026, 9, 30)),
    ("2026_09_05 планёрка.docx", date(2026, 9, 5)),          # не 9 мая
    ("20260930.mp4", date(2026, 9, 30)),
    ("Планёрка 26.09.26.docx", date(2026, 9, 26)),
    ("встреча 10.09.2026 11.05.mp4", date(2026, 9, 10)),     # время — не дата
    ("протокол 30 сентября 2026.docx", date(2026, 9, 30)),
])
def test_single_date(name, expect):
    assert single_date(name, TODAY) == expect


@pytest.mark.parametrize("name", ["запись.mp4", "123456.txt", "31.02.2026.txt", "01.01.2030.txt",
                                  "с 01.09.2026 по 05.09.2026.docx"])
def test_no_single_date(name):
    assert single_date(name, TODAY) is None


def test_dates_two_found():
    assert len(dates_in_name("с 01.09.2026 по 05.09.2026", TODAY)) == 2


def test_classify_transcript():
    txt = "\n".join(f"[00:0{i}:00] Игнатов Иван: реплика {i}" for i in range(6))
    assert classify_text(txt).kind == SourceKind.TRANSCRIPT


def test_classify_notes_by_markers():
    txt = "Протокол встречи\nПовестка: склад\nРешили: регламент\nОтветственный: Петрова, срок 10.10"
    assert classify_text(txt, ["протокол", "повестка", "решили", "ответственный"]).kind == SourceKind.NOTES


def test_classify_own_output_flag():
    txt = "Откуда: собран вчера\nНовые задачи\n| 1 | x |"
    assert classify_text(txt, [], ["Откуда: собран", "Новые задачи"]).own_output


def test_kind_by_extension():
    assert kind_by_extension("a.MP4") == SourceKind.RECORDING
    assert kind_by_extension("b.jpg") == SourceKind.IMAGE
    assert kind_by_extension("c.docx") is None


TEAM = Team([Person("Петрова Анастасия"), Person("Петров Антон"), Person("Игнатов Иван"),
             Person("Алексейко Вероника"), Person("Новый Человек", confirmed=False)],
            diminutives={"настя": ["анастасия"]}, department_heads={"осн": "Игнатов Иван"})


def test_people_full_match_cases():
    assert TEAM.find("Петровой Анастасии").person.full_name == "Петрова Анастасия"
    assert TEAM.find("Настя Петрова").person.full_name == "Петрова Анастасия"


def test_people_partial_is_ambiguous():
    m = TEAM.find("Петров")
    assert m.person is None and len(m.candidates) >= 1


def test_people_alexey_not_same_stem_surname():
    assert TEAM.find("Алексей Алексейко").person is None


def test_people_unconfirmed_not_matched():
    assert TEAM.find("Новый Человек").person is None


def test_department_head():
    m = TEAM.find("отдел ОСН")
    assert m.person.full_name == "Игнатов Иван" and m.via == "department_head"
