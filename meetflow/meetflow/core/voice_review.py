# -*- coding: utf-8 -*-
"""Разбор голосов: новые отпечатки общей базы на решение суперадминистратора (задание владелицы 21.10.2026).

Общий модуль ERP и Планёрки — файлы-близнецы, обязаны совпадать до байта (`proverka_zerkalnosti_pravok.py`). Приложения
он не знает: путь к общей базе голосов, «Команду» и запись встречи передаёт вызывающий. С базой работает напрямую через
sqlite3 — так же, как `voice_rule` и вклад ERP: база одна на две системы, и схема у неё одна.

Зачем. 16–17.10 база «на слух» собиралась на машине разработки: владелица слушала отрывок, видела предложенное имя и
отвечала «это он / нет / другой человек». Новые отпечатки копятся на локальной машине, и проверять их можно только там,
поэтому страница живёт в самих системах, в блоке суперадминистратора.

Что считается новым. Строка `voice_sample`, снятая системой (не «на слух» и не ответом оператора), по которой ещё нет
решения разбора (`review` пусто). Строки другой модели отпечатка не показываются — сравнивать их не с чем.

Группировка. Кластер — говорящий одной встречи: проект, дата записи, номер встречи в своём проекте (`meeting_key`) и
метка разбора по голосам («Говорящий 2»). Предложение по кластеру — правило `voice_rule` (центр окон к центру
человека: косинус ≥ 0,65 и отрыв ≥ 0,10 — «опознан», от 0,55 — «вероятно», ниже — «не узнан»). Кластеры собраны под
предполагаемым человеком.

Решения. «Это он» и «Другой человек» ставят человека (`person_id`) и кладут отпечаток в эталон: `voice_rule.etalony`
берёт строки с решением `yes` / `other` наравне с базой «на слух», поэтому следующее опознание уже считает центр с
ними. «Не он» и «Шум / не голос» снимают привязку и больше не предлагаются. Решение одно на строку: повторное нажатие
по уже решённой строке ничего не меняет. С каждым решением человека (и «Не он» по принятому правилом) пишется кандидат
правила на этот момент: кого предлагало, близость, отрыв, второй кандидат и его близость, статус (колонки `rule_*`,
26.10.2026) — иначе ошибку правила потом не разобрать.

Отрывки. Запись встречи после распознавания удаляется (правило «записи не храним»), поэтому послушать можно только то,
что вырезано при распознавании: до `VOICE_REVIEW_CLIPS_PER_SPEAKER` отрывков на говорящего (с 25.10.2026 — 6, было 3;
самые длинные куски, разнесённые по времени не меньше чем на `VOICE_REVIEW_CLIP_GAP` = 60 с), по
`VOICE_REVIEW_CLIP_SEC` (8) секунд. Отрывок проверяется сразу после вырезания: WAV PCM 16 бит, звука не меньше 1 с;
битый не сохраняется, строка остаётся без отрывка. Сервер битый файл не отдаёт — 404 с причиной словами. Отрывок лежит в папке рядом с общей базой и удаляется сразу после решения по своей
строке; нерешённый — не дольше `VOICE_REVIEW_CLIP_DAYS` (30) дней. Выключить вырезание — `VOICE_REVIEW_CLIPS=off`:
тогда на странице остаются текст реплики и время. Векторы наружу не отдаются.

Только непонятные (замечание владелицы 25.10.2026: «Убери все по ФИО, которые уже определены и подтверждены»). Говорящий,
которого правило опознало к подтверждённому человеку (близость ≥ 0,65, отрыв ≥ 0,10, речи не меньше `MIN_SEK`), в
очередь не выводится и значок его не считает. Его отпечатки получают решение `auto_rule` («принято по правилу»): с кем
(`review_name`), когда (`review_at`), по какому правилу и с какой близостью (`review_by`). К человеку они не привязываются
и в эталон не идут — эталон остаётся «на слух» и ответом оператора, иначе правило со временем мерило бы само себя.
Отрывки таких отпечатков удаляются, как после решения. Отметка ставится при открытии страницы и при подсчёте значка
(`prinyat_po_pravilu`), к накопленной очереди — скриптом `scripts/golosa_po_pravilu_2510.py`. Ошибка правила не должна
стать невидимой: второй вид страницы «Опознанные и решённые» (`reshennye`: принятые правилом и решённые людьми, только
просмотр; первый вид — «На проверку»), у принятых правилом кнопка «Не он»
(`ne_po_pravilu`) ставит `rule_no` и возвращает говорящего в очередь «не узнан» — правило его больше не принимает.

Только то, что можно проверить (замечание владелицы 26.10.2026: «Зачем вывод „реплики нет“ и „отрывок не сохранён“? Не
выводить»). Строка отпечатка показывается, только если у неё есть годный отрывок или текст реплики; пояснений, почему
нет звука или текста, страница не получает. Говорящий без единой такой строки в «На проверку» не выводится и значок его
не считает (`bez_materiala` — сколько таких): отпечатки остаются в базе без решения, и как только с новой встречи придут
строки с отрывком или репликой, говорящий вернётся в очередь. Решение по говорящему относится ко всем его строкам,
включая скрытые, — `ids` кластера полные.

Два почти равных кандидата (решение владелицы 26.10.2026). У «не узнан», где отрыв первого кандидата от второго меньше
отрыва правила, кластер получает `dva_kandidata`: страница показывает «Похож на: А (0,52) или Б (0,50)» и кнопку на
каждого. Решение «это Б» — то же «Это он» (`yes`) с именем второго кандидата из базы голосов.
"""
from __future__ import annotations

import os
import re
import sqlite3
import struct
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import voice_rule

YES, NO, OTHER, NOISE = "yes", "no", "other", "noise"
RESHENIYA = {YES: "Это он", NO: "Не он", OTHER: "Другой человек", NOISE: "Шум / не голос"}
V_ETALON = (YES, OTHER)              # решения, которые кладут отпечаток в центр человека
NE_PREDLAGAT = (NO, NOISE)           # решения, после которых строка больше не предлагается и ни к кому не привязана
AUTO = "auto_rule"                   # принято по правилу без разбора (25.10.2026): не в очереди, не в эталоне
RULE_NO = "rule_no"                  # «Не он» по принятому правилом: снова в очереди «не узнан», правило не принимает

