# -*- coding: utf-8 -*-
"""Свод стиля в промпте протокола — общий файл Планёрки (24.11.2026).

Старый путь `C:/Users/…/Desktop/ERP PM/…` после переезда проекта на P: не существует, и протокол молча уходил
на встроенную копию стиля. Здесь закреплено: свой путь сильнее, общий ищется на SD2 (UNC) и на P:, старый корень
не используется, без файлов — копия.
"""
from meetflow.core import prompts as pr


def test_свой_путь_сильнее_и_вырезается_раздел(tmp_path, monkeypatch):
    файл = tmp_path / "style.md"
    файл.write_text("вступление\n## Строгий корпоративный стиль\n\nПиши коротко.\n\n## Другое\nне брать",
                    encoding="utf-8")
    monkeypatch.setenv("MEETFLOW_STYLE_CODEX", str(файл))
    assert pr.путь_свода() == файл
    текст = pr.свод_стиля()
    assert "Пиши коротко" in текст and "Другое" not in текст and "вступление" not in текст


def test_нет_файлов_даёт_копию(monkeypatch):
    monkeypatch.setenv("MEETFLOW_STYLE_CODEX", "")
    monkeypatch.setattr(pr, "СВОД_СТИЛЯ_ПУТИ", ())
    assert pr.путь_свода() is None
    assert pr.свод_стиля() == pr.CORPORATE_STYLE.strip()


def test_общий_путь_не_старый_корень():
    assert all("Desktop" not in п and "ERP PM" not in п for п in pr.СВОД_СТИЛЯ_ПУТИ)
    assert any("Planerka" in п and "style_guide.md" in п for п in pr.СВОД_СТИЛЯ_ПУТИ)
