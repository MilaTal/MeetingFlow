"""Находка стенда 34 (Планёрка, хаос-проверка, 0e79042): зависший при остановке процесс держал метку запуска, и
следующие запуски работали «вторыми» — без папки-приёмника и подхвата, а экраны отвечали, сбой не виден. В MeetFlow
метки не было вовсе: второй процесс с той же базой на другом порту запускал второй забор из папки. Теперь метка рядом
с базой; «первый уже работает» — только если его процесс жив И его порт слушает; иначе метка перехватывается. Второй
экземпляр — без забора из папки и автокопии, с системным сообщением. Тесты написаны до правки и падали."""
import json
import os
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def other_process():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield p.pid
    p.kill()


def _start(tmp_path, monkeypatch, port):
    monkeypatch.setenv("MEETFLOW_PORT", str(port))
    from meetflow.web.app import create_app
    app = create_app("erp_rollout", str(tmp_path / "t.db"), str(tmp_path / "j.jsonl"), watch=True)
    started = []
    monkeypatch.setattr(app.state.intake, "start", lambda *a, **k: started.append("intake"))
    monkeypatch.setattr(app.state.backups, "start", lambda *a, **k: started.append("backups"))
    with TestClient(app):
        pass
    return app, started


def test_second_instance_on_same_db_does_not_take_the_folder(tmp_path, monkeypatch, other_process):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    first_port = srv.getsockname()[1]
    (tmp_path / "t.launch.json").write_text(json.dumps({"pid": other_process, "port": first_port}), encoding="utf-8")
    try:
        app, started = _start(tmp_path, monkeypatch, first_port + 1)
    finally:
        srv.close()
    assert started == [], "второй экземпляр запустил забор из папки"
    assert app.state.store.q("SELECT * FROM cards WHERE title LIKE 'Второй экземпляр MeetFlow на той же базе%'")


def test_hung_process_without_port_does_not_block(tmp_path, monkeypatch, other_process):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()                                         # процесс жив, а порт не слушает — завис при остановке
    marker = tmp_path / "t.launch.json"
    marker.write_text(json.dumps({"pid": other_process, "port": dead_port}), encoding="utf-8")
    app, started = _start(tmp_path, monkeypatch, dead_port + 1)
    assert started == ["intake", "backups"]
    assert json.loads(marker.read_text(encoding="utf-8"))["pid"] == os.getpid()