# Колонки общей базы для разбора. Их же добавляют Планёрка (`voice_store.ADDED_COLUMNS`) и ERP
# (`voice_contrib._ADDED_COLUMNS`): база одна, и любая из систем может завести её первой.
COLUMNS = (
    ("meeting_key", "VARCHAR(50) DEFAULT ''"),     # номер встречи в своём проекте — только для разбора и карточек
    ("phrase", "TEXT DEFAULT ''"),                 # текст реплики, звучавшей в это время
    ("clip_file", "VARCHAR(200) DEFAULT ''"),      # имя файла отрывка в папке отрывков (не путь)
    ("review", "VARCHAR(20) DEFAULT ''"),          # решение разбора: yes / no / other / noise
    ("review_name", "VARCHAR(200) DEFAULT ''"),    # кто это (yes / other) или кем он не оказался (no)
    ("review_by", "VARCHAR(200) DEFAULT ''"),
    ("review_at", "DATETIME"),
    # Кандидат правила на момент решения человека (отчёт «Ошибки правила голосов», 26.10.2026): без него ошибку правила
    # не разобрать — после «да / другой» отпечаток уже в эталоне, и пересчёт выдаёт того же человека. У строк до 26.10 —
    # пусто. Пишут `primenit` и `ne_po_pravilu`; принятые правилом (`auto_rule`) держат числа в `review_by`, как раньше.
    ("rule_name", "VARCHAR(200) DEFAULT ''"),      # кого предлагало правило
    ("rule_cosine", "FLOAT"),                      # близость к нему
    ("rule_gap", "FLOAT"),                         # отрыв от второго
    ("rule_second", "VARCHAR(200) DEFAULT ''"),    # второй кандидат
    ("rule_second_cosine", "FLOAT"),               # близость ко второму
    ("rule_status", "VARCHAR(40) DEFAULT ''"),     # «опознан по правилу» / «вероятно» / «не узнан»
)

LOCK_WAIT_SECONDS = float(os.environ.get("VOICE_BASE_LOCK_WAIT", "15"))
POKAZAT_V_KLASTERE = 12              # сколько отпечатков кластера показывать списком (отрывки — первыми)
FRAZA_DO = 300                       # длина хранимой реплики


class RazborNeTot(ValueError):
    """Решение задано неверно — причина словами."""


# ------------------------------------------------------------------------------------------ настройки

def _chislo(name: str, default: float, low: float, high: float) -> float:
    raw = (os.environ.get(name) or "").strip().replace(",", ".")
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return min(max(value, low), high)


def nastroyki() -> dict:
    """Вырезание отрывков: включено ли, сколько на говорящего, какой длины и сколько дней ждёт решения."""
    return {"otryvki": (os.environ.get("VOICE_REVIEW_CLIPS", "on").strip().lower() not in ("off", "0", "no", "false")),
            "na_govoryashego": int(_chislo("VOICE_REVIEW_CLIPS_PER_SPEAKER", 6, 0, 20)),
            "sekund": _chislo("VOICE_REVIEW_CLIP_SEC", 8.0, 2.0, 30.0),
            "razryv": _chislo("VOICE_REVIEW_CLIP_GAP", 60.0, 0.0, 3600.0),
            "dney": int(_chislo("VOICE_REVIEW_CLIP_DAYS", 30, 1, 365))}


