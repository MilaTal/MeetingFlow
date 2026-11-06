"""Перенос из Планёрки `16089ef`, `cd6bdf6` (решение владелицы 20.10.2026): «к следующей встрече» — маркер без даты.

Прежнее правило +7 дней с пометкой «оценка» осталось только в Проекте ERP. В MeetFlow срок пуст, вид — «к следующей
встрече», на экране и в документе — словами. Тесты написаны до правки и падали.
"""
from datetime import date

from meetflow.core import deadline
from meetflow.core.dates import due_text


def test_next_meeting_is_marker_without_date():
    # 06.11.2026: `core/deadline.py` заменён файлом ERP 1 в 1, а в ERP маркер «к следующей встрече» по умолчанию
    # выключен (`marker=False` → +7 дней с пометкой «оценка»). Правило владелицы 20.10.2026 в MeetFlow остаётся,
    # поэтому вызов передаёт `marker=True` — как и сборка. Тест перевёрнут на вызов, не удалён.
    d = deadline.resolve("подготовьте к следующей встрече", date(2026, 10, 1), marker=True)
    assert d.due is None and d.kind == deadline.NEXT_MEETING and d.issue is None
    assert deadline.resolve("к следующему совещанию", date(2026, 10, 1), marker=True).due is None
    assert deadline.resolve("не к следующей встрече", date(2026, 10, 1), marker=True).due is None
    assert due_text("", "2026-10-01", deadline.NEXT_MEETING) == "к следующей встрече"
    # разница с ERP видна явно: без флага — оценка +7 дней
    без_флага = deadline.resolve("подготовьте к следующей встрече", date(2026, 10, 1))
    assert без_флага.due == date(2026, 10, 8) and без_флага.kind == deadline.ESTIMATE


def test_other_relative_dates_still_work():
    d = deadline.resolve("сделайте завтра", date(2026, 10, 1))
    assert d.due == date(2026, 10, 2)
