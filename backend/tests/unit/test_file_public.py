from uuid import uuid4

from eneo.files.file_models import FilePublic


def _file_public(**overrides):
    values = {
        "id": uuid4(),
        "name": "policy.pdf",
        "mimetype": "application/pdf",
        "size": 123,
    }
    values.update(overrides)
    return FilePublic(**values)


def test_storage_key_is_exposed_only_as_download_capability():
    public = _file_public(storage_key="tenant/file/original.pdf", file_type="text")

    payload = public.model_dump()

    assert payload["has_download_reference"] is True
    assert "storage_key" not in payload


def test_missing_storage_key_has_no_download_capability():
    assert _file_public().has_download_reference is False


def test_non_text_file_has_no_download_capability():
    public = _file_public(storage_key="tenant/file/image.png", file_type="image")

    assert public.has_download_reference is False
