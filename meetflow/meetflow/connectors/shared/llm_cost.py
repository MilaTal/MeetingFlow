# -*- coding: utf-8 -*-
"""Стоимость вызова модели в деньгах: от поставщика, а если он её не вернул — токены × тариф (решение владельца 15.10.26).

Зачем. DeepSeek цену вызова не возвращает: в журнале вызовов `cost_usd` пустой (живой замер локальной машины 15.10.26),
поэтому «Расход» показывал ноль, а потолок цены прогона `LLM_MAX_COST_PER_RUN_USD` не срабатывал никогда. Правило
владельца: если стоимость не задана поставщиком, считать количество токенов × стоимость по открытому прейскуранту
поставщика.

Файл одинаков до байта в трёх местах — `system/scripts/llm_cost.py` (его читает ERP через оркестратор),
`scripts/llm_cost.py` и `planerka/webapp/app/services/llm_cost.py`; совпадение держит
`scripts/proverka_zerkalnosti_pravok.py`. Модуль ничего не импортирует из продуктов: только стандартная библиотека.

Три исхода на каждом вызове (`стоимость_вызова`):
- поставщик вернул стоимость (OpenRouter `usage.cost`) — она, `cost_source: "поставщик"`;
- не вернул, а у точки есть тариф — токены × тариф, `cost_source: "расчёт по тарифу <источник, дата>"`;
- нет ни того ни другого — `cost_usd: null`, `cost_source: "тариф не задан"`.

Формула (цены — за 1 млн токенов):
    стоимость = ((вход − из кэша) × цена входа + из кэша × цена входа из кэша + выход × цена выхода) / 1 000 000
                × множитель пика, если вызов пришёлся на часы пик (по времени вызова в UTC), иначе × 1.
«Вход» — `prompt_tokens` (у DeepSeek он уже включает попадания в кэш), «из кэша» — `prompt_cache_hit_tokens` у DeepSeek
или `prompt_tokens_details.cached_tokens` у OpenAI-совместимых, «выход» — `completion_tokens` (ход мысли модели, если он
есть, поставщик считает в выходе).

Тариф точки — необязательное поле `tariff` у точки в `models.json`:
    {"input": 0.15, "input_cached": 0.003, "output": 0.60, "currency": "USD",
     "peak": {"multiplier": 2, "utc_hours": [[1, 4], [6, 10]], "weekdays": [0, 1, 2, 3, 4]},
     "source": "…", "as_of": "дд.мм.гггг"}
Нет поля, а модель и адрес совпадают со встроенным справочником открытых прейскурантов (`СПРАВОЧНИК`) — берётся он.
Тариф, заданный администратором у точки, справочник не перекрывает никогда.

Расчётная сумма — по открытому прейскуранту, а не счёт: фактический счёт — в кабинете поставщика. Праздники КНР в часах
пик не учитываются (поставщик в праздник может брать обычную цену, расчёт возьмёт пиковую — сумма выйдет больше).
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

МИЛЛИОН = 1_000_000
ПОСТАВЩИК = "поставщик"
ТАРИФ_НЕ_ЗАДАН = "тариф не задан"
РАСЧЁТ = "расчёт по тарифу"
ЗАДНИМ_ЧИСЛОМ = "задним числом"
ВАЛЮТЫ = ("USD",)
МОСКВА = timedelta(hours=3)          # дни на панели — по Москве, как у остальных строк «Расхода»
ПОДСКАЗКА_ПИКА = ("Часы пик — по UTC, с понедельника по пятницу. Праздники КНР не учитываются: в праздник поставщик "
                  "может взять обычную цену, а расчёт возьмёт пиковую.")
ПОЯСНЕНИЕ = ("Расчётная сумма — токены × открытый прейскурант поставщика, а не счёт: фактический счёт — в кабинете "
             "поставщика. Где поставщик вернул стоимость сам (OpenRouter), берётся его число.")

_ИСТОЧНИК_DEEPSEEK = "открытый прейскурант DeepSeek, api-docs.deepseek.com/quick_start/pricing"
_ИСТОЧНИК_ANTHROPIC = "Anthropic, platform.claude.com/docs/en/about-claude/pricing"
_ПИК_DEEPSEEK = {"multiplier": 2, "utc_hours": [[1, 4], [6, 10]], "weekdays": [0, 1, 2, 3, 4]}

# Встроенный справочник открытых прейскурантов: цены за 1 млн токенов вне часов пик, пик — множителем.
# DeepSeek, снято со страницы поставщика 14.10.2026: deepseek-flash (и прежние имена той же цены) — из кэша 0,003 $,
# мимо кэша 0,15 $, выход 0,60 $ (в пик вдвое: 0,006 / 0,30 / 1,20); deepseek-v4-pro — 0,022 / 0,66 / 1,98 $
# (в пик 0,044 / 1,32 / 3,96).
# Anthropic (Claude по ключу через OpenAI-совместимый адрес, 15.10.26) — снято со страницы поставщика 15.10.2026, часов
# пик нет. Кэш подсказок через этот адрес не работает (prompt_tokens_details пуст), поэтому цена «из кэша» = цене входа.
# claude-haiku-5-5 — базовая ставка, до 100 тыс. токенов входа; выше 100 тыс. поставщик берёт 0,50 / 2,50 $ — расчёт
# этого не учитывает (сумма за длинный вход выйдет меньше счёта).
СПРАВОЧНИК: tuple = (
    {"title": "DeepSeek — deepseek-flash", "hosts": ("api.deepseek.com",),
     "models": ("deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"),
     "tariff": {"input": 0.15, "input_cached": 0.003, "output": 0.60, "currency": "USD", "peak": _ПИК_DEEPSEEK,
                "source": _ИСТОЧНИК_DEEPSEEK, "as_of": "14.10.2026"}},
    {"title": "DeepSeek — deepseek-v4-pro", "hosts": ("api.deepseek.com",), "models": ("deepseek-v4-pro",),
     "tariff": {"input": 0.66, "input_cached": 0.022, "output": 1.98, "currency": "USD", "peak": _ПИК_DEEPSEEK,
                "source": _ИСТОЧНИК_DEEPSEEK, "as_of": "14.10.2026"}},
    {"title": "Anthropic — claude-opus-5-5", "hosts": ("api.anthropic.com",), "models": ("claude-opus-5-5",),
     "tariff": {"input": 4.0, "input_cached": 4.0, "output": 20.0, "currency": "USD",
                "source": _ИСТОЧНИК_ANTHROPIC, "as_of": "15.10.2026"}},
    {"title": "Anthropic — claude-sonnet-5-5", "hosts": ("api.anthropic.com",), "models": ("claude-sonnet-5-5",),
     "tariff": {"input": 2.0, "input_cached": 2.0, "output": 10.0, "currency": "USD",
                "source": _ИСТОЧНИК_ANTHROPIC, "as_of": "15.10.2026"}},
    {"title": "Anthropic — claude-haiku-5-5", "hosts": ("api.anthropic.com",), "models": ("claude-haiku-5-5",),
     "tariff": {"input": 0.10, "input_cached": 0.10, "output": 0.50, "currency": "USD",   # до 100 тыс. входа
                "source": _ИСТОЧНИК_ANTHROPIC, "as_of": "15.10.2026"}},
    {"title": "Anthropic — claude-fable-5-1", "hosts": ("api.anthropic.com",), "models": ("claude-fable-5-1",),
     "tariff": {"input": 10.0, "input_cached": 10.0, "output": 50.0, "currency": "USD",
                "source": _ИСТОЧНИК_ANTHROPIC, "as_of": "15.10.2026"}},
)

_ДАТА = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


class ТарифНеВерен(ValueError):
    """Тариф в файле или в форме заполнен не так: текст — для человека, без технических слов."""


def _число(значение, что: str) -> float:
    if isinstance(значение, bool) or not isinstance(значение, (int, float)):
        raise ТарифНеВерен(f"{что} — число долларов за 1 млн токенов")
    if not math.isfinite(значение) or значение < 0:
        raise ТарифНеВерен(f"{что} — неотрицательное число")
    return float(значение)


def проверить_тариф(тариф) -> dict:
    """Тариф точки — в проверенном виде; неверный — `ТарифНеВерен` с понятным текстом."""
    if not isinstance(тариф, dict):
        raise ТарифНеВерен("тариф — набор цен: вход, из кэша, выход")
    вход = _число(тариф.get("input"), "цена входа")
    выход = _число(тариф.get("output"), "цена выхода")
    из_кэша = _число(тариф["input_cached"], "цена входа из кэша") if тариф.get("input_cached") is not None else вход
    валюта = str(тариф.get("currency") or "USD").upper()
    if валюта not in ВАЛЮТЫ:
        raise ТарифНеВерен("валюта тарифа — только USD: расход складывается в долларах")
    чистый = {"input": вход, "input_cached": из_кэша, "output": выход, "currency": валюта}
    пик = тариф.get("peak")
    if пик:
        if not isinstance(пик, dict):
            raise ТарифНеВерен("часы пик — множитель, часы UTC и дни недели")
        множитель = _число(пик.get("multiplier"), "множитель часов пик")
        if множитель <= 0:
            raise ТарифНеВерен("множитель часов пик — больше нуля")
        часы = пик.get("utc_hours") or []
        if not isinstance(часы, list) or not часы:
            raise ТарифНеВерен("часы пик — промежутки вида [1, 4] (с 01:00 до 04:00 UTC)")
        for промежуток in часы:
            if (not isinstance(промежуток, (list, tuple)) or len(промежуток) != 2
                    or not all(isinstance(ч, int) and not isinstance(ч, bool) for ч in промежуток)
                    or not 0 <= промежуток[0] < промежуток[1] <= 24):
                raise ТарифНеВерен("часы пик — промежутки вида [1, 4]: целые часы UTC от 0 до 24, начало раньше конца")
        дни = пик.get("weekdays", [0, 1, 2, 3, 4])
        if (not isinstance(дни, list) or not дни
                or not all(isinstance(д, int) and not isinstance(д, bool) and 0 <= д <= 6 for д in дни)):
            raise ТарифНеВерен("дни часов пик — номера от 0 (понедельник) до 6 (воскресенье)")
        чистый["peak"] = {"multiplier": множитель, "utc_hours": [list(п) for п in часы], "weekdays": sorted(set(дни))}
    источник = str(тариф.get("source") or "").strip()
    if len(источник) > 200:
        raise ТарифНеВерен("источник тарифа — до 200 знаков")
    дата = str(тариф.get("as_of") or "").strip()
    if дата and not _ДАТА.match(дата):
        raise ТарифНеВерен("дата тарифа — в виде дд.мм.гггг")
    чистый["source"] = источник or "задано администратором"
    чистый["as_of"] = дата
    return чистый


def _хост(адрес: str) -> str:
    try:
        return (urlparse((адрес or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def запись_справочника(модель, адрес: str = "", любой_адрес: bool = False) -> dict | None:
    """Строка справочника по модели и адресу точки. `любой_адрес=True` — только по имени модели (строки журнала,
    записанные до 15.10.26, адреса не хранят)."""
    имя = str(модель or "").strip().lower()
    if not имя:
        return None
    хост = _хост(адрес)
    for запись in СПРАВОЧНИК:
        if имя in запись["models"] and (любой_адрес or хост in запись["hosts"]):
            return запись
    return None


def тариф_справочника(модель, адрес: str = "", любой_адрес: bool = False) -> dict | None:
    запись = запись_справочника(модель, адрес, любой_адрес)
    return copy.deepcopy(запись["tariff"]) if запись else None


def тариф_точки(точка: dict | None, модель=None, адрес: str | None = None) -> tuple[dict | None, str]:
    """(тариф, откуда): «точка» — задан у точки администратором, «справочник» — по модели и адресу, «» — тарифа нет.
    Справочник тариф точки не перекрывает: если поле `tariff` у точки есть, берётся оно."""
    точка = точка or {}
    if точка.get("tariff"):
        return проверить_тариф(точка["tariff"]), "точка"
    найден = тариф_справочника(модель or точка.get("model"), точка.get("url", "") if адрес is None else адрес)
    return (найден, "справочник") if найден else (None, "")


def час_пик(момент_utc: datetime, пик: dict | None) -> bool:
    """Пришёлся ли вызов на часы пик: день недели и час — по UTC, промежуток [начало, конец)."""
    if not пик:
        return False
    if момент_utc.tzinfo is not None:
        момент_utc = момент_utc.astimezone(timezone.utc).replace(tzinfo=None)
    if момент_utc.weekday() not in пик.get("weekdays", [0, 1, 2, 3, 4]):
        return False
    час = момент_utc.hour + момент_utc.minute / 60 + момент_utc.second / 3600
    return any(начало <= час < конец for начало, конец in пик.get("utc_hours") or [])


def _целое(значение) -> int | None:
    if isinstance(значение, bool) or not isinstance(значение, (int, float)) or not math.isfinite(значение):
        return None
    return int(значение)


def токены(usage: dict | None) -> tuple[int | None, int | None, int | None]:
    """(вход, из кэша, выход) из ответа поставщика. Кэш: DeepSeek — `prompt_cache_hit_tokens` (или вход минус
    `prompt_cache_miss_tokens`), OpenAI-совместимые и OpenRouter — `prompt_tokens_details.cached_tokens`."""
    usage = usage if isinstance(usage, dict) else {}
    вход, выход = _целое(usage.get("prompt_tokens")), _целое(usage.get("completion_tokens"))
    подробно = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    из_кэша = _целое(подробно.get("cached_tokens"))
    if из_кэша is None:
        из_кэша = _целое(usage.get("prompt_cache_hit_tokens"))
    if из_кэша is None and вход is not None and _целое(usage.get("prompt_cache_miss_tokens")) is not None:
        из_кэша = max(0, вход - _целое(usage.get("prompt_cache_miss_tokens")))
    return вход, из_кэша, выход


def подпись_тарифа(тариф: dict) -> str:
    """«расчёт по тарифу <источник>, <дата>» — так стоимость подписана в журнале и на экране."""
    хвост = ", ".join(ч for ч in (тариф.get("source") or "", тариф.get("as_of") or "") if ч)
    return f"{РАСЧЁТ} {хвост}".strip()


def посчитать(вход: int | None, из_кэша: int | None, выход: int | None, тариф: dict,
              момент_utc: datetime) -> tuple[float | None, bool]:
    """(стоимость, пик ли) по формуле модуля. Токенов нет совсем — (None, False): считать не из чего."""
    if вход is None and выход is None:
        return None, False
    вход, выход = вход or 0, выход or 0
    из_кэша = min(max(из_кэша or 0, 0), вход)
    пик = час_пик(момент_utc, тариф.get("peak"))
    множитель = тариф["peak"]["multiplier"] if пик else 1.0
    сумма = ((вход - из_кэша) * тариф["input"] + из_кэша * тариф["input_cached"] + выход * тариф["output"]) / МИЛЛИОН
    return round(сумма * множитель, 8), пик


def стоимость_поставщика(usage: dict | None) -> float | None:
    """Число, которое поставщик вернул сам (`usage.cost`); строка, NaN, true — не число."""
    значение = (usage or {}).get("cost") if isinstance(usage, dict) else None
    if isinstance(значение, bool) or not isinstance(значение, (int, float)) or not math.isfinite(значение):
        return None
    return float(значение)


def стоимость_вызова(usage: dict | None, тариф: dict | None, момент_utc: datetime | None = None) -> dict:
    """Поля для строки журнала: cost_usd, cost_source, cached_tokens и (у расчёта) peak."""
    момент_utc = момент_utc or datetime.now(timezone.utc)
    вход, из_кэша, выход = токены(usage)
    итог = {"cached_tokens": из_кэша}
    своя = стоимость_поставщика(usage)
    if своя is not None:
        итог.update(cost_usd=своя, cost_source=ПОСТАВЩИК)
        return итог
    if тариф:
        сумма, пик = посчитать(вход, из_кэша, выход, тариф, момент_utc)
        if сумма is not None:
            итог.update(cost_usd=сумма, cost_source=подпись_тарифа(тариф), peak=пик)
            return итог
    итог.update(cost_usd=None, cost_source=ТАРИФ_НЕ_ЗАДАН)
    return итог


# --- Строки журнала и сводка для панели ------------------------------------------------------------------------

def _момент_строки(строка: dict, время_utc: bool) -> datetime | None:
    """Время строки журнала в UTC (наивное). ERP пишет UTC, Планёрка — местное время машины."""
    try:
        момент = datetime.fromisoformat(str(строка.get("ts") or "").strip())
    except ValueError:
        return None
    if момент.tzinfo is not None:
        return момент.astimezone(timezone.utc).replace(tzinfo=None)
    if время_utc:
        return момент
    return момент.astimezone(timezone.utc).replace(tzinfo=None)      # наивное местное → UTC по поясу машины


def стоимость_строки(строка: dict, время_utc: bool = True) -> tuple[float | None, str]:
    """(стоимость, вид) строки журнала; вид — «поставщик», «расчёт», «не задан».

    Строка, записанная до 15.10.26, не знает, откуда её цифра: число в `cost_usd` — от поставщика; пусто, а модель есть
    в справочнике — расчёт задним числом (по имени модели, адреса в такой строке нет; кэш в строках ERP до 15.10.26
    не записан, поэтому весь вход считается мимо кэша — сумма выходит верхней оценкой)."""
    цена = строка.get("cost_usd")
    число = None if isinstance(цена, bool) or not isinstance(цена, (int, float)) or not math.isfinite(цена) else float(цена)
    источник = str(строка.get("cost_source") or "")
    if источник:
        if число is None:
            return None, "не задан"
        return число, ("поставщик" if источник == ПОСТАВЩИК else "расчёт")
    if число is not None:
        return число, "поставщик"
    тариф = тариф_справочника(строка.get("model"), любой_адрес=True)
    момент = _момент_строки(строка, время_utc)
    if тариф and момент is not None:
        вход = _целое(строка.get("prompt_tokens"))
        выход = _целое(строка.get("completion_tokens"))
        сумма, _ = посчитать(вход, _целое(строка.get("cached_tokens")), выход, тариф, момент)
        if сумма is not None:
            return сумма, "расчёт"
    return None, "не задан"


def деньги(сумма: float | None) -> str:
    """«0,04 $»: два знака после запятой; сумма меньше цента — до четырёх знаков, чтобы не показать ноль там, где он не
    ноль («0,0034 $»)."""
    if сумма is None:
        return "—"
    if сумма and abs(сумма) < 0.005:
        текст = f"{сумма:.4f}".rstrip("0")
    else:
        текст = f"{сумма:.2f}"
    return текст.replace(".", ",") + " $"


def дата(момент: datetime) -> str:
    return момент.strftime("%d.%m.%Y")


def _пусто() -> dict:
    return {"calls": 0, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0, "cost_usd": 0.0,
            "estimated_usd": 0.0, "provider_usd": 0.0, "no_tariff_calls": 0, "cache_unknown_calls": 0}


def _добавить(корзина: dict, строка: dict, сумма: float | None, вид: str) -> None:
    корзина["calls"] += 1
    вход = _целое(строка.get("prompt_tokens")) or 0
    кэш = _целое(строка.get("cached_tokens"))
    корзина["tokens_in"] += вход
    корзина["tokens_out"] += _целое(строка.get("completion_tokens")) or 0
    if кэш is None:
        корзина["cache_unknown_calls"] += 1
    else:
        корзина["tokens_cached"] += min(кэш, вход) if вход else кэш
    if вид == "не задан":
        корзина["no_tariff_calls"] += 1
        return
    корзина["cost_usd"] += сумма or 0.0
    корзина["estimated_usd" if вид == "расчёт" else "provider_usd"] += сумма or 0.0


def _подпись(корзина: dict) -> str:
    """Сумма с пометкой: «расчётная по тарифу», если расчёт есть; у смешанной — сколько из неё расчётная."""
    сумма, расчёт = корзина["cost_usd"], корзина["estimated_usd"]
    текст = деньги(сумма)
    if расчёт > 0 and корзина["provider_usd"] > 0:
        текст += f" · из них расчётная по тарифу {деньги(расчёт)}"
    elif расчёт > 0:
        текст += " · расчётная по тарифу"
    if корзина["no_tariff_calls"]:
        текст += f" · вызовов без стоимости (тариф не задан): {корзина['no_tariff_calls']}"
    return текст


def _отдать(корзина: dict, **сверху) -> dict:
    итог = dict(сверху)
    итог.update({к: (round(в, 6) if isinstance(в, float) else в) for к, в in корзина.items()})
    итог["money"] = деньги(корзина["cost_usd"])
    итог["estimated"] = корзина["estimated_usd"] > 0
    итог["label"] = _подпись(корзина)
    итог["tokens"] = (f"вход {корзина['tokens_in']:,} · из кэша {корзина['tokens_cached']:,} · "
                      f"выход {корзина['tokens_out']:,}").replace(",", " ")
    return итог


def сводка(строки, сейчас_utc: datetime | None = None, время_utc: bool = True, встреч: int = 10) -> dict:
    """Расход для панели: сегодня / 7 / 30 дней (дни по Москве), по встречам, по моделям и по точкам — токены и деньги,
    пометка «расчётная по тарифу» и строка «тариф не задан» с числом таких вызовов. Строки — из `llm_calls.jsonl`;
    строки об остановке по пределу и битые пропускаются. `время_utc` — пишет ли продукт время строки в UTC (ERP) или
    местное (Планёрка)."""
    сейчас_utc = сейчас_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    if сейчас_utc.tzinfo is not None:
        сейчас_utc = сейчас_utc.astimezone(timezone.utc).replace(tzinfo=None)
    сегодня = (сейчас_utc + МОСКВА).date()
    периоды = {"today": _пусто(), "7": _пусто(), "30": _пусто()}
    по_встречам: dict = {}
    по_моделям: dict = {}
    по_точкам: dict = {}
    тарифы: set = set()
    задним_числом = 0
    проб = 0
    for строка in строки:
        if not isinstance(строка, dict) or строка.get("stopped_by_limit"):
            continue
        момент = _момент_строки(строка, время_utc)
        if момент is None:
            continue
        день = (момент + МОСКВА).date()
        дней_назад = (сегодня - день).days
        if дней_назад < 0 or дней_назад >= 30:
            continue
        if строка.get("purpose") == "probe":
            проб += 1            # пробный запрос перед сборкой: токенов поставщика в его строке нет — в деньги не входит
            continue
        сумма, вид = стоимость_строки(строка, время_utc)
        if вид == "расчёт":
            if строка.get("cost_source"):
                тарифы.add(str(строка["cost_source"]))
            else:
                задним_числом += 1
                тариф = тариф_справочника(строка.get("model"), любой_адрес=True) or {}
                тарифы.add(подпись_тарифа(тариф) + f" ({ЗАДНИМ_ЧИСЛОМ})")
        _добавить(периоды["30"], строка, сумма, вид)
        if дней_назад < 7:
            _добавить(периоды["7"], строка, сумма, вид)
        if дней_назад == 0:
            _добавить(периоды["today"], строка, сумма, вид)
        mid = строка.get("meeting_id")
        if isinstance(mid, (int, str)) and not isinstance(mid, bool) and str(mid) != "":
            запись = по_встречам.setdefault(str(mid), {"корзина": _пусто(), "последний": момент})
            запись["последний"] = max(запись["последний"], момент)
            _добавить(запись["корзина"], строка, сумма, вид)
        модель = строка.get("model") if isinstance(строка.get("model"), str) and строка.get("model") else "—"
        _добавить(по_моделям.setdefault(модель, _пусто()), строка, сумма, вид)
        точка = строка.get("route") if isinstance(строка.get("route"), str) and строка.get("route") else "не записана"
        _добавить(по_точкам.setdefault(точка, _пусто()), строка, сумма, вид)
    заголовки = {"today": f"Сегодня, {дата(datetime.combine(сегодня, datetime.min.time()))}",
                 "7": "За 7 дней", "30": "За 30 дней"}
    встречи = sorted(по_встречам.items(), key=lambda п: п[1]["последний"], reverse=True)[:встреч]
    без_тарифа = периоды["30"]["no_tariff_calls"]
    return {
        "periods": [_отдать(периоды[к], key=к, title=заголовки[к]) for к in ("today", "7", "30")],
        "by_meeting": [_отдать(в["корзина"], meeting_id=mid, last_call=дата(в["последний"] + МОСКВА))
                       for mid, в in встречи],
        "by_model": [_отдать(к, model=м) for м, к in sorted(по_моделям.items(), key=lambda п: -п[1]["cost_usd"])],
        "by_route": [_отдать(к, route=т) for т, к in sorted(по_точкам.items(), key=lambda п: -п[1]["cost_usd"])],
        "no_tariff": {"calls": без_тарифа,
                      "label": (f"тариф не задан — вызовов за 30 дней: {без_тарифа}; поставщик стоимость не вернул, "
                                "тарифа у точки нет, в деньги эти вызовы не вошли") if без_тарифа
                      else "тариф не задан — вызовов за 30 дней: 0"},
        "tariffs": sorted(тарифы),
        "backdated_calls": задним_числом,
        "probes": {"calls": проб,
                   "label": (f"пробных запросов перед сборкой за 30 дней: {проб}; токены пробы в журнал не пишутся, "
                             "в деньги они не вошли") if проб else ""},
        "note": ПОЯСНЕНИЕ + " " + ПОДСКАЗКА_ПИКА,
        "as_of": дата(сейчас_utc + МОСКВА),
    }


# --- Поле формы «Модели»: тариф строкой и обратно -----------------------------------------------------------------

def _как_число(текст: str, что: str) -> float:
    try:
        return float(текст.strip().replace(",", ".").replace(" ", "").replace("$", ""))
    except ValueError as exc:
        raise ТарифНеВерен(f"{что}: «{текст.strip()}» — не число") from exc


def _число_строкой(значение: float) -> str:
    """0.6 → «0,60», 0.003 → «0,003»: не меньше двух знаков после запятой, как цены в прейскуранте."""
    текст = f"{значение:.6f}".rstrip("0")
    целая, _, дробь = текст.partition(".")
    return f"{целая},{дробь.ljust(2, '0')}"


def тариф_в_поля(тариф: dict | None) -> dict:
    """Тариф → два поля формы: «вход / из кэша / выход» и «часы пик» («1-4, 6-10 ×2»)."""
    if not тариф:
        return {"tariff_prices": "", "tariff_peak": ""}
    цены = " / ".join(_число_строкой(тариф[к]) for к in ("input", "input_cached", "output"))
    пик = тариф.get("peak") or {}
    часы = ", ".join(f"{н}-{к}" for н, к in пик.get("utc_hours") or [])
    return {"tariff_prices": цены,
            "tariff_peak": f"{часы} ×{пик['multiplier']:g}".replace(".", ",") if часы else ""}


def тариф_из_полей(цены: str, пик: str, источник: str = "", дата_тарифа: str = "") -> dict | None:
    """Два поля формы → тариф точки; пустые цены — тарифа у точки нет (тогда работает справочник)."""
    цены, пик = (цены or "").strip(), (пик or "").strip()
    if not цены:
        if пик:
            raise ТарифНеВерен("часы пик заданы, а цен нет — заполните «вход / из кэша / выход»")
        return None
    части = [ч for ч in re.split(r"[/;]", цены) if ч.strip()]
    if len(части) != 3:
        raise ТарифНеВерен("тариф — три числа через «/»: вход / из кэша / выход, например 0,15 / 0,003 / 0,60")
    тариф = {"input": _как_число(части[0], "цена входа"), "input_cached": _как_число(части[1], "цена входа из кэша"),
             "output": _как_число(части[2], "цена выхода"), "currency": "USD"}
    if пик:
        найден = re.match(r"^(.*?)[×xх*]\s*([\d.,]+)\s*$", пик)
        if not найден:
            raise ТарифНеВерен("часы пик — промежутки часов UTC и множитель, например «1-4, 6-10 ×2»")
        промежутки = []
        for кусок in [к for к in re.split(r"[,;]", найден.group(1)) if к.strip()]:
            м = re.match(r"^\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*$", кусок)
            if not м:
                raise ТарифНеВерен(f"часы пик: «{кусок.strip()}» — нужно «начало-конец», например 1-4")
            промежутки.append([int(м.group(1)), int(м.group(2))])
        тариф["peak"] = {"multiplier": _как_число(найден.group(2), "множитель часов пик"), "utc_hours": промежутки,
                         "weekdays": [0, 1, 2, 3, 4]}
    тариф["source"] = источник or "задано администратором"
    тариф["as_of"] = дата_тарифа or datetime.now().strftime("%d.%m.%Y")
    return проверить_тариф(тариф)


def те_же_цены(а: dict | None, б: dict | None) -> bool:
    """Совпадают ли цены и часы пик (источник и дата не в счёт)."""
    if not а or not б:
        return False
    ключи = ("input", "input_cached", "output")
    if any(abs(float(а[к]) - float(б[к])) > 1e-12 for к in ключи):
        return False
    па, пб = а.get("peak") or {}, б.get("peak") or {}
    return (bool(па) == bool(пб)) and (not па or (abs(па["multiplier"] - пб["multiplier"]) < 1e-12
                                                  and [list(x) for x in па["utc_hours"]] == [list(x) for x in пб["utc_hours"]]
                                                  and sorted(па.get("weekdays", [])) == sorted(пб.get("weekdays", []))))


def справочник_для_формы() -> list[dict]:
    """Справочник для пульта «Модели»: по нему форма предзаполняет тариф новой точки."""
    return [{"title": з["title"], "hosts": list(з["hosts"]), "models": list(з["models"]),
             "source": з["tariff"]["source"], "as_of": з["tariff"]["as_of"], **тариф_в_поля(проверить_тариф(з["tariff"]))}
            for з in СПРАВОЧНИК]


# --- Предел расхода в месяц по поставщику (решение владельца 15.10.26) ---------------------------------------------
#
# Порог платных прогонов — отдельно по поставщикам, не складывать. Предел задаётся у точки в «Моделях» («Предел
# расхода в месяц, $») и действует на поставщика целиком (все его точки). Нет предела — система только считает и
# показывает потраченное. Есть — на 90 % предупреждение, на 100 % платные вызовы ЭТОГО поставщика останавливаются,
# другой поставщик продолжает. Месяц — календарный, по Москве; расход — из журнала вызовов этой системы.

ПОРОГ_ПРЕДУПРЕЖДЕНИЯ = 90
OPENROUTER = "openrouter.ai"
НАЗВАНИЯ_ПОСТАВЩИКОВ = {"api.deepseek.com": "DeepSeek", OPENROUTER: "OpenRouter", "api.z.ai": "Z.ai",
                        "open.bigmodel.cn": "BigModel", "api.openai.com": "OpenAI",
                        "dashscope-intl.aliyuncs.com": "Alibaba DashScope", "api.anthropic.com": "Anthropic"}


def поставщик(род: str, адрес: str = "") -> str:
    """Кто выставит счёт: OpenRouter — по роду точки, остальные — по адресу (имя сервера)."""
    return OPENROUTER if род == "openrouter" else _хост(адрес)


def название_поставщика(поставщик_id: str) -> str:
    return НАЗВАНИЯ_ПОСТАВЩИКОВ.get(поставщик_id or "", поставщик_id or "не определён")


def предел_из_текста(текст) -> float | None:
    """«20» / «20,5» → число долларов; пусто → None. Не число или не больше нуля — `ТарифНеВерен`."""
    if текст is None or (isinstance(текст, str) and not текст.strip()):
        return None
    if isinstance(текст, bool):
        raise ТарифНеВерен("предел расхода в месяц — число долларов больше нуля")
    try:
        значение = float(str(текст).strip().replace(",", ".").replace(" ", "").replace("$", ""))
    except ValueError:
        raise ТарифНеВерен("предел расхода в месяц — число долларов больше нуля, например 20") from None
    if not math.isfinite(значение) or значение <= 0:
        raise ТарифНеВерен("предел расхода в месяц — число долларов больше нуля, например 20")
    return значение


def поставщик_строки(строка: dict) -> str | None:
    """Поставщик строки журнала: записан с 15.10.26; у прежних строк — по модели (справочник — DeepSeek, имя
    с «/» — каталог OpenRouter); иначе неизвестно."""
    if строка.get("provider"):
        return str(строка["provider"])
    запись = запись_справочника(строка.get("model"), любой_адрес=True)
    if запись:
        return запись["hosts"][0]
    if "/" in str(строка.get("model") or ""):
        return OPENROUTER
    return None


def расход_по_поставщикам(строки, сейчас_utc: datetime | None = None, время_utc: bool = True) -> dict:
    """Потрачено за текущий календарный месяц (по Москве) — по поставщику, в долларах."""
    сейчас_utc = сейчас_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    if сейчас_utc.tzinfo is not None:
        сейчас_utc = сейчас_utc.astimezone(timezone.utc).replace(tzinfo=None)
    месяц = (сейчас_utc + МОСКВА).strftime("%Y-%m")
    итог: dict = {}
    for строка in строки:
        if not isinstance(строка, dict) or строка.get("stopped_by_limit") or строка.get("purpose") == "probe":
            continue
        момент = _момент_строки(строка, время_utc)
        if момент is None or (момент + МОСКВА).strftime("%Y-%m") != месяц:
            continue
        кто = поставщик_строки(строка)
        сумма, вид = стоимость_строки(строка, время_utc)
        if not кто or вид == "не задан":
            continue
        итог[кто] = итог.get(кто, 0.0) + (сумма or 0.0)
    return итог


def состояние_предела(поставщик_id: str, потрачено: float, предел: float | None) -> dict:
    """Строка мониторинга и решение по одному поставщику: ok / warn (≥ 90 %) / stop (≥ 100 %) / без предела."""
    название = название_поставщика(поставщик_id)
    if not предел:
        return {"provider": поставщик_id, "title": название, "spent_usd": round(потрачено, 6), "limit_usd": None,
                "share_percent": None, "state": "no_limit",
                "label": f"{название}: потрачено за месяц {деньги(потрачено)} (предел не задан)"}
    доля = 100 * потрачено / предел
    состояние = "stop" if доля >= 100 else "warn" if доля >= ПОРОГ_ПРЕДУПРЕЖДЕНИЯ else "ok"
    текст = f"{название}: потрачено за месяц {деньги(потрачено)} из {деньги(предел)} ({доля:.0f} %)"
    if состояние == "warn":
        текст += f" — предупреждение: пройдено {ПОРОГ_ПРЕДУПРЕЖДЕНИЯ} % предела"
    elif состояние == "stop":
        текст += f" — предел исчерпан, платные вызовы через {название} остановлены до следующего месяца"
    return {"provider": поставщик_id, "title": название, "spent_usd": round(потрачено, 6), "limit_usd": предел,
            "share_percent": round(доля), "state": состояние, "label": текст}


def текст_остановки(состояние: dict) -> str:
    """Что видит человек, когда предел поставщика исчерпан."""
    return (f"Предел расхода {состояние['title']} на месяц исчерпан: потрачено {деньги(состояние['spent_usd'])} из "
            f"{деньги(состояние['limit_usd'])}. Платные вызовы через {состояние['title']} остановлены до следующего "
            "месяца; другие подключения работают. Поднять предел может супер-администратор в «Моделях».")


_журнал_кэш: dict = {}


def строки_журнала(путь) -> list[dict]:
    """Строки журнала вызовов — с памятью по времени и размеру файла: проверка предела идёт перед каждым платным
    вызовом, перечитывать файл целиком каждый раз незачем."""
    from pathlib import Path
    путь = Path(путь)
    try:
        отметка = путь.stat()
    except OSError:
        return []
    ключ = (str(путь), отметка.st_mtime_ns, отметка.st_size)
    if _журнал_кэш.get("ключ") == ключ:
        return _журнал_кэш["строки"]
    строки = []
    for line in путь.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            строки.append(row)
    _журнал_кэш.update(ключ=ключ, строки=строки)
    return строки