def papka(base_path) -> Path:
    """Папка отрывков: `VOICE_REVIEW_CLIPS_DIR` или рядом с файлом общей базы — её видят обе системы."""
    raw = (os.environ.get("VOICE_REVIEW_CLIPS_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    base = Path(str(base_path))
    return base.parent / f"{base.stem}_otryvki"


# ------------------------------------------------------------------------------------------ база

def _put(base_path) -> Path:
    if base_path is None or not str(base_path).strip():
        raise voice_rule.BazaNeTa("не задан VOICE_BASE_PATH — путь к файлу базы голосов")
    path = Path(str(base_path)).expanduser()
    if path.is_dir():
        raise voice_rule.BazaNeTa(f"в VOICE_BASE_PATH указана папка, а нужен файл базы голосов: {path}")
    return path


def _connect(base_path, *, need_file: bool = True) -> sqlite3.Connection:
    path = _put(base_path)
    if need_file and (not path.is_file() or path.stat().st_size == 0):
        raise voice_rule.BazaNeTa(f"файла базы голосов по пути VOICE_BASE_PATH нет: {path}")
    con = sqlite3.connect(str(path), timeout=LOCK_WAIT_SECONDS)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={int(LOCK_WAIT_SECONDS * 1000)}")
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "voice_sample" not in tables:
        con.close()
        raise voice_rule.BazaNeTa("файл по пути VOICE_BASE_PATH — не база голосов: нет таблицы voice_sample")
    ensure_columns(con)
    return con


def ensure_columns(con: sqlite3.Connection) -> None:
    """Колонки разбора — к уже заведённой базе, ничего не пересоздавая."""
    have = {row[1] for row in con.execute("PRAGMA table_info(voice_sample)")}
    changed = False
    for column, ddl in COLUMNS:
        if column not in have:
            con.execute(f"ALTER TABLE voice_sample ADD COLUMN {column} {ddl}")
            changed = True
    if changed:
        con.commit()


_ETALON_SQL = ", ".join(f"'{o}'" for o in voice_rule.ETALON_ORIGINS)
# Новая строка на разбор: снята системой, решения нет (или правило отвергнуто кнопкой «Не он»), модель — та же, что у эталона
_ZHDYOT = (f"COALESCE(review, '') IN ('', '{RULE_NO}') AND COALESCE(origin_project, '') NOT IN ({_ETALON_SQL}) "
           f"AND COALESCE(embedding_model, '') IN ('', '{voice_rule.MODEL}')")


def _unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def _data(value) -> str:
    """«2026-10-15» → «15.10.2026» (даты на экране — дд.мм.гггг)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(value or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(value or "")


# ------------------------------------------------------------------------------------------ при распознавании

def vyrezat_otryvki(base_path, wav_path, project: str, origin_ref: str, meeting_key: str = "") -> int:
    """Вырезать отрывки для прослушивания из записи встречи, пока она ещё на диске. Возвращает число отрывков.

    Берутся строки этой встречи, ждущие разбора и ещё без отрывка; на каждого говорящего — самые длинные, разнесённые
    по времени не меньше чем на `razryv` секунд (не хватает разнесённых — добираются просто самые длинные), не больше
    `na_govoryashego`. Вырезается начало куска длиной `sekund`. Вырезание выключено — 0, ничего не пишется."""
    st = nastroyki()
    if not st["otryvki"] or st["na_govoryashego"] <= 0:
        return 0
    con = _connect(base_path)
    try:
        rows = con.execute(
            f"SELECT id, speaker_label, start_sec, seconds, COALESCE(clip_file, '') FROM voice_sample WHERE {_ZHDYOT} "
            "AND origin_project = ? AND origin_ref = ? AND COALESCE(meeting_key, '') = ? AND start_sec IS NOT NULL",
            (project, str(origin_ref)[:100], str(meeting_key or ""))).fetchall()
        by_speaker: dict[str, list] = {}
        for row in rows:
            by_speaker.setdefault(row[1] or "", []).append(row)
        chosen = []
        for items in by_speaker.values():
            have = [r for r in items if r[4]]
            chosen += _vybrat([r for r in items if not r[4]], have, max(0, st["na_govoryashego"] - len(have)), st["razryv"])
        if not chosen:
            return 0
        folder = papka(base_path)
        folder.mkdir(parents=True, exist_ok=True)
        made = 0
        for sample_id, _label, start, seconds, _clip in chosen:
            name = f"otryvok_{int(sample_id)}.wav"
            length = min(float(seconds or st["sekund"]), st["sekund"])
            if _vyrezat(Path(wav_path), folder / name, float(start), length):
                con.execute("UPDATE voice_sample SET clip_file = ? WHERE id = ?", (name, sample_id))
                made += 1
        con.commit()
        return made
    finally:
        con.close()


def _vybrat(free: list, have: list, n: int, razryv: float) -> list:
    """До `n` строк из `free`: самые длинные, по времени не ближе `razryv` с к уже выбранным (и к строкам с отрывком);
    не хватает разнесённых — добираются оставшиеся самые длинные."""
    if n <= 0:
        return []
    po_dline = sorted(free, key=lambda r: (-(r[3] or 0), r[2]))
    starty = [float(r[2]) for r in have]
    chosen = []
    for r in po_dline:
        if len(chosen) >= n:
            break
        if all(abs(float(r[2]) - s) >= razryv for s in starty):
            chosen.append(r)
            starty.append(float(r[2]))
    for r in po_dline:
        if len(chosen) >= n:
            break
        if r not in chosen:
            chosen.append(r)
    return chosen


MIN_OTRYVOK_SEK = 1.0                # короче — отрывок не сохраняется: слушать нечего
_ZAGOLOVOK_WAV = 44                  # байт заголовка WAV: файл не длиннее — без звука («0:00 / 0:00» в плеере)


def proverit_otryvok(path) -> str:
    """Пусто — отрывок годен (WAV PCM 16 бит, звука не меньше `MIN_OTRYVOK_SEK`); иначе — что с ним не так, словами."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return "файла отрывка нет"
    if size <= _ZAGOLOVOK_WAV:
        return f"отрывок повреждён: файл {size} байт — только заголовок, звука нет"
    try:
        with wave.open(str(path), "rb") as w:
            rate, frames, width = w.getframerate(), w.getnframes(), w.getsampwidth()
    except (wave.Error, EOFError, OSError) as exc:
        return f"отрывок повреждён: не WAV PCM ({exc})"
    if width != 2:
        return f"отрывок повреждён: {width * 8} бит вместо 16"
    if not rate or frames / rate < MIN_OTRYVOK_SEK:
        return f"отрывок повреждён: звука {frames / rate if rate else 0:.1f} с"
    return ""


def _vyrezat(src: Path, dst: Path, start: float, length: float) -> bool:
    """Кусок [start, start + length] из wav в WAV PCM 16 бит. 16-битный PCM — стандартной библиотекой; другой формат
    (24/32 бит, float, WAVE_FORMAT_EXTENSIBLE) — soundfile с переводом в 16 бит. Готовый отрывок проверяется
    (`proverit_otryvok`): пустой, короче 1 с или не 16 бит — удаляется, строка остаётся без отрывка (25.10.2026:
    у владелицы отрывок открывался плеером «0:00 / 0:00»)."""
    ok = False
    try:
        with wave.open(str(src), "rb") as w:
            if w.getsampwidth() == 2:
                rate, frames = w.getframerate(), w.getnframes()
                first = max(0, int(start * rate))
                if first + int(MIN_OTRYVOK_SEK * rate) > frames:
                    return False          # отметка за концом записи — резать нечего
                w.setpos(first)
                data = w.readframes(max(1, min(int(length * rate), frames - first)))
                if len(data) < int(MIN_OTRYVOK_SEK * rate) * 2 * w.getnchannels():
                    return False          # заголовок обещал больше, чем есть в файле
                with wave.open(str(dst), "wb") as out:
                    out.setnchannels(w.getnchannels())
                    out.setsampwidth(2)
                    out.setframerate(rate)
                    out.writeframes(data)
                ok = True
    except (wave.Error, EOFError):
        pass
    if not ok:
        try:
            import soundfile as sf

            info = sf.info(str(src))
            first = max(0, int(start * info.samplerate))
            if first + int(MIN_OTRYVOK_SEK * info.samplerate) > info.frames:
                return False
            data, rate = sf.read(str(src), start=first, frames=int(length * info.samplerate), dtype="int16")
            if len(data) < int(MIN_OTRYVOK_SEK * rate):
                return False
            sf.write(str(dst), data, rate, subtype="PCM_16", format="WAV")
            ok = True
        except Exception:  # noqa: BLE001 — нет отрывка: останутся текст и время
            ok = False
    if ok and proverit_otryvok(dst):
        _udalit(dst)
        ok = False
    return ok


def repliki_iz_teksta(text: str) -> list[tuple[float, float, str]]:
    """Строки расшифровки «00:05:12<таб>[кто<таб>]реплика» → [(начало, конец, реплика)]; конец — начало следующей."""
    out: list[list] = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        nums = [int(p) for p in parts[0].strip().split(":") if p.isdigit()] if parts else []
        if len(parts) < 2 or len(nums) not in (2, 3):
            continue
        sec = nums[0] * 3600 + nums[1] * 60 + nums[2] if len(nums) == 3 else nums[0] * 60 + nums[1]
        phrase = re.sub(r"^(?:Говорящий\s+\d+|SPEAKER_\d+)\s*:\s*", "", parts[-1].strip())
        out.append([float(sec), float(sec) + 30.0, phrase])
    for i in range(len(out) - 1):
        out[i][1] = max(out[i][0], out[i + 1][0])
    return [tuple(x) for x in out]


def zapisat_repliki(base_path, project: str, origin_ref: str, meeting_key: str, repliki) -> int:
    """Текст реплики к строкам этой встречи без текста: всё, что звучало в [начало, конец] куска, до 300 знаков."""
    items = sorted(((float(a), float(b), (t or "").strip()) for a, b, t in (repliki or []) if (t or "").strip()),
                   key=lambda x: x[0])
    if not items:
        return 0
    con = _connect(base_path)
    try:
        rows = con.execute(
            "SELECT id, start_sec, seconds FROM voice_sample WHERE origin_project = ? AND origin_ref = ? "
            "AND COALESCE(meeting_key, '') = ? AND COALESCE(phrase, '') = '' AND start_sec IS NOT NULL",
            (project, str(origin_ref)[:100], str(meeting_key or ""))).fetchall()
        n = 0
        for sample_id, start, seconds in rows:
            a, b = float(start), float(start) + float(seconds or 0)
            words = [t for s, e, t in items if s <= b and e >= a]
            if not words:
                continue
            phrase = " ".join(words)
            con.execute("UPDATE voice_sample SET phrase = ? WHERE id = ?",
                        (phrase[:FRAZA_DO - 1] + "…" if len(phrase) > FRAZA_DO else phrase, sample_id))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


# ------------------------------------------------------------------------------------------ очередь

def _klyuch(row) -> tuple:
    return (row["origin_project"] or "", row["origin_ref"] or "", row["meeting_key"] or "", row["speaker_label"] or "")


def _razlozhit(base_path, settings: dict) -> tuple[dict, dict, str]:
    """Строки, ждущие разбора, по говорящим встречи с решением правила: (кластеры, сводка эталона, почему эталона нет).
    Кластер, по которому правило отвергнуто кнопкой «Не он» (`rule_no`), — «не узнан» без имени."""
    try:
        centry, base = voice_rule.etalony(base_path)
        etalon_net = ""
    except voice_rule.BazaNeTa as exc:
        centry, base, etalon_net = {}, {"lyudey": 0, "otpechatkov": 0}, str(exc)
    con = _connect(base_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT id, origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
            f"COALESCE(speaker_label, '') AS speaker_label, embedding, seconds, start_sec, COALESCE(phrase, '') AS phrase, "
            f"COALESCE(clip_file, '') AS clip_file, COALESCE(claimed_name, '') AS claimed_name, "
            f"COALESCE(hint_name, '') AS hint_name, COALESCE(review, '') AS review, "
            f"COALESCE(review_name, '') AS review_name FROM voice_sample WHERE {_ZHDYOT} "
            f"ORDER BY origin_ref DESC, start_sec").fetchall()
    finally:
        con.close()
    folder = papka(base_path)
    min_sek = float(settings.get("min_sek", voice_rule.MIN_SEK))
    klastery: dict[tuple, dict] = {}
    for row in rows:
        k = _klyuch(row)
        kl = klastery.setdefault(k, {"project": k[0], "ref": k[1], "data": _data(k[1]), "meeting_key": k[2], "label": k[3],
                                     "vectors": [], "otpechatki": [], "seconds": 0.0, "metki_vks": set(), "podskazki": set(),
                                     "ne_po_pravilu": "", "clips": []})
        kl["vectors"].append(_unpack(row["embedding"]))
        kl["seconds"] += float(row["seconds"] or 0)
        if row["claimed_name"]:
            kl["metki_vks"].add(row["claimed_name"])
        if row["hint_name"]:
            kl["podskazki"].add(row["hint_name"])
        if row["review"] == RULE_NO:
            kl["ne_po_pravilu"] = row["review_name"] or kl["ne_po_pravilu"] or "—"
        if row["clip_file"]:
            kl["clips"].append(row["clip_file"])
        est = bool(row["clip_file"]) and not proverit_otryvok(folder / Path(row["clip_file"]).name)
        kl["otpechatki"].append({"id": row["id"], "start": row["start_sec"], "seconds": round(float(row["seconds"] or 0), 1),
                                 "vremya": _vremya(row["start_sec"]), "phrase": row["phrase"], "otryvok": est})
    for kl in klastery.values():
        vectors = kl.pop("vectors")
        try:
            found = voice_rule.reshit(voice_rule.centr(vectors), centry, settings["porog"], settings["otryv"],
                                      settings["podskazka"]) if centry else None
        except voice_rule.BazaNeTa:
            found = None
        found = found or {"status": voice_rule.NONE, "name": "", "cosine": 0.0, "gap": 0.0, "second": "", "second_cosine": 0.0}
        status, prichina = found["status"], ""
        if status == voice_rule.CONFIRMED and kl["seconds"] < min_sek:
            # как при распознавании (`voice_rule.opoznat`): центр по короткому куску ненадёжен — только «вероятно»
            status, prichina = voice_rule.HINT, f"мало речи: {kl['seconds']:.0f} с, нужно не меньше {min_sek:.0f} с"
        if kl["ne_po_pravilu"]:
            status, prichina = voice_rule.NONE, f"правило ошиблось: не {kl['ne_po_pravilu']}"
        kl.update({"status": status, "prichina": prichina, "imya": found["name"] if status != voice_rule.NONE else "",
                   "kandidat": found["name"], "cosine": found["cosine"], "gap": found["gap"], "second": found["second"],
                   "second_cosine": found["second_cosine"], "vsego": len(kl["otpechatki"]), "seconds": round(kl["seconds"], 1),
                   "metki_vks": sorted(kl["metki_vks"]), "podskazki": sorted(kl["podskazki"]),
                   "ids": [o["id"] for o in kl["otpechatki"]]})
    return klastery, base, etalon_net


_PROGON: dict[str, tuple] = {}       # состояние базы при последней отметке: значок не пересчитывает векторы зря


def _sostoyanie(base_path, settings: dict) -> tuple:
    con = _connect(base_path)
    try:
        samples = con.execute("SELECT COUNT(*), COALESCE(MAX(id), 0), "
                              "SUM(CASE WHEN COALESCE(review, '') != '' THEN 1 ELSE 0 END), COUNT(person_id) "
                              "FROM voice_sample").fetchone()
        people = con.execute("SELECT COUNT(*), COALESCE(SUM(confirmed), 0) FROM voice_person").fetchone()
    finally:
        con.close()
    return tuple(samples) + tuple(people) + tuple(sorted(settings.items()))


def _num(x) -> str:
    return f"{float(x):.2f}".replace(".", ",")


def prinyat_po_pravilu(base_path, *, udalyat_otryvki: bool = True) -> dict:
    """Говорящих, опознанных правилом к подтверждённому человеку, — из очереди: решение `auto_rule`.

    {"klasterov", "otpechatkov", "otryvkov_udaleno"}. Человек не привязывается, эталон не меняется. Неверная настройка
    правила или нет эталона — ничего не принимается: очередь остаётся полной, а не теряет людей молча.
    `udalyat_otryvki=False` — для сухого хода на копии: папка отрывков может быть общей (`VOICE_REVIEW_CLIPS_DIR`)."""
    pusto = {"klasterov": 0, "otpechatkov": 0, "otryvkov_udaleno": 0}
    try:
        settings = voice_rule.nastroyki()
    except voice_rule.NastroykaNeTa:
        return pusto
    klyuch = str(Path(str(base_path)).expanduser().resolve())
    if udalyat_otryvki and _PROGON.get(klyuch) == _sostoyanie(base_path, settings):
        return pusto
    klastery, _base, _net = _razlozhit(base_path, settings)
    prinyaty = [kl for kl in klastery.values() if kl["status"] == voice_rule.CONFIRMED]
    otpechatkov = 0
    if prinyaty:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        con = _connect(base_path)
        try:
            for kl in prinyaty:
                pravilo = (f"правило {_num(settings['porog'])} / {_num(settings['otryv'])}: близость {_num(kl['cosine'])}, "
                           f"отрыв {_num(kl['gap'])}" + (f" (второй — {kl['second']}, {_num(kl['second_cosine'])})"
                                                         if kl["second"] else ""))
                marks = ",".join("?" * len(kl["ids"]))
                cur = con.execute(
                    "UPDATE voice_sample SET review = ?, review_name = ?, review_by = ?, review_at = ?, clip_file = '' "
                    f"WHERE id IN ({marks}) AND COALESCE(review, '') = ''",
                    [AUTO, kl["kandidat"][:200], pravilo[:200], now, *kl["ids"]])
                otpechatkov += cur.rowcount
            con.commit()
        finally:
            con.close()
    udaleno = 0
    if udalyat_otryvki:
        folder = papka(base_path)
        udaleno = sum(_udalit(folder / Path(c).name) for kl in prinyaty for c in kl["clips"])
        _PROGON[klyuch] = _sostoyanie(base_path, settings)
    return {"klasterov": len(prinyaty), "otpechatkov": otpechatkov, "otryvkov_udaleno": udaleno}


def _est_material(o: dict) -> bool:
    """Строку есть чем проверить: годный отрывок (кнопка «Слушать») или текст реплики (26.10.2026)."""
    return bool(o["otryvok"] or (o["phrase"] or "").strip())


def dva_kandidata(kl: dict, settings: dict) -> bool:
    """«Не узнан» с двумя почти равными кандидатами (решение владелицы 26.10.2026): отрыв первого от второго меньше
    отрыва правила (`VOICE_RULE_OTRYV`, 0,10). Граница — как в `voice_rule.reshit`: отрыв ровно 0,10 уже явный. Порог
    взят из правила, а не свой: меньше этого отрыва правило и само не различает двух людей, поэтому выбирать между ними
    первым — подсказка, которой нет. Говорящий, по которому правило отвергнуто «Не он», — как раньше: кандидата правила
    человек уже отклонил. Страница тогда показывает обоих на равных и кнопку на каждого."""
    return bool(kl.get("status") == voice_rule.NONE and kl.get("kandidat") and kl.get("second")
                and not kl.get("ne_po_pravilu") and float(kl.get("gap") or 0.0) < float(settings["otryv"]) - 1e-9)


def ochered(base_path) -> dict:
    """Непонятные говорящие — «вероятно» и «не узнан», сгруппированные по говорящему встречи и предполагаемому человеку.

    {"gruppy": [{"imya", "status", "klastery": [...]}], "otpechatkov", "klasterov", "s_otryvkom", "bez_materiala",
    "pravilo", "etalon", "po_pravilu"}. Опознанные правилом сначала отмечаются `auto_rule` и в очередь не входят — они в
    "po_pravilu". В "otpechatki" — только строки с отрывком или репликой; говорящий без таких строк не выводится, он в
    счёте "bez_materiala". Эталона нет (подтверждённых людей нет) — кластеры без предложения, причина в "etalon_net"."""
    pochistit_starye(base_path)
    prinyat_po_pravilu(base_path)
    settings = voice_rule.nastroyki()
    klastery, base, etalon_net = _razlozhit(base_path, settings)
    nepon = [kl for kl in klastery.values() if kl["status"] != voice_rule.CONFIRMED]
    pokaz = [kl for kl in nepon if any(_est_material(o) for o in kl["otpechatki"])]
    gruppy: dict[str, dict] = {}
    for kl in pokaz:
        kl.pop("clips", None)
        kl["otpechatki"] = sorted((o for o in kl["otpechatki"] if _est_material(o)),
                                  key=lambda o: (not o["otryvok"], o["start"] or 0))
        g = gruppy.setdefault(kl["imya"], {"imya": kl["imya"], "klastery": [], "otpechatkov": 0})
        g["klastery"].append(kl)
        g["otpechatkov"] += kl["vsego"]
    s_otryvkom = sum(o["otryvok"] for kl in pokaz for o in kl["otpechatki"])
    for kl in pokaz:
        kl["otpechatki"] = kl["otpechatki"][:POKAZAT_V_KLASTERE]
        kl["dva_kandidata"] = dva_kandidata(kl, settings)
    for g in gruppy.values():
        g["klastery"].sort(key=lambda kl: (kl["ref"], kl["label"]), reverse=True)
        g["status"] = voice_rule.HINT if g["imya"] else voice_rule.NONE
    poryadok = sorted(gruppy.values(), key=lambda g: (not g["imya"], -g["otpechatkov"], g["imya"]))
    return {"gruppy": poryadok, "otpechatkov": sum(kl["vsego"] for kl in pokaz), "klasterov": len(pokaz),
            "s_otryvkom": s_otryvkom, "bez_materiala": len(nepon) - len(pokaz), "pravilo": settings,
            "etalon": {"lyudey": base.get("lyudey", 0), "otpechatkov": base.get("otpechatkov", 0)},
            "etalon_net": etalon_net, "otryvki": nastroyki(), "po_pravilu": po_pravilu(base_path),
            "reshennye": reshennye(base_path)}


POKAZAT_PO_PRAVILU = 300             # сколько принятых правилом говорящих показывать списком (свежие первыми)


def po_pravilu(base_path) -> dict:
    """Принятые правилом без разбора — для просмотра и кнопки «Не он»: {"klasterov", "otpechatkov", "klastery"}."""
    con = _connect(base_path)
    try:
        rows = con.execute(
            "SELECT origin_project, origin_ref, COALESCE(meeting_key, ''), COALESCE(speaker_label, ''), "
            "COALESCE(review_name, ''), MAX(COALESCE(review_by, '')), MAX(review_at), COUNT(*), GROUP_CONCAT(id) "
            "FROM voice_sample WHERE review = ? GROUP BY 1, 2, 3, 4, 5 ORDER BY 7 DESC, 2 DESC, 4", (AUTO,)).fetchall()
    finally:
        con.close()
    klastery = [{"project": p or "", "ref": r or "", "data": _data(r), "meeting_key": m, "label": metka, "imya": imya,
                 "pravilo": by, "kogda": _kogda(at), "vsego": n, "ids": [int(x) for x in str(ids or "").split(",") if x]}
                for p, r, m, metka, imya, by, at, n, ids in rows]
    return {"klasterov": len(klastery), "otpechatkov": sum(k["vsego"] for k in klastery),
            "klastery": klastery[:POKAZAT_PO_PRAVILU]}


RESHENO_TEKST = {AUTO: "опознан по правилу", YES: "это он", OTHER: "другой человек", NO: "не он", NOISE: "шум / не голос"}


def reshennye(base_path) -> dict:
    """Вид «Опознанные и решённые» (владелица 25.10.2026: «нам визуально нужны только новые, те, что на проверку, а
    остальные — убрать на другую вкладку»): принятые правилом и решённые людьми, свежие первыми, только просмотр.
    {"klasterov", "otpechatkov", "po_pravilu", "lyudmi", "klastery"}; у принятых правилом — кнопка «Не он» (`ne_on`)."""
    reshenia = (AUTO, YES, OTHER, NO, NOISE)
    con = _connect(base_path)
    try:
        rows = con.execute(
            "SELECT origin_project, origin_ref, COALESCE(meeting_key, ''), COALESCE(speaker_label, ''), review, "
            "COALESCE(review_name, ''), MAX(COALESCE(review_by, '')), MAX(review_at), COUNT(*), GROUP_CONCAT(id) "
            f"FROM voice_sample WHERE review IN ({', '.join('?' * len(reshenia))}) "
            f"AND COALESCE(origin_project, '') NOT IN ({_ETALON_SQL}) "
            "GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 8 DESC, 2 DESC, 4", reshenia).fetchall()
    finally:
        con.close()
    klastery = [{"project": p or "", "ref": r or "", "data": _data(r), "meeting_key": m, "label": metka, "reshenie": rv,
                 "reshenie_tekst": RESHENO_TEKST.get(rv, rv), "imya": imya,
                 "pravilo": by if rv == AUTO else "", "kto": by if rv != AUTO else "", "kogda": _kogda(at), "vsego": n,
                 "ne_on": rv == AUTO, "ids": [int(x) for x in str(ids or "").split(",") if x] if rv == AUTO else []}
                for p, r, m, metka, rv, imya, by, at, n, ids in rows]
    return {"klasterov": len(klastery), "otpechatkov": sum(k["vsego"] for k in klastery),
            "po_pravilu": sum(k["reshenie"] == AUTO for k in klastery),
            "lyudmi": sum(k["reshenie"] != AUTO for k in klastery), "klastery": klastery[:POKAZAT_PO_PRAVILU]}


def _kogda(value) -> str:
    """«2026-10-25 09:14:00» (UTC) → «25.10.2026 12:14» по Москве."""
    try:
        moment = datetime.fromisoformat(str(value)) + timedelta(hours=3)
    except (TypeError, ValueError):
        return ""
    return f"{moment:%d.%m.%Y %H:%M}"


def ne_po_pravilu(base_path, ids, kto: str = "") -> dict:
    """«Не он» по принятому правилом: строки снова на разбор как «не узнан», правило их больше не принимает.

    {"vozvrasheno", "klastery"}. Меняются только строки с решением `auto_rule`; имя остаётся — как отвергнутый кандидат."""
    ids = sorted({int(i) for i in (ids or [])})
    if not ids:
        raise RazborNeTot("не выбрано ни одного отпечатка")
    con = _connect(base_path)
    con.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT id, origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
                           f"COALESCE(speaker_label, '') AS speaker_label FROM voice_sample "
                           f"WHERE id IN ({marks}) AND review = ?", [*ids, AUTO]).fetchall()
        if rows:
            kandidaty = kandidaty_pravila(base_path, ids, po_pravilu=True)    # до записи решения (26.10.2026)
            now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
            con.executemany(f"UPDATE voice_sample SET review = ?, review_by = ?, review_at = ?, {_SET_PRAVILO} "
                            f"WHERE id = ? AND review = ?",
                            [(RULE_NO, (kto or "")[:200], now, *_pravilo_stroki(kandidaty.get(row["id"])), row["id"], AUTO)
                             for row in rows])
            con.commit()
    finally:
        con.close()
    return {"vozvrasheno": len(rows), "klastery": sorted({_klyuch(row) for row in rows})}


def _vremya(sec) -> str:
    if sec is None:
        return ""
    s = int(float(sec))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def schyot(base_path) -> dict:
    """Сухой подсчёт: сколько отпечатков ждёт разбора, кластеров, с отрывком, по встречам. Векторы не читаются."""
    con = _connect(base_path)
    try:
        rows = con.execute(
            f"SELECT origin_project, origin_ref, COALESCE(meeting_key, ''), COUNT(*), "
            f"COUNT(DISTINCT COALESCE(speaker_label, '')), SUM(CASE WHEN COALESCE(clip_file, '') != '' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN COALESCE(phrase, '') != '' THEN 1 ELSE 0 END) "
            f"FROM voice_sample WHERE {_ZHDYOT} GROUP BY 1, 2, 3 ORDER BY 2 DESC, 1").fetchall()
    finally:
        con.close()
    po_vstrecham = [{"project": p or "", "ref": r or "", "data": _data(r), "meeting_key": m, "otpechatkov": n,
                     "klasterov": k, "s_otryvkom": c or 0, "s_tekstom": t or 0} for p, r, m, n, k, c, t in rows]
    return {"otpechatkov": sum(x["otpechatkov"] for x in po_vstrecham),
            "klasterov": sum(x["klasterov"] for x in po_vstrecham),
            "s_otryvkom": sum(x["s_otryvkom"] for x in po_vstrecham),
            "s_tekstom": sum(x["s_tekstom"] for x in po_vstrecham),
            "vstrech": len(po_vstrecham), "po_vstrecham": po_vstrecham}


def chislo_klasterov(base_path) -> int:
    """Число непонятных говорящих — значок меню. Опознанных правилом сначала отмечает (`prinyat_po_pravilu`; повторно —
    только когда в базе что-то поменялось), дальше — счёт по базе без векторов. Говорящий без строки с отрывком или
    репликой не считается — как и на странице (26.10.2026): проверять его нечем."""
    try:
        prinyat_po_pravilu(base_path)
    except sqlite3.Error:
        pass                          # база занята — значок посчитает всех, страница отметит при открытии
    con = _connect(base_path)
    try:
        rows = con.execute(
            f"SELECT MAX(CASE WHEN TRIM(COALESCE(phrase, '')) != '' THEN 1 ELSE 0 END), "
            f"GROUP_CONCAT(NULLIF(COALESCE(clip_file, ''), ''), '|') FROM voice_sample WHERE {_ZHDYOT} "
            "GROUP BY origin_project, origin_ref, COALESCE(meeting_key, ''), COALESCE(speaker_label, '')").fetchall()
    finally:
        con.close()
    folder = papka(base_path)
    return sum(1 for est_fraza, clips in rows
               if est_fraza or any(not proverit_otryvok(folder / Path(c).name) for c in str(clips or "").split("|") if c))


# ------------------------------------------------------------------------------------------ решение

STATUS_PRAVILA = {voice_rule.CONFIRMED: "опознан по правилу", voice_rule.HINT: "вероятно", voice_rule.NONE: "не узнан"}
_SET_PRAVILO = ("rule_name = ?, rule_cosine = ?, rule_gap = ?, rule_second = ?, rule_second_cosine = ?, "
                "rule_status = ?")


def _pravilo_stroki(k: dict | None) -> tuple:
    """Значения колонок кандидата правила для UPDATE; кандидата нет (правило не посчитано) — пусто и NULL."""
    if not k:
        return ("", None, None, "", None, "")
    return ((k.get("name") or "")[:200], k.get("cosine"), k.get("gap"), (k.get("second") or "")[:200],
            k.get("second_cosine"), STATUS_PRAVILA.get(k.get("status"), k.get("status") or ""))


def kandidaty_pravila(base_path, ids, *, po_pravilu: bool = False) -> dict[int, dict]:
    """Кандидат правила на момент решения человека (26.10.2026): {id отпечатка: {status, name, cosine, gap, second,
    second_cosine}} — по кластеру строки (говорящий встречи), так же, как его видит очередь (`_razlozhit`): центр строк
    кластера, ждущих разбора, к эталону; «опознан» при речи меньше `min_sek` — «вероятно»; кластер с «Не он» по правилу
    (`rule_no`) — «не узнан», кандидат остаётся. `po_pravilu` — кластер из принятых правилом (`auto_rule`, кнопка «Не он»).
    Звать до записи решения: «да / другой» сразу кладут отпечаток в эталон. Нет эталона или настройки — {} (решение
    всё равно пишется, колонки кандидата пустые)."""
    ids = sorted({int(i) for i in (ids or [])})
    if not ids:
        return {}
    try:
        settings = voice_rule.nastroyki()
        centry, _base = voice_rule.etalony(base_path)
    except (voice_rule.NastroykaNeTa, voice_rule.BazaNeTa):
        return {}
    if not centry:
        return {}
    gde, args = ("review = ?", [AUTO]) if po_pravilu else (_ZHDYOT, [])
    con = _connect(base_path)
    con.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(ids))
        vybrany = con.execute(f"SELECT id, origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
                              f"COALESCE(speaker_label, '') AS speaker_label FROM voice_sample "
                              f"WHERE id IN ({marks}) AND {gde}", [*ids, *args]).fetchall()
        kluchi = {_klyuch(r) for r in vybrany}
        refs = sorted({k[1] for k in kluchi})
        rows = con.execute(
            f"SELECT id, origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
            f"COALESCE(speaker_label, '') AS speaker_label, embedding, seconds, COALESCE(review, '') AS review, "
            f"COALESCE(review_name, '') AS review_name FROM voice_sample "
            f"WHERE {gde} AND origin_ref IN ({','.join('?' * len(refs))})", [*args, *refs]).fetchall() if refs else []
    finally:
        con.close()
    klastery: dict[tuple, dict] = {}
    for row in rows:
        k = _klyuch(row)
        if k not in kluchi:
            continue
        kl = klastery.setdefault(k, {"vectors": [], "seconds": 0.0, "rule_no": False})
        kl["vectors"].append(_unpack(row["embedding"]))
        kl["seconds"] += float(row["seconds"] or 0)
        kl["rule_no"] = kl["rule_no"] or row["review"] == RULE_NO
    po_klyuchu: dict[tuple, dict] = {}
    for k, kl in klastery.items():
        try:
            found = voice_rule.reshit(voice_rule.centr(kl["vectors"]), centry, settings["porog"], settings["otryv"],
                                      settings["podskazka"])
        except voice_rule.BazaNeTa:
            continue
        found = dict(found)
        if found["status"] == voice_rule.CONFIRMED and kl["seconds"] < float(settings.get("min_sek", voice_rule.MIN_SEK)):
            found["status"] = voice_rule.HINT
        if kl["rule_no"]:
            found["status"] = voice_rule.NONE
        po_klyuchu[k] = found
    return {int(r["id"]): po_klyuchu[_klyuch(r)] for r in vybrany if _klyuch(r) in po_klyuchu}


