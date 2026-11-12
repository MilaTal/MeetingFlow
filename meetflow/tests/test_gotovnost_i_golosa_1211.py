# -*- coding: utf-8 -*-
"""Готовность протокола и второй этап голосов (12.11.2026).

Слово владелицы: «не выводить ошибочную информацию о готовности» и «финально выдавать результат с голосами, но если
голоса не распознаются — идти по пути деградации». Тест проверяет:
  • пустой протокол (шапка и «задач нет») готовым не считается;
  • протокол с задачами или содержательным текстом — считается;
  • очередь голосов разбирает источник, подписывает текст, ставит пересборку и убирает запись;
  • сбой голосов не теряет протокол: состояние «сбой», расшифровка на месте, карточка.
"""
from __future__ import annotations

import json

from meetflow.core.golosa_ochered import СОСТОЯНИЕ_ЖДЁТ, GolosaOchered
from meetflow.core.protokol_sostoyanie import пустой

ПУСТОЙ = """# Протокол встречи 12.11.2026

## Задачи

Новых задач на этой встрече не зафиксировано.
"""

СОДЕРЖАТЕЛЬНЫЙ = """# Протокол встречи 12.11.2026

## Итоги

Обсудили поставку профиля: график сдвигается на неделю, письмо готовим к пятнице.
Калибровку весового стола перенесли на четверг, мастер подтвердил.
"""


def test_пустой_протокол_не_готов():
    assert пустой(ПУСТОЙ) is True
    assert пустой(ПУСТОЙ, задач=0) is True


def test_протокол_с_содержанием_готов():
    assert пустой(СОДЕРЖАТЕЛЬНЫЙ) is False
    assert пустой(ПУСТОЙ, задач=2) is False          # задачи есть — протокол не пустой, даже если текст короткий


def test_только_дата_и_заголовки_не_содержание():
    assert пустой("# Протокол встречи 12.11.2026\n\n## Задачи\n\nНет.\n") is True
    assert пустой(None) is True and пустой("") is True


class _Карточки:
    def __init__(self):
        self.открытые = []

    def open(self, project_id, kind, title, data=None, meeting_id=None):
        self.открытые.append({"project_id": project_id, "kind": kind, "title": title, "meeting_id": meeting_id})


class _ОчередьСборок:
    def __init__(self):
        self.задания = []

    def enqueue(self, project_id, meeting_id, why="", by=""):
        self.задания.append((project_id, meeting_id, why))
        return len(self.задания)


class _Пайп:
    """Подделка конвейера: голоса «разбираются» без звука."""

    def __init__(self, store, подпишет=True):
        self.s = store
        self.cards = _Карточки()
        self.queue = _ОчередьСборок()
        self.подпишет = подпишет
        self.пересборок = 0

    def _voice_step(self, project_id, meeting_id, wav_path, doc, filename):
        if not self.подпишет:
            doc.meta["voice_error"] = "нет модели разделения голосов"
            return
        doc.text = doc.text.replace("[00:00:10] ", "[00:00:10] Игнатов Иван: ")
        doc.meta["signed_lines"] = 1
        doc.meta["speakers"] = 1

    def run(self, project_id, meeting_id, limits=None):
        self.пересборок += 1
        return type("Отчёт", (), {"status": "ok"})()


def _источник(store, tmp_path, mid, проект):
    запись = tmp_path / "запись.wav"
    запись.write_bytes(b"RIFF")
    return store.insert("sources", meeting_id=mid, name="запись (распознано локально).txt", kind="transcript",
                        text="[00:00:10] Доброе утро, начинаем.", created_at="2026-11-12T15:00:00",
                        local_asr=1, voice_state=СОСТОЯНИЕ_ЖДЁТ,
                        meta=json.dumps({"media_path": str(запись), "segment_lines": ["Доброе утро, начинаем."],
                                         "segment_times": [[10, 12]]}, ensure_ascii=False))


def test_очередь_голосов_подписывает_и_пересобирает(store, project, meeting, tmp_path):
    sid = _источник(store, tmp_path, meeting, project)
    пайп = _Пайп(store)
    очередь = GolosaOchered(пайп, intake=None)
    строка = store.q("SELECT * FROM sources WHERE id=?", (sid,))[0]
    очередь._разобрать(строка)
    после = store.get("sources", sid)
    assert после["voice_state"] == "готово"
    assert "Игнатов Иван" in после["text"]
    assert пайп.queue.задания and пайп.queue.задания[0][1] == meeting     # пересборка с голосами
    assert not (tmp_path / "запись.wav").exists()                         # запись убрана после разбора


def test_сбой_голосов_не_теряет_расшифровку(store, project, meeting, tmp_path):
    sid = _источник(store, tmp_path, meeting, project)
    пайп = _Пайп(store, подпишет=False)
    очередь = GolosaOchered(пайп, intake=None)
    очередь._разобрать(store.q("SELECT * FROM sources WHERE id=?", (sid,))[0])
    после = store.get("sources", sid)
    assert после["voice_state"].startswith("сбой")
    assert "Доброе утро" in после["text"]                                  # расшифровка на месте
    assert not пайп.queue.задания                                          # пересборки нет — нечего подписывать
    assert any(к["kind"] == "technical" for к in пайп.cards.открытые)
