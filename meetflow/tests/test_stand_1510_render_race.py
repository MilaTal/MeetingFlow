"""Находки стенда 10 и 14 (Планёрка 71c9f10, ERP 9b3ecd1): экран, загружаемый асинхронно, дорисовывался поверх
следующего при быстром переходе. В MeetFlow перехват innerHTML ставился заново каждой отрисовкой и пропускал запись
любой — в том числе устаревшей: под адресом «Конфликтов» оставался реестр (живой замер 15.10.26 на стенде 8011:
задержка ответа реестра 100–600 мс — 5 из 5 до правки, 0 из 5 после). Правка: чтение, начатое до смены экрана,
в экран не возвращается. Живой замер — в сверке; здесь сторож, что механизм на месте."""
from pathlib import Path

JS = (Path(__file__).parents[1] / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def test_stale_read_never_returns_to_screen():
    api = JS[JS.index("async function api("):JS.index("function toast(")]
    assert "const seq = renderSeq" in api and "if (read && seq !== renderSeq) throw new Stale" in api
    assert api.index("throw new Stale") < api.index("return data")


def test_render_stops_after_stale_and_before_banner():
    r = JS[JS.index("async function render()"):JS.index("function showLogin()")]
    assert "if (e instanceof Stale || seq !== renderSeq) return;" in r
    assert r.index("if (seq !== renderSeq) return;") < r.index("stand-banner")
    assert 'reason instanceof Stale' in JS
