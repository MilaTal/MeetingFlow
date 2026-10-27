"""Дизайн-система: палитры в коде и в CSS совпадают, контраст по WCAG.

Мерить числом, а не глазом: контраст считается из самого styles.css,
поэтому палитра ниже нормы или забытая в CSS не пройдёт.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from gen_palettes import NEW, contrast  # noqa: E402

from meetflow.core.config import PALETTES  # noqa: E402

CSS = (ROOT / "meetflow" / "web" / "static" / "styles.css").read_text(encoding="utf-8")
JS = (ROOT / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def block(name: str) -> str:
    m = re.search(r'\[data-palette="%s"\]\s*\{([^}]*)\}' % name, CSS)
    assert m, f"нет CSS-блока палитры {name}"
    return m.group(1)


def token(body: str, name: str) -> str:
    m = re.search(r"--%s:\s*(#[0-9a-fA-F]{6})" % name, body)
    assert m, name
    return m.group(1)


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_palette_in_css_and_ui(name):
    """Перевёрнут 27.10.2026 (экраны ERP 1 в 1): фронт MeetFlow — фронт ERP, светлая тема ERP одна; экрана «Оформление»
    и CSS-блоков палитр больше нет, палитры остаются только в теме."""
    assert f'[data-palette="{name}"]' not in CSS
    assert "data-palette" not in JS and "#design" not in JS


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_white_on_accent_aa(name):
    """Перевёрнут 27.10.2026: контраст считается по акценту светлой темы ERP — белое на акценте и акцент на фоне ≥ 4,5."""
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    assert contrast("#ffffff", token(root, "accent")) >= 4.5
    assert contrast(token(root, "accent"), token(root, "bg")) >= 4.5


@pytest.mark.parametrize("name", sorted(NEW))
def test_new_palettes_dark_accent_aa(name):
    """Перевёрнут 27.10.2026: тёмной темы нет (ERP светлая) — ни правил тёмной схемы, ни тёмного акцента в CSS."""
    assert "prefers-color-scheme: dark" not in CSS and "--accent-dark" not in CSS


def test_new_palettes_not_green_or_indigo():
    """Зелёные и индиго заняты проектами-примерами — новые тона вне их диапазона."""
    import colorsys
    for name, (acc, *_rest) in NEW.items():
        r, g, b = (int(acc[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hue = colorsys.rgb_to_hls(r, g, b)[0] * 360
        assert not (90 <= hue <= 175) and not (230 <= hue <= 300), (name, round(hue))


def test_dark_soft_tones_follow_accent():
    """Перевёрнут 27.10.2026: подложки — светлой темы ERP, от её акцента (--accent-soft), тёмных подложек нет."""
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    assert "--accent-soft:" in root and "#1f2a25" not in CSS