def _chelovek(con: sqlite3.Connection, imya: str, kto: str) -> int:
    """Человек общей базы по ФИО: полное имя, затем написание-синоним; нет — заводится подтверждённым (решение
    суперадминистратора на странице разбора и есть подтверждение). «Е» и «ё» — одна буква (правило владелицы 26.10.2026):
    «Фёдоров» находит записанного «Федорова», второй человек не заводится; ФИО в базе остаётся как было записано."""
    from .norm_yo import ключ

    row = con.execute("SELECT id, confirmed FROM voice_person WHERE full_name = ?", (imya,)).fetchone()
    if row is None:
        row = next((r[:2] for r in con.execute("SELECT id, confirmed, full_name FROM voice_person ORDER BY id").fetchall()
                    if ключ(r[2]) == ключ(imya)), None)
    if row is None:
        for pid, aliases in con.execute("SELECT id, COALESCE(aliases, '') FROM voice_person WHERE confirmed = 1").fetchall():
            if ключ(imya) in [ключ(a) for a in aliases.splitlines() if a.strip()]:
                return int(pid)
        cur = con.execute(
            "INSERT INTO voice_person (full_name, aliases, confirmed, confirmed_by, confirmed_at, created_at, note) "
            "VALUES (?, '', 1, ?, datetime('now'), datetime('now'), ?)",
            (imya[:200], (kto or "")[:200], f"разбор голосов, {datetime.now():%d.%m.%Y}"))
        return int(cur.lastrowid)
    if not row[1]:
        con.execute("UPDATE voice_person SET confirmed = 1, confirmed_by = ?, confirmed_at = datetime('now') WHERE id = ?",
                    ((kto or "")[:200], row[0]))
    return int(row[0])


