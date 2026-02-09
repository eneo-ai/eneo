from pathlib import Path
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace

import pytest

from intric.files import file_size_service
from intric.files.file_size_service import FileSizeService


@pytest.fixture
def mock_settings(monkeypatch, tmp_path):
    settings = SimpleNamespace(upload_tmp_dir=tmp_path)
    monkeypatch.setattr(
        file_size_service, "get_settings", lambda: settings
    )
    return settings


async def test_save_file_to_disk_uses_default_tmp_dir():
    """When UPLOAD_TMP_DIR is not set, the default /tmp is used."""
    from intric.main.config import Settings

    settings = Settings(_env_file=None)
    assert settings.upload_tmp_dir == Path("/tmp")


async def test_save_file_to_disk_respects_custom_upload_tmp_dir(mock_settings, tmp_path):
    file = SpooledTemporaryFile()
    file.write(b"hello")
    file.seek(0)

    destination = await FileSizeService.save_file_to_disk(file)

    assert destination.startswith(str(tmp_path))
    assert Path(destination).exists()
    assert Path(destination).read_bytes() == b"hello"

    # cleanup
    Path(destination).unlink()


async def test_save_file_to_disk_writes_file_content(mock_settings, tmp_path):
    content = b"test content 123"
    file = SpooledTemporaryFile()
    file.write(content)
    file.seek(0)

    destination = await FileSizeService.save_file_to_disk(file)

    assert Path(destination).read_bytes() == content

    # cleanup
    Path(destination).unlink()
