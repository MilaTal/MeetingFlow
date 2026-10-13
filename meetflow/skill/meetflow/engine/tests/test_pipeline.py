"""Итерация 1, интеграционные: конвейер целиком на эвристике и на сценарном клиенте модели."""

from meeting_registry.errors import BadModelAnswer, ProviderUnavailable
from meeting_registry.llm import ScriptedClient


def descs(reg):
    return {t["description"]: t for t in reg.all_tasks()}


def test_first_meeting_writes_registry(run, reg, m1):
    res = run(m1)
    assert res["outcome"] == "done"
    tasks = descs(reg)
    assert "Подготовить спецификацию на фильтры" in tasks
    assert tasks["Подготовить спецификацию на фильтры"]["responsible_id"] == "u05"
    assert tasks["Подготовить спецификацию на фильтры"]["due"] == "до пятницы"
    assert tasks["Подготовить график отгрузки"]["responsible_id"] == "u07"   # «я подготовлю» — сам взял
    # цитата лежит в реестре дословно — это и есть опора задачи
    assert "Назаров, подготовьте" in tasks["Подготовить спецификацию на фильтры"]["quote"]
    # тёзки -> карточка, не догадка
    assert any("тёзки" in c["title"] for c in reg.open_cards())
    # вопрос, «вернёмся позже» и «отменять не будем» задачами не стали
    assert not any("счёт" in d or "авианакладн" in d.lower() for d in tasks)


def test_second_meeting_closes_with_quote_and_respects_negation(run, reg, m1, m2):
    run(m1, "2026-10-01")
    res = run(m2, "2026-10-02")
    assert res["outcome"] == "done"
    tasks = descs(reg)
    kp = tasks["Запросить коммерческие предложения у трёх поставщиков"]
    assert kp["status"] == "done" and kp["date_closed"] == "2026-10-02"
    # «пока не подготовил» и «не успел» — не факт выполнения
    assert tasks["Подготовить спецификацию на фильтры"]["status"] == "active"
    assert tasks["Подготовить график отгрузки"]["status"] == "active"
    assert tasks["Посчитать экономику по трём предложениям"]["responsible_id"] == "u08"
    assert "закрыто" not in res["protocol_md"].lower() or "получили" in res["protocol_md"]


def test_same_source_twice_is_idempotent(run, reg, m1):
    run(m1)
    n = len(reg.all_tasks())
    res = run(m1, name="копия.txt")
    assert res["outcome"] == "duplicate"
    assert len(reg.all_tasks()) == n


def test_own_meeting_does_not_close_own_tasks(run, reg):
    text = ("Гаврилов Павел: Назаров, подготовьте отчёт по отгрузкам.\n"
            "Назаров Константин: Отчёт по отгрузкам подготовил уже.\n")
    run(text)
    assert all(t["status"] == "active" for t in reg.all_tasks())


def test_department_goes_to_head_and_headless_to_card(run, reg):
    text = ("Гаврилов Павел: ОСН, запросите счёт у перевозчика.\n"
            "Гаврилов Павел: ОТН, проверьте пломбы на цистернах.\n")
    run(text)
    tasks = descs(reg)
    assert tasks["Запросить счёт у перевозчика"]["responsible_id"] == "u06"
    # перевёрнут 09.10.26: отдел без руководителя — задача заводится без исполнителя, рядом карточка (решение владельца 03.10.26)
    assert [t["responsible_id"] for d, t in tasks.items() if "пломб" in d] == [None]
    assert any("ОТН" in (c["title"] or "") or "Отдел технического" in (c["title"] or "") for c in reg.open_cards())


def test_unknown_person_goes_to_card_not_registry(run, reg):
    run("Гаврилов Павел: Кутузов, подготовьте акт сверки по Титану.\n")
    assert reg.all_tasks() and all(t["responsible_id"] is None for t in reg.all_tasks())  # перевёрнут 09.10.26: задача не теряется — заводится без исполнителя, рядом карточка (решение владельца 03.10.26)
    assert any("Кутузов" in c["title"] for c in reg.open_cards())


def test_scripted_model_line_numbers_and_quote_from_code(run, reg, m1):
    script = {"extract:1/1": {"assignments": [
        {"line": 5, "to": "Назаров", "action": "подготовить спецификацию на фильтры", "due": "до пятницы"},
        {"line": 5, "to": "Ершова", "action": "подготовить спецификацию на фильтры"},     # имени нет в строке
        {"line": 99, "to": "Назаров", "action": "что-то"},                                  # строки нет
        {"line": 3, "to": "Лаптева", "action": "подписать договор"},                       # отчёт, не поручение
    ]}}
    res = run(m1, client=ScriptedClient(script))
    tasks = descs(reg)
    assert list(tasks) == ["Подготовить спецификацию на фильтры"]
    assert tasks["Подготовить спецификацию на фильтры"]["quote"].startswith("Гаврилов Павел: Назаров")
    assert res["held"] >= 2


def test_bad_json_chunk_goes_to_card_others_continue(run, reg, m1):
    res = run(m1, client=ScriptedClient({"extract:1/1": BadModelAnswer("не JSON")}))
    assert res["outcome"] == "done"
    assert any(c["kind"] == "chunk_failed" for c in reg.open_cards())


def test_provider_down_falls_back_to_rules_visibly(run, reg, m1):
    res = run(m1, client=ScriptedClient({"extract:1/1": ProviderUnavailable("connection refused")}))
    assert res["outcome"] == "degraded"
    assert "без языковой модели" not in res["protocol_md"]   # документ чистый (владелец 13.10.26), факт — в карточке
    assert len(reg.all_tasks()) >= 2
    assert any(c["kind"] == "degraded" for c in reg.open_cards())


def test_agent_cannot_assign_person_whose_name_was_not_said(run, reg, m1):
    script = {"extract:1/1": {"assignments": [{"line": 9, "to": "Марина", "action": "проверить остатки на складе"}]},
              "resolve": {"tool": "assign", "args": {"person_id": "u05"}}}   # Назаров вместо «Марины»
    run(m1, client=ScriptedClient(script))
    assert reg.all_tasks() and all(t["responsible_id"] is None for t in reg.all_tasks())  # перевёрнут 09.10.26: задача не теряется — заводится без исполнителя, рядом карточка (решение владельца 03.10.26)
    assert any("не совпадающего" in c["title"] for c in reg.open_cards())


def test_agent_tool_choice_is_visible_in_run_log(run, reg, m1):
    res = run(m1)
    steps = [s["name"] for s in reg.run_steps(res["run_id"])]
    assert "resolve:find_person" in steps and "resolve:participants" in steps and "resolve:to_operator" in steps


def test_run_log_has_steps_tokens_outcome(run, reg, m1):
    res = run(m1)
    r = reg.runs()[-1]
    assert r["outcome"] == "done" and r["calls"] == res["calls"] and r["tokens_in"] > 0
    assert len(reg.run_steps(r["id"])) >= 5