def primenit(base_path, ids, reshenie: str, imya: str = "", kto: str = "") -> dict:
    """Решение по отпечаткам: {"razobrano", "otryvkov_udaleno", "klastery": [(проект, дата, встреча, метка), …]}.

    Меняются только строки, ещё ждущие разбора. «Это он» / «Другой человек» — нужен человек (ФИО полностью);
    «Не он» — `imya` пишется как отклонённый кандидат. Отрывки решённых строк удаляются сразу."""
    if reshenie not in RESHENIYA:
        raise RazborNeTot(f"решение «{reshenie}» неизвестно; есть: {', '.join(RESHENIYA.values())}")
    imya = re.sub(r"\s+", " ", imya or "").strip()
    if reshenie in V_ETALON and len(imya.split()) < 2:
        raise RazborNeTot("нужны фамилия и имя полностью: по одному слову человека не отличить от тёзки")
    ids = sorted({int(i) for i in (ids or [])})
    if not ids:
        raise RazborNeTot("не выбрано ни одного отпечатка")
    con = _connect(base_path)
    con.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT id, origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
                           f"COALESCE(speaker_label, '') AS speaker_label, COALESCE(clip_file, '') AS clip_file "
                           f"FROM voice_sample WHERE id IN ({marks}) AND {_ZHDYOT}", ids).fetchall()
        if not rows:
            return {"razobrano": 0, "otryvkov_udaleno": 0, "klastery": []}
        # кандидат правила — до решения: «да / другой» сразу кладут отпечаток в эталон (26.10.2026)
        kandidaty = kandidaty_pravila(base_path, ids)
        person_id = _chelovek(con, imya, kto) if reshenie in V_ETALON else None
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        con.executemany(
            "UPDATE voice_sample SET review = ?, review_name = ?, review_by = ?, review_at = ?, person_id = ?, clip_file = '', "
            f"{_SET_PRAVILO} WHERE id = ? AND {_ZHDYOT}",
            [(reshenie, imya[:200], (kto or "")[:200], now, person_id, *_pravilo_stroki(kandidaty.get(row["id"])),
              row["id"]) for row in rows])
        con.commit()
    finally:
        con.close()
    folder = papka(base_path)
    udaleno = 0
    for row in rows:
        if row["clip_file"]:
            udaleno += _udalit(folder / Path(row["clip_file"]).name)
    return {"razobrano": len(rows), "otryvkov_udaleno": udaleno,
            "klastery": sorted({_klyuch(row) for row in rows})}


