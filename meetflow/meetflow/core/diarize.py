# -*- coding: utf-8 -*-
"""Разделение записи по голосам — только локальными моделями, без Hugging Face.

Перенесено из ERP (`webapp/app/services/diarize.py`) по заданию владелицы 26.10.2026 («голоса — как в ERP»):
разделение даёт «Говорящий 1», «Говорящий 2»; ФИО подставляет правило `voice_rule` по общей базе отпечатков.
Модели берутся только с диска (`VOICE_MODELS_DIR`), телеметрия pyannote выключена до первого импорта.

Отличие от ERP: запасной путь на открытых моделях (VAD + wespeaker) не переносится — в MeetFlow стоит pyannote 3.1,
файлы моделей лежат на машине; если их нет, шаг честно говорит «моделей нет», а не ищет другой путь.

Сбой разделения не ломает распознавание: текст сохраняется без подписей, причина — в журнале и карточке.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import local_models

os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

MODEL_NAME = "pyannote/speaker-diarization-3.1"
NEAREST_SEC = 1.5


def enabled() -> bool:
    """По умолчанию включено. Выключить — MEETFLOW_DIARIZE=off."""
    return os.environ.get("MEETFLOW_DIARIZE", "on").strip().lower() in ("on", "1", "true", "yes")


def available() -> tuple[bool, str]:
    """Можно ли разделить запись на этой машине; вторым значением — чего не хватает, словами."""
    missing = []
    for module, why in (("pyannote.audio", "разделение по голосам"), ("torch", "вычисления"),
                        ("soundfile", "чтение звука")):
        try:
            __import__(module)
        except Exception:  # noqa: BLE001
            missing.append(f"{module} ({why})")
    ok, why = local_models.check_pyannote()
    if not ok:
        missing.append(why)
    return (not missing), "; ".join(missing)


def state() -> dict:
    """Состояние для панели: ready / not-used / broken и фраза человеку."""
    st = local_models.pyannote_state()
    if st["state"] == "ready":
        return st
    return st


def assert_local_model(name: str) -> str:
    """Пропустить только то, что лежит на этой машине: имя вида `pyannote/…` библиотека поймёт как ссылку в сеть."""
    if os.environ.get("PYANNOTEAI_API_KEY"):
        raise CloudModelRefused("На машине задан PYANNOTEAI_API_KEY — ключ облачного разделения; уберите его")
    if "/" in name and not os.path.isdir(name) and not os.path.isabs(name):
        raise CloudModelRefused(
            f"«{name}» — имя модели из сети, а не папка с файлами: голос не покидает периметр "
            "(решение владельца 05.10.26)")
    return name


class CloudModelRefused(RuntimeError):
    """Попытка загрузить модель, которая считает не на этой машине."""


def _diarization_config() -> dict:
    """Конфиг пайплайна с локальными путями вместо имён моделей (как в ERP)."""
    import yaml

    folder = local_models.assert_local(local_models.diarization_dir(), "модель разделения по голосам")
    config_yml = folder / "config.yaml"
    if not config_yml.is_file():
        raise local_models.LocalModelMissing(f"в папке {folder} нет config.yaml — это не папка модели pyannote")
    config = yaml.safe_load(config_yml.read_text(encoding="utf-8")) or {}
    params = (config.get("pipeline") or {}).get("params") or {}
    params["segmentation"] = str(local_models.assert_local(local_models.segmentation_dir(), "модель сегментации"))
    if params.get("embedding"):
        params["embedding"] = str(local_models.assert_local(local_models.embedding_dir(), "модель отпечатка голоса"))
    if local_models.plda_ready():
        params["plda"] = {"checkpoint": str(local_models.plda_dir())}
    params.pop("pyannoteai_api_key", None)
    return config


def diarize(wav_path: Path) -> tuple[list[dict], dict]:
    """Куски речи [{"start", "end", "speaker": "Говорящий N"}] и сводка {"speakers", "elapsed_seconds", "device"}.
    Номера голосов — по порядку первого появления в записи."""
    from . import otdelnyy_process

    return otdelnyy_process.выполнить(_diarize_here, Path(wav_path))


def _diarize_here(wav_path: Path) -> tuple[list[dict], dict]:
    """Сам разбор — в отдельном процессе: на процессоре он идёт минутами и держит общую блокировку Python."""
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    started = time.monotonic()
    pipeline = Pipeline.from_pretrained(_diarization_config())
    device = "процессор"
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        device = "видеокарта"
    wave, rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
    result = pipeline({"waveform": torch.from_numpy(wave.T), "sample_rate": rate})
    annotation = result.speaker_diarization if hasattr(result, "speaker_diarization") else result
    out, numbers = [], {}
    for turn, _track, speaker in annotation.itertracks(yield_label=True):
        numbers.setdefault(speaker, len(numbers) + 1)
        out.append({"start": float(turn.start), "end": float(turn.end), "speaker": f"Говорящий {numbers[speaker]}"})
    return out, {"speakers": len(numbers), "elapsed_seconds": round(time.monotonic() - started),
                 "device": device, "path": "pyannote (закрытые модели)"}


def assign(times: list[tuple[float, float]], segments: list[dict]) -> list[str | None]:
    """Голос для каждой реплики: с наибольшим пересечением по времени; без пересечения — ближайший не дальше
    NEAREST_SEC; иначе None."""
    out: list[str | None] = []
    for start, end in times:
        best, best_overlap = None, 0.0
        for seg in segments:
            overlap = min(end, seg["end"]) - max(start, seg["start"])
            if overlap > best_overlap:
                best, best_overlap = seg["speaker"], overlap
        if best is None:
            gaps = [(min(abs(seg["start"] - end), abs(start - seg["end"])), seg["speaker"]) for seg in segments]
            gap, who = min(gaps, default=(None, None), key=lambda g: g[0] if g[0] is not None else 1e9)
            best = who if gap is not None and gap <= NEAREST_SEC else None
        out.append(best)
    return out


def label_lines(lines: list[str], times: list[tuple[float, float]], segments: list[dict],
                names: dict[str, str] | None = None) -> tuple[list[str], int]:
    """«00:05:12<TAB>текст» → «00:05:12<TAB>Говорящий 2: текст». Возвращает строки и сколько подписано.

    `names` — голоса, опознанные правилом `voice_rule` ({«Говорящий 2»: ФИО}): у них строка
    «00:05:12<TAB>ФИО<TAB>текст». Не опознан — «Говорящий N»."""
    who = assign(times, segments)
    names = names or {}
    out, n = [], 0
    for line, speaker in zip(lines, who):
        if speaker:
            stamp, sep, text = line.partition("\t")
            person = names.get(speaker)
            if person and sep:
                line = f"{stamp}\t{person}\t{text}"
            else:
                line = f"{stamp}\t{speaker}: {text}" if sep else f"{speaker}: {line}"
            n += 1
        out.append(line)
    return out, n
