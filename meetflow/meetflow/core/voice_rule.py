# -*- coding: utf-8 -*-
"""Опознание говорящего по базе голосов: правило 0,65 / 0,10 (решение владельца 17.10.26 после замера).

Общий модуль ERP и Планёрки — файлы-близнецы, обязаны совпадать до байта (`proverka_zerkalnosti_pravok.py`).
Приложения он не знает: путь к базе, «Команду», папку загрузок и карточки передаёт вызывающий.

Правило — то, что владелица проверила на странице голосов. Говорящий (кластер окон разбора по голосам, метка
расшифровки «Говорящий N» / «SPEAKER_NN») получает ФИО, только если косинус центра его окон к центру
подтверждённых отпечатков человека не ниже `POROG` (0,65) И отрыв от второго кандидата не ниже `OTRYV` (0,10).
Центр — среднее нормированных векторов, снова нормированное; у человека — по всем его подтверждённым отпечаткам.

Замер 17.10.26 на шести встречах (`golos1610/zamer/itog_1710.md`, правда — 197 отрывков, подтверждённых на слух):
это правило дало 141 верно / 0 неверно, охват 72 %, исполнитель «я» 59 / 0. Прежнее правило продукта (отпечаток на
кусок, среднее трёх лучших ≥ 0,50) — 85 / 5, «я» 37 / 4. Ошибка этого правила — на кластер целиком, поэтому порог
не ниже 0,65 и отрыв не ниже 0,10 менять только по новому замеру.

Подсказка (решение 2). Близко, но порога или отрыва нет — ФИО не ставится, говорящий остаётся меткой, а оператору
идёт карточка «вероятно, Иванов Пётр (не подтверждено)». Нижняя граница подсказки — `PODSKAZKA` (0,55), выбрана по
`itog_1710.json` (кластеры с правдой, не прошедшие правило): при косинусе ≥ 0,55 кандидат верен у 12 из 18
кластеров (2 из 3), ниже 0,55 — у 2 из 6 (1 из 3). Ниже границы подсказка чаще ошибается, чем помогает, и карточки
не будет — говорящий остаётся «Говорящий N», как раньше.

Эталоны — только подтверждённые люди и отпечатки, привязанные не кодом: строки проектов из `CODE_LINKED_PROJECTS`
(ERP до 16.10.26 привязывал куски сам по одиночному совпадению) в эталон не идут. Модель отпечатка — та же, что у
базы; строки другой модели не смешиваются молча.

База не та — понятная ошибка `BazaNeTa`, а не «никого не узнали»: путь не задан, файла нет, это не база голосов,
подтверждённых людей нет, отпечатки сняты другой моделью или разной длины.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

POROG = 0.65          # косинус центра говорящего к центру человека — ФИО ставится (решение владельца 17.10.26)
OTRYV = 0.10          # отрыв от второго кандидата
PODSKAZKA = 0.55      # нижняя граница подсказки «вероятно, …» (по itog_1710.json, см. выше)
MIN_SEK = 10.0        # меньше 10 с речи у говорящего — только подсказка: центр по короткому куску ненадёжен (17.10.26)
MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
CODE_LINKED_PROJECTS = ("erp",)
# Эталон человека — только отпечатки, подтверждённые на слух (и, когда появится, ответом оператора «это он»).
# Привязки по метке выгрузки ВКС (верна ~59 %) и привязки кодом ERP в эталон не идут: иначе чистая база «на слух»
# со временем загрязнится (решение владелицы 17.10.26, вариант 1). Метки ВКС по-прежнему видны в расшифровке.
ETALON_ORIGINS = ("na_sluh", "operator")
# Решения страницы «Разбор голосов» (`voice_review`, задание владелицы 21.10.2026): «это он» и «другой человек» — ответ
# оператора «это он», отпечаток идёт в эталон, из какой бы системы он ни пришёл; «не он» и «шум» в эталон не идут никогда.
RAZBOR_ETALON = ("yes", "other")
RAZBOR_NE_ETALON = ("no", "noise")
FOLDER = "golos_opoznanie"            # папка в загрузках продукта: что опознано на встрече (без звука и векторов)
CARD_FIELD = "voice_hint"             # карточка оператору «голос похож — не подтверждено»
CARD_SOURCE = "voice_hint:"           # источник карточки: «voice_hint:<встреча>:<метка>»

CONFIRMED, HINT, NONE = "confirmed", "hint", "none"


class BazaNeTa(RuntimeError):
    """База голосов не годится для опознания — причина словами, чтобы её увидел администратор."""


class NastroykaNeTa(ValueError):
    """Настройка правила задана неверно."""


# ------------------------------------------------------------------------------------------ настройки

def _number(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip().replace(",", ".")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise NastroykaNeTa(f"настройка {name} = «{raw}» — не число; правило опознания не применено") from exc
    if not 0.0 < value < 1.0:
        raise NastroykaNeTa(f"настройка {name} = {value} — должна быть больше 0 и меньше 1; правило не применено")
    return value


def nastroyki() -> dict[str, float]:
    """Порог, отрыв и нижняя граница подсказки: переменные VOICE_RULE_POROG / VOICE_RULE_OTRYV / VOICE_RULE_PODSKAZKA,
    по умолчанию 0,65 / 0,10 / 0,55. Читаются при каждом опознании — перезапуск не нужен."""
    porog = _number("VOICE_RULE_POROG", POROG)
    otryv = _number("VOICE_RULE_OTRYV", OTRYV)
    podskazka = _number("VOICE_RULE_PODSKAZKA", PODSKAZKA)
    if podskazka > porog:
        raise NastroykaNeTa(f"нижняя граница подсказки {podskazka} выше порога {porog}; правило не применено")
    raw = (os.environ.get("VOICE_RULE_MIN_SEK") or "").strip().replace(",", ".")
    try:
        min_sek = float(raw) if raw else MIN_SEK
    except ValueError as exc:
        raise NastroykaNeTa(f"настройка VOICE_RULE_MIN_SEK = «{raw}» — не число; правило опознания не применено") from exc
    if not 0.0 <= min_sek <= 600.0:
        raise NastroykaNeTa(f"настройка VOICE_RULE_MIN_SEK = {min_sek} — должна быть от 0 до 600 с; правило не применено")
    return {"porog": porog, "otryv": otryv, "podskazka": podskazka, "min_sek": min_sek}


# ------------------------------------------------------------------------------------------ векторы

def _unit(vector) -> list[float]:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values))
    if not norm or math.isnan(norm):
        return []
    return [x / norm for x in values]


def centr(vectors) -> list[float]:
    """Центр: среднее нормированных векторов, снова нормированное (как на странице голосов и в замере)."""
    units = [u for u in (_unit(v) for v in vectors) if u]
    if not units:
        return []
    width = len(units[0])
    if any(len(u) != width for u in units):
        raise BazaNeTa("отпечатки разной длины в одном наборе — сняты разными моделями; опознание не выполнено")
    mean = [sum(u[i] for u in units) / len(units) for i in range(width)]
    return _unit(mean)


def _cos(one: list[float], other: list[float]) -> float:
    if not one or not other or len(one) != len(other):
        return 0.0
    return sum(a * b for a, b in zip(one, other))


def _unpack(blob: bytes) -> list[float]:
    import struct

    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


# ------------------------------------------------------------------------------------------ база

def etalony(path) -> tuple[dict[str, list[float]], dict]:
    """Центры подтверждённых людей из базы голосов — {ФИО: центр} и сводка {lyudey, otpechatkov, path}.

    База открывается только на чтение. Не та база — `BazaNeTa` со словами, что не так."""
    if path is None or not str(path).strip():
        raise BazaNeTa("не задан VOICE_BASE_PATH — путь к файлу базы голосов; говорящие остаются метками")
    path = Path(str(path)).expanduser()
    if path.is_dir():
        raise BazaNeTa(f"в VOICE_BASE_PATH указана папка, а нужен файл базы голосов: {path}")
    if not path.is_file() or path.stat().st_size == 0:
        raise BazaNeTa(f"файла базы голосов по пути VOICE_BASE_PATH нет: {path}")
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=15)
    except sqlite3.Error as exc:
        raise BazaNeTa(f"файл по пути VOICE_BASE_PATH не открывается как база: {exc}") from exc
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"voice_person", "voice_sample"} <= tables:
            raise BazaNeTa("файл по пути VOICE_BASE_PATH — не база голосов: нет таблиц voice_person и voice_sample")
        columns = {row[1] for row in con.execute("PRAGMA table_info(voice_sample)")}
        model_sql = "COALESCE(s.embedding_model, '')" if "embedding_model" in columns else "''"
        review_sql = "COALESCE(s.review, '')" if "review" in columns else "''"
        rows = con.execute(
            f"SELECT p.full_name, s.embedding, {model_sql}, COALESCE(s.origin_project, ''), {review_sql} "
            "FROM voice_sample s JOIN voice_person p ON p.id = s.person_id WHERE p.confirmed = 1").fetchall()
    except sqlite3.DatabaseError as exc:
        raise BazaNeTa(f"база голосов не читается: {exc}") from exc
    finally:
        con.close()
    by_person: dict[str, list[list[float]]] = {}
    other_model = 0
    not_etalon = 0
    for name, blob, model, project, review in rows:
        if review in RAZBOR_NE_ETALON or (review not in RAZBOR_ETALON
                                          and (project in CODE_LINKED_PROJECTS or project not in ETALON_ORIGINS)):
            not_etalon += 1
            continue
        if model not in ("", MODEL):
            other_model += 1
            continue
        by_person.setdefault((name or "").strip(), []).append(_unpack(blob))
    if not by_person:
        if other_model:
            raise BazaNeTa(f"все отпечатки подтверждённых людей сняты другой моделью ({other_model} шт.), а не {MODEL}; "
                           "сравнивать их нельзя — опознание не выполнено")
        if not_etalon:
            raise BazaNeTa(f"в базе голосов нет отпечатков, подтверждённых на слух ({not_etalon} шт. других — по метке "
                           "ВКС или кодом, в эталон они не идут); опознавать не по чему — нужна база «на слух»")
        raise BazaNeTa("в базе голосов нет подтверждённых людей с отпечатками — опознавать не по чему")
    centry = {name: centr(vectors) for name, vectors in by_person.items()}
    widths = {len(c) for c in centry.values()}
    if len(widths) != 1:
        raise BazaNeTa("отпечатки людей в базе разной длины — сняты разными моделями; опознание не выполнено")
    return centry, {"lyudey": len(centry), "otpechatkov": sum(len(v) for v in by_person.values()), "path": str(path)}


# ------------------------------------------------------------------------------------------ правило

def reshit(center: list[float], centry: dict[str, list[float]], porog: float = POROG, otryv: float = OTRYV,
           podskazka: float = PODSKAZKA) -> dict:
    """Решение по одному говорящему: {status, name, cosine, gap, second, second_cosine}.

    `confirmed` — косинус ≥ порога и отрыв ≥ нужного; `hint` — не прошло, но косинус ≥ нижней границы подсказки;
    `none` — ниже. Длина центра не та, что у эталонов, — `BazaNeTa` (разные модели)."""
    if center and centry and len(center) != len(next(iter(centry.values()))):
        raise BazaNeTa("отпечаток говорящего и эталоны базы разной длины — сняты разными моделями")
    ranked = sorted(((_cos(center, c), name) for name, c in centry.items()), key=lambda x: (-x[0], x[1]))
    if not ranked or not center:
        return {"status": NONE, "name": "", "cosine": 0.0, "gap": 0.0, "second": "", "second_cosine": 0.0}
    cosine, name = ranked[0]
    second_cosine, second = ranked[1] if len(ranked) > 1 else (0.0, "")
    gap = cosine - second_cosine
    # Сравнение с допуском в 1e-9: 0,65 и 0,10 — границы включительно, а вычитание чисел с плавающей точкой даёт
    # 0,0999999… там, где отрыв ровно 0,10.
    if cosine >= porog - 1e-9 and gap >= otryv - 1e-9:
        status = CONFIRMED
    elif cosine >= podskazka - 1e-9:
        status = HINT
    else:
        status = NONE
    return {"status": status, "name": name, "cosine": round(cosine, 3), "gap": round(gap, 3),
            "second": second, "second_cosine": round(second_cosine, 3)}


def opoznat(samples: list[dict], centry: dict[str, list[float]], in_team=None, settings: dict | None = None) -> dict:
    """{метка: решение} для всех говорящих записи. `samples` — окна с `speaker` и `embedding`.

    `in_team(ФИО) -> ФИО «Команды» или None`: ФИО ставится только человеку из «Команды» этого продукта (как и раньше);
    прошёл порог, но в «Команде» его нет — подсказка с причиной, а не подстановка."""
    settings = settings or nastroyki()
    by_speaker: dict[str, list] = {}
    seconds: dict[str, float | None] = {}
    for sample in samples:
        if sample.get("embedding") and sample.get("speaker"):
            speaker = sample["speaker"]
            by_speaker.setdefault(speaker, []).append(sample["embedding"])
            try:
                length = max(0.0, float(sample["end"]) - float(sample["start"]))
            except (KeyError, TypeError, ValueError):
                length = None             # время окна неизвестно — минимум речи не проверяется
            if length is None or seconds.get(speaker, 0.0) is None:
                seconds[speaker] = None
            else:
                seconds[speaker] = seconds.get(speaker, 0.0) + length
    min_sek = float(settings.get("min_sek", MIN_SEK))
    out = {}
    for speaker, vectors in by_speaker.items():
        found = reshit(centr(vectors), centry, settings["porog"], settings["otryv"], settings["podskazka"])
        found["windows"] = len(vectors)
        found["seconds"] = None if seconds.get(speaker) is None else round(seconds[speaker], 1)
        found["base_name"] = found["name"]
        found["reason"] = ""
        if found["status"] == CONFIRMED and found["seconds"] is not None and found["seconds"] < min_sek:
            found["status"] = HINT
            found["reason"] = f"мало речи: {found['seconds']:.0f} с, нужно не меньше {min_sek:.0f} с"
        if found["status"] != NONE and in_team is not None:
            team_name = in_team(found["name"])
            if team_name:
                found["name"] = team_name
            elif found["status"] == CONFIRMED:
                found["status"] = HINT
                found["reason"] = "голос узнан, но этого человека нет в «Команде»"
        out[speaker] = found
    return out


# ------------------------------------------------------------------------------------------ тексты

def podskazka_tekst(found: dict) -> str:
    """«вероятно, Иванов Пётр (не подтверждено)» — как просила владелица (решение 2)."""
    return f"вероятно, {found.get('name') or found.get('base_name')} (не подтверждено)"


def _num(x) -> str:
    return f"{float(x):.2f}".replace(".", ",")


def kartochka(label: str, found: dict, meeting_date: str, settings: dict | None = None, akkaunt: str = "") -> dict:
    """Текст карточки подсказки: current — метка, proposed — ФИО, evidence — почему не подставлено. `akkaunt` — аккаунт
    выгрузки ВКС на репликах этого голоса (`speaker_names.Сверка.предложения`): только подсказка, кандидат — по голосу
    (решение владелицы 25.10.2026)."""
    settings = settings or nastroyki()
    why = found.get("reason") or (
        f"близость {_num(found['cosine'])} при пороге {_num(settings['porog'])}, отрыв от второго кандидата"
        + (f" ({found['second']})" if found.get("second") else "")
        + f" {_num(found['gap'])} при нужном {_num(settings['otryv'])}")
    return {
        "current_value": label,
        "proposed_value": found.get("name") or found.get("base_name"),
        "evidence_quote": (
            f"Голос «{label}» на встрече {meeting_date}: {podskazka_tekst(found)} — {why}. В расшифровке остался "
            f"«{label}». Если это он, подтвердите: ФИО появится в карточках этой встречи вместо «{label}»; "
            "расшифровка и протокол задним числом не переписываются.") + _akkaunt_tekst(akkaunt),
    }


# Аккаунт ВКС — подсказка, не имя (решение владелицы 25.10.2026, «имя сначала по голосу»): в выгрузке ВКС у реплики имя
# аккаунта, а с чужого аккаунта может говорить коллега, с одного — несколько человек.
AKKAUNT_V_KARTOCHKE = " Подсказка: на репликах этого голоса в выгрузке ВКС — аккаунт ВКС: "


def _akkaunt_tekst(akkaunt: str) -> str:
    akkaunt = " ".join((akkaunt or "").split())
    return f"{AKKAUNT_V_KARTOCHKE}{akkaunt} (аккаунт — не основание: с него мог говорить другой человек)." if akkaunt else ""


def s_akkauntom(evidence: str | None, akkaunt: str) -> str:
    """Текст карточки серой зоны с подсказкой аккаунта ВКС; уже дописана или аккаунта нет — как был."""
    evidence = evidence or ""
    if not (akkaunt or "").strip() or AKKAUNT_V_KARTOCHKE in evidence:
        return evidence
    return evidence + _akkaunt_tekst(akkaunt)


# ------------------------------------------------------------------------------------------ запись на встречу

def _file(uploads_root, meeting_id: int) -> Path:
    return Path(uploads_root) / FOLDER / f"{int(meeting_id)}.json"


def zapisat(uploads_root, meeting_id: int, result: dict, settings: dict, base: dict) -> Path:
    """Что опознано на встрече — без звука и векторов: метка, решение, числа. Читают карточки и страж исполнителя.
    Ответы оператора по прежнему файлу этой встречи сохраняются, если метка и кандидат те же."""
    prev_data = prochitat(uploads_root, meeting_id)
    prev = prev_data.get("speakers", {})
    speakers = {}
    for label, found in result.items():
        entry = dict(found)
        old = prev.get(label) or {}
        if old.get("operator") and old.get("name") == entry.get("name"):
            entry["operator"] = old["operator"]
        speakers[label] = entry
    data = {"meeting_id": int(meeting_id), "at": datetime.utcnow().isoformat(timespec="seconds"),
            "rule": settings, "base": {"lyudey": base.get("lyudey"), "otpechatkov": base.get("otpechatkov")},
            "speakers": speakers}
    if prev_data.get("akkaunty"):
        data["akkaunty"] = prev_data["akkaunty"]       # аккаунты ВКС пишет сборка (25.10.2026) — повторное опознание их не стирает
    path = _file(uploads_root, meeting_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def zapisat_akkaunty(uploads_root, meeting_id: int, akkaunty: dict) -> Path:
    """Аккаунты ВКС у говорящих встречи (`speaker_names.Сверка.как_словарь`): {"predlozheniya": {метка: аккаунт},
    "obshchie": {аккаунт: [метки]}, "raskhozhdeniya": [[аккаунт, голос]]}. Пишет сборка протокола; читает «Разбор голосов»
    (решение владелицы 25.10.2026). Файла опознания ещё нет — заводится с пустым списком говорящих."""
    data = prochitat(uploads_root, meeting_id) or {"meeting_id": int(meeting_id), "speakers": {}}
    data["akkaunty"] = {"predlozheniya": dict(akkaunty.get("predlozheniya") or {}),
                        "obshchie": {k: list(v) for k, v in (akkaunty.get("obshchie") or {}).items()},
                        "raskhozhdeniya": [list(x) for x in akkaunty.get("raskhozhdeniya") or []],
                        "at": datetime.utcnow().isoformat(timespec="seconds")}
    path = _file(uploads_root, meeting_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def akkaunt_klastera(uploads_root, meeting_id, label: str) -> dict:
    """Аккаунт ВКС у говорящего встречи для «Разбора голосов»: {"akkaunt": предложение «аккаунт ВКС: …?» или "",
    "obshchiy": аккаунт, с которого говорили несколько голосов (тогда предложения нет), "golosov": сколько}."""
    out = {"akkaunt": "", "obshchiy": "", "golosov": 0}
    if meeting_id is None or not str(meeting_id).strip().isdigit():
        return out
    data = (prochitat(uploads_root, int(meeting_id)).get("akkaunty") or {})
    for akkaunt, metki in (data.get("obshchie") or {}).items():
        if label in (metki or []):
            return {"akkaunt": "", "obshchiy": akkaunt, "golosov": len(metki)}
    out["akkaunt"] = (data.get("predlozheniya") or {}).get(label) or ""
    return out


def prochitat(uploads_root, meeting_id) -> dict:
    if meeting_id is None:
        return {}
    try:
        path = _file(uploads_root, meeting_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def podtverzhdennye(uploads_root, meeting_id) -> dict[str, str]:
    """{метка: ФИО} — прошедшие правило и подтверждённые оператором по карточке подсказки."""
    out = {}
    for label, found in (prochitat(uploads_root, meeting_id).get("speakers") or {}).items():
        answer = (found.get("operator") or {}).get("answer")
        if (found.get("status") == CONFIRMED and answer != "no") or answer == "yes":
            # ответ разбора голосов «другой человек» несёт своё ФИО (задание владелицы 21.10.2026)
            out[label] = (found.get("operator") or {}).get("name") or found.get("name") or ""
    return {k: v for k, v in out.items() if v}


def podskazki(uploads_root, meeting_id) -> dict[str, str]:
    """{метка: ФИО} — подсказки без ответа оператора."""
    return {label: found.get("name") or ""
            for label, found in (prochitat(uploads_root, meeting_id).get("speakers") or {}).items()
            if found.get("status") == HINT and not found.get("operator") and found.get("name")}


def otvet_operatora(uploads_root, meeting_id: int, label: str, yes: bool, by: str = "", name: str = "") -> bool:
    """Ответ по карточке подсказки: «да, это он» / «нет». False — записи о встрече или метки нет.

    `name` — ФИО из «Команды», если по разбору голосов это другой человек, чем в подсказке (21.10.2026)."""
    data = prochitat(uploads_root, meeting_id)
    found = (data.get("speakers") or {}).get(label)
    if not found:
        return False
    found["operator"] = {"answer": "yes" if yes else "no", "by": by[:200],
                         "at": datetime.utcnow().isoformat(timespec="seconds")}
    if yes and (name or "").strip():
        found["operator"]["name"] = name.strip()[:200]
    _file(uploads_root, meeting_id).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


# ------------------------------------------------------------------------------------------ карточки

def istochnik(meeting_id: int, label: str) -> str:
    return f"{CARD_SOURCE}{int(meeting_id)}:{label}"


def razobrat_istochnik(source: str) -> tuple[int | None, str]:
    """«voice_hint:12:Говорящий 3» → (12, «Говорящий 3»)."""
    if not (source or "").startswith(CARD_SOURCE):
        return None, ""
    rest = source[len(CARD_SOURCE):]
    number, _, label = rest.partition(":")
    return (int(number), label) if number.isdigit() else (None, "")


def vstrecha_kartochki(conflict) -> int | None:
    """Встреча карточки: из источника подсказки, из payload (ERP) или по задаче карточки."""
    number, _ = razobrat_istochnik(getattr(conflict, "source", "") or "")
    if number is not None:
        return number
    payload = getattr(conflict, "payload", None) or {}
    if isinstance(payload, dict) and payload.get("meeting_id"):
        try:
            return int(payload["meeting_id"])
        except (TypeError, ValueError):
            pass
    task = getattr(conflict, "task", None)
    return getattr(task, "source_meeting_id", None) if task is not None else None


# Подсказка голоса в MeetFlow не заводит карточку «Конфликтов»: правило сомнительных задач и подписей живёт
# отдельно (`cards`), а опознание пишется в файл встречи. Функция-заглушка оставлена для общей копии правила:
# вызывающий ERP передаёт свою проверку «метка где-то стоит».
ПРИЧИНА_МЕТКА_НЕ_НУЖНА = "метка не нужна ни в одной карточке, задаче или договорённости встречи"
_ПОЛЯ_ЗАДАЧИ = ("description", "responsible_text", "source_quote", "last_comment")
_ПОЛЯ_ДОГОВОРЁННОСТИ = ("text", "quote", "decided_by", "agreed_by", "proposed_by")
_ПОЛЯ_КАРТОЧКИ = ("current_value", "proposed_value", "evidence_quote")


def метка_не_нужна(db, meeting_id: int | None, label: str) -> bool:
    """В MeetFlow проверки по карточкам нет: метка нужна всегда, подсказка не отбрасывается."""
    return False


# Первое лицо — та же запись, что `draft_checks._FIRST_PERSON_RE` Планёрки (равенство держит тест): человек в строке
# со своим ФИО по голосу сам берёт работу — «я подготовлю», «уточню», «займусь», «подготовим».
FIRST_PERSON_RE = re.compile(
    r"(?:^|[^а-яё])(?:я|мы)(?:[^а-яё]|$)"          # «я направлю», «мы сделаем»
    r"|[а-яё]{4,}(?:ю|усь|юсь)(?:[^а-яё]|$)"       # «уточню», «назначаю», «займусь»
    r"|[а-яё]{5,}(?:аем|яем|ием|уем|д[её]м|им|ем)(?:[^а-яё]|$)",  # «раскатаем», «подготовим»
    re.IGNORECASE)
NOT_FIRST_PERSON = {"нужно", "надо", "необходимо", "можно", "должно", "время", "решение", "значение"}


def first_person(text: str) -> bool:
    """Человек говорит о себе (тем же разбором слов, что у Планёрки)."""
    words = " ".join(w for w in (text or "").lower().replace("ё", "е").split() if w not in NOT_FIRST_PERSON)
    return bool(FIRST_PERSON_RE.search(words))


_LABEL = re.compile(r"(?<![\w(])(?:[Гг]оворящ(?:ий|его|ему|им|ем)\s+(\d{1,3})|SPEAKER_(\d{1,3}))(?![\w)])")


def _key(match: re.Match) -> str:
    return f"Говорящий {int(match.group(1))}" if match.group(1) else f"SPEAKER_{match.group(2)}"


def podpisat_veroyatnyh(text: str | None, hints: dict[str, str] | None) -> str | None:
    """«Говорящий 3» → «Говорящий 3 — вероятно, Иванов Пётр (не подтверждено)» — только при показе карточки;
    метка остаётся, карточка по-прежнему ждёт опознания."""
    if not text or not hints:
        return text

    def _sub(m: re.Match) -> str:
        name = (hints.get(_key(m)) or "").strip()
        tail = text[m.end():m.end() + 12]
        if not name or tail.startswith(" — вероятно"):
            return m.group(0)
        return f"{m.group(0)} — вероятно, {name} (не подтверждено)"
    return _LABEL.sub(_sub, text)
