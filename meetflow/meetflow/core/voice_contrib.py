# -*- coding: utf-8 -*-
"""Вклад ERP в общую базу голосов: ERP не только читает её, но и записывает отпечатки.

Решение владельца 05.10.26. До этого общая база пополнялась только из Планёрки, а в журнале решений
ERP запись из ERP значилась отложенной («Не входит и остаётся частью плана переноса: использование
отпечатков голосов в ERP, запись в базу из ERP»). Теперь ERP обрабатывает свои записи встреч
(Milestone 1–2) и кладёт отпечатки в ту же базу: голос, прозвучавший на встрече, должен опознаваться
в обоих продуктах, а не только там, где запись обработали.

Контракт записи — тот же, что у Планёрки, иначе база станет неоднородной и мера перестанет работать:

- отпечаток считается только для кусков речи не короче 5 секунд (замер 30.09.26: на трёх секундах
  облака своих и чужих соприкасаются, зазор −0,033);
- вектор хранится как float32 little-endian, сравнивается косинусом, порог совпадения 0,5;
- в строку пишется модель отпечатка (`embedding_model`): при смене модели старое и новое смешалось
  бы молча, и выглядело бы это как «люди перестали узнаваться»;
- ERP НЕ привязывает отпечаток к человеку (решения владельца 16.10.26 и 17.10.26). У ERP нет выгрузки
  ВКС, поэтому заявленного имени у его кусков нет (`claimed_name` пустое), а совпадение с подтверждённым
  человеком базы пишется ПОДСКАЗКОЙ: `hint_name` и `hint_score`. `person_id` ставит только оператор
  (или сбор базы на слух). Людей ERP не создаёт и не подтверждает. До 16.10.26 ERP ставил `person_id`
  сам по одиночному совпадению 0,5, и привязанные им же отпечатки становились опорными: запись 08.10,
  положенная в базу 24 раза, дала одному человеку 994 отпечатка при двух эталонах Планёрки.
  `claimed_name` пустое намеренно: подтверждение человека в Планёрке привязывает куски по заявленному
  имени, и подсказка в этом поле молча стала бы привязкой;
- опорные для сравнения — только отпечатки, привязанные НЕ кодом ERP (`_reference_vectors`);
- повторный вклад той же записи отсекается: ключ — проект, запись (`origin_ref`), время начала куска
  (`start_sec`), модель отпечатка. У строк до 16.10.26 времени нет — для них повтор узнаётся по той же
  длительности и тому же вектору (копии 08.10 совпадали с близостью 1,000).

Общая база — один файл на два продукта, и писать в него могут оба ОДНОВРЕМЕННО. Это учтено: журнал
WAL (читающий не ждёт пишущего), `busy_timeout` на ожидание чужой блокировки и повтор при
«database is locked». Проверено тестом на одновременную запись из двух потоков.

Сбой вклада не ломает распознавание: запись идёт после того, как текст уже сохранён, и любая ошибка
уходит системным сообщением, а не отменяет результат.
"""
from __future__ import annotations

import math
import os
import sqlite3
import struct
import time
from pathlib import Path

from . import local_models, voice_review

