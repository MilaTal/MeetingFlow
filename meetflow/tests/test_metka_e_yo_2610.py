"""Метка папки-приёмника: оба имени Планёрки и ERP, «е» и «ё», любой регистр; служебные файлы не мешают (26.10.2026)."""
import pytest

from meetflow.connectors.base import ConnectorError
from meetflow.connectors.watch_folder import check_folder_path, is_marker


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
