# -*- coding: utf-8 -*-
"""Распознавание записи моделью Nemotron-3.5-Transcribe (NVIDIA) — четвёртый род распознавания (24.11.2026).

Зачем отдельный модуль. Сервер модели принимает только `/v1/chat/completions`: маршрута
`/v1/audio/transcriptions` у него нет, аудио идёт base64-строкой в `audio_url`, а заголовок
`Authorization` обязателен, хотя ключ не проверяется — достаточно любой непустой строки («Bearer EMPTY»).
Ни один из прежних родов (`asr-service`, `python`, `faster-whisper`) так не умеет, поэтому заведён свой.

Что проверено на живой записи 23.11.2026 (планёрка 64 мин 37 с):
  * скорость ~13× реального времени: 290 с в четырёх запросах по 20 минут;
  * текст самый связный и полный из четырёх расшифровок (+37 % слов к «Трансу»), термины не теряет;
  * но числа пишет прописью и часть искажает, имена плавают, диаризация грубая — 2–4 кластера на кусок,
    нумерация между кусками не согласована, таймкодов модель не отдаёт.

Поэтому род заведён как **инструмент для опытов**, а не рабочий путь: в цепочку роли `asr` его не назначают
(решение владелицы 24.11.2026). Время строк ниже — оценка по длине текста внутри куска, а не таймкод модели;
в сводке это сказано прямо (`time_source`).

Протокол сервера (проверено 23–24.11.2026):
  * `POST <база>/v1/chat/completions`, заголовок `Authorization: Bearer <непустое>`;
  * аудио — `data:audio/wav;base64,…` внутри `audio_url`, WAV PCM16, желательно 16 кГц mono;
  * `skip_special_tokens=false` — иначе теги `<spk:N>` вырежутся из ответа;
  * жёсткий лимит одного запроса — 3600 с; длиннее режем на куски (по умолчанию 20 минут);
  * `/v1/models` — для «Проверить связь».
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

# Внутренняя сеть: запросы идут мимо системного прокси всегда (как у точки `asr-service`, 27.10.2026) —
# NO_PROXY диапазонами urllib не понимает, и вызов уходил бы через прокси компании.
ОПЕНЕР = urllib.request.build_opener(urllib.request.ProxyHandler({}))

МОДЕЛЬ = "nemotron-transcribe"
ПОДСКАЗКА = "Transcribe the following audio in Russian. Label speakers with <spk:0>, <spk:1> tags."
ЛИМИТ_КУСКА = 3600          # жёсткий лимит сервера на один запрос, секунды
КУСОК_ПО_УМОЛЧАНИЮ = 1200   # 20 минут — проверено на живой встрече
ТАЙМАУТ_ПО_УМОЛЧАНИЮ = 1800

_ТЕГ = re.compile(r"<spk:(\d+)>")
_ВЕРСИЯ_В_АДРЕСЕ = re.compile(r"/v\d+$")


def _база(url: str) -> str:
    """База OpenAI-совместимого API: адрес можно вписать и целиком (`…/v1/chat/completions`), и без версии.

    Правило то же, что у `model_routes.api_base`: адрес, который уже кончается номером версии, берётся как есть,
    иначе дописывается `/v1`. Полный адрес ручки принимается, чтобы точку нельзя было завести «почти правильно»
    и получить 404 на каждом куске."""
    база = (url or "").strip().rstrip("/")
    for хвост in ("/chat/completions", "/models"):
        if база.endswith(хвост):
            база = база[: -len(хвост)].rstrip("/")
    return база if _ВЕРСИЯ_В_АДРЕСЕ.search(база) else база + "/v1"


def _ключ(key_env: str) -> str:
    """Ключ для заголовка. Сервер ключ не проверяет, но пустой заголовок не принимает — отсюда «EMPTY».

    Если у точки задана переменная окружения с ключом, берётся она (на случай, если сервер закроют паролем);
    переменная задана, а значения нет — ошибка, а не тихая подмена: иначе точка «работает», пока сервер не закроют."""
    имя = (key_env or "").strip()
    if not имя:
        return "EMPTY"
    значение = os.environ.get(имя, "").strip()
    if not значение:
        raise RuntimeError(f"переменная окружения «{имя}» не задана — впишите ключ или очистите поле у точки")
    return значение


def _целое(значение, по_умолчанию: int, низ: int, верх: int) -> int:
    try:
        число = int(str(значение).strip())
    except (TypeError, ValueError):
        return по_умолчанию
    return min(max(число, низ), верх)


def _подготовить(wav_path: Path) -> tuple[Path, bool]:
    """WAV 16 кГц mono PCM16 — формат, который ждёт сервер. Другой приводим ffmpeg во временный файл."""
    with wave.open(str(wav_path), "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000):
            return wav_path, False
    import imageio_ffmpeg

    fd, имя = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", имя]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        try:
            os.unlink(имя)
        except OSError:
            pass
        raise RuntimeError(f"не удалось привести звук к 16 кГц mono PCM16: {done.stderr[-300:]}")
    return Path(имя), True


def _куски(wav_path: Path, chunk_seconds: int):
    """(начало, секунд, wav-байты) — куски не длиннее `chunk_seconds`, без перекрытия.

    Перекрытие не делаем: на живой встрече стыки кусков по 20 минут не дали ни дублей, ни потерь."""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        параметры = w.getparams()
        всего = w.getnframes()
        за_кусок = max(1, int(chunk_seconds) * sr)
        начало = 0
        while начало < всего:
            w.setpos(начало)
            данные = w.readframes(min(за_кусок, всего - начало))
            if not данные:
                break
            буфер = io.BytesIO()
            with wave.open(буфер, "wb") as out:
                out.setnchannels(параметры.nchannels)
                out.setsampwidth(параметры.sampwidth)
                out.setframerate(sr)
                out.writeframes(данные)
            секунд = len(данные) / (sr * параметры.sampwidth * параметры.nchannels)
            yield начало / sr, секунд, буфер.getvalue()
            начало += за_кусок


def _запрос(база: str, model: str, ключ: str, wav_bytes: bytes, timeout: float, подсказка: str = "") -> dict:
    """Один кусок — один запрос к `/v1/chat/completions`. Возвращает разобранный JSON ответа."""
    текст = ПОДСКАЗКА
    if подсказка:
        текст += ("\nПодсказка по именам и терминам (не добавляй того, чего не слышно): "
                  + " ".join(str(подсказка).split())[:600])
    тело = {
        "model": model,
        "temperature": 0,
        "max_tokens": 32768,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": текст},
            {"type": "audio_url", "audio_url": {
                "url": "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode("ascii")}},
        ]}],
        "chat_template_kwargs": {"enable_thinking": False},
        "skip_special_tokens": False,
        "mm_processor_kwargs": {"capture_ctc_timestamps": True},
    }
    req = urllib.request.Request(
        база + "/chat/completions", data=json.dumps(тело).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Bearer {ключ}"})
    try:
        with ОПЕНЕР.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            ответ = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 — тело нужно только для подсказки
            ответ = ""
        if exc.code == 400 and ("audio" in ответ.lower() or "duration" in ответ.lower()):
            raise RuntimeError(f"сервер отклонил кусок (HTTP 400): {ответ} — уменьшите «Длину куска» "
                               f"(лимит сервера {ЛИМИТ_КУСКА} с)") from None
        raise RuntimeError(f"сервер Nemotron ответил HTTP {exc.code}: {ответ}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"сервер Nemotron не отвечает ({база}): {exc.reason}") from None


def _содержание(ответ: dict) -> str:
    """Текст ответа: обычная строка `content` (или список частей, как у некоторых OpenAI-совместимых серверов)."""
    try:
        выбор = (ответ.get("choices") or [])[0]
        сообщение = выбор.get("message") or {}
        content = сообщение.get("content")
        if isinstance(content, list):
            content = " ".join(str(ч.get("text") or "") for ч in content if isinstance(ч, dict))
        текст = str(content or "").strip()
        if not текст:
            причина = выбор.get("finish_reason") or ответ.get("error") or "пустой ответ"
            raise RuntimeError(f"сервер вернул пустой текст ({причина})")
        return текст
    except (IndexError, AttributeError, TypeError) as exc:
        raise RuntimeError(f"ответ сервера не разобран: {str(ответ)[:300]}") from exc


def _ходы(текст: str) -> list[tuple[int, str]]:
    """Разбить ответ на ходы по тегам `<spk:N>`; теги в текст протокола не идут (говорящих подписывает наш разбор)."""
    части = _ТЕГ.split(текст)
    if len(части) == 1:
        чисто = " ".join(текст.split())
        return [(0, чисто)] if чисто else []
    ходы: list[tuple[int, str]] = []
    первый = " ".join(части[0].split())
    if первый:
        ходы.append((0, первый))
    for i in range(1, len(части), 2):
        try:
            метка = int(части[i])
        except (TypeError, ValueError):
            метка = 0
        тело = " ".join(части[i + 1].split()) if i + 1 < len(части) else ""
        if тело:
            ходы.append((метка, тело))
    return ходы


def _строки(ходы: list[tuple[int, str]], начало: float, длительность: float):
    """Строки «ЧЧ:ММ:СС<TAB>текст» и их времена. Время — оценка по длине текста внутри куска.

    Модель таймкодов не отдаёт (`capture_ctc_timestamps` в текст не попадают), а продукты сопоставляют строки
    с кусками речи по времени. Оценка честно помечена в сводке (`time_source`): для опытов годится, для цитат
    с точностью до секунды — нет."""
    всего = sum(len(т) for _, т in ходы) or 1
    прошло = 0
    строки, времена = [], []
    for _, текст in ходы:
        старт = начало + длительность * прошло / всего
        прошло += len(текст)
        конец = начало + длительность * прошло / всего
        секунды = int(старт)
        строки.append(f"{секунды // 3600:02d}:{секунды % 3600 // 60:02d}:{секунды % 60:02d}\t{текст}")
        времена.append([round(старт, 1), round(конец, 1)])
    return строки, времена


def сделать(*, url: str, model: str = МОДЕЛЬ, key_env: str = "",
            chunk_seconds=КУСОК_ПО_УМОЛЧАНИЮ, timeout_sec=ТАЙМАУТ_ПО_УМОЛЧАНИЮ):
    """Функция распознавания для точки рода `nemotron`: (путь к wav, **параметры) → (текст, сводка).

    Формат тот же, что у остальных точек распознавания: строки «ЧЧ:ММ:СС<TAB>текст», сводка с `model`,
    `device`, `media_seconds`, `lines`, `elapsed_seconds` — иначе прикладывание расшифровки падает на
    обязательных полях (живой случай 12.10.26)."""
    база = _база(url)
    кусок = _целое(chunk_seconds, КУСОК_ПО_УМОЛЧАНИЮ, 1, ЛИМИТ_КУСКА)
    таймаут = _целое(timeout_sec, ТАЙМАУТ_ПО_УМОЛЧАНИЮ, 30, 6 * 3600)

    def run(wav_path, **params):
        ключ = _ключ(key_env)
        подсказка = " ".join(ч for ч in (str(params.get("initial_prompt") or ""),
                                        str(params.get("hotwords") or "")) if ч)
        начало_работы = time.monotonic()
        путь, временный = _подготовить(Path(wav_path))
        try:
            всего_секунд = 0
            строки: list[str] = []
            времена: list[list[float]] = []
            запросов = 0
            спикеров = 0
            for старт, длительность, данные in _куски(путь, кусок):
                всего_секунд += длительность
                запросов += 1
                ответ = _запрос(база, model, ключ, данные, таймаут, подсказка)
                ходы = _ходы(_содержание(ответ))
                if ходы:
                    спикеров = max(спикеров, max(м for м, _ in ходы) + 1)
                линии, метки = _строки(ходы, старт, длительность)
                строки += линии
                времена += метки
            if not строки:
                raise RuntimeError("ни один кусок не дал текста — проверьте запись и сервер")
            сводка = {
                "model": model,
                "device": "сервер в сети",
                "engine": база,
                "media_seconds": round(всего_секунд),
                "lines": len(строки),
                "elapsed_seconds": round(time.monotonic() - начало_работы),
                "chunks": запросов,
                "chunk_seconds": кусок,
                "speakers": спикеров or None,
                "time_source": "оценка по длине текста (модель не отдаёт таймкоды)",
                "hint_chars": len(подсказка) or None,
                "segment_lines": строки,
                "segment_times": времена,
            }
            return "\n".join(строки), {k: v for k, v in сводка.items() if v not in (None, [], "")}
        finally:
            if временный:
                try:
                    путь.unlink()
                except OSError:
                    pass

    return run


def проверить(*, url: str, model: str = МОДЕЛЬ, key_env: str = "", timeout: float = 60) -> tuple[bool, str]:
    """«Проверить связь»: `GET /v1/models` — сервер жив и модель в списке. Без звука, чтобы не тратить минуты."""
    try:
        база = _база(url)
        ключ = _ключ(key_env)
        req = urllib.request.Request(база + "/models", headers={
            "Accept": "application/json", "Authorization": f"Bearer {ключ}"})
        with ОПЕНЕР.open(req, timeout=timeout) as resp:
            данные = json.loads(resp.read().decode("utf-8"))
        модели = [str(м.get("id") or "") for м in (данные.get("data") or []) if isinstance(м, dict)]
        if model and not any(model in м for м in модели):
            return False, (f"сервер отвечает, но модели «{model}» в списке нет; есть: "
                           + (", ".join(модели[:8]) or "ни одной"))
        return True, f"сервер отвечает, модель на месте ({model}); всего моделей: {len(модели)}"
    except urllib.error.HTTPError as exc:
        return False, f"сервер ответил HTTP {exc.code} — проверьте адрес и заголовок Authorization"
    except urllib.error.URLError as exc:
        return False, f"сервер не отвечает: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 — проверка связи не должна ронять панель
        return False, f"{type(exc).__name__}: {str(exc)[:300]}"
