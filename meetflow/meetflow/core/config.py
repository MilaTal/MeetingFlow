"""Конфигурация под тематику.

В исходных проектах тематика была рассыпана по константам и промптам
(PROJECT_TITLE в meeting_pipeline.py, блоки протокола в draft_checks.py,
коды отделов, «аналитик 1С:ERP 2.4» в скилле). Здесь всё предметное —
в одном JSON-файле темы, который накладывается на themes/_default.json.

Значение "PLACEHOLDER: ..." допустимо: тема загрузится, а заглушка попадёт
в список todo() — его показывает CLI и экран «Параметры».
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

THEMES_DIR = Path(__file__).resolve().parents[2] / "themes"
PALETTES = {"indigo", "forest", "emerald", "polaris", "sage", "meadow",
            # для новых проектов (исследование 03.10.26): не зелёные и не индиго
            "petrol", "ocean", "slate", "graphite", "ochre", "clay", "copper", "claret"}
REQUIRED = ["id", "title", "vocabulary", "protocol_skeleton", "roles", "llm", "design"]


class ThemeError(ValueError):
    pass


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _placeholders(obj: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found += _placeholders(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _placeholders(v, f"{path}[{i}]")
    elif isinstance(obj, str) and obj.startswith(("PLACEHOLDER", "TODO")):
        found.append(f"{path}: {obj}")
    return found


@dataclass
class Theme:
    data: dict[str, Any]
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def id(self) -> str:
        return self.data["id"]

    def word(self, key: str) -> str:
        return self.data["vocabulary"].get(key, key)

    def todo(self) -> list[str]:
        return _placeholders(self.data)


def _family(side: dict) -> str:
    fam = str(side.get("family") or "").strip().lower()
    if fam:
        return fam
    prof = str(side.get("profile") or "").strip().lower()
    if prof and prof != "generic":
        return prof
    name = str(side.get("model") or "").lower().replace("placeholder:", "").strip()
    return re.split(r"[-:._/\d]", name.split("/")[-1], maxsplit=1)[0] or name


def validate(data: dict[str, Any]) -> list[str]:
    errors = [f"нет обязательного ключа «{k}»" for k in REQUIRED if k not in data]
    if errors:
        return errors
    pal = data["design"].get("palette")
    if pal not in PALETTES:
        errors.append(f"design.palette «{pal}» не из {sorted(PALETTES)}")
    roles = data["roles"]
    if not isinstance(roles, list) or "super_admin" not in roles:
        errors.append("roles: нужен список, и в нём super_admin (защита последнего носителя роли)")
    if not data["protocol_skeleton"]:
        errors.append("protocol_skeleton пуст: протоколу нужна структура разделов")
    for side in ("generator", "verifier"):
        if side not in data["llm"]:
            errors.append(f"llm.{side} не задан: генерация и проверка — разные роли")
    g, v = data["llm"].get("generator", {}), data["llm"].get("verifier", {})
    # сравнивается семейство (поле family, иначе профиль, иначе начало имени модели), а не имя:
    # glm-5.3 и glm-4.7-flash — одно семейство, проверка такой парой не независима (01/18)
    # модель не задана (по умолчанию её нет, 13.10.26) — сравнивать нечего: роль «не настроена»
    if g and v and g.get("model") and g.get("model") == v.get("model") and not data["llm"].get("allow_same_verifier"):
        errors.append("llm: проверяющая модель совпадает с генерирующей (allow_same_verifier=false)")
    elif g and v and _family(g) == _family(v) and not data["llm"].get("allow_same_verifier"):
        errors.append(f"llm: проверяющая модель того же семейства, что генерирующая ({_family(g)}); "
                      "нужны разные семейства (allow_same_verifier=false)")
    for side in ("generator", "verifier"):
        model = str(data["llm"].get(side, {}).get("model", ""))
        if "contributor" in model:
            errors.append(f"llm.{side}: модели с обучением на данных запрещены ({model})")
    # второй инструмент — OpenRouter: те же правила, что для локального (решение владельца 03.10.26)
    orr = data["llm"].get("openrouter") or {}
    og, ov = orr.get("generator") or {}, orr.get("verifier") or {}
    if og and ov and not data["llm"].get("allow_same_verifier") and \
            ((og.get("model") and og.get("model") == ov.get("model")) or _family(og) == _family(ov)):
        errors.append(f"llm.openrouter: проверяющая модель того же семейства, что генерирующая ({_family(og)})")
    for side, cfg in (("generator", og), ("verifier", ov)):
        if "contributor" in str(cfg.get("model", "")):
            errors.append(f"llm.openrouter.{side}: модели с обучением на данных запрещены ({cfg.get('model')})")
    cap = data["llm"].get("max_answer_tokens", 4096)
    if not isinstance(cap, int) or not 256 <= cap <= 32000:
        errors.append(f"llm.max_answer_tokens={cap}: нужен целый потолок ответа от 256 до 32000 токенов")
    # опечатка в ключе ронала прогон (находка ревью) — ловим при загрузке темы
    from dataclasses import fields
    from .budget import BudgetLimits
    from .gates import GateConfig
    for section, cls in (("gates", GateConfig), ("budget", BudgetLimits)):
        known = {f.name for f in fields(cls)}
        for k in (data.get(section) or {}):
            if k not in known:
                errors.append(f"{section}.{k}: неизвестный ключ (допустимы {sorted(known)})")
    return errors


def load_theme(name_or_path: str | Path, themes_dir: Path | None = None) -> Theme:
    tdir = Path(themes_dir or THEMES_DIR)
    p = Path(name_or_path)
    if not p.suffix:
        p = tdir / f"{name_or_path}.json"
    if not p.exists():
        raise ThemeError(f"тема не найдена: {p}")
    base = json.loads((tdir / "_default.json").read_text(encoding="utf-8"))
    over = json.loads(p.read_text(encoding="utf-8"))
    data = deep_merge(base, over) if p.name != "_default.json" else base
    errs = validate(data)
    if errs:
        raise ThemeError(f"{p.name}: " + "; ".join(errs))
    return Theme(data, str(p))


def list_themes(themes_dir: Path | None = None) -> list[str]:
    tdir = Path(themes_dir or THEMES_DIR)
    return sorted(x.stem for x in tdir.glob("*.json") if not x.name.startswith("_"))
