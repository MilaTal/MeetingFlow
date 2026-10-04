"""ASR: локальный faster-whisper. Голос не покидает периметр (правило 24.09).

Перенесённые уроки:
- Модель только из локального кэша (local_files_only) и HF_HUB_OFFLINE=1:
  faster-whisper ходил на huggingface.co перед каждой записью (30.09).
- Телеметрия pyannote выключена (PYANNOTE_METRICS_ENABLED=false).
- Облачные клиенты распознавания не подключаются никогда.
- GPU с откатом на CPU; без инструментов запись не теряется, а ждёт
  (waiting_tools) — сообщение уходит супер-админу.
- Длительность вне окна (тема: intake.duration_min/max) — карточка.
- Подсказка распознаванию (initial_prompt/hotwords) по умолчанию выключена:
  замеры ERP и Планёрки показали потерю 6-14 % объёма и искажения.
- После успешного распознавания запись удаляется (keep_media=False).
"""
from __future__ import annotations

import os
from pathlib import Path

from ..core.types import SourceDoc, SourceKind
from .base import ASRConnector, ConnectorError

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

FORBIDDEN_CLOUD = ("pyannoteai", "speechkit", "openai.audio", "deepgram", "assemblyai")


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class WhisperLocalASR(ASRConnector):
    name = "whisper_local"

    def __init__(self, model: str = "large-v3", language: str = "ru", keep_media: bool = False,
                 duration_min: float | None = None, duration_max: float | None = None):
        self.model_name = model
        self.language = language
        self.keep_media = keep_media
        self.duration_min = duration_min
        self.duration_max = duration_max
        self._model = None

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def health(self) -> dict:
        return {"name": self.name, "ok": self.available(), "offline": os.environ.get("HF_HUB_OFFLINE") == "1",
                "detail": "" if self.available() else "faster-whisper не установлен: записи ждут (waiting_tools)"}

    def _load(self):
        if self._model is None:
            if not self.available():
                raise ConnectorError("waiting_tools: инструменты распознавания не установлены, запись ждёт.")
            from faster_whisper import WhisperModel
            try:
                self._model = WhisperModel(self.model_name, device="cuda", compute_type="int8_float16",
                                           local_files_only=True)
            except Exception:
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                           local_files_only=True)
        return self._model

    def transcribe(self, path: Path) -> SourceDoc:
        path = Path(path)
        if not path.exists():
            raise ConnectorError(f"Запись «{path.name}» не найдена.")
        model = self._load()
        segments, info = model.transcribe(str(path), language=self.language, vad_filter=True, beam_size=5)
        dur_min = (getattr(info, "duration", 0) or 0) / 60
        if self.duration_min and dur_min < self.duration_min or self.duration_max and dur_min > self.duration_max:
            raise ConnectorError(f"held_recording: длительность {dur_min:.0f} мин вне окна темы.")
        lines = [f"[{_fmt(s.start)}] Говорящий: {s.text.strip()}" for s in segments if s.text.strip()]
        # запись удаляет конвейер ПОСЛЕ сохранения расшифровки (находка ревью:
        # удаление до записи в БД теряло встречу при сбое) — см. Pipeline.ingest
        return SourceDoc(f"{path.stem} (распознано локально).txt", SourceKind.TRANSCRIPT, "\n".join(lines),
                         {"connector": self.name, "media_seconds": getattr(info, "duration", None),
                          "local": True, "media_path": str(path), "keep_media": self.keep_media})
