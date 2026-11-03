import json

from meetflow.core import proekt_zapisi as pz
from meetflow.core.store import Store, now


def _meeting(s, project_id, label, text, names):
    mid = s.insert("meetings", project_id=project_id, date="2026-11-03", label=label,
                   status="scheduled", created_at=now())
    s.insert("sources", meeting_id=mid, name=label, kind="transcript", text=text, digest=f"{mid}:{text}",
             created_at=now(), local_asr=1,
             meta=json.dumps({"voice_names": {str(i): n for i, n in enumerate(names)}}, ensure_ascii=False))
    return mid


def _db():
    s = Store(":memory:")
    pid = s.insert("projects", name="MeetFlow", theme="it_product", created_at=now(), aliases="[]",
                   active=1, archived=0, general=0, deleted=0)
    return s, pid


def test_одна_тема_и_люди_сводит_в_один_протокол():
    s, pid = _db()
    first = _meeting(s, pid, "из папки-приёмника: Выезд на склады и производство 03.11.2026 13.32.m4a",
                     "первая запись", ["Иванов Иван", "Петров Пётр"])
    second = _meeting(s, pid, "из папки-приёмника: Выезд на склады и производство 03.11.2026 14.26.m4a",
                      "вторая запись", ["Иванов Иван", "Петров Пётр"])
    assert pz.свести_дубль_дня(s, second) == first
    assert s.get("meetings", second)["deleted_at"] is not None
    assert s.get("meetings", first)["merged"]
    sources = s.q("SELECT meeting_id, text, removed_at FROM sources ORDER BY id")
    assert sources[0]["meeting_id"] == first and "вторая запись" in sources[0]["text"]
    assert sources[1]["removed_at"] is not None


def test_разные_люди_не_сводятся():
    s, pid = _db()
    _meeting(s, pid, "Выезд на склады 03.11.2026 13.32.m4a", "первая", ["Иванов Иван"])
    second = _meeting(s, pid, "Выезд на склады 03.11.2026 14.26.m4a", "вторая", ["Сидоров Сидор"])
    assert pz.свести_дубль_дня(s, second) is None
    assert s.get("meetings", second)["deleted_at"] is None


def test_разная_тема_не_сводится():
    s, pid = _db()
    _meeting(s, pid, "Выезд на склады 03.11.2026 13.32.m4a", "первая", ["Иванов Иван"])
    second = _meeting(s, pid, "Маркетинг 03.11.2026 14.26.m4a", "вторая", ["Иванов Иван"])
    assert pz.свести_дубль_дня(s, second) is None