def _udalit(path: Path) -> int:
    try:
        path.unlink()
        return 1
    except OSError:
        return 0


def razobrano(base_path, project: str, meeting_key: str, origin_ref: str, label: str) -> dict | None:
    """Говорящий встречи разобран целиком? {"reshenie", "imya"} — решение большинства его отпечатков; None — есть
    нерешённые, строк нет или база недоступна. Строки без номера встречи (до 21.10.2026) узнаются по дате записи."""
    try:
        con = _connect(base_path)
    except (voice_rule.BazaNeTa, sqlite3.Error):
        return None
    try:
        rows = con.execute(
            "SELECT COALESCE(review, ''), COALESCE(review_name, ''), COUNT(*) FROM voice_sample "
            "WHERE origin_project = ? AND COALESCE(speaker_label, '') = ? "
            "AND (COALESCE(meeting_key, '') = ? OR (COALESCE(meeting_key, '') = '' AND origin_ref = ?)) "
            "GROUP BY 1, 2 ORDER BY 3 DESC",
            (project, label or "", str(meeting_key or ""), str(origin_ref or ""))).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not rows or any(review in ("", AUTO, RULE_NO) for review, _name, _n in rows):
        return None                   # принятое правилом — не решение человека: подсказку в «Конфликтах» закрывает он
    review, name, _n = rows[0]
    return {"reshenie": review, "imya": name}


