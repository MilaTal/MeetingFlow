# -*- coding: utf-8 -*-
"""Разбор отчёта 0948fb1 (MeetFlow, 04.11.2026). Встреча 28.10: все четыре задачи с исполнителем (84, 86, 96, 98) сняты как
заменённые. Новая сборка может не назвать исполнителя, тогда замена без него: исполнитель не должен пропасть вместе со
снятой задачей (тот же дефект, что отчёт 08ef4f0: «2 исполнителя из 4 потеряны»). И разбор снятых: чтение копии базы,
по каждой снятой пересборкой — почему она снята по нынешнему правилу, чтобы возвращать только по слову владелицы."""
import importlib.util
from pathlib import Path

from meetflow.core.rebuild import drop_missing, вернуть
from meetflow.core.registry import TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import TaskStatus

ЦИТАТА = "Петрова Анастасия, подготовьте регламент склада до десятого числа, это важно для приёмки"
ЗАПИСЬ = f"[00:01:00] Иванов Иван: {ЦИТАТА}."


def _база(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    pid = st.insert("projects", name="П", theme="_default")
    mid = st.insert("meetings", project_id=pid, date="2026-10-28", label="в")
    st.insert("sources", meeting_id=mid, name="t.txt", kind="transcript", text=ЗАПИСЬ)
    return st, TaskRegistry(st), pid, mid


def test_замена_без_исполнителя_получает_исполнителя_снятой(tmp_path):
    st, reg, pid, mid = _база(tmp_path)
    старая = reg.add(pid, "Подготовить регламент склада", "Петрова Анастасия", mid, ЦИТАТА)
    новая = reg.add(pid, "Подготовить регламент склада", None, mid, ЦИТАТА)
    итог = drop_missing(st, reg, mid, "2026-10-28", {новая}, текст_записи=ЗАПИСЬ)
    assert [t["id"] for t in итог["dropped"]] == [старая]
    assert st.get("tasks", новая)["assignee"] == "Петрова Анастасия"
    assert any(f"№{старая}" in (h["evidence_quote"] or "") for h in st.q(
        "SELECT evidence_quote FROM task_history WHERE task_id=?", (новая,)))


def test_исполнитель_замены_не_меняется(tmp_path):
    st, reg, pid, mid = _база(tmp_path)
    reg.add(pid, "Подготовить регламент склада", "Петрова", mid, ЦИТАТА)
    новая = reg.add(pid, "Подготовить регламент склада", "Петрова Анастасия", mid, ЦИТАТА)
    drop_missing(st, reg, mid, "2026-10-28", {новая}, текст_записи=ЗАПИСЬ)
    assert st.get("tasks", новая)["assignee"] == "Петрова Анастасия"


def test_не_замена_исполнителя_не_переносит(tmp_path):
    st, reg, pid, mid = _база(tmp_path)
    старая = reg.add(pid, "Согласовать акт сверки с заказчиком", "Петрова Анастасия", mid, ЦИТАТА)
    другая = reg.add(pid, "Заказать экспертизу резервуаров", None, mid, ЦИТАТА)
    drop_missing(st, reg, mid, "2026-10-28", {другая}, текст_записи=ЗАПИСЬ)
    assert st.get("tasks", старая)["status"] == TaskStatus.ACTIVE.value
    assert not st.get("tasks", другая)["assignee"]


def _скрипт():
    путь = Path(__file__).resolve().parents[1] / "scripts" / "razbor_snyatyh_0411.py"
    spec = importlib.util.spec_from_file_location("razbor_snyatyh_0411", путь)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _снять(reg, номер):
    reg.set_status(номер, TaskStatus.DROPPED, "rebuild", "не вошла в пересборку (04.11.2026 12:00)")


def test_разбор_снятых_раскладывает_и_базу_не_меняет(tmp_path, capsys):
    st, reg, pid, mid = _база(tmp_path)
    ложная = reg.add(pid, "Согласовать акт сверки с заказчиком", "Петрова Анастасия", mid, ЦИТАТА)
    заменённая = reg.add(pid, "Подготовить регламент склада", None, mid, ЦИТАТА)
    reg.add(pid, "Подготовить регламент склада", None, mid, ЦИТАТА)
    пустая = reg.add(pid, "Что-то без цитаты", None, mid, "")
    чужая = reg.add(pid, "Задача из прежней записи", None, mid, "этих слов в нынешней записи совсем нет и не было никогда")
    вручную = reg.add(pid, "Снята человеком", None, mid, ЦИТАТА)
    _снять(reg, ложная)
    assert вернуть(st, reg, ложная)                         # возвращена по слову владелицы и снята снова, как 92–98 на 28.10
    for номер in (ложная, заменённая, пустая, чужая):
        _снять(reg, номер)
    reg.set_status(вручную, TaskStatus.DROPPED, "operator", "не нужна")
    файл = tmp_path / "разбор.md"
    assert _скрипт().main(["--db", str(tmp_path / "m.db"), "--out", str(файл)]) == 0
    вывод = capsys.readouterr().out
    assert f"ложно снята, цитата есть, замены нет: 1 [{ложная}]" in вывод
    assert f"заменена той же работой: 1 [{заменённая}]" in вывод
    assert f"цитата пустая: 1 [{пустая}]" in вывод
    assert f"цитаты нет в записи: 1 [{чужая}]" in вывод
    assert "Согласовать" not in вывод                      # в консоль — только номера
    текст = файл.read_text(encoding="utf-8")
    assert "Согласовать акт сверки" in текст and "Снята человеком" not in текст
    assert "Возвращалась раньше: да" in текст
    st2 = Store(str(tmp_path / "m.db"))
    assert st2.get("tasks", ложная)["status"] == "dropped"


def test_разбор_без_цитаты_и_без_встречи_не_падает(tmp_path, capsys):
    Store(str(tmp_path / "m.db"))
    assert _скрипт().main(["--db", str(tmp_path / "m.db")]) == 0


def test_возвращённая_владелицей_не_снимается_0411():
    from meetflow.core import rebuild

    class Склад:
        def __init__(self, строки):
            self.строки = строки

        def q(self, _запрос, аргументы):
            return [{"1": 1} for x in self.строки if x[0] == аргументы[0] and rebuild.ВОЗВРАТ_ВЛАДЕЛИЦЫ in x[1]]

    склад = Склад([(3, f"снова в работе; {rebuild.ВОЗВРАТ_ВЛАДЕЛИЦЫ}"), (4, "снова найдена в пересборке")])
    assert rebuild.возвращена_владелицей(склад, 3)
    assert not rebuild.возвращена_владелицей(склад, 4)
