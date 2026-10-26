# -*- coding: utf-8 -*-
"""Шаг голосов после распознавания: разделение по голосам, ФИО по общей базе, вклад в базу.

Порядок и правила взяты из ERP (`recording_queue._with_speakers/_voice_names/_contribute_voices`), задание
владелицы 26.10.2026:

1. разделение записи по голосам локальными моделями → «Говорящий N» в строках расшифровки;
2. опознание по общей базе правилом 0,65 / 0,10 (`voice_rule`) → ФИО вместо метки, но только человеку из
   подтверждённой «Команды»;
3. отпечатки кусков речи и отрывки для «Разбора голосов» — в общую базу, как это делает ERP;
4. сбой любого шага не отменяет распознанный текст: возвращается текст без подписей и причина.

Модуль ничего не знает о базе данных приложения: встреча, дата, путь к базе и список «Команды» передаются
вызывающим.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import diarize, otdelnyy_process, voice_contrib, voice_review, voice_rule

DEFAULT_LABEL = "Говорящий"


class VoiceStepError(RuntimeError):
    """Шаг голосов не выполнен; текст расшифровки при этом сохраняется."""


def _norm(name: str) -> str:
    """Ключ сравнения ФИО: регистр, лишние пробелы, ё → е (правило владелицы 22.10.2026)."""
    return " ".join((name or "").replace("ё", "е").replace("Ё", "Е").lower().split())


def in_team_factory(team: list[str] | None):
    """Функция «ФИО базы → ФИО „Команды“»: точное совпадение или единственный ключ сравнения."""
    names = [n for n in (team or []) if (n or "").strip()]
    exact = {n: n for n in names}
    by_key: dict[str, list[str]] = {}
    for n in names:
        by_key.setdefault(_norm(n), []).append(n)

    def find(name: str) -> str | None:
        if not name:
            return None
        if name in exact:
            return exact[name]
        found = by_key.get(_norm(name)) or []
        return found[0] if len(found) == 1 else None

    return find


def _pairs(meta: dict) -> tuple[list[str], list[tuple[float, float]]]:
    """Строки реплик и их времена из сводки распознавания; пусто — разбирать нечего."""
    lines = [str(x) for x in (meta.get("segment_lines") or []) if str(x).strip()]
    times = []
    for pair in meta.get("segment_times") or []:
        try:
            times.append((float(pair[0]), float(pair[1])))
        except (TypeError, ValueError, IndexError):
            return lines, []
    if len(lines) != len(times):
        return lines, []
    return lines, times


def _stamp(sec: float) -> str:
    s = int(sec or 0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _display(line: str) -> str:
    """Строка после `label_lines`: «метка<TAB>имя<TAB>текст» → «[метка] имя: текст» (формат MeetFlow)."""
    parts = line.split("\t")
    if len(parts) == 3:
        return f"[{parts[0]}] {parts[1]}: {parts[2]}"
    if len(parts) == 2:
        return f"[{parts[0]}] {parts[1]}"
    return line


def _prepare_wav(src: Path) -> Path:
    """Звук для pyannote и отпечатков: 16 кГц моно. m4a/mp3 soundfile не читает — извлекаем ffmpeg.

    Исходную запись не трогаем: временный wav лежит в своей папке и удаляется после шага. Если файл уже
    читается soundfile, возвращаем его же.
    """
    try:
        import soundfile as sf
        sf.info(str(src))
        return src
    except Exception:  # noqa: BLE001 — не читается: конвертируем
        pass
    try:
        import imageio_ffmpeg
    except Exception as exc:  # noqa: BLE001
        raise VoiceStepError(f"звук записи не читается, а ffmpeg для извлечения не установлен: {exc}") from exc
    folder = Path(tempfile.mkdtemp(prefix="meetflow_voice_"))
    out = folder / "voice.wav"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-vn", str(out)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0 or not out.is_file():
        shutil.rmtree(folder, ignore_errors=True)
        raise VoiceStepError(f"не удалось вынуть звук из записи: {(done.stderr or '')[-300:]}")
    return out


def process(wav_path: str | Path, text: str, meta: dict, *, meeting_id: int, meeting_date: str,
            base_path: str | Path | None = None, team: list[str] | None = None,
            uploads_root: str | Path | None = None, settings: dict | None = None) -> dict:
    """Выполнить шаг голосов. Возвращает сводку; при любой невозможности — `VoiceStepError` с причиной."""
    if not diarize.enabled():
        raise VoiceStepError("разделение по голосам выключено (MEETFLOW_DIARIZE=off)")
    ready, why = diarize.available()
    if not ready:
        raise VoiceStepError(f"разделение по голосам недоступно: {why}")
    lines, times = _pairs(meta)
    if not lines or not times:
        raise VoiceStepError("в сводке распознавания нет времён реплик — делить нечего")
    wav_path = Path(wav_path)
    if not wav_path.is_file():
        raise VoiceStepError("записи уже нет на диске — разделить нечем")

    base = base_path or os.environ.get("VOICE_BASE_PATH")
    settings = settings or voice_rule.nastroyki()
    work_wav = _prepare_wav(wav_path)
    try:
        segments, info = diarize.diarize(work_wav)          # отдельный процесс внутри
        if not segments:
            raise VoiceStepError("разделение не нашло кусков речи")

        # Отпечатки окон считаем один раз: по ним и опознаём, и пополняем базу (ERP делает так же).
        embedded = otdelnyy_process.выполнить(voice_contrib.embed_segments, work_wav, segments)
        names: dict[str, str] = {}
        identified: dict = {}
        base_info: dict = {}
        notes: list[str] = []
        if base:
            try:
                centry, base_info = voice_rule.etalony(base)
                identified = voice_rule.opoznat(embedded, centry, in_team=in_team_factory(team), settings=settings)
                names = {label: v["name"] for label, v in identified.items()
                         if v.get("status") == voice_rule.CONFIRMED and v.get("name")}
                voice_rule.zapisat(uploads_root or Path("data/uploads"), int(meeting_id), identified,
                                   settings, base_info)
            except (voice_rule.BazaNeTa, voice_rule.NastroykaNeTa) as exc:
                # Не та база или настройка — это не повод терять текст: строки останутся «Говорящий N».
                notes.append(f"имена по голосу не подставлены: {exc}")
        # Метка времени — из времён реплик: `segment_lines` её не содержит, а в расшифровке она нужна и до, и после подписи.
        stamped = [f"{_stamp(a)}\t{phrase}" for phrase, (a, _b) in zip(lines, times)]
        labelled, signed = diarize.label_lines(stamped, times, segments, names=names)
        labelled = [_display(x) for x in labelled]

        contribution = {}
        clips = 0
        if base and voice_contrib.enabled():
            try:
                contribution = voice_contrib.contribute(
                    work_wav, segments, origin_ref=str(meeting_date), embedded=embedded,
                    meeting_key=str(meeting_id), base=base)
                # Отрывки и текст реплик — пока запись ещё на диске (после распознавания она удаляется).
                clips = voice_review.vyrezat_otryvki(base, work_wav, voice_contrib._own_project(),
                                                    str(meeting_date), str(meeting_id))
                repliki = [(a, b, line) for line, (a, b) in zip(lines, times)]
                voice_review.zapisat_repliki(base, voice_contrib._own_project(), str(meeting_date),
                                             str(meeting_id), repliki)
            except Exception as exc:  # noqa: BLE001 — вклад не отменяет ни текст, ни подписи
                notes.append(f"отпечатки в общую базу не записаны: {type(exc).__name__}: {str(exc)[:200]}")
                clips = 0

        return {
            "text": "\n".join(labelled),
            "speakers": int(info.get("speakers") or 0),
            "signed_lines": int(signed or 0),
            "names": names,
            "identified": identified,
            "base": base_info,
            "contribution": contribution,
            "clips": int(clips or 0),
            "notes": notes,
            "diarization": {"seconds": info.get("elapsed_seconds"), "device": info.get("device"),
                            "path": info.get("path")},
        }
    finally:
        if work_wav != wav_path:
            shutil.rmtree(work_wav.parent, ignore_errors=True)
