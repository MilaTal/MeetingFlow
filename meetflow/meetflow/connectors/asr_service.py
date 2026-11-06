# -*- coding: utf-8 -*-
"""Вызов сервиса распознавания во внутренней сети — с временами реплик.

Зачем свой вызов, а не общий `model_routes._asr_service`: общий модуль — байтовая копия ERP и Планёрки, и менять
его в MeetFlow нельзя (тест `test_shared_modules_are_byte_copies`). Общий вызов оставляет только готовые строки
«ЧЧ:ММ:СС<TAB>текст»; для разделения по голосам нужны ещё начало и конец каждой реплики, поэтому ответ сервиса
разбирается здесь и в сводку кладутся `segment_lines` / `segment_times`.

Протокол тот же, что у общего вызова: `form=multipart` — multipart с полем `file`, иначе — wav телом и параметры
в строке запроса. Разделение по голосам у сервиса не просим (`diarization=false`): его делает наш код.

С 27.10.2026 — как общий вызов ERP и Планёрки от 26.10.2026 («Транс» рвал соединение на wav с подсказкой):
подсказка (`initial_prompt`, `hotwords`) в строку запроса не идёт — у формы raw с подсказкой запрос уходит multipart,
запись полем `file`, параметры и подсказка полями формы под прежними именами (прежний путь — `prompt_in=query`);
`audio` у точки — формат звука: `wav` (по умолчанию), `m4a` или `ogg` — сжатие общим `_звук_для_сервиса`, временная
папка удаляется сразу. Что ушло сервису — в сводке: `audio_sent`, `audio_bytes`, `prompt_sent`.

С 06.11.2026 — предел времени по часам и отмена (по записи с тендерами из приёмника). Было: предел был только у
сокета (`timeout_sec`, 4 ч), и сервис, который держит соединение и молчит, держал проход сколько угодно — запись
54,6 МБ простояла 4102 с, признак «завис», а убрать её можно было только перезапуском сервера (он начинал
распознавание с нуля). Стало: вызов идёт в отдельном потоке, предел считается по часам (по умолчанию — минута на
мегабайт, но не меньше получаса), а человек может остановить проход с панели «Мониторинг»: наблюдатель закрывает
ответ, поток вызова заканчивается, файл остаётся в папке и берётся следующим проходом.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .shared import model_routes as _mr

# Предел вызова: `deadline_sec` у точки → переменная MEETFLOW_ASR_DEADLINE_SEC → по размеру записи.
ПРЕДЕЛ_МИН_СЕК = 1800          # меньше получаса не ставим: короткая запись на занятой машине идёт долго
ПРЕДЕЛ_СЕК_НА_МБ = 60          # минута на мегабайт отправленного звука — по замеру 06.11: 54,6 МБ ≈ 17 мин


class Отменено(Exception):
    """Вызов остановлен: истёк предел времени или человек нажал «Остановить проход»."""


class Вызов:
    """Один вызов сервиса: что распознаётся, сколько ждать и как прервать."""

    def __init__(self, файл: str, предел_сек: float | None):
        self.файл = файл
        self.предел_сек = предел_сек
        self.начато = time.monotonic()
        self.причина = ""
        self.ответ = None
        self.отменён = threading.Event()

    def привязать(self, ответ) -> None:
        """Запомнить открытый ответ — чтобы отмена могла его закрыть."""
        self.ответ = ответ

    def прервать(self, причина: str) -> None:
        """Закрыть ответ и сокет: заблокированное чтение в потоке вызова падает, поток заканчивается."""
        if self.отменён.is_set():
            return
        self.причина = причина
        self.отменён.set()
        ответ = self.ответ
        if ответ is not None:
            try:
                ответ.close()
            except Exception:  # noqa: BLE001 — закрытие уже закрытого ответа не ошибка
                pass
            try:
                ответ.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except Exception:  # noqa: BLE001 — у не-сокетного ответа этого поля нет
                pass

    def сообщение(self) -> str:
        секунд = int(time.monotonic() - self.начато)
        return f"«{self.файл}» остановлено на {секунд} с: {self.причина or 'без причины'}"


_текущие: dict[int, Вызов] = {}
_замок = threading.Lock()
_счётчик = 0


def начать(файл: str, предел_сек: float | None) -> Вызов:
    global _счётчик
    вызов = Вызов(файл, предел_сек)
    with _замок:
        _счётчик += 1
        _текущие[_счётчик] = вызов
    return вызов


def закончить(вызов: Вызов) -> None:
    with _замок:
        for номер, чужой in list(_текущие.items()):
            if чужой is вызов:
                _текущие.pop(номер, None)


def текущие() -> list[dict]:
    """Что сейчас распознаётся — для панели «Мониторинг» и маршрута отмены."""
    with _замок:
        список = list(_текущие.values())
    return [{"файл": в.файл, "секунд": int(time.monotonic() - в.начато), "предел_сек": в.предел_сек}
            for в in список]


def отменить_все(кем: str = "человек") -> int:
    """Остановить все идущие вызовы. Возвращает, сколько было."""
    with _замок:
        список = list(_текущие.values())
    for вызов in список:
        вызов.прервать(f"остановлено: {кем}")
    return len(список)


def предел_вызова(route, байт: int) -> float:
    """Сколько ждать этот вызов: настройка точки, затем переменная, затем минута на мегабайт."""
    своё = route.opt("deadline_sec")
    if своё:
        return float(своё)
    среда = (os.environ.get("MEETFLOW_ASR_DEADLINE_SEC") or "").strip()
    if среда.replace(".", "", 1).isdigit() and float(среда) > 0:
        return float(среда)
    return max(ПРЕДЕЛ_МИН_СЕК, ПРЕДЕЛ_СЕК_НА_МБ * (байт / 2 ** 20))


def _в_потоке(вызов: Вызов, работа):
    """Выполнить вызов отдельным потоком и ждать не дольше предела. Предел или остановка человеком — вызывающий
    получает `Отменено` сразу, не дожидаясь ответа сервиса: проход папки не стоит. Сам поток вызова остаётся
    ждать ответа в стороне и заканчивается сам — его сокет ограничен двумя пределами (см. `_прочитать`), а не
    четырьмя часами, как раньше."""
    итог: dict = {}

    def поток() -> None:
        try:
            итог["значение"] = работа()
        except BaseException as e:  # noqa: BLE001 — ошибку отдаём в вызывающий поток как есть
            итог["ошибка"] = e

    т = threading.Thread(target=поток, name="meetflow-asr", daemon=True)
    т.start()
    срок = time.monotonic() + вызов.предел_сек if вызов.предел_сек else None
    while т.is_alive():
        if вызов.отменён.wait(0.1):
            break
        if срок is not None and time.monotonic() >= срок:
            вызов.прервать(f"сервис не ответил за {int(вызов.предел_сек)} с")
            break
    if вызов.отменён.is_set():
        raise Отменено(вызов.сообщение())
    if "ошибка" in итог:
        raise итог["ошибка"]
    return итог["значение"]


def call(route, wav_path, *, language: str = "ru", initial_prompt: str = "",
         hotwords: str | None = None) -> tuple[str, dict]:
    """Текст «ЧЧ:ММ:СС<TAB>реплика» и сводка с временами реплик."""
    if not _mr._internal_url(route.url):
        raise _mr.RoutesError("сервис распознавания — только во внутренней сети")
    audio_format = str(route.opt("audio") or "wav").strip().lower()
    data, filename, audio_type, sent = _mr._звук_для_сервиса(wav_path, audio_format)
    prompt = " ".join(x for x in (initial_prompt or "", hotwords or "") if x)
    prompt_in_query = str(route.opt("prompt_in") or "form").strip().lower() == "query"
    sending = {"audio_sent": sent, "audio_bytes": len(data)}
    started = time.monotonic()
    вызов = начать(filename, предел_вызова(route, len(data)))
    try:
        return _в_потоке(вызов, lambda: _отправить(route, data, filename, audio_type, language, initial_prompt,
                                                  hotwords, prompt, prompt_in_query, sending, started, вызов))
    finally:
        закончить(вызов)


def _отправить(route, data: bytes, filename: str, audio_type: str, language: str, initial_prompt: str,
               hotwords: str | None, prompt: str, prompt_in_query: bool, sending: dict, started: float,
               вызов: Вызов) -> tuple[str, dict]:
    """Собственно отправка: тело запроса и разбор ответа (прежний код `call`)."""

    def collect(raw: dict) -> tuple[str, dict]:
        segments = raw.get("segments") if isinstance(raw.get("segments"), list) else []
        rows, texts, times = [], [], []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            phrase = str(segment.get("text") or "").strip()
            if not phrase:
                continue
            try:
                start = float(segment.get("start") or 0)
                end = float(segment.get("end") or start)
            except (TypeError, ValueError):
                continue
            stamp = int(start)
            rows.append(f"{stamp // 3600:02d}:{stamp % 3600 // 60:02d}:{stamp % 60:02d}\t{phrase}")
            texts.append(phrase)
            times.append([round(start, 2), round(end, 2)])
        text = "\n".join(rows) if rows else str(raw.get("text") or "")
        duration = raw.get("duration") or raw.get("media_seconds") \
            or (raw.get("meta") or {}).get("media_seconds")
        meta = dict(raw.get("meta") or {})
        meta.setdefault("model", route.name)
        meta.setdefault("device", "сервис в сети")
        meta.update({
            "engine": route.url,
            "language": raw.get("language") or meta.get("language"),
            "duration": duration,
            "media_seconds": round(float(duration)) if duration else None,
            "lines": len(rows) or len([x for x in text.splitlines() if x.strip()]),
            "elapsed_seconds": round(time.monotonic() - started),
            "speakers": raw.get("speaker_count") or meta.get("speakers"),
            "segments": len(segments),
            "segment_lines": texts,
            "segment_times": times,
        })
        meta.update(sending)
        return text, {k: v for k, v in meta.items() if v not in (None, [], "")}

    def send_form(fields: list[tuple[str, str]]) -> dict:
        boundary = "----meetflow-asr-" + uuid.uuid4().hex
        file_field = str(route.opt("file_field") or "file")
        parts: list[bytes] = []
        for name, value in fields:
            if value == "":
                continue
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
                         .encode("utf-8"))
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                     f"filename=\"{filename}\"\r\nContent-Type: {audio_type}\r\n\r\n".encode("utf-8"))
        parts.append(data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(route.url, data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                              "Content-Length": str(len(body))})
        return _прочитать(req, route, вызов)

    form = str(route.opt("form") or "").strip().lower()
    if form != "multipart":
        query = {k: v for k, v in {"language": language, "initial_prompt": initial_prompt,
                                   "hotwords": hotwords or ""}.items()
                 if isinstance(v, (str, int, float)) and v != ""}
        has_prompt = bool(query.get("initial_prompt") or query.get("hotwords"))
        if has_prompt and not prompt_in_query:
            # подсказка в строке запроса — несколько килобайт после urlencode: полями формы под прежними именами
            sending["prompt_sent"] = "поле формы"
            return collect(send_form([(str(k), str(v)) for k, v in query.items()]))
        if has_prompt:
            sending["prompt_sent"] = "строка запроса"
        url = route.url + (("&" if "?" in route.url else "?") + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": audio_type}, method="POST")
        raw = _прочитать(req, route, вызов)
        return collect(raw)

    fields = [("language", language), ("prompt", prompt), ("wait", "true"),
              ("diarization", "false"), ("identify_speakers", "false"), ("word_timestamps", "false")]
    fields += [(str(k), str(v)) for k, v in (route.opt("extra_fields") or {}).items()]
    if prompt:
        sending["prompt_sent"] = "поле формы"
    return collect(send_form(fields))


def _прочитать(req, route, вызов: Вызов) -> dict:
    """Открыть соединение и прочитать ответ. Ответ привязывается к вызову: отмена закрывает его из другого потока,
    чтение падает — и вызов заканчивается, а не висит до конца сокетного предела (4 ч). Предел сокета ограничен
    двумя пределами вызова: поток, оставленный после остановки, не живёт часами и не держит очередь распознавания."""
    порог = float(route.opt("timeout_sec", 4 * 3600))
    if вызов.предел_сек:
        порог = min(порог, max(вызов.предел_сек * 2, 600))
    with urllib.request.urlopen(req, timeout=порог) as resp:
        вызов.привязать(resp)
        try:
            return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError):
            if вызов.отменён.is_set():
                raise Отменено(вызов.сообщение()) from None
            raise
        finally:
            вызов.привязать(None)
