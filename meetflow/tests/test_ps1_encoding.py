# -*- coding: utf-8 -*-
"""BOM у .ps1: файл с кириллицей обязан начинаться с EF BB BF (записка 9065fb1, 06.11.2026).

Повод: правка 06.11 сохранила `meetflow/scripts/run_dev.ps1` без метки UTF-8. PowerShell 5.1 читает `.ps1` без BOM
как ANSI, кириллица в комментариях разваливает разбор (`MissingEndCurlyBrace`), сервер не стартует, обёртка крутится
вхолостую. Тест ловит потерю BOM до того, как это случится на машине.
"""
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[2]
ПРОПУСТИТЬ = ("Tests/capture_zcode.ps1",)
BOM = b"\xef\xbb\xbf"


def _файлы():
    for p in КОРЕНЬ.rglob("*.ps1"):
        отн = p.relative_to(КОРЕНЬ).as_posix()
        if "__pycache__" in отн or any(отн.endswith(x) for x in ПРОПУСТИТЬ):
            continue
        yield p, отн


def test_ps1_с_кириллицей_начинается_с_bom():
    нарушения = []
    for p, отн in _файлы():
        данные = p.read_bytes()
        есть_не_ascii = any(b >= 0x80 for b in данные)
        if есть_не_ascii and not данные.startswith(BOM):
            нарушения.append(отн)
    assert not нарушения, ("нет BOM при кириллице (PowerShell 5.1 не разберёт): " + ", ".join(нарушения))


def test_обе_копии_run_dev_под_проверкой():
    """Проверка не должна пройти «вхолостую»: обе копии скрипта запуска существуют и попадают в обход."""
    файлы = {отн for _p, отн in _файлы()}
    assert "meetflow/scripts/run_dev.ps1" in файлы
