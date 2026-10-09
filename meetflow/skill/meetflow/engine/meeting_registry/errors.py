"""Классы отказов. Разные причины обрабатываются по-разному — это и есть паттерн «очередь с классами».

Правило из Планёрки (паспорт, Р2): ошибка действия обрабатывается иначе, чем плохой ответ,
а остановка по пределу не повторяется никогда.
"""


class MeetingRegistryError(Exception):
    """Общий предок. Текст сообщения всегда пригоден для показа человеку."""


class SourceRejected(MeetingRegistryError):
    """Источник не принят: пустой, чужой, нечитаемый, слишком большой. Модель не вызывалась, денег не потрачено."""

    def __init__(self, reason: str, code: str):
        super().__init__(reason)
        self.code = code


class SetupError(MeetingRegistryError):
    """Не хватает настройки (нет модели, нет адреса Ollama). Человек может поправить сам — показываем причину дословно."""


class ProviderUnavailable(MeetingRegistryError):
    """Модель недоступна: сеть, 5xx, таймаут. Повтор имеет смысл, но делает его транспорт, а не конвейер."""


class BadModelAnswer(MeetingRegistryError):
    """Модель ответила, но не по контракту (не JSON, не те поля). Один повтор с напоминанием о формате."""


class BudgetExceeded(MeetingRegistryError):
    """Сработал потолок прогона. Не наследник ProviderUnavailable: повтор запрещён, иначе он кормит разгон."""

    def __init__(self, limit: str, value, ceiling):
        super().__init__(f"Остановлено по пределу «{limit}»: {value} при потолке {ceiling}")
        self.limit = limit
        self.value = value
        self.ceiling = ceiling
