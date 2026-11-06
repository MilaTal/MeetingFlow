# -*- coding: utf-8 -*-
"""Ход шага записи: подшаг, дочерний процесс и его процессорное время (06.11.2026).

Зачем. Признак «завис» считался по времени с последней отметки, а отметка ставилась один раз — в начале шага.
Разделение по голосам идёт 50–70 минут, поэтому на любой записи длиннее ~25 минут проход выглядел зависшим,
хотя работал. 06.11 из-за этого дважды перезапустили сервер и потеряли около двух с половиной часов
распознавания записи с тендерами.

Что теперь. «Завис» — это работа, которая не двигается:
* шаг разделения по голосам или отпечатков: дочерний процесс жив, но его процессорное время не растёт
  10 минут подряд — завис; процесса нет — тоже завис;
* вызов сервиса распознавания молчит дольше 30 минут — завис (сам вызов не прерываем: таймаут «Транса» не
  трогаем, решение владельца 06.11.2026);
* остальные шаги — по прежнему правилу времени.

Пока шаг идёт, экран показывает подшаг и сколько он идёт; ожидание считается 1,25 × длительности записи
(замер 28.10.2026: 3 284 с разделения на запись 2 713 с). Процессорное время берём без новых зависимостей:
`psutil`, если он есть, иначе Win32 `GetProcessTimes` / `/proc`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Порог «не двигается»: 10 минут без роста процессорного времени дочернего процесса
СТОП_ПРОЦЕССОРА_СЕК = int(os.environ.get("MEETFLOW_STALL_CHILD_CPU_SEC", "600"))
# Порог молчания сервиса распознавания: полчаса
СТОП_РАСПОЗНАВАНИЯ_СЕК = int(os.environ.get("MEETFLOW_STALL_ASR_SEC", "1800"))
# Ожидание разделения по голосам от длительности записи
ДОЛЯ_ОЖИДАНИЯ = float(os.environ.get("MEETFLOW_VOICE_EXPECT_RATIO", "1.25"))
# Как часто снимать процессорное время (чаще — незачем, экран опрашивает раз в несколько секунд)
ЗАМЕР_КАЖДЫЕ_СЕК = 20


# ---------------------------------------------------------------- процессы без psutil
def _psutil():
    try:
        import psutil  # noqa: PLC0415 — необязательная зависимость
        return psutil
    except Exception:  # noqa: BLE001 — без psutil считаем своим способом
        return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    def _дети_win(parent: int) -> list[int]:
        ядро = ctypes.WinDLL("kernel32", use_last_error=True)
        снимок = ядро.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if снимок == -1:
            return []
        запись = _PROCESSENTRY32()
        запись.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        найдено: list[int] = []
        try:
            if ядро.Process32First(снимок, ctypes.byref(запись)):
                while True:
                    if запись.th32ParentProcessID == parent:
                        найдено.append(int(запись.th32ProcessID))
                    if not ядро.Process32Next(снимок, ctypes.byref(запись)):
                        break
        finally:
            ядро.CloseHandle(снимок)
        return найдено

    def _cpu_win(pid: int) -> float | None:
        ядро = ctypes.WinDLL("kernel32", use_last_error=True)
        ПРАВА = 0x1000 | 0x0400          # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION
        ручка = ядро.OpenProcess(ПРАВА, False, pid)
        if not ручка:
            return None
        try:
            создан, выход, ядро_вр, польз = (wintypes.FILETIME() for _ in range(4))
            if not ядро.GetProcessTimes(ручка, ctypes.byref(создан), ctypes.byref(выход),
                                        ctypes.byref(ядро_вр), ctypes.byref(польз)):
                return None
            def секунды(ft) -> float:
                return (ft.dwHighDateTime << 32 | ft.dwLowDateTime) / 10_000_000
            return секунды(ядро_вр) + секунды(польз)
        finally:
            ядро.CloseHandle(ручка)

    def дети(parent: int) -> list[int]:
        return _дети_win(parent)

    def процессор_секунды(pid: int) -> float | None:
        return _cpu_win(pid)

    def время_создания(pid: int) -> float | None:
        """Когда процесс создан (секунды Unix). Windows переиспользует номера, и по одному PID своего ребёнка от
        чужого не отличить — сверяем время создания (записка 06.11.2026)."""
        ядро = ctypes.WinDLL("kernel32", use_last_error=True)
        ручка = ядро.OpenProcess(0x1000 | 0x0400, False, pid)
        if not ручка:
            return None
        try:
            создан, выход, ядро_вр, польз = (wintypes.FILETIME() for _ in range(4))
            if not ядро.GetProcessTimes(ручка, ctypes.byref(создан), ctypes.byref(выход),
                                        ctypes.byref(ядро_вр), ctypes.byref(польз)):
                return None
            # FILETIME — сотни наносекунд от 1601-01-01; в Unix-время — вычесть 11644473600 с
            return (создан.dwHighDateTime << 32 | создан.dwLowDateTime) / 10_000_000 - 11_644_473_600
        finally:
            ядро.CloseHandle(ручка)

else:
    def дети(parent: int) -> list[int]:
        найдено = []
        try:
            for имя in os.listdir("/proc"):
                if not имя.isdigit():
                    continue
                try:
                    with open(f"/proc/{имя}/stat", "r", encoding="utf-8") as ф:
                        поля = ф.read().rsplit(")", 1)[1].split()
                    if int(поля[1]) == parent:      # ppid — второе поле после имени
                        найдено.append(int(имя))
                except (OSError, IndexError, ValueError):
                    continue
        except OSError:
            return []
        return найдено

    def процессор_секунды(pid: int) -> float | None:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as ф:
                поля = ф.read().rsplit(")", 1)[1].split()
            return (int(поля[11]) + int(поля[12])) / os.sysconf("SC_CLK_TCK")   # utime + stime
        except (OSError, IndexError, ValueError):
            return None

    def время_создания(pid: int) -> float | None:
        """Когда процесс создан (секунды Unix): starttime считаем от времени загрузки системы."""
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as ф:
                поля = ф.read().rsplit(")", 1)[1].split()
            старт_тиков = int(поля[19])                        # starttime — 22-е поле
            with open("/proc/stat", "r", encoding="utf-8") as ф:
                загрузка = next(int(строка.split()[1]) for строка in ф if строка.startswith("btime "))
            return загрузка + старт_тиков / os.sysconf("SC_CLK_TCK")
        except (OSError, IndexError, ValueError, StopIteration):
            return None


def жив(pid: int) -> bool:
    """Процесс есть и не зомби."""
    ps = _psutil()
    if ps is not None:
        try:
            п = ps.Process(pid)
            return п.is_running() and п.status() != ps.STATUS_ZOMBIE
        except Exception:  # noqa: BLE001 — процесса нет
            return False
    if sys.platform != "win32":
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as ф:
                поля = ф.read().rsplit(")", 1)[1].split()
            return поля[0] != "Z"
        except (OSError, IndexError):
            return False
    ядро = ctypes.WinDLL("kernel32", use_last_error=True)
    ручка = ядро.OpenProcess(0x1000, False, pid)
    if not ручка:
        return False
    try:
        код = wintypes.DWORD()
        return bool(ядро.GetExitCodeProcess(ручка, ctypes.byref(код))) and код.value == 259   # STILL_ACTIVE
    finally:
        ядро.CloseHandle(ручка)


# ---------------------------------------------------------------- ход шага
class Ход:
    """Что сейчас делается на шаге записи и двигается ли работа."""

    def __init__(self) -> None:
        self._замок = threading.Lock()
        self._подшаг = ""
        self._начат: float | None = None
        self._детали: dict = {}
        self._pid: int | None = None
        self._cpu: float | None = None
        self._cpu_at: float | None = None
        self._рос: float | None = None         # когда последний раз росло процессорное время
        self._замер: float | None = None

    def подшаг(self, имя: str, **детали) -> None:
        """Отметить подшаг: «распознавание записи», «разделение по голосам», «отпечатки голосов»."""
        with self._замок:
            if имя != self._подшаг:
                self._начат = time.monotonic()
            self._подшаг = имя
            self._детали = детали
            self._pid = self._детали.get("pid")
            self._cpu = None
            self._cpu_at = None
            self._рос = None
            self._замер = None

    def дочерний(self, pid: int | None) -> None:
        with self._замок:
            self._pid = pid
            if pid:
                запомнить_ребёнка(pid)      # чтобы следующий запуск сервера мог подобрать его, если мы упадём

    def сбросить(self) -> None:
        with self._замок:
            self._подшаг = ""
            self._начат = None
            self._детали = {}
            self._pid = None
            self._cpu = None
            self._cpu_at = None
            self._рос = None
            self._замер = None

    def снимок(self) -> dict:
        """Подшаг, сколько идёт, дочерний процесс, его процессор и растёт ли он."""
        with self._замок:
            сейчас = time.monotonic()
            if not self._подшаг:
                return {"подшаг": "", "секунд": 0, "прогноз_сек": None, "pid": None, "cpu": None,
                        "рост_сек": None, "жив": None, "без_роста_сек": None}
            if self._pid is None:
                свои = дети(os.getpid())
                if свои:
                    self._pid = max(свои)
                    запомнить_ребёнка(self._pid)
            pid = self._pid
            if pid is not None and (self._замер is None or сейчас - self._замер >= ЗАМЕР_КАЖДЫЕ_СЕК):
                cpu = процессор_секунды(pid)
                if cpu is not None:
                    if self._cpu is not None and self._cpu_at is not None:
                        рост = cpu - self._cpu
                        if рост > 0.5:
                            self._рос = сейчас
                    elif self._рос is None:
                        self._рос = сейчас      # первый замер — считаем, что работа идёт
                    self._cpu, self._cpu_at = cpu, сейчас
                self._замер = сейчас
            секунд = int(сейчас - self._начат) if self._начат else 0
            прогноз = self._детали.get("прогноз_сек")
            return {"подшаг": self._подшаг, "секунд": секунд,
                    "прогноз_сек": int(прогноз) if прогноз else None,
                    "pid": pid, "cpu": round(self._cpu, 1) if self._cpu is not None else None,
                    "жив": жив(pid) if pid is not None else None,
                    "без_роста_сек": int(сейчас - self._рос) if self._рос else None}

    def завис(self, ход: dict | None = None) -> bool:
        """Работа не двигается: дочерний процесс стоит или сервис распознавания молчит."""
        ход = ход if ход is not None else self.снимок()
        if not ход.get("подшаг"):
            return False
        имя = ход["подшаг"]
        if "разделен" in имя or "отпечат" in имя:
            if ход.get("жив") is False:
                return True
            без_роста = ход.get("без_роста_сек")
            return без_роста is not None and без_роста > СТОП_ПРОЦЕССОРА_СЕК
        if "распознавание" in имя:
            return (ход.get("секунд") or 0) > СТОП_РАСПОЗНАВАНИЯ_СЕК
        return False


ход = Ход()


# ---------------------------------------------------------------- осиротевшие дочерние процессы
# `Stop-Process` по PID сервера на Windows не убивает дочерний процесс spawn: он продолжает считать и отнимает
# процессор у следующего прохода. 06.11 таких нашлось три (с 26.10, с 13:31 и с 15:32) — 1,2 ГБ памяти и
# 95 тысяч секунд процессорного времени. Список своих детей пишем в файл при каждом старте шага: только так
# видно, чей это процесс, — по имени `python.exe` и мёртвому родителю чужой не отличить.
ФАЙЛ_ДЕТЕЙ = Path(os.environ.get("MEETFLOW_CHILD_PIDS") or
                  (Path(__file__).resolve().parents[2] / "data" / "child_pids.json"))
_замок_детей = threading.Lock()


def _прочитать_детей() -> list[dict]:
    try:
        данные = json.loads(ФАЙЛ_ДЕТЕЙ.read_text(encoding="utf-8"))
        return [x for x in данные if isinstance(x, dict) and x.get("pid")]
    except (OSError, ValueError):
        return []


def _записать_детей(список: list[dict]) -> None:
    try:
        ФАЙЛ_ДЕТЕЙ.parent.mkdir(parents=True, exist_ok=True)
        ФАЙЛ_ДЕТЕЙ.write_text(json.dumps(список, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def запомнить_ребёнка(pid: int) -> None:
    """Записать свой дочерний процесс: при следующем старте видно, кого подбирать. Вместе с временем создания —
    Windows переиспользует номера, и по одному PID своего ребёнка от чужого сервера не отличить (06.11.2026)."""
    создан = время_создания(pid)
    with _замок_детей:
        список = [x for x in _прочитать_детей() if x["pid"] != pid]
        список.append({"pid": int(pid), "сервер": os.getpid(), "создан": создан,
                       "начат": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _записать_детей(список)


def забыть_ребёнка(pid: int) -> None:
    with _замок_детей:
        список = [x for x in _прочитать_детей() if x["pid"] != pid]
        _записать_детей(список)


def свои(запись: dict) -> bool:
    """Это наш процесс? Сверяем время создания: у чужого сервера с тем же номером оно другое. Старые записи без
    времени (до 06.11.2026) своим не считаем — лучше не остановить сироту, чем чужой сервер."""
    pid = int(запись.get("pid") or 0)
    записанное = запись.get("создан")
    if not pid or записанное is None:
        return False
    живое = время_создания(pid)
    return живое is not None and abs(float(живое) - float(записанное)) <= 1.0


def занят_другим(запись: dict) -> bool:
    """PID живой, но это не наш ребёнок — номер достался другому процессу."""
    pid = int(запись.get("pid") or 0)
    return bool(pid) and жив(pid) and not свои(запись)


def осиротевшие() -> list[dict]:
    """Записанные дети прошлых запусков, которые ещё живы и точно наши. Записи, чей номер занят другим процессом,
    снимаются: иначе старт сервера сделал бы `taskkill` чужому серверу (ERP 8000, Планёрке 8001)."""
    мои = set(дети(os.getpid()))
    итог = []
    for запись in _прочитать_детей():
        pid = int(запись["pid"])
        if not жив(pid):
            забыть_ребёнка(pid)          # процесс закончился — запись больше не нужна
            continue
        if pid in мои:
            continue                     # наш живой ребёнок: не сирота
        if not свои(запись):
            забыть_ребёнка(pid)
            print(f"MeetFlow: PID {pid} занят другим процессом, пропущен", file=sys.stderr, flush=True)
            continue
        итог.append(запись)
    return итог


def остановить_сирот() -> list[dict]:
    """Остановить детей прошлых запусков (при старте сервера). Возвращает, кого остановили."""
    остановленные = []
    for запись in осиротевшие():
        pid = int(запись["pid"])
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)
            else:
                os.kill(pid, 15)
        except Exception:  # noqa: BLE001 — не смогли остановить: запись останется до следующего раза
            continue
        if not жив(pid):
            забыть_ребёнка(pid)
            остановленные.append(запись)
    return остановленные
