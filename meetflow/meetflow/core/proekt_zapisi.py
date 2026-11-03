# -*- coding: utf-8 -*-
"""Проект записи из папки-приёмника и перенос встречи в другой проект (27.10.2026).

Специфика MeetFlow — многопроектность и папки по проектам; в ERP один проект системы, поэтому образца нет. Повод —
протокол MeetFlow 26.10.2026: в MeetFlow один проект, и запись встречи Проекта ERP 15.10, положенная в корень общей папки
«Встречи по всем проектам», ушла в него вместе со встречей 26.10 из подпапки «Адресный учёт на складе». Таблица задач 26.10
показала 13 открытых задач 15.10: две разные встречи в одном протоколе.

Правило (задание владелицы 27.10.2026):
  * файл в подпапке проекта или подпроекта — этот проект (подпроект): имя подпапки сверяется со справочником проектов —
    названием и вариантами, е = ё, без регистра, по основам (пять букв), служебные слова «проект», «встречи» не в счёт;
    берётся самая глубокая подпапка, которая узналась, — подпапка подпроекта внутри папки проекта даёт подпроект;
  * файл в корне общей папки — проект по названию в имени файла теми же правилами;
  * не определился (не назван или названо два проекта) — встреча молча единственному проекту не приписывается: она
    заводится с пометкой «проект не определён», оператору карточка «Проект записи не определён» с выбором проекта,
    сборка протокола идёт сразу в проекте папки (решение владелицы 28.10.2026; было — ждала выбора), выбор переносит встречу и пересобирает. Распознавание и голоса идут сразу: запись после распознавания удаляется.
  * у папки самого проекта (не общей) файл в корне — этот проект, как было.

Общая ли папка: настройка проекта `watch_folder_shared` (да/нет); не задана — по названию папки («по всем проектам»,
«все проекты», «общая»). Подпапка, назначенная приёмником другого проекта, обходится тем проектом, а не владельцем общей.

Перенос встречи — `перенести_встречу`: встреча и всё, что к ней привязано (задачи, поставленные на ней, единицы,
карточки, «Возможные поручения», строки очереди сборок), переходят в другой проект; каждой задаче — строка истории,
решению — запись в журнале решений. Протокол не переписывается: он документ, его пересобирает человек или очередь.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

КАРТОЧКА = "project_undetermined"
ЗАГОЛОВОК = "Проект записи не определён"
НАСТРОЙКА_ОБЩАЯ = "watch_folder_shared"
_ОБЩАЯ_ПО_ИМЕНИ = ("повсемпроектам", "всепроекты", "всехпроектов", "общая", "общие")
_СЛУЖЕБНЫЕ = {"проект", "проекта", "проекту", "проекты", "проектов", "встреча", "встречи", "встреч", "планерка",
              "планерки", "совещание", "совещания", "запись", "записи", "по", "на", "и", "в", "во", "с", "со", "к",
              "для", "из", "от", "о", "об", "все", "всем", "всех"}


def _н(текст: str | None) -> str:
    return (текст or "").lower().replace("ё", "е")


def _основы(текст: str | None) -> set[str]:
    """Основы значимых слов: пять первых букв, без чисел (дата и время в имени файла) и служебных слов."""
    слова = re.findall(r"[a-zа-я0-9]+", _н(текст))
    return {w[:5] for w in слова if not w.isdigit() and w not in _СЛУЖЕБНЫЕ and len(w) >= 2}


def _варианты(aliases) -> list[str]:
    if isinstance(aliases, str):
        try:
            aliases = json.loads(aliases or "[]")
        except ValueError:
            aliases = re.split(r"[;,\n]", aliases)
    return [str(a).strip() for a in (aliases or []) if str(a).strip()]


ОБЩИЕ = "Общие встречи"


def общие_встречи(store, theme_id: str = "") -> int:
    """Номер служебного проекта «Общие встречи» (Доработка 2, 28.10.2026): встречи без проекта лежат в нём, а не в пустом
    значении — пустое значение у MeetFlow означает «Все проекты». Нет — заводится; переименовать, убрать в архив и удалить
    его нельзя, в узнавании проекта записи он не участвует."""
    from .store import now
    r = store.q("SELECT id FROM projects WHERE COALESCE(general, 0)=1 ORDER BY id LIMIT 1")
    if r:
        return r[0]["id"]
    if not theme_id:
        t = store.q("SELECT theme FROM projects WHERE COALESCE(theme, '')<>'' ORDER BY id LIMIT 1")
        theme_id = t[0]["theme"] if t else "_default"
    return store.insert("projects", name=ОБЩИЕ, theme=theme_id, aliases="[]", active=1, archived=0, general=1,
                        created_at=now())


def проекты(store) -> list[dict]:
    """Действующие проекты и подпроекты справочника: номер, название, варианты, надпроект. «Общие встречи» и удалённые
    проекты в узнавании не участвуют."""
    return [{"id": r["id"], "name": r["name"] or "", "aliases": _варианты(r.get("aliases")), "parent_id": r.get("parent_id")}
            for r in store.q("SELECT id, name, aliases, parent_id FROM projects "
                             "WHERE COALESCE(archived, 0) = 0 AND COALESCE(active, 1) = 1 AND COALESCE(general, 0) = 0 "
                             "AND COALESCE(deleted, 0) = 0 ORDER BY id")]


# Узнавание по содержанию (Доработка 2, 28.10.2026; исследование отрасли: Gong, RingDNA, Syntex, Paperless-ngx — решает
# отрыв лучшего кандидата от второго, а не абсолютное число; ошибочная раскладка хуже, чем раскладка в «Общие встречи»).
# Считаются строки расшифровки, где названы проект или его вариант: все значимые основы написания есть в строке.
ПОРОГ_УПОМИНАНИЙ = 3          # меньше трёх строк с названием — не узнан
ОТРЫВ = 2.0                   # лучший кандидат должен быть назван хотя бы вдвое чаще второго


def по_содержанию(текст: str, справочник: list[dict]) -> dict:
    """{"project_id": номер или None, "how": причина строкой, "counts": {номер: строк}}. Подпроект и его надпроект — не
    соперники: строки подпроекта засчитываются и надпроекту, а выбирается подпроект, если он сам набрал порог."""
    строки = [_основы(x) for x in (текст or "").splitlines()]
    строки = [x for x in строки if x]
    счёт: dict[int, int] = {}
    for п in справочник:
        написания = [_основы(w) for w in [п["name"]] + list(п["aliases"])]
        написания = [w for w in написания if w]
        n = sum(1 for стр in строки if any(w <= стр for w in написания))
        if n:
            счёт[п["id"]] = n
    if not счёт:
        return {"project_id": None, "how": "в общих встречах: проект не назван ни в имени файла, ни в записи", "counts": {}}
    имя = {п["id"]: п["name"] for п in справочник}
    родитель = {п["id"]: п.get("parent_id") for п in справочник}
    верх = {}
    for pid, n in счёт.items():                      # соперничают проекты верхнего уровня: подпроект — часть надпроекта
        корень = pid
        while родитель.get(корень):
            корень = родитель[корень]
        верх[корень] = max(верх.get(корень, 0), n)
    ряд = sorted(верх.items(), key=lambda x: -x[1])
    (лучший, n1), n2 = ряд[0], (ряд[1][1] if len(ряд) > 1 else 0)
    второй = f"; второй — «{имя[ряд[1][0]]}», упоминаний {n2}" if len(ряд) > 1 else ""
    if n1 < ПОРОГ_УПОМИНАНИЙ:
        return {"project_id": None, "counts": счёт,
                "how": f"в общих встречах: «{имя[лучший]}» назван мало, упоминаний {n1}{второй}"}
    if n2 and n1 < ОТРЫВ * n2:
        return {"project_id": None, "counts": счёт,
                "how": f"в общих встречах: два проекта близко — «{имя[лучший]}», упоминаний {n1}{второй}"}
    точнее = [pid for pid, n in счёт.items() if pid != лучший and n >= ПОРОГ_УПОМИНАНИЙ and
              лучший in _предки(pid, родитель)]
    выбран = max(точнее, key=lambda pid: счёт[pid]) if точнее else лучший
    return {"project_id": выбран, "counts": счёт,
            "how": f"по содержанию записи: «{имя[выбран]}», упоминаний {счёт.get(выбран, n1)}{второй}"}


def корень(справочник: list[dict], pid: int) -> int:
    """Проект верхнего уровня для проекта или подпроекта справочника."""
    родитель = {п["id"]: п.get("parent_id") for п in справочник}
    seen = set()
    while родитель.get(pid) and pid not in seen:
        seen.add(pid)
        pid = родитель[pid]
    return pid


def _предки(pid: int, родитель: dict) -> set[int]:
    out, x = set(), родитель.get(pid)
    while x and x not in out:
        out.add(x)
        x = родитель.get(x)
    return out


def текст_встречи(store, meeting_id: int) -> str:
    return "\n".join(r["text"] or "" for r in store.q(
        "SELECT text FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind='transcript'", (meeting_id,)))


def узнать(текст: str, справочник: list[dict]) -> tuple[int | None, list[int]]:
    """Проект по тексту (имя подпапки или файла): все значимые основы названия или варианта есть в тексте. Узнался один —
    его номер; несколько — у кого совпало больше основ; поровну у разных — None и список спорных. Подпроект и его
    надпроект оба узнались (название подпроекта включает название проекта) — подпроект: он точнее."""
    есть = _основы(текст)
    if not есть:
        return None, []
    очки: dict[int, int] = {}
    for п in справочник:
        for написание in [п["name"]] + list(п["aliases"]):
            нужно = _основы(написание)
            if нужно and нужно <= есть:
                очки[п["id"]] = max(очки.get(п["id"], 0), len(нужно))
    if not очки:
        return None, []
    родители = {п["id"]: п.get("parent_id") for п in справочник}
    for pid in list(очки):          # надпроект узнанного подпроекта — не спор, а менее точный ответ
        if родители.get(pid) in очки:
            очки.pop(родители[pid], None)
    return (next(iter(очки)), []) if len(очки) == 1 else (None, sorted(очки))


def общая_папка(store, project_id: int, папка: Path) -> bool:
    if (store.get("projects", project_id) or {}).get("general"):
        return True                   # приёмник «Общих встреч» — общая папка системы (Доработка 2, 28.10.2026)
    v = store.get_setting(НАСТРОЙКА_ОБЩАЯ, project_id, None)
    if v is not None:
        return bool(v)
    имя = re.sub(r"[^a-zа-я]", "", _н(Path(папка).name))
    return any(x in имя for x in _ОБЩАЯ_ПО_ИМЕНИ)


def папки_других(store, project_id: int) -> list[Path]:
    """Приёмники других проектов — их подпапки обходит свой проект, владелец общей папки их не берёт."""
    out = []
    for r in store.q("SELECT project_id, value FROM settings WHERE key='watch_folder' AND project_id IS NOT NULL"):
        if r["project_id"] == project_id:
            continue
        try:
            v = json.loads(r["value"]) if r["value"] else None
        except ValueError:
            v = r["value"]
        if v:
            out.append(Path(str(v)))
    return out


def под_другим(путь: Path, другие: list[Path]) -> bool:
    for д in другие:
        try:
            Path(путь).resolve().relative_to(д.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def проект_файла(store, project_id: int, папка: Path, файл: Path) -> dict:
    """{"project_id": номер или None, "how": как узнан, "disputed": спорные номера}. Владелец папки — `project_id`."""
    справочник = проекты(store)
    try:
        части = Path(файл).resolve().relative_to(Path(папка).resolve()).parts
    except (ValueError, OSError):
        части = (Path(файл).name,)
    подпапки = list(части[:-1])
    спорные: list[int] = []
    for i in range(len(подпапки) - 1, -1, -1):          # самая глубокая узнанная подпапка — подпроект точнее проекта
        pid, спор = узнать(подпапки[i], справочник)
        if pid is not None:
            return {"project_id": pid, "how": f"подпапка «{подпапки[i]}»", "disputed": []}
        спорные = спорные or спор
    pid, спор = узнать(Path(файл).stem, справочник)
    if pid is not None:
        return {"project_id": pid, "how": f"название в имени файла «{Path(файл).name}»", "disputed": []}
    спорные = спорные or спор
    # Общая база компании (28.10.2026): свой справочник не узнал, а назван проект общей базы — встреча общей тематики
    # остаётся проекту папки, если он ведёт такие встречи (`obshchaya_baza.включена`); спор своих проектов — как был
    if not спорные:
        from . import obshchaya_baza
        общие = [{**п, "aliases": _варианты(п["aliases"])} for п in obshchaya_baza.проекты(store, project_id)]
        for текст in list(reversed(подпапки)) + [Path(файл).stem]:
            pid, спор = узнать(текст, общие) if общие else (None, [])
            имена = [п["name"] for п in общие if п["id"] == pid or п["id"] in спор]
            if имена:
                return {"project_id": project_id, "how": f"проект общей базы компании «{имена[0]}»", "disputed": []}
    if not подпапки and not общая_папка(store, project_id, Path(папка)):
        return {"project_id": project_id, "how": "папка проекта", "disputed": []}
    return {"project_id": None, "how": "не определён", "disputed": спорные}


def открыть_карточку(store, cards, owner_id: int, meeting_id: int, файл: str, итог: dict) -> int:
    """Карточка «Проект записи не определён»: кандидаты — проекты справочника (спорные первыми)."""
    справочник = проекты(store)
    спорные = set(итог.get("disputed") or [])
    кандидаты = sorted(справочник, key=lambda п: (п["id"] not in спорные, п["name"]))
    return cards.open(owner_id, КАРТОЧКА, f"{ЗАГОЛОВОК}: «{файл}»",
                      {"meeting_id": meeting_id, "file": файл,
                       "why": "в имени файла и подпапки не назван ни один проект справочника" if not спорные
                       else "в имени названо несколько проектов",
                       "candidates": [{"id": п["id"], "name": п["name"],
                                       "hints": ["назван в имени"] if п["id"] in спорные else []} for п in кандидаты]},
                      meeting_id)


def собрать_после_выбора(store, queue, meeting_id: int, by: str = "") -> int | None:
    """Проект выбран — сборка, которая ждала выбора, встаёт в очередь (если у встречи есть расшифровка или заметки)."""
    m = store.get("meetings", meeting_id) or {}
    есть = store.q("SELECT id FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind IN ('transcript', 'notes')",
                   (meeting_id,))
    if not есть or queue is None or m.get("project_pending"):
        return None
    return queue.enqueue(m["project_id"], meeting_id, "проект записи выбран", by=by)


def ждёт_проекта(meeting: dict | None) -> bool:
    return bool((meeting or {}).get("project_pending"))


def перенести_встречу(store, meeting_id: int, to_project_id: int, by: str = "") -> dict:
    """Встреча и её задачи, единицы, карточки, «Возможные поручения» и строки очереди — в проект `to_project_id`.
    Снимает пометку «проект не определён» и закрывает карточку выбора. Возвращает {from, to, tasks}."""
    from .store import now
    m = store.get("meetings", meeting_id)
    if not m:
        raise ValueError("Встреча не найдена.")
    цель = store.get("projects", to_project_id)
    if not цель or цель.get("archived") or цель.get("deleted"):
        raise ValueError("Проект не найден.")
    было = m["project_id"]
    задачи = store.q("SELECT id FROM tasks WHERE source_meeting_id=?", (meeting_id,))
    with store.tx():
        if было != to_project_id:
            store.update("meetings", meeting_id, project_id=to_project_id)
            for t in задачи:
                store.update("tasks", t["id"], project_id=to_project_id)
                store.insert("task_history", task_id=t["id"], old_status=None, new_status=None, source="meeting_move",
                             evidence_quote=f"Перенесена вместе со встречей в проект «{цель['name']}»",
                             changed_by=by or "администратор", at=now())
            for table in ("units", "possible_assignments"):
                store._conn.execute(f"UPDATE {table} SET project_id=? WHERE meeting_id=?", (to_project_id, meeting_id))
            store._conn.execute("UPDATE cards SET project_id=? WHERE meeting_id=? AND kind<>?",
                                (to_project_id, meeting_id, КАРТОЧКА))
            store._conn.execute("UPDATE build_queue SET project_id=? WHERE meeting_id=? AND status='queued'",
                                (to_project_id, meeting_id))
            прежний = (store.get("projects", было) or {}).get("name") or "—"
            store.insert("decisions", project_id=to_project_id,
                         what=f"Встреча {m.get('date') or ''} перенесена из проекта «{прежний}» в «{цель['name']}»",
                         decision="перенесено", why=f"кто: {by or '—'}; задач: {len(задачи)}", at=now())
        store.update("meetings", meeting_id, project_pending=0)
        for c in store.q("SELECT id FROM cards WHERE meeting_id=? AND kind=? AND status='open'", (meeting_id, КАРТОЧКА)):
            store.update("cards", c["id"], status="accepted", resolution=f"проект «{цель['name']}»", resolved_at=now())
    return {"from": было, "to": to_project_id, "tasks": len(задачи)}


# --- несколько встреч одного дня: одна тема и одни участники — один протокол (решение владелицы 03.11.2026) ---
def _норм_имя(значение: str | None) -> str:
    s = _н(значение)
    s = re.sub(r"[«»\"'*_.,:;!?()\[\]]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _люди_из_meta(store, meeting_id: int) -> set[str]:
    люди: set[str] = set()
    for s in store.q("SELECT meta FROM sources WHERE meeting_id=? AND removed_at IS NULL AND kind='transcript'",
                     (meeting_id,)):
        try:
            meta = json.loads(s["meta"] or "{}")
        except (TypeError, ValueError):
            continue
        voice = meta.get("voice_names") or {}
        if isinstance(voice, dict):
            voice = list(voice.values())
        elif not isinstance(voice, (list, tuple, set)):
            voice = []
        for имя in voice:
            n = _норм_имя(str(имя or ""))
            if n and not n.startswith("говорящ"):
                люди.add(n)
    return люди


def _люди_из_протокола(meeting: dict) -> set[str]:
    md = meeting.get("protocol_md") or ""
    m = re.search(r"(?im)^\s*#{0,3}\s*Участники\b[^\n]*\n+\s*([^\n#]+)", md)
    if not m:
        m = re.search(r"(?im)^\s*#{0,3}\s*Участники\s*:\s*([^\n#]+)", md)
    if not m:
        return set()
    return {_норм_имя(x) for x in re.split(r"[,;]", m.group(1)) if _норм_имя(x)}


def участники_встречи(store, meeting_id: int) -> set[str]:
    """Люди встречи: голоса из расшифровки; если их нет — строка «Участники» готового протокола."""
    люди = _люди_из_meta(store, meeting_id)
    if люди:
        return люди
    return _люди_из_протокола(store.get("meetings", meeting_id) or {})


def _тема_знак(meeting: dict) -> set[str]:
    topic = (meeting.get("topic") or "").strip()
    if topic:
        return _основы(topic)
    label = (meeting.get("label") or "").strip()
    label = re.sub(r"(?i)^\s*из\s+папки[- ]приёмника\s*:\s*", "", label)
    label = re.sub(r"\b\d{1,2}[._-]\d{1,2}[._-]\d{2,4}\b", " ", label)
    label = re.sub(r"\b\d{1,2}[:.]\d{2}\b", " ", label)
    label = re.sub(r"(?i)\.(m4a|mp3|wav|ogg|flac|txt|docx?)$", " ", label)
    return _основы(label)


def _та_же_тема(a: dict, b: dict) -> bool:
    ta, tb = _н((a.get("topic") or "").strip()), _н((b.get("topic") or "").strip())
    if ta and tb:
        return ta == tb
    sa, sb = _тема_знак(a), _тема_знак(b)
    if not sa or not sb:
        return False
    return sa == sb or len(sa & sb) / len(sa | sb) >= 0.8


def свести_в_одну(store, src_id: int, dst_id: int, by: str = "система") -> int:
    """Материалы и карточки src — в dst; src помечается удалённой как сведённая, dst получает историю сведения."""
    from .store import now
    src, dst = store.get("meetings", src_id), store.get("meetings", dst_id)
    if not src or not dst or src_id == dst_id:
        return dst_id
    with store.tx():
        have = {r["digest"] for r in store.q(
            "SELECT digest FROM sources WHERE meeting_id=? AND removed_at IS NULL AND digest IS NOT NULL", (dst_id,))}
        moved = same = 0
        for s in store.q("SELECT id,digest,meta FROM sources WHERE meeting_id=? AND removed_at IS NULL", (src_id,)):
            if s["digest"] and s["digest"] in have:
                store.update("sources", s["id"], removed_at=now(), removed_reason="одинаковый материал уже есть")
                same += 1
                continue
            try:
                meta = json.loads(s["meta"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            meta.update(moved_from_meeting_id=src_id, moved_from_date=(src.get("date") or "")[:10], moved_at=now())
            store.update("sources", s["id"], meeting_id=dst_id, meta=json.dumps(meta, ensure_ascii=False))
            moved += 1
        # Сборка берёт одну расшифровку: несколько записей одной встречи склеиваем в один источник,
        # иначе «свели» бы встречи, а контекст второй записи в протокол не попал.
        trs = store.q("SELECT id,name,text FROM sources WHERE meeting_id=? AND removed_at IS NULL "
                      "AND kind='transcript' ORDER BY id", (dst_id,))
        if len(trs) > 1:
            base = trs[0]
            text = base["text"] or ""
            for part in trs[1:]:
                text += f"\n\n=== {part['name']} ===\n\n{part['text'] or ''}"
            name = " + ".join(s["name"] for s in trs)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            store.update("sources", base["id"], text=text, name=name, digest=digest)
            for part in trs[1:]:
                store.update("sources", part["id"], removed_at=now(),
                             removed_reason=f"вошла в общий источник {base['name']}")
        store._conn.execute("UPDATE cards SET meeting_id=? WHERE meeting_id=?", (dst_id, src_id))
        for t in store.q("SELECT id FROM tasks WHERE source_meeting_id=?", (src_id,)):
            store.update("tasks", t["id"], source_meeting_id=dst_id)
        for table in ("units", "possible_assignments"):
            store._conn.execute(f"UPDATE {table} SET meeting_id=? WHERE meeting_id=?", (dst_id, src_id))
        store._conn.execute("UPDATE build_queue SET status='cancelled' WHERE meeting_id=? AND status='queued'", (src_id,))
        merged = []
        try:
            merged = json.loads(dst.get("merged") or "[]")
        except (TypeError, ValueError):
            merged = []
        merged.append({"from_id": src_id, "from_date": (src.get("date") or "")[:10], "count": moved,
                       "skipped_same": same, "moved_at": now(), "why": "одна тема и участники"})
        store.update("meetings", dst_id, merged=json.dumps(merged, ensure_ascii=False))
        store.update("meetings", src_id, deleted_at=now(),
                     deleted_info=json.dumps({"merged_into": dst_id, "by": by, "materials": moved},
                                             ensure_ascii=False))
    return dst_id


def свести_дубль_дня(store, meeting_id: int, by: str = "система") -> int | None:
    """Если в тот же день в том же проекте есть встреча с той же темой и теми же участниками — свести в неё.

    Срабатывает после распознавания новой записи. Без имён участников не гадает: тогда остаётся отдельная встреча.
    """
    m = store.get("meetings", meeting_id)
    if not m or m.get("deleted_at"):
        return None
    люди = участники_встречи(store, meeting_id)
    if not люди:
        return None
    for other in store.q("SELECT * FROM meetings WHERE date=? AND project_id=? AND id<>? AND deleted_at IS NULL "
                         "ORDER BY id", (m.get("date"), m.get("project_id"), meeting_id)):
        if other.get("protocol_hand_edited") or not _та_же_тема(m, other):
            continue
        старые = участники_встречи(store, other["id"])
        if старые and старые == люди:
            return свести_в_одну(store, meeting_id, other["id"], by=by)
    return None

