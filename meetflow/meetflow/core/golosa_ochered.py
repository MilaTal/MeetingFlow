"""Второй этап: голоса для длинных записей — после протокола, фоном (12.11.2026).

Слово владелицы: пользователю нужен итоговый вариант **с голосами**, но ждать часы нельзя. Поэтому два этапа:

1. Расшифровка → протокол без голосов (минуты). Человек уже работает с протоколом.
2. Разделение по голосам в фоне, затем пересборка того же протокола — уже с подписями говорящих.

Деградация: если голоса не разобрались (нет модели, сбой pyannote, нет записи на диске), протокол остаётся
безымянным, в источнике — «сбой: причина», в «Конфликтах» — карточка. Ничего не теряется.

Почему так, а не «сначала голоса»: в рабочей практике (ASR-first, затем diarization) голоса ставятся на готовый
текст, и сбой разделения не отменяет расшифровку; разделение «сначала» передаёт ошибки границ в текст. Плюс
разделение по голосам на процессоре идёт часами — держать протокол в заложниках нельзя.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

СОСТОЯНИЕ_ЖДЁТ = "ждут голоса (потом)"


class GolosaOchered:
    """Очередь голосов: строки источников с состоянием «ждут голоса (потом)». Отдельной таблицы не заводим."""

    def __init__(self, pipe, intake=None, pause: float = 60.0):
        self.pipe = pipe
        self.s = pipe.s
        self.intake = intake
        self.pause = pause
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.идёт: dict | None = None        # что разбирается сейчас — для /health

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._цикл, name="meetflow-voices", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def ожидают(self) -> int:
        return self.s.q("SELECT COUNT(*) AS n FROM sources WHERE removed_at IS NULL AND voice_state=?",
                        (СОСТОЯНИЕ_ЖДЁТ,))[0]["n"]

    def _цикл(self) -> None:
        while not self._stop.is_set():
            try:
                if self.intake is not None and self.intake.busy():
                    self._stop.wait(self.pause)      # идёт проход приёмника — не отбираем процессор
                    continue
                row = self.s.q("SELECT * FROM sources WHERE removed_at IS NULL AND voice_state=? ORDER BY id LIMIT 1",
                               (СОСТОЯНИЕ_ЖДЁТ,))
                if not row:
                    self._stop.wait(self.pause)
                    continue
                self._разобрать(row[0])
            except Exception as exc:  # noqa: BLE001 — фон не должен падать целиком
                self.идёт = None
                self.pipe.cards.open(None, "technical", "Сбой очереди голосов",
                                     {"error": type(exc).__name__, "detail": str(exc)[:300]})
                self._stop.wait(self.pause)
            self._stop.wait(5)

    def _разобрать(self, row: dict) -> None:
        sid, mid = int(row["id"]), int(row["meeting_id"])
        meta = json.loads(row.get("meta") or "{}")
        путь = Path(meta.get("media_path") or "")
        проект = self.s.q("SELECT project_id FROM meetings WHERE id=?", (mid,))
        project_id = int(проект[0]["project_id"]) if проект else None
        self.идёт = {"source_id": sid, "meeting_id": mid, "file": row.get("name") or ""}
        if not (meta.get("media_path") and путь.is_file()):
            self.s.update("sources", sid, voice_state="сбой: записи нет на диске — голоса не разобраны")
            self.pipe.cards.open(project_id, "technical", "Голоса: записи нет на диске",
                                 {"source_id": sid, "file": str(путь)}, mid)
            self.идёт = None
            return
        from .types import SourceDoc, SourceKind
        doc = SourceDoc(row.get("name") or "", SourceKind.TRANSCRIPT, row.get("text") or "", meta)
        try:
            self.pipe._voice_step(project_id, mid, путь, doc, row.get("name") or "")
            причина = str(doc.meta.get("voice_error") or "")
            self.s.update("sources", sid, text=doc.text, meta=json.dumps(doc.meta, ensure_ascii=False),
                          voice_state=("сбой: " + причина[:300]) if причина else "готово")
            if причина:
                # деградация видна человеку: протокол остался без подписей, причина названа
                self.pipe.cards.open(project_id, "technical", "Голоса не разобраны — протокол остался без подписей",
                                     {"source_id": sid, "file": str(путь), "причина": причина[:300]}, mid)
            elif doc.meta.get("signed_lines"):
                # протокол собран без голосов — пересобираем, чтобы подписи говорящих попали в документ
                q = getattr(self.pipe, "queue", None)
                if q:
                    q.enqueue(project_id, mid, "голоса разобраны — пересборка протокола")
                else:
                    self.pipe.run(project_id, mid)
        except Exception as exc:  # noqa: BLE001 — деградация: протокол без голосов остаётся
            self.s.update("sources", sid, voice_state=f"сбой: {type(exc).__name__}: {str(exc)[:200]}")
            self.pipe.cards.open(project_id, "technical", "Голоса не разобраны — протокол остался без подписей",
                                 {"source_id": sid, "file": str(путь)}, mid)
        finally:
            self.идёт = None
        # запись нужна была только шагу голосов: после разбора её можно удалить (расшифровка уже в базе)
        try:
            if путь.is_file():
                путь.unlink()
                self.s.update("sources", sid, removed_reason="запись распознана и разобрана по голосам, файл удалён")
        except OSError:
            pass
