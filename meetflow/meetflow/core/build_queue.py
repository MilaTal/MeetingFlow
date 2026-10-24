"""Очередь сборок протоколов (находки стенда 41 и 19; обе системы 994da43…371f967, ERP — итог 13.10 12-11).

Одна сборка за раз, по датам встреч; замок — в базе, а не в памяти процесса: второй процесс с той же базой сборку не
начнёт, пока в базе есть идущая. Строка очереди — запись о начале шага: статус «идёт», номер процесса и время. После
перезапуска начатое продолжается по этой записи, а не по косвенному признаку «источник есть, протокола нет», и
выключатель автозапуска запрещает начинать новое, а не доводить начатое. Пересборка после смены модели — в очередь с
«не раньше». Ранняя встреча, пересобранная после поздних, — карточка: поздние собирались, не видя её задач.

Исполнитель — один поток на процесс; он запускается, когда в очереди есть работа, и заканчивается, когда её нет.
Код ERP (`build_queue.py`) на SQLAlchemy байт в байт не переносится; правила — те же.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from .store import now

IDLE_EXIT_SEC = 2.0


def _alive(pid: int) -> bool:
    """Жив ли процесс — по коду выхода (находка стенда 48), общей функцией очереди распознавания."""
    from ..connectors.shared.recognition_lease import _процесс_жив
    return _процесс_жив(int(pid or 0))


class BuildQueue:
    def __init__(self, pipe, tick: float = 0.5):
        self.pipe, self.s, self.tick = pipe, pipe.s, tick
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._done: dict[int, threading.Event] = {}

    # --- постановка ------------------------------------------------------------------------------------------
    def enqueue(self, project_id: int, meeting_id: int, reason: str, not_before: str | None = None,
                by: str = "") -> int:
        """Поставить сборку встречи. Уже стоит в очереди — та же строка (сборка одна), «не раньше» — раннее."""
        with self.s.tx():
            same = self.s.q("SELECT id, not_before FROM build_queue WHERE meeting_id=? AND status='queued'", (meeting_id,))
            if same:
                rid = same[0]["id"]
                if same[0]["not_before"] and (not not_before or not_before < same[0]["not_before"]):
                    self.s.update("build_queue", rid, not_before=not_before)
            else:
                m = self.s.get("meetings", meeting_id) or {}
                rid = self.s.insert("build_queue", project_id=project_id, meeting_id=meeting_id,
                                    meeting_date=m.get("date") or "", status="queued", reason=reason[:200],
                                    not_before=not_before, created_at=now(), by=by[:100])
        self._done.setdefault(rid, threading.Event())
        self._kick()
        return rid

    def _kick(self) -> None:
        self._wake.set()
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="meetflow-build-queue", daemon=True)
                self._thread.start()

    # --- исполнитель ---------------------------------------------------------------------------------------------
    def _next(self) -> dict | None:
        rows = self.s.q("SELECT * FROM build_queue WHERE status='queued' AND (not_before IS NULL OR not_before <= ?) "
                        "ORDER BY meeting_date, id LIMIT 1", (now(),))
        return rows[0] if rows else None

    def _claim(self, row: dict) -> bool:
        """Замок в базе: начать можно, только если идущей сборки нет ни у одного процесса."""
        with self.s.tx() as conn:
            cur = conn.execute("UPDATE build_queue SET status='running', started_at=?, pid=? WHERE id=? AND "
                               "status='queued' AND NOT EXISTS (SELECT 1 FROM build_queue WHERE status='running')",
                               (now(), os.getpid(), row["id"]))
            return cur.rowcount == 1

    def _early_after_late(self, row: dict) -> None:
        """Ранняя встреча собирается после того, как поздние уже собраны: их сверка дублей её задач не видела."""
        later = self.s.q("SELECT DISTINCT meeting_date FROM build_queue WHERE project_id=? AND status='done' AND "
                         "meeting_date > ? ORDER BY meeting_date", (row["project_id"], row["meeting_date"] or ""))
        if later:
            self.pipe.cards.open(row["project_id"], "technical",
                                 f"Встреча {row['meeting_date']}: ранняя пересобрана после поздних",
                                 {"later": [x["meeting_date"] for x in later][:10],
                                  "why": "поздние встречи собирались без её задач — проверьте дубли и закрытия"},
                                 row["meeting_id"])

    def run_one(self) -> bool:
        row = self._next()
        if row is None:
            return False
        lock = getattr(self.pipe, "_meeting_lock", None)
        if lock is not None and lock(row["meeting_id"]).locked():
            return False                       # сборка этой встречи уже идёт мимо очереди — ждём её конца
        if not self._claim(row):
            return False
        self._early_after_late(row)
        if str(row["reason"] or "").startswith("смена модели"):
            self.pipe.cards.open(row["project_id"], "technical",
                                 f"Встреча {row['meeting_date']}: пересборка на новой модели начата",
                                 {"why": "модель генерации сменили во время сборки; из прежнего прохода ничего не берётся"},
                                 row["meeting_id"])
        try:
            rep = self.pipe.run(row["project_id"], row["meeting_id"])
            result = getattr(rep, "__dict__", None) or {"status": "ok"}
            status = "done" if result.get("status") not in ("error",) else "failed"
        except Exception as e:  # noqa: BLE001 — сбой одной сборки не останавливает очередь; человеку — без трассировки
            self.pipe.cards.open(row["project_id"], "technical", "Сбой сервера",
                                 {"where": "сборка протокола", "error": type(e).__name__})
            result = {"status": "error", "internal_error": type(e).__name__,
                      "detail": "К сожалению, что-то пошло не так. Попробуйте ещё раз позже."}
            status = "failed"
        self.s.update("build_queue", row["id"], status=status, finished_at=now(),
                      result=json.dumps(result, ensure_ascii=False, default=str)[:20000])
        self._done.setdefault(row["id"], threading.Event()).set()
        return True

    def _loop(self) -> None:
        idle = 0.0
        while True:
            if self.run_one():
                idle = 0.0
                continue
            waiting = self.s.q("SELECT COUNT(*) AS n FROM build_queue WHERE status IN ('queued', 'running')")[0]["n"]
            if not waiting:
                idle += self.tick
                if idle >= IDLE_EXIT_SEC:
                    return                     # работы нет — поток кончается; новая постановка запустит его снова
            self._wake.wait(self.tick)
            self._wake.clear()

    # --- ожидание и состояние --------------------------------------------------------------------------------------
    def wait(self, rid: int, timeout: float = 4 * 3600) -> dict[str, Any]:
        ev = self._done.setdefault(rid, threading.Event())
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            row = self.s.get("build_queue", rid)
            if row and row["status"] in ("done", "failed"):
                return json.loads(row["result"] or "{}")
            ev.wait(0.2)
        return {"status": "queued", "detail": "сборка ещё в очереди"}

    def state(self, meeting_id: int) -> dict[str, Any]:
        """Состояние сборки встречи — для экрана (находки 3 и 4): в очереди (какая по счёту) или идёт с какого часа."""
        rows = self.s.q("SELECT * FROM build_queue WHERE meeting_id=? AND status IN ('queued', 'running') "
                        "ORDER BY id DESC LIMIT 1", (meeting_id,))
        if not rows:
            last = self.s.q("SELECT status, finished_at FROM build_queue WHERE meeting_id=? ORDER BY id DESC LIMIT 1",
                            (meeting_id,))
            return {"status": "idle", "last": last[0] if last else None}
        r = rows[0]
        if r["status"] == "running":
            return {"status": "running", "started_at": r["started_at"], "reason": r["reason"]}
        ahead = self.s.q("SELECT COUNT(*) AS n FROM build_queue WHERE status='running' OR (status='queued' AND "
                         "(meeting_date < ? OR (meeting_date = ? AND id < ?)))",
                         (r["meeting_date"], r["meeting_date"], r["id"]))[0]["n"]
        return {"status": "queued", "position": ahead + 1, "not_before": r["not_before"], "reason": r["reason"]}

    # --- после перезапуска -----------------------------------------------------------------------------------------
    def recover(self) -> list[dict[str, Any]]:
        """Начатое продолжается по записи о начале (стенд 19): строка «идёт» от умершего процесса — снова в очередь,
        независимо от автозапуска; про каждую — системное сообщение. Очередь с работой — исполнитель запускается."""
        out = []
        for r in self.s.q("SELECT * FROM build_queue WHERE status='running'"):
            if int(r["pid"] or 0) == os.getpid() or _alive(r["pid"]):
                continue
            self.s.update("build_queue", r["id"], status="queued", reason=(r["reason"] or "") + " · после перезапуска")
            self.pipe.cards.open(r["project_id"], "technical",
                                 f"Встреча {r['meeting_date']}: продолжаю сборку после перезапуска",
                                 {"why": "сборка была начата; по записи о начале она продолжается сама — нажимать "
                                         "ничего не нужно"}, r["meeting_id"])
            out.append({"meeting_id": r["meeting_id"], "status": "requeued"})
        if self.s.q("SELECT COUNT(*) AS n FROM build_queue WHERE status='queued'")[0]["n"]:
            self._kick()
        return out


def later(seconds: float) -> str:
    return (datetime.now() + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S")
