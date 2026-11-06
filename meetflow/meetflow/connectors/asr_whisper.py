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
- Маршруты (09.10.26): если в models.json есть роль asr, точки идут по её цепочке — faster-whisper с моделью
  и устройством точки или свой код «модуль:функция»; сбой точки — следующая, точка выводится на охлаждение.
  Без роли — модель темы, как раньше. Супер-администратор выбирает точку на вкладке «Модели».
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

from ..core.types import SourceDoc, SourceKind
from .base import ASRConnector, ConnectorError
from . import llm_routes
from .shared import model_routes as _mr
from .shared import recognition_lease

log = logging.getLogger(__name__)

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
        self._models: dict[tuple, object] = {}
        self.last_route = ""
        # Подсказка распознаванию на одну запись (словарь проектов, `core/slovar_whisper`, как ERP 24–25.10.2026):
        # ставит конвейер перед `transcribe` и снимает после; пусто — без подсказки, как было
        self.initial_prompt = ""

    def available(self) -> bool:
        """Установлен ли faster-whisper — поиском модуля, без импорта: импорт тянет torch, тысячи модулей и
        секунды на первом запросе мониторинга (находка стенда 13, ERP 8020). Импорт — только при распознавании."""
        try:
            return importlib.util.find_spec("faster_whisper") is not None
        except (ImportError, ValueError):
            return False

    def health(self) -> dict:
        ok = self.available()
        return {"name": self.name, "ok": ok, "offline": os.environ.get("HF_HUB_OFFLINE") == "1",
                "detail": "" if ok else "faster-whisper не установлен: записи ждут (waiting_tools)"}

    def _load(self):
        if self._model is None:
            if not self.available():
                raise ConnectorError("waiting_tools: инструменты распознавания не установлены, запись ждёт.")
            from faster_whisper import WhisperModel
            try:
                self._model = WhisperModel(self.model_name, device="cuda", compute_type="int8_float16",
                                           local_files_only=True)
            except Exception as e:     # не молча (находка стенда 33): откат на процессор — в журнал с причиной
                log.warning("Распознавание: видеокарта недоступна (%s: %s) — модель %s на процессоре",
                            type(e).__name__, e, self.model_name)
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                           local_files_only=True)
        return self._model

    def _load_point(self, model: str, device: str = "auto"):
        """Модель точки маршрута; «auto» — видеокарта с откатом на процессор, «cuda» — без отката: откат даёт
        следующая точка цепочки."""
        key = (model, device)
        if key not in self._models:
            if not self.available():
                raise ConnectorError("waiting_tools: инструменты распознавания не установлены, запись ждёт.")
            from faster_whisper import WhisperModel
            if device == "cpu":
                m = WhisperModel(model, device="cpu", compute_type="int8", local_files_only=True)
            else:
                try:
                    m = WhisperModel(model, device="cuda", compute_type="int8_float16", local_files_only=True)
                except Exception as e:
                    if device == "cuda":
                        raise
                    log.warning("Распознавание: видеокарта недоступна (%s: %s) — модель %s на процессоре",
                                type(e).__name__, e, model)
                    m = WhisperModel(model, device="cpu", compute_type="int8", local_files_only=True)
            self._models[key] = m
        return self._models[key]

    def _run(self, model, path: Path):
        доп = {"initial_prompt": self.initial_prompt} if self.initial_prompt else {}
        segments, info = model.transcribe(str(path), language=self.language, vad_filter=True, beam_size=5, **доп)
        lines, texts, times = [], [], []
        for s in segments:
            text = s.text.strip()
            if not text:
                continue
            start = float(getattr(s, "start", 0) or 0)
            # Конец реплики: у настоящего faster-whisper он есть; в тестовых заглушках бывает только начало.
            end = float(getattr(s, "end", start + 2.0) or (start + 2.0))
            lines.append(f"[{_fmt(start)}] {text}")
            # Для разбора по голосам: чистый текст и границы реплики. Метку «Говорящий N» ставит `diarize` —
            # здесь её быть не должно, иначе каждая строка выглядит подписанной без номера.
            texts.append(text)
            times.append([round(start, 2), round(end, 2)])
        return lines, getattr(info, "duration", 0) or 0, {"segment_lines": texts, "segment_times": times}

    def _run_code(self, ref: str, path: Path, folder: str = ""):
        """Свой движок: функция(путь, language=…) возвращает текст или (текст, сведения с duration в секундах).
        `folder` — папка с кодом, если он не установлен пакетом."""
        import importlib
        import sys
        if folder:
            if not Path(folder).is_dir():
                raise ConnectorError(f"папки с кодом нет: {folder}")
            if folder not in sys.path:
                sys.path.insert(0, folder)
        mod, fn = ref.split(":", 1)
        res = getattr(importlib.import_module(mod), fn)(str(path), language=self.language)
        text, meta = res if isinstance(res, tuple) else (res, {})
        return [x for x in str(text).splitlines() if x.strip()], float((meta or {}).get("duration") or 0), dict(meta or {})

    def _run_service(self, url: str, path: Path):
        """Сервис распознавания во внутренней сети: POST wav (audio/wav), язык в строке запроса, ответ JSON
        {"text": …, "meta": {"duration": …}}. Адрес вне внутренней сети не принимается."""
        import json
        import urllib.parse
        import urllib.request
        if not llm_routes.internal_url(url):
            raise ConnectorError("сервис распознавания — только во внутренней сети")
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode({"language": self.language})
        req = urllib.request.Request(full, data=Path(path).read_bytes(), headers={"Content-Type": "audio/wav"}, method="POST")
        with urllib.request.urlopen(req, timeout=4 * 3600) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        meta = raw.get("meta") or {}
        return [x for x in str(raw.get("text") or "").splitlines() if x.strip()], float(meta.get("duration") or 0)

    def _run_service_shared(self, name: str, ep: dict, path: Path):
        """Сервис распознавания во внутренней сети — свой вызов (`asr_service.call`): общий код ERP и Планёрки
        оставляет только строки «ЧЧ:ММ:СС<TAB>текст», а нам нужны времена реплик для разделения по голосам.
        Протокол ответа тот же: текст — строки расшифровки, сводка — `segment_lines`/`segment_times`."""
        from . import asr_service
        text, meta = asr_service.call(_mr._route(name, ep), path, language=self.language,
                                      initial_prompt=self.initial_prompt or "")
        lines = []
        for ln in str(text or "").splitlines():
            if not ln.strip():
                continue
            ts, tab, rest = ln.partition("\t")
            lines.append(f"[{ts}] {rest.strip()}" if tab and ts.count(":") == 2 else ln)
        return lines, float((meta or {}).get("duration") or (meta or {}).get("media_seconds") or 0), dict(meta or {})

    def transcribe(self, path: Path) -> SourceDoc:
        path = Path(path)
        if not path.exists():
            raise ConnectorError(f"Запись «{path.name}» не найдена.")
        routes = llm_routes.asr_chain()
        self.last_route = ""
        if routes is None:
            # модели по умолчанию нет (13.10.26, ответ владельца 15.10.26): роль не назначена — запись ждёт, а не
            # распознаётся моделью темы
            raise ConnectorError("waiting_tools: распознавание не настроено — назначьте точку роли «Распознавание "
                                 "речи» в «Моделях»; запись ждёт")
        points, cooldown = routes
        # очередь распознавания на одну машину — общая аренда ERP, Планёрки и MeetFlow (recognition_lease.py):
        # пока распознаёт другой продукт, запись ждёт на месте и берётся на следующем проходе
        with recognition_lease.держит_аренду("meetflow", path.name) as lease:
            if not lease.взято:
                raise ConnectorError(f"waiting_tools: очередь распознавания на машине — {lease.причина}; запись ждёт")
            errors = []
            segment_meta: dict = {}
            for name, ep in points:
                try:
                    if ep["kind"] == "python":
                        lines, duration, segment_meta = self._run_code(ep["callable"], path, ep.get("path", ""))
                    elif ep["kind"] == "asr-service":
                        lines, duration, segment_meta = self._run_service_shared(name, ep, path)
                    else:
                        lines, duration, segment_meta = self._run(
                            self._load_point(ep["model"], ep.get("device", "auto")), path)
                except Exception as e:  # noqa: BLE001 — любой сбой точки ведёт на следующую
                    llm_routes.mark_down(name, cooldown, str(e))
                    errors.append(f"{name}: {str(e)[:150]}")
                    continue
                llm_routes.mark_up(name)
                self.last_route = name
                # подсказка ушла только faster-whisper и сервису; свой код «модуль:функция» её не принимает
                prompt_sent = bool(self.initial_prompt) and ep["kind"] != "python"
                break
            else:
                raise ConnectorError("waiting_tools: ни одна точка распознавания не сработала, запись ждёт — "
                                     + "; ".join(errors))
        dur_min = duration / 60
        if self.duration_min and dur_min < self.duration_min or self.duration_max and dur_min > self.duration_max:
            raise ConnectorError(f"held_recording: длительность {dur_min:.0f} мин вне окна темы.")
        # запись удаляет конвейер ПОСЛЕ сохранения расшифровки (находка ревью:
        # удаление до записи в БД теряло встречу при сбое) — см. Pipeline.ingest
        meta = {"connector": self.name, "media_seconds": duration or None, "route": self.last_route,
                "local": True, "media_path": str(path), "keep_media": self.keep_media}
        # Времена реплик и их текст — для разбора по голосам. Пустые не кладём, чтобы не выглядело,
        # будто разбор был и ничего не нашёл.
        for key in ("segment_lines", "segment_times", "segments", "speakers", "model", "device"):
            value = (segment_meta or {}).get(key)
            if value not in (None, [], ""):
                meta[key] = value
        meta.setdefault("model", self.last_route)
        if prompt_sent:
            meta["asr_prompt_sent"] = True
        return SourceDoc(f"{path.stem} (распознано локально).txt", SourceKind.TRANSCRIPT, "\n".join(lines), meta)


