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

import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..connectors.base import ConnectorError
from ..connectors.watch_folder import (DONE_DIR, MARKER, SKIP_WORDS, STOPPED_DIR, FolderIntake, check_folder_path,
                                       single_date)
from .store import now

HINT_FILE = "ЧТО СЮДА КЛАСТЬ.md"
HINT_TEXT = ("# Папка-приёмник встреч\n\nСюда кладутся записи и расшифровки встреч. В имени файла — одна дата "
             "встречи, например «Встреча 01.10.2026.mp4». Обработанные файлы уезжают в подпапку «обработано». "
             "Файл без даты остаётся на месте, о нём придёт сообщение.\n")
DEFAULT_INTERVAL = 900
MIN_INTERVAL = 30
BIG_FIRST_PASS = int(os.environ.get("MEETFLOW_WATCH_BIG_FIRST_PASS", "25"))


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
        (p / MARKER).write_text("Эта папка назначена приёмником встреч MeetFlow.\n", encoding="utf-8")
        (p / HINT_FILE).write_text(HINT_TEXT, encoding="utf-8")


def preview_folder(p: Path) -> dict[str, Any]:
    """Что лежит в папке и что заберёт первый проход — до смены адреса (как в Планёрке и ERP с 07.10.26)."""
    files, take, no_date = [], [], []
    for f in sorted(p.rglob("*")):
        parts = f.relative_to(p).parts
        if (not f.is_file() or DONE_DIR in parts or STOPPED_DIR in parts or f.name in (MARKER, HINT_FILE)
                or f.suffix.lower() == ".md" or any(w in f.name.lower() for w in SKIP_WORDS)):
            continue
        files.append(f.name)
        (take if (single_date(f.name) or single_date(f.parent.name)) else no_date).append(f.name)
    return {"files": len(files), "first_pass": len(take), "examples": take[:5], "no_date": no_date[:5],
            "big": len(take) > BIG_FIRST_PASS, "big_limit": BIG_FIRST_PASS}


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
        self.pipe.cards.open(project_id, "technical", "Изменён адрес папки-приёмника",
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
        with self._lock:
            fi = self._intakes.get(project_id)
            if fi is None or str(fi.folder) != path:
                # FolderIntake сравнивает байты файлов; повтор ручной загрузки
                # ловит конвейер по отпечатку текста (ingest -> duplicate)
                fi = self._intakes[project_id] = FolderIntake(path, set(), today)
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
        result.update(waiting=scan.waiting, no_date=scan.no_date, duplicates=scan.duplicates)
        for name in scan.no_date:
            self.pipe.cards.open(project_id, "technical", f"В имени файла нет одной даты: {name}",
                                 {"folder": path, "file": name})
        for item in scan.ready:
            mid = self._meeting_for(project_id, item.meeting_date.isoformat())
            is_media = self.pipe.plugins.resolve_source(item.path.name) is not None and \
                self.pipe.plugins.resolve_source(item.path.name).kind == "asr"
            data = None if is_media else item.path.read_bytes()
            res = self.pipe.ingest(project_id, mid, item.path.name, data, path=item.path if is_media else None)
            st = res.get("status")
            if st in ("ok", "duplicate"):
                fi.known.add(item.digest)
                moved = None
                if item.path.exists():  # запись мог уже удалить конвейер после распознавания
                    moved = fi.done(item.path)
                result["ingested" if st == "ok" else "duplicates"].append(item.path.name)
                if st == "ok" and res.get("kind") == "transcript" and \
                        self.s.get_setting("autorun", project_id, False):
                    rep = self.pipe.run(project_id, mid)
                    result.setdefault("autorun", []).append({"meeting_id": mid, "status": rep.status})
                    if rep.status == "stopped_by_limit" and moved and moved.exists():
                        # не «обработано»: прогон неполный, повтор — решение человека (01/11)
                        to = fi.stopped(moved)
                        self.pipe.cards.open(project_id, "stopped_by_limit",
                                             f"Файл «{item.path.name}» обработан не полностью — лежит в «остановлено»",
                                             {"file": str(to), "detail": rep.detail}, mid)
            elif st == "held":
                result["held"].append(item.path.name)          # ждёт на месте
            else:
                result["rejected"].append(item.path.name)
                self.pipe.cards.open(project_id, "technical", f"Файл из папки не принят: {item.path.name}",
                                     {"reason": res.get("reason", "")})
        result["status"] = "ok"
        self.s.set_setting("watch_last_scan", result, project_id)
        if any(result[k] for k in ("ingested", "held", "rejected", "duplicates", "no_date")):
            self.s.set_setting("watch_last_useful_scan", result, project_id)
        return result

    def _meeting_for(self, project_id: int, iso_date: str) -> int:
        rows = self.s.q("SELECT id FROM meetings WHERE project_id=? AND date=? ORDER BY id", (project_id, iso_date))
        if rows:
            return rows[0]["id"]
        return self.s.insert("meetings", project_id=project_id, date=iso_date, label="из папки-приёмника")

    def state(self, project_id: int) -> dict[str, Any]:
        path = self.folder(project_id)
        last = self.s.get_setting("watch_last_scan", project_id)
        iv, iv_src = self.interval_info(project_id)
        info = {"folder": path, "interval": iv, "interval_source": iv_src, "worker": self.running,
                "last_scan": last, "last_useful_scan": self.s.get_setting("watch_last_useful_scan", project_id),
                "autorun": bool(self.s.get_setting("autorun", project_id, False))}
        # поток жив, а проходов нет дольше трёх интервалов — «завис» (как в ERP)
        info["stalled"] = False
        if path and self.running and last and last.get("at"):
            try:
                age = (datetime.now() - datetime.fromisoformat(last["at"])).total_seconds()
                info["stalled"] = age > 3 * iv
            except ValueError:
                pass
        if path:
            p = Path(path)
            info["exists"] = p.is_dir()
            info["marker"] = (p / MARKER).exists()
            if p.is_dir():
                files = [f for f in p.rglob("*") if f.is_file() and DONE_DIR not in f.relative_to(p).parts
                         and f.name not in (MARKER, HINT_FILE)]
                info["files_waiting"] = len(files)
        return info

    # ------------------------------------------------------------ фон
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, tick: float = 5.0) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(tick,), name="meetflow-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self, tick: float) -> None:
        last: dict[int, float] = {}
        while not self._stop.is_set():
            for r in self.s.q("SELECT project_id FROM settings WHERE key='watch_folder' AND value != 'null'"):
                pid = r["project_id"]
                if time.monotonic() - last.get(pid, -1e9) >= self.interval(pid):
                    last[pid] = time.monotonic()
                    try:
                        self.scan_project(pid)
                    except Exception as e:  # фон не должен падать целиком
                        self.pipe.cards.open(pid, "technical", "Сбой прохода папки-приёмника",
                                             {"error": type(e).__name__})
            self._stop.wait(tick)
