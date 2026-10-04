"""Статические проверки интерфейса (без браузера)."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"


def test_hidden_attribute_always_hides():
    """Письмо 46 meeting-registry (находка Планёрки): display на элементе перебивал атрибут hidden. У нас блок
    супер-админа «Мониторинг · Настройки · Оформление» был виден участнику (подтверждено на демо 03.10.26)."""
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css


def test_model_json_with_raw_tab_in_value():
    """Письмо 48 (прогон ERP у meeting-registry, 2 встречи из 20): модель копирует в цитату сырую табуляцию
    «00:00:00⇥Имя» — строгий разбор падал «Invalid control character»."""
    from meetflow.core.prompts import parse_json
    out = parse_json('{"tasks":[{"quote":"00:00:00' + chr(9) + 'Игнатов: сделать"}]}', False)
    assert out["tasks"][0]["quote"].startswith("00:00:00")