def asr_ping(ep: dict) -> tuple[bool, str]:
    """Проверка точки распознавания без записи: движок установлен, модель на диске, код находится."""
    if ep.get("kind") == "asr-service":
        # тем же путём, что работа: пробный запрос с крошечной тишиной (общий ping ERP и Планёрки, 12.10.26)
        return _mr.ping(_mr._route("проверка", ep))
    if ep.get("kind") == "python":
        import importlib
        import sys
        folder = str(ep.get("path") or "")
        if folder:
            if not Path(folder).is_dir():
                return False, f"папки с кодом нет: {folder}"
            if folder not in sys.path:
                sys.path.insert(0, folder)
        mod, fn = str(ep.get("callable", "")).split(":", 1)
        try:
            ok = callable(getattr(importlib.import_module(mod), fn, None))
        except Exception as e:  # noqa: BLE001
            return False, f"код не загрузился: {str(e)[:150]}"
        return ok, "код найден" if ok else f"в модуле {mod} нет функции {fn}"
    if not WhisperLocalASR().available():
        return False, "faster-whisper не установлен"
    model = str(ep.get("model", ""))
    if Path(model).exists():
        return True, f"модель на диске, устройство {ep.get('device', 'auto')}"
    if "/" in model or "\\" in model:
        return False, "папки модели нет"
    return True, f"модель «{model}» берётся из локального кэша, устройство {ep.get('device', 'auto')}"
