"""Замер защиты на реальных материалах встреч — ложные пометки и ложные замены (только локально).

Реальные записи — закрытые данные: сценарий читает их на месте и печатает только числа и номера строк; в репозиторий
и в отчёт сами реплики не попадают (флаг --show печатает их на экран для разбора человеком).

  set MEETFLOW_REAL_DBS=<путь к app.db>;<путь к app.db>
  python eval/guard/measure_real.py [--show]

Из каждой базы: текущие источники встреч (meeting_sources.file_path: .txt, .md, .docx) — построчно через детектор
входа; собранные протоколы (meeting_minutes.content_md) — через фильтр выхода."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from meetflow.connectors.files_docx import DocxSource  # noqa: E402
from meetflow.core import security  # noqa: E402

try:
    from meetflow.core import guard  # noqa: E402
except ImportError:          # замер «до»: модуля защиты ещё нет
    guard = None


def lines_of(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        try:
            return DocxSource().read(path.read_bytes(), path.name).text.splitlines()
        except Exception:  # noqa: BLE001 — битый файл не мешает замеру
            return []
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []


def main(show: bool) -> None:
    dbs = [p for p in os.environ.get("MEETFLOW_REAL_DBS", "").split(";") if p.strip()]
    total_lines = flagged = files = unsure = 0
    proto_lines = replaced = protos = 0
    for db in dbs:
        base = Path(db).resolve().parents[1]
        con = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)   # рабочую базу только читаем
        for (fp,) in con.execute("SELECT file_path FROM meeting_sources WHERE is_current=1"):
            p = Path(fp) if os.path.isabs(fp) else base / fp
            if not p.exists():
                continue
            files += 1
            for i, ln in enumerate(lines_of(p)):
                if not ln.strip():
                    continue
                total_lines += 1
                v = guard.line_verdict(ln) if guard else {"suspicious": security.looks_like_injection(ln), "addressed": False}
                hit = v["suspicious"]
                unsure += bool(v.get("unsure"))
                if hit:
                    flagged += 1
                    print(f"  пометка: {p.name[:40]} строка {i}" + (f": {ln[:160]}" if show else ""))
        if guard:
            for (md,) in con.execute("SELECT content_md FROM meeting_minutes WHERE content_md IS NOT NULL"):
                protos += 1
                for ln in md.splitlines():
                    if not ln.strip():
                        continue
                    proto_lines += 1
                    out, changed = guard.filter_text(ln)
                    if changed:
                        replaced += 1
                        print("  замена в протоколе" + (f": {ln[:160]}" if show else ""))
    print(f"Источников: {files}, строк: {total_lines}, помечено как атака: {flagged}, на досмотр моделью: {unsure}")
    if guard:
        print(f"Протоколов: {protos}, строк: {proto_lines}, заменено фильтром выхода: {replaced}")


if __name__ == "__main__":
    main("--show" in sys.argv)