def klyuch_klastera(project: str, origin_ref: str, meeting_key: str, label: str) -> str:
    """Ключ блока говорящего на странице «Разбор голосов»: «проект|дата|встреча|метка» — тот же собирает `ключГолоса`
    в razbor.js из полей кластера (26.10.2026)."""
    return "|".join(str(x or "") for x in (project, origin_ref, meeting_key, label))


def mesto_govoryashchego(base_path, project: str, meeting_key: str, origin_ref: str, label: str) -> dict:
    """Где говорящий встречи на странице «Разбор голосов» — для перехода «Прослушать и решить» из карточки подсказки голоса
    (замечание владелицы 26.10.2026: «она никуда не ведёт, и прослушать голос не предлагают»).

    {"vid", "klyuch"}: "proverka" — ждёт разбора и есть отрывок или реплика (вид «На проверку»); "resheno" — принят
    правилом (вид «Опознанные и решённые»); пусто — материала нет (говорящий скрыт из «На проверку»), он уже решён или
    строк нет: решить можно в самой карточке. Строки без номера встречи (до 21.10.2026) узнаются по дате записи, как в
    `razobrano`. Опознанный правилом, но ещё не отмеченный, на странице окажется в «Опознанных и решённых» — экран ищет
    его во втором виде сам."""
    con = _connect(base_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT origin_project, origin_ref, COALESCE(meeting_key, '') AS meeting_key, "
            "COALESCE(speaker_label, '') AS speaker_label, COALESCE(review, '') AS review, COALESCE(phrase, '') AS phrase, "
            f"COALESCE(clip_file, '') AS clip_file, CASE WHEN {_ZHDYOT} THEN 1 ELSE 0 END AS zhdyot FROM voice_sample "
            "WHERE origin_project = ? AND COALESCE(speaker_label, '') = ? "
            "AND (COALESCE(meeting_key, '') = ? OR (COALESCE(meeting_key, '') = '' AND origin_ref = ?)) ORDER BY id",
            (project, label or "", str(meeting_key or ""), str(origin_ref or ""))).fetchall()
    finally:
        con.close()
    folder = papka(base_path)

    def material(row) -> bool:
        return bool(row["phrase"].strip()) or (bool(row["clip_file"])
                                               and not proverit_otryvok(folder / Path(row["clip_file"]).name))

    for vid, podhodit in (("proverka", lambda r: r["zhdyot"] and material(r)), ("resheno", lambda r: r["review"] == AUTO)):
        row = next((r for r in rows if podhodit(r)), None)
        if row is not None:
            return {"vid": vid, "klyuch": klyuch_klastera(*_klyuch(row))}
    return {"vid": "", "klyuch": ""}


