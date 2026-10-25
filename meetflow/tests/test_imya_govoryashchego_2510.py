"""Правило 25.10.2026, пункт 3: имя говорящего — голос, затем аккаунт ВКС подсказкой, затем «Говорящий N».

Аккаунт ВКС — не говорящий: с чужого аккаунта может говорить коллега. Поэтому аккаунт только подсказка в тексте,
исполнителем по «я сделаю» он не становится; с одного аккаунта два голоса и больше — подсказка не ставится никому.
Тест написан до правки. Подключение к сборке — когда появится опознание голоса (строка 43).
"""
from meetflow.core.speakers import can_assign, label, review_suggestion


def test_voice_wins_over_account():
    text, source = label(voice_name="Сидоров Пётр", account="ivan.petrov", voices_same_account=1, index=2)
    assert text == "Сидоров Пётр" and source == "voice" and can_assign(source)


def test_account_is_only_hint():
    text, source = label(account="ivan.petrov", index=3)
    assert text == "ivan.petrov (аккаунт ВКС)" and source == "account"
    assert not can_assign(source)


def test_two_voices_on_one_account_no_hint():
    text, source = label(account="ivan.petrov", voices_same_account=2, index=4)
    assert text == "Говорящий 4" and source == "unknown"


def test_no_voice_no_account_is_speaker_number():
    text, source = label(index=5)
    assert text == "Говорящий 5" and source == "unknown"


def test_review_suggestion_names_account():
    assert review_suggestion("ivan.petrov") == "аккаунт ВКС: ivan.petrov?"
