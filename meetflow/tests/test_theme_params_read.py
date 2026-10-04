"""Письмо 47 meeting-registry (находка Планёрки «настройку пишут, но не читают»). Ревизия параметров тем
MeetFlow: мёртвые — подключить или убрать. Тесты написаны до правки."""
import json

from conftest import TRANSCRIPT
from meetflow.core.config import load_theme


def test_card_cleanup_days_is_applied(store, project, make_pipe):
    """operator.card_cleanup_days: чистка была написана, но никем не вызывалась."""
    old = "2026-01-01T00:00:00"
    held = store.insert("cards", project_id=project, kind="held_task", title="старая", status="open", payload={},
                        created_at=old)
    keep = store.insert("cards", project_id=project, kind="assign_person", title="выбор", status="open", payload={},
                        created_at=old)
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe()
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    p.run(project, mid)
    assert store.get("cards", held)["status"] == "rejected"           # снята по сроку
    assert store.get("cards", keep)["status"] == "open"               # выбор исполнителя — не снимается


def test_units_kinds_filters_units(store, project, make_pipe, theme):
    """units.kinds: список видов единиц никем не читался."""
    th = load_theme("erp_rollout")
    th.data["units"]["kinds"] = ["decision", "agreement", "clarification", "open_question", "task"]   # без вех
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(th=th)
    p.ingest(project, mid, "t 01.10.2026.txt",
             "[00:01:00] Сидоров Пётр: Профиль придёт 10.10.2026 от поставщика по графику.\n"
             "[00:02:00] Игнатов Иван: Решили принимать панели на складе вместе с производством.\n".encode())
    p.run(project, mid)
    kinds = {u["kind"] for u in store.q("SELECT kind FROM units WHERE meeting_id=?", (mid,))}
    assert "milestone" not in kinds and "decision" in kinds


def test_asr_and_vision_models_from_theme(make_pipe):
    """asr.model, asr.language, llm.vision.model: подключения работали на своих умолчаниях."""
    th = load_theme("erp_rollout")
    th.data["asr"].update(model="medium", language="en")
    th.data["llm"]["vision"]["model"] = "llava:13b"
    p = make_pipe(th=th)
    asr = p.plugins.all("asr")[0]
    vis = p.plugins.all("vision")[0]
    assert asr.model_name == "medium" and asr.language == "en" and vis.model == "llava:13b"


def test_dead_fields_removed_from_default():
    d = json.loads(open(load_theme("_default").source, encoding="utf-8").read())
    assert "connector" not in d["llm"]["generator"] and "connector" not in d["llm"]["verifier"]
    assert "connector" not in d["asr"] and "hint" not in d["asr"]
