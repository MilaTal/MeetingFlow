"""Выгрузка ВКС вторым текстом сборки: оба текста в промптах (записка 05.11.2026, п. 1–2, пункт 6 плана, `511fa29`).

Своя локальная остаётся основной, выгрузка идёт рядом — не вместо. Модель получает её отдельным огороженным куском
на то же время и правило: названия объектов, номера и сроки — из выгрузки, где своя искажена; расхождение не
примирять, а оставить оба варианта. `choose_transcript` (правило 25.10.2026) остаётся для случая «своей нет или она
явно неполная».
"""
from __future__ import annotations

import json

from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.registry import default_registry
from meetflow.core.pipeline import MeetingPipeline, teksty_sborki

СВОЯ = ("[00:01:00] Игнатов Иван: Начинаем по колоночному профилю.\n"
        "[00:02:00] Петрова Анастасия: Подготовлю спецификацию к пятнице.\n"
        "[00:03:00] Игнатов Иван: Хорошо, дальше по складу.\n")
ВЫГРУЗКА = ("[00:01:05] Игнатов Иван: Начинаем по колоночному профилю объекта Эль-Дабаа, 5128.\n"
            "[00:02:10] Петрова Анастасия: Подготовлю спецификацию к 17-му.\n")


def _s(name, text, local, sid=1):
    return {"id": sid, "name": name, "text": text, "local_asr": 1 if local else 0}


def test_полная_своя_и_выгрузка_рядом_вторым_текстом():
    своя, чужая = _s("своя", СВОЯ, True), _s("выгрузка", ВЫГРУЗКА, False, 2)
    base, second, reason = teksty_sborki([своя, чужая])
    assert base is своя and second is чужая and reason == ""


def test_короткая_своя_выгрузка_основной_а_не_второй():
    своя, чужая = _s("своя", "а" * 100, True), _s("выгрузка", ВЫГРУЗКА * 10, False, 2)
    base, second, reason = teksty_sborki([своя, чужая])
    assert base is чужая and second is None and "неполная" in reason


def test_без_своей_выгрузка_основной():
    чужая = _s("выгрузка", ВЫГРУЗКА, False)
    base, second, reason = teksty_sborki([чужая])
    assert base is чужая and second is None and "своей" in reason


class Модель(MockLLM):
    """Заглушка запоминает промпты: видно, какие тексты получила сборка."""

    def __init__(self):
        super().__init__()
        self.seen: dict[str, tuple[str, str]] = {}

    def complete(self, system, user, *, json_mode=True, temperature=0.0, purpose="", deadline=None):
        self.seen[purpose] = (system, user)
        return super().complete(system, user, json_mode=json_mode, temperature=temperature, purpose=purpose)


def _сборка(store, project, meeting, theme, tmp_path):
    gen = Модель()
    p = MeetingPipeline(theme, store, default_registry(), gen, MockLLM(), journal_path=tmp_path / "j.jsonl")
    store.insert("sources", meeting_id=meeting, name="своя запись", kind="transcript", text=СВОЯ,
                 digest="v1" + str(meeting), local_asr=1, meta=json.dumps({"voice_names": {}}, ensure_ascii=False),
                 created_at="2026-11-06T10:00:00")
    store.insert("sources", meeting_id=meeting, name="выгрузка ВКС", kind="transcript", text=ВЫГРУЗКА,
                 digest="v2" + str(meeting), local_asr=0, meta=json.dumps({}, ensure_ascii=False),
                 created_at="2026-11-06T10:05:00")
    rep = p.run(project, meeting)
    return gen, rep


def test_оба_текста_в_поручениях_и_протоколе(store, project, meeting, theme, tmp_path):
    gen, _rep = _сборка(store, project, meeting, theme, tmp_path)
    система_поручений, тело_поручений = gen.seen["extract_tasks"]
    система_протокола, тело_протокола = gen.seen["protocol"]
    assert "Эль-Дабаа" in тело_поручений and "5128" in тело_поручений
    assert "Эль-Дабаа" in тело_протокола and "5128" in тело_протокола
    # своя расшифровка в промпте тоже осталась — выгрузка не замена
    assert "Начинаем по колоночному профилю" in тело_поручений
    for система in (система_поручений, система_протокола):
        assert "выгрузка ВКС той же встречи" in система
        assert "не примиряй" in система
        # замер 05.11.2026: объект рядом с поручением (объект назван до разговора о профиле) — часть поручения
        assert "впиши его в формулировку" in система
    # единицы встречи получают тот же второй текст на своё время (записка 05.11.2026, п. 1)
    assert "units" in gen.seen
    система_единиц, тело_единиц = gen.seen["units"]
    assert "Эль-Дабаа" in тело_единиц and "выгрузка ВКС той же встречи" in система_единиц


def test_в_итоге_сборки_видно_что_текстов_два(store, project, meeting, theme, tmp_path):
    _gen, rep = _сборка(store, project, meeting, theme, tmp_path)
    assert "выгрузка ВКС вторым текстом" in rep.source_reason
