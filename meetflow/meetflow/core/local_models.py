"""Локальные модели: распознавание речи и разбор по голосам — только с диска, без Hugging Face.

Решение владельца 05.10.26: с Hugging Face не работаем. Раньше модели тянулись из сети по имени — при
первой установке скачивались, дальше библиотека сверялась с сайтом, не вышла ли новая версия. Теперь
файлы моделей приносят на машину, а код только читает их по путям. Побочный эффект, ради которого это
и делалось: наружу не уходит ни один запрос — ни имён моделей, ни токена владельца, ни времени разбора.

Раскладка внутри папки `VOICE_MODELS_DIR` (имена подпапок фиксированы, чтобы не настраивать каждую):

    whisper-large-v3/                        — модель распознавания (формат CTranslate2)
    pyannote-speaker-diarization-3.1/        — разделение записи по голосам
    pyannote-segmentation-3.0/               — сегментация, её пайплайн требует отдельно
    pyannote-wespeaker-voxceleb-resnet34-LM/ — отпечатки голосов для общей базы

Отдельную папку можно задать своими переменными: `WHISPER_MODEL_DIR`, `PYANNOTE_DIARIZATION_DIR`,
`PYANNOTE_SEGMENTATION_DIR`, `PYANNOTE_EMBEDDING_DIR`. Значения остальных переменных проекта
(`WEBAPP_WHISPER_MODEL`) остались прежними: это имя модели, а не путь, и оно определяет, какую
подпапку взять.

Чего в файлах моделей быть не должно: ничего, кроме самих весов и конфигов. Скачанные из сети
артефакты сюда не кладём — папку переносят целиком между машинами контура.
"""
from __future__ import annotations

import os
from pathlib import Path

# Имена по умолчанию — те, на которых проект проверялся. Совпадают с именами папок в моделях.
WHISPER_SUBFOLDER = "whisper-large-v3"
DIARIZATION_SUBFOLDER = "pyannote-speaker-diarization-3.1"
SEGMENTATION_SUBFOLDER = "pyannote-segmentation-3.0"
EMBEDDING_SUBFOLDER = "pyannote-wespeaker-voxceleb-resnet34-LM"

NO_MODELS_DIR = ("не задана папка с моделями — укажите VOICE_MODELS_DIR в .env.local "
                 "(распознавание и разбор по голосам работают только на локальных файлах)")


def root() -> Path | None:
    """Папка с моделями. Пусто — не задана, и это не ошибка сама по себе: приложение работает
    по текстовому пути и сообщает, чего не хватает."""
    value = (os.environ.get("VOICE_MODELS_DIR") or "").strip()
    return Path(value) if value else None


def _folder(env_name: str, subfolder: str) -> Path | None:
    value = (os.environ.get(env_name) or "").strip()
    if value:
        return Path(value)
    base = root()
    return base / subfolder if base else None


def whisper_dir(model_name: str | None = None) -> Path | None:
    """Папка модели распознавания. `WEBAPP_WHISPER_MODEL` остался именем модели («large-v3»),
    но если в нём указан существующий путь — берём путь: так можно держать распознавание
    отдельно от остальных моделей."""
    name = (model_name or os.environ.get("WEBAPP_WHISPER_MODEL") or "large-v3").strip()
    if os.path.isdir(name):
        return Path(name)
    override = (os.environ.get("WHISPER_MODEL_DIR") or "").strip()
    if override:
        return Path(override)
    base = root()
    if base is None:
        return None
    # «large-v3» -> «whisper-large-v3»: имя папки в наборе моделей отличается от имени модели.
    if name.startswith("whisper-"):
        return base / name
    preferred = base / f"whisper-{name}"
    if preferred.is_dir():
        return preferred
    legacy = base / name
    # Папки нет ни в одном из двух вариантов — возвращаем ожидаемую: в сообщении человек должен
    # увидеть именно тот путь, который ему нужно создать, а не его собственное короткое имя.
    return legacy if legacy.is_dir() else preferred


