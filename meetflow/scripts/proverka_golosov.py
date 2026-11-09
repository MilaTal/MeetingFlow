# -*- coding: utf-8 -*-
"""Проверка разделения по голосам на одной записи — без сервера, без распознавания и без платных вызовов.

Зачем: 09.11.2026 у встречи 9 шаг голосов упал `BrokenProcessPool` — дочерний процесс умер, причина нигде не
записана (сервис при этом жив). Скрипт готовит звук так же, как сборка (16 кГц моно), и запускает pyannote
**в этом процессе** с `faulthandler`: если падение нативное, в stderr будет строка «Windows fatal exception» с
модулем и адресом; если обычное исключение — трассировка Python. Запись при этом не меняется и никуда не уходит.

Применение:
    python scripts/proverka_golosov.py "P:\\...\\запись.m4a"
    python scripts/proverka_golosov.py "P:\\...\\запись.m4a" --в-отдельном

`--в-отдельном` — прогнать через штатный отдельный процесс (как сборка): увидим `BrokenProcessPool`, если он
повторяется, но без причины смерти. По умолчанию — в этом процессе, чтобы причина была видна.
"""
from __future__ import annotations

import argparse
import faulthandler
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _память_мбайт() -> str:
    """Пиковый рабочий набор процесса (Windows, psapi): видно, сколько съел разбор."""
    try:
        import ctypes
        from ctypes import wintypes

        class _Счётчик(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        с = _Счётчик(); с.cb = ctypes.sizeof(с)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(с), с.cb):
            return f"{с.PeakWorkingSetSize / 1024 / 1024:.0f} МБ пик, {с.WorkingSetSize / 1024 / 1024:.0f} МБ сейчас"
    except Exception:  # noqa: BLE001 — не Windows или нет psapi: память просто не печатаем
        pass
    return "память: нет данных"


def main() -> int:
    ap = argparse.ArgumentParser(description="Разделение по голосам на одной записи (диагностика)")
    ap.add_argument("файл", help="путь к записи (m4a/mp3/wav)")
    ap.add_argument("--в-отдельном", action="store_true", help="прогнать штатным отдельным процессом, как сборка")
    args = ap.parse_args()
    src = Path(args.файл)
    if not src.is_file():
        print("нет файла:", src, file=sys.stderr)
        return 2

    faulthandler.enable()
    from meetflow.core.voice_step import _prepare_wav
    from meetflow.core import diarize

    print("запись:", src)
    времечко = time.monotonic()
    wav = _prepare_wav(src)
    print(f"звук для голосов: {wav} ({time.monotonic() - времечко:.1f} с)")
    print(_память_мбайт())

    started = time.monotonic()
    try:
        if args.в_отдельном:
            куски, сводка = diarize.diarize(wav)
        else:
            куски, сводка = diarize._diarize_here(wav)   # noqa: SLF001 — диагностика, намеренно в этом процессе
    except Exception as exc:  # noqa: BLE001 — показываем причину и выходим
        print(f"ОШИБКА {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        print(_память_мбайт())
        return 1
    print(f"готово за {time.monotonic() - started:.1f} с: голосов {сводка.get('speakers')}, "
          f"устройство {сводка.get('device')}, реплик {len(куски)}")
    print(_память_мбайт())
    for к in куски[:5]:
        print(f"  {к['start']:.1f}–{к['end']:.1f}  {к['speaker']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
