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
# экран «Оформление» после переноса фронта ERP — design.js (возвращён 4af9cfa, 27.10.2026)
JS = "".join((ROOT / "meetflow" / "web" / "static" / f).read_text(encoding="utf-8") for f in ("app.js", "design.js"))


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
    block(name)
    assert f"{name}:" in JS, f"палитры {name} нет на экране «Оформление»"


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_white_on_accent_aa(name):
    b = block(name)
    assert contrast("#ffffff", token(b, "accent-fill")) >= 4.5
    assert contrast(token(b, "accent"), "#fafafa") >= 4.5   # ссылки на фоне страницы


@pytest.mark.parametrize("name", sorted(NEW))
def test_new_palettes_dark_accent_aa(name):
    assert contrast(token(block(name), "accent-dark"), "#1b1b1f") >= 4.5


def test_new_palettes_not_green_or_indigo():
    """Зелёные и индиго заняты проектами-примерами — новые тона вне их диапазона."""
    import colorsys
    for name, (acc, *_rest) in NEW.items():
        r, g, b = (int(acc[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hue = colorsys.rgb_to_hls(r, g, b)[0] * 360
        assert not (90 <= hue <= 175) and not (230 <= hue <= 300), (name, round(hue))


def test_dark_soft_tones_follow_accent():
    """Подложки тёмной темы берутся от акцента, а не жёстко зелёные."""
    # с 4af9cfa (27.10.2026) тёмная тема — только по выбору на «Оформлении» (`data-theme="dark"`), блок по настройке
    # системы не возвращён: правило то же — подложки от акцента, не зелёные
    assert "#1f2a25" not in CSS and CSS.count("color-mix(in srgb, var(--accent) 22%") >= 1
