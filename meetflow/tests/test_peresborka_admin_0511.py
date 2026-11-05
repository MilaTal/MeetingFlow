# -*- coding: utf-8 -*-
"""«Пересобрать протокол» — только администратору (слово владелицы 05.11.2026)."""
from pathlib import Path


def test_пересборка_требует_администратора():
    код = (Path(__file__).resolve().parents[1] / "meetflow" / "web" / "erp" / "vstrechi.py").read_text(encoding="utf-8")
    assert "ctx.need_admin(request) if rebuild else ctx.need_user(request)" in код
