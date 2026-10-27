"""Находки стенда 10 и 14 (Планёрка 71c9f10, ERP 9b3ecd1): экран, загружаемый асинхронно, дорисовывался поверх
следующего при быстром переходе. В MeetFlow перехват innerHTML ставился заново каждой отрисовкой и пропускал запись
любой — в том числе устаревшей: под адресом «Конфликтов» оставался реестр (живой замер 15.10.26 на стенде 8011:
задержка ответа реестра 100–600 мс — 5 из 5 до правки, 0 из 5 после). Правка: чтение, начатое до смены экрана,
в экран не возвращается. Живой замер — в сверке; здесь сторож, что механизм на месте."""
from pathlib import Path

JS = (Path(__file__).parents[1] / "meetflow" / "web" / "static" / "app.js").read_text(encoding="utf-8")


def test_stale_read_never_returns_to_screen():
    """Устаревший ответ не попадает на новый экран — с 27.10.2026 правило ERP: `api()` сравнивает номер перехода."""
    api = JS[JS.index("async function api("):JS.index("async function _apiЗапрос(")]
    assert "const переход = _переходов;" in api and "if (устарел()) return new Promise(() => {});" in api


def test_render_stops_after_stale_and_before_banner():
    """Показ решает только самый свежий (`_renderSeq`, ERP 30.09.26) — с 27.10.2026 фронт ERP 1 в 1."""
    r = JS[JS.index("async function render()"):JS.index('document.getElementById("nav")?.addEventListener')]
    assert "const seq = ++_renderSeq;" in r and "if (seq !== _renderSeq) {" in r
    assert r.index("if (seq !== _renderSeq) {") < r.index("if (failed) {")
