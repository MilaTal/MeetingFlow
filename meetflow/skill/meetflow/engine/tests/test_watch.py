"""Итерация 1, запуск без человека: папка-приёмник забирает файл, встреча обрабатывается, файл уезжает."""

from meeting_registry import watch
from meeting_registry.heuristic import HeuristicClient


def test_folder_trigger_processes_and_moves(tmp_path, reg, team, m1, monkeypatch):
    monkeypatch.setattr(watch, "STABLE_SECONDS", 0.05)
    (tmp_path / "Планёрка 2026_10_02.txt").write_text(m1, encoding="utf-8")
    (tmp_path / "заметки без даты.txt").write_text(m1, encoding="utf-8")
    (tmp_path / "пустой 03.10.2026.txt").write_text("   ", encoding="utf-8")
    outs = watch.scan_once(str(tmp_path), reg, team, HeuristicClient)
    by = {o["file"]: o["outcome"] for o in outs}
    assert by["Планёрка 2026_10_02.txt"] == "done"
    assert by["заметки без даты.txt"] == "no_date"
    assert by["пустой 03.10.2026.txt"] in ("rejected", "not_ready")
    assert (tmp_path / "обработано" / "Планёрка 2026_10_02.txt").exists()
    assert (tmp_path / "заметки без даты.txt").exists()                     # остаётся, человеку карточка
    assert any(c["kind"] == "no_date" for c in reg.open_cards())
    assert len(reg.all_tasks()) >= 2


def test_second_pass_same_content_is_duplicate(tmp_path, reg, team, m1, monkeypatch):
    monkeypatch.setattr(watch, "STABLE_SECONDS", 0.05)
    (tmp_path / "Планёрка 2026_10_02.txt").write_text(m1, encoding="utf-8")
    watch.scan_once(str(tmp_path), reg, team, HeuristicClient)
    n = len(reg.all_tasks())
    (tmp_path / "Повтор 2026_10_02.txt").write_text(m1, encoding="utf-8")
    outs = watch.scan_once(str(tmp_path), reg, team, HeuristicClient)
    assert outs[0]["outcome"] == "duplicate" and len(reg.all_tasks()) == n


def test_file_still_growing_is_not_taken(tmp_path, reg, team, monkeypatch):
    monkeypatch.setattr(watch, "STABLE_SECONDS", 0.05)
    p = tmp_path / "Планёрка 2026_10_02.txt"
    p.write_text("", encoding="utf-8")                                       # нулевой размер — ещё пишется
    outs = watch.scan_once(str(tmp_path), reg, team, HeuristicClient)
    assert outs[0]["outcome"] == "not_ready" and p.exists()
