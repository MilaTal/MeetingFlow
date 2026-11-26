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
import re
import time
from pathlib import Path

from . import local_models

os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

MODEL_NAME = "pyannote/speaker-diarization-3.1"
NEAREST_SEC = 1.5
LONG_LINE_SEC = 30.0     # строка длиннее — делим по предложениям и голосам (перенос из Планёрки, 18.11.2026)
MIN_SEGMENT_SEC = 5.0    # голос короче не даёт имени строке: «Доброе утро» без отпечатка пропускается


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


def free_memory_bytes() -> int | None:
    """Сколько физической памяти свободно сейчас, байт; None — измерить не удалось.

    Нужно перед pyannote (21.11.2026): на машине 32 ГБ, но при браузере, двух серверах и проверке местами
    остаётся меньше гигабайта. Дочерний процесс тогда убивает система, а сборка получает `BrokenProcessPool`
    и повторяет разбор пять раз. Лучше честно сказать «мало памяти» и сохранить запись, чем терять причину.
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class Память(ctypes.Structure):
                _fields_ = [("длина", wintypes.DWORD), ("загрузка", wintypes.DWORD),
                            ("всего_физ", ctypes.c_ulonglong), ("свободно_физ", ctypes.c_ulonglong),
                            ("всего_файл", ctypes.c_ulonglong), ("свободно_файл", ctypes.c_ulonglong),
                            ("всего_вирт", ctypes.c_ulonglong), ("свободно_вирт", ctypes.c_ulonglong),
                            ("свободно_расш", ctypes.c_ulonglong)]

            с = Память()
            с.длина = ctypes.sizeof(Память)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(с)):
                return int(с.свободно_физ)
        except Exception:  # noqa: BLE001 — измерение не должно мешать разбору
            return None
        return None
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return None


def проверить_память() -> None:
    """Перед pyannote: хватает ли свободной физической памяти. Меньше порога — `NotEnoughMemory`.

    Порог `VOICE_MIN_FREE_MB`, по умолчанию 2500 МБ. Проверка стоит здесь, а не в шаге голосов: тесты и вызовы,
    где `diarize` подменён, не должны зависеть от памяти машины.
    """
    порог_мб = int(os.environ.get("VOICE_MIN_FREE_MB", "2500") or 2500)
    свободно = free_memory_bytes()
    if свободно is not None and свободно < порог_мб * 1024 * 1024:
        raise NotEnoughMemory(
            f"мало свободной памяти для разделения по голосам: {свободно / 1024 ** 3:.1f} ГБ, нужно не меньше "
            f"{порог_мб / 1024:.1f} ГБ. Закройте лишние программы и повторите; расшифровка сохранена, запись не удалена.")


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


class NotEnoughMemory(RuntimeError):
    """Свободной памяти меньше порога: pyannote в дочернем процессе не запускаем."""


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


def предел_голосов(media_seconds) -> float:
    """Разбор по голосам: 4,5 длины записи + 20 мин, но не меньше 30 мин.
    Паритет с Планёркой (transcribe_queue.предел_голосов) и ERP (recording_queue.предел_голосов);
    решение владелицы 26.11 — единое правило вместо фиксированных 4500 с."""
    база = float(media_seconds or 0)
    return max(30 * 60.0, 4.5 * база + 20 * 60.0)


def diarize(wav_path: Path) -> tuple[list[dict], dict]:
    """Куски речи [{"start", "end", "speaker": "Говорящий N"}] и сводка {"speakers", "elapsed_seconds", "device"}.
    Номера голосов — по порядку первого появления в записи."""
    from . import otdelnyy_process

    # pyannote на процессоре просит несколько гигабайт; при нехватке система убивает дочерний процесс, и сборка
    # получает `BrokenProcessPool` вместо причины. Проверяем память заранее (21.11.2026) и сохраняем запись.
    проверить_память()

    # Предел по правилу Планёрки (26.11, паритет): 4,5 длины + 20 мин, не меньше 30 мин.
    # Длительность из wav (soundfile); если звук недоступен — минимум 30 мин (предел_голосов(0)).
    try:
        import soundfile as sf
        длина = float(sf.info(str(wav_path)).duration)
    except Exception:  # noqa: BLE001 — нет звука под рукой: предел по минимуму
        длина = 0
    предел_диар = int(os.environ.get("VOICE_DIARIZE_TIMEOUT") or 0) or int(предел_голосов(длина))
    # Предел (11.11.2026): без него зависший дочерний процесс держал разбор часами — в Планёрке так вышло
    # 87 минут без движения CPU. По пределу — понятная ошибка, встреча идёт дальше без подписей.
    return otdelnyy_process.выполнить(_diarize_here, Path(wav_path),
                                      предел=предел_диар)


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


def _первый_голос(times: tuple[float, float], segments: list[dict]) -> str | None:
    """Самый ранний голос строки не короче MIN_SEGMENT_SEC — запасное правило длинной строки (как Планёрка).

    Строка дольше 30 секунд часто начинается с короткой реплики, а длиннее в ней говорит другой: правило
    «наибольшего пересечения» подписало бы её вторым. Берём того, кто заговорил первым и держался не меньше
    5 секунд; короткие «Доброе утро» без отпечатка пропускаются."""
    начало, конец = float(times[0]), float(times[1])
    подходящие = [seg for seg in segments
                  if float(seg["end"]) - float(seg["start"]) >= MIN_SEGMENT_SEC
                  and min(конец, float(seg["end"])) > max(начало, float(seg["start"]))]
    if not подходящие:
        return None
    return min(подходящие, key=lambda seg: max(начало, float(seg["start"])))["speaker"]


def split_long_lines(lines: list[str], times: list[tuple[float, float]], segments: list[dict],
                     *, long_sec: float = LONG_LINE_SEC) -> tuple[list[str], list[tuple[float, float]]]:
    """Длинную строку распознавания — на предложения по голосам (перенос из Планёрки, 18.11.2026).

    Строка дольше 30 секунд почти всегда содержит несколько говорящих. Делим её по знакам конца предложения,
    каждому предложению отводим долю времени по длине текста; голос потом берёт `label_lines` по пересечению с
    этой долей. Пословных времён у распознавания нет, границы приблизительные — но внутри строки больше не
    остаётся чужих реплик под одним именем. Возвращает строки и времена; порядок и число строк совпадают."""
    spans = sorted(segments, key=lambda s: float(s["start"]))
    out_lines, out_times = [], []
    for line, (начало, конец) in zip(lines, times):
        начало, конец = float(начало), float(конец)
        if конец - начало <= long_sec or not (line or "").strip():
            out_lines.append(line)
            out_times.append((начало, конец))
            continue
        предложения = [x.strip() for x in re.split(r"(?<=[.!?])\s+", line) if x.strip()]
        if len(предложения) < 2:
            out_lines.append(line)                             # одно предложение — запасное правило в assign
            out_times.append((начало, конец))
            continue
        всего = sum(len(x) for x in предложения) or 1
        смещение = начало
        for предложение in предложения:
            доля = (конец - начало) * len(предложение) / всего
            кусок_конец = min(конец, смещение + доля)
            out_lines.append(предложение)
            out_times.append((смещение, кусок_конец))
            смещение = кусок_конец
    return out_lines, out_times


def assign(times: list[tuple[float, float]], segments: list[dict]) -> list[str | None]:
    """Голос для каждой реплики: с наибольшим пересечением по времени; без пересечения — ближайший не дальше
    NEAREST_SEC; иначе None. Для строки дольше LONG_LINE_SEC — самый ранний голос не короче MIN_SEGMENT_SEC
    (правило Планёрки 12.11.2026: длинную строку начинал один, а говорил дольше другой)."""
    out: list[str | None] = []
    for start, end in times:
        if float(end) - float(start) > LONG_LINE_SEC:
            первый = _первый_голос((start, end), segments)
            if первый:
                out.append(первый)
                continue
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
