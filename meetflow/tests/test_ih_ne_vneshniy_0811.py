"""«Их» — не признак внешнего человека (08.11.2026, остаток аудита ответственного).

Местоимение «их» стояло в списке признаков «это не он» рядом с «подрядчик/заказчик/поставщик». Из-за него ясное
поручение с известным ФИО превращалось в карточку «тот же или новый»: «Их отчёт по складу нужно свести» — карточка,
хотя исполнитель назван. Настоящие признаки внешнего человека не тронуты.
"""
from meetflow.core.people import Team
from meetflow.core.types import Person

ЛЮДИ = [Person("Петрова Анастасия"), Person("Игнатов Иван")]


def test_их_не_делает_человека_внешним():
    m = Team(ЛЮДИ).find("Петрова", context="Их отчёт по складу нужно свести к пятнице")
    assert m.person is not None and m.person.full_name == "Петрова Анастасия"
    assert m.marks == [] and m.via != "same_or_new"


def test_подрядчик_заказчик_поставщик_по_прежнему_признаки():
    for слово in ("подрядчика", "заказчика", "поставщика"):
        m = Team(ЛЮДИ).find("Петрова", context=f"Отчёт {слово} по складу нужно свести")
        assert m.via == "same_or_new" and m.marks == [слово], (слово, m.via, m.marks)


def test_в_сборке_ясное_фио_без_карточки(store, project, meeting, theme, tmp_path):
    """Та же проверка через сборку: цитата с «Их …», исполнитель из «Команды» — задача заведена на него, карточки
    «тот же или новый» нет."""
    import json

    from meetflow.connectors.llm_mock import MockLLM
    from meetflow.connectors.registry import default_registry
    from meetflow.core.pipeline import MeetingPipeline

    class Модель(MockLLM):
        def _extract(self, data):
            return {"tasks": [{"description": "Свести отчёт по складу", "assignee": "Петрова Анастасия",
                               "line": 2, "due_date": "к пятнице"}]}

        def _units(self, data):
            return {"items": []}

    текст = ("[00:01:00] Игнатов Иван: Начинаем по складу, повестка обычная.\n"
             "[00:02:00] Игнатов Иван: Их отчёт по складу, Петрова Анастасия, свести нужно к пятнице.\n")
    p = MeetingPipeline(theme, store, default_registry(), Модель(), MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=текст,
                 digest="их" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    p.run(project, meeting)
    задачи = store.q("SELECT assignee FROM tasks WHERE source_meeting_id=?", (meeting,))
    assert задачи and задачи[0]["assignee"] == "Петрова Анастасия"
    assert not store.q("SELECT id FROM cards WHERE meeting_id=? AND title LIKE 'Тот же или новый%'", (meeting,))
