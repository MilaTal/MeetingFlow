# PLUGIN_GUIDE — как расширять MeetFlow без правки ядра

## 1. Новый тип входа (пример — CSV из системы ВКС)

```python
from meetflow.connectors.base import SourceConnector
from meetflow.core.types import SourceDoc, SourceKind

class CsvSource(SourceConnector):
    name, extensions = "csv", (".csv",)

    def read(self, data: bytes, filename: str) -> SourceDoc:
        rows = [r.split(";") for r in data.decode("utf-8").splitlines() if r.strip()]
        text = "\n".join(f"[00:{i:02d}:00] {who}: {what}" for i, (who, what) in enumerate(rows))
        return SourceDoc(filename, SourceKind.TRANSCRIPT, text, {"connector": self.name})
```

Подключение — одним из двух способов:

```python
registry = default_registry(); registry.register(CsvSource())     # в коде
```

```json
"connectors": {"extra": ["my_package.vks:CsvSource"]}             // в теме
```

Проверено тестом `test_new_connector_without_core_changes`: CSV-встреча проходит весь конвейер, ядро не менялось.

## 2. Новая модель

Подкласс `LLMConnector` с методом `complete(...)`, возвращающим `LLMResult`. Если у модели свой формат рассуждений или JSON — добавьте профиль в `core/prompts.py: PROFILES` или задайте `profile` существующий. Правила, которые коннектор обязан соблюдать: локальный адрес, явный контекст, понятная `ConnectorError` после исчерпания попыток, без истории диалога.

## 3. Новая выгрузка

Подкласс `OutputConnector` с `render(markdown, title) -> bytes` (например, PDF или карточка в трекер). Хранится всегда markdown — выгрузка производная.

## 4. Новая тематика

Скопируйте `themes/it_product.json`, поменяйте `id`, `vocabulary`, `protocol_skeleton`, `notes_markers`, `roles`, `design.palette`, `prompts.domain_role`. Всё, чего нет в файле, придёт из `_default.json`. Проверка:

```bash
python -m meetflow todo --theme моя_тема     # покажет PLACEHOLDER-заглушки
python -m pytest tests -k themes             # тема загрузится в общем тесте
```

Валидатор не пропустит тему без `super_admin`, без разделов протокола, с одинаковыми генератором и проверяющим, с моделью «-contributor» или с неизвестной палитрой.

## 5. Чего плагину делать нельзя

- Менять статус задачи в обход `TaskRegistry.set_status` (цитата и правило отрицаний).
- Писать в базу мимо `Store` (замок на данных).
- Отправлять данные встречи за пределы локального контура.
- Показывать технические ошибки в рабочих вкладках — только карточка `technical` для супер-админа.
