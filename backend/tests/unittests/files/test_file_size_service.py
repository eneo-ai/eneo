from pathlib import Path
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eneo.files.file_size_service import FileSizeService
from eneo.main import process_scratch


@pytest.fixture
def mock_settings(monkeypatch, tmp_path):
    settings = SimpleNamespace(upload_tmp_dir=tmp_path)
    monkeypatch.setattr(process_scratch, "get_settings", lambda: settings)
    yield settings
    process_scratch.stop()


async def test_save_file_to_disk_uses_default_tmp_dir():
    """When UPLOAD_TMP_DIR is not set, the default /tmp is used."""
    from eneo.main.config import Settings

    settings = Settings(_env_file=None)
    assert settings.upload_tmp_dir == Path("/tmp")


async def test_save_file_to_disk_respects_custom_upload_tmp_dir(
    mock_settings, tmp_path
):
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


async def test_save_file_to_disk_cleans_up_on_write_failure(mock_settings, tmp_path):
    file = SpooledTemporaryFile()
    file.write(b"hello")
    file.seek(0)

    with patch(
        "eneo.files.file_size_service.shutil.copyfileobj",
        side_effect=IOError("disk full"),
    ):
        with pytest.raises(IOError, match="disk full"):
            await FileSizeService.save_file_to_disk(file)

    # Nothing left beside the directory's own lock marker
    remaining = [path.name for path in process_scratch.directory().iterdir()]
    assert remaining == ["owner.lock"]


async def test_a_saved_upload_is_in_the_scratch_of_this_process(
    mock_settings, tmp_path
):
    """A crash between saving and removing leaves the upload where the next
    start reclaims it once this process is gone."""
    file = SpooledTemporaryFile()
    file.write(b"hello")
    file.seek(0)

    destination = await FileSizeService.save_file_to_disk(file)

    assert Path(destination).parent == process_scratch.directory()
    assert process_scratch.directory().parent == tmp_path / "eneo-scratch"
