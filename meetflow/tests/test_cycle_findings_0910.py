"""Находки прогона «новая тематика по скиллу meetflow», цикл 1 (09.10.26, тематика «Стройплощадка»).

D1. Исполнитель сверялся по имени, которое написала модель: прозвучало «Ирина» при двух Иринах — модель вписала
    «Ковалёва Ирина», и задача ушла ей; «Лебеде» без имени — «Лебедева Ольга»; «ПТО» — без руководителя.
    Правило скилла: каждое предложение модели сверяется с источником этой встречи, тёзка — всегда карточкой.
D2. Срок «до 7 октября» прозвучал, а модель вернула «2026-10-07» — проверка искала цифры в тексте и срок теряла.
D3. «Заказать бетон М350» не заведена: «заказать» и «закажите» — разные основы, цитата не нашлась.
D4. Единицы встречи заводили карточку «Задача из записи не заведена» на задачу, которую этот же прогон уже завёл."""
import pytest

from meetflow.core import morph
from meetflow.core.gates import TaskGate
from meetflow.core.people import Team
from meetflow.core.pipeline import noise_duplicate
from meetflow.core.types import Person, SourceDoc, SourceKind, TaskDraft

TEAM = Team([Person("Захаров Виктор"), Person("Полякова Ирина", department="ПТО"), Person("Ковалёва Ирина"),
             Person("Ершов Александр", department="Снабжение"), Person("Лебедева Ольга"), Person("Мухин Сергей")],
            {"ира": ["ирина"]}, {"пто": "Полякова Ирина"})


def gate(desc, model_assignee, line):
    src = SourceDoc("t", SourceKind.TRANSCRIPT, f"[00:00:10] Захаров Виктор: Начинаем.\n[00:02:00] {line}")
    return TaskGate(TEAM).check(TaskDraft(desc, model_assignee, quote=line, line_no=1), src)


def test_d1_namesake_said_as_first_name_is_a_card_even_if_model_wrote_full_name():
    g = gate("Подготовить акт скрытых работ", "Ковалёва Ирина", "Захаров Виктор: Ирина, подготовьте акт скрытых работ по арматуре.")
    assert g.accepted and g.assignee is None
    assert {p.full_name for p in g.pending["candidates"]} == {"Полякова Ирина", "Ковалёва Ирина"}


def test_d1_distorted_surname_said_without_name_is_a_candidate():
    g = gate("Проверить складирование арматуры", "Лебедева Ольга", "Захаров Виктор: Лебеде, проверьте складирование арматуры.")
    assert g.accepted and g.assignee is None
    assert [p.full_name for p in g.pending["candidates"]] == ["Лебедева Ольга"]


def test_d1_department_said_goes_to_head_whatever_the_model_wrote():
    for model_says in ("Полякова Ирина", "производственно-технический отдел", "Отдел ПТО"):
        g = gate("Обновить график производства работ", model_says, "Захаров Виктор: ПТО, обновите график производства работ.")
        assert g.accepted and g.assignee and g.assignee.full_name == "Полякова Ирина", model_says


def test_d1_said_name_still_assigns_and_self_take_works():
    g = gate("Подготовить опалубку", "Лебедева Ольга", "Захаров Виктор: Лебедева Ольга, подготовьте опалубку на четвёртый этаж.")
    assert g.assignee and g.assignee.full_name == "Лебедева Ольга"
    g = gate("Проверить башенный кран", "Мухин Сергей", "Захаров Виктор: Мухин, проверьте башенный кран.")
    assert g.assignee and g.assignee.full_name == "Мухин Сергей"
    g = gate("Проверить опалубку", "Лебедева Ольга", "Лебедева Ольга: Беру на себя проверку опалубки.")
    assert g.assignee and g.assignee.full_name == "Лебедева Ольга"


def test_d1_model_name_not_said_at_all_is_not_assigned_silently():
    g = gate("Проверить башенный кран", "Мухин Сергей", "Захаров Виктор: Проверьте башенный кран до пятницы.")
    assert g.assignee is None