# Пороги и имена — часть общего контракта с Планёркой: менять их можно только вместе с ней.
MIN_SEGMENT_SEC = 5.0
SAME_VOICE_SIMILARITY = 0.5
EMBEDDING_MODEL_NAME = "pyannote/wespeaker-voxceleb-resnet34-LM"
# Сколько ждать чужую блокировку базы: её же значение использует Планёрка (`VOICE_BASE_LOCK_WAIT`).
LOCK_WAIT_SECONDS = float(os.environ.get("VOICE_BASE_LOCK_WAIT", "15"))
# Повторы на «database is locked»: ожидание внутри SQLite не всегда спасает, когда пишут оба продукта.
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 2.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_person (
    id INTEGER NOT NULL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    aliases TEXT NOT NULL,
    confirmed BOOLEAN NOT NULL,
    confirmed_by VARCHAR(200) NOT NULL,
    confirmed_at DATETIME,
    created_at DATETIME NOT NULL,
    note TEXT NOT NULL,
    UNIQUE (full_name)
);
CREATE TABLE IF NOT EXISTS voice_sample (
    id INTEGER NOT NULL PRIMARY KEY,
    person_id INTEGER REFERENCES voice_person (id),
    claimed_name VARCHAR(200) NOT NULL,
    speaker_label VARCHAR(50) NOT NULL,
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,
    seconds FLOAT NOT NULL,
    origin_project VARCHAR(50) NOT NULL,
    origin_ref VARCHAR(100) NOT NULL,
    embedding_model VARCHAR(120) DEFAULT '',
    created_at DATETIME NOT NULL,
    start_sec FLOAT,
    hint_name VARCHAR(200) DEFAULT '',
    hint_score FLOAT
);
CREATE INDEX IF NOT EXISTS ix_voice_sample_person_id ON voice_sample (person_id);
CREATE INDEX IF NOT EXISTS ix_voice_sample_claimed_name ON voice_sample (claimed_name);
"""

# Ограничения в DDL выше повторяют базу, созданную Планёркой (её модели объявляют эти поля
# обязательными), — сверено по PRAGMA table_info живой базы 05.10.26. Это не педантизм: ERP заводит
# базу сам, если файла ещё нет, и база, заведённая с более слабыми ограничениями, стала бы «чужой
# схемой» для второго продукта — расхождение выяснилось бы позже и на данных, а не сразу.
# Тест `test_схема_совпадает_с_базой_планёрки` держит это соответствие.


def enabled() -> bool:
    """Вклад включён по умолчанию: смысл решения — чтобы база пополнялась с обеих сторон.
    Выключить — MEETFLOW_VOICE_CONTRIB=off (например, на машине, где записей MeetFlow быть не должно)."""
    return os.environ.get("MEETFLOW_VOICE_CONTRIB", "on").strip().lower() in ("on", "1", "true", "yes")


def base_path() -> Path | None:
    """Путь к общей базе — та же переменная `VOICE_BASE_PATH`, что у чтения: база одна на два продукта.

    Отличие от чтения (`voice_directory.base_path`) намеренное: чтение требует, чтобы файл уже был
    («нет файла — читать нечего»), а запись заводит базу сама, если её ещё нет, — так же, как это
    делает Планёрка. Иначе на новой машине запись падала бы с «не задан VOICE_BASE_PATH», хотя
    переменная задана и человек ничего не должен исправлять."""
    raw = (os.environ.get("VOICE_BASE_PATH") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def available(base: str | Path | None = None) -> tuple[bool, str]:
    """Можно ли сейчас писать отпечатки: путь к базе задан и модель отпечатка на диске.
    Пакеты проверяем импортом — они же нужны разделению по голосам, но здесь это отдельный вопрос."""
    missing = []
    if not (base or base_path()):
        missing.append("не задан VOICE_BASE_PATH — путь к общей базе голосов")
    for module, why in (("soundfile", "чтение звука"), ("numpy", "счёт векторов")):
        try:
            __import__(module)
        except Exception:  # noqa: BLE001
            missing.append(f"{module} ({why})")
    folder = local_models.embedding_dir()
    if folder is None or not Path(folder).is_dir():
        missing.append(f"модель отпечатка голоса не найдена: {folder}")
    return (not missing), "; ".join(missing)


def _connect(base: str | Path | None = None) -> sqlite3.Connection:
    """Открыть базу на запись с теми же настройками, что у Планёрки: WAL и ожидание чужой блокировки."""
    path = Path(base).expanduser().resolve() if base else base_path()
    if path is None:
        raise RuntimeError("не задан VOICE_BASE_PATH — путь к общей базе голосов")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=LOCK_WAIT_SECONDS)
    con.execute("PRAGMA journal_mode=WAL")      # читающий не ждёт пишущего и видит последнее целое состояние
    con.execute(f"PRAGMA busy_timeout={int(LOCK_WAIT_SECONDS * 1000)}")
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    """База могла быть заведена прежним кодом: заводим недостающее, но ничего не пересоздаём.
    Колонка `embedding_model` появилась 30.09.26 — у старых баз её нет."""
    con.executescript(_SCHEMA)
    have = {row[1] for row in con.execute("PRAGMA table_info(voice_sample)")}
    for column, ddl in _ADDED_COLUMNS:
        if column not in have:
            con.execute(f"ALTER TABLE voice_sample ADD COLUMN {column} {ddl}")
    con.commit()


# Колонки, появившиеся после первой схемы. Добавляются к уже заведённой базе, ничего не пересоздавая;
# у старых строк они пустые. Тот же перечень держит Планёрка (`voice_store.ADDED_COLUMNS`).
_ADDED_COLUMNS = (
    ("embedding_model", "VARCHAR(120) DEFAULT ''"),   # 30.09.26 — какой моделью снят отпечаток
    ("start_sec", "FLOAT"),                           # 16.10.26 — начало куска: ключ повтора вклада
    ("hint_name", "VARCHAR(200) DEFAULT ''"),         # 16.10.26 — подсказка по голосу, не привязка
    ("hint_score", "FLOAT"),                          # 16.10.26 — близость, на которой стоит подсказка
) + voice_review.COLUMNS                              # 21.10.2026 — «Разбор голосов»: встреча, реплика, отрывок, решение
# Близость, с которой кусок без времени (строка до 16.10.26) считается тем же куском той же записи.
# Копии записи 08.10 совпадали между собой с близостью 1,000; разные куски одной записи — заметно ниже.
SAME_PIECE_SIMILARITY = 0.999


def pack(vector: list[float]) -> bytes:
    """Отпечаток в байты — тот же формат, что у Планёрки: float32 little-endian."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def similarity(one: list[float], other: list[float]) -> float:
    """Косинусная близость: 1 — тот же голос, 0 — ничего общего. Длины разные — 0,0: сравнивать
    отпечатки разных моделей нельзя, и лучше честный ноль, чем случайное число."""
    if not one or not other or len(one) != len(other):
        return 0.0
    dot = sum(a * b for a, b in zip(one, other))
    na = math.sqrt(sum(a * a for a in one))
    nb = math.sqrt(sum(b * b for b in other))
    if not na or not nb:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def _confirmed_names(con: sqlite3.Connection) -> dict[str, int]:
    """Подтверждённые люди: {каноническое имя: id}. Отпечаток привязывается к человеку ТОЛЬКО если он
    уже подтверждён — людей ERP не создаёт."""
    return {row[0]: row[1] for row in
            con.execute("SELECT full_name, id FROM voice_person WHERE confirmed = 1")}


