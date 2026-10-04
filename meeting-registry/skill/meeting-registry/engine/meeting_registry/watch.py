"""Папка-приёмник: запуск без человека (критерий 3.1 курса). Файл появился — встреча обработана.

Защиты, каждая из своей поломки Планёрки:
- файл берётся, только когда дописан: размер не меняется STABLE_SECONDS и файл можно переименовать
  (01.10.26: недописанный файл забирался, протокол по половине, и каждые 15 минут — новый платный прогон);
- дата встречи — из имени файла; нет одной однозначной даты — файл остаётся, человеку одна карточка;
- обработанное уезжает в подпапку «обработано», отклонённое — в «отклонено» с причиной рядом;
- повтор того же содержимого узнаётся по отпечатку, а не по имени.
"""

import json
import os
import shutil
import time
from pathlib import Path

from . import intake, pipeline
from .errors import SourceRejected

STABLE_SECONDS = 2.0
SUFFIXES = {".txt", ".md", ".docx"}


def _stable(path: Path) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(STABLE_SECONDS)
        s2 = path.stat().st_size
        if s1 != s2 or s1 == 0:
            return False
        probe = path.with_name(path.name + ".probe")
        os.replace(path, probe)  # на Windows пишущая программа держит файл — переименование не пройдёт
        os.replace(probe, path)
        return True
    except OSError:
        return False


def _move(path: Path, sub: str, note: str = ""):
    dst_dir = path.parent / sub
    dst_dir.mkdir(exist_ok=True)
    dst = dst_dir / path.name
    if dst.exists():
        dst = dst_dir / f"{path.stem}.{int(time.time())}{path.suffix}"
    shutil.move(str(path), dst)
    if note:
        dst.with_name(dst.name + ".причина.txt").write_text(note, encoding="utf-8")
    return dst


def scan_once(folder: str, registry, team, client_factory, limits=None) -> list:
    """Один проход по папке. Возвращает список исходов — их же видно в журнале прогонов реестра."""
    folder = Path(folder)
    outcomes = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES or path.name.endswith(".probe"):
            continue
        if not _stable(path):
            outcomes.append({"file": path.name, "outcome": "not_ready"})
            continue
        meeting_date = intake.date_from_name(path.name)
        if not meeting_date:
            registry.add_card("no_date", f"Файл «{path.name}» без однозначной даты встречи в имени",
                              payload={"file": path.name})
            outcomes.append({"file": path.name, "outcome": "no_date"})
            continue
        try:
            text = intake.read_file(str(path))
        except SourceRejected as e:
            _move(path, "отклонено", str(e))
            outcomes.append({"file": path.name, "outcome": "rejected", "reason": str(e)})
            continue
        res = pipeline.process(text, path.name, meeting_date, registry, team, client_factory(), limits)
        if res["outcome"] == "rejected":
            _move(path, "отклонено", res["reason"])
        elif res["outcome"] in ("done", "degraded", "duplicate", "partial_limit"):
            _move(path, "обработано")
        else:
            # остановленное по пределу и сбойное уезжает в «остановлено»: само оно не перерабатывается каждый проход,
            # повтор — решение человека (вернуть файл в папку). Ревью 03.10.26: три прохода давали три прогона подряд.
            _move(path, "остановлено", res.get("reason") or res.get("limit") or res["outcome"])
        outcomes.append({"file": path.name, **{k: res.get(k) for k in ("outcome", "meeting_id", "run_id", "reason", "limit")}})
    return outcomes


def watch(folder, registry, team, client_factory, interval=60, limits=None, once=False):
    while True:
        outs = scan_once(folder, registry, team, client_factory, limits)
        for o in outs:
            print(json.dumps(o, ensure_ascii=False), flush=True)
        if once:
            return outs
        time.sleep(interval)
