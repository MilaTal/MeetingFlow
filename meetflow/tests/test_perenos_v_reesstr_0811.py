"""Д2.2: смена проекта на встрече уводит в реестр нового проекта (решение владелицы 05.11.2026).

Прежде после переноса открывался список встреч, а встреча оставалась в проекте, из которого её уводили; задачи
переезжали, и увидеть их можно было только переключив проект руками.
"""
from pathlib import Path

СТАТИКА = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_перенос_уводит_в_реестр_нового_проекта():
    nav = (СТАТИКА / "nav.js").read_text(encoding="utf-8")
    начало = nav.index("function перенестиВстречу")
    конец = nav.index("// Уведомление с кнопкой «Отменить»")
    кусок = nav[начало:конец]
    assert "Д2.2" in кусок
    assert 'выбратьПроект(String(v.value))' in кусок, "после переноса выбран новый проект — реестр его задач"
    assert "move-project" in кусок


def test_версия_nav_поднята():
    html = (СТАТИКА / "index.html").read_text(encoding="utf-8")
    assert 'nav.js?v=20261109mf86' in html


def test_перенос_вместе_с_задачами_на_сервере(store, project, meeting):
    """Серверная часть Д2.2 не изменилась: встреча переезжает вместе с задачами (проверка рядом со статикой)."""
    from meetflow.core import proekt_zapisi as pz
    from meetflow.core.registry import TaskRegistry

    другой = store.insert("projects", name="Другой", theme="erp_rollout")
    tid = TaskRegistry(store).add(project, "Проверить пломбы", "Сидоров Пётр", meeting, "", None, "2026-10-15")
    итог = pz.перенести_встречу(store, meeting, другой, "Админ")
    assert итог["tasks"] == 1 and store.get("tasks", tid)["project_id"] == другой
