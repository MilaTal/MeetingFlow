# -*- coding: utf-8 -*-
"""Тяжёлый шаг на процессоре — в отдельном процессе, чтобы сервер отвечал (25.10.2026, замечание локальной машины).

Повод. На стенде ERP без видеокарты разделение записи 6 минут по голосам шло 373 с, и всё это время сервер не отвечал
даже на `/health` (`ConnectionError`), после — ожил. Разделение и так шло не в обработчике запроса, а в фоновом потоке
очереди распознавания, но поток делит с сервером один интерпретатор: разбор по голосам на процессоре почти всё время
держит общую блокировку Python, и потокам сервера не достаётся хода. Отдельный поток здесь не помогает — нужен отдельный
процесс: у него своя блокировка, сервер своей не делит ни с кем.

Как. `выполнить(функция, *аргументы)` запускает функцию в дочернем процессе (способ `spawn` — одинаково на Windows и
Linux), ждёт результат и возвращает его; исключение дочернего процесса поднимается здесь же, как будто функция вызвана
на месте, — вызывающий ловит его тем же `except`, что и раньше. Функция и аргументы передаются по имени модуля, поэтому
годится только функция уровня модуля. Подменённая в тестах функция (лямбда, вложенная) по имени не находится — она
выполняется на месте, как раньше; переменная `WEBAPP_HEAVY_IN_PROCESS=off` выключает отдельный процесс совсем
(тесты, отладка). Файл одинаков в ERP и Планёрке до байта."""
from __future__ import annotations

import concurrent.futures
import multiprocessing
import ctypes
import json
import os
import sys
from pathlib import Path

ПЕРЕМЕННАЯ = "MEETFLOW_HEAVY_IN_PROCESS"


def включено() -> bool:
    """Отдельный процесс включён (по умолчанию да); off/0/no/нет — шаг выполняется на месте."""
    return os.environ.get(ПЕРЕМЕННАЯ, "on").strip().lower() not in ("off", "0", "no", "false", "нет")


def по_имени(функция) -> bool:
    """Найдёт ли дочерний процесс функцию по имени модуля: только так её можно передать в другой процесс."""
    модуль = sys.modules.get(getattr(функция, "__module__", "") or "")
    имя = getattr(функция, "__qualname__", "") or ""
    if модуль is None or not имя or "<" in имя:
        return False
    объект = модуль
    for часть in имя.split("."):
        объект = getattr(объект, часть, None)
        if объект is None:
            return False
    return объект is функция


# --- стартовая уборка осиротевших детей (11.11.2026) -----------------------------------------------------
# Внешнее убийство сервера оставляет работника жить (09.11 — 40 616 с CPU). Пишем PID и время создания;
# перед новым тяжёлым шагом снимаем тех, чей родитель мёртв, время создания совпадает ±2 с.
ФАЙЛ_ДЕТЕЙ = Path(__file__).resolve().parents[2] / "data" / "logs" / "heavy_children.json"


def _жив(pid: int) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    код = ctypes.c_ulong()
    ок = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(код))
    ctypes.windll.kernel32.CloseHandle(h)
    return bool(ок) and код.value == 259


def _создан(pid: int) -> float | None:
    if os.name != "nt":
        return None
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    from ctypes import wintypes
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    ок = ctypes.windll.kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u))
    ctypes.windll.kernel32.CloseHandle(h)
    if not ок:
        return None
    return ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 10_000_000 - 11644473600


def _снять(pid: int) -> None:
    if os.name != "nt":
        return
    h = ctypes.windll.kernel32.OpenProcess(0x0001, False, int(pid))
    if h:
        ctypes.windll.kernel32.TerminateProcess(h, 1)
        ctypes.windll.kernel32.CloseHandle(h)


def _запомнить(работники) -> None:
    записи = [{"pid": p.pid, "created": _создан(p.pid), "parent": os.getpid()}
              for p in работники if getattr(p, "pid", None)]
    if записи:
        try:
            ФАЙЛ_ДЕТЕЙ.parent.mkdir(parents=True, exist_ok=True)
            ФАЙЛ_ДЕТЕЙ.write_text(json.dumps(записи), encoding="utf-8")
        except OSError:
            pass


def _забыть() -> None:
    try:
        ФАЙЛ_ДЕТЕЙ.unlink()
    except OSError:
        pass


def убрать_сирот() -> None:
    """Снять работников, чей родитель мёртв. Живого родителя не трогаем."""
    try:
        записи = json.loads(ФАЙЛ_ДЕТЕЙ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    живые = []
    for з in записи if isinstance(записи, list) else []:
        if _жив(int(з.get("parent") or 0)):
            живые.append(з)
            continue
        pid = int(з.get("pid") or 0)
        создан = _создан(pid) if pid else None
        if _жив(pid) and создан is not None and abs(создан - float(з.get("created") or 0)) <= 2:
            _снять(pid)
    try:
        ФАЙЛ_ДЕТЕЙ.write_text(json.dumps(живые), encoding="utf-8")
    except OSError:
        pass



def выполнить(функция, *аргументы, предел: float | None = None, **именованные):
    """Результат `функция(*аргументы, **именованные)`, посчитанный в отдельном процессе (если это возможно).

    `предел` — сколько секунд ждать результат (11.11.2026): раньше вызов с `предел=...` уходил в саму
    функцию, и разбор по голосам падал с «unexpected keyword argument»."""
    if not включено() or not по_имени(функция):
        return функция(*аргументы, **именованные)
    # Запуск из stdin/интерактивной консоли: у главного модуля нет файла, spawn его не повторит.
    main_file = getattr(sys.modules.get("__main__"), "__file__", "") or ""
    if not main_file or main_file.endswith("<stdin>"):
        return функция(*аргументы, **именованные)
    убрать_сирот()
    контекст = multiprocessing.get_context("spawn")
    try:
        пул = concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=контекст)
        работники = []
        предел = float(предел if предел is not None else (os.environ.get("WEBAPP_HEAVY_TIMEOUT_SEC", "0") or 0))
        try:
            future = пул.submit(функция, *аргументы, **именованные)
            работники = list(getattr(пул, "_processes", {}).values())
            _запомнить(работники)
            return future.result(timeout=предел or None)
        finally:
            # Ребёнок гасится явно (10.11.2026): после результата pyannote/torch иногда не отпускают
            # свои потоки, `shutdown(wait=True)` ждёт их, а работник продолжает жечь процессор.
            пул.shutdown(wait=False)
            for работник in работники:
                if работник.is_alive():
                    работник.terminate()
                    работник.join(timeout=5)
                    if работник.is_alive():
                        работник.kill()
            _забыть()
    except RuntimeError as exc:
        # Скрипт без `if __name__ == "__main__"` не может породить процесс: это не поломка разбора,
        # просто считаем на месте (дольше, но результат тот же).
        if "bootstrapping phase" not in str(exc):
            raise
        return функция(*аргументы, **именованные)