def test_d2_numeric_due_is_accepted_when_day_and_month_were_said():
    w = "Захаров Виктор: Лебедева Ольга, подготовьте опалубку на четвёртый этаж до 7 октября."
    assert morph.supported_due("2026-10-07", w) == "2026-10-07"   # без даты встречи — как дала модель
    assert morph.supported_due("07.10.2026", w) == "07.10.2026"
    assert morph.supported_due("2026-10-08", w) is None          # другой день — не прозвучал
    assert morph.supported_due("2030-12-31", w) is None          # выдуманный срок по-прежнему отбрасывается
    assert morph.supported_due("до 7 октября", w) == "до 7 октября"


@pytest.mark.skipif(morph._MORPH is None, reason="нужен pymorphy3")
def test_d3_imperative_and_infinitive_are_the_same_words_for_the_quote():
    # как в прогоне: модель дала номер строки и описание, своей цитаты нет — покрытие считается по описанию
    line = "Захаров Виктор: Ершов Александр, закажите бетон М350 до 12 октября."
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:00:10] Захаров Виктор: Начинаем." + chr(10) + f"[00:03:40] {line}")
    g = TaskGate(TEAM).check(TaskDraft("Заказать бетон М350", "Ершов Александр", quote="", line_no=1), src)
    assert g.accepted and g.quote and "no_verbatim_quote" not in g.reasons


def test_d4_unit_duplicate_of_a_task_added_by_this_run_is_not_a_card():
    added = ["Подготовить опалубку на четвёртый этаж до 7 октября", "Заказать бетон М300 на 9 октября"]
    assert noise_duplicate(["duplicate"], "Подготовить опалубку на четвёртый этаж", added)
    assert not noise_duplicate(["duplicate"], "Подготовить отчёт по технадзору", added)        # дубль чего-то старого — карточка
    assert not noise_duplicate(["duplicate", "no_assignee"], "Подготовить опалубку на четвёртый этаж", added)


# --- повтор цикла 1 на исправленном коде: год срока и адресат без ответа модели ------------------------------


def test_d2b_year_not_said_comes_from_the_meeting_date_not_from_the_model():
    w = "Захаров Виктор: Лебедева Ольга, подготовьте опалубку до 7 октября."
    assert morph.supported_due("2023-10-07", w, meeting_date="2026-10-02") == "07.10.2026"
    assert morph.supported_due("12.10", "Захаров Виктор: Ершов, закажите бетон до 12 октября.", meeting_date="2026-10-09") == "12.10.2026"
    assert morph.supported_due("2026-01-15", "Сдать акт до 15 января.", meeting_date="2026-12-20") == "15.01.2027"
    assert morph.supported_due("2028-10-07", "Сдать до 7 октября 2028 года.", meeting_date="2026-10-02") == "07.10.2028"


def test_d5_addressee_in_the_quote_when_the_model_gave_none():
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:05:30] Захаров Виктор: ПТО, обновите график производства работ.")
    g = TaskGate(TEAM).check(TaskDraft("Обновить график производства работ", None, line_no=0), src)
    assert g.assignee and g.assignee.full_name == "Полякова Ирина"
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:05:30] Захаров Виктор: Хорошо, обновите график производства работ.")
    g = TaskGate(TEAM).check(TaskDraft("Обновить график производства работ", None, line_no=0), src)
    assert g.assignee is None and g.pending is None          # исполнитель не назван — без карточки (решение 03.10.26)


# --- цикл 2 (тематика «Склад»): словесный срок и ложный дубль со сроком в тексте единицы -----------------------


def test_d6_word_due_is_normalized_to_owner_format():
    w = "Котов Максим: Белов, к 20 октября закажите новые паллеты."
    assert morph.supported_due("20 октября", w, meeting_date="2026-10-12") == "20.10.2026"
    assert morph.supported_due("до 20 октября", w, meeting_date="2026-10-12") == "20.10.2026"
    assert morph.supported_due("20 октября", w) == "20 октября"          # без даты встречи — как дала модель
    assert morph.supported_due("к пятнице", "Сделайте к пятнице.", meeting_date="2026-10-12") == "к пятнице"


def test_d7_unit_with_due_in_text_is_still_the_same_task():
    assert noise_duplicate(["duplicate"], "Заказать новые паллеты к 20.10", ["Заказать новые паллеты"])
    assert not noise_duplicate(["duplicate"], "Подготовить акт номер 1", ["Подготовить акт номер 0"])
