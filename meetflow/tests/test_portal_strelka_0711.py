# -*- coding: utf-8 -*-
"""Стрелка «← Единый вход» в MeetFlow — возврат на портал (решение владелицы 07.11.2026, вид 1 — только стрелка).

Те же проверки, что у Проекта ERP и Планёрки (`tests/test_portal_strelka_0711.py` там): адрес портала запоминается в
cookie `portal_home` только после успешного обмена кода и только при том же имени машины; чужой и кривой адрес — нет;
выход снимает; файл стрелки MeetFlow отдаёт со своего адреса, до входа, без портала — пустым. Портал подменён.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from meetflow.web.erp import portal_vhod
from test_portal_vhod_0611 import W, env  # noqa: F401  (фикстура)

ДОМ = "http://testserver:8010/"


def _дом(r) -> str | None:
    for строка in r.headers.get_list("set-cookie"):
        if строка.startswith(portal_vhod.HOME_COOKIE + "="):
            return строка.split(";", 1)[0].split("=", 1)[1]
    return None


def test_вошёл_через_портал_адрес_запомнен(env):
    env.режим(True)
    r = env.get("/auth/portal", params={"home": ДОМ, "code": "c-vsidorova"}, follow_redirects=False)
    assert r.headers["location"] == "/" and _дом(r) == quote(ДОМ, safe="")


def test_тестовый_режим_тоже(env):
    r = env.get("/auth/portal", params={"home": ДОМ, "code": "t-vsidorova"}, follow_redirects=False)
    assert r.headers["location"].startswith("/?portal_user=") and _дом(r) == quote(ДОМ, safe="")


def test_чужой_и_кривой_адрес_не_запоминается(env):
    for плохой in ("http://evil.example:8010/", "http://testserver:8010/x", "http://testserver:8010/?a=1",
                   "javascript:alert(1)", "http://u:p@testserver:8010/", "http://testserver:99999/", "x" * 400):
        r = env.get("/auth/portal", params={"home": плохой, "code": "t-vsidorova"}, follow_redirects=False)
        assert _дом(r) is None, плохой


def test_неудачный_код_не_запоминает(env):
    for код in ("c-никто", "c-ext", "c-off", ""):
        r = env.get("/auth/portal", params={"home": ДОМ, "code": код}, follow_redirects=False)
        assert _дом(r) is None, код


def test_выход_снимает(env, monkeypatch):
    monkeypatch.setattr(portal_vhod, "notify_logout", lambda u: None)
    env.режим(True)
    env.get("/auth/portal", params={"home": ДОМ, "code": "c-vsidorova"}, follow_redirects=False)
    r = env.post("/auth/logout", headers=W)
    assert r.status_code == 204
    снять = [s for s in r.headers.get_list("set-cookie") if s.startswith(portal_vhod.HOME_COOKIE + "=")]
    assert снять and ("max-age=0" in снять[0].lower() or "expires=" in снять[0].lower())


def test_файл_стрелки_без_портала_пустой(env, monkeypatch):
    monkeypatch.delenv("PORTAL_SECRET")
    r = env.get("/auth/portal/vozvrat.js")
    assert r.status_code == 200 and r.text == "" and "javascript" in r.headers["content-type"]


def test_файл_стрелки_с_портала_до_входа(env, monkeypatch):
    class Ответ:
        status = 200

        def read(self, n):
            return "/* стрелка */ portal_home".encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    спрошено = []
    monkeypatch.setattr(portal_vhod._OPENER, "open", lambda req, timeout: (спрошено.append(req.full_url), Ответ())[1])
    monkeypatch.setattr(portal_vhod, "_ARROW", {"text": "", "at": 0.0})
    env.режим(True)
    r = env.get("/auth/portal/vozvrat.js")
    assert r.status_code == 200 and "portal_home" in r.text
    env.get("/auth/portal/vozvrat.js")
    assert len(спрошено) == 1


def test_место_стрелки_над_названием():
    html = (Path(__file__).resolve().parent.parent / "meetflow" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "<div data-portal-back></div>" in html
    assert html.index("data-portal-back") < html.index('class="brand"')
    assert '<script src="/auth/portal/vozvrat.js" defer></script>' in html
