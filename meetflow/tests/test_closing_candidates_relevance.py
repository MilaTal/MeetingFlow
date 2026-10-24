"""Решение владельца 03.10.26 (после прогона ERP, этап 6): карточку «проверены первые 60 открытых задач»
убрать — она ничего не даёт оператору. Вместо первых 60 по порядку модели показываются 60 задач, ближе всего
к сказанному на встрече. Тест написан до правки."""
from meetflow.core.types import TaskStatus


def test_relevant_task_beyond_60_can_close_and_no_card(store, project, make_pipe):
    p = make_pipe()
    for i in range(70):
        p.reg.add(project, f"Согласовать спецификацию номер {i} для цеха", "Игнатов Иван", date_set="2026-09-01")
    target = p.reg.add(project, "Подготовить регламент приёмки цистерн", "Игнатов Иван", date_set="2026-09-01")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Игнатов Иван: Регламент приёмки цистерн готов, сделано.\n".encode())
    p.run(project, mid)
    assert store.get("tasks", target)["status"] == TaskStatus.DONE.value      # 71-я по порядку, но о ней говорили
    assert not store.q("SELECT * FROM cards WHERE kind='limit_cut'")          # карточки «первые 60» нет


def test_task_70_of_80_is_in_check():
    """Письмо 42: №70 из 80 открытых, о ней прямо говорили, — попадает в сверку."""
    from meetflow.core.pipeline import MeetingPipeline
    active = [{"id": i, "description": f"Согласовать спецификацию номер {i} для цеха"} for i in range(1, 81)]
    active[69]["description"] = "Подготовить регламент приёмки цистерн"
    c = MeetingPipeline._closing_candidates(active, ["Регламент приёмки цистерн готов, сделано."])
    assert 70 in [x["task_ref"] for x in c]


def test_more_than_60_mentioned_is_one_protocol_line(store, project, make_pipe):
    """Письмо 42: если на встрече названо больше 60 задач, это видно одной строкой в протоколе, не карточкой."""
    p = make_pipe()
    for i in range(65):
        p.reg.add(project, f"Проверить пломбы цистерны номер {i} на станции", "Игнатов Иван", date_set="2026-09-01")
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Игнатов Иван: Пломбы цистерн на станции проверяем по графику.\n".encode())
    p.run(project, mid)
    proto = store.get("meetings", mid)["protocol_md"]
    # перевёрнут 15.10.26 (находка стенда 30, правило владельца 13.10.26): документ чистый — пометка в журнале прогона
    assert "сверк" not in proto.lower()
    assert [r for r in p.journal.records if r.get("run") == mid][-1]["closing_mentioned"] == 65
    assert not store.q("SELECT * FROM cards WHERE kind='limit_cut'")
