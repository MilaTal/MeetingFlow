"""Генератор палитр для новых проектов (исследование 03.10.26).

Ориентиры — ведущие продукты работы с документами через ИИ (Supabase,
Mintlify, Vercel/Geist, Linear, Harvey, Anthropic, Granola, GitBook).
Их фирменные цвета приглушены до корпоративного уровня: белый текст на
акценте ≥ 4.5 по WCAG. Зелёные и индиго не берутся — заняты проектами-
примерами. Скрипт пишет CSS-блок между метками в styles.css и печатает
таблицу контрастов. Запуск: python scripts/gen_palettes.py
"""
from __future__ import annotations

import io
import re
from pathlib import Path

# имя: (accent, hover, dark_accent, ориентир, тематика)
NEW = {
    "petrol":   ("#1d5e69", "#15454d", "#4fa3b1", "Mintlify / Supabase, сдвиг в сине-зелёный", "медицина, фарма, экология"),
    "ocean":    ("#245a8c", "#1d4870", "#6a9fd4", "Vercel / Otter, приглушён", "ИТ, логистика, госзаказчики"),
    "slate":    ("#46586f", "#384759", "#8a9db6", "Linear по сдержанности", "финансы, аудит, закупки"),
    "graphite": ("#3f4249", "#2e3136", "#9a9ea8", "Harvey: акцент — это чёрный", "юридические документы, договоры"),
    "ochre":    ("#8a5a12", "#6a450e", "#d29a45", "Granola, тёплые нейтрали", "образование, HR, обучение"),
    "clay":     ("#a14e36", "#86412d", "#d08a74", "Anthropic / Claude, затемнён до AA", "стройка, девелопмент, архитектура"),
    "copper":   ("#8c5232", "#724329", "#c99272", "GitBook, приглушён", "производство, энергетика"),
    "claret":   ("#7d3045", "#632637", "#cc8597", "палитры консалтинга", "консалтинг, корпоративное управление"),
}


def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(h: str, share: float, base: str = "#ffffff") -> str:
    a, b = hex2rgb(h), hex2rgb(base)
    return "#" + "".join(f"{round(x * share + y * (1 - share)):02x}" for x, y in zip(a, b))


def lum(h: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in hex2rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def css_block() -> str:
    out = ["/* >>> palettes:generated (scripts/gen_palettes.py) — не править руками */"]
    for name, (acc, hov, dark, ref, use) in NEW.items():
        r, g, b = hex2rgb(acc)
        out.append(f'[data-palette="{name}"] {{ /* {ref}; {use} */\n'
                   f"  --accent: {acc}; --accent-hover: {hov}; --accent-fill: {acc}; --accent-fill-hover: {hov};\n"
                   f"  --accent-soft: {mix(acc, .08)}; --accent-soft-hover: {mix(acc, .14)}; "
                   f"--accent-border: rgba({r}, {g}, {b}, 0.2);\n"
                   f"  --card-top: {mix(acc, .09)}; --card-bottom: {mix(acc, .02)}; "
                   f"--accent-shadow: rgba({r}, {g}, {b}, 0.18); --accent-dark: {dark};\n}}")
    sel = ", ".join(f'[data-palette="{n}"]' for n in NEW)
    # в тёмной теме акцентный текст — светлый вариант палитры (как у Supabase/Mintlify)
    out.append("@media (prefers-color-scheme: dark) {\n  :root:not([data-theme=\"light\"]):is(" + sel +
               ") { --accent-text: var(--accent-dark); }\n}")
    out.append(":root[data-theme=\"dark\"]:is(" + sel + ") { --accent-text: var(--accent-dark); }")
    out.append("/* <<< palettes:generated */")
    return "\n".join(out)


def main() -> None:
    css = Path(__file__).resolve().parents[1] / "meetflow" / "web" / "static" / "styles.css"
    s = io.open(css, encoding="utf-8").read()
    block = css_block()
    pat = re.compile(r"/\* >>> palettes:generated.*?<<< palettes:generated \*/", re.S)
    s = pat.sub(lambda _: block, s) if pat.search(s) else s.replace("\n/* Тёмная тема", "\n" + block + "\n\n/* Тёмная тема", 1)
    io.open(css, "w", encoding="utf-8", newline="\n").write(s)
    print(f"{'палитра':10} {'белый/accent':>13} {'accent/#fafafa':>15} {'accent/soft':>12} {'dark/#1b1b1f':>13}")
    for name, (acc, hov, dark, *_ ) in NEW.items():
        print(f"{name:10} {contrast('#ffffff', acc):13.2f} {contrast(acc, '#fafafa'):15.2f} "
              f"{contrast(acc, mix(acc, .08)):12.2f} {contrast(dark, '#1b1b1f'):13.2f}")


if __name__ == "__main__":
    main()
