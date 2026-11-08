"""Замер ВКС на копии базы: скрипт не трогает рабочую базу (записка 05.11.2026, «Мерить на копии базы»)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "zamer_vks_vtoroy_tekst.py"
    spec = importlib.util.spec_from_file_location("zamer_vks_vtoroy_tekst", путь)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_рабочая_база_отвергается():
    mod = _скрипт()
    with pytest.raises(SystemExit):
        mod.проверить_базу(КОРЕНЬ / "data" / "meetflow.db")


def test_копии_нет_отвергается(tmp_path):
    mod = _скрипт()
    with pytest.raises(SystemExit):
        mod.проверить_базу(tmp_path / "нет-такой-копии.db")


def test_копия_принимается(tmp_path):
    mod = _скрипт()
    копия = tmp_path / "kopiya.db"
    копия.write_bytes(b"")
    assert mod.проверить_базу(копия) == копия.resolve()
