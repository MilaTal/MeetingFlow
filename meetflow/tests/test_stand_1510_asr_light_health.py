"""Находки стенда 13 и 33 (ERP, стенд 8020). 13 — проверка готовности распознавания импортировала faster_whisper
(с torch — тысячи модулей, 3–4 с на первом запросе мониторинга), да ещё дважды за вызов. Теперь — поиск модуля
без импорта. 33 — откат с видеокарты на процессор был молчаливым: теперь в журнал с причиной.
Тесты написаны до правки и падали."""
import builtins
import logging

from meetflow.connectors.asr_whisper import WhisperLocalASR


def test_health_does_not_import_faster_whisper(monkeypatch):
    tried = []
    real = builtins.__import__

    def spy(name, *a, **kw):
        if name.split(".")[0] == "faster_whisper":
            tried.append(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", spy)
    WhisperLocalASR().health()
    assert tried == [], "проверка готовности импортирует faster_whisper"


def test_cuda_to_cpu_fallback_is_logged(monkeypatch, caplog):
    import sys
    import types

    class WM:
        def __init__(self, model, device, **kw):
            if device == "cuda":
                raise RuntimeError("CUDA driver version is insufficient")
            self.device = device
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WM))
    asr = WhisperLocalASR()
    monkeypatch.setattr(asr, "available", lambda: True)
    with caplog.at_level(logging.WARNING):
        m = asr._load_point("large-v3", "auto")
    assert m.device == "cpu"
    assert any("CUDA driver version is insufficient" in r.getMessage() for r in caplog.records)
