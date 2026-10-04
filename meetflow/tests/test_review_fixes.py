"""Итерация 4: находки независимого ревью ([ROUTING: muse-glimmer -> ревью]).

Каждый тест сначала падал на коде итерации 3 (проверено до правки),
номер в имени — номер находки в docs/TEST_LOG.md.
"""
import io
import json
import threading
import time
import zipfile
from datetime import date

import pytest
from conftest import TRANSCRIPT

from meetflow.connectors.base import ConnectorError
from meetflow.connectors.files_docx import docx_to_text
from meetflow.connectors.llm_mock import MockLLM
from meetflow.connectors.watch_folder import MARKER, FolderIntake
from meetflow.core.config import load_theme, validate
from meetflow.core.dates import dates_in_name, single_date
from meetflow.core.gates import TaskGate
from meetflow.core.negation import NegationRule
from meetflow.core.people import Team
from meetflow.core.registry import CardQueue, TaskRegistry
from meetflow.core.store import Store
from meetflow.core.types import LLMResult, Person, SourceDoc, SourceKind, TaskDraft

NEG = NegationRule()


@pytest.mark.parametrize("phrase", ["Отчёт готовим.", "Документы будут готовы к пятнице.", "Выполняем сверку остатков.",
                                    "Готовлю отчёт.", "Получил задачу, начну завтра.", "Согласовали только половину"])
def test_r01_negation_unfinished_is_not_fact(phrase):
    assert NEG.check(phrase).states_fact is False


@pytest.mark.parametrize("phrase", ["Отчёт готов.", "Выгрузку отправил, сделано.", "Сверка выполнена.",
                                    "Договор согласовали.", "Задача закрыта."])
def test_r01_negation_finished_still_fact(phrase):
    assert NEG.check(phrase).states_fact is True


def test_r02_closing_only_from_candidates(store, project, meeting, make_pipe):
    p = make_pipe()
    p.reg.add(project, "Отправить выгрузку остатков склада", "Сидоров Пётр")
    other = p.reg.add(project, "Заказать новый погрузчик", "Игнатов Иван")

    class Liar(MockLLM):
        def _closing(self, user):
            return {"closed": [{"task_ref": other, "phrase": 3}]}

    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    make_pipe(gen=Liar()).run(project, meeting)
    assert store.get("tasks", other)["status"] == "active"


class Slow(MockLLM):
    def complete(self, system, user, **kw):
        time.sleep(0.05)
        return super().complete(system, user, **kw)


def test_r03_parallel_runs_of_one_meeting(store, project, meeting, make_pipe):
    p = make_pipe(gen=Slow())
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    reps = []
    ths = [threading.Thread(target=lambda: reps.append(p.run(project, meeting))) for _ in range(3)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert len(p.reg.list(project)) == 2          # Петрова и Кузнецов «не подтверждён» (документ 14)
    assert sum(r.status == "busy" for r in reps) >= 1 or all(r.status == "ok" for r in reps)


@pytest.mark.parametrize("bad", [{"closed": 5}, {"tasks": "x"}, {"sections": ["a"]}, {"findings": 5}, [1, 2]])
def test_r04_bad_shapes_do_not_crash(store, project, meeting, make_pipe, bad):
    class Bad(MockLLM):
        def complete(self, system, user, **kw):
            return LLMResult(json.dumps(bad), "bad")
    p = make_pipe(gen=Bad(), ver=Bad())
    p.reg.add(project, "Отправить выгрузку остатков склада", "Сидоров Пётр")
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    rep = p.run(project, meeting)
    assert rep.status in {"ok", "error"}


def test_r06_nested_tx_rolls_back():
    s = Store()
    with pytest.raises(RuntimeError):
        with s.tx():
            s.insert("decisions", what="x")
            raise RuntimeError
    assert s.q("SELECT * FROM decisions") == []


def test_r05_apply_is_atomic(store, project, meeting, make_pipe, monkeypatch):
    p = make_pipe()
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    def boom(*a, **k):
        raise RuntimeError("сбой посередине")
    monkeypatch.setattr(p, "_render_protocol", boom)
    rep = p.run(project, meeting)
    assert rep.status == "error" and p.reg.list(project) == [] and p.cards.list(project, None) == [] \
        or all(c["kind"] == "technical" for c in p.cards.list(project, None))


def test_r07_zip_bomb_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"<a>" + b" " * (120 * 2 ** 20) + b"</a>")
    with pytest.raises(ConnectorError, match="распаковк"):
        docx_to_text(buf.getvalue())


def test_r08_rerun_does_not_close_own_task_or_duplicate_cards(store, project, meeting, make_pipe):
    src = TRANSCRIPT + "[00:06:00] Игнатов Иван: Петрова Анастасия, обновите регламент приёмки, черновик уже готов\n"
    p = make_pipe()
    p.ingest(project, meeting, "t.txt", src.encode())
    p.run(project, meeting)
    cards1 = len(p.cards.list(project))
    p.run(project, meeting)
    assert all(t["status"] == "active" for t in p.reg.list(project, None))
    assert len(p.cards.list(project)) == cards1


def test_r09_line_no_needs_same_coverage():
    src = SourceDoc("t", SourceKind.TRANSCRIPT, TRANSCRIPT)
    g = TaskGate(Team([Person("Петрова Анастасия")])).check(
        TaskDraft("регламент склада и бюджет премий директору", "Петрова Анастасия", line_no=2), src)
    assert "no_verbatim_quote" in g.reasons