def diarization_dir() -> Path | None:
    return _folder("PYANNOTE_DIARIZATION_DIR", DIARIZATION_SUBFOLDER)


def segmentation_dir() -> Path | None:
    return _folder("PYANNOTE_SEGMENTATION_DIR", SEGMENTATION_SUBFOLDER)


def embedding_dir() -> Path | None:
    return _folder("PYANNOTE_EMBEDDING_DIR", EMBEDDING_SUBFOLDER)


def plda_dir() -> Path | None:
    """Папка с PLDA-калибровкой — она нужна pyannote 4, иначе пайплайн лезет в сеть за ней.

    Файлы калибровки (`xvec_transform.npz`, `plda.npz`) лежат в `pyannote/speaker-diarization-community-1`
    (третий закрытый репозиторий). Кладём их отдельной папкой в `VOICE_MODELS_DIR` (имя по умолчанию
    `pyannote-plda`) либо указываем путь переменной `PYANNOTE_PLDA_DIR`."""
    value = (os.environ.get("PYANNOTE_PLDA_DIR") or "").strip()
    if value:
        return Path(value)
    base = root()
    return base / "pyannote-plda" if base else None


def plda_ready() -> bool:
    """Есть ли локальная PLDA-калибровка (без неё pyannote 4 идёт в сеть и падает в офлайне)."""
    folder = plda_dir()
    return bool(folder and folder.is_dir() and (folder / "xvec_transform.npz").is_file())


PLDA_HINT = ("нет PLDA-калибровки для pyannote 4: положите папку с файлами xvec_transform.npz и plda.npz "
             "из репозитория pyannote/speaker-diarization-community-1 в VOICE_MODELS_DIR/pyannote-plda")


def _weights_present(folder: Path) -> bool:
    """Веса на месте. Имя файла у разных моделей своё: у пайплайна и сегментации — `pytorch_model.bin`,
    у модели распознавания — `model.bin` в формате CTranslate2."""
    return folder.is_dir() and any((folder / n).is_file() for n in
                                   ("pytorch_model.bin", "model.bin", "segmentation.bin"))


def _config_present(folder: Path) -> bool:
    return (folder / "config.yaml").is_file() or (folder / "config.json").is_file()


def check_whisper(model_name: str | None = None) -> tuple[bool, str]:
    folder = whisper_dir(model_name)
    if folder is None:
        return False, NO_MODELS_DIR
    if not folder.is_dir():
        return False, f"нет папки модели распознавания: {folder}"
    if not _weights_present(folder):
        return False, f"в папке модели распознавания нет весов (model.bin): {folder}"
    return True, ""


def check_pyannote() -> tuple[bool, str]:
    """Готовы ли модели разбора по голосам. Проверяем папки и файлы, а не «скачано ли с сайта»:
    сети в этом пути больше нет вовсе."""
    if root() is None:
        return False, NO_MODELS_DIR
    missing: list[str] = []
    for label, folder in (("разделение по голосам", diarization_dir()),
                          ("сегментация", segmentation_dir()),
                          ("отпечатки голосов", embedding_dir())):
        if folder is None or not folder.is_dir():
            missing.append(f"{label}: нет папки {folder}")
        elif label == "разделение по голосам":
            # Папка пайплайна — это КОНФИГ, а не веса: у `speaker-diarization-3.1` лежат только
            # `config.yaml` и `handler.py`, сами веса — в модели сегментации и в модели отпечатков.
            # Требовать здесь `pytorch_model.bin` значит объявлять готовый разбор сломанным (находка
            # 06.10.26, когда модели наконец скачали). Веса в этой папке тоже принимаем, если есть.
            if not (_config_present(folder) or _weights_present(folder)):
                missing.append(f"{label}: в папке {folder} нет config.yaml пайплайна")
        elif not _weights_present(folder):
            missing.append(f"{label}: в папке {folder} нет файлов модели")
    return (not missing), "; ".join(missing)


