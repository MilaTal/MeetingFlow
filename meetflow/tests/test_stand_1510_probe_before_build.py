"""Находка стенда 39 (ERP 689c739, 746de10; на локальной машине 15.10 проба 1–2 с у DeepSeek): пробный запрос перед
сборкой — начало запроса, ответ обрывается на первом признаке жизни, порог не меньше 600 с; не готова — следующая точка;
не готова ни одна — сборка не начинается, одна карточка на встречу; свежесть 10 минут. Проба — общим model_routes.probe.
Тесты написаны до правки и падали (пробы не было)."""
import json

import pytest

from conftest import TRANSCRIPT
from meetflow.connectors import llm_routes as lr
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.shared import model_routes as mr


class Answering(lr.PointLLM):
    """Точка с настоящей пробой (общий модуль, сеть подменена), но ответом заглушки."""
    def complete(self, system, user, **kw):
        return MockLLM().complete(system, user, **kw)


@pytest.fixture
def two_points(tmp_path, monkeypatch, store, project):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"endpoints": {
        "a": {"kind": "openai", "url": "http://10.0.0.1:1234", "model": "ma"},
        "b": {"kind": "openai", "url": "http://10.0.0.2:1234", "model": "mb"}},
        "roles": {"generate": ["a", "b"]}}), encoding="utf-8")
    monkeypatch.setenv("MODEL_ROUTES_PATH", str(path))
    monkeypatch.setattr(mr._state, "down_until", {})
    monkeypatch.setattr(mr._state, "probe_ok", {})
    ready, probed = {}, []

    def fake_probe(route, **kw):
        probed.append((route.name, kw.get("settings", {}).get("first_sign_sec")))
        ok = ready.get(route.name, True)
        if ok:
            mr._state.probe_ok[mr._probe_key(route, route.model or "")] = __import__("time").time()
        return {"point": route.name, "ok": ok, "reason": "" if ok else "модель молчит дольше 600 с", "seconds": 0.1,
                "first_sign_sec": 0.1 if ok else None}
    monkeypatch.setattr(mr, "probe", fake_probe)
    gen = lr.RoutedLLM("generator", path=path, factory=lambda n, ep: Answering(n, ep))
    return gen, ready, probed


def _run(store, project, make_pipe, gen, date="2026-10-01"):
    mid = store.insert("meetings", project_id=project, date=date, label="встреча")
    p = make_pipe(gen=gen)
    p.ingest(project, mid, f"t {date[8:]}.{date[5:7]}.{date[:4]}.txt", TRANSCRIPT.encode())
    return p, mid, p.run(project, mid)


def test_probe_before_build_next_point_when_first_silent(store, project, make_pipe, two_points):
    gen, ready, probed = two_points
    ready["a"] = False
    p, mid, rep = _run(store, project, make_pipe, gen)
    assert [n for n, _ in probed] == ["a", "b"] and rep.protocol_saved
    assert all(sec >= 600 for _, sec in probed), "порог первого признака не меньше 600 с"
    assert "a" in mr._state.down_until
    assert any(r.get("purpose") == "probe" and r.get("point") == "a" and not r.get("ok") for r in p.journal.records)


def test_no_point_ready_no_build_one_card(store, project, make_pipe, two_points):
    gen, ready, probed = two_points
    ready["a"] = ready["b"] = False
    mid = store.insert("meetings", project_id=project, date="2026-10-01", label="встреча")
    p = make_pipe(gen=gen)
    p.ingest(project, mid, "t 01.10.2026.txt", TRANSCRIPT.encode())
    rep = p.run(project, mid)
    assert rep.status == "not_ready" and not rep.protocol_saved and rep.calls == 0
    mr._state.down_until.clear()
    p.run(project, mid)
    cards = store.q("SELECT * FROM cards WHERE meeting_id=? AND title LIKE 'Сборка не начата: модель не готова%' "
                    "AND status='open'", (mid,))
    assert len(cards) == 1, "одна карточка на встречу"


def test_fresh_probe_is_not_repeated(store, project, make_pipe, two_points):
    gen, ready, probed = two_points
    _run(store, project, make_pipe, gen)
    _run(store, project, make_pipe, gen, date="2026-10-02")
    assert [n for n, _ in probed] == ["a"], "точка прошла пробу меньше 10 минут назад — повторно не проверяется"


def test_probe_can_be_switched_off(store, project, make_pipe, two_points, monkeypatch):
    gen, ready, probed = two_points
    monkeypatch.setenv("MODEL_PROBE", "off")
    ready["a"] = ready["b"] = False
    _, _, rep = _run(store, project, make_pipe, gen)
    assert probed == [] and rep.protocol_saved
