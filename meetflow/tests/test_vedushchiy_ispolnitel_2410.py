"""Перенос из Планёрки `938c62f` (решение владелицы 19.10.2026): ведущий и директор — такие же исполнители, как все.

Прежняя подсказка велела возвращать их задачи с пустым исполнителем — этот запрет снят. Тест написан до правки и
падал.
"""
from conftest import TRANSCRIPT

from meetflow.core.prompts import ModelProfile, PromptBuilder


def test_prompt_does_not_clear_assignee_of_leader():
    sysm, user = PromptBuilder("роль", ModelProfile("generic", 32_000, 8_000, "Ответ — строго JSON.")) \
        .extract_tasks(1, TRANSCRIPT.splitlines(), ["Игнатов Иван"])
    text = (sysm + "\n" + user).lower()
    assert "ведущий планёрки и директор" in text and "такие же исполнители" in text
    assert "задачу, которую берёт ведущий" not in text, "в подсказке остался запрет ведущему быть исполнителем"
    assert "assignee null" in text and "исполнитель не назван" in text