# Закрытые соглашением модели: файлы не отдаются без входа в учётную запись и принятия условий на сайте.
# Решение владельца 05.10.26 — их НЕ ждём, поэтому их отсутствие это не поломка и не «осталось добыть»:
# текст записи распознаётся и без них. Нужны они только для подписей говорящих и отпечатков в общую базу.
GATED_NOTE = ("разбор по голосам не используется: модели разделения по голосам закрыты принятием условий "
              "на сайте, их не ждём — текст записи распознаётся и без них")


def pyannote_state() -> dict:
    """Что НА САМОМ ДЕЛЕ с разбором по голосам: «ready», «not-used» или «broken», и фраза для человека.

    Отличаем отсутствие ЗАКРЫТЫХ моделей от настоящей поломки, потому что это разные новости для
    оператора. Раньше оба случая давали одну строку «нет папки …», и она висела на панели мониторинга
    постоянно, читаясь как поломка (замечание владельца 05.10.26: «все время пишет не то, это не рабочее
    состояние»). Теперь:
      ready    — всё на месте, говорящие подписываются;
      not-used — не хватает только закрытых соглашением моделей: так и решено, продукт работает;
      broken   — не хватает того, что человек может исправить сам (папка отпечатков, веса, путь).
    Возвращает {"state", "message", "gated", "failed"}: message — готовая фраза, gated/failed — перечни.
    """
    if root() is None:
        return {"state": "broken", "message": NO_MODELS_DIR, "gated": [], "failed": [NO_MODELS_DIR]}
    failed: list[str] = []          # исправимо человеком
    gated: list[str] = []           # закрыто соглашением, не ждём
    for label, folder, закрыта in (("разделение по голосам", diarization_dir(), True),
                                   ("сегментация", segmentation_dir(), True),
                                   ("отпечатки голосов", embedding_dir(), False)):
        if folder is None or not folder.is_dir():
            (gated if закрыта else failed).append(f"{label}: нет папки {folder}")
        elif label == "разделение по голосам":
            if not (_config_present(folder) or _weights_present(folder)):
                failed.append(f"{label}: в папке {folder} нет config.yaml пайплайна")
        elif not _weights_present(folder):
            failed.append(f"{label}: в папке {folder} нет файлов модели")
    if not failed and not gated and not plda_ready():
        # Папки на месте, но pyannote 4 без PLDA-калибровки пайплайн не поднимает: идёт в сеть за ней и в
        # офлайне падает. Это не «готово» — говорим, чего не хватает (находка 06.10.26).
        return {"state": "broken", "gated": [], "failed": [PLDA_HINT], "message": PLDA_HINT}
    if failed:
        return {"state": "broken", "gated": gated, "failed": failed,
                "message": "разбор по голосам не работает: " + "; ".join(failed + gated)}
    if gated:
        return {"state": "not-used", "message": GATED_NOTE, "gated": gated, "failed": []}
    return {"state": "ready", "message": "", "gated": [], "failed": []}


def assert_local(folder: Path | None, label: str) -> Path:
    """Страховка перед загрузкой: путь задан и папка на месте. Имена вида `pyannote/...` больше не
    принимаются нигде — такое имя библиотека поймёт как ссылку на сайт и пойдёт в сеть, а сети в этом
    пути быть не должно. Ошибка громкая и до обращения к библиотеке."""
    if folder is None:
        raise LocalModelMissing(f"{label}: не задана папка с моделью. {NO_MODELS_DIR}")
    name = str(folder)
    if not os.path.isabs(name) and not os.path.isdir(name):
        raise LocalModelMissing(
            f"{label}: «{name}» не похоже на локальную папку. С Hugging Face проект не работает — "
            "укажите путь к папке с файлами модели.")
    if not folder.is_dir():
        raise LocalModelMissing(f"{label}: папки нет: {folder}")
    return folder


class LocalModelMissing(RuntimeError):
    """Модели нет на диске по указанному пути. Отдельный вид ошибки: человек может это исправить сам —
    положить файлы модели, — поэтому сообщение идёт оператору как есть, без «что-то пошло не так»."""
