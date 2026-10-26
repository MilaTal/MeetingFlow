"""Папка-приёмник: забирает файлы встреч без участия человека.

Перенесено из Планёрки и ERP:
- Защита пути: нельзя корень диска, домашнюю папку, Документы, Рабочий стол,
  Загрузки; непустая папка принимается только с файлом-меткой.
- Файл берётся только «осевшим»: размер не меняется между двумя проходами
  (растущая запись давала платный прогон каждые 15 мин при «взято 0»).
- Дата — ровно одна из имени файла (core.dates.single_date); без даты
  файл остаётся на месте, причина сообщается ОДИН раз на имя.
- Дубль — по отпечатку содержимого, в том числе между папкой и ручной загрузкой.
- Обработанное уезжает в подпапку «обработано»; метки и .md-памятки не источники.
- Недоступная папка — не «пустой успешный проход», а ошибка.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..core.dates import single_date
from .base import ConnectorError

MARKER = "ЭТО ПАПКА-ПРИЕМНИК.txt"  # основное имя с «е» (правило владелицы 26.10.2026)
# Принимаются оба имени Планёрки и ERP («…ПРИЕМНИК.txt», «…ПРИЕМНИК ЗАПИСЕЙ.txt») с «е» или «ё» и в любом регистре:
# метку пишет человек руками, отказ по одной букве стоит ему рабочего времени (Планёрка 07.10.26, MeetFlow 26.10.26).
MARKER_NAMES = (MARKER, "ЭТО ПАПКА-ПРИЕМНИК ЗАПИСЕЙ.txt")
# Служебные файлы проводника и офиса папку «непустой» не делают.
SLUZHEBNYE = {"desktop.ini", "thumbs.db", ".ds_store"}


def _norm(name: str) -> str:
    return name.strip().casefold().replace("ё", "е")


_METKI = {_norm(n) for n in MARKER_NAMES}


def is_marker(name: str) -> bool:
    return _norm(name) in _METKI


def _sluzhebnyy(f: Path) -> bool:
    return f.name.casefold() in SLUZHEBNYE or f.name.startswith("~$")
DONE_DIR = "обработано"
STOPPED_DIR = "остановлено"   # прогон остановлен по пределу: повтор — решение человека (01/11)
SKIP_WORDS = ("не брать",)


def check_folder_path(path: Path, home: Path | None = None) -> None:
    p = path.resolve()
    home = (home or Path.home()).resolve()
    forbidden = {home, home / "Documents", home / "Desktop", home / "Downloads",
                 home / "Документы", home / "Рабочий стол", home / "Загрузки"}
    if p == Path(p.anchor) or p in forbidden:
        raise ConnectorError(f"Папку «{p}» нельзя назначить приёмником: это системная или общая папка.")
    if p.exists() and not p.is_dir():
        raise ConnectorError(f"«{p}» — это файл, а не папка.")
    if p.exists():
        vse = [f for f in p.iterdir() if not _sluzhebnyy(f)]
        if vse and not any(f.is_file() and is_marker(f.name) for f in vse):
            raise ConnectorError(f"Папка «{p}» не пустая и без файла-метки «{MARKER}» (подходит и «ЭТО ПАПКА-ПРИЕМНИК ЗАПИСЕЙ.txt», с «е» или «ё»).")


@dataclass
class IntakeItem:
    path: Path
    meeting_date: date
    digest: str


@dataclass
class ScanResult:
    ready: list[IntakeItem] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)     # ещё пишется
    no_date: list[str] = field(default_factory=list)     # сообщить один раз
    duplicates: list[str] = field(default_factory=list)


class FolderIntake:
    def __init__(self, folder: str | Path, known_digests: set[str] | None = None, today: date | None = None):
        self.folder = Path(folder)
        self.known = known_digests if known_digests is not None else set()
        self._sizes: dict[Path, int] = {}
        self._reported_no_date: set[str] = set()
        self.today = today

    def scan(self) -> ScanResult:
        if not self.folder.exists() or not self.folder.is_dir():
            raise ConnectorError(f"Папка-приёмник недоступна: {self.folder}")
        res = ScanResult()
        for f in sorted(self.folder.rglob("*")):
            parts = f.relative_to(self.folder).parts
            if (not f.is_file() or DONE_DIR in parts or STOPPED_DIR in parts or is_marker(f.name) or _sluzhebnyy(f)
                    or f.suffix.lower() == ".md"):
                continue
            if any(w in f.name.lower() for w in SKIP_WORDS):
                continue
            size = f.stat().st_size
            if self._sizes.get(f) != size or size == 0:
                self._sizes[f] = size
                res.waiting.append(f.name)
                continue
            d = single_date(f.name, self.today) or single_date(f.parent.name, self.today)
            if d is None:
                if f.name not in self._reported_no_date:
                    self._reported_no_date.add(f.name)
                    res.no_date.append(f.name)
                continue
            dg = hashlib.sha256(f.read_bytes()).hexdigest()
            if dg in self.known:
                res.duplicates.append(f.name)
                self.done(f)
                continue
            res.ready.append(IntakeItem(f, d, dg))
        return res

    def stopped(self, path: Path) -> Path:
        return self.done(path, STOPPED_DIR)

    def done(self, path: Path, subdir: str = DONE_DIR) -> Path:
        target_dir = self.folder / subdir
        target_dir.mkdir(exist_ok=True)
        target = target_dir / path.name
        n = 1
        while target.exists():
            target = target_dir / f"{path.stem} ({n}){path.suffix}"
            n += 1
        path.replace(target)
        self._sizes.pop(path, None)
        return target
