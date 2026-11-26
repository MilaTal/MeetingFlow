"""Приём записей из папки-приёмника: настройка адреса и фоновый забор.

Перенесено из Планёрки и Проекта ERP:
- адрес вводится дважды (защита от опечатки) и проверяется: не корень
  диска, не домашняя папка, не Документы / Рабочий стол / Загрузки, не
  папка самого приложения; непустая папка — только с файлом-меткой;
  пустая — метка и памятка «что сюда класть» кладутся сами;
- у каждого проекта своя папка (решение ERP 30.09);
- каждая смена адреса — запись в журнале решений и техническое сообщение;
- забор — фоном с интервалом (умолчание 900 с, как в Планёрке); кнопки
  «забрать сейчас» нет (решение владельца 30.09: автозабор оставить);
- показывается последний результативный проход, а не пустой;
- недоступная папка — не «пустой успешный проход», а сообщение;
- о файле без даты сообщается один раз; повторы по содержимому — в
  «обработано»; запись без инструментов распознавания ждёт на месте.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from ..connectors.base import ConnectorError
from . import hod
from . import peregovorka
from .golosa_ochered import СОСТОЯНИЕ_ЖДЁТ
from .nazvanie_vstrechi import тема_из_приёмника
from ..connectors.watch_folder import (DONE_DIR, MARKER, SKIP_WORDS, STOPPED_DIR, FolderIntake, IntakeItem,
                                       check_folder_path, is_marker, single_date, дата_по_времени)
from .store import now

HINT_FILE = "ЧТО СЮДА КЛАСТЬ.md"
HINT_TEXT = ("# Папка-приёмник встреч\n\nСюда кладутся записи и расшифровки встреч. Дата встречи берётся из имени "
             "файла (например, «Встреча 01.10.2026.mp4»), иначе из имени папки дня, иначе по времени файла. "
             "Принятые файлы сразу уезжают в подпапку «обработано» — это и значит «забрали».\n")
DEFAULT_INTERVAL = 900
MIN_INTERVAL = 30
BIG_FIRST_PASS = int(os.environ.get("MEETFLOW_WATCH_BIG_FIRST_PASS", "25"))
# Проход, который идёт, — не «завис» (27.10.2026, как сторож обхода ERP): у прохода пульс на каждом шаге и признак
# «идёт, шаг, файл». Зависшим считается проход без пульса дольше трёх интервалов И дольше этого порога. Отличие от
# ERP (там 600 с): в MeetFlow распознавание записи и автосборка протокола идут внутри прохода, шаг длится десятки минут.
STALL_STEP_SEC = int(os.environ.get("MEETFLOW_WATCH_STALL_STEP_SEC", "1800"))
# Автосборка из папки не держит обход (27.10.2026): проход ждёт сборку не дольше этого, дальше она идёт в очереди
# сама, а итог (остановлена по пределу → файл в «остановлено») подбирает следующий проход. Раньше проход ждал до 4 ч:
# сборка, вставшая в очереди (повтор через 10 мин / 1 ч или зависшая), останавливала забор новых файлов.
# 26.11.2026 (передача приёмника): default 0 — проход НЕ ждёт сборку синхронно. Пока очередь занята разбором голосов,
# ожидание по 60 с на каждый файл блокировало поток обхода (watch_last_scan замирал, сторож видел живой поток и не
# поднимал). Файл принимается и сборка ставится в очередь сразу; итог подбирает _check_pending следующим проходом.
# Хотите прежний grace — задайте MEETFLOW_WATCH_AUTORUN_WAIT_SEC (сек).
AUTORUN_WAIT_SEC = float(os.environ.get("MEETFLOW_WATCH_AUTORUN_WAIT_SEC", "0"))
# Выгрузка ВКС рядом с записью прикрепляется к её встрече по дате И времени (записка 05.11.2026, п. 6): время в имени
# файла против времени записи источника. Расхождение больше этого порога — своя встреча, чтобы две встречи одного дня
# не слились в одну. Нет времени в именах — прикрепляется как прежде.
ПОРОГ_ВРЕМЕНИ_МИН = int(os.environ.get("MEETFLOW_INTAKE_TIME_GAP_MIN", "180"))

_ДАТА_В_ИМЕНИ = re.compile(r"\d{1,2}[.\-]\d{1,2}[.\-]\d{2,4}|\d{4}-\d{2}-\d{2}")
_ВРЕМЯ_В_ИМЕНИ = re.compile(r"(?<!\d)(\d{1,2})[-_.: ](\d{2})(?:[-_.: ](\d{2}))?(?!\d)")


def время_из_имени(name: str) -> int | None:
    """Время начала в имени файла, минуты от полуночи: «2026-11-06 11-59-7», «06.11.2026 11.59», «10-15».

    Дата из имени сначала убирается — иначе «06.11» читалось бы как время. Времени нет — None: встреча ищется
    по дате, как раньше."""
    s = _ДАТА_В_ИМЕНИ.sub(" ", name or "")
    было_дата = bool(_ДАТА_В_ИМЕНИ.search(name or ""))
    for m in _ВРЕМЯ_В_ИМЕНИ.finditer(s):
        # «06.11» без года — дата, а не время: время с точкой читаем, только когда в имени была полная дата
        if m.group(0)[len(m.group(1)):len(m.group(1)) + 1] == "." and not было_дата:
            continue
        ч, мин = int(m.group(1)), int(m.group(2))
        if ч > 23 or мин > 59:
            continue
        return ч * 60 + мин
    return None


class IntakeError(ValueError):
    """Отказ в настройке — текст для человека."""


def validate_folder(path_text: str, repeat: str, app_dir: Path | None = None, home: Path | None = None,
                    sign: bool = True) -> Path:
    """Проверка адреса. sign=False — только проверка, без записи в папку: подпись (метка и памятка) кладётся,
    когда смена подтверждена паролем, а не на шаге предпросмотра (11.10.26)."""
    path_text, repeat = (path_text or "").strip().strip('"'), (repeat or "").strip().strip('"')
    if path_text != repeat:
        raise IntakeError("Адрес и его повтор не совпадают — проверьте опечатку.")
    if not path_text:
        raise IntakeError("Адрес пустой.")
    p = Path(path_text)
    if not p.is_absolute():
        raise IntakeError("Нужен полный адрес папки, например C:\\Встречи\\Приёмник.")
    # прежде было: IntakeError внутри try ловился собственным except ValueError
    # (IntakeError — его подкласс), и папка приложения проходила — найдено тестом
    if app_dir is not None and p.resolve().is_relative_to(app_dir.resolve()):
        raise IntakeError("Нельзя назначить приёмником папку самого приложения.")
    if not p.exists():
        raise IntakeError("Папка не найдена. Создайте её и повторите.")
    if not p.is_dir():
        raise IntakeError("Это файл, а не папка.")
    try:
        check_folder_path(p, home=home)
    except ConnectorError as e:
        raise IntakeError(str(e)) from None
    if sign:
        sign_folder(p)
    return p


def sign_folder(p: Path) -> None:
    if not any(p.iterdir()):  # пустая — подписываем как приёмник
        (p / MARKER).write_text("Эта папка назначена приёмником встреч «Встречи Невалаб».\n", encoding="utf-8")
        (p / HINT_FILE).write_text(HINT_TEXT, encoding="utf-8")


def preview_folder(p: Path) -> dict[str, Any]:
    """Что лежит в папке и что заберёт первый проход — до смены адреса (как в Планёрке и ERP с 07.10.26)."""
    files, take, no_date = [], [], []
    for f in sorted(p.rglob("*")):
        parts = f.relative_to(p).parts
        if (not f.is_file() or DONE_DIR in parts or STOPPED_DIR in parts or is_marker(f.name) or f.name == HINT_FILE
                or f.suffix.lower() == ".md" or any(w in f.name.lower() for w in SKIP_WORDS)):
            continue
        files.append(f.name)
        # та же логика даты, что и у прохода: имя → папка дня → время файла (16.11.2026), иначе экран обещал бы
        # «файлов без даты», которые проход на самом деле заберёт
        (take if (single_date(f.name) or single_date(f.parent.name) or дата_по_времени(f)) else no_date).append(f.name)
    return {"files": len(files), "first_pass": len(take), "examples": take[:5], "no_date": no_date[:5],
            "big": len(take) > BIG_FIRST_PASS, "big_limit": BIG_FIRST_PASS}


def автозапуск_включён(store, project_id: int | None) -> bool:
    """Автозапуск протокола (решение владелицы 28.10.2026): включённый при «Все проекты» действует для всех проектов и для
    записи, проект которой не определён; включённый в проекте — для этого проекта. Было — только в выбранном проекте,
    а при «Все проекты» выключатель не действовал."""
    if bool(store.get_setting("autorun", None, False)):
        return True
    return bool(project_id) and bool(store.get_setting("autorun", project_id, False))


def голоса_фоном(store, project_id: int | None) -> bool:
    """Голоса фоном для ВСЕХ записей (решение владелицы 26.11.2026 №7).

    Приёмник принимает запись → расшифровка → протокол СРАЗУ без говорящих → разделение по голосам уходит в очередь
    «ждут голоса (потом)» и идёт фоном, затем протокол пересобирается с именами. Прежде голоса считались внутри прохода
    приёмника (~40–70 мин на запись) и блокировали забор остальных файлов; вторым этапом шли только длинные записи
    переговорки (≥ 20 мин). Теперь фон — для всех, порог переговорки снижен до 0.

    Выключатель (прежний порядок — голоса внутри приёма): настройка `voices_background=False` (проектная или общая)
    либо переменная `MEETFLOW_VOICES_BACKGROUND=off`. По умолчанию фон включён."""
    if os.environ.get("MEETFLOW_VOICES_BACKGROUND", "on").strip().lower() in ("off", "0", "false", "нет"):
        return False
    return bool(store.get_setting("voices_background", project_id,
                                  store.get_setting("voices_background", None, True)))


class IntakeService:
    """Один экземпляр на приложение. Состояние проходов — в настройках проекта."""

    def __init__(self, pipe, interval_default: int = DEFAULT_INTERVAL):
        self.pipe = pipe
        self.s = pipe.s
        self.interval_default = interval_default
        self._intakes: dict[int, FolderIntake] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # идущий проход по проекту: {"started": now(), "step": ..., "file": ..., "pulse": monotonic}
        self._scanning: dict[int, dict[str, Any]] = {}
        # сборки, поставленные проходом и не дождавшиеся: id строки очереди → (проект, встреча, файл, где файл сейчас)
        self._pending: dict[int, tuple[int, int, str, Path | None]] = {}
        # Живучесть фона (26.11.2026): 25.11 поток обхода умер на «database is locked» при записи итога прохода,
        # и забор записей стоял до перезапуска сервера — папка на мониторе значилась «нет», файлы не забирались.
        self._should_run = False       # фон разрешён этому экземпляру (первый на базе, папки включены)
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._restarts = 0
        self._guard: threading.Thread | None = None
        self._guard_stop = threading.Event()

    def _beat(self, project_id: int, step: str, file: str | None = None) -> None:
        cur = self._scanning.get(project_id)
        if cur is not None:
            # «Шаг идёт с» — от начала шага, а не от последней отметки: на длинном шаге отметка одна, и время
            # «шаг идёт 2 минуты» на 68-минутном разделении голосов было неправдой (06.11.2026)
            if cur.get("step") != step or cur.get("step_started") is None:
                cur["step_started"] = time.monotonic()
            cur.update(step=step, file=file, pulse=time.monotonic())

    # ------------------------------------------------------------ настройки
    def folder(self, project_id: int) -> str | None:
        return self.s.get_setting("watch_folder", project_id)

    def set_folder(self, project_id: int, path: Path | None, by: str) -> None:
        old = self.folder(project_id)
        self.s.set_setting("watch_folder", str(path) if path else None, project_id, by)
        with self._lock:
            self._intakes.pop(project_id, None)
        what = f"Папка-приёмник: {old or 'не задана'} → {path or 'отключена'}"
        self.s.insert("decisions", project_id=project_id, what=what, decision="изменено", why=f"кто: {by or '—'}",
                      at=now())
        self.pipe.cards.open(project_id, "event", "Изменён адрес папки-приёмника",
                             {"было": old, "стало": str(path) if path else None, "кто": by})

    def interval(self, project_id: int) -> int:
        return self.interval_info(project_id)[0]

    def interval_info(self, project_id: int) -> tuple[int, str]:
        """Частота обхода и откуда она взята: экран → переменная MEETFLOW_WATCH_INTERVAL_SEC → умолчание."""
        v = self.s.get_setting("watch_interval", project_id)
        if v is not None:
            return int(v), "задана на экране"
        env = os.environ.get("MEETFLOW_WATCH_INTERVAL_SEC", "").strip()
        if env.isdigit() and int(env) >= MIN_INTERVAL:
            return int(env), "из переменной MEETFLOW_WATCH_INTERVAL_SEC"
        return self.interval_default, "по умолчанию"

    # ------------------------------------------------------------ проход
    def scan_project(self, project_id: int, today=None) -> dict[str, Any]:
        path = self.folder(project_id)
        if not path:
            return {"status": "off"}
        self._scanning[project_id] = {"started": now(), "step": "обход папки", "file": None,
                                      "pulse": time.monotonic()}
        try:
            return self._scan(project_id, path, today)
        finally:
            self._scanning.pop(project_id, None)

    def _after_build(self, project_id: int, mid: int, name: str, moved: Path | None, rep: dict) -> None:
        if rep.get("status") == "stopped_by_limit" and moved and moved.exists():
            # не «обработано»: прогон неполный, повтор — решение человека (01/11)
            to = self._intakes[project_id].stopped(moved) if project_id in self._intakes else moved
            self.pipe.cards.open(project_id, "stopped_by_limit",
                                 f"Файл «{name}» обработан не полностью — лежит в «остановлено»",
                                 {"file": str(to), "detail": rep.get("detail")}, mid)

    def _check_pending(self, project_id: int) -> None:
        """Итог сборок, которые проход поставил и не дождался: остановленная по пределу — файл в «остановлено»."""
        for rid, (pid, mid, name, moved) in list(self._pending.items()):
            if pid != project_id:
                continue
            row = self.s.get("build_queue", rid)
            if row is None:
                self._pending.pop(rid, None)
            elif row["status"] in ("done", "failed"):
                self._pending.pop(rid, None)
                self._after_build(pid, mid, name, moved, json.loads(row["result"] or "{}"))

    def _scan(self, project_id: int, path: str, today=None) -> dict[str, Any]:
        self._check_pending(project_id)
        with self._lock:
            fi = self._intakes.get(project_id)
            # Дата по времени файла: у переговорки — через peregovorka.включена; у ОБЩЕГО приёмника — отдельный
            # выключатель watch_date_by_file (26.11.2026, передача приёмника), не включающий прочие режимы переговорки.
            # Default вкл: именованные записи без даты в имени («Планёрка по замечаниям…») не висят как no_date.
            # Выключатель общий (project_id=None) или проектный; выключить — watch_date_by_file=False.
            по_времени = peregovorka.включена(self.s, project_id) or bool(
                self.s.get_setting("watch_date_by_file", project_id,
                                   self.s.get_setting("watch_date_by_file", None, True)))
            if fi is None or str(fi.folder) != path or fi.дата_по_времени != по_времени:
                # FolderIntake сравнивает байты файлов; повтор ручной загрузки
                # ловит конвейер по отпечатку текста (ingest -> duplicate)
                fi = self._intakes[project_id] = FolderIntake(path, set(), today, дата_по_времени=по_времени)
        result: dict[str, Any] = {"at": now(), "folder": path, "ingested": [], "held": [], "rejected": [],
                                  "waiting": [], "no_date": [], "duplicates": []}
        try:
            scan = fi.scan()
        except ConnectorError as e:
            result["status"] = "unavailable"
            result["detail"] = str(e)
            self.pipe.cards.open(project_id, "technical", "Папка-приёмник недоступна", {"folder": path})
            self.s.set_setting("watch_last_scan", result, project_id)
            return result
        result.update(waiting=scan.waiting, no_date=scan.no_date, duplicates=scan.duplicates,
                      # дата взята по времени файла — видно в отчёте прохода (16.11.2026)
                      дата_по_времени=scan.дата_по_времени)
        for name in scan.no_date:
            # Даты нет ни в имени, ни в папке дня, и время файла не годится (старше 120 дней или в будущем) —
            # говорим, что делать, а не только «нет даты» (16.11.2026)
            self.pipe.cards.open(project_id, "technical", f"В имени файла нет даты, и время файла не годится: {name}",
                                 {"folder": path, "file": name,
                                  "что_делать": "переименуйте с датой встречи («Встреча 01.10.2026.mp4») или положите "
                                                "в папку дня (2026-11-12)"})
        from . import proekt_zapisi as pz
        другие = pz.папки_других(self.s, project_id)
        перенесены: dict[str, Path] = {}      # отпечаток → куда файл уехал в «обработано» при приёме
        for item in scan.ready:
            if pz.под_другим(item.path, другие):
                continue                     # подпапка — приёмник другого проекта: её обходит тот проект
            # Файл принят — сразу в «обработано» (слово владелицы 16.11.2026, как в Планёрке: «файл уходит, как только
            # принят»). Прежде он висел в папке всё распознавание — 82-минутная запись часами. Работаем с рабочей
            # копией; не удалось скопировать — работаем по исходнику, как раньше.
            рабочий = self._рабочая_копия(item.path)
            if рабочий is not None:
                fi.known.add(item.digest)
                перенесены[item.digest] = fi.done(item.path)
                item = IntakeItem(рабочий, item.meeting_date, item.digest)
            # Проект записи (27.10.2026): подпапка проекта или подпроекта — он; корень общей папки — по названию в имени
            # файла; не определился — встреча с пометкой «проект не определён» и карточка, сборка ждёт выбора
            чей = pz.проект_файла(self.s, project_id, Path(path), item.path)
            цель = чей["project_id"]
            # Доработка 2 (28.10.2026): не узнан по имени — встреча в «Общих встречах», своя на каждый файл (две неузнанные
            # записи одного дня — две встречи, а не одна на двоих, как 26.10); проект решит содержание после распознавания.
            # Повторный проход, пока запись распознаётся, находит ту же встречу по дате и имени файла.
            общие = pz.общие_встречи(self.s)
            проект_приёма = цель or общие
            is_media = self.pipe.plugins.resolve_source(item.path.name) is not None and \
                self.pipe.plugins.resolve_source(item.path.name).kind == "asr"
            # Новый порядок для переговорки (12.11.2026, слово владелицы): сплошная запись сутками, файлы по темам —
            # сначала измеряем звук (тишина по краям, паузы, обрыв), потом режем на части и только затем распознаём.
            # Прежде 82-минутная запись с тремя встречами принималась одной встречей целиком.
            if is_media and peregovorka.включена(self.s, проект_приёма):
                итог = self._переговорка(проект_приёма, item, чей, result)
                if итог is not None:
                    if итог.get("status") == "held":
                        # Ждёт инструментов: исходник возвращаем в приёмник, рабочую копию убираем — иначе файл
                        # «ушёл в обработано», а повторный проход его уже не увидит (18.11.2026)
                        self._вернуть_в_приёмник(fi.folder, перенесены.get(item.digest))
                        fi.known.discard(item.digest)
                        self._убрать_копию(item.path)
                        result["held"].append(item.path.name)
                    else:
                        fi.known.add(item.digest)
                        if item.digest in перенесены:
                            self._убрать_копию(item.path)   # исходник уже в «обработано»
                        elif item.path.exists():
                            fi.done(item.path)
                        result["ingested" if итог.get("status") == "ok" else "duplicates"].append(item.path.name)
                    continue
            if цель is None:
                # 08.11.2026 (пункт 2 плана): в названии — тема из имени файла без технических знаков,
                # само имя файла хранится отдельным полем
                метка = тема_из_приёмника(item.path.name) or None
                дата = item.meeting_date.isoformat()
                # Та же встреча дня ищется и в «Общих встречах», и в проекте папки: первая запись дня уже ушла из
                # «Общих» в проект по содержанию (`_по_содержанию`), и без проекта папки вторая запись того же дня
                # заводила вторую встречу — выгрузка ВКС рядом с записью переставала к ней прикрепляться (18.11.2026)
                все = self.s.q("SELECT id, label FROM meetings WHERE project_id IN (?, ?) AND date=? AND deleted_at "
                               "IS NULL ORDER BY id", (общие, project_id, дата))
                # выгрузка ВКС рядом с записью — та же встреча, когда время в именах совпало (записка 05.11.2026, п. 6)
                # 26.11.2026: аудиозапись (is_media) — своя встреча на каждую запись; прикрепляем ТОЛЬКО при совпадении
                # времени, без склейки по дате/теме (иначе разные записи дня мешаются в одну встречу и в «Итоги распознавания»).
                подходят = [r for r in все if self._по_времени(r["id"], item.path.name, строгое=is_media)]
                if is_media:
                    таже = подходят[0] if подходят else None
                else:
                    таже = next((r for r in подходят if (r["label"] or None) == метка),
                                подходят[0] if подходят else None)
                mid = таже["id"] if таже else self.s.insert(
                    "meetings", project_id=общие, date=дата, label=метка,
                    file_name=item.path.name, project_how="проект определится по содержанию записи")
            else:
                mid = self._meeting_for(цель, item.meeting_date.isoformat(), item.path.name, строгое=is_media)
                self.s.update("meetings", mid, project_how=чей["how"])
            проект_приёма = цель or общие
            self._beat(project_id, "распознавание записи" if is_media else "приём файла", item.path.name)
            data = None if is_media else item.path.read_bytes()
            # Голоса фоном для всех записей (26.11.2026 №7): расшифровка и протокол — сразу, разделение по голосам
            # уходит в очередь «потом». Проход приёмника больше не ждёт диаризацию (~40–70 мин) и забирает остальные файлы.
            голоса_потом = is_media and голоса_фоном(self.s, проект_приёма)
            res = self.pipe.ingest(проект_приёма, mid, item.path.name, data, path=item.path if is_media else None,
                                   голоса_потом=голоса_потом)
            st = res.get("status")
            if st == "ok" and res.get("kind") == "transcript":
                проект_приёма, как = self._по_содержанию(mid, цель, чей, item.path.name)
                чей = {**чей, "how": как}
                # Решение владелицы 03.11.2026: несколько записей одного дня по одной теме и с теми же участниками —
                # один протокол. Сводим до автозапуска сборки, чтобы не собрать два протокола.
                try:
                    сведено = pz.свести_дубль_дня(self.s, mid)
                except Exception as exc:  # noqa: BLE001 — сведение не должно ломать приём записи
                    сведено = None
                    self.pipe.cards.open(project_id, "technical", "Не удалось свести встречи одного дня",
                                         {"detail": f"{type(exc).__name__}: {str(exc)[:300]}"}, mid)
                if сведено and сведено != mid:
                    result.setdefault("merged", []).append({"from": mid, "to": сведено})
                    mid = сведено
            if st == "ok":
                result.setdefault("projects", []).append({"file": item.path.name, "project_id": проект_приёма,
                                                          "how": чей["how"]})
            if st in ("ok", "duplicate"):
                fi.known.add(item.digest)
                if st == "duplicate" and res.get("existing_meeting"):
                    # тот же файл уже принят в другой встрече (16.11.2026) — говорим, а не молчим
                    self.pipe.cards.open(project_id, "event",
                                         f"Файл «{item.path.name}» уже обработан — встреча {res['existing_meeting']}",
                                         {"existing_meeting": res["existing_meeting"],
                                          "что_делать": "пересобрать протокол — кнопкой на этой встрече"},
                                         int(res["existing_meeting"]))
                moved = перенесены.get(item.digest)
                # Голоса фоном (26.11.2026 №7): запись нужна второму этапу — рабочую копию НЕ убираем, её удалит
                # очередь голосов после удачного разбора. Признак — источник «ждут голоса (потом)» (ставит ingest).
                голоса_ждут = False
                if st == "ok" and res.get("source_id"):
                    строка = self.s.get("sources", int(res["source_id"]))
                    голоса_ждут = bool(строка and строка.get("voice_state") == СОСТОЯНИЕ_ЖДЁТ)
                if item.digest in перенесены:
                    if not голоса_ждут:
                        self._убрать_копию(item.path)      # исходник уже в «обработано» при приёме
                elif item.path.exists():  # запись мог уже удалить конвейер после распознавания
                    moved = fi.done(item.path)
                    if голоса_ждут and moved:
                        # рабочей копии не было (сбой копирования): звук уехал в «обработано» — правим путь в
                        # источнике, иначе очередь голосов скажет «записи нет на диске»
                        строка = self.s.get("sources", int(res["source_id"]))
                        meta = json.loads((строка or {}).get("meta") or "{}")
                        meta["media_path"] = str(moved)
                        self.s.update("sources", int(res["source_id"]), meta=json.dumps(meta, ensure_ascii=False))
                result["ingested" if st == "ok" else "duplicates"].append(item.path.name)
                # запись, проект которой не определён, собирается сразу в проекте папки (решение владелицы 28.10.2026);
                # карточка выбора проекта остаётся, выбор переносит встречу и пересобирает (`собрать_после_выбора`)
                if st == "ok" and res.get("kind") == "transcript" and автозапуск_включён(self.s, проект_приёма):
                    self._beat(project_id, "сборка протокола", item.path.name)
                    q = getattr(self.pipe, "queue", None)       # через очередь сборок (стенд 41)
                    if q:
                        rid = q.enqueue(проект_приёма, mid, "автозапуск из папки-приёмника")
                        rep = q.wait(rid, timeout=AUTORUN_WAIT_SEC)
                        if rep.get("status") == "queued":       # не дождались — сборка идёт сама, итог подберём потом
                            self._pending[rid] = (project_id, mid, item.path.name, moved)
                    else:
                        rep = self.pipe.run(проект_приёма, mid).__dict__
                    result.setdefault("autorun", []).append({"meeting_id": mid, "status": rep.get("status")})
                    if rep.get("status") != "queued":
                        self._after_build(project_id, mid, item.path.name, moved, rep)
            elif st == "held":
                # Запись не обработана — возвращаем исходник в приёмник, чтобы повторный проход её нашёл
                self._вернуть_в_приёмник(fi.folder, перенесены.get(item.digest))
                fi.known.discard(item.digest)
                self._убрать_копию(item.path)
                result["held"].append(item.path.name)          # ждёт на месте
            else:
                # Файл не принят — он тоже возвращается в приёмник: владелица видит его и может убрать (18.11.2026)
                self._вернуть_в_приёмник(fi.folder, перенесены.get(item.digest))
                fi.known.discard(item.digest)
                self._убрать_копию(item.path)
                result["rejected"].append(item.path.name)
                self.pipe.cards.open(project_id, "technical", f"Файл из папки не принят: {item.path.name}",
                                     {"reason": res.get("reason", "")})
        result["status"] = "ok"
        self.s.set_setting("watch_last_scan", result, project_id)
        if any(result[k] for k in ("ingested", "held", "rejected", "duplicates", "no_date")):
            self.s.set_setting("watch_last_useful_scan", result, project_id)
        return result

    # ------------------------------------------------------------ переговорка (12.11.2026)
    def _рабочая_копия(self, path: Path) -> Path | None:
        """Копия записи для обработки: исходник сразу уезжает в «обработано» (как в Планёрке, 16.11.2026).

        Иначе файл висит в папке-приёмнике всё распознавание: 82-минутная запись — часами, и владелица видит «не
        забрали». Копия живёт рядом с базой (`data/приёмник`) и удаляется после приёма; при «ждёт инструментов» —
        остаётся, чтобы повтор работал без новой загрузки.
        """
        try:
            import shutil
            папка = Path(self.s.path).parent / "приёмник" / hashlib.sha1(
                f"{path.name}|{path.stat().st_size}".encode()).hexdigest()[:10]
            папка.mkdir(parents=True, exist_ok=True)
            цель = папка / path.name
            if not цель.exists() or цель.stat().st_size != path.stat().st_size:
                shutil.copy2(path, цель)
            # 25.11.2026: запись с мусором перед заголовком (два байта 0D 0A) сутки не принималась — обе точки
            # распознавания отвечали «Invalid data». Лечим рабочую копию, исходник остаётся в «обработано» как есть.
            from .zvuk_zagolovok import исправить_заголовок
            исправление = исправить_заголовок(цель)
            if исправление:
                self.pipe.cards.open(None, "event", f"Запись «{path.name}»: {исправление}", {"file": str(цель)})
            return цель
        except OSError as exc:
            self.pipe.cards.open(None, "technical", f"Не удалось сделать рабочую копию «{path.name}»",
                                 {"detail": f"{type(exc).__name__}: {str(exc)[:200]}",
                                  "что_делать": "файл обработан на месте, как раньше"})
            return None

    def _убрать_копию(self, path: Path) -> None:
        """Рабочая копия больше не нужна: запись принята, исходник лежит в «обработано»."""
        try:
            if path.is_file() and "приёмник" in str(path).lower():
                path.unlink()
                папка = path.parent
                if not any(папка.iterdir()):
                    папка.rmdir()
        except OSError:
            pass

    def _вернуть_в_приёмник(self, папка: Path, перенесённый: Path | None) -> None:
        """Вернуть файл из «обработано» в корень приёмника: запись не обработана (ждёт инструментов или не принята).

        Правило «файл уходит при приёме» (16.11.2026) касается принятых записей; необработанная должна остаться на
        виду, иначе повторный проход её не найдёт — она уже в «обработано». Возврат с уникальным именем: в приёмнике
        мог появиться новый файл с тем же именем.
        """
        if not перенесённый or not перенесённый.exists() or перенесённый.parent.name != DONE_DIR:
            return
        цель = папка / перенесённый.name
        n = 1
        while цель.exists():
            цель = папка / f"{перенесённый.stem} ({n}){перенесённый.suffix}"
            n += 1
        try:
            перенесённый.replace(цель)
        except OSError:
            pass

    def _переговорка(self, project_id: int, item, чей: dict, result: dict) -> dict | None:
        """Запись из переговорки: измерить, разрезать по паузам, завести по встрече на часть.

        Возвращает итог {"status": "ok|duplicate|held"}; None — разбор не удался, запись идёт обычным путём
        (не теряем её из-за собственного сбоя измерения).
        """
        import tempfile
        from ..core.nazvanie_vstrechi import тема_из_приёмника
        from . import proekt_zapisi as pz

        try:
            разбор = peregovorka.разбор(item.path)
        except Exception as exc:  # noqa: BLE001 — измерение не должно съедать запись
            self.pipe.cards.open(project_id, "technical", f"Не удалось измерить запись «{item.path.name}»",
                                 {"file": str(item.path), "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
            return None
        итог = {"status": "ok"}
        if разбор["без_звука"]:
            # Слово владелицы 12.11.2026: «пустые записи — не собирать и не фиксировать». Карточку не заводим —
            # факт остаётся строкой в отчёте прохода (watch_last_scan), чтобы не плодить записи о тишине.
            итог["без_звука"] = True
            итог["минут"] = round(разбор["длительность_с"] / 60, 1)
            return итог
        # Тот же файл уже принят (16.11.2026): владелица кладёт запись в приёмник повторно — распознавать заново
        # бессмысленно и дорого, встреча-дубль тоже не нужна. Отпечаток сверяем после того, как определены встречи
        # файла: если принятая встреча — одна из них, это повторный проход (запись ждала инструментов), его не режем.
        отпечаток_содержимого = hashlib.sha256(item.path.read_bytes()).hexdigest()
        тема = тема_из_приёмника(item.path.name) or item.path.stem
        дата = item.meeting_date.isoformat()
        части = разбор["части"]
        # id встречи на часть: повторный проход (запись ждала инструментов) находит ту же встречу, а не плодит новую
        встречи = []
        for i, часть in enumerate(части, start=1):
            длительность = float(часть["конец_с"]) - float(часть["начало_с"])
            # Слово владелицы 17.11.2026: запись короче порога протокола — не встреча. В реестр не заводим,
            # оставляем только карточку; иначе появляется «ждёт запись», хотя запись уже была и она короткая.
            if peregovorka.короткая_для_протокола(часть):
                self.pipe.cards.open(
                    project_id, "technical",
                    f"Запись «{item.path.name}»: фрагмент {длительность / 60:.1f} мин — короче "
                    f"{peregovorka.ПОРОГ_ПРОТОКОЛА_МИН:g} мин",
                    {"file": str(item.path), "минут": round(длительность / 60, 1),
                     "порог_мин": peregovorka.ПОРОГ_ПРОТОКОЛА_МИН,
                     "что_делать": "протокол не собираем, в реестр встреч не заводим"}, None)
                continue
            метка = тема if len(части) == 1 else f"{тема} · {peregovorka.ччммсс(часть['начало_с'])}–{peregovorka.ччммсс(часть['конец_с'])}"
            была = self.s.q("SELECT id FROM meetings WHERE project_id=? AND date=? AND label=? AND deleted_at IS NULL "
                            "ORDER BY id LIMIT 1", (project_id, дата, метка))
            mid = была[0]["id"] if была else self.s.insert(
                "meetings", project_id=project_id, date=дата, label=метка, file_name=item.path.name,
                project_how=чей.get("how") or "")
            встречи.append((mid, метка, часть))
        if not встречи:
            return {"status": "ok", "short": True,
                    "reason": f"запись короче {peregovorka.ПОРОГ_ПРОТОКОЛА_МИН:g} мин — в реестр не заводим"}
        # Повтор уже принятого файла — стоп до нарезки и распознавания. Встречи этого файла определены выше: если
        # принятая встреча среди них, это повторный проход (запись ждала инструментов) — идём дальше.
        уже = self.s.q("SELECT meeting_id, name FROM file_digests WHERE digest=?", (отпечаток_содержимого,))
        if уже and int(уже[0]["meeting_id"]) not in [m for m, _, _ in встречи]:
            было_в = int(уже[0]["meeting_id"])
            self.pipe.cards.open(project_id, "event", f"Файл «{item.path.name}» уже обработан — встреча {было_в}",
                                 {"existing_meeting": было_в,
                                  "что_делать": "протокол этой встречи уже есть; пересобрать — кнопкой на встрече"},
                                 было_в)
            return {"status": "duplicate", "existing_meeting": было_в,
                    "reason": f"этот файл уже обработан — встреча {было_в}"}
        # Рабочие звуки — в папке данных рядом с базой, имена латиницей (12.11.2026): во временной папке путь шёл
        # через короткое имя `EMOSKV~1`, и pyannote (libsndfile) не открывал 28-минутную часть — «System error».
        # Папка по отпечатку записи: повторный проход берёт готовые части.
        отпечаток = hashlib.sha1(f"{item.path.name}|{item.path.stat().st_size}".encode()).hexdigest()[:10]
        куда = Path(self.s.path).parent / "переговорка" / отпечаток
        # Голоса вторым этапом — фоном для ВСЕХ записей (26.11.2026 №7; порог снижен до 0, выключатель voices_background).
        # Запись нужна шагу голосов, а исходник уедет в «обработано»: держим свою копию по отпечатку. Копируем байт в
        # байт, а не перекодируем — отпечаток тот же, и уже сделанная расшифровка не распознаётся заново.
        голоса_потом = голоса_фоном(self.s, project_id) and \
            разбор["длительность_с"] >= peregovorka.ПОРОГ_ГОЛОСА_ПОТОМ_МИН * 60
        нарезано = None
        копия = None
        if разбор["нужна_нарезка"]:
            self._beat(project_id, "нарезка записи", item.path.name)
            try:
                нарезано = peregovorka.нарезать(item.path, части, куда, имена="part")
            except Exception as exc:  # noqa: BLE001 — не режем, но запись не теряем
                self.pipe.cards.open(project_id, "technical", f"Не удалось нарезать запись «{item.path.name}»",
                                     {"file": str(item.path), "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
                нарезано = None
        if голоса_потом and нарезано is None:
            # Копия нужна и когда нарезка не удалась (части не получились — звук остаётся целым для шага голосов).
            try:
                import shutil
                куда.mkdir(parents=True, exist_ok=True)
                копия = куда / f"audio{item.path.suffix.lower()}"
                if not копия.exists() or копия.stat().st_size != item.path.stat().st_size:
                    shutil.copy2(item.path, копия)
            except OSError as exc:
                self.pipe.cards.open(project_id, "technical", f"Не удалось сохранить копию записи «{item.path.name}»",
                                     {"file": str(item.path), "detail": f"{type(exc).__name__}: {str(exc)[:300]}"})
                копия = None
            if копия is None:
                # копии нет — прежний порядок: голоса внутри приёма, запись не теряем из-за сбоя копирования
                голоса_потом = False
        статус = "ok"
        сборки = []
        for i, (mid, метка, часть) in enumerate(встречи):
            путь = нарезано[i]["path"] if нарезано else (копия or item.path)
            # имя источника — для человека, а файл на диске — латиницей (libsndfile)
            имя = (f"{тема} — часть {i}.wav" if нарезано else item.path.name)
            self._beat(project_id, "распознавание записи", f"{item.path.name} → {метка}")
            try:
                res = self.pipe.ingest(project_id, mid, имя, None, path=путь, окно_мин=peregovorka.МИН_МИНУТ,
                                       голоса_потом=голоса_потом)
            except Exception as exc:  # noqa: BLE001 — один сбой части не отменяет остальные
                self.pipe.cards.open(project_id, "technical", f"Сбой приёма части «{метка}»",
                                     {"file": str(путь), "detail": f"{type(exc).__name__}: {str(exc)[:300]}"}, mid)
                статус = "held"
                continue
            st = res.get("status")
            if st == "held":
                статус = "held"
                continue
            if st == "ok":
                # короче 3 минут протокол не собираем (слово владелицы 12.11.2026): по фрагменту выходил пустой
                # протокол, а реестр показывал «протокол готов». Расшифровка остаётся материалом встречи.
                if res.get("kind") == "transcript" and автозапуск_включён(self.s, project_id) \
                        and (часть["конец_с"] - часть["начало_с"]) >= peregovorka.ПОРОГ_ПРОТОКОЛА_С:
                    сборки.append(mid)
            elif st == "duplicate":
                статус = "duplicate" if статус == "ok" else статус
            else:
                статус = "held"
        # Отпечаток исходного файла — в общий список: повторная загрузка будет узнана до распознавания
        if встречи and статус != "held":
            self.pipe._запомнить_отпечаток(отпечаток_содержимого, встречи[0][0], item.path.name)
        # итог в проход — для экрана мониторинга
        result.setdefault("переговорка", []).append({
            "file": item.path.name, "минут": round(разбор["длительность_с"] / 60, 1),
            "частей": len(части), "встречи": [m for m, _, _ in встречи],
            "паузы": разбор["паузы"], "обрыв": разбор["обрыв"],
            # «потом» — протокол соберётся без голосов, подписи говорящих добавит второй этап (12.11.2026)
            "голоса": "потом" if голоса_потом else "сразу",
            "тишина_начало_с": разбор["тишина_начало_с"], "тишина_конец_с": разбор["тишина_конец_с"]})
        if разбор["обрыв"]:
            self.pipe.cards.open(project_id, "technical", f"Запись «{item.path.name}» оборвана",
                                 {"file": str(item.path), "недобор_с": разбор["недобор_с"]})
        if len(части) > 1:
            self.pipe.cards.open(project_id, "event", f"Запись «{item.path.name}» разделена на {len(части)} встречи",
                                 {"паузы": разбор["паузы"], "встречи": [m for m, _, _ in встречи],
                                  "порог_паузы_мин": разбор["порог_паузы_мин"]})
        # Деление по смыслу внутри одной части (слово владелицы 12.11.2026): паузы нет, микрофон не прерывался.
        # Явные признаки — режем сразу; сомнительные — подсказка человеку.
        if len(части) == 1 and статус == "ok":
            новые = self._разделить_по_смыслу(project_id, встречи[0][0], тема, item.path.name, разбор, result)
            if новые and автозапуск_включён(self.s, project_id):
                сборки.extend(новые)
        # сборка протоколов — очередью, как автозапуск из папки
        q = getattr(self.pipe, "queue", None)
        for mid in сборки:
            self._beat(project_id, "сборка протокола", item.path.name)
            if q:
                rid = q.enqueue(project_id, mid, "автозапуск из папки-приёмника")
                if q.wait(rid, timeout=AUTORUN_WAIT_SEC).get("status") == "queued":
                    self._pending[rid] = (project_id, mid, item.path.name, None)
            else:
                self.pipe.run(project_id, mid)
        итог["status"] = статус
        итог["встречи"] = [m for m, _, _ in встречи]
        итог["частей"] = len(части)
        return итог

    def _разделить_по_смыслу(self, project_id: int, mid: int, тема: str, файл: str, разбор: dict,
                             result: dict) -> list[int]:
        """Одна часть, но по содержанию это несколько встреч (слово владелицы 12.11.2026).

        Расшифровка одна — распознавание не повторяем. Явные признаки (прощание и приветствие рядом, смена состава)
        режем сразу: первая часть остаётся в исходной встрече, остальные получают свою встречу и свой протокол.
        Сомнительные границы — карточка-подсказка с цитатой и временем, решает человек.
        """
        строки = self.s.q("SELECT id, text FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind='transcript' "
                          "ORDER BY id DESC LIMIT 1", (mid,))
        if not строки:
            return []
        sid, текст = строки[0]["id"], строки[0]["text"] or ""
        итог = peregovorka.границы_по_смыслу(текст, разбор.get("паузы") or [])
        if not итог["авто"]:
            if итог["подсказки"]:
                self.pipe.cards.open(project_id, "event", f"Запись «{файл}»: похоже на несколько встреч — проверьте",
                                     {"подсказки": итог["подсказки"], "порог_авто": peregovorka.ПОРОГ_АВТО},
                                     mid)
                result.setdefault("переговорка", [{}])[-1]["подсказки_границ"] = len(итог["подсказки"])
            return []
        куски = peregovorka.разрезать_текст(текст, итог["авто"])
        if len(куски) < 2:
            return []
        дата = (self.s.get("meetings", mid) or {}).get("date") or ""
        self.s.update("sources", sid, text=куски[0]["текст"])      # первая встреча — в исходной записи
        новые: list[int] = []
        for i, кусок in enumerate(куски[1:], start=2):
            метка = (f"{тема} · {peregovorka.ччммсс(кусок['начало_с']).replace(':', '-')}"
                     f"–{peregovorka.ччммсс(кусок['конец_с']).replace(':', '-')}")
            была = self.s.q("SELECT id FROM meetings WHERE project_id=? AND date=? AND label=? AND deleted_at IS NULL "
                            "ORDER BY id LIMIT 1", (project_id, дата, метка))
            mid2 = была[0]["id"] if была else self.s.insert(
                "meetings", project_id=project_id, date=дата, label=метка, file_name=файл,
                project_how="разделено по смыслу")
            имя = f"{тема} — часть {i} ({peregovorka.ччммсс(кусок['начало_с'])}-{peregovorka.ччммсс(кусок['конец_с'])}).txt"
            try:
                self.pipe.ingest(project_id, mid2, имя, кусок["текст"].encode("utf-8"))
            except Exception as exc:  # noqa: BLE001 — одна часть не отменяет остальные
                self.pipe.cards.open(project_id, "technical", f"Не удалось принять часть «{метка}»",
                                     {"detail": f"{type(exc).__name__}: {str(exc)[:300]}"}, mid2)
                continue
            новые.append(mid2)
        if новые:
            self.pipe.cards.open(project_id, "event", f"Запись «{файл}» разделена по смыслу на {len(куски)} встречи",
                                 {"границы": итог["авто"], "встречи": [mid] + новые}, mid)
            result.setdefault("переговорка", [{}])[-1]["разделено_по_смыслу"] = len(куски)
        return новые

    def _по_содержанию(self, mid: int, цель: int | None, чей: dict, файл: str) -> tuple[int, str]:
        """Проект по содержанию расшифровки (Доработка 2, 28.10.2026). Имя не узнало проект — решает содержание: узнан —
        встреча переносится туда вместе с тем, что к ней привязано, иначе остаётся в «Общих встречах». Имя узнало, а
        содержание уверенно говорит о другом проекте — встреча остаётся по имени, оператору карточка о расхождении:
        расхождение показывается, а не примиряется. Папка самого проекта сильнее содержания — там не сверяется."""
        from . import proekt_zapisi as pz
        справочник = pz.проекты(self.s)
        по = pz.по_содержанию(pz.текст_встречи(self.s, mid), справочник)
        if цель is None:
            if по["project_id"]:
                pz.перенести_встречу(self.s, mid, по["project_id"], "папка-приёмник")
            self.s.update("meetings", mid, project_how=по["how"])
            return по["project_id"] or pz.общие_встречи(self.s), по["how"]
        if по["project_id"] and чей.get("how") != "папка проекта" and not str(чей.get("how")).startswith("проект общей базы"):
            if pz.корень(справочник, по["project_id"]) != pz.корень(справочник, цель):
                имя = (self.s.get("projects", по["project_id"]) or {}).get("name") or ""
                self.pipe.cards.open(цель, "project_mismatch", f"Проект записи «{файл}»: по имени и по содержанию разный",
                                     {"file": файл, "by_name": чей.get("how"), "by_content": по["how"],
                                      "candidate_id": по["project_id"], "candidate": имя}, mid)
        return цель, чей.get("how") or ""

    def _meeting_for(self, project_id: int, iso_date: str, имя: str = "", строгое: bool = False) -> int:
        """Встреча дня. Несколько встреч одного дня различаются временем в именах файлов (записка 05.11.2026, п. 6):
        выгрузка ВКС рядом с записью прикрепляется к встрече своей записи, а не к первой за день. Название — тема из
        имени файла (пункт 2 плана, 08.11.2026), само имя файла — отдельным полем.
        строгое=True (аудио): своя встреча на каждую запись, без склейки по дате (26.11)."""
        rows = self.s.q("SELECT id FROM meetings WHERE project_id=? AND date=? AND deleted_at IS NULL ORDER BY id",
                        (project_id, iso_date))
        for r in rows:
            if self._по_времени(r["id"], имя, строгое=строгое):
                return r["id"]
        return self.s.insert("meetings", project_id=project_id, date=iso_date,
                             label=тема_из_приёмника(имя) or None, file_name=имя)

    def _по_времени(self, mid: int, имя: str, строгое: bool = False) -> bool:
        """Та же встреча по времени: время в имени нового файла против времён источников встречи. Нет времени хотя
        бы с одной стороны или расхождение в пределах порога — та же встреча (прежнее поведение по дате).
        строгое=True (аудиозапись): нет времени в имени — не прикрепляем, своя встреча на каждую запись (26.11)."""
        mine = время_из_имени(имя)
        if mine is None:
            # 26.11.2026: для аудио (строгое) нет времени в имени — НЕ прикрепляем к первой встрече дня,
            # заводим свою (иначе разные записи дня склеиваются в одну, и «Итоги распознавания» мешают все встречи).
            # Для транскриптов/выгрузок ВКС (не строгое) прежняя логика — прикрепление к встрече записи.
            return not строгое
        времена = [t for t in (время_из_имени(s["name"]) for s in
                               self.s.q("SELECT name FROM sources WHERE meeting_id=? AND removed_at IS NULL", (mid,)))
                   if t is not None]
        return not времена or min(abs(mine - t) for t in времена) <= ПОРОГ_ВРЕМЕНИ_МИН


    def state(self, project_id: int) -> dict[str, Any]:
        path = self.folder(project_id)
        last = self.s.get_setting("watch_last_scan", project_id)
        iv, iv_src = self.interval_info(project_id)
        info = {"folder": path, "interval": iv, "interval_source": iv_src, "worker": self.running,
                "last_scan": last, "last_useful_scan": self.s.get_setting("watch_last_useful_scan", project_id),
                "autorun": автозапуск_включён(self.s, project_id),
                # почему фон не работает и сколько раз поднимали — чтобы «нет» на мониторе было с причиной
                "last_error": self._last_error, "last_error_at": self._last_error_at, "restarts": self._restarts}
        # «завис» — по работе, а не по времени (06.11.2026): пока идёт шаг, смотрим подшаг из `hod` — дочерний
        # процесс разделения по голосам жив и его процессорное время растёт. Раньше признак считался по времени с
        # единственной отметки в начале шага, и на записи длиннее ~25 минут проход выглядел зависшим, хотя работал
        # (из-за этого 06.11 дважды перезапустили сервер и потеряли 2,5 часа распознавания).
        info["stalled"] = False
        cur = self._scanning.get(project_id)
        info["scan_in_progress"] = cur is not None
        if cur is not None:
            info.update(scan_started_at=cur["started"], scan_step=cur["step"], current_file=cur["file"],
                        step_seconds=int(time.monotonic() - cur.get("step_started", cur["pulse"])))
            подшаг = hod.ход.снимок()
            if подшаг.get("подшаг"):
                info["substep"] = подшаг
        if path and self.running:
            if cur is not None:
                if info.get("substep"):
                    info["stalled"] = hod.ход.завис(info["substep"])
                else:
                    info["stalled"] = info["step_seconds"] > max(3 * iv, STALL_STEP_SEC)
            elif last and last.get("at"):
                try:
                    age = (datetime.now() - datetime.fromisoformat(last["at"])).total_seconds()
                    info["stalled"] = age > 3 * iv
                except ValueError:
                    pass
        if path:
            p = Path(path)
            info["exists"] = p.is_dir()
            info["marker"] = p.is_dir() and any(f.is_file() and is_marker(f.name) for f in p.iterdir())
            if p.is_dir():
                files = [f for f in p.rglob("*") if f.is_file() and DONE_DIR not in f.relative_to(p).parts
                         and not is_marker(f.name) and f.name != HINT_FILE]
                info["files_waiting"] = len(files)
        return info

    # ------------------------------------------------------------ фон
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _запустить_поток(self, tick: float = 5.0) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(tick,), name="meetflow-watch", daemon=True)
        self._thread.start()

    def start(self, tick: float = 5.0) -> None:
        self._should_run = True
        if self.running:
            return
        self._запустить_поток(tick)

    def ensure_running(self) -> bool:
        """Фон обхода жив? Нет — поднять заново (сторож и мониторинг зовут это). True — поток поднят сейчас.

        Правило то же, что у папки-приёмника ERP (сторож обхода): упавший поток не должен ждать перезапуска
        сервера — иначе записи лежат в папке, а монитор говорит «нет». Поднимаем только там, где фон разрешён
        (`start` был вызван): второй экземпляр на той же базе забор не запускает.
        """
        if not self._should_run or self._stop.is_set() or self.running:
            return False
        self._restarts += 1
        try:
            self.pipe.cards.open(None, "technical", "Фоновый забор папки-приёмника перезапущен",
                                 {"причина": self._last_error or "поток обхода завершился",
                                  "когда": self._last_error_at or now(), "перезапусков": self._restarts})
        except Exception:  # noqa: BLE001 — сообщение не должно мешать подъёму потока
            pass
        self._запустить_поток()
        return True

    def start_guard(self, шаг_сек: float = 120.0) -> None:
        """Сторож фона — один на процесс: раз в две минуты проверяет поток и поднимает, если тот ушёл."""
        if not self._should_run:
            return
        if self._guard is not None and self._guard.is_alive():
            return
        self._guard_stop.clear()

        def цикл() -> None:
            warned: dict[int, float] = {}
            while not self._guard_stop.wait(шаг_сек):
                try:
                    self.ensure_running()
                    self._зависшие_проходы(warned)
                except Exception as exc:  # noqa: BLE001 — сторож не должен умирать от своего сбоя
                    self._запомнить_ошибку(exc)

        self._guard = threading.Thread(target=цикл, name="meetflow-watch-guard", daemon=True)
        self._guard.start()

    def _зависшие_проходы(self, warned: dict[int, float]) -> None:
        """Видимость зависшего прохода (26.11.2026): поток жив, но проход не пульсирует дольше STALL_STEP_SEC —
        карточка, чтобы блок не был молчаливым (раньше watch_last_scan замирал без новости). С неблокирующим
        проходом (AUTORUN_WAIT_SEC=0) ожидание сборки больше не держит обход; это диагностика на прочие случаи."""
        for pid, cur in list(self._scanning.items()):
            pulse = cur.get("pulse") or 0
            age = time.monotonic() - pulse
            if age > STALL_STEP_SEC and warned.get(pid) != pulse:
                warned[pid] = pulse
                try:
                    self.pipe.cards.open(pid, "technical", "Проход папки-приёмника завис",
                                         {"шаг": cur.get("step"), "файл": cur.get("file"),
                                          "без_движения_сек": int(age),
                                          "что_делать": "проверить очередь сборок/разбор голосов; поток обхода жив, проход не пульсирует"})
                except Exception:  # noqa: BLE001 — карточка не должна ронять сторож
                    pass

    def stop(self) -> None:
        self._should_run = False
        self._stop.set()
        self._guard_stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def busy(self) -> bool:
        """Идёт ли проход прямо сейчас (для очереди голосов: два тяжёлых шага на одном процессоре не гоняем)."""
        return bool(self._scanning)

    def _запомнить_ошибку(self, e: BaseException) -> None:
        self._last_error = f"{type(e).__name__}: {str(e)[:300]}"
        self._last_error_at = now()

    def _записать_сбой(self, project_id: int | None, e: BaseException) -> None:
        """Сбой прохода — в состояние и карточкой; карточка best-effort: база бывает занята, и тогда именно она
        и роняла поток (25.11.2026)."""
        self._запомнить_ошибку(e)
        if project_id is None:
            return
        try:
            self.pipe.cards.open(project_id, "technical", "Сбой прохода папки-приёмника",
                                 {"error": type(e).__name__, "detail": str(e)[:400],   # стенд 33
                                  "where": traceback.format_exc(limit=3)[-800:]})
        except Exception:  # noqa: BLE001 — запись карточки не должна ронять фон
            pass

    def _loop(self, tick: float) -> None:
        last: dict[int, float] = {}
        try:
            while not self._stop.is_set():
                try:
                    for r in self.s.q("SELECT project_id FROM settings WHERE key='watch_folder' AND value != 'null'"):
                        pid = r["project_id"]
                        if time.monotonic() - last.get(pid, -1e9) >= self.interval(pid):
                            last[pid] = time.monotonic()
                            try:
                                self.scan_project(pid)
                            except Exception as e:  # noqa: BLE001 — один проект не роняет обход
                                self._записать_сбой(pid, e)
                except Exception as e:  # noqa: BLE001 — база занята или настройки не прочитаны: ждём и повторяем
                    self._запомнить_ошибку(e)
                self._stop.wait(tick)
        finally:
            if not self._stop.is_set():
                self._запомнить_ошибку(RuntimeError("поток обхода завершился без остановки"))
