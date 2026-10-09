import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from meeting_registry import pipeline  # noqa: E402
from meeting_registry.cli import load_team  # noqa: E402
from meeting_registry.registry import Registry  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data")


@pytest.fixture
def team():
    return load_team(os.path.join(DATA, "team.json"))


@pytest.fixture
def reg(tmp_path):
    r = Registry(str(tmp_path / "registry.db"))
    yield r
    r.close()


@pytest.fixture
def run(reg, team):
    def _run(text, date="2026-10-02", client=None, limits=None, name=None):
        return pipeline.process(text, name or f"встреча {date}.txt", date, reg, team, client, limits)
    return _run


MEETING_1 = """Гаврилов Павел: Коллеги, начинаем планёрку. По проекту Титан.
Лаптева Анастасия: По Титану договор подписан, акт отправили заказчику.
Гаврилов Павел: Хорошо. Назаров, подготовьте спецификацию на фильтры до пятницы.
Назаров Константин: Принято.
Гаврилов Павел: Ершова, запросите коммерческие предложения у трёх поставщиков до 10.10.
Ершова Светлана: Сделаем.
Гаврилов Павел: Марина, проверь остатки на складе.
Илюшин Антон: Я подготовлю график отгрузки к понедельнику.
Гаврилов Павел: Отменять заказ не будем, работаем дальше.
Гаврилов Павел: А счёт от перевозчика пришёл?
Гаврилов Павел: По авианакладной вернёмся позже.
"""

MEETING_2 = """Гаврилов Павел: Начинаем. Что по задачам с прошлой встречи?
Ершова Светлана: Коммерческие предложения у трёх поставщиков получили, сравнение готово.
Назаров Константин: Спецификацию на фильтры пока не подготовил, нужен ещё день.
Илюшин Антон: График отгрузки подготовить не успел.
Гаврилов Павел: Понятно. Седова, посчитайте экономику по трём предложениям до среды.
"""


@pytest.fixture
def m1():
    return MEETING_1


@pytest.fixture
def m2():
    return MEETING_2