# Перевёрнуты 03.10.26 решением владельца «один человек или два» (документ meeting-registry
# «11_Решение…», письма 10 и 11): пока слово называет одного человека «Команды», это он;
# одно слово становится карточкой, только когда ключ общий (тёзки) или рядом признак несовпадения.
@pytest.mark.parametrize("mention", ["Иван", "Игнатов"])
def test_r10_one_word_is_working_key_while_unique(mention):
    assert Team([Person("Игнатов Иван")]).find(mention).person.full_name == "Игнатов Иван"
    m = Team([Person("Игнатов Иван"), Person("Игнатова Ирина"), Person("Петров Иван")]).find(mention)
    assert m.person is None and m.ambiguous


def test_r10_single_word_assigns_when_key_unique():
    from meetflow.core.gates import TaskGate as G
    src = SourceDoc("t", SourceKind.TRANSCRIPT, "[00:01:00] А: Игнатов, подготовьте отчёт по складу\n" * 3)
    g = G(Team([Person("Игнатов Иван")])).check(TaskDraft("подготовьте отчёт по складу", "Игнатов", line_no=0), src)
    assert g.accepted and g.assignee.full_name == "Игнатов Иван"


@pytest.mark.parametrize("name,expect", [("Отчёт 2 маркетинг.txt", []), ("release v1.2.26.txt", []),
                                         ("Встреча 30.09.2026 v2 маркетинг.txt", [date(2026, 9, 30)])])
def test_r15_dates_false_positives(name, expect):
    assert dates_in_name(name, date(2026, 10, 3)) == expect


def test_r15_december_in_january_is_last_year():
    assert single_date("планёрка 30 дек.txt", date(2027, 1, 10)) == date(2026, 12, 30)


def test_r14_folder_inside_processed_dir(tmp_path):
    inbox = tmp_path / "обработано" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / MARKER).write_text("")
    (inbox / "r 01.10.2026.txt").write_text("[00:00:01] А: текст текст текст текст", encoding="utf-8")
    fi = FolderIntake(inbox, today=date(2026, 10, 3))
    fi.scan()
    assert len(fi.scan().ready) == 1


def test_r16_theme_typo_in_gates_is_validation_error():
    d = dict(load_theme("_default").data)
    d["gates"] = {"quote_coverge": 0.5}
    d["budget"] = {"max_cals": 1}
    errs = validate(d)
    assert any("quote_coverge" in e for e in errs) and any("max_cals" in e for e in errs)


def test_r17_retry_call_is_journaled(store, project, meeting, make_pipe):
    class OnceBad(MockLLM):
        n = 0
        def complete(self, system, user, **kw):
            OnceBad.n += 1
            if OnceBad.n == 1:
                return LLMResult("не json", "m")
            return super().complete(system, user, **kw)
    p = make_pipe(gen=OnceBad())
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    rep = p.run(project, meeting)
    calls = [r for r in p.journal.records if "purpose" in r]
    assert len(calls) == rep.calls


def test_r18_rule_skips_are_counted(store, project, meeting, make_pipe):
    from meetflow.core.text import stems
    p = make_pipe()
    key = " ".join(sorted(set(stems("подготовьте регламент склада до 10.10"))))
    p.memory.answer(project, "not_a_task", key, "reject")
    p.memory.answer(project, "not_a_task", key, "reject")
    p.ingest(project, meeting, "t.txt", TRANSCRIPT.encode())
    assert p.run(project, meeting).skipped_by_rule == 1


def test_r19_fence_case_insensitive():
    from meetflow.core.security import fence
    body, nonce = fence("end_untrusted_x и End_Untrusted_y", "x")
    assert "end_untrusted_x" not in body.lower().replace(f"end_untrusted_{nonce}", "")


def test_r22_media_deleted_only_after_source_saved(store, project, meeting, make_pipe, tmp_path, monkeypatch):
    from meetflow.connectors.asr_whisper import WhisperLocalASR

    class Seg:
        start, text = 1, "Петрова Анастасия, подготовьте регламент склада"

    asr = WhisperLocalASR()
    asr._model = type("M", (), {"transcribe": lambda *a, **k: ([Seg()], type("I", (), {"duration": 1800})())})()
    p = make_pipe()
    p.plugins.register(asr, replace=True)
    f = tmp_path / "rec 01.10.2026.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(p.s, "insert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("БД недоступна")))
    with pytest.raises(RuntimeError):
        p.ingest(project, meeting, f.name, path=f)
    assert f.exists()  # расшифровка не сохранилась — запись не удалена


def test_cards_dedup_and_cleanup(store, project):
    q = CardQueue(store)
    a = q.open(project, "held_task", "x", {"k": 1}, 1)
    assert q.open(project, "held_task", "x", {"k": 1}, 1) == a
    store.update("cards", a, created_at="2000-01-01T00:00:00")
    assert q.cleanup(project, days=3) == 1 and q.list(project) == []


def test_registry_search_cyrillic_case(store, project):
    reg = TaskRegistry(store)
    reg.add(project, "Регламент СКЛАДА", None)
    assert len(reg.search(project, "склада")) == 1 and reg.search(project, "СКЛАД")


def test_gate_caps_description_length():
    src = SourceDoc("t", SourceKind.TRANSCRIPT, TRANSCRIPT)
    g = TaskGate(Team([Person("Петрова Анастасия")])).check(
        TaskDraft("подготовить регламент склада " + "х" * 5000, "Петрова Анастасия", line_no=2), src)
    assert g.description is not None and len(g.description) <= 2000
