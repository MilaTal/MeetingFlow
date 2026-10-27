"""Метка папки-приёмника: оба имени Планёрки и ERP, «е» и «ё», любой регистр; служебные файлы не мешают (26.10.2026)."""
import pytest

from meetflow.connectors.base import ConnectorError
from meetflow.connectors.watch_folder import MARKER, FolderIntake, check_folder_path, is_marker


@pytest.mark.parametrize("name", ["ЭТО ПАПКА-ПРИЕМНИК.txt", "ЭТО ПАПКА-ПРИЁМНИК.txt",
                                  "ЭТО ПАПКА-ПРИЕМНИК ЗАПИСЕЙ.txt", "это папка-приёмник записей.txt"])
def test_метка_принимается(tmp_path, name):
    (tmp_path / name).write_text("")
    check_folder_path(tmp_path, home=tmp_path.parent / "home")
    assert is_marker(name)


def test_служебные_файлы_не_делают_папку_непустой(tmp_path):
    (tmp_path / "desktop.ini").write_text("")
    (tmp_path / "Thumbs.db").write_text("")
    check_folder_path(tmp_path, home=tmp_path.parent / "home")


def test_чужой_файл_без_метки_отказ(tmp_path):
    (tmp_path / "отчёт.docx").write_text("x")
    with pytest.raises(ConnectorError):
        check_folder_path(tmp_path, home=tmp_path.parent / "home")


def test_общая_папка_берёт_файлы_из_подпапки_проекта(tmp_path):
    """Перевёрнуто 27.10.2026 (было — «общая папка не берёт файлы из подпапки», 6b00389): у подпапки проекта может не
    быть своей папки-приёмника (у «Адресного хранения на складе» её нет), и тогда её файл не забирал никто. Общая папка
    обходится целиком, проект файла — по имени подпапки (`проект_записи.проект_файла`); подпапку, назначенную приёмником
    другого проекта, пропускает `под_другим` — одна запись не становится двумя встречами."""
    (tmp_path / MARKER).write_text("")
    sub = tmp_path / "Адресный учет на складе"
    sub.mkdir()
    (sub / "Встреча 01.10.2026.txt").write_text("x")
    общая = FolderIntake(tmp_path, today=None)
    общая.scan()
    assert [i.path.name for i in общая.scan().ready] == ["Встреча 01.10.2026.txt"]


def test_подпапка_приёмник_другого_проекта_пропускается(tmp_path):
    from meetflow.core.proekt_zapisi import под_другим
    sub = tmp_path / "Второй проект"
    sub.mkdir()
    f = sub / "Встреча 01.10.2026.txt"
    f.write_text("x")
    assert под_другим(f, [sub]) and not под_другим(tmp_path / "Встреча 02.10.2026.txt", [sub])
