"""Проверка в тень: qwen3.8 на spark-1 проверяет тот же черновик, что и основная проверка.

Решение владелицы 24.11.2026: три дня (24–26.11.2026) смотреть, как работает qwen3.8 в роли проверяющей,
и сравнивать её находки с находками основной модели. Тень НИЧЕГО не меняет: ни вердикт, ни протокол, ни
карточки, ни очередь пересборки. Её единственный след — строка в `data/logs/shadow_verify.jsonl`
(рядом с журналом вызовов `llm_calls.jsonl`).

Контроль по шагам: каждая строка журнала — один шаг проверки (черновик, части, находки, время, сбой).
Сводка по шагам — `сводка()` и `python scripts/shadow_verify_report.py`.

Выключатели:
* `SHADOW_VERIFY=0` (или `off`, `false`, `нет`) — тень не считается вовсе;
* `SHADOW_VERIFY_UNTIL=2026-11-27T00:00:00` — до какого времени включена (по умолчанию до 27.11, 00:00);
* `SHADOW_VERIFY_POINT` — имя точки в `models.json` (по умолчанию `spark-qwen3.8-27b`);
* `WEBAPP_SHADOW_VERIFY_PATH` — свой файл журнала (для тестов), иначе `data/logs/shadow_verify.jsonl`.

Тень не должна ронять сборку: любая её ошибка ловится и пишется в журнал как `ошибка`.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ТОЧКА_ПО_УМОЛЧАНИЮ = "spark-qwen3.8-27b"
ДО_ПО_УМОЛЧАНИЮ = "2026-11-27T00:00:00"      # 24, 25, 26.11 — три полных дня
ВЫКЛЮЧЕНО = {"0", "off", "false", "нет", "no"}
МАКС_ТОКЕНОВ = 8000                            # столько же, сколько уточке spark в models.json
ТАЙМАУТ = 240                                  # локальная модель на длинном протоколе думает долго
ПОХОЖЕ = 0.55                                  # цитаты считаются одной находкой от этого сходства


# --- включение -------------------------------------------------------------------------------

def _когда(значение: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(значение).strip())
    except (TypeError, ValueError):
        return None


def включена(сейчас: datetime | None = None) -> bool:
    режим = str(os.environ.get("SHADOW_VERIFY", "1")).strip().lower()
    if режим in ВЫКЛЮЧЕНО:
        return False
    до = _когда(os.environ.get("SHADOW_VERIFY_UNTIL") or ДО_ПО_УМОЛЧАНИЮ)
    if до is None:
        return True
    return (сейчас or datetime.now()) < до


# --- настройки точки -------------------------------------------------------------------------

def _models_path() -> Path:
    """Файл маршрутов: свой (env), из приложения Планёрки или рядом с рабочей папкой ERP.

    Один и тот же файл модуля лежит и в `planerka/webapp/app/services/`, и в `system/scripts/` (ERP),
    поэтому путь ищется без опоры на пакет: сначала явный `SHADOW_VERIFY_MODELS`, потом маршруты
    приложения, потом `webapp/data/models.json` вверх по дереву."""
    свой = (os.environ.get("SHADOW_VERIFY_MODELS") or os.environ.get("MODEL_ROUTES_PATH") or "").strip()
    if свой:
        return Path(свой)
    try:
        from . import model_routes
        путь = model_routes.routes_path()
        if путь is not None:
            return Path(путь)
    except Exception:  # noqa: BLE001 — вне пакета приложения относительного импорта нет
        pass
    for корень in Path(__file__).resolve().parents:
        for хвост in (("webapp", "data", "models.json"), ("data", "models.json")):
            файл = корень.joinpath(*хвост)
            if файл.exists():
                return файл
    raise RuntimeError("models.json не найден — точка тени не задана")


def _ключ(точка: dict) -> str:
    if точка.get("key_source") == "env" and точка.get("key_env"):
        return os.environ.get(str(точка["key_env"]), "")
    if точка.get("key_source") == "value":
        файл = _models_path().parent / "model_keys.local.json"
        try:
            ключи = json.loads(файл.read_text(encoding="utf-8")).get("keys") or {}
        except (OSError, ValueError):
            return ""
        return str(ключи.get(точка.get("name") or "", "") or "")
    return ""


def настройки() -> dict:
    """Адрес, модель, ключ точки тени. Ничего не пишет и не меняет.

    Имена точки в трёх системах разные (`spark-qwen3.8-27b` в Планёрке и ERP, `qwen3.8-27b`
    в MeetFlow), поэтому берётся первое найденное; явное имя — `SHADOW_VERIFY_POINT`."""
    данные = json.loads(_models_path().read_text(encoding="utf-8"))
    заданное = (os.environ.get("SHADOW_VERIFY_POINT") or "").strip()
    имена = (заданное,) if заданное else (ТОЧКА_ПО_УМОЛЧАНИЮ, "qwen3.8-27b")
    точки = данные.get("endpoints") or {}
    имя = next((и for и in имена if isinstance(точки.get(и), dict)), "")
    if not имя:
        raise RuntimeError(f"точка тени не найдена в models.json (искали: {', '.join(имена)})")
    точка = точки[имя]
    адрес = str(точка.get("url") or "").rstrip("/")
    модель = str(точка.get("model") or "")
    if not адрес or not модель:
        raise RuntimeError(f"у точки «{имя}» не заданы адрес или модель")
    return {"имя": имя, "url": адрес, "model": модель, "ключ": _ключ({**точка, "name": имя}),
            "max_tokens": int(точка.get("max_tokens") or МАКС_ТОКЕНОВ)}


# --- журнал ----------------------------------------------------------------------------------

def путь_журнала() -> Path:
    свой = (os.environ.get("WEBAPP_SHADOW_VERIFY_PATH") or "").strip()
    if свой:
        return Path(свой)
    каталог = os.environ.get("WEBAPP_LOG_DIR")
    if каталог:
        return Path(каталог) / "shadow_verify.jsonl"
    for корень in Path(__file__).resolve().parents:
        for хвост in (("data", "logs"), ("webapp", "data", "logs")):
            место = корень.joinpath(*хвост)
            if место.is_dir():
                return место / "shadow_verify.jsonl"
    return Path(__file__).resolve().parents[2] / "data" / "logs" / "shadow_verify.jsonl"


def записать(строка: dict) -> None:
    путь = путь_журнала()
    путь.parent.mkdir(parents=True, exist_ok=True)
    with open(путь, "a", encoding="utf-8") as фх:
        фх.write(json.dumps(строка, ensure_ascii=False) + "\n")


# --- ответ модели ----------------------------------------------------------------------------

def _json_из_текста(текст: str) -> dict:
    """Первый JSON-объект ответа: без markdown-заборов и пояснений вокруг."""
    чистый = (текст or "").strip()
    чистый = re.sub(r"^```(?:json)?\s*|\s*```$", "", чистый, flags=re.I).strip()
    try:
        данные = json.loads(чистый)
        if isinstance(данные, dict):
            return данные
    except ValueError:
        pass
    начало = чистый.find("{")
    глубина = 0
    в_строке = False
    экран = False
    for место in range(начало, len(чистый)):
        символ = чистый[место]
        if в_строке:
            if экран:
                экран = False
            elif символ == "\\":
                экран = True
            elif символ == '"':
                в_строке = False
            continue
        if символ == '"':
            в_строке = True
        elif символ == "{":
            глубина += 1
        elif символ == "}":
            глубина -= 1
            if глубина == 0:
                try:
                    данные = json.loads(чистый[начало:место + 1])
                except ValueError:
                    break
                if isinstance(данные, dict):
                    return данные
                break
    raise ValueError("ответ не в формате JSON")


def _вызов(настройки_точки: dict, system: str, user: str) -> dict:
    тело = {"model": настройки_точки["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "max_tokens": настройки_точки["max_tokens"],
            "reasoning_effort": "none"}
    заголовки = {"Content-Type": "application/json"}
    if настройки_точки.get("ключ"):
        заголовки["Authorization"] = "Bearer " + настройки_точки["ключ"]
    запрос = urllib.request.Request(настройки_точки["url"].rstrip("/") + "/v1/chat/completions",
                                    data=json.dumps(тело, ensure_ascii=False).encode("utf-8"),
                                    headers=заголовки, method="POST")
    # Своя открывашка без прокси: spark-1 во внутренней сети, системный прокси ему не нужен и вреден.
    открывашка = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with открывашка.open(запрос, timeout=ТАЙМАУТ) as ответ:
        данные = json.loads(ответ.read().decode("utf-8", "replace"))
    выбор = (данные.get("choices") or [{}])[0]
    текст = (выбор.get("message") or {}).get("content") or ""
    return {"verdict": _json_из_текста(текст), "usage": данные.get("usage") or {},
            "finish": выбор.get("finish_reason")}


# --- сравнение находок -----------------------------------------------------------------------

_ЗНАКИ = re.compile(r"[^\wа-яё]+", re.I)


def _норма(текст: str) -> str:
    return " ".join(_ЗНАКИ.sub(" ", (текст or "").lower()).split())


def _находки(вердикт) -> list[dict]:
    if not isinstance(вердикт, dict):
        return []
    return [f for f in (вердикт.get("findings") or []) if isinstance(f, dict)]


def _цитата(находка: dict) -> str:
    return _норма(находка.get("quote") or находка.get("цитата") or "")


def совпадения(основные: list[dict], теневые: list[dict]) -> dict:
    """Сколько находок тени повторяют основные: по цитате (0,55 сходства) или по замечанию."""
    свободные = list(range(len(основные)))
    совпало = 0
    for т in теневые:
        цитата = _цитата(т)
        замечание = _норма(т.get("issue") or т.get("note") or т.get("замечание") or "")
        найдено = None
        for место in свободные:
            о = основные[место]
            о_цитата = _цитата(о)
            if цитата and о_цитата:
                сходство = difflib.SequenceMatcher(None, цитата, о_цитата).ratio()
                if сходство >= ПОХОЖЕ:
                    найдено = место
                    break
            elif замечание:
                о_замечание = _норма(о.get("issue") or о.get("note") or о.get("замечание") or "")
                if о_замечание and difflib.SequenceMatcher(None, замечание, о_замечание).ratio() >= 0.7:
                    найдено = место
                    break
        if найдено is not None:
            свободные.remove(найдено)
            совпало += 1
    return {"совпало": совпало, "только_тень": len(теневые) - совпало,
            "только_основная": len(основные) - совпало}


# --- главный шаг -----------------------------------------------------------------------------

def прогнать(*, system: str, пользователь: str, label: str, основной: dict | None,
             части: list[tuple[str, str]] | None = None, источник: str = "planerka",
             meeting_id: int | None = None, точка: str = "", модель: str = "") -> dict | None:
    """Один шаг тени. Возвращает записанную строку или None, если тень выключена.

    `части` — те же куски, что проверяла основная: [(заголовок, текст), …]. Если их нет, идёт
    один вызов на весь черновик. Сбой любой части не мешает остальным: он попадает в `сбои`.
    """
    if not включена():
        return None
    начало = time.monotonic()
    строка = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "источник": источник,
              "label": str(label or "")[:300], "meeting_id": meeting_id,
              "основная": {"точка": точка, "модель": модель,
                            "чисто": (основной or {}).get("clean"),
                            "находок": len(_находки(основной)),
                            "сбой": bool((основной or {}).get("verifier_failed"))}}
    try:
        настройки_точки = настройки()
        строка["тень"] = {"точка": настройки_точки["имя"], "модель": настройки_точки["model"],
                          "max_tokens": настройки_точки["max_tokens"]}
        if точка and точка.strip() == настройки_точки["имя"]:
            # Тень и основная — одна и та же точка: второй такой же вызов ничего не сравнивает, только
            # удваивает время сборки. Так бывает, когда основная модель недоступна и цепочка ушла на тень.
            строка.update({"пропуск": "тень совпадает с основной точкой", "частей": 0, "находок": 0})
            строка["мс"] = int((time.monotonic() - начало) * 1000)
            записать(строка)
            return строка
        находки: list[dict] = []
        сбои: list[str] = []
        куски = части or [("", пользователь)]
        for номер, (_заголовок, текст) in enumerate(куски, 1):
            try:
                ответ = _вызов(настройки_точки, system, текст)
            except (urllib.error.URLError, socket.timeout, OSError, ValueError, RuntimeError) as ошибка:
                сбои.append(f"часть {номер}: {type(ошибка).__name__}: {str(ошибка)[:160]}")
                continue
            вердикт = ответ["verdict"]
            for находка in _находки(вердикт)[:20]:
                находки.append({k: находка.get(k) for k in ("category", "quote", "issue", "note")
                                if находка.get(k) is not None})
        строка["частей"] = len(куски)
        строка["находок"] = len(находки)
        if находки:
            строка["чисто"] = False
        else:
            строка["чисто"] = None if сбои else True
        строка["сбои"] = сбои or None
        строка.update(совпадения(_находки(основной), находки))
        строка["находки"] = находки[:20]
        строка["ошибка"] = None
    except Exception as ошибка:  # noqa: BLE001 — тень не должна ронять сборку
        строка["ошибка"] = f"{type(ошибка).__name__}: {str(ошибка)[:300]}"
    строка["мс"] = int((time.monotonic() - начало) * 1000)
    try:
        записать(строка)
    except OSError:
        pass
    return строка


# --- сводка по шагам -------------------------------------------------------------------------

def сводка(путь: Path | str | None = None, дней: int = 3) -> dict:
    """Итог по журналу за последние `дней`: шаги, сбои, находки, совпадения с основной."""
    файл = Path(путь) if путь else путь_журнала()
    if not файл.exists():
        return {"файл": str(файл), "шагов": 0, "строки": []}
    граница = time.time() - дней * 86400
    шаги = []
    for строка in файл.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            запись = json.loads(строка)
            момент = datetime.fromisoformat(запись["ts"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        if момент >= граница:
            шаги.append(запись)
    итог = {"файл": str(файл), "шагов": len(шаги),
            "сбоев": sum(1 for ш in шаги if ш.get("сбои") or ш.get("ошибка")),
            "находок_тени": sum(int(ш.get("находок") or 0) for ш in шаги),
            "совпало": sum(int(ш.get("совпало") or 0) for ш in шаги),
            "только_тень": sum(int(ш.get("только_тень") or 0) for ш in шаги),
            "только_основная": sum(int(ш.get("только_основная") or 0) for ш in шаги),
            "среднее_мс": (sum(int(ш.get("мс") or 0) for ш in шаги) // len(шаги)) if шаги else 0,
            "строки": шаги}
    return итог
