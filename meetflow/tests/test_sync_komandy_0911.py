"""Синхронизация «Команды» после правки отчеств: сухой ход и применение (план, пункт 31).

Сухой ход ничего не пишет и показывает, что допишется; `--apply` делает копию базы и применяет `sync_all`.
Тесты на вымышленных людях, общая «Команда» подменена.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from meetflow.core.store import Store

КОРЕНЬ = Path(__file__).resolve().parents[1]


def _скрипт():
    путь = КОРЕНЬ / "scripts" / "sync_komandy.py"
    spec = importlib.util.spec_from_file_location("sync_komandy", путь)
    м = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(м)
    return м


@pytest.fixture
def база(tmp_path):
    путь = tmp_path / "t.db"
    s = Store(str(путь))
    pid = s.insert("projects", name="Склад", theme="it_product", archived=0)
    s.insert("people", project_id=pid, full_name="Иванов Пётр", confirmed=1)
    s.insert("people", project_id=pid, full_name="Петрова Анна Сергеевна", confirmed=1)
    s.close()
    return путь


def _общая():
    return [{"full_name": "Иванов Пётр Сергеевич"}, {"full_name": "Петрова Анна Сергеевна"},
            {"full_name": "Сидоров Пётр Иванович"}]


def test_сухой_ход_показывает_изменения_и_ничего_не_меняет(база, monkeypatch, capsys):
    м = _скрипт()
    import meetflow.core.team_sync as ts
    monkeypatch.setattr(ts, "shared_people", lambda *a, **k: _общая())

    def _запрет(*a, **k):
        raise AssertionError("сухой ход не должен синхронизировать")
    monkeypatch.setattr(ts, "sync_all", _запрет)
    assert м.main(["--db", str(база)]) == 0
    вывод = capsys.readouterr().out
    assert "дописать отчество 1" in вывод and "Иванов Пётр Сергеевич" in вывод
    assert "добавить 1" in вывод and "Сидоров Пётр Иванович" in вывод
    assert "ничего не изменено" in вывод

    s = Store(str(база))
    assert [r["full_name"] for r in s.q("SELECT full_name FROM people WHERE project_id=1 ORDER BY id")] == \
        ["Иванов Пётр", "Петрова Анна Сергеевна"]
    s.close()


def test_применение_делает_копию_и_дописывает(база, monkeypatch, capsys):
    м = _скрипт()
    import meetflow.core.team_sync as ts
    monkeypatch.setattr(ts, "shared_people", lambda *a, **k: _общая())
    настоящий = ts.sync_all

    def _sync_all(store, *a, **k):
        return настоящий(store, None)
    monkeypatch.setattr(ts, "sync_all", _sync_all)
    assert м.main(["--db", str(база), "--apply"]) == 0
    вывод = capsys.readouterr().out
    assert "Копия базы" in вывод and "Применено" in вывод
    копии = list(Path(база).parent.glob(f"{Path(база).name}.до-sinhrona-*"))
    assert копии, "перед применением делается копия"
    s = Store(str(база))
    люди = [r["full_name"] for r in s.q("SELECT full_name FROM people WHERE project_id=1")]
    assert "Иванов Пётр Сергеевич" in люди and "Петрова Анна Сергеевна" in люди
    s.close()


def test_пустая_общая_команда_код_3(база, monkeypatch, capsys):
    м = _скрипт()
    import meetflow.core.team_sync as ts
    monkeypatch.setattr(ts, "shared_people", lambda *a, **k: [])
    assert м.main(["--db", str(база)]) == 3
    assert "не читается или пуста" in capsys.readouterr().err


def test_запуск_как_скрипт_работает(база):
    """Скрипт запускается сам по себе (нашли: не было блока `__main__`, и запуск молча ничего не делал)."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(КОРЕНЬ / "scripts" / "sync_komandy.py"), "--db", str(база)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "не читается или пуста" in (r.stderr or "")