# ------------------------------------------------------------------------------------------ отрывки

def put_otryvka(base_path, sample_id: int) -> Path | None:
    """Файл отрывка строки, ждущей разбора; None — нет строки, решена, отрывка нет. Имя файла — только из базы."""
    con = _connect(base_path)
    try:
        row = con.execute(f"SELECT COALESCE(clip_file, '') FROM voice_sample WHERE id = ? AND {_ZHDYOT}",
                          (int(sample_id),)).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return None
    path = papka(base_path) / Path(row[0]).name
    return path if not proverit_otryvok(path) else None   # пустой или битый файл не отдаётся (25.10.2026)


def pochemu_net_otryvka(base_path, sample_id: int) -> str:
    """Почему отрывок не отдаётся — словами для ответа 404."""
    con = _connect(base_path)
    try:
        row = con.execute("SELECT COALESCE(review, ''), COALESCE(clip_file, '') FROM voice_sample WHERE id = ?",
                          (int(sample_id),)).fetchone()
    finally:
        con.close()
    if row is None:
        return "Отрывка нет: такого отпечатка в базе нет."
    if row[0] not in ("", RULE_NO):
        return "Отрывка нет: по отпечатку уже есть решение, отрывок удалён."
    if not row[1]:
        return "Отрывка нет: не вырезан при распознавании или удалён по сроку хранения."
    beda = proverit_otryvok(papka(base_path) / Path(row[1]).name)
    return f"Отрывок не отдаётся: {beda}." if beda else "Отрывок есть."


def pochistit_starye(base_path, dney: int | None = None) -> int:
    """Отрывки, ждущие решения дольше `dney` (по умолчанию `VOICE_REVIEW_CLIP_DAYS`), удаляются: голос не хранится
    бессрочно, даже если разбор не дошёл. Строка остаётся на разбор — с текстом и временем, без звука."""
    dney = nastroyki()["dney"] if dney is None else int(dney)
    folder = papka(base_path)
    if not folder.is_dir():
        return 0
    granica = (datetime.now() - timedelta(days=dney)).timestamp()
    starye = [p for p in folder.glob("otryvok_*.wav") if p.stat().st_mtime < granica]
    if not starye:
        return 0
    udaleno = sum(_udalit(p) for p in starye)
    try:
        con = _connect(base_path)
    except voice_rule.BazaNeTa:
        return udaleno
    try:
        con.executemany("UPDATE voice_sample SET clip_file = '' WHERE clip_file = ?", [(p.name,) for p in starye])
        con.commit()
    finally:
        con.close()
    return udaleno

