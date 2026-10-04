"""Итерация 1, модульные: правило отрицаний, сверка людей, приём источника, текстовые примитивы."""

import pytest

from meeting_registry import intake, negation
from meeting_registry.errors import SourceRejected
from meeting_registry.text import coverage, numbered_lines


@pytest.mark.parametrize("phrase,fact", [
    ("Договор подписан, акт отправили заказчику.", "done"),
    ("Коммерческие предложения получили.", "done"),
    ("Отменять не будем, работаем.", None),          # повод правила 21.09.26
    ("Спецификацию пока не подготовил.", None),
    ("А счёт пришёл?", None),
    ("Если подпишут, отгрузим.", None),
    ("Отгрузим завтра.", None),
    ("Готово на 90 процентов.", None),
    ("Отправьте, пожалуйста, акт.", None),
    ("Эта задача больше не актуальна.", "dropped"),
    ("Снимать задачу не будем.", None),
    ("Вернёмся позже к авианакладной.", None),
])
def test_negation_rule(phrase, fact):
    assert negation.classify(phrase)["fact"] == fact


@pytest.mark.parametrize("phrase,ok", [
    ("Назаров, подготовьте спецификацию.", True),
    ("По авианакладной вернёмся позже.", False),
    ("А инвойс уже пришёл?", False),
    ("Хорошо бы Иван посмотрел.", False),
    ("Не надо готовить отчёт.", False),
    ("Посмотрите, пожалуйста, договор?", True),
])
def test_assignment_shape(phrase, ok):
    assert negation.is_assignment_shape(phrase)["ok"] is ok


@pytest.mark.parametrize("heard,status,ids", [
    ("Назаров", "exact", ["u05"]),
    ("Назарову", "exact", ["u05"]),          # падеж
    ("Костя", "exact", ["u05"]),             # краткая форма, тёзок нет
    ("Марина", "ambiguous", ["u03", "u04"]), # тёзки — карточка
    ("Чистяка", "exact|fixed", ["u03"]),      # искажение распознавания, правило 02.10.26: подставлять молча
    ("Ершова", "exact", ["u06"]),
    ("ОСН", "department", ["u06"]),           # отдел -> руководитель
    ("ОТН", "ambiguous", []),                # отдел без руководителя — карточка
    ("Кутузов", "unknown", []),              # не из «Команды»
    ("", "unknown", []),
])
def test_roster(team, heard, status, ids):
    r = team.resolve(heard)
    assert r["status"] in status.split("|")
    assert sorted(r["candidates"]) == sorted(ids)


def test_names_compatible_blocks_substitution(team):
    assert team.names_compatible("Марина", "u03")
    assert not team.names_compatible("Марина", "u05")


@pytest.mark.parametrize("name,expected", [
    ("Планёрка 2026_09_05.txt", "2026-09-05"),        # не 9 мая (Планёрка, 30.09.26)
    ("встреча 02.10.2026.docx", "2026-10-02"),
    ("Транскрибация 17.09.26.txt", "2026-09-17"),
    ("заметки без даты.txt", None),
    ("02.10.2026 и 03.10.2026.txt", None),             # две даты — не угадываем
])
def test_date_from_name(name, expected):
    assert intake.date_from_name(name) == expected


@pytest.mark.parametrize("text,code", [
    ("", "empty"),
    ("   \n\n  ", "empty"),
    ("!!! ??? ... ---- ====", "empty"),
    ("ааа ааа ааа ааа ааа ааа ааа ааа", "garbage"),
    ("Рецепт борща: свёкла, капуста, картофель, морковь, лук, томат, соль, перец, лавровый лист.", "not_meeting"),
])
def test_intake_rejects(text, code):
    with pytest.raises(SourceRejected) as e:
        intake.check(text)
    assert e.value.code == code


def test_intake_rejects_too_large():
    with pytest.raises(SourceRejected) as e:
        intake.check("Назаров, подготовьте отчёт. " * 20000)
    assert e.value.code == "too_large"


def test_decode_variants():
    t = "Гаврилов Павел: Назаров, подготовьте отчёт по проекту до пятницы."
    assert intake.decode(t.encode("utf-8")) == t
    assert intake.decode(t.encode("cp1251")) == t
    assert intake.decode(t.encode("utf-16")) == t
    with pytest.raises(SourceRejected):
        intake.decode(b"\x00\x01\x02" * 100)


def test_invisible_chars_removed():
    lines = numbered_lines("Гаврилов: Назаров,‮ подготовьте​ отчёт.")
    assert "‮" not in lines[0]["text"] and "​" not in lines[0]["text"]


def test_lines_split_into_sentences():
    lines = numbered_lines("Гаврилов Павел: Хорошо. Назаров, подготовьте спецификацию.")
    assert [l["text"] for l in lines] == ["Хорошо.", "Назаров, подготовьте спецификацию."]
    assert all(l["speaker"] == "Гаврилов Павел" for l in lines)


def test_coverage_instrument_on_known_answers():
    # прибор проверяется на заведомом ответе (письмо Планёрки 13: similarity(a, a) давала 0,72)
    assert coverage("подготовить спецификацию", "подготовить спецификацию") == 1.0
    assert coverage("", "что угодно") == 0.0
    assert coverage("подготовить спецификацию", "купить хлеб") == 0.0
    assert coverage("подготовить спецификацию на фильтры", "Назаров, подготовьте спецификацию") >= 0.5
