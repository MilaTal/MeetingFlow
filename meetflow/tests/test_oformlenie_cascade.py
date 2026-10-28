"""«Оформление»: выбранная палитра действительно доходит до цвета (замечание владелицы 28.10.2026).

После переноса фронта ERP (1494432, 27.10.2026) слой theme-line.css ставил `--accent: #6863bf` правилом
`:root:not([data-theme="dark"])` — специфичность (0,2,0) и файл позже, поэтому блоки `[data-palette=…]` (0,1,0)
из styles.css в светлой теме не применялись: палитра выбиралась, цвет оставался индиго.

Мерить числом: ниже — маленький каскад по файлам в порядке подключения в index.html. Считаются только правила,
которые целиком относятся к самому `<html>` (`:root`, `html`, атрибуты, `:not`/`:is`/`:where`); правила внутри
`@media` не учитываются — тема «Как в системе» здесь не проверяется.
"""
import re
from pathlib import Path

import pytest

from meetflow.core.config import PALETTES

STATIC = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS_FILES = re.findall(r'<link rel="stylesheet" href="([\w.-]+\.css)\?v=', INDEX)
STYLES = (STATIC / "styles.css").read_text(encoding="utf-8")


def _top_rules(css: str):
    """Правила верхнего уровня (селектор, тело); блоки @media и прочие @-правила пропускаются целиком."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    i, n = 0, len(css)
    while i < n:
        j = css.find("{", i)
        if j < 0:
            return
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while depth and k < n:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        if not head.startswith("@"):
            yield head, css[j + 1:k - 1]
        i = k


def _split(s: str):
    parts, depth, cur = [], 0, ""
    for ch in s:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


SIMPLE = re.compile(r':root|html|\[([\w-]+)(?:="([^"]*)")?\]|:(not|is|where)\(')


def _match(sel: str, attrs: dict):
    """(совпало, специфичность) для простого составного селектора без комбинаторов; иначе None."""
    spec, i = [0, 0, 0], 0
    while i < len(sel):
        m = SIMPLE.match(sel, i)
        if not m:
            return None
        tok = m.group(0)
        if tok == ":root":
            spec[1] += 1
            ok = True
        elif tok == "html":
            spec[2] += 1
            ok = True
        elif tok.startswith("["):
            spec[1] += 1
            name, val = m.group(1), m.group(2)
            ok = name in attrs and (val is None or attrs[name] == val)
        else:
            depth, k = 1, m.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(sel[k], 0)
                k += 1
            inner = [_match(s, attrs) for s in _split(sel[m.end():k - 1])]
            if any(r is None for r in inner):
                return None
            best = max((r[1] for r in inner), default=(0, 0, 0))
            hit = any(r[0] for r in inner)
            ok = (not hit) if m.group(3) == "not" else hit
            if m.group(3) != "where":
                spec = [a + b for a, b in zip(spec, best)]
            i = k
            if not ok:
                return False, tuple(spec)
            continue
        if not ok:
            return False, tuple(spec)
        i = m.end()
    return True, tuple(spec)


def resolve(var: str, attrs: dict) -> str:
    """Значение переменной на `<html>` после каскада всех CSS из index.html."""
    best, order = None, 0
    for f in CSS_FILES:
        for head, body in _top_rules((STATIC / f).read_text(encoding="utf-8")):
            decl = re.search(r"(?:^|;)\s*%s\s*:\s*([^;]+)" % re.escape(var), body)
            if not decl:
                continue
            specs = [r[1] for r in (_match(s, attrs) for s in _split(head)) if r and r[0]]
            if not specs:
                continue
            order += 1
            key = (max(specs), order)
            if best is None or key >= best[0]:
                best = (key, decl.group(1).strip())
    assert best, f"{var} не задан"
    return best[1]


def palette_accent(name: str) -> str:
    m = re.search(r'\[data-palette="%s"\]\s*\{[^}]*?--accent:\s*(#[0-9a-fA-F]{6})' % name, STYLES)
    assert m, name
    return m.group(1).lower()


def test_resolver_sees_line_layer():
    """Прибор проверен на известном: без палитры светлая тема даёт акцент «Линии» #6863bf."""
    assert resolve("--accent", {}).lower() == "#6863bf"
    assert "theme-line.css" in CSS_FILES


def test_palette_layer_goes_last():
    """Слой палитры подключён последним — иначе следующий файл с `:root:not(...)` снова перебьёт акцент."""
    assert CSS_FILES[-1] == "oformlenie.css", CSS_FILES


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("name", sorted(PALETTES))
def test_palette_accent_reaches_root(name, theme):
    attrs = {"data-palette": name, "data-sistema": "meetflow", "data-theme": theme}
    assert resolve("--accent", attrs).lower() == palette_accent(name), (name, theme)


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_palette_accent_without_theme_choice(name):
    """«Как в системе» снимает data-theme — светлый слой «Линии» не должен перебивать палитру."""
    assert resolve("--accent", {"data-palette": name}).lower() == palette_accent(name)


def palette_var(name: str, var: str) -> str:
    m = re.search(r'\[data-palette="%s"\]\s*\{[^}]*?--%s:\s*([^;]+);' % (name, re.escape(var)), STYLES)
    assert m, (name, var)
    return m.group(1).strip().lower()


@pytest.mark.parametrize("name", sorted(PALETTES))
def test_palette_tones_light_as_old_meetflow(name):
    """Перевёрнут 28.10.2026: прежде индиго в светлой теме сохраняла нейтральные подложки «Линии» (#fafafa, наведение
    #4f4aa3). Решение владелицы — применение палитры как в MeetFlow до переноса фронта ERP: подложки, наведение и рамки
    всех палитр, индиго тоже, — из её блока в styles.css."""
    for theme in ({}, {"data-theme": "light"}):
        attrs = {"data-palette": name, **theme}
        for var in ("accent", "accent-hover", "accent-soft", "accent-soft-hover", "accent-border"):
            assert resolve("--" + var, attrs).lower() == palette_var(name, var), (name, theme, var)
    assert palette_var("indigo", "accent-soft") == "#eef2ff"


def test_indigo_tint_hover_kept():
    """Подложка наведения у индиго — прежняя «Линии»; от акцента она считается только у остальных палитр."""
    assert resolve("--tint-hover", {"data-palette": "indigo"}).lower() == "#e2e6fa"


def test_system_theme_follows_os():
    """«Как в системе» следует настройке системы (как в MeetFlow до переноса фронта ERP): тёмная система — та же тёмная
    тема, что по кнопке, и смена без перезагрузки."""
    js = (STATIC / "design.js").read_text(encoding="utf-8")
    assert 'matchMedia("(prefers-color-scheme: dark)")' in js
    assert 'addEventListener("change", apply)' in js


def test_old_meetflow_application_rules():
    """Применение палитры к экранам: меню, главная кнопка заливкой акцента, шапки таблиц на подложке акцента, карточки
    с оттенком акцента — правила слоя на месте и перебивают «Линию» (!important там, где он у «Линии»)."""
    css = (STATIC / "oformlenie.css").read_text(encoding="utf-8")
    assert ".sidebar .nav-item.nav-main { color: var(--accent-text); font-weight: 600; }" in css
    assert ".btn-primary { background: var(--accent-fill) !important" in css
    assert "#main table:not(.reg-closed) thead th { background: var(--accent-soft) !important" in css
    assert "linear-gradient(to bottom, var(--card-top) 0%, var(--card-bottom) 100%)" in css