def _own_project() -> str:
    return os.environ.get("MEETFLOW_PROJECT", "meetflow")[:50]


def _reference_vectors(con: sqlite3.Connection) -> dict[str, list[list[float]]]:
    """Отпечатки подтверждённых людей — по ним и узнаём голос. Векторы читаются только для сравнения и
    никуда не показываются: правило «отпечатки наружу не отдаём» остаётся.

    Опорные — только привязанные НЕ кодом ERP (16.10.26). Строки ERP с `person_id` — это привязки, которые
    ERP ставил сам до 16.10.26 по одиночному совпадению; брать их в эталон значит усиливать собственную
    ошибку."""
    out: dict[str, list[list[float]]] = {}
    for name, person_id in _confirmed_names(con).items():
        vectors = [unpack(row[0]) for row in
                   con.execute("SELECT embedding FROM voice_sample WHERE person_id = ? AND origin_project != ?",
                               (person_id, _own_project()))]
        if vectors:
            out[name] = vectors
    return out


def embed_segments(wav_path: Path, segments: list[dict]) -> list[dict]:
    """Вектор отпечатка для каждого достаточно длинного куска речи. Механика та же, что у Планёрки:
    звук читается один раз и режется по отсчётам, потому что pyannote 4 декодирует путь сторонней
    библиотекой, которой нужны отдельно поставленные библиотеки ffmpeg."""
    import numpy as np
    import soundfile as sf
    import torch
    from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding

    folder = local_models.assert_local(local_models.embedding_dir(), "модель отпечатка голоса")
    model = PretrainedSpeakerEmbedding(str(folder))
    data, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
    wave = torch.from_numpy(data.T)   # (каналы, отсчёты)
    out = []
    for seg in segments:
        if (seg["end"] - seg["start"]) < MIN_SEGMENT_SEC:
            continue
        start = max(0, int(seg["start"] * sample_rate))
        end = min(wave.shape[1], int(seg["end"] * sample_rate))
        if end - start < int(MIN_SEGMENT_SEC * sample_rate):
            continue
        vector = np.asarray(model(wave[:, start:end][None]), dtype="float32").reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not norm or math.isnan(norm):
            continue
        out.append({**seg, "embedding": (vector / norm).tolist()})
    return out


# Прежнее имя оставлено: на него опираются тесты и внешние вызовы ERP-копии.
_embed = embed_segments


def _best_match(vector: list[float], references: dict[str, list[list[float]]]) -> tuple[str, float]:
    """Подсказка: имя подтверждённого человека и близость, если голос совпал не ниже порога; иначе ("", 0)."""
    best_name, best_score = "", 0.0
    for name, vectors in references.items():
        for reference in vectors:
            score = similarity(vector, reference)
            if score > best_score:
                best_name, best_score = name, score
    return (best_name, round(best_score, 4)) if best_score >= SAME_VOICE_SIMILARITY else ("", 0.0)


