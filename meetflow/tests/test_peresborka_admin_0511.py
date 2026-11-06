# -*- coding: utf-8 -*-
"""«Пересобрать протокол» — только администратору (слово владелицы 05.11.2026)."""
from pathlib import Path


def test_пересборка_доступна_всем_ролям():
    # Слово владелицы 06.11.2026 отменило ограничение 05.11.2026: кнопка и сервер — всем.
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "web" / "erp" / "vstrechi.py").read_text(encoding="utf-8")
    assert "ctx.need_admin(request) if rebuild else ctx.need_user(request)" not in код
