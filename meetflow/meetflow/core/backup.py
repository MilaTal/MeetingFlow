"""Копии базы — как в Проекте ERP: автокопия по расписанию и «Снять копию сейчас» на мониторинге.

Копия снимается штатным sqlite3 backup (согласованный снимок без остановки сервера) в папку backups рядом с базой.
Автокопии ротируются (храним MEETFLOW_BACKUP_KEEP, по умолчанию 14), ручные — отдельно, ротация их не трогает.
Расписание — MEETFLOW_BACKUP_HOURS (24), выключить — MEETFLOW_BACKUP=off.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class Backups:
    def __init__(self, db_path: str):
        self.db = Path(db_path)
        self.dir = self.db.parent / "backups"
        self.hours = float(os.environ.get("MEETFLOW_BACKUP_HOURS", "24") or 24)
        self.keep = int(os.environ.get("MEETFLOW_BACKUP_KEEP", "14") or 14)
        self.enabled = os.environ.get("MEETFLOW_BACKUP", "on").strip().lower() != "off" and str(db_path) != ":memory:"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""

    def snapshot(self, manual: bool = False) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        kind = "ручная" if manual else "авто"
        target = self.dir / f"{self.db.stem}_{kind}_{datetime.now():%Y-%m-%d_%H-%M-%S}.db"
        src = sqlite3.connect(self.db.resolve().as_uri() + "?mode=ro", uri=True)
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        if not manual:
            autos = sorted(self.dir.glob(f"{self.db.stem}_авто_*.db"))
            for old in autos[:-self.keep] if self.keep > 0 else []:
                old.unlink(missing_ok=True)
        return target

    def files(self) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for f in sorted(self.dir.glob("*.db"), key=lambda x: x.stat().st_mtime, reverse=True):
            out.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1), "manual": "_ручная_" in f.name,
                        "at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")})
        return out

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="meetflow-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(max(60.0, self.hours * 3600)):
            try:
                self.snapshot()
                self.last_error = ""
            except Exception as e:  # фон не падает; ошибка видна на мониторинге
                self.last_error = type(e).__name__