def _best_name(vector: list[float], references: dict[str, list[list[float]]]) -> str:
    """Имя подтверждённого человека, если голос совпал достаточно уверенно; иначе пусто."""
    return _best_match(vector, references)[0]


def _already_contributed(con: sqlite3.Connection, project: str, origin_ref: str) -> list[tuple]:
    """Что этот проект уже положил по этой записи этой моделью: (начало куска, длительность, вектор)."""
    return [(row[0], row[1], unpack(row[2])) for row in con.execute(
        "SELECT start_sec, seconds, embedding FROM voice_sample "
        "WHERE origin_project = ? AND origin_ref = ? AND COALESCE(embedding_model, '') IN (?, '')",
        (project, origin_ref, EMBEDDING_MODEL_NAME))]


def _is_repeat(start: float, seconds: float, vector: list[float], existing: list[tuple]) -> bool:
    """Тот же кусок той же записи уже лежит в базе? С временем — по началу куска; строки без времени (до
    16.10.26) — по той же длительности и тому же вектору."""
    for old_start, old_seconds, old_vector in existing:
        if old_start is not None:
            if abs(float(old_start) - start) < 0.01:
                return True
        elif (abs(float(old_seconds or 0) - seconds) < 0.011
              and similarity(vector, old_vector) >= SAME_PIECE_SIMILARITY):
            return True
    return False


def contribute(wav_path: Path, segments: list[dict], *, origin_ref: str = "", embedded: list[dict] | None = None,
               meeting_key: str = "", base: str | Path | None = None) -> dict:
    """Снять отпечатки с кусков речи и положить их в общую базу. Возвращает сводку для системного
    сообщения: сколько отпечатков записано, у скольких есть подсказка имени по голосу и сколько отсечено
    как повтор уже внесённой записи.

    Привязки к человеку ERP не ставит (16.10.26, 17.10.26): совпадение — подсказка, связь утверждает
    оператор. `named` остаётся в сводке и всегда 0 — по нему экран показывает «с именем», а имени ERP не
    даёт."""
    if not segments:
        return {"samples": 0, "named": 0, "hinted": 0, "duplicates": 0, "skipped": "нет кусков речи"}
    # Отпечатки могли уже снять для имён голосов (`recording_queue._voice_names`) — второй раз не считаем.
    if embedded is None:
        from . import otdelnyy_process     # отпечатки на процессоре — не в процессе сервера (25.10.2026)
        embedded = otdelnyy_process.выполнить(embed_segments, wav_path, segments)
    if not embedded:
        return {"samples": 0, "named": 0, "hinted": 0, "duplicates": 0,
                "skipped": f"нет кусков длиннее {MIN_SEGMENT_SEC:g} с"}

    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        con = None
        try:
            con = _connect(base)
            _ensure_schema(con)
            references = _reference_vectors(con)
            project, ref = _own_project(), str(origin_ref)[:100]
            existing = _already_contributed(con, project, ref)
            rows, hinted, duplicates = [], 0, 0
            for sample in embedded:
                start = round(float(sample["start"]), 2)
                seconds = round(float(sample["end"]) - float(sample["start"]), 2)
                if _is_repeat(start, seconds, sample["embedding"], existing):
                    duplicates += 1
                    continue
                existing.append((start, seconds, sample["embedding"]))
                hint, score = _best_match(sample["embedding"], references)
                if hint:
                    hinted += 1
                rows.append((
                    None, "",                       # привязки и заявленного имени нет — только подсказка
                    (sample.get("speaker") or "")[:50], pack(sample["embedding"]),
                    len(sample["embedding"]), seconds, project, ref, EMBEDDING_MODEL_NAME,
                    start, hint[:200], score if hint else None, str(meeting_key or "")[:50],
                ))
            con.executemany(
                "INSERT INTO voice_sample (person_id, claimed_name, speaker_label, embedding, "
                "embedding_dim, seconds, origin_project, origin_ref, embedding_model, start_sec, hint_name, "
                "hint_score, meeting_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))", rows)
            con.commit()
            out = {"samples": len(rows), "named": 0, "hinted": hinted, "duplicates": duplicates}
            if not rows and duplicates:
                out["skipped"] = f"запись уже внесена в общую базу: все {duplicates} кусков — повтор"
            return out
        except sqlite3.OperationalError as exc:
            # «database is locked» — база общая, в неё в этот момент может писать Планёрка.
            last_error = exc
            if attempt < ATTEMPTS:
                time.sleep(RETRY_PAUSE_SECONDS * attempt)
        finally:
            if con is not None:
                con.close()
    raise RuntimeError(f"не удалось записать отпечатки в общую базу: {last_error}")
