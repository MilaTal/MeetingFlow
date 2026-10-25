"""Имя говорящего по правилу владелицы 25.10.2026.

1. Голос опознан по отпечатку (уверенное совпадение) — имя по голосу, что бы ни было в выгрузке ВКС.
2. Голоса нет, есть имя аккаунта ВКС — подсказка «Фамилия И. (аккаунт ВКС)»; исполнителем аккаунт не становится.
3. Ни голоса, ни аккаунта — «Говорящий N».
4. С одного аккаунта два голоса и больше — подсказка аккаунта не ставится никому.
5. В «Разборе голосов» у неопознанного — предложение «аккаунт ВКС: …?».

Модуль чистый: опознание голоса делает общий голосовой сервис, сюда передаётся результат.
"""
from __future__ import annotations


def label(voice_name: str | None = None, account: str | None = None, voices_same_account: int = 0,
          index: int = 1) -> tuple[str, str]:
    """(как писать в тексте, источник имени): voice / account / unknown."""
    if voice_name and voices_same_account <= 1:
        return voice_name, "voice"
    if account and voices_same_account <= 1:
        return f"{account} (аккаунт ВКС)", "account"
    return f"Говорящий {index}", "unknown"


def can_assign(source: str) -> bool:
    """Исполнителем по «я сделаю» может стать только голос: аккаунт — не человек."""
    return source == "voice"


def review_suggestion(account: str | None) -> str:
    """Подсказка в «Разборе голосов» для неопознанного голоса."""
    return f"аккаунт ВКС: {account}?" if account else ""
